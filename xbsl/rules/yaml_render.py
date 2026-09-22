"""Tier D: what the renderer silently drops - an empty sized group, an over-long hint, a
nullable date input.

The gotchas here share a shape: the file is valid, the compiler is happy, the application
deploys, and the screen simply does not show what the author wrote. Nothing but a rule catches
that before a human notices it in a browser.

- `yaml/empty-group-sized` - a `Group` with a fixed `Height`/`Width` and no `Content` is
  thrown out of the DOM entirely: the spacer it was meant to be leaves no gap at all (found
  twice on the same page of a live project). The cure is a non-empty transparent insert - a
  `КонтейнерHtml` of the same height whose content only paints nothing.

  A size given as a binding (`Высота: =ОтступСнизу`) is the same defect in disguise - the node
  is dropped whatever the binding yields - but it is judged only on a group WITHOUT a `Name`:
  a named empty container is a legitimate pattern, code fills it through the name
  (`Компоненты.<Имя>.Содержимое.Добавить`), while an unnamed one is unreachable from code and
  stays empty forever (a spacer of exactly this shape sat unnoticed on a live public page for
  a month and a half). The cure there is a spacer label of the same height, or a
  `VerticalIndent` on the element the gap was meant for.
- `yaml/hint-too-long` - the renderer cuts a `Tooltip` off with an ellipsis at about 290
  characters, and the tail is not shown at all: there is no scroll and no "more" affordance,
  so the end of a long explanation is simply lost.
- `yaml/insert-row-needs-align` - a horizontal group with no explicit vertical alignment lays
  its children out on the BASELINE, and an insert frame (`HtmlContainer`) carries a baseline
  of its own: the card holding it slides down against its neighbours (50 px on a live bento
  row, 2026-08). Nothing but an eye catches it - the file, the compile and the apply are all
  fine. The cure is one property on the ROW: `ContentVerticalAlign: Top`.

  The judged group is the NEAREST horizontal ancestor of the insert - the one whose baseline
  the insert actually breaks; a horizontal group deeper on the path takes the blame instead of
  its parent, which is what keeps a row whose inner strip is already aligned silent (a live
  project's media group reads exactly that way). Vertical groups on the path are transparent:
  the cards of a row are usually vertical. A group with a single child is skipped - there is
  nothing to slide against.

  The same rule judges a native `Button` next to a native `Picture` standing in the row
  directly. A button keeps its baseline on the caption and a picture on its bottom edge, so
  the button sank 19 px below a picture of the same height on a live row; the cure there is
  `ContentVerticalAlign: Center`. Only this pair is judged, because only this pair was
  measured: a button without a visible caption, a label, a pair inside a card, a child that sets
  its own vertical alignment - none of them is guessed at. A layout binding counts in its
  statically horizontal branches. The pair is judged when one of the two is shown
  unconditionally or both are shown under the same conditions; two different conditions may
  exclude each other in the program, so such a pair is left alone (xbsl/rules/_rows.py).
- `yaml/component-row-needs-align` - the same pair when a neighbour is DRAWN by a project
  component: a wrapper that shows a native button or picture, or picks between the two by
  its own property. The component description lies in another file, so this half is a
  project rule; the file rule keeps the rows it can judge alone, and the project rule leaves
  them to it. A component is expanded only as far as xbsl/rules/_rows.py can read it, and a
  child it cannot resolve takes no part in a pair.

- `yaml/date-input-needs-plain-date` - `Edit<Date?>` is silently not rendered: no field,
  no apply-time error, and a group that held only such fields disappears entirely (found on a
  live project, 2026-08: two date fields read as "the change did not apply"). The cure is a
  plain type - the attribute `Type: Date`, the field `Edit<Date>`, "not set" expressed as
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

from xbsl import i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule, rule_param
from xbsl.parser import parse
from xbsl.rules import _rows
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
    object_kind,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "yaml/insert-row-needs-align.title": {
        "ru": "Ряд без явного выравнивания, у соседей разная базовая линия",
        "en": "A row without an explicit alignment holds neighbours with different baselines",
    },
    "yaml/insert-row-needs-align.button-picture": {
        "ru": "Горизонтальная группа без ВыравниваниеСодержимогоПоВертикали равняет детей по "
              "базовой линии. У Кнопка она проходит по надписи, у Картинка – по нижнему краю, "
              "поэтому '{button}' и '{picture}' встают на разную высоту (на живом ряду кнопка "
              "опустилась на 19 px). Задайте ряду ВыравниваниеСодержимогоПоВертикали: Центр.",
        "en": "A horizontal group with no {n[ВыравниваниеСодержимогоПоВертикали]} lines its "
              "children up on the baseline. A {n[Кнопка]} keeps it on the caption and a "
              "{n[Картинка]} on its bottom edge, so '{button}' and '{picture}' stand at "
              "different heights (the button sank 19 px on a live row). Set "
              "{n[ВыравниваниеСодержимогоПоВертикали]}: {n[Центр]} on the row.",
    },
    "yaml/component-row-needs-align.title": {
        "ru": "Ряд из компонентов ставит кнопку рядом с картинкой без явного выравнивания",
        "en": "A row of components puts a button next to a picture without an explicit alignment",
    },
    "yaml/component-row-needs-align.pair": {
        "ru": "Горизонтальная группа без ВыравниваниеСодержимогоПоВертикали равняет детей по "
              "базовой линии, а её соседи рисуют разное: '{button}' – Кнопка с базовой линией по "
              "надписи, '{picture}' – Картинка с базовой линией по нижнему краю. Они встают на "
              "разную высоту (на живом ряду кнопка опустилась на 19 px). Задайте ряду "
              "ВыравниваниеСодержимогоПоВертикали: Центр.",
        "en": "A horizontal group with no {n[ВыравниваниеСодержимогоПоВертикали]} lines its "
              "children up on the baseline, and its neighbours draw different things: "
              "'{button}' is a {n[Кнопка]} with the baseline on the caption, '{picture}' is a "
              "{n[Картинка]} with the baseline on its bottom edge. They stand at different "
              "heights (the button sank 19 px on a live row). Set "
              "{n[ВыравниваниеСодержимогоПоВертикали]}: {n[Центр]} on the row.",
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
    "yaml/hint-too-long.param.limit": {
        "ru": "предел подсказки в символах: длиннее платформа обрезает текст при отрисовке",
        "en": "the hint limit in characters: past it the platform cuts the text when rendering",
    },
    "yaml/hint-too-long.param.margin": {
        "ru": "запас над пределом, с которого правило заговаривает: у самой границы исход "
              "зависит от шрифта и ширины",
        "en": "the margin over the limit at which the rule speaks: right at the border the "
              "outcome depends on the font and the width",
    },
}
i18n.register(MESSAGES)

# The measured cut-off of the hint (a live project, the session-categories tooltip).
HINT_LIMIT = rule_param("yaml/hint-too-long", "limit", 290, "yaml/hint-too-long.param.limit")

# The margin over the limit at which the rule speaks: closer to the limit the outcome depends on
# the font and the width, and a text that may still fit must not be reported.
HINT_MARGIN = rule_param("yaml/hint-too-long", "margin", 20, "yaml/hint-too-long.param.margin")

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
    """Whether the scalar is a size binding (`=...`) - a value computed at run time.

    A block scalar (`|`, `>`) is text, not a binding, and is skipped the way the other
    binding-aware rules skip it; a quote style does not matter - the platform reads the
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


