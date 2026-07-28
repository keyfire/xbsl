"""Parsing of the documentation dataset in xbsl/extract/uischema.py (the ui schema).

The pages are synthetic, modeled on the real cleaned docs.sqlite markup (xbsl/extract/docs.py);
no distribution or generated data needed. Vendors in the fixtures are acme/globex.
"""

import json
import sqlite3
import sys
from pathlib import Path

from xbsl.extract import uischema as ux

_STD = "stdlib/element/xbsl/Std/"
_OBJECT_ID = _STD + "Object_ru"
_ENUM_BASE_ID = _STD + "Enum_ru"
_COMPONENT_ID = _STD + "Interface/Component_ru"

_BASES_COMPONENT = (
    '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
    f'<a href="#{_OBJECT_ID}">Объект</a>, '
    f'<a href="#{_COMPONENT_ID}">Стд::Интерфейс::Компонент</a></p> '
)


def _page(doc_id: str, title: str, qualified: str, html: str) -> dict:
    return {"id": doc_id, "title": title, "qualified": qualified, "html": html}


_PAGES = [
    _page(_OBJECT_ID, "Объект", "Стд::Объект", "<h1>Объект</h1> <p>Базовый тип.</p>"),
    _page(
        _ENUM_BASE_ID, "Перечисление", "Стд::Перечисление",
        "<h1>Перечисление</h1> <p>Базовый тип перечислений.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_OBJECT_ID}">Объект</a></p>',
    ),
    # The base component: no constructor (abstract), own property sections including a
    # read-only runtime member and a multi-line event signature.
    _page(
        _COMPONENT_ID, "Компонент", "Стд::Интерфейс::Компонент",
        '<h1>Компонент</h1> <p><code>Стд::Интерфейс::Компонент</code> '
        "<code>Доступность: Клиент</code></p> "
        "<p>Самый базовый тип для всех интерфейсных компонентов. Абстрактный.</p> "
        "<p><strong>Сравнение</strong></p> <p>Ссылочное</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_OBJECT_ID}">Объект</a></p> '
        '<h2 id="свойства">Свойства</h2> '
        '<h3 id="видимость">Видимость</h3> <p><code>Доступность: Клиент</code></p> '
        "<pre><code>Видимость: Авто|Булево</code></pre> "
        "<p>Видимость собственно самого компонента.</p> <hr> "
        '<h3 id="естьнаведение">ЕстьНаведение</h3> '
        "<p><code>Доступность: Клиент</code> <code>ТолькоЧтение</code></p> "
        "<pre><code>ЕстьНаведение: Булево</code></pre> "
        "<p>Принимает значение <code>Истина</code>, когда указатель над компонентом.</p> <hr> "
        '<h3 id="принаведении">ПриНаведении</h3> <p><code>Доступность: Клиент</code></p> '
        "<pre><code>ПриНаведении: (\nКомпонент,\nСобытиеКомпонента)-&gt;ничто</code></pre> "
        "<p>Вызывается при наведении указателя.</p>",
    ),
    # A constructible component: named-params constructor (with a struck-out overload),
    # own property sections with a deleted revision, a since marker and a documented default.
    _page(
        _STD + "Interface/CommonComponents/AcmeCard_ru",
        "КарточкаАкме", "Стд::Интерфейс::ОбщиеКомпоненты::КарточкаАкме",
        '<h1>КарточкаАкме</h1> <p><code>Стд::Интерфейс::ОбщиеКомпоненты::КарточкаАкме</code> '
        "<code>Доступность: Клиент</code></p> "
        "<p>Карточка с предопределенной структурой. Вторая фраза в описание не попадает.</p> "
        + _BASES_COMPONENT +
        '<h2 id="конструкторы">Конструкторы</h2> '
        '<h3 id="карточкаакме-1">КарточкаАкме</h3> '
        "<p><code>Версия 9.0 и выше</code></p> <p><code>Доступность: Клиент</code></p> "
        "<p></p><pre><code>@ИменованныеПараметры\nКарточкаАкме(\n"
        "Видимость: Авто|Булево,\n"
        "ВидОтображения: Авто|ВидОтображенияКарточкиАкме,\n"
        "Важность: Авто|ВажностьКоманды,\n"
        "Граница: Авто|ВидГраницы|Строка,\n"
        "Содержимое: Компонент|Строка,\n"
        "Картинка: Картинка?,\n"
        "Изображение: Url|ДвоичныйОбъект.Ссылка|?,\n"
        "Команды: Команда|ГруппаКомандногоИнтерфейса|?,\n"
        "ПриНажатии: (КарточкаАкме, СобытиеПриНажатии)-&gt;ничто)</code></pre> "
        "Создает компонент.<p></p> <hr> "
        '<h3 id="карточкаакме-2"><del>КарточкаАкме</del></h3> '
        "<p><code>Версия 8.0 и ниже</code></p> "
        "<p></p><pre><code>@ИменованныеПараметры\nКарточкаАкме(\n"
        "Устаревшее: Строка)</code></pre> Конструктор удален.<p></p> "
        '<h2 id="свойства">Свойства</h2> '
        '<h3 id="видотображения">ВидОтображения</h3> <p><code>Доступность: Клиент</code></p> '
        "<pre><code>ВидОтображения: Авто|ВидОтображенияКарточкиАкме</code></pre> "
        "<p>Меняет вид отображения карточки. При <code>Авто</code> выбирается "
        '<a href="#x">Баннер</a></p> <hr> '
        '<h3 id="изображение">Изображение</h3> '
        "<p><code>Версия 9.0 и выше</code></p> <p><code>Доступность: Клиент</code></p> "
        "<pre><code>Изображение: Url|ДвоичныйОбъект.Ссылка|?</code></pre> "
        "<p>Изображение в заголовке карточки.</p> <hr> "
        '<h3 id="изображение-1"><del>Изображение</del></h3> '
        "<p><code>Версия 8.0 и ниже</code></p> "
        "<pre><code>Изображение: ДвоичныйОбъект.Ссылка?</code></pre> "
        "<p>Свойство заменено.</p> <hr> "
        '<h3 id="содержимое">Содержимое</h3> <p><code>Доступность: Клиент</code></p> '
        "<pre><code>Содержимое: Компонент|Строка</code></pre> "
        "<p>Основное содержимое карточки.</p>",
    ),
    # A component referenced as a property type (the slot rule) - constructor without
    # a version marker and without deleted overloads: no since is emitted. Its only slot
    # is Команды, so it must NOT be flagged a container (only Содержимое counts).
    _page(
        _STD + "Interface/CommonComponents/Picture_ru",
        "Картинка", "Стд::Интерфейс::ОбщиеКомпоненты::Картинка",
        "<h1>Картинка</h1> <p>Компонент картинки.</p> "
        + _BASES_COMPONENT +
        '<h2 id="конструкторы">Конструкторы</h2> <h3 id="картинка-1">Картинка</h3> '
        "<p></p><pre><code>@ИменованныеПараметры\nКартинка(\n"
        "Видимость: Авто|Булево,\n"
        "Команды: Команда|?)</code></pre> Создает компонент.<p></p>",
    ),
    # The command-interface package: a class (slot rule) and an enumeration (must stay
    # an enumeration, not a command).
    _page(
        _STD + "Interface/Commands/Command_ru",
        "Команда", "Стд::Интерфейс::Команды::Команда",
        "<h1>Команда</h1> <p>Команда интерфейса.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_OBJECT_ID}">Объект</a></p>',
    ),
    _page(
        _STD + "Interface/Commands/CommandImportance_ru",
        "ВажностьКоманды", "Стд::Интерфейс::Команды::ВажностьКоманды",
        "<h1>ВажностьКоманды</h1> <p>Важность команды.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_OBJECT_ID}">Объект</a>, <a href="#{_ENUM_BASE_ID}">Перечисление</a></p> '
        '<h2 id="элементы">Элементы</h2> <h2 id="свойства">Свойства</h2> '
        '<h3 id="обычная">Обычная</h3> <pre><code>Обычная</code></pre> <p>Обычная.</p> <hr> '
        '<h3 id="важная">Важная</h3> <pre><code>Важная</code></pre> <p>Важная.</p>',
    ),
    # The referenced enumeration: values are the OWN property headings; the service
    # members live in the inherited sections only and must not leak into the values.
    _page(
        _STD + "Interface/CommonComponents/AcmeCardDisplayKind_ru",
        "ВидОтображенияКарточкиАкме",
        "Стд::Интерфейс::ОбщиеКомпоненты::ВидОтображенияКарточкиАкме",
        "<h1>ВидОтображенияКарточкиАкме</h1> <p>Вид отображения карточки.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_OBJECT_ID}">Объект</a>, <a href="#{_ENUM_BASE_ID}">Перечисление</a></p> '
        '<h2 id="элементы">Элементы</h2> <h2 id="свойства">Свойства</h2> '
        '<h3 id="карточка">Карточка</h3> '
        "<p><code>Доступность: КлиентИСервер</code> <code>ТолькоЧтение</code></p> "
        "<pre><code>Карточка</code></pre> <p>Вид карточки.</p> <hr> "
        '<h3 id="баннер">Баннер</h3> '
        "<p><code>Доступность: КлиентИСервер</code> <code>ТолькоЧтение</code></p> "
        "<pre><code>Баннер</code></pre> <p>Вид баннера.</p> "
        '<h2 id="список-унаследованных-методов">Список унаследованных методов</h2> '
        f'<h3 id="объект">Объект</h3> <p><a href="#{_OBJECT_ID}#пт">ПолучитьТип</a></p> '
        f'<h3 id="перечисление">Перечисление</h3> <p><a href="#{_ENUM_BASE_ID}#вс">ВСтроку</a>, '
        f'<a href="#{_ENUM_BASE_ID}#пр">Представление</a></p> '
        '<h2 id="список-унаследованных-свойств">Список унаследованных свойств</h2> '
        f'<h3 id="перечисление-1">Перечисление</h3> <p><a href="#{_ENUM_BASE_ID}#и">Индекс</a></p>',
    ),
    # An enumeration referenced only as ONE MEMBER of a wider union (Авто|ВидГраницы|
    # Строка): prop.enum is not resolved, but the top-level enums map must carry it.
    _page(
        _STD + "Interface/BorderKind_ru",
        "ВидГраницы", "Стд::Интерфейс::ВидГраницы",
        "<h1>ВидГраницы</h1> <p>Вид границы.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_ENUM_BASE_ID}">Перечисление</a></p> '
        '<h2 id="свойства">Свойства</h2> '
        '<h3 id="сплошная">Сплошная</h3> <pre><code>Сплошная</code></pre> <p>Сплошная.</p> <hr> '
        '<h3 id="пунктирная">Пунктирная</h3> <pre><code>Пунктирная</code></pre> <p>Пунктирная.</p>',
    ),
    # An enumeration nothing references: it must stay out of the emitted enums map.
    _page(
        _STD + "Interface/FrameColor_ru",
        "ЦветРамкиВиджета", "Стд::Интерфейс::ЦветРамкиВиджета",
        "<h1>ЦветРамкиВиджета</h1> <p>Цвет рамки.</p> "
        '<h2 id="иерархия-типа">Иерархия типа</h2> <p><em>Базовые типы:</em> '
        f'<a href="#{_ENUM_BASE_ID}">Перечисление</a></p> '
        '<h2 id="свойства">Свойства</h2> '
        '<h3 id="красный">Красный</h3> <pre><code>Красный</code></pre> <p>Красный.</p>',
    ),
    # Same-named components in different packages: the Стд::Интерфейс one wins the bare
    # name and lists the loser under conflicts. Its only-ever constructor carries a
    # version marker - the component since is inferred from it.
    _page(
        _STD + "Interface/Widgets/Widget_ru",
        "Виджет", "Стд::Интерфейс::Виджеты::Виджет",
        "<h1>Виджет</h1> <p>Виджет стандартной поставки.</p> "
        + _BASES_COMPONENT +
        '<h2 id="конструкторы">Конструкторы</h2> <h3 id="виджет-1">Виджет</h3> '
        "<p><code>Версия 9.2 и выше</code></p> "
        "<p></p><pre><code>@ИменованныеПараметры\nВиджет(\n"
        "Видимость: Авто|Булево)</code></pre> Создает компонент.<p></p>",
    ),
    _page(
        "stdlib/element/xbsl/Globex/Widget_ru",
        "Виджет", "Глобекс::Компоненты::Виджет",
        "<h1>Виджет</h1> <p>Виджет поставщика глобекс.</p> "
        + _BASES_COMPONENT +
        '<h2 id="конструкторы">Конструкторы</h2> <h3 id="виджет-1">Виджет</h3> '
        "<p></p><pre><code>@ИменованныеПараметры\nВиджет(\n"
        "Видимость: Авто|Булево)</code></pre> Создает компонент.<p></p>",
    ),
]


