"""Russian<->English term pairs of the platform (terms.json).

1C:Element is bilingual: `Запрос` is `Query`, the yaml key `ОбластьВидимости` is
`VisibilityScope`, the value `ВПроекте` is `InProject`. Sources may be written either way,
so anything that matches a platform name by text has to accept both spellings.

The pairs are extracted from the distribution (tools/extract_terms.py) and split by ROLE -
`Ссылка` is the property `Link` and the facet part `Reference`, and only the role tells
which is right. Without the data file every helper degrades to the Russian spelling alone:
a missed English spelling is a false negative, inventing one would be a false positive.
"""

from __future__ import annotations

from xbsl import dataset

SECTIONS = ("types", "facets", "properties", "enums")

_cache: dict[str, dict[str, str]] | None = None
_reverse: dict[str, dict[str, str]] | None = None


def _terms() -> dict[str, dict[str, str]]:
    global _cache
    if _cache is None:
        try:
            data = dataset.load_json("terms.json")
        except Exception:  # noqa: BLE001 - no data, Russian spelling only
            data = {}
        _cache = {section: dict(data.get(section) or {}) for section in SECTIONS}
    return _cache


_common: dict[str, str] | None = None
_common_reverse: dict[str, str] | None = None


def _common_pairs() -> dict[str, str]:
    """{Russian name: English} out of the compiler meta objects (terms_full.json).

    The compact terms.json covers types, facets, yaml properties and enumeration values; the
    names of TYPE MEMBERS and of everything the metamodel annotations leave unnamed - a form
    slot (`Содержимое`), a component property (`Заголовок`) - are only in the full dictionary,
    5254 pairs of them.
    """
    global _common
    if _common is None:
        try:
            data = dataset.load_json("terms_full.json")
        except Exception:  # noqa: BLE001 - no data, Russian spelling only
            data = {}
        _common = dict(data.get("common") or {})
    return _common


def common_english(name: str) -> str | None:
    """The English spelling of any name the compiler dictionary knows, or None."""
    return _common_pairs().get(name)


def common_russian(name: str) -> str | None:
    """The Russian spelling for an English name of the compiler dictionary, or None."""
    global _common_reverse
    if _common_reverse is None:
        _common_reverse = {en: ru for ru, en in _common_pairs().items()}
    return _common_reverse.get(name)


_kinds: dict[str, str] | None = None


def kinds_table() -> dict[str, str]:
    """{Russian element kind: the English spelling the platform's SERIALIZER writes}.

    A section of terms.json read from the serializer's own kind enum of the distribution.
    This is a different vocabulary from the type dictionary: the stdlib TYPE of an
    enumeration is `Enum`, while `ElementKind:` of an English project says `Enumeration`.
    Empty for a dataset generated before the section joined the extractor.
    """
    global _kinds
    if _kinds is None:
        try:
            data = dataset.load_json("terms.json")
        except Exception:  # noqa: BLE001 - no data, Russian spelling only
            data = {}
        _kinds = dict(data.get("kinds") or {})
    return _kinds


def _reset() -> None:
    """Drop the pairs when the data root or version changes (dataset hook).

    Without this the process would keep answering from the previously pinned dataset - a
    pinned root with no terms.json still handed out the English spellings of the old one.
    """
    global _cache, _reverse, _common, _common_reverse, _kinds, _facets
    _facets = None
    _cache = None
    _reverse = None
    _common = None
    _common_reverse = None
    _kinds = None


dataset.register_reset(_reset)


def english(name: str, section: str) -> str | None:
    """The English spelling of a name in the given role, when the platform declares one."""
    return _terms().get(section, {}).get(name)


def russian(name: str, section: str) -> str | None:
    """The Russian spelling for an English name in the given role (the reverse of english)."""
    global _reverse
    if _reverse is None:
        _reverse = {
            section_name: {en: ru for ru, en in pairs.items()}
            for section_name, pairs in _terms().items()
        }
    return _reverse.get(section, {}).get(name)


def forms(name: str, section: str) -> tuple[str, ...]:
    """Both spellings of a name, or just the given one when the platform has no English."""
    other = english(name, section)
    return (name, other) if other else (name,)


_facets: dict[str, str] | None = None


def facet_suffix_english(name: str) -> str | None:
    """The English spelling of a FACET suffix - the part after the dot of a type name.

    `Ссылка` is `Reference` as a facet while the property vocabulary calls the same word
    `Link`, and the entity protocol of an object module speaks the facet language. The table
    is built from the facet section, whose keys carry the owner (`BinaryObject.Reference`):
    the suffix pair holds for every owner, project types included. A suffix two facets spell
    differently is dropped rather than guessed - today there is none.
    """
    global _facets
    if _facets is None:
        table: dict[str, str] = {}
        dropped: set[str] = set()
        for russian, english in _terms().get("facets", {}).items():
            if "." not in russian or "." not in english:
                continue
            ru_suffix, en_suffix = russian.rsplit(".", 1)[1], english.rsplit(".", 1)[1]
            if ru_suffix in dropped:
                continue
            known = table.get(ru_suffix)
            if known is not None and known != en_suffix:
                del table[ru_suffix]
                dropped.add(ru_suffix)
                continue
            table[ru_suffix] = en_suffix
        _facets = table
    return _facets.get(name)


def key_forms(*names: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Both spellings of yaml keys, Russian first.

    A key is looked up as a property and then as a type name - a yaml key may repeat the
    name of a type (`Версия`). `extra` adds spellings seen in real artifacts that the
    metamodel does not declare: the library manifest writes `Vendor`, but no
    `@PropertyInfo` pairs it with `Поставщик`.
    """
    out: list[str] = []
    for name in (*names, *extra):
        candidates = (name,) if name in out else forms(name, "properties")
        if len(candidates) == 1 and name not in extra:
            candidates = forms(name, "types")
        for form in candidates:
            if form not in out:
                out.append(form)
    return tuple(out)
