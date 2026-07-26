"""Tier C: an expression statement must have an effect (a call, a creation, a throw).

An expression used as a statement computes a value and drops it - legal syntax, so a
keyword typo parses fine and silently does nothing: `возрат 5` becomes two harmless
expression statements (a name and a number), `Х == 5` written instead of `Х = 5` is a
dropped comparison. The rule flags an expression statement whose subtree contains no
Call, New or Throw.

Conservative corners (kept effectful so the rule stays at zero false positives):
- a lambda is NOT entered when judging the statement that drops it (its body does not
  run), but lambda bodies are walked for their own statements;
- a rich string with interpolation may call methods inside `%{...}`/`${...}` - the
  lexer keeps it one opaque token, so it counts as an effect;
- `Запрос{...}` and resolvable literals (`Ресурс{...}`) are opaque - count as an effect.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/statement-no-effect.title": {
        "ru": "Оператор-выражение без эффекта",
        "en": "Expression statement with no effect",
    },
    "code/statement-no-effect.found": {
        "ru": "Оператор-выражение не имеет эффекта: значение вычисляется и отбрасывается "
              "(возможно, опечатка)",
        "en": "The expression statement has no effect: the value is computed and dropped "
              "(possibly a typo)",
    },
}
i18n.register(MESSAGES)

_OPAQUE_LITERALS = ("QUERY", "RESOLVABLE")


def _has_effect(expr: P.Expr | None) -> bool:
    if expr is None:
        return False
    if isinstance(expr, (P.Call, P.New, P.Throw)):
        return True
    if isinstance(expr, P.Literal):
        if expr.kind in _OPAQUE_LITERALS:
            return True
        return expr.kind == "STRING" and ("%{" in expr.text or "${" in expr.text)
    if isinstance(expr, P.Lambda):
        return False  # the body does not run when the lambda value is dropped
    if isinstance(expr, P.Unary):
        return _has_effect(expr.operand)
    if isinstance(expr, P.Binary):
        return _has_effect(expr.left) or _has_effect(expr.right)
    if isinstance(expr, P.Compare):
        return _has_effect(expr.first) or any(_has_effect(r) for _op, r in expr.rest)
    if isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        return _has_effect(expr.operand)
    if isinstance(expr, P.Ternary):
        return _has_effect(expr.cond) or _has_effect(expr.then) or _has_effect(expr.otherwise)
    if isinstance(expr, P.Coalesce):
        return _has_effect(expr.left) or _has_effect(expr.right)
    if isinstance(expr, P.Member):
        return _has_effect(expr.obj)
    if isinstance(expr, P.Index):
        return _has_effect(expr.obj) or _has_effect(expr.index)
    if isinstance(expr, P.ArrayLit):
        return any(_has_effect(item) for item in expr.items)
    if isinstance(expr, P.MapLit):
        return any(_has_effect(k) or _has_effect(v) for k, v in expr.entries)
    return False  # Name, This, GlobalAccess, MethodRef, plain literals


def _visit_expr(expr: P.Expr | None, out: list[P.ExprStmt]) -> None:
    """Collect no-effect statements from lambda bodies nested in an expression."""
    if expr is None:
        return
    if isinstance(expr, P.Lambda):
        if isinstance(expr.body_expr, P.Expr):
            _visit_expr(expr.body_expr, out)
        elif isinstance(expr.body_expr, P.Assign):
            _visit_expr(expr.body_expr.target, out)
            _visit_expr(expr.body_expr.value, out)
        if expr.body_stmts is not None:
            _walk_body(expr.body_stmts, out)
        return
    if isinstance(expr, P.Unary):
        _visit_expr(expr.operand, out)
    elif isinstance(expr, P.Binary):
        _visit_expr(expr.left, out)
        _visit_expr(expr.right, out)
    elif isinstance(expr, P.Compare):
        _visit_expr(expr.first, out)
        for _op, right in expr.rest:
            _visit_expr(right, out)
    elif isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        _visit_expr(expr.operand, out)
    elif isinstance(expr, P.Ternary):
        _visit_expr(expr.cond, out)
        _visit_expr(expr.then, out)
        _visit_expr(expr.otherwise, out)
    elif isinstance(expr, P.Coalesce):
        _visit_expr(expr.left, out)
        _visit_expr(expr.right, out)
    elif isinstance(expr, P.Member):
        _visit_expr(expr.obj, out)
    elif isinstance(expr, P.Index):
        _visit_expr(expr.obj, out)
        _visit_expr(expr.index, out)
    elif isinstance(expr, P.Call):
        _visit_expr(expr.callee, out)
        for arg in expr.args:
            _visit_expr(arg.value, out)
    elif isinstance(expr, P.New):
        if expr.args:
            for arg in expr.args:
                _visit_expr(arg.value, out)
    elif isinstance(expr, P.ArrayLit):
        for item in expr.items:
            _visit_expr(item, out)
    elif isinstance(expr, P.MapLit):
        for k, v in expr.entries:
            _visit_expr(k, out)
            _visit_expr(v, out)
    elif isinstance(expr, P.Throw):
        _visit_expr(expr.value, out)


def _walk_body(stmts: list[P.Stmt], out: list[P.ExprStmt]) -> None:
    for st in stmts:
        if isinstance(st, P.ExprStmt):
            if not _has_effect(st.expr):
                out.append(st)
            _visit_expr(st.expr, out)
        elif isinstance(st, P.VarDecl):
            _visit_expr(st.init, out)
        elif isinstance(st, P.Assign):
            _visit_expr(st.target, out)
            _visit_expr(st.value, out)
        elif isinstance(st, P.UseStmt):
            _visit_expr(st.expr, out)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                _visit_expr(cond, out)
                _walk_body(body, out)
            if st.else_body is not None:
                _walk_body(st.else_body, out)
        elif isinstance(st, P.Case):
            if st.subject is not None:
                _visit_expr(st.subject, out)
            for when in st.whens:
                for cond in when.conditions:
                    _visit_expr(cond, out)
                _walk_body(when.body, out)
            if st.else_body is not None:
                _walk_body(st.else_body, out)
        elif isinstance(st, P.While):
            _visit_expr(st.cond, out)
            _walk_body(st.body, out)
        elif isinstance(st, P.ForEach):
            _visit_expr(st.source, out)
            _walk_body(st.body, out)
        elif isinstance(st, P.ForTo):
            _visit_expr(st.start_expr, out)
            _visit_expr(st.to, out)
            if st.step is not None:
                _visit_expr(st.step, out)
            _walk_body(st.body, out)
        elif isinstance(st, P.Try):
            _walk_body(st.body, out)
            for _var, _type, body in st.catches:
                _walk_body(body, out)
            if st.finally_body is not None:
                _walk_body(st.finally_body, out)
        elif isinstance(st, P.Scope):
            _walk_body(st.body, out)
        elif isinstance(st, P.Return):
            _visit_expr(st.value, out)


@rule("code/statement-no-effect", "code/statement-no-effect.title", "C")
def statement_no_effect(source: SourceFile) -> Iterable[Diagnostic]:
    """An expression statement must call, create or throw - otherwise it does nothing."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory; recovery stubs would lie here
    found: list[P.ExprStmt] = []
    for m in module.members:
        if isinstance(m, P.Method):
            for p in m.params:
                _visit_expr(p.default, found)
            _walk_body(m.body, found)
        elif isinstance(m, P.ObjectField):
            _visit_expr(m.init, found)
        elif isinstance(m, P.Structure):
            for sub in m.members:
                if isinstance(sub, P.Method):
                    _walk_body(sub.body, found)
                elif isinstance(sub, P.ObjectField):
                    _visit_expr(sub.init, found)
        elif isinstance(m, P.Enum):
            for sub in m.methods:
                _walk_body(sub.body, found)
    if not found:
        return
    lm = linemap(source)
    for st in found:
        line, col = lm.linecol(st.start)
        yield Diagnostic(
            source.rel, line, col, "code/statement-no-effect", Severity.WARNING,
            i18n.t("code/statement-no-effect.found"),
        )
