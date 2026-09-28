"""Tier A: a scrolled list whose navigation never loads the rest of the rows.

The yaml/list-scroll-without-loading rule and its project half, yaml/dynlist-scroll-without-loading
(the end of this docstring). A list component takes its rows in PORTIONS of `PageSize`, and the
`Navigation` property decides whether the next portion is ever asked for. The platform
documentation of `ListNavigation` says it in so many words: with `None` "the list is always
shown without navigation. Part of the data may then be unavailable if it does not fit the size
of the list."

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

Which lists are judged comes from the documentation as well:

- a TREE source (`TreeDataSource`, `LoadableTreeDataSource`) is never judged, and neither is a
  HIERARCHICAL dynamic list: with any of them the navigation is "always `LoadingOnScroll`"
  (the documentation of `List.Navigation`), whatever the property says;
- the half without a scroll judges an ARRAY source and a flat dynamic list; a list whose source
  the type does not name is not judged there (a documented false negative). The default of
  `Navigation` itself is not `None` (the page of the standard list names `PageSwitcher`), so
  only a written `None` is judged.

Whether a dynamic list is hierarchical is said by its `UsedHierarchy`, typed
`Auto|HierarchyMode|String` (the documentation of `DynamicList`): with `Disabled` "the
dynamic list returns its flat view", `Default` or a string naming a hierarchy shows one, and
`Auto` - the value of a property not written as well - "interprets the query of the dynamic
list depending on whether it supports hierarchy. If it does - `Default`". The declaration is
read where the file keeps it: in the `Source` of the component, or in the default value of the
element property the source binds to (`Source: =List`, the way a list form declares its list).
A list built in code declares nothing in the file and is not judged. Of the values:

- the typed node `UsedHierarchy: {Type: HierarchyMode, Value: Disabled}` - the spelling of
  the platform's own examples - makes the list flat, and the file rule judges it like any list;
- the property not written leaves the answer to the main table, and such a list goes to the
  project half;
- a plain scalar is never judged, and a probe on a live server showed why. A bare word that is
  a value of a member of the union - `Disabled`, `Auto`, `Default` - fails the apply with "the
  value type is not specified" (`Не указан тип значения`), over a catalog with a hierarchy and
  without one: the word fits the enumeration and the string at once. Any other word applies,
  and so does a qualified one - `HierarchyMode.Disabled`, but also `HierarchyMode.NoSuchValue`
  and `NoSuchType.Disabled`, which no enumeration knows. So a qualified word is not read as a
  value of the enumeration either: it is a string, the name of a hierarchy, just like a quoted
  one. What the list shows for a hierarchy name its table does not have is a matter of the
  runtime, not of the file;
- the typed node with `Default` and an expression are never judged either.

The yaml/dynlist-scroll-without-loading rule is that project half. It is split off rather than
the whole check promoted to the project: the editor runs a file rule on every keystroke and a
project rule on save only, and most lists need nothing beyond their own file. It judges the
lists the file left to the main table when the table is an element of the project that
certainly has no hierarchy:

- a catalog - the only kind the platform gives hierarchies to
  (`ObjectEntityWithHierarchiesReflection` has a single child type, `CatalogReflection`) - that
  declares none of `Hierarchical` (other than `False`), `Hierarchy`, `AdditionalHierarchies`
  and `DefaultHierarchy`. A table derived from a catalog (its `Groups` catalog, a hierarchy
  table) is not judged;
- a document, an information or accumulation register, an exchange plan, a settings storage or
  an integrable application - the kinds the documentation of the dynamic list names as main
  tables next to the catalog (its default sort order), none of them with a hierarchy; a table
  derived from them (a register slice) is flat as well.

The table is matched by its name without the namespace, and every element of the project under
that name has to agree. A table outside the project (a system table such as `Users`, a library),
a data journal or a virtual table - composite sources whose hierarchy the documentation does
not settle - is not judged. The findings and the fix are those of the file rule, with the main
table named.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import lru_cache
from typing import NamedTuple

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
    object_kind_fast,
    object_name_fast,
)
from xbsl.rules.yaml_types import _key_spellings, _parse_type_string

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
    "yaml/dynlist-scroll-without-loading.title": {
        "ru": "Прокрутка плоского динамического списка не догружает строки",
        "en": "Scrolling a flat dynamic list never loads more rows",
    },
    "yaml/dynlist-scroll-without-loading.none": {
        "ru": "Список прокручивается ({n[ПрокруткаПоВертикали]}), а {n[Навигация]} задана как "
              "{n[Отсутствует]}. Динамический список здесь плоский: иерархию "
              "({n[ИспользуемаяИерархия]}) решает основная таблица '{table}', а она иерархии не "
              "объявляет. Строки берутся одной порцией ({n[РазмерСтраницы]}), и прокрутка крутит "
              "только её – остальные данные недостижимы (поиск списка их находит, прокрутка "
              "нет). Поставьте {n[Навигация]}: {n[ПодгрузкаПриПрокрутке]}.",
        "en": "The list scrolls ({n[ПрокруткаПоВертикали]}), yet {n[Навигация]} is "
              "{n[Отсутствует]}. The dynamic list is flat here: its hierarchy "
              "({n[ИспользуемаяИерархия]}) is left to the main table '{table}', and the table "
              "declares none. The rows come in a single portion ({n[РазмерСтраницы]}) and the "
              "scrolling moves through that portion alone - the rest of the data is unreachable "
              "(the list search still finds it, the scrolling does not). Write {n[Навигация]}: "
              "{n[ПодгрузкаПриПрокрутке]}.",
    },
    "yaml/dynlist-scroll-without-loading.page": {
        "ru": "Список не прокручивается сам, а {n[Навигация]} задана как {n[Отсутствует]} без "
              "{n[РазмерСтраницы]}. Динамический список здесь плоский: иерархию "
              "({n[ИспользуемаяИерархия]}) решает основная таблица '{table}', а она иерархии не "
              "объявляет. Строки берутся одной порцией в десять штук (размер страницы Авто), и "
              "прокрутка страницы показывает только их – остальные данные недостижимы. Задайте "
              "{n[РазмерСтраницы]} по пределу данных либо {n[Навигация]}: "
              "{n[ПодгрузкаПриПрокрутке]} вместе со своей прокруткой списка "
              "({n[ПрокруткаПоВертикали]}).",
        "en": "The list does not scroll itself, yet {n[Навигация]} is {n[Отсутствует]} with no "
              "{n[РазмерСтраницы]}. The dynamic list is flat here: its hierarchy "
              "({n[ИспользуемаяИерархия]}) is left to the main table '{table}', and the table "
              "declares none. The rows come in a single portion of ten (the automatic page size), "
              "and scrolling the page shows those alone - the rest of the data is unreachable. "
              "Set {n[РазмерСтраницы]} to the limit of the data, or write {n[Навигация]}: "
              "{n[ПодгрузкаПриПрокрутке]} together with a scroll of the list's own "
              "({n[ПрокруткаПоВертикали]}).",
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

#: The enumeration a dynamic list's hierarchy is chosen from and its flat value - the other
#: spelling of each comes from the data.
_HIERARCHY_ENUM = "РежимИерархии"
_FLAT_HIERARCHY = "Выключено"
#: What the declaration of a dynamic list says about its hierarchy (module docstring).
_DECLARED_FLAT = "flat"  # the typed Disabled: the file rule judges the list
_BY_TABLE = "table"  # not written: the main table decides
_UNSETTLED = "unsettled"  # a hierarchy asked for, a scalar, or a value a file cannot read
#: The element kinds the documentation of the dynamic list names as main tables and the
#: platform gives no hierarchy to, the one kind that may carry hierarchies, and the keys a
#: catalog declares them with (the other spelling of each key comes from the metamodel).
_FLAT_KINDS = frozenset({
    "Документ", "РегистрСведений", "РегистрНакопления", "ПланОбмена", "ХранилищеНастроек",
    "ИнтегрируемоеПриложение",
})
_CATALOG_KIND = "Справочник"
_HIERARCHICAL_KEY = "Иерархический"
_HIERARCHY_KEYS = (_HIERARCHICAL_KEY, "Иерархия", "ДополнительныеИерархии", "ИерархияПоУмолчанию")
#: What an element says of the tables named after it: a kind without hierarchies, a catalog
#: declaring none, or anything else - which keeps a list over that name unjudged.
_FLAT_ELEMENT = "kind"
_FLAT_CATALOG = "catalog"
_OTHER_ELEMENT = "other"
#: A source bound to an element property by its bare name (`=List`).
_BINDING_RE = re.compile(r"^=\s*([^\W\d]\w*)\s*$")


@lru_cache(maxsize=1)
def _source_names() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(the array source, the tree sources, the dynamic list) - both spellings, from the data.

    Without the data bundle the English half is simply absent, and the rule has no list
    components to judge in the first place.
    """
    def pair(name: str) -> frozenset[str]:
        return frozenset({name, terms.common_english(name) or name})

    return (
        pair("ИсточникДанныхМассив"),
        pair("ИсточникДанныхДерево") | pair("ИсточникДанныхДеревоПодгружаемый"),
        pair("ДинамическийСписок"),
    )