#: A guide topic: it describes the INSTANCE description, so its headings are the yaml keys -
#: including the auto-interface flag, which no reference page states, and the structural keys.
_GUIDE_PAGES = [
    {
        "id": "topics/acme-card-component",
        "title": "Компонент интерфейса «КарточкаАкме»",
        "html": (
            "<h1>Компонент интерфейса «КарточкаАкме»</h1> <p>Карточка.</p> "
            '<h2 id="свойства">Свойства</h2> '
            '<h3 id="заголовок">Заголовок</h3> <p>Заголовок карточки.</p> '
            '<h3 id="включатьвавтоинтерфейс">ВключатьВАвтоИнтерфейс</h3> <p>Признак.</p> '
            '<h3 id="тип">Тип</h3> <p>Тип наследуемого компонента.</p> '
            '<h3 id="свойство-разработчика">&lt;Свойство разработчика&gt;</h3> <p>Своё.</p> '
            '<h2 id="события">События</h2> '
            '<h3 id="послесоздания">ПослеСоздания</h3> <p>Переопределяемый обработчик.</p> '
            '<h2 id="см-также">См. также</h2> <h3 id="прочее">Прочее</h3> <p>Не свойство.</p>'
        ),
    },
    {
        "id": "topics/modular-development",
        "title": "Модульная разработка",
        "html": '<h1>Модульная разработка</h1> <h2 id="свойства">Свойства</h2> '
                '<h3 id="импорт">Импорт</h3> <p>Не компонентная страница.</p>',
    },
]


