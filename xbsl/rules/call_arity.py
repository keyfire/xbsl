"""Tier C: a call must pass as many arguments as the method's signature allows.

Signatures come from the module's own AST (methods of the module, static methods of its
structures and enums called as `Тип.Метод(...)`), so the check is per-file and needs no
data. A finding is proven: the callee is resolved to exactly one local method and the
positional argument count falls outside [required, total].

Left alone on purpose:
- calls with named arguments (`Имя = значение` - the named-parameters mechanics);
- callee names shadowed by a local declaration or parameter anywhere in the module
  (a variable may hold a lambda with its own arity);
- duplicate method names (broken anyway - the compiler reports it).

Cross-module calls (`Модуль.Метод(...)`) are covered by the project-scope twin
`code/call-arity-cross` below - it resolves the base name to another module of the
project and checks against that module's signatures.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse

MESSAGES = {
    "code/call-arity.title": {
        "ru": "Число аргументов не по сигнатуре",
        "en": "Argument count does not match the signature",
    },
    "code/call-arity.too-many": {
        "ru": "Вызов {name}: передано аргументов – {got}, метод принимает не больше {max}",
        "en": "Call of {name}: {got} arguments passed, the method takes at most {max}",
    },
    "code/call-arity.too-few": {
        "ru": "Вызов {name}: передано аргументов – {got}, методу нужно не меньше {min}",
        "en": "Call of {name}: {got} arguments passed, the method needs at least {min}",
    },
    "code/call-arity-cross.title": {
        "ru": "Число аргументов кросс-модульного вызова не по сигнатуре",
        "en": "Argument count of a cross-module call does not match the signature",
    },
}
i18n.register(MESSAGES)


def _signature(m: P.Method) -> tuple[int, int]:
    required = sum(1 for p in m.params if p.default is None)
    return required, len(m.params)


def _walk_expr(expr: P.Expr | None, calls: list[P.Call], names: set[str]) -> None:
    if expr is None:
        return
    if isinstance(expr, P.Name):
        return
    if isinstance(expr, P.Call):
        calls.append(expr)
        _walk_expr(expr.callee, calls, names)
        for arg in expr.args:
            _walk_expr(arg.value, calls, names)
        return
    if isinstance(expr, P.Lambda):
        names.update(p.name for p in expr.params)
        if isinstance(expr.body_expr, P.Expr):
            _walk_expr(expr.body_expr, calls, names)
        elif isinstance(expr.body_expr, P.Assign):
            _walk_expr(expr.body_expr.target, calls, names)
            _walk_expr(expr.body_expr.value, calls, names)
        if expr.body_stmts is not None:
            _walk_body(expr.body_stmts, calls, names)
        return
    if isinstance(expr, P.Unary):
        _walk_expr(expr.operand, calls, names)
    elif isinstance(expr, P.Binary):
        _walk_expr(expr.left, calls, names)
        _walk_expr(expr.right, calls, names)
    elif isinstance(expr, P.Compare):
        _walk_expr(expr.first, calls, names)
        for _op, right in expr.rest:
            _walk_expr(right, calls, names)
    elif isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        _walk_expr(expr.operand, calls, names)
    elif isinstance(expr, P.Ternary):
        _walk_expr(expr.cond, calls, names)
        _walk_expr(expr.then, calls, names)
        _walk_expr(expr.otherwise, calls, names)
    elif isinstance(expr, P.Coalesce):
        _walk_expr(expr.left, calls, names)
        _walk_expr(expr.right, calls, names)
    elif isinstance(expr, P.Member):
        _walk_expr(expr.obj, calls, names)
    elif isinstance(expr, P.Index):
        _walk_expr(expr.obj, calls, names)
        _walk_expr(expr.index, calls, names)
    elif isinstance(expr, P.New):
        if expr.args:
            for arg in expr.args:
                _walk_expr(arg.value, calls, names)
    elif isinstance(expr, P.ArrayLit):
        for item in expr.items:
            _walk_expr(item, calls, names)
    elif isinstance(expr, P.MapLit):
        for k, v in expr.entries:
            _walk_expr(k, calls, names)
            _walk_expr(v, calls, names)
    elif isinstance(expr, P.Throw):
        _walk_expr(expr.value, calls, names)


def _walk_body(stmts: list[P.Stmt], calls: list[P.Call], names: set[str]) -> None:
    """Collect every call and every locally declared name (shadowing guard)."""
    for st in stmts:
        if isinstance(st, P.VarDecl):
            names.add(st.name)
            _walk_expr(st.init, calls, names)
        elif isinstance(st, P.Assign):
            _walk_expr(st.target, calls, names)
            _walk_expr(st.value, calls, names)
        elif isinstance(st, (P.ExprStmt, P.UseStmt)):
            _walk_expr(st.expr, calls, names)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                _walk_expr(cond, calls, names)
                _walk_body(body, calls, names)
            if st.else_body is not None:
                _walk_body(st.else_body, calls, names)
        elif isinstance(st, P.Case):
            if st.subject is not None:
                _walk_expr(st.subject, calls, names)
            for when in st.whens:
                for cond in when.conditions:
                    _walk_expr(cond, calls, names)
                _walk_body(when.body, calls, names)
            if st.else_body is not None:
                _walk_body(st.else_body, calls, names)
        elif isinstance(st, P.While):
            _walk_expr(st.cond, calls, names)
            _walk_body(st.body, calls, names)
        elif isinstance(st, P.ForEach):
            names.add(st.var)
            _walk_expr(st.source, calls, names)
            _walk_body(st.body, calls, names)
        elif isinstance(st, P.ForTo):
            names.add(st.var)
            _walk_expr(st.start_expr, calls, names)
            _walk_expr(st.to, calls, names)
            if st.step is not None:
                _walk_expr(st.step, calls, names)
            _walk_body(st.body, calls, names)
        elif isinstance(st, P.Try):
            _walk_body(st.body, calls, names)
            for var, _type, body in st.catches:
                if var:
                    names.add(var)
                _walk_body(body, calls, names)
            if st.finally_body is not None:
                _walk_body(st.finally_body, calls, names)
        elif isinstance(st, P.Scope):
            _walk_body(st.body, calls, names)
        elif isinstance(st, P.Return):
            _walk_expr(st.value, calls, names)


@rule("code/call-arity", "code/call-arity.title", "C", severity=Severity.ERROR)
def call_arity(source: SourceFile) -> Iterable[Diagnostic]:
    """A local call must fit the method's [required, total] argument range."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return
    # Signatures: module methods by name; static methods of structures and enums by "Тип.Метод".
    sigs: dict[str, tuple[int, int]] = {}
    dupes: set[str] = set()

    def note(name: str, m: P.Method) -> None:
        if name in sigs:
            dupes.add(name)
        sigs[name] = _signature(m)

    for m in module.members:
        if isinstance(m, P.Method):
            note(m.name, m)
        elif isinstance(m, (P.Structure, P.Enum)):
            subs = m.members if isinstance(m, P.Structure) else m.methods
            for sub in subs:
                if isinstance(sub, P.Method) and sub.is_static:
                    note(f"{m.name}.{sub.name}", sub)
    if not sigs:
        return

    calls: list[P.Call] = []
    declared: set[str] = set()
    for m in module.members:
        if isinstance(m, P.Method):
            declared.update(p.name for p in m.params)
            for p in m.params:
                _walk_expr(p.default, calls, declared)
            _walk_body(m.body, calls, declared)
        elif isinstance(m, P.ObjectField):
            if m.init is not None:
                _walk_expr(m.init, calls, declared)
        elif isinstance(m, (P.Structure, P.Enum)):
            subs = m.members if isinstance(m, P.Structure) else m.methods
            for sub in subs:
                if isinstance(sub, P.Method):
                    declared.update(p.name for p in sub.params)
                    _walk_body(sub.body, calls, declared)
                elif isinstance(sub, P.ObjectField) and sub.init is not None:
                    _walk_expr(sub.init, calls, declared)
    if not calls:
        return

    lm = linemap(source)
    for call in calls:
        if isinstance(call.callee, P.Name):
            name = call.callee.name
            if "::" in name or name in declared:
                continue
        elif (
            isinstance(call.callee, P.Member)
            and isinstance(call.callee.obj, P.Name)
            and not call.callee.safe
        ):
            base = call.callee.obj.name
            if base in declared:
                continue
            name = f"{base}.{call.callee.name}"
        else:
            continue
        sig = sigs.get(name)
        if sig is None or name in dupes:
            continue
        if any(arg.name is not None for arg in call.args):
            continue  # named arguments live by their own rules
        required, total = sig
        got = len(call.args)
        # `Метод()` with a single empty slot parses as zero arguments either way.
        if got > total:
            line, col = lm.linecol(call.start)
            yield Diagnostic(
                source.rel, line, col, "code/call-arity", Severity.ERROR,
                i18n.t("code/call-arity.too-many", name=name, got=got, max=total),
            )
        elif got < required:
            line, col = lm.linecol(call.start)
            yield Diagnostic(
                source.rel, line, col, "code/call-arity", Severity.ERROR,
                i18n.t("code/call-arity.too-few", name=name, got=got, min=required),
            )


