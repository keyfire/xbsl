"""The properties and events of an interface component go in through add-field like any other item.

The `Properties` section of a component - the values its module reads through `этот` and a
form using the component fills in - was the one section add-field refused: the kind was left
out of the extendable ones, and the answer was "no extendable sections" while the file had
exactly such a section. Every property was then written into the yaml by hand, description
and all.

A property is a name and a type; its class declares no `Id`. A missing section goes where
the designer writes it - after `Inherits`, before `Events` - and the description of an item
becomes its documentation comment: the `##` lines at its head, the only comment the
development environment keeps when it writes the file out again.

A property also takes the default value the documentation describes for it, together with
`StoredData` and `Contextual`: the class the metamodel resolved the item to was the light
model the platform reads a component with first, which knows the name and the type alone, so
the value every list form carries was refused. An event is a name and the type of its event
object - a `ComponentEvent` when none is given; its section follows `Properties`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import cli, engine, scaffold
from xbsl.scaffold import ScaffoldError

_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 6f0b6a44-0000-4000-8000-0000000000c1\n"
    "Имя: КарточкаСклада\n"
    "ОбластьВидимости: ВПроекте\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "    Содержимое:\n"
    "        -\n"
    "            Тип: Надпись\n"
    "            Значение: =этот.Название\n"
)

_PROPERTIES = (
    "Свойства:\n"
    "    -\n"
    "        ## Название склада.\n"
    "        Имя: Название\n"
    "        Тип: Строка\n"
)

_EVENTS = (
    "События:\n"
    "    -\n"
    "        Имя: ПриВыбореСклада\n"
    "        Тип: СобытиеКомпонента\n"
)

_HEAD_EN = (
    "ElementKind: InterfaceComponent\n"
    "Id: 6f0b6a44-0000-4000-8000-0000000000c2\n"
    "Name: WarehouseCard\n"
    "VisibilityScope: InProject\n"
    "Inherits:\n"
    "    Type: Group\n"
    "    Content:\n"
    "        -\n"
    "            Type: Label\n"
    "            Value: =this.Title\n"
)

_EVENTS_EN = (
    "Events:\n"
    "    -\n"
    "        Name: OnWarehouseChosen\n"
    "        Type: ComponentEvent\n"
)


def _component(tmp_path: Path, text: str, name: str = "КарточкаСклада.yaml") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def _added(path: Path, name: str, **kw) -> str:
    """The text add-field plans for the file; the file itself is left as it was."""
    return scaffold.op_add_field(path, "свойство", name, **kw).changes[0].content


def _event_added(path: Path, name: str, **kw) -> str:
    """The same for an event of the component."""
    return scaffold.op_add_field(path, "событие", name, **kw).changes[0].content


def _top_keys(text: str) -> list[str]:
    return list(yaml.safe_load(text))


# --- the section ----------------------------------------------------------------------------


def test_a_property_joins_the_existing_properties_section(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    text = _added(path, "Вместимость", type_="Число")

    items = yaml.safe_load(text)["Свойства"]
    assert [item["Имя"] for item in items] == ["Название", "Вместимость"]
    # A name and a type, nothing else - the class of the item declares no Id.
    assert items[1] == {"Имя": "Вместимость", "Тип": "Число"}
    # A pinpoint insertion: everything the file had stays as it was, the comment included.
    assert text.startswith(_HEAD + _PROPERTIES)


def test_a_missing_section_is_created_at_the_end_of_the_file(tmp_path):
    path = _component(tmp_path, _HEAD)

    text = _added(path, "Название")

    assert text == _HEAD + "Свойства:\n    -\n        Имя: Название\n        Тип: Строка\n"
    assert _top_keys(text)[-2:] == ["Наследует", "Свойства"]


def test_a_missing_section_goes_in_front_of_the_events(tmp_path):
    # A note written over the events stays over them.
    path = _component(tmp_path, _HEAD + "# the events of the card\n" + _EVENTS)

    text = _added(path, "Название")

    assert text == (
        _HEAD + "Свойства:\n    -\n        Имя: Название\n        Тип: Строка\n"
        "# the events of the card\n" + _EVENTS
    )
    assert _top_keys(text)[-3:] == ["Наследует", "Свойства", "События"]


def test_a_crlf_file_keeps_its_line_ends(tmp_path):
    path = _component(tmp_path, (_HEAD + _EVENTS).replace("\n", "\r\n"))

    text = _added(path, "Название", doc="Название склада.\nКороткое, в одну строку.")

    # Every line end is the file's own: no bare LF, no lone CR - the description included.
    assert text.count("\n") == text.count("\r\n") == text.count("\r")
    assert "    -\r\n        ## Название склада.\r\n        ## Короткое" in text
    assert _top_keys(text)[-2:] == ["Свойства", "События"]


def test_a_taken_name_is_refused(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    with pytest.raises(ScaffoldError, match="'Название' уже есть в секции Свойства"):
        _added(path, "Название")


def test_the_component_lists_its_properties_and_events_among_the_sections(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES + _EVENTS)

    info = scaffold.object_info(tmp_path, yaml_path=path)

    assert info["sections"] == {"свойство": ["Название"], "событие": ["ПриВыбореСклада"]}


# --- the description -----------------------------------------------------------------------


def test_the_description_opens_the_item(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    text = _added(path, "Адрес", doc="Адрес склада.\n\nПоказывается под названием.  \n")

    assert text.endswith(
        "    -\n"
        "        ## Адрес склада.\n"
        "        ##\n"
        "        ## Показывается под названием.\n"
        "        Имя: Адрес\n"
        "        Тип: Строка\n"
    )
    # A comment, not a key: the item reads the same as one without a description.
    assert yaml.safe_load(text)["Свойства"][1] == {"Имя": "Адрес", "Тип": "Строка"}


def test_an_attribute_of_a_tabular_part_takes_a_description_too(tmp_path):
    """The description is not the component's alone: any item with a documentation comment."""
    path = _component(tmp_path, (
        "ВидЭлемента: Справочник\n"
        "Ид: 6f0b6a44-0000-4000-8000-0000000000c5\n"
        "Имя: Склады\n"
        "ТабличныеЧасти:\n"
        "    -\n"
        "        Ид: 6f0b6a44-0000-4000-8000-0000000000c6\n"
        "        Имя: Партии\n"
        "        Реквизиты:\n"
        "            -\n"
        "                Ид: 6f0b6a44-0000-4000-8000-0000000000c7\n"
        "                Имя: Номер\n"
        "                Тип: Строка\n"
    ), "Склады.yaml")

    result = scaffold.op_add_field(path, "реквизит", "Количество", type_="Число",
                                   tabular="Партии", doc="Сколько единиц в партии.")

    text = result.changes[0].content
    fields = " " * 16
    assert f"            -\n{fields}## Сколько единиц в партии.\n{fields}Ид: " in text
    attributes = yaml.safe_load(text)["ТабличныеЧасти"][0]["Реквизиты"]
    assert [item["Имя"] for item in attributes] == ["Номер", "Количество"]


