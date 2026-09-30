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


# --- a generated EMF package states its pairs in annotations --------------------------------


def _scan_classes(classes: dict[str, bytes], languages: dict[str, str] | None = None):
    """_scan_meta_objects over one platform jar holding the given classes."""
    import io
    import zipfile

    from xbsl.extract.terms import _scan_meta_objects

    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        for name, blob in classes.items():
            z.writestr(name, blob)
    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())
    return _scan_meta_objects(zipfile.ZipFile(car), languages=languages)


def test_the_pairs_of_an_emf_package_are_spelled_as_its_annotations_state_them():
    """The annotations write the Russian spelling first, and the pool keeps that order: read
    by adjacency, the English of one annotation met the Russian of the next, and this node of an
    exchange plan got `ReceivedNumber`. The same class under another base is read by adjacency
    alone, and shows the shift."""
    from test_extract_classcode import EMF_OWNER, NODE_ANNOTATIONS, _package_of

    name = EMF_OWNER + ".class"
    members, common, _types = _scan_classes({name: _package_of(NODE_ANNOTATIONS)})
    shifted, _common, _types = _scan_classes(
        {name: _package_of(NODE_ANNOTATIONS, base="java/lang/Object")})

    assert members["DemoPackageImpl"] == {
        "НомерПринятого": "ReceivedNumber", "ЭтотУзел": "ThisNode",
    }
    assert common["ЭтотУзел"] == "ThisNode"
    assert shifted["DemoPackageImpl"] == {
        "НомерПринятого": "SentNumber", "ЭтотУзел": "ReceivedNumber",
    }


def test_a_word_no_annotation_of_the_package_pairs_is_no_pair():
    """A property the package annotates in Russian alone stands next to the English name of
    the previous annotation, and the neighbourhood took that name for its spelling."""
    from test_extract_classcode import EMF_OWNER, _package_of

    annotations = [["ru", "Тип", "en", "Type"], ["ru", "Длина"]]
    members, common, _types = _scan_classes({EMF_OWNER + ".class": _package_of(annotations)})
    neighbours, _common, _types = _scan_classes(
        {EMF_OWNER + ".class": _package_of(annotations, base="java/lang/Object")})

    assert "DemoPackageImpl" not in members
    assert "Длина" not in common
    assert neighbours["DemoPackageImpl"] == {"Длина": "Type"}


def test_a_word_the_package_states_two_ways_keeps_only_a_neighbour_it_states():
    """Two properties of one Russian name: the neighbour that is one of the stated spellings
    stays, a third one is dropped - the package cannot say which of the two it would be."""
    from test_extract_classcode import EMF_OWNER, _package_of

    two_ways = [["ru", "Метрика", "en", "Metric"], ["ru", "Метрика", "en", "UpdatingMetric"]]
    confirmed, _common, _types = _scan_classes({EMF_OWNER + ".class": _package_of(
        [["ru", "Узел", "en", "Node"], ["en", "Metric", "ru", "Метрика"], two_ways[1]])})
    stranger, _common, _types = _scan_classes({EMF_OWNER + ".class": _package_of(
        [["ru", "ПараметрМетрики", "en", "MetricParameter"], *two_ways])})

    assert confirmed["DemoPackageImpl"] == {"Метрика": "Metric"}
    assert "DemoPackageImpl" not in stranger


def test_a_data_class_is_read_by_the_aliases_of_its_properties():
    """A data class names a property of its JSON in English and aliases it in Russian, the
    alias first: the neighbourhood read the English of one property with the Russian of the
    next. Under an annotation nobody reads, the same pool still shows the shift."""
    from test_extract_classcode import DTO_PARAMETERS, JSON_ALIAS, JSON_PROPERTY, _data_class_of

    from xbsl.extract import terms

    members, _common, _types = _scan_classes(
        {"demo/dto/DemoDto.class": _data_class_of(DTO_PARAMETERS)})
    unread = [[(kind.replace("jackson", "acme"), elements) for kind, elements in parameter]
              for parameter in DTO_PARAMETERS]
    shifted, _common, _types = _scan_classes(
        {"demo/dto/DemoDto.class": _data_class_of(unread)})

    assert members["DemoDto"] == {"Поставщик": "Vendor", "Разработчик": "Developer"}
    assert shifted["DemoDto"] == {"Поставщик": "Developer", "Разработчик": "Name"}
    # The fixture spells the annotations the extractor reads, not a lookalike.
    assert (JSON_ALIAS, JSON_PROPERTY) == (terms._JSON_ALIAS, terms._JSON_PROPERTY)