#: The insert frame, whose own baseline breaks an unaligned row.
_INSERT = "КонтейнерHtml"


def _is_horizontal(mapping) -> bool:
    return _rows.is_horizontal(_scalar_entries(mapping))


def _row_findings(mapping, nearest, out: list) -> None:
    """Walk the subtree, pairing every insert with the nearest horizontal ancestor."""
    for child in _rows.component_children(mapping):
        if _rows.component_kind(child) == _INSERT and nearest is not None:
            out.append(nearest)
        _row_findings(child, child if _is_horizontal(child) else nearest, out)


def _row_verdict(mapping):
    """(layout key node, message) when the file rule reports the group, else None.

    The project rule asks the same question first and leaves such a row alone.
    """
    entries = _scalar_entries(mapping)
    if _rows.ALIGN_KEY in entries:
        return None
    horizontal = _rows.row_formula(entries)
    if horizontal is None:
        return None
    children = _rows.component_children(mapping)
    if len(children) < 2:
        return None  # a single child has nothing to slide against
    key_node = entries[_rows.LAYOUT_KEY][0]
    rows: list = []
    _row_findings(mapping, mapping, rows)
    if any(row is mapping for row in rows):
        return key_node, i18n.t("yaml/insert-row-needs-align.baseline")
    taking_part = []
    for child in children:
        drawn = _rows.participant(child)
        if drawn is not None:
            taking_part.append((*drawn, _rows.label(child)))
    pair = _rows.conflict(horizontal, taking_part)
    if pair is None:
        return None  # no insert of its own, and no button shown together with a picture
    return key_node, i18n.t(
        "yaml/insert-row-needs-align.button-picture", button=pair[0], picture=pair[1],
    )


@rule(
    "yaml/insert-row-needs-align", "yaml/insert-row-needs-align.title", "D",
    severity=Severity.WARNING,
)
def insert_row_needs_align(source: SourceFile) -> Iterable[Diagnostic]:
    """A row without an explicit vertical alignment whose children stand on different baselines."""
    seen: set[tuple[int, int]] = set()
    for mapping in _object_mappings(source):
        verdict = _row_verdict(mapping)
        if verdict is None:
            continue
        key_node, message = verdict
        position = (key_node.start_mark.line + 1, key_node.start_mark.column + 1)
        if position in seen:
            continue
        seen.add(position)
        yield Diagnostic(
            source.rel, position[0], position[1],
            "yaml/insert-row-needs-align", Severity.WARNING, message,
        )


