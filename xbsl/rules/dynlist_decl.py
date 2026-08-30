"""Tier D: pitfalls in the yaml DECLARATION of a dynamic list.

--- yaml/dynlist-joined-table-param ---

A JOINED table of a dynamic list (`Источник.ПрисоединенныеТаблицы`) cannot reference the
list's parameters or bind to code. The main table's arguments legally carry `&Имя` - a
live corpus form passes thirteen of them as list parameters - but inside a joined-table
item the very same spellings are a runtime refusal: an argument expression is parsed by
the query language (the metamodel says so of TableArgumentExpression), which knows neither
`&Имя` nor `=Method()`, and a filter expression of the joined table never gets the
parameter substituted. The compiler accepts all of it silently; the list fails at first
draw.

The exact slice keeps the legal forms out:
- only nodes INSIDE a JoinedTables item are judged; the main table's arguments and the
  list-level filter are never touched;
- an argument VALUE (a scalar, or the nested form with a type and a value) is flagged
  when the whole value matches `&Имя` - a data string that merely starts with '&', such
  as "&nbsp;", is not a parameter - or when it starts with '=' (that leading sign is how
  the platform itself tells a binding from a literal);
- an argument EXPRESSION is flagged when it starts with '=' or mentions `&Имя` outside
  string literals;
- a FILTER expression of the joined table is flagged when it mentions `&Имя` outside
  string literals; '=' is not judged there, since `==` is the query comparison.

The cure, already canonical in the corpus (the currencies list form): keep a literal in
the yaml and assign the live value from code on opening -
`Источник.ПрисоединенныеТаблицы[i].Аргументы`. All four corpora hold zero violations
with real material (17 joined tables with arguments), so the rule guards a convention
the code already follows.

--- yaml/list-form-needs-dynlist ---

A form inheriting ListForm whose content holds a table over an array source
(`Таблица<ИсточникДанныхМассив<...>>`, `ПроизвольныйСписок<...>` likewise) and not a
single type with DynamicList anywhere: the list-form skeleton is built around a
dynamic-list table, and the navigation item of such a form silently disappears - the
historical corpus case was cured by inheriting a plain form instead, with the fix naming
exactly that reason. Only this precise signal is reported: a list form with no list
component AT ALL is left alone on purpose, because the dynamic list may live inside a
nested project component the outer yaml never names (the platform docs bind the table
through `КомпонентТаблицы: =Компоненты.Cписок.Компоненты.Таблица`), and judging absence
would guess. The dynamic-list evidence is any content type carrying a DynamicList chain:
the scaffold's own card list is legally `ПроизвольныйСписок<ДинамическийСписок<...>>`,
so requiring specifically a table would misfire.

--- yaml/dynlist-filter-disabled ---

A filter item declared with `Использовать: Ложь` in the yaml while the PAIRED module
enables it by assigning the Use member is a first-render race: the platform reads the
list at draw time without waiting for the code, and until the assignment lands the list
shows the WHOLE table - in a personal account that meant another tenant's rows for over a
second, measured live and cured by declaring the filter enabled with an empty value. The
declared-disabled state alone is not judged (a filter the user switches on through the
platform's filter panel is legal), and neither is the assignment alone - assigning
`.Использовать` over an enabled-with-empty-value declaration IS the cure - so only the
pair of both halves fires. The yaml half is an explicit `Использовать: Ложь` on an item
typed as a filter item (a missing key defaults to enabled and proves nothing); the code
half is a token triple - the Use member after a dot, followed by a single '='
(the lexer keeps `==` one token, so a comparison cannot match). The finding is a warning,
not an error: one corpus list keeps the disabled declaration deliberately (row-level
security bounds what the first frame can leak there), and such a spot belongs in the
baseline rather than in a gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import code_tokens
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _mapping_nodes,
    _parsed,
    value_of,
)

if _HAVE_YAML:
    import yaml
from xbsl.rules.yaml_types import _key_spellings, _NAME_RE, _parse_type_string, _value_positions

MESSAGES = {
    "yaml/dynlist-joined-table-param.title": {
        "ru": "Параметр в присоединённой таблице динамического списка",
        "en": "A parameter in a dynamic list's joined table",
    },
    "yaml/dynlist-joined-table-param.argument": {
        "ru": "Аргумент присоединённой таблицы содержит '{text}' – параметры (&Имя) и "
              "биндинги (=...) в аргументах присоединённых таблиц не вычисляются: компилятор "
              "такой yaml принимает, а список отказывает в рантайме. Оставьте в yaml литерал, "
              "а живое значение присваивайте из кода при открытии: "
              "Источник.ПрисоединенныеТаблицы[i].Аргументы.",
        "en": "The joined table's argument carries '{text}' - parameters (&Name) and bindings "
              "(=...) in a joined table's arguments are never evaluated: the compiler accepts "
              "such a yaml, and the list fails at runtime. Keep a literal in the yaml and "
              "assign the live value from code on opening: "
              "{n[Источник]}.{n[ПрисоединенныеТаблицы]}[i].{n[Аргументы]}.",
    },
    "yaml/dynlist-joined-table-param.filter": {
        "ru": "Выражение фильтра присоединённой таблицы ссылается на параметр '{param}' – "
              "в фильтр присоединённой таблицы параметры не подставляются, и список "
              "отказывает в рантайме. Сравнивайте с литералом, а живое значение передавайте "
              "аргументом таблицы, присваивая его из кода: "
              "Источник.ПрисоединенныеТаблицы[i].Аргументы.",
        "en": "The joined table's filter expression references the parameter '{param}' - "
              "parameters are not substituted into a joined table's filter, and the list "
              "fails at runtime. Compare against a literal and pass the live value as a "
              "table argument assigned from code: "
              "{n[Источник]}.{n[ПрисоединенныеТаблицы]}[i].{n[Аргументы]}.",
    },
    "yaml/list-form-needs-dynlist.title": {
        "ru": "ФормаСписка без динамического списка",
        "en": "A list form without a dynamic list",
    },
    "yaml/list-form-needs-dynlist.array": {
        "ru": "Форма наследует ФормаСписка, а в содержимом нет ни одного типа с "
              "ДинамическийСписок – таблица типизирована '{table}'. Каркас формы списка "
              "заточен под таблицу динамического списка, и пункт навигации такой формы "
              "молча исчезает. Либо дайте таблице источник ДинамическийСписок, либо "
              "наследуйте обычную форму (Тип: Форма).",
        "en": "The form inherits {n[ФормаСписка]} while its content carries no type with "
              "{n[ДинамическийСписок]} - the table is typed '{table}'. The list-form "
              "skeleton is built around a dynamic-list table, and the navigation item of "
              "such a form silently disappears. Either give the table a "
              "{n[ДинамическийСписок]} source or inherit a plain form ({n[Тип]}: {n[Форма]}).",
    },
    "yaml/dynlist-filter-disabled.title": {
        "ru": "Выключенный отбор динамического списка включается кодом",
        "en": "A disabled dynamic-list filter enabled from code",
    },
    "yaml/dynlist-filter-disabled.race": {
        "ru": "Элемент отбора '{field}' объявлен с 'Использовать: Ложь', а парный модуль "
              "включает его присваиванием – гонка первого показа: платформа читает список "
              "при отрисовке, не дожидаясь кода, и до включения отбора показывает всю "
              "таблицу. Объявляйте отбор включённым с пустым значением, а выключайте из "
              "кода, когда он действительно не нужен.",
        "en": "The filter item '{field}' is declared with '{n[Использовать]}: False' while "
              "the paired module enables it by assignment - the first-render race: the "
              "platform reads the list at draw time without waiting for the code, and until "
              "the filter is on it shows the whole table. Declare the filter enabled with an "
              "empty value, and switch it off from code when it is really not needed.",
    },
    "yaml/dynlist-filter-disabled.race-unnamed": {
        "ru": "Элемент отбора объявлен с 'Использовать: Ложь', а парный модуль включает его "
              "присваиванием – гонка первого показа: платформа читает список при отрисовке, "
              "не дожидаясь кода, и до включения отбора показывает всю таблицу. Объявляйте "
              "отбор включённым с пустым значением, а выключайте из кода, когда он "
              "действительно не нужен.",
        "en": "A filter item is declared with '{n[Использовать]}: False' while the paired "
              "module enables it by assignment - the first-render race: the platform reads "
              "the list at draw time without waiting for the code, and until the filter is "
              "on it shows the whole table. Declare the filter enabled with an empty value, "
              "and switch it off from code when it is really not needed.",
    },
}
i18n.register(MESSAGES)

#: A list parameter: '&' straight before a name (the query-language spelling).
_PARAM_RE = re.compile("&" + _NAME_RE.pattern)
#: A double-quoted string literal of a query expression - cut out before the parameter
#: search, so that '&' inside data text never counts.
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"')


def _entries(mapping) -> dict:
    """{raw key: value node} of a composed mapping, scalar keys only.

    Raw keys on purpose: the walk below matches them against the spelling tuples the
    data provides, and a canonicalizing lookup would need a schema context the nested
    source nodes do not carry.
    """
    return {
        k.value: v
        for k, v in mapping.value
        if isinstance(k, yaml.ScalarNode)
    }


def _scalar_text(node) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) and isinstance(node.value, str) else None


def _argument_offence(text: str, expression: bool) -> bool:
    """Whether an argument value/expression is a parameter or a binding.

    A VALUE is a parameter only when it matches `&Имя` whole (prefix matching would flag
    data such as "&nbsp;"); an EXPRESSION also hides parameters deeper, so it is searched
    with its string literals cut out. The leading '=' is the platform's own binding marker
    in both forms.
    """
    stripped = text.strip()
    if stripped.startswith("="):
        return True
    if _PARAM_RE.fullmatch(stripped):
        return True
    return expression and _PARAM_RE.search(_STRING_RE.sub('""', text)) is not None


def _argument_findings(args_node) -> Iterator[tuple[int, int, str]]:
    """(line, col, offending text) for the arguments of one joined-table item."""
    if not isinstance(args_node, yaml.SequenceNode):
        return
    value_keys = _key_spellings("Значение")
    expr_keys = _key_spellings("Выражение")
    for arg in args_node.value:
        if not isinstance(arg, yaml.MappingNode):
            continue
        for key, node in _entries(arg).items():
            if key in value_keys:
                text = _scalar_text(node)
                if text is None and isinstance(node, yaml.MappingNode):
                    # The nested form: a mapping with a type and the value itself.
                    for inner_key, inner in _entries(node).items():
                        if inner_key in value_keys:
                            node, text = inner, _scalar_text(inner)
                if text is not None and _argument_offence(text, expression=False):
                    yield node.start_mark.line + 1, node.start_mark.column + 1, text.strip()
            elif key in expr_keys:
                text = _scalar_text(node)
                if text is not None and _argument_offence(text, expression=True):
                    yield node.start_mark.line + 1, node.start_mark.column + 1, text.strip()


def _filter_findings(node) -> Iterator[tuple[int, int, str]]:
    """(line, col, parameter) for every parameter in a joined table's filter subtree."""
    expr_keys = _key_spellings("Выражение")
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, yaml.MappingNode):
            for key, value in _entries(current).items():
                if key in expr_keys:
                    text = _scalar_text(value)
                    if text is None:
                        continue
                    found = _PARAM_RE.search(_STRING_RE.sub('""', text))
                    if found is not None:
                        yield (value.start_mark.line + 1, value.start_mark.column + 1,
                               found.group(0))
                else:
                    stack.append(value)
        elif isinstance(current, yaml.SequenceNode):
            stack.extend(current.value)


