"""Safe update of an installed xbsl by unpacking the wheel (`xbsl self-update`).

A regular `pip install --upgrade` on Windows breaks the installation when one of the
package's files is held by a running process (typical case: `xbsl-lsp.exe` is held by the
VS Code LSP server, the compiled `lexer.pyd` - by an agent's MCP session): pip removes the
old version first, fails to unpack the new one and says nothing about the empty space it
left behind - the next `xbsl --version` answers `ModuleNotFoundError`. This command is
built so that the same situation ends with a working installation instead:

1. **Holders are named before anything is touched.** The package directory is renamed
   first - a rename fails fast while a file inside is open, and nothing has been deleted
   yet at that point. The processes are then listed by pid and command line, and the
   command stops and says who to close. The command's own process tree is never offered:
   the shim that started it looks like a holder by name, and stopping it would end the
   update midway. The mypyc shared libraries living in the site-packages ROOT are renamed
   aside as well - a rename of a loaded module passes where an overwrite fails, and the
   running command itself keeps them loaded.
2. **Only servers are stopped.** `--stop-holders` ends the servers - the LSP server, the MCP
   server or the worker of its supervisor, the web server: they live as long as their client
   and keep running the old code anyway. A running xbsl command of another session (a lint,
   a scaffolding call) is somebody's work in progress, so it is named and left alone, and
   while it keeps the compiled modules loaded the update is refused with the advice to wait
   for it. `--stop-holders=all` stops the commands too, and such a command ends without a
   result.
3. **The wheel matches the platform, not the current install.** The wheel built for this
   interpreter and platform is preferred even when the installed copy is portable: deciding
   by the install would turn one portable update (a release without a native wheel, a bug
   in wheel picking) into a ratchet - every later update stays portable, silently, and the
   compiled `lexer`/`parser` never come back. Caught live on the 0.53.0 release. Without a
   native wheel for the platform the portable one is used - out loud when that demotes a
   native install.
4. **A failure rolls back.** The previous installation is kept aside until the new one has
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
import re
import shutil
import signal
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

from xbsl import __version__, i18n, mcpjournal

#: Where the files come from. Two of these LIST the releases - the simple index (PEP 691) and
#: the JSON summary - and both are cached on the CDN, each node on its own, so either may lag
#: behind a release by minutes and sometimes by half an hour. The page of one version is the
#: fresh one: right after a release nobody has asked for it yet. See `_latest`.
PYPI_SIMPLE = "https://pypi.org/simple/xbsl/"
PYPI_VERSION = "https://pypi.org/pypi/xbsl/{version}/json"
PYPI_LATEST = "https://pypi.org/pypi/xbsl/json"
#: The same URL answers an HTML page unless JSON is asked for by name.
SIMPLE_ACCEPT = "application/vnd.pypi.simple.v1+json"
#: How many releases past the listings the pages are followed (see `_newer_on_pages`): two
#: releases inside one lag window are rare, and every round costs three requests.
_PAGE_ROUNDS = 3

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
# ... and a plain interpreter counts only when it RUNS our code: a module of the package or our
# console script handed to it as a file. The command line alone is not enough on its own: an
# editor or an agent mentions "xbsl" in its arguments (a project path, a baseline file) without
# holding anything - and such a process must never be offered for stopping. Caught live: the
# client of the agent itself matched.
_PACKAGES = ("xbsl", "xbsllint")
#: `python`, `python3.12`, `pythonw`, the `py` launcher and the like.
_INTERPRETER = re.compile(r"(?:python|pythonw|pypy|pyw|py)(?:\d+(?:\.\d+)*[a-z]?)?")
#: The command line of the package: its first argument tells what it runs...
_CLI_EXECUTABLES = frozenset({"xbsl", "xbsllint"})
_CLI_MODULES = frozenset({
    "xbsl", "xbsl.cli", "xbsl.__main__", "xbsllint", "xbsllint.cli", "xbsllint.__main__",
})
#: ... and these first arguments start a server (`xbsl lsp`); anything else is a command.
_SERVER_SUBCOMMANDS = frozenset({"lsp", "mcp", "web"})
#: The modules a plain interpreter runs as a server; the worker of the supervisor is one of them.
_SERVER_MODULES = frozenset({
    "xbsl.mcp_server", "xbsl.lsp", "xbsl.web",
    "xbsllint.mcp_server", "xbsllint.lsp", "xbsllint.web",
})
# `xbsl-mcp` runs the supervisor (xbsl/mcp_supervisor.py), which holds nothing of the package:
# it is a holder only when started with `--no-supervisor`, as the bare server.
_SUPERVISOR_EXECUTABLES = frozenset({"xbsl-mcp", "xbsllint-mcp"})
_SUPERVISOR_MODULES = frozenset({"xbsl.mcp_supervisor", "xbsllint.mcp_supervisor"})
_NO_SUPERVISOR = "--no-supervisor"
#: The worker of the supervisor: the one process under it that loads the engine.
_WORKER_MODULE = "xbsl.mcp_server"
#: How much of a command line a message quotes: enough to recognize the command.
_LINE_LIMIT = 200

#: What `--stop-holders` stops: the servers alone, or every holder, the running commands of
#: other sessions included.
STOP_SERVERS, STOP_ALL = "servers", "all"
STOP_MODES = (STOP_SERVERS, STOP_ALL)
#: The two kinds of a holder. A server lives as long as its client and keeps running the old
#: code after the update, so ending it belongs to the update; a command is somebody's work.
SERVER, COMMAND = "server", "command"


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
    except (OSError, ValueError) as error:  # ValueError: a page that is not JSON
        raise SelfUpdateError(i18n.t("selfupdate.pypi-unreachable", error=error)) from error


def _simple_files() -> list[dict]:
    """Files of the project from the simple index: `{"filename", "url", "version"}` each.

    Empty list when the index cannot be read as JSON (a mirror that answers HTML, a network
    failure) - the caller then falls back to the JSON metadata, which reports the outage in
    its own words. Yanked files are dropped here: a yanked release must not win the "latest"
    race nor be installed by name.
    """
    request = urllib.request.Request(PYPI_SIMPLE, headers={"Accept": SIMPLE_ACCEPT})
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            data = json.load(resp)
    except (OSError, ValueError):
        return []
    files = []
    for item in data.get("files") or []:
        name, url = str(item.get("filename") or ""), str(item.get("url") or "")
        if not name or not url or item.get("yanked"):
            continue
        version = _version_of(name)
        if version:
            files.append({"filename": name, "url": url, "version": version})
    return files


def _version_of(filename: str) -> str:
    """Version segment of a distribution file name; "" when the name is not one of ours."""
    for suffix in (".whl", ".tar.gz", ".zip"):
        if filename.lower().endswith(suffix):
            parts = filename[: -len(suffix)].split("-")
            return parts[1] if len(parts) > 1 else ""
    return ""


def _release_key(version: str) -> tuple[tuple[int, ...], int] | None:
    """Sort key of a plain release (`0.51.0` -> `((0, 51, 0), 0)`); None for anything else.

    Deliberately narrow: only digits and an optional `.postN` are ranked, so a pre-release
    or a dev build can never be picked as the latest version by accident.
    """
    head, _, post = version.partition(".post")
    if post and not post.isdigit():
        return None
    parts = head.split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts), int(post or 0)


def _latest_release(files: list[dict]) -> str:
    """The newest plain release among the files; "" when none of them ranks."""
    ranked = []
    for version in {item["version"] for item in files if item["filename"].lower().endswith(".whl")}:
        key = _release_key(version)
        if key is not None:
            ranked.append((key, version))
    return max(ranked)[1] if ranked else ""


def _newest(*versions: str) -> str:
    """The newest plain release among the versions; "" when none of them ranks."""
    ranked = [(key, version) for version in versions if (key := _release_key(version)) is not None]
    return max(ranked)[1] if ranked else ""


def _next_versions(version: str) -> list[str]:
    """The numbers the release after `version` may carry: the next patch, minor and major.

    `0.117.0` gives `0.117.1`, `0.118.0` and `1.0.0`. A post-release steps from its base; a
    version that does not rank (a pre-release, a dev build) gives nothing.
    """
    key = _release_key(version)
    if key is None:
        return []
    parts = list(key[0])
    out = []
    for index in range(len(parts) - 1, -1, -1):
        bumped = parts[:index] + [parts[index] + 1] + [0] * (len(parts) - index - 1)
        out.append(".".join(str(part) for part in bumped))
    return out


def _page_wheels(version: str) -> list[dict]:
    """The wheels the page of one version lists; empty when PyPI does not know the version.

    Quiet on purpose: this is a look past the listings, and a 404 is its usual answer - a
    failure here must not stop an update the listings already allow. A yanked release and
    its yanked files never count, and neither does a page that names another version.
    """
    try:
        with urllib.request.urlopen(PYPI_VERSION.format(version=version), timeout=30) as resp:
            data = json.load(resp)
    except (OSError, ValueError):  # HTTPError (the 404) is an OSError too
        return []
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict) or info.get("yanked") or info.get("version") != version:
        return []
    return [
        item for item in data.get("urls") or []
        if str(item.get("filename") or "").lower().endswith(".whl") and not item.get("yanked")
    ]


def _newer_on_pages(version: str) -> tuple[str, list[dict]]:
    """A release newer than `version` that only its own page shows yet: (version, wheels).

    The listings lag behind a release; the page of the new version does not - nobody has
    asked the CDN for it before the release, so the first answer comes from PyPI itself.
    The pages of the next patch, minor and major are asked, the newest one found wins, and
    the look goes on from it in case two releases fell into one lag window. ("", []) when
    nothing newer is published.

    A 404 of such a page is cached by the CDN for about a minute (measured 25.09.2026: every
    fourth request at 15-second steps missed the cache). That is the price: a
    `--version X.Y.Z` in the minute after someone probed for X.Y.Z before it was published
    may be told the version is not there, and one more minute settles it.
    """
    found, wheels = "", []
    current = version
    for _round in range(_PAGE_ROUNDS):
        step, step_wheels = "", []
        for candidate in _next_versions(current):
            listed = _page_wheels(candidate)
            if listed and _newest(step, candidate) == candidate:
                step, step_wheels = candidate, listed
        if not step:
            break
        found, wheels, current = step, step_wheels, step
    return found, wheels


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


def _pick_wheel(entries: list[dict]) -> tuple[str, str]:
    """URL and kind of the wheel to install: native for this platform, or the portable one.

    The native wheel is preferred UNCONDITIONALLY - not only when the current install is
    native. Deciding by the install made a ratchet out of one portable update: `is_native`
    then answered False forever, and every later self-update kept the portable wheel with
    no message (the demotion warning only fires on a native install).
    """
    portable = next(
        (e["url"] for e in entries if e["filename"].endswith("-py3-none-any.whl")), ""
    )
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


def _wheel_url(version: str | None, log=None) -> tuple[str, str, str]:
    """URL, exact version and kind of the wheel from PyPI (latest or the given one).

    The file list is taken from the SIMPLE index, not from the JSON metadata. Caught live
    on 31.07.2026: right after a release `self-update --version 0.51.0` answered "PyPI has
    no suitable xbsl wheel" while the wheel was already served by the index - the JSON is a
    cache that catches up in minutes, and naming the version explicitly did not help,
    because the files were read from that same lagging document. A minute later the same
    command went through. The JSON stays as the fallback for an index that does not answer
    PEP 691 (and it is the one that reports an outage in words).

    The index lags too. On 23.09.2026 it served the previous release for more than half an
    hour after publishing, while the version page already listed every file. So a version
    named explicitly and missing from the index is looked up on its own page; only a 404
    there means the version does not exist. The latest version is not taken from one
    listing either - see `_latest`; `log` hears when the sources disagree.
    """
    files = _simple_files()
    if version is None:
        target, wheels = _latest(files, log or (lambda _message: None))
        url, kind = _pick_wheel(wheels)
        return url, target, kind
    if files:
        entries = [
            item for item in files
            if item["version"] == version and item["filename"].lower().endswith(".whl")
        ]
        if entries:
            url, kind = _pick_wheel(entries)
            return url, version, kind
    data = _fetch_json(PYPI_VERSION.format(version=version))
    resolved = data["info"]["version"]
    url, kind = _pick_wheel(data["urls"])
    return url, resolved, kind


def _latest(files: list[dict], log) -> tuple[str, list[dict]]:
    """The newest release and the files to pick its wheel from, asked of every source.

    Caught live on 24.09.2026: two minutes after 0.118.0 was published the command answered
    "already current: xbsl 0.117.0", while `--version 0.118.0` went through at once. The
    latest version came from the simple index alone, and the index still listed the previous
    release; the explicit version was found on its own page (see `_wheel_url`). Both
    listings are cached on the CDN node by node, and 31.07 showed each of them lagging while
    the other was fresh. So:

    1. both listings are read - the simple index and the JSON summary - and the newer of the
       two is taken;
    2. the pages of the next versions are asked (`_newer_on_pages`): a release the listings
       do not show yet is already there;
    3. when the sources disagree, `log` hears a line naming what each of them said, so an
       answer is never mistaken for a fact the moment after a release.

    Only when neither listing answers is the failure raised, in the words of the JSON one.
    """
    listed = _latest_release(files)
    try:
        summary = _fetch_json(PYPI_LATEST)
    except SelfUpdateError:
        if not files:
            raise
        summary = {}
    info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
    summarized = _newest(str(info.get("version") or ""))
    best = _newest(listed, summarized)
    paged, paged_wheels = _newer_on_pages(best) if best else ("", [])
    target = paged or best
    if paged or (listed and summarized and listed != summarized):
        sources = [
            i18n.t(key, version=said)
            for key, said in (("selfupdate.source.simple", listed),
                              ("selfupdate.source.summary", summarized),
                              ("selfupdate.source.page", paged))
            if said
        ]
        log(i18n.t("selfupdate.sources-differ", sources="; ".join(sources), version=target))
    if paged:
        return target, paged_wheels
    wheels = [
        item for item in files
        if item["version"] == target and item["filename"].lower().endswith(".whl")
    ]
    if not wheels and summarized == target:
        wheels = [item for item in summary.get("urls") or [] if not item.get("yanked")]
    if not target or not wheels:
        raise SelfUpdateError(i18n.t("selfupdate.no-wheel"))
    return target, wheels


# -- holders -------------------------------------------------------------------------------


def holders() -> list[dict]:
    """Live processes of ours that may hold the installation.

    Each is {"pid", "ppid", "name", "kind", "command_line"}, the kind being SERVER or COMMAND
    (`holder_kind`). Best effort by design: the answer only makes the message useful ("close
    these"), it is never a precondition. `psutil` is used when it happens to be installed,
    otherwise the system process listing is read - and if neither works, the caller still
    reports the lock itself, just without names. The command's own process tree is excluded:
    started via the installed shim, the command is a python child of an `xbsl.exe` launcher
    that looks exactly like a holder by name - and stopping it ends the update midway.
    """
    rows = _psutil_listing()
    if rows is None:
        rows = _process_listing()
    family = _family_pids(rows)
    supervising = _above_workers(rows)
    found = []
    for pid, ppid, name, line in rows:
        if pid in family:
            continue
        kind = holder_kind(name, line)
        if not kind and _started_by_stub(name, line) and pid not in supervising:
            kind = SERVER  # an `xbsl-mcp` still running the bare server of an older release
        if kind:
            found.append({"pid": pid, "ppid": ppid, "name": name, "kind": kind,
                          "command_line": " ".join(line.split())})
    return found


def _started_by_stub(name: str, command_line: str) -> bool:
    """Is this an `xbsl-mcp` started by its command stub - a supervisor, unless it runs old code?

    A process started before its stub handed over to the supervisor (xbsl/mcp_server.py) runs
    the bare server under the same name and command line. What tells the two apart is the
    worker: only a supervisor runs one under itself.
    """
    found = _runs(name, command_line)
    return (found is not None and found[0] in _SUPERVISOR_EXECUTABLES
            and _NO_SUPERVISOR not in found[1])


def _above_workers(rows: list[tuple[int, int, str, str]]) -> set[int]:
    """Pids of every process that has a worker of the MCP supervisor among its descendants."""
    parent_of = {pid: ppid for pid, ppid, _name, _line in rows}
    above: set[int] = set()
    for pid, _ppid, name, line in rows:
        found = _runs(name, line)
        if found is None or found[0] != f"-m {_WORKER_MODULE}":
            continue
        cursor = pid
        for _hop in range(64):  # bounded walk, as in _family_pids
            cursor = parent_of.get(cursor, 0)
            if cursor <= 0 or cursor in above:
                break
            above.add(cursor)
    return above


def _psutil_listing() -> list[tuple[int, int, str, str]] | None:
    """The process listing via psutil, or None when psutil is absent or broken.

    The arguments are joined back with quotes where a word has spaces: a path under
    `Program Files` joined with bare spaces would read as several words, and the script of a
    holder would not be recognized in it.
    """
    try:  # psutil comes with some extras; when absent, fall back to the OS listing
        import psutil  # noqa: PLC0415 - optional dependency, imported on demand

        return [
            (process.info["pid"], process.info.get("ppid") or 0,
             process.info.get("name") or "",
             subprocess.list2cmdline(process.info.get("cmdline") or []))
            for process in psutil.process_iter(["pid", "ppid", "name", "cmdline"])
        ]
    except Exception:  # noqa: BLE001 - any psutil trouble degrades to the OS listing
        return None


def _family_pids(rows: list[tuple[int, int, str, str]]) -> set[int]:
    """Pids of our own process tree: self, ancestors and descendants.

    Ancestors and descendants are excluded from the holders wholesale - stopping the shim
    that started this very command kills the command itself (the launcher's job object
    takes the child down with it). A reused pid can only put an extra process into the
    set, which errs on the safe side: a skipped holder, never a killed stranger.
    """
    own = os.getpid()
    parent_of = {pid: ppid for pid, ppid, _name, _line in rows}
    children_of: dict[int, list[int]] = {}
    for pid, ppid, _name, _line in rows:
        children_of.setdefault(ppid, []).append(pid)
    family = {own}
    cursor = own
    for _hop in range(64):  # bounded walk: a broken listing must not loop forever
        cursor = parent_of.get(cursor, 0)
        if cursor <= 0 or cursor in family:
            break
        family.add(cursor)
    queue = [own]
    while queue:
        for child in children_of.get(queue.pop(), ()):
            if child not in family:
                family.add(child)
                queue.append(child)
    return family


def is_holder(name: str, command_line: str) -> bool:
    """Is this process one of ours - a server or a command that may hold the installation?

    Our own executable by name, or an interpreter running our code. Anything else that
    merely mentions xbsl in its arguments is left alone: the wrong answer here is not a
    missed holder but an offer to kill someone else's process.
    """
    return bool(holder_kind(name, command_line))


def holder_kind(name: str, command_line: str) -> str:
    """SERVER or COMMAND for a process of ours, "" for anything else.

    A server is what an update has to end: the LSP, MCP and web servers live as long as their
    client and keep running the old code. Anything else of ours is a command - a lint, a
    scaffolding call, another self-update - and a command of another session is never ended
    by default: the wrong answer here kills that work with no verdict. So a server is
    recognized positively, by its program, module or first argument, and whatever is not
    certain stays a command.

    `xbsl-mcp` is the supervisor of the server: it loads no engine and is not stopped - the
    session it keeps is the point of it. Its worker (`-m xbsl.mcp_server`) and a bare server
    (`--no-supervisor`) hold the package and are. An `xbsl-mcp` still running the bare server
    from before its stub handed over is told by `holders`, by the missing worker.
    """
    found = _runs(name, command_line)
    if found is None:
        return ""
    what, args = found
    if what.startswith("-m "):
        module = what[3:]
        if module in _SERVER_MODULES:
            return SERVER
        if module in _SUPERVISOR_MODULES:
            return SERVER if _NO_SUPERVISOR in args else ""
        if module not in _CLI_MODULES:
            return COMMAND
    elif what in _SUPERVISOR_EXECUTABLES:
        return SERVER if _NO_SUPERVISOR in args else ""
    elif what not in _CLI_EXECUTABLES:
        return SERVER  # xbsl-lsp, xbsl-web and their twins under the old name
    return SERVER if args[:1] and args[0] in _SERVER_SUBCOMMANDS else COMMAND


def _runs(name: str, command_line: str) -> tuple[str, list[str]] | None:
    """What of ours a process runs and the arguments after it; None when nothing of ours.

    The first is our console script (`xbsl-lsp`) or, for an interpreter, `-m` with the module
    (`-m xbsl.mcp_server`). An interpreter handed our console script as a file (the launcher of
    a venv starts `python.exe ...\\Scripts\\xbsl-lsp.exe`) runs the script. `-c` code, a script
    of somebody else's and a module of another package are not ours, whatever their arguments
    mention.
    """
    words = _words(command_line)
    own = _base(name)
    if own in _HOLDER_EXECUTABLES:
        start = next((index + 1 for index, word in enumerate(words) if _base(word) == own), 1)
        return own, words[start:]
    if not _INTERPRETER.fullmatch(own):
        return None
    # The arguments start after the interpreter's own word. A listing that lost the quotes
    # (ps) splits a path with spaces, and the interpreter ends it.
    index = next((position + 1 for position, word in enumerate(words)
                  if _INTERPRETER.fullmatch(_base(word))), 1)
    while index < len(words):
        word = words[index]
        if word == "-" or not word.startswith("-"):
            break
        if word.startswith("--"):
            index += 2 if word == "--check-hash-based-pycs" else 1
            continue
        letters = word[1:]  # a cluster of one-letter options: `-P`, `-uB`, `-Xutf8`, `-m module`
        for position, letter in enumerate(letters):
            rest = letters[position + 1:]
            if letter == "c":
                return None
            if letter == "m":
                module = (rest or (words[index + 1] if index + 1 < len(words) else "")).lower()
                if not any(module == package or module.startswith(package + ".")
                           for package in _PACKAGES):
                    return None
                return f"-m {module}", words[index + (1 if rest else 2):]
            if letter in "XW":
                index += 0 if rest else 1  # the value is the rest of the word or the next one
                break
        index += 1
    if index >= len(words) or words[index] == "-":
        return None
    script = _base(words[index])
    return (script, words[index + 1:]) if script in _HOLDER_EXECUTABLES else None


def _words(command_line: str) -> list[str]:
    """The words of a command line, the double quotes around a path taken off.

    Not a shell parser: a process listing is read here, not a command run, and the words only
    have to show the program, its module and its first argument.
    """
    words: list[str] = []
    word: list[str] = []
    quoted = started = False
    for char in command_line or "":
        if char == '"':
            quoted, started = not quoted, True
        elif char.isspace() and not quoted:
            if started:
                words.append("".join(word))
            word, started = [], False
        else:
            word.append(char)
            started = True
    if started:
        words.append("".join(word))
    return words


def _base(path: str) -> str:
    """The file name a word or a process name points at, lowercased and without `.exe`.

    Both separators count whatever the system: a listing from Windows is read by the tests
    on any of them.
    """
    name = re.split(r"[\\/]", (path or "").strip())[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _process_listing() -> list[tuple[int, int, str, str]]:
    """(pid, ppid, name, command line) from the system tools; empty list when they are unavailable."""
    if sys.platform == "win32":
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_Process | "
            "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress",
        ]
    else:
        command = ["ps", "-eo", "pid=,ppid=,comm=,args="]
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, timeout=30, encoding="utf-8",
            errors="replace", stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    if sys.platform != "win32":
        rows = []
        for line in out.splitlines():
            parts = line.strip().split(None, 3)
            if len(parts) == 4 and parts[0].isdigit() and parts[1].isdigit():
                rows.append((int(parts[0]), int(parts[1]), parts[2], parts[3]))
        return rows
    try:
        data = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = [data]
    return [
        (int(item.get("ProcessId") or 0), int(item.get("ParentProcessId") or 0),
         str(item.get("Name") or ""), str(item.get("CommandLine") or ""))
        for item in data
    ]


def _launches(processes: list[dict]) -> list[dict]:
    """One process per launch: those whose parent is not on the list.

    A console script on Windows runs as a chain - the launcher and the interpreter it starts -
    both with nearly the same command line. The head of the chain names the launch; the rest
    are its parts.
    """
    pids = {item["pid"] for item in processes}
    return [item for item in processes if item.get("ppid") not in pids]


def _described(process: dict) -> str:
    """The pid and the command line of a process, the way a message names it."""
    line = process.get("command_line") or process.get("name") or i18n.t("selfupdate.process")
    if len(line) > _LINE_LIMIT:
        line = line[: _LINE_LIMIT - 3].rstrip() + "..."
    return f"pid {process['pid']} – {line}"


def _listed(processes: list[dict]) -> str:
    return "; ".join(_described(item) for item in processes)


def _end(pid: int) -> str:
    """Stop one process: "" when it ended or was gone already, the reason when it was not."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True,
                                    timeout=30, stdin=subprocess.DEVNULL)
            # 128 is "not found": the launcher stopped a moment ago took its interpreter along.
            if result.returncode not in (0, 128):
                return f"taskkill {result.returncode}"
        else:
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return ""
    except (OSError, subprocess.SubprocessError) as error:
        return str(error)
    return ""


