"""xbsl/modulehandlers.py: the handlers a module of an interface component overrides by name.

The lists come from the `module_handlers` section of stdlib.json, each type with its own
handlers; the reader adds those of the bases, answers both spellings and walks a chain of
project components down to the platform type. Every test builds its own tiny data root, so
the module is checked in a public checkout too.
"""

import json

import pytest

from xbsl import dataset, modulehandlers

_STDLIB = {
    "meta": {"bilingual_keys": "expand"},
    "names": ["Компонент", "Форма", "ФормаОбъекта", "Надпись", "Объект"],
    "bases": {
        "Компонент": ["Объект"],
        "Форма": ["Компонент", "Объект"],
        "ФормаОбъекта": ["Компонент", "Объект", "Форма"],
        "Надпись": ["Компонент", "Объект"],
    },
    "module_handlers": {
        "Компонент": [{"ru": "ПослеСоздания", "en": "AfterCreate"}],
        "Форма": [{"ru": "ПередЗакрытием", "en": "BeforeClose"},
                  {"ru": "ПолучитьДанныеЧата", "en": "GetChatData", "to": "8.0"}],
        "ФормаОбъекта": [{"ru": "ПередЗаписью", "en": "BeforeWrite"}],
    },
}
_TERMS = {"types": {"Компонент": "Component", "Форма": "Form", "ФормаОбъекта": "ObjectForm",
                    "Надпись": "Label", "Объект": "Object"}}


def _root(tmp_path, stdlib: dict) -> None:
    version = tmp_path / "9.9.9"
    version.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": ["9.9.9"], "default": "9.9.9"}), encoding="utf-8")
    (version / "stdlib.json").write_text(json.dumps(stdlib, ensure_ascii=False), encoding="utf-8")
    (version / "terms.json").write_text(json.dumps(_TERMS, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def data(tmp_path):
    _root(tmp_path, _STDLIB)
    dataset.set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        dataset.set_data_root(None)


def test_a_type_answers_its_own_handlers_and_those_of_its_bases_nearest_first(data):
    rows = modulehandlers.rows_of("ФормаОбъекта")
    assert [row["ru"] for row in rows] == [
        "ПередЗаписью", "ПередЗакрытием", "ПолучитьДанныеЧата", "ПослеСоздания"]
    # The compatibility mode the description states travels with the row.
    assert rows[2]["to"] == "8.0"


def test_both_spellings_answer_the_english_one(data):
    names = modulehandlers.of_type("Форма")
    assert names["ПередЗакрытием"] == names["BeforeClose"] == "BeforeClose"
    assert names["ПослеСоздания"] == "AfterCreate"
    assert "ПередЗаписью" not in names  # the object form's own handler is not a form's


def test_an_english_type_name_reads_the_same_lists(data):
    assert modulehandlers.of_type("ObjectForm") == modulehandlers.of_type("ФормаОбъекта")


def test_a_component_without_handlers_of_its_own_inherits_the_base_ones(data):
    assert modulehandlers.of_type("Надпись") == {
        "ПослеСоздания": "AfterCreate", "AfterCreate": "AfterCreate"}


def test_an_unknown_type_has_no_handlers(data):
    assert modulehandlers.rows_of("ПридуманныйТип") == ()
    assert modulehandlers.of_type("ПридуманныйТип") == {}


def test_every_spelling_of_every_list(data):
    assert modulehandlers.all_names() == {
        "ПослеСоздания", "AfterCreate", "ПередЗакрытием", "BeforeClose",
        "ПолучитьДанныеЧата", "GetChatData", "ПередЗаписью", "BeforeWrite"}


def test_data_without_the_section_answers_nothing(tmp_path):
    """Data extracted before the section existed: every answer is empty, nothing is judged."""
    _root(tmp_path, {key: value for key, value in _STDLIB.items() if key != "module_handlers"})
    dataset.set_data_root(tmp_path)
    try:
        assert not modulehandlers.available()
        assert modulehandlers.of_type("Форма") == {}
        assert modulehandlers.platform_base("Форма", lambda _name: None) == ""
    finally:
        dataset.set_data_root(None)


def test_no_data_at_all_answers_nothing(tmp_path):
    dataset.set_data_root(tmp_path)
    try:
        assert not modulehandlers.available()
        assert modulehandlers.all_names() == frozenset()
    finally:
        dataset.set_data_root(None)


def test_the_chain_of_project_components_ends_at_the_platform_type(data):
    project = {"КарточкаСклада": "БазоваяКарточка", "БазоваяКарточка": "ФормаОбъекта"}
    assert modulehandlers.platform_base("КарточкаСклада", project.get) == "ФормаОбъекта"
    assert modulehandlers.platform_base("Форма", project.get) == "Форма"


@pytest.mark.parametrize("project", [
    {"Первая": "Вторая", "Вторая": "Первая"},  # a loop
    {"Первая": ""},  # a name the project has as something that is not a component
    {"Первая": "ВнешняяФорма"},  # the chain leaves both the project and the catalog
])
def test_a_chain_that_cannot_be_told_gives_no_base(data, project):
    assert modulehandlers.platform_base("Первая", project.get) == ""
