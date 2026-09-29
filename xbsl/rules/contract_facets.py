"""Tier A: the restrictions of an entity contract implementation must agree with the contract.

Two project rules over the yaml of an entity contract (`EntityContract`) and of the elements
that implement it (`TypeOptions: <Kind>.Object: Contracts: - <Contract>.Object`). A property of
the contract is overridden by the attribute of the same name, and the compiler holds the
restrictions of the two against each other - the string length, and for a number the lengths of
the integer and fractional parts and the bounds. Both rules need two files, so both are
project-wide. Either spelling of a file is read.

yaml/contract-facet-mismatch - a regular attribute (and an attribute of a tabular section that
overrides an attribute of a contract table). The checks follow the compiler's own order, and a
live probe reproduced every branch:

- the property has no restriction, the attribute has one - "Restrictions must not be set for
  the attribute that overrides entity contract property"; a restriction here is ANY key of the
  group, not only the length: `Multiline` or `LengthControl` alone make the attribute a
  restricted string just the same (both failed in the probe), and a nullable `String?` changes
  nothing. A read-only property (`ReadOnly: True`) lets the attribute be restricted;
- the property is restricted, the attribute is not - "No restrictions are set ..." (a
  read-only property demands it too);
- both are restricted - the values must be EQUAL ("... must be equal to 50"), and for a
  read-only property the attribute may be stricter but not wider ("... cannot be greater than
  50"). An attribute of a number restricted by one key takes the documented defaults for the
  rest (integer part 10, fractional part 0), so `IntegerPartLength: 12` alone against a
  property with a fractional part 2 fails on the fractional part; a bound the property sets and
  the attribute does not is "No maximum value is specified ..." (or minimal).

yaml/contract-standard-length - a STANDARD attribute of the implementation (`Name` of a catalog,
`Code`, `Number` of a document): its length (`Length`, default 150, 7 and 9) meets the
`MaxLength` of the property (for a numeric code - `IntegerPartLength`). A property with no
length at all gives "The maximum length for property ... is not set in entity contract" - a
standard attribute always has one; a length other than the attribute's gives "The length of
attribute ... that overrides the property of entity contract ... must be equal to 100"; a
read-only property only caps it ("... cannot exceed 100"). The probe reproduced all three on a
catalog and the first one on `Code` and on the `Number` of a document.

Narrowing, to keep the zero-false-positive bar: the attribute and the property must declare the
same type (a type mismatch is another error of its own); an array type (the restrictions then
belong to the items) and a union of a string with a number (the compiler's notion of a set
restriction is shared between the two there) are left alone; a contract is found by its short
name and skipped when two contracts of the project share it; only the direct properties of the
contract are compared - a property inherited from a base contract is not read.

Quick fixes where the cure is mechanical: an unequal or too wide string length of an attribute
is set to the property's value, a missing one is added after `Type`, and a length of a standard
attribute is set to the property's value. A restriction the property does not allow and a
length the contract lacks are left to the author: there the fix is a decision (drop the
restriction or restrict the contract too), or it lives in the other file.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _parsed, object_kind

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/contract-facet-mismatch.title": {
        "ru": "Ограничения реквизита расходятся со свойством контракта",
        "en": "Attribute restrictions disagree with the contract property",
    },
    "yaml/contract-facet-mismatch.unexpected": {
        "ru": "Реквизит '{attr}' переопределяет свойство контракта '{contract}', у которого "
              "ограничений нет, а сам ограничен ({keys}): сервер отвергнет сборку с "
              "'Restrictions must not be set for the attribute that overrides entity contract "
              "property'. Снимите ограничение или задайте такое же у свойства контракта.",
        "en": "Attribute '{attr}' overrides a property of contract '{contract}' that has no "
              "restrictions, while the attribute is restricted ({keys}): the server rejects "
              "the build with 'Restrictions must not be set for the attribute that overrides "
              "entity contract property'. Drop the restriction or set the same one on the "
              "contract property.",
    },
    "yaml/contract-facet-mismatch.missing": {
        "ru": "Свойство '{attr}' контракта '{contract}' ограничено ({keys}), а переопределяющий "
              "его реквизит – нет: сервер отвергнет сборку с 'No restrictions are set for the "
              "attribute that overrides entity contract property'. Задайте реквизиту те же "
              "ограничения.",
        "en": "Property '{attr}' of contract '{contract}' is restricted ({keys}), while the "
              "attribute that overrides it is not: the server rejects the build with 'No "
              "restrictions are set for the attribute that overrides entity contract "
              "property'. Give the attribute the same restrictions.",
    },
    "yaml/contract-facet-mismatch.missing-bound": {
        "ru": "У свойства '{attr}' контракта '{contract}' задано {key}: {expected}, а у "
              "переопределяющего его реквизита – нет: сервер отвергнет сборку с 'No ... value "
              "is specified for the attribute that overrides entity contract property'. "
              "Укажите реквизиту {key}: {expected}.",
        "en": "Property '{attr}' of contract '{contract}' sets {key}: {expected}, while the "
              "attribute that overrides it does not: the server rejects the build with 'No "
              "... value is specified for the attribute that overrides entity contract "
              "property'. Set {key}: {expected} on the attribute.",
    },
    "yaml/contract-facet-mismatch.differs": {
        "ru": "{key} реквизита '{attr}' – {actual}, а у свойства контракта '{contract}' – "
              "{expected}: значения должны совпадать, иначе сервер отвергнет сборку ('... must "
              "be equal to {expected}'). Укажите {key}: {expected}.",
        "en": "{key} of attribute '{attr}' is {actual}, while the property of contract "
              "'{contract}' has {expected}: the values must be equal, or the server rejects the "
              "build ('... must be equal to {expected}'). Set {key}: {expected}.",
    },
    "yaml/contract-facet-mismatch.exceeds": {
        "ru": "{key} реквизита '{attr}' – {actual}, больше, чем {expected} у свойства "
              "контракта '{contract}' только для чтения: реализация может быть строже "
              "контракта, но не шире ('... cannot be greater than {expected}').",
        "en": "{key} of attribute '{attr}' is {actual}, above the {expected} of the read-only "
              "property of contract '{contract}': an implementation may be stricter than the "
              "contract, not wider ('... cannot be greater than {expected}').",
    },
    "yaml/contract-facet-mismatch.below": {
        "ru": "{key} реквизита '{attr}' – {actual}, меньше, чем {expected} у свойства "
              "контракта '{contract}' только для чтения: реализация может быть строже "
              "контракта, но не шире ('... cannot be less than {expected}').",
        "en": "{key} of attribute '{attr}' is {actual}, below the {expected} of the read-only "
              "property of contract '{contract}': an implementation may be stricter than the "
              "contract, not wider ('... cannot be less than {expected}').",
    },
    "yaml/contract-standard-length.title": {
        "ru": "Длина стандартного реквизита расходится со свойством контракта",
        "en": "Standard attribute length disagrees with the contract property",
    },
    "yaml/contract-standard-length.not-set": {
        "ru": "Стандартный реквизит '{attr}' имеет длину {length}, а у свойства '{attr}' "
              "контракта '{contract}' нет ключа {key}: сервер отвергнет сборку с '{quote}'. "
              "Задайте свойству {key}: {length} или объявите его {readonly}.",
        "en": "Standard attribute '{attr}' has the length {length}, while property '{attr}' "
              "of contract '{contract}' sets no {key}: the server rejects the build with "
              "'{quote}'. Set {key}: {length} on the property or declare it {readonly}.",
    },
    "yaml/contract-standard-length.differs": {
        "ru": "Длина стандартного реквизита '{attr}' – {length}, а у свойства контракта "
              "'{contract}' {key}: {expected}: они должны совпадать ('... must be equal to "
              "{expected}'). Задайте реквизиту {length_key}: {expected} или объявите свойство "
              "{readonly}.",
        "en": "The length of standard attribute '{attr}' is {length}, while the property of "
              "contract '{contract}' has {key}: {expected}: they must be equal ('... must be "
              "equal to {expected}'). Set {length_key}: {expected} on the attribute or declare "
              "the property {readonly}.",
    },
    "yaml/contract-standard-length.exceeds": {
        "ru": "Длина стандартного реквизита '{attr}' – {length}, больше, чем {key}: {expected} "
              "у свойства контракта '{contract}' только для чтения ('... cannot exceed "
              "{expected}').",
        "en": "The length of standard attribute '{attr}' is {length}, above {key}: {expected} "
              "of the read-only property of contract '{contract}' ('... cannot exceed "
              "{expected}').",
    },
}
i18n.register(MESSAGES)

#: Every key the rules read, in the metamodel's (Russian) spelling.
_KEYS = (
    "Имя", "Ид", "Тип", "Свойства", "Реквизиты", "ТабличныеЧасти", "НастройкиТипов",
    "Контракты", "ТолькоЧтение", "Длина", "МаксимальнаяДлина", "Многострочная",
    "КонтрольДлины", "ДлинаЦелойЧасти", "ДлинаДробнойЧасти", "МаксимальноеЗначение",
    "МинимальноеЗначение", "КонтрольПредельныхЗначений", "КонтрольДробнойЧасти",
)
#: The restriction groups. A contract property knows only the values (its facets are the
#: base ones); an attribute also has the switches, and any of them creates the group.
_STRING_KEYS = ("МаксимальнаяДлина", "Многострочная", "КонтрольДлины")
_NUMBER_VALUE_KEYS = (
    "ДлинаЦелойЧасти", "ДлинаДробнойЧасти", "МаксимальноеЗначение", "МинимальноеЗначение",
)
_NUMBER_KEYS = _NUMBER_VALUE_KEYS + ("КонтрольПредельныхЗначений", "КонтрольДробнойЧасти")
#: The documented defaults of a number restriction (metamodel: NumberAttributeFacet).
_INT_DEFAULT = 10
_FRACT_DEFAULT = 0
#: Standard attributes that carry a length - (kinds, the type when none is written, the
#: default length; metamodel: NameAttributeDescriptor, CodeAttributeDescriptor,
#: NumberAttributeDescriptor).
_STANDARD = {
    "Наименование": (("Справочник", "ПланОбмена", "ИнтегрируемоеПриложение"), "Строка", 150),
    "Код": (("Справочник", "ПланОбмена", "ИнтегрируемоеПриложение"), "Строка", 7),
    "Номер": (("Документ",), "Строка", 9),
}
_STANDARD_CLASSES = {
    "Наименование": "CatalogNameAttribute", "Код": "CodeAttributeDescriptor",
    "Номер": "NumberAttributeDescriptor",
}
_TRUE = frozenset({"Истина", "True", "true"})
_NULLABLE = frozenset({"?", "Неопределено", "Undefined"})
_OBJECT_FACET = "Объект"


@lru_cache(maxsize=1)
def _aliases() -> dict[str, str]:
    """{any spelling of a key: its Russian spelling} - a translated project is read alike."""
    out = {key: key for key in _KEYS}
    for key in _KEYS:
        english = metamodel.english_name(key)
        if english:
            out.setdefault(english, key)
    return out


@lru_cache(maxsize=1)
def _type_words() -> dict[str, str]:
    """{spelling: Russian} for the two types the restrictions belong to."""
    out: dict[str, str] = {}
    for word in ("Строка", "Число"):
        for form in terms.forms(word, "types") or (word,):
            out[form] = word
        out[word] = word
    return out


@lru_cache(maxsize=1)
def _standard_names() -> dict[str, str]:
    """{spelling: Russian} of the standard attributes, the English one from the metamodel."""
    out = {name: name for name in _STANDARD}
    for name, cls in _STANDARD_CLASSES.items():
        english = metamodel.dispatch_english(cls)
        if english:
            out[english] = name
    return out


@lru_cache(maxsize=1)
def _object_facets() -> frozenset[str]:
    english = terms.facet_suffix_english(_OBJECT_FACET)
    return frozenset(name for name in (_OBJECT_FACET, english) if name)


for _cache in (_aliases, _type_words, _standard_names, _object_facets):
    dataset.register_reset(_cache.cache_clear)


# --- reading the files -----------------------------------------------------------------------


def _entries(mapping) -> dict:
    """{Russian key: (key node, value node)} of a composed mapping, scalar keys only."""
    aliases = _aliases()
    out: dict = {}
    for key_node, value_node in mapping.value:
        if isinstance(key_node, yaml.ScalarNode):
            out.setdefault(aliases.get(key_node.value, key_node.value), (key_node, value_node))
    return out


def _scalar(entries: dict, key: str) -> str | None:
    entry = entries.get(key)
    if entry is None or not isinstance(entry[1], yaml.ScalarNode):
        return None
    return entry[1].value


def _items(entries: dict, key: str) -> list:
    entry = entries.get(key)
    if entry is None or not isinstance(entry[1], yaml.SequenceNode):
        return []
    return [node for node in entry[1].value if isinstance(node, yaml.MappingNode)]


def _type_set(text: str | None) -> tuple[str, ...] | None:
    """The alternatives of a type as a sorted tuple, `?` for the empty member; None - a type
    the rules do not judge (a generic, an array)."""
    if not text or "<" in text:
        return None
    words = _type_words()
    out: set[str] = set()
    for alt in (a.strip() for a in text.split("|")):
        if not alt:
            return None
        if alt in _NULLABLE:
            out.add("?")
            continue
        if alt.endswith("?"):
            out.add("?")
            alt = alt[:-1].strip()
        out.add(words.get(alt, alt))
    return tuple(sorted(out))


def _number(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return None


def _point(node) -> tuple[int, int, int, int]:
    """(line, column, start, end) of a value node - a position and a replaceable span."""
    quote = 1 if node.style in ("'", '"') else 0
    return (node.start_mark.line + 1, node.start_mark.column + 1 + quote,
            node.start_mark.index, node.end_mark.index)


def _restrictions(entries: dict, source: SourceFile, contract_side: bool) -> dict:
    """The restriction groups of a property or an attribute, with the positions of the keys."""
    string_keys = ("МаксимальнаяДлина",) if contract_side else _STRING_KEYS
    number_keys = _NUMBER_VALUE_KEYS if contract_side else _NUMBER_KEYS
    info: dict = {"keys": {}}
    for key in set(string_keys) | set(number_keys):
        entry = entries.get(key)
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        line, col, start, end = _point(entry[1])
        raw_ok = not entry[1].style and source.text[start:end] == entry[1].value
        info["keys"][key] = (entry[0].value, entry[1].value, line, col, start, end, raw_ok)
    written = info["keys"]
    if any(key in written for key in string_keys):
        length = _number(written.get("МаксимальнаяДлина", (None, None))[1])
        info["str"] = int(length) if length is not None else 0
    if any(key in written for key in number_keys):
        whole = _number(written.get("ДлинаЦелойЧасти", (None, None))[1])
        fract = _number(written.get("ДлинаДробнойЧасти", (None, None))[1])
        info["num"] = (
            int(whole) if whole is not None else _INT_DEFAULT,
            int(fract) if fract is not None else _FRACT_DEFAULT,
            _number(written.get("МинимальноеЗначение", (None, None))[1]),
            _number(written.get("МаксимальноеЗначение", (None, None))[1]),
        )
    return info


def _member(mapping, source: SourceFile, contract_side: bool) -> dict | None:
    """What the rules need of one property or attribute."""
    entries = _entries(mapping)
    name = _scalar(entries, "Имя")
    if not name:
        return None
    name_node = entries["Имя"][1]
    record = _restrictions(entries, source, contract_side)
    record["name"] = name
    record["id"] = "Ид" in entries
    record["types"] = _type_set(_scalar(entries, "Тип"))
    record["typed"] = "Тип" in entries
    record["ro"] = _scalar(entries, "ТолькоЧтение") in _TRUE
    record["at"] = (name_node.start_mark.line + 1, name_node.start_mark.column + 1)
    type_entry = entries.get("Тип")
    if type_entry is not None and isinstance(type_entry[1], yaml.ScalarNode):
        # Where a missing key goes: a line of its own right after `Type`, at the same indent.
        record["after_type"] = (_line_end(source.text, type_entry[1].end_mark.index),
                                type_entry[0].start_mark.column, type_entry[0].value)
    record["after_name"] = (_line_end(source.text, name_node.end_mark.index),
                            entries["Имя"][0].start_mark.column, entries["Имя"][0].value)
    length = entries.get("Длина")
    if length is not None and isinstance(length[1], yaml.ScalarNode):
        line, col, start, end = _point(length[1])
        raw_ok = not length[1].style and source.text[start:end] == length[1].value
        record["length"] = (length[0].value, length[1].value, line, col, start, end, raw_ok)
    return record


def _line_end(text: str, index: int) -> int:
    end = text.find("\n", index)
    return len(text) if end < 0 else end


def _contract_names(entries: dict) -> list[str]:
    """Short names of the entity contracts the element implements (`X.Объект` entries)."""
    options = entries.get("НастройкиТипов")
    if options is None or not isinstance(options[1], yaml.MappingNode):
        return []
    facets = _object_facets()
    names: list[str] = []
    for key_node, value_node in options[1].value:
        if not isinstance(key_node, yaml.ScalarNode) or not isinstance(value_node, yaml.MappingNode):
            continue
        if key_node.value.rsplit(".", 1)[-1] not in facets:
            continue
        contracts = _entries(value_node).get("Контракты")
        if contracts is None or not isinstance(contracts[1], yaml.SequenceNode):
            continue
        for node in contracts[1].value:
            if not isinstance(node, yaml.ScalarNode):
                continue
            head, _, facet = node.value.strip().rpartition(".")
            if facet in facets and head:
                names.append(head.rsplit("::", 1)[-1])
    return names


def _mapper(source: SourceFile) -> dict | None:
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    text = source.text
    if "Контракт" not in text and "Contract" not in text:
        return None  # neither a contract nor an implementation - the cheap gate
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    if kind is None:
        return None
    root = _composed(source)
    if root is None or not isinstance(root, yaml.MappingNode):
        return None
    top = _entries(root)
    name = _scalar(top, "Имя")
    if not name:
        return None
    if kind == "КонтрактСущности":
        props = {}
        for item in _items(top, "Свойства"):
            member = _member(item, source, contract_side=True)
            if member:
                props.setdefault(member["name"], member)
        tables = {}
        for table in _items(top, "ТабличныеЧасти"):
            table_entries = _entries(table)
            table_name = _scalar(table_entries, "Имя")
            if not table_name:
                continue
            tables[table_name] = {
                m["name"]: m for m in (
                    _member(item, source, contract_side=True)
                    for item in _items(table_entries, "Реквизиты")
                ) if m
            }
        return {"contract": {"name": name, "props": props, "tables": tables}}
    contracts = _contract_names(top)
    if not contracts:
        return None
    attrs = [m for m in (_member(item, source, contract_side=False)
                         for item in _items(top, "Реквизиты")) if m]
    tables = {}
    for table in _items(top, "ТабличныеЧасти"):
        table_entries = _entries(table)
        table_name = _scalar(table_entries, "Имя")
        if table_name:
            tables[table_name] = [m for m in (_member(item, source, contract_side=False)
                                              for item in _items(table_entries, "Реквизиты")) if m]
    return {"impl": {"kind": kind, "contracts": contracts, "attrs": attrs, "tables": tables}}


# --- judging ---------------------------------------------------------------------------------


def _key_word(record: dict, key: str) -> str:
    """The key as the file of the record spells it (the English file gets the English key)."""
    written = record["keys"].get(key)
    if written:
        return written[0]
    type_key = (record.get("after_type") or record["after_name"])[2]
    if type_key in ("Тип", "Имя"):
        return key
    return metamodel.english_name(key) or key


def _set_value_fix(record: dict, key: str, value: int, anchor: str) -> TextEdit | None:
    """Set `key: value` on the item: replace a plain written value, or add a line after the
    anchor line (`after_type` / `after_name`) at the same indent."""
    written = record["keys"].get(key) if key != "Длина" else record.get("length")
    if written is not None:
        _word, _raw, _line, _col, start, end, raw_ok = written
        return TextEdit(start, end, str(value)) if raw_ok else None
    place = record.get(anchor)
    if place is None:
        return None
    offset, indent, _word = place
    return TextEdit(offset, offset, "\n" + " " * indent + f"{_key_word(record, key)}: {value}")


def _position(record: dict, key: str | None) -> tuple[int, int]:
    if key is not None:
        written = record["keys"].get(key) if key != "Длина" else record.get("length")
        if written is not None:
            return written[2], written[3]
    return record["at"]


def _keys_text(record: dict, keys: Iterable[str]) -> str:
    return ", ".join(_key_word(record, key) for key in keys if key in record["keys"])


def _facet_findings(attr: dict, prop: dict) -> list[tuple[str, str | None, dict, TextEdit | None]]:
    """(message key, key to point at, message arguments, fix) for one attribute and property,
    in the compiler's order."""
    out: list = []
    types = attr["types"]
    if types is None or types != prop["types"]:
        return out
    if "Строка" in types and "Число" in types:
        return out
    if "Строка" in types:
        out.extend(_string_findings(attr, prop))
    if "Число" in types:
        out.extend(_number_findings(attr, prop))
    return out


