"""Tier C: an expression statement must be a method call or a throw.

The compiler takes an expression as a statement only when it is a method call (plain, `?.`,
through a module or a variable holding a lambda) or a `выбросить`; an assignment is a
statement of its own. Every other expression statement is a build error - the value is
computed and nothing uses it. That covers the typos the parser accepts (`возрат 5` becomes
two statements, a name and a number; `Х == 5` instead of `Х = 5` is a dropped comparison),
and it covers statements that do run code: `Метод() + 1`, `новый Массив<Число>()`,
`Флаг ? Метод() : 0`, `Пустая ?? Метод()`, `Метод()!`, `Метод()[0]`, a rich string with
`%{Метод()}` inside, `Запрос{...}`, a lambda. Parentheses change nothing: the parser unwraps
them, so `(Метод())` stays a call and `(Имя)` stays a name - the compiler reads them the
same way.

The two cases get two messages. With nothing inside that runs code, the statement does
nothing at all and is most likely a typo. With a call or `новый` inside, the call runs but
its result is dropped, and the statement still does not build.

Walked: the bodies of methods (module, structure and enumeration methods) and full lambda
bodies at any depth, including every nested block. The expression body of a short lambda
(`Н -> Н + 1`) is a value, not a statement, and is not judged. A file with a parse error is
left to `code/parse-error`: recovery stubs would read as statements here.
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
    "code/statement-no-effect.value-dropped": {
        "ru": "Значение выражения не используется, и такой оператор не соберётся: оператором "
              "может быть только вызов метода, присваивание или 'выбросить'. Сохраните результат "
              "в переменную или оставьте один вызов",
        "en": "The value of the expression is not used, and such a statement does not build: a "
              "statement can only be a method call, an assignment or '{n[выбросить]}'. Assign "
              "the result to a variable or keep the call alone",
    },
}
i18n.register(MESSAGES)


def _is_statement(expr: P.Expr) -> bool:
    """A call or a throw - the only expressions the compiler takes as a statement."""
    return isinstance(expr, (P.Call, P.Throw))


def _runs_code(expr: P.Expr | None) -> bool:
    """Does the expression call, create or throw anything (a lambda body does not run)?"""
    if expr is None:
        return False
    if isinstance(expr, (P.Call, P.New, P.Throw)):
        return True
    if isinstance(expr, P.Literal):
        # A rich string is one lexer token; a call may hide inside `%{...}`/`${...}`.
        return expr.kind == "STRING" and ("%{" in expr.text or "${" in expr.text)
    if isinstance(expr, P.Lambda):
        return False
    if isinstance(expr, P.Unary):
        return _runs_code(expr.operand)
    if isinstance(expr, P.Binary):
        return _runs_code(expr.left) or _runs_code(expr.right)
    if isinstance(expr, P.Compare):
        return _runs_code(expr.first) or any(_runs_code(r) for _op, r in expr.rest)
    if isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        return _runs_code(expr.operand)
    if isinstance(expr, P.Ternary):
        return _runs_code(expr.cond) or _runs_code(expr.then) or _runs_code(expr.otherwise)
    if isinstance(expr, P.Coalesce):
        return _runs_code(expr.left) or _runs_code(expr.right)
    if isinstance(expr, P.Member):
        return _runs_code(expr.obj)
    if isinstance(expr, P.Index):
        return _runs_code(expr.obj) or _runs_code(expr.index)
    if isinstance(expr, P.ArrayLit):
        return any(_runs_code(item) for item in expr.items)
    if isinstance(expr, P.MapLit):
        return any(_runs_code(k) or _runs_code(v) for k, v in expr.entries)
    return False  # Name, This, GlobalAccess, MethodRef, plain and opaque literals


def _visit_expr(expr: P.Expr | None, out: list[P.ExprStmt]) -> None:
    """Collect the offending statements of lambda bodies nested in an expression."""
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
            if not _is_statement(st.expr):
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


@rule(
    "code/statement-no-effect", "code/statement-no-effect.title", "C",
    severity=Severity.ERROR,
)
def statement_no_effect(source: SourceFile) -> Iterable[Diagnostic]:
    """An expression statement must be a method call or a throw - anything else does not build."""
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
        key = "value-dropped" if _runs_code(st.expr) else "found"
        yield Diagnostic(
            source.rel, line, col, "code/statement-no-effect", Severity.ERROR,
            i18n.t(f"code/statement-no-effect.{key}"),
        )
