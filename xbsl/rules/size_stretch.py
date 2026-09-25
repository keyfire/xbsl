"""Tier D: fixed sizes and stretch weights the platform reads differently than intended.

Four checks, all of them disabled by default: each one is true about the layout, yet whether
it MATTERS depends on where the component ends up, which a file cannot say. Enable them
point-blank when the symptom is on the screen.

--- yaml/matrix-group-max-width (a phone draws the page at desktop width) ---

`MaxWidth` of a group is not only a ceiling but the AVAILABLE width the platform lays the
automatic columns of a matrix layout out by. A group with automatic columns of
`MinWidth: 260` and a maximum of 2000 gets `grid-template-columns: 260px 260px 260px 260px`
even on a 390 px screen: the width is computed from the maximum rather than from the window.
The chain of groups then carries that width upwards (groups are `min-width: min-content`) and
the application root becomes wider than the screen - the content runs off the right edge
while `InterfaceKind` is Phone and every mobile branch of the markup has worked.

Hence the rule: "a deliberately large number so the limit never applies" is NOT a technique
on a phone - there must be no limit at all. `MaxWidth` accepts `Auto|Number`, and a width
token is expected to answer `Auto`; a number for computations in code belongs in a separate
method. Judged is a numeric `MaxWidth` on a group that lays out as a matrix (the layout value
or the matrix settings say so); `Auto` and bindings are the cure, not the defect.

--- yaml/card-literal-stretch-weight (a card collapsed to one line on iPhone) ---

`StretchWeight` on a card becomes a flex with a ZERO BASIS. In a horizontal row that is
exactly right - the cards share the width. But when the same component goes into a vertical
column on a phone, the zero basis applies to the HEIGHT instead: Safari leaves the card zero
height and clips the content with the rounding, while Chrome inflates it by content and shows
no defect at all. The cure is to drop the weight on a phone (a binding that answers `Auto`
there and the weight on a wide screen) - on the card AND on its inner columns.

The defect was found on the owner's own device: neither Chrome's emulation nor WebKit with an
iPhone profile reproduces it. So the rule judges only the LITERAL weight - a binding is
already the cure - and stays off by default: a card that lives only in a wide row keeps its
literal weight legitimately.

Judged are the card itself and the GROUPS inside it - the inner columns the cure had to
cover as well. Everything else inside a card is left alone, and reconnaissance is why: a
live project carries four literal weights on `Label` nodes inside cards (a text sharing
the width of its row), which the collapse does not touch.

--- yaml/size-needs-no-stretch (a fixed size without disabling the stretch) ---

The platform gotcha: `VerticalStretch`/`HorizontalStretch` are `Auto|Boolean`, and at `Auto`
the platform resolves the stretch by the component kind (the docs topic on arranging
components on the screen). When it resolves to "stretch", flex-grow takes the parent's leftover
space and the fixed Height/Width is overridden - blank space below the component, inflated
neighbours. The fix is an explicit `VerticalStretch: False` (respectively
`HorizontalStretch: False`) next to the size.

Which kinds stretch at the auto value is not in the data. The ui schema gives both stretch
properties of every component the same type and one line of text, no default. The
documentation spells a resolution out twice, and the two lists disagree. The page of the base
component type names the table, the HTML container and a multi-line input field as stretching
and every other kind as not, a group and pages by their children. The pages of the components
name only the table (and a matrix group), so the HTML container does not stretch there. The web
client agrees with neither list in full. So the checked set is an OBSERVATION, kept in
`_STRETCH_AT_AUTO` below. A live page (25.09.2026) put every kind that needs no data of its own
into cells of a fixed size - `Height: 100` in a vertical cell 420 high, `Width: 100` in a
horizontal cell 360 wide - in four variants: no key, `Auto`, `False`, `True`; the computed flex
of the component and its size were read in the browser. The variant without the key matched
`Auto` on every kind, `True` stretched every kind, `False` stopped the stretch on every kind
(flex-grow 0, the control). What `Auto` did:

- stretched along both axes: the HTML container, the table, the standard and the custom list,
  the formatted document, the PDF view, the speedometer and the pie chart, the separating group;
- stretched along the width only: pages, the tags panel, the stages panel, the file list, a
  multi-line input field (`StringInputSettings` with `Multiline: True`);
- kept the size along both axes: the label, the picture, a single-line input field, the button,
  the checkbox, the group (a matrix one too, against the component pages), the stack group, the
  collapsible component, the standard and the custom card, the choice component, the value
  choice, the HTML editor, the file choice.

The groups follow their content, as both lists say: a group, a stack group or pages holding an
HTML container without the key stretched along both axes. The rule does not follow that chain -
the content is judged on its own line.

A kind that was not measured is not judged: whether it stretches is exactly what a file cannot
tell, and a guess would either stay silent where it matters or speak where it does not. A new
kind joins the table only with a measurement on a live page behind it.

A list kind - the table, the standard list, the custom list - does not keep its height with the
stretch off alone: its rows area keeps a content minimum (`min-height: min-content`), the list
grows with its rows, and `Height` becomes a lower bound (three rows under `Height: 100` came out
156-220 pixels high). `VerticalScroll: True` lifts the minimum, and only the pair holds the
height. So for a list the vertical advice names both keys, and `VerticalStretch: False` without
that scroll is judged as well - it is where an author who followed half of the advice ends up,
and the height does not hold there either. The width of a list holds with `False` alone.

The stretch acts along the main axis of the parent: a height inside a horizontal group (a width
inside a vertical one) kept its size on every measured kind with the key and without it, the
lists aside. The yaml does not tell the axis of the parent reliably - forms, pages and slots lay
their content out by their own defaults - so the rule does not try, which is one more reason it
is a hint. Some kinds also keep a minimum of their own that `False` does not lift (the formatted
document 200 pixels either way, the stages panel 300 in width, the file list its content height):
a size below it does not hold with any key, and that is not this rule's business.

Hence the rule is a diagnostic hint, not a warning: severity INFO and disabled by default (the
style/line-length model). A live project keeps 20 of 93 size-carrying HTML containers without the
key, and they work - their parent has no leftover space along that axis, which is not statically
decidable. Enable the rule point-blank (`--select yaml/size-needs-no-stretch`) when a layout shows
the symptom - blank space or inflated neighbours around a fixed-size component - to list the
candidates. Judged is a size that is set: a positive number or a binding; the auto value and zero
are skipped. Only a missing stretch key fires (and the list case above) - an explicit `Auto` or
`True` is taken as the author's deliberate choice.

A binding (`Height: =FrameHeightPx`) is a set size: it yields a number at run time, and the
stretch overrides that number exactly as it overrides a literal. Skipping bindings hid the case
the rule exists for: an insert whose height followed its widget through a binding took the
whole leftover height of a full-screen phone window and pushed the button below it under the
browser toolbar, while a point-blank run over the project reported nothing. A binding with an
`Auto` branch is judged too - its numeric branch is overridden all the same.

--- yaml/col-width-needs-no-stretch (a column width that turns into a share) ---

All three table column kinds - `StandardTableColumn`, `TableColumn`, `CustomTableColumn` -
carry both `Width` and `HorizontalStretch` in the ui schema, and the schema defines `Width`
as a DEFAULT width ("Задает ширину компонента по умолчанию."). When the column stretches -
which `Auto` readily resolves to inside a stretching table - the number acts as a share of
the free space (a flex basis) rather than pixels: the column comes out wider than asked and
the content drifts away from its neighbour. The trap is that the author usually MEANS
pixels: the reference case in a deployed project is a 40-pixel badge column whose badge ran
far away from the adjacent name until an explicit `HorizontalStretch: False` pinned it, and
the comment left next to the cure says exactly that.

Judged is a column of one of the three kinds whose `Width` sets a width - a positive number
or a binding, which yields one at run time and turns into a share just the same (not `Auto`,
not zero) - with NO `HorizontalStretch` key in the same node. An
explicit value of ANY kind - `False`, `True`, `Auto`, a binding - is the author's
deliberate choice and is never judged: the same project keeps `Width: 300` together with
`HorizontalStretch: True` on purpose, the width working as the flex basis of a share.

Width-as-a-share is a legitimate technique in its own right, documented in the surveyed
project itself (a share layout keeps numeric widths deliberately and hands one column the
whole leftover), and the convention is INVERTED relative to `HtmlContainer`: of 43
numeric-width columns only 2 spell the ban out. Statically the trap cannot be told from
the technique, so the rule follows the family model - severity INFO, disabled by default,
enabled point-blank when the symptom is on the screen (a column wider than asked, content
drifting away from its neighbour). The message carries both cures: `HorizontalStretch:
False` for a pixel width, and `MinWidth` for a share with a guaranteed minimum - 30
columns of the surveyed project already live that way.

A SEPARATE rule rather than a new entry in `_STRETCH_AT_AUTO`: a point-blank `--select` must
tell columns from `HtmlContainer`, and a column is judged on the `Width` axis alone - the
`Height` axis of a column has not been surveyed.

Positions come from the composed yaml node graph (yaml.compose keeps line/column marks), so
equal values in different nodes are told apart; PyYAML counts CRLF line breaks correctly.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
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
    "yaml/matrix-group-max-width.title": {
        "ru": "Числовой максимум ширины у матричной группы",
        "en": "A numeric width maximum on a matrix group",
    },
    "yaml/matrix-group-max-width.available": {
        "ru": "МаксимальнаяШирина: {value} у группы с матричной компоновкой – это не только "
              "потолок, но и РАСПОЛАГАЕМАЯ ширина: платформа разложит автоматические колонки "
              "по максимуму, а не по окну, и на телефоне корень приложения станет шире "
              "экрана (контент уйдёт за правый край, хотя мобильные ветки разметки "
              "отработали). Заведомо большое число не помогает – ограничения быть не должно "
              "вовсе: отдавайте Авто.",
        "en": "MaxWidth: {value} on a group with a matrix layout is not only a ceiling but "
              "the AVAILABLE width: the platform lays the automatic columns out by the "
              "maximum rather than by the window, and on a phone the application root "
              "becomes wider than the screen (the content runs off the right edge though "
              "every mobile branch of the markup has worked). A deliberately large number "
              "does not help – there must be no limit at all: answer {n[Авто]}.",
    },
    "yaml/card-literal-stretch-weight.title": {
        "ru": "Литеральный вес растягивания у карточки",
        "en": "A literal stretch weight on a card",
    },
    "yaml/card-literal-stretch-weight.collapses": {
        "ru": "ВесПриРастягивании: {value} у карточки '{type}' даёт flex с НУЛЕВОЙ базой. В "
              "горизонтальном ряду это и нужно, но в вертикальной колонке (мобильная "
              "раскладка) нулевая база относится уже к высоте: Safari оставляет карточке ноль "
              "и обрезает содержимое скруглением, а Chrome дефекта не показывает. Снимайте "
              "вес на телефоне биндингом – у карточки И у её внутренних колонок.",
        "en": "StretchWeight: {value} on the '{type}' card makes a flex with a ZERO basis. In "
              "a horizontal row that is what is wanted, but in a vertical column (the mobile "
              "layout) the zero basis applies to the HEIGHT: Safari leaves the card zero and "
              "clips the content with the rounding, while Chrome shows no defect. Drop the "
              "weight on a phone through a binding – on the card AND on its inner columns.",
    },
    "yaml/size-needs-no-stretch.title": {
        "ru": "Размер без отключения растягивания",
        "en": "A size without disabling the stretch",
    },
    "yaml/size-needs-no-stretch.missing": {
        "ru": "У компонента {type} задан размер {size_key}: {value}, но нет {stretch_key}: {n[Ложь]} – "
              "при 'Авто' компонент этого вида растягивается на остаток родителя, "
              "и заданный размер будет перебит.",
        "en": "The {type} component has a fixed {size_key}: {value} but no {stretch_key}: {n[Ложь]} – "
              "at '{n[Авто]}' a component of this kind stretches over the parent's leftover space, "
              "overriding the size.",
    },
    "yaml/size-needs-no-stretch.missing-scroll": {
        "ru": "У компонента {type} задан размер {size_key}: {value}, но нет {stretch_key}: {n[Ложь]} – "
              "при 'Авто' список растягивается на остаток родителя, и заданный размер будет "
              "перебит. Одного {stretch_key}: {n[Ложь]} списку мало: без {scroll_key}: {n[Истина]} "
              "он растёт по своим строкам и высоту не держит – нужны оба ключа.",
        "en": "The {type} component has a fixed {size_key}: {value} but no {stretch_key}: {n[Ложь]} – "
              "at '{n[Авто]}' a list stretches over the parent's leftover space, overriding the "
              "size. {stretch_key}: {n[Ложь]} alone is not enough for a list: without "
              "{scroll_key}: {n[Истина]} it grows with its rows and does not keep the height – "
              "set both keys.",
    },
    "yaml/size-needs-no-stretch.no-scroll": {
        "ru": "У компонента {type} заданы {size_key}: {value} и {stretch_key}: {n[Ложь]}, но нет "
              "{scroll_key}: {n[Истина]} – без своей прокрутки список растёт по строкам, и "
              "высота работает только как нижняя граница.",
        "en": "The {type} component has a fixed {size_key}: {value} and {stretch_key}: {n[Ложь]} "
              "but no {scroll_key}: {n[Истина]} – without a scroll of its own the list grows with "
              "its rows, and the height works only as a lower bound.",
    },
    "yaml/col-width-needs-no-stretch.title": {
        "ru": "Ширина колонки без отключения растягивания",
        "en": "A column width without disabling the stretch",
    },
    "yaml/col-width-needs-no-stretch.share": {
        "ru": "У колонки {type} задана {width_key}: {value} без {stretch_key} – при "
              "растягивании (на '{n[Авто]}' платформа решает сама) число работает как доля "
              "свободного места, а не пиксели: колонка выходит шире заданного, и содержимое "
              "уезжает от соседней. Пиксельной ширине – {stretch_key}: {n[Ложь]}, доле с "
              "гарантированным минимумом – {min_width_key}.",
        "en": "The {type} column sets {width_key}: {value} but no {stretch_key} – when "
              "the column stretches (at '{n[Авто]}' the platform decides on its own) the "
              "number acts as a share of the free space rather than pixels: the column comes "
              "out wider than asked and the content drifts away from its neighbour. A pixel "
              "width needs {stretch_key}: {n[Ложь]}, a share with a guaranteed minimum – "
              "{min_width_key}.",
    },
    "yaml/col-width-needs-no-stretch.off": {
        "ru": "ширина-как-доля – законная техника (долевые раскладки колонок носят её "
              "сознательно), и статически ловушка от техники не отличается – предупреждение "
              "дало бы ложные. Включайте точечно, когда колонка на экране шире заданного и "
              "содержимое уезжает от соседней",
        "en": "a width-as-a-share is a legitimate technique (share layouts of columns carry "
              "it on purpose), and the trap is statically indistinguishable from the "
              "technique – a warning would be false. Enable it point-blank when a column on "
              "the screen is wider than asked and the content drifts away from its neighbour",
    },
}
i18n.register(MESSAGES)

_HEIGHT, _WIDTH = "Высота", "Ширина"

#: The kinds whose stretch resolves to "stretch" at `Auto`, and the size keys it overrides
#: there. An observation of the web client, not data (the ui schema carries no default): the
#: live page described in the module docstring. The kinds measured as keeping their size are
#: absent on purpose, as are the kinds never measured.
_STRETCH_AT_AUTO: dict[str, frozenset[str]] = {
    "КонтейнерHtml": frozenset({_HEIGHT, _WIDTH}),
    "Таблица": frozenset({_HEIGHT, _WIDTH}),
    "СтандартныйСписок": frozenset({_HEIGHT, _WIDTH}),
    "ПроизвольныйСписок": frozenset({_HEIGHT, _WIDTH}),
    "ФорматированныйДокумент": frozenset({_HEIGHT, _WIDTH}),
    "ПросмотрPdf": frozenset({_HEIGHT, _WIDTH}),
    "ДиаграммаСпидометр": frozenset({_HEIGHT, _WIDTH}),
    "КруговаяДиаграмма": frozenset({_HEIGHT, _WIDTH}),
    "РазделяющаяГруппа": frozenset({_HEIGHT, _WIDTH}),
    "Страницы": frozenset({_WIDTH}),
    "ПанельТегов": frozenset({_WIDTH}),
    "ПанельЭтапов": frozenset({_WIDTH}),
    "СписокФайлов": frozenset({_WIDTH}),
}

#: The list kinds: with the stretch off their rows area still keeps a content minimum, and the
#: height holds only together with a scroll of their own.
_SCROLLED_LISTS = frozenset({"Таблица", "СтандартныйСписок", "ПроизвольныйСписок"})

#: An input field stretches along the width only when it is multi-line; a single-line one keeps
#: its size (both measured). The setting lives in a nested block of the node.
_INPUT_FIELD = "ПолеВвода"
_STRING_INPUT_SETTINGS = "НастройкиВводаСтроки"
_MULTILINE = "Многострочная"
_V_SCROLL_KEY = "ПрокруткаПоВертикали"
#: The literal values of a boolean key, in either spelling of the file; anything else (a
#: binding) is left to the author.
_TRUE_VALUES = frozenset({"Истина", "True", "true"})
_FALSE_VALUES = frozenset({"Ложь", "False", "false"})
_LITERALS = _TRUE_VALUES | _FALSE_VALUES | frozenset({"Авто", "Auto"})

# (the size key, the stretch key of the same axis)
_AXES = (
    (_HEIGHT, "РастягиватьПоВертикали"),
    (_WIDTH, "РастягиватьПоГоризонтали"),
)


def _fixed_size(node) -> bool:
    """Whether the scalar is a fixed positive number (not Авто, not a binding, not zero)."""
    if not isinstance(node, yaml.ScalarNode):
        return False
    try:
        return float(node.value) > 0
    except ValueError:
        return False


def _set_size(node) -> bool:
    """Whether the scalar sets a size: a fixed positive number or a binding (`=...`).

    A block scalar (`|`, `>`) is text rather than a binding and is skipped, the way the other
    binding-aware rules skip it; the quote style does not matter - the platform reads the
    string the same either way.
    """
    if _fixed_size(node):
        return True
    if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
        return False
    return node.value.strip().startswith("=")


#: The layout that lays children out in automatic columns, and the settings block that
#: describes those columns (either key alone marks the group as a matrix one).
_MATRIX = "Матричная"
_LAYOUT_ENUM = "КомпоновкаСодержимого"
_LAYOUT_KEYS = ("Компоновка", "Layout")
_MATRIX_SETTINGS_KEYS = ("НастройкиМатричнойКомпоновки", "MatrixLayoutSettings")
_MAX_WIDTH_KEYS = ("МаксимальнаяШирина", "MaxWidth")
_WEIGHT_KEY = "ВесПриРастягивании"


@lru_cache(maxsize=1)
def _weight_keys() -> tuple[str, ...]:
    """Both spellings of the stretch-weight property, from the platform dictionary.

    The English spelling used to be written by hand - and matched nothing: the serializer
    spells the property another way, so on a translated tree the rule went silent (the text
    gate below never passed). A spelling that has a data source never gets typed again.
    """
    return tuple(dict.fromkeys(
        name for name in (_WEIGHT_KEY, uischema.english_property(_WEIGHT_KEY)) if name
    ))


dataset.register_reset(_weight_keys.cache_clear)
#: The inner columns of a card: the cure had to cover them too. A text or a picture inside a
#: card carries a weight legitimately and is left alone.
_GROUP_COMPONENTS = frozenset({"Группа", "Group"})


@lru_cache(maxsize=1)
def _matrix_names() -> frozenset[str]:
    """Both spellings of the matrix layout value, from the platform's own dictionary."""
    aliases = uischema.enum_value_aliases(_LAYOUT_ENUM)
    return frozenset({_MATRIX, aliases.get(_MATRIX)} - {None})


