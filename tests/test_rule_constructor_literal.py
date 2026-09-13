"""style/constructor-literal: a call that a literal of the same type replaces.

The platform IDE warns that a literal would say the same on a constructor of a literal type
called with constant arguments only, and on `FindType` with a constant name. The IDE language
server confirmed the variants below on probe projects: it warns on
the reported ones, stays quiet on the quiet ones (a variable argument, an interpolation, a type
the module declares, a `FindType` of its own), and accepts every literal the fix writes - the
same probes run again after `--fix` came back with neither an error nor a warning on the
rewritten lines.

The rule parses the module, so the module needs the Element data (listed in conftest).
"""

from pathlib import Path

import pytest

from xbsl import cli, engine

RULE = "style/constructor-literal"


def _lint(content: str, name: str = "Проба.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _method(expression: str, params: str = "", result: str = "Объект?") -> str:
    return f"метод Проба({params}): {result}\n    возврат {expression}\n;\n"


def _fixed(text: str, found) -> str:
    fix = found.fix
    assert fix is not None, found.message
    return text[:fix.start] + fix.new + text[fix.end:]


# --- what is reported ---------------------------------------------------------------------------

def test_a_date_from_a_constant_string_is_reported_with_the_literal():
    text = _method('новый Дата("9999-12-31")', result="Дата")
    found = _lint(text)

    assert len(found) == 1, [d.message for d in found]
    assert (found[0].line, found[0].col) == (2, 13)
    assert found[0].severity.value == "warning"
    assert "Дата{9999-12-31}" in found[0].message
    assert _fixed(text, found[0]) == _method("Дата{9999-12-31}", result="Дата")


@pytest.mark.parametrize(("expression", "literal"), [
    ('новый ДатаВремя("2026-01-31T10:20:30")', "ДатаВремя{2026-01-31T10:20:30}"),
    ('новый ДатаВремя("2026-01-31 10:20")', "ДатаВремя{2026-01-31 10:20}"),
    ('новый ДатаВремя("2026-01-31T10:20:30.123")', "ДатаВремя{2026-01-31T10:20:30.123}"),
    ('новый Время("10:20")', "Время{10:20}"),
    ('новый Момент("2026-01-31T10:20:30+03:00")', "Момент{2026-01-31T10:20:30+03:00}"),
    ('новый Момент("2026-01-31T10:20:30Z")', "Момент{2026-01-31T10:20:30Z}"),
    ('новый ЧасовойПояс("UTC+3")', "ЧасовойПояс{UTC+3}"),
    ('новый ЧасовойПояс("Europe/Moscow")', "ЧасовойПояс{Europe/Moscow}"),
    ('новый Ууид("550e8400-e29b-41d4-a716-446655440000")', "Ууид{550e8400-e29b-41d4-a716-446655440000}"),
    ('новый Байты("4D5A")', "Байты{4D5A}"),
    ('новый Версия("1.0.2-beta")', "Версия{1.0.2-beta}"),
    ('новый Версия("2")', "Версия{2}"),
    ('новый Локаль("en-GB")', "Локаль{en-GB}"),
    ('новый Булево("Истина")', "Истина"),
    ('новый Булево("false")', "Ложь"),
    ('новый Число("123")', "123"),
])
def test_a_string_the_literal_holds_is_carried_over(expression, literal):
    text = _method(expression)
    found = _lint(text)

    assert len(found) == 1, (expression, [d.message for d in found])
    assert _fixed(text, found[0]) == _method(literal)


@pytest.mark.parametrize(("expression", "literal"), [
    ("новый Дата(2026, 1, 31)", "Дата{2026-01-31}"),
    ("новый ДатаВремя(2026, 1, 31, 10, 20, 30)", "ДатаВремя{2026-01-31 10:20:30}"),
    ("новый ДатаВремя(2026, 1, 31, 10, 20, 30, 5)", "ДатаВремя{2026-01-31 10:20:30.005}"),
    ("новый ДатаВремя(Дата{2026-01-31}, Время{10:20})", "ДатаВремя{2026-01-31 10:20}"),
    ("новый Время(10, 20, 30, 0)", "Время{10:20:30}"),
    ("новый Длительность(1, 30, 0, 0)", "1ч30м"),
    ("новый Длительность(2, 1, 30, 0, 0)", "2д1ч30м"),
    ("новый Длительность(36, 0, 0, 0, Ложь)", "1д12ч"),  # hours, minutes, seconds, ms, sign
    ("новый Длительность(0, 36, 0, 0, Ложь)", "36м"),
    ("новый Длительность(0,0,0,0)", "0мс"),
])
def test_parts_of_the_value_become_the_literal_the_platform_writes(expression, literal):
    text = _method(expression)
    found = _lint(text)

    assert len(found) == 1, (expression, [d.message for d in found])
    assert _fixed(text, found[0]) == _method(literal)


@pytest.mark.parametrize("expression", [
    'новый Дата("31.01.2026")',  # the constructor reads it, a date literal does not
    'новый Дата("2026-02-30")',
    'новый Ууид("не ууид")',
    'новый Дата("")',  # an empty literal is the default value, the constructor throws
    'новый Байты("")',
    'новый Число("-12.3")',  # a unary minus in place of a call changes the precedence
    'новый Число("1.23e+2")',
    "новый Длительность(1, 30, 0, 0, Истина)",
    "новый Момент(2026, 1, 31, ЧасовойПояс{UTC})",
    "новый Строка(Байты{4D5A})",
    "новый Дата(Год = 2026, Месяц = 1, День = 31)",
    "новый Число(0x1F)",
])
def test_a_value_without_a_proven_literal_is_reported_without_a_fix(expression):
    found = _lint(_method(expression))

    assert len(found) == 1, (expression, [d.message for d in found])
    assert found[0].fix is None


def test_a_parenthesized_constant_is_still_a_constant():
    """The IDE model keeps no node for brackets, so the argument is the string itself."""
    text = _method('новый Дата(("2026-01-31"))')
    found = _lint(text)

    assert len(found) == 1
    assert _fixed(text, found[0]) == _method("Дата{2026-01-31}")


def test_find_type_with_a_constant_name_is_reported_without_a_fix():
    found = _lint(_method('НайтиТип("Стд::Строка")', result="Тип?"))

    assert len(found) == 1, [d.message for d in found]
    assert found[0].fix is None
    assert "Тип<Стд::Строка>" in found[0].message


def test_find_type_qualified_with_the_standard_namespace_is_the_same_method():
    assert len(_lint(_method('Стд::НайтиТип("Стд::Строка")', result="Тип?"))) == 1
    assert _lint(_method('Склады::НайтиТип("Стд::Строка")', result="Тип?")) == []


def test_english_spelling_gets_the_english_literal():
    text = (
        "method Probe(): Object?\n"
        '    val First = new Date("2026-01-31")\n'
        '    val Second = new Boolean("True")\n'
        "    val Third = new Duration(1, 30, 0, 0)\n"
        '    val Fourth = new Дата("9999-12-31")\n'
        '    return FindType("Std::String")\n'
        ";\n"
    )
    found = _lint(text, "Probe.xbsl")

    assert [(d.line, d.fix.new if d.fix else None) for d in found] == [
        (2, "Date{2026-01-31}"),
        (3, "True"),
        (4, "1h30m"),
        (5, "Дата{9999-12-31}"),
        (6, None),
    ]
    assert "Type<Std::String>" in found[-1].message


# --- what stays quiet ---------------------------------------------------------------------------

@pytest.mark.parametrize(("expression", "params"), [
    ("новый Дата(Срок)", "Срок: Строка"),
    ('новый Дата("2026-01-%{День}")', "День: Число"),
    ('новый Дата("2026-01-%День")', "День: Число"),
    ('новый Дата("2026" + "-01-31")', ""),
    ("новый Ууид()", ""),
    ("новый Длительность(-1, 0, 0, 0)", ""),
    ("новый Строка(Байты{4D5A}, Кодировка.Utf8)", ""),
    ('новый Образец("[0-9]+")', ""),
    ("новый РазмерБайтов(Мб = 1)", ""),
    ("новый Массив<Число>()", ""),
    ("НайтиТип(ИмяТипа)", "ИмяТипа: Строка"),
])
def test_arguments_that_are_not_constants_and_types_without_a_literal_stay_quiet(expression, params):
    assert _lint(_method(expression, params)) == []


def test_negative_control_the_same_call_with_a_constant_is_reported():
    """The quiet variable form above is quiet because of the argument, not a silent rule."""
    assert len(_lint(_method('новый Дата("2026-01-31")', "Срок: Строка"))) == 1


def test_a_type_the_module_declares_is_not_the_platform_one():
    text = (
        "структура Версия\n"
        "    пер Номер: Строка\n"
        ";\n\n"
        + _method('новый Версия("2")')
    )
    assert _lint(text) == []


def test_find_type_declared_by_the_module_is_its_own_method():
    text = (
        "метод НайтиТип(Имя: Строка): Тип?\n"
        "    возврат Неопределено\n"
        ";\n\n"
        + _method('НайтиТип("Склады")')
    )
    assert _lint(text) == []


def test_a_variable_named_like_the_type_does_not_hide_it():
    text = "метод Проба(): Дата\n    знч Дата = новый Дата(\"2026-01-31\")\n    возврат Дата\n;\n"
    assert len(_lint(text)) == 1


def test_a_comment_inside_the_call_keeps_the_call():
    found = _lint(_method('новый Дата( // крайний срок\n        "2026-01-31")'))

    assert len(found) == 1 and found[0].fix is None


def test_a_member_access_after_a_bare_literal_keeps_the_call():
    found = _lint(_method('новый Число("5").ВСтроку()', result="Строка"))

    assert len(found) == 1 and found[0].fix is None


def test_a_member_access_after_a_braced_literal_is_rewritten():
    text = _method('новый Дата("2026-01-31").ДеньГода()', result="Число")
    found = _lint(text)

    assert _fixed(text, found[0]) == _method("Дата{2026-01-31}.ДеньГода()", result="Число")


def test_calls_inside_strings_and_comments_are_not_code():
    text = (
        "метод Проба(): Строка\n"
        '    // новый Дата("2026-01-31")\n'
        '    возврат "новый Дата(\\"2026-01-31\\")"\n'
        ";\n"
    )
    assert _lint(text) == []


def test_every_statement_shape_is_walked():
    """Branches of `если` and `попытка` are tuples in the tree - the walk must enter them."""
    text = (
        "метод Проба(Флаг: Булево): Дата\n"
        "    если Флаг\n"
        '        возврат новый Дата("2026-01-31")\n'
        "    ;\n"
        "    попытка\n"
        '        возврат новый Дата("2026-02-01")\n'
        "    поймать Ошибка: Исключение\n"
        '        возврат новый Дата("2026-02-02")\n'
        "    ;\n"
        "    возврат Дата{}\n"
        ";\n"
    )
    assert [d.line for d in _lint(text)] == [3, 6, 8]


# --- the fix on a file --------------------------------------------------------------------------

def test_cli_fix_rewrites_a_copy_of_the_file(tmp_path: Path):
    """--fix on a file with CRLF endings: offsets index the decoded file text, not a test string."""
    source = (
        "@НаСервере\r\n"
        "метод КрайнийСрок(Срок: Дата): Дата\r\n"
        '    возврат Срок == Дата{} ? новый Дата("9999-12-31") : Срок\r\n'
        ";\r\n"
    )
    module = tmp_path / "Задачи.xbsl"
    module.write_bytes(source.encode("utf-8"))

    code = cli.main([str(module), "--select", RULE, "--no-baseline", "--fix"])

    assert code == 0
    assert module.read_bytes().decode("utf-8") == source.replace('новый Дата("9999-12-31")', "Дата{9999-12-31}")
    assert _lint(module.read_bytes().decode("utf-8"), "Задачи.xbsl") == []
