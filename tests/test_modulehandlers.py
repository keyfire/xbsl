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


def _root(tmp_path, stdlib: dict, terms: dict | None = None) -> None:
    version = tmp_path / "9.9.9"
    version.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": ["9.9.9"], "default": "9.9.9"}), encoding="utf-8")
    (version / "stdlib.json").write_text(json.dumps(stdlib, ensure_ascii=False), encoding="utf-8")
    (version / "terms.json").write_text(json.dumps(terms or _TERMS, ensure_ascii=False),
                                        encoding="utf-8")


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


def test_a_handler_gone_from_a_mode_is_there_below_that_mode_only(data):
    row = next(row for row in modulehandlers.rows_of("Форма") if row["en"] == "GetChatData")
    assert modulehandlers.declared_in(row, (7, 0))
    assert not modulehandlers.declared_in(row, (8, 0))  # `to` is the first mode it is gone from
    assert not modulehandlers.declared_in(row, (9, 0))
    assert modulehandlers.declared_in(row, None)  # an unknown mode keeps every row


@pytest.mark.parametrize("bounds, mode, declared", [
    ({}, (6, 0), True),
    ({"from": "8.0"}, (7, 0), False),
    ({"from": "8.0"}, (8, 0), True),  # `from` is the first mode the handler is there in
    ({"from": "8.0"}, (9, 0), True),
    ({"from": "7.0", "to": "9.0"}, (6, 0), False),
    ({"from": "7.0", "to": "9.0"}, (8, 0), True),
    ({"from": "7.0", "to": "9.0"}, (9, 0), False),
])
def test_the_modes_of_a_row_are_a_half_open_range(bounds, mode, declared):
    row = {"ru": "ПолучитьДанныеЧата", "en": "GetChatData", **bounds}
    assert modulehandlers.declared_in(row, mode) is declared


def test_a_row_carries_both_spellings_of_the_handler(data):
    rows = {row["ru"]: row["en"] for row in modulehandlers.rows_of("Форма")}
    assert rows["ПередЗакрытием"] == "BeforeClose"
    assert rows["ПослеСоздания"] == "AfterCreate"
    assert "ПередЗаписью" not in rows  # the object form's own handler is not a form's


def test_an_english_type_name_reads_the_same_lists(data):
    assert modulehandlers.rows_of("ObjectForm") == modulehandlers.rows_of("ФормаОбъекта")


def test_a_component_without_handlers_of_its_own_inherits_the_base_ones(data):
    assert modulehandlers.rows_of("Надпись") == ({"ru": "ПослеСоздания", "en": "AfterCreate"},)


def test_an_unknown_type_has_no_handlers(data):
    assert modulehandlers.rows_of("ПридуманныйТип") == ()


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
        assert modulehandlers.rows_of("Форма") == ()
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


# --- the modules of the other elements ----------------------------------------------------

_ELEMENTS = {
    "Справочник": {
        "": {"handlers": [{"ru": "ПолучитьЗначенияВыбора", "en": "GetChoiceValues"}],
             "dynamic": ["computeHandlerTerm"]},
        "Объект": {"handlers": [{"ru": "ПередЗаписью", "en": "BeforeWrite"},
                                {"ru": "ПриЗаполнении", "en": "OnFill"}]},
    },
    "ЗапланированноеЗадание": {"": {"handlers": [{"ru": "Обработчик", "en": "Handler"}]}},
}


@pytest.fixture
def elements(tmp_path):
    _root(tmp_path, {**_STDLIB, "element_module_handlers": _ELEMENTS})
    dataset.set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        dataset.set_data_root(None)


def test_an_element_module_answers_its_rows(elements):
    assert modulehandlers.element_available()
    rows = modulehandlers.element_slot("Справочник", "Объект")
    assert [row["en"] for row in rows] == ["BeforeWrite", "OnFill"]
    assert [row["ru"] for row in modulehandlers.element_slot("ЗапланированноеЗадание", "")] == [
        "Обработчик"]


def test_a_module_with_names_taken_at_build_time_is_not_answered(elements):
    """The own module of the catalog takes access handler names from its settings."""
    assert modulehandlers.element_slot("Справочник", "") is None


def test_a_module_the_data_does_not_list_is_not_answered(elements):
    assert modulehandlers.element_slot("Справочник", "НаборЗаписей") is None
    assert modulehandlers.element_slot("HttpСервис", "") is None


def test_the_module_words_and_the_names_of_the_element_lists(elements):
    assert modulehandlers.element_modules() == {"Объект"}
    assert modulehandlers.element_names() == {
        "ПолучитьЗначенияВыбора", "GetChoiceValues", "ПередЗаписью", "BeforeWrite",
        "ПриЗаполнении", "OnFill", "Обработчик", "Handler"}


def test_data_without_the_element_section_answers_nothing(data):
    assert not modulehandlers.element_available()
    assert modulehandlers.element_slot("Справочник", "Объект") is None


# --- what the element lists give the translator and the guard ------------------------------

