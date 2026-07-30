"""Tests of the code/unclosed-resource rule: an early exit from a loop over a closeable.

The platform closes a query result once the pass over it is over, so only a `возврат` or a
`прервать` in the middle of the loop leaks it. The rule therefore has to tell those apart, and
the negative cases below are what buys it the right to be on by default.
"""

from __future__ import annotations

import pytest

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources
from xbsl.parser import parse

QUERY = "Запрос{ ВЫБРАТЬ З.Ссылка КАК Ссылка, З.Важность КАК Важность ИЗ Задачи КАК З }.Выполнить()"


def _lint(code: str) -> list[Diagnostic]:
    """Lint one fixture, having first proved that it parses.

    The rule bails out on a module the parser rejects, so a typo in a fixture would turn every
    negative test green without checking anything. The assertion keeps the silence honest.
    """
    src = load_text("КарточкаЗадачи.xbsl", code)
    _module, errors = parse(src)
    assert not errors, f"фикстура не разобралась парсером: {errors}"
    return list(run_sources([src], select={"code/unclosed-resource"}, scopes=("file",)))


def _loop(declaration: str, body: str, tail: str = '    возврат ""\n') -> str:
    return (
        "метод НайтиВажную(): Строка\n"
        f"    {declaration} = {QUERY}\n"
        "    для Задача из Выборка\n"
        f"{body}"
        "    ;\n"
        f"{tail}"
        ";\n"
    )


# --- positive control --------------------------------------------------------------------

def test_early_return_from_the_loop_is_flagged():
    diags = _lint(_loop("знч Выборка", "        возврат Задача.Ссылка.ВСтроку()\n"))
    assert len(diags) == 1
    assert diags[0].rule_id == "code/unclosed-resource"
    assert "Выборка" in diags[0].message
    assert "РезультатЗапроса" in diags[0].message
    assert "исп" in diags[0].message
    assert diags[0].line == 2  # reported at the declaration - that is where the fix goes


def test_early_break_from_the_loop_is_flagged():
    code = (
        "метод СосчитатьВажные(Предел: Число): Число\n"
        "    пер Число1 = 0\n"
        f"    пер Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        если Число1 >= Предел\n"
        "            прервать\n"
        "        ;\n"
        "        Число1 = Число1 + 1\n"
        "    ;\n"
        "    возврат Число1\n"
        ";\n"
    )
    diags = _lint(code)
    assert len(diags) == 1
    assert "прервать" in diags[0].message


def test_return_nested_in_conditions_is_still_an_exit():
    body = (
        "        если Задача.Важность > 5\n"
        "            если Истина\n"
                     # a возврат at any depth leaves the method, and the loop with it
        "                возврат Задача.Ссылка.ВСтроку()\n"
        "            ;\n"
        "        ;\n"
    )
    assert len(_lint(_loop("знч Выборка", body))) == 1


# --- negative control --------------------------------------------------------------------

def test_resource_declared_with_use_is_silent():
    """`исп` closes the resource on every exit path - this is the cure the rule advises."""
    assert _lint(_loop("исп Выборка", "        возврат Задача.Ссылка.ВСтроку()\n")) == []


def test_full_pass_is_silent():
    code = (
        "метод СосчитатьВсе(): Число\n"
        "    пер Число1 = 0\n"
        f"    знч Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        Число1 = Число1 + Задача.Важность\n"
        "    ;\n"
        "    возврат Число1\n"
        ";\n"
    )
    assert _lint(code) == []


def test_continue_is_not_an_exit():
    code = (
        "метод СосчитатьВажные(): Число\n"
        "    пер Число1 = 0\n"
        f"    знч Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        если Задача.Важность == 0\n"
        "            продолжить\n"
        "        ;\n"
        "        Число1 = Число1 + 1\n"
        "    ;\n"
        "    возврат Число1\n"
        ";\n"
    )
    assert _lint(code) == []


def test_query_result_without_a_loop_is_silent():
    code = (
        "метод ЕстьЗадачи(): Булево\n"
        f"    знч Выборка = {QUERY}\n"
        "    возврат не Выборка.Пусто()\n"
        ";\n"
    )
    assert _lint(code) == []


