"""Tier C: a name, a value or a type written twice where the compiler wants it once.

Three rules find a repetition the compiler refuses. Each finding is a compile error: the server
refuses the build and the stand keeps running the previous one. The forms and their controls were
probed against the IDE language server.

`code/duplicate-when` - a `когда` of `выбор` that names a value or a type an earlier `когда` of the
same `выбор` already handles. A value is a literal - a number, a string without interpolation,
`True` or `False` in either spelling, `Undefined` - or an item of an enumeration declared in this
file; a number compares by its value, so `1` and `1.0` are one value. A type is a member of the
type list after `когда это` (`это Строка?` handles the empty value too), both spellings of a
platform name meeting in one. A name of a variable or a constant is left alone: only the compiler
knows its value. So is a type that merely includes another one - `когда это Объект` before
`когда это Строка`: the compiler does not call that a repetition.

`code/duplicate-catch` - a `поймать` of `попытка` that lists an exception type an earlier `поймать`
of the same `попытка` already catches, or that lists one type twice. The comparison is by the
type as written; a base type before its descendant is legal.

`code/duplicate-declaration` - one name declared twice where the compiler compares names
ignoring letter case:

- two types of the module - structures, exceptions and enumerations share one list;
- two fields of a structure or of an exception; an exception already has `Description` and
  `Cause` of its own, in either spelling;
- two items of an enumeration, and a second `умолчание` item;
- two methods of one module, structure or enumeration whose names differ in letter case only
  (the same name in the same case is an overload and legal);
- two parameters of a method or of a lambda;
- two module constants;
- a local name - `знч`, `пер`, `исп`, the variable of a loop or of `поймать`, a lambda parameter -
  that repeats a name of the method or of an enclosing block; a sibling block is a scope of its
  own, and a module constant may be hidden by a local. A local named exactly like a parameter of
  the method outside a lambda is `code/param-redeclared` territory and is not reported twice.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator
from decimal import Decimal
from dataclasses import dataclass
from functools import cache, lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.typeinfer import canonical_name

MESSAGES = {
    "code/duplicate-when.title": {
        "ru": "Повтор значения или типа в 'когда'",
        "en": "A value or a type repeated in '{n[когда]}'",
    },
    "code/duplicate-when.value": {
        "ru": "Значение '{value}' уже обработано выше в этом же 'выбор': до этой ветви дело не "
              "дойдёт, и компилятор такую ветвь отвергает. Уберите повтор либо объедините ветви.",
        "en": "The value '{value}' is already handled above in the same '{n[выбор]}': this branch "
              "is never reached, and the compiler rejects it. Remove the repetition or merge the "
              "branches.",
    },
    "code/duplicate-when.type": {
        "ru": "Тип '{value}' уже обработан выше в этом же 'выбор': до этой ветви дело не дойдёт, "
              "и компилятор такую ветвь отвергает. Уберите повтор либо объедините ветви.",
        "en": "The type '{value}' is already handled above in the same '{n[выбор]}': this branch "
              "is never reached, and the compiler rejects it. Remove the repetition or merge the "
              "branches.",
    },
    "code/duplicate-catch.title": {
        "ru": "Повтор типа исключения в 'поймать'",
        "en": "An exception type repeated in '{n[поймать]}'",
    },
    "code/duplicate-catch.found": {
        "ru": "Исключение '{type}' уже перехватывает секция 'поймать' выше в этой же 'попытка': "
              "компилятор второй перехват того же типа отвергает. Уберите повтор либо объедините "
              "секции.",
        "en": "The exception '{type}' is already caught by a '{n[поймать]}' section above in the "
              "same '{n[попытка]}': the compiler rejects a second catch of the same type. Remove "
              "the repetition or merge the sections.",
    },
    "code/duplicate-declaration.title": {
        "ru": "Повтор имени в объявлении",
        "en": "A name declared twice",
    },
    "code/duplicate-declaration.type": {
        "ru": "Тип с именем '{name}' уже объявлен в этом модуле (строка {line}); имена типов "
              "сравниваются без учёта регистра, и компилятор второе объявление отвергает.",
        "en": "A type named '{name}' is already declared in this module (line {line}); type names "
              "are compared ignoring letter case, and the compiler rejects the second declaration.",
    },
    "code/duplicate-declaration.field": {
        "ru": "Поле с именем '{name}' уже есть у '{owner}' (строка {line}); имена полей "
              "сравниваются без учёта регистра, и компилятор второе объявление отвергает.",
        "en": "A field named '{name}' already exists in '{owner}' (line {line}); field names are "
              "compared ignoring letter case, and the compiler rejects the second declaration.",
    },
    "code/duplicate-declaration.exception-field": {
        "ru": "Поле с именем '{name}' уже есть у любого исключения – это его собственное "
              "свойство, и компилятор повторное объявление отвергает. Выберите другое имя.",
        "en": "Every exception already has a field named '{name}' - its own property, and the "
              "compiler rejects declaring it again. Choose another name.",
    },
    "code/duplicate-declaration.item": {
        "ru": "Элемент '{name}' уже есть в перечислении '{owner}' (строка {line}); имена "
              "элементов сравниваются без учёта регистра, и компилятор повтор отвергает.",
        "en": "The item '{name}' already exists in the enumeration '{owner}' (line {line}); item "
              "names are compared ignoring letter case, and the compiler rejects the repetition.",
    },
    "code/duplicate-declaration.default": {
        "ru": "У перечисления '{owner}' уже есть элемент 'умолчание' (строка {line}): значение "
              "по умолчанию бывает одно, и компилятор второе отвергает.",
        "en": "The enumeration '{owner}' already has a '{n[умолчание]}' item (line {line}): there "
              "is one default value, and the compiler rejects a second one.",
    },
    "code/duplicate-declaration.method-case": {
        "ru": "Метод '{name}' отличается от метода '{other}' (строка {line}) только регистром "
              "букв: компилятор такие имена не различает и объявление отвергает. Перегрузка "
              "пишется тем же именем в том же регистре.",
        "en": "Method '{name}' differs from method '{other}' (line {line}) in letter case only: "
              "the compiler does not tell such names apart and rejects the declaration. An "
              "overload is written with the same name in the same case.",
    },
    "code/duplicate-declaration.parameter": {
        "ru": "Параметр с именем '{name}' уже объявлен выше в этом же списке параметров; имена "
              "сравниваются без учёта регистра, и компилятор повтор отвергает.",
        "en": "A parameter named '{name}' is already declared earlier in the same parameter "
              "list; names are compared ignoring letter case, and the compiler rejects the "
              "repetition.",
    },
    "code/duplicate-declaration.constant": {
        "ru": "Константа с именем '{name}' уже объявлена в этом модуле (строка {line}); компилятор "
              "повтор отвергает.",
        "en": "A constant named '{name}' is already declared in this module (line {line}); the "
              "compiler rejects the repetition.",
    },
    "code/duplicate-declaration.local": {
        "ru": "Имя '{name}' уже занято в этом методе (строка {line}): вложенный блок не может "
              "объявить имя внешнего, имена сравниваются без учёта регистра, и компилятор "
              "объявление отвергает. Выберите другое имя.",
        "en": "The name '{name}' is already taken in this method (line {line}): a nested block "
              "cannot declare a name of an enclosing one, names are compared ignoring letter "
              "case, and the compiler rejects the declaration. Choose another name.",
    },
}
i18n.register(MESSAGES)

_WORD = re.compile(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*")
_DECIMAL = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_BLANK = re.compile(r"\s*")
#: The fields every exception has of its own, named as the catalog names the members.
_EXCEPTION_OWN = ("Описание", "Причина")
_EXCEPTION_TYPE = "Исключение"


@cache
def _node_fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


def _fold(name: str) -> str:
    """A name as the compiler compares it: letter case does not count."""
    return name.casefold()


def _canonical_type(member: str) -> str:
    """A written type with every name in one spelling, so both spellings compare equal."""
    return _WORD.sub(lambda m: canonical_name(m.group(0)) or m.group(0), member.replace(" ", ""))


def _members_with_offsets(text: str, start: int) -> list[tuple[str, int]]:
    """The members of a written type list (`А|Б`) with the offset each one starts at."""
    out: list[tuple[str, int]] = []
    depth = 0
    begin = 0
    for index, char in enumerate(text + "|"):
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        elif char == "|" and depth == 0:
            piece = text[begin:index]
            stripped = piece.strip()
            if stripped:
                out.append((stripped, start + begin + (len(piece) - len(piece.lstrip()))))
            begin = index + 1
    return out


@lru_cache(maxsize=1)
def _empty_forms() -> frozenset[str]:
    keywords = dataset.load_json("language.json")["keywords"]
    empty = frozenset(terms.forms("Неопределено", "types"))
    return empty | frozenset(keywords["UNDEFINED"]["forms"])


dataset.register_reset(_empty_forms.cache_clear)


# --- code/duplicate-when --------------------------------------------------------------------


def _number(text: str, negative: bool) -> tuple[str, str] | None:
    """A number literal by its value: `1` and `1.0` are one value to the compiler."""
    if not _DECIMAL.fullmatch(text):
        return None
    value = Decimal(text).normalize()
    return ("NUMBER", str(-value if negative else value))


def _value_key(expr: P.Expr, enums: dict[str, set[str]]) -> tuple[str, str] | None:
    """What a `когда` value compares by, when the file alone knows it; None otherwise."""
    if isinstance(expr, P.Unary) and expr.op == "-" and isinstance(expr.operand, P.Literal) \
            and expr.operand.kind == "NUMBER":
        return _number(expr.operand.text, negative=True)
    if isinstance(expr, P.Literal):
        if expr.kind in ("TRUE", "FALSE", "UNDEFINED"):
            return (expr.kind, "")
        if expr.kind == "NUMBER":
            return _number(expr.text, negative=False)
        if expr.kind == "STRING" and not re.search(r"[%$]", expr.text):
            return ("STRING", expr.text)
        return None
    if isinstance(expr, P.Member) and not expr.safe and isinstance(expr.obj, P.Name):
        items = enums.get(expr.obj.name)
        if items is not None and expr.name in items:
            return ("ITEM", f"{expr.obj.name}.{expr.name}")
    return None


def _cases(module: P.Module) -> Iterator[P.Case]:
    yield from (node for node in _nodes(module) if isinstance(node, P.Case))


def _nodes(root: object) -> Iterator[P.Node]:
    stack: list[object] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(reversed(node))
        elif isinstance(node, P.Node) and not isinstance(node, (P.TypeRef, P.Literal, P.Name)):
            yield node
            stack.extend(reversed([getattr(node, name) for name in _node_fields(type(node))]))


def _type_keys(source: SourceFile, check: P.IsType) -> list[str]:
    written = check.type
    if written is None:
        return []
    raw = source.text[written.start:written.end]
    keys = []
    empty = _empty_forms()
    for member, _offset in _members_with_offsets(raw, written.start):
        nullable = member.endswith("?")
        name = member.rstrip("?").strip()
        keys.append("Неопределено" if name in empty else _canonical_type(name))
        if nullable:
            keys.append("Неопределено")
    return keys


@rule("code/duplicate-when", "code/duplicate-when.title", "C", severity=Severity.ERROR)
def duplicate_when(source: SourceFile) -> Iterable[Diagnostic]:
    """A `когда` that repeats a value or a type of an earlier one - the compiler rejects it."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    enums = {m.name: {item.name for item in m.items}
             for m in module.members if isinstance(m, P.Enum)}
    lm = linemap(source)
    for case in _cases(module):
        values: set[tuple[str, str]] = set()
        types: set[str] = set()
        for when in case.whens:
            for condition in when.conditions:
                if isinstance(condition, P.IsType):
                    keys = _type_keys(source, condition)
                    repeated = [key for key in keys if key in types]
                    types.update(keys)
                    if not repeated:
                        continue
                    key, text = "type", source.text[condition.type.start:condition.type.end]
                else:
                    value = _value_key(condition, enums)
                    if value is None:
                        continue
                    if value not in values:
                        values.add(value)
                        continue
                    key, text = "value", source.text[condition.start:condition.end]
                line, col = lm.linecol(condition.start)
                yield Diagnostic(source.rel, line, col, "code/duplicate-when", Severity.ERROR,
                                 i18n.t(f"code/duplicate-when.{key}", value=text.strip()))


