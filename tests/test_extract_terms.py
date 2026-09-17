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


def test_a_term_a_class_states_reaches_the_common_table_past_the_adjacency_filter():
    """`Code` names a class-file attribute and is never an English candidate of the
    neighbourhood reading, so the built-in code attribute had no common spelling at all -
    although a dozen classes state the term `Code`. A stated term is the platform's own
    word and answers where the neighbourhood settled nothing; a class named after no type
    files no type and no member by it."""
    import io
    import zipfile

    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _scan_meta_objects

    blob = _class_of_terms([("CODE_ATTR_NAME", TERM, ["Code", "Код"])])
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("demo/metadata/CodeAttributeMetadata.class", blob)
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())

    members, common, types = _scan_meta_objects(zipfile.ZipFile(car))

    assert common == {"Код": "Code"}
    assert types == {}
    assert "CodeAttributeMetadata" not in members


def test_a_stated_term_does_not_unsettle_a_word_the_neighbourhood_knows():
    """A class states its OWN vocabulary: mixed into the flat count, the statements of a dozen
    classes broke the dominance of fifteen settled words on a real distribution. So a stated
    term answers only where the neighbourhood settled nothing - here the word for rows is read
    by adjacency as `Rows` in two classes against one `Lines`, which settles nothing either
    way, and the statements of the same classes add no third opinion."""
    import io
    import zipfile

    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _scan_meta_objects

    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        for index in range(2):
            z.writestr(f"demo/rows/Table{index}.class",
                       _class_of_terms([("ROWS_PROPERTY_TERM", TERM, ["Rows", "Строки"])]))
        z.writestr("demo/text/Editor.class",
                   _class_of_terms([("LINES_PROPERTY_TERM", TERM, ["Lines", "Строки"])]))
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())

    _members, common, _types = _scan_meta_objects(zipfile.ZipFile(car))

    assert "Строки" not in common  # two against one is not dominance, as it never was


def test_the_common_table_comes_back_sorted_by_the_russian_key():
    """A pair is filed as its class is read, so an unsorted table put a word wherever its
    class happens to sit in the distribution - a re-extraction that changed no spelling still
    moved hundreds of unrelated lines in terms_full.json. Sorting by the Russian key means the
    file changes only where a word actually did."""
    import io
    import zipfile

    from test_extract_classcode import TERM, _class_of_terms

    from xbsl.extract.terms import _scan_meta_objects

    # Filed in the reverse of alphabetical order - a passthrough of scan order would fail this.
    pairs = [("BOX_TERM", ["Box", "Ящик"]), ("TITLE_TERM", ["Title", "Название"]),
             ("ADDRESS_TERM", ["Address", "Адрес"])]
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        for index, (field, pair) in enumerate(pairs):
            z.writestr(f"demo/scan/Class{index}.class", _class_of_terms([(field, TERM, pair)]))
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())

    _members, common, _types = _scan_meta_objects(zipfile.ZipFile(car))

    assert common == {"Ящик": "Box", "Название": "Title", "Адрес": "Address"}
    assert list(common.keys()) == sorted(common.keys())


# --- the kind table: the fullest copy of the serializer enum, not the first ---------------


def _kind_enum_blob(pairs: list[tuple[str, str]]) -> bytes:
    """A class whose constant pool holds English/Russian kind pairs in order."""
    import struct

    strings: list[str] = []
    for en, ru in pairs:
        strings.extend((en, ru))
    out = bytearray(b"\xca\xfe\xba\xbe" + b"\x00" * 4)
    out += struct.pack(">H", len(strings) + 1)
    for text in strings:
        data = text.encode("utf-8")
        out += b"\x01" + struct.pack(">H", len(data)) + data
    return bytes(out)


def _car_with_kind_tables(copies: list[tuple[str, list[tuple[str, str]]]]):
    """A .car whose named jars each hold one copy of the kind enum."""
    import io
    import zipfile

    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        for jar_name, pairs in copies:
            jar = io.BytesIO()
            with zipfile.ZipFile(jar, "w") as jz:
                jz.writestr(
                    "com/e1c/g5rt/demo/ProjectElementKindCmptEnum.class",
                    _kind_enum_blob(pairs),
                )
            z.writestr(jar_name, jar.getvalue())
    return zipfile.ZipFile(car)


