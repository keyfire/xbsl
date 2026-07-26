"""Tier D: the top-level properties of a yaml object against the Element metamodel.

The metamodel (`xbsl/metamodel.py` over the generated metamodel.json) knows the properties of
every configuration element kind. The yaml/unknown-property rule checks the TOP-LEVEL keys of a
yaml object: a key that is not among them is an invalid property (a typo or a copy-over from
another vid).

Only vetted vids are judged - the ones whose class has been checked against real sources; for the
rest the rule stays silent, which rules out false positives where the class may be incomplete.
Only the top level is checked (not the nested components) - validating those needs resolving the
node type by discriminators (a separate stage).

The yaml/unknown-attribute-property rule takes the same idea one level down, to the ITEMS of the
attribute collections (Реквизиты, and the attributes of tabular sections, dimensions and
resources of registers): the metamodel gives every attribute a class of its own, and the classes
differ - a `Длина` is declared by the built-in `Код`, while a regular attribute of type Число has
`ДлинаЦелойЧасти` / `ДлинаДробнойЧасти` and a string one `МаксимальнаяДлина`. Writing `Длина: 12`
on a regular attribute costs a deploy cycle ("Неизвестное свойство Длина"), which is why the rule
is an error - the compiler answers `Неизвестное свойство "Длина"` for a Число attribute and
the same for `Length` in an English source. Only classes under `IAttributeDescriptor` are
judged: the metamodel is incomplete for other item families (a form's PropertyModel does not
declare `ЗначениеПоУмолчанию`, which forms do carry), and an incomplete class means false
positives. `Имя` is always allowed - a dispatched built-in attribute has a fixed
name, so its class does not declare the key the sources nonetheless spell; `Ид` is NOT (the same
probe rejected an `Ид` on the built-in `Наименование`).

The yaml/presentation-field rule checks the VALUE of the Представление property where the
metamodel declares it an attribute NAME (type AttributeName: a catalog, a document, a constant
set, an exchange plan, a settings store). The platform documentation (topics/element-view): the
property names "any attribute of the catalog whose type is Строка"; when unset, the standard
Наименование is used. A title text pasted there, or a reference-typed attribute, passes yaml
parsing but fails the deploy compilation ("Field specified as a presentation field is not
found" / "The type of the field specified as a presentation is not String") - which is why the
rule is an error. Commands, rights and reports carry a localizable or plain text in the same-named
property and are not judged.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _parsed,
    object_kind,
    value_of,
    yaml,
)
from xbsl.rules.yaml_types import _parse_type_string, _value_positions

MESSAGES = {
    "yaml/unknown-property.title": {
        "ru": "Неизвестное свойство объекта",
        "en": "Unknown object property",
    },
    "yaml/unknown-property.unknown": {
        "ru": "Свойство '{prop}' недопустимо для вида '{vid}'.",
        "en": "Property '{prop}' is not allowed for vid '{vid}'.",
    },
    "yaml/unknown-attribute-property.title": {
        "ru": "Неизвестное свойство реквизита",
        "en": "Unknown attribute property",
    },
    "yaml/unknown-attribute-property.unknown": {
        "ru": "Свойство '{prop}' недопустимо у реквизита '{name}' – применение сборки его "
              "отвергнет ('Неизвестное свойство').",
        "en": "Property '{prop}' is not allowed on attribute '{name}' – applying the build "
              "rejects it ('Неизвестное свойство').",
    },
    "yaml/unknown-attribute-property.close": {
        "ru": "Свойство '{prop}' недопустимо у реквизита '{name}' – применение сборки его "
              "отвергнет ('Неизвестное свойство'). Возможно, имелось в виду: {close}.",
        "en": "Property '{prop}' is not allowed on attribute '{name}' – applying the build "
              "rejects it ('Неизвестное свойство'). Did you mean: {close}?",
    },
    "yaml/item-id-required.title": {
        "ru": "У элемента коллекции нет Ид",
        "en": "Collection item without an Id",
    },
    "yaml/item-id-required.missing": {
        "ru": "У элемента '{name}' не задан Ид – применение сборки отвергает объект "
              "('ID required'). Идентификатор постоянный: по нему платформа узнаёт элемент "
              "после переименования.",
        "en": "Item '{name}' has no {n[Ид]} – applying the build rejects the object ('ID required'). "
              "The identifier is permanent: the platform recognizes the item by it after a rename.",
    },
    "yaml/presentation-field.title": {
        "ru": "Поле представления объекта",
        "en": "The presentation field of an object",
    },
    "yaml/presentation-field.unknown": {
        "ru": "Представление '{value}' – у объекта нет реквизита с таким именем; здесь указывается "
              "имя существующего строкового реквизита (обычно Наименование), а не текст заголовка.",
        "en": "{n[Представление]} '{value}' – the object has no attribute with this name; the property "
              "takes the name of an existing string attribute (usually {n[Наименование]}), not a title text.",
    },
    "yaml/presentation-field.non-string": {
        "ru": "Представление '{value}' – реквизит имеет тип '{type}', а полем представления может "
              "быть только строковый реквизит.",
        "en": "{n[Представление]} '{value}' – the attribute type is '{type}', while only a string "
              "attribute can be the presentation field.",
    },
}
i18n.register(MESSAGES)

# A top-level yaml key: a name at the start of the line (no indent) up to the colon.
_TOPKEY_RE = re.compile(r"(?m)^([^\s#:][^:\n]*):")


@lru_cache(maxsize=1)
def _attribute_name_kinds() -> frozenset[str]:
    """Element kinds whose Представление is the NAME of an attribute (metamodel type
    AttributeName) rather than a text: Справочник, Документ, НаборКонстант, ПланОбмена,
    ХранилищеНастроек in the current data. Computed from the metamodel, not hardcoded."""
    return frozenset(
        vid for vid in metamodel.kinds()
        if (metamodel.properties(vid).get("Представление") or {}).get("type") == "AttributeName"
    )


dataset.register_reset(_attribute_name_kinds.cache_clear)


def _non_string_type(vid: str, name: str, item: dict) -> str | None:
    """The declared (or defaulted) type of the attribute when it is provably NOT a string,
    otherwise None. An explicit Тип is parsed as a type expression: a lone Строка chain (with
    or without the nullable marker) is a string; an expression that still ALLOWS Строка among
    alternatives is not proven invalid and is left alone. A record without Тип is judged by the
    metamodel default of its dispatched class: the standard Код defaults to Строка, Наименование
    has no Тип property at all (always a string), a regular attribute has no default (its
    missing Тип is another rule's business)."""
    declared = item.get("Тип")
    if isinstance(declared, str):
        chains = _parse_type_string(declared)
        if not chains or ["Строка"] in chains:
            return None
        return declared
    if declared is not None:
        return None  # not a scalar - malformed yaml, not this rule's business
    cls = metamodel.item_class(vid, [("Реквизиты", name)])
    props = metamodel.properties_of_class(cls) if cls else None
    if not props or "Тип" not in props:
        return None  # no Тип property at all (Наименование) - a string by construction
    default = props["Тип"].get("default")
    if not isinstance(default, str) or default.rpartition("::")[2] == "Строка":
        return None
    return default.rpartition("::")[2]


@rule("yaml/presentation-field", "yaml/presentation-field.title", "D", severity=Severity.ERROR)
def presentation_field(source: SourceFile) -> Iterable[Diagnostic]:
    """The value of Представление on a data object is the name of an existing STRING attribute
    (the platform: "имя любого из реквизитов справочника, имеющего тип Строка"; unset falls
    back to the standard Наименование). Judged only for kinds whose metamodel declares the
    property as AttributeName - commands and reports carry a text there. A `$`/`=` value
    (a localized-string reference / a binding) is not a name and is skipped."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not metamodel.available():
        return  # the metamodel is not generated - skip the check
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    vid = object_kind(data)
    if not isinstance(vid, str) or vid not in _attribute_name_kinds():
        return
    value = value_of(data, "Представление")
    if not isinstance(value, str) or not value.strip() or value.startswith(("$", "=")):
        return  # missing is naming/presentation's business; $/= is not an attribute name
    attrs = {
        value_of(item, "Имя"): item
        for item in value_of(data, "Реквизиты") or []
        if isinstance(item, dict) and isinstance(value_of(item, "Имя"), str)
    }
    item = attrs.get(value)
    if item is None:
        message = i18n.t("yaml/presentation-field.unknown", value=value)
    else:
        bad_type = _non_string_type(vid, value, item)
        if bad_type is None:
            return
        message = i18n.t("yaml/presentation-field.non-string", value=value, type=bad_type)
    positions = _value_positions(source, value, key="Представление") or [(1, 1)]
    for line, col in positions:
        yield Diagnostic(
            source.rel, line, col, "yaml/presentation-field", Severity.ERROR, message,
        )


# The family the rule judges, and the key every item carries whatever its class declares.
# Only the name: a built-in Наименование carrying an `Ид` answers `Неизвестное свойство "Id"`,
# so `Ид` is judged by the class like any other property - a regular attribute declares it,
# a dispatched built-in does not.
_ATTRIBUTE_BASE = "IAttributeDescriptor"
_ALWAYS_ALLOWED = frozenset({"Имя", "Name"})


@lru_cache(maxsize=None)
def _class_keys(cls: str) -> frozenset[str]:
    """Every yaml key valid on an item of this class, either spelling, aliases included."""
    keys = set(_ALWAYS_ALLOWED)
    for name, record in metamodel.properties_of_class(cls).items():
        keys.add(name)
        keys.update(record.get("alias") or ())
        if record.get("en"):
            keys.add(record["en"])
    return frozenset(keys)


dataset.register_reset(_class_keys.cache_clear)


def _scalar_value(mapping, *names: str) -> str | None:
    """The scalar value of the first key of the mapping node found among `names`."""
    for key_node, value_node in mapping.value:
        if (
            isinstance(key_node, yaml.ScalarNode) and key_node.value in names
            and isinstance(value_node, yaml.ScalarNode)
        ):
            return value_node.value
    return None


@lru_cache(maxsize=None)
def _untranslated_dispatch_keys(cls: str, section: str) -> frozenset[str]:
    """Keys to tolerate on an item whose ASCII name could be an untranslated built-in.

    A dispatched collection picks a class by the item's name, and the English spelling of the
    name comes from the platform dictionary. For `Наименование`, `Владелец`, `Номер` and `Дата`
    it is there; for `Код` the dictionary knows no pair at all, so an English source spelling
    that attribute cannot be recognized as the built-in and would be judged as a regular one.
    Rather than invent a spelling, the rule widens the allowed set by the keys of exactly those
    classes whose name does not translate - a missed finding instead of a false one.
    """
    record = metamodel.properties_of_class(cls).get(section) or {}
    item = record.get("item")
    if not record.get("dispatch") or not item:
        return frozenset()
    keys: set[str] = set()
    for name, presents in metamodel.dispatched_classes(item):
        if terms.common_english(presents) is None:
            keys |= _class_keys(name)
    return frozenset(keys)


dataset.register_reset(_untranslated_dispatch_keys.cache_clear)


def _section_record(props: dict[str, dict], key: str) -> tuple[str, dict] | None:
    """(the section as the metamodel names it, its record) for a collection key of the file.

    The file may spell the section in English (`Attributes`), so the English name of every
    list property is matched too.
    """
    record = props.get(key)
    if record is not None:
        return (key, record) if record.get("kind") == "list" else None
    for name, candidate in props.items():
        if candidate.get("kind") == "list" and candidate.get("en") == key:
            return name, candidate
    return None


def _close_properties(key: str, declared: tuple[str, ...]) -> list[str]:
    """Up to three declared properties worth suggesting instead of `key`.

    A plain difflib ratio is too blunt for the case that matters: `Длина` scores 0.5 against
    `ДлинаЦелойЧасти` and would be dropped, while it is exactly the property the author meant.
    So names CONTAINING the key come first (the platform composes property names out of words),
    and difflib only fills in the rest - a typo such as `Длинна`.
    """
    lowered = key.lower()
    contains = [name for name in declared if lowered in name.lower() and name != key]
    rest = [
        name for name in difflib.get_close_matches(key, declared, n=3, cutoff=0.6)
        if name not in contains
    ]
    return (contains + rest)[:3]


def _unknown_attribute_keys(cls: str, mapping, rel: str, extra: frozenset[str]) -> Iterable[Diagnostic]:
    """Diagnostics for the keys of an attribute item its class does not declare."""
    allowed = _class_keys(cls) | extra
    declared = sorted(metamodel.properties_of_class(cls))
    name = _scalar_value(mapping, "Имя", "Name") or "?"
    for key_node, _value in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.value in allowed:
            continue
        close = _close_properties(key_node.value, tuple(declared))
        key = "yaml/unknown-attribute-property." + ("close" if close else "unknown")
        yield Diagnostic(
            rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/unknown-attribute-property", Severity.ERROR,
            i18n.t(key, prop=key_node.value, name=name, close=", ".join(close)),
        )


def _collection_items(cls: str, mapping) -> Iterable[tuple[str, object, frozenset[str]]]:
    """(class, node, tolerated extra keys) of every collection item under a node, recursively."""
    props = metamodel.properties_of_class(cls)
    for key_node, value_node in mapping.value:
        if not isinstance(key_node, yaml.ScalarNode) or not isinstance(value_node, yaml.SequenceNode):
            continue
        found = _section_record(props, key_node.value)
        if found is None:
            continue
        section, _record = found
        default = metamodel.collection_item_class(cls, section, None)
        for item in value_node.value:
            if not isinstance(item, yaml.MappingNode):
                continue
            name = _scalar_value(item, "Имя", "Name")
            child = metamodel.collection_item_class(cls, section, name)
            if not child:
                continue
            # An ASCII name that did not dispatch may be a built-in the dictionary does not
            # translate - then the keys of those classes are tolerated (see the helper).
            widen = frozenset()
            if name and name.isascii() and child == default:
                widen = _untranslated_dispatch_keys(cls, section)
            yield child, item, widen
            yield from _collection_items(child, item)


def _vetted_root(source: SourceFile) -> tuple[str, object] | None:
    """(the class of the element, its composed root) for a vetted object yaml, else None."""
    if source.kind != "yaml" or not _HAVE_YAML or not metamodel.available():
        return None
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return None
    vid = object_kind(data)
    if not isinstance(vid, str) or not metamodel.is_vetted(vid):
        return None  # the vid is not vetted - its classes may be incomplete
    cls = metamodel.class_for_kind(vid)
    root = _composed(source)
    if not cls or root is None or not isinstance(root, yaml.MappingNode):
        return None
    return cls, root


@rule(
    "yaml/unknown-attribute-property", "yaml/unknown-attribute-property.title", "D",
    severity=Severity.ERROR,
)
def unknown_attribute_property(source: SourceFile) -> Iterable[Diagnostic]:
    """A key an attribute's own class does not declare - apply rejects the object."""
    got = _vetted_root(source)
    if got is None:
        return
    cls, root = got
    for child, item, widen in _collection_items(cls, root):
        if metamodel.inherits(child, _ATTRIBUTE_BASE):
            yield from _unknown_attribute_keys(child, item, source.rel, widen)


@rule("yaml/item-id-required", "yaml/item-id-required.title", "D", severity=Severity.ERROR)
def item_id_required(source: SourceFile) -> Iterable[Diagnostic]:
    """An item of a metadata collection must carry the `Ид` its class declares.

    The compiler answers `ID required` for every family at once - an attribute, an attribute
    of a tabular section, the tabular section itself, an item of an enumeration and a
    parameter of an access key: an item whose class declares `Ид` always carries it. A dispatched built-in (`Наименование`,
    `Код`) has a class of its own that declares no `Ид` - and there the key is forbidden
    rather than required, which the neighbouring rule reports.
    """
    got = _vetted_root(source)
    if got is None:
        return
    cls, root = got
    for child, item, _widen in _collection_items(cls, root):
        if "Ид" not in metamodel.properties_of_class(child):
            continue
        if _scalar_value(item, "Ид", "Id"):
            continue
        name = _scalar_value(item, "Имя", "Name") or "?"
        yield Diagnostic(
            source.rel, item.start_mark.line + 1, item.start_mark.column + 1,
            "yaml/item-id-required", Severity.ERROR,
            i18n.t("yaml/item-id-required.missing", name=name),
        )


@rule("yaml/unknown-property", "yaml/unknown-property.title", "D", severity=Severity.WARNING)
def unknown_property(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return []
    if not metamodel.available():
        return []  # the metamodel is not generated – skip the check
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return []
    vid = object_kind(data)
    if not isinstance(vid, str) or not metamodel.is_vetted(vid):
        return []  # the vid is not vetted – skip it
    allowed = metamodel.allowed_keys(vid)

    diags: list[Diagnostic] = []
    lm = linemap(source)
    for m in _TOPKEY_RE.finditer(source.text):
        key = m.group(1).strip()
        if key in data and key not in allowed:  # only the real top-level keys
            line, col = lm.linecol(m.start(1))
            diags.append(Diagnostic(
                source.rel, line, col, "yaml/unknown-property", Severity.WARNING,
                i18n.t("yaml/unknown-property.unknown", prop=key, vid=vid),
            ))
    return diags
