"""Tier D: project element names per the 1C:Element standard "Имена элементов проекта".

Checked are the names in descriptions (.yaml): the name of the element itself and the names of
its attributes, dimensions, resources, tabular sections, fields and enumeration values. The
standard is mandatory in new code, so all rules of the group are warnings.

What is checked (clauses of the standard):

- 1.2 the letter "ё" and underscores in names (naming/yo, naming/underscore);
- 1.3 an abbreviation is written as one word: Ндс, not НДС (naming/abbreviation);
- 1.4 an English term is written in the original: Xml, not Хмл (naming/latin-term);
- 1.5 enumerations are named with the word "Вид", not "Тип" (naming/enum-vid);
- 1.8 the name does not repeat the element kind and contains no filler words
  (naming/kind-in-name, naming/filler-word), and a common module does not carry an environment
  suffix (naming/module-suffix);
- 1.9 a boolean attribute is named as an assertion, not a negation (naming/boolean-name);
- 2.1 the element has Представление filled in, and for a deprecated one it starts with
  "(не используется)" (naming/presentation);
- section 3: the grammatical number of the name by element kind (naming/number) and the
  mandatory prefixes of certain kinds (naming/prefix-by-kind).

The number of the name (catalogs in the plural, enumerations in the singular) is determined by
morphology: pymorphy3 is required (the [morph] extra). Without it the naming/number rule stays
silent - guessing by endings is not an option: a singular "Номенклатура" does not violate the
standard, while "Программы" and "Акции" without case analysis read as genitive singular.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_schema import _HAVE_YAML, _NAME_LINE_RE, _is_object, _parsed

MESSAGES = {
    "naming/yo.title": {"ru": "Буква \"ё\" в имени", "en": "Letter \"ё\" in a name"},
    "naming/yo.found": {
        "ru": "Буква 'ё' в имени '{name}' – в именах она не используется: '{suggestion}'.",
        "en": "The letter 'ё' in the name '{name}' – names do not use it: '{suggestion}'.",
    },
    "naming/underscore.title": {"ru": "Подчёркивание в имени", "en": "Underscore in a name"},
    "naming/underscore.found": {
        "ru": "Подчёркивание в имени '{name}' – имена пишутся слитно, каждое слово с заглавной; "
              "подчёркивание допустимо только для версии (ФизическоеЛицо_v2, ФизическиеЛицаApi_3_1).",
        "en": "Underscore in the name '{name}' – names are written in UpperCamelCase; an underscore "
              "is allowed only for a version suffix (ФизическоеЛицо_v2, ФизическиеЛицаApi_3_1).",
    },
    "naming/abbreviation.title": {
        "ru": "Аббревиатура заглавными буквами в имени",
        "en": "All-caps abbreviation in a name",
    },
    "naming/abbreviation.caps": {
        "ru": "Аббревиатура заглавными в имени '{name}' – в имени она пишется как одно слово, "
              "заглавной остаётся только первая буква: '{suggestion}'.",
        "en": "All-caps abbreviation in the name '{name}' – in a name it is written as one word, "
              "only the first letter stays capital: '{suggestion}'.",
    },
    "naming/latin-term.title": {
        "ru": "Англоязычный термин записан русскими буквами",
        "en": "English term spelled in Cyrillic",
    },
    "naming/latin-term.found": {
        "ru": "'{word}' в имени '{name}' – англоязычный термин пишется оригиналом: '{suggestion}'.",
        "en": "'{word}' in the name '{name}' – an English term is written as the original: '{suggestion}'.",
    },
    "naming/enum-vid.title": {
        "ru": "Имя перечисления со словом \"Тип\"",
        "en": "Enumeration name with the word \"Тип\"",
    },
    "naming/enum-vid.bad-prefix": {
        "ru": "Имя перечисления '{name}' начинается с '{prefix}' – при равнозначном выборе "
              "используется 'Вид': '{suggestion}'.",
        "en": "Enumeration name '{name}' starts with '{prefix}' – when the choice is equal, "
              "'Вид' is used: '{suggestion}'.",
    },
    "naming/kind-in-name.title": {"ru": "Вид элемента в его имени", "en": "Element kind inside its name"},
    "naming/kind-in-name.found": {
        "ru": "Имя '{name}' начинается с названия вида ('{prefix}') – вид не включают в имя: '{suggestion}'.",
        "en": "The name '{name}' starts with its kind ('{prefix}') – the kind is not part of the name: "
              "'{suggestion}'.",
    },
    "naming/filler-word.title": {"ru": "Слово-пустышка в имени", "en": "Filler word in a name"},
    "naming/filler-word.found": {
        "ru": "'{word}' в имени '{name}' – без этого слова смысл не меняется, уберите его "
              "(исключение – термин предметной области).",
        "en": "'{word}' in the name '{name}' – the meaning does not change without it, drop it "
              "(unless it is a domain term).",
    },
    "naming/module-suffix.title": {
        "ru": "Постфикс окружения в имени общего модуля",
        "en": "Environment suffix in a common module name",
    },
    "naming/module-suffix.found": {
        "ru": "Имя общего модуля '{name}' несёт постфикс окружения ('{suffix}') – окружение задаётся "
              "свойством Окружение, в имя его не выносят: '{suggestion}'.",
        "en": "The common module name '{name}' carries an environment suffix ('{suffix}') – the "
              "environment is set by a property, not by the name: '{suggestion}'.",
    },
    "naming/number.title": {"ru": "Число имени не по виду элемента", "en": "Wrong number for the element kind"},
    "naming/number.plural": {
        "ru": "Имя '{name}' в единственном числе – {vid} именуется во множественном "
              "(по заголовку списка в интерфейсе).",
        "en": "The name '{name}' is singular – {vid} is named in the plural (after the list title).",
    },
    "naming/number.singular": {
        "ru": "Имя '{name}' во множественном числе – {vid} именуется в единственном.",
        "en": "The name '{name}' is plural – {vid} is named in the singular.",
    },
    "naming/boolean-name.title": {"ru": "Имя булева реквизита", "en": "Boolean attribute name"},
    "naming/boolean-name.negation": {
        "ru": "Имя булева реквизита '{name}' содержит отрицание – имя образуют от истинного значения "
              "признака (Успешно вместо НетОшибок).",
        "en": "The boolean attribute name '{name}' is a negation – name it after the true value "
              "(Успешно rather than НетОшибок).",
    },
    "naming/boolean-name.noun": {
        "ru": "Имя булева реквизита '{name}' – существительное: начните его со слов Это, Есть или "
              "Содержит ('Это{name}'), иначе имя читается как ссылка или строка.",
        "en": "The boolean attribute name '{name}' is a noun: start it with Это, Есть or Содержит "
              "('Это{name}'), otherwise the name reads as a reference or a string.",
    },
    "naming/presentation.title": {"ru": "Представление элемента", "en": "Element presentation"},
    "naming/presentation.missing": {
        "ru": "У элемента вида '{vid}' не заполнено Представление – оно обязательно для элементов "
              "верхнего уровня и задаёт заголовок в интерфейсе.",
        "en": "The element of kind '{vid}' has no Представление – it is required for top-level elements "
              "and sets the title in the interface.",
    },
    "naming/presentation.deprecated": {
        "ru": "Имя '{name}' начинается с 'Устарело', а представление не начинается с "
              "'(не используется)' – у устаревших элементов представление помечают именно так.",
        "en": "The name '{name}' starts with 'Устарело', but the presentation does not start with "
              "'(не используется)' – that is how deprecated elements are marked.",
    },
    "naming/prefix-by-kind.title": {
        "ru": "Имя вида без обязательного префикса",
        "en": "Kind-specific name without its prefix",
    },
    "naming/prefix-by-kind.missing": {
        "ru": "Имя '{name}' вида '{vid}' – по стандарту оно образуется с {what} '{prefix}'.",
        "en": "The name '{name}' of kind '{vid}' – by the standard it is formed with the {what} '{prefix}'.",
    },
    "naming/prefix-by-kind.forbidden": {
        "ru": "'{word}' в имени HTTP-сервиса '{name}' – слова, от удаления которых смысл не меняется "
              "(web, Api), в имя не включают.",
        "en": "'{word}' in the HTTP service name '{name}' – words that change nothing when removed "
              "(web, Api) are not part of the name.",
    },
}
i18n.register(MESSAGES)

# --- description parsing ---------------------------------------------------------------

# Lines with the Имя key are parsed by the shared regex yaml_schema._NAME_LINE_RE (it strips
# quotes and a trailing comment off the value); the sections where the key may occur are below:
# the indent tells whose name it is.
_SECTION_RE = re.compile(
    r"(?m)^([ \t]*)(Реквизиты|Измерения|Ресурсы|ТабличныеЧасти|Элементы|Поля|Параметры):"
)

# A word in an UpperCamelCase name: Cyrillic, Latin or a number.
_WORD_RE = re.compile(r"[А-ЯЁ][а-яё]*|[A-Z][a-z]*|\d+")
# An abbreviation: two or more consecutive capitals (АПИ, НДС, HTTP).
_ABBREV_RE = re.compile(r"[А-ЯЁA-Z]{2,}")
# The version tail for which the standard allows an underscore: _v2, Api_3_1.
_VERSION_TAIL_RE = re.compile(r"_(v\d+|\d+(_\d+)*)$")


@dataclass(frozen=True)
class NameRef:
    """A name in a description: what name it is, where it is and what it belongs to."""

    name: str
    line: int
    col: int
    section: str  # "" - the element's own name, otherwise the section (Реквизиты, ТабличныеЧасти, ...)


def _names(source: SourceFile) -> list[NameRef]:
    """All names of a description: the element name and the names in sections (attributes,
    tabular sections, values and so on).

    Cached: the result is shared by all rules of the naming/ group, and there are twelve of
    them - without the cache the parsing of a single file was repeated for every rule (visible
    in the profile).
    """
    cached = source.cache.get("naming_names")
    if cached is not None:
        return cached
    lm = linemap(source)
    sections: list[tuple[int, int, str]] = [
        (m.start(), len(m.group(1)), m.group(2)) for m in _SECTION_RE.finditer(source.text)
    ]
    out: list[NameRef] = []
    for m in _NAME_LINE_RE.finditer(source.text):
        if not m.group(3):
            continue  # empty value (or a lone comment) - no name
        indent = len(m.group(1))
        line, col = lm.linecol(m.start(3))
        section = ""
        if indent:
            # the closest section above with a smaller indent is the one this item belongs to
            for start, sec_indent, name in reversed(sections):
                if start < m.start() and sec_indent < indent:
                    section = name
                    break
        out.append(NameRef(m.group(3), line, col, section))
    source.cache["naming_names"] = out
    return out


def _object_name(refs: list[NameRef]) -> NameRef | None:
    return next((r for r in refs if not r.section), None)


def _vid(source: SourceFile) -> tuple[str, dict] | None:
    """The element kind and the parsed description (or None if this is not an object description)."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return None
    vid = data.get("ВидЭлемента")
    return (vid, data) if isinstance(vid, str) else None


