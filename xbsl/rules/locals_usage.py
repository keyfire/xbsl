"""Tier C-2: unused local variables and loop variables.

The two rules reproduce a warning of the platform's language server: `Неиспользуемая переменная`
(diagnostic code UNUSED_VARIABLE, catalog keys `unused_variable__0` and
`only_assign_variable__0`) - the check the IDE runs while it binds the names of a method body.
What counts, as the IDE counts it (probed against the IDE on a project of its own):

- tracked are the locals declared by `знч`, `пер` and `исп`, and the variable of a
  `для Х из ...` loop. Not reported as unused variables: the variable of `для Х = А по Б`,
  the variable of `поймать`, the parameters of a lambda and the parameters of a method;
- a reference that resolves to the declaration and is not the direct target of an
  assignment is a READ and makes the variable used. A read counts wherever it stands: in a
  lambda body (a closure), in a string interpolation (`%Имя`, `%{...}`, `${...}`), in the
  interpolation of a query literal;
- a variable that is only ever assigned (`Х = ...`, `Х += ...`) is reported with a message
  of its own: the value is stored and never read;
- names are resolved through the block scopes the compiler uses (topics/name-scope): a
  variable of one branch is not the variable of a sibling branch with the same name, and a
  named argument `Имя = значение` or a member `.Имя` is not a reference at all.

The walk runs over the parser's tree, not over the token stream. A token count cannot tell
the scopes apart and, worse, cannot tell the end of a block from a `;` inside a query
literal: a batch query (`ВЫБРАТЬ ... ПОМЕСТИТЬ ... ;`) used to cut the method short, and a
variable read after the query was reported as never read.

An unused `исп` variable has a mechanical cure. The grammar has a use statement over an
expression (`исп Выражение`, the form the docs show for `КонтекстДоступа.Привилегированный()`),
and the resource it opens is closed at the end of the same scope - so the fix drops the name
and keeps the statement. Deleting the declaration instead would delete the resource: the
localization context, the access context or the transaction the statement opens.

A method the parser could not read in full is skipped: a read lost to the error recovery
would turn into a false "never used".
"""

from __future__ import annotations

import dataclasses
import re
from bisect import bisect_left
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token, _skip_interpolation, tokenize, tokens
from xbsl.parser import parse

MESSAGES = {
    "code/unused-local.title": {
        "ru": "Неиспользуемая локальная переменная",
        "en": "Unused local variable",
    },
    "code/unused-local.declared": {
        "ru": "Локальная переменная '{name}' объявлена, но не используется.",
        "en": "Local variable '{name}' is declared but not used.",
    },
    "code/unused-local.only-assigned": {
        "ru": "Локальной переменной '{name}' только присваивается значение, но оно нигде не "
              "читается.",
        "en": "Local variable '{name}' is only assigned: its value is never read.",
    },
    "code/unused-local.use-name": {
        "ru": "Имя '{name}' ресурса '{n[исп]}' нигде не используется. Ресурс нужен только на "
              "время области видимости, и '{n[исп]}' без имени закроет его так же: "
              "'{n[исп]} <выражение>'.",
        "en": "The name '{name}' of the '{n[исп]}' resource is never used. The resource only "
              "has to live through the scope, and an unnamed '{n[исп]}' closes it the same "
              "way: '{n[исп]} <expression>'.",
    },
    "code/unused-loop-var.title": {
        "ru": "Неиспользуемая переменная цикла",
        "en": "Unused loop variable",
    },
    "code/unused-loop-var.unused": {
        "ru": "Переменная цикла '{name}' не используется.",
        "en": "Loop variable '{name}' is not used.",
    },
}
i18n.register(MESSAGES)

# Declarations the rules report: the three variable kinds and the `для Х из` loop variable.
_DECLARED = frozenset({"VAL", "VAR", "USE"})
_LOOP = "FOR"
_TRACKED = _DECLARED | {_LOOP}
# The member operators: a name right after one of them is a member, not a variable.
_MEMBER_OPS = frozenset({".", "?."})
_NAME_RE = re.compile(r"[^\W\d]\w*", re.UNICODE)


