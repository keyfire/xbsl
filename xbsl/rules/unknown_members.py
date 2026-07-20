"""Tier D: a member access must exist on the type it is addressed through - two rules.

code/unknown-member (file scope) judges a member by the DECLARED type of a variable, and
code/unknown-static-member (project scope) judges it by a TYPE NAME standing in the value
position (`ДатаВремя.Минимальная()`), carrying the type of such a call along the chain. The
split is deliberate: the declared-type check needs nothing but the file, so it stays instant
in the editor, while reading a bare name as a type is only safe once the whole project has
been seen - a form attribute named Email is not the mail type.


First-hop only, negatives only. A variable counts as typed when every declaration of that
name in the method (parameters, `пер`/`знч` with an explicit type, `поймать`) names the
same single non-generic stdlib type; the member is then checked against the type's
properties + methods from the stdlib catalog. Entity aggregates (Пользователи,
ДвоичныйОбъект...) keep their record and reference members on facet pages - the catalog's
facet_members - so the aggregate name covers the union of its facets, and a facet itself
(ДвоичныйОбъект.Ссылка) works as a nominal type. Everything else is skipped: project
types, generic and compound types, chains beyond the first hop, Latin member spellings
(the bilingual stdlib is cataloged under Russian member names), names redeclared with
different or absent types anywhere in the method (lambda parameters included).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.semantics import _object_name_fast
from xbsl.rules.undefined_names import _IMPLICIT

MESSAGES = {
    "code/unknown-member.title": {
        "ru": "Неизвестный член типа",
        "en": "Unknown member of a type",
    },
    "code/unknown-member.found": {
        "ru": "У типа {type} нет члена {member}",
        "en": "The type {type} has no member {member}",
    },
    "code/unknown-member.found-hint": {
        "ru": "У типа {type} нет члена {member} – возможно, имелся в виду {hint}",
        "en": "The type {type} has no member {member} - did you mean {hint}",
    },
}
i18n.register(MESSAGES)

# Undocumented members seen on every instance (the object protocol).
_COMMON_MEMBERS = frozenset({"ПолучитьТип", "ВСтроку", "Представление"})

# A plain name or a one-dot facet name (ДвоичныйОбъект.Ссылка).
_NOMINAL_RE = re.compile(r"[А-Яа-яЁёA-Za-z0-9_]+(?:\.[А-Яа-яЁёA-Za-z0-9_]+)?")

_members_cache: dict[str, frozenset[str]] | None = None


def _stdlib_members() -> dict[str, frozenset[str]]:
    """Type name -> members. Entity aggregates carry their record and reference members
    on facet pages (Пользователи.Объект, ДвоичныйОбъект.Ссылка) - facet_members of the
    catalog; a variable typed with the bare aggregate name may hold any facet, so the
    aggregate's set is the union, and every facet is also usable as a nominal type."""
    global _members_cache
    if _members_cache is None:
        try:
            data = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - no data, no rule
            data = {}
        raw = data.get("type_members") or {}
        facets = data.get("facet_members") or {}
        facet_union: dict[str, set[str]] = {}
        result: dict[str, frozenset[str]] = {}
        for fname, fm in facets.items():
            members = frozenset(fm.get("properties", ())) | frozenset(fm.get("methods", ()))
            result[fname] = members
            facet_union.setdefault(fname.split(".", 1)[0], set()).update(members)
        for name, m in raw.items():
            members = frozenset(m.get("properties", ())) | frozenset(m.get("methods", ()))
            result[name] = members | frozenset(facet_union.get(name, ()))
        _members_cache = result
    return _members_cache


def _nominal(tref: P.TypeRef | None) -> str | None:
    """The single plain (or one-dot facet) type name of a declaration, or None."""
    if tref is None or len(tref.names) != 1:
        return None
    text = tref.text.strip().removesuffix("?").strip()
    if not _NOMINAL_RE.fullmatch(text):
        return None
    return text


class _Scope:
    """Per-method collection: name -> type (or None once the name is poisoned)."""

    def __init__(self) -> None:
        self.types: dict[str, str | None] = {}

    def declare(self, name: str, tref: P.TypeRef | None, init: P.Expr | None = None) -> None:
        # `init` is what the sibling rule below infers types from; the declared type is the
        # only source here, so the initializer is ignored - the walkers are shared.
        nominal = _nominal(tref)
        if name in self.types and self.types[name] != nominal:
            self.types[name] = None
        else:
            self.types[name] = nominal


