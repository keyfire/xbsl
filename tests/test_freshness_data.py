"""A long-lived server tells when the platform data it read is not the data on disk now.

Caught on 29.09.2026: an MCP worker started two seconds before the data files of a reinstalled
plugin were written, and `translate_status` counted six untranslated tokens and eighteen gaps of
the platform data where the CLI on the same interpreter counted none. The worker had read
`terms.json` while it imported - a few modules take their constants from it at import, and no
cache reset rebuilds those - and nothing in its answers said so: `version_info` saw the same
versions, and the data had no place in the checks of xbsl/freshness.py. A restart cured it.

Every data file a process reads, or looks for and does not find, is now noted with the size and
the modification time the disk held just before (xbsl/dataset.py). A server that took its start
compares them with the disk and treats a change like a change of its code: the MCP tools refuse
before they run, the supervisor answers the call from a new worker, the language server asks
for a restart.

No Element data: the data root is a folder of the test's own.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from xbsl import cli, dataset, engine, freshness, i18n, mcp_supervisor, mcpcli, mcpjournal, terms

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0"


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _reinstall(path: Path, data: dict) -> None:
    """Replace a file the way an install does - remove it, write it anew - and move its time
    on, whatever the resolution of the clock."""
    before = path.stat().st_mtime_ns
    path.unlink()
    _write(path, data)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, max(stat.st_mtime_ns, before) + 2_000_000_000))


def _index(folder: Path, default: str = VERSION, *more: str) -> None:
    _write(folder / "index.json", {"default": default, "available": sorted({default, *more})})


@pytest.fixture()
def root(tmp_path):
    """A data root of one version, pinned for the process: the index, the pairs, the catalog."""
    folder = tmp_path / "element"
    _index(folder)
    _write(folder / VERSION / "terms.json", {"types": {"Массив": "Array"}})
    _write(folder / VERSION / "stdlib.json", {"globals": ["Сообщить"]})
    dataset.set_data_root(folder)
    try:
        yield folder
    finally:
        dataset.set_data_root(None)


@pytest.fixture()
def fresh(monkeypatch, tmp_path):
    """A start of this test's own: what `remember` takes is put back after it. The code and
    the plugins of this very process are not what these tests change, so their checks answer
    that nothing moved - a pull in the checkout during the run must not decide a test here."""
    for name in ("_started", "_checked", "_engine", "_noted", "_marks", "_plugins_found"):
        monkeypatch.setattr(freshness, name, None)
    monkeypatch.setattr(freshness, "_unsettled", False)
    monkeypatch.setattr(freshness, "_data_watched", False)
    for check in ("plugins_state", "engine_sources_state", "sources_state"):
        monkeypatch.setattr(freshness, check, lambda: None)
    # A refusal saves the data of a call for its CLI command - here in the test's own folder.
    (tmp_path / "staged").mkdir()
    monkeypatch.setattr(mcpcli, "_staged_in", str(tmp_path / "staged"))


@pytest.fixture()
def started(root, fresh):
    """The pairs read the way a module reads them at import, then the start of a server."""
    assert terms.english("Массив", "types") == "Array"
    freshness.remember()
    return root


# -- what the process read ----------------------------------------------------------------------


def test_the_files_a_process_read_are_noted_with_what_the_disk_held(root):
    dataset.load_json("terms.json")
    reads = dataset.data_reads()
    stat = (root / VERSION / "terms.json").stat()
    assert reads[(str(root), VERSION, "terms.json")] == (stat.st_size, stat.st_mtime_ns)
    assert (str(root), "", "index.json") in reads
    assert (str(root), VERSION, "stdlib.json") not in reads  # never read


def test_a_file_looked_for_in_vain_is_noted_as_absent(root):
    assert dataset.load_optional(dataset.UI_SCHEMA_FILE) is None
    assert dataset.data_reads()[(str(root), VERSION, dataset.UI_SCHEMA_FILE)] is None


def test_the_first_reading_stays_after_the_caches_are_dropped(root):
    """A cache reset rebuilds the tables registered with it, not a constant taken at import."""
    dataset.load_json("terms.json")
    first = dataset.data_reads()[(str(root), VERSION, "terms.json")]
    _reinstall(root / VERSION / "terms.json", {"types": {"Массив": "Array", "Строка": "String"}})

    # Any later read looks at the stamps and drops every cache over the changed file.
    assert dataset.load_json("terms.json")["types"]["Строка"] == "String"

    assert dataset.data_reads()[(str(root), VERSION, "terms.json")] == first


# -- the check ----------------------------------------------------------------------------------


def test_a_process_that_took_no_start_judges_no_data(root, fresh):
    """The CLI lives for one run: it reads the data once and has nothing to compare."""
    dataset.load_json("terms.json")
    _reinstall(root / VERSION / "terms.json", {"types": {}})
    assert freshness.data_state() is None and freshness.call_state() is None


def test_untouched_data_is_fresh(started):
    for _call in range(3):
        assert freshness.data_state() is None
        assert freshness.call_state() is None and freshness.state(sources=True) is None


def test_a_data_file_replaced_under_the_process_makes_it_stale(started):
    _reinstall(started / VERSION / "terms.json", {"types": {"Массив": "Array", "Строка": "String"}})

    found = freshness.data_state()

    assert {key: found[key] for key in ("reason", "loaded", "on_disk", "root", "changed")} == {
        "reason": "data", "loaded": VERSION, "on_disk": VERSION, "root": str(started),
        "changed": [{"file": f"{VERSION}/terms.json", "change": "modified"}],
    }
    assert len(found["fingerprint"]) == 12 and int(found["fingerprint"], 16) >= 0
    assert freshness.call_state() == found and freshness.state() == found
    assert freshness.describe(found) == (
        "данные платформы на диске изменились после запуска этого процесса: "
        f"{VERSION}/terms.json в {started}")


def test_each_change_of_the_data_has_a_fingerprint_of_its_own(started):
    """The supervisor tells a new change from the one a worker was started after by it."""
    _reinstall(started / VERSION / "terms.json", {"types": {"Строка": "String"}})
    first = freshness.data_state()["fingerprint"]
    _reinstall(started / VERSION / "terms.json", {"types": {"Число": "Number"}})
    assert freshness.data_state()["fingerprint"] != first


def test_a_file_the_process_did_not_read_does_not_count(started):
    """The catalog was never read, so no answer of this process came from it: a new process
    would answer the same. The documentation database is not among the reads either - every
    call opens it anew and its index is keyed by the file's own size and time."""
    _reinstall(started / VERSION / "stdlib.json", {"globals": []})
    _write(started / VERSION / "docs.sqlite", {})
    _write(started / "2.0" / "terms.json", {"types": {}})  # a version the index does not name
    assert freshness.data_state() is None


