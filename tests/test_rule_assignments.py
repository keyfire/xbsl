"""Assignments rejected by their shape (xbsl/rules/assignments.py).

The forms and their controls repeat what the IDE language server answered on probe projects:
an assignment to itself (`code/self-assignment`) and a left side that cannot receive a value
(`code/assign-target`). Silence on the accepted variants is as much the point as the findings.
"""

from pathlib import Path

import pytest

from xbsl import fixer
from xbsl.engine import load, load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rules parse the module; the lexer reads the data

SELF = "code/self-assignment"
TARGET = "code/assign-target"


def _diags(code: str, rule: str) -> list:
    src = load_text("Модуль.xbsl", code)
    return run_sources([src], select={rule}, scopes=("file",))


def _lines(code: str, rule: str) -> list[int]:
    return [d.line for d in _diags(code, rule)]


# --- code/self-assignment ------------------------------------------------------------------

_CELL = (
    "структура Ячейка\n"
    "    пер Значение: Число = 0\n"
    "    обз пер Вложенная: Ячейка\n"
    "\n"
    "    метод Сбросить()\n"
    "        Значение = Значение\n"
    "        этот.Значение = этот.Значение\n"
    "        этот.Значение = Значение\n"
    "        Значение = этот.Значение\n"
    "    ;\n"
    ";\n"
)


def test_plain_self_assignment_of_local_parameter_and_parentheses():
    code = (
        "метод Проба(Параметр: Число): Число\n"
        "    пер Х = 1\n"
        "    Х = Х\n"
        "    Параметр = Параметр\n"
        "    Х = (Х)\n"
        "    возврат Х + Параметр\n"
        ";\n"
    )
    diags = _diags(code, SELF)
    assert [d.line for d in diags] == [3, 4, 5]
    assert all(d.severity.value == "error" for d in diags)
    assert "'Х'" in diags[0].message


def test_fields_through_bare_name_and_this_but_not_mixed():
    assert _lines(_CELL, SELF) == [6, 7]


def test_member_chains_safe_access_on_the_right_and_short_lambda():
    code = (
        "метод Проба(Я: Ячейка, Ячейки: Массив<Ячейка>)\n"
        "    Я.Значение = Я.Значение\n"
        "    Я.Вложенная.Значение = Я.Вложенная.Значение\n"
        "    Я.Значение = Я?.Значение\n"
        "    Ячейки.ДляКаждого(Эл -> Эл.Значение = Эл.Значение)\n"
        ";\n"
    )
    assert _lines(code, SELF) == [2, 3, 4, 5]


def test_different_expressions_compile():
    code = (
        "метод Проба(Мас: Массив<Число>, Пустая: Число?, Я: Ячейка, Другая: Ячейка)\n"
        "    пер Х = 1\n"
        "    Х = Х + 0\n"
        "    Мас[0] = Мас[0]\n"
        "    пер Н: Число? = Пустая\n"
        "    Н = Н!\n"
        "    пер Объ: Объект = 1\n"
        "    Объ = Объ как Число\n"
        "    Я.Значение = Другая.Значение\n"
        "    Х = х\n"
        ";\n"
    )
    assert _diags(code, SELF) == []


def test_compound_operators_on_numbers():
    code = (
        "метод Проба(): Число\n"
        "    пер Х = 1\n"
        "    Х -= Х\n"
        "    Х *= Х\n"
        "    Х /= Х\n"
        "    Х += Х\n"
        "    пер Сумма: Число? = 0\n"
        "    Сумма += Сумма\n"
        "    возврат Х\n"
        ";\n"
    )
    diags = _diags(code, SELF)
    assert [d.line for d in diags] == [3, 4, 5, 6, 8]
    assert "'Х = Х - Х'" in diags[0].message


def test_string_concatenation_with_itself_compiles():
    code = (
        "метод Проба(Параметр: Строка, Пустая: Строка?): Строка\n"
        "    пер Текст = \"а\"\n"
        "    Текст += Текст\n"
        "    Параметр += Параметр\n"
        "    пер Второй: Строка? = Пустая\n"
        "    Второй += Второй\n"
        "    возврат Текст\n"
        ";\n"
    )
    assert _diags(code, SELF) == []


def test_compound_operator_needs_every_declaration_to_agree():
    # Sibling branches declare the name with different types; the unknown type is not compared.
    code = (
        "метод Проба(Флаг: Булево): Число\n"
        "    если Флаг\n"
        "        пер Х = \"а\"\n"
        "        Х += Х\n"
        "    иначе\n"
        "        пер Х = 1\n"
        "        Х += Х\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
        "\n"
        "метод Вызов(Значение: неизвестно)\n"
        "    Значение -= Значение\n"
        ";\n"
        "\n"
        "метод Результат(Данные: Массив<Число>)\n"
        "    пер Итог = Данные.Размер()\n"
        "    Итог += Итог\n"
        ";\n"
    )
    assert _diags(code, SELF) == []


