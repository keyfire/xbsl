"""Tier A: a scrolled list whose navigation never loads the rest of the rows.

The yaml/list-scroll-without-loading rule. A list component takes its rows in PORTIONS of
`PageSize`, and the `Navigation` property decides whether the next portion is ever asked
for. The platform documentation of `ListNavigation` says it in so many words: with
`None` "the list is always shown without navigation. Part of the data may then be
unavailable if it does not fit the size of the list."

`VerticalScroll` does not change that - it scrolls what is already loaded. So the pair
`VerticalScroll: True` with `Navigation: None` is a contradiction the compiler cannot see:
the author expects a long list the reader scrolls through, while the component holds one
portion and asks for nothing more. The tail of the data is unreachable by any means; a
row beyond the portion is still found by the list's own search, which filters the whole
source - a search finding a row the scrolling does not show is the field mark of this trap.

Judged is exactly that pair, on a component the ui schema gives a `Navigation` property to
(the list-like ones - a project component or any other node is never touched):

- `Navigation: None` (also written qualified, `ListNavigation.None`) - the only value that
  drops the tail; `PageSwitcher` keeps it reachable by the buttons, and the two loading
  values load it;
- `VerticalScroll` present and not `False` - `True` or a binding (a form that scrolls on the
  desktop and lets the page scroll on a phone still scrolls somewhere). A list without the
  property, and one that explicitly does not scroll, is left alone: there the author is not
  promising the reader a scroll.

An expression in `Navigation` itself is skipped - the value is then unknown to a file rule.

The cure is one line, `Navigation: LoadingOnScroll`; `LoadingButton` works too when an
explicit "Show more" is wanted.
"""

from __future__ import annotations

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
    "yaml/list-scroll-without-loading.title": {
        "ru": "Прокрутка списка не догружает строки",
        "en": "Scrolling a list never loads more rows",
    },
    "yaml/list-scroll-without-loading.none": {
        "ru": "Список прокручивается ({n[ПрокруткаПоВертикали]}), а {n[Навигация]} задана как "
              "{n[Отсутствует]}: строки берутся одной порцией ({n[РазмерСтраницы]}), и "
              "прокрутка крутит только её – остальные данные недостижимы (поиск списка их "
              "находит, прокрутка нет). Поставьте {n[Навигация]}: {n[ПодгрузкаПриПрокрутке]}.",
        "en": "The list scrolls ({n[ПрокруткаПоВертикали]}), yet {n[Навигация]} is "
              "{n[Отсутствует]}: the rows come in a single portion ({n[РазмерСтраницы]}) and "
              "the scrolling moves through that portion alone - the rest of the data is "
              "unreachable (the list search still finds it, the scrolling does not). Write "
              "{n[Навигация]}: {n[ПодгрузкаПриПрокрутке]}.",
    },
}
i18n.register(MESSAGES)

#: The property that decides whether the next portion is requested, either spelling.
_NAVIGATION_KEYS = ("Навигация", "Navigation")
#: The property that promises the reader a scroll, either spelling.
_SCROLL_KEYS = ("ПрокруткаПоВертикали", "VerticalScroll")
#: The navigation value that drops the tail, either spelling.
_NONE_VALUES = frozenset({"Отсутствует", "None"})
#: A scroll explicitly turned off - the author promises nothing, either spelling.
_FALSE_VALUES = frozenset({"Ложь", "False"})


@lru_cache(maxsize=1)
def _list_components() -> frozenset[str]:
    """Component names the ui schema gives a navigation property to, as the schema spells them.

    Taken from the data rather than listed by hand: the property belongs to the list family
    and a new member of it would be judged the day the data knows it. Empty without the data
    bundle - the rule then stays silent instead of guessing which node is a list.
    """
    schema = dataset.load_ui_schema() or {}
    return frozenset(
        name
        for name, record in (schema.get("components") or {}).items()
        if any(key in (record.get("props") or {}) for key in _NAVIGATION_KEYS)
    )


dataset.register_reset(_list_components.cache_clear)


def _head(written: str) -> str:
    """The type head folded to the spelling the schema uses.

    The generic arguments, the nullable suffix and a namespace qualifier are stripped
    first (`Pack.Table<Source>?` -> `Table` -> the schema's own name for it).
    """
    head = written.split("<", 1)[0].strip().rstrip("?").strip()
    if "." in head:
        head = head.rsplit(".", 1)[1]
    return uischema.canonical_component(head)


def _entry(entries: dict, keys: tuple[str, ...]):
    """The (key node, value node) pair of the first key present, either spelling."""
    for key in keys:
        found = entries.get(key)
        if found is not None:
            return found
    return None


def _plain_value(node) -> str | None:
    """The written value of a scalar node, or None for anything a file rule cannot read."""
    if not isinstance(node, yaml.ScalarNode) or node.style in ("|", ">"):
        return None
    value = node.value.strip()
    return value or None


@rule(
    "yaml/list-scroll-without-loading", "yaml/list-scroll-without-loading.title", "A",
    severity=Severity.WARNING,
)
def list_scroll_without_loading(source: SourceFile) -> Iterable[Diagnostic]:
    """A scrolled list that never loads the tail - see the module docstring."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return
    if not any(key in source.text for key in _NAVIGATION_KEYS):
        return  # the cheap gate: the property this rule is about is not written here
    components = _list_components()
    if not components:
        return  # no data bundle: which node is a list is unknown
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = _entry(entries, ("Тип", "Type"))
        if type_entry is None or _head(str(_plain_value(type_entry[1]) or "")) not in components:
            continue
        navigation = _entry(entries, _NAVIGATION_KEYS)
        if navigation is None:
            continue
        written = _plain_value(navigation[1])
        if written is None or written[0] in "=%":
            continue  # an expression: the value is not knowable from the file
        if written.rsplit(".", 1)[-1] not in _NONE_VALUES:
            continue
        scroll = _entry(entries, _SCROLL_KEYS)
        if scroll is None:
            continue  # nothing promises a scroll here
        scrolled = _plain_value(scroll[1])
        if scrolled is None or scrolled in _FALSE_VALUES:
            continue  # the list explicitly does not scroll
        value_node = navigation[1]
        yield Diagnostic(
            source.rel,
            value_node.start_mark.line + 1, value_node.start_mark.column + 1,
            "yaml/list-scroll-without-loading", Severity.WARNING,
            i18n.t("yaml/list-scroll-without-loading.none"),
        )
