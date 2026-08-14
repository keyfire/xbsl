"""Tier D: fields of a dynamic list's generated row type (code/unknown-row-field).

A form's dynamic list names its row type with `ИмяТипаДанныхСтроки`, and the fields of that
type are the list's `Поля` - the `Псевдоним` when there is one, otherwise the last segment of
the expression. The type itself the engine already knows (`semantics._row_type_names`), but
nobody checked the FIELDS: `Строка.КодАбонент` instead of `КодАбонента` passes the linter and
fails the server-side compilation.

How a variable gets the row type (an AST walk, per method - one map per FILE would be wrong,
because a variable named `Строка` carries different row types in different handlers):

- a parameter or a declaration annotated `СтрокаДинамическогоСписка<Форма.ТипСтроки>`;
- `знч С = <такая переменная>.Данные` - the shape every generated handler uses.

Narrowing: only the first hop through a variable is judged. A direct chain
(`ДанныеСтроки.Данные.Поле`) is left alone - the member walker collects the inner access, and
guessing the outer one is not worth a false positive. A name declared twice with different row
types anywhere in the method is poisoned and skipped. The object protocol members
(ВСтроку, ПолучитьТип, Представление) are always allowed.
"""

from __future__ import annotations

import dataclasses
import difflib
import re
from collections.abc import Iterable
from functools import cache, lru_cache

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.unknown_members import _COMMON_MEMBERS, _walk_body, _walk_expr
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/unknown-row-field.title": {
        "ru": "Неизвестное поле строки динамического списка",
        "en": "Unknown field of a dynamic list row",
    },
    "code/unknown-row-field.found": {
        "ru": "У строки '{type}' нет поля '{field}' – поля строки перечислены в 'Поля' "
              "динамического списка (псевдоним либо последний сегмент выражения).",
        "en": "Row type '{type}' has no field '{field}' - the fields of a row are the list's "
              "'{n[Поля]}' (the alias, or the last segment of the expression).",
    },
    "code/unknown-row-field.found-hint": {
        "ru": "У строки '{type}' нет поля '{field}' – возможно, имелось в виду '{hint}'.",
        "en": "Row type '{type}' has no field '{field}' - did you mean '{hint}'?",
    },
    "code/row-field-null.title": {
        "ru": "Поле строки через ссылку может быть Null",
        "en": "A row field taken through a reference may be Null",
    },
    "code/row-field-null.assign": {
        "ru": "Поле '{field}' получено через ссылку ('{expr}'), поэтому его тип – '{type}|Null', "
              "а поле '{target}' структуры '{struct}' объявлено как '{type}': компилятор "
              "откажет ('Null cannot be assigned'). В описании списка допишите "
              "'.ЗаменитьNull(...)' к выражению поля.",
        "en": "Field '{field}' is taken through a reference ('{expr}'), so its type is "
              "'{type}|Null', while field '{target}' of structure '{struct}' is declared "
              "'{type}': the compiler refuses ('Null cannot be assigned'). Append "
              "'.ЗаменитьNull(...)' to the field expression in the list description.",
    },
}
i18n.register(MESSAGES)

# `СтрокаДинамическогоСписка<Форма.ТипСтроки>` in either spelling; the argument is the row type.
_ROW_TYPE_RE = re.compile(
    r"^\s*(?:СтрокаДинамическогоСписка|DynamicListRow)\s*<\s*([^<>]+?)\s*>\s*$"
)
_DATA_MEMBERS = frozenset({"Данные", "Data"})