def stop_holders(processes: list[dict], log, reason: str = "self-update --stop-holders") -> list[dict]:
    """End the listed processes; returns those that survived.

    A forced stop leaves the stopped server no chance to write its own end, so the MCP
    journal gets the record from here: a client of that server sees only a closed transport,
    and `xbsl mcp-log` then names the update that ended it. A launch gets one line in the log,
    the one of its head (see `_launches`): the parts of the chain go with it.
    """
    heads = {item["pid"] for item in _launches(processes)}
    alive = []
    for process in processes:
        pid = int(process["pid"])
        error = _end(pid)
        if error:
            alive.append({**process, "error": error})
            log(i18n.t("selfupdate.stop-failed", process=_described(process), error=error))
            continue
        mcpjournal.record("stopped", target=pid, name=process.get("name") or "", reason=reason)
        if process["pid"] in heads:
            stopped = ("selfupdate.command-stopped" if process.get("kind") == COMMAND
                       else "selfupdate.server-stopped")
            log(i18n.t(stopped, process=_described(process)))
    return alive


def _stop_for_update(stop: str, log, reason: str) -> None:
    """End what `stop` covers, and name the running commands it leaves alone."""
    busy = holders()
    ending = [item for item in busy if stop == STOP_ALL or item.get("kind") == SERVER]
    if ending:
        stop_holders(ending, log, reason=reason)
    for item in _launches([item for item in busy if item not in ending]):
        log(i18n.t("selfupdate.command-spared", process=_described(item)))


