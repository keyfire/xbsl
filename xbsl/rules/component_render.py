"""Tier D: property combinations one half of which the platform silently ignores.

Two rules live here. Both are about a component node whose yaml sets a property that
another property's value disables: the build applies cleanly, the screen just misses
what was written - exactly the silent class a linter exists for.

--- yaml/badge-column-image (an image on a badge column) ---

A `StandardTableColumn` with `Kind: Badge` draws the cell value as tag pills -
the documentation of `TableColumnKind` describes the badge kind as a label with the
badge display kind - and an `Image` set on the same column is not shown: the
property is documented for the picture kind only (the column page reads
"Если не указано, но при этом Вид = Картинка, то будет отображаться картинка из данных",
and no other kind gives the picture a path to the screen). The working replacements
live on real sources: an image WITHOUT a kind (at the automatic kind the picture
stands next to the plain value text), or `Kind: Picture` for a picture column.

Narrowings, so that the rule keeps the zero-false-positive bar:

- only `StandardTableColumn` is judged: its relatives (`TableColumn`,
  `CustomTableColumn`) declare neither `Kind` nor `Image` in the ui
  schema, so the combination cannot exist on them;
- the kind must be a scalar literal, the qualified `TableColumnKind.Badge`
  spelling included; a binding is not statically judgeable and a block scalar is
  text, so both are skipped;
- `Kind: Tags` next to an image may lose the picture the same way, but no probe has
  shown it - not judged until one does.

Proven on four real corpora: zero findings (both live badge columns carry no image,
and every image-carrying column either says `Вид: Картинка` or leaves the kind to the
automatic "picture next to text" mode), while a control fixture with seeded defects in
both spellings and the qualified form is caught in full and its clean neighbours stay
silent.

--- yaml/value-choice-title (a title on a switcher) ---

A `ValueChoice` with an explicit `SwitcherDisplayKind: Switcher` does
not draw its `Title`: the component's documentation page states the title is
ignored for that display kind, so the field stays unlabeled on the screen - measured
on a live stand, where a promo-video block and two settings fields lost their captions
exactly this way. The cure is a separate label component next to the switcher.

Narrowings:

- only an EXPLICIT switcher kind is judged: what the automatic kind resolves to is
  not documented (the ui schema records no default for the property), so a node
  without the key is left alone - if a probe ever proves the default is the switcher,
  the predicate grows by one line;
- an `Array<...>` type argument turns the component into a checkbox group, where the
  switcher display kind does not apply (the docs scope it to the case when the data
  type resolves to a single-value choice) - such nodes are skipped;
- the kind spelled as a binding is not statically judgeable - skipped;
- an empty title is no title;
- any OTHER display kind draws the title (`RadioButtonGroup` carries no such clause
  and live radio nodes keep their captions), so only the switcher value fires. Every
  form of the title - a literal, a `=` binding, a `$` localized reference - is flagged
  alike: none of them is drawn.

The corpus run gave six findings, three per language snapshot, each verified true by
reading the surrounding markup; the full default rule set is silent on the control
fixture, so the niche is free.

Both rules take every platform spelling from the data (the ui schema, the term
dictionaries, uiterms) and stay silent without it; both facts of each predicate live
in one file, so the rules are file-scoped and the editor highlights while typing.
Positions come from the composed node graph (line/column marks kept).
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
    "yaml/badge-column-image.title": {
        "ru": "Изображение у колонки-значка",
        "en": "An image on a badge column",
    },
    "yaml/badge-column-image.hidden": {
        "ru": "У колонки задано {kind_key}: {value} вместе с {image_key} – платформа картинку "
              "не покажет: при этом виде значение колонки рисуется тегами-пилюлями, а "
              "{image_key} задокументировано только для {kind_key}: {picture}. Чтобы картинка "
              "была видна, уберите {kind_key} (картинка встанет рядом с обычным текстом "
              "значения) либо задайте {kind_key}: {picture}.",
        "en": "The column sets {kind_key}: {value} together with {image_key} – the platform "
              "does not show the picture: with this kind the column value is drawn as tag "
              "pills, and {image_key} is documented only for {kind_key}: {picture}. To make "
              "the picture visible, drop {kind_key} (the picture then stands next to the "
              "plain value text) or set {kind_key}: {picture}.",
    },
    "yaml/value-choice-title.title": {
        "ru": "Заголовок у переключателя",
        "en": "A title on a switcher",
    },
    "yaml/value-choice-title.unshown": {
        "ru": "{title_key} у компонента ВыборЗначения не рисуется при {kind_key}: {value} – "
              "документация прямо оговаривает, что при этом виде отображения заголовок не "
              "учитывается, и поле останется на экране без подписи. Кладите подпись отдельной "
              "Надписью рядом с переключателем.",
        "en": "{title_key} of a {n[ВыборЗначения]} component is not drawn with "
              "{kind_key}: {value} – the documentation states outright that this display kind "
              "ignores the title, so the field stays unlabeled on the screen. Put the caption "
              "into a separate {n[Надпись]} component next to the switcher.",
    },
}
i18n.register(MESSAGES)

_COLUMN = "СтандартнаяКолонкаТаблицы"
_KIND_PROP = "Вид"
_IMAGE_PROP = "Изображение"
_COLUMN_KIND_ENUM = "ВидКолонкиТаблицы"
_BADGE = "Значок"
_PICTURE = "Картинка"

_CHOICE = "ВыборЗначения"
_SWITCH_PROP = "ВидОтображенияПереключателя"
_SWITCH_ENUM = "ВидОтображенияПереключателя"
_TITLE_PROP = "Заголовок"
_SWITCHER = "Переключатель"
_ARRAY = "Массив"


def _spellings(*names: str | None) -> tuple[str, ...]:
    """The given names deduplicated, the unknown (None) ones dropped."""
    return tuple(dict.fromkeys(name for name in names if name))


@lru_cache(maxsize=1)
def _badge_facts() -> tuple[tuple[str, ...], tuple[str, ...], frozenset[str], str] | None:
    """(column spellings, image-key spellings, badge values, English picture) or None.

    None without the ui schema: the whole point of the rule is the pair of properties the
    schema declares on this one column kind, and the English spellings a translated tree
    is judged by come from the same data - without it the rule stays silent rather than
    guessing.
    """
    schema = dataset.load_ui_schema()
    if not schema or _COLUMN not in (schema.get("components") or {}):
        return None
    aliases = uischema.enum_value_aliases(_COLUMN_KIND_ENUM)
    return (
        _spellings(_COLUMN, terms.english(_COLUMN, "types") or terms.common_english(_COLUMN)),
        _spellings(_IMAGE_PROP, uischema.english_property(_IMAGE_PROP)),
        frozenset(_spellings(_BADGE, aliases.get(_BADGE))),
        aliases.get(_PICTURE) or _PICTURE,
    )


@lru_cache(maxsize=1)
def _switcher_facts() -> tuple[tuple[str, ...], frozenset[str], frozenset[str]] | None:
    """(kind-key spellings, switcher values, array heads) or None without the data."""
    schema = dataset.load_ui_schema()
    if not schema or _CHOICE not in (schema.get("components") or {}):
        return None
    return (
        _spellings(_SWITCH_PROP, uischema.english_property(_SWITCH_PROP)),
        frozenset(_spellings(
            _SWITCHER, uischema.enum_value_aliases(_SWITCH_ENUM).get(_SWITCHER),
        )),
        frozenset(_spellings(
            _ARRAY, terms.english(_ARRAY, "types") or terms.common_english(_ARRAY),
        )),
    )


dataset.register_reset(_badge_facts.cache_clear)
dataset.register_reset(_switcher_facts.cache_clear)


def _plain_scalar(node) -> str | None:
    """The stripped value of a plain scalar, or None for anything not statically judgeable.

    A binding (`=`), an interpolation (`%`) and a block scalar carry a computed or textual
    value the rule cannot read; an empty scalar carries nothing at all.
    """
    if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
        return None
    value = node.value.strip()
    if not value or value[0] in "=%":
        return None
    return value


def _component_of(entries: dict) -> str | None:
    """The canonical component name the node's type key declares, or None."""
    type_entry = entries.get("Тип") or entries.get("Type")
    if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
        return None
    return uischema.canonical_component(type_entry[1].value.split("<", 1)[0].strip())