@dataclass
class _Local:
    """A name a method body binds, and what the body does with it."""

    kind: str  # VAL | VAR | USE | FOR, or an untracked PARAM | LOOP_TO | CATCH | LAMBDA
    name: str
    anchor: Token | None
    decl: P.VarDecl | None = None
    read: bool = False
    assigned: bool = False


def _is_name_token(tok: Token) -> bool:
    """An identifier, or a keyword spelled as a name (`Query`, `Type` may name a variable)."""
    return tok.kind == "IDENT" or (tok.kind == "KEYWORD" and tok.value[:1].isupper())


def _token_reads(toks: list[Token]) -> list[str]:
    """Names an interpolated expression reads, from its tokens.

    A member after `.`/`?.` and a named argument label (`(Имя = ...`, `, Имя = ...`) are
    not reads; a nested string contributes its own interpolations.
    """
    out: list[str] = []
    for k, tok in enumerate(toks):
        if tok.kind == "STRING":
            out.extend(_string_reads(tok.value))
            continue
        if not _is_name_token(tok):
            continue
        prev = toks[k - 1] if k else None
        if prev is not None and prev.kind == "OP" and prev.value in _MEMBER_OPS:
            continue
        nxt = toks[k + 1] if k + 1 < len(toks) else None
        if (nxt is not None and nxt.kind == "OP" and nxt.value == "="
                and prev is not None and prev.kind == "OP" and prev.value in ("(", ",")):
            continue
        out.append(tok.value)
    return out


@lru_cache(maxsize=8192)
def _string_reads(value: str) -> tuple[str, ...]:
    """Names the interpolations of a string literal read: `%Имя`, `$Имя`, `%{...}`, `${...}`."""
    out: list[str] = []
    i, n = 0, len(value)
    while i < n:
        c = value[i]
        if c == "\\":
            i += 2
            continue
        if c in "%$" and i + 1 < n:
            if value[i + 1] == "{":
                end = _skip_interpolation(value, i + 2)
                inner = value[i + 2:max(i + 2, end - 1)]
                code = [t for t in tokenize(inner) if t.kind not in ("COMMENT", "BOM", "EOF")]
                out.extend(_token_reads(code))
                i = end
                continue
            m = _NAME_RE.match(value, i + 1)
            if m is not None:
                out.append(m.group(0))
                i = m.end()
                continue
        i += 1
    return tuple(out)


