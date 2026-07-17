"""Правила группы naming/: имена элементов проекта по стандарту 1С:Элемент.

Правила читают yaml-описание, поэтому данные Элемента нужны только правилу naming/presentation –
оно спрашивает у метамодели, есть ли у вида свойство Представление; такие тесты помечены
needs_data. Число имени (naming/number и ветка "существительное" правила naming/boolean-name)
считает морфология: тесты берут её через фикстуру morph и без pymorphy3 пропускаются. Остальные
тесты проходят в чистом чекауте – ни данных, ни морфологии им не нужно.
"""

import pytest

from xbsl import engine
from xbsl.rules import naming

_YO = "naming/yo"
_UNDERSCORE = "naming/underscore"
_ABBREV = "naming/abbreviation"
_LATIN = "naming/latin-term"
_ENUM_VID = "naming/enum-vid"
_KIND = "naming/kind-in-name"
_FILLER = "naming/filler-word"
_MODULE = "naming/module-suffix"
_NUMBER = "naming/number"
_BOOLEAN = "naming/boolean-name"
_PRESENTATION = "naming/presentation"
_PREFIX = "naming/prefix-by-kind"

_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def morph():
    """Морфология (pymorphy3): без неё правила числа и существительного молчат."""
    pytest.importorskip("pymorphy3")
    if naming._morph() is None:  # pragma: no cover – анализатор не поднялся
        pytest.skip("pymorphy3 недоступен")


def _yaml(vid, name, tail=""):
    """Минимальное описание объекта: вид, Ид, Имя и хвост (Представление, секции)."""
    return f"ВидЭлемента: {vid}\nИд: {_ID}\nИмя: {name}\n{tail}"


def _section(section, *items):
    """Секция описания из пар (Имя, Тип); пустой Тип не выводится (у табличных частей его нет)."""
    out = f"{section}:\n"
    for i, (name, kind) in enumerate(items, start=1):
        out += "    -\n"
        out += f"        Ид: 22222222-3333-4444-5555-{i:012d}\n"
        out += f"        Имя: {name}\n"
        if kind:
            out += f"        Тип: {kind}\n"
    return out


def _lint(rule_id, vid, name, tail=""):
    """Диагностики одного правила по описанию объекта в памяти."""
    source = engine.load_text(f"{name}.yaml", _yaml(vid, name, tail))
    return engine.run_sources([source], select={rule_id})


# --- 1.2 буква "ё" ----------------------------------------------------------------------

def test_yo_in_object_name():
    d = _lint(_YO, "Справочник", "ПересчётТоваров")
    assert len(d) == 1
    assert d[0].rule_id == _YO
    assert d[0].line == 3  # строка Имя
    assert "ПересчетТоваров" in d[0].message  # подсказка – то же имя через "е"


def test_yo_in_attribute_name():
    # Имена реквизитов проверяются наравне с именем объекта, диагностика встаёт на их строку.
    d = _lint(_YO, "Справочник", "Товары", _section("Реквизиты", ("Объём", "Число")))
    assert len(d) == 1
    assert d[0].line == 7


def test_yo_clean_name_silent():
    assert _lint(_YO, "Справочник", "ПересчетТоваров") == []


# --- 1.2 подчёркивание ------------------------------------------------------------------

def test_underscore_as_separator():
    d = _lint(_UNDERSCORE, "ОбщийМодуль", "Разбор_Ответа")
    assert len(d) == 1
    assert d[0].rule_id == _UNDERSCORE


@pytest.mark.parametrize("name", ["ФизическоеЛицо_v2", "ФизическиеЛицаApi_3_1"])
def test_underscore_version_tail_allowed(name):
    # Версионный хвост – единственное, ради чего стандарт разрешает подчёркивание.
    assert _lint(_UNDERSCORE, "Справочник", name) == []


def test_underscore_clean_name_silent():
    assert _lint(_UNDERSCORE, "Справочник", "ФизическиеЛица") == []


# --- 1.3 аббревиатура одним словом ------------------------------------------------------

@pytest.mark.parametrize(("name", "suggestion"), [
    ("ЗапросыКМССервер", "ЗапросыКмсСервер"),  # последняя заглавная – начало слова "Сервер"
    ("СуммаНДС", "СуммаНдс"),
])
def test_abbreviation_caps(name, suggestion):
    d = _lint(_ABBREV, "ОбщийМодуль", name)
    assert len(d) == 1
    assert d[0].rule_id == _ABBREV
    assert suggestion in d[0].message


@pytest.mark.parametrize("name", [
    "ДоступКПриложениям", "КнопкаЗаписатьИЗакрыть", "ОбращенияВПоддержку",
])
def test_abbreviation_ignores_prepositions(name):
    # Одиночная заглавная перед словом – предлог или союз, а не аббревиатура.
    assert _lint(_ABBREV, "Справочник", name) == []