def _schema() -> dict:
    return ux.build_schema(_PAGES, "9.9.9+0", _GUIDE_PAGES)


# --- helper units ------------------------------------------------------------------------


def test_normalize_type_folds_wrapped_signature():
    raw = "( \nКомпонент,\nСобытиеКомпонента )-&gt;  ничто"
    assert ux.normalize_type(raw) == "(Компонент, СобытиеКомпонента)->ничто"


def test_split_union_variants():
    assert ux.split_union("Авто|Булево") == (["Авто", "Булево"], False)
    assert ux.split_union("Картинка?") == (["Картинка"], True)
    assert ux.split_union("Url|ДвоичныйОбъект.Ссылка|?") == (["Url", "ДвоичныйОбъект.Ссылка"], True)
    # "|" inside generic arguments must not split the member
    assert ux.split_union("Массив<РазделФормы|Группа>") == (["Массив<РазделФормы|Группа>"], False)
    assert ux.split_union("ФрагментКомандногоИнтерфейса<Команда>?") == (
        ["ФрагментКомандногоИнтерфейса<Команда>"], True,
    )


def test_parse_ctor_params_single_line_and_arrows():
    # Parameters on one line, a generic component name, an arrow that must not be taken
    # for a closing angle bracket.
    sig = ("@ИменованныеПараметры\nВиджет<ТипДанных>(А: Авто|Число, "
           "Б: Массив<Строка, Число>, В: (Виджет<ТипДанных>, СобытиеКомпонента)->ничто)")
    assert ux.parse_ctor_params(sig) == [
        ("А", "Авто|Число"),
        ("Б", "Массив<Строка, Число>"),
        ("В", "(Виджет<ТипДанных>, СобытиеКомпонента)->ничто"),
    ]


