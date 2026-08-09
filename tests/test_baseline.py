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
    """Add an entry nothing can spend: its file is not even in the run."""
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

    cli.main(["--baseline", str(bl), "--stale-baseline", *_NO_PAIR, str(f)])
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

    code = cli.main(["--baseline", str(bl), "--prune-baseline", *_NO_PAIR, str(f)])
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

    _, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
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