def _holders_message(processes: list[dict], stop: str = "") -> str:
    """Who holds the installation and what to do about it, the servers apart from the commands.

    A server can be closed or stopped with `--stop-holders`. A command is somebody's work, so
    the advice is to wait for it, and the way to stop it anyway is named with its price. What
    the mode of this run was meant to stop and is still listed did not go: closing it by hand is
    the advice left. With nothing listed, the message says so honestly.
    """
    servers = _launches([item for item in processes if item.get("kind") != COMMAND])
    commands = _launches([item for item in processes if item.get("kind") == COMMAND])
    if not servers and not commands:
        return f"{i18n.t('selfupdate.holders-unknown')}. {i18n.t('selfupdate.advice-servers')}"
    parts = []
    if servers:
        parts.append(i18n.t("selfupdate.holders", list=_listed(servers)))
        parts.append(i18n.t("selfupdate.advice-close" if stop else "selfupdate.advice-servers"))
    if commands:
        parts.append(i18n.t("selfupdate.holders-commands", list=_listed(commands)))
        parts.append(i18n.t(
            "selfupdate.advice-close" if stop == STOP_ALL else "selfupdate.advice-commands"
        ))
    return ". ".join(parts)


# -- the update itself ---------------------------------------------------------------------


def _native_root_modules(site: Path) -> list[Path]:
    """Root-level native modules of THIS distribution (the mypyc shared libraries).

    mypyc puts its shared library NEXT to the package, in the site-packages root, under a
    name that is stable across versions - so extraction OVERWRITES it in place, and that
    fails with Errno 13 while the running self-update itself keeps the module loaded (a
    rename of a loaded module passes, an overwrite does not). The list is read from the
    installed RECORD rather than globbed: another distribution built with mypyc keeps its
    own `*__mypyc*` library in the same root, and that one must not be touched.
    """
    files: list[Path] = []
    for dist_info in site.glob("xbsl-*.dist-info"):
        if dist_info.name.endswith(_BACKUP_SUFFIX):
            continue
        try:
            text = (dist_info / "RECORD").read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            name = line.split(",")[0].strip()
            if not name or "/" in name or "\\" in name:
                continue
            if name.lower().endswith(_NATIVE_SUFFIXES) and (site / name).is_file():
                files.append(site / name)
    return files


