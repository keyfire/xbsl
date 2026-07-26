"""Properties of configuration elements by kind (metamodel.json).

The platform describes every configuration element with an EMF class: `Справочник` is
`CatalogNativeDescriptor`, whose properties (`Иерархический`, `ВводПоСтроке`, `КонтрольДоступа`
...) come from the class itself, from the classes it extends and from the ones it splices in
(`inline` - a member with no key of its own, which is how a string attribute gets its length
limits). `tools/extract_metamodel.py` collects all of that from the distribution.

Two consumers, two views of the same data:

- the `yaml/unknown-property` rule needs the SET OF ALLOWED KEYS and judges only vetted kinds
  (`vetted`) - an incomplete class would turn into a false diagnostic;
- the properties panel of the editor needs TYPED PROPERTIES for every kind the mapping knows
  (`vid2class`) - there an unlisted property is a missing hint, not a diagnostic.

Older data (a plain list of names per class) is read as well: properties come back without a
type, which the panel renders as plain text editors.
"""

from __future__ import annotations

import re
from functools import lru_cache

from xbsl import dataset, terms

#: Kinds of a property value, as told to an editor (see tools/extract_metamodel.py).
SCALAR_KINDS = ("boolean", "number", "string", "enum", "type")

#: A closed data-type constraint of a `kind: type` property (`@PossibleTypes`):
#: Std::Type<Std::String|Std::Number> - the value may name only the listed types.
_TYPE_CONSTRAINT_RE = re.compile(r"^(?:Std|Стд)::(?:Type|Тип)<(.+)>$")


def type_options(record: dict) -> list[str] | None:
    """Russian spellings of a closed data-type constraint, or None for an open one.

    The Код of a Справочник declares `Std::Type<Std::String|Std::Number>` - the panel must
    offer exactly Строка and Число, not every type of the project. A member that cannot be
    resolved to a platform name keeps the list open (offering everything beats forbidding
    something legal), and a nested generic would not match the constraint shape at all.
    """
    m = _TYPE_CONSTRAINT_RE.match(str(record.get("types") or ""))
    if not m:
        return None
    out: list[str] = []
    for member in m.group(1).split("|"):
        member = member.strip().split("::")[-1]
        nullable = member.endswith("?")
        if nullable:
            member = member[:-1]
        if not member:
            return None
        russian = terms.russian(member, "types") or (
            member if terms.english(member, "types") else None
        )
        if russian is None:
            return None
        out.append(russian + "?" if nullable else russian)
    return out or None


def _with_type_options(props: dict[str, dict]) -> dict[str, dict]:
    """Copies of the records with a closed constraint resolved into `options`."""
    out: dict[str, dict] = {}
    for key, record in props.items():
        options = type_options(record) if record.get("kind") == "type" else None
        out[key] = {**record, "options": options} if options else record
    return out


@lru_cache(maxsize=1)
def _data() -> dict | None:
    try:
        return dataset.load_json("metamodel.json")
    except (dataset.DatasetError, KeyError, ValueError):
        return None


def _reset() -> None:
    """Drop the derived tables when the data root or version changes (dataset hook)."""
    for cached in (_data, _class_properties, properties, properties_of_class, _bases, allowed_keys,
                   _english_keys, _common_english, english_name, _english_kinds,
                   dispatched_classes):
        cached.cache_clear()


dataset.register_reset(_reset)


def available() -> bool:
    """True when the generated metamodel is present."""
    return _data() is not None


def kinds() -> tuple[str, ...]:
    """Element kinds whose root class is known (the panel's coverage)."""
    data = _data()
    return tuple(sorted(data["vid2class"])) if data else ()


def class_names() -> tuple[str, ...]:
    """Every class the metamodel declares - the pool a name outside the palette resolves against."""
    data = _data()
    return tuple(sorted(data["classes"])) if data else ()


def class_for_kind(kind: str) -> str | None:
    data = _data()
    return data["vid2class"].get(kind) if data else None


