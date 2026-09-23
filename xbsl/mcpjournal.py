"""A journal of MCP server lives: when a server started, how it ended and who stopped it.

A client that loses its server reports only that the transport closed. Three different causes
look the same from there: the server failed, the client closed its end, or `self-update
--stop-holders` of another session stopped the process to replace the package. The journal
tells them apart. The server writes its own start and end; a forced stop cannot be caught by
the process it ends, so the stopper writes that record for it. `xbsl mcp-log` prints the result.

One JSON object per line, appended; the file keeps its last KEEP_LINES lines. Writing never
fails the caller: a journal that cannot be written costs a diagnostic, not a server.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

#: The number of lines kept when the journal is trimmed.
KEEP_LINES = 500
#: The size past which the next write trims the journal.
TRIM_AT_BYTES = 256 * 1024
#: The variable that moves the journal, for tests and for a machine with an unusual layout.
ENV_PATH = "XBSL_MCP_JOURNAL"


def journal_path() -> Path:
    """Where the journal lives: the user's local state folder, not the installation."""
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "xbsl" / "mcp-journal.jsonl"


def record(event: str, **fields: object) -> None:
    """Append one event with the time and the writing process; errors are swallowed."""
    entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, "pid": os.getpid()}
    entry.update(fields)
    path = journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if path.stat().st_size > TRIM_AT_BYTES:
            _trim(path)
    except OSError:
        pass


def _trim(path: Path) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-KEEP_LINES:]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")


def read(last: int = 0) -> list[dict]:
    """The journal's events, oldest first; `last` above zero keeps that many newest ones."""
    path = journal_path()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue  # a line cut by a concurrent trim says nothing reliable
        if isinstance(item, dict):
            events.append(item)
    return events[-last:] if last > 0 else events