dataset.register_reset(_source_names.cache_clear)


@lru_cache(maxsize=1)
def _hierarchy_words() -> tuple[frozenset[str], frozenset[str]]:
    """(the hierarchy mode enumeration, its flat value) - both spellings.

    The English value is taken per enumeration: the same Russian word answers to other English
    names in other enumerations.
    """
    def pair(name: str, english: str | None) -> frozenset[str]:
        return frozenset({name, english or name})

    values = uischema.enum_value_aliases(_HIERARCHY_ENUM)
    return (
        pair(_HIERARCHY_ENUM, terms.common_english(_HIERARCHY_ENUM)),
        pair(_FLAT_HIERARCHY, values.get(_FLAT_HIERARCHY)),
    )


dataset.register_reset(_hierarchy_words.cache_clear)


#: A namespace qualifier in front of a name (`Vendor::Project::Subsystem::`) - the type parser
#: does not read one, so it is dropped before the parse (the pattern `yaml/ambiguous-type`
#: validates types with). A row type written in full is how a list form names its own rows.
_QUALIFIER = re.compile(r"(?<![\w.])(?:[^\W\d]\w*\s*::\s*)+")


def _source_head(written: str) -> str | None:
    """The data source named by the first type argument of a component type, or None.

    `Table<ArrayDataSource<Row>>` gives `ArrayDataSource`; a namespace qualifier is dropped,
    and a type the parser does not read names no source.
    """
    chains = _parse_type_string(_QUALIFIER.sub("", written))
    if not chains or len(chains) < 2 or not chains[1]:
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