def test_type_refs_skips_type_literals():
    assert ux.type_refs("Массив<РазделФормы|Группа>") == {"Массив", "РазделФормы", "Группа"}
    # Тип<...> is a type literal - it references types, it does not nest components
    assert ux.type_refs("Тип<ПроизвольнаяСтрока<Компонент>>?") == set()
    assert ux.type_refs("ДвоичныйОбъект.Ссылка") == {"ДвоичныйОбъект.Ссылка"}


def test_first_sentence():
    assert ux.first_sentence("Одно. Два.") == "Одно."
    assert ux.first_sentence("Без точки") == "Без точки"


# --- the built schema --------------------------------------------------------------------


def test_component_set_and_meta():
    schema = _schema()
    assert set(schema["components"]) == {"Компонент", "КарточкаАкме", "Картинка", "Виджет"}
    assert schema["meta"]["element_version"] == "9.9.9+0"
    assert schema["meta"]["count"] == 4
    assert schema["meta"]["source"] == "docs"


def test_constructible_component_props():
    card = _schema()["components"]["КарточкаАкме"]
    assert "abstract" not in card
    assert card["package"] == "Стд::Интерфейс::ОбщиеКомпоненты"
    assert card["doc"] == "Карточка с предопределенной структурой."
    props = card["props"]
    # the property list is exactly the current constructor's parameter list
    assert list(props) == [
        "Видимость", "ВидОтображения", "Важность", "Граница", "Содержимое", "Картинка",
        "Изображение", "Команды", "ПриНажатии",
    ]
    assert "Устаревшее" not in props  # the struck-out overload is ignored
    assert "ЕстьНаведение" not in props  # a runtime member is not a constructor parameter


