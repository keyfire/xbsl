"""Разбор страниц доков дистрибутива в tools/extract_stdlib.py (component_props).

Инструмент – скрипт вне пакета, поэтому грузится по пути через importlib; сеть и
дистрибутив не нужны – страницы синтетические, по образцу реальной разметки Docusaurus.
"""

import importlib.util
import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _extractor():
    spec = importlib.util.spec_from_file_location("extract_stdlib", _TOOLS / "extract_stdlib.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("extract_stdlib", mod)
    spec.loader.exec_module(mod)
    return mod


_МОДУЛЬ = _extractor()

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
    # члены типа = свойства (H3) и методы (H3) раздельно + унаследованные (ссылки своей секции),
    # без конструкторов и иерархии
    props, methods = _МОДУЛЬ.page_members(_СТРАНИЦА_ТИПА)
    assert props == {"ТекущийПользователь"}
    assert methods == {"Привилегированный", "ВыполнитьСПравами", "ТипЗначения"}
    assert "Объект" not in props | methods  # базовый тип из иерархии – не член


def test_page_members_control_chars_cleaned():
    # в части страниц доков заголовки и имена приходят с управляющими символами внутри слова:
    # без чистки секция не опознаётся, а имя не проходит проверку – члены теряются молча
    props, methods = _МОДУЛЬ.page_members(_СТРАНИЦА_С_МУСОРОМ)
    assert props == {"Позиция"} and methods == {"Закрыть"}


def test_component_page_props_collected():
    got = _МОДУЛЬ.component_props("какой-то/путь/index.html", _СТРАНИЦА_КОМПОНЕНТА)
    assert got is not None
    name, props = got
    assert name == "МойКомпонент"
    # свои свойства – только заголовки H3 (дубль геттер/сеттер схлопнут, ссылки на типы
    # из описаний не попадают), унаследованные – тексты ссылок своей секции
    assert props == {"Заголовок", "Видимость", "Ширина"}


def test_non_component_page_skipped():
    # в базовых типах нет Стд::Интерфейс::Компонент – страница не компонент
    assert _МОДУЛЬ.component_props("какой-то/путь/index.html", _СТРАНИЦА_НЕ_КОМПОНЕНТА) is None


def test_component_base_page_included_by_path():
    # сама страница Компонента (в базовых только Объект) включается по известному пути
    raw = _СТРАНИЦА_НЕ_КОМПОНЕНТА.replace("ПростойТип", "Компонент")
    got = _МОДУЛЬ.component_props(_МОДУЛЬ.COMPONENT_PAGE, raw)
    assert got is not None
    assert got[0] == "Компонент" and got[1] == {"Заголовок"}
