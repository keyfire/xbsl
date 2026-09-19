"""`--summary` and `--compare`: a run as counts, and the difference with the run saved before.

Comparing the findings before and after a change on a few projects is everyday work on the
rules. It went through `--format json` and a script, and the text of every finding travelled
along - several hundred characters each, tens of thousands of lines over a set of projects.
The unit tests below build the diagnostics by hand and need no Element data; the tests that
run the linter itself are marked `needs_data`.
"""

from __future__ import annotations

import json

import pytest

from xbsl import cli, i18n, report, rundiff
from xbsl.diagnostics import Diagnostic, Severity


def _d(path, line, rule="style/x", message="m", col=1, severity=Severity.WARNING):
    return Diagnostic(path=str(path), line=line, col=col, rule_id=rule, severity=severity,
                      message=message)


def _run(findings, corpora=("Задачи",), *, rules=None, selection=None, lang="ru", checked=3):
    """A run built from its keyed findings: (path given, file, line, col, rule, message)."""
    if rules is None:
        rules = {f[4]: True for f in findings}
    return rundiff.Run(
        corpora=list(corpora), findings=sorted(findings), checked=checked, lang=lang,
        selection=selection or {"select": None, "ignore": None, "enable": None}, rules=rules,
    )


def _f(file="Шаги.xbsl", line=1, rule="code/a", message="m", corpus="Задачи", col=1):
    return (corpus, file, line, col, rule, message)


# --- the counts -----------------------------------------------------------------------------


def test_rule_table_counts_files_and_findings_per_rule():
    """The row of a rule: its files and its findings, ordered as breakdown() orders by_rule."""
    diags = [
        _d("a.xbsl", 1, "code/a"), _d("a.xbsl", 2, "code/a"), _d("b.xbsl", 1, "code/a"),
        _d("b.xbsl", 1, "code/b"), _d("c.xbsl", 1, "code/c"),
    ]
    assert report.rule_table(diags) == [("code/a", 2, 3), ("code/b", 1, 1), ("code/c", 1, 1)]
    assert report.rule_table([]) == []


def test_the_summary_is_a_table_and_a_line_of_totals():
    diags = [_d("a.xbsl", 1, "code/a"), _d("a.xbsl", 2, "code/a"), _d("b.xbsl", 1, "code/b")]
    lines = rundiff.summary_lines(diags, checked=7)
    assert lines[0].split() == ["правило", "файлов", "находок"]
    assert lines[1].split() == ["code/a", "1", "2"]
    assert lines[2].split() == ["code/b", "1", "1"]
    assert lines[3] == "Находок: 3; правил с находками: 2; файлов с находками: 2 из 7"
    assert len(lines) == 4


def test_a_clean_run_is_one_line_of_totals():
    assert rundiff.summary_lines([], checked=5) == [
        "Находок: 0; правил с находками: 0; файлов с находками: 0 из 5"
    ]


def test_the_totals_name_what_the_baseline_suppressed():
    lines = rundiff.summary_lines([_d("a.xbsl", 1)], checked=1, suppressed=4)
    assert lines[-1].endswith("; погашено списком принятых: 4")


# --- the key of a finding -------------------------------------------------------------------


def test_a_finding_is_keyed_by_the_path_given_and_the_file_under_it(tmp_path):
    corpus = tmp_path / "Задачи"
    (corpus / "Шаги").mkdir(parents=True)
    source = corpus / "Шаги" / "Шаг.xbsl"
    source.write_text("", encoding="utf-8")
    other = tmp_path / "Отчёты.xbsl"
    other.write_text("", encoding="utf-8")

    keys = rundiff.findings(
        [_d(source, 3, col=5), _d(other, 1)], [str(corpus), str(other)],
    )
    assert keys == [
        (corpus.as_posix(), "Шаги/Шаг.xbsl", 3, 5, "style/x", "m"),
        (other.as_posix(), "", 1, 1, "style/x", "m"),
    ]


def test_a_relative_path_keys_the_same_from_two_checkouts(tmp_path, monkeypatch):
    """`xbsl demo` run from two worktrees names the same findings: the path as it was given
    and the file under it, not the absolute place of the checkout."""
    seen = []
    for checkout in ("main", "branch"):
        root = tmp_path / checkout
        (root / "demo" / "Задачи").mkdir(parents=True)
        (root / "demo" / "Задачи" / "Задачи.xbsl").write_text("", encoding="utf-8")
        monkeypatch.chdir(root)
        seen.append(rundiff.findings([_d("demo/Задачи/Задачи.xbsl", 2)], ["demo/"]))
    assert seen[0] == seen[1] == [("demo", "Задачи/Задачи.xbsl", 2, 1, "style/x", "m")]


# --- the comparison -------------------------------------------------------------------------


