"""Tier D: operations whose outcome the types of the code already decide.

The platform's own editor warns about two such operations, and until now the linter named
neither - both are questions about the SET of types an expression holds, which the engine did
not keep (see `_typesets.py`).

**`code/redundant-undefined-guard`** - `А ?? Б`, `Х!` and `Х?.Член` over a value whose type has
no empty value: the default of `??` is never used, the insistent operation asserts what the type
already guarantees, the safe access guards against nothing. The editor warns about such a guard
when the set of types of the operand is known and has no `Undefined` in it - for all three
operations alike - and so does the rule. On a live project the editor points at three such places,
and all three are typed by readings the engine lacked: the value of a component its markup
declares `ПолеВвода<Число>`, the new value of an event parameter declared
`СобытиеПриИзменении<Строка>`.

The fix removes `?? Б` and `!`, and only when nothing else moves: the text left behind must parse
into the same tree with the operand in place of the operation, and for `??` the default must not
widen the type of the whole (`Строка ?? 0` is a string or a number, and a variable declared by it
would change its type). The safe access keeps no fix: `Х?.Член` is nullable and `Х.Член` is not,
so a declaration initialized by it would change its type.

**`code/redundant-type-check`** - `Х это Тип` whose result the type of `Х` decides: every type of
the set fits the checked list, so the check passes whatever the value is, and `это не` never does.
The editor judges that by whether the checked types can hold every value of the expression; the
rule reads it as inclusion of names widened by the bases the catalog states (a string fits the
object type). A generic base is not followed, since the data does not say which argument it
takes - silence, never a false finding. The one place on a live project is a column of a query
row, and a column is typed by the fields the project's yaml declares - which is why this rule
runs over the whole project: a module alone cannot tell the type of `Запись.Цена`.

Both rules judge the methods of the module itself; a structure's methods reach its fields by a
bare name the module facts do not describe, and they are skipped.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator

from xbsl import i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.rules._querytypes import column_shapes, resolve
from xbsl.rules._typesets import (
    Declaration,
    MethodScope,
    TypeSet,
    holds,
    module_facts,
    module_methods,
    parse_type,
    split_generic,
    walk_nodes,
)

GUARD = "code/redundant-undefined-guard"
CHECK = "code/redundant-type-check"

MESSAGES = {
    f"{GUARD}.title": {
        "ru": "Защита от Неопределено у значения, которое им не бывает",
        "en": "A guard against Undefined on a value that never is",
    },
    f"{GUARD}.coalesce": {
        "ru": "Значение слева от '??' не бывает '{n[Неопределено]}': его тип '{type}', поэтому "
              "значение по умолчанию справа никогда не используется – '?? ...' можно убрать.",
        "en": "The value left of '??' is never '{n[Неопределено]}': its type is '{type}', so "
              "the default on the right is never used - the '?? ...' can go.",
    },
    f"{GUARD}.insist": {
        "ru": "Значение перед '!' не бывает '{n[Неопределено]}': его тип '{type}' – "
              "настойчивая операция ничего не проверяет, '!' можно убрать.",
        "en": "The value before '!' is never '{n[Неопределено]}': its type is '{type}' - "
              "the insistent operation checks nothing, the '!' can go.",
    },
    f"{GUARD}.safe": {
        "ru": "Значение перед '?.' не бывает '{n[Неопределено]}': его тип '{type}' – "
              "безопасный доступ ни от чего не защищает, достаточно '.'.",
        "en": "The value before '?.' is never '{n[Неопределено]}': its type is '{type}' - "
              "the safe access guards against nothing, a plain '.' will do.",
    },
    f"{CHECK}.title": {
        "ru": "Проверка типа, результат которой известен заранее",
        "en": "A type check whose result is known in advance",
    },
    f"{CHECK}.true": {
        "ru": "Результат '{n[это]} {check}' известен заранее: значение типа '{type}' проходит "
              "такую проверку всегда, и условие ничего не проверяет.",
        "en": "The result of '{n[это]} {check}' is known in advance: a value of type '{type}' "
              "always passes it, so the condition checks nothing.",
    },
    f"{CHECK}.false": {
        "ru": "Результат '{n[это]} {n[не]} {check}' известен заранее: значение типа '{type}' "
              "всегда подходит под '{check}', и условие не выполняется никогда.",
        "en": "The result of '{n[это]} {n[не]} {check}' is known in advance: a value of type "
              "'{type}' always fits '{check}', so the condition never holds.",
    },
}
i18n.register(MESSAGES)


def display(types: TypeSet) -> str:
    """A set as the reader's language writes it: the names through the platform dictionary."""
    names = sorted(_display_name(name) for name in types.names)
    if not types.undefined:
        return "|".join(names)
    return f"{names[0]}?" if len(names) == 1 else "|".join([*names, "?"])


