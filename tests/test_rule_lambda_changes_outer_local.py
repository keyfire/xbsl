"""code/lambda-changes-outer-local: a lambda body assigns a local of the code around it.

Every case below was put through the editor's own language server first (a probe project of
its own, one module per case), and each test repeats its verdict: the lambda message, another
error (a read-only variable, a name not yet defined) or nothing. The silent cases select
code/parse-error as well - a silence that comes from a broken fixture would prove nothing.
"""

import pytest

from xbsl import engine

pytestmark = pytest.mark.needs_data

RULE = "code/lambda-changes-outer-local"


def _lint(content: str, name: str = "Модуль.xbsl"):
    diags = engine.run_sources([engine.load_text(name, content)],
                               select={RULE, "code/parse-error"})
    assert not [d for d in diags if d.rule_id == "code/parse-error"], [d.message for d in diags]
    return [d for d in diags if d.rule_id == RULE]


def _lines(diags) -> list[int]:
    return [d.line for d in diags]


# --- Reported --------------------------------------------------------------------------------

@pytest.mark.parametrize("op", ["=", "+=", "-=", "*=", "/="])
def test_a_short_lambda_assigns_a_variable_of_the_method(op):
    diags = _lint(
        "метод Посчитать()\n"
        "    пер Счётчик = 1\n"
        f"    знч Действие = () -> Счётчик {op} 2\n"
        "    Действие()\n"
        ";\n"
    )
    assert [(d.line, d.col) for d in diags] == [(3, 26)]
    assert "'Счётчик'" in diags[0].message and diags[0].severity.value == "error"


def test_a_full_lambda_assigns_inside_a_block_of_its_body():
    diags = _lint(
        "метод Посчитать()\n"
        "    пер Счётчик = 1\n"
        "    знч Действие = метод() ->\n"
        "        если Истина\n"
        "            Счётчик += 2\n"
        "        ;\n"
        "    ;\n"
        "    Действие()\n"
        ";\n"
    )
    assert _lines(diags) == [5]


def test_every_assignment_of_a_full_lambda_is_reported():
    diags = _lint(
        "метод Посчитать()\n"
        "    пер Первое = 1\n"
        "    пер Второе = 1\n"
        "    знч Действие = метод() ->\n"
        "        Первое = 2\n"
        "        Второе = 3\n"
        "    ;\n"
        "    Действие()\n"
        ";\n"
    )
    assert _lines(diags) == [5, 6]


def test_a_parameter_of_the_method_is_captured_too():
    diags = _lint(
        "метод Посчитать(Предел: Число)\n"
        "    знч Внешняя = метод() ->\n"
        "        знч Внутренняя = () -> Предел += 1\n"
        "        Внутренняя()\n"
        "    ;\n"
        "    Внешняя()\n"
        ";\n"
    )
    assert _lines(diags) == [3]


def test_an_inner_lambda_assigns_a_variable_and_a_parameter_of_the_outer_one():
    diags = _lint(
        "метод Посчитать()\n"
        "    знч Внешняя = метод(Значение: Число) ->\n"
        "        пер Сумма = 1\n"
        "        знч Внутренняя = метод() ->\n"
        "            Сумма = 2\n"
        "            Значение = 3\n"
        "        ;\n"
        "        Внутренняя()\n"
        "    ;\n"
        "    Внешняя(1)\n"
        ";\n"
    )
    assert _lines(diags) == [5, 6]


def test_a_parameter_of_an_outer_short_lambda_assigned_two_lambdas_deep():
    diags = _lint(
        "метод Посчитать()\n"
        "    знч Числа = [1, 2]\n"
        "    Числа.ДляКаждого(Элемент -> Числа.Фильтровать(Х -> Х > Элемент)"
        ".ДляКаждого(Х -> Элемент = Х))\n"
        ";\n"
    )
    assert _lines(diags) == [3]


def test_a_lambda_passed_to_a_call_and_as_a_named_argument():
    diags = _lint(
        "метод Применить(Действие: ()->ничто)\n"
        "    Действие()\n"
        ";\n"
        "\n"
        "метод Посчитать()\n"
        "    пер Сумма = 0\n"
        "    знч Числа = [1, 2]\n"
        "    Числа.ДляКаждого(Элемент -> Сумма += Элемент)\n"
        "    Применить(Действие = () -> Сумма = 2)\n"
        ";\n"
    )
    assert _lines(diags) == [8, 9]