def test_a_file_looked_for_in_vain_counts_once_it_appears(started):
    """The process concluded the file was not there, and what it built stays without it."""
    assert dataset.load_optional(dataset.UI_SCHEMA_FILE) is None
    assert freshness.data_state() is None

    _write(started / VERSION / dataset.UI_SCHEMA_FILE, {"components": {}})

    found = freshness.data_state()
    assert found["changed"] == [{"file": f"{VERSION}/{dataset.UI_SCHEMA_FILE}", "change": "added"}]
    assert "uischema.json (появился)" in freshness.describe(found)


def test_a_new_data_version_shows_through_the_index(started):
    """A new version comes as a folder of its own and a new default in the index; the process
    read the index to pick its version, so the index names the change."""
    _write(started / "2.0" / "terms.json", {"types": {"Массив": "Array"}})
    _reinstall(started / "index.json", {"default": "2.0", "available": [VERSION, "2.0"]})

    found = freshness.data_state()

    assert found["changed"] == [{"file": "index.json", "change": "modified"}]
    assert (found["loaded"], found["on_disk"]) == (VERSION, "2.0")


def test_a_root_that_vanished_makes_the_process_stale(started):
    aside = started.with_name("element-aside")
    started.rename(aside)
    try:
        found = freshness.data_state()
    finally:
        aside.rename(started)

    assert found["changed"] == [
        {"file": f"{VERSION}/terms.json", "change": "removed"},
        {"file": "index.json", "change": "removed"},
    ]
    assert (found["loaded"], found["on_disk"]) == (VERSION, "")
    assert "index.json (удален)" in freshness.describe(found)
    assert freshness.data_state() is None  # the root is back as it was


