"""Parsing of distribution docs pages in xbsl/extract/stdlib.py (component_props).

No network or distribution needed - the pages are synthetic, modeled on the real
Docusaurus markup.
"""

from xbsl.extract import stdlib as _MODULE

_COMPONENT_PAGE = (
    "<html><head><title>МойКомпонент | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>МойКомпонент</h1>"
    '<h2 class="anchor" id="иерархия-типа">Иерархия типа<a href="#иерархия-типа" '
    'class="hash-link">​</a></h2>'
    '<p>Базовые типы: <a href="/Object_ru/">Объект</a>, '
    '<a href="/Component_ru/">Стд::Интерфейс::Компонент</a></p>'
    "<h2>Конструкторы​</h2><h3>МойКомпонент​</h3>"
    "<h2>Свойства​</h2>"
    '<h3 class="anchor" id="заголовок">Заголовок<a href="#заголовок" '
    'class="hash-link">​</a></h3>'
    '<p>Тип: <a href="/String_ru/">Строка</a></p>'
    "<h3>Заголовок​</h3><p>Тип: <a href='/String_ru/'>Строка</a> (установка)</p>"
    "<h2>Список унаследованных свойств​</h2>"
    '<h3 class="anchor" id="компонент">Компонент<a href="#компонент" '
    'class="hash-link">​</a></h3>'
    '<p><a href="/Component_ru/#видимость">Видимость</a>, '
    '<a href="/Component_ru/#ширина">Ширина</a></p>'
    "</article></body></html>"
)

_PLAIN_TYPE_PAGE = (
    "<html><head><title>ПростойТип | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>ПростойТип</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Свойства​</h2><h3>Заголовок​</h3>"
    "</article></body></html>"
)


_TYPE_PAGE = (
    "<html><head><title>КонтекстДоступа | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>КонтекстДоступа</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Свойства​</h2><h3>ТекущийПользователь​</h3>"
    "<h2>Методы​</h2><h3>Привилегированный​</h3><h3>ВыполнитьСПравами​</h3>"
    "<h2>Список унаследованных методов​</h2>"
    "<p><a href='/Object_ru/#tzn'>ТипЗначения</a></p>"
    "</article></body></html>"
)


_NOISY_PAGE = (
    "<html><head><title>ПотокЧтения | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>ПотокЧтения</h1>"
    "<h2>Св\x00ойства​</h2><h3>Позиц\x00ия​</h3>"
    "<h2>Список унаследованных \x00методов​</h2>"
    "<p><a href='/Object_ru/#zakryt'>Закр\x00ыть</a></p>"
    "</article></body></html>"
)


_EVENT_PAGE = (
    "<html><head><title>Кнопка | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>Кнопка</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Component_ru/'>Компонент</a></p>"
    "<h2>Свойства​</h2><h3>Заголовок​</h3>"
    "<h2>Методы​</h2><h3>Активировать​</h3>"
    "<h2>События​</h2><h3>ПриНажатии​</h3>"
    "<h2>Список унаследованных событий​</h2>"
    "<h3 class='anchor' id='компонент'>Компонент</h3>"
    "<p><a href='/Component_ru/#принаведении'>ПриНаведении</a>, "
    "<a href='/Component_ru/#припотеренаведения'>ПриПотереНаведения</a></p>"
    "</article></body></html>"
)


def test_page_members_reads_the_events_section():
    """The newer documents moved events out of the properties section, and reading two sections only made
    the data-diff report dozens of members as REMOVED while the API had not changed."""
    props, methods, events = _MODULE.page_members(_EVENT_PAGE)
    assert props == {"Заголовок"} and methods == {"Активировать"}
    assert events == {"ПриНажатии", "ПриНаведении", "ПриПотереНаведения"}
    # An event is not a property: the kinds stay apart, or the consumers would offer an event
    # where a property is expected.
    assert not events & props


