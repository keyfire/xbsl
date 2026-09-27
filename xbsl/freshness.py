"""Is the code on disk still the code this process runs?

A long-lived process - the MCP server above all - imports its modules lazily. When the
installation is replaced under it (`self-update`, a `git pull` in an editable checkout), the
modules it already holds stay old, and every module it imports afterwards comes from the new
code. The two halves then disagree about their own interfaces. Caught live on 24.09.2026: a
server started on 0.117.0 and left running while its editable checkout moved to 0.118.0 answered
`lint_paths` with four rule crashes, `TypeError: ProjectCatalog.register_row() takes 3
positional arguments but 4 were given` - the catalog in memory was the old class, the rules
calling it were new. The CLI over the same files was clean, and nothing in the answer said that
a restart was the cure.

The plugins go stale the same way. Caught on 25.09.2026: after a plugin was upgraded under a
running server, `lint_paths` named the version it had loaded while the CLI and CI ran the new
one - two rule sets over one tree, and no word about it in the answer.

Three checks, by cost:

- the VERSION: `__version__` in memory against the `__init__.py` on disk. One small file, cheap
  enough for every call of a tool (`version_state`);
- the PLUGINS: the plugin distributions the process loaded, as the walk that loaded them read
  their metadata, against the ones installed now (`plugins_state`). A walk over the installed
  distributions costs tens of milliseconds, hundreds in a big environment, so it runs only when
  a folder the distributions live in changed its modification time since the last walk - the
  signal importlib.metadata itself reads to know that its view of a folder is stale. An install
  or a removal renames folders there. Otherwise a check is a stat of a folder or two;
- the SOURCES: a fingerprint of the code files of the engine and of the plugin packages - path,
  size, modification time - taken when the process starts (`remember`) against one taken now
  (`sources_state`). A walk over some two hundred files, a couple of milliseconds: it covers
  the pull between two releases, where the number stays while the code changes. The MCP server
  checks it only after something failed; the language server every few seconds at most.

The plugins and the sources are judged only in a process that called `remember` at its start:
the CLI lives for one run and has nothing to compare.

Nothing here restarts or stops the process: a client such as Codex does not start a failed
server again, so the server keeps answering and says what to do.
"""

from __future__ import annotations

import hashlib
import os
import re
import sysconfig
import time
from pathlib import Path

import xbsl
from xbsl import __version__, i18n, plugins

MESSAGES = {
    "freshness.version": {
        "ru": "код движка на диске обновлен: {loaded} -> {on_disk}, а этот процесс работает на "
              "{loaded} из памяти",
        "en": "the engine code on disk was updated: {loaded} -> {on_disk}, while this process "
              "runs {loaded} from memory",
    },
    "freshness.sources": {
        "ru": "исходники движка или его надстроек на диске изменились после запуска этого "
              "процесса (номер версии тот же, {loaded})",
        "en": "the sources of the engine or of its plugins changed on disk after this process "
              "started (the version number is the same, {loaded})",
    },
    "freshness.plugins": {
        "ru": "надстройки на диске сменились после запуска этого процесса: {changes}",
        "en": "the plugins on disk changed after this process started: {changes}",
    },
    "freshness.plugin-absent": {"ru": "нет", "en": "none"},
    "freshness.refusal": {
        "ru": "{state}. Модули, которые сервер подгрузит дальше, будут из нового кода и не "
              "сойдутся с уже загруженными, поэтому инструменты не выполняются. Перезапустите "
              "сервер MCP xbsl; сам сервер не перезапускается и не завершается",
        "en": "{state}. The modules the server loads from now on come from the new code and do "
              "not match the ones already loaded, so the tools do not run. Restart the xbsl MCP "
              "server; the server neither restarts nor exits on its own",
    },
    "freshness.plugins-warning": {
        "ru": "{state}. Инструменты работают, но с правилами надстроек, загруженных при старте, "
              "и ответ может разойтись с CLI и CI. Перезапустите сервер MCP xbsl",
        "en": "{state}. The tools run, but with the rules of the plugins loaded at start, and an "
              "answer may differ from the CLI and CI. Restart the xbsl MCP server",
    },
    "freshness.failure": {
        "ru": "{state}: инструмент упал ({error}), скорее всего, на смеси старого и нового кода. "
              "Перезапустите сервер MCP xbsl",
        "en": "{state}: the tool failed ({error}), most likely on a mix of the old and the new "
              "code. Restart the xbsl MCP server",
    },
    "freshness.crash": {
        "ru": "{state}: правило, скорее всего, упало на смеси старого и нового кода. "
              "Перезапустите процесс – сервер MCP или LSP-сервер редактора",
        "en": "{state}: the rule most likely crashed on a mix of the old and the new code. "
              "Restart the process - the MCP server or the editor's LSP server",
    },
    "freshness.editor": {
        "ru": "xbsl-lsp: {state}. Проверки идут на коде, загруженном при старте, и могут "
              "разойтись с CLI и CI. Перезапустите сервер языка: в VS Code – команда \"XBSL: "
              "Перезапустить линтер\" или перезагрузка окна",
        "en": "xbsl-lsp: {state}. The checks run on the code loaded at start and may differ "
              "from the CLI and CI. Restart the language server: in VS Code, the \"XBSL: "
              "Restart the linter\" command or a reload of the window",
    },
}
i18n.register(MESSAGES)

