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
    def fake_index(root, *, progress=None):
        paths = lsp.indexer._discover(root)
        if progress is not None:
            progress("index", 0, len(paths), "")
            for completed, path in enumerate(paths, 1):
                progress("index", completed, len(paths), path.name)
        return {}

    monkeypatch.setattr(lsp.indexer, "build_index", fake_index)
    server = lsp._make_server()
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    manager = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(manager, "features", manager)
    published = {}
    progress_events = []
    trace = []

    def notify(method, params):
        if method == "$/progress":
            progress_events.append((params.token, params.value))
            trace.append((params.value.kind, params.token))

    monkeypatch.setattr(server.lsp, "notify", notify)

    def key(path):
        return lsp._doc_key(Path(path), "")

    def uri(path):
        return uris.from_fs_path(str(path))

    def publish(document_uri, diagnostics=None, *args, **kwargs):
        published[key(uris.to_fs_path(document_uri))] = [d.code for d in diagnostics or []]
        trace.append(("publish", document_uri))

    monkeypatch.setattr(server, "publish_diagnostics", publish)
    monkeypatch.setattr(server, "show_message_log", lambda *args, **kwargs: None)

    def reindex(params=None):
        assert "xbsl/reindexProject" in features
        return features["xbsl/reindexProject"](params)

    def open_document(path, text):
        server.workspace.put_text_document(lsp.lsp.TextDocumentItem(
            uri=uri(path), language_id="xbsl", version=1, text=text,
        ))

    try:
        yield SimpleNamespace(
            reindex=reindex, relint=lambda: features["xbsl/relint"](None),
            server=server, features=features, published=published, key=key, uri=uri,
            open=open_document, original_index=original_index,
            progress=progress_events, trace=trace,
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


def _stage(value):
    import re

    match = re.search(r"(?:Этап|Stage) (\d+)/8", value.message or "")
    return int(match.group(1)) if match else None


def test_reindex_reports_actual_stages_and_ends_after_publication(tmp_path, editor):
    module = tmp_path / "Module.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")

    answer = editor.reindex({"workDoneToken": "manual"})

    assert answer == {"ok": True, "files": 1, "diagnostics": 1}
    values = [value for token, value in editor.progress if token == "manual"]
    assert values and values[0].kind == "begin" and values[-1].kind == "end"
    reports = [value for value in values if value.kind == "report"]
    stages = [_stage(value) for value in reports]
    assert set(stages) == set(range(1, 9))
    assert stages == sorted(stages)
    assert reports[-1].percentage == 100 and _stage(reports[-1]) == 8
    assert all(value.percentage is None for value in reports[:-1])
    assert any("1/1" in (value.message or "") for value in reports if _stage(value) == 4)
    assert editor.trace.index(("publish", editor.uri(module))) < editor.trace.index(("end", "manual"))
    assert "manual" not in editor.server.progress.tokens


