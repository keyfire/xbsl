"""The MCP server journal: a closed transport on the client side gets a readable cause."""

import json
import sys

import pytest

from xbsl import cli, i18n, mcpjournal, selfupdate


def _events():
    return mcpjournal.read()


def test_events_come_back_in_order_with_time_and_process():
    mcpjournal.record("start", version="1.2.3", parent=7)
    mcpjournal.record("exit", reason="input-closed")
    first, second = _events()
    assert first["event"] == "start" and first["version"] == "1.2.3" and first["parent"] == 7
    assert second == {**second, "event": "exit", "reason": "input-closed"}
    assert first["time"] and first["pid"] == second["pid"]


def test_the_journal_keeps_its_newest_lines(monkeypatch):
    monkeypatch.setattr(mcpjournal, "TRIM_AT_BYTES", 10)
    monkeypatch.setattr(mcpjournal, "KEEP_LINES", 3)
    for number in range(10):
        mcpjournal.record("start", version=str(number))
    assert [event["version"] for event in _events()] == ["7", "8", "9"]


def test_read_keeps_the_newest_and_skips_a_cut_line(monkeypatch):
    path = mcpjournal.journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"event": "start", "version": str(n)}) for n in range(4)]
    path.write_text("\n".join(lines[:2] + ['{"event": "st'] + lines[2:]) + "\n", encoding="utf-8")
    assert [event["version"] for event in mcpjournal.read()] == ["0", "1", "2", "3"]
    assert [event["version"] for event in mcpjournal.read(2)] == ["2", "3"]


def test_an_unwritable_journal_never_stops_the_caller(monkeypatch, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv(mcpjournal.ENV_PATH, str(blocker / "journal.jsonl"))
    mcpjournal.record("start")
    assert mcpjournal.read() == []


def test_the_default_place_is_the_user_state_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(mcpjournal.ENV_PATH)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    path = mcpjournal.journal_path()
    assert path.name == "mcp-journal.jsonl" and path.parent.name == "xbsl"
    assert str(path).startswith(str(tmp_path))


def test_a_forced_stop_is_written_for_the_process_it_ends(monkeypatch):
    monkeypatch.setattr(selfupdate.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(selfupdate.os, "kill", lambda pid, sig: None)
    selfupdate.stop_holders([{"pid": 4242, "name": "python.exe"}], lambda text: None,
                            reason="self-update 1.0.0 -> 1.1.0")
    (event,) = _events()
    assert event["event"] == "stopped" and event["target"] == 4242
    assert event["name"] == "python.exe" and event["reason"] == "self-update 1.0.0 -> 1.1.0"


def test_mcp_log_tells_the_story_in_words(capsys):
    mcpjournal.record("start", version="1.0.0", parent=31)
    mcpjournal.record("stopped", target=99, name="python.exe", reason="self-update 1.0.0 -> 1.1.0")
    mcpjournal.record("exit", reason="failed", error="RuntimeError: boom")
    i18n.set_lang("en")
    try:
        assert cli.main(["mcp-log"]) == 0
    finally:
        i18n.set_lang("ru")
    out = capsys.readouterr().out
    assert "server xbsl 1.0.0 started, parent process 31" in out
    assert "process 99 (python.exe) stopped: self-update 1.0.0 -> 1.1.0" in out
    assert "ended with a failure: RuntimeError: boom" in out


def test_mcp_log_json_and_last(capsys):
    for number in range(3):
        mcpjournal.record("start", version=str(number))
    assert cli.main(["mcp-log", "--json", "--last", "2"]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [event["version"] for event in printed] == ["1", "2"]


def test_mcp_log_on_an_empty_journal_says_so(capsys):
    assert cli.main(["mcp-log"]) == 0
    out = capsys.readouterr().out
    assert str(mcpjournal.journal_path()) in out and "записей нет" in out


def test_the_server_writes_its_start_and_its_end(mcp_module, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["xbsl-mcp"])
    monkeypatch.setattr(mcp_module.mcp, "run", lambda: None, raising=False)
    mcp_module.main()
    start, end = _events()
    assert start["event"] == "start" and start["version"] == mcp_module.__version__
    assert end["event"] == "exit" and end["reason"] == "input-closed"


def test_a_failed_server_leaves_the_error(mcp_module, monkeypatch):
    def broken():
        raise RuntimeError("stdio is gone")

    monkeypatch.setattr(sys, "argv", ["xbsl-mcp"])
    monkeypatch.setattr(mcp_module.mcp, "run", broken, raising=False)
    with pytest.raises(RuntimeError):
        mcp_module.main()
    end = _events()[-1]
    assert end["reason"] == "failed" and end["error"] == "RuntimeError: stdio is gone"