def _diag(source: SourceFile, ref: NameRef, rule_id: str, key: str, **kw) -> Diagnostic:
    return Diagnostic(
        source.rel, ref.line, ref.col, rule_id, Severity.WARNING, i18n.t(key, **kw)
    )


# --- morphology ------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _morph():
    """The morphological analyzer (pymorphy3), or None if the [morph] extra is not installed."""
    try:
        import pymorphy3
    except ImportError:
        return None
    return pymorphy3.MorphAnalyzer()


def _head_number(name: str) -> str | None:
    """The number of the name's head word: 'sing', 'plur' or None (no morphology / not parsed).

    The head word is the first noun of the name: in "АрхивныеКопии" it is "Копии", in
    "БанковскиеСчетаОрганизаций" - "Счета" ("Организаций" only qualifies it). The number is
    taken from the nominative case: without it "Программы" and "Акции" read as genitive
    singular.
    """
    morph = _morph()
    if morph is None:
        return None
    words = [w for w in _WORD_RE.findall(name) if len(w) > 1 and w[0] in "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"]
    for word in words:
        # Contractions and abbreviations (Доп, МС) carry no number - keep looking for the head word.
        nouns = [
            p for p in morph.parse(word)
            if p.tag.POS in ("NOUN", "ADJF") and "Abbr" not in p.tag
        ]
        if not nouns:
            continue
        nominative = [p for p in nouns if "nomn" in p.tag]
        best = nominative[0] if nominative else nouns[0]
        if best.tag.POS != "NOUN" and word is not words[0]:
            continue  # skip a qualifying adjective, keep looking for a noun
        number = best.tag.number
        if number:
            return str(number)
    return None


