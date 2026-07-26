"""Tests of the code/call-arity rule: call argument count against the module method signature."""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/call-arity"}, scopes=("file",)))


_SIG = (
    "метод Сумма(А: Число, Б: Число = 0): Число\n"
    "    возврат А + Б\n"
    ";\n"
)


def test_too_many_arguments():
    diags = _lint(_SIG + "метод Тест()\n    Сумма(1, 2, 3)\n;\n")
    assert len(diags) == 1
    assert "не больше 2" in diags[0].message


def test_too_few_arguments():
    diags = _lint(_SIG + "метод Тест()\n    Сумма()\n;\n")
    assert len(diags) == 1
    assert "не меньше 1" in diags[0].message


def test_optional_range_is_fine():
    diags = _lint(_SIG + "метод Тест()\n    Сумма(1)\n    Сумма(1, 2)\n;\n")
    assert diags == [], [d.message for d in diags]


def test_named_arguments_are_skipped():
    diags = _lint(_SIG + "метод Тест()\n    Сумма(А = 1, Б = 2)\n;\n")
    assert diags == []


def test_shadowed_name_is_skipped():
    # a variable holding a lambda shadows the method - the lambda's arity is unknown to the rule
    diags = _lint(
        _SIG
        + "метод Тест()\n"
        "    знч Сумма = метод (А: Число, Б: Число, В: Число) -> А + Б + В\n"
        "    Сумма(1, 2, 3)\n"
        ";\n"
    )
    assert diags == []


def test_static_struct_method():
    diags = _lint(
        "структура Точка\n"
        "    знч Х: Число = 0\n"
        "    статический метод Ноль(): Точка\n"
        "        возврат новый Точка()\n"
        "    ;\n"
        ";\n"
        "метод Тест()\n"
        "    Точка.Ноль(7)\n"
        ";\n"
    )
    assert len(diags) == 1


def test_unknown_callee_is_silent():
    diags = _lint("метод Тест()\n    Чужой(1, 2, 3)\n;\n")
    assert diags == []