def test_a_property_listed_under_the_events_heading_stays_a_property():
    """Observed in the distribution: the list and diagram pages state the inherited PROPERTIES
    under the inherited-events heading, with links to the property anchors of the base. Copied
    verbatim, a dozen sizing properties would become events of every such type."""
    page = _EVENT_PAGE.replace(
        "<p><a href='/Component_ru/#принаведении'>ПриНаведении</a>, ",
        "<p><a href='/Component_ru/#видимость'>Видимость</a>, "
        "<a href='/Component_ru/#принаведении'>ПриНаведении</a>, ",
    ).replace("<h2>Свойства​</h2><h3>Заголовок​</h3>",
              "<h2>Свойства​</h2><h3>Заголовок​</h3><h3>Видимость​</h3>")
    props, _methods, events = _MODULE.page_members(page)

    assert "Видимость" in props
    assert "Видимость" not in events
    assert {"ПриНажатии", "ПриНаведении", "ПриПотереНаведения"} <= events


def test_page_members_props_and_methods():
    # type members = properties (H3) and methods (H3) separately + inherited ones (links of their
    # own section), without constructors and the hierarchy
    props, methods, events = _MODULE.page_members(_TYPE_PAGE)
    assert props == {"ТекущийПользователь"}
    assert methods == {"Привилегированный", "ВыполнитьСПравами", "ТипЗначения"}
    assert events == set()
    assert "Объект" not in props | methods  # a base type from the hierarchy is not a member


def test_page_members_control_chars_cleaned():
    # on some docs pages headings and names arrive with control characters inside the word:
    # without cleaning, the section is not recognized and the name fails validation - members
    # get lost silently
    props, methods, _events = _MODULE.page_members(_NOISY_PAGE)
    assert props == {"Позиция"} and methods == {"Закрыть"}


def test_component_page_props_collected():
    got = _MODULE.component_props("какой-то/путь/index.html", _COMPONENT_PAGE)
    assert got is not None
    name, props = got
    assert name == "МойКомпонент"
    # own properties - only H3 headings (the getter/setter duplicate is collapsed, type links
    # from descriptions do not get in), inherited ones - link texts of their own section
    assert props == {"Заголовок", "Видимость", "Ширина"}


def test_non_component_page_skipped():
    # the base types do not include Стд::Интерфейс::Компонент - the page is not a component
    assert _MODULE.component_props("какой-то/путь/index.html", _PLAIN_TYPE_PAGE) is None


def test_component_base_page_included_by_path():
    # the Компонент page itself (only Объект among its base types) is included by its known path
    raw = _PLAIN_TYPE_PAGE.replace("ПростойТип", "Компонент")
    got = _MODULE.component_props(_MODULE.COMPONENT_PAGE, raw)
    assert got is not None
    assert got[0] == "Компонент" and got[1] == {"Заголовок"}


_GENERICS_PAGE = (
    "<html><head><title>СпискиНастроек | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>СпискиНастроек</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Методы​</h2>"
    "<h3>ПолучитьМножество​</h3>"
    # The real page markup: type names wrapped in links, generic brackets as entities.
    '<pre class="highlight"><code>ПолучитьМножество(): '
    '<a href="/ReadableSet_ru/">ЧитаемоеМножество</a>&lt;'
    '<a href="/Settings_ru/">Настройки</a>&gt;</code></pre>'
    "<h3>Значение​</h3>"
    '<pre class="highlight"><code>Значение(): <a href="/String_ru/">Строка</a>?</code></pre>'
    "<h3>Общий​</h3>"
    '<pre class="highlight"><code>Общий(Имя: <a href="/String_ru/">Строка</a>): '
    '<a href="/Array_ru/">Массив</a>&lt;<a href="/String_ru/">Строка</a>&gt;</code></pre>'
    '<pre class="highlight"><code>Общий(): '
    '<a href="/Array_ru/">Массив</a>&lt;<a href="/Number_ru/">Число</a>&gt;</code></pre>'
    "<h3>Разный​</h3>"
    '<pre class="highlight"><code>Разный(): <a href="/String_ru/">Строка</a></code></pre>'
    '<pre class="highlight"><code>Разный(): <a href="/Number_ru/">Число</a></code></pre>'
    "</article></body></html>"
)