# --- standard data ---------------------------------------------------------------------

# Kinds named in the plural (after the list title in the interface), and in the singular.
PLURAL_KINDS = {
    "Справочник": "справочник",
    "Документ": "документ",
    "РегистрСведений": "регистр сведений",
    "РегистрНакопления": "регистр накопления",
    "ПланОбмена": "план обмена",
    "КонтрактСущности": "контракт сущности",
}
SINGULAR_KINDS = {
    "Перечисление": "перечисление",
    "Структура": "структура",
    "КонтрактТипа": "контракт типа",
    "ЗапланированноеЗадание": "запланированное задание",
}
# A tabular section is named in the plural (the table title on a form).
PLURAL_SECTIONS = {"ТабличныеЧасти"}

# Words whose number is not a matter of choice: changing it distorts the meaning of the entity.
# The standard itself lists them as exceptions - the catalog Номенклатура, the registers
# ИсторияРассылокОтчетов and ОчередьСообщений, the structures ДанныеЗадачи and
# СведенияОСотруднике. A name with such a head word is left alone by the rule.
NUMBER_EXEMPT_HEADS = frozenset({
    "Номенклатура", "Данные", "Сведения", "История", "Очередь", "Итоги", "Информация",
    "Настройки", "Статистика",
})

# The kind word at the start of a name: the kind is not part of the name (the report
# ЗависшиеЗадачи, not ОтчетЗависшиеЗадачи).
KIND_PREFIXES = {
    "Отчет": "Отчет", "Отчёт": "Отчет",
    "Обработка": "Обработка",
    "Структура": "Структура",
    "Справочник": "Справочник",
    "Документ": "Документ",
    "Перечисление": "Перечисление",
    "Регистр": "Регистр",
    "ВиртуальнаяТаблица": "Таблица",
}
_VT_PREFIX_RE = re.compile(r"^(ВТ_|Таблица[А-ЯЁ])")