def _cross_mapper(source: SourceFile) -> dict | None:
    """The map phase: this module's signatures plus its candidate cross-module calls.

    Everything local is settled here (named arguments, bases shadowed by a declaration
    or by an own member, `::` bases, positions); the reduce only resolves base names
    against the other modules' signatures and the stdlib shadow set.
    """
    if source.kind != "xbsl":
        return None
    stem = source.rel.replace("\\", "/").rsplit("/", 1)[-1].removesuffix(".xbsl")
    module, errors = parse(source)
    if errors:
        # A broken file gives no candidates, but its stem must still poison the name.
        return {"stem": stem if "." not in stem else None, "sigs": None, "calls": []}
    own: set[str] = set()
    calls: list[P.Call] = []
    declared: set[str] = set()
    sigs: dict[str, tuple[int, int]] = {}
    dupes: set[str] = set()
    for m in module.members:
        if isinstance(m, (P.Method, P.Structure, P.Enum, P.ObjectField)):
            own.add(m.name)
        if isinstance(m, P.Method):
            if m.name in sigs:
                dupes.add(m.name)
            sigs[m.name] = _signature(m)
            declared.update(p.name for p in m.params)
            for p in m.params:
                _walk_expr(p.default, calls, declared)
            _walk_body(m.body, calls, declared)
        elif isinstance(m, P.ObjectField):
            if m.init is not None:
                _walk_expr(m.init, calls, declared)
        elif isinstance(m, (P.Structure, P.Enum)):
            subs = m.members if isinstance(m, P.Structure) else m.methods
            for sub in subs:
                if isinstance(sub, P.Method):
                    declared.update(p.name for p in sub.params)
                    _walk_body(sub.body, calls, declared)
                elif isinstance(sub, P.ObjectField) and sub.init is not None:
                    _walk_expr(sub.init, calls, declared)
    for d in dupes:
        sigs.pop(d, None)
    lm = None
    candidates: list[tuple[str, str, int, int, int]] = []
    for call in calls:
        callee = call.callee
        if not (
            isinstance(callee, P.Member)
            and isinstance(callee.obj, P.Name)
            and not callee.safe
        ):
            continue
        base = callee.obj.name
        if "::" in base or base in declared or base in own:
            continue
        if any(arg.name is not None for arg in call.args):
            continue
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(call.start)
        candidates.append((base, callee.name, len(call.args), line, col))
    if "." in stem and not candidates:
        return None  # an object module and friends: not callable by name, nothing to check
    return {"stem": stem if "." not in stem else None, "sigs": sigs, "calls": candidates}


