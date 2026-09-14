"""Tests of the code/call-arity rule: call argument count against the module method signature."""

from __future__ import annotations

import pytest

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


def test_valid_named_arguments_are_accepted():
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


def _named_call_lint(arguments, *, cross=False, signature="First: Number, Second: Number = 0"):
    target = f"method MergeValues({signature})\n;\n"
    prefix = "SampleApi." if cross else ""
    caller = f"method RunExample()\n    {prefix}MergeValues({arguments})\n;\n"
    sources = (
        [load_text("SampleApi.xbsl", target), load_text("Caller.xbsl", caller)]
        if cross else [load_text("Caller.xbsl", target + caller)]
    )
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    return list(run_sources(sources, select={rule_id}))



@pytest.mark.parametrize("cross", [False, True])
@pytest.mark.parametrize("arguments, message", [
    ("First = 1, First = 2", "повторно"),
    ("1, First = 2", "повторно"),
    ("Other = 1", "неизвестный параметр Other"),
    ("First = 1, 2", "позиционный аргумент после именованного"),
    ("Second = 2", "обязательный параметр First"),
])
def test_invalid_named_binding(cross, arguments, message):
    diags = _named_call_lint(arguments, cross=cross)
    assert len(diags) == 1
    assert message in diags[0].message
    assert diags[0].severity.value == "error"


@pytest.mark.parametrize("cross", [False, True])
@pytest.mark.parametrize("arguments", [
    "First = 1", "First = 1, Second = 2", "Second = 2, First = 1", "1, Second = 2",
])
def test_valid_named_binding(cross, arguments):
    assert _named_call_lint(arguments, cross=cross) == []


@pytest.mark.parametrize("cross", [False, True])
@pytest.mark.parametrize("arguments, invalid", [
    ("Second = 2", False), ("1, Second = 2", False),
    ("First = 1", True), ("1", True), ("", True),
])
def test_required_parameter_after_optional(cross, arguments, invalid):
    diags = _named_call_lint(arguments, cross=cross, signature="First: Number = 0, Second: Number")
    assert bool(diags) == invalid


@pytest.mark.parametrize("cross", [False, True])
def test_named_binding_in_russian(cross):
    target = "метод Объединить(Первый: Число, Второй: Число = 0)\n;\n"
    prefix = "Пример." if cross else ""
    caller = f"метод Запустить()\n    {prefix}Объединить(Первый = 1, Первый = 2)\n;\n"
    sources = [load_text("Пример.xbsl", target), load_text("Вызов.xbsl", caller)] if cross else [load_text("Вызов.xbsl", target + caller)]
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    diags = list(run_sources(sources, select={rule_id}))
    assert len(diags) == 1
    assert "Первый" in diags[0].message


@pytest.mark.parametrize("cross", [False, True])
def test_ambiguous_signature_with_named_arguments_is_silent(cross):
    target = "method MergeValues(First: Number)\n;\nmethod MergeValues(Second: String)\n;\n"
    prefix = "SampleApi." if cross else ""
    caller = f"method RunExample()\n    {prefix}MergeValues(Other = 1)\n;\n"
    sources = [load_text("SampleApi.xbsl", target), load_text("Caller.xbsl", caller)] if cross else [load_text("Caller.xbsl", target + caller)]
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    assert list(run_sources(sources, select={rule_id})) == []


@pytest.mark.parametrize("cross", [False, True])
def test_generated_manager_overload_is_not_bound_to_own_signature(cross):
    # An ordinary module with the same name is also skipped at file scope:
    # without paired metadata the generated overload cannot be excluded.
    target = "method Delete(Item: Number)\n;\n"
    prefix = "SampleApi." if cross else ""
    caller = f"method RunExample()\n    {prefix}Delete(RecordKey = 1)\n;\n"
    sources = [load_text("SampleApi.xbsl", target), load_text("Caller.xbsl", caller)] if cross else [load_text("Caller.xbsl", target + caller)]
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    assert list(run_sources(sources, select={rule_id})) == []