@rule(
    "yaml/dynlist-joined-table-param", "yaml/dynlist-joined-table-param.title", "D",
    severity=Severity.ERROR,
)
def dynlist_joined_table_param(source: SourceFile) -> Iterable[Diagnostic]:
    """Parameters and bindings inside a joined table - a silent runtime refusal."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    joined_keys = _key_spellings("ПрисоединенныеТаблицы")
    if not any(key in source.text for key in joined_keys):
        return
    root = _composed(source)
    if root is None:
        return
    args_keys = _key_spellings("Аргументы")
    filter_keys = _key_spellings("Фильтр")
    for mapping in _mapping_nodes(root):
        for key, value in _entries(mapping).items():
            if key not in joined_keys or not isinstance(value, yaml.SequenceNode):
                continue
            for item in value.value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                for item_key, item_value in _entries(item).items():
                    if item_key in args_keys:
                        for line, col, text in _argument_findings(item_value):
                            yield Diagnostic(
                                source.rel, line, col,
                                "yaml/dynlist-joined-table-param", Severity.ERROR,
                                i18n.t("yaml/dynlist-joined-table-param.argument",
                                       text=text),
                            )
                    elif item_key in filter_keys:
                        for line, col, param in _filter_findings(item_value):
                            yield Diagnostic(
                                source.rel, line, col,
                                "yaml/dynlist-joined-table-param", Severity.ERROR,
                                i18n.t("yaml/dynlist-joined-table-param.filter",
                                       param=param),
                            )


@lru_cache(maxsize=1)
def _list_form_names() -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
    """(list form, dynamic list, array source, list heads) - both spellings, from the data.

    A name the term dictionary does not pair stays as the platform writes it in Russian,
    so nothing here is invented; without the data bundle the English half is simply absent
    and an English project is not judged at all.
    """
    def pair(name: str) -> frozenset[str]:
        return frozenset({name, terms.common_english(name) or name})

    return (
        pair("ФормаСписка"),
        pair("ДинамическийСписок"),
        pair("ИсточникДанныхМассив"),
        pair("Таблица") | pair("ПроизвольныйСписок"),
    )


dataset.register_reset(_list_form_names.cache_clear)


def _content_types(node) -> Iterator[str]:
    """Every string value of a type key in the parsed content subtree, both spellings."""
    type_keys = _key_spellings("Тип")
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key in type_keys:
                value = current.get(key)
                if isinstance(value, str):
                    yield value
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


@rule(
    "yaml/list-form-needs-dynlist", "yaml/list-form-needs-dynlist.title", "D",
    severity=Severity.ERROR,
)
def list_form_needs_dynlist(source: SourceFile) -> Iterable[Diagnostic]:
    """A list form over an array table with no dynamic list - the navigation item vanishes."""
    if not _HAVE_YAML or source.kind != "yaml":
        return
    list_form, dynlist, array_source, list_heads = _list_form_names()
    if not any(name in source.text for name in list_form):
        return
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return
    inherits = value_of(data, "Наследует")
    if not isinstance(inherits, dict):
        return
    base = value_of(inherits, "Тип")
    if not isinstance(base, str):
        return
    base_chains = _parse_type_string(base)
    # The generic argument is optional in the wild: both a bare list form and one over
    # an explicit row type are written, so only the head is required.
    if not base_chains or len(base_chains[0]) != 1 or base_chains[0][0] not in list_form:
        return
    array_table: str | None = None
    for typ in _content_types(value_of(inherits, "Содержимое")):
        chains = _parse_type_string(typ)
        if not chains:
            continue
        if any(chain[0] in dynlist for chain in chains):
            return  # a dynamic list somewhere in the content - the skeleton is served
        if (array_table is None and len(chains) > 1 and len(chains[0]) == 1
                and chains[0][0] in list_heads
                and any(chain[0] in array_source for chain in chains[1:])):
            array_table = typ
    if array_table is None:
        return  # no list at all: it may live in a nested component - absence is not judged
    positions = _value_positions(source, base)
    line, col = positions[0] if positions else (1, 1)
    yield Diagnostic(
        source.rel, line, col, "yaml/list-form-needs-dynlist", Severity.ERROR,
        i18n.t("yaml/list-form-needs-dynlist.array", table=array_table),
    )


#: The declared-disabled spellings of the Use flag - what the platform serializer writes.
_FALSE_VALUES = ("Ложь", "False")


@lru_cache(maxsize=1)
def _filter_item_types() -> frozenset[str]:
    """The filter item type names, both spellings, from the term dictionary."""
    names = ("ЭлементФильтра", "ЭлементФильтраВыражение", "ГруппаЭлементовФильтра")
    out: set[str] = set()
    for name in names:
        out.add(name)
        english = terms.common_english(name)
        if english:
            out.add(english)
    return frozenset(out)


dataset.register_reset(_filter_item_types.cache_clear)


def _disabled_filter_items(source: SourceFile) -> list[tuple[int, int, str]]:
    """(line, col, field) of the filter items the yaml declares disabled.

    The position is the declared value itself; the field is what names the item in the
    message - the filter field, the expression, or an empty string for a group.
    """
    root = _composed(source)
    if root is None:
        return []
    item_types = _filter_item_types()
    type_keys = _key_spellings("Тип")
    use_keys = _key_spellings("Использовать")
    field_keys = _key_spellings("Поле") + _key_spellings("Выражение")
    items: list[tuple[int, int, str]] = []
    for mapping in _mapping_nodes(root):
        entries = _entries(mapping)
        typ = next(
            (_scalar_text(entries[key]) for key in type_keys if key in entries), None
        )
        if typ not in item_types:
            continue
        declared = next(
            (entries[key] for key in use_keys if key in entries), None
        )
        text = _scalar_text(declared)
        if text is None or text.strip() not in _FALSE_VALUES:
            continue
        field = next(
            (_scalar_text(entries[key]) for key in field_keys if key in entries), None
        )
        items.append(
            (declared.start_mark.line + 1, declared.start_mark.column + 1, field or "")
        )
    return items


def _filter_disabled_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml contributes its declared-disabled filter items; a module
    contributes the fact that it assigns the Use member of something - the reduce joins
    the pair by the file stem, and only the pair fires."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        use_members = _key_spellings("Использовать")
        if not any("." + member in source.text for member in use_members):
            return None
        toks = code_tokens(source)
        n = len(toks)
        for i, t in enumerate(toks):
            if (t.kind == "IDENT" and t.value in use_members
                    and i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == "."
                    and i + 1 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "="):
                return {"k": "x", "stem": _pair_stem(source.rel)}
        return None
    if source.kind != "yaml":
        return None
    use_keys = _key_spellings("Использовать")
    if not (any(key in source.text for key in use_keys)
            and any(value in source.text for value in _FALSE_VALUES)):
        return None
    items = _disabled_filter_items(source)
    if not items:
        return None
    return {"k": "y", "stem": _pair_stem(source.rel), "items": items}


@rule(
    "yaml/dynlist-filter-disabled", "yaml/dynlist-filter-disabled.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_filter_disabled_mapper,
)
def dynlist_filter_disabled(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    setters = {fact["stem"] for fact in facts.values() if fact["k"] == "x"}
    for rel, fact in facts.items():
        if fact["k"] != "y" or fact["stem"] not in setters:
            continue
        for line, col, field in fact["items"]:
            if field:
                message = i18n.t("yaml/dynlist-filter-disabled.race", field=field)
            else:
                message = i18n.t("yaml/dynlist-filter-disabled.race-unnamed")
            yield Diagnostic(
                rel, line, col, "yaml/dynlist-filter-disabled", Severity.WARNING, message,
            )