@rule(
    "code/call-arity-cross", "code/call-arity-cross.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_cross_mapper,
)
def call_arity_cross(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`Модуль.Метод(...)` must fit the target module's method signature.

    Signatures come from the project's own module files (the file stem is the callable
    name; dotted stems - object modules and other satellites - are not callable by name).
    A finding needs the base name to resolve to exactly one clean project module and the
    method to exist there. Skipped: stdlib name shadows (Пользователи), duplicated module
    or method names, named arguments, bases shadowed by any local declaration, broken
    files (both as callers and as signature sources).
    """
    try:
        stdlib_names = set(dataset.load_json("stdlib.json").get("names", ()))
    except Exception:  # noqa: BLE001
        return  # without the catalog a project module cannot be told from a stdlib shadow
    # Module name -> {method: (required, total)}; None marks an unusable name
    # (a parse-broken file or twin modules in different directories).
    module_sigs: dict[str, dict[str, tuple[int, int]] | None] = {}
    for fact in facts.values():
        stem = fact["stem"]
        if stem is None:
            continue
        if fact["sigs"] is None or stem in module_sigs:
            module_sigs[stem] = None
        else:
            module_sigs[stem] = fact["sigs"]
    if not any(module_sigs.values()):
        return
    for rel, fact in facts.items():
        for base, method, got, line, col in fact["calls"]:
            if base in stdlib_names:
                continue
            target = module_sigs.get(base)
            if not target:
                continue
            sig = target.get(method)
            if sig is None:
                continue  # no such method there - not this rule's business
            required, total = sig
            name = f"{base}.{method}"
            if got > total:
                yield Diagnostic(
                    rel, line, col, "code/call-arity-cross", Severity.ERROR,
                    i18n.t("code/call-arity.too-many", name=name, got=got, max=total),
                )
            elif got < required:
                yield Diagnostic(
                    rel, line, col, "code/call-arity-cross", Severity.ERROR,
                    i18n.t("code/call-arity.too-few", name=name, got=got, min=required),
                )
