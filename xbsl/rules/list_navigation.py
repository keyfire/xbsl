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

The cure is one line, `Navigation: LoadingOnScroll`, and the rule carries it as an autofix
in the spelling of the value it replaces (a qualifier the author wrote is kept). Where a
list wants an explicit "Show more" button instead, `LoadingButton` is the other answer -
hence the fix is offered, not applied silently.

A list WITHOUT a scroll of its own loses the tail the same way: a feed the page scrolls
around it holds one portion too, and the automatic `PageSize` is ten rows ("0 or Auto -
automatically (equals 10)", the documentation of `List.PageSize`). One project met it on a
card whose feed had loaded fourteen comments and showed ten; ten lists of the same shape
were found there and each got an explicit page size. So `Navigation: None` with the scroll
absent or off is judged as well, while `PageSize` is not written or is written as the
automatic value (`Auto`, 0). An explicit number, or an expression, is the author's own limit
and is left alone. The cure is not one line here - a page size by the limit of the data, or
`LoadingOnScroll` together with a scroll of the list's own changes the layout - so this half
carries no fix.

Which lists the rule judges comes from the documentation as well:

- a TREE source (`TreeDataSource`, `LoadableTreeDataSource`) is never judged - with such a
  source the navigation is "always `LoadingOnScroll`" (the documentation of `List.Navigation`),
  whatever the property says;
- the half without a scroll judges an ARRAY source only (`ArrayDataSource` in the type of the
  component). A dynamic list is loaded on scroll as well when it is hierarchical, and by
  default that is decided by the metadata of its main table, which a file rule does not see;
  a list whose source the type does not name is not judged either. Both are documented false
  negatives. The default of `Navigation` itself is not `None` (the page of the standard list
  names `PageSwitcher`), so only a written `None` is judged.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
)
from xbsl.rules.yaml_types import _parse_type_string

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
    "yaml/list-scroll-without-loading.page": {
        "ru": "Список не прокручивается сам, а {n[Навигация]} задана как {n[Отсутствует]} без "
              "{n[РазмерСтраницы]}: строки берутся одной порцией в десять штук (размер страницы "
              "Авто), и прокрутка страницы показывает только их – остальные данные недостижимы. "
              "Задайте {n[РазмерСтраницы]} по пределу данных либо {n[Навигация]}: "
              "{n[ПодгрузкаПриПрокрутке]} вместе со своей прокруткой списка "
              "({n[ПрокруткаПоВертикали]}).",
        "en": "The list does not scroll itself, yet {n[Навигация]} is {n[Отсутствует]} with no "
              "{n[РазмерСтраницы]}: the rows come in a single portion of ten (the automatic page "
              "size), and scrolling the page shows those alone - the rest of the data is "
              "unreachable. Set {n[РазмерСтраницы]} to the limit of the data, or write "
              "{n[Навигация]}: {n[ПодгрузкаПриПрокрутке]} together with a scroll of the list's "
              "own ({n[ПрокруткаПоВертикали]}).",
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
#: The enumeration the navigation values belong to, and the value the fix writes.
_NAVIGATION_ENUM = "НавигацияВСписке"
_LOADING_VALUE = "ПодгрузкаПриПрокрутке"
#: The size of a portion, either spelling, and the values that leave it automatic (ten rows).
_PAGE_SIZE_KEYS = ("РазмерСтраницы", "PageSize")
_AUTO_PAGE_SIZES = frozenset({"Авто", "Auto", "0"})


@lru_cache(maxsize=1)
def _source_names() -> tuple[frozenset[str], frozenset[str]]:
    """(the array source, the tree sources) - both spellings, from the data.

    Without the data bundle the English half is simply absent, and the rule has no list
    components to judge in the first place.
    """
    def pair(name: str) -> frozenset[str]:
        return frozenset({name, terms.common_english(name) or name})

    return (
        pair("ИсточникДанныхМассив"),
        pair("ИсточникДанныхДерево") | pair("ИсточникДанныхДеревоПодгружаемый"),
    )


dataset.register_reset(_source_names.cache_clear)


def _source_head(written: str) -> str | None:
    """The data source named by the first type argument of a component type, or None.

    `Table<ArrayDataSource<Row>>` gives `ArrayDataSource`; a namespace qualifier is dropped.
    """
    chains = _parse_type_string(written)
    if len(chains) < 2 or not chains[1]:
        return None
    return chains[1][-1]


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


def _automatic_page_size(entries: dict) -> bool:
    """Whether the portion of the list is the automatic ten rows: `PageSize` not written, or
    written as `Auto` or 0. A number of the author's own or an expression is a limit chosen on
    purpose, and a value a file rule cannot read is not judged."""
    page = _entry(entries, _PAGE_SIZE_KEYS)
    if page is None:
        return True
    written = _plain_value(page[1])
    return written is not None and written.rsplit(".", 1)[-1] in _AUTO_PAGE_SIZES


def _loading_spelled(written: str) -> str:
    """`LoadingOnScroll` in the spelling of the value being replaced.

    The English name of the value comes from the data (per enumeration - the same Russian word
    answers to different English ones elsewhere), and a qualifier the author wrote is kept as
    written: `ListNavigation.None` becomes `ListNavigation.LoadingOnScroll`.
    """
    qualifier, _, value = written.rpartition(".")
    if value.isascii():
        aliases = uischema.enum_value_aliases(_NAVIGATION_ENUM)
        target = aliases.get(_LOADING_VALUE) or _LOADING_VALUE
    else:
        target = _LOADING_VALUE
    return f"{qualifier}.{target}" if qualifier else target


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
    array_source, tree_sources = _source_names()
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = _entry(entries, ("Тип", "Type"))
        written_type = str(_plain_value(type_entry[1]) or "") if type_entry is not None else ""
        if type_entry is None or _head(written_type) not in components:
            continue
        navigation = _entry(entries, _NAVIGATION_KEYS)
        if navigation is None:
            continue
        written = _plain_value(navigation[1])
        if written is None or written[0] in "=%":
            continue  # an expression: the value is not knowable from the file
        if written.rsplit(".", 1)[-1] not in _NONE_VALUES:
            continue
        source_head = _source_head(written_type)
        if source_head in tree_sources:
            continue  # a tree source always loads on scroll, whatever the property says
        value_node = navigation[1]
        scroll = _entry(entries, _SCROLL_KEYS)
        scrolled = _plain_value(scroll[1]) if scroll is not None else None
        if scroll is None or scrolled in _FALSE_VALUES:
            # No scroll of its own: the page scrolls around one portion of the list.
            if source_head in array_source and _automatic_page_size(entries):
                yield Diagnostic(
                    source.rel,
                    value_node.start_mark.line + 1, value_node.start_mark.column + 1,
                    "yaml/list-scroll-without-loading", Severity.WARNING,
                    i18n.t("yaml/list-scroll-without-loading.page"),
                )
            continue
        if scrolled is None:
            continue  # a scroll value a file rule cannot read
        start, end = value_node.start_mark.index, value_node.end_mark.index
        # The fix replaces the value in place, and only when the raw slice IS that value:
        # a quoted or otherwise decorated scalar is reported without one.
        fix = (
            TextEdit(start, end, _loading_spelled(written))
            if source.text[start:end] == written else None
        )
        yield Diagnostic(
            source.rel,
            value_node.start_mark.line + 1, value_node.start_mark.column + 1,
            "yaml/list-scroll-without-loading", Severity.WARNING,
            i18n.t("yaml/list-scroll-without-loading.none"),
            fix=fix,
        )
