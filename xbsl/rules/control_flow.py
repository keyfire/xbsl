"""Tier C: control flow the compiler rejects - code nothing reaches, a jump with nowhere to go.

Both are compile errors: the server refuses the build and the stand keeps running the previous
one. The semantics below were taken from the IDE language server on probe projects, form by
form, together with the variants it accepts.

`code/unreachable-statement` - a statement that follows, in the same block, a statement which
always ends the block:

- `возврат`, `прервать`, `продолжить` and an expression statement `выбросить ...`;
- a call of a method whose result type is `никогда` - only a method declared in this file, and
  only when every method of that name within reach is one (an overload may return, and a local
  or a parameter of the same name may be the thing called);
- `если` with `иначе` where every branch ends, `попытка` whose body and every `поймать` end (the
  `вконце` section does not count), `выбор` with `иначе` where every branch ends, `область` whose
  body ends. A branch ends when ANY of its statements ends it, not only the last one.

A loop never ends the block it stands in: `пока Истина` with a `возврат` inside is followed by
reachable code as far as the compiler is concerned. Every ending statement reports the one right
after it, so `возврат 1` / `возврат 2` / `возврат 3` gives two findings, while `возврат` followed
by two assignments gives one. A comment is not a statement.

Two more places are unreachable by the same logic: a declaration and an assignment whose value is
such a call or a `выбросить` (`знч Х = Никогда()`, `Х = Никогда()`) - the finding stands on the
declaration or on the target, and the statement after it is not reported.

A `выбор` without `иначе` ends the block as well when its branches name every value the switched
one may take: all items of an enumeration, both boolean literals, the very type of the value in
`когда это`. The rule takes the type from the file alone - `выбор этот` in a method of an
enumeration, or a subject every declaration of which writes it: an enumeration declared in this
file, a non-nullable `Boolean`, a single non-nullable type met by a `когда это` among conditions
that are all type tests. A subject typed anywhere else is taken as a branch that may fall
through: the rule misses the code after it rather than guessing.

`code/misplaced-jump` - `прервать` or `продолжить` with no loop around it, and `возврат`,
`прервать` or `продолжить` inside a `вконце` section. The compiler counts the loops of the whole
method, lambdas included: `прервать` in a lambda body inside a loop is accepted, the same lambda
outside any loop is not. A `вконце` section is looked for from the statement outwards up to the
method - through lambdas as well - and for `прервать`/`продолжить` only up to the nearest loop:
a loop inside `вконце` may be left freely. `выбросить` is allowed in `вконце`. A jump that is both
outside a loop and inside `вконце` is reported once, as the one outside a loop.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable, Iterator
from functools import cache, lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules._typesets import walk_nodes

MESSAGES = {
    "code/unreachable-statement.title": {
        "ru": "Код, до которого не доходит выполнение",
        "en": "Code that execution never reaches",
    },
    "code/unreachable-statement.after-exit": {
        "ru": "Сюда выполнение не доходит: '{word}' выше всегда завершает блок, и компилятор "
              "отвергает код после него. Удалите этот код либо перенесите выход.",
        "en": "Execution never gets here: '{word}' above always ends the block, and the compiler "
              "rejects the code after it. Delete this code or move the exit.",
    },
    "code/unreachable-statement.after-branches": {
        "ru": "Сюда выполнение не доходит: каждая ветвь '{word}' выше завершает блок, и "
              "компилятор отвергает код после него. Удалите этот код либо оставьте ветвь, после "
              "которой выполнение продолжается.",
        "en": "Execution never gets here: every branch of '{word}' above ends the block, and the "
              "compiler rejects the code after it. Delete this code or leave a branch that "
              "carries on.",
    },
    "code/unreachable-statement.after-never": {
        "ru": "Сюда выполнение не доходит: метод '{name}' выше не возвращает управление (его тип "
              "результата 'никогда'), и компилятор отвергает код после вызова.",
        "en": "Execution never gets here: method '{name}' above never returns (its result type "
              "is '{n[никогда]}'), and the compiler rejects the code after the call.",
    },
    "code/unreachable-statement.never-value": {
        "ru": "Метод '{name}' не возвращает управление (его тип результата 'никогда'): значения "
              "для присваивания не будет, и компилятор отвергает такую инструкцию как "
              "недостижимую. Вызовите метод отдельной инструкцией.",
        "en": "Method '{name}' never returns (its result type is '{n[никогда]}'): there is no "
              "value to assign, and the compiler rejects the statement as never reached. Call "
              "the method as a statement of its own.",
    },
    "code/unreachable-statement.throw-value": {
        "ru": "'{word}' не даёт значения: присваивать нечего, и компилятор отвергает такую "
              "инструкцию как недостижимую. Выбросьте исключение отдельной инструкцией.",
        "en": "'{word}' gives no value: there is nothing to assign, and the compiler rejects the "
              "statement as never reached. Throw the exception as a statement of its own.",
    },
    "code/misplaced-jump.title": {
        "ru": "Переход вне цикла или из секции 'вконце'",
        "en": "A jump outside a loop or out of a '{n[вконце]}' section",
    },
    "code/misplaced-jump.not-in-loop": {
        "ru": "'{word}' стоит вне цикла: этот оператор прерывает или продолжает только цикл, а "
              "его здесь нет. Выйти из метода можно через 'возврат'.",
        "en": "'{word}' stands outside a loop: the statement only breaks or continues a loop, "
              "and there is none here. To leave the method, use '{n[возврат]}'.",
    },
    "code/misplaced-jump.in-finally": {
        "ru": "'{word}' внутри секции 'вконце': эта секция выполняется при любом выходе из "
              "'попытка' и сама прерывать выполнение не может. Вынесите '{word}' за пределы "
              "'вконце'.",
        "en": "'{word}' inside a '{n[вконце]}' section: the section runs on every way out of "
              "'{n[попытка]}' and cannot interrupt the flow itself. Move '{word}' out of "
              "'{n[вконце]}'.",
    },
}
i18n.register(MESSAGES)

_LOOP = "loop"
_FINALLY = "finally"
#: Expressions with nothing inside that could hold a lambda body.
_LEAVES = (P.Name, P.Literal, P.This, P.GlobalAccess, P.MethodRef)


@cache
def _node_fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


@lru_cache(maxsize=1)
def _never_words() -> frozenset[str]:
    """Both spellings of the result type of a method that never returns."""
    return frozenset(dataset.load_json("language.json")["keywords"]["NEVER"]["forms"])


dataset.register_reset(_never_words.cache_clear)


def _never_returns(method: P.Method) -> bool:
    written = method.return_type
    return written is not None and written.text in _never_words()


_Owner = P.Structure | P.Enum | None


def _owners(module: P.Module) -> Iterator[tuple[_Owner, list[P.Method], list[P.Method]]]:
    """Each method set with its owner and the methods a bare call from it reaches: its own
    ones first, the module's after."""
    top = [m for m in module.members if isinstance(m, P.Method)]
    yield None, top, top
    for member in module.members:
        if isinstance(member, P.Structure):
            own = [m for m in member.members if isinstance(m, P.Method)]
            yield member, own, own + top
        elif isinstance(member, P.Enum):
            yield member, list(member.methods), list(member.methods) + top


