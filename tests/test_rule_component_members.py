"""yaml/component-member-unique: the own properties and events of a component share one namespace.

A live probe was refused twice for a component that declared a property and an event of the
same name: "Property name X is not unique" at the property, "Event name X is not unique" at
the event. The rule reads the yaml alone, so the Russian cases run in a clean checkout; an
English file needs the data for the English spellings of the keys.
"""

import pytest

from xbsl import engine

RULE = "yaml/component-member-unique"

_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 0c0c0c0c-1111-2222-3333-444444444444\n"
    "Имя: ПанельПробы\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "    Содержимое:\n"
    "        -\n"
    "            Тип: Надпись\n"
    "            Имя: Смена\n"
)


def _members(properties=(), events=()) -> str:
    text = _HEAD
    if properties:
        text += "Свойства:\n" + "".join(
            f"    -\n        Имя: {name}\n        Тип: Строка\n" for name in properties
        )
    if events:
        text += "События:\n" + "".join(
            f"    -\n        Имя: {name}\n        Тип: СобытиеКомпонента\n" for name in events
        )
    return text


def _lint(text: str, name: str = "ПанельПробы.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={RULE})


def test_property_and_event_of_one_name_are_reported():
    diags = _lint(_members(properties=["Смена"], events=["Смена"]))
    assert [d.rule_id for d in diags] == [RULE]
    # At the later of the two - the event - naming the line of the property.
    text = _members(properties=["Смена"], events=["Смена"])
    event_line = text.splitlines().index("        Имя: Смена", 14) + 1
    assert diags[0].line == event_line
    assert "Событие 'Смена'" in diags[0].message and "(свойство)" in diags[0].message
    assert 'Event name "Смена" is not unique' in diags[0].message


def test_distinct_names_are_silent():
    # The negative control: the same file with the event renamed.
    assert _lint(_members(properties=["Смена"], events=["ПриСмене"])) == []


def test_a_name_repeated_inside_one_section_is_reported_once():
    diags = _lint(_members(properties=["Режим", "Режим"]))
    assert len(diags) == 1
    assert 'Property name "Режим" is not unique' in diags[0].message


def test_a_nested_component_name_is_another_namespace():
    # `Смена` names a label of the markup; the component's own property may share it.
    assert _lint(_members(properties=["Смена"])) == []


def test_other_kinds_are_not_judged():
    text = _members(properties=["Смена"], events=["Смена"]).replace(
        "КомпонентИнтерфейса", "Структура", 1,
    )
    assert _lint(text) == []


@pytest.mark.needs_data
def test_english_file_is_judged():
    text = (
        "ElementKind: InterfaceComponent\n"
        "Id: 0c0c0c0c-1111-2222-3333-444444444444\n"
        "Name: TrialPanel\n"
        "Inherits:\n"
        "    Type: Group\n"
        "Properties:\n"
        "    -\n        Name: Shift\n        Type: String\n"
        "Events:\n"
        "    -\n        Name: Shift\n        Type: ComponentEvent\n"
    )
    diags = _lint(text, "TrialPanel.yaml")
    assert [d.rule_id for d in diags] == [RULE]