def test_the_name_of_a_constant_is_not_the_english_of_its_value():
    """The pool keeps the name of a string constant next to the string: `FINISH_NAME_RU` came
    out as the English of the word for finish. A constant of the platform is written in
    capitals in both languages, and that pair stays."""
    from test_extract_classcode import _class_of

    from xbsl.extract.terms import _names_its_field

    members, common, _types = _scan_classes({"demo/words/Constants.class": _class_of(
        [], extra_strings=["FINISH_NAME_RU", "Завершить", "NEW_LINE", "НОВАЯ_СТРОКА"])})

    assert members["Constants"] == {"НОВАЯ_СТРОКА": "NEW_LINE"}
    assert "Завершить" not in common
    assert _names_its_field("SENDER_NAME_RU", "Отправитель")
    assert not _names_its_field("NEW_LINE", "НОВАЯ_СТРОКА")
    assert not _names_its_field("Recipient", "Получатель")


def test_a_language_name_is_paired_only_as_the_language_table_says():
    """An enumeration presents each language in its own language, so the pool holds English
    right before the Russian name of Russian; a reader of the descriptor lists the Russian
    and the English names in turn. Checked against the table of the languages, neither
    neighbourhood is a pair, and the Russian name keeps its common spelling."""
    from test_extract_classcode import _class_of

    presented = _class_of([], extra_strings=["EN", "English", "Русский"])
    listed = _class_of([], extra_strings=["Russian", "Английский", "English"])
    stated = _class_of([], extra_strings=["Russian", "Русский"])
    classes = {"demo/lang/Presented.class": presented, "demo/lang/Listed.class": listed,
               "demo/lang/Stated.class": stated}
    table = {"Русский": "Russian", "Английский": "English"}

    members, common, _types = _scan_classes(classes, languages=table)
    unchecked, unsettled, _types = _scan_classes(classes)

    assert "Presented" not in members and "Listed" not in members
    assert members["Stated"] == {"Русский": "Russian"}
    assert common["Русский"] == "Russian"
    assert unchecked["Presented"] == {"Русский": "English"}
    assert unchecked["Listed"] == {"Английский": "Russian"}
    assert "Русский" not in unsettled


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


def test_a_title_with_a_control_character_inside_a_word_still_pairs(tmp_path):
    """Pages of one build carry NUL characters inside words, the title among them: the pair is
    read from the title without them, the way the stdlib step reads a page."""
    import zipfile

    from xbsl.extract import stdlib, terms

    car = tmp_path / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    page = "<html><head><title>Пере\x00чень | Product</title></head><body></body></html>"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr(stdlib.STD_BASE + "Tools/Listing_ru/index.html", page)

    sections, _conflicts = terms.extract(tmp_path)

    assert sections["types"].get("Перечень") == "Listing"


# --- the reserved words of the query language, out of the help ------------------------------

#: The table as a minified site writes it: the closing tags of rows and cells are left out.
_RESERVED_MINIFIED = (
    "<p>В языке запросов зарезервированы следующие ключевые слова:</p>"
    "<table><thead><tr><th>Русский язык<th>Английский язык<th>Подробнее<tbody>"
    "<tr><td><code>ИЗ</code><td><code>FROM</code><td><a href=/docs/help/topics/select-from/>"
    "Предложение ИЗ</a>"
    "<tr><td><code>ИСТИНА</code><td><code>TRUE</code><td>Значение типа <code>Булево</code>"
    "<tr><td><code>НЕОПРЕДЕЛЕНО</code><td><code>UNDEFINED</code><td>Литерал типа Неопределено"
    "</table>\n<p>Также зарезервированными словами языка запросов без варианта на русском языке "
    "являются <a href=/docs/help/topics/is-null-expression/><code>NULL</code></a> и "
    "<code>TEMP</code>.</p>\n<p>Ключевые слова нечувствительны к регистру.</p>"
)
#: The same table with every closing tag, as an older help writes it.
_RESERVED_FULL = (
    "<table><thead><tr><th>Русский язык</th><th>Английский язык</th><th>Подробнее</th></tr>"
    "</thead><tbody><tr><td><code>ИЗ</code></td><td><code>FROM</code></td><td>-</td></tr>"
    "<tr><td><code>ИСТИНА</code></td><td><code>TRUE</code></td><td>-</td></tr>"
    "<tr><td><code>НЕОПРЕДЕЛЕНО</code></td><td><code>UNDEFINED</code></td><td>-</td></tr>"
    "</tbody></table> <p>Также зарезервированными словами языка запросов без варианта на "
    "русском языке являются <code>NULL</code> и <code>TEMP</code>.</p>"
)
_RESERVED = {"ИЗ": "FROM", "ИСТИНА": "TRUE", "НЕОПРЕДЕЛЕНО": "UNDEFINED"}


