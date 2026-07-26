"""The yaml/presentation-field rule: the value of Представление on a data object.

Where the metamodel declares Представление an attribute name (type AttributeName - a catalog,
a document, a constant set...), the value must name an existing STRING attribute of the object
(the platform documentation, topics/element-view). The whole module needs the metamodel and is
listed in conftest._DATA_DEPENDENT.

Both production gotchas are covered: a pasted title text ("Field specified as a presentation
field is not found" on deploy) and a reference-typed attribute ("The type of the field specified
as a presentation is not String").
"""

from xbsl import engine

_RULE = "yaml/presentation-field"
_ID = "11111111-2222-3333-4444-555555555555"


def _lint(tail, vid="Справочник"):
    text = f"ВидЭлемента: {vid}\nИд: {_ID}\nИмя: Тест\n{tail}"
    source = engine.load_text("Тест.yaml", text)
    return engine.run_sources([source], select={_RULE})


def _attr(name, typ=None, ident="22222222-3333-4444-5555-000000000001"):
    out = f"    -\n        Ид: {ident}\n        Имя: {name}\n"
    if typ:
        out += f"        Тип: {typ}\n"
    return out


def test_title_text_is_not_an_attribute_name():
    # The production gotcha: a human title pasted into the property; the deploy fails with
    # "Field specified as a presentation field is not found" - the rule catches it earlier.
    d = _lint("Представление: Активные пользователи\nРеквизиты:\n" + _attr("Наименование"))
    assert len(d) == 1
    assert d[0].rule_id == _RULE
    assert d[0].severity.value == "error"
    assert "нет реквизита" in d[0].message
    assert d[0].line == 4  # the Представление line


def test_declared_name_attribute_silent():
    assert _lint("Представление: Наименование\nРеквизиты:\n" + _attr("Наименование")) == []


def test_reference_attribute_rejected():
    # The second production gotcha: the attribute exists but is a reference, not a string
    # ("The type of the field specified as a presentation is not String").
    tail = "Представление: Пользователь\nРеквизиты:\n" + _attr("Пользователь", "Пользователи.Ссылка")
    d = _lint(tail)
    assert len(d) == 1
    assert "Пользователи.Ссылка" in d[0].message


def test_explicit_string_attribute_silent():
    assert _lint("Представление: Заголовок\nРеквизиты:\n" + _attr("Заголовок", "Строка")) == []


def test_nullable_string_left_alone():
    # Строка? still allows a string - not proven invalid, the rule stays silent.
    assert _lint("Представление: Заголовок\nРеквизиты:\n" + _attr("Заголовок", "Строка?")) == []


def test_standard_code_defaults_to_string():
    # Код without Тип: the metamodel default of CodeAttributeDescriptor is Стд::Строка.
    assert _lint("Представление: Код\nРеквизиты:\n" + _attr("Код")) == []


def test_standard_code_declared_as_number_rejected():
    d = _lint("Представление: Код\nРеквизиты:\n" + _attr("Код", "Число"))
    assert len(d) == 1
    assert "Число" in d[0].message


def test_undeclared_standard_name_rejected():
    # Наименование exists only when declared (Имя: Наименование) - without the record the
    # compiler finds no field, and neither does the rule.
    d = _lint("Представление: Наименование\n")
    assert len(d) == 1
    assert "Наименование" in d[0].message


def test_text_presentation_kind_not_judged():
    # A command's Представление is a localizable text, not an attribute name.
    assert _lint("Представление: Открыть список\n", vid="ОбычнаяКоманда") == []


def test_missing_value_is_another_rules_business():
    # Requiring the property is naming/presentation's job; this rule judges only a set value.
    assert _lint("Реквизиты:\n" + _attr("Наименование")) == []


def test_localized_reference_skipped():
    # A $-reference points into localized strings, not at an attribute - not judged.
    assert _lint("Представление: $НС::Строки.Ключ\nРеквизиты:\n" + _attr("Наименование")) == []