def test_enum_resolution_and_default():
    props = _schema()["components"]["КарточкаАкме"]["props"]
    vid = props["ВидОтображения"]
    assert vid["types"] == ["Авто", "ВидОтображенияКарточкиАкме"]
    assert vid["enum"] == ["Карточка", "Баннер"]
    assert vid["default"] == "Баннер"
    assert vid["doc"] == "Меняет вид отображения карточки."
    # an enumeration from the commands package resolves as an enum, not as a slot
    imp = props["Важность"]
    assert imp["enum"] == ["Обычная", "Важная"]
    assert "slot" not in imp


def test_enum_member_of_wider_union_not_resolved_but_mapped():
    # Авто|ВидГраницы|Строка: two real members - prop.enum stays unresolved (its
    # semantics is "the single-member case"), but the enums map carries the values
    # for the paired Type+Value editor.
    schema = _schema()
    border = schema["components"]["КарточкаАкме"]["props"]["Граница"]
    assert border["types"] == ["Авто", "ВидГраницы", "Строка"]
    assert "enum" not in border
    assert schema["enums"]["ВидГраницы"]["values"] == ["Сплошная", "Пунктирная"]


def test_nullable_and_since():
    props = _schema()["components"]["КарточкаАкме"]["props"]
    img = props["Изображение"]
    assert img["types"] == ["Url", "ДвоичныйОбъект.Ссылка"]
    assert img["nullable"] is True
    assert img["since"] == "9.0"  # from the current section; the deleted revision is skipped
    assert img["doc"] == "Изображение в заголовке карточки."
    pic = props["Картинка"]
    assert pic["types"] == ["Картинка"] and pic["nullable"] is True


def test_slots():
    props = _schema()["components"]["КарточкаАкме"]["props"]
    assert props["Содержимое"]["slot"] is True       # a component in the union
    assert props["Картинка"]["slot"] is True         # a component type reference
    assert props["Команды"]["slot"] is True          # command-interface classes
    assert "slot" not in props["ВидОтображения"]     # an enum union is not a slot
    assert "slot" not in props["Видимость"]


def test_container_flag_only_for_content_slot():
    comps = _schema()["components"]
    assert comps["КарточкаАкме"]["container"] is True  # props carry a slot Содержимое
    # a Команды slot alone does not make a container - only Содержимое counts
    assert comps["Картинка"]["props"]["Команды"]["slot"] is True
    assert "container" not in comps["Картинка"]
    assert "container" not in comps["Виджет"]      # no slots at all
    assert "container" not in comps["Компонент"]   # the abstract base has no Содержимое


