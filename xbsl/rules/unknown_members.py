"""Tier D: a member access must exist on the type it is addressed through - two rules.

code/unknown-member (file scope) judges a member by the DECLARED type of a variable, and
code/unknown-static-member (project scope) judges it by a TYPE NAME standing in the value
position (`ДатаВремя.Минимальная()`), carrying the type of such a call along the chain. The
split is deliberate: the declared-type check needs nothing but the file, so it stays instant
in the editor, while reading a bare name as a type is only safe once the whole project has
been seen - a form attribute named Email is not the mail type.


First-hop only, negatives only. A variable counts as typed when every declaration of that
name in the method (parameters, `пер`/`знч` with an explicit type, `поймать`, or a `новый Тип(...)`
initializer - a constructor names the type as plainly as an annotation) names the
same single stdlib type; the member is then checked against the type's properties + methods
from the stdlib catalog. A generic counts by its HEAD - `Массив<Строка>` and `Массив<Число>`
carry the same member names, the arguments only type them. Entity aggregates (Пользователи,
ДвоичныйОбъект...) keep their record and reference members on facet pages - the catalog's
facet_members - so the aggregate name covers the union of its facets, and a facet itself
(ДвоичныйОбъект.Ссылка) works as a nominal type. Everything else is skipped: project
types, compound types, chains beyond the first hop, Latin member spellings (the bilingual
stdlib is cataloged under Russian member names), names redeclared with different or absent
types anywhere in the method (lambda parameters included).

A variable with NO declared type whose value comes from another module -
`знч Строки = Каталог.Позиции(...)`, the shape that once took `Количество()` (an array has
`Размер`) into a build - is resolved in the project phase: every module publishes the return
types of its own methods, and the reduce joins `Модуль.Метод(...)` to them by the file stem
(the same resolution `code/call-arity-cross` uses).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable
from typing import NamedTuple

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._syntax import YAML_NAME_RE, pair_yaml_names
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
    """The single type name of a declaration: plain, a one-dot facet or a generic head, or None.

    A generic's ARGUMENTS type its members, they do not name them - `Размер` is on every
    ЧитаемыйМассив whatever it holds - so the head alone answers "does this member exist".
    Skipping generics outright is what let `ЧитаемыйМассив<...>.Количество()` (a habit from
    another platform; Element has `Размер`) through the linter and into a failed build.
    """
    if tref is None or len(tref.names) != 1:
        return None
    text = tref.text.strip().removesuffix("?").strip()
    if _NOMINAL_RE.fullmatch(text):
        return text
    head = tref.names[0]
    return head if text.startswith(f"{head}<") and text.endswith(">") else None


class _Scope:
    """Per-method collection: name -> type (or None once the name is poisoned)."""

    def __init__(self) -> None:
        self.types: dict[str, str | None] = {}

    def declare(self, name: str, tref: P.TypeRef | None, init: P.Expr | None = None) -> None:
        # Without an annotation one initializer still NAMES the type outright: `новый Массив<Строка>()`
        # is as explicit as `: Массив<Строка>`, and this is the shape that let `Количество()` (an
        # array has `Размер`) through the linter and into a failed build. Everything else about the
        # initializer is inference and belongs to the sibling rule below.
        nominal = _nominal(tref)
        if nominal is None and isinstance(init, P.New):
            nominal = _nominal(init.type)
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

_roots_cache: frozenset[str] | None = None


def _hierarchy_roots() -> frozenset[str]:
    """Types whose whole member set is the bare object protocol - nothing to judge by.

    `Объект` and `Одиночка` sit at the top of the hierarchy and carry only ВСтроку /
    ПолучитьТип / Представление, so any access through them would look unknown. Computed
    from the catalog rather than listed by hand: a type that gains a member stops being a
    blind spot on its own, and a new empty base type becomes one without a code change.
    """
    global _roots_cache
    if _roots_cache is None:
        _roots_cache = frozenset(
            name for name, members in _stdlib_members().items()
            if not (members - _COMMON_MEMBERS)
        )
    return _roots_cache

# The `Имя: X` scan and the disk-pair read live in _syntax (the hover shares them).
_YAML_NAME_RE = YAML_NAME_RE

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


class _Typed(NamedTuple):
    """A stdlib type known already in the map phase, plus the bare name it came from.

    The shadow root is the name the type was inferred from (`ДатаВремя` in
    `знч Б = ДатаВремя.Сейчас()`): the reduce phase drops the finding if the project turns
    out to mean something else by that name. It is None when the chain started from a
    declared type - written in the code, so no project name can shadow it.
    """

    name: str
    root: str | None


class _Pending(NamedTuple):
    """A value taken from `Модуль.Метод(...)` - only the project knows what it returns."""

    module: str
    method: str


class _StaticScope:
    """name -> what is known about its value, or None once the name is poisoned."""

    def __init__(self) -> None:
        self.types: dict[str, _Typed | _Pending | None] = {}
        self.declared: set[str] = set()  # types stated outright - the sibling rule's business
        self.locals: set[str] = set()  # every name the method binds, whatever is known of it

    def declare(self, name: str, tref: P.TypeRef | None, init: P.Expr | None = None) -> None:
        self.locals.add(name)
        nominal = _nominal(tref)
        if nominal is not None:
            info: _Typed | _Pending | None = _Typed(nominal, None)
            self.declared.add(name)
        elif tref is None and init is not None:
            info = self.infer(init)
        else:
            info = None
        if name in self.types and self.types[name] != info:
            self.types[name] = None
        else:
            self.types[name] = info

    def infer(self, expr: P.Expr) -> _Typed | _Pending | None:
        """The type of `Основа.Член` / `Основа.Член(...)`, when the catalog names it.

        A CALL through a base the catalog knows nothing about is kept as pending: the base
        may be another module of the project, and its method's declared return type is only
        available once every file has been mapped.
        """
        is_call = isinstance(expr, P.Call)
        target = expr.callee if is_call else expr
        if not isinstance(target, P.Member) or not isinstance(target.obj, P.Name):
            return None
        base = target.obj.name
        if "::" in base:
            return None
        known = base in self.types
        if known:
            info = self.types[base]
            if not isinstance(info, _Typed):
                return None  # a poisoned name, or a chain over a pending value - one hop only
            base_type, root = info.name, info.root
        else:
            base_type, root = base, base  # a bare name that is not declared: a type name
        raw = _member_types().get(base_type, {}).get(target.name)
        if raw is None:
            if is_call and not known and base_type not in _stdlib_members():
                return _Pending(base, target.name)
            return None
        # The catalog may keep the full docs spelling (М<Т>, Тип?) - the rule judges the
        # members of the nominal head, which is the same set for every parameter.
        member_type = dataset.member_type_head(raw)
        if member_type is None or not _NOMINAL_RE.fullmatch(member_type):
            return None  # a compound head - inference territory, not this rule's
        return _Typed(member_type, root)


def _module_shadow(module: P.Module) -> set[str]:
    """Names the module itself provides - they are never a reference to a stdlib type."""
    names = {imp.name.split("::")[-1] for imp in module.imports}
    for m in module.members:
        name = getattr(m, "name", None)
        if name:
            names.add(name)
    return names


def _pair_names_from_disk(source: SourceFile) -> set[str]:
    """Names of the paired yaml read straight from the module's neighbor on disk.

    A single-file check (`xbsl lint Форма.xbsl`, the editor linting one saved module)
    reaches the reduce with no yaml facts at all, so the form-attribute shadow - "a form
    attribute named Email is not the mail type" - would be lost with the pair. The read
    happens only when the module has candidate findings, so a clean module costs nothing;
    a whole-project run contributes the same names through the reduce anyway.
    """
    return pair_yaml_names(source.path)


def _module_returns(module: P.Module) -> dict[str, str]:
    """Module-level method -> the nominal head of its DECLARED return type.

    Only methods of the module itself: `Модуль.Метод(...)` reaches nothing else in one hop,
    and a static method of a structure would need two. A name declared twice is dropped -
    the compiler rejects that anyway, and the rule must not guess which one was meant.
    """
    result: dict[str, str] = {}
    dupes: set[str] = set()
    for m in module.members:
        if not isinstance(m, P.Method):
            continue
        if m.name in result or m.name in dupes:
            dupes.add(m.name)
            result.pop(m.name, None)
            continue
        nominal = _nominal(m.return_type)
        if nominal is not None:
            result[m.name] = nominal
    return result


def _static_mapper(source: SourceFile) -> dict | None:
    """The map phase: candidate findings of a module, or the names a yaml contributes.

    Everything the file can settle alone is settled here (local declarations, module-level
    names, imports, implicit roots, members that do exist); the reduce only drops candidates
    whose base name the project gives another meaning, resolves the values taken from other
    modules, and computes the spelling hints.
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
    # The callable name of a module is its file stem; dotted stems (object and manager
    # modules) are not reachable as `Имя.Метод(...)` - the same rule as call-arity-cross.
    stem = source.path.name.removesuffix(".xbsl")
    if "." in stem:
        stem = ""
    module, errors = parse(source)
    if errors:
        # A broken file gives no candidates, but its stem must still poison the name.
        return {"stem": stem, "returns": None} if stem else None
    shadow = _module_shadow(module) | _IMPLICIT | _hierarchy_roots()
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
    pending: list[tuple[str, str, str, int, int]] = []
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
                if isinstance(info, _Pending):
                    # `пер Разделы = Разделы.ПолучитьВсе()` names the variable after
                    # the module: within the method the name means both, and the scope is not
                    # flow-sensitive - a name the method binds is never read as a module here.
                    if info.module in shadow or info.module in scope.locals:
                        continue
                    if _is_latin(use.name):
                        continue
                    if lm is None:
                        lm = linemap(source)
                    line, col = lm.linecol(use.start)
                    pending.append((info.module, info.method, use.name, line, col))
                    continue
                type_name, root = info.name, info.root
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
    fact: dict = {"stem": stem, "returns": _module_returns(module) if stem else None}
    if found:
        fact["uses"] = found
    if pending:
        fact["pending"] = pending
    if found or pending:
        pair_names = _pair_names_from_disk(source)
        if pair_names:
            fact["pair_names"] = sorted(pair_names)
    elif not stem:
        return None
    return fact


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

    The same phase resolves a value that came from ANOTHER module (`знч Строки =
    Каталог.Позиции(...)`): every module publishes the return types of its own methods, and
    the base name is matched to a module by its file stem.
    """
    members_by_type = _stdlib_members()
    if not members_by_type:
        return
    global_shadow: set[str] = set()
    paired: dict[str, set[str]] = {}
    # Module name -> {method: return type}; None marks an unusable name (a parse-broken
    # file or twin modules in different directories).
    module_returns: dict[str, dict[str, str] | None] = {}
    for rel, fact in facts.items():
        stem = fact.get("stem")
        if stem:
            returns = fact.get("returns")
            module_returns[stem] = None if (returns is None or stem in module_returns) else returns
        if "names" not in fact:
            continue
        if fact["object"]:
            global_shadow.add(fact["object"])
        paired.setdefault(_pair_key(rel), set()).update(fact["names"])
    for rel, fact in facts.items():
        # pair_names duplicates the paired-yaml facts for runs that do not carry the yaml
        # (a single-file check); in a whole-project run the union is a no-op.
        own_names = paired.get(_pair_key(rel), set()) | set(fact.get("pair_names", ()))
        for base, method, member, line, col in fact.get("pending", ()):
            if base in own_names:
                continue  # a form attribute named like a module: the call is on the attribute
            target = module_returns.get(base)
            if not target:
                continue
            type_name = target.get(method)
            if type_name is None:
                continue  # no such method there, or its return type is not declared
            members = members_by_type.get(type_name)
            if members is None or member in members or member in _COMMON_MEMBERS:
                continue
            hint = difflib.get_close_matches(member, members, n=1, cutoff=0.75)
            message = (
                i18n.t("code/unknown-static-member.found-hint",
                       type=type_name, member=member, hint=hint[0])
                if hint
                else i18n.t("code/unknown-static-member.found", type=type_name, member=member)
            )
            yield Diagnostic(
                rel, line, col, "code/unknown-static-member", Severity.ERROR, message,
            )
        uses = fact.get("uses")
        if not uses:
            continue
        shadow = global_shadow | own_names
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
