"""The values add-field and set-field-property write: the words and the quotes of the file.

Two ways a value read differently from the file around it:

- a boolean given as a word through the CLI (`--prop Многострочная=Истина`) was written as the
  word came, so an English file got a Russian island - while the same boolean from the MCP (a
  JSON `true`) came out `True`. A property the metamodel types as a boolean, and the default of
  an item whose own type is boolean, is spelled by the file whichever word came in; any other
  text is the author's and stays as written;
- a type set among the properties of set-field-property was quoted over a `>` that add-field
  wrote bare. One rule decides for both now, the rule of the YAML grammar: quotes where a bare
  value would read as something else, and nowhere else.

The help of both commands lists the field kinds out of the operations' own table, so it can
no longer leave out a kind the operation takes.
"""

from __future__ import annotations

import argparse
import json

import pytest
import yaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import cli, scaffold

_SET_RU = (
    "ВидЭлемента: НаборКонстант\n"
    "Ид: 5b7c3e10-0000-4000-8000-0000000000d1\n"
    "Имя: НастройкиУчета\n"
    "ОбластьВидимости: ВПроекте\n"
)
_SET_EN = (
    "ElementKind: ConstantsSet\n"
    "Id: 5b7c3e10-0000-4000-8000-0000000000d2\n"
    "Name: AccountingSettings\n"
    "VisibilityScope: InProject\n"
)
_CONSTANT_RU = (
    "Константы:\n"
    "    -\n"
    "        Ид: 5b7c3e10-0000-4000-8000-0000000000d3\n"
    "        Имя: {name}\n"
    "        Тип: {type}\n"
)
_CONSTANT_EN = (
    "Constants:\n"
    "    -\n"
    "        Id: 5b7c3e10-0000-4000-8000-0000000000d4\n"
    "        Name: {name}\n"
    "        Type: {type}\n"
)

_COMPONENT = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 5b7c3e10-0000-4000-8000-0000000000d5\n"
    "Имя: КарточкаПартии\n"
    "ОбластьВидимости: ВПроекте\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "События:\n"
    "    -\n"
    "        Имя: ПриОчисткеПартии\n"
    "        Тип: СобытиеКомпонента\n"
)