def test_a_root_that_appears_after_the_start_makes_the_process_stale(tmp_path, monkeypatch,
                                                                     fresh):
    """The root a plugin declares had no index yet when the process chose its root - a plugin
    being installed - and the process went on without data. The probe that chose counts as a
    look at the file."""
    declared = tmp_path / "plugin-data"
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(dataset.plugins, "data_roots", lambda: [declared])
    monkeypatch.setattr(dataset, "BUNDLED_DATA_ROOT", bundled)
    monkeypatch.delenv("XBSL_DATA_DIR", raising=False)
    monkeypatch.delenv("XBSLLINT_DATA_DIR", raising=False)
    dataset.set_data_root(None)
    try:
        assert dataset.data_root() == bundled and terms.english("Массив", "types") is None
        freshness.remember()
        assert freshness.data_state() is None

        _write(declared / VERSION / "terms.json", {"types": {"Массив": "Array"}})
        _index(declared)

        found = freshness.data_state()
    finally:
        dataset.set_data_root(None)

    assert found["root"] == str(declared) and (found["loaded"], found["on_disk"]) == ("", VERSION)
    assert found["changed"] == [{"file": "index.json", "change": "added"}]


def test_the_changes_of_two_roots_are_told_apart(started, tmp_path):
    """A process that read two roots - a pinned one after the default one - names both."""
    other = tmp_path / "other"
    _index(other)
    _write(other / VERSION / "terms.json", {"types": {}})
    dataset.set_data_root(other)
    dataset.load_json("terms.json")
    _reinstall(started / VERSION / "terms.json", {"types": {}})
    _reinstall(started / VERSION / "stdlib.json", {"globals": []})  # never read: no change
    _reinstall(other / VERSION / "terms.json", {"types": {"Массив": "Array"}})
    _reinstall(other / "index.json", {"default": VERSION, "available": [VERSION]})

    found = freshness.data_state()

    assert found["root"] == str(other)
    assert found["changed"] == [
        {"file": f"{VERSION}/terms.json", "change": "modified"},
        {"file": "index.json", "change": "modified"},
        {"file": f"{VERSION}/terms.json", "change": "modified", "root": str(started)},
    ]
    assert freshness.describe(found).endswith(
        f"{VERSION}/terms.json, index.json в {other}; {VERSION}/terms.json в {started}")


def test_the_check_reads_nothing_and_drops_no_cache(started, monkeypatch):
    """A stat per file read, nothing more: the check runs before every call of a tool."""
    loaded = dataset.load_json("terms.json")
    opened: list = []
    monkeypatch.setattr(dataset, "read_json", lambda path: opened.append(path) or {})
    for _call in range(3):
        freshness.call_state()
    assert opened == [] and dataset.load_json("terms.json") is loaded


def test_the_version_on_disk_is_read_past_the_caches(started):
    assert dataset.version_on_disk(str(started)) == VERSION
    _reinstall(started / "index.json", {"default": "2.0", "available": [VERSION, "2.0"]})
    assert dataset.version_on_disk(str(started)) == "2.0"
    assert dataset.default_version() == "2.0"  # the dataset itself sees it the same way
    assert dataset.version_on_disk(str(started / "missing")) == ""


