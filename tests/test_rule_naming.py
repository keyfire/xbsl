"""The naming/ rule group: project element names per the 1C:Element standard.

The rules read the yaml description, so the Element data is needed only by naming/presentation -
it asks the metamodel whether the kind has the Представление property; such tests are marked
needs_data. The grammatical number of a name (naming/number and the "noun" branch of
naming/boolean-name) is computed by morphology: the tests take it via the morph fixture and are
skipped without pymorphy3. The remaining tests pass in a clean checkout - they need neither the
data nor the morphology.
"""

import pytest

from xbsl import engine, i18n
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
    """Morphology (pymorphy3): without it the number and noun rules stay silent."""
    pytest.importorskip("pymorphy3")
    if naming._morph() is None:  # pragma: no cover - the analyzer did not come up
        pytest.skip("pymorphy3 недоступен")


def _yaml(vid, name, tail=""):
    """A minimal object description: the kind, Ид, Имя and a tail (Представление, sections)."""
    return f"ВидЭлемента: {vid}\nИд: {_ID}\nИмя: {name}\n{tail}"


def _section(section, *items):
    """A description section of (Имя, Тип) pairs; an empty Тип is omitted (tabular sections have none)."""
    out = f"{section}:\n"
    for i, (name, kind) in enumerate(items, start=1):
        out += "    -\n"
        out += f"        Ид: 22222222-3333-4444-5555-{i:012d}\n"
        out += f"        Имя: {name}\n"
        if kind:
            out += f"        Тип: {kind}\n"
    return out


def _lint(rule_id, vid, name, tail=""):
    """Diagnostics of a single rule over an in-memory object description."""
    source = engine.load_text(f"{name}.yaml", _yaml(vid, name, tail))
    return engine.run_sources([source], select={rule_id})


# --- 1.2 the letter "ё" ----------------------------------------------------------------------

def test_yo_in_object_name():
    d = _lint(_YO, "Справочник", "ПересчётТоваров")
    assert len(d) == 1
    assert d[0].rule_id == _YO
    assert d[0].line == 3  # the Имя line
    assert "ПересчетТоваров" in d[0].message  # the suggestion is the same name spelled with "е"


def test_yo_in_attribute_name():
    # Attribute names are checked on par with the object name, the diagnostic lands on their line.
    d = _lint(_YO, "Справочник", "Товары", _section("Реквизиты", ("Объём", "Число")))
    assert len(d) == 1
    assert d[0].line == 7


def test_yo_clean_name_silent():
    assert _lint(_YO, "Справочник", "ПересчетТоваров") == []


# --- 1.2 underscore ------------------------------------------------------------------

def test_underscore_as_separator():
    d = _lint(_UNDERSCORE, "ОбщийМодуль", "Разбор_Ответа")
    assert len(d) == 1
    assert d[0].rule_id == _UNDERSCORE


@pytest.mark.parametrize("name", ["ФизическоеЛицо_v2", "ФизическиеЛицаApi_3_1"])
def test_underscore_version_tail_allowed(name):
    # A version tail is the only thing the standard allows the underscore for.
    assert _lint(_UNDERSCORE, "Справочник", name) == []


def test_underscore_clean_name_silent():
    assert _lint(_UNDERSCORE, "Справочник", "ФизическиеЛица") == []


# --- 1.3 an abbreviation as one word ------------------------------------------------------

@pytest.mark.parametrize(("name", "suggestion"), [
    ("ЗапросыКМССервер", "ЗапросыКмсСервер"),  # the last capital letter starts the word "Сервер"
    ("СуммаНДС", "СуммаНдс"),
])
def test_abbreviation_caps(name, suggestion):
    d = _lint(_ABBREV, "ОбщийМодуль", name)
    assert len(d) == 1
    assert d[0].rule_id == _ABBREV
    assert suggestion in d[0].message


@pytest.mark.parametrize("name", [
    "ДоступКПриложениям", "КнопкаЗаписатьИЗакрыть", "ЗаметкиВАрхиве",
])
def test_abbreviation_ignores_prepositions(name):
    # A single capital before a word is a preposition or a conjunction, not an abbreviation.
    assert _lint(_ABBREV, "Справочник", name) == []


def test_abbreviation_clean_name_silent():
    assert _lint(_ABBREV, "ОбщийМодуль", "ЗапросыКмсСервер") == []


def test_abbreviation_leaves_latin_terms_to_its_rule():
    # АПИ is an English term: naming/latin-term owns it, no double diagnostic here.
    assert _lint(_ABBREV, "ОбщийМодуль", "АПИОбмена") == []