def test_the_reserved_words_are_read_from_the_table_of_the_help():
    """The literals of the query language are in no vocabulary of the parser; the help lists
    them in a table of both spellings, and the words without a Russian spelling after it. The
    minified markup and the full one read alike."""
    from xbsl.extract.terms import query_reserved_words

    assert query_reserved_words(_RESERVED_MINIFIED) == (_RESERVED, ["NULL", "TEMP"])
    assert query_reserved_words(_RESERVED_FULL) == (_RESERVED, ["NULL", "TEMP"])


def test_only_the_table_of_both_spellings_is_the_list_of_the_reserved_words():
    """Another table of the help and a paragraph that is not about the missing Russian spelling
    give nothing: a code word of any paragraph is not a reserved word."""
    from xbsl.extract.terms import query_reserved_words

    other = _RESERVED_FULL.replace("Русский язык", "Имя").replace("Английский язык", "Тип")
    unrelated = _RESERVED_FULL.replace("без варианта на русском языке", "среди прочих")

    assert query_reserved_words(other) == ({}, [])
    assert query_reserved_words(unrelated) == (_RESERVED, [])
    assert query_reserved_words("<p>Страница без таблицы</p>") == ({}, [])


def test_the_step_takes_the_reserved_words_from_the_page_of_the_distribution(tmp_path):
    """End to end over a distribution: the page is read the way the other pages are, and a help
    without the page leaves both lists empty, so the step writes neither key."""
    import zipfile

    from xbsl.extract import terms

    with_page = tmp_path / "with"
    with_page.mkdir()
    car = with_page / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr(terms._QUERY_SYNTAX_PAGE, "<html><body>" + _RESERVED_MINIFIED + "</body></html>")
    without_page = tmp_path / "without"
    without_page.mkdir()
    with zipfile.ZipFile(without_page / car.name, "w") as z:
        z.writestr("data/docs/help/ru/topics/other/index.html", _RESERVED_MINIFIED)

    sections, _conflicts = terms.extract(with_page)
    empty, _conflicts = terms.extract(without_page)

    assert sections["query_reserved"] == _RESERVED
    assert sections["query_reserved_english_only"] == ["NULL", "TEMP"]
    assert empty["query_reserved"] == {} and empty["query_reserved_english_only"] == []


def test_the_reserved_words_are_written_only_when_the_help_lists_them(tmp_path):
    """An absent key tells a reader to keep the words it knows by hand; an empty list would claim
    that the language reserves nothing."""
    import json
    import zipfile

    from xbsl.extract import _distro, terms

    written = {}
    pages = (("with", terms._QUERY_SYNTAX_PAGE), ("without", "data/docs/help/ru/x/index.html"))
    for name, page in pages:
        dist = tmp_path / name
        dist.mkdir()
        car = dist / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
        with zipfile.ZipFile(car, "w") as z:
            z.writestr(page, _RESERVED_MINIFIED)
        root = tmp_path / f"data-{name}"
        try:
            terms.main(["--dist", str(dist), "--element-version", "9.9.9+1",
                        "--data-dir", str(root)])
        finally:
            _distro.set_data_root(None)
        written[name] = json.loads((root / "9.9.9+1" / "terms.json").read_text(encoding="utf-8"))

    assert written["with"]["query_reserved"] == _RESERVED
    assert written["with"]["query_reserved_english_only"] == ["NULL", "TEMP"]
    assert "query_reserved" not in written["without"]
    assert "query_reserved_english_only" not in written["without"]