@lru_cache(maxsize=1)
def _card_components() -> frozenset[str]:
    """Palette components that are cards - the shape the zero basis collapses."""
    schema = dataset.load_ui_schema() or {}
    return frozenset(
        name for name in (schema.get("components") or {}) if "Карточка" in name
    )


dataset.register_reset(_matrix_names.cache_clear)
dataset.register_reset(_card_components.cache_clear)


def _numeric(node) -> str | None:
    """The value of a scalar that is a plain number (not Авто, not a binding), else None."""
    if not isinstance(node, yaml.ScalarNode):
        return None
    try:
        float(node.value)
    except ValueError:
        return None
    return node.value


def _entry(entries: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in entries:
            return entries[key]
    return None


@rule(
    "yaml/matrix-group-max-width", "yaml/matrix-group-max-width.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="yaml/matrix-group-max-width.off",
)
def matrix_group_max_width(source: SourceFile) -> Iterable[Diagnostic]:
    """A numeric width maximum on a matrix group - the phone lays out by the maximum."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(key in source.text for key in _MAX_WIDTH_KEYS):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    matrix_names = _matrix_names()
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        max_width = _entry(entries, _MAX_WIDTH_KEYS)
        if max_width is None:
            continue
        value = _numeric(max_width[1])
        if value is None:
            continue  # the auto value or a binding - the cure, not the defect
        layout = _entry(entries, _LAYOUT_KEYS)
        is_matrix = (
            layout is not None
            and isinstance(layout[1], yaml.ScalarNode)
            and layout[1].value.strip() in matrix_names
        )
        if not is_matrix:
            # The settings block is a mapping rather than a scalar: look it up on the node.
            is_matrix = any(
                isinstance(key, yaml.ScalarNode) and key.value in _MATRIX_SETTINGS_KEYS
                for key, _value in mapping.value
            )
        if not is_matrix:
            continue
        key_node = max_width[0]
        yield Diagnostic(
            source.rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/matrix-group-max-width", Severity.INFO,
            i18n.t("yaml/matrix-group-max-width.available", value=value),
        )


def _component_head(mapping) -> str | None:
    """The canonical component name of a node, or None when it declares no type."""
    entries = _scalar_entries(mapping)
    type_entry = entries.get("Тип") or entries.get("Type")
    if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
        return None
    return uischema.canonical_component(type_entry[1].value.split("<", 1)[0].strip())


def _card_scoped_nodes(node, cards: frozenset[str], inside: bool = False):
    """(node, head) of every card and of every group standing inside one.

    The whole tree is walked rather than the flat node list: whether a group is INSIDE a
    card is exactly what the flat list cannot say, and a form nests its content through
    `Inherits` as readily as through `Content`.
    """
    if isinstance(node, yaml.MappingNode):
        head = _component_head(node)
        is_card = head in cards
        if is_card or (inside and head in _GROUP_COMPONENTS):
            yield node, head
        for _key, value in node.value:
            yield from _card_scoped_nodes(value, cards, inside or is_card)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _card_scoped_nodes(item, cards, inside)


@rule(
    "yaml/card-literal-stretch-weight", "yaml/card-literal-stretch-weight.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="yaml/card-literal-stretch-weight.off",
)
def card_literal_stretch_weight(source: SourceFile) -> Iterable[Diagnostic]:
    """A literal stretch weight on a card - the zero basis collapses it in a column."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(key in source.text for key in _weight_keys()):
        return
    cards = _card_components()
    if not cards:
        return  # no palette data - no rule
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping, head in _card_scoped_nodes(root, cards):
        weight = _entry(_scalar_entries(mapping), _weight_keys())
        if weight is None:
            continue
        value = _numeric(weight[1])
        if value is None or float(value) == 0:
            continue  # a binding is the cure; a zero weight does not stretch at all
        key_node = weight[0]
        yield Diagnostic(
            source.rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/card-literal-stretch-weight", Severity.INFO,
            i18n.t("yaml/card-literal-stretch-weight.collapses", value=value, type=head),
        )


@rule(
    "yaml/size-needs-no-stretch", "yaml/size-needs-no-stretch.title", "D",
    severity=Severity.INFO, enabled_by_default=False, off_reason="yaml/size-needs-no-stretch.off",
)
def size_needs_no_stretch(source: SourceFile) -> Iterable[Diagnostic]:
    """A set size on a kind that stretches at `Auto` - the stretch overrides the size."""
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
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        written_type = type_entry[1].value.split("<", 1)[0].strip()
        kind = uischema.canonical_component(written_type)
        stretched_sizes = _stretched_sizes(mapping, kind)
        if not stretched_sizes:
            continue
        for size_key, stretch_key in _AXES:
            entry = keys.get(size_key)
            if size_key not in stretched_sizes or entry is None or not _set_size(entry[1]):
                continue
            message_key = _size_verdict(keys, kind, size_key, stretch_key)
            if message_key is None:
                continue
            key_node = entry[0]
            # The advice names the keys the way the file spells them: telling an English-spelled
            # form to add `РастягиватьПоВертикали` would send the author looking for a key that
            # does not belong in it.
            shown_stretch, shown_scroll = stretch_key, _V_SCROLL_KEY
            if key_node.value.isascii():
                shown_stretch = terms.common_english(stretch_key) or stretch_key
                shown_scroll = terms.common_english(_V_SCROLL_KEY) or _V_SCROLL_KEY
            yield Diagnostic(
                source.rel,
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                "yaml/size-needs-no-stretch", Severity.INFO,
                i18n.t(
                    message_key,
                    type=written_type, size_key=key_node.value, value=entry[1].value,
                    stretch_key=shown_stretch, scroll_key=shown_scroll,
                ),
            )


def _stretched_sizes(mapping, kind: str | None) -> frozenset[str]:
    """The size keys the stretch at `Auto` overrides on this node, empty when it keeps them."""
    sizes = _STRETCH_AT_AUTO.get(kind or "")
    if sizes:
        return sizes
    if kind == _INPUT_FIELD and _is_multiline(mapping):
        return frozenset({_WIDTH})
    return frozenset()


def _is_multiline(mapping) -> bool:
    """Whether an input field node sets `Multiline: True` in its string input settings."""
    for key, value in mapping.value:
        if (
            isinstance(key, yaml.ScalarNode)
            and uischema.canonical_property(key.value) == _STRING_INPUT_SETTINGS
            and isinstance(value, yaml.MappingNode)
        ):
            entry = _scalar_entries(value).get(_MULTILINE)
            return (
                entry is not None
                and isinstance(entry[1], yaml.ScalarNode)
                and entry[1].value.strip() in _TRUE_VALUES
            )
    return False


def _size_verdict(keys: dict, kind: str | None, size_key: str, stretch_key: str) -> str | None:
    """The message key for a set size on a kind that stretches at `Auto`, or None when it holds.

    A missing stretch key is the finding everywhere. The height of a list needs its own scroll
    as well, so there a missing key is reported with both keys named, and a literal `False`
    without `VerticalScroll: True` is reported too. Any other value the author wrote - `Auto`,
    `True`, a binding, a bound scroll - is a deliberate choice and stays silent.
    """
    needs_scroll = kind in _SCROLLED_LISTS and size_key == _HEIGHT
    scroll = keys.get(_V_SCROLL_KEY)
    scroll_value = (
        scroll[1].value.strip() if scroll is not None and isinstance(scroll[1], yaml.ScalarNode)
        else None
    )
    scrolls = scroll_value in _TRUE_VALUES
    # A bound scroll is the author's call: no advice about it either way.
    scroll_literal = scroll is None or scroll_value in _LITERALS
    stretch = keys.get(stretch_key)
    if stretch is None:
        if needs_scroll and not scrolls and scroll_literal:
            return "yaml/size-needs-no-stretch.missing-scroll"
        return "yaml/size-needs-no-stretch.missing"
    if not needs_scroll or scrolls or not scroll_literal:
        return None
    stretch_off = (
        isinstance(stretch[1], yaml.ScalarNode) and stretch[1].value.strip() in _FALSE_VALUES
    )
    if not stretch_off:
        return None
    return "yaml/size-needs-no-stretch.no-scroll"


#: The table column kinds: the abstract base and both concrete kinds alike carry `Width`
#: and `HorizontalStretch` in the ui schema, so all three are judged.
_COLUMN_TYPES = frozenset({
    "КолонкаТаблицы",
    "ПроизвольнаяКолонкаТаблицы",
    "СтандартнаяКолонкаТаблицы",
})
_WIDTH_KEY = "Ширина"
_H_STRETCH_KEY = "РастягиватьПоГоризонтали"
_MIN_WIDTH_KEY = "МинимальнаяШирина"


@rule(
    "yaml/col-width-needs-no-stretch", "yaml/col-width-needs-no-stretch.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="yaml/col-width-needs-no-stretch.off",
)
def col_width_needs_no_stretch(source: SourceFile) -> Iterable[Diagnostic]:
    """A fixed column width without disabling the stretch - the number acts as a share."""
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
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        written_type = type_entry[1].value.split("<", 1)[0].strip()
        if uischema.canonical_component(written_type) not in _COLUMN_TYPES:
            continue
        entry = keys.get(_WIDTH_KEY)
        if entry is None or _H_STRETCH_KEY in keys or not _set_size(entry[1]):
            continue
        key_node = entry[0]
        # The advice names the keys the way the file spells them, like the sibling rule
        # above: an English-spelled form must not be sent looking for a Russian key.
        shown_stretch, shown_min = _H_STRETCH_KEY, _MIN_WIDTH_KEY
        if key_node.value.isascii():
            shown_stretch = terms.common_english(_H_STRETCH_KEY) or shown_stretch
            shown_min = terms.common_english(_MIN_WIDTH_KEY) or shown_min
        yield Diagnostic(
            source.rel, key_node.start_mark.line + 1, key_node.start_mark.column + 1,
            "yaml/col-width-needs-no-stretch", Severity.INFO,
            i18n.t(
                "yaml/col-width-needs-no-stretch.share",
                type=written_type, width_key=key_node.value, value=entry[1].value,
                stretch_key=shown_stretch, min_width_key=shown_min,
            ),
        )
