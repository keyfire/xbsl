"""Checks of the type sets of xbsl/typeinfer.py: written types, the verdicts, the catalog.

The written-type parser, the verdicts and the signature reader are pure functions and run in
every checkout; the catalog reads the platform catalog (member results, bases, type parameters),
and those tests carry `needs_data`. The rules that read the typing are tested over small
projects in test_rule_type_casts.py and test_redundant_checks.py.
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


def test_a_check_always_holds_only_when_every_type_of_the_value_passes():
    assert ti.always_holds(_set("Строка"), _set("Строка"), _equal)
    assert ti.always_holds(_set("Строка?"), _set("Строка?"), _equal)
    assert ti.always_holds(_set("Строка"), _set("Строка|Число"), _equal)
    # the empty value fails a check that does not name it, and so does a part of a union
    assert not ti.always_holds(_set("Строка?"), _set("Строка"), _equal)
    assert not ti.always_holds(_set("Строка|Число"), _set("Строка"), _equal)
    # Null, which no written type holds, and the empty value alone are never decided
    assert not ti.always_holds(ti.TypeSet(frozenset({"Строка"}), null=True), _set("Строка"), _equal)
    assert not ti.always_holds(ti.TypeSet(undefined=True), _set("Строка?"), _equal)


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


# --- the members of the platform catalog and the file reach ---------------------------------------


def test_the_signature_reader_counts_optional_and_variadic_parameters():
    fewest, most, result, generic = ti._signature('Найти(Строка: Строка, От: Число = 0): Число?')
    assert (fewest, most, result, generic) == (1, 2, "Число?", False)
    assert ti._signature("Шаблон(Шаблон: Строка, ...Аргументы: Объект?): Строка")[:2] == (1, 10_000)
    assert ti._signature("Очистить()")[2] is None


def test_a_default_with_a_comma_inside_quotes_is_one_parameter():
    shape = ti._signature('Соединить(Разделитель: Строка = ", ", Хвост: Булево = Ложь): Строка')
    assert shape[:2] == (0, 2)


def test_a_generic_method_is_marked_generic():
    shape = ti._signature("ПервыйИлиУмолчание<ТипУмолчания>(Умолчание: ТипЭлемента|ТипУмолчания): "
                          "ТипЭлемента|ТипУмолчания")
    assert shape[3] is True


def _file_catalog() -> ti.ProjectCatalog:
    """The catalog of the file reach: nothing of the project, a name it cannot resolve kept."""
    return ti.ProjectCatalog(open_world=True)


@pytest.mark.needs_data
def test_written_types_read_as_sets_in_either_language():
    catalog = _file_catalog()
    assert catalog.written("Строка|Число|?", None) == ti.TypeSet(frozenset({"Строка", "Число"}), True)
    assert catalog.written("Строка|Число?", None) == ti.TypeSet(frozenset({"Строка", "Число"}), True)
    assert catalog.written("String?", None) == catalog.written("Строка?", None)
    assert catalog.written("Массив<Строка?>", None) == ti.TypeSet.of("Массив<Строка?>")


@pytest.mark.needs_data
def test_a_type_the_reader_cannot_compare_answers_nothing():
    catalog = _file_catalog()
    assert catalog.written("неизвестно", None) is None
    assert catalog.written("()->ничто", None) is None


@pytest.mark.needs_data
def test_a_name_the_file_cannot_resolve_is_kept_and_the_project_names_nothing_by_it():
    """The file reach judges only the empty value of a type, so an element of the project it does
    not see keeps its written name; the project reach resolves names, and one it lacks is no type."""
    assert _file_catalog().written("Основное::Задачи.Ссылка", None) == ti.TypeSet.of("Задачи.Ссылка")
    assert ti.ProjectCatalog().written("Основное::Задачи.Ссылка", None) is None


@pytest.mark.needs_data
def test_a_member_of_a_generic_type_is_typed_by_the_argument():
    catalog = _file_catalog()
    assert catalog.platform_member("СобытиеПриИзменении<Строка>", "НовоеЗначение", False) \
        == ti.TypeSet.of("Строка")
    got = catalog.platform_member("СобытиеПриИзменении<Строка?>", "НовоеЗначение", False)
    assert got == ti.TypeSet(frozenset({"Строка"}), True)
    # A raw receiver binds nothing, and no member of it is typed.
    assert catalog.platform_member("СобытиеПриИзменении", "НовоеЗначение", False) is None


@pytest.mark.needs_data
def test_overloads_that_disagree_about_the_result_give_no_type():
    """The zero-argument overload of the documentation yields the empty value, the others do not."""
    catalog = _file_catalog()
    assert catalog.platform_member("Массив<Строка>", "ПервыйИлиУмолчание", True, 0) \
        == ti.TypeSet(frozenset({"Строка"}), True)
    assert catalog.platform_member("Массив<Строка>", "ПервыйИлиУмолчание", True, 1) is None


_VERSIONED_BLOCK = (
    '<h3 id="таблица">Таблица</h3> <p><code>Версия 8.0 и выше</code></p>'
    " <pre><code>Таблица: ОтражениеТаблицы?</code></pre> <hr>\n"
    '<h3 id="таблица-1"><del>Таблица</del></h3> <p><code>Версия 7.0 и ниже</code></p>'
    " <pre><code>Таблица: ОтражениеТаблицы</code></pre> <hr>"
)


def test_a_property_the_page_prints_nullable_in_its_current_form_is_not_trusted(monkeypatch):
    """The catalog folded both versions into the bare head; the current form admits the empty value."""
    from xbsl import docs

    ti._documented_types.cache_clear()
    monkeypatch.setattr(docs, "available", lambda version=None: True)
    monkeypatch.setattr(docs, "member_doc", lambda name, version=None: {"block": _VERSIONED_BLOCK})
    try:
        assert ti._documented_types("Отражение", "Таблица") == ("ОтражениеТаблицы?",)
        assert ti._documented_alike("Отражение", "Таблица") is False
    finally:
        ti._documented_types.cache_clear()


def test_a_property_documented_plain_in_every_form_is_trusted(monkeypatch):
    from xbsl import docs

    ti._documented_types.cache_clear()
    block = '<h3 id="имя">Имя</h3> <pre><code>Имя: Строка</code></pre> <hr>'
    monkeypatch.setattr(docs, "available", lambda version=None: True)
    monkeypatch.setattr(docs, "member_doc", lambda name, version=None: {"block": block})
    try:
        assert ti._documented_alike("Задачи", "Имя") is True
    finally:
        ti._documented_types.cache_clear()


@pytest.mark.needs_data
def test_a_property_folded_from_two_versions_is_left_untyped():
    """The page prints the main table of a reflection nullable for the current platform and plain for
    an old one; the catalog kept the plain head, the documentation check keeps the member untyped."""
    from xbsl import docs

    if not docs.available():
        pytest.skip("the documentation database is not installed")
    assert _file_catalog().platform_member("ОтражениеЭлементаПроектаСТаблицами", "ОсновнаяТаблица",
                                           False) is None


@pytest.mark.needs_data
def test_a_disputed_property_is_left_untyped_while_the_data_still_calls_it_plain():
    """The entry is evidence from the editor; once the data admits the empty value it is redundant."""
    from xbsl import dataset

    catalog = _file_catalog()
    for owner, member in ti._DISPUTED_PROPERTIES:
        written = (dataset.load_json("stdlib.json")["member_types"].get(owner) or {}).get(member)
        got = catalog.written(written, None)
        assert got is not None and not got.undefined, f"{owner}.{member} is no longer plain - drop it"
        assert catalog.platform_member(owner, member, False) is None
