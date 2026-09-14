"""Tier C: assignments the compiler rejects by their shape alone.

Two rules read the two sides of an assignment - a statement `Х = ...`, `Х += ...`, or the body of
a short lambda `Эл -> Эл.Поле = 1` - and need nothing beyond the file. Both are compile errors: the
server refuses the build and the stand keeps running the previous one. The semantics were taken
from the IDE language server on probe projects, form by form, with the variants it accepts.

`code/self-assignment` - the value goes back to the place it is read from: `Х = Х`, `Х = (Х)`,
`этот.Поле = этот.Поле`, `Я.Поле = Я.Поле`, a nested chain of members, `Х -= Х`. The compiler
compares the two sides as ACCESSES: a bare name with the same bare name (letter case counts - a
name spelled otherwise is another name), a member with the member of the same name on the same
receiver, `этот` with `этот`. Parentheses are transparent, and a safe access `?.` on the right
compares as a plain one (`Я.Поле = Я?.Поле` is rejected as well). Anything else is another
expression and compiles: `Мас[0] = Мас[0]`, `Х = Х + 0`, `Х = Х!`, `Х = Х как Тип`, and the mixed
`этот.Поле = Поле`.

A compound operator is compared only after the operand types check out: `Текст += Текст` joins
two strings and compiles, and a target of the unknown type is not compared at all. The file knows
the type of a local, a parameter, a field of the structure the method belongs to and a module
constant, when the declaration writes the type or initializes with a literal or a constructor; a
compound self-assignment is reported only when EVERY declaration of that name within reach of the
method names a known type, and none of them is a string or the unknown type. A member chain
(`Я.Сумма += Я.Сумма`) needs the type of the receiver and is left to the compiler.

An assignment with `=` to itself changes nothing, so its fix deletes the line - offered when the
statement stands alone on its line. A compound one doubles, zeroes or squares the value, and the
intent is not written anywhere: the message shows the explicit form instead.

`code/assign-target` - the left side cannot receive a value. The compiler walks the target from
the outermost access down to the root of the chain:

- at the top a call (`Функция() = 1`, `Объект.Метод() = 1`), a cast (`Х как Тип = ...`), `этот`
  itself or any other expression is not a place to write to;
- a member reached through the safe access `?.` is not either (`Пустая?.Значение = 1`,
  `А?.Б.В = 1`, `А?.Дети[0] = 1`): when the receiver is empty there is nowhere to write;
- an index, a cast and a call on the way down are fine (`(Объ как Тип).Поле = 1`,
  `Узлы().Значение = 1`, `Узлы().Дети[0] = 1`), and so is the insistent `!` anywhere
  (`А! = ...`, `А!.Поле = 1`);
- the walk does not look at a safe access standing before a CALL: `А?.Получить().Поле = 1`
  compiles, and the rule stays silent there too.

A root the walk cannot classify (a literal or a query in the middle of a chain) stays silent.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from functools import cache, lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.typeinfer import walk_nodes

MESSAGES = {
    "code/self-assignment.title": {
        "ru": "Присваивание самому себе",
        "en": "Assignment to itself",
    },
    "code/self-assignment.plain": {
        "ru": "Слева и справа от '=' одно и то же место '{target}': компилятор отвергает "
              "присваивание самому себе, да и значения оно не меняет – присваивание можно убрать.",
        "en": "Both sides of '=' name the same place '{target}': the compiler rejects an "
              "assignment to itself, and it would not change the value anyway - the assignment "
              "can go.",
    },
    "code/self-assignment.compound": {
        "ru": "Слева и справа от '{op}' одно и то же место '{target}': компилятор отвергает "
              "присваивание самому себе и в составной операции. Запишите действие явно: "
              "'{target} = {target} {operator} {target}'.",
        "en": "Both sides of '{op}' name the same place '{target}': the compiler rejects an "
              "assignment to itself in a compound operation too. Write the operation out: "
              "'{target} = {target} {operator} {target}'.",
    },
    "code/assign-target.title": {
        "ru": "Недопустимая левая часть присваивания",
        "en": "Invalid assignment target",
    },
    "code/assign-target.safe": {
        "ru": "Левая часть присваивания '{target}' проходит через безопасный доступ '?.': "
              "когда значение перед ним Неопределено, записывать некуда, и компилятор такое "
              "присваивание отвергает. Проверьте значение заранее и присвойте через '.'.",
        "en": "The assignment target '{target}' goes through the safe access '?.': when the "
              "value before it is {n[Неопределено]} there is nowhere to write, and the compiler "
              "rejects the assignment. Check the value beforehand and assign through '.'.",
    },
    "code/assign-target.call": {
        "ru": "Слева от '{op}' вызов метода '{target}': присвоить можно переменной, свойству "
              "или элементу по индексу, но не результату вызова.",
        "en": "The left side of '{op}' is a method call '{target}': a value is assigned to a "
              "variable, a property or an indexed element, not to the result of a call.",
    },
    "code/assign-target.cast": {
        "ru": "Слева от '{op}' приведение типа '{target}': присваивается переменной или "
              "свойству, а приведение пишется в скобках перед обращением к члену – "
              "'(Значение как Тип).Поле = ...'.",
        "en": "The left side of '{op}' is a type cast '{target}': a value is assigned to a "
              "variable or a property, and a cast goes in parentheses before a member access - "
              "'(Value {n[как]} Type).Field = ...'.",
    },
    "code/assign-target.this": {
        "ru": "Слева от '{op}' стоит 'этот': заменить сам объект нельзя, присвоить можно только "
              "его свойству – 'этот.Поле = ...'.",
        "en": "The left side of '{op}' is '{n[этот]}': the object itself cannot be replaced, "
              "only its property can be assigned - '{n[этот]}.Field = ...'.",
    },
    "code/assign-target.expression": {
        "ru": "Слева от '{op}' выражение '{target}', а не переменная, свойство или элемент по "
              "индексу: такому выражению значение не присвоить.",
        "en": "The left side of '{op}' is the expression '{target}', not a variable, a property "
              "or an indexed element: such an expression cannot receive a value.",
    },
}
i18n.register(MESSAGES)

_PLAIN = "="
_SPACES = re.compile(r"\s+")

#: The top-level forms of a target that are not an access, by the message that names them.
_EXPRESSIONS = (
    P.Literal, P.New, P.Unary, P.Binary, P.Compare, P.Ternary, P.Coalesce, P.IsType,
    P.ArrayLit, P.MapLit,
)
#: Nodes that hold neither a statement nor a lambda: the search for assignments skips them.
_OPAQUE = (P.TypeRef, P.Annotation, P.Literal, P.MethodRef, P.Import)


# --- where the assignments are -----------------------------------------------------------


def _methods(module: P.Module) -> Iterator[tuple[P.Method, P.Structure | None]]:
    """Every method with the structure it belongs to (None for a module or enum method)."""
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


@cache
def _fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


def _assignments(source: SourceFile, module: P.Module) -> tuple[list[P.Assign], set[int]]:
    """Every assignment of the file in source order, and the ids of those that are the body of a
    short lambda.

    Both rules of the module read the same list, so it is collected once per file. The walk
    does not enter the nodes that hold no statement and no lambda - a type, an annotation, a
    literal - which is most of what a generic walk over the tree visits.
    """
    cached = source.cache.get("assignments")
    if cached is not None:
        return cached
    found: list[P.Assign] = []
    bodies: set[int] = set()
    stack: list[object] = [module]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
            continue
        if not isinstance(node, P.Node) or isinstance(node, _OPAQUE):
            continue
        if isinstance(node, P.Assign):
            found.append(node)
        elif isinstance(node, P.Lambda) and isinstance(node.body_expr, P.Assign):
            bodies.add(id(node.body_expr))
        for name in _fields(type(node)):
            child = getattr(node, name)
            if isinstance(child, (P.Node, list, tuple)):
                stack.append(child)
    found.sort(key=lambda st: st.start)
    source.cache["assignments"] = (found, bodies)
    return found, bodies


# --- code/self-assignment ----------------------------------------------------------------


def _same_place(left: P.Expr, right: P.Expr | None) -> bool:
    """Whether both sides name one access the way the compiler compares them."""
    if isinstance(left, P.Name) and isinstance(right, P.Name):
        return bool(left.name) and left.name == right.name
    if isinstance(left, P.Member) and isinstance(right, P.Member):
        return (not left.safe and left.name == right.name
                and _same_place(left.obj, right.obj))
    return isinstance(left, P.This) and isinstance(right, P.This)


@lru_cache(maxsize=1)
def _type_words() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Both spellings of the string type, of the empty value, and of the unknown type."""
    forms = dataset.load_json("language.json")["keywords"]["UNKNOWN"]["forms"]
    return (frozenset(terms.forms("Строка", "types")),
            frozenset(terms.forms("Неопределено", "types")),
            frozenset(forms))