def test_compound_operator_on_a_field_of_the_structure():
    code = (
        "структура Счетчик\n"
        "    пер Итог: Число = 0\n"
        "    пер Подпись: Строка = \"\"\n"
        "\n"
        "    метод Удвоить()\n"
        "        этот.Итог += этот.Итог\n"
        "        Подпись += Подпись\n"
        "    ;\n"
        ";\n"
    )
    assert _lines(code, SELF) == [6]


def test_english_spelling():
    code = (
        "structure Cell\n"
        "    var Value: Number = 0\n"
        "\n"
        "    method Reset()\n"
        "        this.Value = this.Value\n"
        "        Value *= Value\n"
        "    ;\n"
        ";\n"
    )
    assert _lines(code, SELF) == [5, 6]


def test_fix_removes_the_line_only_for_plain_assignment_alone_on_it(tmp_path: Path):
    path = tmp_path / "Модуль.xbsl"
    path.write_bytes(
        "метод Проба(Числа: Массив<Число>)\r\n"
        "    пер Х = 1\r\n"
        "    Х = Х\r\n"
        "    Х = Х // оставлено\r\n"
        "    Х *= Х\r\n"
        "    Числа.ДляКаждого(Н -> Н = Н)\r\n"
        ";\r\n".encode("utf-8")
    )
    src = load(path)
    diags = run_sources([src], select={SELF}, scopes=("file",))
    assert [d.line for d in diags] == [3, 4, 5, 6]
    assert [d.fix is not None for d in diags] == [True, False, False, False]
    fixed = fixer.fix_source(src, diags).text
    assert fixed == path.read_bytes().decode("utf-8").replace("    Х = Х\r\n", "", 1)


# --- code/assign-target --------------------------------------------------------------------

_NODES = (
    "структура Узел\n"
    "    пер Значение: Число = 0\n"
    "    обз пер Дети: Массив<Число>\n"
    "\n"
    "    метод Получить(): Узел\n"
    "        возврат этот\n"
    "    ;\n"
    ";\n"
    "\n"
    "метод Узлы(): Узел\n"
    "    возврат новый Узел(Дети = [0])\n"
    ";\n"
    "\n"
)


def test_safe_access_anywhere_in_the_chain():
    code = _NODES + (
        "метод Проба(А: Узел?, Б: Узел)\n"
        "    А?.Значение = 1\n"
        "    А?.Получить().Значение = 1\n"
        "    А?.Дети[0] = 1\n"
        "    Б.Получить().Дети[0] = 1\n"
        ";\n"
    )
    diags = _diags(code, TARGET)
    assert [d.line for d in diags] == [15, 17]
    assert "'?.'" in diags[0].message and diags[0].severity.value == "error"


def test_call_cast_and_this_at_the_top():
    code = _NODES + (
        "метод Проба(Б: Узел, Объ: Объект)\n"
        "    Узлы() = Б\n"
        "    Б.Получить() = Б\n"
        "    Объ как Узел = Б\n"
        ";\n"
        "\n"
        "структура Лист\n"
        "    метод Заменить()\n"
        "        этот = новый Лист()\n"
        "    ;\n"
        ";\n"
    )
    diags = _diags(code, TARGET)
    assert [(d.line, d.col) for d in diags] == [(15, 5), (16, 5), (17, 5), (22, 9)]
    assert "'Узлы()'" in diags[0].message
    assert "'Объ как Узел'" in diags[2].message
    assert "'этот'" in diags[3].message


def test_accesses_that_receive_a_value():
    code = _NODES + (
        "метод Проба(А: Узел?, Мас: Массив<Число>, Объ: Объект, Б: Узел)\n"
        "    А! = Б\n"
        "    А!.Значение = 1\n"
        "    (Объ как Узел).Значение = 1\n"
        "    Мас[0] = 1\n"
        "    Узлы().Значение = 1\n"
        "    Узлы().Дети[0] = 1\n"
        ";\n"
    )
    assert _diags(code, TARGET) == []


def test_target_in_a_short_lambda_and_english_spelling():
    code = (
        "method Probe(Items: Array<Node?>)\n"
        "    Items.ForEach(Item -> Item?.Value = 1)\n"
        ";\n"
    )
    assert _lines(code, TARGET) == [2]