def test_page_member_types_keeps_the_generic_parameter():
    got = _MODULE.page_member_types(_GENERICS_PAGE)
    # The full docs spelling survives (entities unescaped, link tags stripped)...
    assert got["ПолучитьМножество"] == "ЧитаемоеМножество<Настройки>"
    assert got["Значение"] == "Строка?"
    # ...overloads that agree on the head alone degrade to the head...
    assert got["Общий"] == "Массив"
    # ...and overloads with differing heads are dropped, as before.
    assert "Разный" not in got


def test_extract_merges_topic_only_types(tmp_path):
    """A surface documented only in a guide topic still lands in the name catalog.

    The end-to-end path matters: the supplement must survive the page walk of extract(),
    not just exist as a constant - a refactor that rebuilds `names` from the pages alone
    would silently drop it, and yaml/unknown-type would flag legitimate code again.
    """
    import zipfile

    car = tmp_path / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    with zipfile.ZipFile(car, "w") as z:
        z.writestr(_MODULE.STD_BASE + "AccessContext_ru/index.html", _TYPE_PAGE)
    names = _MODULE.extract(tmp_path)[0]
    assert _MODULE.TOPIC_ONLY_TYPES <= names
    assert "КонтекстДоступа" in names  # the ordinary page walk is intact


# --- constructors: "empty" / "args" / "none" (page_constructors) ----------------------------

def _ctor_page(*, name: str, body: str) -> str:
    """A type page carrying the given constructors section - the markup is the real one."""
    return (
        f"<html><head><title>{name} | 1С:Предприятие.Элемент</title></head><body>"
        f"<article><h1>{name}</h1>"
        "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
        f"{body}"
        "<h2>Методы​</h2><h3>ВСтроку​</h3>"
        '<pre class="highlight"><code>ВСтроку(): <a href="/String_ru/">Строка</a></code></pre>'
        "</article></body></html>"
    )


def test_page_constructors_empty_overload_wins():
    """Two overloads, one of them argument-less: the type is constructible empty."""
    body = (
        "<h2>Конструкторы​</h2><h3>Массив​</h3>"
        '<pre class="highlight"><code>Массив()</code></pre>'
        "<h3>Массив​</h3>"
        '<pre class="highlight"><code>Массив(Обходимое: '
        '<a href="/Iterable_ru/">Обходимое</a>&lt;ТипЭлемента&gt;)</code></pre>'
    )
    raw = _ctor_page(name="Массив", body=body)
    assert _MODULE.page_constructors(raw, "Массив") == _MODULE.CTOR_EMPTY


def test_page_constructors_only_copying_one_is_args():
    """A copying constructor alone: the type has no default value."""
    body = (
        "<h2>Конструкторы​</h2><h3>ЧитаемыйМассив​</h3>"
        '<pre class="highlight"><code>ЧитаемыйМассив(Обходимое: '
        '<a href="/Iterable_ru/">Обходимое</a>&lt;ТипЭлемента&gt;)</code></pre>'
    )
    raw = _ctor_page(name="ЧитаемыйМассив", body=body)
    assert _MODULE.page_constructors(raw, "ЧитаемыйМассив") == _MODULE.CTOR_ARGS


def test_page_constructors_all_parameters_defaulted_is_empty():
    body = (
        "<h2>Конструкторы​</h2><h3>Настройка​</h3>"
        '<pre class="highlight"><code>Настройка(Режим: '
        '<a href="/Mode_ru/">Режим</a> = Режим.Обычный)</code></pre>'
    )
    raw = _ctor_page(name="Настройка", body=body)
    assert _MODULE.page_constructors(raw, "Настройка") == _MODULE.CTOR_EMPTY