def _file(tmp_path, text: str, name: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _added(path, name: str, **kwargs) -> str:
    return scaffold.op_add_field(path, "константа", name, **kwargs).changes[0].content


def _set(path, name: str, props: dict) -> str:
    return scaffold.op_set_field_property(path, "константа", name, props).changes[0].content


# --- a boolean in the words of the file -------------------------------------------------------


@pytest.mark.needs_data  # the kind of a property and its English key come from the metamodel
@pytest.mark.parametrize("given, russian, english", [
    ("Истина", "Истина", "True"),
    ("True", "Истина", "True"),
    ("ложь", "Ложь", "False"),
    ("false", "Ложь", "False"),
], ids=["ru-word", "en-word", "ru-lower", "yaml-lower"])
def test_a_boolean_word_is_written_in_the_words_of_the_file(tmp_path, given, russian, english):
    ru = _file(tmp_path, _SET_RU, "НастройкиУчета.yaml")
    en = _file(tmp_path, _SET_EN, "AccountingSettings.yaml")

    ru_text = _added(ru, "Комментарий", props={"Многострочная": given})
    en_text = _added(en, "Comment", props={"Multiline": given})

    assert ru_text.endswith(f"        Многострочная: {russian}\n")
    assert en_text.endswith(f"        Multiline: {english}\n")


@pytest.mark.needs_data  # the kind of a property and its English key come from the metamodel
def test_a_boolean_word_elsewhere_stays_the_authors_text(tmp_path):
    # The control: a caption is text, and a boolean property given something that is not a
    # boolean word keeps it too - the compiler is the one to refuse it, not the tool to guess.
    en = _file(tmp_path, _SET_EN, "AccountingSettings.yaml")

    text = _added(en, "Comment", props={"Presentation": "Истина", "Multiline": "Да"})

    assert "        Presentation: Истина\n" in text
    assert "        Multiline: Да\n" in text


@pytest.mark.needs_data  # the kind of a property and its English key come from the metamodel
def test_set_field_property_spells_a_boolean_by_the_file_as_well(tmp_path):
    ru = _file(tmp_path, _SET_RU + _CONSTANT_RU.format(name="Комментарий", type="Строка")
               + "        Многострочная: Ложь\n", "НастройкиУчета.yaml")
    en = _file(tmp_path, _SET_EN + _CONSTANT_EN.format(name="Comment", type="String")
               + "        Multiline: False\n", "AccountingSettings.yaml")

    ru_text = _set(ru, "Комментарий", {"Многострочная": "True", "ЗаполнятьПриКопировании": "false"})
    en_text = _set(en, "Comment", {"Multiline": "Истина", "FillOnCopy": "Ложь"})

    # One line replaced in place, one appended - both in the words of the file.
    assert ru_text.endswith("        Многострочная: Истина\n        ЗаполнятьПриКопировании: Ложь\n")
    assert en_text.endswith("        Multiline: True\n        FillOnCopy: False\n")


def test_the_default_of_a_boolean_item_is_a_boolean_too(tmp_path):
    # The metamodel records the default as a value of any type: the item's own type tells
    # what it holds. A Russian file needs no data for that.
    ru = _file(tmp_path, _SET_RU, "НастройкиУчета.yaml")

    flag = _added(ru, "ВестиУчетПартий", type_="Булево", props={"ЗначениеПоУмолчанию": "true"})
    maybe = _added(ru, "УчетСерий", type_="Булево?", props={"ЗначениеПоУмолчанию": "False"})
    text = _added(ru, "Подпись", type_="Строка", props={"ЗначениеПоУмолчанию": "true"})

    assert flag.endswith("        Тип: Булево\n        ЗначениеПоУмолчанию: Истина\n")
    assert maybe.endswith("        Тип: Булево?\n        ЗначениеПоУмолчанию: Ложь\n")
    # The control: the default of a string is the author's text.
    assert text.endswith("        Тип: Строка\n        ЗначениеПоУмолчанию: true\n")


@pytest.mark.needs_data  # the English keys and the boolean pair come from the platform data
def test_the_default_of_a_boolean_item_follows_an_english_file(tmp_path):
    en = _file(tmp_path, _SET_EN, "AccountingSettings.yaml")

    flag = _added(en, "TrackBatches", type_="Boolean", props={"DefaultValue": "Истина"})
    text = _added(en, "Caption", type_="String", props={"DefaultValue": "Истина"})

    assert flag.endswith("        Type: Boolean\n        DefaultValue: True\n")
    assert text.endswith("        Type: String\n        DefaultValue: Истина\n")


@pytest.mark.needs_data  # the English keys and the boolean pair come from the platform data
def test_set_field_property_reads_the_type_of_the_item_for_its_default(tmp_path):
    en = _file(tmp_path, _SET_EN + _CONSTANT_EN.format(name="TrackBatches", type="Boolean"),
               "AccountingSettings.yaml")
    ru = _file(tmp_path, _SET_RU + _CONSTANT_RU.format(name="Подпись", type="Строка"),
               "НастройкиУчета.yaml")

    declared = _set(en, "TrackBatches", {"DefaultValue": "Ложь"})
    retyped = _set(ru, "Подпись", {"Тип": "Булево", "ЗначениеПоУмолчанию": "True"})
    kept = _set(ru, "Подпись", {"ЗначениеПоУмолчанию": "True"})

    assert declared.endswith("        Type: Boolean\n        DefaultValue: False\n")
    # The type this very call sets decides, not the one the item had.
    assert retyped.endswith("        Тип: Булево\n        ЗначениеПоУмолчанию: Истина\n")
    assert kept.endswith("        Тип: Строка\n        ЗначениеПоУмолчанию: True\n")


# --- the quotes: the rule of the YAML grammar -------------------------------------------------


def test_a_type_reads_the_same_whichever_operation_writes_it(tmp_path):
    component = _file(tmp_path, _COMPONENT, "КарточкаПартии.yaml")

    added = scaffold.op_add_field(component, "событие", "ПриВыбореПартии",
                                  type_="СобытиеСДанными<Строка>").changes[0].content
    retyped = scaffold.op_set_field_property(component, "событие", "ПриОчисткеПартии",
                                             {"Тип": "СобытиеСДанными<Строка>"}).changes[0].content

    assert "        Имя: ПриВыбореПартии\n        Тип: СобытиеСДанными<Строка>\n" in added
    assert "        Имя: ПриОчисткеПартии\n        Тип: СобытиеСДанными<Строка>\n" in retyped


def test_the_cli_writes_a_type_property_bare(tmp_path, capsys):
    component = _file(tmp_path, _COMPONENT, "КарточкаПартии.yaml")

    code = cli.main(["set-field-property", str(component), "событие", "ПриОчисткеПартии",
                     "--prop", "Тип=СобытиеСДанными<Массив<Строка>>", "--dry-run"])

    assert code == 0
    content = json.loads(capsys.readouterr().out)["files"][0]["content"]
    assert "        Тип: СобытиеСДанными<Массив<Строка>>\n" in content
    assert yaml.safe_load(content)["События"][0]["Тип"] == "СобытиеСДанными<Массив<Строка>>"


@pytest.mark.parametrize("value", [
    "СобытиеСДанными<Строка>", "Строка|Число", "e1c::Партии::Партия", "https://example.com/api",
    'Фирма "Ромашка"', "Партия#2", "Партия!", "50%", "-5",
], ids=["generic", "union", "namespace", "address", "inner-quotes", "inner-hash", "bang",
        "percent", "negative"])
def test_an_indicator_inside_a_value_leaves_it_bare(value):
    assert scaffold._yaml_scalar(value) == value
    assert yaml.load(f"k: {value}\n", Loader=yaml.BaseLoader)["k"] == value


@pytest.mark.parametrize("value", [
    "Итого: 5", "Партия #2 и #3", ">Партия", "[Партия]", "{Партия}", "&Партия", "*Партия",
    "!Партия", "|Партия", "%Партия", "@Партия", "- Партия", "-", "Партия:", "14:53",
    " Партия", "Партия ", "", "Партия\tСклад",
])
def test_a_value_a_bare_scalar_would_misread_is_quoted(value):
    written = scaffold._yaml_scalar(value)

    assert written.startswith('"') and written.endswith('"')
    assert yaml.safe_load(f"k: {written}\n")["k"] == value


def test_a_value_the_caller_quoted_is_left_as_it_is():
    assert scaffold._yaml_scalar('"Итого: 5"') == '"Итого: 5"'
    assert scaffold._yaml_scalar("'Итого: 5'") == "'Итого: 5'"


def test_a_quoted_value_reads_back_through_the_file(tmp_path):
    ru = _file(tmp_path, _SET_RU, "НастройкиУчета.yaml")

    text = _added(ru, "Подпись", props={"ЗначениеПоУмолчанию": "Итого: 5",
                                        "Представление": "Склад [основной] 2&3"})

    assert '        ЗначениеПоУмолчанию: "Итого: 5"\n' in text
    assert "        Представление: Склад [основной] 2&3\n" in text
    constant = yaml.safe_load(text)["Константы"][0]
    assert constant["ЗначениеПоУмолчанию"] == "Итого: 5"
    assert constant["Представление"] == "Склад [основной] 2&3"


# --- the kinds the help lists -------------------------------------------------------------------


def _kinds_in_help(command: str) -> list[str]:
    parser = cli._scaffold_parser()
    subparsers = next(action for action in parser._actions
                      if isinstance(action, argparse._SubParsersAction))
    field_kind = next(action for action in subparsers.choices[command]._actions
                      if action.dest == "field_kind")
    return field_kind.help.split(", ")


def test_the_help_names_every_kind_the_operation_takes():
    # What the operations take is what some object kind has a section for.
    taken = {kind for kinds in scaffold.KIND_SECTIONS.values() for kind in kinds}
    entries = set(scaffold._MAPPING_SPECS)  # a key and a value: nothing to set on one

    assert set(_kinds_in_help("add-field")) == taken
    assert set(_kinds_in_help("set-field-property")) == taken - entries
    # The kinds the hand-written lists had left out.
    assert {"константа", "операция", "индекс", "параметр-запроса"} <= set(
        _kinds_in_help("add-field"))
    assert {"табличная-часть", "операция", "индекс", "параметр-запроса"} <= set(
        _kinds_in_help("set-field-property"))


def test_set_field_property_takes_a_tabular_section(tmp_path):
    catalog = _file(tmp_path, (
        "ВидЭлемента: Справочник\n"
        "Ид: 5b7c3e10-0000-4000-8000-0000000000d6\n"
        "Имя: Партии\n"
        "ОбластьВидимости: ВПроекте\n"
        "ТабличныеЧасти:\n"
        "    -\n"
        "        Ид: 5b7c3e10-0000-4000-8000-0000000000d7\n"
        "        Имя: Ячейки\n"
    ), "Партии.yaml")

    text = scaffold.op_set_field_property(catalog, "табличная-часть", "Ячейки",
                                          {"ЗаполнятьПриКопировании": "Ложь"}).changes[0].content

    assert text.endswith("        Имя: Ячейки\n        ЗаполнятьПриКопировании: Ложь\n")