def test_identical_runs_have_no_changes():
    findings = [_f(line=1), _f(line=2, rule="code/b")]
    changes = rundiff.compare(_run(findings), _run(findings))
    assert (changes.appeared, changes.disappeared, changes.skipped) == ([], [], [])


def test_a_moved_finding_disappears_at_the_old_place_and_appears_at_the_new():
    changes = rundiff.compare(_run([_f(line=1)]), _run([_f(line=2)]))
    assert changes.disappeared == [_f(line=1)]
    assert changes.appeared == [_f(line=2)]


def test_repeated_findings_are_counted_one_by_one():
    """Two equal findings at one place are two: losing one of them is a change."""
    changes = rundiff.compare(_run([_f(), _f()]), _run([_f()]))
    assert changes.disappeared == [_f()]
    assert changes.appeared == []


def test_a_path_only_one_run_checked_is_not_compared():
    """Leaving a project out of the command line is not the same as its findings going away."""
    saved = _run([_f(), _f(corpus="Шаги"), _f(corpus="Шаги", line=2)],
                 corpora=["Задачи", "Шаги"])
    now = _run([_f(), _f(corpus="Отчёты")], corpora=["Задачи", "Отчёты"])
    changes = rundiff.compare(saved, now)
    assert (changes.appeared, changes.disappeared) == ([], [])
    assert changes.skipped == [
        ("rundiff.skipped-paths-gone", ["Шаги"], 2),
        ("rundiff.skipped-paths-new", ["Отчёты"], 1),
    ]


def test_rules_selected_differently_are_not_compared():
    """A narrower --select is not the findings of the other rules going away."""
    rules = {"code/a": True, "code/b": True}
    saved = _run([_f(), _f(rule="code/b")], rules=rules)
    now = _run([_f()], rules={"code/a": True, "code/b": False},
               selection={"select": ["code/a"], "ignore": None, "enable": None})
    changes = rundiff.compare(saved, now)
    assert (changes.appeared, changes.disappeared) == ([], [])
    assert changes.skipped == [("rundiff.skipped-rules-gone", ["code/b"], 1)]


def test_left_out_rules_are_named_by_their_findings_first():
    """A full run compared with a narrow one leaves out two hundred rules; the few with
    findings are the ones to see, not the first five of the alphabet."""
    saved = _run([_f(rule="code/c", line=n) for n in (1, 2, 3)] + [_f(rule="code/b")],
                 rules={"code/a": True, "code/b": True, "code/c": True, "code/d": True})
    now = _run([], rules={"code/a": False, "code/b": False, "code/c": False, "code/d": True},
               selection={"select": ["code/d"], "ignore": None, "enable": None})
    assert rundiff.compare(saved, now).skipped == [
        ("rundiff.skipped-rules-gone", ["code/c", "code/b", "code/a"], 4),
    ]


def test_a_rule_the_engine_turned_on_is_compared():
    """With the same flags a different rule set comes from the engine itself: a rule new to
    it, or one it now turns on by default, is exactly the change being measured."""
    saved = _run([_f()], rules={"code/a": True, "code/b": False})
    now = _run([_f(), _f(rule="code/b"), _f(rule="code/new")],
               rules={"code/a": True, "code/b": True, "code/new": True})
    changes = rundiff.compare(saved, now)
    assert changes.appeared == [_f(rule="code/b"), _f(rule="code/new")]
    assert changes.skipped == []


def test_a_rule_the_new_engine_does_not_know_is_compared_even_under_other_flags():
    saved = _run([_f(), _f(rule="code/gone")], rules={"code/a": True, "code/gone": True})
    now = _run([_f()], rules={"code/a": True},
               selection={"select": None, "ignore": ["style"], "enable": None})
    changes = rundiff.compare(saved, now)
    assert changes.disappeared == [_f(rule="code/gone")]
    assert changes.skipped == []


# --- the saved run --------------------------------------------------------------------------


def test_the_saved_run_reads_back(tmp_path):
    target = tmp_path / "запуск.json"
    run = _run([_f(), _f(line=7, message="ёмкий текст")], corpora=["Задачи", "Шаги"])
    rundiff.save(target, run, None)
    assert rundiff.load(target, "ru") == run
    assert not target.read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_changes_are_saved_ahead_of_the_findings_one_per_line(tmp_path):
    """Past the listing limit the terminal points at the file, so the changes open it."""
    target = tmp_path / "запуск.json"
    run = _run([_f(line=2), _f(line=3)])
    changes = rundiff.compare(_run([_f(line=1)]), run)
    rundiff.save(target, run, changes)
    text = target.read_text(encoding="utf-8")
    assert text.index('"changes"') < text.index('"findings"')
    rows = [line.strip().rstrip(",") for line in text.splitlines()]
    assert '["Задачи", "Шаги.xbsl", 1, 1, "code/a", "m"]' in rows
    data = json.loads(text)
    assert data["changes"]["disappeared"] == [list(_f(line=1))]
    assert data["changes"]["appeared"] == [list(_f(line=2)), list(_f(line=3))]