_HTTP_SOAP = [("HttpService", "HttpСервис"), ("SoapService", "SoapСервис")]
_FULL_KINDS = _HTTP_SOAP + [
    ("Catalog", "Справочник"),
    ("CommonModule", "ОбщийМодуль"),
    ("InterfaceComponent", "КомпонентИнтерфейса"),
]


def test_the_fullest_kind_table_wins_over_an_earlier_short_copy():
    """A server-with-IDE archive can list a two-kind copy first; taking that one
    dropped Catalog, CommonModule and InterfaceComponent from the metamodel.

    Seen at least on 9.2.9+12 and 9.3.1+4. The scan does not read the version out of
    the jar names, so a later build is handled the same way.
    """
    from xbsl.extract.terms import scan_kind_table

    table = scan_kind_table(_car_with_kind_tables([
        ("data/lib/chassis/modules/com.e1c.g5rt.appengine.core.reflection.common-9.2.9-1-proguard.jar",
         _HTTP_SOAP),
        ("data/ide/theia/plugins/@1c-appengine-plugin/bin/appengine-lsp/repo/"
         "com.e1c.g5rt.lsp.server.appengine-9.3.1-1.jar", _FULL_KINDS),
    ]))

    assert table == {
        "HttpСервис": "HttpService",
        "SoapСервис": "SoapService",
        "Справочник": "Catalog",
        "ОбщийМодуль": "CommonModule",
        "КомпонентИнтерфейса": "InterfaceComponent",
    }


def test_a_later_short_kind_table_does_not_replace_a_full_one():
    from xbsl.extract.terms import scan_kind_table

    table = scan_kind_table(_car_with_kind_tables([
        ("data/lib/com.e1c.g5rt.full-1.0.jar", _FULL_KINDS),
        ("data/lib/com.e1c.g5rt.tiny-1.0.jar", _HTTP_SOAP),
    ]))

    assert "Справочник" in table and len(table) == len(_FULL_KINDS)


def test_a_single_full_kind_table_is_kept():
    """A build that ships only the complete copy is not a special case of the scan."""
    from xbsl.extract.terms import scan_kind_table

    table = scan_kind_table(_car_with_kind_tables([
        ("data/lib/com.e1c.g5rt.lsp.server.appengine-8.0.0-1.jar", _FULL_KINDS),
    ]))
    assert table["КомпонентИнтерфейса"] == "InterfaceComponent"
    assert len(table) == len(_FULL_KINDS)


def test_no_kind_enum_copy_answers_with_nothing():
    import io
    import zipfile

    from xbsl.extract.terms import scan_kind_table

    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("readme.txt", "no jars")
    assert scan_kind_table(zipfile.ZipFile(car)) == {}


# --- the members table that spells the manager of an element kind ------------------------------

_MANAGER_CLASS = "demo/acme/AcmeRightManagerCtMetaObject"
_PROJECT_TYPE_INIT = "(Ldemo/acme/AcmeRightG5ProjectType;)V"
_TEMPLATE_PAGE = ("data/docs/help/ru/stdlib/element/xbsl/DeveloperName/ProjectName/SubsystemName/"
                  "AcmeRightName_ru/index.html")
_LSP_JAR = ("data/ide/theia/plugins/@1c-appengine-plugin/bin/appengine-lsp/repo/"
            "com.e1c.g5rt.lsp.server.appengine-1.0.jar")
_LSP_PAGE = "docs/element/xbsl/ru/DeveloperName_ProjectName_SubsystemName_AcmeRightName.md"


def _template_html(methods: list[str]) -> str:
    own = "".join(f"<h3>{name}</h3><p>Доступность: Сервер</p>" for name in methods)
    return (
        "<html><head><title>{ИмяПраваАкме} | 1С:Предприятие.Элемент</title></head><body>"
        f"<article><h2>Методы</h2>{own}"
        "<h2>Список унаследованных методов</h2><h3>Объект</h3><a href=\"#\">ВСтроку</a>"
        "</article></body></html>"
    )


