"""A rule that crashes is one diagnostic, not the end of the run.

0.36.0 showed why this matters: a single rule walked a parser node through `vars()`, the
compiled wheel has no `__dict__` there, and every lint of every project died with a traceback
instead of reporting the other 109 rules. A rule is code like any other - its bug belongs in
the report, under the id of the rule at fault.
"""

import pytest

from xbsl import engine
from xbsl.diagnostics import Diagnostic, Severity

_BOOM = "code/тестовое-падение"
_QUIET = "code/тестовое-тихое"


@pytest.fixture(autouse=True)
def _restore_registry():
    """The registry is global state - the temporary rules of a test leave with it."""
    rules_before = list(engine.RULES)
    yield
    engine.RULES[:] = rules_before


def _sources():
    return [
        engine.load_text("acme/П/О/Первый.xbsl", "метод А()\n;\n"),
        engine.load_text("acme/П/О/Второй.xbsl", "метод Б()\n;\n"),
    ]


def _finding(src) -> Diagnostic:
    return Diagnostic(src.rel, 1, 1, _QUIET, Severity.WARNING, "нашлось")


def _register_quiet_file_rule():
    engine.rule(_QUIET, "тихое", "C")(lambda src: [_finding(src)])


def test_a_crashing_file_rule_does_not_stop_the_others():
    _register_quiet_file_rule()

    @engine.rule(_BOOM, "падение", "C")
    def _boom(src):
        raise TypeError("vars() argument must have __dict__ attribute")

    sources = _sources()
    diags = engine.run_sources(sources, select={_BOOM, _QUIET})
    crashes = [d for d in diags if d.rule_id == _BOOM]
    assert [d.rule_id for d in diags if d.rule_id == _QUIET] == [_QUIET] * 2
    # one per file: the rule is asked about each of them separately
    assert len(crashes) == 2 and {d.path for d in crashes} == {s.rel for s in sources}
    assert crashes[0].severity is Severity.ERROR
    assert "TypeError" in crashes[0].message and "__dict__" in crashes[0].message


def test_a_crashing_mapper_leaves_the_other_files_to_the_rule():
    seen: list[str] = []

    def _mapper(src):
        if src.rel.endswith("Первый.xbsl"):
            raise RuntimeError("мэппер упал")
        return {"rel": src.rel}

    @engine.rule(_BOOM, "падение", "D", scope="project", mapper=_mapper)
    def _reduce(facts):
        seen.extend(sorted(facts))
        return []

    first, second = _sources()
    diags = engine.run_sources([first, second], select={_BOOM})
    assert seen == [second.rel]  # the surviving file still reached the rule
    assert len(diags) == 1 and diags[0].path == first.rel
    assert "мэппер упал" in diags[0].message


def test_a_crashing_project_rule_is_anchored_to_the_first_source():
    @engine.rule(_BOOM, "падение", "D", scope="project")
    def _boom(sources):
        raise ValueError("правило упало")

    sources = _sources()
    diags = engine.run_sources(sources, select={_BOOM})
    assert len(diags) == 1 and diags[0].rule_id == _BOOM
    assert diags[0].path == sources[0].rel


def test_the_crash_is_silenced_by_ignoring_the_rule():
    """The finding carries the id of the failing rule, so the usual escape hatch works:
    the rule does not run at all, and nothing is left to report."""
    _register_quiet_file_rule()

    @engine.rule(_BOOM, "падение", "C")
    def _boom(src):
        raise TypeError("падение")

    diags = engine.run_sources(_sources(), select={_BOOM, _QUIET}, ignore={_BOOM})
    assert [d.rule_id for d in diags] == [_QUIET] * 2


def test_a_missing_dataset_keeps_its_own_report():
    """The environment is not a rule bug: a dataset failure breaks every rule at once and is
    reported once, by the caller ("Element data error: ..."), instead of a hundred findings."""
    from xbsl.dataset import DatasetError

    @engine.rule(_BOOM, "падение", "C")
    def _boom(src):
        raise DatasetError("данных нет")

    with pytest.raises(DatasetError):
        engine.run_sources(_sources(), select={_BOOM})


def test_a_healthy_run_is_untouched():
    _register_quiet_file_rule()
    diags = engine.run_sources(_sources(), select={_QUIET})
    assert [d.rule_id for d in diags] == [_QUIET] * 2
