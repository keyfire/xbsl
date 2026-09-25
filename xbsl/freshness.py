"""Is the engine code on disk still the code this process runs?

A long-lived process - the MCP server above all - imports its modules lazily. When the
installation is replaced under it (`self-update`, a `git pull` in an editable checkout), the
modules it already holds stay old, and every module it imports afterwards comes from the new
code. The two halves then disagree about their own interfaces. Caught live on 24.09.2026: a
server started on 0.117.0 and left running while its editable checkout moved to 0.118.0 answered
`lint_paths` with four rule crashes, `TypeError: ProjectCatalog.register_row() takes 3
positional arguments but 4 were given` - the catalog in memory was the old class, the rules
calling it were new. The CLI over the same files was clean, and nothing in the answer said that
a restart was the cure.

Two checks, by cost:

- the VERSION: `__version__` in memory against the `__init__.py` on disk. One small file, cheap
  enough for every call of a tool (`version_state`);
- the SOURCES: a fingerprint of the code files - relative path, size, modification time - taken
  when the server starts (`remember`) against one taken now (`sources_state`). A walk over some
  two hundred files, a couple of milliseconds, done only after something failed: it covers the
  pull between two releases, where the number stays while the code changes.

Nothing here restarts or stops the process: a client such as Codex does not start a failed
server again, so the server keeps answering and says what to do.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path

import xbsl
from xbsl import __version__, i18n

MESSAGES = {
    "freshness.version": {
        "ru": "код движка на диске обновлен: {loaded} -> {on_disk}, а этот процесс работает на "
              "{loaded} из памяти",
        "en": "the engine code on disk was updated: {loaded} -> {on_disk}, while this process "
              "runs {loaded} from memory",
    },
    "freshness.sources": {
        "ru": "исходники движка на диске изменились после запуска этого процесса (номер версии "
              "тот же, {loaded})",
        "en": "the engine sources on disk changed after this process started (the version "
              "number is the same, {loaded})",
    },
    "freshness.refusal": {
        "ru": "{state}. Модули, которые сервер подгрузит дальше, будут из нового кода и не "
              "сойдутся с уже загруженными, поэтому инструменты не выполняются. Перезапустите "
              "сервер MCP xbsl; сам сервер не перезапускается и не завершается",
        "en": "{state}. The modules the server loads from now on come from the new code and do "
              "not match the ones already loaded, so the tools do not run. Restart the xbsl MCP "
              "server; the server neither restarts nor exits on its own",
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


def fingerprint(package: Path | None = None) -> str:
    """A digest of the code files of the package: relative path, size and modification time."""
    root = package or PACKAGE
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
                    rows.append((os.path.relpath(entry.path, root), stat.st_size, stat.st_mtime_ns))
            except OSError:
                continue
    rows.sort()
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def remember() -> None:
    """Take the fingerprint of the code as this process loaded it; a server calls it at start."""
    global _started, _checked
    _started, _checked = fingerprint(), None


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
    """The version state, and with `sources` the sources state when the version is the same."""
    found = version_state()
    if found is None and sources:
        found = sources_state()
    return found


def describe(found: dict) -> str:
    """The state in words: what changed on disk against what this process runs."""
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