def _walk_expr(expr: P.Expr | None, scope: _Scope, uses: list[P.Member]) -> None:
    if expr is None:
        return
    if isinstance(expr, P.Member):
        if isinstance(expr.obj, P.Name):
            uses.append(expr)
        else:
            _walk_expr(expr.obj, scope, uses)
        return
    if isinstance(expr, P.Lambda):
        for p in expr.params:
            scope.declare(p.name, p.type)
        if isinstance(expr.body_expr, P.Expr):
            _walk_expr(expr.body_expr, scope, uses)
        elif isinstance(expr.body_expr, P.Assign):
            _walk_expr(expr.body_expr.target, scope, uses)
            _walk_expr(expr.body_expr.value, scope, uses)
        if expr.body_stmts is not None:
            _walk_body(expr.body_stmts, scope, uses)
        return
    if isinstance(expr, P.Call):
        _walk_expr(expr.callee, scope, uses)
        for arg in expr.args:
            _walk_expr(arg.value, scope, uses)
    elif isinstance(expr, P.Unary):
        _walk_expr(expr.operand, scope, uses)
    elif isinstance(expr, P.Binary):
        _walk_expr(expr.left, scope, uses)
        _walk_expr(expr.right, scope, uses)
    elif isinstance(expr, P.Compare):
        _walk_expr(expr.first, scope, uses)
        for _op, right in expr.rest:
            _walk_expr(right, scope, uses)
    elif isinstance(expr, (P.IsType, P.AsType, P.NonNull)):
        _walk_expr(expr.operand, scope, uses)
    elif isinstance(expr, P.Ternary):
        _walk_expr(expr.cond, scope, uses)
        _walk_expr(expr.then, scope, uses)
        _walk_expr(expr.otherwise, scope, uses)
    elif isinstance(expr, P.Coalesce):
        _walk_expr(expr.left, scope, uses)
        _walk_expr(expr.right, scope, uses)
    elif isinstance(expr, P.Index):
        _walk_expr(expr.obj, scope, uses)
        _walk_expr(expr.index, scope, uses)
    elif isinstance(expr, P.New):
        if expr.args:
            for arg in expr.args:
                _walk_expr(arg.value, scope, uses)
    elif isinstance(expr, P.ArrayLit):
        for item in expr.items:
            _walk_expr(item, scope, uses)
    elif isinstance(expr, P.MapLit):
        for k, v in expr.entries:
            _walk_expr(k, scope, uses)
            _walk_expr(v, scope, uses)
    elif isinstance(expr, P.Throw):
        _walk_expr(expr.value, scope, uses)


def _walk_body(stmts: list[P.Stmt], scope: _Scope, uses: list[P.Member]) -> None:
    for st in stmts:
        if isinstance(st, P.VarDecl):
            scope.declare(st.name, st.type, st.init)
            _walk_expr(st.init, scope, uses)
        elif isinstance(st, P.Assign):
            _walk_expr(st.target, scope, uses)
            _walk_expr(st.value, scope, uses)
        elif isinstance(st, (P.ExprStmt, P.UseStmt)):
            _walk_expr(st.expr, scope, uses)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                _walk_expr(cond, scope, uses)
                _walk_body(body, scope, uses)
            if st.else_body is not None:
                _walk_body(st.else_body, scope, uses)
        elif isinstance(st, P.Case):
            if st.subject is not None:
                _walk_expr(st.subject, scope, uses)
            for when in st.whens:
                for cond in when.conditions:
                    _walk_expr(cond, scope, uses)
                _walk_body(when.body, scope, uses)
            if st.else_body is not None:
                _walk_body(st.else_body, scope, uses)
        elif isinstance(st, P.While):
            _walk_expr(st.cond, scope, uses)
            _walk_body(st.body, scope, uses)
        elif isinstance(st, P.ForEach):
            scope.declare(st.var, None)  # the element type is inference territory
            _walk_expr(st.source, scope, uses)
            _walk_body(st.body, scope, uses)
        elif isinstance(st, P.ForTo):
            scope.declare(st.var, None)
            _walk_expr(st.start_expr, scope, uses)
            _walk_expr(st.to, scope, uses)
            if st.step is not None:
                _walk_expr(st.step, scope, uses)
            _walk_body(st.body, scope, uses)
        elif isinstance(st, P.Try):
            _walk_body(st.body, scope, uses)
            for var, tref, body in st.catches:
                if var:
                    scope.declare(var, tref)
                _walk_body(body, scope, uses)
            if st.finally_body is not None:
                _walk_body(st.finally_body, scope, uses)
        elif isinstance(st, P.Scope):
            _walk_body(st.body, scope, uses)
        elif isinstance(st, P.Return):
            _walk_expr(st.value, scope, uses)


def _is_latin(name: str) -> bool:
    return all(ord(c) < 128 for c in name)


