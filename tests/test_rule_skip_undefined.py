"""Redundant SkipUndefined calls follow the element type and preserve materialization."""

import pytest

from xbsl import engine, parser

RULE = "code/redundant-skip-undefined"
pytestmark = pytest.mark.needs_data


def _lint(text):
    source = engine.load_text("Sample.xbsl", text)
    _, errors = parser.parse(source)
    assert errors == []
    return source, engine.run_sources([source], select={RULE})


@pytest.mark.parametrize("declaration, expression", [
    ("Items: Array<String>", "Items.SkipUndefined()"),
    ("Items: Set<String>", "Items.SkipUndefined()"),
    ("Items: ReadableArray<Number>", "Items.SkipUndefined()"),
    ("Items: Iterable<String>", "Items.SkipUndefined()"),
    ("Items: Sequence<String>", "Items.SkipUndefined()"),
    ("Items: Array<String|Number>", "Items.SkipUndefined()"),
    ("", "[1, 2].SkipUndefined()"),
    ("Items: Array<String>", "Items.AsSequence().SkipUndefined()"),
    ("Items: Array<String>", "Items.Filter(Item -> True).SkipUndefined()"),
])
def test_known_nonnullable_element_is_reported(declaration, expression):
    _, findings = _lint(f"method Example({declaration})\n    var Result = {expression}\n;\n")
    assert len(findings) == 1
    assert findings[0].severity.value == "warning"


@pytest.mark.parametrize("declaration, expression", [
    ("Items: Array<String?>", "Items.SkipUndefined()"),
    ("Items: Sequence<String?>", "Items.SkipUndefined()"),
    ("Items: Array<String>|Array<Number>", "Items.SkipUndefined()"),
    ("Items: unknown", "Items.SkipUndefined()"),
    ("Items: Array<unknown>", "Items.SkipUndefined()"),
    ("Items: Array<String>?", "Items?.SkipUndefined()"),
    ("", "[1, Undefined].SkipUndefined()"),
    ("", "[].SkipUndefined()"),
])
def test_nullable_or_unresolved_element_is_not_reported(declaration, expression):
    _, findings = _lint(f"method Example({declaration})\n    var Result = {expression}\n;\n")
    assert findings == []


def test_russian_spelling_comes_from_the_same_platform_operation():
    _, findings = _lint("метод Пример(Значения: Массив<Строка>)\n    знч Результат = Значения.ПропуститьНеопределено()\n;\n")
    assert len(findings) == 1


def test_user_method_with_the_same_name_is_not_reported():
    _, findings = _lint("""structure Wrapper
    method SkipUndefined(): String
        return "value"
    ;
;
method Example(Item: Wrapper)
    var Result = Item.SkipUndefined()
;
""")
    assert findings == []


def test_both_redundant_calls_in_a_chain_are_reported():
    _, findings = _lint("method Example(Items: Array<String>)\n    var Result = Items.SkipUndefined().SkipUndefined()\n;\n")
    assert len(findings) == 2


@pytest.mark.parametrize("expression, expected", [
    ("Items.SkipUndefined()", "Items.ToArray()"),
    ("(Items).SkipUndefined()", "(Items).ToArray()"),
    ("(Flag ? Items : Items).SkipUndefined()", "(Flag ? Items : Items).ToArray()"),
    ("Items /* receiver */ . /* member */ SkipUndefined(/* call */)",
     "Items /* receiver */ . /* member */ ToArray(/* call */)"),
    ("Items.SkipUndefined().Count()", "Items.ToArray().Count()"),
])
def test_fix_changes_only_the_member_name_and_preserves_materialization(expression, expected):
    from xbsl import fixer

    source, findings = _lint(f"method Example(Items: Set<String>, Flag: Boolean)\n    var Result = {expression}\n;\n")
    assert len(findings) == 1 and findings[0].fix is not None
    fixed = fixer.fix_source(source, findings).text
    assert f"var Result = {expected}\n" in fixed
    assert _lint(fixed)[1] == []


def test_russian_fix_uses_the_documented_russian_array_conversion():
    from xbsl import fixer

    source, findings = _lint("метод Пример(Значения: Массив<Строка>)\n    знч Результат = Значения.ПропуститьНеопределено()\n;\n")
    assert len(findings) == 1 and findings[0].fix is not None
    assert "Значения.ВМассив()" in fixer.fix_source(source, findings).text


def test_sequence_retains_its_result_contract_without_an_autofix():
    _, findings = _lint("method Example(Items: Sequence<String>)\n    var Result = Items.SkipUndefined()\n;\n")
    assert len(findings) == 1 and findings[0].fix is None



def test_unresolved_named_element_is_not_assumed_nonnullable():
    _, findings = _lint("method Example(Items: Array<MissingType>)\n    var Result = Items.SkipUndefined()\n;\n")
    assert findings == []


def test_known_local_element_type_is_not_mistaken_for_an_unknown_type():
    _, findings = _lint("structure Entry\n;\nmethod Example(Items: Array<Entry>)\n    var Result = Items.SkipUndefined()\n;\n")
    assert len(findings) == 1



def test_nullable_members_inside_a_nonnullable_element_do_not_make_the_element_nullable():
    _, findings = _lint("method Example(Items: Array<Array<String?>>)\n    var Result = Items.SkipUndefined()\n;\n")
    assert len(findings) == 1


def test_file_fix_preserves_bom_crlf_and_comments(tmp_path):
    from xbsl import fixer

    path = tmp_path / "Sample.xbsl"
    text = "method Example(Items: Array<String>)\r\n    var Result = Items./* keep */SkipUndefined()\r\n;\r\n"
    path.write_bytes(text.encode("utf-8-sig"))
    source = engine.load(path)
    findings = engine.run_sources([source], select={RULE})
    assert len(findings) == 1 and findings[0].fix is not None
    fixed = fixer.fix_source(source, findings)
    assert fixer.encode(source, fixed.text) == text.replace("SkipUndefined", "ToArray").encode("utf-8-sig")


def test_user_type_named_like_a_platform_collection_keeps_its_own_method():
    _, findings = _lint("""structure Array
    method SkipUndefined(): String
        return "value"
    ;
;
method Example(Item: Array)
    var Result = Item.SkipUndefined()
;
""")
    assert findings == []


def test_malformed_argument_list_is_not_treated_as_the_platform_no_argument_call():
    _, findings = _lint("method Example(Items: Array<String>)\n    var Result = Items.SkipUndefined(1)\n;\n")
    assert findings == []
