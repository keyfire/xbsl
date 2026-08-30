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

Judged is a column of one of the three kinds whose `Width` is a fixed positive number (not
`Auto`, not a binding, not zero) with NO `HorizontalStretch` key in the same node. An
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

A SEPARATE rule rather than a new entry in `_CHECKED_TYPES`: a point-blank `--select` must
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
              "при 'Авто' платформа может растянуть компонент на остаток родителя, "
              "и заданный размер будет перебит.",
        "en": "The {type} component has a fixed {size_key}: {value} but no {stretch_key}: {n[Ложь]} – "
              "at '{n[Авто]}' the platform may stretch the component over the parent's leftover space, "
              "overriding the size.",
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
        "en": "The {type} column has a fixed {width_key}: {value} but no {stretch_key} – when "
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
        if entry is None or _H_STRETCH_KEY in keys or not _fixed_size(entry[1]):
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