def test_event_signature_kept_as_string():
    props = _schema()["components"]["КарточкаАкме"]["props"]
    assert props["ПриНажатии"] == {"event": "(КарточкаАкме, СобытиеПриНажатии)->ничто"}


def test_inherited_doc_resolved_through_hierarchy():
    # Видимость is not documented on the card page - the doc comes from Компонент
    props = _schema()["components"]["КарточкаАкме"]["props"]
    assert props["Видимость"]["doc"] == "Видимость собственно самого компонента."


def test_abstract_component_props_from_sections():
    comp = _schema()["components"]["Компонент"]
    assert comp["abstract"] is True
    props = comp["props"]
    assert props["Видимость"]["types"] == ["Авто", "Булево"]
    assert props["ЕстьНаведение"]["readonly"] is True  # the docs mark it ТолькоЧтение
    # the multi-line handler signature folds into one line
    assert props["ПриНаведении"]["event"] == "(Компонент, СобытиеКомпонента)->ничто"


def test_topic_property_names_only_from_component_topics():
    names = ux.topic_property_names(_GUIDE_PAGES)
    assert set(names) == {"КарточкаАкме"}  # the guide about modular development is not one
    # the headings of the property and event sections; the placeholder headings are dropped
    assert names["КарточкаАкме"] == {
        "Заголовок", "ВключатьВАвтоИнтерфейс", "Тип", "ПослеСоздания",
    }


def test_yaml_props_carry_documented_names_outside_the_typed_set():
    comps = _schema()["components"]
    card = comps["КарточкаАкме"]
    # from the guide topic: neither is a constructor parameter
    assert "ВключатьВАвтоИнтерфейс" in card["yaml_props"]
    assert "ПослеСоздания" in card["yaml_props"]
    # from the inherited property sections: a read-only runtime member is not a ctor parameter
    assert "ЕстьНаведение" in card["yaml_props"]
    # a typed property is never repeated here
    assert "ВидОтображения" not in card["yaml_props"]
    assert card["yaml_props"] == sorted(card["yaml_props"])
    # a component without a guide topic gets the documented names of the hierarchy only
    assert "ВключатьВАвтоИнтерфейс" not in comps["Виджет"]["yaml_props"]
    assert "ЕстьНаведение" in comps["Виджет"]["yaml_props"]


def test_schema_without_guides_has_no_yaml_props_from_topics():
    comps = ux.build_schema(_PAGES, "9.9.9+0")["components"]
    assert "ВключатьВАвтоИнтерфейс" not in (comps["КарточкаАкме"].get("yaml_props") or [])


def test_component_since_only_without_deleted_overloads():
    comps = _schema()["components"]
    # КарточкаАкме has a struck-out overload - it predates the current constructor
    assert "since" not in comps["КарточкаАкме"]
    assert comps["Виджет"]["since"] == "9.2"  # the only-ever constructor carries the marker
    assert "since" not in comps["Картинка"]   # no marker at all


def test_namesake_components_winner_and_conflicts():
    widget = _schema()["components"]["Виджет"]
    assert widget["package"] == "Стд::Интерфейс::Виджеты"
    assert widget["conflicts"] == ["Глобекс::Компоненты::Виджет"]


def test_enums_map_only_referenced():
    # Every enumeration referenced by ANY union member is in (ВидГраницы comes from a
    # multi-member union); the unreferenced ЦветРамкиВиджета stays out.
    enums = _schema()["enums"]
    assert set(enums) == {"ВидОтображенияКарточкиАкме", "ВажностьКоманды", "ВидГраницы"}
    assert enums["ВидОтображенияКарточкиАкме"] == {
        "package": "Стд::Интерфейс::ОбщиеКомпоненты",
        "values": ["Карточка", "Баннер"],  # page order, no service members
    }


# --- type parameters and their defaults --------------------------------------------------

