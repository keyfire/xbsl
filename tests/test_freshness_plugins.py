"""A long-lived server tells when the plugins on disk are not the ones it loaded.

Caught on 25.09.2026: after a plugin upgrade under a running MCP server, `lint_paths` named the
version it had loaded while the CLI and CI ran the new one - two rule sets over one tree, and no
word about it in the answer. The version of each plugin is now read by the walk that loads it; a
server that took its start (`freshness.remember`) compares that with the plugins installed now,
and walks the installed distributions only when a folder they live in changed. The MCP tools
keep answering on the loaded rules and carry `stale`; the language server, which has no answer
to put a warning into, says it once per state. The language server takes the fingerprint of the
sources at start as well, and the fingerprint covers the code of the plugins.

No Element data, no real plugin and no live server: the entry points and their distributions
are stubs, the folders are the test's own.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbsl import cli, freshness, mcpjournal, plugins


class _Dist:
    """A distribution the way importlib.metadata shows one: metadata, a version, its folder."""

    def __init__(self, name: str, version: str, folder: Path):
        self.metadata = {"Name": name}
        self.version = version
        self._folder = folder

    def locate_file(self, path):
        return self._folder / path


class _EP:
    def __init__(self, name: str, group: str, value: str, dist: _Dist):
        self.name, self.group, self.value, self.dist = name, group, value, dist

    def load(self):
        return {}


class _Installed:
    """`entry_points` over a set the test changes: asked for a group, or for everything."""

    def __init__(self, *eps):
        self.eps = list(eps)

    def __call__(self, group=None):
        return self if group is None else [ep for ep in self.eps if ep.group == group]

    def select(self, group):
        return self(group=group)


def _settle(folder: Path) -> None:
    """The folder as an install left it a minute ago: its time is not a fresh one."""
    past = time.time_ns() - 60_000_000_000
    os.utime(folder, ns=(past, past))


def _bump(folder: Path) -> None:
    """An install in the folder: a new entry, and a time of its own.

    The time goes BACK ten seconds from the last one: two installs a test makes in a row may
    fall into one tick of the clock, and a time in the past is one the folder has settled at.
    """
    before = folder.stat().st_mtime_ns
    (folder / f"entry-{len(list(folder.iterdir()))}").mkdir()
    os.utime(folder, ns=(before, before - 10_000_000_000))


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """One plugin installed into a folder of the test's own, loaded as the engine loads it."""
    monkeypatch.delenv("XBSL_NO_PLUGINS", raising=False)
    folder = tmp_path / "site-packages"
    folder.mkdir()
    environment = tmp_path / "environment"
    environment.mkdir()
    ep = _EP("acme", plugins.SEVERITY_GROUP, "acme_rules:levels",
             _Dist("acme-rules", "1.0.0", folder))
    installed = _Installed(ep)
    monkeypatch.setattr(plugins, "entry_points", installed)
    monkeypatch.setattr(freshness.sysconfig, "get_paths", lambda: {
        "purelib": str(environment), "platlib": str(environment)})
    for name in ("_started", "_checked", "_noted", "_marks", "_plugins_found"):
        monkeypatch.setattr(freshness, name, None)
    monkeypatch.setattr(freshness, "_unsettled", False)
    monkeypatch.setattr(freshness, "_SOURCES_TTL", 0.0)
    _settle(folder)
    _settle(environment)
    plugins.installed()  # the walk that loads the plugins reads their versions
    return SimpleNamespace(folder=folder, environment=environment, ep=ep, installed=installed)


def _upgrade(site, version: str) -> None:
    """What pip does: the metadata on disk says the new version, the folder changes."""
    site.ep.dist = _Dist("acme-rules", version, site.folder)
    _bump(site.folder)


def _count_walks(monkeypatch) -> list:
    walks: list = []
    real = plugins.on_disk
    monkeypatch.setattr(plugins, "on_disk", lambda: walks.append(1) or real())
    return walks


# -- plugins: loaded and on disk ------------------------------------------------------------