# --- the types of the literals, out of the same table ------------------------------------------

#: The table with its column of details as the help writes it: a literal links the page of its
#: type (next to a page of a topic), a keyword - a topic only. `ПУСТО` is a made-up literal whose
#: type page sits in a namespace, `НИЧЕГО` links two type pages at once.
_RESERVED_LINKED = (
    "<table><thead><tr><th>Русский язык<th>Английский язык<th>Подробнее<tbody>"
    "<tr><td><code>ИЗ</code><td><code>FROM</code><td>"
    "<a class=\"\" href=\"/docs/help/topics/select-from/\">Предложение ИЗ</a>"
    "<tr><td><code>ИСТИНА</code><td><code>TRUE</code><td>Значение типа "
    "<a class=\"\" href=\"/docs/help/stdlib/element/xbsl/Std/Boolean_ru/\"><code>Булево</code></a>."
    " Используется в <a class=\"\" "
    "href=\"/docs/help/topics/logical-and-boolean-operations-in-query-language/\">операциях</a>"
    "<tr><td><code>НЕОПРЕДЕЛЕНО</code><td><code>UNDEFINED</code><td>Литерал типа "
    "<a href=/docs/help/stdlib/element/xbsl/Std/Undefined_ru/>Неопределено</a>"
    "<tr><td><code>ПУСТО</code><td><code>EMPTY</code><td>Литерал типа "
    "<a href=\"/docs/help/stdlib/element/xbsl/Std/Collections/Blank_ru/\">Пустота</a>"
    "<tr><td><code>НИЧЕГО</code><td><code>NOTHING</code><td>"
    "<a href=\"/docs/help/stdlib/element/xbsl/Std/Boolean_ru/\">Булево</a> или "
    "<a href=\"/docs/help/stdlib/element/xbsl/Std/Undefined_ru/\">Неопределено</a>"
    "</table>"
)
_TYPE_PAIRS = {"Булево": "Boolean", "Неопределено": "Undefined", "Пустота": "Blank"}


def test_the_type_of_a_literal_is_the_type_page_its_row_links():
    """The column of details links a literal to the reference page of its type: the English
    name of the page is paired with the Russian one by the type pairs of the distribution. A
    row that links a topic only gives nothing, and so does a row that links two type pages."""
    from xbsl.extract.terms import query_reserved_types

    assert query_reserved_types(_RESERVED_LINKED, _TYPE_PAIRS) == {
        "ИСТИНА": "Булево", "НЕОПРЕДЕЛЕНО": "Неопределено", "ПУСТО": "Пустота",
    }


def test_a_literal_whose_type_has_no_pair_gets_no_type():
    """Nothing is guessed: a page the type pairs do not know, a table without links (an older
    help) and a page without the table answer with nothing."""
    from xbsl.extract.terms import query_reserved_types, query_reserved_words

    unpaired = {"Булево": "Boolean"}

    assert query_reserved_types(_RESERVED_LINKED, unpaired) == {"ИСТИНА": "Булево"}
    assert query_reserved_types(_RESERVED_FULL, _TYPE_PAIRS) == {}
    assert query_reserved_types("<p>Страница без таблицы</p>", _TYPE_PAIRS) == {}
    # The words of the same table read as before.
    words, _english_only = query_reserved_words(_RESERVED_LINKED)
    assert words["ПУСТО"] == "EMPTY" and words["ИСТИНА"] == "TRUE"


def _car_with_types(dist, page: str):
    """A distribution with the syntax page and the reference pages of two types."""
    import zipfile

    from xbsl.extract import stdlib, terms

    dist.mkdir()
    car = dist / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr(terms._QUERY_SYNTAX_PAGE, "<html><body>" + page + "</body></html>")
        for russian, english in (("Булево", "Boolean"), ("Неопределено", "Undefined")):
            z.writestr(stdlib.STD_BASE + f"{english}_ru/index.html",
                       f"<html><head><title>{russian} | Product</title></head></html>")
    return dist


