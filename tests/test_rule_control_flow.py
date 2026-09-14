"""Unreachable code and misplaced jumps (xbsl/rules/control_flow.py).

The forms and their controls repeat what the IDE language server answered on probe projects:
what ends a block (and what does not - a loop, an `если` without `иначе`), which statement is
reported, and where `прервать`, `продолжить` and `возврат` may not stand.
"""

import pytest

from xbsl.engine import load_text, run_sources

pytestmark = pytest.mark.needs_data  # the rules parse the module; the lexer reads the data

UNREACHABLE = "code/unreachable-statement"
JUMP = "code/misplaced-jump"


def _diags(code: str, rule: str) -> list:
    return run_sources([load_text("Модуль.xbsl", code)], select={rule}, scopes=("file",))


def _lines(code: str, rule: str) -> list[int]:
    return [d.line for d in _diags(code, rule)]


# --- code/unreachable-statement ------------------------------------------------------------


def test_after_return_throw_break_and_continue():
    code = (
        "метод Проба(Числа: Массив<Число>): Число\n"
        "    пер Итог = 0\n"
        "    для Н из Числа\n"
        "        прервать\n"
        "        Итог += Н\n"
        "    ;\n"
        "    для Н из Числа\n"
        "        продолжить\n"
        "        Итог += Н\n"
        "    ;\n"
        "    если Итог > 0\n"
        "        выбросить новый ИсключениеНедопустимоеСостояние(\"проба\")\n"
        "        Итог = 1\n"
        "    ;\n"
        "    возврат Итог\n"
        "    // только комментарий\n"
        "    Итог = 2\n"
        "    Итог = 3\n"
        ";\n"
    )
    diags = _diags(code, UNREACHABLE)
    assert [(d.line, d.col) for d in diags] == [(5, 9), (9, 9), (13, 9), (17, 5)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'прервать'" in diags[0].message and "'возврат'" in diags[3].message


def test_every_ending_statement_reports_the_next_one():
    code = "метод Проба(): Число\n    возврат 1\n    возврат 2\n    возврат 3\n;\n"
    assert _lines(code, UNREACHABLE) == [3, 4]


def test_branches_that_all_end():
    code = (
        "метод Проба(Флаг: Булево, Номер: Число): Число\n"
        "    если Флаг\n"
        "        возврат 1\n"
        "    иначе если Номер > 0\n"
        "        возврат 2\n"
        "    иначе\n"
        "        выбросить новый ИсключениеНедопустимоеСостояние(\"а\")\n"
        "    ;\n"
        "    Номер.ВСтроку()\n"
        "    выбор Номер\n"
        "        когда 1\n"
        "            возврат 1\n"
        "        иначе\n"
        "            возврат 2\n"
        "    ;\n"
        "    Номер.ВСтроку()\n"
        "    попытка\n"
        "        возврат 1\n"
        "    поймать Искл: Исключение\n"
        "        выбросить Искл\n"
        "    вконце\n"
        "        Номер.ВСтроку()\n"
        "    ;\n"
        "    Номер.ВСтроку()\n"
        "    область\n"
        "        возврат 3\n"
        "    ;\n"
        "    возврат 4\n"
        ";\n"
    )
    diags = _diags(code, UNREACHABLE)
    assert [d.line for d in diags] == [9, 16, 24, 28]
    assert "'если'" in diags[0].message and "'попытка'" in diags[2].message


def test_a_branch_ends_on_any_of_its_statements():
    code = (
        "метод Проба(Флаг: Булево, Числа: Массив<Число>): Число\n"
        "    для Н из Числа\n"
        "        если Н > 0\n"
        "            прервать\n"
        "        иначе\n"
        "            продолжить\n"
        "        ;\n"
        "        Н.ВСтроку()\n"
        "    ;\n"
        "    если Флаг\n"
        "        возврат 1\n"
        "        Флаг.ВСтроку()\n"
        "    иначе\n"
        "        возврат 2\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _lines(code, UNREACHABLE) == [8, 12, 16]


def test_blocks_that_may_fall_through_stay_silent():
    code = (
        "метод Проба(Флаг: Булево, Номер: Число, Числа: Массив<Число>): Число\n"
        "    для Н из Числа\n"
        "        если Н > 0\n"
        "            прервать\n"
        "        ;\n"
        "        Н.ВСтроку()\n"
        "    ;\n"
        "    если Флаг\n"
        "        возврат 1\n"
        "    иначе если Номер > 0\n"
        "        возврат 2\n"
        "    ;\n"
        "    пока Истина\n"
        "        возврат 3\n"
        "    ;\n"
        "    попытка\n"
        "        возврат 4\n"
        "    поймать Искл: Исключение\n"
        "        Номер.ВСтроку()\n"
        "    ;\n"
        "    выбор Номер\n"
        "        когда 1\n"
        "            возврат 5\n"
        "    ;\n"
        "    если Флаг\n"
        "        возврат 6\n"
        "    иначе\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _diags(code, UNREACHABLE) == []


def test_never_returning_method_of_the_file():
    code = (
        "метод Стоп(): никогда\n"
        "    выбросить новый ИсключениеНедопустимоеСостояние(\"проба\")\n"
        ";\n"
        "\n"
        "метод Проба(): Число\n"
        "    Стоп()\n"
        "    возврат 1\n"
        ";\n"
        "\n"
        "метод Значение(): Число\n"
        "    знч Результат = Стоп()\n"
        "    пер Х = 0\n"
        "    Х = Стоп()\n"
        "    возврат Результат + Х\n"
        ";\n"
    )
    diags = _diags(code, UNREACHABLE)
    assert [(d.line, d.col) for d in diags] == [(7, 5), (11, 5), (13, 5)]
    assert "'Стоп'" in diags[0].message


def test_never_call_is_not_judged_when_the_name_may_mean_something_else():
    code = (
        "метод Стоп(): никогда\n"
        "    выбросить новый ИсключениеНедопустимоеСостояние(\"проба\")\n"
        ";\n"
        "\n"
        "метод Стоп(Код: Число): Число\n"
        "    возврат Код\n"
        ";\n"
        "\n"
        "метод Выход(): никогда\n"
        "    выбросить новый ИсключениеНедопустимоеСостояние(\"проба\")\n"
        ";\n"
        "\n"
        "метод Проба(Выход: () -> ничто): Число\n"
        "    Стоп()\n"
        "    Выход()\n"
        "    Модуль.Выход()\n"
        "    Прервать()\n"
        "    возврат 1\n"
        ";\n"
    )
    assert _diags(code, UNREACHABLE) == []


def test_lambda_body_is_a_block_of_its_own():
    code = (
        "метод Проба(Числа: Массив<Число>): Число\n"
        "    знч Строки = Числа.Преобразовать(метод(Н) ->\n"
        "        возврат Н.ВСтроку()\n"
        "        Н.ВСтроку()\n"
        "    ;)\n"
        "    возврат Строки.Размер()\n"
        ";\n"
    )
    assert _lines(code, UNREACHABLE) == [4]


def test_switch_covering_every_value_of_a_typed_subject():
    code = (
        "перечисление Цвет\n"
        "    Красный,\n"
        "    Зеленый\n"
        "\n"
        "    метод Код(): Число\n"
        "        выбор этот\n"
        "            когда Цвет.Красный\n"
        "                возврат 1\n"
        "            когда Цвет.Зеленый\n"
        "                возврат 2\n"
        "        ;\n"
        "        возврат 0\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод ПоЦвету(Значение: Цвет, Флаг: Булево, Объ: Объект): Число\n"
        "    выбор Значение\n"
        "        когда == Цвет.Красный\n"
        "            возврат 1\n"
        "        когда Цвет.Зеленый\n"
        "            возврат 2\n"
        "    ;\n"
        "    Флаг.ВСтроку()\n"
        "    выбор Флаг\n"
        "        когда Истина\n"
        "            возврат 1\n"
        "        когда Ложь\n"
        "            возврат 2\n"
        "    ;\n"
        "    Флаг.ВСтроку()\n"
        "    выбор Объ\n"
        "        когда это Строка\n"
        "            возврат 1\n"
        "        когда это Объект\n"
        "            возврат 2\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _lines(code, UNREACHABLE) == [12, 23, 30, 37]


def test_switch_that_leaves_a_value_out_stays_silent():
    code = (
        "перечисление Цвет\n"
        "    Красный,\n"
        "    Зеленый\n"
        ";\n"
        "\n"
        "метод Проба(Значение: Цвет, Пустой: Булево?, Объ: Объект, Номер: Число): Число\n"
        "    выбор Значение\n"
        "        когда Цвет.Красный\n"
        "            возврат 1\n"
        "    ;\n"
        "    выбор Пустой\n"
        "        когда Истина\n"
        "            возврат 1\n"
        "        когда Ложь\n"
        "            возврат 2\n"
        "    ;\n"
        "    выбор Объ\n"
        "        когда это Строка\n"
        "            возврат 1\n"
        "    ;\n"
        "    выбор Номер\n"
        "        когда 1\n"
        "            возврат 1\n"
        "    ;\n"
        "    выбор Значение\n"
        "        когда Цвет.Красный\n"
        "            возврат 1\n"
        "        когда Цвет.Зеленый\n"
        "            Номер.ВСтроку()\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _diags(code, UNREACHABLE) == []


def test_english_spelling():
    code = (
        "method Stop(): never\n"
        "    throw new IllegalStateException(\"probe\")\n"
        ";\n"
        "\n"
        "method Probe(Items: Array<Number>): Number\n"
        "    for Item in Items\n"
        "        break\n"
        "        Item.ToString()\n"
        "    ;\n"
        "    Stop()\n"
        "    return 1\n"
        ";\n"
    )
    assert _lines(code, UNREACHABLE) == [8, 11]


# --- code/misplaced-jump -------------------------------------------------------------------


def test_break_and_continue_outside_a_loop():
    code = (
        "метод Проба(Флаг: Булево, Номер: Число, Числа: Массив<Число>)\n"
        "    если Флаг\n"
        "        прервать\n"
        "    ;\n"
        "    выбор Номер\n"
        "        когда 1\n"
        "            продолжить\n"
        "    ;\n"
        "    Числа.ДляКаждого(метод(М) ->\n"
        "        прервать\n"
        "    ;)\n"
        ";\n"
    )
    diags = _diags(code, JUMP)
    assert [(d.line, d.col) for d in diags] == [(3, 9), (7, 13), (10, 9)]
    assert all(d.severity.value == "error" for d in diags)
    assert "'прервать'" in diags[0].message and "цикла" in diags[0].message


def test_jumps_inside_a_loop_are_fine():
    code = (
        "метод Проба(Числа: Массив<Число>)\n"
        "    для Н из Числа\n"
        "        выбор Н\n"
        "            когда 1\n"
        "                прервать\n"
        "        ;\n"
        "        попытка\n"
        "            Числа.Размер()\n"
        "        поймать Искл: Исключение\n"
        "            продолжить\n"
        "        ;\n"
        "        Числа.ДляКаждого(метод(М) ->\n"
        "            прервать\n"
        "        ;)\n"
        "    ;\n"
        "    попытка\n"
        "        Числа.Размер()\n"
        "    вконце\n"
        "        для Н из Числа\n"
        "            прервать\n"
        "        ;\n"
        "    ;\n"
        ";\n"
    )
    assert _diags(code, JUMP) == []


def test_jumps_out_of_a_finally_section():
    code = (
        "метод Проба(Флаг: Булево, Числа: Массив<Число>): Число\n"
        "    для Н из Числа\n"
        "        попытка\n"
        "            Числа.Размер()\n"
        "        вконце\n"
        "            продолжить\n"
        "        ;\n"
        "    ;\n"
        "    попытка\n"
        "        возврат 1\n"
        "    вконце\n"
        "        если Флаг\n"
        "            возврат 2\n"
        "        ;\n"
        "        Числа.ДляКаждого(метод(М) ->\n"
        "            возврат\n"
        "        ;)\n"
        "        выбросить новый ИсключениеНедопустимоеСостояние(\"в\")\n"
        "    ;\n"
        ";\n"
    )
    diags = _diags(code, JUMP)
    assert [(d.line, d.col) for d in diags] == [(6, 13), (13, 13), (16, 13)]
    assert "'вконце'" in diags[0].message


def test_break_outside_loop_inside_finally_is_reported_once():
    code = (
        "метод Проба(Числа: Массив<Число>)\n"
        "    попытка\n"
        "        Числа.Размер()\n"
        "    вконце\n"
        "        прервать\n"
        "    ;\n"
        ";\n"
    )
    diags = _diags(code, JUMP)
    assert len(diags) == 1 and "цикла" in diags[0].message


def test_english_jump_spelling():
    code = (
        "method Probe(Items: Array<Number>)\n"
        "    try\n"
        "        Items.Size()\n"
        "    finally\n"
        "        for Item in Items\n"
        "            continue\n"
        "        ;\n"
        "        return\n"
        "    ;\n"
        "    break\n"
        ";\n"
    )
    diags = _diags(code, JUMP)
    assert [d.line for d in diags] == [8, 10]
    assert "'return'" in diags[0].message and "'break'" in diags[1].message