def test_abbreviation_clean_name_silent():
    assert _lint(_ABBREV, "ОбщийМодуль", "ЗапросыКмсСервер") == []


def test_abbreviation_leaves_latin_terms_to_its_rule():
    # АПИ – англоязычный термин: его ведёт naming/latin-term, здесь двойной диагностики нет.
    assert _lint(_ABBREV, "ОбщийМодуль", "АПИСервиса") == []


# --- 1.4 англоязычный термин оригиналом -------------------------------------------------

@pytest.mark.parametrize(("name", "word", "suggestion"), [
    ("АпиСервиса", "Апи", "ApiСервиса"),
    ("АПИСервиса", "АПИ", "ApiСервиса"),  # тот же термин, записанный заглавными
    ("РазборУрл", "Урл", "РазборUrl"),
])
def test_latin_term(name, word, suggestion):
    d = _lint(_LATIN, "ОбщийМодуль", name)
    assert len(d) == 1
    assert d[0].rule_id == _LATIN
    assert word in d[0].message
    assert suggestion in d[0].message


@pytest.mark.parametrize("name", ["Токены", "ЛогинПользователя"])
def test_latin_term_keeps_borrowed_words(name):
    # Токен и логин вошли в русский язык – стандарт их не запрещает.
    assert _lint(_LATIN, "Справочник", name) == []


def test_latin_term_original_spelling_silent():
    assert _lint(_LATIN, "ОбщийМодуль", "РазборUrl") == []


# --- 1.5 перечисление именуется словом "Вид" --------------------------------------------

@pytest.mark.parametrize(("name", "suggestion"), [
    ("ТипыСтатей", "ВидыСтатей"),
    ("ТипСтатьи", "ВидСтатьи"),
])
def test_enum_vid_bad_prefix(name, suggestion):
    d = _lint(_ENUM_VID, "Перечисление", name)
    assert len(d) == 1
    assert d[0].rule_id == _ENUM_VID
    assert suggestion in d[0].message


def test_enum_vid_correct_name_silent():
    assert _lint(_ENUM_VID, "Перечисление", "ВидыСтатей") == []


def test_enum_vid_word_beginning_with_tip_silent():
    # "Типизация" – слово целиком, а не приставленный к имени "Тип".
    assert _lint(_ENUM_VID, "Перечисление", "Типизация") == []


def test_enum_vid_only_for_enumerations():
    assert _lint(_ENUM_VID, "Справочник", "ТипыСтатей") == []


# --- 1.8 вид элемента в имени -----------------------------------------------------------

def test_kind_in_name_report():
    d = _lint(_KIND, "Отчет", "ОтчетЗависшиеЗадачи")
    assert len(d) == 1
    assert d[0].rule_id == _KIND
    assert "ЗависшиеЗадачи" in d[0].message


def test_kind_in_name_clean_silent():
    assert _lint(_KIND, "Отчет", "ЗависшиеЗадачи") == []


def test_kind_in_name_skips_interface_component():
    # Компоненту интерфейса стандарт разрешает префикс-уточнение типа – правило его не проверяет.
    assert _lint(_KIND, "КомпонентИнтерфейса", "ПолеВводаАдреса") == []


def test_kind_in_name_virtual_table_prefix():
    d = _lint(_KIND, "ВиртуальнаяТаблица", "ВТ_Остатки")
    assert len(d) == 1
    assert "Остатки" in d[0].message


def test_kind_in_name_virtual_table_clean_silent():
    assert _lint(_KIND, "ВиртуальнаяТаблица", "Остатки") == []


# --- 1.8 слово-пустышка -----------------------------------------------------------------

def test_filler_word_report():
    d = _lint(_FILLER, "ОбщийМодуль", "УправлениеЦветами")
    assert len(d) == 1
    assert d[0].rule_id == _FILLER
    assert "Управление" in d[0].message


def test_filler_word_clean_silent():
    assert _lint(_FILLER, "ОбщийМодуль", "Цвета") == []


def test_filler_word_needs_a_word_boundary():
    # 'РаботаСЦветами' - это "работа с цветами" (пустышка), а 'РаботаСотрудника' -
    # "работа сотрудника": те же буквы, другое слово (проверка на боевом корпусе БизКуба)
    assert len(_lint(_FILLER, "ОбщийМодуль", "РаботаСJson")) == 1
    assert _lint(_FILLER, "Структура", "РаботаСотрудника") == []