def _raw_entries(mapping) -> dict:
    """{key as written: value node} of a composed mapping, scalar keys only.

    The nodes that declare a dynamic list and its element are no component, so the schema
    has no canonical name for their keys; they are matched by the spellings from the data.
    """
    return {k.value: v for k, v in mapping.value if isinstance(k, yaml.ScalarNode)}


def _first(entries: dict, name: str):
    """The value node of the first spelling of `name` the raw entries carry, or None."""
    return next((entries[key] for key in _key_spellings(name) if key in entries), None)


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


def _element_properties(root) -> dict[str, dict]:
    """{name: raw entries} of the properties the element declares at its top level - the ones a
    bare `=Name` binding of its markup reads."""
    if not isinstance(root, yaml.MappingNode):
        return {}
    section = _first(_raw_entries(root), "Свойства")
    if not isinstance(section, yaml.SequenceNode):
        return {}
    found: dict[str, dict] = {}
    for item in section.value:
        if isinstance(item, yaml.MappingNode):
            entries = _raw_entries(item)
            name = _plain_value(_first(entries, "Имя"))
            if name:
                found.setdefault(name, entries)
    return found


def _declaration(entries: dict, properties: dict[str, dict]) -> dict | None:
    """The raw entries that declare the dynamic list a component shows, or None.

    Either the component's own `Source` or the default value of the element property the source
    binds to by name (`Source: =List`). A list built in code, or a source bound to anything
    else, declares nothing the file can read.
    """
    source = _entry(entries, _key_spellings("Источник"))
    if source is None:
        return None
    if isinstance(source[1], yaml.MappingNode):
        return _raw_entries(source[1])
    bound = _BINDING_RE.match(_plain_value(source[1]) or "")
    owner = properties.get(bound.group(1)) if bound else None
    default = _first(owner, "ЗначениеПоУмолчанию") if owner is not None else None
    return _raw_entries(default) if isinstance(default, yaml.MappingNode) else None