# -- the rest of the process --------------------------------------------------------------------


def test_the_language_server_is_told_of_the_data_too(started):
    """The server of the editor asks `state` - the same check, the same reason."""
    _reinstall(started / VERSION / "terms.json", {"types": {}})
    found = freshness.state(sources=True)
    text = i18n.t("freshness.editor", state=freshness.describe(found))
    assert found["reason"] == "data" and text.startswith("xbsl-lsp: данные платформы")
    assert "Перезапустите сервер языка" in text and "на коде" not in text


def test_a_rule_crash_after_the_data_changed_names_the_restart(started):
    _reinstall(started / VERSION / "terms.json", {"types": {}})
    error = TypeError("boom")
    message = engine._crash_diag("code/missing-return", "Задачи.xbsl", error).message
    assert "данные платформы" in message and "смеси прежних и новых данных" in message
    assert "Перезапустите процесс" in message and "сообщите" not in message
    assert freshness.take_noted()["reason"] == "data"


def test_the_data_messages_speak_english_too(started):
    _reinstall(started / VERSION / "terms.json", {"types": {}})
    found = freshness.data_state()
    i18n.set_lang("en")
    try:
        texts = [freshness.describe(found), freshness.refusal(found),
                 freshness.failure(found, "TypeError: boom"),
                 i18n.t("freshness.editor", state=freshness.describe(found))]
    finally:
        i18n.set_lang("ru")
    assert texts[0] == (f"the platform data on disk changed after this process started: "
                        f"{VERSION}/terms.json in {started}")
    assert "Restart the xbsl MCP server" in texts[1]
    assert "a mix of the old and the new data" in texts[2]
    for text in texts:
        assert not any("а" <= char <= "я" for char in text.lower().replace(
            str(started).lower(), "")), text


# -- the MCP server -----------------------------------------------------------------------------


def _stale_events():
    return [event for event in mcpjournal.read() if event["event"] == "stale"]


def test_a_tool_is_refused_before_it_runs_when_the_data_changed(started, mcp_module):
    called = []

    def translate_status(root: str) -> dict:
        called.append(root)
        return {"untranslated": 0}

    guarded = mcp_module._stale_guard(translate_status)
    assert guarded(root="acme") == {"untranslated": 0}
    _reinstall(started / VERSION / "terms.json", {"types": {"Массив": "Array"}})

    answer = guarded(root="acme")
    guarded(root="acme")

    assert called == ["acme"]  # the later calls never started
    stale = answer["stale"]
    assert (stale["reason"], stale["ran"], stale["root"]) == ("data", False, str(started))
    assert stale["changed"] == [{"file": f"{VERSION}/terms.json", "change": "modified"}]
    assert "данные платформы на диске изменились" in answer["error"]
    assert "прежних файлов данных" in answer["error"] and "Перезапустите сервер MCP" in answer["error"]
    assert "cli" in answer  # the same call through a new process reads the data on disk
    (event,) = _stale_events()
    assert (event["reason"], event["tool"], event["root"]) == ("data", "translate_status",
                                                               str(started))


def test_version_info_names_the_data_change(started, mcp_module):
    _reinstall(started / VERSION / "terms.json", {"types": {}})

    info = mcp_module.version_info()

    assert info["stale"]["reason"] == "data" and info["stale"]["on_disk"] == VERSION
    assert info["stale"]["changed"] == [{"file": f"{VERSION}/terms.json", "change": "modified"}]
    assert "Перезапустите сервер MCP" in info["stale"]["message"]


def test_version_info_on_untouched_data_carries_no_stale_record(started, mcp_module):
    assert "stale" not in mcp_module.version_info()