def test_filler_word_inside_a_compound_term_is_silent():
    # стандарт говорит о ПРЕФИКСАХ и постфиксах; внутри составного термина
    # ('контент-менеджер' - должность) слово пустышкой не является
    assert _lint(_FILLER, "КомпонентИнтерфейса", "ПанельКонтентМенеджера") == []
    # а постфиксом - является
    assert len(_lint(_FILLER, "ОбщийМодуль", "ОбменДаннымиМеханизм")) == 1


# --- постфикс окружения у общего модуля -------------------------------------------------

@pytest.mark.parametrize(("name", "suggestion"), [
    ("ОбщееКлиент", "Общее"),
    ("ОбменДаннымиКлиентИСервер", "ОбменДанными"),
])
def test_module_suffix_report(name, suggestion):
    d = _lint(_MODULE, "ОбщийМодуль", name)
    assert len(d) == 1
    assert d[0].rule_id == _MODULE
    assert suggestion in d[0].message


def test_module_suffix_clean_silent():
    assert _lint(_MODULE, "ОбщийМодуль", "ОбменДанными") == []


def test_module_suffix_only_for_common_modules():
    # Постфикс окружения ищется только у общих модулей: у справочника это часть имени.
    assert _lint(_MODULE, "Справочник", "ОбщееКлиент") == []


# --- число имени по виду элемента (нужна морфология) ------------------------------------

def test_number_catalog_must_be_plural(morph):
    d = _lint(_NUMBER, "Справочник", "Акция")
    assert len(d) == 1
    assert d[0].rule_id == _NUMBER
    assert "справочник" in d[0].message


def test_number_catalog_plural_silent(morph):
    assert _lint(_NUMBER, "Справочник", "Акции") == []


def test_number_exempt_heads_silent(morph):
    # стандарт сам оговаривает исключения: у этих терминов числа не выбирают - изменение числа
    # исказило бы смысл (справочник Номенклатура, регистр ОчередьСообщений, структура ДанныеЗадачи)
    assert _lint(_NUMBER, "Справочник", "Номенклатура") == []
    assert _lint(_NUMBER, "РегистрСведений", "ОчередьСообщений") == []
    assert _lint(_NUMBER, "Структура", "ДанныеЗадачи") == []
    assert _lint(_NUMBER, "Структура", "СведенияОСотруднике") == []


def test_number_enumeration_must_be_singular(morph):
    d = _lint(_NUMBER, "Перечисление", "ВидыСтатей")
    assert len(d) == 1
    assert "перечисление" in d[0].message


def test_number_enumeration_singular_silent(morph):
    assert _lint(_NUMBER, "Перечисление", "ВидСтатьи") == []


def test_number_tabular_section_must_be_plural(morph):
    # Табличная часть – во множественном; вторая ТЧ названа верно и молчит.
    tail = _section("ТабличныеЧасти", ("Цена", ""), ("Скидки", ""))
    d = _lint(_NUMBER, "Справочник", "Товары", tail)
    assert len(d) == 1
    assert "табличная часть" in d[0].message
    assert d[0].line == 7  # строка имени первой табличной части


def test_number_silent_without_morphology(monkeypatch):
    # Без pymorphy3 правило молчит: гадать число по окончаниям нельзя.
    monkeypatch.setattr(naming, "_morph", lambda: None)
    assert _lint(_NUMBER, "Справочник", "Акция") == []


# --- 1.9 имя булева реквизита -----------------------------------------------------------

def test_boolean_negation():
    # Отрицание ловится без морфологии – по приставкам Не/Нет.
    tail = _section("Реквизиты", ("НетОшибок", "Булево"))
    d = _lint(_BOOLEAN, "Справочник", "Загрузки", tail)
    assert len(d) == 1
    assert d[0].rule_id == _BOOLEAN
    assert "отрицание" in d[0].message


def test_boolean_noun(morph):
    tail = _section("Реквизиты", ("Администратор", "Булево"))
    d = _lint(_BOOLEAN, "Справочник", "Пользователи", tail)
    assert len(d) == 1
    assert "ЭтоАдминистратор" in d[0].message  # подсказка – имя с приставкой


def test_boolean_prefixed_name_silent(morph):
    tail = _section("Реквизиты", ("ЭтоАдминистратор", "Булево"))
    assert _lint(_BOOLEAN, "Справочник", "Пользователи", tail) == []


def test_boolean_only_boolean_attributes(morph):
    # То же имя-существительное, но реквизит не булев – правило его не касается.
    tail = _section("Реквизиты", ("Администратор", "Строка"))
    assert _lint(_BOOLEAN, "Справочник", "Пользователи", tail) == []


# --- 2.1 представление элемента (нужна метамодель) --------------------------------------

@pytest.mark.needs_data
def test_presentation_missing():
    d = _lint(_PRESENTATION, "Справочник", "Акции")
    assert len(d) == 1
    assert d[0].rule_id == _PRESENTATION
    assert "Представление" in d[0].message


