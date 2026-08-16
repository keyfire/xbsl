"""Checks of the yaml/unknown-attribute-property rule (a key an attribute's class rejects)."""

from xbsl import engine

_RULE = "yaml/unknown-attribute-property"


def _lint(text: str, name: str = "Задачи.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={_RULE})


_HEAD = (
    "ВидЭлемента: Справочник\n"
    "Ид: 42073842-db14-41d6-a17a-7b03a5d57933\n"
    "Имя: Задачи\n"
)


def test_length_on_a_regular_attribute_is_an_error():
    d = _lint(
        _HEAD + "Реквизиты:\n"
        "    -\n        Имя: Сумма\n        Тип: Число\n        Длина: 12\n"
    )
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].severity.value == "error"
    assert (d[0].line, d[0].col) == (8, 9)
    # the suggestion names the properties that DO exist on a number attribute
    assert "ДлинаЦелойЧасти" in d[0].message and "Сумма" in d[0].message


def test_length_on_the_built_in_name_is_silent():
    # the standard Наименование has a class of its own, and it does declare Длина
    d = _lint(
        _HEAD + "Реквизиты:\n"
        "    -\n        Имя: Наименование\n        Длина: 250\n"
    )
    assert d == []


def test_id_on_a_built_in_attribute_is_reported():
    """The compiler rejects an `Ид` on the built-in Наименование is rejected.

    `Пробники.yaml [12:9]: Неизвестное свойство "Id"` - so `Ид` is judged by the class like any
    other property (a regular attribute declares it, a dispatched built-in does not), while
    `Имя` stays allowed everywhere (the compiler accepts it on the built-in).
    """
    d = _lint(
        _HEAD + "Реквизиты:\n"
        "    -\n        Ид: 54c9050e-3377-4a67-8c34-c80d1074edfc\n"
        "        Имя: Наименование\n        Длина: 250\n"
    )
    assert len(d) == 1 and d[0].line == 6 and "'Ид'" in d[0].message


def test_attribute_of_a_tabular_section_is_judged():
    d = _lint(
        _HEAD + "ТабличныеЧасти:\n"
        "    -\n        Имя: Строки\n        Реквизиты:\n"
        "            -\n                Имя: Комментарий\n                Тип: Строка\n"
        "                Длина: 50\n"
    )
    assert len(d) == 1 and d[0].line == 11


def test_known_properties_are_silent():
    d = _lint(
        _HEAD + "Реквизиты:\n"
        "    -\n        Ид: 54c9050e-3377-4a67-8c34-c80d1074edfc\n"
        "        Имя: Сумма\n        Тип: Число\n"
        "        ДлинаЦелойЧасти: 12\n        ДлинаДробнойЧасти: 2\n"
        "        МаксимальноеЗначение: 1000\n"
    )
    assert d == []


def test_typo_is_reported_with_the_close_property():
    d = _lint(
        _HEAD + "Реквизиты:\n"
        "    -\n        Имя: Описание\n        Тип: Строка\n"
        "        Многострочнная: Истина\n"
    )
    assert len(d) == 1 and "Многострочная" in d[0].message


def test_an_english_source_is_judged_exactly_as_its_russian_twin():
    """The dictionary used to lack the English spelling of the names the built-in code
    attribute declares, and such a key went unreported in an English source - a miss the test
    recorded as the behaviour of the day. The term extractor reads mixed spellings now, the
    pair is there, and both languages answer the same: the key of another class and the
    unknown key alike.
    """
    text = (
        "ElementKind: Catalog\n"
        "Id: 42073842-db14-41d6-a17a-7b03a5d57933\n"
        "Name: Tasks\n"
        "Attributes:\n"
        "    -\n        Name: Amount\n        Type: Number\n"
        "        Length: 12\n        Nonsense: 1\n"
    )
    d = _lint(text, name="Tasks.yaml")
    assert [x.line for x in d] == [8, 9]  # exactly what the Russian twin answers
    assert "Length" in d[0].message and "Nonsense" in d[1].message


def test_english_built_in_name_dispatches_through_the_dictionary():
    # `Name` is the English of `Наименование` in the platform dictionary, so the item resolves
    # to the built-in class and its own properties are accepted
    from xbsl import metamodel

    catalog = metamodel.class_for_kind("Справочник")
    assert metamodel.collection_item_class(catalog, "Реквизиты", "Name") == "CatalogNameAttribute"
    assert (metamodel.collection_item_class(catalog, "Реквизиты", "Наименование")
            == "CatalogNameAttribute")