class _Walk:
    """Binds the names of one file's method bodies to their declarations, scope by scope."""

    def __init__(self, source: SourceFile) -> None:
        self.code = [t for t in tokens(source) if t.kind not in ("COMMENT", "BOM")]
        self.starts = [t.start for t in self.code]
        self.scopes: list[dict[str, _Local]] = []
        self.tracked: list[_Local] = []

    # --- names ------------------------------------------------------------------------

    def _name_token(self, at: int, name: str) -> Token | None:
        """The token of `name` in the first few tokens from offset `at` (the keyword)."""
        i = bisect_left(self.starts, at)
        for tok in self.code[i:i + 4]:
            if tok.value == name and _is_name_token(tok):
                return tok
        return None

    def _resolve(self, name: str) -> _Local | None:
        for scope in reversed(self.scopes):
            local = scope.get(name)
            if local is not None:
                return local
        return None

    def _declare(self, kind: str, name: str, at: int, decl: P.VarDecl | None = None) -> None:
        if not name:
            return
        anchor = self._name_token(at, name) if kind in _TRACKED else None
        local = _Local(kind, name, anchor, decl)
        self.scopes[-1][name] = local
        if kind in _TRACKED:
            self.tracked.append(local)

    def _read(self, name: str) -> None:
        local = self._resolve(name)
        if local is not None:
            local.read = True

    def _loop_variable(self, kind: str, name: str, at: int) -> None:
        """The variable of a loop: a new name of the loop scope - or an outer local the loop
        assigns, when the name is already bound (a loop over an existing variable)."""
        outer = self._resolve(name) if name else None
        if outer is not None:
            outer.assigned = True
        else:
            self._declare(kind, name, at)

    # --- a method ---------------------------------------------------------------------

    def method(self, method: P.Method) -> list[_Local]:
        self.scopes = [{}]
        self.tracked = []
        for param in method.params:
            self._declare("PARAM", param.name, param.start)
        self._statements(method.body)
        return self.tracked

    def _block(self, stmts: list[P.Stmt]) -> None:
        self.scopes.append({})
        self._statements(stmts)
        self.scopes.pop()

    def _statements(self, stmts: list[P.Stmt]) -> None:
        for stmt in stmts:
            self._statement(stmt)

    def _statement(self, st: P.Stmt) -> None:
        if isinstance(st, P.VarDecl):
            self._expr(st.init)  # a variable cannot be read in its own initializer
            self._declare(st.kind, st.name, st.start, st)
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
        elif isinstance(st, P.ForEach):
            self._expr(st.source)
            self.scopes.append({})
            self._loop_variable(_LOOP, st.var, st.start)
            self._statements(st.body)
            self.scopes.pop()
        elif isinstance(st, P.ForTo):
            self._expr(st.start_expr)
            self._expr(st.to)
            self._expr(st.step)
            self.scopes.append({})
            self._loop_variable("LOOP_TO", st.var, st.start)
            self._statements(st.body)
            self.scopes.pop()
        elif isinstance(st, P.Try):
            self._block(st.body)
            for var, _type, body in st.catches:
                self.scopes.append({})
                self._declare("CATCH", var, st.start)
                self._statements(body)
                self.scopes.pop()
            if st.finally_body is not None:
                self._block(st.finally_body)
        elif isinstance(st, P.Scope):
            self._block(st.body)
        elif dataclasses.is_dataclass(st) and not isinstance(st, (P.Break, P.Continue)):
            # A statement the parser grows later: whatever it holds is still read.
            self.scopes.append({})
            for f in dataclasses.fields(st):
                self._walk_value(getattr(st, f.name))
            self.scopes.pop()

    def _assign(self, st: P.Assign) -> None:
        # Only a bare name on the left is written; `Х.Поле = ...` and `Х[0] = ...` read Х.
        if isinstance(st.target, P.Name) and st.value is not None:
            local = self._resolve(st.target.name)
            if local is not None:
                local.assigned = True
        else:
            self._expr(st.target)
        self._expr(st.value)

    # --- expressions ------------------------------------------------------------------

    def _expr(self, e: P.Expr | None) -> None:
        if e is None:
            return
        if isinstance(e, P.Name):
            self._read(e.name)
        elif isinstance(e, P.Literal):
            if e.kind == "STRING":
                for name in _string_reads(e.text):
                    self._read(name)
            elif e.kind == "QUERY":
                self._query(e.start, e.end)
        elif isinstance(e, P.Member):
            self._expr(e.obj)
        elif isinstance(e, P.Call):
            self._expr(e.callee)
            for arg in e.args:
                self._expr(arg.value)
        elif isinstance(e, P.New):
            for arg in e.args or ():
                self._expr(arg.value)
        elif isinstance(e, P.Lambda):
            self.scopes.append({})
            for param in e.params:
                self._declare("LAMBDA", param.name, param.start)
            if isinstance(e.body_expr, P.Assign):
                self._assign(e.body_expr)
            else:
                self._expr(e.body_expr)
            if e.body_stmts is not None:
                self._statements(e.body_stmts)
            self.scopes.pop()
        elif isinstance(e, (P.This, P.GlobalAccess, P.MethodRef)):
            return  # a method reference starts with a type, never with a local
        else:
            # Every other expression reads whatever its sub-expressions read. The fields are
            # walked generically, so a node the parser grows later cannot hide a read.
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

    def _query(self, start: int, end: int) -> None:
        """Reads of a query literal: `%Имя` and the names of `%{...}`."""
        code, n = self.code, len(self.code)
        i = bisect_left(self.starts, start)
        while i < n and code[i].start < end:
            tok = code[i]
            if tok.kind == "OP" and tok.value == "%" and i + 1 < n:
                nxt = code[i + 1]
                if _is_name_token(nxt):
                    self._read(nxt.value)
                    i += 2
                    continue
                if nxt.kind == "OP" and nxt.value == "{":
                    depth, j = 1, i + 2
                    while j < n:
                        if code[j].kind == "OP" and code[j].value in ("{", "}"):
                            depth += 1 if code[j].value == "{" else -1
                            if depth == 0:
                                break
                        j += 1
                    for name in _token_reads(code[i + 2:j]):
                        self._read(name)
                    i = j + 1
                    continue
            elif tok.kind == "STRING":
                for name in _string_reads(tok.value):
                    self._read(name)
            i += 1