def _component_row(mapping) -> dict | None:
    """The fact of a row the file rule cannot judge alone: a child is a project component."""
    entries = _scalar_entries(mapping)
    if _rows.ALIGN_KEY in entries:
        return None
    children = _rows.component_children(mapping)
    if len(children) < 2:
        return None
    if not any(_rows.child_is_component(child) for child in children):
        return None
    horizontal = _rows.row_formula(entries)
    if horizontal is None or _row_verdict(mapping) is not None:
        return None
    key_node = entries[_rows.LAYOUT_KEY][0]
    return {
        "line": key_node.start_mark.line + 1,
        "col": key_node.start_mark.column + 1,
        "horizontal": horizontal,
        "children": [_rows.child_fact(child) for child in children],
    }


def _component_row_mapper(source: SourceFile) -> dict | None:
    """The map phase: what a component draws, the conditions of its module, the rows of a page."""
    if source.kind == "xbsl":
        if is_query_file(source.path):
            return None
        module, errors = parse(source)
        if errors:
            return None
        methods = _rows.module_conditions(module, source.text)
        return {"stem": _pair_stem(source.rel), "methods": methods} if methods else None
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, error = _parsed(source)
    root = _composed(source) if error is None and _is_object(data) else None
    if root is None:
        return None
    fact: dict = {}
    if object_kind(data) == "КомпонентИнтерфейса":
        name = next(
            (data[key] for key in terms.key_forms("Имя") if isinstance(data.get(key), str)), None,
        )
        if name:
            fact["comp"] = {**_rows.component_fact(root, name), "stem": _pair_stem(source.rel)}
    rows = [row for row in map(_component_row, _mapping_nodes(root)) if row is not None]
    if rows:
        fact["rows"] = rows
    return fact or None


@rule(
    "yaml/component-row-needs-align", "yaml/component-row-needs-align.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_component_row_mapper,
)
def component_row_needs_align(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A row where a project component draws a button or a picture next to the other one."""
    definitions: dict[str, list[dict]] = {}
    conditions: dict[str, dict] = {}
    for fact in facts.values():
        if "comp" in fact:
            definitions.setdefault(fact["comp"]["name"], []).append(fact["comp"])
        if "methods" in fact:
            conditions[fact["stem"]] = fact["methods"]
    for rel in sorted(facts):
        for row in facts[rel].get("rows", ()):
            taking_part = []
            for child in row["children"]:
                if child["native"] is not None:
                    taking_part.append((*child["native"], child["label"]))
                    continue
                found = definitions.get(child["type"]) if child["component"] else None
                if not found or len(found) != 1:
                    continue  # no description, or two components of one name
                definition = found[0]
                drawn = _rows.instance_draw(
                    child, definition, conditions.get(definition["stem"], {}),
                )
                if drawn is not None:
                    named = child["label"] != child["type"]
                    shown_as = f"{child['label']} ({child['type']})" if named else child["type"]
                    taking_part.append((*drawn, shown_as))
            pair = _rows.conflict(row["horizontal"], taking_part)
            if pair is None:
                continue
            yield Diagnostic(
                rel, row["line"], row["col"], "yaml/component-row-needs-align", Severity.WARNING,
                i18n.t("yaml/component-row-needs-align.pair", button=pair[0], picture=pair[1]),
            )


@rule("yaml/empty-group-sized", "yaml/empty-group-sized.title", "D", severity=Severity.WARNING)
def empty_group_sized(source: SourceFile) -> Iterable[Diagnostic]:
    """A `Group` with a size and no content - the renderer drops it, the spacer never appears.

    Only a group whose `Содержимое` key is absent altogether or holds an empty sequence is
    judged: a group filled by a binding (`Содержимое: =...`) or by anything else is content
    the rule cannot weigh.

    The size comes in two flavours. A positive literal is judged on any such group - the node
    is dropped regardless of what else it declares. A binding (`Высота: =ОтступСнизу`) is
    judged only on a group WITHOUT a `Name`: a named empty container is filled from code
    through its name (`Компоненты.<Имя>.Содержимое.Добавить` - both live near-misses of the wider
    predicate on real projects are exactly that), while an unnamed one is unreachable from
    code, so the renderer drops it whatever the binding yields - the exact spacer shape that
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
            continue  # a named empty container is filled from code - a legitimate pattern
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
    """`ПолеВвода<Дата?>` - the renderer silently drops the field; the type must be plain.

    The position points at the argument inside the value - the place to actually edit. A
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
    """A `Tooltip` longer than the render limit - the tail is lost without a trace.

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