#: The package this process imported: the code a stale state is judged against.
PACKAGE = Path(xbsl.__file__).resolve().parent
_VERSION_RE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']""", re.M)
#: Folders of the package that hold no code: the generated language data runs to megabytes.
_SKIP_DIRS = frozenset({"data", "__pycache__"})
_CODE_SUFFIXES = (".py", ".pyd", ".so")
#: How long a verdict on the sources is reused: a rule that crashes on every file of a run
#: walks the package once, not once per file.
_SOURCES_TTL = 5.0

#: The fingerprint taken by `remember`; None in a process that never took one (the CLI).
_started: str | None = None
_checked: tuple[float, bool] | None = None
#: The stale state a crash noted since the last `take_noted`.
_noted: dict | None = None
#: The folders the plugin check watches and their modification times at the last walk (see
#: `plugins_state`); None in a process that never called `remember`.
_marks: dict[str, int] | None = None
#: The verdict of that walk: the plugins state, None while the disk holds the loaded plugins.
_plugins_found: dict | None = None


def disk_version(package: Path | None = None) -> str:
    """The version the `__init__.py` on disk declares; "" when it cannot be read.

    An unreadable file is no verdict: `self-update` renames the package aside for a moment, and
    a call that comes in that moment must not be refused over it.
    """
    try:
        text = ((package or PACKAGE) / "__init__.py").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return ""
    found = _VERSION_RE.search(text)
    return found.group(1) if found else ""


def version_state() -> dict | None:
    """{"reason": "version", "loaded", "on_disk"} when the disk declares another version."""
    on_disk = disk_version()
    if on_disk and on_disk != __version__:
        return {"reason": "version", "loaded": __version__, "on_disk": on_disk}
    return None


def _code_roots() -> list[Path]:
    """The engine package, then the packages (or single modules) of the loaded plugins."""
    roots = [PACKAGE]
    try:
        files = plugins.module_files()
    except Exception:  # noqa: BLE001 - the fingerprint must answer whatever a plugin is like
        files = []
    for file in files:
        path = Path(file).resolve()
        root = path.parent if path.name == "__init__.py" else path
        if root not in roots:
            roots.append(root)
    return roots


