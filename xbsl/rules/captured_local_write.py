"""Tier C: assignments after a lambda captures the local binding.

The platform captures values at lambda creation and rejects later writes to the same
local (topics/lambda-expression, context capture). The existing scope walker supplies
binding identity and reads, including string and query interpolation. Capture state
follows lexical branch order, including a later sibling branch. A loop additionally
rechecks writes to bindings that existed before it: a capture below the write freezes
that binding for subsequent iterations. A local declared inside the loop is fresh.

This is a lexical restriction, not a general control-flow analysis. It does not prove
branch conditions, call timing or whether a loop runs more than once. Assignments
inside a lambda to an outer binding belong to lambda-changes-outer-local. Bindings declared by a lambda itself stay mutable after nested capture in the platform
compiler, so only bindings owned by a named method are judged here. Read-only
bindings and mutations of an object's members or elements are left to other checks.
There is no automatic fix: moving an assignment or changing storage can change behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.rules.locals_usage import _Local, _Walk as _LocalWalk, _methods

RULE = "code/captured-local-write"
MESSAGES = {
    f"{RULE}.title": {
        "ru": "Изменение локальной переменной после захвата лямбдой",
        "en": "Local variable changed after lambda capture",
    },
    f"{RULE}.found": {
        "ru": "Локальная переменная '{name}' изменяется после захвата лямбдой, "
              "в том числе при следующем повторении цикла. Платформа запрещает такое "
              "изменение. Завершите изменение до захвата или используйте отдельную "
              "переменную для захватываемого значения.",
        "en": "Local variable '{name}' is changed after a lambda captures it, including "
              "on a later loop iteration. The platform forbids this change. Complete "
              "the changes before capture or use a separate variable for the captured value.",
    },
}
i18n.register(MESSAGES)

_ASSIGNABLE = frozenset({"VAR", "PARAM"})


@dataclass
class _Capture:
    local: _Local
    owner: int
    captured: bool = False


class _CaptureWalk(_LocalWalk):
    """Add capture state to the shared block-scope and interpolation traversal."""

    def analyze(self, method: P.Method) -> list[tuple[int, str]]:
        self.depth = 0
        self.bindings: dict[int, _Capture] = {}
        self.loops: list[tuple[set[int], list[tuple[_Capture, P.Name]]]] = []
        self.found: dict[int, str] = {}
        self.method(method)
        return sorted(self.found.items())

    def _declare(self, kind: str, name: str, at: int, decl: P.VarDecl | None = None,
                 *, bind: bool = True) -> None:
        super()._declare(kind, name, at, decl, bind=bind)
        if name and bind:
            local = self.scopes[-1][name]
            self.bindings[id(local)] = _Capture(local, self.depth)

    def _read(self, name: str) -> None:
        local = self._resolve(name)
        capture = self.bindings.get(id(local))
        if capture is not None and capture.owner < self.depth:
            capture.captured = True

    def _assign(self, stmt: P.Assign) -> None:
        self._expr(stmt.value)
        if not isinstance(stmt.target, P.Name):
            self._expr(stmt.target)
            return
        local = self._resolve(stmt.target.name)
        capture = self.bindings.get(id(local))
        if capture is None:
            return
        if capture.owner < self.depth:
            capture.captured = True
            return
        if capture.owner != 0 or capture.local.kind not in _ASSIGNABLE:
            return
        if capture.captured:
            self.found[stmt.target.start] = stmt.target.name
        for visible, writes in self.loops:
            if id(local) in visible:
                writes.append((capture, stmt.target))

    def _expr(self, expr: P.Expr | None) -> None:
        if not isinstance(expr, P.Lambda):
            return super()._expr(expr)
        self.depth += 1
        super()._expr(expr)
        self.depth -= 1

    def _statement(self, stmt: P.Stmt) -> None:
        if not isinstance(stmt, (P.ForEach, P.ForTo, P.While)):
            return super()._statement(stmt)
        visible = {id(local) for scope in self.scopes for local in scope.values()
                   if self.bindings[id(local)].owner == self.depth}
        writes: list[tuple[_Capture, P.Name]] = []
        self.loops.append((visible, writes))
        super()._statement(stmt)
        self.loops.pop()
        for capture, target in writes:
            if capture.captured:
                self.found[target.start] = target.name


@rule(RULE, f"{RULE}.title", "C", severity=Severity.ERROR)
def captured_local_write(source: SourceFile) -> Iterable[Diagnostic]:
    """Report a mutable local written after capture, with loop reuse accounted for."""
    if source.kind != "xbsl" or is_query_file(source.path) or "->" not in source.text:
        return []
    module, errors = P.parse(source)
    walk = _CaptureWalk(source)
    out = []
    for method in _methods(module):
        if method.is_abstract or any(method.start <= e.start <= method.end for e in errors):
            continue
        for at, name in walk.analyze(method):
            line, col = linemap(source).linecol(at)
            out.append(Diagnostic(source.rel, line, col, RULE, Severity.ERROR,
                                  i18n.t(f"{RULE}.found", name=name)))
    return out
