"""Repetitions the compiler refuses (xbsl/rules/repetitions.py).

The forms and their controls repeat what the IDE language server answered on probe projects: a
repeated value or type in `когда`, a repeated exception type in `поймать`, and one name declared
twice where names are compared ignoring letter case.
"""

import pytest

from xbsl.engine import load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rules parse the module; the lexer reads the data

WHEN = "code/duplicate-when"
CATCH = "code/duplicate-catch"
DECLARATION = "code/duplicate-declaration"


def _diags(code: str, rule: str) -> list:
    return run_sources([load_text("Модуль.xbsl", code)], select={rule}, scopes=("file",))


def _places(code: str, rule: str) -> list[tuple[int, int]]:
    return [(d.line, d.col) for d in _diags(code, rule)]


# --- code/duplicate-when --------------------------------------------------------------------

_SIGNALS = "перечисление Сигнал\n    Красный,\n    Зеленый\n;\n\n"


def test_repeated_values():
    code = _SIGNALS + (
        "метод Проба(Номер: Число, Текст: Строка, Флаг: Булево, Сигн: Сигнал): Число\n"
        "    выбор Номер\n"
        "        когда 1\n"
        "            возврат 1\n"
        "        когда 1.0\n"
        "            возврат 2\n"
        "        когда -3, -3\n"
        "            возврат 3\n"
        "    ;\n"
        "    выбор Текст\n"
        "        когда \"а\", \"а\"\n"
        "            возврат 4\n"
        "    ;\n"
        "    выбор Флаг\n"
        "        когда Истина\n"
        "            возврат 5\n"
        "        когда True\n"
        "            возврат 6\n"
        "    ;\n"
        "    выбор Сигн\n"
        "        когда Сигнал.Красный\n"
        "            возврат 7\n"
        "        когда Сигнал.Красный\n"
        "            возврат 8\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    diags = _diags(code, WHEN)
    assert [(d.line, d.col) for d in diags] == [(10, 15), (12, 19), (16, 20), (22, 15), (28, 15)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'1.0'" in diags[0].message


def test_repeated_types():
    code = (
        "метод Проба(Значение: Объект?, Другое: Объект): Число\n"
        "    выбор Значение\n"
        "        когда это Строка?\n"
        "            возврат 1\n"
        "        когда это Неопределено\n"
        "            возврат 2\n"
        "    ;\n"
        "    выбор Другое\n"
        "        когда это Строка|Число\n"
        "            возврат 3\n"
        "        когда это Число\n"
        "            возврат 4\n"
        "        когда это String\n"
        "            возврат 5\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _places(code, WHEN) == [(5, 15), (11, 15), (13, 15)]


def test_when_values_the_file_does_not_know_stay_silent():
    code = (
        "метод Проба(Номер: Число, Порог: Число, Другое: Объект): Число\n"
        "    выбор Номер\n"
        "        когда Порог\n"
        "            возврат 1\n"
        "        когда Порог\n"
        "            возврат 2\n"
        "        когда == 7\n"
        "            возврат 3\n"
        "        когда == 7\n"
        "            возврат 4\n"
        "        когда 1\n"
        "            возврат 5\n"
        "        когда \"1\"\n"
        "            возврат 6\n"
        "    ;\n"
        "    выбор Другое\n"
        "        когда это Объект\n"
        "            возврат 7\n"
        "        когда это Строка\n"
        "            возврат 8\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _diags(code, WHEN) == []


# --- code/duplicate-catch -------------------------------------------------------------------


def test_repeated_exception_types():
    code = (
        "метод Проба(): Число\n"
        "    попытка\n"
        "        возврат 1\n"
        "    поймать А: ИсключениеНедопустимоеСостояние\n"
        "        возврат 2\n"
        "    поймать Б: ИсключениеНедопустимыйАргумент | ИсключениеНедопустимоеСостояние\n"
        "        возврат 3\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод Написания(): Число\n"
        "    попытка\n"
        "        возврат 1\n"
        "    поймать А: ИсключениеНедопустимоеСостояние|IllegalStateException\n"
        "        возврат 2\n"
        "    ;\n"
        ";\n"
    )
    diags = _diags(code, CATCH)
    assert [(d.line, d.col) for d in diags] == [(6, 49), (14, 48)]
    assert all(d.severity.value == "error" for d in diags)


def test_hierarchy_and_nested_attempts_are_legal():
    code = (
        "метод Проба(): Число\n"
        "    попытка\n"
        "        попытка\n"
        "            возврат 1\n"
        "        поймать А: ИсключениеНедопустимоеСостояние\n"
        "            возврат 2\n"
        "        ;\n"
        "    поймать Б: Исключение\n"
        "        возврат 3\n"
        "    поймать В: ИсключениеНедопустимоеСостояние\n"
        "        возврат 4\n"
        "    ;\n"
        ";\n"
    )
    assert _diags(code, CATCH) == []


# --- code/duplicate-declaration ---------------------------------------------------------------


def test_module_types_fields_items_and_constants():
    code = (
        "конст ПОРОГ = 1\n"
        "конст порог = 2\n"
        "\n"
        "структура Повтор\n"
        "    пер Поле: Число = 0\n"
        "    пер поле: Строка = \"\"\n"
        ";\n"
        "\n"
        "перечисление повтор\n"
        "    Малый умолчание,\n"
        "    малый,\n"
        "    Большой умолчание\n"
        ";\n"
        "\n"
        "исключение ИсключениеПробы\n"
        "    пер Описание: Строка = \"\"\n"
        "    пер Cause: Строка = \"\"\n"
        ";\n"
    )
    diags = _diags(code, DECLARATION)
    assert [(d.line, d.col) for d in diags] == [
        (2, 1), (6, 5), (9, 1), (11, 5), (12, 5), (16, 5), (17, 5),
    ]
    assert all(d.severity.value == "error" for d in diags)
    assert "строка 4" in diags[2].message


def test_methods_differing_in_case_but_not_overloads():
    code = (
        "метод Прочитать(): Число\n"
        "    возврат 1\n"
        ";\n"
        "\n"
        "@НаСервере\n"
        "метод прочитать(Сдвиг: Число): Число\n"
        "    возврат Сдвиг\n"
        ";\n"
        "\n"
        "метод Записать(): Число\n"
        "    возврат 1\n"
        ";\n"
        "\n"
        "метод Записать(Сдвиг: Число): Число\n"
        "    возврат Сдвиг\n"
        ";\n"
    )
    diags = _diags(code, DECLARATION)
    assert [(d.line, d.col) for d in diags] == [(6, 1)]
    assert "'Прочитать'" in diags[0].message


def test_parameters_and_locals():
    code = (
        "метод Проба(А: Число, а: Строка, Флаг: Булево, Числа: Массив<Число>): Число\n"
        "    знч Итог = 1\n"
        "    если Флаг\n"
        "        пер итог = 2\n"
        "    ;\n"
        "    для Итог из Числа\n"
        "    ;\n"
        "    попытка\n"
        "        Числа.Размер()\n"
        "    поймать Итог: Исключение\n"
        "        Числа.Размер()\n"
        "    ;\n"
        "    Числа.ДляКаждого(Итог -> Итог.ВСтроку())\n"
        "    Числа.ДляКаждого(метод(Н) ->\n"
        "        знч Флаг = Н\n"
        "    ;)\n"
        "    возврат Итог\n"
        ";\n"
    )
    diags = _diags(code, DECLARATION)
    assert [(d.line, d.col) for d in diags] == [
        (1, 23), (4, 9), (6, 9), (10, 13), (13, 22), (15, 9),
    ]


def test_legal_names_stay_silent():
    code = (
        "конст ПОРОГ = 1\n"
        "\n"
        "структура Ячейка\n"
        "    пер Значение: Число = 0\n"
        "\n"
        "    метод Сдвинуть(): Число\n"
        "        знч Значение = 1\n"
        "        возврат Значение\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод Проба(Флаг: Булево, Сумма: Число): Число\n"
        "    если Флаг\n"
        "        знч Ветка = 1\n"
        "        возврат Ветка\n"
        "    иначе\n"
        "        знч Ветка = 2\n"
        "        возврат Ветка\n"
        "    ;\n"
        "    знч ПОРОГ = 3\n"
        "    пер Сумма = 4\n"
        "    возврат ПОРОГ + Сумма\n"
        ";\n"
    )
    # `пер Сумма` repeats a parameter exactly: code/param-redeclared reports it, not this rule
    assert _diags(code, DECLARATION) == []


def test_english_spelling():
    code = (
        "structure Cell\n"
        "    var Value: Number = 0\n"
        "    var value: String = \"\"\n"
        ";\n"
        "\n"
        "method Probe(Items: Array<Number>): Number\n"
        "    val Total = 1\n"
        "    for total in Items\n"
        "    ;\n"
        "    return Total\n"
        ";\n"
    )
    assert _places(code, DECLARATION) == [(3, 5), (8, 9)]


def test_distinct_large_numeric_when_values_do_not_round_together():
    code = (
        "method Probe(Value: Number): Number\n"
        "    case Value\n"
        "        when 12345678901234567890123456781\n"
        "            return 1\n"
        "        when 12345678901234567890123456782\n"
        "            return 2\n"
        "        when 12345678901234567890123456781.0\n"
        "            return 3\n"
        "    ;\n"
        "    return 0\n"
        ";\n"
    )
    assert _places(code, WHEN) == [(7, 14)]