def _template_markdown(methods: list[str], template: str = "AcmeRightName") -> str:
    rows = [f"# DeveloperName::ProjectName::SubsystemName::{template}#{name}()\n\n"
            "**Определен:** **ИмяПраваАкме**\n" for name in methods]
    rows.append(f"# DeveloperName::ProjectName::SubsystemName::{template}#ToString()\n\n"
                "**Определен:** **Объект**\n")
    return "Содержит методы права.\n\n" + "\n".join(rows)


def _manager_car(*, constructed_from: str | None = _PROJECT_TYPE_INIT,
                 russian: tuple[str, ...] = ("ЕстьПраво", "Проверить"),
                 english: tuple[str, ...] = ("Check", "HasRight"),
                 twin: bool = False, foreign_pair: bool = False,
                 view_from_project_type: bool = False,
                 second_kind: bool = False, namesake: bool = False):
    """A distribution with one element kind, its template pages and the compiler classes.

    `second_kind` adds a kind whose template documents exactly the same members, so one class
    fits both. `namesake` moves the terms into a class of the SAME simple name in another
    package, leaving the constructed one stating nothing.
    """
    import io
    import zipfile

    from test_extract_classcode import TERM, _class_constructing, _class_of

    stated = [(TERM, ["Check", "Проверить"]), (TERM, ["HasRight", "ЕстьПраво"])]
    kinds = [("AcmeRight", "АкмеПраво")]
    if second_kind:
        kinds.append(("AcmeMark", "АкмеМетка"))
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("demo/kinds/ProjectElementKindCmptEnum.class", _kind_enum_blob(kinds))
        if namesake:
            # Written FIRST, so the walk meets it before the class the environment builds.
            z.writestr("demo/other/AcmeRightManagerCtMetaObject.class", _class_of(stated))
            z.writestr(_MANAGER_CLASS + ".class", _class_of([]))
        else:
            z.writestr(_MANAGER_CLASS + ".class", _class_of(stated))
        steps: list[tuple[str, ...]] = []
        if constructed_from is not None:
            steps += [("new", _MANAGER_CLASS), ("init", _MANAGER_CLASS, constructed_from)]
        if view_from_project_type:
            # the same environment builds something else from the project type: not a metaobject
            steps += [("new", "demo/acme/AcmeRightView"),
                      ("init", "demo/acme/AcmeRightView", _PROJECT_TYPE_INIT)]
        if twin:
            twin_class = "demo/acme/AcmeRightManagerClientCtMetaObject"
            z.writestr(twin_class + ".class", _class_of(stated))
            steps += [("new", twin_class), ("init", twin_class, _PROJECT_TYPE_INIT)]
        z.writestr("demo/acme/AcmeCtEnvironment.class", _class_constructing(steps))
        if foreign_pair:
            z.writestr("demo/acme/AcmeRightManagerBslImpl.class",
                       _class_of([(TERM, ["Lock", "Заблокировать"])]))
    lsp = io.BytesIO()
    with zipfile.ZipFile(lsp, "w") as z:
        z.writestr(_LSP_PAGE, _template_markdown(list(english)))
        if second_kind:
            z.writestr(_LSP_PAGE.replace("AcmeRightName", "AcmeMarkName"),
                       _template_markdown(list(english), "AcmeMarkName"))
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())
        z.writestr(_LSP_JAR, lsp.getvalue())
        z.writestr(_TEMPLATE_PAGE, _template_html(list(russian)))
        if second_kind:
            z.writestr(_TEMPLATE_PAGE.replace("AcmeRightName", "AcmeMarkName"),
                       _template_html(list(russian)))
    return zipfile.ZipFile(car)


def _owners(car) -> dict[str, str]:
    from xbsl.extract.terms import ManagerEvidence, _scan_meta_objects, manager_owners

    evidence = ManagerEvidence()
    members, _common, _types = _scan_meta_objects(car, evidence)
    return manager_owners(car, members, evidence)


def test_a_manager_is_filed_under_the_kind_its_template_documents():
    """The compiler builds the metaobject from the project type of an element, the class
    states the member pairs, and the template of the kind documents exactly those members in
    both languages - the Russian help page and the language-server page of the compiled
    template. The owner is the key the members table files the class under."""
    assert _owners(_manager_car()) == {"АкмеПраво": "AcmeRightManager"}


