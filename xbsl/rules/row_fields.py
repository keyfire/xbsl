"""Tier D: fields of a dynamic list's generated row type (code/unknown-row-field).

A form's dynamic list names its row type with `ИмяТипаДанныхСтроки`, and the fields of that
type are the list's `Поля` - the `Псевдоним` when there is one, otherwise the last segment of
the expression. The type itself the engine already knows (`semantics._row_type_names`), but
nobody checked the FIELDS: `Строка.КодИсполнитель` instead of `КодИсполнителя` passes the linter and
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

code/row-field-null judges the same Null in a row of a query literal as well: a column that
reads a field through a reference or from the joined side of an outer join, passed to a place
whose declared type refuses Null (see `_query_flows`). The row of the query is typed by
`typeinfer`, the origin of the Null by `querytypes.NullOrigin`.
"""

from __future__ import annotations

import dataclasses
import difflib
import re
from collections.abc import Iterable
from functools import cache, lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl import typeinfer as T
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._syntax import code_tokens
from xbsl.rules.redundant_checks import _local_names, _TextSource, display
from xbsl.rules.return_mismatch import _returns
from xbsl.rules.unknown_members import _common_member_forms, _walk_body, _walk_expr
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
    "code/row-field-null.query": {
        "ru": "Колонка '{column}' запроса читает '{expr}' через ссылку, поэтому её тип – "
              "'{type}|Null', а {target} имеет тип '{declared}': компилятор откажет "
              "('Null cannot be assigned'). Допишите '.ЗаменитьNull(...)' к выражению колонки.",
        "en": "Column '{column}' of the query reads '{expr}' through a reference, so its type is "
              "'{type}|Null', while {target} is of type '{declared}': the compiler refuses "
              "('Null cannot be assigned'). Append '.ЗаменитьNull(...)' to the column expression.",
    },
    "code/row-field-null.query-outer": {
        "ru": "Колонка '{column}' запроса читает '{expr}' из присоединённой таблицы внешнего "
              "соединения, поэтому её тип – '{type}|Null', а {target} имеет тип '{declared}': "
              "компилятор откажет ('Null cannot be assigned'). Допишите '.ЗаменитьNull(...)' к "
              "выражению колонки.",
        "en": "Column '{column}' of the query reads '{expr}' from the joined side of an outer "
              "join, so its type is '{type}|Null', while {target} is of type '{declared}': the "
              "compiler refuses ('Null cannot be assigned'). Append '.ЗаменитьNull(...)' to the "
              "column expression.",
    },
    "code/row-field-null.to-field": {
        "ru": "поле '{name}' структуры '{owner}'",
        "en": "field '{name}' of structure '{owner}'",
    },
    "code/row-field-null.to-member": {
        "ru": "поле '{name}'",
        "en": "field '{name}'",
    },
    "code/row-field-null.to-parameter": {
        "ru": "параметр '{name}' метода '{owner}'",
        "en": "parameter '{name}' of method '{owner}'",
    },
    "code/row-field-null.to-variable": {
        "ru": "переменная '{name}'",
        "en": "variable '{name}'",
    },
    "code/row-field-null.to-result": {
        "ru": "результат метода '{owner}'",
        "en": "the result of method '{owner}'",
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

    The catalog keeps members in Russian, and a translated module writes the same member in
    English - so each name is paired FORWARD through the dictionary. A member the dictionary
    does not pair keeps its Russian spelling alone; nothing here is invented.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, the rule still has _DATA_MEMBERS
        return frozenset()
    record = (catalog.get("type_members") or {}).get("СтрокаДинамическогоСписка") or {}
    own = frozenset(record.get("properties", ()) or ()) | frozenset(record.get("methods", ()) or ())
    english = (terms.common_english(name) for name in own)
    return own | frozenset(name for name in english if name)


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

    A field taken THROUGH A REFERENCE (`Исполнитель.Номер`) is typed `<тип>|Null`, and that costs:
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
            if (row is None or use.name in _DATA_MEMBERS
                    or use.name in _common_member_forms()
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


def _has_query_literal(source) -> bool:
    """Whether a module builds a query literal: such a module carries its text into the reduce,
    since the rows of a query are typed there and a row never leaves the method of its query."""
    return any(token.kind == "KEYWORD" and token.canonical == "QUERY" for token in code_tokens(source))


T.wants_text(_has_query_literal)


def _row_null_mapper(source: SourceFile) -> dict | None:
    """The map phase: the dynamic list facts (`_row_fields_mapper`) and the typing facts of the
    project (`typeinfer.project_fact`, shared with every rule that reads the typing)."""
    rows = _row_fields_mapper(source)
    typing = T.project_fact(source)
    if rows is None and typing is None:
        return None
    return {"rows": rows, "typing": typing}


@rule(
    "code/row-field-null", "code/row-field-null.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_row_null_mapper,
)
def row_field_null(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A row field taken through a reference is `<тип>|Null` and cannot fill a typed field.

    The compiler is explicit: `новый Карточка(Номер = Строка.НомерИсполнителя)`, where the list
    field is `Исполнитель.Номер`, answers
    `Incompatible types: "Null" cannot be assigned to "Число"`. The description of the list
    itself compiles - the probe applied it cleanly - so the finding belongs to the assignment,
    and the fix is `.ЗаменитьNull(...)` on the field expression. A row of a query literal is
    judged the same way (`_query_nulls`).
    """
    rows = {rel: fact["rows"] for rel, fact in facts.items() if fact.get("rows")}
    yield from _dynamic_list_nulls(rows)
    typing = {rel: fact["typing"] for rel, fact in facts.items() if fact.get("typing")}
    if typing:
        for rel, module in T.project_typings(typing).items():
            yield from _query_nulls(rel, module)


def _dynamic_list_nulls(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """The fields of a dynamic list row passed to a typed field of a structure."""
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


# --- the rows of a query literal ---------------------------------------------------------------

#: Element kinds whose own name is a structure type with declared fields.
_STRUCTURE_KINDS = frozenset({"Структура", "ХранимаяСтруктура"})
#: The facets of an element whose values carry its attributes.
_DATA_FACETS = frozenset({"Объект", "Данные", "Запись"})


def _query_nulls(rel: str, typing: T.ModuleTyping) -> Iterable[Diagnostic]:
    """A column of a query row that may hold Null, sent where the declared type refuses it.

    Every place was shown to the compiler, each answering
    `Incompatible types: type "Null" cannot be assigned to "Число"`: a named argument of a
    structure constructor, an argument of a method of the project, an assignment to a variable
    or a field declared with a type, such a declaration itself and the result of a method. The
    row reaches them through a loop over the result, a lambda of `Transform` and the like
    (the parameter typed by the signature of the platform method) or `ПервыйИлиНеопределено()`.
    A type that admits the empty value refuses Null all the same (`ДвоичныйОбъект.Ссылка?`), and
    only `Object` takes it. A computed column is not judged (see `querytypes.NullOrigin`).
    """
    queries = [token.start for token in typing.tokens
               if token.kind == "KEYWORD" and token.canonical == "QUERY"]
    if not queries:
        return
    typer = typing.typer
    typer._prepare(typing.tree)
    catalog = typing.catalog
    lines = None
    local: dict[str, str] = {}
    for method, this_type, owner_fields in typer._methods(typing.tree, True):
        start, end = int(method.start), int(method.end)
        if not any(start <= offset < end for offset in queries):
            continue  # a row never leaves the method of its query
        nodes = T.walk_nodes(getattr(method, "body", None))
        try:
            scope = T._MethodScope(method, nodes, callbacks=True)
        except RecursionError:
            continue
        evaluator = T._Evaluator(typer, scope, this_type, owner_fields)
        for value, target, place in _query_flows(method, nodes, scope, evaluator, typer):
            try:
                column = _null_column(evaluator, catalog, value)
            except RecursionError:
                continue
            if column is None or target is None or not _refuses_null(target):
                continue
            name, typed, origin = column
            if lines is None:
                lines = linemap(_TextSource(typing.text))
                local = _local_names(typing)
            kind, place_name, owner = place
            line, col = lines.linecol(int(value.start))
            key = ("code/row-field-null.query" if origin.kind == "reference"
                   else "code/row-field-null.query-outer")
            yield Diagnostic(
                rel, line, col, "code/row-field-null", Severity.ERROR,
                i18n.t(
                    key, column=name, expr=origin.path,
                    type=display(typed.without_null(), local),
                    target=i18n.t(f"code/row-field-null.to-{kind}", name=place_name, owner=owner),
                    declared=display(target, local),
                ),
            )


def _null_column(evaluator: T._Evaluator, catalog: T.ProjectCatalog,
                 value: object) -> tuple[str, T.TypeSet, object] | None:
    """(column, its type, the origin of its Null) of `<строка>.<Колонка>`, when the column is a
    plain path of a query row that may hold Null; None for any other value."""
    if not isinstance(value, P.Member):
        return None
    owner = evaluator.value(value.obj)
    if not isinstance(owner, T.TypeSet) or len(owner.names) != 1 or owner.null:
        return None
    origin = (catalog.row_nulls.get(next(iter(owner.names))) or {}).get(value.name)
    if origin is None:
        return None
    typed = evaluator.types(value)
    if typed is None or not typed.null:
        return None
    return value.name, typed, origin


def _refuses_null(target: T.TypeSet) -> bool:
    """Whether a declared type provably refuses Null: a type that names neither Null nor the
    root of the hierarchy (a parameter declared `Объект?` takes the column as it is)."""
    if target.null or not target.names:
        return False
    return not any(T.split_nominal(name)[0] in ("Null", "Объект") for name in target.names)


def _query_flows(method: P.Method, nodes: list, scope: T._MethodScope,
                 evaluator: T._Evaluator, typer: T.ModuleTyper):
    """(value, declared type of the place it goes to, (kind, name, owner)) of every place of the
    method that takes a value by a declared type: a named argument of a structure constructor,
    an assignment, a declaration with a type, an argument of a method of the project and the
    result of the method. Places whose type is not declared in the project are not listed."""
    catalog = typer.catalog
    written = typer.written
    for node in nodes:
        if isinstance(node, P.New) and node.args:
            struct = written(T._written_ref(node.type))
            if struct is None or len(struct.names) != 1 or struct.undefined:
                continue
            owner = next(iter(struct.names))
            if not _is_structure(catalog, owner):
                continue
            for argument in node.args:
                if argument.name and argument.value is not None:
                    yield (argument.value, catalog.member(owner, argument.name, False),
                           ("field", argument.name, node.type.text.strip()))
        elif isinstance(node, P.Assign) and node.op == "=" and node.value is not None:
            target = node.target
            if isinstance(target, P.Name):
                yield (node.value, _written_name(target, scope, evaluator, typer),
                       ("variable", target.name, ""))
            elif isinstance(target, P.Member):
                yield (node.value, _declared_member(target, evaluator, catalog),
                       ("member", target.name, ""))
        elif isinstance(node, P.VarDecl) and node.init is not None and node.type is not None:
            yield node.init, written(T._written_ref(node.type)), ("variable", node.name, "")
        elif isinstance(node, P.Call) and node.args:
            yield from _call_flows(node, scope, evaluator, typer)
    if method.return_type is not None:
        result = written(T._written_ref(method.return_type))
        found: list[P.Return] = []
        _returns(method.body or [], found)
        for statement in found:
            if statement.value is not None:
                yield statement.value, result, ("result", "", method.name)


def _is_structure(catalog: T.ProjectCatalog, owner: str) -> bool:
    """Whether a canonical type name is a structure of the project: of a module or an element."""
    first, dot, rest = owner.partition(".")
    if dot and rest in ((catalog.modules.get(first) or {}).get("structures") or {}):
        return True
    return (catalog.elements.get(owner) or {}).get("kind") in _STRUCTURE_KINDS


def _written_name(target: P.Name, scope: T._MethodScope, evaluator: T._Evaluator,
                  typer: T.ModuleTyper) -> T.TypeSet | None:
    """The declared type of a name assigned to: a local or a parameter with a written type, a
    field of the structure the method belongs to, a field of the module or a property of the
    paired yaml. A local typed by its initializer is not taken - its type is inferred."""
    entry = scope.lookup(target.name, int(target.start))
    if isinstance(entry, T._Declared):
        return typer.written(entry.payload) if entry.kind == "written" and entry.payload else None
    if entry is not T._MISSING:
        return None
    owner_fields = evaluator.owner_fields
    if owner_fields is not None and target.name in owner_fields:
        return typer.written(owner_fields[target.name])
    field = typer.fields.get(target.name)
    if field is not None:
        return typer.written(T._written_ref(getattr(field, "type", None)))
    own = typer.scope.own_properties.get(target.name)
    return typer.written(own) if own else None


def _declared_member(target: P.Member, evaluator: T._Evaluator,
                     catalog: T.ProjectCatalog) -> T.TypeSet | None:
    """The declared type of `<значение>.Поле` assigned to, when the project declares the field:
    a field of a structure or an attribute of an element's object, data or record."""
    owner = evaluator.value(target.obj)
    if not isinstance(owner, T.TypeSet) or len(owner.names) != 1 or owner.undefined or owner.null:
        return None
    name = next(iter(owner.names))
    element, dot, facet = name.partition(".")
    declared = _is_structure(catalog, name) or (
        bool(dot) and facet in _DATA_FACETS and element in catalog.elements)
    return catalog.member(name, target.name, False) if declared else None


def _call_flows(node: P.Call, scope: T._MethodScope, evaluator: T._Evaluator,
                typer: T.ModuleTyper):
    """The arguments of a call of a method a module of the project declares once: a bare call of
    the module's own method or `Модуль.Метод(...)`. A positional argument goes to the parameter
    of its index, a named one to the parameter of its name."""
    catalog = typer.catalog
    callee = node.callee
    module: str | None = None
    name = ""
    if isinstance(callee, P.Name):
        name = callee.name
        if scope.lookup(name, int(callee.start)) is not T._MISSING:
            return
        if evaluator.owner_fields is not None and name in evaluator.owner_fields:
            return
        if catalog.structure_method(evaluator.this_type, name)[0]:
            return  # a method of the structure itself
        module = typer.scope.module
    elif isinstance(callee, P.Member):
        owner = evaluator.value(callee.obj)
        if isinstance(owner, T.StaticName) and owner.name in catalog.modules:
            module = owner.name
        name = callee.name
    if not module:
        return
    params = catalog.method_params(module, name)
    if params is None:
        return
    named = False
    for index, argument in enumerate(node.args):
        if argument.value is None:
            continue
        if argument.name:
            named = True
            param = next((p for p in params if p[0] == argument.name), None)
        elif named or index >= len(params):
            continue
        else:
            param = params[index]
        if param is None or not param[1]:
            continue
        yield argument.value, catalog.written(param[1], module), ("parameter", param[0], name)