def _mode_value(written: str, enums: frozenset[str]) -> str | None:
    """The value of a hierarchy mode without its qualifier (`HierarchyMode.Disabled` ->
    `Disabled`); None when the qualifier names something else."""
    qualifier, _, value = written.rpartition(".")
    if qualifier and _QUALIFIER.sub("", qualifier) not in enums:
        return None
    return value


def _hierarchy_mode(declaration: dict) -> str:
    """What the declaration says about the hierarchy of the list - see the module docstring."""
    node = _first(declaration, "ИспользуемаяИерархия")
    if node is None:
        return _BY_TABLE  # not written: Auto
    if not isinstance(node, yaml.MappingNode):
        # A bare Disabled, Auto or Default fails the apply; any other scalar is the name of a
        # hierarchy, a qualified word included; an expression is unknown to a file.
        return _UNSETTLED
    enums, flat = _hierarchy_words()
    # The typed node of the platform's own examples - {Type: HierarchyMode, Value: Disabled}.
    typed = _raw_entries(node)
    kind = _plain_value(_first(typed, "Тип"))
    value = _plain_value(_first(typed, "Значение"))
    if kind and value and _QUALIFIER.sub("", kind) in enums:
        return _DECLARED_FLAT if _mode_value(value, enums) in flat else _UNSETTLED
    return _UNSETTLED


def _main_table(declaration: dict) -> str | None:
    """The main table of a dynamic list as written, or None when the file cannot read it."""
    main = _first(declaration, "ОсновнаяТаблица")
    if not isinstance(main, yaml.MappingNode):
        return None
    table = _plain_value(_first(_raw_entries(main), "Таблица"))
    if table is None or table[0] in "=%&$":
        return None
    return table


class _Finding(NamedTuple):
    """A list with `Navigation: None` that loses its tail unless its source is hierarchical."""

    #: The message: `none` for a list that scrolls, `page` for one the page scrolls around.
    key: str
    #: The `Navigation` value node - where the finding points and what the fix replaces.
    node: object
    fix: TextEdit | None
    #: None for a source that is no dynamic list, else what its declaration says (`_DECLARED_FLAT`
    #: or `_BY_TABLE` - an unsettled list is not a finding at all).
    mode: str | None
    #: The main table of a dynamic list as written, None when the file does not name it.
    table: str | None


def _findings(source: SourceFile) -> list[_Finding]:
    """The lists of the file that lose their tail, both halves, cached per source.

    The two rules sort them: the file rule reports all but the lists whose main table decides,
    the project rule reports those when the table has no hierarchy.
    """
    key = "list_navigation_findings"
    if key not in source.cache:
        source.cache[key] = list(_collect(source))
    return source.cache[key]


def _collect(source: SourceFile) -> Iterator[_Finding]:
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
    array_source, tree_sources, dynamic_list = _source_names()
    properties: dict[str, dict] | None = None  # read once, and only for a dynamic list
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
        mode = table = None
        if source_head in dynamic_list:
            if properties is None:
                properties = _element_properties(root)
            declaration = _declaration(entries, properties)
            if declaration is None:
                continue  # built elsewhere: whether it is hierarchical is not in the file
            mode = _hierarchy_mode(declaration)
            if mode == _UNSETTLED:
                continue  # a hierarchical list always loads on scroll
            table = _main_table(declaration)
        value_node = navigation[1]
        scroll = _entry(entries, _SCROLL_KEYS)
        scrolled = _plain_value(scroll[1]) if scroll is not None else None
        if scroll is None or scrolled in _FALSE_VALUES:
            # No scroll of its own: the page scrolls around one portion of the list.
            if (source_head in array_source or mode is not None) and _automatic_page_size(entries):
                yield _Finding("page", value_node, None, mode, table)
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
        yield _Finding("none", value_node, fix, mode, table)