dataset.register_reset(_type_words.cache_clear)


def _literal_type(value: P.Expr | None) -> str | None:
    """The type a literal initializer or a constructor gives a declaration; None otherwise."""
    if isinstance(value, P.Unary) and value.op in ("-", "+"):
        value = value.operand
    if isinstance(value, P.Literal):
        return {"NUMBER": "Число", "STRING": "Строка", "TRUE": "Булево",
                "FALSE": "Булево"}.get(value.kind)
    if isinstance(value, P.New) and value.type.names:
        return value.type.names[0]
    return None


def _declared_type(written: P.TypeRef | None, value: P.Expr | None) -> str | None:
    """The single root type a declaration names; None when the file does not tell it.

    A union other than with the empty value is no single type: the compiler refuses member
    arithmetic on it, and a finding would name the wrong error.
    """
    if written is None:
        return _literal_type(value)
    _string, empty, _unknown = _type_words()
    roots = {name for name in written.names if name not in empty}
    return next(iter(roots)) if len(roots) == 1 else None


def _declarations(method: P.Method, owner: P.Structure | None,
                  module: P.Module) -> dict[str, list[str | None]]:
    """The types every declaration a bare name of the method may resolve to gives it.

    Scopes are not told apart on purpose: a name counts with all its declarations at once, so
    a sibling branch or a field hidden by a local can only make the answer "unknown".
    """
    found: dict[str, list[str | None]] = defaultdict(list)
    for param in method.params:
        found[param.name].append(_declared_type(param.type, param.default))
    for node in walk_nodes(method.body):
        if isinstance(node, P.VarDecl):
            found[node.name].append(_declared_type(node.type, node.init))
        elif isinstance(node, P.Lambda):
            for param in node.params:
                found[param.name].append(_declared_type(param.type, None))
        elif isinstance(node, (P.ForEach, P.ForTo)):
            found[node.var].append(None)
        elif isinstance(node, P.Try):
            for var, _type, _body in node.catches:
                found[var].append(None)
    fields = owner.members if owner is not None and not method.is_static else []
    for member in [*fields, *module.members]:
        if isinstance(member, P.ObjectField):
            found[member.name].append(_declared_type(member.type, member.init))
    return found