def _display_name(name: str) -> str:
    split = split_generic(name)
    if split is None:
        return name
    head, args = split
    shown = i18n.name(head, "types") if "." not in head else i18n.name(head)
    if not args:
        return shown
    return f"{shown}<{', '.join(display(arg) for arg in args)}>"


# --- code/redundant-undefined-guard ---------------------------------------------------------


def _guarded(node: P.Node) -> tuple[P.Expr, str] | None:
    """(the operand, the kind of guard) of a node that guards against the empty value."""
    if isinstance(node, P.Coalesce) and node.right is not None:
        return node.left, "coalesce"
    if isinstance(node, P.NonNull):
        return node.operand, "insist"
    if isinstance(node, P.Member) and node.safe:
        return node.obj, "safe"
    return None


#: A guard in the text: `??`, `?.` or a `!` that is not the start of `!=`.
_GUARD_TEXT_RE = re.compile(r"\?\?|\?\.|!(?!=)")


@rule(GUARD, f"{GUARD}.title", "D", severity=Severity.WARNING)
def redundant_undefined_guard(source: SourceFile) -> Iterable[Diagnostic]:
    """`??`, `!` and `?.` over a value whose type has no empty value."""
    if source.kind != "xbsl" or not _GUARD_TEXT_RE.search(source.text):
        return
    parsed = module_facts(source)
    if parsed is None:
        return
    module, facts = parsed
    lm = linemap(source)
    for method in module_methods(module):
        if not _mentions(source.text, method, ("??", "?.", "!"), _GUARD_TEXT_RE):
            continue
        nodes = walk_nodes(method.body)
        guards = [(node, found) for node in nodes if (found := _guarded(node)) is not None]
        if not guards:
            continue
        scope = MethodScope(method, facts, nodes)
        for node, (operand, kind) in guards:
            types = scope.evaluator.types(operand)
            if types is None or not types.names or types.undefined:
                continue
            line, col = lm.linecol(int(operand.start))
            fix = None
            if kind == "coalesce":
                fix = _coalesce_fix(source, module, node, types, scope)
            elif kind == "insist":
                fix = _insist_fix(source, module, node)
            yield Diagnostic(
                source.rel, line, col, GUARD, Severity.WARNING,
                i18n.t(f"{GUARD}.{kind}", type=display(types)), fix=fix,
            )


def _mentions(text: str, method: P.Method, words: tuple[str, ...], pattern: re.Pattern) -> bool:
    """Whether the text of a method may hold the operation at all: a plain substring first, the
    pattern only then - most methods of a module have none, and the pattern is the slower test."""
    start, end = int(method.start), int(method.end)
    if not any(text.find(word, start, end) >= 0 for word in words):
        return False
    return pattern.search(text, start, end) is not None


def _significant(source: SourceFile) -> list:
    return [token for token in tokens(source) if token.kind not in ("COMMENT", "BOM", "EOF")]