#: A catalog whose own module takes the record-level security handlers at build time, and a
#: processing whose object module takes the names of its operations.
_ACCESS_ELEMENTS = {
    "Справочник": {
        "": {"handlers": [{"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"}],
             "dynamic": [modulehandlers.RECORD_SECURITY_SOURCE]},
        "Объект": {"handlers": [{"ru": "ПередЗаписью", "en": "BeforeWrite"}]},
    },
    "Обработка": {
        "Объект": {"handlers": [{"ru": "ПриЗаполнении", "en": "OnFill"}],
                   "dynamic": ["IProcessingOperationRtMetadata.getNameTerm"]},
    },
    "РегистрСведений": {
        "НаборЗаписей": {"handlers": [{"ru": "ПередЗаписью", "en": "BeforeWrite"}]},
    },
}
_FACET_TERMS = {**_TERMS, "facets": {
    "Справочник.Объект": "Catalog.Object",
    "РегистрСведений.НаборЗаписей": "InformationRegister.RecordSet",
}}
_RECORD_SECURITY_NAMES = {name for row in modulehandlers.RECORD_SECURITY
                          for name in (row["ru"], row["en"])}


@pytest.fixture
def access(tmp_path):
    _root(tmp_path, {**_STDLIB, "element_module_handlers": _ACCESS_ELEMENTS}, _FACET_TERMS)
    dataset.set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        dataset.set_data_root(None)


def test_the_rows_of_a_module_that_takes_the_record_security_handlers(access):
    """The slot is not judged, yet its names are the platform's: the static rows lead."""
    assert modulehandlers.element_slot("Справочник", "") is None
    rows = modulehandlers.element_rows("Справочник", "")
    assert [row["en"] for row in rows] == [
        "ComputeAccessPermissions", "ComputeAccessPermissionsForObjects",
        "ComputeAccessKeysForRead", "ComputeAccessKeysForUpdate"]


def test_the_rows_leave_out_what_a_description_names(access):
    """The operations of a processing are the project's words: only the fixed rows answer."""
    assert modulehandlers.element_slot("Обработка", "Объект") is None
    assert modulehandlers.element_rows("Обработка", "Объект") == (
        {"ru": "ПриЗаполнении", "en": "OnFill"},)


def test_the_rows_of_a_static_module_are_its_slot(access):
    assert modulehandlers.element_rows("Справочник", "Объект") == \
        modulehandlers.element_slot("Справочник", "Объект")


def test_a_module_the_data_does_not_list_has_no_rows(access):
    assert modulehandlers.element_rows("Справочник", "НаборЗаписей") == ()
    assert modulehandlers.element_rows("HttpСервис", "") == ()


def test_the_names_of_the_data_take_the_record_security_handlers_with_their_slot(access):
    names = modulehandlers.handler_names()
    assert _RECORD_SECURITY_NAMES <= names
    assert {"ПослеСоздания", "AfterCreate", "ПриЗаполнении", "OnFill"} <= names


def test_control_a_slot_of_another_source_does_not_bring_them(elements):
    """The negative control: the same shape, a dynamic source of another name."""
    assert modulehandlers.handler_names().isdisjoint(_RECORD_SECURITY_NAMES)
    assert modulehandlers.element_rows("Справочник", "") == (
        {"ru": "ПолучитьЗначенияВыбора", "en": "GetChoiceValues"},)


@pytest.mark.parametrize("stem, pair", [
    ("Склады/Склады.Объект", ("Склады/Склады", "Объект")),
    ("Stock/Stock.Object", ("Stock/Stock", "Объект")),
    ("Stock/Stock.RecordSet", ("Stock/Stock", "НаборЗаписей")),
    ("Склады/Склады", ("Склады/Склады", "")),  # the element's own module
    ("Склады.Черновик", ("Склады.Черновик", "")),  # a word the section does not name
    ("v1.Объект/Склады", ("v1.Объект/Склады", "")),  # a dot in a folder is not a module word
])
def test_a_module_file_names_its_element_and_its_module(access, stem, pair):
    assert modulehandlers.element_module(stem) == pair


def test_without_the_element_section_every_module_is_its_elements_own(data):
    assert modulehandlers.element_module("Склады/Склады.Объект") == ("Склады/Склады.Объект", "")
    assert modulehandlers.element_rows("Справочник", "Объект") == ()
    assert modulehandlers.handler_names() == modulehandlers.all_names()


# --- the access settings of an entity pick the handlers the build uses ---------------------