def test_a_metaobject_no_environment_builds_from_a_project_type_names_no_kind():
    assert _owners(_manager_car(constructed_from=None)) == {}
    assert _owners(_manager_car(constructed_from="(Ldemo/acme/Layout;)V",
                                view_from_project_type=True)) == {}


def test_a_template_documented_otherwise_names_no_kind():
    """The same metaobject with one more method on the help page, or another English member on
    the language-server page, is not proven to be this kind's manager."""
    assert _owners(_manager_car(russian=("ЕстьПраво", "Заблокировать", "Проверить"))) == {}
    assert _owners(_manager_car(english=("HasRight", "Verify"))) == {}


def test_two_metaobjects_that_fit_one_kind_name_none_of_them():
    assert _owners(_manager_car(twin=True)) == {}


def test_one_metaobject_that_fits_two_kinds_names_neither():
    """The mirror of the case above: two templates documenting exactly the same members leave
    the class fitting both, and a manager that could belong to either is proven for neither."""
    assert _owners(_manager_car(second_kind=True)) == {}


def test_evidence_of_two_classes_of_one_simple_name_is_not_merged():
    """The class the environment builds and the class that states the terms are told apart by
    their full name. Kept by the SIMPLE name, the two were one: a namesake in another package
    lent its pairs to a class that states nothing, and the join was stated on evidence no single
    class gives. Here the namesake is met first, which is what used to decide it."""
    assert _owners(_manager_car(namesake=True)) == {}


def test_a_members_table_with_a_word_the_template_lacks_names_no_kind():
    """The runtime reads the whole row of the owner: a foreign pair under the same key would
    answer for a word the manager of the kind does not have."""
    assert _owners(_manager_car(foreign_pair=True)) == {}


# --- the tied owner of a template page is picked by name, not by set iteration order ------


def _heading(owner: str, method: str) -> str:
    return (f"# DeveloperName::ProjectName::SubsystemName::AcmeRightName#{method}()\n\n"
            f"**Определен:** **{owner}**\n")


def test_a_tied_owner_count_is_broken_alphabetically():
    """Two owners naming the same number of methods on a template page is a genuine tie, and
    `set(owners)` used to answer it: string hashing is randomized per process, so the same
    distribution picked a different owner - and with it a different set of members - from one
    run of `xbsl extract` to the next. Written with the alphabetically LATER owner first, so a
    plain "first one found" reading would get it wrong too."""
    from xbsl.extract.terms import _template_markdown_members

    text = "\n".join([
        _heading("Проверить", "MethodOne"), _heading("Проверить", "MethodTwo"),
        _heading("Активность", "MethodThree"), _heading("Активность", "MethodFour"),
    ])

    assert _template_markdown_members(text, "AcmeRightName") == {"MethodThree", "MethodFour"}


def test_the_alphabetical_tie_break_does_not_depend_on_source_order():
    """Same tie, owners written in the opposite order - the winner must not move, or the
    choice would be reading TEXT order rather than the alphabet."""
    from xbsl.extract.terms import _template_markdown_members

    text = "\n".join([
        _heading("Активность", "MethodThree"), _heading("Активность", "MethodFour"),
        _heading("Проверить", "MethodOne"), _heading("Проверить", "MethodTwo"),
    ])

    assert _template_markdown_members(text, "AcmeRightName") == {"MethodThree", "MethodFour"}


def test_an_outright_majority_owner_still_wins_over_the_alphabet():
    """The tie-break only applies to an actual tie - three against one still picks the three,
    even though the runner-up sorts first."""
    from xbsl.extract.terms import _template_markdown_members

    text = "\n".join([
        _heading("Активность", "MethodOne"),
        _heading("Проверить", "MethodTwo"), _heading("Проверить", "MethodThree"),
        _heading("Проверить", "MethodFour"),
    ])

    assert _template_markdown_members(text, "AcmeRightName") == {
        "MethodTwo", "MethodThree", "MethodFour",
    }