def test_variables_of_blocks_around_the_lambda_are_outer_locals():
    diags = _lint(
        "метод Посчитать(Режим: Число)\n"
        "    для Элемент из [1, 2]\n"
        "        пер Сумма = Элемент\n"
        "        знч Действие = () -> Сумма += 1\n"
        "        Действие()\n"
        "    ;\n"
        "    попытка\n"
        "        пер Итог = 1\n"
        "        знч Действие = () -> Итог = 2\n"
        "        Действие()\n"
        "    поймать Ошибка: Исключение\n"
        "        возврат\n"
        "    ;\n"
        "    выбор Режим\n"
        "        когда 1\n"
        "            пер Доля = 1\n"
        "            знч Действие = () -> Доля = 2\n"
        "            Действие()\n"
        "    ;\n"
        ";\n"
    )
    assert _lines(diags) == [4, 9, 17]


def test_a_lambda_parameter_named_like_an_outer_local_does_not_take_the_name():
    """The parameter is refused, and inside the body the name keeps meaning the variable."""
    diags = _lint(
        "метод Посчитать(Предел: Число)\n"
        "    знч Действие = (Предел: Число) -> Предел = 1\n"
        "    Действие(2)\n"
        ";\n"
    )
    assert _lines(diags) == [2]


def test_a_parenthesized_target_is_the_same_variable():
    diags = _lint(
        "метод Посчитать()\n"
        "    пер Счётчик = 1\n"
        "    знч Действие = метод() ->\n"
        "        (Счётчик) = 2\n"
        "    ;\n"
        "    Действие()\n"
        ";\n"
    )
    assert [(d.line, d.col) for d in diags] == [(4, 10)]


def test_methods_of_a_structure_static_or_not():
    diags = _lint(
        "структура Счёт\n"
        "    пер Сумма: Число\n"
        "\n"
        "    метод Пересчитать()\n"
        "        пер Итог = 1\n"
        "        знч Действие = () -> Итог = 2\n"
        "        Действие()\n"
        "    ;\n"
        "\n"
        "    статический метод Посчитать()\n"
        "        пер Итог = 1\n"
        "        знч Действие = () -> Итог = 2\n"
        "        Действие()\n"
        "    ;\n"
        ";\n"
    )
    assert _lines(diags) == [6, 12]


def test_the_english_spelling():
    diags = _lint(
        "method Count()\n"
        "    var Counter = 1\n"
        "    val Action = () -> Counter += 2\n"
        "    Action()\n"
        ";\n",
        name="Module.xbsl",
    )
    assert [(d.line, d.col) for d in diags] == [(3, 24)]
    assert "'Counter'" in diags[0].message


# --- Silent ----------------------------------------------------------------------------------

def test_a_member_or_an_element_of_a_captured_value_may_change():
    """The variables here are assignable ones - a `пер` and a parameter - so the silence comes
    from the shape of the target, not from a read-only binding."""
    assert not _lint(
        "структура Партия\n"
        "    пер Остаток: Число\n"
        ";\n"
        "\n"
        "метод Посчитать(Запись: Партия)\n"
        "    пер Копия = новый Партия(0)\n"
        "    пер Числа = [1, 2]\n"
        "    знч Действие = метод() ->\n"
        "        Запись.Остаток += 1\n"
        "        Копия.Остаток = 1\n"
        "        Числа[0] = 5\n"
        "    ;\n"
        "    Действие()\n"
        ";\n"
    )


def test_a_variable_and_a_parameter_of_the_lambda_itself():
    assert not _lint(
        "метод Посчитать()\n"
        "    пер Сумма = 1\n"
        "    знч Действие = метод(Значение: Число) ->\n"
        "        пер Итог = Сумма\n"
        "        Итог = 2\n"
        "        Значение = 3\n"
        "    ;\n"
        "    Действие(1)\n"
        ";\n"
    )


