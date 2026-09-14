"""code/ternary-and-or: a ternary after `это Тип` in an operand of `и`/`или`.

The ternary of a type check (`Х это Тип ? X : Y`) belongs to the check and binds tighter than the
`и`/`или` to its left, so `А и Х это Тип ? 1 : 0` is `А и (Х это Тип ? 1 : 0)`. The language
server of the IDE refused that form with non-boolean branches and accepted the plain
`А и Б ? 1 : 0`, a group around the condition and the form with boolean branches - the same in
every compatibility mode of the platform enumeration.

The rule parses the module and types the branches, so the tests need the Element data.
"""

from pathlib import Path

import pytest

from xbsl import cli, engine, i18n

pytestmark = pytest.mark.needs_data

RULE = "code/ternary-and-or"
PARAMS = "Флаг: Булево, Второй: Булево, Значение: Объект?, Количество: Число"


def _module(expression: str, result: str = "Объект?") -> str:
    return f"метод Проба({PARAMS}): {result}\n    возврат {expression}\n;\n"


def _lint(content: str, name: str = "Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


# --- what is reported -------------------------------------------------------------------------

def test_the_form_after_a_type_check_is_reported_with_the_condition_in_parentheses():
    text = _module("Флаг и Значение это Строка ? 1 : 0")
    found = _lint(text)

    assert len(found) == 1, [d.message for d in found]
    assert (found[0].line, found[0].col) == (2, 13)
    assert found[0].severity.value == "error"
    assert "'и'" in found[0].message
    assert _fixed(text, found[0]) == _module("(Флаг и Значение это Строка) ? 1 : 0")


@pytest.mark.parametrize(("expression", "written"), [
    ("Флаг или Значение это Строка ? 1 : 0", "(Флаг или Значение это Строка) ? 1 : 0"),
    ("Флаг и Значение это не Строка ? 1 : 0", "(Флаг и Значение это не Строка) ? 1 : 0"),
    ("Флаг и Значение это Строка|Число ? 1 : 0", "(Флаг и Значение это Строка|Число) ? 1 : 0"),
    ("Флаг и Второй и Значение это Строка ? 1 : 0", "(Флаг и Второй и Значение это Строка) ? 1 : 0"),
    ("Флаг и Значение это Строка ? \"да\" : \"нет\"", "(Флаг и Значение это Строка) ? \"да\" : \"нет\""),
    ("Флаг и Значение это Строка ? Значение как Строка : \"\"",
     "(Флаг и Значение это Строка) ? Значение как Строка : \"\""),
    ("не Флаг и Значение это Строка ? Количество : 0", "(не Флаг и Значение это Строка) ? Количество : 0"),
])
def test_every_shape_of_the_form_is_reported(expression, written):
    text = _module(expression)
    found = _lint(text)

    assert len(found) == 1, (expression, [d.message for d in found])
    assert _fixed(text, found[0]) == _module(written)


def test_the_form_inside_a_call_argument_is_reported():
    text = _module("Строка(Флаг и Значение это Строка ? 1 : 0)")
    found = _lint(text)

    assert len(found) == 1
    assert _fixed(text, found[0]) == _module("Строка((Флаг и Значение это Строка) ? 1 : 0)")


def test_a_branch_the_module_cannot_type_keeps_the_finding_without_a_fix():
    text = _module("Флаг и Значение это Строка ? Неизвестный() : Другой()")
    found = _lint(text)

    assert len(found) == 1
    assert found[0].fix is None


def test_the_english_message_names_the_keywords_in_english():
    i18n.set_lang("en")
    try:
        found = _lint("method Probe(Flag: Boolean, Value: Object?): Number\n"
                      "    return Flag and Value is String ? 1 : 0\n;\n", "Probe.xbsl")
    finally:
        i18n.set_lang("ru")

    assert len(found) == 1
    assert "'is Type'" in found[0].message and "'and'" in found[0].message


# --- what is not reported ---------------------------------------------------------------------

@pytest.mark.parametrize("expression", [
    # the plain forms: the ternary takes the whole condition
    "Флаг и Второй ? 1 : 0",
    "Флаг или Второй ? \"да\" : \"нет\"",
    "Флаг и Количество > 0 ? 1 : 0",
    "Флаг и не Второй ? 1 : 0",
    "Значение это Строка и Флаг ? 1 : 0",
    # a group around the condition or around the ternary
    "(Флаг и Значение это Строка) ? 1 : 0",
    "Флаг и (Значение это Строка ? 1 : 0) == 1",
    # boolean branches: the compiler accepts the form
    "Флаг и Значение это Строка ? Истина : Ложь",
    "Флаг и Значение это Строка ? Второй : Ложь",
    "Флаг или Значение это Строка ? Количество > 0 : не Второй",
    # a type with the empty value: the ternary is read at the level of the expression
    "Флаг и Значение это Неопределено ? 1 : 0",
])
def test_the_forms_the_compiler_accepts_are_not_reported(expression):
    assert _lint(_module(expression)) == []


def test_a_module_that_does_not_parse_is_not_judged():
    assert _lint(_module("Флаг и Значение это Строка ? 1 : 0") + "метод Сломан(\n") == []


# --- --fix on a file --------------------------------------------------------------------------

def test_fix_rewrites_the_file_by_its_own_offsets(tmp_path: Path):
    target = tmp_path / "Проба.xbsl"
    lines = [
        f"метод Проба({PARAMS}): Строка",
        "    знч Код = Флаг и Значение это Строка ? 1 : 0",
        "    возврат Код.ВСтроку()",
        ";",
        "",
    ]
    target.write_bytes("\r\n".join(lines).encode("utf-8"))

    code = cli.main([str(tmp_path), "--select", RULE, "--no-baseline", "--fix"])

    assert code == 0
    assert target.read_bytes().decode("utf-8") == "\r\n".join(
        [lines[0], "    знч Код = (Флаг и Значение это Строка) ? 1 : 0", *lines[2:]])
