"""Tier D: a fixed component size without disabling the stretch (yaml/size-needs-no-stretch).

The platform gotcha: РастягиватьПоВертикали/РастягиватьПоГоризонтали are `Авто|Булево` and at
`Авто` the platform decides on its own whether to stretch the component (the docs topic
"Размещение компонентов на экране"). When it decides to stretch, flex-grow takes the parent's
leftover space and the fixed Высота/Ширина is overridden – blank space below the component,
inflated neighbours. The fix is an explicit `РастягиватьПоВертикали: Ложь` (respectively
`РастягиватьПоГоризонтали: Ложь`) next to the size.

Narrowing – driven by a survey of a real deployed project (130 yaml, 195 nodes carrying
Высота/Ширина), where a formal "size without Растягивать" is often perfectly valid:

- components with an intrinsic (content) size – Картинка (80 nodes), Группа (7), Надпись (1),
  РедакторHtml (1) – practically never set Растягивать next to a size and work fine: for them
  `Авто` reliably resolves to "do not stretch", so they are not checked;
- КонтейнерHtml – the only kind with mass evidence both ways: 73 of 93 size-carrying nodes set
  `Растягивать*: Ложь` (or a binding), yet 20 deployed nodes omit it and still work (the parent
  has no leftover space along that axis, which is not statically decidable). The convention is
  strong but not a 100% law, so a warning is impossible without false positives;
- Таблица<...> (3 without / 1 with) and СтандартнаяКарточка (bindings only) – singular samples,
  not checked.

Hence the rule is a diagnostic hint, not a warning: severity INFO and disabled by default (the
style/line-length model). Enable it point-blank (`--select yaml/size-needs-no-stretch`) when a
layout shows the symptom – blank space or inflated neighbours around a fixed-size component –
to list the candidates. Checked are only КонтейнерHtml nodes (an iframe has no intrinsic size,
so `Авто` most often resolves to "stretch") whose size is a fixed positive number; `Авто`,
bindings (`=...`) and zero are skipped. Only a missing Растягивать* key fires – an explicit
`Авто` or `Истина` is taken as the author's deliberate choice.

Positions come from the composed yaml node graph (yaml.compose keeps line/column marks), so
equal values in different nodes are told apart; PyYAML counts CRLF line breaks correctly.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/size-needs-no-stretch.title": {
        "ru": "Размер без отключения растягивания",
        "en": "A size without disabling the stretch",
    },
    "yaml/size-needs-no-stretch.missing": {
        "ru": "У компонента {type} задан размер {size_key}: {value}, но нет {stretch_key}: Ложь – "
              "при 'Авто' платформа может растянуть компонент на остаток родителя, "
              "и заданный размер будет перебит.",
        "en": "The {type} component has a fixed {size_key}: {value} but no {stretch_key}: Ложь – "
              "at '{n[Авто]}' the platform may stretch the component over the parent's leftover space, "
              "overriding the size.",
    },
}
i18n.register(MESSAGES)

# The component kinds checked: only where `Авто` regularly resolves to "stretch" (no
# intrinsic size) and the `Растягивать*: Ложь` convention is the norm.
_CHECKED_TYPES = frozenset({"КонтейнерHtml"})

# (the size key, the stretch key of the same axis)
_AXES = (
    ("Высота", "РастягиватьПоВертикали"),
    ("Ширина", "РастягиватьПоГоризонтали"),
)


def _fixed_size(node) -> bool:
    """Whether the scalar is a fixed positive number (not Авто, not a binding, not zero)."""
    if not isinstance(node, yaml.ScalarNode):
        return False
    try:
        return float(node.value) > 0
    except ValueError:
        return False


@rule(
    "yaml/size-needs-no-stretch", "yaml/size-needs-no-stretch.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
)
def size_needs_no_stretch(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        keys = _scalar_entries(mapping)
        type_entry = keys.get("Тип")
        if (
            type_entry is None
            or not isinstance(type_entry[1], yaml.ScalarNode)
            or uischema.canonical_component(type_entry[1].value) not in _CHECKED_TYPES
        ):
            continue
        for size_key, stretch_key in _AXES:
            entry = keys.get(size_key)
            if entry is None or stretch_key in keys or not _fixed_size(entry[1]):
                continue
            key_node = entry[0]
            # The advice names the keys the way the file spells them: telling an English-spelled
            # form to add `РастягиватьПоВертикали` would send the author looking for a key that
            # does not belong in it.
            shown_stretch = stretch_key
            if key_node.value.isascii():
                shown_stretch = terms.common_english(stretch_key) or stretch_key
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/size-needs-no-stretch", Severity.INFO,
                i18n.t(
                    "yaml/size-needs-no-stretch.missing",
                    type=type_entry[1].value, size_key=key_node.value,
                    value=entry[1].value, stretch_key=shown_stretch,
                ),
            )
