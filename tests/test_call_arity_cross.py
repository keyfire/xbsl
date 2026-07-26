"""Tests of the code/call-arity-cross rule: arity of a Модуль.Метод(...) call against the
target module's signature (project scope)."""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources

_TARGET = (
    "метод Сумма(А: Число, Б: Число = 0): Число\n"
    "    возврат А + Б\n"
    ";\n"
)


def _lint(caller: str, *extra: tuple[str, str]) -> list[Diagnostic]:
    sources = [load_text("Служебный.xbsl", _TARGET), load_text("Вызывающий.xbsl", caller)]
    for name, text in extra:
        sources.append(load_text(name, text))
    return [
        d for d in run_sources(sources, select={"code/call-arity-cross"})
        if d.rule_id == "code/call-arity-cross"
    ]


def test_too_many_arguments_cross_module():
    diags = _lint("метод Тест()\n    Служебный.Сумма(1, 2, 3)\n;\n")
    assert len(diags) == 1
    assert "Служебный.Сумма" in diags[0].message and "не больше 2" in diags[0].message


def test_valid_range_is_fine():
    diags = _lint("метод Тест()\n    Служебный.Сумма(1)\n    Служебный.Сумма(1, 2)\n;\n")
    assert diags == [], [d.message for d in diags]


def test_unknown_method_is_silent():
    diags = _lint("метод Тест()\n    Служебный.НетТакого(1, 2, 3)\n;\n")
    assert diags == []


def test_twin_module_names_are_silent():
    # two modules with the same name in different directories - the target cannot be proven
    diags = _lint(
        "метод Тест()\n    Служебный.Сумма(1, 2, 3)\n;\n",
        ("Другое/Служебный.xbsl", "метод Сумма(А: Число, Б: Число, В: Число): Число\n    возврат А\n;\n"),
    )
    assert diags == []


def test_shadowed_base_is_silent():
    diags = _lint(
        "метод Тест(Служебный: МойТип)\n    Служебный.Сумма(1, 2, 3)\n;\n"
    )
    assert diags == []


def test_stdlib_shadow_is_silent():
    # the module name coincides with a stdlib name - the call may be going to the platform
    sources = [
        load_text("Пользователи.xbsl", _TARGET),
        load_text("Вызывающий.xbsl", "метод Тест()\n    Пользователи.Сумма(1, 2, 3)\n;\n"),
    ]
    diags = [
        d for d in run_sources(sources, select={"code/call-arity-cross"})
        if d.rule_id == "code/call-arity-cross"
    ]
    assert diags == []