@lru_cache(maxsize=1)
def _row_own_members() -> frozenset[str]:
    """The members the row type itself carries, from the catalog rather than from a list.

    A row is not only the list's fields: the type has `Data` and `Key` of its own, and the key
    is how a row command reaches the reference behind the row - casting it to the reference type
    is the documented shape. While the rule knew the data member alone, that shape read as a
    field the list does not have. Taken from the data, so a member added by a platform build
    needs no edit here; without the data the set is empty and the rule keeps its own guards.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, the rule still has _DATA_MEMBERS
        return frozenset()
    record = (catalog.get("type_members") or {}).get("СтрокаДинамическогоСписка") or {}
    return frozenset(record.get("properties", ()) or ()) | frozenset(record.get("methods", ()) or ())


dataset.register_reset(_row_own_members.cache_clear)


def _row_of_typeref(tref: P.TypeRef | None) -> str | None:
    """The row type named by `СтрокаДинамическогоСписка<...>`, or None."""
    if tref is None:
        return None
    m = _ROW_TYPE_RE.match(tref.text)
    return m.group(1).strip() if m else None


class _RowScope:
    """Per-method collection: variable name -> row type (None once the name is poisoned).

    The interface `_walk_body` expects (declare/types), so the walkers of unknown_members are
    reused as they are.
    """

    def __init__(self) -> None:
        self.types: dict[str, str | None] = {}

    def declare(self, name: str, tref: P.TypeRef | None, init: P.Expr | None = None) -> None:
        row = _row_of_typeref(tref)
        if row is None and isinstance(init, P.Member) and init.name in _DATA_MEMBERS:
            if isinstance(init.obj, P.Name):
                row = self.types.get(init.obj.name)
        if name in self.types and self.types[name] != row:
            self.types[name] = None
        else:
            self.types[name] = row


def _table_aliases(node) -> set[str]:
    """Aliases the list declares for its tables - a dotted head that names one is not a reference."""
    aliases: set[str] = set()
    main = value_of(node, "ОсновнаяТаблица")
    if isinstance(main, dict):
        alias = value_of(main, "Псевдоним")
        if isinstance(alias, str) and alias:
            aliases.add(alias)
    joined = value_of(node, "ПрисоединенныеТаблицы")
    for item in joined if isinstance(joined, list) else ():
        if isinstance(item, dict):
            alias = value_of(item, "Псевдоним")
            if isinstance(alias, str) and alias:
                aliases.add(alias)
    return aliases


def _list_fields(node) -> Iterable[tuple[str, dict[str, str]]]:
    """(row type name, {field: the expression that may yield Null, '' when it may not}).

    A field taken THROUGH A REFERENCE (`Абонент.Номер`) is typed `<тип>|Null`, and that costs:
    assigning it to a typed structure field answers
    `Incompatible types: "Null" cannot be assigned to "Число"`. A dotted head that names one of
    the list's own table aliases is not a reference, and neither is an expression that already
    ends with `.ЗаменитьNull(...)`.
    """
    if isinstance(node, dict):
        name = value_of(node, "ИмяТипаДанныхСтроки")
        if isinstance(name, str) and name:
            aliases = _table_aliases(node)
            fields: dict[str, str] = {}
            items = value_of(node, "Поля")
            for item in items if isinstance(items, list) else ():
                if not isinstance(item, dict):
                    continue
                expr = value_of(item, "Выражение")
                expr = expr if isinstance(expr, str) else ""
                # `Вид.Код.ЗаменитьNull("")` -> Код: the call tail is not part of the name
                head = expr.split("(", 1)[0].strip()
                segment = head.rsplit(".", 1)[-1].strip()
                alias = value_of(item, "Псевдоним")
                field = alias if isinstance(alias, str) and alias else segment
                if not field:
                    continue
                through_reference = (
                    "." in head
                    and "ЗаменитьNull" not in expr and "ReplaceNull" not in expr
                    and head.split(".", 1)[0].strip() not in aliases
                )
                fields[field] = expr if through_reference else ""
            yield name, fields
        for value in node.values():
            yield from _list_fields(value)
    elif isinstance(node, list):
        for item in node:
            yield from _list_fields(item)


def _row_fields_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes the row types it declares with their fields, a module
    the member accesses on variables it could type as a row."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict) or not object_kind(data):
            return None
        owner = value_of(data, "Имя")
        rows = [
            (f"{owner}.{name}" if isinstance(owner, str) else name, name, fields)
            for name, fields in _list_fields(data)
        ]
        return {"k": "y", "rows": rows} if rows else None
    if source.kind != "xbsl":
        return None
    module, errors = parse(source)
    if errors:
        return None  # a broken file has its own diagnostics (code/parse-error)
    lm = linemap(source)
    methods: list[P.Method] = []
    for m in module.members:
        if isinstance(m, P.Method):
            methods.append(m)
        elif isinstance(m, P.Structure):
            methods.extend(sub for sub in m.members if isinstance(sub, P.Method))
        elif isinstance(m, P.Enum):
            methods.extend(m.methods)
    cands: list[tuple[str, str, int, int]] = []
    assigns: list[tuple[str, str, str, str, int, int]] = []
    for method in methods:
        scope = _RowScope()
        for p in method.params:
            scope.declare(p.name, p.type)
        uses: list[P.Member] = []
        for p in method.params:
            _walk_expr(p.default, scope, uses)
        _walk_body(method.body, scope, uses)
        for use in uses:
            if not isinstance(use.obj, P.Name):
                continue
            row = scope.types.get(use.obj.name)
            if (row is None or use.name in _DATA_MEMBERS or use.name in _COMMON_MEMBERS
                    or use.name in _row_own_members()):
                continue
            line, col = lm.linecol(use.start)
            cands.append((row, use.name, line, col))
        for row, field, struct, target, offset in _constructor_assignments(method, scope):
            line, col = lm.linecol(offset)
            assigns.append((row, field, struct, target, line, col))
    fact: dict = {"k": "x"}
    if cands:
        fact["cands"] = cands
    if assigns:
        fact["assigns"] = assigns
    structures = _module_structures(module)
    if structures:
        fact["structs"] = structures
    return fact if len(fact) > 1 else None


def _module_structures(module: P.Module) -> dict[str, dict[str, str]]:
    """{structure: {field: its declared type}} for the structures a module declares.

    A field whose type is nullable (or absent) accepts Null and is not recorded - only a field
    that provably refuses it can turn a row field into a finding.
    """
    out: dict[str, dict[str, str]] = {}
    for member in module.members:
        if not isinstance(member, P.Structure):
            continue
        fields: dict[str, str] = {}
        for sub in member.members:
            if not isinstance(sub, P.ObjectField) or sub.type is None:
                continue
            text = sub.type.text.strip()
            if text.endswith("?") or "Неопределено" in text or "Null" in text:
                continue
            fields[sub.name] = text
        if fields:
            out[member.name] = fields
    return out


def _constructor_assignments(
    method: P.Method, scope: _RowScope,
) -> Iterable[tuple[str, str, str, str, int]]:
    """(row type, row field, structure, target field, offset) of `новый Стр(Поле = Строка.Поле)`.

    Only a NAMED argument is taken: it names the target field outright, while a positional one
    would have to be matched against the declaration order - and a wrong guess here is a false
    error about types.
    """
    for new in _new_nodes(method.body):
        struct = new.type.text.strip() if new.type is not None else ""
        if not struct or "<" in struct:
            continue
        for arg in new.args or ():
            value = arg.value
            if not arg.name or not isinstance(value, P.Member):
                continue
            if not isinstance(value.obj, P.Name):
                continue
            row = scope.types.get(value.obj.name)
            if row:
                yield row, value.name, struct, arg.name, value.start


@cache
def _node_field_names(cls: type) -> tuple[str, ...]:
    """Field names of a node class, declared once per class (the walk below runs a lot)."""
    return tuple(f.name for f in dataclasses.fields(cls))


def _new_nodes(node) -> Iterable[P.New]:
    """Every `новый ...` expression inside a statement tree (a walk over the node fields).

    The fields come from the dataclass declaration and NOT from `vars(node)`: in the released
    wheel the parser is compiled by mypyc, and a compiled class has no `__dict__` at all - the
    attribute walk raised TypeError there and took the whole lint down with it.
    """
    if isinstance(node, P.New):
        yield node
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _new_nodes(item)
        return
    if not isinstance(node, P.Node):
        return
    for name in _node_field_names(type(node)):
        value = getattr(node, name, None)
        if isinstance(value, (P.Node, list, tuple)):
            yield from _new_nodes(value)


@rule(
    "code/unknown-row-field", "code/unknown-row-field.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_row_fields_mapper,
)
def unknown_row_field(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A field addressed on a dynamic list row must be among the list's Поля."""
    by_full, by_short = _row_catalog(facts)
    if not by_full:
        return
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        for row, field, line, col in fact.get("cands", ()):
            fields = by_full.get(row)
            if fields is None:
                fields = by_short.get(row)
            if not fields or field in fields:
                continue
            hint = difflib.get_close_matches(field, sorted(fields), n=1, cutoff=0.7)
            message = (
                i18n.t("code/unknown-row-field.found-hint", type=row, field=field, hint=hint[0])
                if hint else i18n.t("code/unknown-row-field.found", type=row, field=field)
            )
            yield Diagnostic(rel, line, col, "code/unknown-row-field", Severity.ERROR, message)


