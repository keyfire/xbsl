"""Guaranteed results across branches, loops and project enumeration cases."""

import pytest

from xbsl import i18n
from xbsl.engine import load_text, run_sources
from xbsl.parser import parse

pytestmark = pytest.mark.needs_data
RULE = "code/missing-return"


def _lint(code, extra=()):
    source = load_text("Sample.xbsl", code)
    assert parse(source)[1] == []
    return run_sources([source, *extra], select={RULE}, scopes=("project",))


@pytest.mark.parametrize("body", [
    "",
    "    var Temporary = 1\n",
    "    if Flag\n        return 1\n    ;\n",
    "    if Flag\n        return 1\n    else if Flag\n        return 2\n    ;\n",
    "    if Flag\n        return 1\n    else\n        var Temporary = 2\n    ;\n",
    "    case Value\n    when 1\n        return 1\n    ;\n",
    "    case Value\n    when 1\n        return 1\n    else\n        var Result = 2\n    ;\n",
    "    while True\n        return 1\n    ;\n",
    "    for Item in [1, 2]\n        return Item\n    ;\n",
    "    for Item = 1 to 2\n        return Item\n    ;\n",
    "    try\n        return 1\n    catch Error: Exception\n        var Result = 2\n    ;\n",
    "    try\n        var Result = 2\n    catch Error: Exception\n        return 1\n    ;\n",
    "    scope\n        if Flag\n            return 1\n        ;\n    ;\n",
    "    val Lambda = method () ->\n        return 1\n    ;\n",
])
def test_incomplete_paths(body):
    found = _lint("method Sample(Flag: Boolean, Value: Number): Number\n" + body + ";\n")
    assert len(found) == 1
    assert found[0].severity.value == "error"
    assert found[0].fix is None


@pytest.mark.parametrize("body", [
    "    return 1\n",
    "    if Flag\n        return 1\n    else\n        return 2\n    ;\n",
    "    if Flag\n        return 1\n    ;\n    return 2\n",
    "    case Value\n    when 1\n        return 1\n    else\n        return 2\n    ;\n",
    "    scope\n        return 1\n    ;\n",
    "    try\n        return 1\n    catch Error: Exception\n        throw Error\n    ;\n",
    "    while True\n        break\n    ;\n    return 1\n",
    "    throw new IllegalStateException(\"probe\")\n",
])
def test_guaranteed_paths(body):
    assert _lint("method Sample(Flag: Boolean, Value: Number): Number\n" + body + ";\n") == []


@pytest.mark.parametrize("result", ["", ": void", ": ничто", ": never"])
def test_methods_without_a_result_are_not_required_to_return(result):
    assert _lint(f"method Sample(){result}\n;\n") == []


@pytest.mark.parametrize("result,expected", [("", 1), (": void", 1), (": never", 0), (": Number", 1)])
def test_known_local_call_does_not_hide_fallthrough(result, expected):
    assert len(_lint(f"method Log(){result}\n    throw new IllegalStateException(\"probe\")\n;\n"
                     "method Sample(): Number\n    Log()\n;\n")) == expected


@pytest.mark.parametrize("result,expected", [("", 1), (": never", 0)])
def test_project_call_result(result, expected):
    other = load_text("Utility.xbsl", f"method Log(){result}\n    throw new IllegalStateException(\"probe\")\n;\n")
    assert len(_lint("method Sample(): Number\n    Utility.Log()\n;\n", [other])) == expected


def test_catalog_void_call_still_falls_through():
    assert len(_lint("method Sample(Values: Array<Number>): Number\n    Values.Clear()\n;\n")) == 1


@pytest.mark.parametrize("tail,expected", [("", 1), ("    when Direction.Right\n        return 2\n", 0)])
def test_local_enum_completeness(tail, expected):
    code = ("enum Direction\n    Left, Right\n;\n"
            "method Sample(Value: Direction): Number\n    case Value\n"
            "    when Direction.Left\n        return 1\n" + tail + "    ;\n;\n")
    assert len(_lint(code)) == expected


@pytest.mark.parametrize("tail,expected", [("", 1), ("    when Right\n        return 2\n", 0)])
def test_yaml_enum_this_completeness(tail, expected):
    pair = load_text("Sample.yaml", "ElementKind: Enumeration\nName: Sample\nItems:\n- Name: Left\n- Name: Right\n")
    code = "method Sample(): Number\n    case this\n    when Left\n        return 1\n" + tail + "    ;\n;\n"
    assert len(_lint(code, [pair])) == expected


@pytest.mark.parametrize("nullable,tail,expected", [
    ("", "", 0), ("?", "", 1), ("?", "    when Undefined\n        return 3\n", 0),
])
def test_boolean_coverage_preserves_nullable(nullable, tail, expected):
    code = (f"method Sample(Value: Boolean{nullable}): Number\n    case Value\n"
            "    when True\n        return 1\n    when False\n        return 2\n" + tail + "    ;\n;\n")
    assert len(_lint(code)) == expected


