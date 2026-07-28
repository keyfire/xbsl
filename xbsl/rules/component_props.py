"""Tier A: a markup key that belongs to ANOTHER interface component.

The yaml/unknown-component-property rule. A node of the markup names its component in `Type`,
and every other key of that node is a property of that component. A key the component does
not have costs a deploy cycle: applying the build answers `Неизвестное свойство "X"` -
measured on a probe for `Checkbox` + `PlaceholderText` and for `HtmlEditor` +
`DataValidationResult` / `MessageWarning`. All three are properties of `Edit` copied over to a
neighbouring component, which is what the rule is named after: the key exists in the platform,
just not here.

Judged is exactly that class - a key the ui schema declares as a TYPED property of at least
one other component. The reason is that the documentation does not describe a component's
yaml keys in full, and the gaps are not guessable:

- the reference page of a constructible component lists its properties in the constructor,
  and a property outside it (`ListForm.TableComponent`) is only in the prose section;
- the keys of an instance description are the business of the guide topics
  (`IncludeInAutoInterface`, `TrackDataModification`, the title of a list form's create
  command), and only about half the components have such a topic;
- a legal property may be missing from the reference entirely and appear only in the guide
  (`FilesChoice.Title`) - or in neither, as `StandardTableColumn.BadgeBackgroundColor` and the
  events of `SchedulesComponent`, which the documentation writes in its own examples while
  describing them nowhere.

So "not in the schema" alone is not a violation, and the extractor now folds what the prose
and the guides state into `yaml_props` (see xbsl/extract/uischema.py). What remains judged is
the copy-over: a name the platform does type - for another component. A key nothing declares
(a typo, an undocumented property) is silence, deliberately: on real projects such keys are
legal far more often than not.

Zero-false-positive guards beyond that:

- only nodes UNDER `Inherits` are walked - the markup of a component instance. Elsewhere a
  `Type` names a type, not a component: an item of `Properties` declaring `Type: Picture`
  carries `DefaultValue`, which is no component property at all;
- a node is judged only when its `Type` names a component of the schema (the generic head is
  taken: `Edit<String>` -> `Edit`), so a project component - whose own properties the schema
  cannot know - is never judged;
- `Type` and `Name` are the structural keys of a node, always allowed;
- a Latin key that the platform dictionaries cannot map to a schema name is skipped: the data
  does not spell every component property in English (the property dictionary is built from
  the sources that do, and a handful of properties have no English spelling anywhere), so
  judging an ASCII key would report legal English sources. A missed finding rather than a
  false one.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _parsed,
    _scalar_entries,
    yaml,
)

MESSAGES = {
    "yaml/unknown-component-property.title": {
        "ru": "Неизвестное свойство компонента",
        "en": "Unknown component property",
    },
    "yaml/unknown-component-property.foreign": {
        "ru": "Свойства '{prop}' у компонента '{component}' нет – оно объявлено у {owners}. "
              "Применение сборки отвергнет узел разметки ('Неизвестное свойство').",
        "en": "Component '{component}' has no property '{prop}' – it is declared by {owners}. "
              "Applying the build rejects the markup node ('Неизвестное свойство').",
    },
}
i18n.register(MESSAGES)

#: The key whose subtree is the markup of the component instance, either spelling.
_MARKUP_KEYS = ("Наследует", "Inherits")
#: Keys of a markup node that name the node itself rather than a property of the component.
_STRUCTURAL = frozenset({"Тип", "Имя"})


@lru_cache(maxsize=1)
def _tables() -> tuple[dict[str, frozenset[str]], dict[str, tuple[str, ...]]]:
    """({component: the keys it accepts}, {property: the components that declare it}).

    Built once: resolving the dataset walks the installed data plugins, and both tables are
    the same for every file. The accepted keys are the typed properties plus `yaml_props` -
    the names the prose and the guide topics state (see the module docstring); the owner
    table holds TYPED properties only, so an undocumented or instance-only key is never
    judged for anyone.

    A schema generated before `yaml_props` existed knows the constructor parameters alone,
    and judging against it reports legal code all over a real project. Such a schema switches
    the rule off entirely - the same degradation as having no data at all.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}, {}
    records = (schema.get("components") or {}).values()
    if not any(record.get("yaml_props") for record in records):
        return {}, {}  # data older than the rule - see the docstring
    accepted: dict[str, frozenset[str]] = {}
    owners: dict[str, list[str]] = {}
    for component, record in (schema.get("components") or {}).items():
        props = record.get("props") or {}
        accepted[component] = frozenset(props) | frozenset(record.get("yaml_props") or ())
        for prop in props:
            owners.setdefault(prop, []).append(component)
    return accepted, {prop: tuple(sorted(names)) for prop, names in owners.items()}


dataset.register_reset(_tables.cache_clear)


def _markup_nodes(root):
    """Every mapping under an `Inherits` key of the document - the markup of an instance."""
    stack = [(root, False)]
    seen: set[int] = set()
    while stack:
        node, inside = stack.pop()
        if id(node) in seen:  # an anchor may alias the same node twice
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            if inside:
                yield node
            for key_node, value_node in node.value:
                is_markup = isinstance(key_node, yaml.ScalarNode) and key_node.value in _MARKUP_KEYS
                stack.append((value_node, inside or is_markup))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend((item, inside) for item in node.value)


def _type_value(mapping):
    """The scalar value node of the `Type` key of a mapping, either spelling, or None."""
    for key_node, value_node in mapping.value:
        if (
            isinstance(key_node, yaml.ScalarNode) and key_node.value in ("Тип", "Type")
            and isinstance(value_node, yaml.ScalarNode)
        ):
            return value_node
    return None


@rule(
    "yaml/unknown-component-property", "yaml/unknown-component-property.title", "A",
    severity=Severity.ERROR,
)
def unknown_component_property(source: SourceFile) -> Iterable[Diagnostic]:
    """A markup key the component does not declare while another component does."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    accepted, owners = _tables()
    if not accepted or not any(key in source.text for key in _MARKUP_KEYS):
        return  # no ui schema, or no component markup in this file
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        component = uischema.canonical_component(type_node.value.split("<", 1)[0].strip())
        allowed = accepted.get(component)
        if allowed is None:
            continue  # a project component, a data type, a command - not a palette component
        # The keys are canonicalized only for a node that is worth judging: building the
        # dictionary for every mapping of every file would be the bulk of the rule's cost.
        for key, (key_node, _value) in _scalar_entries(mapping).items():
            if key in _STRUCTURAL or key in allowed or key_node.value in allowed:
                continue
            declared = owners.get(key)
            if not declared:
                continue  # no component types this name - see the module docstring
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/unknown-component-property", Severity.ERROR,
                i18n.t(
                    "yaml/unknown-component-property.foreign",
                    prop=key_node.value, component=component,
                    owners=", ".join(declared[:3]),
                ),
            )
