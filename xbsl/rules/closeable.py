"""Tier D: a closeable resource left unclosed by an early exit from the loop over it.

`знч Выборка = Запрос{ ... }.Выполнить()` binds a descendant of `Закрываемое` to an ordinary
variable. Walking such a result to the END closes it - the platform releases the resource once
the iteration is over - but a `возврат` or a `прервать` in the middle of the loop leaves it
open, and the platform records `СобытиеНезакрытыйРесурс` in the event log. Nothing fails at
that moment, which is why the leak survives review: it is visible only in the log of a running
application.

The cure is the `исп` modifier: "метод Закрыть() будет вызван автоматически в тот момент, когда
переменная выходит из области видимости" (topics/closeable-type), so the resource is released
on every exit path, the early ones included.

Zero false positives are bought by narrowing, not by guessing:

- the type is taken from the catalog, not from the name - a finding needs the initializer to
  resolve to a descendant of `Закрываемое` through the chain (a query literal, a constructor
  or member returns); anything the chain cannot type is left alone;
- the loop is joined to the NEAREST PRECEDING declaration of that name INSIDE THE SAME method.
  Keyed by name alone, a `Результат` declared in a dozen methods reports whichever declaration
  happened to be last in the file;
- only a variable this method DECLARES counts: a resource that arrived as a parameter belongs
  to the caller, and the docs put its lifetime there;
- `прервать` is credited to the loop it actually leaves, so the one inside a nested loop is
  not read as an exit from ours, while `продолжить` is no exit at all;
- a `возврат` inside a lambda returns from the lambda. Lambdas live in expressions and this
  walk never descends into expressions, so such a `возврат` cannot be seen in the first place;
- a method that calls `Закрыть()` on the variable itself, or that returns the resource to its
  caller (the ownership transfer the docs describe), manages the lifetime by hand and is
  left alone.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/unclosed-resource.title": {
        "ru": "Незакрытый ресурс при досрочном выходе из перебора",
        "en": "Resource left unclosed by an early exit from the loop",
    },
    "code/unclosed-resource.early-exit": {
        "ru": "'{name}' ({type}) – закрываемый ресурс, а '{exit}' в строке {line} выходит из "
              "перебора досрочно: полный проход платформа закрывает сама, досрочный – нет, и в "
              "журнал событий попадает СобытиеНезакрытыйРесурс. Объявить ресурс через "
              "'{n[исп]}' – тогда он закрывается на любом пути выхода.",
        "en": "'{name}' ({type}) is a closeable resource and '{exit}' on line {line} leaves the "
              "loop early: the platform closes a full pass by itself, an early exit it does "
              "not, and the event log gets an unclosed-resource event. Declare the resource "
              "with '{n[исп]}' – then it is closed on every exit path.",
    },
}
i18n.register(MESSAGES)

#: The root of the closeable hierarchy, in both name forms.
_CLOSEABLE_ROOTS = frozenset({"Закрываемое", "Closeable"})
#: The contract method of that hierarchy - an explicit call means a hand-managed lifetime.
_CLOSE_METHODS = frozenset({"Закрыть", "Close"})
#: A query literal constructs a typed query (docs topics/query-literal), whatever it is spelled in.
_QUERY_TYPE = "ТипизированныйЗапрос"
#: The exit keyword to name in the message, by the statement that performs it.
_EXIT_WORD = {P.Return: "возврат", P.Break: "прервать"}


@lru_cache(maxsize=1)
def _catalog() -> tuple[frozenset[str], dict]:
    """(closeable type names, type -> member -> the member's own type).

    A closeable is a type that INHERITS `Закрываемое` - the catalog carries the whole ancestor
    chain of every documented type, so this is the platform's own answer rather than a list
    maintained here by hand. Both name forms are in the catalog, so a project written in
    English answers the same.
    """
    try:
        data = dataset.load_json("stdlib.json")
    except Exception:  # noqa: BLE001 - no data, no rule
        data = {}
    bases = data.get("bases") or {}
    closeable = frozenset(
        name for name, chain in bases.items() if chain and _CLOSEABLE_ROOTS & set(chain)
    )
    return closeable, data.get("member_types") or {}


dataset.register_reset(_catalog.cache_clear)


def _chain_type(expr: P.Expr | None, scope: dict[str, str], returns: dict) -> str | None:
    """The type of a call chain `Корень.Метод(...).Метод2(...)`, or None when unknown.

    The root is a query literal, a constructor or a name already typed in this method; every
    further link is resolved through the member catalog. An unresolved link ends the inference
    - a guess here would cost a false positive.
    """
    links: list[str] = []
    node: object = expr
    while True:
        if isinstance(node, P.Call):
            node = node.callee
            continue
        if isinstance(node, P.Member):
            links.append(node.name)
            node = node.obj
            continue
        break

    if isinstance(node, P.Literal) and node.kind == "QUERY":
        current: str | None = _QUERY_TYPE
    elif isinstance(node, P.New):
        current = node.type.names[0] if node.type and node.type.names else None
    elif isinstance(node, P.Name):
        current = scope.get(node.name)
    else:
        return None

    for link in reversed(links):
        if current is None:
            return None
        raw = returns.get(current, {}).get(link)
        current = dataset.member_type_head(raw) if raw else None
    return current


def _child_bodies(st: P.Stmt) -> list[list[P.Stmt]]:
    """The statement lists a statement owns - the walk stays inside statements on purpose.

    Expressions are never entered, so a lambda body (which is an expression's child) is out of
    reach: its `возврат` returns from the lambda, not from the method, and reading it as an
    early exit would be a false positive.
    """
    if isinstance(st, P.If):
        bodies = [body for _cond, body in st.branches]
        if st.else_body is not None:
            bodies.append(st.else_body)
        return bodies
    if isinstance(st, P.Case):
        bodies = [when.body for when in st.whens]
        if st.else_body is not None:
            bodies.append(st.else_body)
        return bodies
    if isinstance(st, P.Try):
        bodies = [st.body] + [body for _var, _type, body in st.catches]
        if st.finally_body is not None:
            bodies.append(st.finally_body)
        return bodies
    if isinstance(st, (P.While, P.ForEach, P.ForTo, P.Scope)):
        return [st.body]
    return []


def _closed_by_hand(method: P.Method) -> set[str]:
    """Names on which the method calls `Закрыть()` itself - it manages the lifetime by hand."""
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
            return
        if not isinstance(node, P.Node):
            return
        if (
            isinstance(node, P.Member)
            and node.name in _CLOSE_METHODS
            and isinstance(node.obj, P.Name)
        ):
            names.add(node.obj.name)
        for f in dataclasses.fields(node):
            walk(getattr(node, f.name, None))

    walk(method.body)
    return names


def _early_exit(body: list[P.Stmt], resource: str) -> P.Stmt | None:
    """The first statement that leaves the loop before the pass is over, or None.

    `возврат` leaves the method from any depth; `прервать` leaves only the innermost loop, so
    the one written inside a nested loop says nothing about ours. Returning the resource itself
    hands it to the caller - the exception the docs spell out - and is not counted.
    """
    found: P.Stmt | None = None

    def walk(stmts: list[P.Stmt], in_nested_loop: bool) -> None:
        nonlocal found
        for st in stmts:
            if found is not None:
                return
            if isinstance(st, P.Return):
                if isinstance(st.value, P.Name) and st.value.name == resource:
                    continue  # the caller takes over the resource and its closing
                found = st
                return
            if isinstance(st, P.Break) and not in_nested_loop:
                found = st
                return
            nested = in_nested_loop or isinstance(st, (P.While, P.ForEach, P.ForTo))
            for child in _child_bodies(st):
                walk(child, nested)
                if found is not None:
                    return

    walk(body, False)
    return found


def _method_findings(
    method: P.Method, closeable: frozenset[str], returns: dict,
) -> list[tuple[P.VarDecl, str, str, P.Stmt]]:
    """(declaration, name, type, exit statement) for every leaking loop of one method."""
    scope: dict[str, str] = {}  # name -> the type inferred so far
    owned: dict[str, P.VarDecl] = {}  # closeables this method holds outside `исп`
    hand_closed = _closed_by_hand(method)
    findings: list[tuple[P.VarDecl, str, str, P.Stmt]] = []

    def walk(stmts: list[P.Stmt]) -> None:
        for st in stmts:
            if isinstance(st, P.VarDecl):
                if st.type is not None and st.type.names:
                    inferred: str | None = st.type.names[0]
                else:
                    inferred = _chain_type(st.init, scope, returns)
                if inferred:
                    scope[st.name] = inferred
                else:
                    scope.pop(st.name, None)
                # A redeclaration replaces what the name meant: the loop below binds to the
                # nearest preceding declaration, which is exactly this one.
                if inferred in closeable and st.kind != "USE":
                    owned[st.name] = st
                else:
                    owned.pop(st.name, None)
                continue
            if (
                isinstance(st, P.ForEach)
                and isinstance(st.source, P.Name)
                and st.source.name in owned
                and st.source.name not in hand_closed
            ):
                exit_stmt = _early_exit(st.body, st.source.name)
                if exit_stmt is not None:
                    findings.append((
                        owned[st.source.name], st.source.name, scope[st.source.name], exit_stmt,
                    ))
            for child in _child_bodies(st):
                walk(child)

    walk(method.body)
    return findings


def _methods(module: P.Module) -> Iterable[P.Method]:
    """Every method of the module, those of structures and enumerations included."""
    for member in module.members:
        if isinstance(member, P.Method):
            yield member
        elif isinstance(member, P.Structure):
            for sub in member.members:
                if isinstance(sub, P.Method):
                    yield sub
        elif isinstance(member, P.Enum):
            yield from member.methods


@rule("code/unclosed-resource", "code/unclosed-resource.title", "D", severity=Severity.WARNING)
def unclosed_resource(source: SourceFile) -> Iterable[Diagnostic]:
    """A closeable held outside `исп` and abandoned by an early exit from the loop over it."""
    if source.kind != "xbsl":
        return
    closeable, returns = _catalog()
    if not closeable:
        return  # without the stdlib catalog a closeable cannot be told from anything else
    module, errors = parse(source)
    if errors:
        return
    lm = None
    for method in _methods(module):
        for decl, name, type_name, exit_stmt in _method_findings(method, closeable, returns):
            if lm is None:
                lm = linemap(source)
            line, col = lm.linecol(decl.start)
            exit_line, _exit_col = lm.linecol(exit_stmt.start)
            yield Diagnostic(
                source.rel, line, col, "code/unclosed-resource", Severity.WARNING,
                i18n.t(
                    "code/unclosed-resource.early-exit",
                    name=name,
                    type=i18n.name(type_name, "types"),
                    exit=i18n.name(_EXIT_WORD.get(type(exit_stmt), "возврат")),
                    line=exit_line,
                ),
            )