def is_vetted(kind: str) -> bool:
    """True when the rule may judge this kind (its class is confirmed against real sources)."""
    data = _data()
    if not data:
        return False
    vetted = data.get("vetted")
    if vetted is None:
        return kind in data["vid2class"]  # older data: the mapping itself was the vetted list
    return kind in vetted


@lru_cache(maxsize=None)
def _common_english(key: str) -> str | None:
    """The English spelling of an envelope key, taken from any class that declares the property.

    `ВидЭлемента`, `Ид` and their neighbours are added to every kind from the `common` list, which
    carries names only; the pair itself lives in the classes that spell the property out.
    """
    data = _data()
    for node in (data["classes"] if data else {}).values():
        # Legacy data keeps a plain list of names per class - nothing to look a pair up in.
        props = node.get("props")
        record = props.get(key) if isinstance(props, dict) else None
        if isinstance(record, dict) and record.get("en"):
            return record["en"]
    return None


def common_keys() -> tuple[str, ...]:
    """Keys of the project element envelope, shared by every kind."""
    data = _data()
    return tuple(data["common"]) if data else ()


@lru_cache(maxsize=None)
def key_aliases() -> dict[str, str]:
    """{English spelling: the Russian key} of element properties - for surfaces outside python.

    The metadata tree of the editor parses the yaml itself (a tree view cannot call into the
    engine per node), so it needs the same pairs the classes carry: without them an English
    object shows empty branches - the sections are looked up by `Реквизиты` while the file
    spells `Attributes`. Every pair comes from the `en` of a class property, never from a guess.

    The whole metamodel is walked, not one kind: a section item is a class of its own
    (`TabularSectionDescriptor` spells its own `Реквизиты`), and the tree descends into those.
    """
    data = _data()
    out: dict[str, str] = {}
    for node in (data["classes"] if data else {}).values():
        for key, record in _props_of(node).items():
            english = record.get("en") if isinstance(record, dict) else None
            if english and english != key:
                out.setdefault(english, key)
    return out


def enum_values(name: str) -> tuple[str, ...]:
    """Values of a metamodel enumeration, or () when unknown."""
    data = _data()
    return tuple((data.get("enums") or {}).get(name, ())) if data else ()


def has_class(name: str) -> bool:
    """True when the metamodel declares such a class (a type name, not an element kind)."""
    data = _data()
    return data is not None and name in data["classes"]


def class_property_names(name: str) -> frozenset[str]:
    """Property names of a class, inheritance included - the built-in members of a base type."""
    return frozenset(_class_properties(name))


def _props_of(node: dict) -> dict[str, dict]:
    """The class's own properties, normalizing the older list-of-names form."""
    props = node.get("props") or {}
    if isinstance(props, dict):
        return props
    return {name: {} for name in props}


@lru_cache(maxsize=None)
def _class_properties(name: str) -> dict[str, dict]:
    """Properties of a class following `ext` (inheritance) and `inline` (spliced members)."""
    data = _data()
    if not data:
        return {}
    classes = data["classes"]
    out: dict[str, dict] = {}
    seen: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        node = classes.get(current)
        if not node:
            continue
        for key, record in _props_of(node).items():
            out.setdefault(key, record)
        stack.extend(node.get("ext") or ())
        stack.extend(node.get("inline") or ())
    return out


@lru_cache(maxsize=None)
def properties(kind: str) -> dict[str, dict]:
    """Typed properties applicable to an element kind, the envelope keys included.

    Ordered the way the platform's own designer orders them - by the IDE priority first, then
    alphabetically - so the panel can render the list as is.
    """
    cls = class_for_kind(kind)
    if not cls:
        return {}
    props = dict(_class_properties(cls))
    for key in common_keys():
        # The envelope keys are synthesized here, so their English spelling has to be looked up
        # too - otherwise `ElementKind` in a valid English source reads as an unknown property.
        props.setdefault(key, {"kind": "string", **({"en": en} if (en := _common_english(key)) else {})})
    order = sorted(props.items(), key=lambda kv: (-int(kv[1].get("priority") or 0), kv[0]))
    return _with_type_options(dict(order))


