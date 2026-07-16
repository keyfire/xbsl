"""Базлайн (--write-baseline / --baseline) и включение правил поверх дефолта (--enable).

Зависит от данных Элемента (main() резолвит версию данных) – модуль в списке
пропускаемых conftest, если данные не сгенерированы.
"""

import json

from xbsllint import cli

_ХВОСТ = "метод Ф()\n    возврат 1  \n;\n"  # хвостовой пробел на строке 2

# у временных файлов нет парного yaml – это не предмет модуля
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

    # второе нарушение того же правила с тем же сообщением: бюджет 1 – гасится первое
    # по порядку строк, новое всплывает
    f.write_text("метод Ф()\n    пер А = 1  \n    возврат А  \n;\n", encoding="utf-8")
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

    f.write_text("// комментарий сверху\n" + _ХВОСТ, encoding="utf-8")  # находка съехала вниз
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

    f.write_text("метод Ф()\n    возврат 1\n;\n", encoding="utf-8")  # долг починен
    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert payload["diagnostics"] == []
    assert payload["summary"]["baselined"] == 0
    assert payload["summary"]["baseline_unused"] == 1


def test_baselined_error_does_not_fail_the_run(tmp_path, capsys):
    f = tmp_path / "Ч.xbsl"
    f.write_text("метод Ф()\n    пер Икс = (1 + 2\n;\n", encoding="utf-8")  # ошибка скобок
    bl = tmp_path / "baseline.json"
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()

    code, payload = _run_json(["--baseline", str(bl), str(f)], capsys)
    assert code == 0 and payload["diagnostics"] == []

    # без базлайна та же ошибка валит прогон
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


# --- Причины исключений ({count, reason}) ------------------------------------------------


def test_reason_entry_suppresses(tmp_path, capsys):
    """Запись вида {"count": N, "reason": ...} гасит находку так же, как голое число."""
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
    """--write-baseline переносит причины выживших записей из прежнего файла."""
    from xbsllint import baseline

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
    # причины исчезнувших находок не переносятся: чистый файл - пустой базлайн
    f.write_text("метод Ф()\n    возврат 1\n;\n", encoding="utf-8")
    cli.main(["--write-baseline", str(bl), *_БЕЗ_ПАРЫ, str(f)])
    capsys.readouterr()
    assert baseline.load(bl)["files"] == {}


def test_lsp_apply_baseline_file(tmp_path):
    """Фильтр LSP: нет файла - без изменений, битый - проблема, валидный - гасит."""
    from xbsllint import baseline
    from xbsllint.diagnostics import Diagnostic, Severity
    from xbsllint.lsp import apply_baseline_file

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