def _target_type(target: P.Expr, owner: P.Structure | None,
                 declarations: dict[str, list[str | None]]) -> str | None:
    """The type of a compound operation's target, when every reading of it agrees."""
    if isinstance(target, P.Name):
        types = declarations.get(target.name, [])
    elif (isinstance(target, P.Member) and isinstance(target.obj, P.This)
          and owner is not None):
        types = [_declared_type(m.type, m.init) for m in owner.members
                 if isinstance(m, P.ObjectField) and m.name == target.name]
    else:
        return None
    if not types or None in types or len(set(types)) != 1:
        return None
    return types[0]


def _compared(op: str, target_type: str | None) -> bool:
    """Whether the compiler gets to comparing the sides of a compound operation."""
    if target_type is None:
        return False
    string, _empty, unknown = _type_words()
    if target_type in unknown:
        return False
    return not (op == "+=" and target_type in string)


def _line_removal(text: str, st: P.Assign) -> TextEdit | None:
    """The whole line of the statement, when nothing else stands on it."""
    line_start = text.rfind("\n", 0, st.start) + 1
    if text[line_start:st.start].strip():
        return None
    line_end = text.find("\n", st.end)
    tail = text[st.end:] if line_end == -1 else text[st.end:line_end]
    if tail.strip():
        return None
    return TextEdit(line_start, len(text) if line_end == -1 else line_end + 1, "")