def test_a_missing_or_empty_file_means_nothing_to_compare_yet(tmp_path):
    assert rundiff.load(tmp_path / "нет.json", "ru") is None
    empty = tmp_path / "пустой.json"
    empty.write_text("", encoding="utf-8")
    assert rundiff.load(empty, "ru") is None


@pytest.mark.parametrize("content", [
    '{"meta": {"tool": "xbsl", "format": 1}, "files": {}}',  # a baseline
    "not JSON",
    '{"meta": {"tool": "xbsl", "kind": "run", "format": 1}, "findings": [["x"]]}',
])
def test_a_file_that_is_not_a_saved_run_is_refused(tmp_path, content):
    """Writing the run over some other file would destroy it - a baseline, most likely."""
    target = tmp_path / ".xbsllint-baseline"
    target.write_text(content, encoding="utf-8")
    with pytest.raises(rundiff.RunStateError, match="не похож на запуск"):
        rundiff.load(target, "ru")
    with pytest.raises(rundiff.RunStateError):
        rundiff.load(tmp_path, "ru")  # a directory


def test_a_run_saved_in_another_language_is_refused(tmp_path):
    """The text of a finding is part of its key: every one of them would differ."""
    target = tmp_path / "запуск.json"
    rundiff.save(target, _run([_f()], lang="en"), None)
    with pytest.raises(rundiff.RunStateError, match="--lang en"):
        rundiff.load(target, "ru")


# --- the text of a comparison ---------------------------------------------------------------


def test_no_changes_is_one_line():
    run = _run([_f()])
    lines = rundiff.changes_lines(rundiff.compare(run, run), [_d("Задачи/Шаги.xbsl", 1, "code/a")],
                                  path="запуск.json", checked=3)
    assert lines == [
        "Без изменений по сравнению с запуск.json. Находок: 1; правил с находками: 1; "
        "файлов с находками: 1 из 3"
    ]


def test_changes_name_the_rule_and_list_the_findings():
    saved = _run([_f(line=1), _f(rule="code/b", line=5)])
    now = _run([_f(line=2), _f(rule="code/b", line=5)])
    diags = [_d("Задачи/Шаги.xbsl", 2, "code/a"), _d("Задачи/Шаги.xbsl", 5, "code/b")]
    lines = rundiff.changes_lines(rundiff.compare(saved, now), diags, path="запуск.json",
                                  checked=3)
    assert lines[0].split() == ["правило", "файлов", "находок", "появилось", "исчезло"]
    assert lines[1].split() == ["code/a", "1", "1", "1", "1"]
    assert lines[2] == "- Задачи/Шаги.xbsl:1:1: [code/a] m"
    assert lines[3] == "+ Задачи/Шаги.xbsl:2:1: [code/a] m"
    assert lines[4].startswith("По сравнению с запуск.json: появилось 1, исчезло 1. Находок: 2;")
    assert len(lines) == 5


def test_past_the_limit_the_list_stays_in_the_file():
    limit = report.COMPACT_FINDINGS_LIMIT
    now = _run([_f(line=n) for n in range(1, limit + 2)])
    lines = rundiff.changes_lines(rundiff.compare(_run([]), now), [], path="запуск.json",
                                  checked=3)
    assert not any(line.startswith("+ ") for line in lines)
    assert f"Изменений больше {limit}: весь список – в запуск.json, раздел changes" in lines


def test_the_parts_left_out_of_the_comparison_are_named():
    saved = _run([_f(corpus="Шаги")], corpora=["Задачи", "Шаги"])
    lines = rundiff.changes_lines(rundiff.compare(saved, _run([])), [], path="запуск.json",
                                  checked=3)
    assert lines[0] == ("Не сравнивались пути, которых нет в этом запуске: Шаги; "
                        "их находок в сохранённом: 1")
    assert lines[1].startswith("Без изменений по сравнению с запуск.json.")


def test_a_long_list_of_names_is_cut():
    rules = {f"code/r{n}": True for n in range(8)}
    saved = _run([], rules=rules)
    now = _run([], rules={name: name == "code/r0" for name in rules},
               selection={"select": ["code/r0"], "ignore": None, "enable": None})
    (key, names, count), = rundiff.compare(saved, now).skipped
    assert (key, len(names), count) == ("rundiff.skipped-rules-gone", 7, 0)
    lines = rundiff.changes_lines(rundiff.compare(saved, now), [], path="запуск.json",
                                  checked=3)
    assert "code/r1, code/r2, code/r3, code/r4, code/r5 и ещё 2;" in lines[0]


