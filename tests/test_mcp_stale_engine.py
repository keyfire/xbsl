"""A server whose engine was replaced on disk says so instead of crashing its rules.

Caught live on 24.09.2026: an MCP server started on 0.117.0 kept running while its editable
checkout moved to 0.118.0, and `lint_paths` answered with four crashes of rules -
`TypeError: ProjectCatalog.register_row() takes 3 positional arguments but 4 were given` - the
modules loaded later were new, the catalog in memory was old. The CLI over the same files was
clean. Now every tool but version_info compares the version on disk with the loaded one and
refuses with the cure named; the engine's code files are compared with the start before the call
too, so a pull between two releases is refused before the tool runs; a failure is checked
against the fingerprint of all the sources taken at start; a crashed rule names the restart in
its own report.

A restart is in the client's hands, not the agent's: on 27.09.2026 a session met the refusal on
every call after the engine moved from 0.119.1 to 0.120.0 and finished its work through the CLI
by hand. So the refusal of a tool the CLI can run carries `cli`, the command line of the same
call (xbsl/mcpcli.py; the command itself is tested in tests/test_mcpcli.py).

No Element data and no live server: the package on disk is a folder of the test's own.
"""

from __future__ import annotations

import inspect
import json
import os
import shlex
from pathlib import Path

import pytest

from xbsl import cli, engine, freshness, i18n, mcpcli, mcpjournal