def test_the_step_writes_the_types_of_the_literals_it_can_pair(tmp_path):
    """End to end: the type pairs of the distribution pair the pages the table links, the
    step writes them next to the reserved words - and leaves the key out when the table links no
    type page, the way it leaves out the words when there is no table."""
    import json

    from xbsl.extract import _distro, terms

    written = {}
    for name, page in (("linked", _RESERVED_LINKED), ("plain", _RESERVED_MINIFIED)):
        dist = _car_with_types(tmp_path / name, page)
        root = tmp_path / f"data-{name}"
        try:
            terms.main(["--dist", str(dist), "--element-version", "9.9.9+1",
                        "--data-dir", str(root)])
        finally:
            _distro.set_data_root(None)
        written[name] = json.loads((root / "9.9.9+1" / "terms.json").read_text(encoding="utf-8"))

    # `Blank` has no page in this distribution, so `ПУСТО` pairs nothing.
    assert written["linked"]["query_reserved_types"] == {
        "ИСТИНА": "Булево", "НЕОПРЕДЕЛЕНО": "Неопределено",
    }
    assert "query_reserved_types" not in written["plain"]
    assert written["plain"]["query_reserved"] == _RESERVED


# --- the languages of a project: a compiled enumeration ---------------------------------------


def _car_with_classes(path, classes: dict[str, bytes], jar_name: str = "com.e1c.g5rt.demo-1.0.jar",
                      extra: dict[str, str] | None = None):
    """A distribution whose one platform jar holds the given classes (and extra text members)."""
    import io
    import zipfile

    path.mkdir()
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        for member, blob in classes.items():
            z.writestr(member, blob)
        for member, text in (extra or {}).items():
            z.writestr(member, text)
    car = path / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/chassis/modules/" + jar_name, jar.getvalue())
    return path


def test_a_language_is_read_from_its_code_its_term_and_its_mode():
    from test_extract_classcode import DEMO_LANGUAGES, _enumeration

    from xbsl.extract.terms import language_rows

    assert language_rows(_enumeration(DEMO_LANGUAGES)) == [
        {"ru": "Английский", "en": "English", "code": "en", "since": "1.0"},
        {"ru": "Вьетнамский", "en": "Vietnamese", "code": "vi", "since": "9.1"},
    ]


def test_an_enumeration_of_another_shape_is_no_language_table():
    """One constant without a mode - or with something other than a language code before its
    term - makes the class some other enumeration, whatever the rest of it looks like."""
    from test_extract_classcode import DEMO_LANGUAGES, _enumeration

    from xbsl.extract.terms import language_rows

    no_mode = DEMO_LANGUAGES + [("RU", "ru", "Russian", "Русский", None)]
    no_code = DEMO_LANGUAGES + [("RU", "Default", "Russian", "Русский", "CMODE_1_0")]

    assert language_rows(_enumeration(no_mode)) is None
    assert language_rows(_enumeration(no_code)) is None


def test_the_scan_finds_the_languages_by_their_shape_and_names_the_class(tmp_path):
    import zipfile

    from test_extract_classcode import DEMO_LANGUAGES, _enumeration

    from xbsl.extract import _distro
    from xbsl.extract.terms import scan_language_table

    dist = _car_with_classes(tmp_path / "dist", {
        "demo/lang/DemoLanguages.class": _enumeration(DEMO_LANGUAGES),
        "demo/lang/Other.class": b"\xca\xfe\xba\xbe not a class the reader follows CMODE_",
    })

    with zipfile.ZipFile(_distro.find_car(dist)) as car:
        found = scan_language_table(car)

    assert found is not None
    assert found[0] == "DemoLanguages"
    assert [row["code"] for row in found[1]] == ["en", "vi"]


def test_the_step_gives_every_language_its_english_spelling(tmp_path):
    """End to end: the values of the language enumeration join the enumeration values of the
    term dictionary, which a translation of a project descriptor reads them by."""
    import json

    from test_extract_classcode import DEMO_LANGUAGES, _enumeration

    from xbsl.extract import _distro, terms

    dist = _car_with_classes(tmp_path / "dist", {
        "demo/lang/DemoLanguages.class": _enumeration(DEMO_LANGUAGES),
    })
    root = tmp_path / "data"
    try:
        terms.main(["--dist", str(dist), "--element-version", "9.9.9+1", "--data-dir", str(root)])
    finally:
        _distro.set_data_root(None)
    written = json.loads((root / "9.9.9+1" / "terms.json").read_text(encoding="utf-8"))

    assert written["enums"]["Вьетнамский"] == "Vietnamese"
    assert written["enums"]["Английский"] == "English"


