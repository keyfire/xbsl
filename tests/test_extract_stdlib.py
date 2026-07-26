"""Parsing of distribution docs pages in xbsl/extract/stdlib.py (component_props).

No network or distribution needed - the pages are synthetic, modeled on the real
Docusaurus markup.
"""

from xbsl.extract import stdlib as _МОДУЛЬ

_СТРАНИЦА_КОМПОНЕНТА = (
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

_СТРАНИЦА_НЕ_КОМПОНЕНТА = (
    "<html><head><title>ПростойТип | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>ПростойТип</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Свойства​</h2><h3>Заголовок​</h3>"
    "</article></body></html>"
)


_СТРАНИЦА_ТИПА = (
    "<html><head><title>КонтекстДоступа | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>КонтекстДоступа</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Свойства​</h2><h3>ТекущийПользователь​</h3>"
    "<h2>Методы​</h2><h3>Привилегированный​</h3><h3>ВыполнитьСПравами​</h3>"
    "<h2>Список унаследованных методов​</h2>"
    "<p><a href='/Object_ru/#tzn'>ТипЗначения</a></p>"
    "</article></body></html>"
)


_СТРАНИЦА_С_МУСОРОМ = (
    "<html><head><title>ПотокЧтения | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>ПотокЧтения</h1>"
    "<h2>Св\x00ойства​</h2><h3>Позиц\x00ия​</h3>"
    "<h2>Список унаследованных \x00методов​</h2>"
    "<p><a href='/Object_ru/#zakryt'>Закр\x00ыть</a></p>"
    "</article></body></html>"
)


def test_page_members_props_and_methods():
    # type members = properties (H3) and methods (H3) separately + inherited ones (links of their
    # own section), without constructors and the hierarchy
    props, methods = _МОДУЛЬ.page_members(_СТРАНИЦА_ТИПА)
    assert props == {"ТекущийПользователь"}
    assert methods == {"Привилегированный", "ВыполнитьСПравами", "ТипЗначения"}
    assert "Объект" not in props | methods  # a base type from the hierarchy is not a member


def test_page_members_control_chars_cleaned():
    # on some docs pages headings and names arrive with control characters inside the word:
    # without cleaning, the section is not recognized and the name fails validation - members
    # get lost silently
    props, methods = _МОДУЛЬ.page_members(_СТРАНИЦА_С_МУСОРОМ)
    assert props == {"Позиция"} and methods == {"Закрыть"}


def test_component_page_props_collected():
    got = _МОДУЛЬ.component_props("какой-то/путь/index.html", _СТРАНИЦА_КОМПОНЕНТА)
    assert got is not None
    name, props = got
    assert name == "МойКомпонент"
    # own properties - only H3 headings (the getter/setter duplicate is collapsed, type links
    # from descriptions do not get in), inherited ones - link texts of their own section
    assert props == {"Заголовок", "Видимость", "Ширина"}


def test_non_component_page_skipped():
    # the base types do not include Стд::Интерфейс::Компонент - the page is not a component
    assert _МОДУЛЬ.component_props("какой-то/путь/index.html", _СТРАНИЦА_НЕ_КОМПОНЕНТА) is None


def test_component_base_page_included_by_path():
    # the Компонент page itself (only Объект among its base types) is included by its known path
    raw = _СТРАНИЦА_НЕ_КОМПОНЕНТА.replace("ПростойТип", "Компонент")
    got = _МОДУЛЬ.component_props(_МОДУЛЬ.COMPONENT_PAGE, raw)
    assert got is not None
    assert got[0] == "Компонент" and got[1] == {"Заголовок"}


_СТРАНИЦА_ДЖЕНЕРИКОВ = (
    "<html><head><title>СпискиНастроек | 1С:Предприятие.Элемент</title></head><body>"
    "<article><h1>СпискиНастроек</h1>"
    "<h2>Иерархия типа​</h2><p>Базовые типы: <a href='/Object_ru/'>Объект</a></p>"
    "<h2>Методы​</h2>"
    "<h3>ПолучитьМножество​</h3>"
    # The real page markup: type names wrapped in links, generic brackets as entities.
    '<pre class="highlight"><code>ПолучитьМножество(): '
    '<a href="/ReadableSet_ru/">ЧитаемоеМножество</a>&lt;'
    '<a href="/Settings_ru/">НастройкиСервиса</a>&gt;</code></pre>'
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
    got = _МОДУЛЬ.page_member_types(_СТРАНИЦА_ДЖЕНЕРИКОВ)
    # The full docs spelling survives (entities unescaped, link tags stripped)...
    assert got["ПолучитьМножество"] == "ЧитаемоеМножество<НастройкиСервиса>"
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
        z.writestr(_МОДУЛЬ.STD_BASE + "AccessContext_ru/index.html", _СТРАНИЦА_ТИПА)
    names = _МОДУЛЬ.extract(tmp_path)[0]
    assert _МОДУЛЬ.TOPIC_ONLY_TYPES <= names
    assert "КонтекстДоступа" in names  # the ordinary page walk is intact