def test_page_constructors_generic_argument_does_not_split_parameters():
    """A comma inside a generic argument does not make two parameters out of one."""
    body = (
        "<h2>Конструкторы​</h2><h3>Обёртка​</h3>"
        '<pre class="highlight"><code>Обёртка(Данные: '
        '<a href="/Map_ru/">Соответствие</a>&lt;<a href="/String_ru/">Строка</a>, '
        '<a href="/Number_ru/">Число</a>&gt;)</code></pre>'
    )
    raw = _ctor_page(name="Обёртка", body=body)
    assert _MODULE.page_constructors(raw, "Обёртка") == _MODULE.CTOR_ARGS


def test_page_constructors_example_block_is_not_an_overload():
    """An examples block follows the signature under the same H3 - it is not an overload."""
    body = (
        "<h2>Конструкторы​</h2><h3>УзелДанных​</h3>"
        '<pre class="highlight"><code>УзелДанных(Данные: '
        '<a href="/String_ru/">Строка</a>)</code></pre>'
        "<h4>Примеры​</h4>"
        '<pre class="highlight"><code>знч Узел = новый УзелДанных()</code></pre>'
    )
    raw = _ctor_page(name="УзелДанных", body=body)
    assert _MODULE.page_constructors(raw, "УзелДанных") == _MODULE.CTOR_ARGS


def test_page_constructors_absent_section_is_none():
    raw = _ctor_page(name="ОтветHttp", body="")
    assert _MODULE.page_constructors(raw, "ОтветHttp") == _MODULE.CTOR_NONE


# --- method signatures: what to pass, not just what comes back ---------------------------

SIGNATURES_PAGE = (
    "<html><head><title>КонтекстДоступа | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>КонтекстДоступа</h1>"
    "<h2>Методы​</h2>"
    # Overloads are separate H3 headings of the same name, as the real pages print them.
    "<h3>Дополнить​</h3>"
    '<pre class="highlight"><code>Дополнить(Ключи: '
    '<a href="/AccessKey_ru/">ЧитаемаяКоллекция</a>&lt;'
    '<a href="/AccessKey_ru/">КлючДоступа.Объект</a>&gt;): '
    '<a href="/AccessContext_ru/">КонтекстДоступа</a></code></pre>'
    "<h3>Дополнить​</h3>"
    '<pre class="highlight"><code>Дополнить(Тип: <a href="/Type_ru/">Тип</a>,'
    '<a href="/Rights_ru/">Права</a>: <a href="/Rights_ru/">ЧитаемаяКоллекция</a>): '
    '<a href="/AccessContext_ru/">КонтекстДоступа</a></code></pre>'
    "<h4>Примеры​</h4>"
    '<pre class="highlight"><code>знч К = КонтекстДоступа.Исходный()</code></pre>'
    "<h3>Информация​</h3>"
    '<pre class="highlight"><code>Информация(): <a href="/String_ru/">Строка</a></code></pre>'
    "<h2>Свойства​</h2><h3>Привилегированный​</h3>"
    '<pre class="highlight"><code>Привилегированный: <a href="/Boolean_ru/">Булево</a></code></pre>'
    "</article></body></html>"
)


def test_page_member_signatures_keeps_every_overload():
    got = _MODULE.page_member_signatures(SIGNATURES_PAGE)
    assert got["Дополнить"] == [
        "Дополнить(Ключи: ЧитаемаяКоллекция<КлючДоступа.Объект>): КонтекстДоступа",
        # The docs print no space after the comma - a rendering artifact, normalized here.
        "Дополнить(Тип: Тип, Права: ЧитаемаяКоллекция): КонтекстДоступа",
    ]
    assert got["Информация"] == ["Информация(): Строка"]


def test_page_member_signatures_leaves_examples_and_properties_out():
    got = _MODULE.page_member_signatures(SIGNATURES_PAGE)
    # The example block under the same heading opens with `знч`, not with the member name.
    assert not any("знч" in sig for sigs in got.values() for sig in sigs)
    # Properties have no parameters to show; their type is what member_types already answers.
    assert "Привилегированный" not in got