def _coalesce_fix(source: SourceFile, module: P.Module, node: P.Coalesce, left: TypeSet,
                  scope: MethodScope) -> TextEdit | None:
    """Remove `?? Б` when the default cannot widen the type and the tree stays the same."""
    right = scope.evaluator.types(node.right)
    if right is None or right.undefined or not right.names <= left.names:
        return None
    toks = _significant(source)
    operator = next((i for i, t in enumerate(toks)
                     if t.kind == "OP" and t.value == "??" and int(node.left.end) <= t.start
                     and t.start < int(node.right.start)), None)
    if operator is None or operator == 0:
        return None
    start = toks[operator - 1].end
    opened = sum(1 for t in toks[operator + 1:] if t.start < int(node.right.start)
                 and t.kind == "OP" and t.value == "(")
    end = int(node.right.end)
    after = [t for t in toks if t.start >= end]
    for token in after[:opened]:
        if not (token.kind == "OP" and token.value == ")"):
            return None
        end = token.end
    return _verified(source, module, node, node.left, start, end)


def _insist_fix(source: SourceFile, module: P.Module, node: P.NonNull) -> TextEdit | None:
    """Remove the `!` when the tree stays the same without it."""
    toks = _significant(source)
    bang = next((t for t in toks if t.kind == "OP" and t.value == "!"
                 and int(node.operand.end) <= t.start < int(node.end)), None)
    if bang is None:
        return None
    return _verified(source, module, node, node.operand, bang.start, bang.end)


def _verified(source: SourceFile, module: P.Module, node: P.Node, operand: P.Node,
              start: int, end: int) -> TextEdit | None:
    """The edit, when the text without [start, end) parses into the tree with `operand` for `node`.

    A removed range must hold no comment: the edit would take it along.
    """
    if any(token.kind == "COMMENT" and start <= token.start < end for token in tokens(source)):
        return None
    edited, errors = P.parse_text(source.text[:start] + source.text[end:])
    if errors:
        return None
    if _shape(edited) != _shape(module, replace=(node, operand)):
        return None
    return TextEdit(start, end, "")


def _shape(node: object, replace: tuple[object, object] | None = None) -> object:
    """A node tree without offsets, `replace` = (node, the node standing in for it)."""
    if replace is not None and node is replace[0]:
        node = replace[1]
    if isinstance(node, (list, tuple)):
        return tuple(_shape(item, replace) for item in node)
    if not isinstance(node, P.Node):
        return node
    return (type(node).__name__, tuple(
        _shape(getattr(node, f.name), replace)
        for f in dataclasses.fields(node) if f.name not in ("start", "end")
    ))


# --- code/redundant-type-check ------------------------------------------------------------------


_CHECK_TEXT_RE = re.compile(r"(?<![\w.])(?:это|is)(?!\w)")


def _always(types: TypeSet, check: TypeSet) -> bool:
    """Whether every value of `types` fits the check: each type is held by a checked one, and
    the empty value is checked for when the expression may hold it."""
    if not types.names:
        return False
    if types.undefined and not check.undefined:
        return False
    return all(any(holds(wanted, name) for wanted in check.names) for name in types.names)


def _checks(nodes: list[P.Node]) -> Iterator[tuple[P.IsType, P.Expr]]:
    """(the check, its operand) of every `это` among the nodes of a method, the predicate form of
    `выбор` too."""
    for node in nodes:
        if isinstance(node, P.IsType):
            operand = node.operand
            if isinstance(operand, P.Name) and not operand.name:
                continue  # the predicate form: its operand is the subject of `выбор`, below
            yield node, operand
        elif isinstance(node, P.Case) and node.subject is not None:
            for when in node.whens:
                for condition in when.conditions:
                    if (isinstance(condition, P.IsType) and isinstance(condition.operand, P.Name)
                            and not condition.operand.name):
                        yield condition, node.subject


def _object_fact(source: SourceFile) -> dict | None:
    """The typed fields and tabular sections a project object declares."""
    from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

    if not _HAVE_YAML:
        return None
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    if not kind:
        return None
    name = value_of(data, "Имя", kind)
    if not isinstance(name, str) or not name:
        return None
    name_keys = tuple(terms.key_forms("Имя"))
    type_keys = tuple(terms.key_forms("Тип"))

    def typed(items: object) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in items if isinstance(items, list) else ():
            if not isinstance(item, dict):
                continue
            field = next((item[k] for k in name_keys if isinstance(item.get(k), str)), None)
            written = next((item[k] for k in type_keys if isinstance(item.get(k), str)), None)
            if field and written:
                out[field.casefold()] = written
        return out

    fields = typed(value_of(data, "Реквизиты", kind))
    tables: dict[str, dict[str, str]] = {}
    sections = value_of(data, "ТабличныеЧасти", kind)
    for item in sections if isinstance(sections, list) else ():
        if not isinstance(item, dict):
            continue
        section = next((item[k] for k in name_keys if isinstance(item.get(k), str)), None)
        if section:
            tables[section.casefold()] = typed(value_of(item, "Реквизиты"))
    if not fields and not tables:
        return None
    return {"k": "y", "name": name.casefold(), "fields": fields, "tables": tables}