def _string_findings(attr: dict, prop: dict) -> list:
    own, theirs = attr.get("str"), prop.get("str")
    if own is None:
        if theirs is not None:
            fix = _set_value_fix(attr, "МаксимальнаяДлина", theirs, "after_type")
            return [("missing", None, {"keys": _keys_text(prop, ("МаксимальнаяДлина",))}, fix)]
        return []
    if theirs is None:
        if prop["ro"]:
            return []
        first = next(k for k in _STRING_KEYS if k in attr["keys"])
        return [("unexpected", first, {"keys": _keys_text(attr, _STRING_KEYS)}, None)]
    key = "МаксимальнаяДлина"
    args = {"key": _key_word(attr, key), "actual": own, "expected": theirs}
    if prop["ro"]:
        if own > theirs:
            return [("exceeds", key, args, _set_value_fix(attr, key, theirs, "after_type"))]
        return []
    if own != theirs:
        return [("differs", key, args, _set_value_fix(attr, key, theirs, "after_type"))]
    return []


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _number_findings(attr: dict, prop: dict) -> list:
    own, theirs = attr.get("num"), prop.get("num")
    if own is None:
        if theirs is not None:
            return [("missing", None, {"keys": _keys_text(prop, _NUMBER_VALUE_KEYS)}, None)]
        return []
    if theirs is None:
        if prop["ro"]:
            return []
        first = next(k for k in _NUMBER_KEYS if k in attr["keys"])
        return [("unexpected", first, {"keys": _keys_text(attr, _NUMBER_KEYS)}, None)]
    whole, fract, low, high = own
    c_whole, c_fract, c_low, c_high = theirs
    out: list = []

    def bound(msg: str, key: str, actual, expected) -> None:
        out.append((msg, key if msg != "missing-bound" else None, {
            "key": _key_word(attr, key), "actual": actual if actual is None else _fmt(actual)
            if isinstance(actual, Decimal) else actual,
            "expected": _fmt(expected) if isinstance(expected, Decimal) else expected,
        }, None))

    if prop["ro"]:
        if c_low is not None and low is None:
            bound("missing-bound", "МинимальноеЗначение", None, c_low)
            return out
        if c_low is not None and low is not None and low < c_low:
            bound("below", "МинимальноеЗначение", low, c_low)
            return out
        if c_high is not None and high is None:
            bound("missing-bound", "МаксимальноеЗначение", None, c_high)
            return out
        if c_high is None and high is not None:
            return [("unexpected", "МаксимальноеЗначение",
                     {"keys": _key_word(attr, "МаксимальноеЗначение")}, None)]
        if c_high is not None and high is not None and high > c_high:
            bound("exceeds", "МаксимальноеЗначение", high, c_high)
        if whole > c_whole:
            bound("exceeds", "ДлинаЦелойЧасти", whole, c_whole)
        if fract > c_fract:
            bound("exceeds", "ДлинаДробнойЧасти", fract, c_fract)
        return out
    for key, mine, contract in (("МинимальноеЗначение", low, c_low),
                                ("МаксимальноеЗначение", high, c_high)):
        if contract is not None and mine is None:
            bound("missing-bound", key, None, contract)
        if contract is None and mine is not None:
            out.append(("unexpected", key, {"keys": _key_word(attr, key)}, None))
        if contract is not None and mine is not None and mine != contract:
            bound("differs", key, mine, contract)
    if whole != c_whole:
        bound("differs", "ДлинаЦелойЧасти", whole, c_whole)
    if fract != c_fract:
        bound("differs", "ДлинаДробнойЧасти", fract, c_fract)
    return out


