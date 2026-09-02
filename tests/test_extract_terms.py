"""Query keyword pairs out of the parser's constant pool (xbsl/extract/terms.py).

The windows below are real: they were read out of the QueryTerms class of a distribution,
and each one is a shape the pool actually holds. Taken by adjacency alone, the constant of
one entry became the "English" of the next, and the generated dictionary claimed that `ОТ`
answers `OTLICHAYETSYA` and `ДЛЯ` answers `CREATE_INDEX` - two words the translating side
then skipped by hand.

No Element data is needed here: the function is pure, the pool is the fixture.
"""

from xbsl.extract.terms import _query_pairs


def test_a_plain_pair_is_read():
    assert _query_pairs(["FROM", "ИЗ", "WHERE", "ГДЕ"]) == {"ИЗ": "FROM", "ГДЕ": "WHERE"}


def test_the_enum_constant_of_a_pair_is_not_the_next_english():
    """`CREATE INDEX`, `СОЗДАТЬ ИНДЕКС`, `CREATE_INDEX` - the third is the constant of the
    pair, and the word after it is a keyword of its own."""
    pairs = _query_pairs([
        "CREATE INDEX", "СОЗДАТЬ ИНДЕКС", "CREATE_INDEX", "ДЛЯ", "DLYA",
        "CREATE TEMPORARY TABLE", "СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ",
    ])

    assert pairs["СОЗДАТЬ ИНДЕКС"] == "CREATE INDEX"
    assert pairs["СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ"] == "CREATE TEMPORARY TABLE"
    assert "ДЛЯ" not in pairs


def test_a_keyword_without_an_english_spelling_is_left_out():
    """What follows such a keyword is a transliteration - its constant name, not a translation."""
    pairs = _query_pairs([
        "GROUP", "ГРУППИРОВАТЬ", "HAVING", "ИМЕЮЩИЕ",
        "ОТЛИЧАЕТСЯ", "OTLICHAYETSYA", "ОТ", "OT",
        "INSERT", "ВСТАВИТЬ",
    ])

    assert pairs == {
        "ГРУППИРОВАТЬ": "GROUP", "ИМЕЮЩИЕ": "HAVING", "ВСТАВИТЬ": "INSERT",
    }


def test_an_empty_pool_answers_with_nothing():
    assert _query_pairs([]) == {}
    assert _query_pairs(["SELECT"]) == {}


# --- members stated as terms belong to the type the class is named after --------------------


def test_a_class_named_after_a_type_states_that_type_and_its_members():
    """A Constants class stores the type's own term and one term per member; the members are
    the TYPE's, not the class's - filed under the class name they answered no receiver."""
    from test_extract_classcode import NAMESPACE, TERM, _class_of_terms

    from xbsl.extract.terms import _declared_type

    blob = _class_of_terms([
        ("NS_TERM", NAMESPACE, ["Std::Interface::Favorites", "Стд::Интерфейс::Избранное"]),
        ("USER_FAVORITES_ITEM_TERM", TERM, ["UserFavoritesItem", "ЭлементИзбранногоПользователя"]),
        ("LINK_PROPERTY_TERM", TERM, ["Link", "Ссылка"]),
        ("PIN_METHOD_TERM", TERM, ["Pin", "Закрепить"]),
        ("NAME_PARAM_TERM", TERM, ["Name", "Имя"]),
    ])

    assert _declared_type("UserFavoritesItemConstants", blob) == (
        "UserFavoritesItem", "ЭлементИзбранногоПользователя",
        {"Ссылка": "Link", "Закрепить": "Pin"},
    )
    # The type class states the type alone - the same pair, no members.
    assert _declared_type("UserFavoritesItemG5Type", _class_of_terms([
        ("TYPE_TERM", TERM, ["UserFavoritesItem", "ЭлементИзбранногоПользователя"]),
    ])) == ("UserFavoritesItem", "ЭлементИзбранногоПользователя", {})


def test_a_class_that_states_no_type_of_its_own_name_declares_nothing():
    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _declared_type

    blob = _class_of_terms([("LINK_PROPERTY_TERM", TERM, ["Link", "Ссылка"])])
    assert _declared_type("RegistryConstants", blob) is None
    assert _declared_type("RegistryConstants", b"\xca\xfe\xba\xbe") is None


def test_a_term_is_not_a_type_because_a_class_is_named_after_it():
    """The kind a Constants class serves, the yaml key a generator spells, the query keyword a
    terms class lists - each is a pair the class is named after, and none is a type."""
    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _declared_type

    kind = _class_of_terms([("PROJECT_ELEMENT_KIND_TERM", TERM, ["CommonModule", "ОбщийМодуль"])])
    assert _declared_type("CommonModuleConstants", kind) is None
    key = _class_of_terms([("NAME_TERM", TERM, ["Name", "Имя"])])
    assert _declared_type("NameGenerator", key) is None
    keyword = _class_of_terms([("VALUE", TERM, ["Value", "Значение"])])
    assert _declared_type("ValueTerms", keyword) is None
    # The type class of a collection stores its term under TYPE_NAME - that one is the type.
    typed = _class_of_terms([("TYPE_NAME", TERM, ["MutableMap", "ИзменяемоеСоответствие"])])
    assert _declared_type("MutableMapG5Type", typed) == ("MutableMap", "ИзменяемоеСоответствие", {})


def test_the_scan_files_declared_members_under_the_type_and_reports_the_type_pair():
    import io
    import zipfile

    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _scan_meta_objects

    blob = _class_of_terms([
        ("USER_FAVORITES_ITEM_TERM", TERM, ["UserFavoritesItem", "ЭлементИзбранногоПользователя"]),
        ("LINK_PROPERTY_TERM", TERM, ["Link", "Ссылка"]),
    ])
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("demo/favorites/UserFavoritesItemConstants.class", blob)
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())

    members, _common, types = _scan_meta_objects(zipfile.ZipFile(car))

    assert members["UserFavoritesItem"] == {"Ссылка": "Link"}
    # The neighbourhood reading of the class stays under the class name, as it always did.
    assert members["UserFavoritesItemConstants"]["Ссылка"] == "Link"
    assert types == {"ЭлементИзбранногоПользователя": "UserFavoritesItem"}
