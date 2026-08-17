"""Tests of code/use-needs-closeable: the `исп` modifier over a non-closeable type.

`исп` is defined for a variable whose type descends from `Closeable`, and the compiler
answers "Type XmlReader is not Closeable" otherwise. The verdict comes from the type
catalog, so the negative cases below - an unresolved chain and a type the catalog does not
describe - are what buys the rule the right to be on by default.
"""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources
from xbsl.parser import parse

RULE = "code/use-needs-closeable"


def _lint(code: str) -> list[Diagnostic]:
    """Lint one fixture, having first proved that it parses.

    The rule bails out on a module the parser rejects, so a typo in a fixture would turn
    every negative test green without checking anything.
    """
    src = load_text("Обработка.xbsl", code)
    _module, errors = parse(src)
    assert not errors, f"фикстура не разобралась парсером: {errors}"
    return list(run_sources([src], select={RULE}, scopes=("file",)))


def _method(body: str) -> str:
    return "метод Прочитать()\n" + body + ";\n"


# --- positive control --------------------------------------------------------------------

def test_constructor_of_a_non_closeable_is_flagged():
    diags = _lint(_method("    исп Чтение = новый ЧтениеXml()\n"))
    assert len(diags) == 1, [d.message for d in diags]
    assert diags[0].rule_id == RULE
    assert (diags[0].line, diags[0].col) == (2, 5)
    assert "ЧтениеXml" in diags[0].message and "Закрываемое" in diags[0].message


def test_a_written_type_is_judged_as_well():
    diags = _lint(_method("    исп Чтение: ЧтениеXml = новый ЧтениеXml()\n"))
    assert len(diags) == 1, [d.message for d in diags]


def test_a_declaration_inside_a_branch_is_reached():
    diags = _lint(_method(
        "    если Истина тогда\n"
        "        исп Чтение = новый ЧтениеXml()\n"
        "    ;\n"
    ))
    assert len(diags) == 1, [d.message for d in diags]
    assert diags[0].line == 3


# --- negative control --------------------------------------------------------------------

def test_a_closeable_is_exactly_what_the_modifier_is_for():
    diags = _lint(_method(
        "    исп Выборка = Запрос{ ВЫБРАТЬ 1 КАК Один }.Выполнить()\n"
    ))
    assert diags == [], [d.message for d in diags]


def test_another_modifier_over_the_same_type_is_not_judged():
    diags = _lint(_method(
        "    знч Чтение = новый ЧтениеXml()\n"
        "    Сообщить(Чтение.ВСтроку())\n"
    ))
    assert diags == [], [d.message for d in diags]


def test_a_type_the_catalog_does_not_describe_is_left_alone():
    """A project type has unknown ancestors - unknown is not the same as "not closeable"."""
    diags = _lint(_method("    исп Сессия = новый СессияЗагрузки()\n"))
    assert diags == [], [d.message for d in diags]


def test_an_unresolved_chain_is_left_alone():
    diags = _lint(_method("    исп Ответ = Соединение.Получить(Запрос)\n"))
    assert diags == [], [d.message for d in diags]
