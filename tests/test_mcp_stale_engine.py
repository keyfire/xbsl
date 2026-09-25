"""A server whose engine was replaced on disk says so instead of crashing its rules.

Caught live on 24.09.2026: an MCP server started on 0.117.0 kept running while its editable
checkout moved to 0.118.0, and `lint_paths` answered with four crashes of rules -
`TypeError: ProjectCatalog.register_row() takes 3 positional arguments but 4 were given` - the
modules loaded later were new, the catalog in memory was old. The CLI over the same files was
clean. Now every tool but version_info compares the version on disk with the loaded one and
refuses with the cure named; a failure under the same number is checked against the fingerprint
of the sources taken at start; a crashed rule names the restart in its own report.

No Element data and no live server: the package on disk is a folder of the test's own.
"""

from __future__ import annotations

import json
import os

import pytest

from xbsl import cli, engine, freshness, i18n, mcpjournal


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
    monkeypatch.setattr(freshness, "_noted", None)
    monkeypatch.setattr(freshness, "_SOURCES_TTL", 0.0)
    return folder


def _update(folder, version: str) -> None:
    (folder / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")


def _touch(path, text: str) -> None:
    """Rewrite a file and move its time on, as a pull does, whatever the clock resolution."""
    path.write_text(text, encoding="utf-8")
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


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
    assert freshness.sources_state() == {
        "reason": "sources", "loaded": freshness.__version__, "on_disk": freshness.__version__}


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

    assert set(answer) == {"error", "stale"}
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


def test_the_journal_hears_the_state_once_not_per_call(mcp_module, disk, tmp_path):
    _update(disk, "9.9.9")
    for _call in range(3):
        _lint(mcp_module)(paths=[str(tmp_path)])
    (event,) = _stale_events()
    assert event["reason"] == "version" and event["on_disk"] == "9.9.9"
    assert event["tool"] == "lint_paths" and event["loaded"] == freshness.__version__


def test_a_failure_after_the_sources_moved_is_explained(mcp_module, disk):
    freshness.remember()

    def broken(**kwargs):
        raise TypeError("register_row() takes 3 positional arguments but 4 were given")

    guarded = mcp_module._stale_guard(broken)
    with pytest.raises(TypeError):  # the same code on disk: a failure is a failure
        guarded()

    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")
    answer = guarded()

    assert "TypeError: register_row()" in answer["error"] and "номер версии тот же" in answer["error"]
    assert answer["stale"]["reason"] == "sources"
    (event,) = _stale_events()
    assert event["reason"] == "sources" and "register_row" in event["error"]


def test_a_rule_crash_noted_during_a_call_reaches_the_journal(mcp_module, disk):
    freshness.remember()
    _touch(disk / "rules" / "catalog.py", "def register_row(a, b, c):\n    pass\n")

    answer = mcp_module._stale_guard(lambda: {"crash": _crash()})()

    assert "Перезапустите процесс" in answer["crash"]
    (event,) = _stale_events()
    assert event["reason"] == "sources" and event["tool"] == "<lambda>"


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