def test_the_loaded_version_is_the_one_read_at_load_not_the_disk(site):
    _upgrade(site, "2.0.0")
    assert plugins.installed() == [{"name": "acme-rules", "version": "1.0.0"}]
    assert plugins.on_disk() == [{"name": "acme-rules", "version": "2.0.0"}]


def test_the_folders_of_the_loaded_plugins_are_known(site):
    assert plugins.installed_folders() == [str(site.folder)]
    watched = {os.path.normcase(folder) for folder in freshness._watched()}
    assert watched == {os.path.normcase(str(site.environment)), os.path.normcase(str(site.folder))}


def test_the_files_of_the_imported_plugin_modules_are_named(site, monkeypatch, tmp_path):
    module = tmp_path / "acme_rules.py"
    module.write_text("levels = {}\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "acme_rules", SimpleNamespace(__file__=str(module)))
    assert plugins.module_files() == [str(module)]


def test_no_plugins_means_nothing_on_disk_either(site, monkeypatch):
    monkeypatch.setenv("XBSL_NO_PLUGINS", "1")
    assert plugins.on_disk() == []


# -- the check ------------------------------------------------------------------------------


def test_a_process_that_took_no_start_judges_no_plugins(site):
    """The CLI lives for one run: the disk it reads is the disk it loaded."""
    _upgrade(site, "2.0.0")
    assert freshness.plugins_state() is None


def test_a_check_walks_nothing_while_the_folders_stand(site, monkeypatch):
    freshness.remember()
    walks = _count_walks(monkeypatch)
    for _call in range(3):
        assert freshness.plugins_state() is None
    assert walks == []


def test_an_upgrade_under_the_process_is_found_by_one_walk(site, monkeypatch):
    freshness.remember()
    walks = _count_walks(monkeypatch)
    _upgrade(site, "2.0.0")

    found = freshness.plugins_state()

    assert found == {
        "reason": "plugins", "loaded": "acme-rules 1.0.0", "on_disk": "acme-rules 2.0.0",
        "changed": [{"name": "acme-rules", "loaded": "1.0.0", "on_disk": "2.0.0"}],
    }
    assert freshness.plugins_state() == found and len(walks) == 1
    assert freshness.state() == found
    assert freshness.describe(found) == (
        "надстройки на диске сменились после запуска этого процесса: acme-rules 1.0.0 -> 2.0.0")


def test_a_folder_still_changing_is_walked_again_until_it_settles(site, monkeypatch):
    """An install writes several entries within one tick of the clock: a walk made in the
    middle of it would keep seeing half an install if its verdict stood."""
    freshness.remember()
    walks = _count_walks(monkeypatch)
    now = time.time_ns()
    (site.folder / "half-written").mkdir()
    os.utime(site.folder, ns=(now, now))

    freshness.plugins_state()
    freshness.plugins_state()
    assert len(walks) == 2  # the folder changed just now: its verdict is taken again

    os.utime(site.folder, ns=(now, now - 10 * freshness._SETTLE_NS))  # the install is over
    freshness.plugins_state()
    freshness.plugins_state()
    assert len(walks) == 3  # one more walk sees it settled, and that verdict stands


def test_a_removed_and_a_new_plugin_are_both_named(site):
    freshness.remember()
    site.installed.eps = [_EP("beta", plugins.RULES_GROUP, "beta_rules",
                              _Dist("beta-rules", "0.1", site.environment))]
    _bump(site.environment)

    found = freshness.plugins_state()

    assert found["changed"] == [
        {"name": "acme-rules", "loaded": "1.0.0", "on_disk": ""},
        {"name": "beta-rules", "loaded": "", "on_disk": "0.1"},
    ]
    assert freshness.describe(found).endswith("acme-rules 1.0.0 -> нет, beta-rules нет -> 0.1")


def test_the_loaded_version_back_on_disk_clears_the_state(site):
    freshness.remember()
    _upgrade(site, "2.0.0")
    assert freshness.plugins_state() is not None
    _upgrade(site, "1.0.0")
    assert freshness.plugins_state() is None


def test_a_walk_that_fails_is_no_verdict(site, monkeypatch):
    freshness.remember()

    def broken():
        raise OSError("the folder is being rewritten")

    monkeypatch.setattr(plugins, "on_disk", broken)
    _bump(site.folder)
    assert freshness.plugins_state() is None


def test_a_rule_crash_after_a_plugin_upgrade_names_the_restart(site):
    from xbsl import engine

    freshness.remember()
    _upgrade(site, "2.0.0")
    message = engine._crash_diag("code/missing-return", "Задачи.xbsl", TypeError("boom")).message
    assert "acme-rules 1.0.0 -> 2.0.0" in message and "Перезапустите процесс" in message
    assert freshness.take_noted()["reason"] == "plugins"


def test_the_fingerprint_follows_the_plugin_code(site, monkeypatch, tmp_path):
    module = tmp_path / "acme_rules.py"
    module.write_text("levels = {}\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "acme_rules", SimpleNamespace(__file__=str(module)))
    freshness.remember()
    assert freshness.sources_state() is None

    module.write_text("levels = {'code/missing-return': 'off'}\n", encoding="utf-8")
    stat = module.stat()
    os.utime(module, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))

    assert freshness.sources_state()["reason"] == "sources"
    assert "надстроек" in freshness.describe(freshness.sources_state())


def test_the_plugin_messages_speak_english_too(site):
    from xbsl import i18n

    freshness.remember()
    _upgrade(site, "2.0.0")
    found = freshness.plugins_state()
    i18n.set_lang("en")
    try:
        texts = [freshness.describe(found),
                 i18n.t("freshness.plugins-warning", state=freshness.describe(found)),
                 i18n.t("freshness.editor", state=freshness.describe(found))]
    finally:
        i18n.set_lang("ru")
    assert texts[0].endswith("started: acme-rules 1.0.0 -> 2.0.0") and "Restart" in texts[1]
    for text in texts:
        assert not any("а" <= char <= "я" for char in text.lower()), text


# -- the MCP server -------------------------------------------------------------------------


def _stale_events():
    return [event for event in mcpjournal.read() if event["event"] == "stale"]


def test_a_tool_runs_on_the_loaded_plugins_and_says_so_first(site, mcp_module):
    freshness.remember()
    _upgrade(site, "2.0.0")
    guarded = mcp_module._stale_guard(lambda: {"diagnostics": [], "summary": {"files": 1}})

    answer = guarded()
    guarded()

    assert list(answer) == ["stale", "diagnostics", "summary"]
    stale = answer["stale"]
    assert stale["reason"] == "plugins" and stale["location"]
    assert stale["changed"] == [{"name": "acme-rules", "loaded": "1.0.0", "on_disk": "2.0.0"}]
    assert "Перезапустите сервер MCP xbsl" in stale["message"]
    (event,) = _stale_events()
    assert event["reason"] == "plugins" and event["on_disk"] == "acme-rules 2.0.0"


def test_an_answer_that_is_a_list_stays_a_list(site, mcp_module):
    freshness.remember()
    _upgrade(site, "2.0.0")
    assert mcp_module._stale_guard(lambda: [{"id": "code/missing-return"}])() == [
        {"id": "code/missing-return"}]
    assert [event["reason"] for event in _stale_events()] == ["plugins"]


def test_a_tool_on_the_plugins_it_loaded_carries_no_stale_record(site, mcp_module):
    freshness.remember()
    assert mcp_module._stale_guard(lambda: {"ok": True})() == {"ok": True}


def test_version_info_names_the_loaded_plugins_and_the_installed_ones(site, mcp_module):
    freshness.remember()
    _upgrade(site, "2.0.0")

    info = mcp_module.version_info()

    assert info["plugins"] == [{"name": "acme-rules", "version": "1.0.0"}]
    assert info["plugins_on_disk"] == [{"name": "acme-rules", "version": "2.0.0"}]
    assert info["stale"]["reason"] == "plugins" and "Перезапустите" in info["stale"]["message"]


def test_mcp_log_tells_the_plugins_state_in_words(capsys):
    mcpjournal.record("stale", reason="plugins", loaded="acme-rules 1.0.0",
                      on_disk="acme-rules 2.0.0", tool="lint_paths",
                      changed=[{"name": "acme-rules", "loaded": "1.0.0", "on_disk": "2.0.0"}])
    assert cli.main(["mcp-log"]) == 0
    out = capsys.readouterr().out
    assert "надстройки на диске сменились после запуска сервера: acme-rules 1.0.0 -> 2.0.0 " \
           "(вызов lint_paths)" in out


# -- the language server --------------------------------------------------------------------


class _RightAway:
    """A timer that runs its function on `start()`: the debounce made synchronous."""

    def __init__(self, *args, target=None, **kwargs):
        self.function = target if target is not None else args[1]
        self.daemon = kwargs.get("daemon", False)

    def start(self):
        self.function()

    def cancel(self):
        pass


def test_the_language_server_tells_the_editor_once_per_state(tmp_path, monkeypatch):
    pytest.importorskip("pygls", reason="the LSP handlers need the [lsp] extra")
    import threading

    from pygls import uris
    from pygls.workspace import Workspace

    from xbsl import lsp

    saved = dict(vars(lsp.STATE))
    lsp.STATE.__init__()
    lsp.STATE.select = {"whitespace/trailing"}
    monkeypatch.setattr(lsp, "threading", SimpleNamespace(
        Timer=_RightAway, Thread=_RightAway, Lock=threading.Lock))
    states = iter([
        None,
        {"reason": "sources", "loaded": "1.0", "on_disk": "1.0"},
        {"reason": "sources", "loaded": "1.0", "on_disk": "1.0"},
        {"reason": "version", "loaded": "1.0", "on_disk": "1.1"},
    ])
    monkeypatch.setattr(freshness, "state", lambda sources=False: next(states))
    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    shown, logged = [], []
    monkeypatch.setattr(server, "show_message", lambda text, kind=None: shown.append((text, kind)))
    monkeypatch.setattr(server, "show_message_log", lambda text, *args: logged.append(text))
    monkeypatch.setattr(server, "publish_diagnostics", lambda *args, **kwargs: None)
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    path = tmp_path / "Задачи.yaml"
    path.write_text("Имя: Задачи\n", encoding="utf-8")
    uri = uris.from_fs_path(str(path))
    server.workspace.put_text_document(lsp.lsp.TextDocumentItem(
        uri=uri, language_id="yaml", version=1, text=path.read_text(encoding="utf-8")))
    try:
        for _edit in range(4):
            features[lsp.lsp.TEXT_DOCUMENT_DID_OPEN](
                SimpleNamespace(text_document=SimpleNamespace(uri=uri)))
    finally:
        vars(lsp.STATE).clear()
        vars(lsp.STATE).update(saved)

    assert [kind for _text, kind in shown] == [lsp.lsp.MessageType.Warning] * 2
    assert "номер версии тот же" in shown[0][0] and "1.0 -> 1.1" in shown[1][0]
    assert all(text.startswith("xbsl-lsp: ") and "Перезапустите сервер языка" in text
               for text, _kind in shown)
    assert logged == [text for text, _kind in shown]


def test_the_language_server_takes_the_start_before_it_serves(monkeypatch):
    pytest.importorskip("pygls", reason="the LSP handlers need the [lsp] extra")
    from xbsl import lsp

    order: list[str] = []
    saved = dict(vars(lsp.STATE))
    monkeypatch.setattr(sys, "argv", ["xbsl-lsp"])
    monkeypatch.setattr(freshness, "remember", lambda: order.append("remember"))
    monkeypatch.setattr(lsp, "_make_server", lambda: SimpleNamespace(
        start_io=lambda: order.append("serve")))
    try:
        lsp.main()
    finally:
        vars(lsp.STATE).clear()
        vars(lsp.STATE).update(saved)
    assert order == ["remember", "serve"]