# Words whose removal does not change the meaning of the name (1.8). The standard speaks of
# PREFIXES and POSTFIXES ("Избегайте слов, префиксов и постфиксов..."; its own bad examples -
# РаботаСЦветами, УправлениеЦветами, УправлениеАдресами - are all prefixes), so _filler_hit
# matches only at a word boundary at either end: inside a name such a fragment belongs to a
# compound term (ПанельКонтентМенеджера - a content manager's panel) and is not a filler.
FILLER_WORDS = ("Управление", "Механизм", "Функциональность", "Менеджер", "Процедуры", "РаботаС")


def _filler_hit(name: str) -> str | None:
    """The filler word of the name, or None. A prefix must be followed by a new word
    (an uppercase letter): `РаботаСЦветами` is "работа с цветами", while `РаботаСотрудника`
    is "работа сотрудника" - the same letters, another word."""
    for word in FILLER_WORDS:
        if name.startswith(word):
            rest = name[len(word):]
            if not rest or rest[:1].isupper():
                return word
        if name.endswith(word) and len(name) > len(word):
            return word
    return None

# Environment suffixes of common modules: the environment is set by a property, not by the name.
MODULE_SUFFIXES = ("КлиентИСервер", "КлиентСервер", "Клиент", "Сервер")

# English terms spelled in Cyrillic (1.4): they are written in the original. Only genuine
# distortions - words adopted into Russian (токен, логин, куки, смс) are not forbidden by the
# standard.
TRANSLITERATED = {
    "Хмл": "Xml", "Хттп": "Http", "Джсон": "Json", "Хтмл": "Html", "Урл": "Url",
    "Апи": "Api", "Эксель": "Excel", "Ворд": "Word", "Пдф": "Pdf", "Джава": "Java",
}
# The same terms as all-caps abbreviations (АПИ, ХМЛ): naming/abbreviation leaves them alone -
# the term as a whole is owned by naming/latin-term, which handles both spellings (see
# _latin_term).
_TRANSLIT_CAPS = {w.upper() for w in TRANSLITERATED}