@rule("code/unknown-member", "code/unknown-member.title", "D", severity=Severity.ERROR)
def unknown_member(source: SourceFile) -> Iterable[Diagnostic]:
    """A first-hop member access on a variable of a plain stdlib type must exist on it."""
    if source.kind != "xbsl":
        return
    members_by_type = _stdlib_members()
    if not members_by_type:
        return
    module, errors = parse(source)
    if errors:
        return
    lm = linemap(source)
    methods: list[P.Method] = []
    for m in module.members:
        if isinstance(m, P.Method):
            methods.append(m)
        elif isinstance(m, P.Structure):
            methods.extend(sub for sub in m.members if isinstance(sub, P.Method))
        elif isinstance(m, P.Enum):
            methods.extend(m.methods)
    for method in methods:
        scope = _Scope()
        for p in method.params:
            scope.declare(p.name, p.type)
        uses: list[P.Member] = []
        for p in method.params:
            _walk_expr(p.default, scope, uses)
        _walk_body(method.body, scope, uses)
        for use in uses:
            assert isinstance(use.obj, P.Name)
            type_name = scope.types.get(use.obj.name)
            if type_name is None:
                continue
            members = members_by_type.get(type_name)
            if members is None or _is_latin(use.name):
                continue
            if use.name in members or use.name in _COMMON_MEMBERS:
                continue
            hint = difflib.get_close_matches(use.name, members, n=1, cutoff=0.75)
            line, col = lm.linecol(use.start)
            message = (
                i18n.t("code/unknown-member.found-hint",
                       type=type_name, member=use.name, hint=hint[0])
                if hint
                else i18n.t("code/unknown-member.found", type=type_name, member=use.name)
            )
            yield Diagnostic(
                source.rel, line, col, "code/unknown-member", Severity.ERROR, message,
            )


# --- The same check reached through a TYPE NAME ----------------------------------------

MESSAGES_STATIC = {
    "code/unknown-static-member.title": {
        "ru": "Неизвестный член при обращении по имени типа",
        "en": "Unknown member on a type name",
    },
    "code/unknown-static-member.found": {
        "ru": "У типа {type} нет члена {member}",
        "en": "The type {type} has no member {member}",
    },
    "code/unknown-static-member.found-hint": {
        "ru": "У типа {type} нет члена {member} – возможно, имелся в виду {hint}",
        "en": "The type {type} has no member {member} - did you mean {hint}",
    },
}
i18n.register(MESSAGES_STATIC)

# The roots of the type hierarchy: every type inherits them, so their own member set is the
# bare object protocol. Judging anything against it would report every real member as unknown.
_HIERARCHY_ROOTS = frozenset({"Объект", "Одиночка", "Object", "Singleton"})

# `Имя: X` anywhere in a yaml - an object name, a form attribute, a component, a column. Any of
# them becomes a bare name in the paired module and would shadow a same-named stdlib type.
_YAML_NAME_RE = re.compile(
    r"^[ \t]*(?:-[ \t]*)?(?:Имя|Name):[ \t]*(['\"]?)([^\r\n#]*?)\1[ \t]*(?:#.*)?$", re.M,
)

_member_types_cache: dict[str, dict[str, str]] | None = None


def _member_types() -> dict[str, dict[str, str]]:
    """Type name -> member -> the member's own type (method returns and property types)."""
    global _member_types_cache
    if _member_types_cache is None:
        try:
            data = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - no data, no rule
            data = {}
        _member_types_cache = data.get("member_types") or {}
    return _member_types_cache


def _pair_key(rel: str) -> str:
    """The key that joins a module to its yaml: the path without the extension."""
    return rel.replace("\\", "/").rsplit(".", 1)[0].lower()


class _StaticScope:
    """name -> (type, shadow root) or None once the name is poisoned.

    The shadow root is the bare name the type was inferred from (`ДатаВремя` in
    `знч Б = ДатаВремя.Сейчас()`): the reduce phase drops the finding if the project turns
    out to mean something else by that name. It is None when the chain started from a
    declared type - written in the code, so no project name can shadow it.
    """

    def __init__(self) -> None:
        self.types: dict[str, tuple[str, str | None] | None] = {}
        self.declared: set[str] = set()  # types stated outright - the sibling rule's business

    def declare(self, name: str, tref: P.TypeRef | None, init: P.Expr | None = None) -> None:
        nominal = _nominal(tref)
        if nominal is not None:
            info: tuple[str, str | None] | None = (nominal, None)
            self.declared.add(name)
        elif tref is None and init is not None:
            info = self.infer(init)
        else:
            info = None
        if name in self.types and self.types[name] != info:
            self.types[name] = None
        else:
            self.types[name] = info

    def infer(self, expr: P.Expr) -> tuple[str, str | None] | None:
        """The type of `Основа.Член` / `Основа.Член(...)`, when the catalog names it."""
        target = expr.callee if isinstance(expr, P.Call) else expr
        if not isinstance(target, P.Member) or not isinstance(target.obj, P.Name):
            return None
        base = target.obj.name
        if "::" in base:
            return None
        if base in self.types:
            info = self.types[base]
            if info is None:
                return None
            base_type, root = info
        else:
            base_type, root = base, base  # a bare name that is not declared: a type name
        member_type = _member_types().get(base_type, {}).get(target.name)
        if member_type is None or not _NOMINAL_RE.fullmatch(member_type):
            return None  # generic or compound - inference territory, not this rule's
        return (member_type, root)


