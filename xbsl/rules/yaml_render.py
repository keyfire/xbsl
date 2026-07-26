"""Tier D: what the renderer silently drops – an empty sized group and an over-long hint.

Both gotchas share a shape: the file is valid, the compiler is happy, the application deploys,
and the screen simply does not show what the author wrote. Nothing but a rule catches that
before a human notices it in a browser.

- `yaml/empty-group-sized` – a `Группа` with a fixed `Высота`/`Ширина` and no `Содержимое` is
  thrown out of the DOM entirely: the spacer it was meant to be leaves no gap at all (found
  twice on the same page of a live project). The cure is a non-empty transparent insert – a
  `КонтейнерHtml` of the same height whose content only paints nothing.
- `yaml/hint-too-long` – the renderer cuts a `Подсказка` off with an ellipsis at about 290
  characters, and the tail is not shown at all: there is no scroll and no "more" affordance,
  so the end of a long explanation is simply lost.

The limit is deliberately checked with a margin (the exact cut-off depends on the font and the
width, and the measured value is about 290): only a hint that is longer than the measured limit
by a clear margin is reported, so a text that may still fit is left alone.

Positions come from the composed yaml node graph, so equal values in different nodes are told
apart.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n, uischema
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
    "yaml/empty-group-sized.title": {
        "ru": "Пустая группа с размером не отрисуется",
        "en": "An empty sized group will not render",
    },
    "yaml/empty-group-sized.spacer": {
        "ru": "Пустая {n[Группа]} с {size_key}: {value} и без {n[Содержимое]} не отрисуется вовсе – "
              "рендер выбрасывает такой узел, и зазора не будет. Нужен зазор – поставьте непустую "
              "прозрачную вставку {n[КонтейнерHtml]} той же высоты.",
        "en": "An empty {n[Группа]} with {size_key}: {value} and no {n[Содержимое]} will not render "
              "at all – the renderer throws such a node out, and there will be no gap. If a gap is "
              "what is needed, use a non-empty transparent {n[КонтейнерHtml]} of the same height.",
    },
    "yaml/hint-too-long.title": {
        "ru": "Подсказка длиннее предела отрисовки",
        "en": "The hint is longer than the render limit",
    },
    "yaml/hint-too-long.cut": {
        "ru": "{n[Подсказка]} длиной {length} символов – рендер обрывает её примерно на {limit}, "
              "и хвост не показывается вовсе. Сожмите текст под предел.",
        "en": "A {n[Подсказка]} of {length} characters – the renderer cuts it off at about {limit}, "
              "and the tail is not shown at all. Shorten the text to fit.",
    },
}
i18n.register(MESSAGES)

# The measured cut-off of the hint (a live project, the session-categories tooltip).
HINT_LIMIT = 290

# The margin over the limit at which the rule speaks: closer to the limit the outcome depends on
# the font and the width, and a text that may still fit must not be reported.
HINT_MARGIN = 20

_SIZE_KEYS = ("Высота", "Ширина")


def _fixed_size(node) -> bool:
    """Whether the scalar is a fixed positive number (not Авто, not a binding, not zero)."""
    if not isinstance(node, yaml.ScalarNode):
        return False
    try:
        return float(node.value) > 0
    except ValueError:
        return False


def _object_mappings(source: SourceFile):
    """Every mapping of a yaml object file, or nothing when the file is not one."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return []
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return []
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return []
    return _mapping_nodes(root)


@rule("yaml/empty-group-sized", "yaml/empty-group-sized.title", "D", severity=Severity.WARNING)
def empty_group_sized(source: SourceFile) -> Iterable[Diagnostic]:
    """A `Группа` with a size and no content – the renderer drops it, the spacer never appears.

    Only a group whose `Содержимое` key is absent altogether or holds an empty sequence is
    judged: a group filled by a binding (`Содержимое: =...`) or by anything else is content
    the rule cannot weigh.
    """
    for mapping in _object_mappings(source):
        keys = _scalar_entries(mapping)
        type_entry = keys.get("Тип")
        if (
            type_entry is None
            or not isinstance(type_entry[1], yaml.ScalarNode)
            or uischema.canonical_component(type_entry[1].value) != "Группа"
        ):
            continue
        content = keys.get("Содержимое")
        if content is not None and not (
            isinstance(content[1], yaml.SequenceNode) and not content[1].value
        ):
            continue
        for size_key in _SIZE_KEYS:
            entry = keys.get(size_key)
            if entry is None or not _fixed_size(entry[1]):
                continue
            key_node = entry[0]
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/empty-group-sized", Severity.WARNING,
                i18n.t(
                    "yaml/empty-group-sized.spacer",
                    size_key=key_node.value, value=entry[1].value,
                ),
            )
            return  # one finding per node: both axes are the same defect


@rule("yaml/hint-too-long", "yaml/hint-too-long.title", "D", severity=Severity.WARNING)
def hint_too_long(source: SourceFile) -> Iterable[Diagnostic]:
    """A `Подсказка` longer than the render limit – the tail is lost without a trace.

    A binding (`=...`) is skipped: the text is computed, and its length is not in the file.
    """
    for mapping in _object_mappings(source):
        entry = _scalar_entries(mapping).get("Подсказка")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        text = entry[1].value
        if text.startswith("=") or len(text) <= HINT_LIMIT + HINT_MARGIN:
            continue
        key_node = entry[0]
        yield Diagnostic(
            source.rel,
            key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/hint-too-long", Severity.WARNING,
            i18n.t("yaml/hint-too-long.cut", length=len(text), limit=HINT_LIMIT),
        )
