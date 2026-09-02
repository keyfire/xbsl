"""Russian -> English spellings of PLATFORM tokens, one facade for the translator.

Every pair comes from the generated dataset - the distribution's own vocabulary - never from
a translation: an unknown name is answered with None, the token stays as written and the
caller reports it. The flat dictionaries carry only the names the whole platform agrees on
(an ambiguous one such as `Ссылка` - Reference as a facet, Link as a property - is excluded
at extraction time), so a flat hit is safe by construction. The project dictionary
(dictionary.py) always wins over these tables: a project may name its own method after a
platform word, and one spelling must keep meaning one thing after the rewrite exactly as it
did before.
"""

from __future__ import annotations

import re
from functools import lru_cache

from xbsl import dataset, metamodel, terms, typeinfer, uischema


def _reset() -> None:
    for cached in (keyword_english, _query_english, query_phrases, _component_english,
                   ident_english, member_english, _metamodel_enum_value, _ui_enum_tables,
                   _unanimous_enum_value):
        cached.cache_clear()


dataset.register_reset(_reset)


@lru_cache(maxsize=1)
def keyword_english() -> dict[str, str]:
    """{Russian keyword form: the English form of the same case} out of the grammar tables.

    "Выбор" -> `Case` and "выбор" -> `case`: the grammar lists every form, and the pair keeps
    the case of the first letter, so a rewritten keyword looks exactly like the author wrote
    the rest of the file.
    """
    pairs: dict[str, str] = {}
    try:
        table = (dataset.load_json("language.json") or {}).get("keywords") or {}
    except Exception:  # noqa: BLE001 - no data, no substitution
        table = {}
    for record in table.values():
        forms = record.get("forms") if isinstance(record, dict) else None
        if not forms:
            continue
        english = [f for f in forms if f.isascii()]
        russian = [f for f in forms if not f.isascii()]
        for word in russian:
            upper = word[:1].isupper()
            match = next((f for f in english if f[:1].isupper() == upper), None)
            if match:
                pairs[word] = match
    return pairs


@lru_cache(maxsize=1)
def query_phrases() -> dict[tuple[str, ...], tuple[str, ...]]:
    """{the words of a query PHRASE: its English words}, both upper-cased.

    The query language has multi-word keywords, and a word inside one may mean something else
    on its own: "ПО" is `ON` after a join and `BY` after GROUP or ORDER. Translating word by
    word therefore produces a query the compiler refuses ("ORDER ON"), which is exactly what a
    real project turned into. Phrases are matched first, longest first.
    """
    try:
        section = (dataset.load_json("terms.json") or {}).get("query") or {}
    except Exception:  # noqa: BLE001 - no data, no phrases
        return {}
    out: dict[tuple[str, ...], tuple[str, ...]] = {}
    for russian, english in section.items():
        words = tuple(russian.upper().split())
        if len(words) < 2:
            continue
        out[words] = tuple(english.upper().split())
    return out


#: Query-language words the extracted table misses or spells wrong, taken from the platform
#: documentation ("Синтаксис текста запросов"). The table is built out of the compiler data,
#: and the LITERALS are not in it at all: without them `!= НЕОПРЕДЕЛЕНО` fell through to the flat
#: dictionary, which answers `NULL` for it - a reserved word of its own that no Russian
#: spelling maps to. The compiler accepts the result, so nothing fails at build time; at run
#: time a condition against `NULL` is never true, and the query silently returns nothing.
_VERIFIED_QUERY_SPELLINGS: dict[str, str] = {
    "ИСТИНА": "TRUE",
    "ЛОЖЬ": "FALSE",
    "НЕОПРЕДЕЛЕНО": "UNDEFINED",
    "ВРЕМЕННУЮ": "TEMPORARY",
    "ДЛЯ": "FOR",
    "ИНДЕКСИРОВАТЬ": "INDEX",
    "СОЗДАТЬ": "CREATE",
    "ТАБЛИЦУ": "TABLE",
}

#: Words the extracted table pairs with something that is not an English keyword at all (a
#: transliteration left by the extractor). Answering with one of these would produce a query
#: the compiler refuses, so the word is left alone instead.
_QUERY_SPELLINGS_TO_DROP: frozenset[str] = frozenset({"ОТ"})


