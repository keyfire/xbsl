"""Baseline (--write-baseline / --baseline) and enabling rules on top of defaults (--enable).

Depends on the Element data (main() resolves the data version) - the module is in the
conftest skip list when the data has not been generated.
"""

import json

from xbsl import cli

_ХВОСТ = "метод Ф(): Число\n    возврат 1  \n;\n"  # trailing whitespace on line 2

# temporary files have no paired yaml - that is not what this module is about
_БЕЗ_ПАРЫ = ["--ignore", "structure/xbsl-pair"]


def _run_json(argv, capsys):
    code = cli.main(["--format", "json", *_БЕЗ_ПАРЫ, *argv])
    return code, json.loads(capsys.readouterr().out)


def test_write_then_check_suppresses_all(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"

    code = cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
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
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    # a second violation of the same rule with the same message: the budget is 1 - the first
    # one in line order is suppressed, the new one surfaces
    f.write_text("метод Ф(): Число\n    пер А = 1  \n    возврат А  \n;\n", encoding="utf-8")
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    diags = payload["diagnostics"]
    assert len(diags) == 1 and diags[0]["line"] == 3
    assert payload["summary"]["baselined"] == 1


def test_line_shift_keeps_finding_suppressed(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    f.write_text("// комментарий сверху\n" + _ХВОСТ, encoding="utf-8")  # the finding shifted down
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 1
    assert payload["summary"]["baseline_unused"] == 0


def test_fixed_finding_counts_as_unused(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
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
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert code == 0 and payload["diagnostics"] == []

    # without the baseline the same error fails the run
    code, payload = _run_json([str(f)], capsys)
    assert code == 1 and payload["summary"]["errors"] >= 1


def test_missing_baseline_file_is_an_error(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_ХВОСТ, encoding="utf-8")
    code = cli.main(["--baseline", str(tmp_path / "нет.json"), *_БЕЗ_ПАРЫ, str(f)])
    assert code == 2
    assert "не найден" in capsys.readouterr().err


def test_text_summary_reports_baseline(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    cli.main(["--baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    err = capsys.readouterr().err
    assert "Погашено базлайном: 1" in err


def test_enable_adds_rule_on_top_of_defaults(tmp_path, capsys):
    long_line = "    пер Переменная = 1  # " + "х" * 120
    f = tmp_path / "Ч.xbsl"
    f.write_text(f"метод Ф()\n{long_line}\n    возврат Переменная  \n;\n", encoding="utf-8")

    code, payload = _run_json([str(f)], capsys)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert "whitespace/trailing" in rules and "style/line-length" not in rules

    code, payload = _run_json(["--enable", "style/line-length", str(f)], capsys)
    rules = {d["rule"] for d in payload["diagnostics"]}
    assert {"whitespace/trailing", "style/line-length"} <= rules


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
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
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
    f.write_text(_ХВОСТ, encoding="utf-8")
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    data = json.loads(bl.read_text(encoding="utf-8"))
    per_message = data["files"]["Ч.xbsl"]["whitespace/trailing"]
    message = next(iter(per_message))
    per_message[message] = {"count": per_message[message], "reason": "так надо"}
    bl.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()
    rewritten = baseline.load(bl)
    entry = rewritten["files"]["Ч.xbsl"]["whitespace/trailing"][message]
    assert entry == {"count": 1, "reason": "так надо"}
    # reasons of vanished findings are not carried over: a clean file - an empty baseline
    f.write_text("метод Ф(): Число\n    возврат 1\n;\n", encoding="utf-8")
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
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
