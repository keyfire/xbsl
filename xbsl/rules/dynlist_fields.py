"""Tier D: completeness of a dynamic list's field set against its object's attributes.

The yaml/dynlist-missing-field rule encodes a pitfall that neither the compiler nor apply
catches: a dynamic list typed with the row data of the object's automatic list form
(`Таблица<ДинамическийСписок<Акция.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>`) must
select EVERY attribute of that object in `Источник.Поля` – at runtime the list crashes
with "Отсутствует обязательное поле <Имя>" for the first attribute it cannot find. The
typical way to hit it: an attribute is added to the object, the list forms stay behind.

The criterion is empirical. Every list typed with the three-segment chain `<Объект>.АвтоматическаяФормаСписка.
ДанныеСтрокиСписка` carries the object's ENTIRE declared attribute set in `Поля` (plus
`Ссылка`); the weaker criterion "only the required attributes" has no empirical support and
is not used. Lists
that derive the row type from the declaration itself require nothing and are skipped:
the untyped `Таблица<ДинамическийСписок>` (a list is kept untyped exactly when the full
set cannot be selected) and a form's own row type (`ФормаX.ДанныеСтрокиСписка`,
two segments – the platform docs declare such lists with a subset of fields).

Zero-false-positive guards:
- only nodes whose `Тип` contains exactly one generic argument of the form
  `X.АвтоматическаяФормаСписка.ДанныеСтрокиСписка`, where X is a project object of kind
  Справочник/Документ with a parsed `Реквизиты` list;
- `Источник.ОсновнаяТаблица.Таблица` must equal X – an aliased or foreign table is skipped;
- `Источник.Поля` must be a non-empty list of mappings with string `Выражение` values;
  anything else means the field set cannot be trusted, and the node is skipped;
- collection-typed attributes (Массив/Соответствие/Множество/СписокЗначений) and binary
  ones (ДвоичныйОбъект) are not required: a typed selection cannot carry them at all
  (the compiler rejects "references a collection attribute", so such lists stay untyped) – a typed list over such an object is a documented false negative;
- `Ссылка` and standard fields not declared in `Реквизиты` are not required – the rule
  checks only what the object's yaml declares;
- an attribute counts as present when its name matches a field's `Выражение` (bare or
  the last segment of a qualified `Псевдоним.Имя`) or the field's `Псевдоним`.

The rule is project-wide: it needs the objects' yaml next to the forms' yaml, so it does
not run in single-file mode.

--- yaml/dynlist-row-editing ---

The OnRowEdit event of a list is declared for the NODE types of a hierarchical source, and
on a flat dynamic list the platform never calls it at all (verified live, the registry case
of 2026-08): the handler looks like working code, `СтандартнаяОбработка = Ложь` inside it
changes nothing, and a click still opens the object's automatic form with its service
attributes. The cure is to give the object its OWN object form - the standard mechanism
opens it without any handler.

The slice keeps both sides certain:

* the component's type names the entity explicitly - a chain of a list head over a dynamic
  list with an argument (the entity itself or its row-form type, whose first segment is the
  entity). The untyped list of a list form implies its entity rather than naming it, and
  resolving the implication would guess;
* the entity's yaml is in the project and declares NO hierarchy (none of the hierarchy
  keys): a hierarchical source has node rows, for which the event is documented, so it is
  left alone whatever the component does with the hierarchy.

--- yaml/dynlist-column-sort-lost ---

A column whose `Value` CALLS something (`=FormatDate(RowData.Data.Start)`) cannot be sorted
by clicking its header: the sort is bound to the FIELD of the source, not to the text on the
screen, and the platform simply does not react to the click. The cure is a binding straight
onto the field (`=RowData.Data.Start`, the platform renders the value by its type); when both
a custom format and sorting are needed, the presentation field goes into the dynamic list
itself (a `DynamicListField` with an `Expression`) instead of being computed on the client.

Only a column of a table over a DYNAMIC LIST is judged - header sorting exists there; an
array-backed list has none, and a computed column in it is not a defect at all. A column that
switches sorting off itself (`ОтключитьСортировку: Истина`, `DisableSorting: True`) is skipped
as well: there is no header sorting left for the computed value to cost. The rule is
info and OFF by default: the finding is true (the header really does not sort), but whether
that column was ever meant to sort is not visible from the file - a status badge or a
service column is legitimately unsortable. Enable it when a header does not react and you
are looking for the reason.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from functools import lru_cache

from xbsl import dataset, i18n, metamodel, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
    object_kind,
    value_of,
)

if _HAVE_YAML:
    import yaml
from xbsl.rules.yaml_types import (
    _key_spellings,
    _NAME_RE,
    _parse_type_string,
    _value_positions,
)
from xbsl.translation import platform_map

MESSAGES = {
    "yaml/dynlist-missing-field.title": {
        "ru": "Нет поля динамического списка",
        "en": "Missing dynamic-list field",
    },
    "yaml/dynlist-missing-field.missing": {
        "ru": "В Источник.Поля нет реквизита '{attr}' объекта '{obj}' – список типизирован "
              "'{obj}.АвтоматическаяФормаСписка.ДанныеСтрокиСписка' и требует все реквизиты; "
              "в рантайме список упадёт с ошибкой 'Отсутствует обязательное поле'.",
        "en": "{n[Источник.Поля]} misses attribute '{attr}' of object '{obj}' – the list is typed "
              "with '{obj}.{n[АвтоматическаяФормаСписка]}.ДанныеСтрокиСписка' and requires every "
              "attribute; at runtime the list crashes with a required-field error.",
    },
    "yaml/dynlist-column-sort-lost.title": {
        "ru": "Колонка с вычисляемым значением не сортируется",
        "en": "A column with a computed value does not sort",
    },
    "yaml/dynlist-column-sort-lost.computed": {
        "ru": "Значение колонки – вызов '{call}', и сортировка по её заголовку работать не "
              "будет: платформа сортирует по ПОЛЮ источника, а не по отображаемому тексту. "
              "Нужна сортировка – привязывайте колонку прямо к полю (представление платформа "
              "нарисует по типу значения) либо добавьте поле-представление в сам динамический "
              "список (ПолеДинамическогоСписка с Выражение), а не считайте его на клиенте.",
        "en": "The column value is a call of '{call}', so sorting by its header will not "
              "work: the platform sorts by the FIELD of the source, not by the text on "
              "screen. If sorting is needed, bind the column straight to the field (the "
              "platform renders the value by its type) or add a presentation field to the "
              "dynamic list itself (a {n[ПолеДинамическогоСписка]} with an {n[Выражение]}) "
              "instead of computing it on the client.",
    },
    "yaml/dynlist-row-editing.title": {
        "ru": "ПриРедактированииСтроки у плоского динамического списка",
        "en": "OnRowEdit on a flat dynamic list",
    },
    "yaml/dynlist-row-editing.silent": {
        "ru": "Событие '{key}' у списка с плоским динамическим источником '{obj}' платформа "
              "не вызывает вовсе (оно объявлено для узловых строк иерархии): обработчик "
              "выглядит рабочим, а по нажатию открывается автоформа объекта со служебными "
              "реквизитами. Дайте объекту свою форму объекта (Интерфейс.Объект.Форма) – "
              "штатный механизм откроет её.",
        "en": "The '{key}' event of a list over the flat dynamic source '{obj}' is never "
              "called by the platform (it is declared for the node rows of a hierarchy): "
              "the handler looks like working code, while a click opens the object's "
              "automatic form with its service attributes. Give the object its own object "
              "form – the standard mechanism opens it.",
    },
}
i18n.register(MESSAGES)

# The automatic list form's row-data chain: <Объект>.АвтоматическаяФормаСписка.ДанныеСтрокиСписка.
_AUTO_TAIL = ("АвтоматическаяФормаСписка", "ДанныеСтрокиСписка")


@lru_cache(maxsize=1)
def _auto_tails() -> tuple[tuple[str, ...], ...]:
    """The row-data chain segment by segment, every spelling the platform declares.

    The first segment is paired in the distribution's member dictionary; the second one is
    not paired anywhere, so it stands alone - a name the platform does not translate is left
    as the author wrote it rather than invented here.
    """
    return tuple(
        tuple(dict.fromkeys((segment, platform_map.member_english(segment) or segment)))
        for segment in _AUTO_TAIL
    )


dataset.register_reset(_auto_tails.cache_clear)

# Object kinds whose declared attributes are known to make up the automatic row type.
_OBJECT_KINDS = frozenset({"Справочник", "Документ"})

# Attribute type roots a typed selection cannot carry – excluded from the required set.
_EXCLUDED_ROOTS = frozenset({
    "Массив", "Соответствие", "Множество", "СписокЗначений", "ДвоичныйОбъект",
})


def _source_nodes(node) -> Iterator[dict]:
    """Mapping nodes of the parsed yaml tree that carry both a type key and a mapping source.

    Both keys count in either spelling: an English project writes `Type:` and `Source:`, and
    a walk that knows the Russian names alone finds no dynamic list in such a project at all.
    """
    if isinstance(node, dict):
        if any(key in node for key in _key_spellings("Тип")) and isinstance(
            value_of(node, "Источник"), dict
        ):
            yield node
        for v in node.values():
            yield from _source_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _source_nodes(item)


def _declared_names(fields: list) -> set[str] | None:
    """Field names a `Поля` list declares, or None when the list cannot be trusted.

    A name is the `Выражение` itself, the last segment of a qualified expression
    (`Псевдоним.Имя`) and the `Псевдоним` when present. A field without a string
    `Выражение` makes the whole set unreliable – the caller skips the node.
    """
    names: set[str] = set()
    for f in fields:
        if not isinstance(f, dict):
            return None
        expr = value_of(f, "Выражение")
        if not isinstance(expr, str):
            return None
        names.add(expr)
        if "." in expr:
            names.add(expr.rsplit(".", 1)[1])
        alias = value_of(f, "Псевдоним")
        if isinstance(alias, str):
            names.add(alias)
    return names


def _dynlist_mapper(source: SourceFile) -> dict | None:
    """The map phase: an object yaml contributes its attribute list, any yaml its
    dynamic-list nodes - (object, declared field names, position). The required-versus-
    present check runs in the reduce, where the object attributes are known."""
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    fact: dict = {}
    attrs = _own_attributes(data)
    if attrs is not None:
        fact["attrs"] = attrs
    if object_kind(data):
        lists: list[tuple[str, list[str], int, int]] = []
        seen: dict[str, int] = {}  # pairing of repeated `Тип` values with their text positions
        tails = _auto_tails()
        for node in _source_nodes(data):
            typ = value_of(node, "Тип")
            if not isinstance(typ, str):
                continue
            occurrence = seen.get(typ, 0)
            seen[typ] = occurrence + 1
            chains = _parse_type_string(typ)
            if not chains:
                continue
            autos = [
                c for c in chains
                if len(c) == 3 and all(seg in forms for seg, forms in zip(c[1:], tails))
            ]
            if len(autos) != 1:
                continue
            obj = autos[0][0]
            src = value_of(node, "Источник")
            main = value_of(src, "ОсновнаяТаблица")
            if not isinstance(main, dict) or value_of(main, "Таблица") != obj:
                continue
            fields = value_of(src, "Поля")
            if not isinstance(fields, list) or not fields:
                continue
            present = _declared_names(fields)
            if present is None:
                continue
            positions = _value_positions(source, typ)
            if occurrence < len(positions):
                line, col = positions[occurrence]
            elif positions:
                line, col = positions[0]
            else:
                line, col = 1, 1
            lists.append((obj, sorted(present), line, col))
        if lists:
            fact["lists"] = lists
    return fact or None


def _own_attributes(data: dict) -> tuple[str, list[str]] | None:
    """(object name, required attribute names) of an object yaml, else None."""
    kind = object_kind(data)
    if kind not in _OBJECT_KINDS:
        return None
    name = value_of(data, "Имя", kind)
    parts = value_of(data, "Реквизиты", kind)
    if not isinstance(name, str) or not isinstance(parts, list):
        return None
    attrs: list[str] = []
    for p in parts:
        if not isinstance(p, dict):
            continue
        attr = value_of(p, "Имя")
        if not isinstance(attr, str) or not _NAME_RE.fullmatch(attr):
            continue
        typ = value_of(p, "Тип")
        if isinstance(typ, str):
            chains = _parse_type_string(typ)
            if chains is None or any(c[0] in _EXCLUDED_ROOTS for c in chains):
                continue
        attrs.append(attr)
    return name, attrs


#: The list component heads the event may sit on (canonical names).
_LIST_HEADS = frozenset({"Таблица", "СтандартныйСписок", "ПроизвольныйСписок", "Список"})
_ROW_EDIT = "ПриРедактированииСтроки"
_DYNLIST = "ДинамическийСписок"
#: The keys an entity yaml declares a hierarchy with (the Catalog metamodel).
_HIER_KEYS = ("Иерархический", "Иерархия", "ДополнительныеИерархии")


@lru_cache(maxsize=1)
def _row_edit_names() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """(event keys, dynamic-list names, hierarchy keys) - both spellings, from the
    dictionaries; the component heads are canonicalized at match time instead."""
    def pair(name: str, english: str | None) -> frozenset[str]:
        return frozenset({name, english} - {None})

    aliases = metamodel.key_aliases()
    hier = frozenset(_HIER_KEYS) | frozenset(
        en for en, ru in aliases.items() if ru in _HIER_KEYS
    )
    return (
        pair(_ROW_EDIT, terms.common_english(_ROW_EDIT)),
        pair(_DYNLIST, terms.common_english(_DYNLIST)),
        hier,
    )


dataset.register_reset(_row_edit_names.cache_clear)


def _typed_nodes(node) -> Iterator[dict]:
    """Mapping nodes of the parsed yaml tree that carry a type key in either spelling."""
    if isinstance(node, dict):
        if "Тип" in node or "Type" in node:
            yield node
        for v in node.values():
            yield from _typed_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _typed_nodes(item)


def _row_edit_mapper(source: SourceFile) -> dict | None:
    """The map phase. An entity yaml contributes its name and whether it declares a
    hierarchy; any yaml contributes the row-edit handlers of its explicitly typed
    dynamic lists - (entity, event key, position)."""
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    events_keys, dynlist_names, hier_keys = _row_edit_names()
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    fact: dict = {}
    kind = object_kind(data)
    if kind:
        name = value_of(data, "Имя", kind)
        if isinstance(name, str) and name:
            fact["entity"] = (name, any(data.get(key) for key in hier_keys))
    if any(key in source.text for key in events_keys):
        handlers: list[tuple[str, str, int, int]] = []
        seen: dict[tuple[str, str], int] = {}
        for node in _typed_nodes(data):
            typ = node.get("Тип") or node.get("Type")
            if not isinstance(typ, str):
                continue
            chains = _parse_type_string(typ)
            if (not chains or len(chains) < 3 or len(chains[0]) != 1
                    or len(chains[1]) != 1 or chains[1][0] not in dynlist_names):
                continue
            if uischema.canonical_component(chains[0][0]) not in _LIST_HEADS:
                continue
            entity = chains[2][0]  # the entity itself or the head of its row-form type
            for key, value in node.items():
                if key not in events_keys or not isinstance(value, str):
                    continue
                occurrence = seen.get((key, value), 0)
                seen[(key, value)] = occurrence + 1
                positions = _value_positions(source, value, key=key)
                if occurrence < len(positions):
                    line, col = positions[occurrence]
                elif positions:
                    line, col = positions[0]
                else:
                    line, col = 1, 1
                handlers.append((entity, key, line, col))
        if handlers:
            fact["row_edits"] = handlers
    return fact or None


#: The value of a column that CALLS something: `=Метод(...)`, `=Модуль.Метод(...)`. A bare
#: path binding (`=RowData.Data.Поле`) carries no parentheses and is the sortable form.
_CALL_VALUE_RE = re.compile(r"^\s*=\s*(?P<call>[^\W\d][\w.]*)\s*\(", re.UNICODE)
_COLUMNS_KEYS = ("Колонки", "Columns")
_VALUE_KEYS = ("Значение", "Value")
_DISABLE_SORT_KEYS = ("ОтключитьСортировку", "DisableSorting")
_TRUE_VALUES = ("Истина", "True")


def _sorting_disabled(column: yaml.MappingNode) -> bool:
    """The column switches header sorting off itself - a computed value costs it nothing."""
    for key, value in column.value:
        if not (isinstance(key, yaml.ScalarNode) and key.value in _DISABLE_SORT_KEYS):
            continue
        if isinstance(value, yaml.ScalarNode) and (value.value or "").strip() in _TRUE_VALUES:
            return True
    return False


@rule(
    "yaml/dynlist-column-sort-lost", "yaml/dynlist-column-sort-lost.title", "D",
    severity=Severity.INFO, enabled_by_default=False,
    off_reason="yaml/dynlist-column-sort-lost.off",
)
def dynlist_column_sort_lost(source: SourceFile) -> Iterable[Diagnostic]:
    """A computed column of a table over a dynamic list - its header will not sort."""
    if not _HAVE_YAML or source.kind != "yaml" or "(" not in source.text:
        return
    _events, dynlist_names, _hier = _row_edit_names()
    if not dynlist_names:
        return
    root = _composed(source)
    if root is None:
        return
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип") or entries.get("Type")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        chains = _parse_type_string(type_entry[1].value)
        if not chains or not any(
            len(chain) == 1 and chain[0] in dynlist_names for chain in chains
        ):
            continue  # the table is not typed over a dynamic list - no header sorting at all
        columns = None
        for key, value in mapping.value:
            if isinstance(key, yaml.ScalarNode) and key.value in _COLUMNS_KEYS:
                columns = value
        if not isinstance(columns, yaml.SequenceNode):
            continue
        for column in columns.value:
            if not isinstance(column, yaml.MappingNode):
                continue
            if _sorting_disabled(column):
                continue  # the column has no header sorting to lose
            for key, value in column.value:
                if not (isinstance(key, yaml.ScalarNode) and key.value in _VALUE_KEYS):
                    continue
                if not isinstance(value, yaml.ScalarNode):
                    continue
                found = _CALL_VALUE_RE.match(value.value or "")
                if found is None:
                    continue
                yield Diagnostic(
                    source.rel,
                    value.start_mark.line + 1, value.start_mark.column + 1,
                    "yaml/dynlist-column-sort-lost", Severity.INFO,
                    i18n.t("yaml/dynlist-column-sort-lost.computed",
                           call=found.group("call")),
                )


@rule(
    "yaml/dynlist-row-editing", "yaml/dynlist-row-editing.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_row_edit_mapper,
)
def dynlist_row_editing(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    hierarchical: dict[str, bool] = {}
    for fact in facts.values():
        if "entity" in fact:
            name, hier = fact["entity"]
            hierarchical[name] = hier
    for rel, fact in facts.items():
        for entity, key, line, col in fact.get("row_edits", ()):
            if hierarchical.get(entity) is not False:
                continue  # unknown entity, or a hierarchical one - the node rows are legal
            yield Diagnostic(
                rel, line, col, "yaml/dynlist-row-editing", Severity.WARNING,
                i18n.t("yaml/dynlist-row-editing.silent", key=key, obj=entity),
            )


@rule(
    "yaml/dynlist-missing-field", "yaml/dynlist-missing-field.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_dynlist_mapper,
)
def dynlist_missing_field(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    # Object -> its required attribute names, from the yaml facts.
    objects: dict[str, list[str]] = {}
    for fact in facts.values():
        if "attrs" in fact:
            name, attrs = fact["attrs"]
            objects[name] = attrs
    if not objects:
        return
    for rel, fact in facts.items():
        for obj, present, line, col in fact.get("lists", ()):
            required = objects.get(obj)
            if not required:
                continue
            for attr in required:
                if attr not in present:
                    yield Diagnostic(
                        rel, line, col, "yaml/dynlist-missing-field", Severity.WARNING,
                        i18n.t("yaml/dynlist-missing-field.missing", attr=attr, obj=obj),
                    )