_FRAGMENT_ID = _STD + "Interface/Commands/CommandInterfaceFragmentAcme_ru"
_FRAGMENT_PAGE = _page(
    _FRAGMENT_ID, "ФрагментАкме", "Стд::Интерфейс::Команды::ФрагментАкме&lt;ТипКоманды&gt;",
    "<h1>ФрагментАкме</h1> <p><code>Стд::Интерфейс::Команды::ФрагментАкме&lt;ТипКоманды&gt;"
    "</code> <code>Доступность: Клиент</code></p> "
    '<p>ТипКоманды: тип команды фрагмента. По умолчанию <a href="#x">КомандаАкме</a>. '
    "Ограничения параметра типа: Стд::Интерфейс::Команды::КомандаАкме.</p> "
    "<p>Фрагмент командного интерфейса.</p>",
)


def test_declared_type_params():
    assert ux.declared_type_params("Стд::Формы::ФормаАкме<ТипОбъекта,ТипРезультата>") == [
        "ТипОбъекта", "ТипРезультата",
    ]
    assert ux.declared_type_params("Стд::Интерфейс::Кнопка") == []


def test_param_defaults_are_cut_by_parameter_names():
    """One paragraph describes every parameter, so a default belongs to its own sentence."""
    head = (
        "<p>ТипЗаписи: тип записи. Ограничения параметра типа: Стд::Запись. "
        "ТипРезультата: тип результата. По умолчанию Неопределено.</p>"
    )
    assert ux.param_defaults(head, ["ТипЗаписи", "ТипРезультата"]) == {
        "ТипРезультата": "Неопределено",  # ТипЗаписи has none, and does not borrow this one
    }


def test_param_default_written_with_a_dash():
    head = "<p>ТипРезультата: тип результата. По умолчанию - Неопределено. Далее текст.</p>"
    assert ux.param_defaults(head, ["ТипРезультата"]) == {"ТипРезультата": "Неопределено"}


def test_type_params_section_of_the_schema():
    schema = ux.build_schema(_PAGES + [_FRAGMENT_PAGE], "9.9.9+0")
    assert schema["type_params"]["ФрагментАкме"] == {
        "params": ["ТипКоманды"], "defaults": {"ТипКоманды": "КомандаАкме"},
    }
    assert "Кнопка" not in schema["type_params"]  # a type with no parameters is not listed


# --- end to end through docs.sqlite ------------------------------------------------------


def test_end_to_end_writes_next_to_docs(tmp_path, monkeypatch):
    ver = "9.9.9+0"
    ver_dir = tmp_path / ver
    ver_dir.mkdir()
    con = sqlite3.connect(ver_dir / "docs.sqlite")
    con.execute(
        "CREATE TABLE pages (id TEXT PRIMARY KEY, kind TEXT, title TEXT, qualified TEXT,"
        " availability TEXT, url TEXT, html TEXT)"
    )
    for p in _PAGES:
        con.execute(
            "INSERT INTO pages VALUES(?, 'type', ?, ?, '', '', ?)",
            (p["id"], p["title"], p["qualified"], p["html"]),
        )
    for p in _GUIDE_PAGES:  # the guides are read through docs.guide_pages (kind <> 'type')
        con.execute(
            "INSERT INTO pages VALUES(?, 'member', ?, '', '', '', ?)",
            (p["id"], p["title"], p["html"]),
        )
    con.commit()
    con.close()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": [ver], "default": ver}), encoding="utf-8"
    )
    monkeypatch.setattr(sys, "argv", ["extract_uischema", "--data-dir", str(tmp_path)])
    try:
        assert ux.main() == 0
    finally:
        ux.dataset.set_data_root(None)
        ux._distro.set_data_root(None)
    data = json.loads((ver_dir / "uischema.json").read_text(encoding="utf-8"))
    assert data["meta"]["element_version"] == ver
    assert "КарточкаАкме" in data["components"]
    assert data["components"]["Компонент"]["abstract"] is True
    # the guide topic of the card reached the schema through docs.guide_pages
    assert "ВключатьВАвтоИнтерфейс" in data["components"]["КарточкаАкме"]["yaml_props"]