# Mandatory prefixes and suffixes by kind (section 3).
KIND_PREFIX_REQUIRED = {
    "КлючДоступа": "КлючДоступа",
    "ПравоНаДействие": "ПравоНа",
    "ПравоНаЭлемент": "ПравоНа",
    "НавигационнаяКоманда": "Навигация",
    "ПереключаемаяКоманда": "Команда",
}
KIND_SUFFIX_REQUIRED = {
    "ЛокализованныеСтроки": "Локализация",
}
# HTTP service: words that are not part of the name.
HTTP_FORBIDDEN = ("Api", "Web", "Апи", "Веб")


def _abbrev_core(name: str, m: re.Match) -> str:
    """The abbreviation proper within a group of capital letters.

    The last capital belongs to the next word when a lowercase letter follows it: in
    "ЗапросыКМССервер" the abbreviation is КМС, and "С" starts "Сервер". After that the group
    may be down to a single letter - that is not an abbreviation but a preposition or
    conjunction glued to a word: "ДоступКПриложениям", "КнопкаЗаписатьИЗакрыть",
    "ОбращенияВПоддержку".
    """
    group = m.group(0)
    tail = name[m.end():m.end() + 1]
    return group[:-1] if (tail and tail.islower()) else group


def _suggest_abbrev(name: str) -> str:
    """Turn an all-caps abbreviation into one word: АПИСервиса -> АпиСервиса."""
    def fix(m: re.Match) -> str:
        core = _abbrev_core(name, m)
        if len(core) < 2:
            return m.group(0)  # a preposition or conjunction before a word - leave it alone
        rest = m.group(0)[len(core):]
        return core[0] + core[1:].lower() + rest

    return _ABBREV_RE.sub(fix, name)


def _abbreviations(name: str) -> list[str]:
    """All-caps abbreviations in a name, except English terms (they have a rule of their own)."""
    out = []
    for m in _ABBREV_RE.finditer(name):
        core = _abbrev_core(name, m)
        if len(core) >= 2 and core.upper() not in _TRANSLIT_CAPS:
            out.append(core)
    return out


def _latin_term(name: str) -> tuple[str, str] | None:
    """The first English term spelled in Cyrillic, and its original: Урл -> Url.

    The term is looked for in both spellings - regular (АпиСервиса) and all-caps (АПИСервиса).
    The capital group has to be handled separately: _WORD_RE splits it into single letters
    (А, П, И), so on its own the name АПИСервиса would be seen neither by this rule nor by
    naming/abbreviation - the latter skips such abbreviations precisely in favor of this rule.
    """
    for m in _ABBREV_RE.finditer(name):
        core = _abbrev_core(name, m)
        if len(core) >= 2 and core.capitalize() in TRANSLITERATED:
            return core, TRANSLITERATED[core.capitalize()]
    for word in _WORD_RE.findall(name):
        if word.capitalize() in TRANSLITERATED:
            return word, TRANSLITERATED[word.capitalize()]
    return None