@lru_cache(maxsize=None)
def properties_of_class(name: str) -> dict[str, dict]:
    """Typed properties of a class, ordered as the platform's own designer orders them.

    The counterpart of `properties` for something that is not an element of its own: an item of a
    collection (an attribute, a dimension, a value of an enumeration). The envelope keys are NOT
    added here - a collection item carries no `ВидЭлемента` and no `ОбластьВидимости`.
    """
    props = dict(_class_properties(name))
    order = sorted(props.items(), key=lambda kv: (-int(kv[1].get("priority") or 0), kv[0]))
    return _with_type_options(dict(order))


@lru_cache(maxsize=None)
def _bases(name: str) -> frozenset[str]:
    """The class itself plus everything it extends, transitively."""
    data = _data()
    if not data:
        return frozenset()
    classes = data["classes"]
    out: set[str] = set()
    stack = [name]
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        node = classes.get(current)
        if node:
            stack.extend(node.get("ext") or ())
    return frozenset(out)


def _class_by_impl(impl: str) -> str | None:
    """The class the metamodel declares as this implementation (`@DefaultImpl(name=...)`)."""
    data = _data()
    if not data:
        return None
    for name, node in data["classes"].items():
        if node.get("implName") == impl:
            return name
    return None


def _dispatched_class(item: str, value: str) -> str | None:
    """The class a dispatched collection picks for an item whose key holds `value`.

    The platform marks such classes with `@DescriptorPresentation` (the built-in attributes
    `Код`, `Наименование`, `Владелец` each have their own class); the same value occurs in
    unrelated families, so the candidate must also be assignable to the collection's item type.

    A source may spell the name in English (`Name` for `Наименование`), so the English spelling
    of the presentation is matched too - it comes from the platform dictionary, never from a
    guess, and where the dictionary knows no pair the name simply does not dispatch.
    """
    for name, presents in dispatched_classes(item):
        if presents == value or terms.common_english(presents) == value:
            return name
    return None


@lru_cache(maxsize=None)
def dispatched_classes(item: str) -> tuple[tuple[str, str], ...]:
    """[(class, the name it is dispatched by)] of the classes a collection of `item` dispatches to."""
    data = _data()
    if not data:
        return ()
    return tuple(
        (name, node["presents"])
        for name, node in data["classes"].items()
        if node.get("presents") and item in _bases(name)
    )


def collection_item_class(cls: str, section: str, name: str | None) -> str | None:
    """The class of an item of the `section` collection declared by the class `cls`.

    One step of `item_class`, taken from a CLASS rather than from an element kind: a rule that
    walks the yaml tree already knows the class of the node it stands on. `name` is the `Имя` of
    the item and matters only where the collection dispatches by it (the built-in `Код`,
    `Наименование` and `Владелец` have classes of their own). None when the section is not a
    collection of this class.
    """
    record = _class_properties(cls).get(section)
    if not record or record.get("kind") != "list":
        return None
    item = record.get("item")
    if not item:
        return None
    chosen = None
    if record.get("dispatch") and name:
        chosen = _dispatched_class(item, name)
    if not chosen and record.get("impl"):
        chosen = _class_by_impl(record["impl"])
    return chosen or item


def inherits(cls: str, base: str) -> bool:
    """Whether the class is the base itself or extends it, transitively."""
    return base in _bases(cls)


def item_class(kind: str, path: tuple[tuple[str, str | None], ...]) -> str | None:
    """The class of a nested element: a collection item, possibly nested several levels deep.

    `path` is the way from the element's root down to the node, one `(section, name)` pair per
    level - the yaml key of the collection and the `Имя` of the item inside it (the name matters
    only where the metamodel dispatches by it). Returns None when the path leads nowhere.
    """
    current = class_for_kind(kind)
    if not current:
        return None
    for section, name in path:
        current = collection_item_class(current, section, name)
        if not current:
            return None
    return current


