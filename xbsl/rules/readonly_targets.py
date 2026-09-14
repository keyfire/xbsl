"""Tier C: an assignment to a name that can only be read.

The compiler binds the name on the left of `=`, `+=`, `-=`, `*=`, `/=` and refuses the
assignment when the binding is read-only - a compile error, so the server refuses the build and
the stand keeps running the previous one. Which bindings are read-only, the file alone tells
(the forms and their controls were probed against the IDE language server):

- a local declared with `знч`, and a resource declared with `исп`;
- the variable of a loop, `для Х из ...` and `для Х = А по Б` alike; a loop always declares a
  new name (reusing a name already in scope is an error of its own);
- the variable of `поймать`;
- a module constant;
- a `знч` field of a structure, assigned in a method of that structure by its bare name or
  through `этот`.

A parameter of a method or of a lambda is writable, and so is a `пер` field. Names are resolved
through the block scopes the compiler uses: the innermost declaration wins, a sibling branch has
a scope of its own, a local hides a field of the same name, and letter case counts. A read-only
local stays read-only inside a lambda: the IDE names that assignment with this same complaint,
not as the change of a captured variable.

A field reached through another receiver (`Я.Метка = ...`) needs the type of the receiver, and a
property of a form or an object is declared in yaml - both are left to the compiler.

The one mechanical cure is for a local `знч` the method goes on to change: the declaration
becomes `пер`. It is not offered when a lambda of the method mentions the name - a captured
variable may not change either, and the fix would only trade one compile error for another.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache, lru_cache

from xbsl import dataset, i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._typesets import walk_nodes

MESSAGES = {
    "code/assign-readonly.title": {
        "ru": "Присваивание переменной только для чтения",
        "en": "Assignment to a read-only name",
    },
    "code/assign-readonly.val": {
        "ru": "Переменная '{name}' объявлена через 'знч' и доступна только для чтения – "
              "присваивание не скомпилируется. Если значение должно меняться, объявите "
              "переменную через 'пер'.",
        "en": "Variable '{name}' is declared with '{n[знч]}' and can only be read - the "
              "assignment does not compile. If the value has to change, declare the variable "
              "with '{n[пер]}'.",
    },
    "code/assign-readonly.use": {
        "ru": "Переменная '{name}' объявлена через 'исп' и доступна только для чтения: ресурс "
              "закроется в конце области видимости, заменить его нельзя. Для другого ресурса "
              "заведите отдельную переменную.",
        "en": "Variable '{name}' is declared with '{n[исп]}' and can only be read: the resource "
              "is closed at the end of the scope and cannot be replaced. Declare a separate "
              "variable for another resource.",
    },
    "code/assign-readonly.loop": {
        "ru": "'{name}' – переменная цикла 'для', она доступна только для чтения. Чтобы менять "
              "значение внутри цикла, скопируйте его в переменную 'пер'.",
        "en": "'{name}' is the variable of a '{n[для]}' loop and can only be read. To change the "
              "value inside the loop, copy it into a '{n[пер]}' variable.",
    },
    "code/assign-readonly.catch": {
        "ru": "'{name}' – переменная секции 'поймать', она доступна только для чтения. Для "
              "другого исключения заведите отдельную переменную.",
        "en": "'{name}' is the variable of a '{n[поймать]}' section and can only be read. "
              "Declare a separate variable for another exception.",
    },
    "code/assign-readonly.const": {
        "ru": "'{name}' – константа модуля, её значение не меняется. Для изменяемого значения "
              "нужна переменная метода.",
        "en": "'{name}' is a module constant, its value does not change. A changing value "
              "needs a variable of the method.",
    },
    "code/assign-readonly.field": {
        "ru": "Поле '{name}' объявлено через 'знч' и доступно только для чтения: значение "
              "задаётся при создании структуры. Если поле должно меняться, объявите его через "
              "'пер'.",
        "en": "Field '{name}' is declared with '{n[знч]}' and can only be read: the value is "
              "set when the structure is created. If the field has to change, declare it with "
              "'{n[пер]}'.",
    },
}
i18n.register(MESSAGES)

#: Binding kinds that refuse an assignment, by the message that explains each.
_READONLY = {
    "VAL": "val", "USE": "use", "LOOP": "loop", "CATCH": "catch", "CONST": "const",
    "FIELD": "field",
}
_WORD = re.compile(r"\w+")
#: Expressions with nothing inside that could assign a name or declare one.
_LEAVES = (P.Name, P.Literal, P.This, P.GlobalAccess, P.MethodRef)


@cache
def _node_fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


@dataclass
class _Binding:
    kind: str  # VAL | VAR | USE | LOOP | CATCH | CONST | FIELD, or WRITABLE for the rest
    decl: P.VarDecl | None = None


@dataclass
class _Finding:
    binding: _Binding
    name: str
    at: int  # the offset of the name on the left side


class _Walk:
    """Binds the names of one method to their declarations, scope by scope."""

    def __init__(self, outer: list[dict[str, _Binding]]) -> None:
        self.scopes = outer
        self.findings: list[_Finding] = []
        self.fields: dict[str, _Binding] = {}

    def _resolve(self, name: str) -> _Binding | None:
        for scope in reversed(self.scopes):
            binding = scope.get(name)
            if binding is not None:
                return binding
        return None

    def _declare(self, name: str, binding: _Binding) -> None:
        if name:
            self.scopes[-1][name] = binding

    def block(self, stmts: list[P.Stmt], *names: tuple[str, _Binding]) -> None:
        self.scopes.append({})
        for name, binding in names:
            self._declare(name, binding)
        for st in stmts:
            self.statement(st)
        self.scopes.pop()

    def statement(self, st: P.Stmt) -> None:
        if isinstance(st, P.VarDecl):
            self.expr(st.init)
            self._declare(st.name, _Binding(st.kind, st))
        elif isinstance(st, P.Assign):
            self.assign(st)
        elif isinstance(st, P.If):
            for cond, body in st.branches:
                self.expr(cond)
                self.block(body)
            if st.else_body is not None:
                self.block(st.else_body)
        elif isinstance(st, P.Case):
            self.expr(st.subject)
            for when in st.whens:
                for cond in when.conditions:
                    self.expr(cond)
                self.block(when.body)
            if st.else_body is not None:
                self.block(st.else_body)
        elif isinstance(st, P.While):
            self.expr(st.cond)
            self.block(st.body)
        elif isinstance(st, P.ForEach):
            self.expr(st.source)
            self.block(st.body, (st.var, _Binding("LOOP")))
        elif isinstance(st, P.ForTo):
            for part in (st.start_expr, st.to, st.step):
                self.expr(part)
            self.block(st.body, (st.var, _Binding("LOOP")))
        elif isinstance(st, P.Try):
            self.block(st.body)
            for var, _type, body in st.catches:
                self.block(body, (var, _Binding("CATCH")))
            if st.finally_body is not None:
                self.block(st.finally_body)
        elif isinstance(st, P.Scope):
            self.block(st.body)
        else:  # an expression statement, a use statement, a return
            for name in _node_fields(type(st)):
                self._value(getattr(st, name))

    def assign(self, st: P.Assign) -> None:
        target = st.target
        if isinstance(target, P.Name) and "::" not in target.name:
            binding = self._resolve(target.name)
            if binding is not None and binding.kind in _READONLY:
                self.findings.append(_Finding(binding, target.name, target.start))
        elif (isinstance(target, P.Member) and isinstance(target.obj, P.This)
              and not target.safe):
            binding = self.fields.get(target.name)
            if binding is not None and binding.kind in _READONLY:
                self.findings.append(_Finding(binding, target.name, target.end - len(target.name)))
        else:
            self.expr(target)
        self.expr(st.value)

    def expr(self, e: P.Expr | None) -> None:
        if e is None or isinstance(e, _LEAVES):
            return
        if isinstance(e, P.Lambda):
            self.scopes.append({})
            for param in e.params:
                self._declare(param.name, _Binding("WRITABLE"))
            if isinstance(e.body_expr, P.Assign):
                self.assign(e.body_expr)
            else:
                self.expr(e.body_expr)
            if e.body_stmts is not None:
                for st in e.body_stmts:
                    self.statement(st)
            self.scopes.pop()
            return
        for name in _node_fields(type(e)):
            self._value(getattr(e, name))

    def _value(self, value: object) -> None:
        if isinstance(value, P.Expr):
            self.expr(value)
        elif isinstance(value, P.Stmt):
            self.statement(value)
        elif isinstance(value, P.CallArg):
            self.expr(value.value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._value(item)


def _methods(module: P.Module) -> Iterable[tuple[P.Method, P.Structure | None]]:
    for member in module.members:
        if isinstance(member, P.Method):
            yield member, None
        elif isinstance(member, P.Structure):
            for sub in member.members:
                if isinstance(sub, P.Method):
                    yield sub, member
        elif isinstance(member, P.Enum):
            for sub in member.methods:
                yield sub, None


def _fields(owner: P.Structure | None, method: P.Method) -> dict[str, _Binding]:
    """The fields a method of a structure reaches by a bare name or through `этот`."""
    if owner is None or method.is_static:
        return {}
    return {m.name: _Binding("FIELD" if m.kind == "VAL" else "WRITABLE")
            for m in owner.members if isinstance(m, P.ObjectField) and m.name}


@lru_cache(maxsize=1)
def _mutable_spelling() -> dict[str, str]:
    """`знч` -> `пер` in the language the declaration is written in, from the grammar data."""
    keywords = dataset.load_json("language.json")["keywords"]
    val, var = keywords["VAL"]["forms"], keywords["VAR"]["forms"]
    by_script = {form.isascii(): form for form in var}
    return {form: by_script[form.isascii()] for form in val if form.isascii() in by_script}


dataset.register_reset(_mutable_spelling.cache_clear)


def _mutable_fix(source: SourceFile, method: P.Method, finding: _Finding) -> TextEdit | None:
    decl = finding.binding.decl
    if finding.binding.kind != "VAL" or decl is None:
        return None
    for node in walk_nodes(method.body):
        if isinstance(node, P.Lambda) and any(
            isinstance(inner, P.Name) and inner.name == finding.name for inner in walk_nodes(node)
        ):
            return None
    word = _WORD.match(source.text, decl.start)
    replacement = _mutable_spelling().get(word.group(0)) if word else None
    if replacement is None:
        return None
    return TextEdit(word.start(), word.end(), replacement)


@rule("code/assign-readonly", "code/assign-readonly.title", "C", severity=Severity.ERROR)
def assign_readonly(source: SourceFile) -> Iterable[Diagnostic]:
    """A value assigned to a name that can only be read - the compiler rejects it."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    constants = {m.name: _Binding("CONST") for m in module.members
                 if isinstance(m, P.ObjectField) and m.kind == "CONST" and m.name}
    lm = linemap(source)
    for method, owner in _methods(module):
        if method.is_abstract:
            continue
        fields = _fields(owner, method)
        params = {p.name: _Binding("WRITABLE") for p in method.params if p.name}
        walk = _Walk([constants, fields, params])
        walk.fields = fields
        walk.block(method.body)
        for finding in walk.findings:
            line, col = lm.linecol(finding.at)
            yield Diagnostic(
                source.rel, line, col, "code/assign-readonly", Severity.ERROR,
                i18n.t(f"code/assign-readonly.{_READONLY[finding.binding.kind]}",
                       name=finding.name),
                fix=_mutable_fix(source, method, finding),
            )