def _spelled(text: str, node: P.Node) -> str:
    return _SPACES.sub(" ", text[node.start:node.end]).strip()


def _compound_compared(module: P.Module, st: P.Assign) -> bool:
    """Whether the compiler compares the sides of a compound self-assignment (see the header)."""
    for method, owner in _methods(module):
        if method.start <= st.start < method.end:
            declarations = _declarations(method, owner, module)
            return _compared(st.op, _target_type(st.target, owner, declarations))
    return False  # an initializer outside any method: no declaration tells the type


@rule("code/self-assignment", "code/self-assignment.title", "C", severity=Severity.ERROR)
def self_assignment(source: SourceFile) -> Iterable[Diagnostic]:
    """A value assigned back to the place it is read from - the compiler rejects it."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    found, lambda_bodies = _assignments(source, module)
    lm = linemap(source)
    text = source.text
    for st in found:
        if not _same_place(st.target, st.value):
            continue
        target = _spelled(text, st.target)
        if st.op == _PLAIN:
            message = i18n.t("code/self-assignment.plain", target=target)
            fix = None if id(st) in lambda_bodies else _line_removal(text, st)
        elif _compound_compared(module, st):
            message = i18n.t("code/self-assignment.compound", op=st.op, target=target,
                             operator=st.op[:-1])
            fix = None
        else:
            continue
        line, col = lm.linecol(st.start)
        yield Diagnostic(source.rel, line, col, "code/self-assignment", Severity.ERROR,
                         message, fix=fix)


# --- code/assign-target ------------------------------------------------------------------


def _target_fault(target: P.Expr) -> str | None:
    """Why the compiler refuses the target: a message key suffix, or None when it accepts it."""
    top = True
    expr: P.Expr | None = target
    while expr is not None:
        if isinstance(expr, P.NonNull):  # the insistent `!` belongs to the access it follows
            expr = expr.operand
            continue
        if isinstance(expr, P.Name):
            return None
        if isinstance(expr, P.This):
            return "this" if top else None
        if isinstance(expr, P.AsType):
            if top:
                return "cast"
            expr = expr.operand
            continue
        if isinstance(expr, P.Call):
            if top:
                return "call"
            if isinstance(expr.callee, P.Member):  # a call on a receiver: walk on to the receiver
                expr = expr.callee.obj
                continue
            return None  # a call of a module method starts the chain
        if isinstance(expr, P.Member):
            if expr.safe:
                return "safe"
            expr = expr.obj
        elif isinstance(expr, P.Index):
            expr = expr.obj
        elif top and isinstance(expr, _EXPRESSIONS):
            return "expression"
        else:
            return None  # a root the walk does not know: the compiler is left to judge it
        top = False
    return None


@rule("code/assign-target", "code/assign-target.title", "C", severity=Severity.ERROR)
def assign_target(source: SourceFile) -> Iterable[Diagnostic]:
    """The left side of an assignment is not a place to write to - the compiler rejects it."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    lm = linemap(source)
    found, _bodies = _assignments(source, module)
    for st in found:
        fault = _target_fault(st.target)
        if fault is None:
            continue
        line, col = lm.linecol(st.target.start)
        yield Diagnostic(
            source.rel, line, col, "code/assign-target", Severity.ERROR,
            i18n.t(f"code/assign-target.{fault}", op=st.op,
                   target=_spelled(source.text, st.target)),
        )