def test_own_members_strips_inherited_signatures():
    """A signature repeated by an heir is stored once - the loader re-expands it by `bases`."""
    types = {"Наследник": {"properties": set(), "methods": {"Общий", "Свой"}},
             "База": {"properties": set(), "methods": {"Общий"}}}
    sigs = {"Наследник": {"Общий": ["Общий(): Строка"], "Свой": ["Свой(Имя: Строка)"]},
            "База": {"Общий": ["Общий(): Строка"]}}
    _own_types, _own_returns, own_sigs = _MODULE._own_members(
        types, {}, sigs, {"Наследник": ["База"]}
    )
    assert own_sigs["Наследник"] == {"Свой": ["Свой(Имя: Строка)"]}
    assert own_sigs["База"] == {"Общий": ["Общий(): Строка"]}


# --- template directories -> element kinds (_template_kinds) --------------------------------

_KIND_TABLE = {
    "Справочник": "Catalog",
    "НаборКонстант": "ConstantsSet",
    "КонтрактСущности": "EntityContract",
    "КомпонентИнтерфейса": "InterfaceComponent",
}


def _template_car(tmp_path, *dirs: str):
    """A car carrying the given template directories (one index.html each)."""
    import zipfile

    car = tmp_path / "1c-enterprise-element-server-with-ide-9.9.9+1-test.car"
    with zipfile.ZipFile(car, "w") as z:
        for d in dirs:
            z.writestr(_MODULE.TEMPLATE_BASE + d + "/index.html", "<html></html>")
    return zipfile.ZipFile(car)


def test_template_kinds_derived_from_the_serializer_table(tmp_path, monkeypatch):
    """The template directory of a kind is its ENGLISH name plus `Name` - so a kind the docs
    describe is picked up without anyone adding a line to a hand-written map."""
    monkeypatch.setattr(_MODULE, "scan_kind_table", lambda _car: _KIND_TABLE)
    with _template_car(tmp_path, "CatalogName_ru", "ConstantsSetName_ru") as car:
        kinds, unmapped = _MODULE._template_kinds(car)

    assert kinds == {"CatalogName": "Справочник", "ConstantsSetName": "НаборКонстант"}
    assert unmapped == []


def test_template_kinds_sees_a_kind_that_has_no_page_of_its_own(tmp_path, monkeypatch):
    """EntityContract in 9.2.8+11 has only the pages of the types it generates. Collecting the
    own pages alone dropped the kind - and with it the members it used to have."""
    monkeypatch.setattr(_MODULE, "scan_kind_table", lambda _car: _KIND_TABLE)
    with _template_car(
        tmp_path, "EntityContractName.Object_ru", "EntityContractName.Reference_ru",
    ) as car:
        kinds, unmapped = _MODULE._template_kinds(car)

    assert kinds == {"EntityContractName": "КонтрактСущности"}
    assert unmapped == []


def test_template_kinds_names_a_template_it_cannot_map(tmp_path, monkeypatch):
    """A template that names no kind is REPORTED, not swallowed: it is either a kind of a new
    build or a page describing no kind, and only a human tells the two apart."""
    monkeypatch.setattr(_MODULE, "scan_kind_table", lambda _car: _KIND_TABLE)
    with _template_car(tmp_path, "CatalogName_ru", "SomethingNewName_ru") as car:
        kinds, unmapped = _MODULE._template_kinds(car)

    assert "SomethingNewName" not in kinds
    assert unmapped == ["SomethingNewName"]


def test_template_kinds_exceptions_win_over_the_rule(tmp_path, monkeypatch):
    """The hand-written exceptions: a kind the rule spells differently, and pages that name
    no kind at all (a base of an interface component) - neither is reported as unmapped."""
    monkeypatch.setattr(_MODULE, "scan_kind_table", lambda _car: _KIND_TABLE)
    with _template_car(tmp_path, "ComponentName_ru", "FormName_ru") as car:
        kinds, unmapped = _MODULE._template_kinds(car)

    assert kinds == {"ComponentName": "КомпонентИнтерфейса"}
    assert unmapped == []