@lru_cache(maxsize=1)
def _query_english() -> dict[str, str]:
    """{RUSSIAN query keyword, upper-cased: the English keyword} - SINGLE words only.

    A word that also appears inside a phrase is left to `query_phrases`: alone it may mean
    something else entirely.
    """
    try:
        section = (dataset.load_json("terms.json") or {}).get("query") or {}
    except Exception:  # noqa: BLE001 - no data, no substitution
        return dict(_VERIFIED_QUERY_SPELLINGS)
    out: dict[str, str] = {}
    dropped: set[str] = set()

    def put(russian: str, english: str) -> None:
        if russian in dropped:
            return
        known = out.get(russian)
        if known is not None and known != english:
            del out[russian]
            dropped.add(russian)
            return
        out[russian] = english

    for russian, english in section.items():
        key = russian.upper()
        if " " in key:
            continue
        if len(english.split()) == 1:
            put(key, english.upper())
    for key in _QUERY_SPELLINGS_TO_DROP:
        out.pop(key, None)
    out.update(_VERIFIED_QUERY_SPELLINGS)
    return out


def query_keyword_english(word: str) -> str | None:
    """The English spelling of a query-language KEYWORD, or None.

    A keyword is written in upper case in this language, and the sources follow that: a word
    in mixed case inside a query is a field, a table or an alias, not a keyword. Without that
    test the vocabulary answered a FIELD named like a keyword (a reference field came out as
    the type-test operator), and the compiler refused the query.

    The general term dictionary must NOT answer here either: a reverse lookup over it pulls
    words that are not query keywords at all.
    """
    if word != word.upper():
        return None
    return _query_english().get(word)


def facet_suffix_english(name: str) -> str | None:
    """The English spelling of a facet suffix (the part after the dot of a type)."""
    return terms.facet_suffix_english(name)


@lru_cache(maxsize=1)
def _component_english() -> dict[str, str]:
    """{Russian component type: its English spelling} - the forward view of the ui schema."""
    return {russian: english for english, russian in uischema.component_aliases().items()}


#: Property spellings the extracted ui vocabulary gets WRONG, corrected against the compiler
#: on a throwaway project. The uiterms table is built by pairing constant pools, and a shift
#: there mis-pairs whole runs of names; a wrong pair here is not a missing translation but a
#: confident wrong one, and the build refuses it ("unknown property"). Each entry below was
#: accepted by the compiler in the spelling on the right and refused in the extracted one.
_VERIFIED_PROPERTY_SPELLINGS: dict[str, str] = {
    "МинимальноеЗначение": "MinValue",
    "МаксимальноеЗначение": "MaxValue",
    "ШагИзменения": "ChangeStep",
    "ДлинаЦелойЧасти": "IntegerPartLength",
}


#: Member spellings the flat compiler dictionary gets wrong for the receivers a project
#: actually uses. The flat section holds ONE spelling per word, and where the platform names
#: the same word differently by owner, that one is a coin toss; each entry below was refused
#: by the compiler in the flat spelling and accepted in the one on the right.
_VERIFIED_MEMBER_SPELLINGS: dict[str, str] = {
    "УдалитьПоИндексу": "RemoveByIndex",
    "Символ": "CharAt",
    "ПолучитьСтроки": "GetLines",
    "Обрезать": "Crop",
}


@lru_cache(maxsize=1)
def _member_names() -> frozenset[str]:
    """Every name the platform declares as a MEMBER of a type, whatever the type.

    The receiver of a call is not always known - a chain of calls, a variable of an inferred
    type - so this is a name check, not a lookup: it answers whether the word after a dot is
    something the PLATFORM declares at all.
    """
    try:
        std = dataset.load_json("stdlib.json") or {}
    except Exception:  # noqa: BLE001 - no data, no answer
        return frozenset()
    out: set[str] = set()
    for table in ("type_members", "object_members", "manager_members", "facet_members"):
        for members in (std.get(table) or {}).values():
            groups = members.values() if isinstance(members, dict) else ()
            for group in groups:
                for member in group if isinstance(group, list) else ():
                    name = member.get("name") if isinstance(member, dict) else member
                    if isinstance(name, str) and name:
                        out.add(name)
    return frozenset(out)