def test_unknown_call_is_conservative_but_an_independent_gap_is_reported():
    assert _lint("method Sample(): Number\n    Unresolved()\n;\n") == []
    assert len(_lint("method Sample(Flag: Boolean): Number\n    if Flag\n        Unresolved()\n    ;\n;\n")) == 1


def test_local_shadow_of_never_call_is_unknown():
    assert _lint("method Stop(): never\n    throw new IllegalStateException(\"probe\")\n;\n"
                 "method Sample(Stop: unknown): Number\n    Stop()\n;\n") == []


def test_own_method_takes_precedence_over_module_method():
    code = ("method Log(): never\n    throw new IllegalStateException(\"probe\")\n;\n"
            "structure Item\n    method Log()\n    ;\n"
            "    method Sample(): Number\n        Log()\n    ;\n;\n")
    assert len(_lint(code)) == 1


def test_unknown_enum_does_not_turn_complete_branches_into_a_finding():
    assert _lint("method Sample(Value: External): Number\n    case Value\n    when First\n        return 1\n    ;\n;\n") == []


def test_parse_errors_are_not_judged():
    source = load_text("Broken.xbsl", "method Sample(: Number\n")
    assert parse(source)[1]
    assert run_sources([source], select={RULE}, scopes=("project",)) == []


def test_russian_source_and_message_location():
    found = _lint("метод Пример(): Число\n;\n")
    assert [(d.line, d.col) for d in found] == [(1, 17)]
    assert "Пример" in found[0].message


def test_english_message():
    previous = i18n.current_lang()
    i18n.set_lang("en")
    try:
        found = _lint("method Sample(): Number\n;\n")
    finally:
        i18n.set_lang(previous)
    assert "return" in found[0].message


@pytest.mark.parametrize("tail,expected", [("", 1), ("    when is String\n        return 2\n", 0)])
def test_union_type_case(tail, expected):
    code = ("method Sample(Value: Number|String): Number\n    case Value\n"
            "    when is Number\n        return 1\n" + tail + "    ;\n;\n")
    assert len(_lint(code)) == expected


def test_nullable_catalog_void_call_still_falls_through():
    assert len(_lint("method Sample(Values: Array<Number>?): Number\n    Values?.Clear()\n;\n")) == 1


@pytest.mark.parametrize("tail,expected", [("", 1), ("    when Right\n        return 2\n", 0)])
def test_project_member_enum_case(tail, expected):
    enum = load_text("Direction.yaml", "ElementKind: Enumeration\nName: Direction\nItems:\n- Name: Left\n- Name: Right\n")
    other = load_text("Holder.xbsl", "structure Entry\n    var Direction: Direction\n;\n")
    code = ("method Sample(Value: Holder.Entry): Number\n    case Value.Direction\n"
            "    when Left\n        return 1\n" + tail + "    ;\n;\n")
    assert len(_lint(code, [enum, other])) == expected


def test_catch_gap_location_points_to_the_unfinished_branch():
    code = ("method Sample(): Number\n    try\n        return 1\n"
            "    catch Error: Exception\n        var Count = 0\n    ;\n;\n")
    assert [(d.line, d.col) for d in _lint(code)] == [(5, 21)]


@pytest.mark.parametrize("type_name,first,second", [
    ("SortingDirection", "Ascending", "Descending"),
    ("НаправлениеСортировки", "ПоВозрастанию", "ПоУбыванию"),
])
@pytest.mark.parametrize("complete,expected", [(True, 0), (False, 1)])
def test_platform_enum_completeness(type_name, first, second, complete, expected):
    tail = f"    when {type_name}.{second}\n        return 2\n" if complete else ""
    code = (f"method Sample(Value: {type_name}): Number\n    case Value\n"
            f"    when {type_name}.{first}\n        return 1\n" + tail + "    ;\n;\n")
    assert len(_lint(code)) == expected


def test_mixed_type_and_value_patterns_remain_conservative():
    assert _lint("method Sample(Value: Number?): Number\n    case Value\n"
                 "    when is Number\n        return 1\n"
                 "    when Undefined\n        return 2\n    ;\n;\n") == []


@pytest.mark.parametrize("body", ["", "        Stop()\n", "        throw new IllegalStateException(\"probe\")\n"])
def test_finally_does_not_supply_the_missing_result(body):
    code = ("method Stop(): never\n    throw new IllegalStateException(\"probe\")\n;\n"
            "method Sample(): Number\n    try\n    finally\n" + body + "    ;\n;\n")
    assert len(_lint(code)) == 1


@pytest.mark.parametrize("body", [
    "    val Value: Number = Stop()\n",
    "    var Value = 1\n    Value = Stop()\n",
    "    Sink(Stop())\n",
    "    val Value: Number = throw new IllegalStateException(\"probe\")\n",
    "    if Stop()\n        return 1\n    ;\n",
], ids=["initializer", "assignment", "argument", "throw-initializer", "condition"])
def test_embedded_never_or_throw_does_not_supply_the_missing_result(body):
    code = ("method Stop(): never\n    throw new IllegalStateException(\"probe\")\n;\n"
            "method Sink(Value: Number): void\n;\n"
            "method Sample(): Number\n" + body + ";\n")
    assert len(_lint(code)) == 1