def _never_names(reach: list[P.Method]) -> frozenset[str]:
    """Names every method of which within reach never returns."""
    by_name: dict[str, list[bool]] = defaultdict(list)
    for method in reach:
        by_name[method.name].append(_never_returns(method))
    return frozenset(name for name, flags in by_name.items() if name and all(flags))


def _local_names(method: P.Method) -> frozenset[str]:
    """Every name the method binds anywhere in its body - a call of such a name is not judged."""
    names = {p.name for p in method.params}
    for node in walk_nodes(method.body):
        if isinstance(node, P.VarDecl):
            names.add(node.name)
        elif isinstance(node, P.Lambda):
            names.update(p.name for p in node.params)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.add(node.var)
        elif isinstance(node, P.Try):
            names.update(var for var, _type, _body in node.catches)
    return frozenset(names)


@lru_cache(maxsize=1)
def _boolean_words() -> frozenset[str]:
    return frozenset(terms.forms("Булево", "types"))


dataset.register_reset(_boolean_words.cache_clear)


def _written_type(written: P.TypeRef | None, value: P.Expr | None) -> str | None:
    """The one non-nullable type a declaration names; None when it does not tell one."""
    if written is None:
        boolean = isinstance(value, P.Literal) and value.kind in ("TRUE", "FALSE")
        return "Булево" if boolean else None
    if written.nullable or len(written.names) != 1 or "|" in written.text:
        return None
    return written.text


