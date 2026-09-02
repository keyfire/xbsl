"""Baseline (--write-baseline / --baseline) and enabling rules on top of defaults (--enable).

Depends on the Element data (main() resolves the data version) - the module is in the
conftest skip list when the data has not been generated.
"""

import json

from xbsl import cli

_TRAILING = "метод Ф(): Число\n    возврат 1  \n;\n"  # trailing whitespace on line 2

# temporary files have no paired yaml - that is not what this module is about
_NO_PAIR = ["--ignore", "structure/xbsl-pair"]


def _run_json(argv, capsys):
    code = cli.main(["--format", "json", *_NO_PAIR, *argv])
    return code, json.loads(capsys.readouterr().out)


def test_write_then_check_suppresses_all(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"

    code = cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    err = capsys.readouterr().err
    assert code == 0 and bl.is_file()
    assert "Базлайн записан" in err

    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert code == 0
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 1
    assert payload["summary"]["baseline_unused"] == 0


def test_new_same_kind_finding_surfaces(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    # a second violation of the same rule with the same message: the budget is 1 - the first
    # one in line order is suppressed, the new one surfaces
    f.write_text("метод Ф(): Число\n    пер Итог = 1  \n    возврат Итог  \n;\n", encoding="utf-8")
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    diags = payload["diagnostics"]
    assert len(diags) == 1 and diags[0]["line"] == 3
    assert payload["summary"]["baselined"] == 1


def test_line_shift_keeps_finding_suppressed(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    f.write_text("// комментарий сверху\n" + _TRAILING, encoding="utf-8")  # the finding shifted down
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 1
    assert payload["summary"]["baseline_unused"] == 0


def test_fixed_finding_counts_as_unused(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    f.write_text("метод Ф(): Число\n    возврат 1\n;\n", encoding="utf-8")  # the debt is fixed
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 0
    assert payload["summary"]["baseline_unused"] == 1


def test_baselined_error_does_not_fail_the_run(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф()\n    пер Икс = (1 + 2\n;\n", encoding="utf-8")  # parenthesis error
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert code == 0 and payload["diagnostics"] == []

    # without the baseline the same error fails the run
    code, payload = _run_json([str(f)], capsys)
    assert code == 1 and payload["summary"]["errors"] >= 1


def test_baseline_with_a_bom_is_read(tmp_path):
    """Базлайн, переписанный PowerShell (Out-File -Encoding utf8 ставит BOM), годен."""
    from xbsl import baseline

    bl = tmp_path / "baseline.json"
    bl.write_bytes(b'\xef\xbb\xbf{"files": {}}')
    assert baseline.load(bl)["files"] == {}


def test_missing_baseline_file_is_an_error(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    code = cli.main(["--baseline", str(tmp_path / "нет.json"), *_NO_PAIR, str(f)])
    assert code == 2
    assert "не найден" in capsys.readouterr().err


def test_text_summary_reports_baseline(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    cli.main(["--baseline", str(bl), *_NO_PAIR, str(f)])
    err = capsys.readouterr().err
    assert "Погашено базлайном: 1" in err


def test_enable_adds_rule_on_top_of_defaults(tmp_path, capsys):
    """`--enable` adds a rule that the default set leaves out.

    The example is `code/unused-method`: the style rules used to serve here, but they are
    documented platform conventions and now run by default, so they no longer demonstrate
    anything. A rule stays out of the default set only when its finding may legitimately be
    a false positive - that is the class this flag exists for.
    """
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод НикемНеВызываемый()\n    возврат 1  \n;\n", encoding="utf-8")

    code, payload = _run_json([str(f)], capsys)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert "whitespace/trailing" in rules and "code/unused-method" not in rules

    code, payload = _run_json(["--enable", "code/unused-method", str(f)], capsys)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert {"whitespace/trailing", "code/unused-method"} <= rules


def test_enable_respects_ignore(tmp_path, capsys):
    long_line = "    пер Переменная = 1  # " + "х" * 120
    f = tmp_path / "Ч.xbsl"
    f.write_text(f"метод Ф()\n{long_line}\n    возврат Переменная\n;\n", encoding="utf-8")

    code, payload = _run_json(
        ["--enable", "style/line-length", "--ignore", "style/line-length", str(f)], capsys,
    )
    assert all(d["rule"] != "style/line-length" for d in payload["diagnostics"])


# --- Suppression reasons ({count, reason}) -----------------------------------------------


def test_reason_entry_suppresses(tmp_path, capsys):
    """An entry of the form {"count": N, "reason": ...} suppresses a finding just like a bare number."""
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    data = json.loads(bl.read_text(encoding="utf-8"))
    per_rule = data["files"]["Ч.xbsl"]
    message, count = next(iter(per_rule["whitespace/trailing"].items()))
    per_rule["whitespace/trailing"][message] = {"count": count, "reason": "проектное решение"}
    bl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert code == 0
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 1


def test_rewrite_keeps_reasons(tmp_path, capsys):
    """--write-baseline carries over the reasons of surviving entries from the previous file."""
    from xbsl import baseline

    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    data = json.loads(bl.read_text(encoding="utf-8"))
    per_message = data["files"]["Ч.xbsl"]["whitespace/trailing"]
    message = next(iter(per_message))
    per_message[message] = {"count": per_message[message], "reason": "так надо"}
    bl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    rewritten = baseline.load(bl)
    entry = rewritten["files"]["Ч.xbsl"]["whitespace/trailing"][message]
    assert entry == {"count": 1, "reason": "так надо"}
    # reasons of vanished findings are not carried over: a clean file - an empty baseline
    f.write_text("метод Ф(): Число\n    возврат 1\n;\n", encoding="utf-8")
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    assert baseline.load(bl)["files"] == {}


def test_lsp_apply_baseline_file(tmp_path):
    """LSP filter: no file - unchanged, broken file - a problem, valid file - suppresses."""
    from xbsl import baseline
    from xbsl.diagnostics import Diagnostic, Severity
    from xbsl.lsp import apply_baseline_file

    d = Diagnostic(str(tmp_path / "Ч.xbsl"), 2, 5, "whitespace/trailing", Severity.WARNING, "Хвостовые пробелы.")
    kept, problem = apply_baseline_file([d], None)
    assert kept == [d] and problem is None
    kept, problem = apply_baseline_file([d], tmp_path / "нет.json")
    assert kept == [d] and problem is None

    bad = tmp_path / "битый.json"
    bad.write_text("{", encoding="utf-8")
    kept, problem = apply_baseline_file([d], bad)
    assert kept == [d] and problem

    bl = tmp_path / "baseline.json"
    baseline.write(bl, [d])
    kept, problem = apply_baseline_file([d], bl)
    assert kept == [] and problem is None


def _seed_stale(bl, extra_path="Ушедший.xbsl"):
    """Add an entry nothing can spend: its file is gone (a run over the directory reaches it)."""
    data = json.loads(bl.read_text(encoding="utf-8"))
    data["files"][extra_path] = {"whitespace/trailing": {"Хвостовые пробелы.": 2}}
    bl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_stale_entries_are_listed(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    _seed_stale(bl)

    cli.main(["--baseline", str(bl), "--stale-baseline", *_NO_PAIR, str(tmp_path)])
    err = capsys.readouterr().err
    # the entry is named - path, rule and how many suppressions it still holds
    assert "Ушедший.xbsl" in err and "whitespace/trailing" in err and "x2" in err
    # the live entry is not called stale
    assert err.count("устаревшая запись") == 1


def test_prune_removes_only_stale_entries(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    _seed_stale(bl)

    code = cli.main(["--baseline", str(bl), "--prune-baseline", *_NO_PAIR, str(tmp_path)])
    err = capsys.readouterr().err
    assert code == 0 and "удалено записей: 1" in err
    data = json.loads(bl.read_text(encoding="utf-8"))
    assert "Ушедший.xbsl" not in data["files"]
    # the finding that still occurs keeps its entry, and stays suppressed afterwards
    assert data["files"]["Ч.xbsl"]["whitespace/trailing"]
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert payload["summary"]["baselined"] == 1 and payload["summary"]["baseline_stale"] == 0


def test_prune_without_stale_entries_leaves_the_file(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    before = bl.read_text(encoding="utf-8")

    cli.main(["--baseline", str(bl), "--prune-baseline", *_NO_PAIR, str(f)])
    assert "удалено записей: 0" in capsys.readouterr().err
    assert bl.read_text(encoding="utf-8") == before


def test_json_payload_names_stale_entries(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    _seed_stale(bl)

    _, payload = _run_json(["--baseline", str(bl), str(tmp_path)], capsys)
    summary = payload["summary"]
    # one entry, two suppressions behind it - the two counters are not the same number
    assert summary["baseline_stale"] == 1 and summary["baseline_unused"] == 2
    assert summary["baseline_stale_entries"][0]["path"] == "Ушедший.xbsl"


def test_project_baseline_is_found_without_the_flag(tmp_path, capsys):
    """A committed baseline applies on its own: a local run must not contradict CI.

    CI passes --baseline explicitly, so a linter that ignored the file locally reported
    everything the project had deliberately frozen - and that reads as a broken linter.
    """
    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    f = project / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    code = cli.main([*_NO_PAIR, str(f)])
    err = capsys.readouterr().err
    assert code == 0 and "Найден базлайн проекта" in err
    assert "Погашено базлайном: 1" in err


def test_discovery_is_switched_off_by_the_flag(tmp_path, capsys):
    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    f = project / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    cli.main(["--no-baseline", *_NO_PAIR, str(f)])
    out, err = capsys.readouterr()
    assert "Найден базлайн" not in err and "Погашено базлайном" not in err
    assert "whitespace/trailing" in out


def test_explicit_baseline_wins_over_discovery(tmp_path, capsys):
    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    f = project / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    discovered = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(discovered), *_NO_PAIR, str(f)])
    named = tmp_path / "другой.json"
    named.write_text('{"meta": {"format": 1}, "files": {}}', encoding="utf-8")
    capsys.readouterr()

    cli.main(["--baseline", str(named), *_NO_PAIR, str(f)])
    out, err = capsys.readouterr()
    # the named (empty) baseline suppresses nothing, and the discovery message never appears
    assert "Найден базлайн" not in err and "whitespace/trailing" in out


def _seed_other_rule(bl):
    """An entry of a rule that a narrower run will not carry."""
    data = json.loads(bl.read_text(encoding="utf-8"))
    data["files"]["Ч.xbsl"]["typography/em-dash"] = {
        "Длинное тире (em dash) - в этом проекте пишут среднее.": {"count": 3},
    }
    bl.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def test_entry_of_a_rule_the_run_skipped_is_not_stale(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    _seed_other_rule(bl)

    _, payload = _run_json(["--baseline", str(bl), "--ignore", "typography/em-dash", str(f)],
                           capsys)
    summary = payload["summary"]
    # the rule was not carried, so its three suppressions are neither spent nor stale
    assert summary["baseline_stale"] == 0 and summary["baseline_unused"] == 0
    assert summary["baseline_not_checked"] == 1


def test_prune_leaves_the_entries_it_could_not_check(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    _seed_other_rule(bl)

    code = cli.main(["--baseline", str(bl), "--prune-baseline",
                     "--ignore", "typography/em-dash", *_NO_PAIR, str(f)])
    assert code == 0 and "удалено записей: 0" in capsys.readouterr().err
    data = json.loads(bl.read_text(encoding="utf-8"))
    assert "typography/em-dash" in data["files"]["Ч.xbsl"]


def test_not_checked_line_is_silent_on_a_full_run(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()

    cli.main(["--baseline", str(bl), *_NO_PAIR, str(f)])
    err = capsys.readouterr().err
    assert "не проверено" not in err


# --- a path INSIDE the text of a finding ------------------------------------------------------

def _entry(message: str, reason: str = "") -> dict:
    """A one-entry baseline payload for the module below, with the given message."""
    value: object = {"count": 1, "reason": reason} if reason else 1
    return {"meta": {"tool": "xbsl", "format": 1},
            "files": {"Второй.yaml": {"yaml/duplicate-subtree": {message: value}}}}


def _finding(base_dir, message: str):
    from xbsl.diagnostics import Diagnostic, Severity

    return Diagnostic(str(base_dir / "Второй.yaml"), 1, 1, "yaml/duplicate-subtree",
                      Severity.WARNING, message)


def test_a_path_in_the_message_is_read_in_the_baselines_own_form(tmp_path):
    """The same finding, written on Windows and met on Linux: one entry, one identity.

    A rule that names a SECOND file writes the path the way the run received it - with the
    separators of the host, absolute when the run was given an absolute root. The baseline
    keys on the text of the finding, so without a common form an entry frozen on one machine
    freezes nothing on the other and is announced stale on both.
    """
    from xbsl import baseline

    windows = "Повторяет поддерево в файле Основное\Первый.yaml (всего таких мест: 2)."
    posix = "Повторяет поддерево в файле Основное/Первый.yaml (всего таких мест: 2)."
    absolute = (f"Повторяет поддерево в файле {tmp_path / 'Основное' / 'Первый.yaml'}"
                " (всего таких мест: 2).")

    for stored in (windows, posix):
        for met in (windows, posix, absolute):
            kept, suppressed, unused, stale = baseline.apply(
                [_finding(tmp_path, met)], _entry(stored), tmp_path)
            assert (kept, suppressed, unused, stale) == ([], 1, 0, []), (stored, met)


def test_the_written_baseline_states_the_path_in_one_form(tmp_path):
    """What --write-baseline stores must be what another host will look up."""
    from xbsl import baseline

    absolute = (f"Повторяет поддерево в файле {tmp_path / 'Основное' / 'Первый.yaml'}"
                " (всего таких мест: 2).")
    data = baseline.build([_finding(tmp_path, absolute)], tmp_path)

    stored = list(data["files"]["Второй.yaml"]["yaml/duplicate-subtree"])
    assert stored == ["Повторяет поддерево в файле Основное/Первый.yaml (всего таких мест: 2)."]


def test_a_reason_survives_a_rewrite_of_an_entry_naming_a_file(tmp_path):
    """The reasons are carried over by identity - which must be the common form too."""
    from xbsl import baseline

    windows = "Повторяет поддерево в файле Основное\Первый.yaml (всего таких мест: 2)."
    posix = "Повторяет поддерево в файле Основное/Первый.yaml (всего таких мест: 2)."
    reasons = baseline.reasons_of(_entry(windows, reason="две формы списка одного вида"),
                                  tmp_path)
    data = baseline.build([_finding(tmp_path, posix)], tmp_path, reasons)

    entry = data["files"]["Второй.yaml"]["yaml/duplicate-subtree"][posix]
    assert entry == {"count": 1, "reason": "две формы списка одного вида"}


# --- the run's reach: entries of files the run did not cover ---------------------------------

def test_entries_of_files_outside_the_run_are_not_stale(tmp_path, capsys):
    """A run over ONE file judges the entries of that file alone.

    The whole baseline used to be weighed against a partial run: `lint_paths` over two files
    answered "0 suppressed, 76 stale" while the same server over the project answered "74
    suppressed, 4 stale" - the difference was the files nobody asked about.
    """
    first = tmp_path / "А.xbsl"
    second = tmp_path / "Б.xbsl"
    first.write_text(_TRAILING, encoding="utf-8")
    second.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(first), str(second)])
    capsys.readouterr()

    _, payload = _run_json(["--baseline", str(bl), str(first)], capsys)
    summary = payload["summary"]
    assert summary["baselined"] == 1
    assert summary["baseline_stale"] == 0 and summary["baseline_unused"] == 0
    assert summary["baseline_not_checked"] == 1
    assert summary["baseline_not_checked_paths"] == 1
    assert summary["baseline_not_checked_rules"] == 0

    # a directory run reaches every file under it: the entry of a deleted file IS stale
    second.unlink()
    _, payload = _run_json(["--baseline", str(bl), str(tmp_path)], capsys)
    summary = payload["summary"]
    assert summary["baselined"] == 1 and summary["baseline_stale"] == 1
    assert summary["baseline_not_checked"] == 0


def test_the_not_checked_line_names_the_files_outside_the_run(tmp_path, capsys):
    first = tmp_path / "А.xbsl"
    second = tmp_path / "Б.xbsl"
    first.write_text(_TRAILING, encoding="utf-8")
    second.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(first), str(second)])
    capsys.readouterr()

    cli.main(["--baseline", str(bl), *_NO_PAIR, str(first)])
    err = capsys.readouterr().err
    assert "не проверено: 1" in err and "вне проверенных путей" in err


def test_a_run_above_the_baseline_reaches_every_entry(tmp_path, capsys):
    """The baseline may live BELOW the requested root: everything under it is in reach."""
    nested = tmp_path / "проект"
    nested.mkdir()
    f = nested / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = nested / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    f.write_text("метод Ф(): Число\n    возврат 1\n;\n", encoding="utf-8")

    _, payload = _run_json(["--baseline", str(bl), str(tmp_path)], capsys)
    assert payload["summary"]["baseline_stale"] == 1
    assert payload["summary"]["baseline_not_checked"] == 0


# --- xbsl baseline add ------------------------------------------------------------------------

def _lines(path) -> list[bytes]:
    # bytes, not text: a line ending rewritten from LF to CRLF is a changed line too
    return path.read_bytes().split(b"\n")


def _is_pure_addition(before: list[bytes], after: list[bytes]) -> bool:
    """Every old line survives, in its old order: the diff holds added lines and nothing else."""
    rest = iter(after)
    return all(any(line == candidate for candidate in rest) for line in before)


def _with_reason(bl, path: str, reason: str) -> str:
    """Give the (only) entry of `path` a hand-written reason; returns its message."""
    from xbsl import baseline

    data = json.loads(bl.read_text(encoding="utf-8"))
    per_message = data["files"][path]["whitespace/trailing"]
    message = next(iter(per_message))
    per_message[message] = {"count": per_message[message], "reason": reason}
    baseline.save(bl, data)
    return message


def test_add_appends_one_finding_without_reordering_or_touching_reasons(tmp_path, capsys):
    """`baseline add` writes ONLY the new finding: the file grows, nothing in it moves.

    Until the command existed, one finding with a reason meant a rewrite (which drops the
    reasons of nothing else, but re-sorts) or a snapshot into a temporary file merged by
    hand - the first attempt of which re-sorted the file (a diff of 28/16 lines for +12).
    """
    from xbsl import baseline

    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    first = project / "Альфа.xbsl"
    third = project / "Омега.xbsl"
    first.write_text(_TRAILING, encoding="utf-8")
    third.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(first), str(third)])
    message = _with_reason(bl, "acme/Проба/Альфа.xbsl", "так надо")
    before = _lines(bl)
    second = project / "Бета.xbsl"  # sorts between the two frozen files
    second.write_text(_TRAILING, encoding="utf-8")
    capsys.readouterr()

    code = cli.main(["baseline", "add", str(second), "--rule", "whitespace/trailing",
                     "--reason", "новая причина"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Бета.xbsl" in out and "whitespace/trailing" in out
    after = _lines(bl)
    assert len(after) > len(before) and _is_pure_addition(before, after)
    data = baseline.load(bl)
    assert list(data["files"]) == [
        "acme/Проба/Альфа.xbsl", "acme/Проба/Бета.xbsl", "acme/Проба/Омега.xbsl",
    ]
    assert data["files"]["acme/Проба/Альфа.xbsl"]["whitespace/trailing"][message] == {
        "count": 1, "reason": "так надо",
    }
    assert data["files"]["acme/Проба/Бета.xbsl"]["whitespace/trailing"][message] == {
        "count": 1, "reason": "новая причина",
    }
    # the baseline now covers the finding: the plain check is clean
    _, payload = _run_json([str(second)], capsys)
    assert payload["diagnostics"] == [] and payload["summary"]["baselined"] == 1


def test_add_is_idempotent_and_says_so(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    capsys.readouterr()
    frozen = bl.read_bytes()

    code = cli.main(["baseline", "add", str(f), "--rule", "whitespace/trailing",
                     "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["added"] == [] and payload["written"] is False
    assert payload["baseline"] == str(bl)
    assert bl.read_bytes() == frozen


def test_add_raises_the_count_of_an_existing_entry_and_keeps_its_reason(tmp_path, capsys):
    from xbsl import baseline

    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_NO_PAIR, str(f)])
    message = _with_reason(bl, "Ч.xbsl", "так надо")
    # a second occurrence of the same finding in the same file
    f.write_text("метод Ф(): Число\n    пер Итог = 1  \n    возврат Итог  \n;\n", encoding="utf-8")
    capsys.readouterr()

    code = cli.main(["baseline", "add", str(f), "--rule", "whitespace/trailing",
                     "--baseline", str(bl), "--reason", "другая", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["written"] is True
    assert payload["added"] == [{
        "path": "Ч.xbsl", "rule": "whitespace/trailing", "message": message,
        "count": 1, "reason": "так надо",
    }]
    entry = baseline.load(bl)["files"]["Ч.xbsl"]["whitespace/trailing"][message]
    assert entry == {"count": 2, "reason": "так надо"}


def test_add_takes_only_the_named_rule(tmp_path, capsys):
    """Other findings of the file stay out: the command adds ONE kind of debt, not a snapshot."""
    from xbsl import baseline

    f = tmp_path / "Ч.xbsl"  # trailing whitespace AND no paired yaml
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    baseline.save(bl, baseline.build([], tmp_path))
    capsys.readouterr()

    code = cli.main(["baseline", "add", str(f), "--rule", "whitespace/trailing"])

    assert code == 0
    data = baseline.load(bl)
    assert list(data["files"]["Ч.xbsl"]) == ["whitespace/trailing"]


def test_add_refuses_an_unknown_rule_and_a_missing_baseline(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")

    assert cli.main(["baseline", "add", str(f), "--rule", "whitespace/nothing"]) == 2
    assert "whitespace/nothing" in capsys.readouterr().err

    assert cli.main(["baseline", "add", str(f), "--rule", "whitespace/trailing"]) == 2
    assert "--write-baseline" in capsys.readouterr().err


def test_save_keeps_the_line_endings_and_the_bom_of_an_existing_file(tmp_path):
    """A committed baseline is LF; a rewrite in the platform's native style once turned a
    one-entry addition on Windows into a diff of every line."""
    from xbsl import baseline

    bl = tmp_path / "baseline.json"
    payload = baseline.build([], tmp_path)
    baseline.save(bl, payload)
    assert b"\r" not in bl.read_bytes()  # a new file: LF, the form it is committed in

    crlf = bl.read_bytes().replace(b"\n", b"\r\n")
    bl.write_bytes(crlf)
    baseline.save(bl, payload)
    assert bl.read_bytes() == crlf  # an existing CRLF file stays CRLF

    bl.write_bytes(b"\xef\xbb\xbf" + crlf)
    baseline.save(bl, payload)
    assert bl.read_bytes() == b"\xef\xbb\xbf" + crlf  # and keeps its BOM