def _methods(module: P.Module) -> Iterable[P.Method]:
    """The methods with a body: of the module, of its structures and enumerations."""
    for member in module.members:
        if isinstance(member, P.Method):
            yield member
        elif isinstance(member, P.Structure):
            yield from (m for m in member.members if isinstance(m, P.Method))
        elif isinstance(member, P.Enum):
            yield from member.methods


def _analysis(source: SourceFile) -> list[_Local]:
    """The tracked locals of every method of the file that were never read (cached)."""
    cached = source.cache.get("locals_usage")
    if cached is not None:
        return cached
    module, errors = parse(source)
    walk = _Walk(source)
    result: list[_Local] = []
    for method in _methods(module):
        if method.is_abstract:
            continue
        if any(method.start <= err.start <= method.end for err in errors):
            continue
        result.extend(local for local in walk.method(method) if not local.read)
    source.cache["locals_usage"] = result
    return result


def _use_fix(source: SourceFile, local: _Local) -> TextEdit | None:
    """`исп Имя = Выражение` -> `исп Выражение`, when nothing but `=` stands between the two."""
    decl, anchor = local.decl, local.anchor
    if decl is None or anchor is None or decl.type is not None or decl.init is None:
        return None
    between = source.text[anchor.end:decl.init.start]
    if between.strip() != "=":
        return None
    return TextEdit(anchor.start, decl.init.start, "")


def _applies(source: SourceFile) -> bool:
    return source.kind == "xbsl" and not is_query_file(source.path)


@rule("code/unused-local", "code/unused-local.title", "C", severity=Severity.WARNING)
def unused_local(source: SourceFile) -> Iterable[Diagnostic]:
    if not _applies(source):
        return []
    diags: list[Diagnostic] = []
    for local in _analysis(source):
        if local.kind not in _DECLARED or local.anchor is None:
            continue
        fix = None
        if local.assigned:
            key = "code/unused-local.only-assigned"
        elif local.kind == "USE":
            key = "code/unused-local.use-name"
            fix = _use_fix(source, local)
        else:
            key = "code/unused-local.declared"
        diags.append(Diagnostic(
            source.rel, local.anchor.line, local.anchor.col,
            "code/unused-local", Severity.WARNING,
            i18n.t(key, name=local.name), fix=fix,
        ))
    return diags


@rule("code/unused-loop-var", "code/unused-loop-var.title", "C", severity=Severity.WARNING)
def unused_loop_var(source: SourceFile) -> Iterable[Diagnostic]:
    # The variable of a `для Х из` loop that the body never reads. The counter of
    # `для Х = А по Б` is not reported: the IDE does not track it either.
    if not _applies(source):
        return []
    return [
        Diagnostic(
            source.rel, local.anchor.line, local.anchor.col,
            "code/unused-loop-var", Severity.WARNING,
            i18n.t("code/unused-loop-var.unused", name=local.name),
        )
        for local in _analysis(source)
        if local.kind == _LOOP and local.anchor is not None
    ]
