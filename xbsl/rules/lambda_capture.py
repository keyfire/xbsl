"""Tier C: a lambda body changes a local variable of the code around it.

A lambda captures the values of the outer locals it uses at the moment it is created, and the
platform forbids changing such a variable inside the body (topics/lambda-expression, section
on capturing the context). The compiler refuses the project and the apply rolls the stand back,
while the parser has nothing to say: the assignment is well formed.

The rule binds the names of every method body to their declarations, block by block, and marks
each binding with the body that owns it - the method itself or a lambda at some depth. Reported
is an assignment (`=`, `+=`, `-=`, `*=`, `/=`) whose target is a bare name bound by an
enclosing body, in the short form (`() -> Счётчик += 1`) and the full one (`метод() -> ... ;`),
however deep in the blocks of the lambda, and a parenthesized name alike. Which bindings count
was settled by the language server of the platform IDE on probe projects written for this rule:

- captured and reported: a `пер` variable and a parameter of the method, and - for a lambda
  inside a lambda - a `пер` variable or a parameter of the outer lambda;
- not this rule's case: a `знч` or `исп` variable and the variable of a `для` loop or of
  `поймать` are read-only wherever they are assigned, and the compiler says so in a message of
  its own;
- a lambda parameter named like a local of the code around it is refused, and the name keeps
  meaning the outer variable - so an assignment to it inside the body is reported. A variable
  declared again inside the body (refused as well) takes the name over, and a loop of the body
  over an outer name declares a new variable rather than assigning the old one;
- left alone: a member or an element of a captured value (`Запись.Остаток = 1`,
  `Числа[0] = 5`) - the variable still holds the same object; a variable or a parameter of the
  lambda itself; a name bound only after the lambda is written; a name that is not a local at
  all - a field of the structure, a property of the element.

A change of a captured variable after the lambda, outside its body, is refused with a message of
its own and is not reported here.

A method the parser could not read in full is skipped, as every rule over the tree does: a
declaration lost to the error recovery would turn a variable of the lambda into a captured one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.return_mismatch import _methods

RULE = "code/lambda-changes-outer-local"

MESSAGES = {
    f"{RULE}.title": {
        "ru": "Лямбда меняет внешнюю локальную переменную",
        "en": "A lambda changes an outer local variable",
    },
    f"{RULE}.found": {
        "ru": "Лямбда меняет локальную переменную '{name}', объявленную за её пределами. "
              "Платформа такое изменение не компилирует: лямбда захватывает значение "
              "переменной, когда создаётся. Верните значение из лямбды или храните его в "
              "объекте, например в поле структуры или в элементе массива.",
        "en": "The lambda changes '{name}', a local variable declared outside it. The platform "
              "does not compile this: a lambda captures the value of the variable when it is "
              "created. Return the value from the lambda or keep it in an object, such as a "
              "structure field or an array element.",
    },
}
i18n.register(MESSAGES)

#: The bindings an assignment may change at all. The rest are read-only wherever they stand.
_ASSIGNABLE = frozenset({"PARAM", "VAR", "LAMBDA_PARAM"})


@dataclass
class _Binding:
    kind: str  # PARAM | VAR | VAL | USE | LOOP | CATCH | LAMBDA_PARAM
    owner: int  # the lambda depth the name was bound at: 0 is the method body itself


class _Walk:
    """Binds the names of one method body, block by block, and collects the assignments to
    names bound outside the lambda that assigns them."""

    def __init__(self) -> None:
        self.scopes: list[dict[str, _Binding]] = []
        self.depth = 0
        self.found: list[tuple[str, int]] = []  # (name, offset of the assigned name)

    def method(self, method: P.Method) -> list[tuple[str, int]]:
        self.scopes = [{}]
        self.depth = 0
        self.found = []
        for param in method.params:
            self._bind(param.name, "PARAM")
        self._statements(method.body)
        return self.found

    # --- names ------------------------------------------------------------------------

    def _bind(self, name: str, kind: str) -> None:
        if name:
            self.scopes[-1][name] = _Binding(kind, self.depth)

    def _resolve(self, name: str) -> _Binding | None:
        for scope in reversed(self.scopes):
            binding = scope.get(name)
            if binding is not None:
                return binding
        return None

    # --- statements -------------------------------------------------------------------

    def _block(self, stmts: list[P.Stmt]) -> None:
        self.scopes.append({})
        self._statements(stmts)
        self.scopes.pop()

    def _statements(self, stmts: list[P.Stmt]) -> None:
        for stmt in stmts:
            self._statement(stmt)

    def _statement(self, st: P.Stmt) -> None:
        if isinstance(st, P.VarDecl):
            self._expr(st.init)  # the variable is not bound inside its own initializer
            self._bind(st.name, st.kind)
        elif isinstance(st, P.Assign):
            self._assign(st)
        elif isinstance(st, (P.ExprStmt, P.UseStmt)):
            self._expr(st.expr)
        elif isinstance(st, P.Return):
            self._expr(st.value)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                self._expr(cond)
                self._block(body)
            if st.else_body is not None:
                self._block(st.else_body)
        elif isinstance(st, P.Case):
            self._expr(st.subject)
            for when in st.whens:
                for cond in when.conditions:
                    self._expr(cond)
                self._block(when.body)
            if st.else_body is not None:
                self._block(st.else_body)
        elif isinstance(st, P.While):
            self._expr(st.cond)
            self._block(st.body)
        elif isinstance(st, (P.ForEach, P.ForTo)):
            if isinstance(st, P.ForEach):
                self._expr(st.source)
            else:
                self._expr(st.start_expr)
                self._expr(st.to)
                self._expr(st.step)
            self.scopes.append({})
            self._bind(st.var, "LOOP")
            self._statements(st.body)
            self.scopes.pop()
        elif isinstance(st, P.Try):
            self._block(st.body)
            for var, _type, body in st.catches:
                self.scopes.append({})
                self._bind(var, "CATCH")
                self._statements(body)
                self.scopes.pop()
            if st.finally_body is not None:
                self._block(st.finally_body)
        elif isinstance(st, P.Scope):
            self._block(st.body)
        elif dataclasses.is_dataclass(st) and not isinstance(st, (P.Break, P.Continue)):
            # A statement the parser grows later: a lambda inside it is still walked.
            for f in dataclasses.fields(st):
                self._walk_value(getattr(st, f.name))

    def _assign(self, st: P.Assign) -> None:
        if isinstance(st.target, P.Name):
            binding = self._resolve(st.target.name)
            if binding is not None and binding.owner < self.depth and binding.kind in _ASSIGNABLE:
                self.found.append((st.target.name, st.target.start))
        else:
            self._expr(st.target)  # `Х.Поле = ...`, `Х[0] = ...` change the object, not Х
        self._expr(st.value)

    # --- expressions ------------------------------------------------------------------

    def _lambda(self, e: P.Lambda) -> None:
        self.depth += 1
        self.scopes.append({})
        for param in e.params:
            # A parameter named like a name already bound is refused, and the name goes on
            # meaning the outer binding inside the body.
            if self._resolve(param.name) is None:
                self._bind(param.name, "LAMBDA_PARAM")
        if isinstance(e.body_expr, P.Assign):
            self._assign(e.body_expr)
        else:
            self._expr(e.body_expr)
        if e.body_stmts is not None:
            self._statements(e.body_stmts)
        self.scopes.pop()
        self.depth -= 1

    def _expr(self, e: P.Expr | None) -> None:
        if e is None:
            return
        if isinstance(e, P.Lambda):
            self._lambda(e)
            return
        if isinstance(e, (P.Name, P.Literal, P.This, P.GlobalAccess, P.MethodRef)):
            return
        for f in dataclasses.fields(e):
            self._walk_value(getattr(e, f.name))

    def _walk_value(self, value: object) -> None:
        if isinstance(value, P.Expr):
            self._expr(value)
        elif isinstance(value, P.Stmt):
            self._statement(value)
        elif isinstance(value, P.CallArg):
            self._expr(value.value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._walk_value(item)


@rule(RULE, f"{RULE}.title", "C", severity=Severity.ERROR)
def lambda_changes_outer_local(source: SourceFile) -> Iterable[Diagnostic]:
    """An assignment inside a lambda body to a local the lambda captured - see the module."""
    if source.kind != "xbsl" or is_query_file(source.path) or "->" not in source.text:
        return []
    module, errors = parse(source)
    walk = _Walk()
    lm = None
    out: list[Diagnostic] = []
    for method in _methods(module):
        if method.is_abstract:
            continue
        if any(method.start <= err.start <= method.end for err in errors):
            continue
        for name, at in walk.method(method):
            lm = lm or linemap(source)
            line, col = lm.linecol(at)
            out.append(Diagnostic(
                source.rel, line, col, RULE, Severity.ERROR,
                i18n.t(f"{RULE}.found", name=name),
            ))
    return out
