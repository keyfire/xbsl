"""`yaml/component-member-unique`: a name shared by the own properties and events of a component.

An interface component declares its own properties (`Properties`) and its own events (`Events`)
by name, and the two lists are one namespace to the compiler. A probe on a live server built a
component with a property and an event of the same name and was refused twice: "Property name
X is not unique" at the property, "Event name X is not unique" at the event. The build stops
there, so the name has to change on one side - the paired module reads the property as
`этот.X` and a form using the component binds a handler to the event by the same name.

Judged is the component's own yaml: the top-level `Properties` and `Events` of an element of
the kind `InterfaceComponent`. The markup under `Inherits` is not looked at - a nested
component's name lives in another namespace. A repeated name is reported at every occurrence
after the first, and the message names the line of the first. There is no fix: which of the
two to rename is the author's call.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, object_kind_fast
from xbsl.rules.yaml_types import _key_spellings

if _HAVE_YAML:
    import yaml

RULE = "yaml/component-member-unique"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Свойство и событие компонента с одним именем",
        "en": "A component property and event sharing a name",
    },
    f"{RULE}.found": {
        "ru": "{what} '{name}' повторяет имя, объявленное в строке {line} ({first}). Свойства и "
              "события компонента – одно пространство имен, и сборка откажет: \"{compiler} "
              "name \"{name}\" is not unique\". Переименуйте одно из двух.",
        "en": "{what} '{name}' repeats the name declared at line {line} ({first}). The properties "
              "and events of a component share one namespace, and the build refuses it: "
              "\"{compiler} name \"{name}\" is not unique\". Rename one of the two.",
    },
    f"{RULE}.property": {"ru": "Свойство", "en": "Property"},
    f"{RULE}.event": {"ru": "Событие", "en": "Event"},
    f"{RULE}.property-of": {"ru": "свойство", "en": "a property"},
    f"{RULE}.event-of": {"ru": "событие", "en": "an event"},
}
i18n.register(MESSAGES)

_KIND = "КомпонентИнтерфейса"
#: The two sections and the word the compiler names each by in its refusal.
_SECTIONS = (("Свойства", "property", "Property"), ("События", "event", "Event"))
_NAME = "Имя"


def _declared(root) -> Iterable[tuple[str, str, object]]:
    """(name, role, the name's scalar node) of every own property and event, in file order."""
    names = set(_key_spellings(_NAME))
    for key, value in root.value:
        if not isinstance(key, yaml.ScalarNode) or not isinstance(value, yaml.SequenceNode):
            continue
        role = next((r for section, r, _ in _SECTIONS if key.value in _key_spellings(section)), None)
        if role is None:
            continue
        for item in value.value:
            if not isinstance(item, yaml.MappingNode):
                continue
            for item_key, item_value in item.value:
                if (isinstance(item_key, yaml.ScalarNode) and item_key.value in names
                        and isinstance(item_value, yaml.ScalarNode) and item_value.value):
                    yield item_value.value, role, item_value
                    break


@rule(RULE, f"{RULE}.title", "A", severity=Severity.ERROR)
def component_member_unique(source: SourceFile) -> Iterable[Diagnostic]:
    """A name repeated among the own properties and events of a component - see the docstring."""
    if source.kind != "yaml" or not _HAVE_YAML or object_kind_fast(source) != _KIND:
        return
    root = _composed(source)
    if not isinstance(root, yaml.MappingNode):
        return
    compiler = {role: word for _, role, word in _SECTIONS}
    first: dict[str, tuple[str, int]] = {}
    for name, role, node in _declared(root):
        line = node.start_mark.line + 1
        if name not in first:
            first[name] = (role, line)
            continue
        first_role, first_line = first[name]
        yield Diagnostic(
            source.rel, line, node.start_mark.column + 1, RULE, Severity.ERROR,
            i18n.t(
                f"{RULE}.found", what=i18n.t(f"{RULE}.{role}"), name=name, line=first_line,
                first=i18n.t(f"{RULE}.{first_role}-of"), compiler=compiler[role],
            ),
        )