# --- 1.4 an English term in its original spelling -------------------------------------------------

@pytest.mark.parametrize(("name", "word", "suggestion"), [
    ("АпиОбмена", "Апи", "ApiОбмена"),
    ("АПИОбмена", "АПИ", "ApiОбмена"),  # the same term written in capitals
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
    # Токен and логин have entered the Russian language - the standard does not forbid them.
    assert _lint(_LATIN, "Справочник", name) == []


def test_latin_term_original_spelling_silent():
    assert _lint(_LATIN, "ОбщийМодуль", "РазборUrl") == []


# --- 1.5 an enumeration is named with the word "Вид" --------------------------------------------

@pytest.mark.parametrize(("name", "suggestion"), [
    ("ТипыОплат", "ВидыОплат"),
    ("ТипОплаты", "ВидОплаты"),
])
def test_enum_vid_bad_prefix(name, suggestion):
    d = _lint(_ENUM_VID, "Перечисление", name)
    assert len(d) == 1
    assert d[0].rule_id == _ENUM_VID
    assert suggestion in d[0].message


def test_enum_vid_correct_name_silent():
    assert _lint(_ENUM_VID, "Перечисление", "ВидыОплат") == []


def test_enum_vid_word_beginning_with_tip_silent():
    # "Типизация" is a whole word, not a "Тип" prepended to the name.
    assert _lint(_ENUM_VID, "Перечисление", "Типизация") == []


def test_enum_vid_only_for_enumerations():
    assert _lint(_ENUM_VID, "Справочник", "ТипыОплат") == []


def _lint_english(rule_id, kind, name):
    """The same, over a description written in English - the platform reads it either way."""
    source = engine.load_text(
        f"{name}.yaml", f"ElementKind: {kind}\nId: {_ID}\nName: {name}\n",
    )
    return engine.run_sources([source], select={rule_id})


@pytest.mark.needs_data
def test_enum_vid_english_name_judged_by_its_tail():
    """An English name carries the kind word as a SUFFIX - the head of a compound is last.

    Judged by the Russian prefix alone, the rule saw nothing in a translated project.
    """
    d = _lint_english(_ENUM_VID, "Enumeration", "PaymentType")
    assert len(d) == 1 and "PaymentKind" in d[0].message


@pytest.mark.needs_data
def test_enum_vid_english_correct_name_silent():
    assert _lint_english(_ENUM_VID, "Enumeration", "PaymentKind") == []


# --- 1.8 the element kind in the name -----------------------------------------------------------

def test_kind_in_name_report():
    d = _lint(_KIND, "Отчет", "ОтчетЗависшиеЗадачи")
    assert len(d) == 1
    assert d[0].rule_id == _KIND
    assert "ЗависшиеЗадачи" in d[0].message


@pytest.mark.needs_data
def test_kind_in_name_english_judged_by_its_tail():
    # the kind word leads a Russian name and trails an English one
    d = _lint_english(_KIND, "Report", "StuckTasksReport")
    assert len(d) == 1 and "StuckTasks" in d[0].message


@pytest.mark.needs_data
def test_kind_in_name_english_clean_silent():
    assert _lint_english(_KIND, "Report", "StuckTasks") == []


def test_kind_in_name_clean_silent():
    assert _lint(_KIND, "Отчет", "ЗависшиеЗадачи") == []


def test_kind_in_name_skips_interface_component():
    # The standard allows an interface component a type-clarifying prefix - the rule skips it.
    assert _lint(_KIND, "КомпонентИнтерфейса", "ПолеВводаАдреса") == []


def test_kind_in_name_virtual_table_prefix():
    d = _lint(_KIND, "ВиртуальнаяТаблица", "ВТ_Остатки")
    assert len(d) == 1
    assert "Остатки" in d[0].message


def test_kind_in_name_virtual_table_clean_silent():
    assert _lint(_KIND, "ВиртуальнаяТаблица", "Остатки") == []


# --- 1.8 filler word -----------------------------------------------------------------

def test_filler_word_report():
    d = _lint(_FILLER, "ОбщийМодуль", "УправлениеЦветами")
    assert len(d) == 1
    assert d[0].rule_id == _FILLER
    assert "Управление" in d[0].message


def test_filler_word_clean_silent():
    assert _lint(_FILLER, "ОбщийМодуль", "Цвета") == []


def test_filler_word_needs_a_word_boundary():
    # 'РаботаСЦветами' is "работа с цветами" (a filler), while 'РаботаСотрудника' is
    # "работа сотрудника": the same letters, a different word 
    assert len(_lint(_FILLER, "ОбщийМодуль", "РаботаСJson")) == 1
    assert _lint(_FILLER, "Структура", "РаботаСотрудника") == []


def test_filler_word_english_suffix():
    # A Russian filler prefix lands at the end of the translated compound:
    # `УправлениеСкладами` - `WarehouseManagement`.
    d = _lint(_FILLER, "ОбщийМодуль", "WarehouseManagement")
    assert len(d) == 1
    assert "Management" in d[0].message


def test_filler_word_english_compound_silent():
    # Inside a name the word belongs to a compound term, as in the Russian branch.
    assert _lint(_FILLER, "ОбщийМодуль", "TaskManagementPanel") == []
    assert _lint(_FILLER, "ОбщийМодуль", "TaskManagerContact") == []


def test_filler_word_inside_a_compound_term_is_silent():
    # the standard speaks of PREFIXES and postfixes; inside a compound term
    # ('контент-менеджер' is a job title) the word is not a filler
    assert _lint(_FILLER, "КомпонентИнтерфейса", "ПанельКонтентМенеджера") == []
    # as a postfix - it is
    assert len(_lint(_FILLER, "ОбщийМодуль", "ОбменДаннымиМеханизм")) == 1


# --- the environment postfix of a common module -------------------------------------------------

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
    # The environment postfix concerns only common modules: on a Справочник it is part of the name.
    assert _lint(_MODULE, "Справочник", "ОбщееКлиент") == []


@pytest.mark.needs_data
def test_module_suffix_english_name_judged():
    # the environment words come from the dictionary, so an English name is read the same way
    d = _lint_english(_MODULE, "CommonModule", "DataExchangeClientAndServer")
    assert len(d) == 1 and "DataExchange" in d[0].message


@pytest.mark.needs_data
def test_module_suffix_english_clean_silent():
    assert _lint_english(_MODULE, "CommonModule", "DataExchange") == []


# --- the number of a name by element kind (morphology needed) ------------------------------------

def test_number_catalog_must_be_plural(morph):
    d = _lint(_NUMBER, "Справочник", "Акция")
    assert len(d) == 1
    assert d[0].rule_id == _NUMBER
    assert "справочник" in d[0].message


def test_number_catalog_plural_silent(morph):
    assert _lint(_NUMBER, "Справочник", "Партии") == []


def test_number_exempt_heads_silent(morph):
    # the standard itself lists the exceptions: these terms get no choice of number - changing
    # it would distort the meaning (справочник Номенклатура, регистр ОчередьСообщений,
    # структура ДанныеЗадачи)
    assert _lint(_NUMBER, "Справочник", "Номенклатура") == []
    assert _lint(_NUMBER, "РегистрСведений", "ОчередьСообщений") == []
    assert _lint(_NUMBER, "Структура", "ДанныеЗадачи") == []
    assert _lint(_NUMBER, "Структура", "СведенияОСотруднике") == []


def test_number_enumeration_must_be_singular(morph):
    d = _lint(_NUMBER, "Перечисление", "ВидыОплат")
    assert len(d) == 1
    assert "перечисление" in d[0].message


def test_number_enumeration_singular_silent(morph):
    assert _lint(_NUMBER, "Перечисление", "ВидОплаты") == []


def test_number_tabular_section_must_be_plural(morph):
    # A tabular section is plural; the second one is named correctly and stays silent.
    tail = _section("ТабличныеЧасти", ("Цена", ""), ("Скидки", ""))
    d = _lint(_NUMBER, "Справочник", "Товары", tail)
    assert len(d) == 1
    assert "табличная часть" in d[0].message
    assert d[0].line == 7  # the name line of the first tabular section


def test_number_silent_without_morphology(monkeypatch):
    # Without pymorphy3 the rule stays silent: guessing the number of a RUSSIAN name by
    # endings is not allowed.
    monkeypatch.setattr(naming, "_morph", lambda: None)
    assert _lint(_NUMBER, "Справочник", "Акция") == []


# --- the number of an English name (suffix heuristics, no morphology) ---------------------------

def test_number_english_register_singular(monkeypatch):
    # The head of an English compound is its last word; no pymorphy3 is needed for it.
    monkeypatch.setattr(naming, "_morph", lambda: None)
    d = _lint(_NUMBER, "РегистрСведений", "CurrencyRate")
    assert len(d) == 1
    assert "CurrencyRate" in d[0].message


def test_number_english_plural_silent():
    assert _lint(_NUMBER, "Справочник", "WarehouseSections") == []
    assert _lint(_NUMBER, "Справочник", "Tasks") == []


def test_number_english_enumeration_plural():
    d = _lint(_NUMBER, "Перечисление", "PaymentKinds")
    assert len(d) == 1
    assert "PaymentKinds" in d[0].message


def test_number_english_exempt_heads_silent():
    # The translated spellings of the standard's exceptions: the head does not choose a number.
    assert _lint(_NUMBER, "Справочник", "Nomenclature") == []
    assert _lint(_NUMBER, "Структура", "TaskData") == []
    assert _lint(_NUMBER, "РегистрСведений", "MessageQueue") == []


def test_number_english_undecided_silent():
    # Mass nouns and ambiguous tails (-os) are not guessed.
    assert _lint(_NUMBER, "Справочник", "News") == []
    assert _lint(_NUMBER, "Справочник", "BatchPhotos") == []


@pytest.mark.needs_data
def test_number_english_tabular_section():
    # A fully translated description: the English kind, the Name key and the TabularParts
    # section are read the same way as the Russian spellings.
    text = (
        "ElementKind: Catalog\n"
        f"Id: {_ID}\n"
        "Name: Warehouses\n"
        "TabularParts:\n"
        "    -\n"
        "        Id: 22222222-3333-4444-5555-000000000001\n"
        "        Name: Structure\n"
    )
    source = engine.load_text("Warehouses.yaml", text)
    d = engine.run_sources([source], select={_NUMBER})
    assert len(d) == 1
    assert "Structure" in d[0].message


# --- 1.9 the name of a boolean attribute -----------------------------------------------------------

def test_boolean_negation():
    # Negation is caught without morphology - by the Не/Нет prefixes.
    tail = _section("Реквизиты", ("НетОшибок", "Булево"))
    d = _lint(_BOOLEAN, "Справочник", "Загрузки", tail)
    assert len(d) == 1
    assert d[0].rule_id == _BOOLEAN
    assert "отрицание" in d[0].message


def test_boolean_noun(morph):
    tail = _section("Реквизиты", ("Администратор", "Булево"))
    d = _lint(_BOOLEAN, "Справочник", "Пользователи", tail)
    assert len(d) == 1
    assert "ЭтоАдминистратор" in d[0].message  # the suggestion is the name with a prefix


def test_boolean_prefixed_name_silent(morph):
    tail = _section("Реквизиты", ("ЭтоАдминистратор", "Булево"))
    assert _lint(_BOOLEAN, "Справочник", "Пользователи", tail) == []


def test_boolean_only_boolean_attributes(morph):
    # The same noun name, but the attribute is not boolean - the rule leaves it alone.
    tail = _section("Реквизиты", ("Администратор", "Строка"))
    assert _lint(_BOOLEAN, "Справочник", "Пользователи", tail) == []


# --- 2.1 and 2.3 the element presentation (metamodel needed) ------------------------------

_LIST_CAPTION = "Интерфейс:\n    Список:\n        Представление: Партии товаров\n"
_OBJECT_CAPTION = "Интерфейс:\n    Объект:\n        Представление: Партия товара\n"
_BOTH_CAPTIONS = (
    "Интерфейс:\n"
    "    Список:\n        Представление: Партии товаров\n"
    "    Объект:\n        Представление: Партия товара\n"
)


@pytest.mark.needs_data
def test_presentation_missing():
    d = _lint(_PRESENTATION, "Справочник", "Партии")
    assert len(d) == 1
    assert d[0].rule_id == _PRESENTATION
    assert "Представление" in d[0].message


@pytest.mark.needs_data
def test_presentation_filled_silent():
    # A report keeps its caption in the top-level property, a catalog in its interface section.
    assert _lint(_PRESENTATION, "Отчет", "Сверка", "Представление: Сверка\n") == []
    assert _lint(_PRESENTATION, "Справочник", "Партии", _BOTH_CAPTIONS) == []


@pytest.mark.needs_data
def test_presentation_attribute_name_does_not_stand_for_the_captions():
    """The top-level Presentation of a catalog names an attribute, and naming one does not
    caption the element: the standard (2.3) wants the list and the object captioned."""
    tail = "Представление: Наименование\n" + _section("Реквизиты", ("Наименование", "Строка"))
    d = _lint(_PRESENTATION, "Справочник", "Партии", tail)
    assert len(d) == 1
    assert "нет заголовков в интерфейсе" in d[0].message
    assert _lint(_PRESENTATION, "Справочник", "Партии", tail + _BOTH_CAPTIONS) == []


@pytest.mark.needs_data
def test_presentation_deprecated_not_marked():
    # On a report the property is a text - the deprecation mark applies.
    d = _lint(_PRESENTATION, "Отчет", "УстарелоСверка", "Представление: Сверка\n")
    assert len(d) == 1
    assert "не используется" in d[0].message


@pytest.mark.needs_data
def test_presentation_deprecated_marked_silent():
    tail = "Представление: (не используется) Сверка\n"
    assert _lint(_PRESENTATION, "Отчет", "УстарелоСверка", tail) == []


@pytest.mark.needs_data
def test_presentation_deprecated_skips_attribute_name_kinds():
    # A catalog's Представление is an attribute NAME (metamodel type AttributeName): no
    # "(не используется)" prefix can be written into it, so the mark is asked of the
    # interface captions alone.
    tail = (
        "Представление: Наименование\n" + _section("Реквизиты", ("Наименование", ""))
        + _BOTH_CAPTIONS.replace("Представление: Парти", "Представление: (не используется) Парти")
    )
    assert _lint(_PRESENTATION, "Справочник", "УстарелоПартии", tail) == []


@pytest.mark.needs_data
def test_presentation_skips_kind_without_property():
    # A common module has neither a `Presentation` property nor captions in an interface
    # section - nothing to require.
    assert _lint(_PRESENTATION, "ОбщийМодуль", "Общее") == []


@pytest.mark.needs_data
def test_presentation_of_an_attribute_name_kind_points_at_the_interface():
    """A catalog's top-level Presentation names an attribute: the message must not call it a
    caption (a caption pasted there fails the build) and says where the captions go."""
    d = _lint(_PRESENTATION, "Справочник", "Партии")
    assert len(d) == 1
    assert "имя строкового реквизита" in d[0].message
    assert "Интерфейс.Список.Представление" in d[0].message
    assert "Интерфейс.Объект.Представление" in d[0].message
    assert "задаёт заголовок" not in d[0].message
    # A kind whose top-level property is a text keeps the caption message.
    report = _lint(_PRESENTATION, "Отчет", "Сверка")
    assert len(report) == 1 and "задаёт заголовок" in report[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("vid", [
    "Справочник", "Документ", "ПланОбмена", "ИнтегрируемоеПриложение", "ХранилищеНастроек",
])
def test_presentation_both_captions_satisfy_an_attribute_name_kind(vid):
    assert _lint(_PRESENTATION, vid, "Партии", _BOTH_CAPTIONS) == []
    assert len(_lint(_PRESENTATION, vid, "Партии")) == 1


@pytest.mark.needs_data
@pytest.mark.parametrize("tail, headline, missing", [
    (_LIST_CAPTION, "нет заголовка объекта", "Интерфейс.Объект.Представление"),
    (_OBJECT_CAPTION, "нет заголовка списка", "Интерфейс.Список.Представление"),
])
def test_presentation_one_caption_does_not_stand_for_the_other(tail, headline, missing):
    """The list is captioned in the plural and the object in the singular (2.3), so one
    caption is not enough, and the message names the one that is missing."""
    for vid in ("Справочник", "Документ"):
        d = _lint(_PRESENTATION, vid, "Партии", tail)
        assert len(d) == 1
        assert d[0].message.startswith(f"У элемента вида '{vid}' {headline} в интерфейсе: {missing} ")


@pytest.mark.needs_data
def test_presentation_interface_without_a_caption_is_still_reported():
    # The negative control: an interface section that names no caption satisfies nothing.
    tail = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n    Список:\n        Форма: Партии\n"
    assert len(_lint(_PRESENTATION, "Справочник", "Партии", tail)) == 1


@pytest.mark.needs_data
def test_presentation_interface_caption_does_not_count_for_a_text_kind():
    # A report keeps its caption in the top-level property; an interface block is no excuse.
    assert len(_lint(_PRESENTATION, "Отчет", "Сверка", _BOTH_CAPTIONS)) == 1


def _english_catalog(tail: str = "") -> list:
    text = f"ElementKind: Catalog\nId: {_ID}\nName: Batches\nPresentation: Name\n{tail}"
    return engine.run_sources([engine.load_text("Batches.yaml", text)], select={_PRESENTATION})


@pytest.mark.needs_data
def test_presentation_interface_captions_in_an_english_file():
    both = (
        "Interface:\n"
        "    List:\n        Presentation: Batches of goods\n"
        "    Object:\n        Presentation: Batch of goods\n"
    )
    assert _english_catalog(both) == []
    list_only = _english_catalog("Interface:\n    List:\n        Presentation: Batches of goods\n")
    assert len(list_only) == 1
    assert "нет заголовка объекта в интерфейсе: Интерфейс.Объект.Представление " in list_only[0].message
    assert len(_english_catalog()) == 1


@pytest.mark.needs_data
def test_presentation_english_message_names_the_english_paths():
    i18n.set_lang("en")
    d = _lint(_PRESENTATION, "Справочник", "Партии", _LIST_CAPTION)
    assert len(d) == 1
    assert d[0].message.startswith(
        "The element of kind 'Catalog' has no object caption in the interface: "
        "Interface.Object.Presentation - "
    )


_REGISTER_LIST = "Интерфейс:\n    Список:\n        Представление: Цены товаров\n"
_REGISTER_RECORD = "    Запись:\n        Представление: Цена товара\n"


@pytest.mark.needs_data
def test_presentation_information_register_needs_the_list_and_the_record():
    """2.3 names the registers too: an information register captions its list in the plural
    and its record in the singular. It has no top-level property, so the interface section is
    the only place to caption it."""
    d = _lint(_PRESENTATION, "РегистрСведений", "Цены")
    assert len(d) == 1
    assert d[0].message.startswith("У элемента вида 'РегистрСведений' нет заголовков в интерфейсе.")
    assert "Интерфейс.Список.Представление" in d[0].message
    assert "Интерфейс.Запись.Представление" in d[0].message
    assert _lint(_PRESENTATION, "РегистрСведений", "Цены", _REGISTER_LIST + _REGISTER_RECORD) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("tail, headline, missing", [
    (_REGISTER_LIST, "нет заголовка записи", "Интерфейс.Запись.Представление"),
    ("Интерфейс:\n" + _REGISTER_RECORD, "нет заголовка списка", "Интерфейс.Список.Представление"),
])
def test_presentation_register_caption_alone_names_the_other(tail, headline, missing):
    d = _lint(_PRESENTATION, "РегистрСведений", "Цены", tail)
    assert len(d) == 1
    assert d[0].message.startswith(f"У элемента вида 'РегистрСведений' {headline} в интерфейсе: {missing} ")
    # A register has no top-level property, and the message does not talk about one.
    assert "верхнего уровня" not in d[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("vid", ["РегистрНакопления", "ЖурналДанных"])
def test_presentation_list_only_kinds_need_the_list_caption(vid):
    """An accumulation register and a data journal have a list and no record form: the list
    caption is the one presentation they have, and 2.1 wants it filled in."""
    d = _lint(_PRESENTATION, vid, "Остатки")
    assert len(d) == 1
    assert "нет заголовка списка в интерфейсе: Интерфейс.Список.Представление" in d[0].message
    listed = "Интерфейс:\n    Список:\n        Представление: Остатки товаров\n"
    assert _lint(_PRESENTATION, vid, "Остатки", listed) == []


_SET_RECORD = "Интерфейс:\n    Запись:\n        Представление: Настройки приложения\n"


@pytest.mark.needs_data
def test_presentation_constants_set_is_captioned_by_its_record():
    """The top-level property of a constants set names a constant (a probe build took any
    value there, a phrase included), and the commands keep the name of the set until the
    interface captions them: the record caption is what the standard asks for."""
    d = _lint(_PRESENTATION, "НаборКонстант", "Настройки", "Представление: Настройки приложения\n")
    assert len(d) == 1
    assert "нет заголовка записи в интерфейсе: Интерфейс.Запись.Представление" in d[0].message
    # A filled top-level property is named for what it is.
    assert "у набора констант в нем указывается константа" in d[0].message
    bare = _lint(_PRESENTATION, "НаборКонстант", "Настройки")
    assert len(bare) == 1 and "константа" not in bare[0].message
    assert _lint(_PRESENTATION, "НаборКонстант", "Настройки", _SET_RECORD) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("periodicity", ["День", "Day"])
def test_presentation_periodic_constants_set_needs_its_list_caption(periodicity):
    # The list form of a constants set exists for a periodic set alone - and then it is owed.
    head = f"Периодичность: {periodicity}\n"
    d = _lint(_PRESENTATION, "НаборКонстант", "Курс", head + _SET_RECORD)
    assert len(d) == 1 and "нет заголовка списка в интерфейсе" in d[0].message
    both = ("Интерфейс:\n    Список:\n        Представление: Курсы\n"
            "    Запись:\n        Представление: Курс\n")
    assert _lint(_PRESENTATION, "НаборКонстант", "Курс", head + both) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("periodicity", ["Непериодический", "NonPeriodic"])
def test_presentation_non_periodic_constants_set_has_no_list_to_caption(periodicity):
    tail = f"Периодичность: {periodicity}\n" + _SET_RECORD
    assert _lint(_PRESENTATION, "НаборКонстант", "Настройки", tail) == []


_PROCESSING_CAPTION = "Интерфейс:\n    Представление: Загрузка цен\n"


@pytest.mark.needs_data
def test_presentation_processing_is_captioned_by_its_interface_section():
    """2.1 names processings among the top-level elements. A processing has no top-level
    property: its caption is the interface section's own, and it names both the form and the
    command that opens it."""
    d = _lint(_PRESENTATION, "Обработка", "ЗагрузкаЦен")
    assert len(d) == 1
    assert d[0].message.startswith(
        "У элемента вида 'Обработка' нет заголовка в интерфейсе: Интерфейс.Представление – "
    )
    assert "верхнего уровня" not in d[0].message
    assert _lint(_PRESENTATION, "Обработка", "ЗагрузкаЦен", _PROCESSING_CAPTION) == []
    # The negative control: a section that names no caption satisfies nothing.
    bare = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n    Форма: ЗагрузкаЦенФорма\n"
    assert len(_lint(_PRESENTATION, "Обработка", "ЗагрузкаЦен", bare)) == 1


@pytest.mark.needs_data
def test_presentation_processing_in_an_english_file():
    head = f"ElementKind: Processing\nId: {_ID}\nName: PriceImport\n"

    def lint(tail=""):
        return engine.run_sources([engine.load_text("PriceImport.yaml", head + tail)],
                                  select={_PRESENTATION})

    assert lint("Interface:\n    Presentation: Price import\n") == []
    assert len(lint()) == 1
    i18n.set_lang("en")
    d = lint("Interface:\n    IncludeInAutoInterface: True\n")
    assert len(d) == 1
    assert d[0].message.startswith(
        "The element of kind 'Processing' has no caption in the interface: "
        "Interface.Presentation - "
    )


@pytest.mark.needs_data
def test_presentation_deprecated_processing_marks_its_caption():
    d = _lint(_PRESENTATION, "Обработка", "УстарелоЗагрузкаЦен", _PROCESSING_CAPTION)
    assert len(d) == 1
    assert "заголовок Интерфейс.Представление не начинается с '(не используется)'" in d[0].message
    # Reported at the caption itself, the fifth line of the description.
    assert (d[0].line, d[0].col) == (5, 20)
    marked = _PROCESSING_CAPTION.replace("Загрузка цен", "(не используется) Загрузка цен")
    assert _lint(_PRESENTATION, "Обработка", "УстарелоЗагрузкаЦен", marked) == []


@pytest.mark.needs_data
def test_presentation_register_captions_in_an_english_file():
    head = f"ElementKind: InformationRegister\nId: {_ID}\nName: Prices\n"

    def lint(tail):
        return engine.run_sources([engine.load_text("Prices.yaml", head + tail)], select={_PRESENTATION})

    both = "Interface:\n    List:\n        Presentation: Prices\n    Record:\n        Presentation: Price\n"
    assert lint(both) == []
    assert len(lint("Interface:\n    List:\n        Presentation: Prices\n")) == 1
    i18n.set_lang("en")
    d = lint("Interface:\n    List:\n        Presentation: Prices\n")
    assert d[0].message.startswith(
        "The element of kind 'InformationRegister' has no record caption in the interface: "
        "Interface.Record.Presentation - "
    )


_DEPRECATED_CAPTIONS = (
    "Интерфейс:\n"
    "    Список:\n        Представление: (не используется) Партии\n"
    "    Объект:\n        Представление: {object}\n"
)


@pytest.mark.needs_data
def test_presentation_deprecated_caption_without_the_mark():
    """1.6 marks the presentation of a deprecated element, and an element captioned in its
    interface section keeps its presentation there: every caption starts with the mark."""
    d = _lint(_PRESENTATION, "Справочник", "УстарелоПартии", _DEPRECATED_CAPTIONS.format(object="Партия"))
    assert len(d) == 1
    assert "заголовок Интерфейс.Объект.Представление не начинается с '(не используется)'" in d[0].message
    # Reported at the caption itself, the eighth line of the description.
    assert (d[0].line, d[0].col) == (8, 24)
    register = _REGISTER_LIST.replace("Цены товаров", "(не используется) Цены товаров")
    d = _lint(_PRESENTATION, "РегистрСведений", "УстарелоЦены", register + _REGISTER_RECORD)
    assert len(d) == 1 and "Интерфейс.Запись.Представление" in d[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("caption", ["(не используется) Партия", "$Словарь.Партия", "Batch"])
def test_presentation_deprecated_caption_judged_on_a_russian_text(caption):
    # A marked caption passes; a localized-string reference and an English caption carry no
    # text the Russian mark could head.
    tail = _DEPRECATED_CAPTIONS.format(object=caption)
    assert _lint(_PRESENTATION, "Справочник", "УстарелоПартии", tail) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("value", ["$Отчеты.Сверка", "Reconciliation"])
def test_presentation_deprecated_text_judged_on_a_russian_text(value):
    assert _lint(_PRESENTATION, "Отчет", "УстарелоСверка", f"Представление: {value}\n") == []


# --- mandatory prefixes and postfixes by kind -----------------------------------------

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
    d = _lint(_PREFIX, "ЛокализованныеСтроки", "Обмен")
    assert len(d) == 1
    assert "Локализация" in d[0].message


def test_suffix_by_kind_present_silent():
    assert _lint(_PREFIX, "ЛокализованныеСтроки", "ОбменЛокализация") == []


@pytest.mark.needs_data
def test_prefix_by_kind_english_suffix_silent():
    # The head of an English compound is its last word: the English name carries the same
    # kind word as a SUFFIX, spelled by the platform dictionary - a translated tree used to
    # get one report per element here.
    assert _lint(_PREFIX, "КлючДоступа", "AdministratorAccessKey") == []
    assert _lint(_PREFIX, "ПравоНаДействие", "ContentImportPrivilege") == []
    assert _lint(_PREFIX, "НавигационнаяКоманда", "MainNavigation") == []
    assert _lint(_PREFIX, "ЛокализованныеСтроки", "MainLocalization") == []


@pytest.mark.needs_data
def test_prefix_by_kind_english_missing_names_the_english_form():
    d = _lint(_PREFIX, "КлючДоступа", "Administrator")
    assert len(d) == 1
    assert "AccessKey" in d[0].message


# --- a trailing comment and quotes on the Имя line ----------------------------------------

def test_trailing_comment_not_part_of_name():
    # Per YAML a comment after the value is not a part of it: previously such a line did not
    # match the name regex at all, and the whole naming/ group kept silent about this name.
    d = _lint(_YO, "Справочник", "ПересчётТоваров # комментарий")
    assert len(d) == 1
    assert "ПересчётТоваров" in d[0].message  # the name without the tail


def test_trailing_comment_in_section_name():
    d = _lint(_YO, "Справочник", "Товары", _section("Реквизиты", ("Объём # комментарий", "Число")))
    assert len(d) == 1
    assert d[0].line == 7
    assert "Объём" in d[0].message


def test_trailing_comment_number(morph):
    # A repro of the original false negative: a register name in the singular + a comment.
    d = _lint(_NUMBER, "РегистрСведений", "КешЗапросов # закэшированные токены")
    assert len(d) == 1
    assert "КешЗапросов" in d[0].message


def test_quoted_name_with_comment():
    source = engine.load_text(
        "Товары.yaml",
        f'ВидЭлемента: Справочник\nИд: {_ID}\nИмя: "ПересчётТоваров" # комментарий\n',
    )
    d = engine.run_sources([source], select={_YO})
    assert len(d) == 1
    assert "ПересчётТоваров" in d[0].message  # without the quotes and the tail


def test_comment_only_value_is_no_name():
    source = engine.load_text(
        "Товары.yaml", f"ВидЭлемента: Справочник\nИд: {_ID}\nИмя: # имени нет\n",
    )
    assert engine.run_sources([source], select={_YO}) == []


# --- the group as a whole ---------------------------------------------------------------------

def test_structural_yaml_skipped():
    # A file without ВидЭлемента (Проект, Подсистема) does not describe an element - its names
    # are not checked, though "Управление_Складом" would violate both naming/underscore and
    # naming/filler-word.
    source = engine.load_text("Подсистема.yaml", "Имя: Управление_Складом\nСодержимое:\n    - Партии\n")
    assert engine.run_sources([source], select={"naming"}) == []


@pytest.mark.needs_data
def test_correct_object_passes_whole_group(morph):
    tail = (
        _BOTH_CAPTIONS
        + _section("Реквизиты", ("ЭтоАрхивная", "Булево"), ("Заголовок", "Строка"))
        + _section("ТабличныеЧасти", ("Условия", ""))
    )
    source = engine.load_text("Партии.yaml", _yaml("Справочник", "Партии", tail))
    assert engine.run_sources([source], select={"naming"}) == []
