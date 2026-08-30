"""Tier D: what the renderer silently drops – an empty sized group, an over-long hint, a
nullable date input.

The gotchas here share a shape: the file is valid, the compiler is happy, the application
deploys, and the screen simply does not show what the author wrote. Nothing but a rule catches
that before a human notices it in a browser.

- `yaml/empty-group-sized` – a `Группа` with a fixed `Высота`/`Ширина` and no `Содержимое` is
  thrown out of the DOM entirely: the spacer it was meant to be leaves no gap at all (found
  twice on the same page of a live project). The cure is a non-empty transparent insert – a
  `КонтейнерHtml` of the same height whose content only paints nothing.

  A size given as a binding (`Высота: =ОтступСнизу`) is the same defect in disguise – the node
  is dropped whatever the binding yields – but it is judged only on a group WITHOUT a `Name`:
  a named empty container is a legitimate pattern, code fills it through the name
  (`Компоненты.<Имя>.Содержимое.Добавить`), while an unnamed one is unreachable from code and
  stays empty forever (a spacer of exactly this shape sat unnoticed on a live public page for
  a month and a half). The cure there is a spacer label of the same height, or a
  `VerticalIndent` on the element the gap was meant for.
- `yaml/hint-too-long` – the renderer cuts a `Подсказка` off with an ellipsis at about 290
  characters, and the tail is not shown at all: there is no scroll and no "more" affordance,
  so the end of a long explanation is simply lost.
- `yaml/insert-row-needs-align` – a horizontal group with no explicit vertical alignment lays
  its children out on the BASELINE, and an insert frame (`HtmlContainer`) carries a baseline
  of its own: the card holding it slides down against its neighbours (50 px on a live bento
  row, 2026-08). Nothing but an eye catches it - the file, the compile and the apply are all
  fine. The cure is one property on the ROW: `VerticalContentAlignment: Top`.

  The judged group is the NEAREST horizontal ancestor of the insert - the one whose baseline
  the insert actually breaks; a horizontal group deeper on the path takes the blame instead of
  its parent, which is what keeps a row whose inner strip is already aligned silent (a live
  project's media group reads exactly that way). Vertical groups on the path are transparent:
  the cards of a row are usually vertical. A group with a single child is skipped - there is
  nothing to slide against.

- `yaml/date-input-needs-plain-date` – `Edit<Date?>` is silently not rendered: no field,
  no apply-time error, and a group that held only such fields disappears entirely (found on a
  live project, 2026-08: two date fields read as "the change did not apply"). The cure is a
  plain type – the attribute `Type: Date`, the field `Edit<Date>`, "not set" expressed as
  the empty date. Only `Date` is judged: the `DateTime`/`Time` siblings have not been
  verified on a live stand, and silence is the safe side until they are.

The limit is deliberately checked with a margin (the exact cut-off depends on the font and the
width, and the measured value is about 290): only a hint that is longer than the measured limit
by a clear margin is reported, so a text that may still fit is left alone.

Positions come from the composed yaml node graph, so equal values in different nodes are told
apart.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, uischema
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
    "yaml/insert-row-needs-align.title": {
        "ru": "Ряд со вставкой без явного выравнивания",
        "en": "A row holding an insert without an explicit alignment",
    },
    "yaml/insert-row-needs-align.baseline": {
        "ru": "Горизонтальная группа со вставкой КонтейнерHtml и без "
              "ВыравниваниеСодержимогоПоВертикали равняет детей ПО БАЗОВОЙ ЛИНИИ, а у вставки "
              "она своя – элемент со вставкой съезжает вниз относительно соседей (на живом "
              "ряду – 50 px). Задайте ряду ВыравниваниеСодержимогоПоВертикали: Верх явно.",
        "en": "A horizontal group holding an {n[КонтейнерHtml]} insert and no "
              "{n[ВыравниваниеСодержимогоПоВертикали]} lays its children out ON THE BASELINE, "
              "and the insert carries one of its own – the element holding it slides down "
              "against its neighbours (50 px on a live row). Set "
              "{n[ВыравниваниеСодержимогоПоВертикали]} on the row explicitly.",
    },
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
    "yaml/empty-group-sized.binding": {
        "ru": "Пустая безымянная {n[Группа]} с биндингом {size_key}: {value} и без {n[Содержимое]} "
              "не отрисуется вовсе – рендер выбрасывает такой узел при любом значении биндинга, и "
              "отступа не будет, а без {n[Имя]} группу не наполнить и из кода. Нужен зазор – несите "
              "его распоркой {n[Надпись]} без текста той же высоты либо задайте "
              "{n[ОтступПоВертикали]} элементу, ради которого отступ писался.",
        "en": "An empty unnamed {n[Группа]} with a {size_key}: {value} binding and no "
              "{n[Содержимое]} will not render at all – the renderer throws such a node out "
              "whatever the binding yields, there will be no gap, and without a {n[Имя]} the group "
              "cannot be filled from code either. If a gap is what is needed, carry it with a "
              "{n[Надпись]} spacer of the same height and no text, or set {n[ОтступПоВертикали]} "
              "on the element the gap was meant for.",
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
    "yaml/date-input-needs-plain-date.title": {
        "ru": "Поле ввода даты с nullable-типом не рисуется",
        "en": "A nullable date input field does not render",
    },
    "yaml/date-input-needs-plain-date.invisible": {
        "ru": "Тип '{field}<{spelled}>' – поле ввода даты, допускающей пустое значение, платформа "
              "молча не отрисовывает: ни поля, ни ошибки применения, а группа, оставшаяся без "
              "содержимого, исчезает целиком. Объявите тип непустым – реквизит "
              "'{n[Тип]}: {arg}', поле '{field}<{arg}>'; 'не задано' выражается пустой датой "
              "'{arg}{{}}'.",
        "en": "Type '{field}<{spelled}>' – an input field for a date that allows the empty value "
              "is silently not rendered: no field, no apply-time error, and a group left without "
              "content disappears entirely. Make the type plain – the attribute "
              "'{n[Тип]}: {arg}', the field '{field}<{arg}>'; 'not set' is expressed by the "
              "empty date '{arg}{{}}'.",
    },
}
i18n.register(MESSAGES)

# The measured cut-off of the hint (a live project, the session-categories tooltip).
HINT_LIMIT = 290

# The margin over the limit at which the rule speaks: closer to the limit the outcome depends on
# the font and the width, and a text that may still fit must not be reported.
HINT_MARGIN = 20

_SIZE_KEYS = ("Высота", "Ширина")

#: A date input with a nullable parameter, both spellings, `?` or `|?` flavour of nullable.
_NULLABLE_DATE_INPUT_RE = re.compile(
    r"^\s*(ПолеВвода|Edit)\s*<\s*((Дата|Date)\s*(?:\?|\|\s*\?))\s*>\s*$"
)


def _fixed_size(node) -> bool:
    """Whether the scalar is a fixed positive number (not Авто, not a binding, not zero)."""
    if not isinstance(node, yaml.ScalarNode):
        return False
    try:
        return float(node.value) > 0
    except ValueError:
        return False


def _binding_size(node) -> bool:
    """Whether the scalar is a size binding (`=...`) – a value computed at run time.

    A block scalar (`|`, `>`) is text, not a binding, and is skipped the way the other
    binding-aware rules skip it; a quote style does not matter – the platform reads the
    string the same either way.
    """
    if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
        return False
    return node.value.strip().startswith("=")


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


#: The layout value that lays children out in a row, and the property that overrides the
#: baseline alignment of such a row.
_HORIZONTAL = "Горизонтальная"
_LAYOUT_ENUM = "КомпоновкаСодержимого"
_LAYOUT_KEY = "Компоновка"
_ALIGN_KEY = "ВыравниваниеСодержимогоПоВертикали"
_INSERT = "КонтейнерHtml"
_CONTENT_KEY = "Содержимое"


def _component_children(mapping):
    """Direct child components of a node: the mappings of its content key."""
    entries = {
        key.value: value for key, value in mapping.value
        if isinstance(key, yaml.ScalarNode)
    }
    content = entries.get(_CONTENT_KEY) or entries.get("Content")
    if isinstance(content, yaml.SequenceNode):
        return [item for item in content.value if isinstance(item, yaml.MappingNode)]
    if isinstance(content, yaml.MappingNode):
        return [content]
    return []


def _component_kind(mapping) -> str | None:
    """The canonical component name of a node, or None when it declares no type."""
    entry = _scalar_entries(mapping).get("Тип")
    if entry is None or not isinstance(entry[1], yaml.ScalarNode):
        return None
    return uischema.canonical_component(entry[1].value.split("<", 1)[0].strip())


@lru_cache(maxsize=1)
def _horizontal_names() -> frozenset[str]:
    """Both spellings of the horizontal layout value, from the platform's own dictionary."""
    aliases = uischema.enum_value_aliases(_LAYOUT_ENUM)
    return frozenset({_HORIZONTAL, aliases.get(_HORIZONTAL)} - {None})