@rule(
    "yaml/list-scroll-without-loading", "yaml/list-scroll-without-loading.title", "A",
    severity=Severity.WARNING,
)
def list_scroll_without_loading(source: SourceFile) -> Iterable[Diagnostic]:
    """A scrolled list that never loads the tail - see the module docstring."""
    for finding in _findings(source):
        if finding.mode == _BY_TABLE:
            continue  # the main table decides: yaml/dynlist-scroll-without-loading
        yield Diagnostic(
            source.rel,
            finding.node.start_mark.line + 1, finding.node.start_mark.column + 1,
            "yaml/list-scroll-without-loading", Severity.WARNING,
            i18n.t(f"yaml/list-scroll-without-loading.{finding.key}"),
            fix=finding.fix,
        )


def _is_false(value) -> bool:
    """A flag written as false in either spelling (yaml reads `False` as a boolean)."""
    return value is False or (isinstance(value, str) and value.strip() in _FALSE_VALUES)


def _element_verdict(source: SourceFile) -> tuple[str, str] | None:
    """(name, what the element says of the tables named after it) of an element description."""
    kind = object_kind_fast(source)
    name = object_name_fast(source) if kind else None
    if not name:
        return None
    if kind in _FLAT_KINDS:
        return name, _FLAT_ELEMENT
    if kind != _CATALOG_KIND:
        return name, _OTHER_ELEMENT
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return name, _OTHER_ELEMENT
    for key in _HIERARCHY_KEYS:
        for spelled in _key_spellings(key):
            if spelled in data and not (key == _HIERARCHICAL_KEY and _is_false(data[spelled])):
                return name, _OTHER_ELEMENT  # a hierarchy, or something a file cannot rule out
    return name, _FLAT_CATALOG


def _dynlist_mapper(source: SourceFile) -> dict | None:
    """The map phase: an element contributes its name and what it says of its tables; a yaml
    with lists contributes those whose main table decides - (table, message key, line, column,
    fix as (start, end, text))."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    fact: dict = {}
    element = _element_verdict(source)
    if element is not None:
        fact["element"] = element
    lists = [
        (
            finding.table, finding.key,
            finding.node.start_mark.line + 1, finding.node.start_mark.column + 1,
            (finding.fix.start, finding.fix.end, finding.fix.new) if finding.fix else None,
        )
        for finding in _findings(source)
        if finding.mode == _BY_TABLE and finding.table
    ]
    if lists:
        fact["lists"] = lists
    return fact or None


def _flat_table(table: str, elements: dict[str, set[str]]) -> bool:
    """Whether the main table certainly has no hierarchy - see the module docstring."""
    head, derived, _rest = _QUALIFIER.sub("", table).strip().partition(".")
    verdicts = elements.get(head)
    if not verdicts:
        return False  # not an element of the project: a system table, a library
    allowed = {_FLAT_ELEMENT} if derived else {_FLAT_ELEMENT, _FLAT_CATALOG}
    return verdicts <= allowed


@rule(
    "yaml/dynlist-scroll-without-loading", "yaml/dynlist-scroll-without-loading.title", "A",
    scope="project", severity=Severity.WARNING, mapper=_dynlist_mapper,
)
def dynlist_scroll_without_loading(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A flat dynamic list that never loads the tail, its hierarchy left to the main table."""
    elements: dict[str, set[str]] = {}
    for fact in facts.values():
        element = fact.get("element")
        if element is not None:
            elements.setdefault(element[0], set()).add(element[1])
    for rel, fact in facts.items():
        for table, key, line, col, fix in fact.get("lists", ()):
            if not _flat_table(table, elements):
                continue
            yield Diagnostic(
                rel, line, col, "yaml/dynlist-scroll-without-loading", Severity.WARNING,
                i18n.t(f"yaml/dynlist-scroll-without-loading.{key}", table=table),
                fix=TextEdit(*fix) if fix else None,
            )