# --- rules -------------------------------------------------------------------------------

@rule("naming/yo", "naming/yo.title", "D", severity=Severity.WARNING)
def yo(source: SourceFile) -> Iterable[Diagnostic]:
    """1.2: names do not use the letter "ё" (ПересчетТоваров, not ПересчётТоваров)."""
    if _vid(source) is None:
        return
    for ref in _names(source):
        if "ё" in ref.name or "Ё" in ref.name:
            suggestion = ref.name.replace("ё", "е").replace("Ё", "Е")
            yield _diag(source, ref, "naming/yo", "naming/yo.found",
                        name=ref.name, suggestion=suggestion)


@rule("naming/underscore", "naming/underscore.title", "D", severity=Severity.WARNING)
def underscore(source: SourceFile) -> Iterable[Diagnostic]:
    """1.2: an underscore is allowed only for a version (ФизическоеЛицо_v2), not as a separator."""
    if _vid(source) is None:
        return
    for ref in _names(source):
        if "_" not in ref.name:
            continue
        if _VERSION_TAIL_RE.search(ref.name) and not ref.name.startswith("_"):
            continue  # versioning - allowed by the standard
        yield _diag(source, ref, "naming/underscore", "naming/underscore.found", name=ref.name)


@rule("naming/abbreviation", "naming/abbreviation.title", "D", severity=Severity.WARNING)
def abbreviation(source: SourceFile) -> Iterable[Diagnostic]:
    """1.3: in a name an abbreviation is one word with only the first letter capital (Ндс, Мчд, Кмс)."""
    if _vid(source) is None:
        return
    for ref in _names(source):
        if not _abbreviations(ref.name):
            continue
        yield _diag(source, ref, "naming/abbreviation", "naming/abbreviation.caps",
                    name=ref.name, suggestion=_suggest_abbrev(ref.name))


@rule("naming/latin-term", "naming/latin-term.title", "D", severity=Severity.WARNING)
def latin_term(source: SourceFile) -> Iterable[Diagnostic]:
    """1.4: an English term is written in the original (ОтправитьXml, not ОтправитьХмл)."""
    if _vid(source) is None:
        return
    for ref in _names(source):
        found = _latin_term(ref.name)
        if found is None:
            continue
        word, original = found
        yield _diag(source, ref, "naming/latin-term", "naming/latin-term.found",
                    word=word, name=ref.name, suggestion=ref.name.replace(word, original, 1))


@rule("naming/enum-vid", "naming/enum-vid.title", "D", severity=Severity.WARNING)
def enum_vid(source: SourceFile) -> Iterable[Diagnostic]:
    """1.5: an enumeration is named with the word "Вид", not "Тип" (ВидЗадачи, not ТипЗадачи)."""
    got = _vid(source)
    if got is None or got[0] != "Перечисление":
        return
    ref = _object_name(_names(source))
    if ref is None:
        return
    for prefix in ("Типы", "Тип"):
        rest = ref.name[len(prefix):]
        if ref.name.startswith(prefix) and rest[:1].isupper():
            replacement = "Виды" if prefix == "Типы" else "Вид"
            yield _diag(source, ref, "naming/enum-vid", "naming/enum-vid.bad-prefix",
                        name=ref.name, prefix=prefix, suggestion=replacement + rest)
            return