def _declared_types(method: P.Method) -> dict[str, list[str | None]]:
    """What every declaration of each name in the method says about its type."""
    found: dict[str, list[str | None]] = defaultdict(list)
    for param in method.params:
        found[param.name].append(_written_type(param.type, param.default))
    for node in walk_nodes(method.body):
        if isinstance(node, P.VarDecl):
            found[node.name].append(_written_type(node.type, node.init))
        elif isinstance(node, P.Lambda):
            for param in node.params:
                found[param.name].append(None)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            found[node.var].append(None)
        elif isinstance(node, P.Try):
            for var, _type, _body in node.catches:
                found[var].append(None)
    return found


def _compared_value(condition: P.Expr) -> P.Expr | None:
    """The value a condition names: `когда == Х` compares with Х, `когда Х` names Х itself."""
    if (isinstance(condition, P.Compare) and isinstance(condition.first, P.Name)
            and not condition.first.name and len(condition.rest) == 1
            and condition.rest[0][0] == "=="):
        return condition.rest[0][1]
    return condition


def _covers_enum(enum: P.Enum, conditions: list[P.Expr]) -> bool:
    items = {item.name for item in enum.items}
    covered = set()
    for condition in conditions:
        value = _compared_value(condition)
        if not (isinstance(value, P.Member) and not value.safe and value.name in items
                and isinstance(value.obj, P.Name) and value.obj.name == enum.name):
            return False
        covered.add(value.name)
    return covered == items


def _covers_boolean(conditions: list[P.Expr]) -> bool:
    kinds = set()
    for condition in conditions:
        value = _compared_value(condition)
        if not (isinstance(value, P.Literal) and value.kind in ("TRUE", "FALSE")):
            return False
        kinds.add(value.kind)
    return kinds == {"TRUE", "FALSE"}


@dataclasses.dataclass
class _Unreachable:
    """A finding of code/unreachable-statement and what to name in its message."""

    at: P.Node  # the node the finding stands on
    key: str  # the message key suffix
    name: str  # the never-returning method, for the keys that name one
    cause: P.Node  # the statement or expression whose first word the message quotes