def is_member_name(name: str) -> bool:
    """True when the platform itself declares a member spelled that way.

    What it answers is "whose gap is this": a word after a dot that no table spells in English
    is the DATA's gap when the platform declares it, and the project's own only otherwise. The
    difference matters at the dictionary: an English name invented for a platform member is
    refused by the compiler, and no dictionary entry can be right.
    """
    return bool(name) and name in _member_names()


def verified_member(name: str) -> str | None:
    """The checked spelling of a member the flat dictionary gets wrong, whatever the receiver.

    The receiver of a call is not always known - a value read off a project object, a chain
    of calls - and the flat dictionary answers `Symbol` for the string method the compiler
    only takes as `CharAt`; the checked table answers for such a receiver too.
    """
    return _VERIFIED_MEMBER_SPELLINGS.get(name)


def member_of(owner: str, name: str) -> str | None:
    """The English spelling of `name` as a member OF `owner`, or None.

    The flat dictionary keeps one spelling per word, and where the platform names the same
    word differently by receiver that one is a coin toss: `Загрузить` is `Load` on a binary
    object and `Upload` on the object storage, and the wrong half is refused by the compiler.
    `owner` may be given in either spelling - the table is keyed by the English name. The
    owner table and the walk over the type's ancestors live in terms.member_english_of, shared
    with the member rules of the linter, so the two read one and the same vocabulary.
    """
    if not owner or not name:
        return None
    verified = _VERIFIED_MEMBER_SPELLINGS.get(name)
    if verified:
        # The checked spelling answers before the owner table for the same reason it answers
        # before the flat one: it exists because the data is wrong about this word, and the
        # data is wrong about it under its owner too (`Символ` of a String is `CharAt`, which
        # the compiler takes, and the table says `Symbol`, which it refuses).
        return verified
    return terms.member_english_of(owner, name)


def component_member_english(name: str) -> str | None:
    """The English spelling of a member reached through a form COMPONENT, or None.

    A component answers with the ui vocabulary, not the general one: the built-in command of
    a table is `Remove` there while the flat dictionary spells the same word `Delete` (right
    for a collection, wrong for the table), and the build refuses the form.
    """
    return property_english(name) or _VERIFIED_MEMBER_SPELLINGS.get(name)


def property_english(name: str) -> str | None:
    """The English spelling of a component property, the verified corrections applied first."""
    verified = _VERIFIED_PROPERTY_SPELLINGS.get(name)
    if verified:
        return verified
    return uischema.english_property(name)


def type_english(name: str) -> str | None:
    """The English spelling of a platform TYPE, or None - members are not consulted here."""
    return terms.english(name, "types") or component_english(name)


def is_platform_type(name: str) -> bool:
    """Whether the platform declares a TYPE spelled so, in either language.

    The type catalog and the type pairs answer; the flat compiler dictionary does not, because
    it pairs every word the platform uses anywhere, member names included, and a project
    structure named after one of those is still the project's.
    """
    if not name:
        return False
    return bool(
        terms.english(name, "types") or terms.russian(name, "types")
        or typeinfer.is_type_name(name) or component_english(name)
    )


def component_english(name: str) -> str | None:
    """The English spelling of a form component type, or None."""
    return _component_english().get(name)


def enum_value_of(enum: str, value: str) -> str | None:
    """The English spelling of `value` when `enum` really is a platform enumeration, else None.

    Used where the ROOT of a chain is known by name only: it answers nothing for a receiver
    that is not an enumeration, so an ordinary member lookup can take over.
    """
    if not enum or not value:
        return None
    per_enum = uischema.enum_value_aliases(enum)
    if per_enum:
        return per_enum.get(value)
    return _metamodel_enum_value(enum, value)


def enum_value_english(enum: str, value: str) -> str | None:
    """The English spelling of one enumeration's value, or None.

    Per enumeration on purpose - globally the same Russian word answers to several English
    ones (`Обычная` is Common, Normal and Usual). The interface enumerations come from
    uiterms; a metamodel enumeration is matched by its VALUE SET (its class name is English
    and the uiterms table is keyed by the Russian names), and the flat unambiguous section
    is the last resort.
    """
    if enum:
        per_enum = uischema.enum_value_aliases(enum)
        english = per_enum.get(value)
        if english:
            return english
        english = _metamodel_enum_value(enum, value)
        if english:
            return english
    return terms.english(value, "enums") or _unanimous_enum_value(value)