def _type_check_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml gives its typed fields, a module its checks.

    A check whose operand the module types itself is decided here; one over a column of a
    query row is described (the shapes of the column) and decided in the reduce, with the fields.
    """
    if source.kind == "yaml":
        return _object_fact(source)
    if source.kind != "xbsl" or not _CHECK_TEXT_RE.search(source.text):
        return None
    parsed = module_facts(source)
    if parsed is None:
        return None
    module, facts = parsed
    lm = linemap(source)
    decided: list = []
    pending: list = []
    for method in module_methods(module):
        if not _mentions(source.text, method, ("это", "is"), _CHECK_TEXT_RE):
            continue
        nodes = walk_nodes(method.body)
        checks = list(_checks(nodes))
        if not checks:
            continue
        scope = MethodScope(method, facts, nodes)
        for node, operand in checks:
            check = parse_type(getattr(node.type, "text", None))
            if check is None:
                continue
            line, col = lm.linecol(int(node.start))
            types = scope.evaluator.types(operand)
            if types is not None:
                if _always(types, check):
                    decided.append([line, col, bool(node.negated), types.key(), check.key()])
                continue
            if not (isinstance(operand, P.Member) and not operand.safe
                    and isinstance(operand.obj, P.Name)):
                continue
            entry = scope.lookup(operand.obj.name, int(operand.obj.start))
            if not isinstance(entry, Declaration) or entry.row is None:
                continue
            shapes = column_shapes(source, (entry.row.start, entry.row.end), operand.name)
            if shapes:
                pending.append([line, col, bool(node.negated), check.key(), shapes])
    if not decided and not pending:
        return None
    return {"k": "x", "decided": decided, "pending": pending}


@rule(CHECK, f"{CHECK}.title", "D", scope="project", severity=Severity.WARNING,
      mapper=_type_check_mapper)
def redundant_type_check(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`Х это Тип` whose result the type of `Х` already decides."""
    objects: dict[str, dict | None] = {}
    for fact in facts.values():
        if fact.get("k") != "y":
            continue
        name = fact["name"]
        # A name two objects share is ambiguous for a query: neither answers.
        objects[name] = None if name in objects else fact

    def fields_of(table: str) -> dict[str, str] | None:
        head, dot, section = table.partition(".")
        record = objects.get(head.casefold())
        if record is None:
            return None
        if not dot:
            return record["fields"]
        return record["tables"].get(section.casefold())

    for rel, fact in sorted(facts.items()):
        if fact.get("k") != "x":
            continue
        # The sets travel as their keys and are shown here, in the language of the run: a worker
        # process of a parallel run has no say in the language of the message.
        for line, col, negated, types_key, check_key in fact["decided"]:
            types, check = parse_type(types_key), parse_type(check_key)
            if types is not None and check is not None:
                yield _check_diagnostic(rel, line, col, negated, display(types), display(check))
        for line, col, negated, check_key, shapes in fact["pending"]:
            check = parse_type(check_key)
            types = resolve(shapes, fields_of)
            if check is None or types is None or not _always(types, check):
                continue
            yield _check_diagnostic(rel, line, col, negated, display(types), display(check))


def _check_diagnostic(rel: str, line: int, col: int, negated: bool, shown: str,
                      check: str) -> Diagnostic:
    variant = "false" if negated else "true"
    return Diagnostic(rel, line, col, CHECK, Severity.WARNING,
                      i18n.t(f"{CHECK}.{variant}", type=shown, check=check))
