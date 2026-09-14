"""Initializers the compiler demands or refuses (xbsl/rules/initializers.py).

The forms and their controls repeat what the IDE language server answered on probe projects: a
required field with a default value (`code/required-field-default`), and a declaration that
cannot do without a value (`code/declaration-needs-init`).
"""

from pathlib import Path

import pytest

from xbsl import fixer
from xbsl.engine import load, load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rules parse the module; the lexer reads the data

DEFAULT = "code/required-field-default"
NEEDS = "code/declaration-needs-init"


def _diags(code: str, rule: str) -> list:
    return run_sources([load_text("Модуль.xbsl", code)], select={rule}, scopes=("file",))


def _places(code: str, rule: str) -> list[tuple[int, int]]:
    return [(d.line, d.col) for d in _diags(code, rule)]


# --- code/required-field-default ------------------------------------------------------------


def test_required_field_with_default_in_structure_and_exception():
    code = (
        "структура Заказ\n"
        "    обз пер Номер: Число = 5\n"
        "    обз знч Код: Строка = \"\"\n"
        "    обз пер Клиент: Строка\n"
        "    пер Комментарий: Строка = \"\"\n"
        ";\n"
        "\n"
        "исключение ИсключениеЗаказа\n"
        "    обз пер Уровень: Число = 1\n"
        ";\n"
    )
    diags = _diags(code, DEFAULT)
    assert [(d.line, d.col) for d in diags] == [(2, 28), (3, 27), (9, 30)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'Номер'" in diags[0].message and "'обз'" in diags[0].message


def test_required_field_default_english_spelling():
    code = "structure Order\n    req var Number: Number = 5\n    req var Customer: String\n;\n"
    assert _places(code, DEFAULT) == [(2, 30)]


def test_required_field_default_fix_removes_the_value(tmp_path: Path):
    path = tmp_path / "Модуль.xbsl"
    text = "структура Заказ\r\n    обз пер Номер: Число = 5 // номер\r\n;\r\n"
    path.write_bytes(text.encode("utf-8"))
    src = load(path)
    diags = run_sources([src], select={DEFAULT}, scopes=("file",))
    assert len(diags) == 1 and diags[0].fix is not None
    fixed = fixer.fix_source(src, diags).text
    assert fixed == path.read_bytes().decode("utf-8").replace(": Число = 5 //", ": Число //", 1)
    assert run_sources([load_text("Модуль.xbsl", fixed)], select={DEFAULT}, scopes=("file",)) == []


# --- code/declaration-needs-init ------------------------------------------------------------


def test_union_local_without_value():
    code = (
        "метод Проба(): Число\n"
        "    пер Смесь: Число|Строка\n"
        "    знч Смесь2: Число|Строка\n"
        "    пер Пустая: Число|Строка|?\n"
        "    пер Пустая2: Число|Неопределено\n"
        "    пер Одна: Число?\n"
        "    пер Повтор: Строка|Строка\n"
        "    пер Написания: Строка|String\n"
        "    пер Заданная: Число|Строка = 1\n"
        "    пер Число1: Число\n"
        "    возврат 1\n"
        ";\n"
    )
    diags = _diags(code, NEEDS)
    assert [(d.line, d.col) for d in diags] == [(2, 5), (3, 5)]
    assert "'Число|Строка'" in diags[0].message and "'?'" in diags[0].message


def test_union_field_that_is_not_required():
    code = (
        "структура Заказ\n"
        "    пер Смесь: Число|Строка\n"
        "    обз пер СмесьОбз: Число|Строка\n"
        "    пер СмесьПустая: Число|Строка|?\n"
        "    знч Задано: Число|Строка = 0\n"
        ";\n"
    )
    diags = _diags(code, NEEDS)
    assert [(d.line, d.col) for d in diags] == [(2, 5)]
    assert "'обз'" in diags[0].message


def test_use_variable_and_module_constant_without_value():
    code = (
        "конст ПУСТАЯ: Число\n"
        "конст ПОРОГ = 1\n"
        "\n"
        "метод Проба(Данные: Байты): Число\n"
        "    исп Поток: ПотокЧтения\n"
        "    исп Открытый = ПотокЧтения.ИзБайтов(Данные)\n"
        "    возврат ПОРОГ\n"
        ";\n"
    )
    diags = _diags(code, NEEDS)
    assert [(d.line, d.col) for d in diags] == [(1, 1), (5, 5)]
    assert "'ПУСТАЯ'" in diags[0].message and "'исп'" in diags[1].message


def test_declarations_inside_a_lambda_count_too():
    code = (
        "метод Проба(Числа: Массив<Число>)\n"
        "    Числа.ДляКаждого(метод(Н) ->\n"
        "        пер Смесь: Число|Строка\n"
        "        Смесь = Н\n"
        "    ;)\n"
        ";\n"
    )
    assert _places(code, NEEDS) == [(3, 9)]


def test_declaration_needs_init_english_spelling():
    code = (
        "const EMPTY: Number\n"
        "\n"
        "method Probe(): Number\n"
        "    var Mix: Number|String\n"
        "    use Stream: ReadableStream\n"
        "    var Maybe: Number|Undefined\n"
        "    return 1\n"
        ";\n"
    )
    assert _places(code, NEEDS) == [(1, 1), (4, 5), (5, 5)]
