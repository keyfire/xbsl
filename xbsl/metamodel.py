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

from functools import lru_cache

from xbsl import dataset, terms

#: Kinds of a property value, as told to an editor (see tools/extract_metamodel.py).
SCALAR_KINDS = ("boolean", "number", "string", "enum", "type")


@lru_cache(maxsize=1)
def _data() -> dict | None:
    try:
        return dataset.load_json("metamodel.json")
    except (dataset.DatasetError, KeyError, ValueError):
        return None


def _reset() -> None:
    """Drop the derived tables when the data root or version changes (dataset hook)."""
    for cached in (_data, _class_properties, properties, properties_of_class, _bases, allowed_keys):
        cached.cache_clear()


dataset.register_reset(_reset)


def available() -> bool:
    """True when the generated metamodel is present."""
    return _data() is not None


def kinds() -> tuple[str, ...]:
    """Element kinds whose root class is known (the panel's coverage)."""
    data = _data()
    return tuple(sorted(data["vid2class"])) if data else ()


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


def common_keys() -> tuple[str, ...]:
    """Keys of the project element envelope, shared by every kind."""
    data = _data()
    return tuple(data["common"]) if data else ()


def enum_values(name: str) -> tuple[str, ...]:
    """Values of a metamodel enumeration, or () when unknown."""
    data = _data()
    return tuple((data.get("enums") or {}).get(name, ())) if data else ()


def has_class(name: str) -> bool:
    """True when the metamodel declares such a class (a type name, not an element kind)."""
    data = _data()
    return bool(data) and name in data["classes"]


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
        props.setdefault(key, {"kind": "string"})
    order = sorted(props.items(), key=lambda kv: (-int(kv[1].get("priority") or 0), kv[0]))
    return dict(order)


@lru_cache(maxsize=None)
def properties_of_class(name: str) -> dict[str, dict]:
    """Typed properties of a class, ordered as the platform's own designer orders them.

    The counterpart of `properties` for something that is not an element of its own: an item of a
    collection (an attribute, a dimension, a value of an enumeration). The envelope keys are NOT
    added here - a collection item carries no `ВидЭлемента` and no `ОбластьВидимости`.
    """
    props = dict(_class_properties(name))
    order = sorted(props.items(), key=lambda kv: (-int(kv[1].get("priority") or 0), kv[0]))
    return dict(order)


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
    """
    data = _data()
    if not data:
        return None
    for name, node in data["classes"].items():
        if node.get("presents") == value and item in _bases(name):
            return name
    return None


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
        record = _class_properties(current).get(section)
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
        current = chosen or item
    return current


@lru_cache(maxsize=None)
def allowed_keys(kind: str) -> frozenset[str]:
    """Every yaml key valid at the top level of an element of this kind.

    Alternate spellings count: the compiler still accepts `Разработчик` for `Поставщик`, and the
    rule must not call a legacy source wrong.
    """
    props = properties(kind)
    keys = set(props)
    for record in props.values():
        keys.update(record.get("alias") or ())
    return frozenset(keys)


def localized(props: dict[str, dict], lang: str) -> dict[str, dict]:
    """The same properties keyed in the project's language (English when the platform declares one).

    Metamodel names are Russian; a project written in English spells the very same keys the other
    way, and a panel that mixed the two would show every set property twice.
    """
    if lang != "en":
        return props
    out: dict[str, dict] = {}
    for name, record in props.items():
        english = terms.english(name, "properties") or terms.english(name, "types")
        out[english or name] = record
    return out
