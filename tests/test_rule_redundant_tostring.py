"""`style/redundant-tostring` judges by position, not by the line.

The call is redundant only as the right operand of a `+` that already has a string literal
among the operands to its left, in one chain at one bracket depth: that is the one form the
platform converts implicitly. A `+` inside the receiver's own brackets, a number first, a call
passed as an argument - none of these is that form, and the rule stays quiet on them.
"""

from xbsl import engine

RULE = "style/redundant-tostring"


def _findings(body: str, name: str = "Модуль.xbsl"):
    src = engine.load_text(name, "метод Ф()\n" + body + ";\n")
    return engine.run_sources([src], select={RULE})


def _count(body: str) -> int:
    return len(_findings(body))


def test_tostring_after_a_string_literal_is_redundant():
    found = _findings('    знч Р = "Итерация №" + Счетчик.ВСтроку()\n')
    assert [(d.line, d.col) for d in found] == [(2, 36)]  # anchored at the method name


def test_tostring_after_a_string_and_a_value_is_redundant():
    assert _count('    знч Р = "а" + Прочее + Счетчик.ВСтроку()\n') == 1


def test_tostring_of_a_bracketed_sum_after_a_string_is_redundant():
    assert _count('    знч Стиль = "width:" + (Колонки + 2 * Отступ).ВСтроку() + "px"\n') == 1


def test_tostring_chain_across_lines_is_judged_whole():
    """The documentation's own example wraps the chain; both calls are redundant."""
    body = (
        '    пер Результат = "Итерация №" +\n'
        "                    Счетчик.ВСтроку() +\n"
        '                    " из " + Всего.ВСтроку()\n'
    )
    assert [d.line for d in _findings(body)] == [3, 4]


def test_tostring_first_in_the_chain_is_needed():
    """`Число + Строка` is not an addition the language defines: the call has to stay."""
    assert _count('    знч Стиль = Ширина.ВСтроку() + "px"\n') == 0


def test_tostring_of_a_bracketed_sum_first_is_needed():
    assert _count('    знч Стиль = (Колонки + 2 * Отступ).ВСтроку() + "px"\n') == 0


def test_tostring_of_a_bracketed_sum_assigned_alone_is_quiet():
    assert _count("    знч Т = (Верх + Линия).ВСтроку()\n") == 0


def test_tostring_added_to_a_string_variable_is_needed():
    """`Текст += X.ВСтроку() + ","`: the right side is evaluated first, and there a number is first."""
    assert _count('    Текст += Элемент.Код.ВСтроку() + ","\n') == 0


def test_tostring_passed_as_an_argument_is_quiet():
    assert _count('    знч Р = "а" + Преобразовать(Момент.ВСтроку())\n') == 0
    assert _count('    знч Р = Шаблон.Заменить("[размер]", Размер.ВСтроку())\n') == 0


def test_tostring_after_a_string_inside_arguments_is_redundant():
    assert _count('    Сообщить("Итого: " + Сумма.ВСтроку())\n') == 1


def test_tostring_in_a_ternary_branch_is_judged_by_its_own_chain():
    assert _count('    знч Р = Флаг ? "а" + Число.ВСтроку() : "б"\n') == 1
    assert _count('    знч Р = "а" + (Флаг ? Число.ВСтроку() : "б")\n') == 0


def test_tostring_followed_by_a_member_is_quiet():
    assert _count('    знч Р = "а" + Число.ВСтроку().Длина\n') == 0


def test_tostring_with_an_argument_is_quiet():
    assert _count('    знч Р = "а" + Число.ВСтроку(2)\n') == 0


def test_string_inside_a_call_to_the_left_does_not_count():
    """`Имя("x") + Номер.ВСтроку()`: the literal is an argument, the operand is the call's result."""
    assert _count('    знч Р = Имя("x") + Номер.ВСтроку()\n') == 0


def test_tostring_on_an_indexed_or_called_receiver_is_redundant():
    assert _count('    знч Р = "а" + Номера[0].ВСтроку()\n') == 1
    assert _count('    знч Р = "а" + Объект.Получить(1).Поле.ВСтроку()\n') == 1


def test_tostring_on_this_or_a_persistent_value_is_redundant():
    assert _count('    знч Р = "а" + этот.Номер.ВСтроку()\n') == 1
    assert _count('    знч Р = "а" + Значение!.ВСтроку()\n') == 1
    assert _count('    знч Р = "а" + Значение! + Номер.ВСтроку()\n') == 1


def test_tostring_english_spelling_is_judged_the_same():
    assert _count('    val R = "Iteration" + Counter.ToString()\n') == 1
    assert _count('    val R = Counter.ToString() + "px"\n') == 0


def test_tostring_without_any_concatenation_is_quiet():
    assert _count("    возврат Счетчик.ВСтроку()\n") == 0
