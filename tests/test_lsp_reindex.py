"""Awaited project reindexing through the LSP request."""

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from xbsl import lsp

TRAILING = "whitespace/trailing"
CLEAN = "метод Before()\n    возврат\n;\n"
WITH_FINDING = "метод Before()   \n    возврат\n;\n"


class _PendingTimer:
    """A debounce timer the test can inspect and fire without sleeping."""

    def __init__(self, interval, function):
        self.function = function
        self.cancelled = False
        self.daemon = False

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.function()


@pytest.fixture
def editor(tmp_path, monkeypatch):
    pytest.importorskip("pygls", reason="the LSP handlers need the [lsp] extra")
    from pygls import uris
    from pygls.workspace import Workspace

    saved = dict(vars(lsp.STATE))
    lsp.STATE.__init__()
    lsp.STATE.root = tmp_path
    lsp.STATE.select = {TRAILING}
    background = []

    def make_thread(*args, **kwargs):
        worker = threading.Thread(*args, **kwargs)
        background.append(worker)
        return worker

    monkeypatch.setattr(lsp, "threading", SimpleNamespace(
        Timer=_PendingTimer, Thread=make_thread, Lock=threading.Lock,
    ))
    original_index = lsp.indexer.build_index
    monkeypatch.setattr(lsp.indexer, "build_index", lambda root: {})
    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    manager = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(manager, "features", manager)
    published = {}

    def key(path):
        return lsp._doc_key(Path(path), "")

    def uri(path):
        return uris.from_fs_path(str(path))

    def publish(document_uri, diagnostics=None, *args, **kwargs):
        published[key(uris.to_fs_path(document_uri))] = [d.code for d in diagnostics or []]

    monkeypatch.setattr(server, "publish_diagnostics", publish)
    monkeypatch.setattr(server, "show_message_log", lambda *args, **kwargs: None)

    def reindex():
        assert "xbsl/reindexProject" in features
        return features["xbsl/reindexProject"](None)

    def open_document(path, text):
        server.workspace.put_text_document(lsp.lsp.TextDocumentItem(
            uri=uri(path), language_id="xbsl", version=1, text=text,
        ))

    try:
        yield SimpleNamespace(
            reindex=reindex, relint=lambda: features["xbsl/relint"](None),
            server=server, features=features, published=published, key=key, uri=uri,
            open=open_document, original_index=original_index,
        )
    finally:
        if lsp.STATE.project_timer is not None:
            lsp.STATE.project_timer.cancel()
        for worker in background:
            worker.join(timeout=5)
            assert not worker.is_alive(), "the test must finish every background pass"
        vars(lsp.STATE).clear()
        vars(lsp.STATE).update(saved)


@pytest.mark.needs_data
def test_reindex_rereads_disk_rebuilds_index_and_replaces_diagnostics(tmp_path, editor, monkeypatch):
    monkeypatch.setattr(lsp.indexer, "build_index", editor.original_index)
    module = tmp_path / "Module.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")

    assert editor.reindex() == {"ok": True, "files": 1, "diagnostics": 1}
    assert lsp.STATE.lookup.method("Module", "Before") is not None
    assert editor.published[editor.key(module)] == [TRAILING]

    module.write_text(CLEAN.replace("Before", "After"), encoding="utf-8")

    assert editor.reindex() == {"ok": True, "files": 1, "diagnostics": 0}
    assert lsp.STATE.lookup.method("Module", "Before") is None
    assert lsp.STATE.lookup.method("Module", "After") is not None
    assert editor.published[editor.key(module)] == []


def test_reindex_clears_findings_for_a_removed_file(tmp_path, editor):
    module = tmp_path / "Removed.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")
    assert editor.reindex()["diagnostics"] == 1

    module.unlink()

    assert editor.reindex() == {"ok": True, "files": 0, "diagnostics": 0}
    assert editor.published[editor.key(module)] == []