class _Flow:
    """Walks one method: which statements end their block, what follows them, where jumps go."""

    def __init__(self, enums: dict[str, P.Enum]) -> None:
        self.enums = enums
        self.never: frozenset[str] = frozenset()
        self.owner: _Owner = None
        self.method: P.Method | None = None
        self.declared: dict[str, list[str | None]] | None = None
        self.frames: list[str] = []
        self.unreachable: list[_Unreachable] = []
        self.jumps: list[tuple[P.Stmt, str]] = []

    def enter(self, method: P.Method, owner: _Owner, never: frozenset[str]) -> None:
        self.method, self.owner, self.declared = method, owner, None
        self.never = never - _local_names(method) if never else never
        self.frames = []

    # --- what ends a block -----------------------------------------------------------------

    def _never_call(self, e: P.Expr | None) -> str | None:
        """The name of a never-returning method the expression calls directly, if it does."""
        if (isinstance(e, P.Call) and isinstance(e.callee, P.Name)
                and "::" not in e.callee.name and e.callee.name in self.never):
            return e.callee.name
        return None

    def block(self, stmts: list[P.Stmt]) -> bool:
        """Walks a block; True when some statement of it always ends the block."""
        ends = False
        for i, st in enumerate(stmts):
            reason = self.statement(st)
            if reason is None:
                continue
            ends = True
            if i + 1 < len(stmts):
                key, name = reason
                self.unreachable.append(_Unreachable(stmts[i + 1], key, name, st))
        return ends

    def statement(self, st: P.Stmt) -> tuple[str, str] | None:
        """Walks a statement; why it ends the block (message key, method name), or None."""
        if isinstance(st, P.Return):
            self._jump(st, is_return=True)
            self.expr(st.value)
            return "after-exit", ""
        if isinstance(st, (P.Break, P.Continue)):
            self._jump(st, is_return=False)
            return "after-exit", ""
        if isinstance(st, P.ExprStmt):
            self.expr(st.expr)
            if isinstance(st.expr, P.Throw):
                return "after-exit", ""
            name = self._never_call(st.expr)
            return ("after-never", name) if name else None
        if isinstance(st, P.VarDecl):
            self.expr(st.init)
            self._value_check(st, st.init)
            return None
        if isinstance(st, P.Assign):
            self.expr(st.target)
            self.expr(st.value)
            self._value_check(st.target, st.value)
            return None
        if isinstance(st, P.If):
            ends = []
            for cond, body in st.branches:
                self.expr(cond)
                ends.append(self.block(body))
            if st.else_body is None:
                return None
            ends.append(self.block(st.else_body))
            return ("after-branches", "") if all(ends) else None
        if isinstance(st, P.Case):
            self.expr(st.subject)
            ends = []
            for when in st.whens:
                for cond in when.conditions:
                    self.expr(cond)
                ends.append(self.block(when.body))
            if st.else_body is None:
                covered = bool(ends) and all(ends) and self._covers_every_value(st)
                return ("after-branches", "") if covered else None
            ends.append(self.block(st.else_body))
            return ("after-branches", "") if all(ends) else None
        if isinstance(st, (P.While, P.ForEach, P.ForTo)):
            for name in _node_fields(type(st)):
                if name != "body":
                    self._value(getattr(st, name))
            self.frames.append(_LOOP)
            self.block(st.body)
            self.frames.pop()
            return None
        if isinstance(st, P.Try):
            ends = [self.block(st.body)]
            ends.extend(self.block(body) for _var, _type, body in st.catches)
            if st.finally_body is not None:
                self.frames.append(_FINALLY)
                self.block(st.finally_body)
                self.frames.pop()
            return ("after-branches", "") if all(ends) else None
        if isinstance(st, P.Scope):
            return ("after-exit", "") if self.block(st.body) else None
        for name in _node_fields(type(st)):  # a use statement, or one the parser grows later
            self._value(getattr(st, name))
        return None

    def _covers_every_value(self, st: P.Case) -> bool:
        """Whether a `выбор` without `иначе` names every value of a subject the file types."""
        conditions = [c for when in st.whens for c in when.conditions]
        if not conditions:
            return False
        if isinstance(st.subject, P.This):
            return isinstance(self.owner, P.Enum) and _covers_enum(self.owner, conditions)
        if not isinstance(st.subject, P.Name) or "::" in st.subject.name:
            return False
        if self.declared is None and self.method is not None:
            self.declared = _declared_types(self.method)
        types = (self.declared or {}).get(st.subject.name, [])
        written = types[0] if types and len(set(types)) == 1 else None
        if written is None:
            return False
        if written in self.enums:
            return _covers_enum(self.enums[written], conditions)
        if written == "Булево" or written in _boolean_words():
            return _covers_boolean(conditions)
        return all(isinstance(c, P.IsType) for c in conditions) and any(
            isinstance(c, P.IsType) and not c.negated and c.type is not None
            and c.type.text == written for c in conditions
        )

    def _value_check(self, at: P.Node, value: P.Expr | None) -> None:
        """A declaration or an assignment whose value never comes is itself never reached."""
        if isinstance(value, P.Throw):
            self.unreachable.append(_Unreachable(at, "throw-value", "", value))
            return
        name = self._never_call(value)
        if name:
            self.unreachable.append(_Unreachable(at, "never-value", name, value))

    # --- jumps -------------------------------------------------------------------------------

    def _jump(self, st: P.Stmt, is_return: bool) -> None:
        if not is_return and _LOOP not in self.frames:
            self.jumps.append((st, "not-in-loop"))
            return
        for frame in reversed(self.frames):
            if frame == _LOOP and not is_return:
                return
            if frame == _FINALLY:
                self.jumps.append((st, "in-finally"))
                return

    # --- expressions: lambda bodies are blocks of their own ------------------------------------

    def expr(self, e: P.Expr | None) -> None:
        if e is None or isinstance(e, _LEAVES):
            return
        if isinstance(e, P.Lambda):
            if isinstance(e.body_expr, P.Assign):
                self.expr(e.body_expr.target)
                self.expr(e.body_expr.value)
                self._value_check(e.body_expr.target, e.body_expr.value)
            else:
                self.expr(e.body_expr)
            if e.body_stmts is not None:
                self.block(e.body_stmts)
            return
        for name in _node_fields(type(e)):
            self._value(getattr(e, name))

    def _value(self, value: object) -> None:
        if isinstance(value, P.Expr):
            self.expr(value)
        elif isinstance(value, P.CallArg):
            self.expr(value.value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self._value(item)


def _analysis(source: SourceFile) -> _Flow | None:
    """The findings of both rules for the file, walked once (cached on the source)."""
    cached = source.cache.get("control_flow")
    if cached is not None:
        return cached or None
    module, errors = parse(source)
    if errors:
        source.cache["control_flow"] = False  # a broken file is code/parse-error territory
        return None
    flow = _Flow({m.name: m for m in module.members if isinstance(m, P.Enum) and m.name})
    for owner, own, reach in _owners(module):
        never = _never_names(reach)
        for method in own:
            if method.is_abstract:
                continue
            flow.enter(method, owner, never)
            for param in method.params:
                flow.expr(param.default)
            flow.block(method.body)
    source.cache["control_flow"] = flow
    return flow


def _word(source: SourceFile, node: P.Node) -> str:
    """The keyword a statement starts with, as the source spells it."""
    text = source.text[node.start:node.end]
    return text.split(None, 1)[0] if text.strip() else ""


def _applies(source: SourceFile) -> bool:
    return source.kind == "xbsl"


@rule("code/unreachable-statement", "code/unreachable-statement.title", "C",
      severity=Severity.ERROR)
def code_never_reached(source: SourceFile) -> Iterable[Diagnostic]:
    """Code after a statement that always ends its block - the compiler rejects it."""
    if not _applies(source):
        return
    flow = _analysis(source)
    if flow is None or not flow.unreachable:
        return
    lm = linemap(source)
    for found in sorted(flow.unreachable, key=lambda item: item.at.start):
        fields = {"name": found.name} if found.name else {"word": _word(source, found.cause)}
        line, col = lm.linecol(found.at.start)
        yield Diagnostic(source.rel, line, col, "code/unreachable-statement", Severity.ERROR,
                         i18n.t(f"code/unreachable-statement.{found.key}", **fields))


@rule("code/misplaced-jump", "code/misplaced-jump.title", "C", severity=Severity.ERROR)
def misplaced_jump(source: SourceFile) -> Iterable[Diagnostic]:
    """`прервать`/`продолжить` outside a loop, and a jump out of `вконце` - compile errors."""
    if not _applies(source):
        return
    flow = _analysis(source)
    if flow is None:
        return
    lm = linemap(source)
    for st, key in sorted(flow.jumps, key=lambda item: item[0].start):
        line, col = lm.linecol(st.start)
        yield Diagnostic(source.rel, line, col, "code/misplaced-jump", Severity.ERROR,
                         i18n.t(f"code/misplaced-jump.{key}", word=_word(source, st)))