def test_the_english_edition():
    i18n.set_lang("en")
    saved = _run([_f(line=1)])
    now = _run([_f(line=2)])
    lines = rundiff.changes_lines(rundiff.compare(saved, now), [_d("Задачи/Шаги.xbsl", 2, "code/a")],
                                  path="run.json", checked=3)
    assert lines[0].split() == ["rule", "files", "findings", "appeared", "disappeared"]
    assert lines[-1] == ("Against run.json: 1 appeared, 1 disappeared. Findings: 1; "
                         "rules with findings: 1; files with findings: 1 of 3")
    assert rundiff.summary_lines([], checked=2) == [
        "Findings: 0; rules with findings: 0; files with findings: 0 of 2"
    ]


# --- the command line -----------------------------------------------------------------------


def _source(tmp_path, body="метод Ф(): Число\n    возврат 1  \n;\n"):
    project = tmp_path / "Задачи"
    project.mkdir(exist_ok=True)
    source = project / "Шаги.xbsl"
    source.write_text(body, encoding="utf-8")
    return project, source


@pytest.mark.needs_data
def test_summary_prints_counts_instead_of_findings(tmp_path, capsys):
    project, _ = _source(tmp_path)
    code = cli.main([str(project), "--select", "whitespace/trailing", "--summary"])
    cap = capsys.readouterr()
    assert code == 0
    assert cap.out.splitlines() == [
        "правило              файлов  находок",
        "whitespace/trailing       1        1",
        "Находок: 1; правил с находками: 1; файлов с находками: 1 из 1",
    ]
    assert "Проверено файлов" not in cap.err  # the totals are in the report itself
    assert "Набор проверки" in cap.err


@pytest.mark.needs_data
def test_compare_saves_the_run_and_then_prints_only_the_difference(tmp_path, capsys):
    project, source = _source(tmp_path)
    state = tmp_path / "запуск.json"
    argv = [str(project), "--select", "whitespace/trailing", "--compare", str(state)]

    cli.main(argv)
    out = capsys.readouterr().out.splitlines()
    assert out[1].split() == ["whitespace/trailing", "1", "1"]
    assert out[-1] == f"Сравнивать пока не с чем: запуск сохранён в {state}"
    assert state.is_file()

    cli.main(argv)
    out = capsys.readouterr().out.splitlines()
    assert out == [f"Без изменений по сравнению с {state}. Находок: 1; правил с находками: 1; "
                   "файлов с находками: 1 из 1"]

    source.write_text("метод Ф(): Число\n    возврат 1  \n;  \n", encoding="utf-8")
    cli.main(argv)
    out = capsys.readouterr().out.splitlines()
    assert out[1].split() == ["whitespace/trailing", "1", "2", "1", "0"]
    assert out[2].startswith(f"+ {project.as_posix()}/Шаги.xbsl:3:")
    assert out[-1].startswith(f"По сравнению с {state}: появилось 1, исчезло 0.")


@pytest.mark.needs_data
@pytest.mark.parametrize("flags", [["--format", "json"], ["--format", "codeclimate"],
                                   ["--write-baseline", "принятые.json"]])
def test_compare_refuses_a_second_report_and_keeps_the_file(tmp_path, capsys, flags):
    project, _ = _source(tmp_path)
    state = tmp_path / "запуск.json"
    state.write_text("", encoding="utf-8")
    code = cli.main([str(project), "--compare", str(state), *flags])
    assert code == 2
    assert "не сочетаются с" in capsys.readouterr().err
    assert state.read_text(encoding="utf-8") == ""


@pytest.mark.needs_data
def test_compare_refuses_a_foreign_file_before_the_run(tmp_path, capsys):
    project, _ = _source(tmp_path)
    baseline = tmp_path / ".xbsllint-baseline"
    baseline.write_text('{"meta": {"tool": "xbsl", "format": 1}, "files": {}}', encoding="utf-8")
    code = cli.main([str(project), "--no-baseline", "--compare", str(baseline)])
    assert code == 2
    assert "не похож на запуск" in capsys.readouterr().err
    assert json.loads(baseline.read_text(encoding="utf-8"))["files"] == {}


@pytest.mark.needs_data
def test_compare_speaks_english(tmp_path, capsys):
    project, _ = _source(tmp_path)
    state = tmp_path / "run.json"
    argv = [str(project), "--select", "whitespace/trailing", "--compare", str(state),
            "--lang", "en"]
    cli.main(argv)
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"Nothing to compare with yet: the run is saved to {state}")
    cli.main(argv)
    assert capsys.readouterr().out.startswith(f"No changes against {state}. Findings: 1;")