def _contract_index(facts: dict[str, dict]) -> dict[str, dict]:
    """{short name: contract} - a name two contracts share is dropped as ambiguous."""
    seen: dict[str, dict | None] = {}
    for fact in facts.values():
        contract = fact.get("contract")
        if contract is None:
            continue
        name = contract["name"]
        seen[name] = None if name in seen else contract
    return {name: contract for name, contract in seen.items() if contract is not None}


@rule(
    "yaml/contract-facet-mismatch", "yaml/contract-facet-mismatch.title", "A",
    scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def contract_facet_mismatch(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    contracts = _contract_index(facts)
    if not contracts:
        return
    for rel, fact in facts.items():
        impl = fact.get("impl")
        if impl is None:
            continue
        standard = _standard_names()
        for contract_name in impl["contracts"]:
            contract = contracts.get(contract_name)
            if contract is None:
                continue
            pairs = []
            for attr in impl["attrs"]:
                if not attr["typed"] or (not attr["id"] and attr["name"] in standard):
                    continue
                prop = contract["props"].get(attr["name"])
                if prop is not None:
                    pairs.append((attr, prop, attr["name"]))
            for table_name, attrs in impl["tables"].items():
                table = contract["tables"].get(table_name)
                if table is None:
                    continue
                for attr in attrs:
                    prop = table.get(attr["name"])
                    if prop is not None and attr["typed"]:
                        pairs.append((attr, prop, f"{table_name}.{attr['name']}"))
            for attr, prop, label in pairs:
                for msg, key, args, fix in _facet_findings(attr, prop):
                    line, col = _position(attr, key)
                    yield Diagnostic(
                        rel, line, col, "yaml/contract-facet-mismatch", Severity.ERROR,
                        i18n.t(f"yaml/contract-facet-mismatch.{msg}", attr=label,
                               contract=contract_name, **args),
                        fix=fix,
                    )


_QUOTES = {
    "МаксимальнаяДлина": "The maximum length for property ... is not set in entity contract",
    "ДлинаЦелойЧасти": "The integer part for property ... is not set in entity contract",
}


@rule(
    "yaml/contract-standard-length", "yaml/contract-standard-length.title", "A",
    scope="project", severity=Severity.ERROR, mapper=_mapper,
)
def contract_standard_length(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    contracts = _contract_index(facts)
    if not contracts:
        return
    names = _standard_names()
    for rel, fact in facts.items():
        impl = fact.get("impl")
        if impl is None:
            continue
        for attr in impl["attrs"]:
            name = names.get(attr["name"])
            if name is None or attr["id"]:
                continue
            kinds, default_type, default_length = _STANDARD[name]
            if impl["kind"] not in kinds:
                continue
            types = attr["types"] if attr["typed"] else (default_type,)
            if types not in (("Строка",), ("Число",)):
                continue
            length_text = attr.get("length", (None, None))[1]
            length_value = _number(length_text) if length_text is not None else None
            length = int(length_value) if length_value is not None else default_length
            for contract_name in impl["contracts"]:
                contract = contracts.get(contract_name)
                prop = contract["props"].get(attr["name"]) if contract else None
                if prop is None or prop["types"] != types:
                    continue
                string = types == ("Строка",)
                key = "МаксимальнаяДлина" if string else "ДлинаЦелойЧасти"
                if string:
                    limit = prop.get("str")
                else:
                    limit = prop["num"][0] if prop.get("num") else None
                key_word = _key_word(prop, key)
                readonly = f"{_key_word(prop, 'ТолькоЧтение')}: " + (
                    "Истина" if key_word == key else "True")
                length_key = attr.get("length", (None,))[0] or (
                    "Длина" if key_word == key else metamodel.english_name("Длина") or "Длина")
                args = {"attr": attr["name"], "contract": contract_name, "key": key_word,
                        "length": length}
                if prop["ro"]:
                    if limit is not None and length > limit:
                        line, col = _position(attr, "Длина")
                        yield Diagnostic(
                            rel, line, col, "yaml/contract-standard-length", Severity.ERROR,
                            i18n.t("yaml/contract-standard-length.exceeds", expected=limit,
                                   **args),
                            fix=_set_value_fix(attr, "Длина", limit, "after_name"),
                        )
                    continue
                if limit is None:
                    yield Diagnostic(
                        rel, *attr["at"], "yaml/contract-standard-length", Severity.ERROR,
                        i18n.t("yaml/contract-standard-length.not-set", quote=_QUOTES[key],
                               readonly=readonly, **args),
                    )
                elif length != limit:
                    line, col = _position(attr, "Длина")
                    yield Diagnostic(
                        rel, line, col, "yaml/contract-standard-length", Severity.ERROR,
                        i18n.t("yaml/contract-standard-length.differs", expected=limit,
                               length_key=length_key, readonly=readonly, **args),
                        fix=_set_value_fix(attr, "Длина", limit, "after_name"),
                    )
