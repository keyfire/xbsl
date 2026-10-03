"""Progress counts completed lint and index work, and permits callback cancellation."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from xbsl import dataset, engine, indexer
from xbsl.diagnostics import Diagnostic, Severity


def _rule(rule_id, scope, func, *, title="", mapper=None, enabled=True):
    return engine.RuleInfo(
        rule_id, title or rule_id, "A", scope, Severity.WARNING, func,
        enabled_by_default=enabled, mapper=mapper,
    )


@pytest.fixture
def isolated_rules(monkeypatch):
    monkeypatch.setattr(engine, "RULES", [])
    monkeypatch.setattr(engine, "SEVERITY_OVERRIDES", {})
    monkeypatch.setattr(engine, "_overrides_applied", True)
    monkeypatch.setattr(dataset, "recheck_data", lambda: None)
    monkeypatch.setattr(dataset, "begin_pass", lambda: None)
    return engine.RULES


def test_lint_progress_counts_completed_files_and_mapped_project_rules(isolated_rules):
    sources = [engine.load_text(name, "") for name in ("First.xbsl", "Context.yaml", "Last.xbsl")]
    trace = []

    def file_rule(src):
        trace.append(("checked", src.rel))
        return []

    def project_rule(items):
        trace.append(("project sources", len(items)))
        return []

    def mapper(src):
        trace.append(("mapped", src.rel))
        return src.rel

    def reduce_rule(facts):
        trace.append(("reduced", tuple(facts)))
        return []

    isolated_rules.extend([
        _rule("test/file", "file", file_rule),
        _rule("test/project", "project", project_rule, title="Project references"),
        _rule("test/mapped", "project", reduce_rule, title="Mapped references", mapper=mapper),
        _rule("test/disabled", "project", project_rule, enabled=False),
    ])
    events = []

    def progress(*event):
        events.append(event)
        trace.append(event)

    assert engine.run_sources(sources, context={Path("Context.yaml")}, progress=progress) == []
    assert events == [
        ("file", 0, 2, ""),
        ("file", 1, 2, "First.xbsl"),
        ("file", 2, 2, "Last.xbsl"),
        ("project", 0, 2, ""),
        ("project", 0, 2, "Project references"),
        ("project", 1, 2, "Project references"),
        ("project", 1, 2, "Mapped references"),
        ("project", 2, 2, "Mapped references"),
    ]
    assert trace == [
        events[0], ("checked", "First.xbsl"), events[1],
        ("checked", "Last.xbsl"), events[2], events[3],
        events[4], ("project sources", 3), events[5], events[6],
        ("mapped", "First.xbsl"), ("mapped", "Context.yaml"), ("mapped", "Last.xbsl"),
        ("reduced", ("First.xbsl", "Context.yaml", "Last.xbsl")), events[7],
    ]


@pytest.mark.parametrize("scopes, expected", [
    (("file",), [("file", 0, 1, ""), ("file", 1, 1, "Sample.xbsl")]),
    (("project",), [
        ("project", 0, 1, ""), ("project", 0, 1, "test/project"),
        ("project", 1, 1, "test/project"),
    ]),
    ((), []),
])
def test_lint_progress_respects_scopes_and_rule_selection(isolated_rules, scopes, expected):
    isolated_rules.extend([
        _rule("test/file", "file", lambda src: []),
        _rule("test/project", "project", lambda items: []),
        _rule("other/project", "project", lambda items: []),
    ])
    events = []
    engine.run_sources(
        [engine.load_text("Sample.xbsl", "")], scopes=scopes,
        select={"test"}, progress=lambda *event: events.append(event),
    )
    assert events == expected


def test_lint_empty_phases_report_zero_work(isolated_rules):
    events = []
    engine.run_sources([], progress=lambda *event: events.append(event))
    assert events == [("file", 0, 0, ""), ("project", 0, 0, "")]


@pytest.mark.parametrize("phase, completed", [("file", 0), ("file", 1), ("project", 0), ("project", 1)])
def test_lint_callback_failure_propagates_and_stops_work(isolated_rules, phase, completed):
    checked = []
    projected = []

    def file_rule(src):
        checked.append(src.rel)
        return []

    def project_rule(items):
        projected.append(len(items))
        return []

    isolated_rules.extend([
        _rule("test/file", "file", file_rule),
        _rule("test/one", "project", project_rule),
        _rule("test/two", "project", project_rule),
    ])
    cancellation = RuntimeError("cancel progress")

    def progress(actual_phase, actual_completed, total, detail):
        if (actual_phase, actual_completed) == (phase, completed):
            raise cancellation

    with pytest.raises(RuntimeError) as caught:
        engine.run_sources(
            [engine.load_text("First.xbsl", ""), engine.load_text("Last.xbsl", "")],
            progress=progress,
        )
    assert caught.value is cancellation
    assert len(checked) == (completed if phase == "file" else 2)
    assert len(projected) == (completed if phase == "project" else 0)


@pytest.mark.parametrize("mapped", [False, True])
def test_lint_callback_can_cancel_before_project_rule_starts(isolated_rules, mapped):
    attempted = []

    def mapper(src):
        attempted.append("map")
        return src.rel

    def project_rule(items):
        attempted.append("rule")
        return []

    isolated_rules.append(_rule(
        "test/project", "project", project_rule, title="Project label",
        mapper=mapper if mapped else None,
    ))
    cancellation = RuntimeError("cancel before rule")
    events = []

    def progress(phase, completed, total, detail):
        events.append((phase, completed, total, detail))
        if detail == "Project label":
            raise cancellation

    with pytest.raises(RuntimeError) as caught:
        engine.run_sources(
            [engine.load_text("Sample.xbsl", "")], scopes=("project",), progress=progress,
        )
    assert caught.value is cancellation
    assert attempted == []
    assert events == [("project", 0, 1, ""), ("project", 0, 1, "Project label")]


def test_lint_progress_preserves_diagnostics_and_rule_crashes(isolated_rules):
    def findings(src):
        yield Diagnostic(src.rel, 1, 1, "test/finding", Severity.WARNING, "Example finding")

    def broken(src):
        raise ValueError("example rule failure")

    isolated_rules.extend([
        _rule("test/finding", "file", findings),
        _rule("test/broken", "file", broken),
    ])
    sources = [engine.load_text("Sample.xbsl", "")]
    baseline = engine.run_sources(sources)
    events = []
    assert engine.run_sources(sources, progress=lambda *event: events.append(event)) == baseline
    assert len(baseline) == 2
    assert events == [
        ("file", 0, 1, ""), ("file", 1, 1, "Sample.xbsl"), ("project", 0, 0, ""),
    ]


@pytest.fixture
def index_without_platform_data(monkeypatch):
    # Hook tests exercise real discovery, loading and YAML attempts without a platform catalog.
    monkeypatch.setattr(indexer, "_file_local_type_decls", lambda src: [])
    monkeypatch.setattr(indexer, "parse", lambda src: (SimpleNamespace(members=[]), []))
    monkeypatch.setattr(indexer, "_method_decls", lambda src: [])
    monkeypatch.setattr(indexer, "_manager_member_types", lambda: {})
    monkeypatch.setattr(indexer, "_kind_facet_members", lambda: {})
    monkeypatch.setattr(indexer, "tokens", lambda src: [])


def _index_sources(root):
    for name, text in {
        "First.xbsl": "method Example()\n;\n",
        "Broken.xbsl": "method (\n",
        "Query.xbql": "SELECT 1\n",
        "Broken.yaml": "broken: [\n",
        "Empty.yaml": "",
        "ignored.txt": "",
    }.items():
        (root / name).write_text(text, encoding="utf-8")
    hidden = root / ".cache"
    hidden.mkdir()
    (hidden / "Ignored.xbsl").write_text("", encoding="utf-8")


def test_index_progress_reports_only_after_final_reference_processing(
    index_without_platform_data, monkeypatch, tmp_path,
):
    _index_sources(tmp_path)
    completed = []
    events = []
    module_refs = indexer._module_references
    handler_refs = indexer._handler_references

    def module_references(src, *args):
        result = module_refs(src, *args)
        completed.append(src.path.name)
        return result

    def handler_references(src, *args):
        result = handler_refs(src, *args)
        completed.append(src.path.name)
        return result

    monkeypatch.setattr(indexer, "_module_references", module_references)
    monkeypatch.setattr(indexer, "_handler_references", handler_references)

    def progress(phase, count, total, detail):
        assert phase == "index"
        assert count == len(completed)
        assert total == 5
        if count:
            assert detail == completed[-1]
        events.append((phase, count, total, detail))

    baseline = indexer.build_index(tmp_path)
    completed.clear()
    assert indexer.build_index(tmp_path, progress=progress) == baseline
    assert events == [
        ("index", 0, 5, ""),
        ("index", 1, 5, "Broken.xbsl"),
        ("index", 2, 5, "First.xbsl"),
        ("index", 3, 5, "Query.xbql"),
        ("index", 4, 5, "Broken.yaml"),
        ("index", 5, 5, "Empty.yaml"),
    ]


@pytest.mark.parametrize("source_name", [None, "Single.yaml", "Single.xbsl", "Single.xbql"])
def test_index_progress_handles_empty_project_and_single_source(
    index_without_platform_data, tmp_path, source_name,
):
    root = tmp_path
    if source_name:
        root = tmp_path / source_name
        root.write_text("", encoding="utf-8")
    events = []
    indexer.build_index(root, progress=lambda *event: events.append(event))
    total = int(source_name is not None)
    expected = [("index", 0, total, "")]
    if source_name:
        expected.append(("index", 1, 1, source_name))
    assert events == expected


@pytest.mark.parametrize("cancel_at", [0, 1])
def test_index_callback_failure_propagates_and_stops_work(
    index_without_platform_data, monkeypatch, tmp_path, cancel_at,
):
    _index_sources(tmp_path)
    loaded = []
    completed = []
    load_source = indexer.load
    module_refs = indexer._module_references

    def load(path):
        loaded.append(path.name)
        return load_source(path)

    def module_references(src, *args):
        result = module_refs(src, *args)
        completed.append(src.path.name)
        return result

    monkeypatch.setattr(indexer, "load", load)
    monkeypatch.setattr(indexer, "_module_references", module_references)
    cancellation = RuntimeError("cancel indexing")

    def progress(phase, count, total, detail):
        if count == cancel_at:
            raise cancellation

    with pytest.raises(RuntimeError) as caught:
        indexer.build_index(tmp_path, progress=progress)
    assert caught.value is cancellation
    assert len(loaded) == (5 if cancel_at else 0)
    assert len(completed) == cancel_at
