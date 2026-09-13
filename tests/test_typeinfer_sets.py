"""Checks of the type sets of xbsl/typeinfer.py: written types, the verdict on a cast, the catalog.

The written-type parser and the verdict are pure functions and run in every checkout; the
catalog reads the platform catalog (member results, bases, type parameters), and those tests
carry `needs_data`.
"""

import pytest

from xbsl import typeinfer as ti

_SPELLINGS = {"String": "Строка", "Number": "Число", "Array": "Массив", "Map": "Соответствие"}


def _resolve(name: str) -> str:
    return _SPELLINGS.get(name, name)


def _set(text: str) -> ti.TypeSet:
    got = ti.parse_type(text, _resolve)
    assert got is not None, text
    return got


def _equal(source: str, target: str) -> bool:
    return source == target


# --- written types ---------------------------------------------------------------------------


def test_a_nullable_type_is_the_type_plus_the_empty_value():
    got = _set("Строка?")
    assert got.names == frozenset({"Строка"}) and got.undefined and not got.single
    assert got.text() == "Строка?"


def test_a_union_is_a_set_and_its_order_does_not_matter():
    assert _set("Строка|Число") == _set("Число|Строка")
    assert _set("Строка|Неопределено") == _set("Строка?")
    assert _set("Строка|Число|?").text() == "Строка|Число|?"


def test_generic_arguments_are_part_of_the_name_and_canonical():
    assert _set("Map<String, Array<Number>>?") == _set("Соответствие<Строка,Массив<Число>>?")
    assert ti.split_nominal("Соответствие<Строка,Массив<Число>>") == (
        "Соответствие", ("Строка", "Массив<Число>"))


def test_one_unresolved_name_makes_the_whole_type_unknown():
    resolve = {"Строка": "Строка"}.get
    assert ti.parse_type("Строка|НетТакого", resolve) is None
    assert ti.parse_type("Массив<", _resolve) is None
    assert ti.parse_type("", _resolve) is None


# --- the verdict of the compiler ---------------------------------------------------------------


@pytest.mark.parametrize("source, target, verdict", [
    ("Строка", "Строка", "redundant"),
    ("Строка?", "Строка?", "redundant"),
    ("Строка", "Строка?", "redundant"),
    ("Строка?", "Строка", "insistent"),
    ("Строка|Число|?", "Строка|Число", "insistent"),
    ("Строка|Число", "Строка|Число|Булево", "redundant"),
    ("Строка|Число", "Строка", None),
    ("Строка", "Число", None),
])
def test_the_verdict_follows_the_compiler(source, target, verdict):
    assert ti.cast_verdict(_set(source), _set(target), _equal) == verdict


def test_the_empty_value_alone_is_left_to_the_compiler():
    # `Неопределено как Строка?` is an error of the common inheritor, not either warning
    assert ti.cast_verdict(ti.TypeSet(undefined=True), _set("Строка?"), _equal) is None


def test_null_blocks_both_verdicts():
    # a query column read through a reference holds Null, and no written type holds it
    column = ti.TypeSet(frozenset({"Строка"}), null=True)
    assert ti.cast_verdict(column, _set("Строка"), _equal) is None
    assert ti.cast_verdict(column, _set("Строка?"), _equal) is None


def test_an_unproven_relation_is_no_verdict():
    never = lambda source, target: False  # noqa: E731 - the relation the caller could not prove
    assert ti.cast_verdict(_set("Строка"), _set("Объект"), never) is None
    # the exact case does not need the relation at all
    assert ti.cast_verdict(_set("Строка?"), _set("Строка"), never) == "insistent"


# --- the catalog ---------------------------------------------------------------------------------


def _catalog() -> ti.ProjectCatalog:
    return ti.ProjectCatalog(
        elements={
            "Склады": {"kind": "Справочник", "attributes": {"Наименование": None,
                                                             "Вместимость": "Число",
                                                             "Родитель": "Склады.Ссылка?"},
                       "contracts": ["МестаХранения.Объект"]},
            "Партии": {"kind": "Справочник", "attributes": {}},
            "МестаХранения": {"kind": "КонтрактСущности", "properties": {"Наименование": "Строка"}},
            "ВидПартии": {"kind": "Перечисление", "values": ["Штучная", "Весовая"]},
        },
        modules={
            "Остатки": {"methods": {"Найти": ["Склады.Ссылка?"], "Двойной": ["Строка", "Число"]},
                        "structures": {"Строка": {"fields": {"Склад": "Склады.Ссылка"}}},
                        "enums": {}, "fields": {}},
        },
    )


@pytest.mark.needs_data  # the platform names come from the type catalog
def test_a_module_structure_is_named_by_its_module():
    catalog = _catalog()
    assert catalog.written("Строка", "Остатки") == ti.TypeSet.of("Остатки.Строка")
    assert catalog.written("Строка", None) == ti.TypeSet.of("Строка")
    assert catalog.written("Склады.Reference", None) == ti.TypeSet.of("Склады.Ссылка")


@pytest.mark.needs_data
def test_members_of_a_project_object_come_from_its_yaml_and_its_kind():
    catalog = _catalog()
    assert catalog.member("Склады.Объект", "Вместимость", False) == ti.TypeSet.of("Число")
    assert catalog.member("Склады.Объект", "Наименование", False) == ti.TypeSet.of("Строка")
    assert catalog.member("Склады.Объект", "Родитель", False) == _set("Склады.Ссылка?")
    # the kind answers what the yaml does not declare, with the element's name put in
    assert catalog.member("Склады.Ссылка", "ЗагрузитьОбъект", True) == _set("Склады.Объект?")


@pytest.mark.needs_data
def test_a_generic_member_is_typed_by_the_arguments():
    catalog = _catalog()
    assert catalog.member("Соответствие<Строка,Число>", "ПолучитьИлиНеопределено", True) \
        == _set("Число?")
    assert catalog.member("Массив<Склады.Ссылка>", "Первый", True) == ti.TypeSet.of("Склады.Ссылка")
    # a query result is iterated by the base's element parameter
    result = ti.TypeSet.of("РезультатЗапроса<Строка>")
    assert catalog.element_of(result) == ti.TypeSet.of("Строка")
    # a map's element is a key-and-value pair the data does not state: no answer
    assert catalog.element_of(ti.TypeSet.of("Соответствие<Строка,Число>")) is None


@pytest.mark.needs_data
def test_static_members_of_the_project():
    catalog = _catalog()
    assert catalog.static_member("ВидПартии", "Штучная", False, None) == ti.TypeSet.of("ВидПартии")
    assert catalog.static_member("Остатки", "Найти", True, None) == _set("Склады.Ссылка?")
    # overloads that disagree about the result name nothing
    assert catalog.static_member("Остатки", "Двойной", True, None) is None
    assert catalog.static_member("Склады", "НайтиПоКоду", True, None) == _set("Склады.Ссылка?")


@pytest.mark.needs_data
def test_assignability_knows_the_root_the_bases_and_the_contracts():
    catalog = _catalog()
    assert catalog.assignable("Строка", "Объект")
    assert catalog.assignable("Массив<Строка>", "ЧитаемыйМассив<Строка>")
    assert not catalog.assignable("Массив<Строка>", "ЧитаемыйМассив<Число>")
    assert catalog.assignable("Склады.Ссылка", "МестаХранения.Ссылка")
    assert catalog.assignable("Склады.Объект", "МестаХранения.Объект")
    assert not catalog.assignable("Партии.Ссылка", "МестаХранения.Ссылка")
    assert not catalog.assignable("Склады.Ссылка", "Партии.Ссылка")