def test_the_supervisor_answers_a_data_refusal_from_a_new_worker():
    """The refusal did not run the tool, so the same call goes to a new worker."""
    stale = {"reason": "data", "loaded": VERSION, "on_disk": VERSION, "root": "r",
             "changed": [{"file": "1.0/terms.json", "change": "modified"}],
             "fingerprint": "0123456789ab", "ran": False}
    answer = {"jsonrpc": "2.0", "id": 5, "result": {
        "content": [{"type": "text", "text": json.dumps({"error": "x", "stale": stale})}]}}
    assert mcp_supervisor.verdict(answer, "translate_status") == ("replay", stale)


def test_mcp_log_tells_the_data_state_in_words(capsys, tmp_path):
    root = str(tmp_path / "element")
    mcpjournal.record("stale", reason="data", loaded=VERSION, on_disk=VERSION, root=root,
                      changed=[{"file": "1.0/terms.json", "change": "modified"},
                               {"file": "1.0/uischema.json", "change": "added"}],
                      fingerprint="0123456789ab", tool="translate_status")
    mcpjournal.record("restart", target=101, reason="data", loaded=VERSION, on_disk=VERSION)
    assert cli.main(["mcp-log"]) == 0
    out = capsys.readouterr().out
    assert ("данные платформы на диске изменились после запуска сервера: 1.0/terms.json, "
            f"1.0/uischema.json (появился) в {root} (вызов translate_status)") in out
    assert "супервизор заменяет процесс сервера 101: данные платформы на диске изменились" in out
    i18n.set_lang("en")
    try:
        assert cli.main(["mcp-log"]) == 0
        english = capsys.readouterr().out
    finally:
        i18n.set_lang("ru")
    assert "the platform data on disk changed after the server started: 1.0/terms.json" in english
    assert "the supervisor replaces the server process 101: the platform data on disk" in english


def test_the_real_server_is_replaced_when_the_data_it_read_is_replaced(tmp_path):
    """The whole way, as on 29.09.2026: the worker reads the pairs while it imports, the file is
    replaced under it, and the next call is answered by a new worker instead of the old data."""
    pytest.importorskip("mcp")
    from test_mcp_supervisor import CLIENT_PARAMS, Session, payload

    data = tmp_path / "element"
    _index(data)
    _write(data / VERSION / "terms.json", {"types": {"Массив": "Array"}})
    work = tmp_path / "work"
    work.mkdir()
    env = dict(os.environ, PYTHONPATH=str(ROOT), XBSL_NO_PLUGINS="1", XBSL_DATA_DIR=str(data),
               PYTHONIOENCODING="utf-8")
    session = Session([sys.executable, "-m", "xbsl.mcp_supervisor"], env=env, cwd=work,
                      stderr=tmp_path / "stderr.txt")
    try:
        assert session.request(0, "initialize", CLIENT_PARAMS)["result"]
        session.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        rules = {"select": ["code/brackets"]}
        before = payload(session.call(1, "list_rules", rules))
        loaded = payload(session.call(2, "version_info"))

        _reinstall(data / VERSION / "terms.json", {"types": {"Массив": "Array", "Строка": "String"}})
        after = payload(session.call(3, "list_rules", rules))
        info = payload(session.call(4, "version_info"))
        assert session.close() == 0
    finally:
        if session.process.poll() is None:
            session.process.kill()
            session.process.wait()
        session.stderr.close()

    assert before["id"] == "code/brackets" and "stale" not in loaded
    assert after.get("id") == "code/brackets", after  # not a refusal
    assert info["engine"] == loaded["engine"] and "stale" not in info
    events = mcpjournal.read()
    (stale,) = [event for event in events if event["event"] == "stale"]
    assert (stale["tool"], stale["reason"], stale["root"]) == ("list_rules", "data", str(data))
    assert stale["changed"] == [{"file": f"{VERSION}/terms.json", "change": "modified"}]
    (restart,) = [event for event in events if event["event"] == "restart"]
    assert restart["reason"] == "data"
    assert len([event for event in events if event["event"] == "start"]) == 2