# --- code/duplicate-catch -------------------------------------------------------------------


@rule("code/duplicate-catch", "code/duplicate-catch.title", "C", severity=Severity.ERROR)
def duplicate_catch(source: SourceFile) -> Iterable[Diagnostic]:
    """A `поймать` that repeats an exception type already caught - the compiler rejects it."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return
    lm = linemap(source)
    for attempt in (node for node in _nodes(module) if isinstance(node, P.Try)):
        caught: set[str] = set()
        for _var, written, _body in attempt.catches:
            if written is None or written.nullable:
                continue
            raw = source.text[written.start:written.end]
            for member, offset in _members_with_offsets(raw, written.start):
                key = _canonical_type(member)
                if key not in caught:
                    caught.add(key)
                    continue
                line, col = lm.linecol(offset)
                yield Diagnostic(source.rel, line, col, "code/duplicate-catch", Severity.ERROR,
                                 i18n.t("code/duplicate-catch.found", type=member))


# --- code/duplicate-declaration --------------------------------------------------------------


@dataclass
class _Seen:
    name: str
    at: int


@lru_cache(maxsize=1)
def _exception_own_fields() -> frozenset[str]:
    """The folded names of the fields every exception has, in both spellings."""
    names = set()
    for member in _EXCEPTION_OWN:
        names.add(_fold(member))
        english = terms.member_english_of(_EXCEPTION_TYPE, member)
        if english:
            names.add(_fold(english))
    return frozenset(names)


dataset.register_reset(_exception_own_fields.cache_clear)


def _has_name_annotation(annotations: list[P.Annotation]) -> bool:
    """A declaration renamed by an annotation compares by another name - it is not judged."""
    return any(a.name.rsplit("::", 1)[-1] == "Ru" for a in annotations)


class _Declarations:
    """Collects the repeated declarations of one file."""

    def __init__(self, source: SourceFile) -> None:
        self.source = source
        self.lm = linemap(source)
        self.found: list[tuple[int, str, dict[str, str]]] = []

    def line_of(self, offset: int) -> str:
        return str(self.lm.linecol(offset)[0])

    def report(self, at: int, key: str, **fields: str) -> None:
        self.found.append((at, key, fields))

    # --- members of the module ---------------------------------------------------------------

    def module(self, module: P.Module) -> None:
        types: dict[str, _Seen] = {}
        constants: dict[str, _Seen] = {}
        for member in module.members:
            if isinstance(member, (P.Structure, P.Enum)) and member.name \
                    and not _has_name_annotation(member.annotations):
                seen = types.get(_fold(member.name))
                if seen is None:
                    types[_fold(member.name)] = _Seen(member.name, member.start)
                else:
                    self.report(member.start, "type", name=member.name, line=self.line_of(seen.at))
            elif isinstance(member, P.ObjectField) and member.kind == "CONST" and member.name:
                seen = constants.get(_fold(member.name))
                if seen is None:
                    constants[_fold(member.name)] = _Seen(member.name, member.start)
                else:
                    self.report(member.start, "constant", name=member.name,
                                line=self.line_of(seen.at))
        self.methods([m for m in module.members if isinstance(m, P.Method)])
        for member in module.members:
            if isinstance(member, P.Structure):
                self.fields(member)
                self.methods([m for m in member.members if isinstance(m, P.Method)])
            elif isinstance(member, P.Enum):
                self.items(member)
                self.methods(list(member.methods))

    def fields(self, owner: P.Structure) -> None:
        seen: dict[str, _Seen] = {}
        own = _exception_own_fields() if owner.kind == "EXCEPTION" else frozenset()
        for field in owner.members:
            if not isinstance(field, P.ObjectField) or not field.name \
                    or _has_name_annotation(field.annotations):
                continue
            folded = _fold(field.name)
            if folded in own:
                self.report(field.start, "exception-field", name=field.name)
            elif folded in seen:
                self.report(field.start, "field", name=field.name, owner=owner.name,
                            line=self.line_of(seen[folded].at))
            else:
                seen[folded] = _Seen(field.name, field.start)

    def items(self, enum: P.Enum) -> None:
        seen: dict[str, _Seen] = {}
        default: _Seen | None = None
        for item in enum.items:
            if item.is_default:
                if default is not None:
                    self.report(item.start, "default", owner=enum.name,
                                line=self.line_of(default.at))
                else:
                    default = _Seen(item.name, item.start)
            folded = _fold(item.name)
            if folded in seen:
                self.report(item.start, "item", name=item.name, owner=enum.name,
                            line=self.line_of(seen[folded].at))
            elif item.name:
                seen[folded] = _Seen(item.name, item.start)

    def methods(self, methods: list[P.Method]) -> None:
        first: dict[str, _Seen] = {}
        for method in methods:
            if not method.name or _has_name_annotation(method.annotations):
                continue
            folded = _fold(method.name)
            seen = first.get(folded)
            head = self.head(method)
            if seen is None:
                first[folded] = _Seen(method.name, head)
            elif seen.name != method.name:
                self.report(head, "method-case", name=method.name, other=seen.name,
                            line=self.line_of(seen.at))
        for method in methods:
            if not method.is_abstract:
                _Locals(self, method).run()

    def head(self, method: P.Method) -> int:
        """Where a method declaration begins past its annotations - where the compiler reports."""
        if not method.annotations:
            return method.start
        return _BLANK.match(self.source.text, method.annotations[-1].end).end()


class _Locals:
    """The local names of one method, scope by scope, the way the compiler adds them."""

    def __init__(self, owner: _Declarations, method: P.Method) -> None:
        self.owner = owner
        self.method = method
        self.params = {p.name for p in method.params}
        self.scopes: list[dict[str, _Seen]] = []
        self.lambda_depth = 0

    def run(self) -> None:
        self.scopes = [{}]
        self.parameters(self.method.params)
        self.statements(self.method.body)

    # --- declaring -----------------------------------------------------------------------------

    def parameters(self, params: list[P.Param]) -> None:
        own: set[str] = set()
        for param in params:
            if not param.name:
                continue
            folded = _fold(param.name)
            if folded in own:
                self.owner.report(param.start, "parameter", name=param.name)
                continue
            own.add(folded)
            if len(self.scopes) > 1 or self.lambda_depth:
                self.declare(param.name, param.start)
            else:
                self.scopes[-1][folded] = _Seen(param.name, param.start)

    def declare(self, name: str, at: int, exact_param_owned: bool = False) -> None:
        if not name:
            return
        folded = _fold(name)
        for scope in self.scopes:
            seen = scope.get(folded)
            if seen is None:
                continue
            is_param = scope is self.scopes[0] and seen.name in self.params
            if not (exact_param_owned and is_param and seen.name == name):
                self.owner.report(at, "local", name=name, line=self.owner.line_of(seen.at))
            break
        self.scopes[-1].setdefault(folded, _Seen(name, at))

    def block(self, stmts: list[P.Stmt], declare: Iterable[tuple[str, int]] = ()) -> None:
        self.scopes.append({})
        for name, at in declare:
            self.declare(name, at)
        self.statements(stmts)
        self.scopes.pop()

    # --- walking ---------------------------------------------------------------------------------

    def statements(self, stmts: list[P.Stmt]) -> None:
        for st in stmts:
            self.statement(st)

    def statement(self, st: P.Stmt) -> None:
        if isinstance(st, P.VarDecl):
            self.expr(st.init)
            # outside a lambda a name repeating a parameter exactly is code/param-redeclared's
            self.declare(st.name, st.start, exact_param_owned=self.lambda_depth == 0)
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
        elif isinstance(st, (P.ForEach, P.ForTo)):
            for name in _node_fields(type(st)):
                if name not in ("body", "var"):
                    self.value(getattr(st, name))
            self.block(st.body, [(st.var, self.loop_var_at(st))])
        elif isinstance(st, P.Try):
            self.block(st.body)
            for var, written, body in st.catches:
                self.block(body, [(var, self.catch_var_at(var, written, st))])
            if st.finally_body is not None:
                self.block(st.finally_body)
        elif isinstance(st, P.Scope):
            self.block(st.body)
        else:
            for name in _node_fields(type(st)):
                self.value(getattr(st, name))

    def loop_var_at(self, st: P.ForEach | P.ForTo) -> int:
        match = re.compile(re.escape(st.var)).search(self.owner.source.text, st.start, st.end)
        return match.start() if match else st.start

    def catch_var_at(self, var: str, written: P.TypeRef | None, attempt: P.Try) -> int:
        text = self.owner.source.text
        if written is not None:
            at = text.rfind(var, attempt.start, written.start)
            if at >= 0:
                return at
        return attempt.start

    def expr(self, e: P.Expr | None) -> None:
        if e is None or isinstance(e, (P.Name, P.Literal, P.This, P.GlobalAccess, P.MethodRef)):
            return
        if isinstance(e, P.Lambda):
            self.scopes.append({})
            self.lambda_depth += 1
            self.parameters(e.params)
            if isinstance(e.body_expr, P.Assign):
                self.expr(e.body_expr.target)
                self.expr(e.body_expr.value)
            else:
                self.expr(e.body_expr)
            if e.body_stmts is not None:
                self.statements(e.body_stmts)
            self.lambda_depth -= 1
            self.scopes.pop()
            return
        for name in _node_fields(type(e)):
            self.value(getattr(e, name))

    def value(self, value: object) -> None:
        if isinstance(value, P.Expr):
            self.expr(value)
        elif isinstance(value, P.Stmt):
            self.statement(value)
        elif isinstance(value, P.CallArg):
            self.expr(value.value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.value(item)


@rule("code/duplicate-declaration", "code/duplicate-declaration.title", "C",
      severity=Severity.ERROR)
def duplicate_declaration(source: SourceFile) -> Iterable[Diagnostic]:
    """One name declared twice where the compiler wants it once - it rejects the declaration."""
    if source.kind != "xbsl":
        return
    module, errors = parse(source)
    if errors:
        return  # a broken file is code/parse-error territory
    declarations = _Declarations(source)
    declarations.module(module)
    for at, key, fields in sorted(declarations.found, key=lambda item: item[0]):
        line, col = declarations.lm.linecol(at)
        yield Diagnostic(source.rel, line, col, "code/duplicate-declaration", Severity.ERROR,
                         i18n.t(f"code/duplicate-declaration.{key}", **fields))