dataset.register_reset(_horizontal_names.cache_clear)


def _is_horizontal(mapping) -> bool:
    entries = _scalar_entries(mapping)
    entry = entries.get(_LAYOUT_KEY) or entries.get("Layout")
    if entry is None or not isinstance(entry[1], yaml.ScalarNode):
        return False
    return entry[1].value.strip() in _horizontal_names()


def _row_findings(mapping, nearest, out: list) -> None:
    """Walk the subtree, pairing every insert with the nearest horizontal ancestor."""
    for child in _component_children(mapping):
        if _component_kind(child) == _INSERT and nearest is not None:
            out.append(nearest)
        _row_findings(child, child if _is_horizontal(child) else nearest, out)


@rule(
    "yaml/insert-row-needs-align", "yaml/insert-row-needs-align.title", "D",
    severity=Severity.WARNING,
)
def insert_row_needs_align(source: SourceFile) -> Iterable[Diagnostic]:
    """A row holding an insert without an explicit vertical alignment."""
    seen: set[int] = set()
    for mapping in _object_mappings(source):
        entries = _scalar_entries(mapping)
        if _ALIGN_KEY in entries or "VerticalContentAlignment" in entries:
            continue
        if not _is_horizontal(mapping):
            continue
        if len(_component_children(mapping)) < 2:
            continue  # a single child has nothing to slide against
        rows: list = []
        _row_findings(mapping, mapping, rows)
        if not any(row is mapping for row in rows):
            continue  # the insert belongs to a deeper row - that one answers for it
        key_node = entries[_LAYOUT_KEY][0]
        position = (key_node.start_mark.line + 1, key_node.start_mark.column + 1)
        if position in seen:
            continue
        seen.add(position)
        yield Diagnostic(
            source.rel, position[0], position[1],
            "yaml/insert-row-needs-align", Severity.WARNING,
            i18n.t("yaml/insert-row-needs-align.baseline"),
        )