def test_a_blank_description_writes_nothing(tmp_path):
    path = _component(tmp_path, _HEAD)

    assert _added(path, "Название", doc=" \n ") == _added(path, "Название")


def test_a_description_of_several_names_at_once_is_refused(tmp_path):
    path = _component(tmp_path, _HEAD)

    with pytest.raises(ScaffoldError, match="одному элементу"):
        scaffold.op_add_fields(path, "свойство", ["Название", "Адрес"], doc="Общий текст")


def test_a_description_of_a_mapping_entry_is_refused(tmp_path):
    path = _component(tmp_path, (
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Ид: 6f0b6a44-0000-4000-8000-0000000000c3\n"
        "Имя: СтрокиСкладов\n"
        "Строки:\n"
        "    Склад: Склад\n"
    ), "СтрокиСкладов.yaml")

    with pytest.raises(ScaffoldError, match="документирующего комментария"):
        scaffold.op_add_field(path, "строка", "Партия", doc="Подпись партии")


def test_a_description_with_a_control_character_is_refused(tmp_path):
    path = _component(tmp_path, _HEAD)

    with pytest.raises(ScaffoldError, match="управляющий символ"):
        _added(path, "Название", doc="Название\x00склада")


# --- the default value and the other keys of a property --------------------------------------


@pytest.mark.needs_data  # the keys a property takes are its metamodel class's own
def test_a_property_takes_its_default_value_and_the_other_keys_of_its_class(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    text = _added(path, "Показывать", type_="Булево", props={
        "ЗначениеПоУмолчанию": False, "СохраняемыеДанные": True, "Контекстное": "Истина",
    })

    assert text.endswith(
        "    -\n"
        "        Имя: Показывать\n"
        "        Тип: Булево\n"
        "        ЗначениеПоУмолчанию: Ложь\n"
        "        СохраняемыеДанные: Истина\n"
        "        Контекстное: Истина\n"
    )


@pytest.mark.needs_data  # both spellings of a key come from the metamodel
def test_a_property_key_is_accepted_in_english_and_written_in_the_file_language(tmp_path):
    path = _component(tmp_path, _HEAD)

    text = _added(path, "Вместимость", type_="Число", props={"DefaultValue": 0})

    assert yaml.safe_load(text)["Свойства"] == [
        {"Имя": "Вместимость", "Тип": "Число", "ЗначениеПоУмолчанию": 0},
    ]


@pytest.mark.needs_data  # the list of the keys comes from the metamodel
def test_a_key_the_property_does_not_declare_is_refused_with_the_ones_it_does(tmp_path):
    path = _component(tmp_path, _HEAD)

    with pytest.raises(ScaffoldError, match="нет свойства 'Представление'") as refused:
        _added(path, "Название", props={"Представление": "Склад"})
    assert "ЗначениеПоУмолчанию" in str(refused.value)
    assert "Контекстное" in str(refused.value)


@pytest.mark.needs_data  # the keys a property takes are its metamodel class's own
def test_the_default_of_an_existing_property_is_set_in_place(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    text = scaffold.op_set_field_property(
        path, "свойство", "Название", {"ЗначениеПоУмолчанию": "Главный склад"},
    ).changes[0].content

    assert yaml.safe_load(text)["Свойства"] == [
        {"Имя": "Название", "Тип": "Строка", "ЗначениеПоУмолчанию": "Главный склад"},
    ]


_PROPERTIES_EN = (
    "Properties:\n"
    "    -\n"
    "        Name: Title\n"
    "        Type: String\n"
)


@pytest.mark.needs_data  # the English keys and the boolean pair come from the platform data
def test_a_boolean_goes_into_an_english_component_the_way_english_sources_write_it(tmp_path):
    # The English sources of the distribution write `True` and `False`; the Russian word in the
    # middle of an English file is an island the next reader has to know.
    path = _component(tmp_path, _HEAD_EN, "WarehouseCard.yaml")

    text = _added(path, "Shown", type_="Boolean", props={
        "DefaultValue": False, "StoredData": True, "Contextual": "True",
    })

    assert text.endswith(
        "Properties:\n    -\n        Name: Shown\n        Type: Boolean\n"
        "        DefaultValue: False\n        StoredData: True\n        Contextual: True\n"
    )


@pytest.mark.needs_data  # the keys a property takes are its metamodel class's own
def test_a_boolean_set_on_an_existing_property_keeps_the_spelling_of_the_file(tmp_path):
    russian = _component(tmp_path, _HEAD + _PROPERTIES)
    english = _component(tmp_path, _HEAD_EN + _PROPERTIES_EN, "WarehouseCard.yaml")

    ru = scaffold.op_set_field_property(russian, "свойство", "Название",
                                        {"СохраняемыеДанные": True}).changes[0].content
    en = scaffold.op_set_field_property(english, "свойство", "Title",
                                        {"StoredData": True}).changes[0].content

    assert ru == _HEAD + _PROPERTIES + "        СохраняемыеДанные: Истина\n"
    assert en == _HEAD_EN + _PROPERTIES_EN + "        StoredData: True\n"


@pytest.mark.needs_data  # the schema answers from the metamodel
def test_the_schema_of_a_component_item_matches_what_add_field_takes(mcp_module):
    """metadata_schema is where a caller learns the keys before passing them: it has to
    name the default value add-field now takes, and an event holds a name and a type."""
    prop = mcp_module.metadata_schema("КомпонентИнтерфейса", sections=["Свойства"],
                                      names=["Название"])
    event = mcp_module.metadata_schema("КомпонентИнтерфейса", sections=["События"],
                                       names=["ПриВыборе"])

    assert {"ЗначениеПоУмолчанию", "СохраняемыеДанные", "Контекстное"} <= set(prop["props"])
    assert prop["props"]["Контекстное"]["en"] == "Contextual"
    assert set(event["props"]) == {"Имя", "Тип"}


# --- the events --------------------------------------------------------------------------------


def test_an_event_joins_the_existing_events_section(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES + _EVENTS)

    text = _event_added(path, "ПриОчисткеСклада", type_="СобытиеСДанными<Строка>")

    assert text == _HEAD + _PROPERTIES + _EVENTS + (
        "    -\n        Имя: ПриОчисткеСклада\n        Тип: СобытиеСДанными<Строка>\n"
    )


def test_an_event_without_a_type_is_a_component_event(tmp_path):
    # The platform's own default, written out: an event with no type is a `ComponentEvent`.
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    text = _event_added(path, "ПриВыбореСклада")

    assert text == _HEAD + _PROPERTIES + _EVENTS


def test_a_missing_events_section_follows_the_properties(tmp_path):
    # The properties stand before Inherits here: the events join them, the note written over
    # Inherits stays over it.
    inherits = "# the base\nНаследует:\n    Тип: Группа\n"
    head = "ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаСклада\n"
    path = _component(tmp_path, head + _PROPERTIES + inherits)

    text = _event_added(path, "ПриВыбореСклада")

    assert text == head + _PROPERTIES + _EVENTS + inherits
    assert _top_keys(text)[-3:] == ["Свойства", "События", "Наследует"]


def test_the_events_and_the_properties_land_the_same_whichever_comes_first(tmp_path):
    events_first = _component(tmp_path, _HEAD, "Первая.yaml")
    properties_first = _component(tmp_path, _HEAD, "Вторая.yaml")

    scaffold.apply_result(scaffold.op_add_field(events_first, "событие", "ПриВыбореСклада"))
    scaffold.apply_result(scaffold.op_add_field(events_first, "свойство", "Название"))
    scaffold.apply_result(scaffold.op_add_field(properties_first, "свойство", "Название"))
    scaffold.apply_result(scaffold.op_add_field(properties_first, "событие", "ПриВыбореСклада"))

    expected = _HEAD + "Свойства:\n    -\n        Имя: Название\n        Тип: Строка\n" + _EVENTS
    assert events_first.read_text(encoding="utf-8") == expected
    assert properties_first.read_text(encoding="utf-8") == expected


def test_a_taken_event_name_is_refused(tmp_path):
    path = _component(tmp_path, _HEAD + _EVENTS)

    with pytest.raises(ScaffoldError, match="'ПриВыбореСклада' уже есть в секции События"):
        _event_added(path, "ПриВыбореСклада")


def test_an_event_takes_a_description(tmp_path):
    path = _component(tmp_path, _HEAD)

    text = _event_added(path, "ПриВыбореСклада", doc="Склад выбран в списке.")

    assert text.endswith("События:\n    -\n        ## Склад выбран в списке.\n"
                         "        Имя: ПриВыбореСклада\n        Тип: СобытиеКомпонента\n")


@pytest.mark.needs_data  # the class of an event comes from the metamodel
def test_an_event_takes_no_default_value(tmp_path):
    path = _component(tmp_path, _HEAD)

    with pytest.raises(ScaffoldError, match="нет свойства 'ЗначениеПоУмолчанию'"):
        _event_added(path, "ПриВыбореСклада", props={"ЗначениеПоУмолчанию": "Истина"})


def test_a_property_and_an_event_share_one_namespace(tmp_path):
    """A live probe refused a component with a property and an event of one name ("Property
    name X is not unique", "Event name X is not unique"): add-field does not write one."""
    path = _component(tmp_path, _HEAD + _PROPERTIES + _EVENTS)

    with pytest.raises(ScaffoldError, match="'ПриВыбореСклада' уже есть в секции События"):
        _added(path, "ПриВыбореСклада")
    with pytest.raises(ScaffoldError, match="'Название' уже есть в секции Свойства"):
        _event_added(path, "Название")
    # The negative control: a free name goes into either section.
    assert "Имя: Емкость" in _added(path, "Емкость")
    assert "Имя: ПриОчистке" in _event_added(path, "ПриОчистке")


@pytest.mark.needs_data  # both spellings of the sections come from the metamodel
def test_a_property_and_an_event_share_one_namespace_in_english(tmp_path):
    path = _component(tmp_path, _HEAD_EN + _EVENTS_EN, "WarehouseCard.yaml")

    with pytest.raises(ScaffoldError, match="'OnWarehouseChosen' уже есть"):
        _added(path, "OnWarehouseChosen")


def test_an_event_is_the_component_s_own_kind(tmp_path):
    path = _component(tmp_path, (
        "ВидЭлемента: Структура\n"
        "Ид: 6f0b6a44-0000-4000-8000-0000000000c8\n"
        "Имя: ДанныеСклада\n"
    ), "ДанныеСклада.yaml")

    with pytest.raises(ScaffoldError, match="нет секции для 'событие'"):
        scaffold.op_add_field(path, "событие", "ПриИзменении")


# --- the language of the file and the linter -------------------------------------------------


@pytest.mark.needs_data  # the English keys are the metamodel's own
def test_an_english_component_gets_the_section_and_the_keys_in_english(tmp_path):
    path = _component(tmp_path, _HEAD_EN + _EVENTS_EN, "WarehouseCard.yaml")

    text = _added(path, "Title", type_="Строка", doc="The warehouse name.")

    assert text == (
        _HEAD_EN + "Properties:\n    -\n        ## The warehouse name.\n"
        "        Name: Title\n        Type: String\n" + _EVENTS_EN
    )


@pytest.mark.needs_data  # both spellings of the section come from the metamodel
def test_an_english_component_extends_its_properties_and_refuses_a_taken_name(tmp_path):
    path = _component(tmp_path, _HEAD_EN + "Properties:\n    -\n        Name: Title\n"
                                "        Type: String\n", "WarehouseCard.yaml")

    text = _added(path, "Capacity", type_="Number")

    assert yaml.safe_load(text)["Properties"] == [
        {"Name": "Title", "Type": "String"}, {"Name": "Capacity", "Type": "Number"},
    ]
    with pytest.raises(ScaffoldError, match="'Title' уже есть"):
        _added(path, "Title")


@pytest.mark.needs_data  # the English keys and type names are the platform's own
def test_an_english_component_gets_its_events_and_defaults_in_english(tmp_path):
    path = _component(tmp_path, _HEAD_EN, "WarehouseCard.yaml")
    scaffold.apply_result(scaffold.op_add_field(path, "событие", "OnWarehouseChosen"))
    scaffold.apply_result(scaffold.op_add_field(path, "свойство", "Title",
                                                props={"ЗначениеПоУмолчанию": "Main"}))

    # The default types are written the way the file writes its types, as a type the caller
    # passes already was - not a Russian name in the middle of an English file.
    assert path.read_text(encoding="utf-8") == (
        _HEAD_EN + "Properties:\n    -\n        Name: Title\n        Type: String\n"
        "        DefaultValue: Main\n" + _EVENTS_EN
    )


@pytest.mark.needs_data  # the documentation slots and the rules come from the metamodel
def test_the_written_component_passes_the_yaml_rules(tmp_path):
    path = _component(tmp_path, _HEAD + _EVENTS)
    scaffold.apply_result(scaffold.op_add_field(path, "свойство", "Название",
                                                doc="Название склада."))
    scaffold.apply_result(scaffold.op_add_field(path, "свойство", "Вместимость", type_="Число",
                                                props={"ЗначениеПоУмолчанию": 0},
                                                doc="Сколько партий помещается."))
    scaffold.apply_result(scaffold.op_add_field(path, "событие", "ПриОчисткеСклада",
                                                type_="СобытиеСДанными<Строка>",
                                                doc="Склад очищен."))

    # The group selected whole: the two comment rules are off by default and come with it.
    assert engine.run([path], select={"yaml"}) == []

    # The control: the same description one line higher, above the dash, is where the
    # environment does not read it - and the rule says so.
    text = path.read_text(encoding="utf-8-sig")
    misplaced = text.replace("    -\n        ## Название склада.\n",
                             "    ## Название склада.\n    -\n")
    assert misplaced != text
    path.write_text(misplaced, encoding="utf-8")
    assert [d.rule_id for d in engine.run([path], select={"yaml"})] == [
        "yaml/doc-comment-misplaced"
    ]


@pytest.mark.needs_data  # the class of a built-in attribute comes from the metamodel
def test_a_built_in_attribute_takes_no_description(tmp_path):
    path = _component(tmp_path, (
        "ВидЭлемента: Справочник\n"
        "Ид: 6f0b6a44-0000-4000-8000-0000000000c4\n"
        "Имя: Склады\n"
    ), "Склады.yaml")

    with pytest.raises(ScaffoldError, match="реквизита Код .*нет места для документирующего"):
        scaffold.op_add_field(path, "реквизит", "Код", doc="Код склада")
    # An ordinary attribute next to it holds a comment.
    text = scaffold.op_add_field(path, "реквизит", "Адрес", doc="Адрес склада").changes[0].content
    assert "    -\n        ## Адрес склада\n        Ид: " in text


# --- the surfaces --------------------------------------------------------------------------


def test_the_cli_passes_the_description(tmp_path, capsys):
    path = _component(tmp_path, _HEAD)

    code = cli.main(["add-field", str(path), "свойство", "Название", "--type", "Строка",
                     "--doc", "Название склада.", "--dry-run"])

    assert code == 0
    content = json.loads(capsys.readouterr().out)["files"][0]["content"]
    assert content.endswith("Свойства:\n    -\n        ## Название склада.\n"
                            "        Имя: Название\n        Тип: Строка\n")
    assert path.read_text(encoding="utf-8") == _HEAD  # a dry run writes nothing


@pytest.mark.parametrize("field_kind, name, prop, expected", [
    ("свойство", "Название", "ЗначениеПоУмолчанию=Главный склад",
     {"Имя": "Название", "Тип": "Строка", "ЗначениеПоУмолчанию": "Главный склад"}),
    ("событие", "ПриВыбореСклада", "Тип=СобытиеСДанными<Строка>",
     {"Имя": "ПриВыбореСклада", "Тип": "СобытиеСДанными<Строка>"}),
], ids=["property", "event"])
def test_the_cli_sets_a_property_and_an_event_of_the_component(
        tmp_path, capsys, field_kind, name, prop, expected):
    # The help of set-field-property names both kinds: the operation takes them the way
    # add-field does.
    path = _component(tmp_path, _HEAD + _PROPERTIES + _EVENTS)

    code = cli.main(["set-field-property", str(path), field_kind, name, "--prop", prop,
                     "--dry-run"])

    assert code == 0
    content = json.loads(capsys.readouterr().out)["files"][0]["content"]
    section = "Свойства" if field_kind == "свойство" else "События"
    assert yaml.safe_load(content)[section] == [expected]


def test_the_mcp_tool_writes_the_property_with_its_description(mcp_module, tmp_path):
    path = _component(tmp_path, _HEAD + _EVENTS)

    res = mcp_module.meta_add_field(str(path), "свойство", "Название", doc="Название склада.")

    assert "error" not in res, res
    text = path.read_text(encoding="utf-8-sig")
    assert "Свойства:\n    -\n        ## Название склада.\n        Имя: Название\n" in text
    batch = mcp_module.meta_add_field(str(path), "свойство", names=["Адрес", "Вместимость"],
                                      doc="Общий текст")
    assert "одному элементу" in batch["error"]


@pytest.mark.needs_data  # the English keys and the boolean pair come from the platform data
def test_the_mcp_tool_writes_a_json_boolean_in_the_spelling_of_the_file(mcp_module, tmp_path):
    # The MCP is where a boolean arrives as one: the JSON of the call carries `true`.
    path = _component(tmp_path, _HEAD_EN + _PROPERTIES_EN, "WarehouseCard.yaml")

    res = mcp_module.meta_set_field_property(str(path), "свойство", "Title",
                                             {"StoredData": True})

    assert "error" not in res, res
    assert path.read_text(encoding="utf-8-sig") == (
        _HEAD_EN + _PROPERTIES_EN + "        StoredData: True\n"
    )


def test_the_lsp_request_passes_the_description(tmp_path):
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from pygls import uris
    from pygls.workspace import Workspace

    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    # The operations read files through the editor buffers - a workspace has to exist.
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    path = _component(tmp_path, _HEAD)

    result = features["xbsl/metaAddField"]({
        "path": str(path), "fieldKind": "свойство", "name": "Название",
        "doc": "Название склада.",
    })

    assert result["files"][0]["content"].endswith(
        "Свойства:\n    -\n        ## Название склада.\n        Имя: Название\n"
        "        Тип: Строка\n"
    )


def test_every_surface_adds_an_event(tmp_path, capsys, mcp_module):
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from pygls import uris
    from pygls.workspace import Workspace

    from xbsl import lsp as lsp_module

    expected = "События:\n    -\n        ## Склад выбран.\n        Имя: ПриВыбореСклада\n"
    path = _component(tmp_path, _HEAD)

    code = cli.main(["add-field", str(path), "событие", "ПриВыбореСклада",
                     "--doc", "Склад выбран.", "--dry-run"])
    assert code == 0
    assert expected in json.loads(capsys.readouterr().out)["files"][0]["content"]

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    server.lsp._workspace = Workspace(uris.from_fs_path(str(tmp_path)))
    result = features["xbsl/metaAddField"]({
        "path": str(path), "fieldKind": "событие", "name": "ПриВыбореСклада",
        "doc": "Склад выбран.",
    })
    assert expected in result["files"][0]["content"]
    assert path.read_text(encoding="utf-8") == _HEAD  # neither of the two wrote the file

    res = mcp_module.meta_add_field(str(path), "событие", "ПриВыбореСклада",
                                    type="СобытиеСДанными<Строка>", doc="Склад выбран.")
    assert "error" not in res, res
    assert path.read_text(encoding="utf-8-sig").endswith(
        expected + "        Тип: СобытиеСДанными<Строка>\n"
    )
