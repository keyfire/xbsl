"""Tier D: a popup component placed in the yaml markup draws its content inline.

`PopupComponent` is a window: the docs topic "popup-component" describes it opened
exclusively by `OpenInPopupWindow`, its `Opened` property is read-only, and the ui schema
(a container of the common-components package) offers no property restricting the drawing
to the window. Yet the schema formally ACCEPTS a placement in the markup - the node carries
ordinary yaml properties and the compiler is silent - and a placed instance renders as a
regular element: the window content shows up right in the form flow before the window ever
opens. `Visible: False` is not a cure - the platform does not unfold a hidden component,
so the window itself stops working. The only working shape is building the window in code
on every opening (`new PopupComponent(...)` + `OpenInPopupWindow`), which is exactly what
the project sources settled on: the live components (`ЗначокБейджа`, `ПодсказкаПоКлику`)
construct the popup in code, and their yaml comments document the trap in so many words.

The predicate: inside the `Inherits` subtree of a yaml element, a mapping whose `Type`
head (the name before the generic arguments, the `?` suffix and a namespace qualifier) is
the popup component - or a project interface component that TRANSITIVELY inherits it,
closed over the root `Inherits.Type` of every yaml of the project (hence the project
scope; a direct raw placement would be catchable per file, the derived one is not).

What is NOT judged, and why:

- the `Inherits` mapping's own `Type` - that is the legitimate DEFINITION of a derived
  popup component, the very shape the cure produces;
- property and variable declarations (the `Properties` list) - they live outside the
  `Inherits` subtree and reference the component without placing it (the live sources
  keep such a reference to close the popup on mouse-out);
- `PopupMenu` - a different component with a similar name, placed in markup legitimately.

A placement inside the WINDOW content of a derived popup's own definition
(`Inherits/Content/...`) IS judged: there it renders inline in that window's content just
the same.

English spellings are folded through the ui schema data (`PopupComponent`,
`Inherits`/`Type` read directly - the platform accepts either spelling); without the data
bundle the rule still works over Russian sources. All four reconnaissance corpora are
clean (the trap was cleaned out before the rule), so the rule is a zero-noise regression
guard; the seeded fixtures confirmed both the raw and the transitive detection while the
legitimate definition and the property declaration stayed silent.

Positions come from the composed yaml node graph (yaml.compose keeps line/column marks),
so equal type values in different nodes are told apart.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/popup-in-markup.title": {
        "ru": "Всплывающий компонент размещён в разметке",
        "en": "A popup component is placed in the markup",
    },
    "yaml/popup-in-markup.placed": {
        "ru": "{n[ВсплывающийКомпонент]} размещён в разметке: его содержимое рисуется прямо "
              "в строке формы ещё до открытия окна – свойства, ограничивающего отрисовку "
              "окном, у платформы нет, а скрытие через {n[Видимость]} ломает само окно. "
              "Собирайте окно кодом на каждое открытие: новый {n[ВсплывающийКомпонент]}(...) "
              "и затем {n[ОткрытьВоВсплывающемОкне]}().",
        "en": "A {n[ВсплывающийКомпонент]} is placed in the markup: its content is drawn "
              "right in the form flow before the window ever opens – the platform has no "
              "property restricting the drawing to the window, and hiding it via "
              "{n[Видимость]} breaks the window itself. Build the window in code on every "
              "opening: a new {n[ВсплывающийКомпонент]}(...) followed by "
              "{n[ОткрытьВоВсплывающемОкне]}().",
    },
    "yaml/popup-in-markup.derived": {
        "ru": "'{written}' наследует {n[ВсплывающийКомпонент]} и размещён в разметке: его "
              "содержимое рисуется прямо в строке формы ещё до открытия окна – свойства, "
              "ограничивающего отрисовку окном, у платформы нет, а скрытие через "
              "{n[Видимость]} ломает само окно. Собирайте окно кодом на каждое открытие: "
              "новый {written}(...) и затем {n[ОткрытьВоВсплывающемОкне]}().",
        "en": "'{written}' inherits {n[ВсплывающийКомпонент]} and is placed in the markup: "
              "its content is drawn right in the form flow before the window ever opens – "
              "the platform has no property restricting the drawing to the window, and "
              "hiding it via {n[Видимость]} breaks the window itself. Build the window in "
              "code on every opening: a new {written}(...) followed by "
              "{n[ОткрытьВоВсплывающемОкне]}().",
    },
}
i18n.register(MESSAGES)

#: The key whose subtree is the markup of the element, either spelling (the platform reads
#: the sources both ways, see yaml_schema).
_INHERIT_KEYS = ("Наследует", "Inherits")
#: The structural keys of a markup node, either spelling.
_TYPE_KEYS = ("Тип", "Type")
_NAME_KEYS = ("Имя", "Name")

#: The popup component as the schema names it; the English spelling folds into this one
#: through the ui schema data (`canonical_component`).
_POPUP = "ВсплывающийКомпонент"


@lru_cache(maxsize=1)
def _known_components() -> frozenset[str]:
    """The component names the ui schema declares - the fact-size filter of the mapper.

    A placement whose head is a schema component other than the popup can never become a
    finding (the inheritance closure only ever adds PROJECT component names), so the mapper
    drops it on the spot instead of shipping every markup node to the reduce. Without the
    data bundle the set is empty and every head travels - more facts, same findings.
    """
    schema = dataset.load_ui_schema() or {}
    return frozenset(schema.get("components") or ())


dataset.register_reset(_known_components.cache_clear)


def _head(written: str) -> str:
    """The type head as the schema names it: `Pack.MyHint<...>?` -> `MyHint`.

    The generic arguments, the nullable suffix and a namespace qualifier are stripped
    before folding the spelling - a placement writes any of them freely.
    """
    head = written.split("<", 1)[0].strip().rstrip("?").strip()
    if "." in head:
        head = head.rsplit(".", 1)[1]
    return uischema.canonical_component(head)


def _placed_type_nodes(inherits) -> Iterable:
    """Scalar `Type` value nodes of the mappings STRICTLY BELOW the `Inherits` mapping.

    The `Inherits` mapping's own `Type` is the definition of the element and stays out;
    everything deeper - the markup, including the window content of a derived popup's own
    definition - is a placement.
    """
    stack = [(inherits, True)]
    seen: set[int] = set()
    while stack:
        node, top = stack.pop()
        if id(node) in seen:  # an anchor may alias the same node twice
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            for key_node, value_node in node.value:
                if (
                    not top
                    and isinstance(key_node, yaml.ScalarNode)
                    and key_node.value in _TYPE_KEYS
                    and isinstance(value_node, yaml.ScalarNode)
                ):
                    yield value_node
                stack.append((value_node, False))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend((item, False) for item in node.value)


def _popup_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its name with the root `Inherits.Type` head (the
    raw material of the inheritance closure) and the candidate placements of its markup."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if not any(key in source.text for key in _INHERIT_KEYS):
        return None  # the cheap gate: no markup subtree, nothing to contribute
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return None
    entries = {
        key.value: value for key, value in root.value if isinstance(key, yaml.ScalarNode)
    }
    inherits = next((entries[key] for key in _INHERIT_KEYS if key in entries), None)
    if inherits is None:
        return None
    fact: dict = {}
    name_node = next((entries[key] for key in _NAME_KEYS if key in entries), None)
    if isinstance(name_node, yaml.ScalarNode) and isinstance(inherits, yaml.MappingNode):
        for key_node, value_node in inherits.value:
            if (
                isinstance(key_node, yaml.ScalarNode)
                and key_node.value in _TYPE_KEYS
                and isinstance(value_node, yaml.ScalarNode)
            ):
                fact["component"] = [name_node.value.strip(), _head(value_node.value)]
                break
    known = _known_components()
    placed: list[list] = []
    for value_node in _placed_type_nodes(inherits):
        written = value_node.value.strip()
        head = _head(written)
        if head == _POPUP or head not in known:
            placed.append(
                [head, written, value_node.start_mark.line + 1, value_node.start_mark.column + 1]
            )
    if placed:
        fact["placed"] = placed
    return fact or None


@rule(
    "yaml/popup-in-markup", "yaml/popup-in-markup.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_popup_mapper,
)
def popup_in_markup(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A popup component placed in the markup - see the module docstring."""
    parents: dict[str, str] = {}
    for fact in facts.values():
        component = fact.get("component")
        if component:
            parents[component[0]] = component[1]
    popup = {_POPUP}
    changed = True
    while changed:  # transitive closure over the root inheritance of the project
        changed = False
        for child, parent in parents.items():
            if parent in popup and child not in popup:
                popup.add(child)
                changed = True
    for rel, fact in facts.items():
        for head, written, line, col in fact.get("placed") or ():
            if head not in popup:
                continue
            key = "yaml/popup-in-markup.placed" if head == _POPUP else "yaml/popup-in-markup.derived"
            yield Diagnostic(
                rel, line, col, "yaml/popup-in-markup", Severity.WARNING,
                i18n.t(key, written=written),
            )
