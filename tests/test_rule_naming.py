"""The naming/ rule group: project element names per the 1C:Element standard.

The rules read the yaml description, so the Element data is needed only by naming/presentation -
it asks the metamodel whether the kind has the Представление property; such tests are marked
needs_data. The grammatical number of a name (naming/number and the "noun" branch of
naming/boolean-name) is computed by morphology: the tests take it via the morph fixture and are
skipped without pymorphy3. The remaining tests pass in a clean checkout - they need neither the
data nor the morphology.
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
    "ДоступКПриложениям", "КнопкаЗаписатьИЗакрыть", "ОбращенияВПоддержку",
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


# --- 1.8 the element kind in the name -----------------------------------------------------------

def test_kind_in_name_report():
    d = _lint(_KIND, "Отчет", "ОтчетЗависшиеЗадачи")
    assert len(d) == 1
    assert d[0].rule_id == _KIND
    assert "ЗависшиеЗадачи" in d[0].message


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


# --- 2.1 the element presentation (metamodel needed) --------------------------------------

@pytest.mark.needs_data
def test_presentation_missing():
    d = _lint(_PRESENTATION, "Справочник", "Партии")
    assert len(d) == 1
    assert d[0].rule_id == _PRESENTATION
    assert "Представление" in d[0].message


@pytest.mark.needs_data
def test_presentation_filled_silent():
    assert _lint(_PRESENTATION, "Справочник", "Партии", "Представление: Партии\n") == []


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
    # "(не используется)" prefix can be written into it - the branch must stay silent.
    tail = "Представление: Наименование\n" + _section("Реквизиты", ("Наименование", ""))
    assert _lint(_PRESENTATION, "Справочник", "УстарелоПартии", tail) == []


@pytest.mark.needs_data
def test_presentation_skips_kind_without_property():
    # A common module has no Представление property - nothing to require.
    assert _lint(_PRESENTATION, "ОбщийМодуль", "Общее") == []


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
        "Представление: Партии\n"
        + _section("Реквизиты", ("ЭтоАрхивная", "Булево"), ("Заголовок", "Строка"))
        + _section("ТабличныеЧасти", ("Условия", ""))
    )
    source = engine.load_text("Партии.yaml", _yaml("Справочник", "Партии", tail))
    assert engine.run_sources([source], select={"naming"}) == []