def _module_shadow(module: P.Module) -> set[str]:
    """Names the module itself provides - they are never a reference to a stdlib type."""
    names = {imp.name.split("::")[-1] for imp in module.imports}
    for m in module.members:
        name = getattr(m, "name", None)
        if name:
            names.add(name)
    return names


def _static_mapper(source: SourceFile) -> dict | None:
    """The map phase: candidate findings of a module, or the names a yaml contributes.

    Everything the file can settle alone is settled here (local declarations, module-level
    names, imports, implicit roots, members that do exist); the reduce only drops candidates
    whose base name the project gives another meaning, and computes the spelling hints.
    """
    if source.kind == "yaml":
        names = {m.group(2).strip() for m in _YAML_NAME_RE.finditer(source.text)}
        names.discard("")
        if not names:
            return None
        # The object name is visible project-wide; the rest only in the paired module.
        obj = _object_name_fast(source)
        return {"object": obj, "names": sorted(names)}
    if source.kind != "xbsl":
        return None
    members_by_type = _stdlib_members()
    if not members_by_type:
        return None
    module, errors = parse(source)
    if errors:
        return None
    shadow = _module_shadow(module) | _IMPLICIT | _HIERARCHY_ROOTS
    methods: list[P.Method] = []
    for m in module.members:
        if isinstance(m, P.Method):
            methods.append(m)
        elif isinstance(m, P.Structure):
            methods.extend(sub for sub in m.members if isinstance(sub, P.Method))
        elif isinstance(m, P.Enum):
            methods.extend(m.methods)
    lm = None
    found: list[tuple[str | None, str, str, int, int]] = []
    for method in methods:
        scope = _StaticScope()
        for p in method.params:
            scope.declare(p.name, p.type)
        uses: list[P.Member] = []
        for p in method.params:
            _walk_expr(p.default, scope, uses)
        _walk_body(method.body, scope, uses)
        for use in uses:
            assert isinstance(use.obj, P.Name)
            name = use.obj.name
            if name in scope.declared or "::" in name:
                continue  # a declared type is checked by code/unknown-member itself
            if name in scope.types:
                info = scope.types[name]
                if info is None:
                    continue
                type_name, root = info
            else:
                if name in shadow or name not in members_by_type:
                    continue
                type_name, root = name, name
            members = members_by_type.get(type_name)
            if members is None or _is_latin(use.name):
                continue
            if use.name in members or use.name in _COMMON_MEMBERS:
                continue
            if lm is None:
                lm = linemap(source)
            line, col = lm.linecol(use.start)
            found.append((root, type_name, use.name, line, col))
    return {"uses": found} if found else None


@rule(
    "code/unknown-static-member", "code/unknown-static-member.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_static_mapper,
)
def unknown_static_member(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A member reached through a type name must exist on that type.

    Covers what code/unknown-member cannot see: `ДатаВремя.Минимальная()` addresses the TYPE,
    not a value, and the type of such a call is carried on (`знч Б = ДатаВремя.Сейчас()` makes
    `Б` a ДатаВремя), so the chain is checked too. The base name is only read as a type when
    the project gives it no other meaning - an object name anywhere, or a name of the paired
    yaml (a form attribute called Email is not the mail type). Project scope is what makes that
    possible; everything else is settled per file in the mapper.
    """
    members_by_type = _stdlib_members()
    if not members_by_type:
        return
    global_shadow: set[str] = set()
    paired: dict[str, set[str]] = {}
    for rel, fact in facts.items():
        if "names" not in fact:
            continue
        if fact["object"]:
            global_shadow.add(fact["object"])
        paired.setdefault(_pair_key(rel), set()).update(fact["names"])
    for rel, fact in facts.items():
        uses = fact.get("uses")
        if not uses:
            continue
        shadow = global_shadow | paired.get(_pair_key(rel), set())
        for root, type_name, member, line, col in uses:
            if root is not None and root in shadow:
                continue
            hint = difflib.get_close_matches(member, members_by_type[type_name], n=1, cutoff=0.75)
            message = (
                i18n.t("code/unknown-static-member.found-hint",
                       type=type_name, member=member, hint=hint[0])
                if hint
                else i18n.t("code/unknown-static-member.found", type=type_name, member=member)
            )
            yield Diagnostic(
                rel, line, col, "code/unknown-static-member", Severity.ERROR, message,
            )