@pytest.mark.needs_data
def test_presentation_filled_silent():
    assert _lint(_PRESENTATION, "Справочник", "Акции", "Представление: Акции\n") == []


@pytest.mark.needs_data
def test_presentation_deprecated_not_marked():
    d = _lint(_PRESENTATION, "Справочник", "УстарелоАкции", "Представление: Акции\n")
    assert len(d) == 1
    assert "не используется" in d[0].message


@pytest.mark.needs_data
def test_presentation_deprecated_marked_silent():
    tail = "Представление: (не используется) Акции\n"
    assert _lint(_PRESENTATION, "Справочник", "УстарелоАкции", tail) == []


@pytest.mark.needs_data
def test_presentation_skips_kind_without_property():
    # У общего модуля свойства Представление нет – требовать нечего.
    assert _lint(_PRESENTATION, "ОбщийМодуль", "Общее") == []


# --- обязательные префиксы и постфиксы по видам -----------------------------------------

@pytest.mark.parametrize("name", ["ApiСайта", "WebСайт"])
def test_http_service_forbidden_word(name):
    d = _lint(_PREFIX, "HttpСервис", name)
    assert len(d) == 1
    assert d[0].rule_id == _PREFIX


def test_http_service_clean_name_silent():
    assert _lint(_PREFIX, "HttpСервис", "Сайт") == []


def test_prefix_by_kind_missing_prefix():
    d = _lint(_PREFIX, "КлючДоступа", "Партнеры")
    assert len(d) == 1
    assert "КлючДоступа" in d[0].message


def test_prefix_by_kind_present_silent():
    assert _lint(_PREFIX, "КлючДоступа", "КлючДоступаПартнера") == []


def test_suffix_by_kind_missing_suffix():
    d = _lint(_PREFIX, "ЛокализованныеСтроки", "Сайт")
    assert len(d) == 1
    assert "Локализация" in d[0].message


def test_suffix_by_kind_present_silent():
    assert _lint(_PREFIX, "ЛокализованныеСтроки", "СайтЛокализация") == []


# --- хвостовой комментарий и кавычки в строке Имя ----------------------------------------

def test_trailing_comment_not_part_of_name():
    # По YAML комментарий после значения не является его частью: раньше такая строка вовсе
    # не совпадала с регексом имён, и вся группа naming/ молчала об этом имени.
    d = _lint(_YO, "Справочник", "ПересчётТоваров # комментарий")
    assert len(d) == 1
    assert "ПересчётТоваров" in d[0].message  # имя без хвоста


def test_trailing_comment_in_section_name():
    d = _lint(_YO, "Справочник", "Товары", _section("Реквизиты", ("Объём # комментарий", "Число")))
    assert len(d) == 1
    assert d[0].line == 7
    assert "Объём" in d[0].message


def test_trailing_comment_number(morph):
    # Репро исходного ложного минуса: имя регистра в единственном числе + комментарий.
    d = _lint(_NUMBER, "РегистрСведений", "КешТокенов # закэшированные токены")
    assert len(d) == 1
    assert "КешТокенов" in d[0].message


def test_quoted_name_with_comment():
    source = engine.load_text(
        "Товары.yaml",
        f'ВидЭлемента: Справочник\nИд: {_ID}\nИмя: "ПересчётТоваров" # комментарий\n',
    )
    d = engine.run_sources([source], select={_YO})
    assert len(d) == 1
    assert "ПересчётТоваров" in d[0].message  # без кавычек и без хвоста


def test_comment_only_value_is_no_name():
    source = engine.load_text(
        "Товары.yaml", f"ВидЭлемента: Справочник\nИд: {_ID}\nИмя: # имени нет\n",
    )
    assert engine.run_sources([source], select={_YO}) == []


# --- группа целиком ---------------------------------------------------------------------

def test_structural_yaml_skipped():
    # Файл без ВидЭлемента (Проект, Подсистема) не описывает элемент – имена в нём не проверяются,
    # хотя "Управление_Сайтом" нарушило бы и naming/underscore, и naming/filler-word.
    source = engine.load_text("Подсистема.yaml", "Имя: Управление_Сайтом\nСодержимое:\n    - Акции\n")
    assert engine.run_sources([source], select={"naming"}) == []


@pytest.mark.needs_data
def test_correct_object_passes_whole_group(morph):
    tail = (
        "Представление: Акции\n"
        + _section("Реквизиты", ("ЭтоАрхивная", "Булево"), ("Заголовок", "Строка"))
        + _section("ТабличныеЧасти", ("Условия", ""))
    )
    source = engine.load_text("Акции.yaml", _yaml("Справочник", "Акции", tail))
    assert engine.run_sources([source], select={"naming"}) == []
