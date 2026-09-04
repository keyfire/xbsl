"""Tier D: a slot the schema types as a list, holding a single component.

A container property such as `Content` is declared `Array<Component>`, and a component written
under it WITHOUT the leading dash is one component, not a list of one. Nothing about that reads
as broken: the yaml parses, every key exists, the component is legal in that place. The apply is
what refuses it, on the server, with a message saying the value cannot be assigned to an array -
a whole deploy cycle spent, and the project rolled back to the previous build.

What makes the check possible is that the ui schema already carries both halves: a property
declared a slot, and the type expression it is declared with. So the rule asks the data, not the
property name - `Content` is a list on a group and a single component on a form template, and a
rule keyed by the name would report the second as a defect.

Narrowings, so that doubt keeps silence:

- only nodes UNDER `Inherits` are walked - the markup of a component instance. Elsewhere a
  `Type` names a type rather than a component, and its neighbouring keys are not properties;
- only components the schema knows are judged, by the generic head of the type
  (`Table<X>` -> `Table`): a project component declares its own slots, which the palette
  cannot know;
- only a MAPPING value is judged - one component where a list belongs. A scalar is left alone:
  the schema does not say whether a name may stand for a component there, and an unverified
  reading of a scalar would be a false finding on legal markup;
- the opposite shape - a list in a slot typed with a single component - is NOT judged. The live
  defect this rule is named after went the one way, and the other direction has no evidence
  behind it; judging it would rest on a guess about the compiler.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.component_props import _MARKUP_KEYS, _markup_nodes, _type_value
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _parsed,
    _scalar_entries,
    yaml,
)

MESSAGES = {
    "yaml/slot-needs-list.title": {
        "ru": "Слот-список получил один компонент",
        "en": "A list slot holding a single component",
    },
    "yaml/slot-needs-list.single": {
        "ru": "Свойство '{prop}' компонента '{component}' описано типом '{declared}' – это "
              "список, а здесь под ним стоит один компонент. Применение сборки отвергает такую "
              "разметку сообщением \"не может быть присвоено\": поставьте перед компонентом "
              "дефис, чтобы он стал элементом списка.",
        "en": "Property '{prop}' of component '{component}' is declared '{declared}' - a list - "
              "and here it holds a single component. The apply refuses such markup with a "
              "\"cannot be assigned\" message: put a dash in front of the component so that it "
              "becomes an item of the list.",
    },
}
i18n.register(MESSAGES)

#: Both spellings of the array type constructor, as the schema writes them.
_ARRAY_PREFIXES = ("Массив<", "Array<")


@lru_cache(maxsize=1)
def _array_slots() -> dict[str, dict[str, str]]:
    """{component: {property: the array type it is declared with}}.

    Built once: resolving the dataset walks the installed data plugins, and the table is the
    same for every file. A schema that marks no slot at all leaves the table empty, which
    switches the rule off - the same degradation as having no platform data.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}
    table: dict[str, dict[str, str]] = {}
    for component, record in (schema.get("components") or {}).items():
        slots = {}
        for prop, described in (record.get("props") or {}).items():
            if not described.get("slot"):
                continue
            for expression in described.get("types") or ():
                if expression.startswith(_ARRAY_PREFIXES):
                    slots[prop] = expression
                    break
        if slots:
            table[component] = slots
    return table


dataset.register_reset(_array_slots.cache_clear)


@rule("yaml/slot-needs-list", "yaml/slot-needs-list.title", "D", severity=Severity.ERROR)
def slot_needs_list(source: SourceFile) -> Iterable[Diagnostic]:
    """A slot typed as a list, given one component instead of a list of one."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    table = _array_slots()
    if not table or not any(key in source.text for key in _MARKUP_KEYS):
        return  # no ui schema, or no component markup in this file
    data, error = _parsed(source)
    if error is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _markup_nodes(root):
        type_node = _type_value(mapping)
        if type_node is None:
            continue
        component = uischema.canonical_component(type_node.value.split("<", 1)[0].strip())
        slots = table.get(component)
        if slots is None:
            continue  # a project component, a data type, a command - not a palette component
        for prop, (key_node, value_node) in _scalar_entries(mapping).items():
            declared = slots.get(prop)
            if declared is None or not isinstance(value_node, yaml.MappingNode):
                continue
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/slot-needs-list", Severity.ERROR,
                i18n.t(
                    "yaml/slot-needs-list.single",
                    prop=key_node.value, component=component, declared=declared,
                ),
            )