def test_reindex_progress_waits_for_diagnostic_publication(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(WITH_FINDING, encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    original_publish = editor.server.publish_diagnostics

    def publish(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original_publish(*args, **kwargs)

    monkeypatch.setattr(editor.server, "publish_diagnostics", publish)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(editor.reindex, {"workDoneToken": "manual"})
        try:
            assert entered.wait(5)
            assert not future.done()
            assert not any(value.kind == "end" or value.percentage == 100
                           for _token, value in editor.progress if value.kind != "end")
            assert not any(value.kind == "end" for _token, value in editor.progress)
        finally:
            release.set()
        assert future.result(timeout=5)["ok"] is True
    assert editor.progress[-1][1].kind == "end"


def test_reindex_progress_ends_on_failure_without_claiming_completion(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")

    def fail(*args, **kwargs):
        raise OSError("synthetic check failure")

    monkeypatch.setattr(lsp.engine, "run_sources", fail)

    answer = editor.reindex({"workDoneToken": "failed"})

    assert answer["ok"] is False
    values = [value for token, value in editor.progress if token == "failed"]
    assert values and values[0].kind == "begin" and values[-1].kind == "end"
    assert not any(getattr(value, "percentage", None) == 100 for value in values)
    assert not any(_stage(value) == 8 for value in values)
    assert "failed" not in editor.server.progress.tokens


def test_reindex_progress_tokens_are_isolated_and_optional(tmp_path, editor):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    assert editor.reindex({"workDoneToken": 0})["ok"] is True
    first = len(editor.progress)
    assert first > 0 and all(token == 0 for token, _value in editor.progress)
    assert editor.reindex({"workDoneToken": "second"})["ok"] is True
    assert all(token == "second" for token, _value in editor.progress[first:])
    second = len(editor.progress)
    assert editor.reindex()["ok"] is True
    assert len(editor.progress) == second
    assert not editor.server.progress.tokens


def test_reindex_reports_waiting_heartbeats_before_lock_acquisition(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    monkeypatch.setattr(lsp, "_PROJECT_PROGRESS_INTERVAL", 0.01)
    repeated = threading.Event()
    original_notify = editor.server.lsp.notify
    waiting_reports = []

    def notify(method, params):
        original_notify(method, params)
        if method == "$/progress" and params.value.kind == "report" and _stage(params.value) == 1:
            waiting_reports.append(params.value)
            if len(waiting_reports) >= 3:
                repeated.set()

    monkeypatch.setattr(editor.server.lsp, "notify", notify)
    lsp.STATE.project_lock.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(editor.reindex, {"workDoneToken": "waiting"})
        try:
            assert repeated.wait(5), "waiting must report activity while another pass holds the lock"
            assert not future.done()
        finally:
            lsp.STATE.project_lock.release()
        assert future.result(timeout=5)["ok"] is True


def test_reindex_canceled_while_waiting_ends_progress_and_does_not_release_another_pass_lock(tmp_path, editor):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    started = threading.Event()
    original_notify = editor.server.lsp.notify

    def notify(method, params):
        original_notify(method, params)
        if method == "$/progress" and params.value.kind == "begin":
            started.set()

    editor.server.lsp.notify = notify
    lsp.STATE.project_lock.acquire()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(editor.reindex, {"workDoneToken": "canceled"})
        try:
            assert started.wait(5)
            editor.server.progress.tokens["canceled"].cancel()
            answer = future.result(timeout=5)
            assert answer["ok"] is False and answer["canceled"] is True
            assert lsp.STATE.project_lock.locked()
        finally:
            lsp.STATE.project_lock.release()
    values = [value for token, value in editor.progress if token == "canceled"]
    assert values[-1].kind == "end"
    assert not any(getattr(value, "percentage", None) == 100 for value in values)
    assert "canceled" not in editor.server.progress.tokens


def test_reindex_file_progress_is_throttled_but_stage_completion_is_immediate(tmp_path, editor, monkeypatch):
    from types import SimpleNamespace

    for index in range(100):
        (tmp_path / f"Module{index:03}.xbsl").write_text(CLEAN, encoding="utf-8")
    clock = [0.0]
    monkeypatch.setattr(lsp, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(lsp, "_PROJECT_PROGRESS_INTERVAL", 0.2)

    def run(sources, *, progress=None, **kwargs):
        if progress is not None:
            progress("file", 0, len(sources), "")
            for completed, source in enumerate(sources, 1):
                clock[0] += 0.01
                progress("file", completed, len(sources), source.rel)
            if "project" in kwargs.get("scopes", ("file", "project")):
                progress("project", 0, 0, "")
        return []

    monkeypatch.setattr(lsp.engine, "run_sources", run)

    assert editor.reindex({"workDoneToken": "throttled"})["ok"] is True

    files = [value for _token, value in editor.progress if value.kind == "report" and _stage(value) == 4]
    assert 2 <= len(files) <= 8
    assert "0/100" in files[0].message and "100/100" in files[-1].message
    assert editor.progress[-1][1].kind == "end"


def test_reindex_progress_messages_follow_the_selected_language(tmp_path, editor):
    from xbsl import i18n

    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    i18n.set_lang("en")

    assert editor.reindex({"workDoneToken": "english"})["ok"] is True

    values = [value for token, value in editor.progress if token == "english"]
    assert "Reindex" in values[0].title
    reports = [value for value in values if value.kind == "report"]
    assert any("Stage 4/8" in value.message and "remaining" in value.message for value in reports)


def test_reindex_cancellation_between_stages_ends_without_full_completion(tmp_path, editor, monkeypatch):
    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    original_notify = editor.server.lsp.notify
    canceled = []

    def notify(method, params):
        original_notify(method, params)
        if method == "$/progress" and params.value.kind == "report" and _stage(params.value) == 3 and not canceled:
            editor.server.progress.tokens["stage-cancel"].cancel()
            canceled.append(True)

    monkeypatch.setattr(editor.server.lsp, "notify", notify)

    answer = editor.reindex({"workDoneToken": "stage-cancel"})

    assert answer["ok"] is False and answer["canceled"] is True
    values = [value for token, value in editor.progress if token == "stage-cancel"]
    assert values[-1].kind == "end"
    assert not any(getattr(value, "percentage", None) == 100 for value in values)
    assert "stage-cancel" not in editor.server.progress.tokens
    assert not lsp.STATE.project_lock.locked()


def test_a_long_project_rule_reports_its_human_title_before_it_finishes(tmp_path, editor, monkeypatch):
    from xbsl import engine
    from xbsl.diagnostics import Severity

    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()
    shown = threading.Event()
    title = "Synthetic project rule"
    original_notify = editor.server.lsp.notify
    monkeypatch.setattr(lsp, "_PROJECT_PROGRESS_INTERVAL", 0.01)

    def rule(sources):
        entered.set()
        assert release.wait(5)
        return []

    custom = engine.RuleInfo("synthetic/project", title, "A", "project", Severity.WARNING, rule)
    monkeypatch.setattr(engine, "active_rules", lambda *args: [custom])

    def notify(method, params):
        original_notify(method, params)
        if method == "$/progress" and params.value.kind == "report" and _stage(params.value) == 5:
            if title in params.value.message and "0/1" in params.value.message:
                shown.set()

    monkeypatch.setattr(editor.server.lsp, "notify", notify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(editor.reindex, {"workDoneToken": "rule-start"})
        try:
            assert entered.wait(5)
            assert shown.wait(5), "the rule title must be reported while the rule is still running"
            assert not future.done()
        finally:
            release.set()
        assert future.result(timeout=5)["ok"] is True


def test_cancel_after_publication_keeps_uri_tracked_for_the_next_clear(tmp_path, editor, monkeypatch):
    module = tmp_path / "Module.xbsl"
    module.write_text(WITH_FINDING, encoding="utf-8")
    original_publish = editor.server.publish_diagnostics

    def publish(uri, diagnostics=None, *args, **kwargs):
        original_publish(uri, diagnostics, *args, **kwargs)
        editor.server.progress.tokens["publish-cancel"].cancel()

    monkeypatch.setattr(editor.server, "publish_diagnostics", publish)
    answer = editor.reindex({"workDoneToken": "publish-cancel"})
    assert answer["ok"] is False and answer["canceled"] is True
    assert editor.published[editor.key(module)] == [TRAILING]
    assert editor.key(module) in lsp.STATE.published

    monkeypatch.setattr(editor.server, "publish_diagnostics", original_publish)
    module.write_text(CLEAN, encoding="utf-8")
    assert editor.reindex() == {"ok": True, "files": 1, "diagnostics": 0}
    assert editor.published[editor.key(module)] == []


def test_rule_counters_precede_a_long_title_in_the_progress_message(tmp_path, editor, monkeypatch):
    from xbsl import engine
    from xbsl.diagnostics import Severity

    (tmp_path / "Module.xbsl").write_text(CLEAN, encoding="utf-8")
    title = "Synthetic project rule with a very long description " * 4
    custom = engine.RuleInfo("synthetic/project", title, "A", "project", Severity.WARNING, lambda sources: [])
    monkeypatch.setattr(engine, "active_rules", lambda *args: [custom])
    assert editor.reindex({"workDoneToken": "long-title"})["ok"] is True
    messages = [value.message for _, value in editor.progress if value.kind == "report" and title in value.message]
    assert messages
    assert all(message.index("/1") < message.index(title) for message in messages)