def _package(folder, version: str):
    """A stand-in for the installed package: an `__init__.py` with a BOM, a module, the data."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text(f'﻿"""doc"""\n\n__version__ = "{version}"\n',
                                        encoding="utf-8")
    (folder / "rules").mkdir(exist_ok=True)
    (folder / "rules" / "catalog.py").write_text("def register_row(a, b):\n    pass\n",
                                                  encoding="utf-8")
    (folder / "data").mkdir(exist_ok=True)
    (folder / "data" / "index.json").write_text("{}", encoding="utf-8")
    return folder


@pytest.fixture()
def disk(tmp_path, monkeypatch):
    """The package on disk, declaring the loaded version until a test says otherwise."""
    folder = _package(tmp_path / "xbsl", freshness.__version__)
    monkeypatch.setattr(freshness, "PACKAGE", folder)
    monkeypatch.setattr(freshness, "_started", None)
    monkeypatch.setattr(freshness, "_checked", None)
    monkeypatch.setattr(freshness, "_engine", None)
    monkeypatch.setattr(freshness, "_noted", None)
    monkeypatch.setattr(freshness, "_marks", None)
    monkeypatch.setattr(freshness, "_plugins_found", None)
    monkeypatch.setattr(freshness, "_unsettled", False)
    monkeypatch.setattr(freshness, "_SOURCES_TTL", 0.0)
    # A refusal saves the data of a call for its CLI command - here in the test's own folder.
    (tmp_path / "staged").mkdir()
    monkeypatch.setattr(mcpcli, "_staged_in", str(tmp_path / "staged"))
    return folder


def _update(folder, version: str) -> None:
    (folder / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def _touch(path, text: str) -> None:
    """Rewrite a file in place and move its time on, whatever the clock resolution. Its folder
    keeps its time, as it does when an editor saves a file."""
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


def _pull(path, text: str) -> None:
    """Replace a file the way git does - remove it, write it anew - and move the times of the
    file and of its folder on, whatever the clock resolution."""
    folder = path.parent.stat()
    path.unlink()
    _touch(path, text)
    os.utime(path.parent, ns=(folder.st_atime_ns, folder.st_mtime_ns + 2_000_000_000))


def _stale_events():
    return [event for event in mcpjournal.read() if event["event"] == "stale"]


# -- reading the disk ---------------------------------------------------------------------------


def test_the_version_on_disk_is_read_through_a_byte_order_mark(disk):
    assert freshness.disk_version() == freshness.__version__
    _update(disk, "9.9.9")
    assert freshness.disk_version() == "9.9.9"


def test_an_unreadable_package_is_no_verdict(disk):
    """self-update renames the package aside for a moment: a call then must not be refused."""
    (disk / "__init__.py").unlink()
    assert freshness.disk_version() == "" and freshness.version_state() is None


def test_the_version_state_names_both_numbers(disk):
    assert freshness.version_state() is None
    _update(disk, "9.9.9")
    assert freshness.version_state() == {
        "reason": "version", "loaded": freshness.__version__, "on_disk": "9.9.9"}


def test_the_fingerprint_follows_the_code_and_not_the_data(disk):
    before = freshness.fingerprint()
    _touch(disk / "data" / "index.json", '{"default": "9.0"}')
    assert freshness.fingerprint() == before
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    assert freshness.fingerprint() != before


def test_the_sources_are_judged_only_against_a_remembered_start(disk):
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    assert freshness.sources_state() is None  # the CLI takes no fingerprint
    freshness.remember()
    assert freshness.sources_state() is None
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c, d):\n    pass\n")
    found = freshness.sources_state()
    assert {key: found[key] for key in ("reason", "loaded", "on_disk")} == {
        "reason": "sources", "loaded": freshness.__version__, "on_disk": freshness.__version__}
    # The number stays: a digest of the files on disk tells this change from the next one.
    assert len(found["fingerprint"]) == 12 and int(found["fingerprint"], 16) >= 0


# -- a crashed rule -----------------------------------------------------------------------------


def _crash() -> str:
    error = TypeError("register_row() takes 3 positional arguments but 4 were given")
    return engine._crash_diag("code/missing-return", "Задачи.xbsl", error).message


def test_a_rule_crash_on_a_fresh_engine_is_still_a_bug_to_report(disk):
    assert "сообщите" in _crash() and "перезапустите" not in _crash().lower()


def test_a_rule_crash_on_a_replaced_engine_names_the_restart(disk):
    _update(disk, "9.9.9")
    message = _crash()
    assert "TypeError: register_row()" in message
    assert f"{freshness.__version__} -> 9.9.9" in message and "Перезапустите процесс" in message
    assert "сообщите" not in message
    assert freshness.take_noted()["on_disk"] == "9.9.9"


def test_a_rule_crash_after_a_pull_between_releases_names_the_restart(disk):
    freshness.remember()
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    message = _crash()
    assert "номер версии тот же" in message and "Перезапустите процесс" in message


# -- the MCP server -----------------------------------------------------------------------------


def _lint(mcp_module):
    """lint_paths as the server holds it - behind the check."""
    return mcp_module.mcp.tools["lint_paths"]


def test_a_fresh_engine_lets_the_call_through(mcp_module, disk):
    called = []
    guarded = mcp_module._stale_guard(lambda **kwargs: called.append(kwargs) or {"ok": True})
    assert guarded(paths=["a"]) == {"ok": True} and called == [{"paths": ["a"]}]
    assert _stale_events() == []


def test_a_replaced_engine_is_refused_in_words_not_in_a_type_error(mcp_module, disk, tmp_path):
    source = tmp_path / "Задачи.xbsl"
    source.write_text("метод Проба()\n;\n", encoding="utf-8")
    _update(disk, "9.9.9")

    answer = _lint(mcp_module)(paths=[str(source)])

    assert set(answer) == {"error", "cli", "stale"}
    assert f"{freshness.__version__} -> 9.9.9" in answer["error"]
    assert "Перезапустите сервер MCP" in answer["error"]
    assert answer["stale"]["reason"] == "version" and answer["stale"]["on_disk"] == "9.9.9"
    assert answer["stale"]["location"]


def test_every_tool_but_version_info_is_behind_the_check(mcp_module, disk):
    _update(disk, "9.9.9")
    for name, tool in mcp_module.mcp.tools.items():
        if name == "version_info":
            continue
        assert tool.__wrapped__ is getattr(mcp_module, name), name
    info = mcp_module.mcp.tools["version_info"]()
    assert info["engine"] == freshness.__version__ and info["engine_on_disk"] == "9.9.9"
    assert info["stale"]["on_disk"] == "9.9.9" and "Перезапустите" in info["stale"]["message"]


def test_version_info_on_a_fresh_engine_carries_no_stale_record(mcp_module, disk):
    info = mcp_module.version_info()
    assert info["engine_on_disk"] == info["engine"] and "stale" not in info


def _after_xbsl(words: list[str]) -> list[str]:
    """The words of a command after `-m xbsl`: what the CLI reads."""
    return words[words.index("-m") + 2:]


def _words(line: str) -> list[str]:
    """The words of a line of one run. On Python 3.10 the run stands in a subshell that changes
    into a folder first, `(cd FOLDER && ...)` (mcpcli._start_folder): its words are inside."""
    words = shlex.split(line)
    if words[0] == "(cd":
        assert words[2] == "&&" and words[-1].endswith(")"), words
        words = [*words[3:-1], words[-1][:-1]]
    return words


def test_a_refusal_names_the_cli_command_of_the_same_call(mcp_module, disk, tmp_path):
    _update(disk, "9.9.9")

    answer = _lint(mcp_module)(paths=["acme/Задачи.xbsl"], root=str(tmp_path), select=["code"])

    assert list(answer) == ["error", "cli", "stale"]
    assert "Перезапустите сервер MCP" in answer["error"]
    assert "команда из поля cli" in answer["error"]
    assert _after_xbsl(_words(answer["cli"])) == [
        str(tmp_path / "acme" / "Задачи.xbsl"), "--select", "code", "--format", "json"]


def test_a_refused_lint_source_saves_its_text_for_the_stdin_of_the_command(mcp_module, disk):
    _update(disk, "9.9.9")
    content = "метод Ф()\r\n;\n"

    answer = mcp_module.mcp.tools["lint_source"](filename="Задачи.xbsl", content=content)

    words = _words(answer["cli"])
    staged = words[words.index("<") + 1]
    assert Path(staged).read_bytes() == content.encode("utf-8")
    assert staged in answer["cli_note"] and "--stdin" in words
    assert list(answer) == ["error", "cli", "cli_note", "stale"]


def test_every_guarded_tool_can_answer_with_a_refusal(mcp_module):
    """The refusal is an object, and the SDK checks an answer against the declared return type.

    A tool declared to return a list alone had its refusal replaced by a validation error of the
    SDK, the message lost inside it (`docs_search`, until 28.09.2026).
    """
    for name, tool in mcp_module.mcp.tools.items():
        if name == "version_info":
            continue
        declared = str(inspect.signature(tool).return_annotation).split("|")
        assert any(part.strip() == "dict" or part.strip().startswith("dict[")
                   for part in declared), name


def test_a_tool_without_a_cli_counterpart_is_refused_as_before(mcp_module, disk):
    _update(disk, "9.9.9")

    answer = mcp_module.mcp.tools["docs_search"](query="Массив")

    assert set(answer) == {"error", "stale"}
    assert answer["error"] == i18n.t("freshness.refusal", state=freshness.describe(
        freshness.version_state()))


def test_a_failure_after_the_sources_moved_names_the_command_too(mcp_module, disk, tmp_path):
    """The sources moved while the call ran: the check before it had nothing to see."""
    freshness.remember()

    def translate_drift(root: str, filter: str = "", limit: int = 50, offset: int = 0) -> dict:
        _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
        raise TypeError("drift_rows() takes 2 positional arguments but 3 were given")

    guarded = mcp_module._stale_guard(translate_drift)

    answer = guarded(root=str(tmp_path), filter="Задач")

    assert answer["stale"]["reason"] == "sources" and "TypeError: drift_rows()" in answer["error"]
    assert answer["stale"]["ran"] is True
    assert _after_xbsl(_words(answer["cli"])) == [
        "translate", str(tmp_path), "--drift", "--filter", "Задач", "--limit", "50",
        "--format", "json"]


def test_a_pull_between_releases_is_refused_before_the_tool_runs(mcp_module, disk, tmp_path):
    """The number on disk stays and the code changes: the tool does not start on a mix.

    Found only after a failure, such a change let the first call run half on the old code and
    half on the new; the refusal says `ran: false`, so the supervisor answers the same call from
    a new process, and without it the refusal names the CLI command as for a new version.
    """
    freshness.remember()
    called = []

    def lint_paths(paths: list[str], root: str | None = None, select: list[str] | None = None):
        called.append(paths)
        return {"diagnostics": []}

    guarded = mcp_module._stale_guard(lint_paths)
    assert guarded(paths=["a.xbsl"], root=str(tmp_path)) == {"diagnostics": []}
    _pull(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")

    answer = guarded(paths=["acme/Задачи.xbsl"], root=str(tmp_path), select=["code"])

    assert called == [["a.xbsl"]]  # the second call never started
    assert list(answer) == ["error", "cli", "stale"]
    stale = answer["stale"]
    assert (stale["reason"], stale["ran"], stale["on_disk"]) == ("sources", False, freshness.__version__)
    assert stale["fingerprint"] and stale["location"]
    assert "номер версии тот же" in answer["error"] and "Перезапустите сервер MCP" in answer["error"]
    assert _after_xbsl(_words(answer["cli"])) == [
        str(tmp_path / "acme" / "Задачи.xbsl"), "--select", "code", "--format", "json"]
    (event,) = _stale_events()
    assert event["reason"] == "sources" and event["tool"] == "lint_paths"


def _count_walks(monkeypatch) -> list:
    walks: list = []
    real = freshness._code_rows
    monkeypatch.setattr(freshness, "_code_rows",
                        lambda root, marks=None: walks.append(root) or real(root, marks))
    return walks


def test_the_check_before_a_call_walks_the_files_only_when_a_folder_moved(disk, monkeypatch):
    """A stat of the folders per call; the files are walked when git replaced one of them."""
    monkeypatch.setattr(freshness, "_SOURCES_TTL", 3600.0)
    freshness.remember()
    walks = _count_walks(monkeypatch)
    for _call in range(3):
        assert freshness.call_state() is None
    assert walks == []

    _pull(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    found = freshness.call_state()

    assert found["reason"] == "sources" and len(walks) == 1
    assert freshness.call_state() == found and len(walks) == 1  # the verdict stands, unwalked


def test_a_file_rewritten_in_place_is_found_once_the_last_walk_is_old(disk, monkeypatch):
    """An editor leaves the folder's time as it was: the next walk is due by the clock."""
    monkeypatch.setattr(freshness, "_SOURCES_TTL", 3600.0)
    freshness.remember()
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    assert freshness.engine_sources_state() is None  # the last walk is fresh: no new one

    freshness._engine.walked -= 3600.0

    assert freshness.engine_sources_state()["reason"] == "sources"