# --- the compiled enumerations the properties of the model are typed by ---------------------


def test_the_values_of_a_compiled_enumeration_come_in_both_spellings():
    from test_extract_classcode import DEMO_PRIORITIES, PRIORITIES, _value_enumeration

    from xbsl.extract.terms import enumeration_values

    built = _value_enumeration("demo/acme/StepState", [
        ("DONE", "Done", "Готово"), ("PLAIN_TEXT", "PlainText", "PlainText", "CMODE_9_1"),
    ], builder=True)

    assert enumeration_values(_value_enumeration(PRIORITIES, DEMO_PRIORITIES)) == [
        ("Low", "Низкая"), ("High", "Высокая"),
    ]
    # A value spelled alike in both languages is still a value.
    assert enumeration_values(built) == [("Done", "Готово"), ("PlainText", "PlainText")]


def test_an_enumeration_of_another_shape_gives_no_values():
    """Every constant must be built from its own name and one pair: a constant that pushes
    anything else first, or no pair at all, makes the class some other enumeration."""
    from test_extract_classcode import (
        DEMO_LANGUAGES, DEMO_PRIORITIES, PRIORITIES, _enumeration, _value_enumeration,
    )

    from xbsl.extract.terms import enumeration_values

    presented = [("EN", "English"), ("RU", "Русский")]
    named_apart = DEMO_PRIORITIES + [("MEDIUM", "Normal", "Обычная", "7420e42d")]

    assert enumeration_values(_value_enumeration(PRIORITIES, presented)) is None
    assert enumeration_values(_value_enumeration(PRIORITIES, DEMO_PRIORITIES, named=False)) is None
    # A constant named apart from its value (MEDIUM for Normal) still gives the value.
    assert enumeration_values(_value_enumeration(PRIORITIES, named_apart)) == [
        ("Low", "Низкая"), ("High", "Высокая"), ("Normal", "Обычная"),
    ]
    # The term the language enumeration builds is its pair.
    assert enumeration_values(_enumeration(DEMO_LANGUAGES)) == [
        ("English", "Английский"), ("Vietnamese", "Вьетнамский"),
    ]


def test_the_scan_reads_the_classes_asked_for_and_keeps_the_fullest_copy(tmp_path):
    import io
    import zipfile

    from test_extract_classcode import DEMO_PRIORITIES, PRIORITIES, _value_enumeration

    from xbsl.extract.terms import scan_enumeration_classes

    path = PRIORITIES + ".class"

    def jar(blob: bytes) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr(path, blob)
            z.writestr("demo/acme/Other.class", blob)
        return out.getvalue()

    car = io.BytesIO()
    with zipfile.ZipFile(car, "w") as z:
        z.writestr("data/lib/com.e1c.g5rt.short-1.0.jar",
                   jar(_value_enumeration(PRIORITIES, DEMO_PRIORITIES[:1])))
        z.writestr("data/lib/com.e1c.g5rt.full-1.0.jar",
                   jar(_value_enumeration(PRIORITIES, DEMO_PRIORITIES)))
        z.writestr("data/lib/vendor-lib-1.0.jar", jar(b"not a class"))

    found = scan_enumeration_classes(zipfile.ZipFile(car), {path, "demo/acme/Missing.class"})

    assert found == {path: [("Low", "Низкая"), ("High", "Высокая")]}


def test_the_step_spells_the_values_of_the_wrapped_enumerations(tmp_path):
    """End to end: the values of an enumeration the model only wraps join the enumeration
    values of the term dictionary, the way the languages do."""
    import json

    from test_extract_metamodel import _wrapping_distribution

    from xbsl.extract import _distro, terms

    dist = _wrapping_distribution(tmp_path)
    root = tmp_path / "data"
    try:
        terms.main(["--dist", str(dist), "--element-version", "9.9.9+1", "--data-dir", str(root)])
    finally:
        _distro.set_data_root(None)
    written = json.loads((root / "9.9.9+1" / "terms.json").read_text(encoding="utf-8"))

    assert written["enums"]["Низкая"] == "Low"
    assert written["enums"]["Высокая"] == "High"
    assert written["enums"]["Готово"] == "Done"
    assert "Любой" not in written["enums"]
