"""style/redundant-union-member: a member of a union type that another member already covers.

The platform IDE warns about a repeated member (`Строка|Строка`), a second empty value
(`Строка|Неопределено|?`) and a member a wider one covers (`Строка|Объект`,
`Массив<Строка>|ЧитаемыйМассив<Строка>`). Its language server confirmed the variants below on
probe projects - the positions it judges (a function type is not one of them), how the members
compare, the place it reports (a repeat at the EARLIER member, a covered member where it stands)
and that the unions the fix writes pass without a warning.

The rule parses the module and reads the platform catalog, so the tests need the Element data.
"""

from pathlib import Path

import pytest

from xbsl import cli, engine, i18n

pytestmark = pytest.mark.needs_data

RULE = "style/redundant-union-member"


def _lint(content: str, name: str = "Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _param(written: str) -> str:
    return f"метод Проба(Значение: {written}): Число\n    возврат 1\n;\n"


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


# --- what is reported -------------------------------------------------------------------------

def test_a_repeated_member_is_reported_at_the_first_one_with_the_union_rewritten():
    text = _param("Строка|Число|Строка")
    found = _lint(text)

    assert len(found) == 1, [d.message for d in found]
    assert (found[0].line, found[0].col) == (1, 23)
    assert found[0].severity.value == "warning"
    assert "повторяется" in found[0].message
    assert _fixed(text, found[0]) == _param("Строка|Число")


@pytest.mark.parametrize(("written", "columns", "rewritten"), [
    ("Строка|Строка", [23], "Строка"),
    ("Строка|Строка|Строка", [23], "Строка"),
    ("Строка|Строка?", [23], "Строка?"),
    ("Строка?|Строка?", [23, 29], "Строка?"),
    ("Строка|Неопределено|?", [30], "Строка?"),
    ("Число?|Неопределено", [28], "Число?"),
    ("Строка|String", [23], "Строка"),
    ("Строка|Объект", [23], "Объект"),
    ("Объект|Число|?", [30], "Объект?"),
    ("Строка|Объект|Число", [23, 37], "Объект"),
    ("Строка|Представляемое", [23], "Представляемое"),
    ("Массив<Строка>|ЧитаемыйМассив<Строка>", [23], "ЧитаемыйМассив<Строка>"),
    ("Обходимое<Строка>|Массив<Строка>", [41], "Обходимое<Строка>"),
    ("Соответствие<Строка, Число>|ЧитаемоеСоответствие<Строка, Число>", [23],
     "ЧитаемоеСоответствие<Строка, Число>"),
    ("Исключение|ИсключениеНедопустимоеСостояние?", [34], "Исключение?"),
    ("Массив<Строка>|Массив<Строка>", [23], "Массив<Строка>"),
])
def test_the_members_compare_the_way_the_platform_reads_them(written, columns, rewritten):
    text = _param(written)
    found = _lint(text)

    assert [d.col for d in found] == columns, (written, [d.message for d in found])
    assert _fixed(text, found[0]) == _param(rewritten)


def test_a_covered_member_names_the_wider_one():
    found = _lint(_param("Строка|Объект"))

    assert "уже входит в тип 'Объект'" in found[0].message


def test_types_of_the_module_are_covered_by_object():
    text = "структура Точка\n    пер Икс: Число = 0\n;\n\n" + _param("Точка|Объект")
    found = _lint(text)

    assert [(d.line, d.col) for d in found] == [(5, 23)]


@pytest.mark.parametrize(("code", "column"), [
    ("    пер Итог: Строка|Строка = \"\"\n    возврат 1\n", 15),
    ("    знч Итог = Значение это Строка|Строка\n    возврат 1\n", 29),
    ("    знч Итог = Значение это не Строка|Строка\n    возврат 1\n", 32),
    ("    знч Итог = Значение как Строка|Строка\n    возврат 1\n", 29),
    ("    знч Итог = новый Массив<Строка|Строка>()\n    возврат 1\n", 29),
    ("    знч Итог = <Строка|Строка>[]\n    возврат 1\n", 17),
    ("    знч Итог = (Х: Строка|Строка) -> Х.Длина()\n    возврат 1\n", 20),
    ("    выбор Значение\n        когда это Число|Число\n            возврат 1\n    ;\n    возврат 2\n", 19),
    ("    попытка\n        возврат 1\n    поймать Ошибка: ИсключениеНедопустимоеСостояние|Исключение\n"
     "        возврат 2\n    ;\n", 21),
])
def test_every_written_type_is_judged(code, column):
    text = f"метод Проба(Значение: Объект?): Число\n{code};\n"
    found = _lint(text)

    assert [d.col for d in found] == [column], (code, [d.message for d in found])


def test_a_result_a_field_and_a_constant_of_the_module_are_judged():
    text = ("конст ПУСТО: Строка|Строка = \"\"\n\nструктура Запись\n    пер Поле: Число|Число = 0\n;\n\n"
            "метод Проба(): Число|Число\n    возврат 1\n;\n")

    assert [(d.line, d.col) for d in _lint(text)] == [(1, 14), (4, 15), (7, 16)]


def test_the_ternary_after_a_type_check_keeps_its_question_mark():
    text = "метод Проба(Значение: Объект?): Число\n    возврат Значение это Строка|Строка ? 1 : 2\n;\n"
    found = _lint(text)

    assert len(found) == 1
    assert _fixed(text, found[0]) == \
        "метод Проба(Значение: Объект?): Число\n    возврат Значение это Строка ? 1 : 2\n;\n"


def test_the_english_module_names_the_empty_value_in_english():
    text = "method Probe(Value: String|?|Undefined): Number\n    return 1\n;\n"
    i18n.set_lang("en")
    try:
        found = _lint(text, "Probe.xbsl")
    finally:
        i18n.set_lang("ru")

    assert len(found) == 1
    assert "Type 'Undefined' repeats" in found[0].message
    assert _fixed(text, found[0]) == "method Probe(Value: String?): Number\n    return 1\n;\n"


# --- what is not reported ---------------------------------------------------------------------

@pytest.mark.parametrize("written", [
    "Число|Строка",
    "Объект?",
    "Массив<Строка>|Массив<Число>",
    "Массив<Строка?>|ЧитаемыйМассив<Строка>",
    # a wider argument: the IDE judges it by the variance of the parameter, which the catalog lacks
    "Массив<Строка>|ЧитаемыйМассив<Объект>",
    "Массив<Строка>|Массив<Объект>",
    "ИзменяемыйМассив<Объект>|Массив<Строка>",
    "(Строка|Строка)->Число",
    "()->Строка|Строка",
    "()->Массив<Строка|Строка>",
    # the catalog does not say which argument the base takes from a map
    "Соответствие<Строка, Число>|Обходимое<КлючИЗначение<Строка, Число>>",
])
def test_unions_that_add_something_with_each_member_are_not_reported(written):
    assert _lint(_param(written)) == []


def test_a_module_that_does_not_parse_is_not_judged():
    assert _lint(_param("Строка|Строка") + "метод Сломан(\n") == []


# --- the fix ----------------------------------------------------------------------------------

def test_a_union_spread_over_lines_keeps_the_finding_without_a_fix():
    text = "метод Проба(\n        Значение: Строка // первый\n            |Строка\n    ): Число\n    возврат 1\n;\n"
    found = _lint(text)

    assert len(found) == 1
    assert found[0].fix is None


def test_fix_rewrites_the_file_by_its_own_offsets(tmp_path: Path):
    target = tmp_path / "Проба.xbsl"
    lines = [
        "метод Проба(Значение: Строка|Строка?, Список: Массив<Число|Число>): Число|Объект",
        "    возврат 1",
        ";",
        "",
    ]
    target.write_bytes("\r\n".join(lines).encode("utf-8"))

    code = cli.main([str(tmp_path), "--select", RULE, "--no-baseline", "--fix"])

    assert code == 0
    assert target.read_bytes().decode("utf-8") == "\r\n".join([
        "метод Проба(Значение: Строка?, Список: Массив<Число>): Объект",
        *lines[1:],
    ])
