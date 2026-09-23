"""Tier D: a resolved procedure call used where an expression needs a value.

The rule code/procedure-as-value.

A method with no declared result type is a procedure. Calling it as a statement is legal;
using its missing result in an initializer, argument, return expression or interpolation is a
compiler error. The verdict needs the project method index: a call is reported only when its
target resolves to one own-module or cross-module method and every indexed overload is a
procedure. Unknown, duplicated and mixed procedure/function targets stay silent.

The module trees and method index come from the shared project typing. Rich strings are opaque
atoms in the core parser, so full interpolation expressions alone are parsed as fragments by
the same wrapper pattern used by the ternary rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from xbsl import i18n
from xbsl import parser as P
from xbsl import typeinfer
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_imports import (
    _interpolation_bodies,
    _layout_from,
    _missing_import_mapper,
    _public_scopes,
)

RULE_ID = "code/procedure-as-value"
_WRAP_PREFIX = "method Probe()\n    return "
_WRAP_SUFFIX = "\n;\n"

MESSAGES = {
    f"{RULE_ID}.title": {
        "ru": "Результат процедуры используется как значение",
        "en": "A procedure result is used as a value",
    },
    f"{RULE_ID}.found": {
        "ru": "'{name}' является процедурой без возвращаемого значения, но ее вызов стоит "
              "в контексте значения.",
        "en": "'{name}' is a procedure with no return value, but its call is used in a value "
              "context.",
    },
}
i18n.register(MESSAGES)


def _wants_text(source: SourceFile) -> bool:
    """Whether a parsed module contains any call that may need project resolution."""
    if source.kind != "xbsl" or "(" not in source.text:
        return False
    module, errors = P.parse(source)
    return not errors and (
        any(isinstance(node, P.Call) for node in typeinfer.walk_nodes(module))
        or "%{" in source.text or "${" in source.text
    )


typeinfer.wants_text(_wants_text)


def _mapper(source: SourceFile) -> dict | None:
    """Shared method facts plus the existing namespace-reach fact of this source."""
    method_fact = typeinfer.project_fact(source)
    reach_fact = _missing_import_mapper(source)
    if method_fact is None and reach_fact is None:
        return None
    fact = dict(method_fact or {"k": "procedure-reach"})
    fact["procedure_reach"] = reach_fact
    return fact


class _Reach:
    """Whether a static project module name is visible from one module."""

    def __init__(self, facts: dict[str, dict]) -> None:
        self.facts = facts
        reach = {
            rel: fact["procedure_reach"]
            for rel, fact in facts.items() if fact.get("procedure_reach") is not None
        }
        self.layout = _layout_from(reach)
        self.elements: dict[str, list[dict]] = {}
        for fact in reach.values():
            if fact.get("k") != "el" or not fact.get("name"):
                continue
            place = self.layout.place(Path(fact["path"]))
            self.elements.setdefault(fact["name"], []).append({**fact, "place": place})

    def allows(self, rel: str, module: str) -> bool:
        source = (self.facts.get(rel) or {}).get("procedure_reach") or {}
        if source.get("k") != "mod" or not self.layout.known:
            return False
        owners = self.elements.get(module) or ()
        if len(owners) != 1:
            return False
        target = owners[0]
        source_path, target_path = Path(source["path"]), Path(target["path"])
        mine = self.layout.place(source_path)
        theirs = target["place"]
        if mine is not None and theirs is not None and mine.subsystem == theirs.subsystem:
            return True
        source_root = mine.project_dir if mine is not None else self.layout.project_dir_of(source_path)
        if mine is None and theirs is None:
            target_root = self.layout.project_dir_of(target_path)
            return source_root is not None and source_root == target_root
        if theirs is None or target.get("vis") not in _public_scopes():
            return False
        imports = {self.layout.local_name(name, source_root) for name in source.get("imports", ())}
        return theirs.key in imports


def _results(table: dict, name: str):
    got = table.get(name)
    return got if isinstance(got, list) and got else None


def _is_procedure(table: dict, name: str) -> bool | None:
    """True for procedure-only overloads, False for functions, None when unresolved/mixed."""
    results = _results(table, name)
    if results is None:
        return None
    distinct = set(results)
    if distinct == {None}:
        return True
    if None not in distinct:
        return False
    return None


def _method_shadows(method: P.Method) -> frozenset[str]:
    names = {param.name for param in method.params}
    for node in typeinfer.walk_nodes(method):
        if isinstance(node, P.VarDecl):
            names.add(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.add(node.var)
        elif isinstance(node, P.Try):
            names.update(name for name, _type, _body in node.catches if name)
        elif isinstance(node, P.Lambda):
            names.update(param.name for param in node.params)
    names.discard("")
    return frozenset(names)


def _safe_call_starts(tree: object) -> set[int]:
    """Calls whose result is discarded: statements, `use`, and procedure-lambda bodies."""
    safe: set[int] = set()
    for node in typeinfer.walk_nodes(tree):
        if isinstance(node, (P.ExprStmt, P.UseStmt)) and isinstance(node.expr, P.Call):
            safe.add(node.expr.start)
        elif isinstance(node, P.VarDecl) and node.kind == "USE" and isinstance(node.init, P.Call):
            safe.add(node.init.start)
        elif isinstance(node, P.Lambda) and isinstance(node.body_expr, P.Call):
            safe.add(node.body_expr.start)
    return safe


def _owner_methods(owner: P.Structure | P.Enum | None) -> dict[str, list[str | None]]:
    if owner is None:
        return {}
    members = owner.members if isinstance(owner, P.Structure) else owner.methods
    out: dict[str, list[str | None]] = {}
    for member in members:
        if isinstance(member, P.Method):
            written = member.return_type.text.strip() if member.return_type is not None else None
            out.setdefault(member.name, []).append(written)
    return out


def _module_names(typing: typeinfer.ModuleTyping) -> frozenset[str]:
    module = typing.catalog.modules.get(typing.scope.module or "") or {}
    return frozenset({
        *(module.get("methods") or {}),
        *(module.get("structures") or {}),
        *(module.get("enums") or {}),
        *(module.get("fields") or {}),
        *typing.scope.own_properties,
        *typing.scope.opaque,
    })


def _resolve(
    typing: typeinfer.ModuleTyping,
    call: P.Call,
    shadows: frozenset[str],
    owner_methods: dict[str, list[str | None]],
    reach: _Reach,
) -> tuple[str, str] | None:
    """The indexed procedure target of a bare or static project-module call."""
    callee = call.callee
    mine = typing.scope.module or ""
    if isinstance(callee, P.Name):
        if callee.name in shadows or "::" in callee.name:
            return None
        if callee.name in owner_methods:
            owner_verdict = _is_procedure(owner_methods, callee.name)
            return (mine, callee.name) if owner_verdict is True else None
        methods = (typing.catalog.modules.get(mine) or {}).get("methods") or {}
        return (mine, callee.name) if _is_procedure(methods, callee.name) is True else None
    if not (isinstance(callee, P.Member) and isinstance(callee.obj, P.Name) and not callee.safe):
        return None
    module = callee.obj.name
    if "::" in module or module in shadows or module in _module_names(typing):
        return None
    if not reach.allows(typing.rel, module):
        return None
    methods = (typing.catalog.modules.get(module) or {}).get("methods") or {}
    return (module, callee.name) if _is_procedure(methods, callee.name) is True else None


def _interpolation_calls(literal: P.Literal) -> Iterable[tuple[int, P.Call]]:
    """Calls in full interpolations, with offsets in the containing module."""
    for offset, body in _interpolation_bodies(literal.text, blank_strings=False):
        wrapped = _WRAP_PREFIX + body + _WRAP_SUFFIX
        tree, errors = P.parse_text(wrapped)
        if errors:
            continue
        safe = _safe_call_starts(tree)
        for node in typeinfer.walk_nodes(tree):
            if isinstance(node, P.Call) and node.start not in safe:
                yield literal.start + offset + node.start - len(_WRAP_PREFIX), node


def _method_findings(
    typing: typeinfer.ModuleTyping,
    method: P.Method,
    owner: P.Structure | P.Enum | None,
    reach: _Reach,
) -> Iterable[tuple[int, tuple[str, str]]]:
    owner_fields = {
        member.name for member in (owner.members if isinstance(owner, P.Structure) else ())
        if isinstance(member, P.ObjectField)
    }
    shadows = frozenset(set(_method_shadows(method)) | owner_fields)
    owner_methods = _owner_methods(owner)
    safe = _safe_call_starts(method)
    yield from _node_findings(typing, method, shadows, owner_methods, reach, safe)


def _node_findings(
    typing: typeinfer.ModuleTyping,
    root: object,
    shadows: frozenset[str],
    owner_methods: dict[str, list[str | None]],
    reach: _Reach,
    safe: set[int] | None = None,
) -> Iterable[tuple[int, tuple[str, str]]]:
    safe = safe or set()
    for node in typeinfer.walk_nodes(root):
        if isinstance(node, P.Call) and node.start not in safe:
            target = _resolve(typing, node, shadows, owner_methods, reach)
            if target is not None:
                yield node.start, target
        elif isinstance(node, P.Literal) and node.kind == "STRING":
            for offset, call in _interpolation_calls(node):
                target = _resolve(typing, call, shadows, owner_methods, reach)
                if target is not None:
                    yield offset, target


def _findings(
    typing: typeinfer.ModuleTyping, reach: _Reach,
) -> Iterable[tuple[int, tuple[str, str]]]:
    tree = typing.tree
    if not isinstance(tree, P.Module):
        return
    for member in tree.members:
        if isinstance(member, P.Method):
            yield from _method_findings(typing, member, None, reach)
        elif isinstance(member, P.ObjectField) and member.init is not None:
            yield from _node_findings(typing, member.init, frozenset(), {}, reach)
        elif isinstance(member, P.Structure):
            for inner in member.members:
                if isinstance(inner, P.Method):
                    yield from _method_findings(typing, inner, member, reach)
                elif isinstance(inner, P.ObjectField) and inner.init is not None:
                    owner_fields = frozenset(
                        field.name for field in member.members if isinstance(field, P.ObjectField)
                    )
                    yield from _node_findings(
                        typing, inner.init, owner_fields, _owner_methods(member), reach,
                    )
        elif isinstance(member, P.Enum):
            for inner in member.methods:
                yield from _method_findings(typing, inner, member, reach)


@rule(
    RULE_ID, f"{RULE_ID}.title", "D", scope="project", severity=Severity.ERROR,
    mapper=_mapper,
)
def procedure_as_value(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A uniquely resolved project procedure call used where a value is required."""
    reach = _Reach(facts)
    for rel, typing in typeinfer.project_typings(facts).items():
        line_map = None
        for offset, (module, method) in _findings(typing, reach):
            if line_map is None:
                line_map = linemap(_TextSource(typing.text))
            line, column = line_map.linecol(offset)
            name = method if module == typing.scope.module else f"{module}.{method}"
            yield Diagnostic(
                rel, line, column, RULE_ID, Severity.ERROR,
                i18n.t(f"{RULE_ID}.found", name=name),
            )


class _TextSource:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cache: dict = {}