def test_a_package_moved_aside_is_no_verdict_before_a_call(disk):
    """self-update renames the package aside for a moment: a call then is not refused."""
    freshness.remember()
    aside = disk.with_name("xbsl-aside")
    disk.rename(aside)
    try:
        assert freshness.call_state() is None and freshness.engine_sources_state() is None
    finally:
        aside.rename(disk)
    assert freshness.call_state() is None


def test_version_info_names_a_change_of_the_sources(mcp_module, disk):
    freshness.remember()
    _pull(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")

    info = mcp_module.version_info()

    assert info["engine_on_disk"] == info["engine"]
    assert info["stale"]["reason"] == "sources" and "Перезапустите" in info["stale"]["message"]


def test_the_journal_hears_the_state_once_not_per_call(mcp_module, disk, tmp_path):
    _update(disk, "9.9.9")
    for _call in range(3):
        _lint(mcp_module)(paths=[str(tmp_path)])
    (event,) = _stale_events()
    assert event["reason"] == "version" and event["on_disk"] == "9.9.9"
    assert event["tool"] == "lint_paths" and event["loaded"] == freshness.__version__


def test_a_failure_after_the_sources_moved_is_explained(mcp_module, disk):
    """A pull that lands while the call runs: the failure names the restart."""
    freshness.remember()
    pulled = []

    def broken(**kwargs):
        if pulled:
            _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
        raise TypeError("register_row() takes 3 positional arguments but 4 were given")

    guarded = mcp_module._stale_guard(broken)
    with pytest.raises(TypeError):  # the same code on disk: a failure is a failure
        guarded()

    pulled.append(True)
    answer = guarded()

    assert "TypeError: register_row()" in answer["error"] and "номер версии тот же" in answer["error"]
    assert answer["stale"]["reason"] == "sources"
    (event,) = _stale_events()
    assert event["reason"] == "sources" and "register_row" in event["error"]


def test_a_rule_crash_noted_during_a_call_reaches_the_journal(mcp_module, disk):
    freshness.remember()

    def crashing():
        _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
        return {"crash": _crash()}

    answer = mcp_module._stale_guard(crashing)()

    assert "Перезапустите процесс" in answer["crash"]
    (event,) = _stale_events()
    assert event["reason"] == "sources" and event["tool"] == "crashing"


def test_mcp_log_tells_the_stale_state_in_words(capsys):
    mcpjournal.record("stale", reason="version", loaded="0.117.0", on_disk="0.118.0",
                      tool="lint_paths")
    mcpjournal.record("stale", reason="sources", loaded="0.118.0", on_disk="0.118.0",
                      tool="meta_add_field", error="TypeError: boom")
    assert cli.main(["mcp-log"]) == 0
    out = capsys.readouterr().out
    assert "сервер 0.117.0 увидел на диске 0.118.0 (вызов lint_paths)" in out
    assert "исходники движка 0.118.0 на диске изменились" in out and "ошибка: TypeError: boom" in out

    i18n.set_lang("en")
    try:
        assert cli.main(["mcp-log", "--json"]) == 0
        printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert [event["reason"] for event in printed] == ["version", "sources"]
        assert cli.main(["mcp-log"]) == 0
        english = capsys.readouterr().out
    finally:
        i18n.set_lang("ru")
    assert "server 0.117.0 saw 0.118.0 on disk" in english
    assert not any("а" <= char <= "я" for char in english.lower().replace(
        str(mcpjournal.journal_path()).lower(), ""))


def test_the_messages_speak_english_too(disk):
    _update(disk, "9.9.9")
    i18n.set_lang("en")
    try:
        found = freshness.version_state()
        texts = [freshness.describe(found), _crash(),
                 i18n.t("freshness.refusal", state=freshness.describe(found)),
                 i18n.t("freshness.failure", state=freshness.describe(found), error="TypeError")]
    finally:
        i18n.set_lang("ru")
    assert "Restart" in texts[1] and "restart" in texts[2].lower()
    for text in texts:
        assert not any("а" <= char <= "я" for char in text.lower()), text