def _remove_any(path: Path) -> None:
    """Remove a directory or a file, quietly: leftovers are cleaned up, never fought over."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            path.unlink()
        except OSError:
            pass


def _free_backup_name(path: Path) -> Path:
    """A backup name for `path` that is free right now.

    The plain name is cleared first. It stays taken when the previous run left a backup that
    a live process still has loaded: Windows lets such a file be renamed but not deleted.
    Then the backup gets a numbered name. Every name ends with the backup suffix, so the
    next run sweeps them all.
    """
    backup = path.with_name(path.name + _BACKUP_SUFFIX)
    number = 0
    while True:
        _remove_any(backup)
        if not os.path.lexists(backup):
            return backup
        number += 1
        backup = path.with_name(f"{path.name}.{number}{_BACKUP_SUFFIX}")


def _move_aside(site: Path) -> list[tuple[Path, Path]]:
    """Move the current installation aside. Raises when a file inside is open.

    A rename is the gate of the whole procedure: while a compiled module is loaded by a
    live process, Windows refuses it - and at that moment nothing has been removed yet.
    The root-level mypyc libraries go aside too - for those the rename passes even under
    our own process, which is the point: extraction then writes a fresh file instead of
    failing to overwrite a loaded one.
    """
    for stale in site.glob("*" + _BACKUP_SUFFIX):
        _remove_any(stale)  # a file backup our own process held last time (see _drop_backups)
    moved: list[tuple[Path, Path]] = []
    targets = _native_root_modules(site)
    try:
        for pattern in _OWNED_PATTERNS:
            targets.extend(
                path for path in sorted(site.glob(pattern))
                if not path.name.endswith(_BACKUP_SUFFIX)
            )
        for path in targets:
            backup = _free_backup_name(path)
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
    """Drop the kept-aside installation once the new one is proven.

    A FILE backup may refuse to go: the renamed mypyc library is still loaded by this very
    process, and a loaded module cannot be deleted - only renamed. Such a leftover is
    removed by the next run's sweep in `_move_aside`.
    """
    for _path, backup in moved:
        _remove_any(backup)


def verify_install(site: Path, expected: str) -> str:
    """Version reported by a FRESH interpreter, or "" when the package does not import.

    The check runs in a separate process on purpose: the current one holds the old code in
    memory and would report success no matter what happened on disk.
    """
    code = "import xbsl, sys; sys.stdout.write(xbsl.__version__)"
    # PYTHONIOENCODING because the answer is READ as text: without it the child writes in the
    # console code page, and a decoding that says utf-8 gets replacement characters back
    # while the exit code goes on saying that all is well.
    env = {**os.environ, "PYTHONPATH": str(site), "PYTHONIOENCODING": "utf-8"}
    try:
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120,
            cwd=str(site), env=env, encoding="utf-8", errors="replace",
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def self_update(version: str | None = None, log=print, *, stop: str = "") -> tuple[str, str]:
    """Update xbsl in site-packages by unpacking the wheel. Return (old, new).

    `stop` is what `--stop-holders` asked for: STOP_SERVERS ends the servers holding the
    installation and names the running commands without touching them, STOP_ALL ends the
    commands as well, and "" ends nothing.
    """
    site = _site_packages()
    _ensure_regular_install(site)
    was_native = is_native(site)

    url, target, kind = _wheel_url(version, log=log)
    if version is None and target == __version__:
        log(i18n.t("selfupdate.up-to-date", version=__version__))
        return __version__, __version__
    if version is None and _newest(target, __version__) == __version__:
        # Every source lags behind a release installed by its number a minute ago: without
        # this the plain command would have "updated" back to the previous release.
        log(i18n.t("selfupdate.newer-installed", installed=__version__, latest=target))
        return __version__, __version__
    if was_native and kind == PORTABLE:
        log(i18n.t("selfupdate.native-missing"))
    elif not was_native and kind == NATIVE:
        log(i18n.t("selfupdate.native-restored"))

    log(i18n.t("selfupdate.downloading", version=target, kind=i18n.t(f"selfupdate.kind.{kind}")))
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            blob = resp.read()
    except OSError as error:
        raise SelfUpdateError(i18n.t("selfupdate.download-failed", error=error)) from error

    if stop:
        _stop_for_update(stop, log, reason=f"self-update {__version__} -> {target}")

    try:
        moved = _move_aside(site)
    except OSError as error:
        raise SelfUpdateError(
            i18n.t("selfupdate.busy", error=error, holders=_holders_message(holders(), stop))
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
            meta.write_text(json.dumps(data, indent=4), encoding="utf-8", newline="")
            log(i18n.t("selfupdate.pipx-updated"))
    except (OSError, ValueError):
        pass