@rule("yaml/badge-column-image", "yaml/badge-column-image.title", "D", severity=Severity.WARNING)
def badge_column_image(source: SourceFile) -> Iterable[Diagnostic]:
    """An image on a badge column - the picture is silently dropped from the screen."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    facts = _badge_facts()
    if facts is None:
        return
    columns, image_keys, badge_values, english_picture = facts
    if not any(name in source.text for name in columns):
        return
    if not any(key in source.text for key in image_keys):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        if _component_of(entries) != _COLUMN:
            continue
        kind_entry = entries.get(_KIND_PROP)
        image_entry = entries.get(_IMAGE_PROP)
        if kind_entry is None or image_entry is None:
            continue
        value = _plain_scalar(kind_entry[1])
        # The qualified spelling names the enumeration first: `TableColumnKind.Badge`.
        if value is None or value.rsplit(".", 1)[-1] not in badge_values:
            continue
        image_key = image_entry[0]
        # The advice spells the picture kind the way the file spells the badge: telling an
        # English-spelled form the Russian word would send the author the wrong spelling.
        picture = english_picture if value.isascii() else _PICTURE
        yield Diagnostic(
            source.rel, image_key.start_mark.line + 1, image_key.start_mark.column + 1,
            "yaml/badge-column-image", Severity.WARNING,
            i18n.t(
                "yaml/badge-column-image.hidden",
                kind_key=kind_entry[0].value, value=value,
                image_key=image_key.value, picture=picture,
            ),
        )


def _argument_head(type_value: str) -> str:
    """The head of a generic's first argument: `ValueChoice<Array<String>>` -> `Array`.

    Empty for a type written without an argument. The namespace qualifier and the nullable
    suffix are stripped, so a qualified spelling compares by its own name.
    """
    open_at = type_value.find("<")
    if open_at < 0:
        return ""
    close_at = type_value.rfind(">")
    inner = type_value[open_at + 1: close_at if close_at > open_at else len(type_value)]
    head = inner.split("<", 1)[0].strip().rstrip("?")
    return head.rsplit("::", 1)[-1]


@rule("yaml/value-choice-title", "yaml/value-choice-title.title", "D", severity=Severity.WARNING)
def value_choice_title(source: SourceFile) -> Iterable[Diagnostic]:
    """A title on an explicit switcher - the platform leaves the field unlabeled."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    facts = _switcher_facts()
    if facts is None:
        return
    switch_keys, switcher_values, array_heads = facts
    if not any(key in source.text for key in switch_keys):
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        if _component_of(entries) != _CHOICE:
            continue
        type_entry = entries.get("Тип") or entries.get("Type")
        if _argument_head(type_entry[1].value.strip()) in array_heads:
            continue  # a checkbox group: the switcher display kind does not apply
        kind_entry = entries.get(_SWITCH_PROP)
        if kind_entry is None:
            continue  # no explicit kind - what the automatic one draws is undocumented
        value = _plain_scalar(kind_entry[1])
        if value is None or value.rsplit(".", 1)[-1] not in switcher_values:
            continue
        title_entry = entries.get(_TITLE_PROP)
        if title_entry is None or not isinstance(title_entry[1], yaml.ScalarNode):
            continue
        if not title_entry[1].value.strip():
            continue  # an empty title is no title
        title_key = title_entry[0]
        yield Diagnostic(
            source.rel, title_key.start_mark.line + 1, title_key.start_mark.column + 1,
            "yaml/value-choice-title", Severity.WARNING,
            i18n.t(
                "yaml/value-choice-title.unshown",
                title_key=title_key.value, kind_key=kind_entry[0].value, value=value,
            ),
        )