@lru_cache(maxsize=None)
def allowed_keys(kind: str) -> frozenset[str]:
    """Every yaml key valid at the top level of an element of this kind.

    Alternate spellings count: the compiler still accepts `Разработчик` for `Поставщик`, and the
    rule must not call a legacy source wrong. The ENGLISH spelling of every property counts too -
    the platform is bilingual all the way into the sources (a catalog spelled `ElementKind` /
    `Name` / `Attributes` / `Length` compiles).
    """
    props = properties(kind)
    keys = set(props)
    for record in props.values():
        keys.update(record.get("alias") or ())
        if record.get("en"):
            keys.add(record["en"])
    return frozenset(keys)


@lru_cache(maxsize=None)
def _english_keys(kind: str) -> dict[str, str]:
    """English yaml key -> the Russian one, for the top-level properties of a kind.

    Per KIND rather than globally on purpose: four names have two English spellings depending on
    the class (`Элементы` is Elements or Items), and seven English names cover two Russian ones
    (`Name` is Имя and Наименование), so a global table would have to guess.
    """
    return {rec["en"]: ru for ru, rec in properties(kind).items() if rec.get("en")}


@lru_cache(maxsize=None)
def english_name(name: str) -> str | None:
    """The English spelling of a property name when the WHOLE metamodel agrees on one.

    Used where the class is not known - a key of a collection item, say. Ambiguity is answered
    with None rather than a guess: four Russian names carry two English spellings depending on
    the class (`Элементы` is Elements or Items).
    """
    data = _data()
    seen: set[str] = set()
    for node in (data["classes"] if data else {}).values():
        props = node.get("props")
        record = props.get(name) if isinstance(props, dict) else None
        if isinstance(record, dict) and record.get("en"):
            seen.add(record["en"])
    return seen.pop() if len(seen) == 1 else None


def canonical_key(kind: str, key: str) -> str:
    """The key as the metamodel names it: an English spelling comes back Russian, the rest as is."""
    return _english_keys(kind).get(key, key)


def canonical_kind(value: str) -> str:
    """The element kind as the metamodel names it (`Catalog` -> `Справочник`).

    Kinds live in the term dictionary, not in the metamodel classes, so the pair comes from there;
    a name the dictionary does not know is returned unchanged.
    """
    if not value or not value.isascii():
        return value
    return _english_kinds().get(value, value)


@lru_cache(maxsize=None)
def _english_kinds() -> dict[str, str]:
    """{English spelling: the element kind} over the kinds the metamodel knows.

    Built FORWARD from the kinds themselves: the dictionaries are many-to-one the other way
    (`Type` is the English of both `Тип` and `ТипЭлементаПроекта`), so a plain reverse map would
    answer with whichever pair came last. The two sources complement each other - the compact
    dictionary names Catalog and HttpService, the compiler meta objects InterfaceComponent and
    CommonModule.
    """
    out: dict[str, str] = {}
    for kind in kinds():
        english = terms.english(kind, "types") or terms.common_english(kind)
        if english:
            out[english] = kind
    return out


def localized(props: dict[str, dict], lang: str) -> dict[str, dict]:
    """The same properties keyed in the project's language (English when the platform declares one).

    Metamodel names are Russian; a project written in English spells the very same keys the other
    way, and a panel that mixed the two would show every set property twice.
    """
    if lang != "en":
        return props
    # The English key of a property is in the metamodel record itself (the `en` argument of
    # @PropertyInfo, or the member name capitalized where the annotation declares none). The term
    # dictionary used to answer this and covered barely half the keys - `Реквизиты` had no English
    # name there at all, though `Attributes:` compiles.
    return {record.get("en") or name: record for name, record in props.items()}