def test_reindex_cancels_a_pending_debounce_and_runs_one_pass(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    built = []
    monkeypatch.setattr(lsp.indexer, "build_index", lambda root: built.append(root) or {})
    assert editor.relint() == {"ok": True}
    timer = lsp.STATE.project_timer

    assert editor.reindex() == {"ok": True, "files": 1, "diagnostics": 0}
    assert timer.cancelled
    assert lsp.STATE.project_timer is None
    timer.fire()
    assert built == [tmp_path]


def test_reindex_waits_for_the_active_pass_then_reads_a_fresh_snapshot(tmp_path, editor, monkeypatch):
    module = tmp_path / "Module.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    original_run = lsp.engine.run_sources
    snapshots = []

    def run(sources, **kwargs):
        if sources:
            snapshots.append(sources[0].text.replace("\r\n", "\n"))
            if len(snapshots) == 1:
                entered.set()
                assert release.wait(5), "the test must release the active background pass"
        return original_run(sources, **kwargs)

    monkeypatch.setattr(lsp.engine, "run_sources", run)
    assert editor.relint() == {"ok": True}
    lsp.STATE.project_timer.fire()
    assert entered.wait(5), "the background pass must reach the source check"
    started = threading.Event()

    def request():
        started.set()
        return editor.reindex()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(request)
        try:
            assert started.wait(5)
            assert not future.done()
            module.write_text(CLEAN, encoding="utf-8")
        finally:
            release.set()
        assert future.result(timeout=5) == {"ok": True, "files": 1, "diagnostics": 0}

    assert snapshots == [WITH_FINDING, CLEAN]
    assert editor.published[editor.key(module)] == []


def test_reindex_keeps_dirty_buffers_and_open_documents_outside_the_root(tmp_path, editor):
    root = tmp_path / "src"
    root.mkdir()
    dirty = root / "Dirty.xbsl"
    dirty.write_text(WITH_FINDING, encoding="utf-8")
    outside = tmp_path / "Outside.xbsl"
    outside.write_text(CLEAN, encoding="utf-8")
    lsp.STATE.root = root
    editor.open(dirty, CLEAN)
    editor.open(outside, CLEAN)
    dirty_key = editor.key(dirty)
    outside_key = editor.key(outside)
    lsp.STATE.dirty.add(dirty_key)
    lsp.STATE.published = {dirty_key: editor.uri(dirty), outside_key: editor.uri(outside)}
    editor.published.update({dirty_key: ["buffer/dirty"], outside_key: ["buffer/outside"]})

    assert editor.reindex() == {"ok": True, "files": 1, "diagnostics": 1}
    assert editor.published == {dirty_key: ["buffer/dirty"], outside_key: ["buffer/outside"]}


def test_reindex_without_a_project_root_returns_an_error(editor):
    lsp.STATE.root = None

    answer = editor.reindex()

    assert answer["ok"] is False
    assert answer["files"] == 0 and answer["diagnostics"] == 0
    assert answer["error"]


def test_reindex_reports_failure_and_releases_the_project_lock(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("synthetic read failure")

    monkeypatch.setattr(lsp.engine, "run_sources", fail)

    answer = editor.reindex()

    assert answer["ok"] is False and "synthetic read failure" in answer["error"]
    assert lsp.STATE.project_lock.acquire(blocking=False)
    lsp.STATE.project_lock.release()


def test_reindex_reports_an_index_failure_after_completing_diagnostics(tmp_path, editor, monkeypatch):
    module = tmp_path / "Module.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")

    def fail(root):
        raise OSError("synthetic index failure")

    monkeypatch.setattr(lsp.indexer, "build_index", fail)

    answer = editor.reindex()

    assert answer["ok"] is False and answer["error"]
    assert answer["files"] == 1 and answer["diagnostics"] == 1
    assert editor.published[editor.key(module)] == [TRAILING]


def test_reindex_is_registered_for_threaded_dispatch(editor):
    from pygls.protocol.json_rpc import is_thread_function

    assert is_thread_function(editor.features["xbsl/reindexProject"])


def test_reindex_responds_after_diagnostics_are_published(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(WITH_FINDING, encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    original_publish = editor.server.publish_diagnostics

    def publish(*args, **kwargs):
        entered.set()
        assert release.wait(5), "the test must release diagnostic publication"
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(editor.server, "publish_diagnostics", publish)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(editor.reindex)
        try:
            assert entered.wait(5), "the pass must reach diagnostic publication"
            assert not future.done()
        finally:
            release.set()
        assert future.result(timeout=5) == {"ok": True, "files": 1, "diagnostics": 1}