def _row_catalog(facts: dict[str, dict]) -> tuple[dict[str, dict[str, str]], dict]:
    """({full row name: fields}, {short name: fields or None when ambiguous})."""
    by_full: dict[str, dict[str, str]] = {}
    by_short: dict[str, dict[str, str] | None] = {}
    for fact in facts.values():
        if fact["k"] != "y":
            continue
        for full, short, fields in fact["rows"]:
            by_full[full] = dict(fields)
            # A short name is usable only while it is unambiguous across the project.
            by_short[short] = None if short in by_short else dict(fields)
    return by_full, by_short


@rule(
    "code/row-field-null", "code/row-field-null.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_row_fields_mapper,
)
def row_field_null(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A row field taken through a reference is `<тип>|Null` and cannot fill a typed field.

    The compiler is explicit: `новый Карточка(Номер = Строка.НомерАбонента)`, where the list
    field is `Абонент.Номер`, answers
    `Incompatible types: "Null" cannot be assigned to "Число"`. The description of the list
    itself compiles - the probe applied it cleanly - so the finding belongs to the assignment,
    and the fix is `.ЗаменитьNull(...)` on the field expression.
    """
    by_full, by_short = _row_catalog(facts)
    if not by_full:
        return
    structs: dict[str, dict[str, str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            structs.update(fact.get("structs") or {})
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        for row, field, struct, target, line, col in fact.get("assigns", ()):
            fields = by_full.get(row)
            if fields is None:
                fields = by_short.get(row)
            expr = (fields or {}).get(field)
            if not expr:
                continue  # the field is unknown here, or it cannot be Null
            declared = (structs.get(struct) or {}).get(target)
            if not declared:
                continue  # the structure or its field is unknown, or the field accepts Null
            yield Diagnostic(
                rel, line, col, "code/row-field-null", Severity.ERROR,
                i18n.t(
                    "code/row-field-null.assign",
                    field=field, expr=expr, type=declared, target=target, struct=struct,
                ),
            )
