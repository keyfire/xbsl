"""style/boolean-ternary: a ternary whose branches are the two boolean literals.

The platform IDE warns that `Флаг ? Истина : Ложь` equals its condition and `Флаг ? Ложь : Истина`
its negation. Its language server confirmed the variants below on probe projects: the reported
ones in modules, in string interpolations and in yaml bindings, the quiet ones (equal branches, a
branch that is an expression, numbers, strings, a double-quoted yaml value), and how `не` binds -
over a comparison but not over `это`, `и` and `или`, which is what the negation of the fix follows.

The rule parses the module, so the tests need the Element data.
"""

from pathlib import Path

import pytest

from xbsl import cli, engine, i18n

pytestmark = pytest.mark.needs_data

RULE = "style/boolean-ternary"
PARAMS = ("Флаг: Булево, Второй: Булево, Текст: Строка?, Количество: Число, Значение: Объект?, "
          "Числа: Массив<Число>")


def _module(expression: str) -> str:
    return f"метод Проба({PARAMS}): Объект?\n    возврат {expression}\n;\n"


def _lint(content: str, name: str = "Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


# --- what is reported -------------------------------------------------------------------------

def test_the_condition_form_is_reported_with_the_condition():
    text = _module("Флаг ? Истина : Ложь")
    found = _lint(text)

    assert len(found) == 1, [d.message for d in found]
    assert (found[0].line, found[0].col) == (2, 13)
    assert found[0].severity.value == "warning"
    assert "равен своему условию" in found[0].message
    assert _fixed(text, found[0]) == _module("Флаг")


def test_the_negation_form_is_reported_with_the_negation():
    text = _module("Флаг ? Ложь : Истина")
    found = _lint(text)

    assert len(found) == 1
    assert "отрицанию" in found[0].message
    assert _fixed(text, found[0]) == _module("не Флаг")


@pytest.mark.parametrize(("expression", "written"), [
    ("Количество > 0 ? Истина : Ложь", "Количество > 0"),
    ("не Флаг ? Истина : Ложь", "не Флаг"),
    ("(Флаг) ? Истина : Ложь", "Флаг"),
    ("(Флаг и Второй) ? Истина : Ложь", "(Флаг и Второй)"),
    ("Флаг и Второй ? Истина : Ложь", "Флаг и Второй"),
    ("Флаг ? (Истина) : (Ложь)", "Флаг"),
    ("Флаг ? True : False", "Флаг"),
    ("Числа.Размер() > 0 ? Истина : Ложь", "Числа.Размер() > 0"),
    ("Значение это Строка ? Истина : Ложь", "Значение это Строка"),
])
def test_the_condition_is_carried_over_as_written(expression, written):
    text = _module(expression)
    found = _lint(text)

    assert len(found) == 1, (expression, [d.message for d in found])
    assert _fixed(text, found[0]) == _module(written)


@pytest.mark.parametrize(("expression", "written"), [
    # `не` covers a comparison whole: `не А > 0` is `не (А > 0)`
    ("Количество > 0 ? Ложь : Истина", "не Количество > 0"),
    # a single equality flips instead
    ("Текст == Неопределено ? Ложь : Истина", "Текст != Неопределено"),
    ("Текст != Неопределено ? Ложь : Истина", "Текст == Неопределено"),
    # a leading `не` drops away
    ("не Флаг ? Ложь : Истина", "Флаг"),
    ("(не Флаг) ? Ложь : Истина", "Флаг"),
    ("не (Флаг и Второй) ? Ложь : Истина", "(Флаг и Второй)"),
    # `и` and `или` lie beyond `не`
    ("Флаг и Второй ? Ложь : Истина", "не (Флаг и Второй)"),
    ("(Флаг или Второй) ? Ложь : Истина", "не (Флаг или Второй)"),
    # `это` is negated inside: `не А это Т` would be `(не А) это Т`
    ("Значение это Строка ? Ложь : Истина", "Значение это не Строка"),
    ("Значение это не Строка ? Ложь : Истина", "Значение это Строка"),
    ("(Значение это Строка) ? Ложь : Истина", "(Значение это не Строка)"),
    # a group around a single operand drops, any other group stays
    ("(Флаг) ? Ложь : Истина", "не Флаг"),
    ("(Количество > 0) ? Ложь : Истина", "не (Количество > 0)"),
    ("Числа.Содержит(1) ? Ложь : Истина", "не Числа.Содержит(1)"),
])
def test_the_negation_follows_how_the_platform_binds_it(expression, written):
    text = _module(expression)
    found = _lint(text)

    assert len(found) == 1, (expression, [d.message for d in found])
    assert _fixed(text, found[0]) == _module(written)


def test_a_ternary_inside_a_bigger_expression_is_replaced_in_place():
    text = _module("(Флаг ? Истина : Ложь) и Второй")
    found = _lint(text)

    assert len(found) == 1
    assert found[0].col == 14
    assert _fixed(text, found[0]) == _module("(Флаг) и Второй")


def test_only_the_inner_of_nested_ternaries_is_reported():
    text = _module("Флаг ? Истина : (Второй ? Истина : Ложь)")
    found = _lint(text)

    assert [(d.line, d.col) for d in found] == [(2, 30)]


def test_a_ternary_in_the_body_of_a_short_lambda_is_reported():
    text = _module("Числа.Фильтровать(Число -> Число > 1 ? Истина : Ложь)")
    found = _lint(text)

    assert len(found) == 1
    assert _fixed(text, found[0]) == _module("Числа.Фильтровать(Число -> Число > 1)")


def test_a_ternary_in_a_string_interpolation_is_reported_in_place():
    text = _module('"Итог: %{Флаг ? Ложь : Истина}"')
    found = _lint(text)

    assert len(found) == 1
    assert (found[0].line, found[0].col) == (2, 22)
    assert _fixed(text, found[0]) == _module('"Итог: %{не Флаг}"')


def test_the_english_module_gets_the_english_negation():
    text = "method Probe(Flag: Boolean): Boolean\n    return Flag ? False : True\n;\n"
    found = _lint(text, "Probe.xbsl")

    assert len(found) == 1
    assert _fixed(text, found[0]) == "method Probe(Flag: Boolean): Boolean\n    return not Flag\n;\n"


def test_the_english_message_names_the_literals_in_english():
    i18n.set_lang("en")
    try:
        found = _lint(_module("Флаг ? Ложь : Истина"))
    finally:
        i18n.set_lang("ru")

    assert "'False' and 'True'" in found[0].message


def test_a_ternary_over_several_lines_with_a_comment_keeps_the_finding_without_a_fix():
    text = f"метод Проба({PARAMS}): Булево\n    возврат Флаг // пояснение\n        ? Истина\n        : Ложь\n;\n"
    found = _lint(text)

    assert len(found) == 1
    assert found[0].fix is None


# --- what is not reported ---------------------------------------------------------------------

@pytest.mark.parametrize("expression", [
    "Флаг ? Истина : Истина",
    "Флаг ? Ложь : Ложь",
    "Флаг ? Истина : Количество > 0",
    "Флаг ? 1 : 0",
    '"Флаг" == "" ? "Истина" : "Ложь"',
    "Флаг ? Истина : Неопределено",
    "Флаг ? Ложь : Текст == Неопределено",
])
def test_other_branches_are_not_reported(expression):
    assert _lint(_module(expression)) == []


def test_a_module_that_does_not_parse_is_not_judged():
    text = _module("Флаг ? Истина : Ложь") + "метод Сломан(\n"
    assert _lint(text) == []


# --- yaml bindings ----------------------------------------------------------------------------

_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 00000000-0000-4000-8000-000000000001
Имя: ЗадачиФормаОбъекта
Наследует:
    Тип: ФормаОбъекта<Задачи.Объект>
    Содержимое:
        Тип: Надпись
        Видимость: {value}
"""


def test_a_binding_in_single_quotes_is_reported_at_the_value():
    text = _FORM.format(value="'=Объект.Выполнена ? Ложь : Истина'")
    found = _lint(text, "ЗадачиФормаОбъекта.yaml")

    assert len(found) == 1
    assert (found[0].line, found[0].col) == (8, 20)
    assert _fixed(text, found[0]) == _FORM.format(value="'=не Объект.Выполнена'")


def test_a_plain_binding_is_reported():
    text = _FORM.format(value="=Объект.Выполнена ?Истина :Ложь")
    found = _lint(text, "ЗадачиФормаОбъекта.yaml")

    assert len(found) == 1
    assert _fixed(text, found[0]) == _FORM.format(value="=Объект.Выполнена")


def test_a_double_quoted_value_is_a_string_and_not_judged():
    text = _FORM.format(value='"=Объект.Выполнена ? Истина : Ложь"')
    assert _lint(text, "ЗадачиФормаОбъекта.yaml") == []


def test_a_binding_with_an_escaped_quote_keeps_the_finding_without_a_fix():
    text = _FORM.format(value="'=Объект.Наименование == ''а'' ? Истина : Ложь'")
    found = _lint(text, "ЗадачиФормаОбъекта.yaml")

    assert len(found) == 1
    assert found[0].fix is None


def test_the_negation_in_a_binding_follows_the_english_key():
    text = _FORM.format(value="'=Object.Done ? False : True'").replace("Видимость:", "Visible:")
    found = _lint(text, "ЗадачиФормаОбъекта.yaml")

    assert len(found) == 1
    assert _fixed(text, found[0]).endswith("Visible: '=not Object.Done'\n")


def test_the_negation_in_a_binding_follows_its_own_keywords_first():
    text = _FORM.format(value="'=Flag and Other ? False : True'")
    found = _lint(text, "ЗадачиФормаОбъекта.yaml")

    assert len(found) == 1
    assert _fixed(text, found[0]) == _FORM.format(value="'=not (Flag and Other)'")


def test_a_binding_with_strings_in_the_branches_is_not_reported():
    text = _FORM.format(value="'=Объект.Выполнена ? \"Да\" : \"Нет\"'")
    assert _lint(text, "ЗадачиФормаОбъекта.yaml") == []


# --- --fix on a file --------------------------------------------------------------------------

def test_fix_rewrites_the_file_by_its_own_offsets(tmp_path: Path):
    target = tmp_path / "Проба.xbsl"
    lines = [
        f"метод Проба({PARAMS}): Булево",
        "    знч Первое = Флаг ? Истина : Ложь",
        "    знч Второе = Текст == Неопределено ? Ложь : Истина",
        "    возврат Первое и Второе",
        ";",
        "",
    ]
    target.write_bytes("\r\n".join(lines).encode("utf-8"))

    code = cli.main([str(tmp_path), "--select", RULE, "--no-baseline", "--fix"])

    assert code == 0
    fixed = target.read_bytes().decode("utf-8")
    assert fixed == "\r\n".join([
        lines[0],
        "    знч Первое = Флаг",
        "    знч Второе = Текст != Неопределено",
        *lines[3:],
    ])
