"""Assignment to a read-only name (xbsl/rules/readonly_targets.py).

The kinds and their controls repeat what the IDE language server answered on probe projects:
`знч` and `исп` locals, loop and `поймать` variables, module constants and `знч` fields are
read-only; parameters, lambda parameters and `пер` fields are not; scopes decide which
declaration a name means.
"""

from pathlib import Path

import pytest

from xbsl import fixer
from xbsl.engine import load, load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rule parses the module; the lexer reads the data

RULE = "code/assign-readonly"


def _diags(code: str) -> list:
    return run_sources([load_text("Модуль.xbsl", code)], select={RULE}, scopes=("file",))


def _places(code: str) -> list[tuple[int, int]]:
    return [(d.line, d.col) for d in _diags(code)]


def test_val_and_use_locals():
    code = (
        "метод Проба(Данные: Байты): Число\n"
        "    знч Постоянная = 1\n"
        "    Постоянная = 2\n"
        "    Постоянная += 1\n"
        "    исп Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    Поток = ПотокЧтения.ИзБайтов(Данные)\n"
        "    возврат Постоянная\n"
        ";\n"
    )
    diags = _diags(code)
    assert [(d.line, d.col) for d in diags] == [(3, 5), (4, 5), (6, 5)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'Постоянная'" in diags[0].message and "'знч'" in diags[0].message
    assert "'исп'" in diags[2].message


def test_loop_and_catch_variables_in_nested_blocks():
    code = (
        "метод Проба(Числа: Массив<Число>, Флаг: Булево): Число\n"
        "    для Н из Числа\n"
        "        для М из Числа\n"
        "            Н = М\n"
        "        ;\n"
        "    ;\n"
        "    для Индекс = 0 по 3\n"
        "        Индекс = 5\n"
        "    ;\n"
        "    попытка\n"
        "        Числа.Добавить(1)\n"
        "    поймать Искл: Исключение\n"
        "        если Флаг\n"
        "            Искл = новый ИсключениеНедопустимоеСостояние(\"в\")\n"
        "        ;\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    diags = _diags(code)
    assert [(d.line, d.col) for d in diags] == [(4, 13), (8, 9), (14, 13)]
    assert "цикла" in diags[0].message and "'поймать'" in diags[2].message


def test_module_constant_and_val_field_by_bare_name_and_this():
    code = (
        "конст ПОРОГ = 1\n"
        "\n"
        "структура Метка\n"
        "    знч Текст: Строка = \"\"\n"
        "    пер Счет: Число = 0\n"
        "\n"
        "    метод Изменить()\n"
        "        Текст = \"б\"\n"
        "        этот.Текст = \"в\"\n"
        "        Счет = 1\n"
        "        этот.Счет = 2\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод Константа(): Число\n"
        "    ПОРОГ = 2\n"
        "    возврат ПОРОГ\n"
        ";\n"
    )
    assert _places(code) == [(8, 9), (9, 14), (16, 5)]


def test_writable_names_and_scopes_stay_silent():
    code = (
        "конст Предел = 10\n"
        "\n"
        "метод Проба(Параметр: Число, Числа: Массив<Число>, Флаг: Булево): Число\n"
        "    Параметр = 5\n"
        "    Числа.ДляКаждого(Н -> Н = 1)\n"
        "    если Флаг\n"
        "        знч Х = 1\n"
        "        возврат Х\n"
        "    иначе\n"
        "        пер Х = 2\n"
        "        Х = 3\n"
        "    ;\n"
        "    пер Предел = 1\n"
        "    Предел = 2\n"
        "    знч Копия = Параметр\n"
        "    х = 1\n"
        "    возврат Параметр + Предел + Копия\n"
        ";\n"
    )
    assert _diags(code) == []


def test_val_local_stays_read_only_inside_a_lambda():
    code = (
        "метод Проба(Числа: Массив<Число>): Число\n"
        "    знч Последнее = 1\n"
        "    Числа.ДляКаждого(Н -> Последнее = Н)\n"
        "    возврат Последнее\n"
        ";\n"
    )
    diags = _diags(code)
    assert [(d.line, d.col) for d in diags] == [(3, 27)]
    assert diags[0].fix is None  # a captured variable may not change either


def test_static_method_does_not_see_the_fields():
    code = (
        "структура Метка\n"
        "    знч Текст: Строка = \"\"\n"
        "\n"
        "    статический метод Создать(): Метка\n"
        "        пер Текст = \"а\"\n"
        "        Текст = \"б\"\n"
        "        возврат новый Метка(Текст = Текст)\n"
        "    ;\n"
        ";\n"
    )
    assert _diags(code) == []


def test_english_spelling():
    code = (
        "method Probe(Items: Array<Number>): Number\n"
        "    val Limit = 1\n"
        "    Limit = 2\n"
        "    for Item in Items\n"
        "        Item = 3\n"
        "    ;\n"
        "    return Limit\n"
        ";\n"
    )
    assert _places(code) == [(3, 5), (5, 9)]


def test_fix_turns_the_val_declaration_into_var(tmp_path: Path):
    path = tmp_path / "Модуль.xbsl"
    path.write_bytes(
        "метод Проба(): Число\r\n"
        "    знч Итог = 0\r\n"
        "    Итог = Итог + 1\r\n"
        "    Итог += 2\r\n"
        "    возврат Итог\r\n"
        ";\r\n".encode("utf-8")
    )
    src = load(path)
    diags = run_sources([src], select={RULE}, scopes=("file",))
    assert [d.line for d in diags] == [3, 4]
    result = fixer.fix_source(src, diags)
    expected = path.read_bytes().decode("utf-8").replace("знч Итог", "пер Итог", 1)
    assert result.text == expected
    assert run_sources([load_text("Модуль.xbsl", result.text)], select={RULE},
                       scopes=("file",)) == []


def test_fix_keeps_the_english_keyword():
    code = (
        "method Probe(): Number\n"
        "    val Total = 0\n"
        "    Total = 1\n"
        "    return Total\n"
        ";\n"
    )
    diags = _diags(code)
    assert [d.fix.new for d in diags] == ["var"]


def test_no_fix_for_other_read_only_kinds():
    code = (
        "конст ПОРОГ = 1\n"
        "\n"
        "метод Проба(Числа: Массив<Число>)\n"
        "    ПОРОГ = 2\n"
        "    для Н из Числа\n"
        "        Н = 1\n"
        "    ;\n"
        ";\n"
    )
    assert [d.fix for d in _diags(code)] == [None, None]