def _code_rows(root: Path) -> list[tuple[str, int, int]]:
    """(path, size, modification time) of every code file under a folder, or of a single module."""
    if root.is_file():
        try:
            stat = root.stat()
        except OSError:
            return []
        return [(str(root), stat.st_size, stat.st_mtime_ns)]
    rows: list[tuple[str, int, int]] = []
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRS:
                        stack.append(Path(entry.path))
                elif entry.name.endswith(_CODE_SUFFIXES):
                    stat = entry.stat()
                    rows.append((entry.path, stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
    return rows


def fingerprint(package: Path | None = None) -> str:
    """A digest of the code files: path, size and modification time.

    Without `package` it covers the engine package and the packages of the loaded plugins: a
    pull in the checkout of an editable plugin changes the rules this process holds while every
    version number stays the same.
    """
    rows: list[tuple[str, int, int]] = []
    for root in ([package] if package is not None else _code_roots()):
        rows.extend(_code_rows(root))
    rows.sort()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _key(folder: str) -> str:
    return os.path.normcase(os.path.normpath(folder))


def _watched() -> list[str]:
    """The folders distributions are installed into: this environment's site-packages, and the
    folders the loaded plugins came from (a user site, a second path)."""
    folders: dict[str, str] = {}
    paths = sysconfig.get_paths()
    for folder in (paths.get("purelib"), paths.get("platlib"), *plugins.installed_folders()):
        if folder:
            folders.setdefault(_key(folder), folder)
    return list(folders.values())


def _folder_marks(folders: list[str]) -> dict[str, int]:
    marks: dict[str, int] = {}
    for folder in folders:
        try:
            marks[folder] = os.stat(folder).st_mtime_ns
        except OSError:
            marks[folder] = -1  # a folder that is gone is a change as well
    return marks


def remember() -> None:
    """Take the code and the plugins as this process loaded them; a server calls it at start.

    The plugins are not walked here: at start the disk holds what was just loaded, so the
    modification times of the watched folders are enough to tell a later change by.
    """
    global _started, _checked, _marks, _plugins_found
    _started, _checked = fingerprint(), None
    _marks, _plugins_found = _folder_marks(_watched()), None


def _listed(versions: dict[str, str]) -> str:
    listed = ", ".join(f"{name} {version}" for name, version in sorted(versions.items()))
    return listed or i18n.t("cli.plugins-none")


def _compare_plugins() -> dict | None:
    """The plugins state after a walk over the installed distributions, None when they match."""
    loaded = {row["name"]: row["version"] for row in plugins.installed()}
    try:
        now = {row["name"]: row["version"] for row in plugins.on_disk()}
    except Exception:  # noqa: BLE001 - a walk that fails is no verdict, like an unreadable file
        return None
    if now == loaded:
        return None
    changed = [
        {"name": name, "loaded": loaded.get(name, ""), "on_disk": now.get(name, "")}
        for name in sorted(set(loaded) | set(now)) if loaded.get(name) != now.get(name)
    ]
    return {"reason": "plugins", "loaded": _listed(loaded), "on_disk": _listed(now),
            "changed": changed}


def plugins_state() -> dict | None:
    """{"reason": "plugins", "loaded", "on_disk", "changed"} when the plugins installed now are
    not the ones this process loaded: upgraded, removed or newly installed.

    `changed` holds {name, loaded, on_disk} per distribution that differs ("" for none). None in
    a process that did not call `remember`. The installed distributions are walked only when a
    watched folder changed since the last walk, and the verdict of that walk stands until the
    next change.
    """
    global _marks, _plugins_found
    if _marks is None:
        return None
    marks = _folder_marks(list(_marks))
    if marks != _marks:
        _marks = marks
        _plugins_found = _compare_plugins()
    return _plugins_found


def sources_state() -> dict | None:
    """{"reason": "sources", "loaded", "on_disk"} when the code files changed since `remember`.

    None in a process that took no fingerprint. The verdict is reused for a few seconds.
    """
    global _checked
    if _started is None:
        return None
    now = time.monotonic()
    if _checked is None or now - _checked[0] >= _SOURCES_TTL:
        _checked = (now, fingerprint() != _started)
    if _checked[1]:
        return {"reason": "sources", "loaded": __version__, "on_disk": __version__}
    return None


def state(*, sources: bool = False) -> dict | None:
    """The version state; then the plugins; with `sources`, the sources when both still hold."""
    found = version_state()
    if found is None:
        found = plugins_state()
    if found is None and sources:
        found = sources_state()
    return found


def plugin_changes(changed: list[dict]) -> str:
    """The changed plugins in words: "name loaded -> on disk", a missing side named as none."""
    absent = i18n.t("freshness.plugin-absent")
    return ", ".join(
        f"{row['name']} {row['loaded'] or absent} -> {row['on_disk'] or absent}" for row in changed
    )


def describe(found: dict) -> str:
    """The state in words: what changed on disk against what this process runs."""
    if found["reason"] == "plugins":
        return i18n.t("freshness.plugins", changes=plugin_changes(found.get("changed", [])))
    return i18n.t(f"freshness.{found['reason']}", loaded=found["loaded"], on_disk=found["on_disk"])


def crash_note() -> str:
    """The cause a crashed rule names; "" while the code on disk is the loaded one.

    The state found is kept for `take_noted`: the MCP server writes it into its journal.
    """
    global _noted
    found = state(sources=True)
    if found is None:
        return ""
    _noted = found
    return i18n.t("freshness.crash", state=describe(found))


def take_noted() -> dict | None:
    """The stale state a crash noted since the last call, once."""
    global _noted
    found, _noted = _noted, None
    return found