def test_read_only_variables_are_another_error():
    """A `знч`, `исп`, loop or catch variable is refused as read-only wherever it is assigned."""
    assert not _lint(
        "метод Посчитать()\n"
        "    знч Предел = 1\n"
        "    исп Контекст = КонтекстДоступа.Привилегированный()\n"
        "    знч Действие = метод() ->\n"
        "        Предел = 2\n"
        "        Контекст = КонтекстДоступа.Привилегированный()\n"
        "    ;\n"
        "    для Элемент из [1, 2]\n"
        "        знч Шаг = () -> Элемент = 3\n"
        "        Шаг()\n"
        "    ;\n"
        "    для Индекс = 1 по 3\n"
        "        знч Шаг = () -> Индекс = 5\n"
        "        Шаг()\n"
        "    ;\n"
        "    попытка\n"
        "        Действие()\n"
        "    поймать Ошибка: Исключение\n"
        "        знч Шаг = () -> Ошибка = Ошибка\n"
        "        Шаг()\n"
        "    ;\n"
        ";\n"
    )


def test_names_that_are_not_locals():
    """A field of the structure by a bare name or through `этот`, and a name the method does not
    bind at all (a property of the element in a component module) - none is a captured local."""
    assert not _lint(
        "структура Счёт\n"
        "    пер Сумма: Число\n"
        "\n"
        "    метод Пересчитать()\n"
        "        знч Действие = метод() ->\n"
        "            Сумма = 1\n"
        "            этот.Сумма = 2\n"
        "            СобственнаяМодифицированность = Истина\n"
        "        ;\n"
        "        Действие()\n"
        "    ;\n"
        ";\n"
    )


def test_changes_outside_the_body_before_or_after_the_capture():
    """A change after the capture is refused by a message of its own - not this rule's."""
    assert not _lint(
        "метод Посчитать()\n"
        "    пер Счётчик = 1\n"
        "    Счётчик = 2\n"
        "    знч Действие = () -> Счётчик + 1\n"
        "    Счётчик = 3\n"
        "    Действие()\n"
        ";\n"
    )


def test_a_name_bound_only_after_the_lambda_or_in_a_sibling_block():
    assert not _lint(
        "метод Посчитать()\n"
        "    если Истина\n"
        "        пер Счётчик = 0\n"
        "    ;\n"
        "    знч Действие = метод() ->\n"
        "        пер Счётчик = 1\n"
        "        Счётчик = 2\n"
        "        пер Буфер = 1\n"
        "        Буфер = 2\n"
        "    ;\n"
        "    Действие()\n"
        "    пер Буфер = 3\n"
        ";\n"
    )


def test_a_variable_declared_again_in_the_body_and_a_loop_over_an_outer_name():
    """Both are refused as a repeated name; the repeated declaration takes the name over."""
    assert not _lint(
        "метод Посчитать()\n"
        "    пер Сообщение = \"а\"\n"
        "    пер Имя = \"\"\n"
        "    знч Печать = метод() ->\n"
        "        пер Сообщение = \"б\"\n"
        "        Сообщение = \"в\"\n"
        "        для Имя из [\"а\", \"б\"]\n"
        "        ;\n"
        "    ;\n"
        "    Печать()\n"
        ";\n"
    )


def test_a_lambda_in_the_initializer_of_the_variable_it_assigns():
    """The variable is not defined yet there - the compiler says that instead."""
    assert not _lint(
        "метод Вызвать(Действие: ()->ничто): Число\n"
        "    Действие()\n"
        "    возврат 1\n"
        ";\n"
        "\n"
        "метод Посчитать()\n"
        "    пер Итог = Вызвать(() -> Итог = 2)\n"
        ";\n"
    )


def test_a_method_that_does_not_parse_is_skipped():
    diags = engine.run_sources([engine.load_text(
        "Модуль.xbsl",
        "метод Посчитать()\n"
        "    пер Счётчик = 1\n"
        "    знч Действие = () -> Счётчик = 2\n"
        "    пер Сломано = (1 +\n"
        ";\n",
    )], select={RULE, "code/parse-error"})
    assert [d.rule_id for d in diags if d.rule_id == "code/parse-error"]
    assert not [d for d in diags if d.rule_id == RULE]


def test_the_message_names_the_variable_in_english():
    from xbsl import i18n

    i18n.set_lang("en")
    diags = _lint("метод М()\n    пер Счётчик = 1\n    знч Д = () -> Счётчик = 2\n    Д()\n;\n")
    assert diags and diags[0].message.startswith("The lambda changes 'Счётчик'")
