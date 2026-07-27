"""Safe update of an installed xbsl by unpacking the wheel (`xbsl self-update`).

A regular `pip install --upgrade` on Windows breaks the installation when one of the
package's files is held by a running process (typical case: `xbsl-lsp.exe` is held by the
VS Code LSP server, the compiled `lexer.pyd` - by an agent's MCP session): pip removes the
old version first, fails to unpack the new one and says nothing about the empty space it
left behind - the next `xbsl --version` answers `ModuleNotFoundError`. This command is
built so that the same situation ends with a working installation instead:

1. **Holders are named before anything is touched.** The package directory is renamed
   first - a rename fails fast while a file inside is open, and nothing has been deleted
   yet at that point. The processes are then listed by name and pid; `--stop-holders`
   ends them, otherwise the command stops and says who to close.
2. **The wheel matches what is installed.** A native install (compiled `lexer`/`parser`)
   is updated from the wheel built for this interpreter and platform - taking the portable
   one would silently swap the compiled modules for pure Python and cost several times the
   speed. Without a native wheel for the platform the portable one is used, out loud.
3. **A failure rolls back.** The previous installation is kept aside until the new one has
   been PROVEN to import in a separate process (the current one still runs the old code in
   memory and cannot judge). Anything unexpected - the old installation is put back.

The wheel ships both the xbsl package and the xbsllint alias package - both are replaced.
The dist-info of the transitional `xbsllint` METApackage (a separate, code-free
distribution) is not touched. Only xbsl itself is updated, not its extras ([mcp]/[lsp]).

Download and unpack with the standard library (urllib + zipfile) - the command must work
even in an installation without extras.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from xbsl import __version__, i18n

PYPI_VERSION = "https://pypi.org/pypi/xbsl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/xbsl/json"

# What belongs to the xbsl wheel in site-packages. The xbsl-*.dist-info pattern will not
# touch the metapackage's xbsllint-*.dist-info: glob matches the prefix literally.
_OWNED_PATTERNS = ("xbsl", "xbsllint", "xbsl-*.dist-info")
# Suffix of the directory kept aside while the new version is being proven.
_BACKUP_SUFFIX = ".xbsl-selfupdate-backup"
# Kind of the wheel: a catalog key suffix, not a word - the message is translated, the
# decision "native or portable" is not.
NATIVE, PORTABLE = "native", "portable"
# Compiled modules: their presence means the install is native, and they are also what a
# running process keeps open.
_NATIVE_SUFFIXES = (".pyd", ".so")
# Our own executables - a holder is recognized by the PROCESS NAME first.
_HOLDER_EXECUTABLES = frozenset({
    "xbsl", "xbsl-lsp", "xbsl-mcp", "xbsl-web",
    "xbsllint", "xbsllint-lsp", "xbsllint-mcp", "xbsllint-web",
})
# ... and a plain interpreter counts only when it RUNS one of our modules. The command line
# alone is not enough on its own: an editor or an agent mentions "xbsl" in its arguments
# (a project path, a baseline file) without holding anything - and such a process must
# never be offered for stopping. Caught live: the client of the agent itself matched.
_HOLDER_MODULES = ("xbsl.mcp_server", "xbsl.lsp", "xbsl.web", "xbsllint.mcp_server")
_INTERPRETERS = ("python", "python3", "pythonw", "py", "pypy", "pypy3")


class SelfUpdateError(RuntimeError):
    """Self-update error; the text is shown to the user as is."""


def _site_packages() -> Path:
    """Directory the package is installed into (site-packages in a production install)."""
    return Path(__file__).resolve().parent.parent


def _ensure_regular_install(site: Path) -> None:
    """Guard against an editable install: git updates it, and unpacking a wheel would corrupt the repository."""
    if site.name.lower() not in ("site-packages", "dist-packages"):
        raise SelfUpdateError(i18n.t("selfupdate.editable", site=site))


def _fetch_json(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise SelfUpdateError(i18n.t("selfupdate.no-version")) from error
        raise SelfUpdateError(i18n.t("selfupdate.pypi-status", status=error.code)) from error
    except OSError as error:
        raise SelfUpdateError(i18n.t("selfupdate.pypi-unreachable", error=error)) from error


# -- what is installed and which wheel fits it ---------------------------------------------


def is_native(site: Path) -> bool:
    """Does the installation carry compiled modules (lexer/parser built by mypyc)?"""
    package = site / "xbsl"
    return any(
        child.suffix.lower() in _NATIVE_SUFFIXES for child in package.glob("*") if child.is_file()
    )


#: Interpreter prefixes of wheel tags, by implementation name.
_INTERPRETER_PREFIX = {"cpython": "cp", "pypy": "pp", "ironpython": "ip", "jython": "jy"}


def platform_tags() -> tuple[str, tuple[str, ...]]:
    """The interpreter tag (`cp314`) and the platform keywords a wheel name must carry.

    Assembled from the standard library instead of asking `packaging`: the command must
    work in an installation without extras. NOT from `sys.implementation.cache_tag` - that
    one spells the same interpreter as `cpython-314` (it names `__pycache__` files), and no
    wheel is ever called that; the mismatch quietly sent a native install to the portable
    wheel. The platform keywords are deliberately loose - a manylinux wheel names the
    platform as `manylinux_2_17_x86_64`, so the architecture is what distinguishes it.
    """
    prefix = _INTERPRETER_PREFIX.get(sys.implementation.name, sys.implementation.name[:2])
    interpreter = f"{prefix}{sys.version_info.major}{sys.version_info.minor}"
    platform = sysconfig.get_platform().lower().replace("-", "_").replace(".", "_")
    if platform.startswith("win"):
        return interpreter, (platform,)
    if platform.startswith("macosx"):
        return interpreter, ("macosx", platform.rsplit("_", 1)[-1])
    return interpreter, ("linux", platform.rsplit("_", 1)[-1])


def _pick_wheel(entries: list[dict], *, native: bool) -> tuple[str, str]:
    """URL and kind of the wheel to install: native for this platform, or the portable one."""
    portable = next(
        (e["url"] for e in entries if e["filename"].endswith("-py3-none-any.whl")), ""
    )
    if native:
        interpreter, keywords = platform_tags()
        for entry in entries:
            name = entry["filename"].lower()
            if not name.endswith(".whl") or f"-{interpreter}-" not in name:
                continue
            if all(word in name for word in keywords):
                return entry["url"], NATIVE
    if not portable:
        raise SelfUpdateError(i18n.t("selfupdate.no-wheel"))
    return portable, PORTABLE


def _wheel_url(version: str | None, *, native: bool = False) -> tuple[str, str, str]:
    """URL, exact version and kind of the wheel from PyPI (latest or the given one)."""
    data = _fetch_json(PYPI_VERSION.format(version=version) if version else PYPI_LATEST)
    resolved = data["info"]["version"]
    url, kind = _pick_wheel(data["urls"], native=native)
    return url, resolved, kind


# -- holders -------------------------------------------------------------------------------


def holders() -> list[dict]:
    """Live processes that look like holders of the installation: {"pid", "name"}.

    Best effort by design: the answer only makes the message useful ("close these"), it is
    never a precondition. `psutil` is used when it happens to be installed, otherwise the
    system process listing is read - and if neither works, the caller still reports the
    lock itself, just without names.
    """
    found: list[dict] = []
    own = os.getpid()
    try:  # psutil comes with some extras; when absent, fall back to the OS listing
        import psutil  # noqa: PLC0415 - optional dependency, imported on demand

        for process in psutil.process_iter(["pid", "name", "cmdline"]):
            line = " ".join(process.info.get("cmdline") or [])
            name = process.info.get("name") or ""
            if process.info["pid"] != own and is_holder(name, line):
                found.append({"pid": process.info["pid"], "name": name})
        return found
    except Exception:  # noqa: BLE001 - any psutil trouble degrades to the OS listing
        pass
    for pid, name, line in _process_listing():
        if pid != own and is_holder(name, line):
            found.append({"pid": pid, "name": name})
    return found


def is_holder(name: str, command_line: str) -> bool:
    """Is this process one of ours - and therefore worth offering for a stop?

    Our own executable by name, or an interpreter running one of our modules. Anything
    else that merely mentions xbsl in its arguments is left alone: the wrong answer here
    is not a missed holder but an offer to kill someone else's process.
    """
    stem = Path((name or "").strip()).stem.lower()
    if stem in _HOLDER_EXECUTABLES:
        return True
    if stem not in _INTERPRETERS:
        return False
    lowered = (command_line or "").lower()
    if any(f"-m {module}" in lowered for module in _HOLDER_MODULES):
        return True
    # A console script started by its path (`.../Scripts/xbsl-lsp.exe`, `.../bin/xbsl-mcp`).
    return any(f"{script}.exe" in lowered or lowered.endswith(script) for script in _HOLDER_EXECUTABLES)


def _process_listing() -> list[tuple[int, str, str]]:
    """(pid, name, command line) from the system tools; empty list when they are unavailable."""
    if sys.platform == "win32":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ]
    else:
        command = ["ps", "-eo", "pid=,comm=,args="]
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if sys.platform != "win32":
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and parts[0].isdigit():
                rows.append((int(parts[0]), parts[1], parts[2]))
        return rows
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (int(item.get("ProcessId") or 0), str(item.get("Name") or ""), str(item.get("CommandLine") or ""))
        for item in data
    ]


def stop_holders(processes: list[dict], log) -> list[dict]:
    """End the listed processes; returns those that survived."""
    alive = []
    for process in processes:
        pid = int(process["pid"])
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)
            else:
                os.kill(pid, 15)
            log(i18n.t("selfupdate.holder-stopped", name=process.get("name") or "", pid=pid))
        except (OSError, subprocess.SubprocessError) as error:
            alive.append({**process, "error": str(error)})
    return alive


def _holders_message(processes: list[dict]) -> str:
    """Who to close - by name and pid, or an honest "could not tell"."""
    if not processes:
        return i18n.t("selfupdate.holders-unknown")
    listed = ", ".join(
        f"{item.get('name') or i18n.t('selfupdate.process')} (pid {item['pid']})"
        for item in processes
    )
    return i18n.t("selfupdate.holders", list=listed)


# -- the update itself ---------------------------------------------------------------------


def _move_aside(site: Path) -> list[tuple[Path, Path]]:
    """Move the current installation aside. Raises when a file inside is open.

    A rename is the gate of the whole procedure: while a compiled module is loaded by a
    live process, Windows refuses it - and at that moment nothing has been removed yet.
    """
    moved: list[tuple[Path, Path]] = []
    try:
        for pattern in _OWNED_PATTERNS:
            for path in sorted(site.glob(pattern)):
                if path.name.endswith(_BACKUP_SUFFIX):
                    continue
                backup = path.with_name(path.name + _BACKUP_SUFFIX)
                shutil.rmtree(backup, ignore_errors=True)
                path.rename(backup)
                moved.append((path, backup))
    except OSError:
        _restore(moved)
        raise
    return moved


def _restore(moved: list[tuple[Path, Path]]) -> None:
    """Put the previous installation back (the new files, if any, are removed first)."""
    for path, backup in moved:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True) if path.is_dir() else path.unlink(missing_ok=True)
        try:
            backup.rename(path)
        except OSError:
            pass


def _drop_backups(moved: list[tuple[Path, Path]]) -> None:
    for _path, backup in moved:
        shutil.rmtree(backup, ignore_errors=True)


def verify_install(site: Path, expected: str) -> str:
    """Version reported by a FRESH interpreter, or "" when the package does not import.

    The check runs in a separate process on purpose: the current one holds the old code in
    memory and would report success no matter what happened on disk.
    """
    code = "import xbsl, sys; sys.stdout.write(xbsl.__version__)"
    env = {**os.environ, "PYTHONPATH": str(site)}
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
            cwd=str(site), env=env, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def self_update(version: str | None = None, log=print, *, stop_busy: bool = False) -> tuple[str, str]:
    """Update xbsl in site-packages by unpacking the wheel. Return (old, new)."""
    site = _site_packages()
    _ensure_regular_install(site)
    native = is_native(site)

    url, target, kind = _wheel_url(version, native=native)
    if version is None and target == __version__:
        log(i18n.t("selfupdate.up-to-date", version=__version__))
        return __version__, __version__
    if native and kind == PORTABLE:
        log(i18n.t("selfupdate.native-missing"))

    log(i18n.t("selfupdate.downloading", version=target, kind=i18n.t(f"selfupdate.kind.{kind}")))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise SelfUpdateError(i18n.t("selfupdate.download-failed", error=error)) from error

    if stop_busy:
        busy = holders()
        if busy:
            stop_holders(busy, log)

    try:
        moved = _move_aside(site)
    except OSError as error:
        raise SelfUpdateError(
            i18n.t("selfupdate.busy", error=error, holders=_holders_message(holders()))
        ) from error

    log(i18n.t("selfupdate.extracting", site=site))
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            archive.extractall(site)
    except (OSError, zipfile.BadZipFile) as error:
        _restore(moved)
        raise SelfUpdateError(i18n.t("selfupdate.extract-failed", error=error)) from error

    installed = verify_install(site, target)
    if installed != target:
        _restore(moved)
        reason = (
            i18n.t("selfupdate.reason.version", version=installed)
            if installed
            else i18n.t("selfupdate.reason.no-import")
        )
        raise SelfUpdateError(
            i18n.t("selfupdate.unverified", reason=reason, version=__version__)
        )
    _drop_backups(moved)

    _update_pipx_metadata(site, target, log)
    log(i18n.t("selfupdate.done", old=__version__, new=target,
               kind=i18n.t(f"selfupdate.kind.{kind}")))
    return __version__, target


def _update_pipx_metadata(site: Path, version: str, log) -> None:
    """Fix package_version in pipx_metadata.json (otherwise pipx list shows the old version)."""
    meta = site.parent.parent / "pipx_metadata.json"  # <venv>/Lib/site-packages -> <venv>
    if not meta.is_file():
        return
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        main = data.get("main_package") or {}
        if main.get("package") == "xbsl":
            main["package_version"] = version
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8")
            log(i18n.t("selfupdate.pipx-updated"))
    except (OSError, ValueError):
        pass