_PERMISSIONS = {"ru": "ВычислитьРазрешенияДоступа", "en": "ComputeAccessPermissions"}
_CHOICE = {"ru": "ПолучитьЗначенияВыбора", "en": "GetChoiceValues"}
_SECURITY = {"handlers": [_PERMISSIONS], "dynamic": [modulehandlers.RECORD_SECURITY_SOURCE]}
_SETTINGS_ELEMENTS = {
    "Справочник": {"": {"handlers": [_PERMISSIONS, _CHOICE],
                        "dynamic": [modulehandlers.RECORD_SECURITY_SOURCE]}},
    "РегистрСведений": {"": _SECURITY},
    "РегистрНакопления": {"": _SECURITY},
    "НаборКонстант": {"": _SECURITY},
    "ХранилищеНастроек": {"": _SECURITY},
    # A kind this module does not know the record-level security handlers of.
    "НовыйВид": {"": _SECURITY},
    "Проект": {"": {"handlers": [{"ru": "ВычислитьСистемныеРазрешенияДоступа",
                                  "en": "ComputeSystemAccessPermissions"}]}},
}
_OBJECTS, _READ, _UPDATE = modulehandlers.RECORD_SECURITY
_Settings = modulehandlers.AccessSettings


@pytest.fixture
def settings_data(tmp_path):
    _root(tmp_path, {**_STDLIB, "element_module_handlers": _SETTINGS_ELEMENTS})
    dataset.set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        dataset.set_data_root(None)


def _names(rows):
    return [row["ru"] for row in rows]


def test_without_computed_permissions_the_permissions_handler_is_left_off(settings_data):
    used, off = modulehandlers.access_slot("Справочник", "", _Settings())
    assert _names(used) == ["ПолучитьЗначенияВыбора"]
    assert _names(off) == ["ВычислитьРазрешенияДоступа", "ВычислитьРазрешенияДоступаДляОбъектов"]
    assert modulehandlers.unused_reason("Справочник", off[0], _Settings()) == "computed"
    assert modulehandlers.unused_reason("Справочник", off[1], _Settings()) == "per-object"


def test_computed_permissions_use_the_permissions_handler_alone(settings_data):
    used, off = modulehandlers.access_slot("Справочник", "", _Settings(computed=True))
    assert _names(used) == ["ВычислитьРазрешенияДоступа", "ПолучитьЗначенияВыбора"]
    assert _names(off) == ["ВычислитьРазрешенияДоступаДляОбъектов"]


def test_permissions_for_each_object_use_both(settings_data):
    used, off = modulehandlers.access_slot(
        "Справочник", "", _Settings(computed=True, per_object=True))
    assert _names(used) == ["ВычислитьРазрешенияДоступа", "ПолучитьЗначенияВыбора",
                            "ВычислитьРазрешенияДоступаДляОбъектов"]
    assert off == ()


def test_a_register_takes_its_keys_by_its_periodicity(settings_data):
    per_object = _Settings(computed=True, per_object=True)
    periodic = _Settings(computed=True, per_object=True, periodic=True)
    assert modulehandlers.access_slot("РегистрСведений", "", per_object)[0][1:] == (_OBJECTS,)
    assert modulehandlers.access_slot("РегистрСведений", "", periodic)[0][1:] == (_READ, _UPDATE)
    assert modulehandlers.access_slot("РегистрНакопления", "", per_object)[0][1:] == (
        _READ, _UPDATE)
    # A periodicity that cannot be told answers every handler the kind may declare.
    assert modulehandlers.record_security_rows("РегистрСведений", None) == (
        modulehandlers.RECORD_SECURITY)


def test_the_standard_permissions_and_a_constants_set_leave_the_handlers_off(settings_data):
    standard = _Settings(computed=True, per_object=True, standard=True)
    used, off = modulehandlers.access_slot("ХранилищеНастроек", "", standard)
    assert used == () and _names(off) == ["ВычислитьРазрешенияДоступа",
                                          "ВычислитьРазрешенияДоступаДляОбъектов"]
    assert modulehandlers.unused_reason("ХранилищеНастроек", off[1], standard) == "standard"
    used, off = modulehandlers.access_slot("НаборКонстант", "", _Settings(True, True))
    assert used == (_PERMISSIONS,) and off == (_READ, _UPDATE)
    assert modulehandlers.unused_reason("НаборКонстант", _READ, _Settings(True, True)) == "never"


def test_unreadable_settings_use_every_handler_of_the_kind(settings_data):
    used, off = modulehandlers.access_slot("Справочник", "", None)
    assert _names(used) == ["ВычислитьРазрешенияДоступа", "ПолучитьЗначенияВыбора",
                            "ВычислитьРазрешенияДоступаДляОбъектов"]
    assert off == ()


def test_control_other_modules_are_not_split_by_the_settings(settings_data):
    """The negative control: a kind not known here, a static slot and no slot answer None."""
    assert modulehandlers.access_slot("НовыйВид", "", _Settings()) is None
    assert modulehandlers.access_slot("Проект", "", _Settings()) is None
    assert modulehandlers.access_slot("Справочник", "Объект", _Settings()) is None


def test_the_module_of_the_project_answers_its_handlers(settings_data):
    assert _names(modulehandlers.project_rows()) == ["ВычислитьСистемныеРазрешенияДоступа"]
    assert "ComputeSystemAccessPermissions" in modulehandlers.handler_names()


def test_control_without_the_project_slot_the_project_has_no_handlers(elements):
    assert modulehandlers.project_rows() == ()