@rule("naming/kind-in-name", "naming/kind-in-name.title", "D", severity=Severity.WARNING)
def kind_in_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.8: the kind is not part of the name (the report ЗависшиеЗадачи, not ОтчетЗависшиеЗадачи).

    Interface components are not checked: the standard allows them a type-qualifying prefix
    (ПолеВводаАдреса, СтраницаРеквизиты) and even the word Компонент for complex custom ones.
    """
    got = _vid(source)
    if got is None:
        return
    vid = got[0]
    ref = _object_name(_names(source))
    if ref is None:
        return
    if vid == "ВиртуальнаяТаблица" and _VT_PREFIX_RE.match(ref.name):
        yield _diag(source, ref, "naming/kind-in-name", "naming/kind-in-name.found",
                    name=ref.name, prefix="ВТ_/Таблица",
                    suggestion=re.sub(r"^(ВТ_|Таблица)", "", ref.name))
        return
    prefix = KIND_PREFIXES.get(vid)
    if not prefix:
        return
    rest = ref.name[len(prefix):]
    if ref.name.startswith(prefix) and rest[:1].isupper():
        yield _diag(source, ref, "naming/kind-in-name", "naming/kind-in-name.found",
                    name=ref.name, prefix=prefix, suggestion=rest)


@rule("naming/filler-word", "naming/filler-word.title", "D", severity=Severity.WARNING)
def filler_word(source: SourceFile) -> Iterable[Diagnostic]:
    """1.8: without the words управление, механизм, менеджер, работа с - the meaning stays the same."""
    if _vid(source) is None:
        return
    ref = _object_name(_names(source))
    if ref is None:
        return
    word = _filler_hit(ref.name)
    if word is not None:
        yield _diag(source, ref, "naming/filler-word", "naming/filler-word.found",
                    word=word, name=ref.name)


@rule("naming/module-suffix", "naming/module-suffix.title", "D", severity=Severity.WARNING)
def module_suffix(source: SourceFile) -> Iterable[Diagnostic]:
    """Section 3: a common module name carries no environment suffix (ОбменДаннымиКлиентИСервер)."""
    got = _vid(source)
    if got is None or got[0] != "ОбщийМодуль":
        return
    ref = _object_name(_names(source))
    if ref is None:
        return
    for suffix in MODULE_SUFFIXES:
        if ref.name.endswith(suffix) and len(ref.name) > len(suffix):
            yield _diag(source, ref, "naming/module-suffix", "naming/module-suffix.found",
                        name=ref.name, suffix=suffix, suggestion=ref.name[: -len(suffix)])
            return


def _number_exempt(name: str) -> bool:
    """A name whose number is not checked: its head word does not choose one (ДанныеЗадачи,
    СведенияОСотруднике, ОчередьСообщений, Номенклатура)."""
    head = next(iter(_WORD_RE.findall(name)), "")
    return head in NUMBER_EXEMPT_HEADS


@rule("naming/number", "naming/number.title", "D", severity=Severity.WARNING)
def number(source: SourceFile) -> Iterable[Diagnostic]:
    """Section 3: catalogs, documents, registers and tabular sections - in the plural,
    enumerations and structures - in the singular. Silent without the [morph] extra (pymorphy3)."""
    got = _vid(source)
    if got is None or _morph() is None:
        return
    vid = got[0]
    refs = _names(source)

    obj = _object_name(refs)
    if obj is not None and not _number_exempt(obj.name):
        if vid in PLURAL_KINDS and _head_number(obj.name) == "sing":
            yield _diag(source, obj, "naming/number", "naming/number.plural",
                        name=obj.name, vid=PLURAL_KINDS[vid])
        elif vid in SINGULAR_KINDS and _head_number(obj.name) == "plur":
            yield _diag(source, obj, "naming/number", "naming/number.singular",
                        name=obj.name, vid=SINGULAR_KINDS[vid])

    for ref in refs:
        if ref.section not in PLURAL_SECTIONS or _number_exempt(ref.name):
            continue
        if _head_number(ref.name) == "sing":
            yield _diag(source, ref, "naming/number", "naming/number.plural",
                        name=ref.name, vid="табличная часть")


@rule("naming/boolean-name", "naming/boolean-name.title", "D", severity=Severity.WARNING)
def boolean_name(source: SourceFile) -> Iterable[Diagnostic]:
    """1.9: a boolean attribute is named after the true value of the flag, with no negations;
    a noun is prefixed with Это, Есть or Содержит (ЭтоАдминистратор, not Администратор)."""
    got = _vid(source)
    if got is None:
        return
    data = got[1]
    booleans: set[str] = set()
    for section in ("Реквизиты", "Измерения", "Ресурсы"):
        for item in data.get(section) or []:
            if isinstance(item, dict) and item.get("Тип") == "Булево" and isinstance(item.get("Имя"), str):
                booleans.add(item["Имя"])
    if not booleans:
        return

    morph = _morph()
    prefixes = ("Это", "Есть", "Содержит")
    for ref in _names(source):
        if ref.name not in booleans:
            continue
        if re.match(r"^(Не|Нет)[А-ЯЁ]", ref.name):
            yield _diag(source, ref, "naming/boolean-name", "naming/boolean-name.negation", name=ref.name)
            continue
        if morph is None or ref.name.startswith(prefixes):
            continue
        head = next(iter(_WORD_RE.findall(ref.name)), "")
        if head and any(p.tag.POS == "NOUN" for p in morph.parse(head)[:1]):
            yield _diag(source, ref, "naming/boolean-name", "naming/boolean-name.noun", name=ref.name)


@rule("naming/presentation", "naming/presentation.title", "D", severity=Severity.WARNING)
def presentation(source: SourceFile) -> Iterable[Diagnostic]:
    """2.1: a top-level element has Представление filled in; for a deprecated one it starts
    with "(не используется)" (1.6). Kinds that have no Представление property are skipped."""
    got = _vid(source)
    if got is None:
        return
    vid, data = got
    from xbsl.rules.yaml_properties import _allowed_for_class, _metamodel

    mm = _metamodel()
    if not mm:
        return
    cls = mm["vid2class"].get(vid)
    if not cls or "Представление" not in _allowed_for_class(cls):
        return  # the kind has no such property - nothing to require

    ref = _object_name(_names(source))
    value = data.get("Представление")
    if not isinstance(value, str) or not value.strip():
        line, col = (ref.line, ref.col) if ref else (1, 1)
        yield Diagnostic(
            source.rel, line, col, "naming/presentation", Severity.WARNING,
            i18n.t("naming/presentation.missing", vid=vid),
        )
        return
    if ref is not None and ref.name.startswith("Устарело") and not value.startswith("(не используется)"):
        yield _diag(source, ref, "naming/presentation", "naming/presentation.deprecated", name=ref.name)


@rule("naming/prefix-by-kind", "naming/prefix-by-kind.title", "D", severity=Severity.WARNING)
def prefix_by_kind(source: SourceFile) -> Iterable[Diagnostic]:
    """Section 3: an access key is КлючДоступа<whose>, a right is ПравоНа<what>, a navigation
    command is Навигация<what>, a switchable one is Команда<what>, localized strings are
    <Project>Локализация; an HTTP service name does not include web or Api."""
    got = _vid(source)
    if got is None:
        return
    vid = got[0]
    ref = _object_name(_names(source))
    if ref is None:
        return

    prefix = KIND_PREFIX_REQUIRED.get(vid)
    if prefix and not ref.name.startswith(prefix):
        yield _diag(source, ref, "naming/prefix-by-kind", "naming/prefix-by-kind.missing",
                    name=ref.name, vid=vid, prefix=prefix, what=i18n.t("naming.prefix-word"))
        return

    suffix = KIND_SUFFIX_REQUIRED.get(vid)
    if suffix and not ref.name.endswith(suffix):
        yield _diag(source, ref, "naming/prefix-by-kind", "naming/prefix-by-kind.missing",
                    name=ref.name, vid=vid, prefix=suffix, what=i18n.t("naming.suffix-word"))
        return

    if vid == "HttpСервис":
        for word in HTTP_FORBIDDEN:
            if re.search(word + r"(?![а-яёa-z])", ref.name):
                yield _diag(source, ref, "naming/prefix-by-kind", "naming/prefix-by-kind.forbidden",
                            word=word, name=ref.name)
                return


i18n.register({
    "naming.prefix-word": {"ru": "префиксом", "en": "prefix"},
    "naming.suffix-word": {"ru": "постфиксом", "en": "suffix"},
})