def test_static_structure_method_matching_manager_name_is_checked():
    code = (
        "structure SampleBox\n"
        "    static method Delete(Item: Number)\n    ;\n;\n"
        "method RunExample()\n    SampleBox.Delete(RecordKey = 1)\n;\n"
    )
    diags = _lint(code)
    assert len(diags) == 1
    assert "RecordKey" in diags[0].message


@pytest.mark.parametrize("cross", [False, True])
def test_named_call_shadowed_by_local_is_silent(cross):
    target = "method MergeValues(First: Number)\n;\n"
    variable = "SampleApi" if cross else "MergeValues"
    prefix = "SampleApi." if cross else ""
    caller = f"method RunExample({variable}: Object)\n    {prefix}MergeValues(Other = 1)\n;\n"
    sources = [load_text("SampleApi.xbsl", target), load_text("Caller.xbsl", caller)] if cross else [load_text("Caller.xbsl", target + caller)]
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    assert list(run_sources(sources, select={rule_id})) == []


@pytest.mark.parametrize("modifier", ["", "static "])
@pytest.mark.parametrize("argument, expected", [("Second", None), ("First", "First")])
def test_bare_call_binds_to_its_structure_method_before_module_method(modifier, argument, expected):
    code = (
        "method MergeValues(First: Number)\n;\n"
        "structure SampleBox\n"
        f"    {modifier}method MergeValues(Second: Number)\n    ;\n"
        f"    {modifier}method RunExample()\n"
        f"        MergeValues({argument} = 1)\n    ;\n;\n"
    )
    source = load_text("SampleApi.xbsl", code)
    diags = list(run_sources([source], select={"code/call-arity", "code/parse-error"}))
    if expected is None:
        assert diags == []
    else:
        assert len(diags) == 1 and diags[0].rule_id == "code/call-arity"
        assert "неизвестный параметр " + expected in diags[0].message


def test_overloaded_structure_method_does_not_fall_back_to_module_signature():
    code = (
        "method MergeValues(First: Number)\n;\n"
        "structure SampleBox\n"
        "    static method MergeValues(Second: Number)\n    ;\n"
        "    static method MergeValues(Other: String)\n    ;\n"
        "    static method RunExample()\n        MergeValues(Other = 1)\n    ;\n;\n"
    )
    assert _lint(code) == []


def test_structure_method_does_not_shadow_module_call_outside_structure():
    code = (
        "method MergeValues(First: Number)\n;\n"
        "structure SampleBox\n"
        "    static method MergeValues(Second: Number)\n    ;\n;\n"
        "method RunExample()\n    MergeValues(Second = 1)\n;\n"
    )
    diags = _lint(code)
    assert len(diags) == 1 and "неизвестный параметр Second" in diags[0].message


@pytest.mark.parametrize("cross", [False, True])
@pytest.mark.parametrize("outside_call", [False, True])
def test_structure_field_shadows_receiver_only_inside_its_owner(cross, outside_call):
    target = "method MergeValues(First: Number)\n;\n"
    caller = (
        "structure OwnApi\n"
        "    method MergeValues(Second: Number)\n    ;\n;\n"
        "structure Caller\n"
        "    req var Target: OwnApi\n"
        "    method RunExample()\n"
        "        Target.MergeValues(Second = 1)\n    ;\n;\n"
    )
    if outside_call:
        caller += "method RunOutside()\n    Target.MergeValues(Second = 1)\n;\n"
    if cross:
        sources = [load_text("Target.xbsl", target), load_text("Caller.xbsl", caller)]
    else:
        static_target = "structure Target\n    static " + target + ";\n"
        sources = [load_text("Caller.xbsl", static_target + caller)]
    rule_id = "code/call-arity-cross" if cross else "code/call-arity"
    diags = list(run_sources(sources, select={rule_id, "code/parse-error"}))
    assert len(diags) == int(outside_call)
    if outside_call:
        assert diags[0].rule_id == rule_id
        assert "Second" in diags[0].message
        assert diags[0].line == sources[-1].text.splitlines().index("    Target.MergeValues(Second = 1)") + 1
