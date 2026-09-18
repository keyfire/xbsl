"""The comment above a declaration that the environment does not show (comment/doc-marker).

The environment reads a documentation comment of a module by its marker: `///` lines before a
declaration. The rule reports a `//` block right above a declaration and respells it, reports a
block comment in that place without a fix, and leaves alone everything that is not a
description of a declaration: a note separated by a blank line, a comment inside a body.

The rule parses the module, so the whole module needs the data bundle (listed in
conftest._DATA_DEPENDENT).
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "comment/doc-marker"


def _lint(tmp_path, text: str, name: str = "РасчетПробы.xbsl"):
    (tmp_path / name).write_bytes(text.encode("utf-8"))
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _fixed(text: str, diags) -> str:
    for diag in sorted((d for d in diags if d.fix), key=lambda d: d.fix.start, reverse=True):
        text = text[: diag.fix.start] + diag.fix.new + text[diag.fix.end:]
    return text


_MODULE = """// Расчет цен: общие правила модуля.

// Цена товара со скидкой.
// Скидка задана в процентах.
@ВПроекте
@НаСервере
метод ЦенаСоСкидкой(Цена: Число, Скидка: Число): Число
    // округление до копеек
    возврат Цена * (100 - Скидка) / 100
;
"""


def test_block_above_annotations_is_reported_and_respelled(tmp_path):
    diags = _lint(tmp_path, _MODULE)
    assert len(diags) == 1 and (diags[0].line, diags[0].col) == (3, 1)
    fixed = _fixed(_MODULE, diags)
    assert "/// Цена товара со скидкой.\n/// Скидка задана в процентах.\n@ВПроекте\n" in fixed
    # The note about the module and the comment inside the body keep their marker.
    assert fixed.startswith("// Расчет цен: общие правила модуля.\n")
    assert "    // округление до копеек\n" in fixed
    assert _lint(tmp_path, fixed) == []


def test_documentation_comment_is_silent(tmp_path):
    text = _MODULE.replace("// Цена товара", "/// Цена товара").replace("// Скидка задана", "/// Скидка задана")
    assert _lint(tmp_path, text) == []


def test_note_separated_by_a_blank_line_is_left_alone(tmp_path):
    text = "// Раздел расчета.\n\n@НаСервере\nметод Проба()\n;\n"
    assert _lint(tmp_path, text) == []


def test_mixed_block_keeps_the_lines_already_respelled(tmp_path):
    text = "/// Цена товара.\n// Скидка в процентах.\nметод Проба()\n;\n"
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].line == 2
    assert _fixed(text, diags) == "/// Цена товара.\n/// Скидка в процентах.\nметод Проба()\n;\n"


def test_structure_field_enumeration_item_and_constant(tmp_path):
    text = (
        "// Ответ расчета.\n"
        "структура ОтветПробы\n"
        "    // Итоговая цена.\n"
        "    пер Цена: Число\n"
        ";\n"
        "\n"
        "// Виды скидок.\n"
        "перечисление ВидСкидкиПробы\n"
        "    // Скидка по карте.\n"
        "    ПоКарте,\n"
        "    Разовая\n"
        ";\n"
        "\n"
        "// Наибольшая скидка.\n"
        "конст ПРЕДЕЛ_СКИДКИ = 50\n"
    )
    diags = _lint(tmp_path, text)
    assert [d.line for d in diags] == [1, 3, 7, 9, 14]
    fixed = _fixed(text, diags)
    assert "    /// Итоговая цена.\n    пер Цена: Число\n" in fixed
    assert "    /// Скидка по карте.\n    ПоКарте,\n" in fixed
    assert _lint(tmp_path, fixed) == []


def test_block_comment_is_reported_without_a_fix(tmp_path):
    text = "/*\n * Цена товара со скидкой.\n */\n@НаСервере\nметод Проба()\n;\n"
    diags = _lint(tmp_path, text)
    assert len(diags) == 1 and diags[0].fix is None
    assert "`/* ... */`" in diags[0].message


def test_trailing_comment_of_the_previous_line_is_not_a_description(tmp_path):
    text = "конст ПЕРВАЯ = 1 // единица\nконст ВТОРАЯ = 2\n"
    assert _lint(tmp_path, text) == []


def test_crlf_module_keeps_its_line_ends(tmp_path):
    text = _MODULE.replace("\n", "\r\n")
    fixed = _fixed(text, _lint(tmp_path, text))
    assert "\n" not in fixed.replace("\r\n", "")
    assert "/// Цена товара со скидкой.\r\n/// Скидка задана в процентах.\r\n@ВПроекте\r\n" in fixed


def test_english_module_is_judged_the_same(tmp_path):
    text = (
        "// The price with a discount.\n"
        "@InProject\n"
        "@AtServer\n"
        "method DiscountedPrice(Price: Number, Discount: Number): Number\n"
        "    return Price * (100 - Discount) / 100\n"
        ";\n"
    )
    diags = _lint(tmp_path, text, name="ProbePricing.xbsl")
    assert len(diags) == 1 and diags[0].fix is not None
