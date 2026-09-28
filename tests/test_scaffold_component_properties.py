"""The properties of an interface component go in through add-field like any other item.

The `Properties` section of a component - the values its module reads through `этот` and a
form using the component fills in - was the one section add-field refused: the kind was left
out of the extendable ones, and the answer was "no extendable sections" while the file had
exactly such a section. Every property was then written into the yaml by hand, description
and all.

A property is a name and a type; its class declares no `Id`. A missing section goes where
the designer writes it - after `Inherits`, before `Events` - and the description of an item
becomes its documentation comment: the `##` lines at its head, the only comment the
development environment keeps when it writes the file out again.
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


def test_the_component_lists_its_properties_among_the_sections(tmp_path):
    path = _component(tmp_path, _HEAD + _PROPERTIES)

    info = scaffold.object_info(tmp_path, yaml_path=path)

    assert info["sections"] == {"свойство": ["Название"]}


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


@pytest.mark.needs_data  # the documentation slots and the rules come from the metamodel
def test_the_written_component_passes_the_yaml_rules(tmp_path):
    path = _component(tmp_path, _HEAD + _EVENTS)
    scaffold.apply_result(scaffold.op_add_field(path, "свойство", "Название",
                                                doc="Название склада."))
    scaffold.apply_result(scaffold.op_add_field(path, "свойство", "Вместимость", type_="Число",
                                                doc="Сколько партий помещается."))

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


def test_the_mcp_tool_writes_the_property_with_its_description(mcp_module, tmp_path):
    path = _component(tmp_path, _HEAD + _EVENTS)

    res = mcp_module.meta_add_field(str(path), "свойство", "Название", doc="Название склада.")

    assert "error" not in res, res
    text = path.read_text(encoding="utf-8-sig")
    assert "Свойства:\n    -\n        ## Название склада.\n        Имя: Название\n" in text
    batch = mcp_module.meta_add_field(str(path), "свойство", names=["Адрес", "Вместимость"],
                                      doc="Общий текст")
    assert "одному элементу" in batch["error"]


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