@lru_cache(maxsize=None)
def _unanimous_enum_value(value: str) -> str | None:
    """The spelling of a value EVERY enumeration that carries it agrees on, or None.

    The last resort for a value whose enumeration could not be pinned (a generic component
    the schema does not list): "Подменю" answers one spelling in every enumeration that has it, while
    a genuinely ambiguous "Обычная" collects three spellings and honestly stays None.
    """
    spellings = {
        pairs[value]
        for pairs in _ui_enum_tables().values()
        if value in pairs
    }
    return spellings.pop() if len(spellings) == 1 else None


@lru_cache(maxsize=None)
def _metamodel_enum_value(enum_class: str, value: str) -> str | None:
    """A metamodel enumeration's value, matched into uiterms by the value set.

    The metamodel names its enumerations in English (`EventImportance`) while uiterms is
    keyed by the Russian names, so the bridge is the values themselves: every uiterms
    enumeration whose Russian values all belong to the metamodel one is a candidate, and
    the spelling is taken only when every candidate agrees on it.
    """
    values = set(metamodel.enum_values(enum_class))
    if not values:
        return None
    spellings: set[str] = set()
    for pairs in _ui_enum_tables().values():
        if value not in pairs or not set(pairs).issubset(values):
            continue
        spellings.add(pairs[value])
    return spellings.pop() if len(spellings) == 1 else None


@lru_cache(maxsize=1)
def _ui_enum_tables() -> dict[str, dict[str, str]]:
    try:
        data = dataset.load_json("uiterms.json") or {}
    except Exception:  # noqa: BLE001 - no data, no pairs
        return {}
    return {
        name: dict(pairs)
        for name, pairs in (data.get("enum_values") or {}).items()
        if isinstance(pairs, dict)
    }


_PARAMETRIC_TYPE_RE = re.compile(r"^(.*?[^\d_])(\d+(?:_\d+)?)$")


@lru_cache(maxsize=None)
def member_english(name: str) -> str | None:
    """The English spelling of a name standing AFTER A DOT - a member, or None.

    The verified corrections answer first: where the flat dictionary holds a spelling the
    compiler refuses for the receivers a project uses, the checked one wins.

    The compiler dictionary answers first here: after a dot the name is a member, and where
    the two dictionaries disagree the member reading is the right one (the same word is the
    type `Strings` and the member `Rows`).
    """
    return (
        _VERIFIED_MEMBER_SPELLINGS.get(name)
        or terms.common_english(name)
        or terms.english(name, "properties")
        or terms.english(name, "types")
    )


@lru_cache(maxsize=None)
def ident_english(name: str) -> str | None:
    """The English spelling of a platform identifier standing on its own, or None.

    A bare name is a TYPE (or a variable), so the type dictionaries answer first and the
    compiler dictionary of members last - it also carries member names, and those would
    otherwise win over the type of the same spelling. Enumeration VALUES are deliberately
    not consulted - out of their enumeration they are ambiguous. A parameterized type
    spelling ("Число2" - a Number of two digits) is paired through its base: the digits are
    the platform's own naming scheme, not part of the name.
    """
    direct = (
        terms.english(name, "types")
        or component_english(name)
        or terms.common_english(name)
    )
    if direct:
        return direct
    m = _PARAMETRIC_TYPE_RE.match(name)
    if m:
        base = terms.english(m.group(1), "types")
        if base:
            return base + m.group(2)
    return None


def kind_english(kind: str) -> str | None:
    """The `ElementKind` value as an English project writes it - `Enumeration` and kin.

    The serializer's own vocabulary, not the stdlib type names (the TYPE of an enumeration
    is `Enum`, the kind is `Enumeration`): the distribution's table when the dataset carries
    one, the metamodel's proven spellings otherwise.
    """
    english = terms.kinds_table().get(kind)
    if english:
        return english
    # The metamodel builds the reverse map from the same proven constant; walking it forward
    # here keeps one source of truth without exporting the constant.
    for en, ru in metamodel._english_kinds().items():  # noqa: SLF001 - same-package data view
        if ru == kind and en != kind:
            return en
    return None


def boolean_english(value: str) -> str | None:
    """The boolean keyword as an English yaml writes it (`True`/`False`), or None."""
    return keyword_english().get(value)