@rule("yaml/empty-group-sized", "yaml/empty-group-sized.title", "D", severity=Severity.WARNING)
def empty_group_sized(source: SourceFile) -> Iterable[Diagnostic]:
    """A `Группа` with a size and no content – the renderer drops it, the spacer never appears.

    Only a group whose `Содержимое` key is absent altogether or holds an empty sequence is
    judged: a group filled by a binding (`Содержимое: =...`) or by anything else is content
    the rule cannot weigh.

    The size comes in two flavours. A positive literal is judged on any such group – the node
    is dropped regardless of what else it declares. A binding (`Высота: =ОтступСнизу`) is
    judged only on a group WITHOUT a `Name`: a named empty container is filled from code
    through its name (`Компоненты.<Имя>.Содержимое.Добавить` – both live near-misses of the wider
    predicate on real projects are exactly that), while an unnamed one is unreachable from
    code, so the renderer drops it whatever the binding yields – the exact spacer shape that
    sat unnoticed on a live public page for a month and a half. The literal flavour keeps its
    original reach on purpose: it has live findings behind it and no name-shaped
    counter-example on the corpora.
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
        if "Имя" in keys:
            continue  # a named empty container is filled from code – a legitimate pattern
        for size_key in _SIZE_KEYS:
            entry = keys.get(size_key)
            if entry is None or not _binding_size(entry[1]):
                continue
            key_node = entry[0]
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/empty-group-sized", Severity.WARNING,
                i18n.t(
                    "yaml/empty-group-sized.binding",
                    size_key=key_node.value, value=entry[1].value,
                ),
            )
            return  # one finding per node: both axes are the same defect


@rule(
    "yaml/date-input-needs-plain-date", "yaml/date-input-needs-plain-date.title", "D",
    severity=Severity.WARNING,
)
def date_input_needs_plain_date(source: SourceFile) -> Iterable[Diagnostic]:
    """`ПолеВвода<Дата?>` – the renderer silently drops the field; the type must be plain.

    The position points at the argument inside the value – the place to actually edit. A
    block scalar is text, not a type, and is skipped the same way the reference rule does.
    """
    for mapping in _object_mappings(source):
        entry = _scalar_entries(mapping).get("Тип")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        value_node = entry[1]
        if value_node.style in ("|", ">"):
            continue
        m = _NULLABLE_DATE_INPUT_RE.match(value_node.value)
        if m is None:
            continue
        quote = 1 if value_node.style in ("'", '"') else 0
        yield Diagnostic(
            source.rel,
            value_node.start_mark.line + 1,
            value_node.start_mark.column + 1 + m.start(2) + quote,
            "yaml/date-input-needs-plain-date", Severity.WARNING,
            i18n.t(
                "yaml/date-input-needs-plain-date.invisible",
                field=m.group(1), spelled=m.group(2), arg=m.group(3),
            ),
        )


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
