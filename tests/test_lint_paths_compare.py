"""`lint_paths(compare=FILE)`: the difference with the previous call, as data.

The CLI `--compare` keeps a run in a file and prints what changed since the one before it.
Agents check projects through MCP more often than in a terminal, and the tool had no such
mode: the difference was worked out from two full answers. `compare` takes the same file under
the same rules - the first call saves the run, every next one compares with it and saves over
it - and the answer carries the changes as records, not as lines of text. The unit tests of the
record need no Element data; the calls of the tool itself are marked `needs_data`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xbsl import cli, report, rundiff
from xbsl.diagnostics import Diagnostic, Severity

_ONE_TRAILING = "метод Ф(): Число\n    возврат 1  \n;\n"  # trailing whitespace on line 2
_TWO_TRAILING = "метод Ф(): Число\n    возврат 1  \n;  \n"  # and on line 3
_ASK = {"select": ["whitespace/trailing"], "no_baseline": True}


def _d(path, line, rule="code/a", message="m"):
    return Diagnostic(path=str(path), line=line, col=1, rule_id=rule, severity=Severity.WARNING,
                      message=message)


def _f(line=1, rule="code/a", corpus="Задачи", file="Шаги.xbsl"):
    return (corpus, file, line, 1, rule, "m")


def _run(findings, corpora=("Задачи",), *, roots=None, rules=None, selection=None):
    if rules is None:
        rules = {f[4]: True for f in findings}
    return rundiff.Run(
        corpora=list(corpora), findings=sorted(findings), checked=1, lang="ru",
        selection=selection or {"select": None, "ignore": None, "enable": None}, rules=rules,
        roots=roots or {},
    )


def _project(tmp_path, body=_ONE_TRAILING):
    project = tmp_path / "Задачи"
    project.mkdir(exist_ok=True)
    source = project / "Шаги.xbsl"
    source.write_text(body, encoding="utf-8")
    return project, source


# --- the record of a comparison -------------------------------------------------------------


def test_a_first_run_is_saved_and_nothing_is_compared():
    record = rundiff.compare_record(None, _run([]), [], path="запуск.json")
    assert record == {"file": "запуск.json", "compared": False}


def test_the_changes_come_as_counts_rule_rows_and_records(tmp_path):
    root = tmp_path / "Задачи"
    roots = {"Задачи": root.as_posix()}
    saved = _run([_f(line=1), _f(line=5, rule="code/b")], roots=roots)
    now = _run([_f(line=2), _f(line=5, rule="code/b")], roots=roots)
    diagnostics = [_d(root / "Шаги.xbsl", 2), _d(root / "Шаги.xbsl", 5, rule="code/b")]

    record = rundiff.compare_record(rundiff.compare(saved, now), now, diagnostics,
                                    path="запуск.json")

    where = str(root / "Шаги.xbsl")
    assert record == {
        "file": "запуск.json",
        "compared": True,
        "appeared": 1,
        "disappeared": 1,
        "rules": [{"rule": "code/a", "files": 1, "findings": 1, "appeared": 1,
                   "disappeared": 1}],
        "findings": {
            "appeared": [{"path": where, "line": 2, "col": 1, "rule": "code/a", "message": "m"}],
            "disappeared": [{"path": where, "line": 1, "col": 1, "rule": "code/a",
                             "message": "m"}],
        },
    }


def test_a_rule_whose_findings_all_went_keeps_its_row_at_zero():
    record = rundiff.compare_record(rundiff.compare(_run([_f()]), _run([])), _run([]), [],
                                    path="запуск.json")
    assert record["rules"] == [{"rule": "code/a", "files": 0, "findings": 0, "appeared": 0,
                                "disappeared": 1}]


def test_past_the_limit_a_compact_record_points_at_the_file():
    limit = report.COMPACT_FINDINGS_LIMIT
    now = _run([_f(line=n) for n in range(1, limit + 2)])
    changes = rundiff.compare(_run([]), now)

    brief = rundiff.compare_record(changes, now, [], path="запуск.json", compact=True)
    whole = rundiff.compare_record(changes, now, [], path="запуск.json")

    assert "findings" not in brief
    # Not "call again without compact": the next call compares with the run this one saved,
    # and the changes the hint speaks of are then gone from the answer.
    assert brief["findings_hint"] == (
        f"изменений: {limit + 1}, это больше {limit} строк краткого ответа – весь список лежит "
        "в запуск.json, в разделе changes"
    )
    assert brief["appeared"] == limit + 1
    assert len(whole["findings"]["appeared"]) == limit + 1
    assert "findings_hint" not in whole


def test_the_parts_left_out_are_named_as_data():
    rules = {f"code/r{n}": True for n in range(8)}
    saved = _run([_f(rule="code/r3", corpus="Отчёты")], corpora=["Задачи", "Отчёты"],
                 rules=rules)
    now = _run([], rules={name: name == "code/r0" for name in rules},
               selection={"select": ["code/r0"], "ignore": None, "enable": None})
    changes = rundiff.compare(saved, now)

    whole = rundiff.compare_record(changes, now, [], path="запуск.json")
    brief = rundiff.compare_record(changes, now, [], path="запуск.json", compact=True)

    assert whole["not_compared"] == [
        {"part": "paths", "only_in": "saved", "names": ["Отчёты"], "findings": 1},
        {"part": "rules", "only_in": "saved",
         "names": [f"code/r{n}" for n in range(1, 8)], "findings": 0},
    ]
    assert brief["not_compared"][1] == {
        "part": "rules", "only_in": "saved",
        "names": ["code/r1", "code/r2", "code/r3", "code/r4", "code/r5"], "more": 2,
        "findings": 0,
    }


def test_nothing_left_out_is_not_mentioned():
    run = _run([_f()])
    assert "not_compared" not in rundiff.compare_record(rundiff.compare(run, run), run, [],
                                                        path="запуск.json")


def test_a_rule_this_run_alone_carried_is_named_on_the_current_side():
    saved = _run([], rules={"code/a": False, "code/b": True})
    now = _run([_f()], rules={"code/a": True, "code/b": True},
               selection={"select": None, "ignore": None, "enable": ["code/a"]})
    record = rundiff.compare_record(rundiff.compare(saved, now), now, [], path="запуск.json")
    assert record["not_compared"] == [
        {"part": "rules", "only_in": "current", "names": ["code/a"], "findings": 1},
    ]


# --- the tool -------------------------------------------------------------------------------


def test_a_file_that_is_not_a_saved_run_is_refused_before_the_check(mcp_module, tmp_path,
                                                                     monkeypatch):
    """Writing the run over a baseline would destroy it, and a refusal after a long check
    leaves the result nowhere to go."""
    baseline = tmp_path / ".xbsllint-baseline"
    baseline.write_text('{"meta": {"tool": "xbsl", "format": 1}, "files": {}}', encoding="utf-8")
    checked = []
    monkeypatch.setattr(mcp_module, "run", lambda *args, **kwargs: checked.append(1) or [])

    answer = mcp_module.lint_paths([str(tmp_path)], compare=str(baseline))

    assert list(answer) == ["error"]
    assert "не похож на запуск" in answer["error"]
    assert checked == []
    assert json.loads(baseline.read_text(encoding="utf-8"))["files"] == {}


@pytest.mark.needs_data
def test_the_first_call_saves_and_the_next_ones_answer_with_the_changes(mcp_module, tmp_path):
    project, source = _project(tmp_path)
    state = tmp_path / "запуск.json"

    first = mcp_module.lint_paths([str(project)], compare=str(state), **_ASK)
    source.write_text(_TWO_TRAILING, encoding="utf-8")
    second = mcp_module.lint_paths([str(project)], compare=str(state), **_ASK)
    third = mcp_module.lint_paths([str(project)], compare=str(state), **_ASK)

    assert set(first) == {"summary", "compare"}
    assert first["compare"] == {"file": str(state), "compared": False}
    assert first["summary"]["by_rule"] == {"whitespace/trailing": 1}
    assert rundiff.load(state, "ru").corpora == [project.as_posix()]

    diff = second["compare"]
    assert set(second) == {"summary", "compare"}
    assert (diff["compared"], diff["appeared"], diff["disappeared"]) == (True, 1, 0)
    assert diff["rules"] == [{"rule": "whitespace/trailing", "files": 1, "findings": 2,
                              "appeared": 1, "disappeared": 0}]
    (came,) = diff["findings"]["appeared"]
    assert Path(came["path"]).resolve() == source.resolve()
    assert (came["line"], came["rule"]) == (3, "whitespace/trailing")
    assert set(came) == {"path", "line", "col", "rule", "message"}
    assert diff["findings"]["disappeared"] == []
    assert "not_compared" not in diff
    assert second["summary"]["by_file"]  # the summary of the run stays whole

    assert (third["compare"]["appeared"], third["compare"]["disappeared"]) == (0, 0)


@pytest.mark.needs_data
def test_compact_holds_the_compared_answer_short(mcp_module, tmp_path):
    project, source = _project(tmp_path)
    state = tmp_path / "запуск.json"
    mcp_module.lint_paths([str(project)], compare=str(state), compact=True, **_ASK)
    source.write_text("метод Ф(): Число\n" + "    возврат 1  \n" * 12 + ";\n", encoding="utf-8")

    answer = mcp_module.lint_paths([str(project)], compare=str(state), compact=True, **_ASK)

    assert set(answer) == {"summary", "compare"}
    assert "by_file" not in answer["summary"]
    diff = answer["compare"]
    assert diff["appeared"] == 11
    assert "findings" not in diff
    assert str(state) in diff["findings_hint"]


@pytest.mark.needs_data
def test_a_relative_file_resolves_against_the_root(mcp_module, tmp_path, monkeypatch):
    _project(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    answer = mcp_module.lint_paths(["Задачи"], root=str(tmp_path), compare="запуск.json", **_ASK)

    assert answer["compare"]["file"] == str(tmp_path / "запуск.json")
    assert (tmp_path / "запуск.json").is_file()
    assert not (elsewhere / "запуск.json").exists()


@pytest.mark.needs_data
def test_the_terminal_and_the_tool_share_one_file(mcp_module, tmp_path, monkeypatch, capsys):
    """The terminal names the folder as typed from where it runs, the tool by its full path;
    the two runs pair by the folder and compare."""
    project, _ = _project(tmp_path)
    state = tmp_path / "запуск.json"
    monkeypatch.chdir(tmp_path)
    cli.main(["Задачи", "--select", "whitespace/trailing", "--no-baseline", "--compare",
              str(state)])
    capsys.readouterr()

    answer = mcp_module.lint_paths([str(project)], compare=str(state), **_ASK)

    diff = answer["compare"]
    assert (diff["compared"], diff["appeared"], diff["disappeared"]) == (True, 0, 0)
    assert "not_compared" not in diff