def test_loop_over_a_non_closeable_is_silent():
    code = (
        "метод Первая(Названия: Массив<Строка>): Строка\n"
        "    знч Выборка = Названия\n"
        "    для Название из Выборка\n"
        "        возврат Название\n"
        "    ;\n"
        '    возврат ""\n'
        ";\n"
    )
    assert _lint(code) == []


def test_break_of_a_nested_loop_says_nothing_about_ours():
    """`прервать` leaves the innermost loop - the outer pass still runs to the end."""
    code = (
        "метод Пересечь(Названия: Массив<Строка>): Число\n"
        "    пер Число1 = 0\n"
        f"    знч Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        для Название из Названия\n"
        "            если Название == \"\"\n"
        "                прервать\n"
        "            ;\n"
        "        ;\n"
        "        Число1 = Число1 + 1\n"
        "    ;\n"
        "    возврат Число1\n"
        ";\n"
    )
    assert _lint(code) == []


def test_the_loop_binds_to_the_declaration_of_its_own_method():
    """A namesake in another method must not lend its declaration to this loop.

    Keyed by name alone, `Выборка` declared under `знч` anywhere in the file would make every
    loop over any `Выборка` a finding - the shape that produced pure noise before the scoping
    was added.
    """
    code = (
        "метод Первый(): Строка\n"
        f"    исп Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        возврат Задача.Ссылка.ВСтроку()\n"
        "    ;\n"
        '    возврат ""\n'
        ";\n"
        "\n"
        "метод Второй(Выборка: Массив<Строка>): Строка\n"
        "    для Название из Выборка\n"
        "        возврат Название\n"
        "    ;\n"
        '    возврат ""\n'
        ";\n"
    )
    assert _lint(code) == []


def test_resource_arriving_as_a_parameter_belongs_to_the_caller():
    code = (
        "метод Первая(Выборка: РезультатЗапроса): Строка\n"
        "    для Задача из Выборка\n"
        "        возврат Задача.Ссылка.ВСтроку()\n"
        "    ;\n"
        '    возврат ""\n'
        ";\n"
    )
    assert _lint(code) == []


def test_closing_by_hand_is_left_alone():
    body = (
        "        если Задача.Важность > 5\n"
        "            Выборка.Закрыть()\n"
        "            возврат Задача.Ссылка.ВСтроку()\n"
        "        ;\n"
    )
    assert _lint(_loop("знч Выборка", body)) == []


def test_returning_the_resource_hands_it_to_the_caller():
    """The exception the docs spell out: the caller takes over the lifetime."""
    code = (
        "метод Взять(): РезультатЗапроса\n"
        f"    знч Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        возврат Выборка\n"
        "    ;\n"
        "    возврат Выборка\n"
        ";\n"
    )
    assert _lint(code) == []


def test_return_inside_a_lambda_returns_from_the_lambda():
    """A lambda body is not the method's control flow - its `возврат` is no early exit."""
    code = (
        "метод Названия(): Число\n"
        "    пер Число1 = 0\n"
        f"    знч Выборка = {QUERY}\n"
        "    для Задача из Выборка\n"
        "        знч Отбор = метод (Э) -> возврат Э.Важность > 0; \n"
        "        Число1 = Число1 + 1\n"
        "    ;\n"
        "    возврат Число1\n"
        ";\n"
    )
    assert _lint(code) == []


# --- the catalog behind the rule ----------------------------------------------------------

def test_closeable_set_comes_from_the_type_hierarchy():
    """A closeable is recognized by inheriting Закрываемое, not by a list kept here."""
    from xbsl.rules import closeable

    closeable._catalog.cache_clear()
    types, returns = closeable._catalog()
    if not types:
        pytest.skip("нет данных Элемента")
    assert "РезультатЗапроса" in types
    assert "QueryResult" in types  # the English spelling answers the same
    assert "Массив" not in types
    assert returns["ТипизированныйЗапрос"]["Выполнить"].startswith("РезультатЗапроса")


def test_rule_is_silent_without_the_catalog(monkeypatch):
    """No data - no rule: a closeable cannot be told from anything else, so stay quiet.

    Only the rule's own table is emptied. Patching `dataset.load_json` instead would also take
    away language.json, the module would stop parsing, and the silence would prove nothing.
    """
    from xbsl.rules import closeable

    monkeypatch.setattr(closeable, "_catalog", lambda: (frozenset(), {}))
    assert _lint(_loop("знч Выборка", "        возврат Задача.Ссылка.ВСтроку()\n")) == []
