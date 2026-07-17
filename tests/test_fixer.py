"""Аппликатор механических правок (--fix): fixer.py и его правила.

Пробные части чинилки (fix_source/encode/is_fixable) работают над готовыми Diagnostic
и данных Элемента не требуют. Тесты правил-источников правок (typography/whitespace)
идут через лексер и данные, поэтому помечены skipif как в других файлах правил.
"""

import pytest

from xbsl import dataset, engine, fixer
from xbsl.cli import discover
from xbsl.diagnostics import Diagnostic, Severity, TextEdit


def _src(name, content):
    return engine.load_text(name, content)


def _diag(path, offset, end, new, rule="whitespace/trailing"):
    return Diagnostic(path, 1, 1, rule, Severity.WARNING, "x", fix=TextEdit(offset, end, new))


# --- Чистая механика чинилки (без данных Элемента) -------------------------------------

def test_span_edits_applied_right_to_left():
    src = _src("М.xbsl", "абвгде")
    diags = [
        _diag("М.xbsl", 0, 1, "A"),   # а -> A
        _diag("М.xbsl", 4, 6, ""),    # удалить "де"
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "Aбвг"
    assert res.applied == 2 and res.changed


def test_overlapping_edits_earliest_wins():
    src = _src("М.xbsl", "абвгде")
    diags = [
        _diag("М.xbsl", 0, 3, "X"),   # покрывает абв
        _diag("М.xbsl", 2, 4, "Y"),   # пересекается – отбрасывается
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "Xгде"
    assert res.applied == 1


def test_no_fix_no_change():
    src = _src("М.xbsl", "абв")
    res = fixer.fix_source(src, [Diagnostic("М.xbsl", 1, 1, "r", Severity.WARNING, "x")])
    assert not res.changed and res.applied == 0


def test_mixed_newline_normalized_to_dominant():
    # CRLF ×2, LF ×1 -> преобладает CRLF
    src = _src("М.xbsl", "а\r\nб\r\nв\n")
    diag = Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x")
    res = fixer.fix_source(src, [diag])
    assert res.text == "а\r\nб\r\nв\r\n"
    assert res.applied == 1 and res.changed


def test_mixed_newline_after_trailing_edit():
    # хвостовой пробел удаляется, затем переводы строк нормализуются
    src = _src("М.xbsl", "а  \r\nб\n")
    diags = [
        _diag("М.xbsl", 1, 3, ""),  # два пробела после "а"
        Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x"),
    ]
    res = fixer.fix_source(src, diags)
    assert res.text == "а\r\nб\r\n"
    assert res.applied == 2


def test_encode_preserves_bom():
    src = engine.make_source(__import__("pathlib").Path("М.xbsl"), "﻿абв".encode("utf-8"))
    assert src.had_bom
    data = fixer.encode(src, "абвг")
    assert data.startswith(b"\xef\xbb\xbf") and data.decode("utf-8-sig") == "абвг"


def test_is_fixable():
    assert fixer.is_fixable(_diag("М.xbsl", 0, 1, ""))
    assert fixer.is_fixable(
        Diagnostic("М.xbsl", 1, 1, "whitespace/mixed-newline", Severity.WARNING, "x"))
    assert not fixer.is_fixable(Diagnostic("М.xbsl", 1, 1, "structure/xbsl-pair", Severity.WARNING, "x"))


# --- Правила-источники правок (нужны данные Элемента) ----------------------------------

_needs_data = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте tools/extract_grammar.py + extract_stdlib.py",
)


@_needs_data
def test_trailing_rule_carries_fix():
    src = _src("М.xbsl", "метод Ф(): Число\n    возврат 1  \n;\n")
    diags = [d for d in engine.run_sources([src], select={"whitespace/trailing"})
             if d.rule_id == "whitespace/trailing"]
    assert diags and diags[0].fix is not None
    assert fixer.fix_source(src, diags).text == "метод Ф(): Число\n    возврат 1\n;\n"


@_needs_data
def test_typography_rules_carry_fixes():
    src = _src("М.xbsl", "// “цитата” и многоточие… и тире —\nметод Ф()\n;\n")
    diags = engine.run_sources([src], select={"typography"})
    fixed = fixer.fix_source(src, diags).text
    assert '"цитата"' in fixed
    assert "многоточие..." in fixed
    assert "тире –" in fixed  # среднее тире U+2013
    assert "—" not in fixed and "“" not in fixed and "…" not in fixed


@_needs_data
def test_cli_fix_writes_and_reports(tmp_path, capsys):
    from xbsl import cli

    f = tmp_path / "М.xbsl"
    f.write_text("// многоточие…\nметод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")
    code = cli.main(["--fix", "--ignore", "structure/xbsl-pair", str(f)])
    err = capsys.readouterr().err
    assert code == 0
    assert "Исправлено замечаний: 2" in err
    text = f.read_text(encoding="utf-8")
    assert "многоточие..." in text and "возврат 1\n" in text


@_needs_data
def test_cli_fix_rejects_stdin(capsys):
    from xbsl import cli

    code = cli.main(["--fix", "--stdin", "--filename", "М.xbsl"])
    assert code == 2 and "--stdin" in capsys.readouterr().err


@_needs_data
def test_cli_fix_rejects_baseline(tmp_path, capsys):
    from xbsl import cli

    f = tmp_path / "М.xbsl"
    f.write_text("метод Ф()\n;\n", encoding="utf-8")
    code = cli.main(["--fix", "--baseline", str(tmp_path / "b.json"), str(f)])
    assert code == 2 and "--baseline" in capsys.readouterr().err
