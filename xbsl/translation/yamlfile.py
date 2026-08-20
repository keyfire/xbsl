"""Translate an element's yaml: keys by the metamodel, values by what the key declares.

The composed node graph keeps exact positions (`Mark.index`), so the file is rewritten by
span edits like the code side - formatting, order and comments stay put. The metamodel
drives the walk: the class of every node names its keys' English spellings and TYPES its
values, and the value's type decides what happens to it:

- `Term` / `AttributeName`   - an identifier of the project: the dictionary;
- `kind: type`               - a type expression: platform types, facets, project names;
- `kind: enum` / `*G5Enum`   - an enumeration value, translated within its enumeration;
- `kind: boolean`            - "Истина" -> `True`;
- `Localizable` / `String`   - DATA: left as written (a `$Словарь.Ключ` reference is the
  exception - both of its parts are names and follow their renames);
- `= expression`             - code: re-tokenized and translated like a module body;
- `kind: list` / `block`     - the walk descends with the item's class.

Below the metamodel's reach - the component tree of a form - the ui schema takes over: a
node's `Type` key names the component, the component's property record tells text from name from
enumeration. A key or value neither source can type falls back to a short table of known
identifier-valued keys, and everything else is left alone as data.

A dictionary of localized strings is special-cased: the keys of the `Strings`/`Templates` sections are the
project's own tokens, the values are localized data.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

from xbsl import dataset, metamodel, terms, uischema
from xbsl.engine import SourceFile
from xbsl.rules.yaml_schema import _composed, _parsed, object_kind
from xbsl.translation import platform_map
from xbsl.translation.code import (
    Edit,
    Resolver,
    apply_edits,
    has_cyrillic,
    translate_expression,
    translate_interpolations,
    translate_type_expression,
)
from xbsl.translation.reporting import FileReport

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

#: yaml keys whose value is an identifier (or a dotted chain) even where no schema record
#: types them: event handlers of forms, dynamic-list column fields, object form references.
_IDENT_VALUE_KEYS = frozenset({
    "Обработчик", "ПослеСоздания", "Поле", "ПолеЗначения", "Форма",
    # The alias of a dynamic-list field NAMES a field of the row type the platform generates,
    # and the modules read it by that name: left in Russian, every reader breaks.
    "Псевдоним",
})
#: yaml keys whose value is an XBSL expression WITHOUT the leading `=`.
_EXPR_VALUE_KEYS = frozenset({"Выражение"})

#: yaml keys whose value names a TYPE or a data table - a name that must move with the object
#: it points at. The metamodel types some of them, but inside a component tree the schema is
#: the ui one, and there they are ordinary properties: left as data, the reference outlives
#: the rename and the build refuses it ("unknown type", "unknown table name").
_TYPE_VALUE_KEYS = frozenset({
    "ТипФормы", "ТипЗначения", "ТипДанных", "ТипКомпонентаСтроки",
    # The generated row type of a dynamic list is DECLARED by this key and referenced as
    # `<Form>.<Name>` everywhere else; left as data the declaration and its references drift
    # apart, the table type never resolves, and every `Components.<Table>` after it fails too.
    "ИмяТипаДанныхСтроки",
    # The source of a dynamic list carries the table name one level inside its main-table
    # block - that inner key is the one actually holding the name.
    "Таблица",
})

#: A `$Словарь.Ключ` reference to a localized string.
_DOLLAR_REF_RE = re.compile(r"^\$(\w+)\.(\w+)$", re.UNICODE)

#: A value that is a resource file name: the stem is a project token, the extension stays.
_RESOURCE_VALUE_RE = re.compile(r"^([\w-]+)\.(svg|png|jpe?g|gif|webp|ico|css|js|json|html|woff2?|ttf|pdf|mp4)$",
                                re.UNICODE | re.IGNORECASE)

#: A scalar that looks like a bare identifier or a dotted chain of identifiers.
_IDENT_CHAIN_RE = re.compile(r"^\w+(\.\w+)*$", re.UNICODE)

#: The kind-carrying key and the sections of a localized-strings body.
_LOCALIZATION_SECTIONS = ("Строки", "Шаблоны", "Strings", "Templates")

#: File stems that carry a fixed element kind without declaring `ElementKind`.
_STEM_KINDS = {"Проект": "Проект", "Project": "Проект"}


def translate_yaml(source: SourceFile, resolver: Resolver, report: FileReport) -> str:
    """The translated text of one yaml file."""
    if yaml is None:  # pragma: no cover - pyyaml is an install-time dependency
        return source.text
    data, err = _parsed(source)
    root = _composed(source)
    edits: list[Edit] = []
    if err is None and isinstance(root, yaml.MappingNode):
        kind = object_kind(data) or _STEM_KINDS.get(source.path.stem)
        if kind == "ЛокализованныеСтроки":
            _walk_object(root, kind, resolver, report, edits, localized_strings=True)
        elif kind is not None and metamodel.class_for_kind(kind):
            _walk_object(root, kind, resolver, report, edits)
        elif _is_localization_body(root):
            # A translation file carries no header, so the dictionary it belongs to is named
            # by the FILE - the platform requires the two to share a name.
            _walk_localization_body(root, resolver, report, edits, scope=source.path.stem)
        else:
            # A subsystem or resource descriptor: no element kind, a handful of keys.
            _walk_plain(root, resolver, report, edits)
    _comment_edits(source, root, resolver, report, edits)
    return apply_edits(source.text, edits)


def _is_localization_body(root) -> bool:
    """A translation file of a localized-strings element: only Строки/Шаблоны, no header."""
    keys = [k.value for k, _v in root.value if isinstance(k, yaml.ScalarNode)]
    return bool(keys) and all(k in _LOCALIZATION_SECTIONS for k in keys)


# --- spans and scalar rewriting ----------------------------------------------------------


def _at(node) -> tuple[int, int]:
    return node.start_mark.line + 1, node.start_mark.column + 1


def _set_scalar(node, new_value: str, edits: list[Edit]) -> None:
    if new_value == node.value:
        return
    if node.style == '"':
        text = json.dumps(new_value, ensure_ascii=False)
    elif node.style == "'":
        text = "'" + new_value.replace("'", "''") + "'"
    elif node.style in ("|", ">"):
        return  # a block scalar is data; nothing identifier-shaped is written this way
    else:
        text = new_value
    edits.append((node.start_mark.index, node.end_mark.index, text))


# --- shared value translators -------------------------------------------------------------


def _identifier_value(node, resolver, report, edits, scope: str = "") -> None:
    """A value that names things: a bare identifier, a dotted chain, a resource file.

    `scope` is the element this name is declared in: a name lives in the namespace of its
    owner, so a project may need a spelling here that the same word cannot carry globally
    (a property of a component named after a word the base type already uses).
    """
    value = node.value
    if not isinstance(value, str) or not has_cyrillic(value):
        return
    m = _RESOURCE_VALUE_RE.match(value)
    if m:
        stem, extension = m.group(1), m.group(2)
        replacement = resolver.dictionary.token(stem)
        if replacement:
            report.user_done += 1
            _set_scalar(node, f"{replacement}.{extension}", edits)
        else:
            line, col = _at(node)
            report.note_token(stem, line, col, resource=True)
        return
    if not _IDENT_CHAIN_RE.match(value):
        # Not a name after all (a label pasted into a name-typed slot): data, left alone.
        line, col = _at(node)
        report.texts_kept.append((value if len(value) <= 60 else value[:57] + "...", line, col))
        return
    _set_scalar(node, translate_expression(value, resolver, report, at=_at(node), scope=scope), edits)


def _dollar_ref(node, resolver, report, edits) -> bool:
    """A `$Словарь.Ключ` value; True when the value was one."""
    value = node.value
    if not isinstance(value, str) or not value.startswith("$"):
        return False
    m = _DOLLAR_REF_RE.match(value)
    if not m:
        return False
    parts = []
    dictionary_name = m.group(1)
    for index, part in enumerate((dictionary_name, m.group(2))):
        if not has_cyrillic(part):
            parts.append(part)
            continue
        if index and dictionary_name in resolver.dictionary_scopes:
            replacement, plane = resolver.dictionary_key(part, dictionary_name)
        else:
            replacement, plane = resolver.identifier(part)
        if plane == "user":
            report.user_done += 1
        if replacement is None:
            line, col = _at(node)
            report.note_token(part, line, col)
            parts.append(part)
        else:
            parts.append(replacement)
    _set_scalar(node, f"${parts[0]}.{parts[1]}", edits)
    return True


def _generic_scalar(node, resolver, report, edits) -> None:
    """A value nothing typed: expressions, references and resource files translate, data stays."""
    value = node.value
    if not isinstance(value, str) or not value:
        return
    if "%{" in value or "${" in value:
        # A presentation template is prose with EXPRESSIONS inside: `%{Interface}` names a
        # property of the event, and left in Russian it names one that no longer exists.
        _set_scalar(node, translate_interpolations(value, resolver, report, at=_at(node)), edits)
        return
    if _RESOURCE_VALUE_RE.match(value) and has_cyrillic(value):
        # A resource file is named by the same map that renames the file itself; a reference
        # left behind points at a file that no longer exists, and the build refuses it.
        _identifier_value(node, resolver, report, edits)
        return
    if value.startswith("="):
        _set_scalar(node, "=" + translate_expression(value[1:], resolver, report, at=_at(node)), edits)
        return
    if _dollar_ref(node, resolver, report, edits):
        return
    if has_cyrillic(value):
        line, col = _at(node)
        report.texts_kept.append((value if len(value) <= 60 else value[:57] + "...", line, col))


def _enum_scalar(node, enum_name: str | None, resolver, report, edits) -> None:
    value = node.value
    if not isinstance(value, str) or not has_cyrillic(value):
        return
    replacement = platform_map.enum_value_english(enum_name or "", value)
    if replacement is None:
        replacement = resolver.dictionary.token(value)
        if replacement:
            report.user_done += 1
    if replacement:
        _set_scalar(node, replacement, edits)
    else:
        line, col = _at(node)
        report.note_platform(value, line, col)


def _boolean_scalar(node, edits) -> bool:
    value = node.value
    if isinstance(value, str) and not value.isascii():
        replacement = platform_map.boolean_english(value)
        if replacement:
            _set_scalar(node, replacement, edits)
            return True
    return False


# --- the metamodel walk --------------------------------------------------------------------


def _walk_object(root, kind: str, resolver, report, edits, *, localized_strings: bool = False,
                 owner: str = "") -> None:
    cls = metamodel.class_for_kind(kind)
    props = metamodel.properties(kind)
    # The keys of a localized-strings element live in the namespace of that element, so the
    # dictionary may hold a spelling for this one dictionary (`<Dictionary>.<Key>`).
    name = _mapping_value(root, "Имя") or ""
    scope = name if localized_strings else ""
    _walk_meta_mapping(root, cls, props, kind, resolver, report, edits, owner=name,
                       namespace=name, localized_strings=localized_strings, scope=scope)


def _walk_meta_mapping(node, cls, props, kind, resolver, report, edits, *, owner: str = "",
                       namespace: str = "",
                       localized_strings: bool = False, scope: str = "") -> None:
    for knode, vnode in node.value:
        if not isinstance(knode, yaml.ScalarNode):
            continue
        key = knode.value
        record = props.get(key)
        if record is None and key.isascii():
            # An English-spelled key in a Russian project is legal; find its record.
            canonical = metamodel.canonical_key(kind, key) if kind else key
            record = props.get(canonical)
            key = canonical
        if record is not None:
            english = record.get("en")
            if english and english != knode.value:
                _set_scalar(knode, english, edits)
            elif not english and has_cyrillic(key):
                line, col = _at(knode)
                report.note_platform(key, line, col)
            if localized_strings and key in ("Строки", "Шаблоны"):
                _walk_localization_section(vnode, resolver, report, edits, scope=scope)
                continue
            _meta_value(key, vnode, record, cls, kind, resolver, report, edits, owner, namespace)
        else:
            _component_key_value(knode, vnode, None, resolver, report, edits, owner)


def _meta_value(key, vnode, record, cls, kind, resolver, report, edits, owner: str = "",
                namespace: str = "") -> None:
    value_kind = record.get("kind")
    declared = str(record.get("type") or "")
    if key == "ВидЭлемента":
        replacement = platform_map.kind_english(vnode.value) if isinstance(vnode, yaml.ScalarNode) else None
        if replacement:
            _set_scalar(vnode, replacement, edits)
        elif isinstance(vnode, yaml.ScalarNode) and has_cyrillic(str(vnode.value)):
            line, col = _at(vnode)
            report.note_platform(vnode.value, line, col)
        return
    if isinstance(vnode, yaml.MappingNode):
        if value_kind == "block" and declared == "Localizable":
            return  # localized data blocks hold texts
        if declared.startswith("DataBinding<Type"):
            # A block that BINDS a type (the form a navigation command opens): its scalar is a
            # type name, not data - left alone it points at a name the project no longer has.
            _walk_component_mapping(vnode, resolver, report, edits, owner)
            return
        inner = declared if value_kind == "block" and metamodel.has_class(declared) else None
        if inner and record.get("dispatch"):
            inner = _dispatched_class(inner, record["dispatch"], vnode) or inner
        if inner:
            _walk_meta_mapping(vnode, inner, metamodel.properties_of_class(inner), None,
                               resolver, report, edits, owner=owner)
        else:
            _walk_component_mapping(vnode, resolver, report, edits, owner)
        return
    if isinstance(vnode, yaml.SequenceNode):
        item_cls = record.get("item") or ""
        for item in vnode.value:
            if isinstance(item, yaml.MappingNode):
                name = _mapping_value(item, record.get("dispatch") or "Имя")
                target = metamodel.collection_item_class(cls, key, name) if cls else None
                # The items of one collection share a namespace: two names translated into
                # one word is what the platform refuses on apply.
                own_name = _mapping_value(item, "Имя")
                if own_name and has_cyrillic(own_name):
                    # The very resolution the rewrite uses, qualifier included: a check that
                    # asked differently reported collisions the rewrite does not make.
                    translated, _plane = resolver.identifier(own_name, scope=owner)
                    if translated:
                        report.note_name(f"{namespace}.{key}", own_name, translated)
                if target:
                    _walk_meta_mapping(item, target, metamodel.properties_of_class(target), None,
                                       resolver, report, edits, owner=owner,
                                       namespace=f"{namespace}.{own_name}" if own_name else namespace)
                else:
                    _walk_component_mapping(item, resolver, report, edits, owner)
            elif isinstance(item, yaml.ScalarNode):
                if item_cls.endswith("G5Enum"):
                    _enum_scalar(item, item_cls, resolver, report, edits)
                else:
                    _identifier_value(item, resolver, report, edits)
        return
    # Scalars, by the declared type of the property.
    if not isinstance(vnode, yaml.ScalarNode):
        return
    if key == "Имя":
        # Always a name; the metamodel types some `Name` slots as a plain String. The name is
        # translated in the namespace of the element that declares it: a component property
        # may need a spelling the same word cannot carry globally (the base type already uses
        # the global one, and the server refuses a duplicate).
        _identifier_value(vnode, resolver, report, edits, scope=owner)
        return
    if key == "ОбластьВидимости":
        # An enumeration wherever it stands; on some kinds the record says plain string.
        _enum_scalar(vnode, None, resolver, report, edits)
        return
    if key in _IDENT_VALUE_KEYS and declared not in ("String", "Localizable"):
        _identifier_value(vnode, resolver, report, edits)
        return
    if value_kind == "boolean":
        _boolean_scalar(vnode, edits)
        return
    if value_kind == "enum":
        _enum_scalar(vnode, record.get("enum"), resolver, report, edits)
        return
    if (value_kind == "type" or key == "Тип" or declared in ("TypeNameHolder", "TypeSet")
            or declared.startswith("DataBinding<Type")):
        value = vnode.value
        if isinstance(value, str) and has_cyrillic(value):
            _set_scalar(vnode, translate_type_expression(value, resolver, report, at=_at(vnode)), edits)
        return
    if declared.endswith("G5Enum"):
        _enum_scalar(vnode, declared, resolver, report, edits)
        return
    if declared in ("Term", "AttributeName"):
        _identifier_value(vnode, resolver, report, edits)
        return
    if declared == "UUID":
        return
    _generic_scalar(vnode, resolver, report, edits)


def _mapping_value(node, key: str) -> str | None:
    """The scalar value of the given key of a mapping (`Name`, or a dispatch key)."""
    wanted = (key, "Name") if key == "Имя" else (key,)
    for knode, vnode in node.value:
        if isinstance(knode, yaml.ScalarNode) and knode.value in wanted \
                and isinstance(vnode, yaml.ScalarNode):
            return vnode.value
    return None


def _dispatched_class(item: str, dispatch_key: str, node) -> str | None:
    """The concrete class a dispatched BLOCK resolves to (`RepeatsOnError` by its `Kind` key)."""
    value = _mapping_value(node, dispatch_key)
    if not value:
        return None
    for name, presents in metamodel.dispatched_classes(item):
        if presents == value or terms.common_english(presents) == value:
            return name
    return None


# --- the component walk ---------------------------------------------------------------------


@lru_cache(maxsize=1)
def _ui_components() -> dict:
    try:
        schema = dataset.load_ui_schema(None) or {}
    except Exception:  # noqa: BLE001 - no data, no records
        return {}
    return schema.get("components") or {}


@lru_cache(maxsize=1)
def _any_component_prop() -> dict[str, dict]:
    """{property name: a record} from whichever component declares it - the untyped fallback."""
    out: dict[str, dict] = {}
    for record in _ui_components().values():
        for name, prop in (record.get("props") or {}).items():
            out.setdefault(name, prop)
    return out


def _reset() -> None:
    _ui_components.cache_clear()
    _any_component_prop.cache_clear()


dataset.register_reset(_reset)


def _component_prop(comp_type: str | None, key: str) -> dict | None:
    if comp_type:
        record = ((_ui_components().get(comp_type) or {}).get("props") or {}).get(key)
        if record is not None:
            return record
    return _any_component_prop().get(key)


def _walk_component_mapping(node, resolver, report, edits, owner: str = "") -> None:
    comp_type = None
    for knode, vnode in node.value:
        if isinstance(knode, yaml.ScalarNode) and knode.value in ("Тип", "Type") \
                and isinstance(vnode, yaml.ScalarNode) and isinstance(vnode.value, str):
            comp_type = vnode.value.split("<", 1)[0].strip()
            break
    for knode, vnode in node.value:
        if isinstance(knode, yaml.ScalarNode):
            _component_key_value(knode, vnode, comp_type, resolver, report, edits, owner)


#: An event key of a component: the platform names its own events this way, and a project
#: component follows the same habit. The VALUE of such a key is the handler METHOD - left as
#: data it names a method that the rename has already moved.
_EVENT_KEY_RE = re.compile(r"^(При|On)[А-ЯЁA-Z]", re.UNICODE)


def _is_event_key(key: str) -> bool:
    return bool(_EVENT_KEY_RE.match(key))


def _looks_like_type(value: str) -> bool:
    """A scalar shaped like a type expression: a dotted name, optionally generic or nullable."""
    return bool(re.match(r"^\w+(\.\w+)+\??$", value, re.UNICODE)) or "<" in value


def _typed_value(node, type_name: str, resolver, report, edits) -> None:
    """The value of a typed block: an item of `type_name` when that is an enumeration."""
    value = node.value
    if not isinstance(value, str) or not has_cyrillic(value):
        return
    replacement = platform_map.enum_value_of(type_name, value)
    if not replacement:
        replacement, plane = resolver.identifier(value, after_dot=True, scope=type_name)
        del plane
    if replacement:
        _set_scalar(node, replacement, edits)
    else:
        line, col = _at(node)
        report.note_token(value, line, col)


def _component_key_value(knode, vnode, comp_type, resolver, report, edits, owner: str = "") -> None:
    key = knode.value
    if has_cyrillic(key):
        # A property of a PROJECT component belongs to the project: the platform vocabulary
        # happens to know the word (`ПриУдалении` is a platform event elsewhere), and using
        # its spelling here renames a property the project declared under another name.
        # The structural keys of a node belong to the platform whatever the component is:
        # one says which component this is, the other names the node.
        structural = key in ("Тип", "Имя")
        # ...and only a name the PROJECT declared is the project's: a component of its own
        # still inherits the platform properties, and those keep the platform spelling.
        project_component = (
            not structural
            and bool(comp_type)
            and comp_type not in _ui_components()
            and key in resolver.project_names
        )
        english = (
            resolver.dictionary.token(key, comp_type) if project_component else None
        ) or (
            None if project_component else (
                platform_map.property_english(key)
                or metamodel.english_name(key)
                or terms.english(key, "properties")
                or terms.common_english(key)
            )
        )
        if english:
            _set_scalar(knode, english, edits)
        else:
            # Not a key the platform names: a custom property or event of a PROJECT
            # component, or a field of a project structure - the project's own token.
            replacement = resolver.dictionary.token(key)
            if replacement:
                report.user_done += 1
                _set_scalar(knode, replacement, edits)
            else:
                line, col = _at(knode)
                report.note_token(key, line, col)
    if isinstance(vnode, yaml.MappingNode):
        _walk_component_mapping(vnode, resolver, report, edits, owner)
        return
    if isinstance(vnode, yaml.SequenceNode):
        for item in vnode.value:
            if isinstance(item, yaml.MappingNode):
                _walk_component_mapping(item, resolver, report, edits, owner)
            elif isinstance(item, yaml.ScalarNode):
                _generic_scalar(item, resolver, report, edits)
        return
    if not isinstance(vnode, yaml.ScalarNode):
        return
    value = vnode.value
    if not isinstance(value, str) or not value:
        return
    if key in ("Тип", "Type") or key in _TYPE_VALUE_KEYS:
        if has_cyrillic(value):
            _set_scalar(vnode, translate_type_expression(value, resolver, report, at=_at(vnode)), edits)
        return
    if key in ("Имя", "Name"):
        _identifier_value(vnode, resolver, report, edits, scope=owner)
        return
    if key in ("ОбластьВидимости", "VisibilityScope"):
        _enum_scalar(vnode, None, resolver, report, edits)
        return
    if key in ("Значение", "Value") and comp_type and not value.startswith(("=", "$")):
        # A typed value block names its type right above (`Type: SubscriptionState`), so the
        # value belongs to THAT enumeration - and a project enumeration answers by dictionary.
        _typed_value(vnode, comp_type, resolver, report, edits)
        return
    if key in ("Ключ", "Key") and has_cyrillic(value) and _looks_like_type(value):
        # The key of a per-type settings map is a TYPE expression, not data.
        _set_scalar(vnode, translate_type_expression(value, resolver, report, at=_at(vnode)), edits)
        return
    if value.startswith(("=", "$")):
        _generic_scalar(vnode, resolver, report, edits)
        return
    if key in _EXPR_VALUE_KEYS:
        if has_cyrillic(value):
            _set_scalar(vnode, translate_expression(value, resolver, report, at=_at(vnode)), edits)
        return
    if key in _IDENT_VALUE_KEYS or _is_event_key(key):
        _identifier_value(vnode, resolver, report, edits)
        return
    record = _component_prop(comp_type, key)
    if record is not None:
        types = [str(t) for t in (record.get("types") or [])]
        if record.get("event"):
            _identifier_value(vnode, resolver, report, edits)
            return
        if record.get("enum"):
            _enum_scalar(vnode, types[-1] if types else None, resolver, report, edits)
            return
        if "Булево" in types and _boolean_scalar(vnode, edits):
            return
        if any(t in ("Строка", "Локализуемое", "ЛокализуемоеЗначение") for t in types):
            _generic_scalar(vnode, resolver, report, edits)
            return
        if any(t.startswith("Событие") for t in types):
            _identifier_value(vnode, resolver, report, edits)
            return
    if _boolean_scalar(vnode, edits):
        return
    _generic_scalar(vnode, resolver, report, edits)


# --- localized strings -----------------------------------------------------------------------


def _walk_localization_body(root, resolver, report, edits, scope: str = "") -> None:
    sections = metamodel.properties("ЛокализованныеСтроки")
    for knode, vnode in root.value:
        if not isinstance(knode, yaml.ScalarNode):
            continue
        english = (sections.get(knode.value) or {}).get("en") or metamodel.english_name(knode.value)
        if english and has_cyrillic(knode.value):
            _set_scalar(knode, english, edits)
        _walk_localization_section(vnode, resolver, report, edits, scope=scope)


def _walk_localization_section(node, resolver, report, edits, scope: str = "") -> None:
    """Keys of the strings and templates sections are the project's tokens; values are data.

    Both sections of a dictionary share ONE namespace (the platform refuses a repeated key
    on apply), so the keys are registered under one namespace of the report - two Russian
    keys translated into one English word is a defect the dictionary alone can fix.
    """
    if not isinstance(node, yaml.MappingNode):
        return
    for knode, _vnode in node.value:
        if not isinstance(knode, yaml.ScalarNode) or not has_cyrillic(knode.value):
            continue
        replacement, plane = resolver.dictionary_key(knode.value, scope)
        if plane == "user":
            report.user_done += 1
        if replacement:
            # The namespace is the DICTIONARY, not "the localization of the project": two
            # dictionaries may hold the same key, and the platform only refuses a repeat
            # inside one element. Calling that a collision sent people renaming keys that
            # never met.
            report.note_name(f"localization:{scope or '?'}", knode.value, replacement)
            _set_scalar(knode, replacement, edits)
        else:
            line, col = _at(knode)
            report.note_token(knode.value, line, col)


# --- descriptors without an element kind ------------------------------------------------------


def _walk_plain(node, resolver, report, edits) -> None:
    """A subsystem or resource descriptor: chain-translated keys, values by shape."""
    for knode, vnode in node.value:
        if not isinstance(knode, yaml.ScalarNode):
            continue
        key = knode.value
        if has_cyrillic(key):
            english = (
                metamodel.english_name(key)
                or uischema.english_property(key)
                or terms.english(key, "properties")
                or terms.common_english(key)
            )
            if english:
                _set_scalar(knode, english, edits)
            else:
                line, col = _at(knode)
                report.note_platform(key, line, col)
        if isinstance(vnode, yaml.MappingNode):
            _walk_plain(vnode, resolver, report, edits)
        elif isinstance(vnode, yaml.SequenceNode):
            for item in vnode.value:
                if isinstance(item, yaml.ScalarNode):
                    _identifier_value(item, resolver, report, edits)
                elif isinstance(item, yaml.MappingNode):
                    _walk_plain(item, resolver, report, edits)
        elif isinstance(vnode, yaml.ScalarNode):
            if _boolean_scalar(vnode, edits):
                continue
            value = vnode.value
            if isinstance(value, str) and has_cyrillic(value) and _IDENT_CHAIN_RE.match(value):
                enum_hit = terms.english(value, "enums")
                if enum_hit:
                    _set_scalar(vnode, enum_hit, edits)
                    continue
            _generic_scalar(vnode, resolver, report, edits)


# --- comments ---------------------------------------------------------------------------------

_COMMENT_TEXT_RE = re.compile(r"^(#+\s*)(.*?)(\s*)$")


def _scalar_spans(root) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    stack = [root] if root is not None else []
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, yaml.ScalarNode):
            spans.append((node.start_mark.index, node.end_mark.index))
        elif isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                stack.append(k)
                stack.append(v)
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
    return spans


def _comment_edits(source: SourceFile, root, resolver, report, edits: list[Edit]) -> None:
    spans = _scalar_spans(root)
    offset = 0
    for number, line in enumerate(source.text.splitlines(keepends=True), 1):
        body = line.rstrip("\r\n")
        hash_pos = body.find("#")
        while hash_pos != -1:
            absolute = offset + hash_pos
            before = body[:hash_pos]
            standalone = not before.strip()
            trailing = hash_pos > 0 and body[hash_pos - 1] in " \t"
            inside_scalar = any(start <= absolute < end for start, end in spans)
            if (standalone or trailing) and not inside_scalar:
                match = _COMMENT_TEXT_RE.match(body[hash_pos:])
                if match and has_cyrillic(match.group(2)):
                    payload = match.group(2)
                    start = absolute + match.start(2)
                    translated = resolver.dictionary.phrase(payload)
                    if translated is not None:
                        report.phrases_done += 1
                        if translated != payload:
                            edits.append((start, start + len(payload), translated))
                    else:
                        report.note_phrase(payload, number, hash_pos + 1)
                break
            hash_pos = body.find("#", hash_pos + 1)
        offset += len(line)
