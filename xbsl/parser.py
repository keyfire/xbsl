"""The XBSL parser: tokens -> AST + syntax errors.

Recursive descent written rule-by-rule against the platform grammar (the generated
InternalBsl.g inside the distribution jar; the same source language.json is extracted
from). Each parse method cites the grammar rule it implements.

Design notes, verified empirically on the platform and its corpus:

- Line breaks are hidden almost everywhere (a binary operator may end or start a line).
  The one place a break matters is after `иначе`/`else`: `иначе если` on one line is an
  elsif branch, while `если` on the NEXT line is a nested if inside the else branch
  (the grammar spells it `RULE_ELSE (RULE_NL)+ elsePartStatement`). The parser compares
  token line numbers instead of tracking NL tokens.
- `<` is ambiguous between generics and comparison (the platform lexer disambiguates
  contextually into RULE_LT / RULE_LT_CMP; ours does not) - the parser speculatively
  tries the generic reading and rolls back.
- The bodies of `Запрос{...}`, pattern literals `'...'` and strings (including their
  interpolations) stay atoms on this level: queries have their own DSL (and rules),
  string interpolation is not re-lexed here.
- Error recovery is per statement: on an error the parser records a diagnostic and
  skips to the next line or block terminator, so one broken statement does not hide
  the rest of the file.

The parser must accept the whole real-world corpus with zero errors - like the token
heuristics in rules/_syntax.py, a construct we are unsure about is parsed permissively.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from xbsl import i18n
from xbsl.lexer import Token, tokens

__all__ = ["parse", "parse_text", "ParseError", "Module"]


# Parser diagnostics. Messages are resolved at ParseError creation time (the language is
# pinned for the whole run, and the AST cache lives within one run, so cached errors
# cannot leak a stale language). Every emit site has its own full key - no fragments to
# glue, and tests/test_i18n.py checks the ru/en parity automatically.
MESSAGES = {
    "parser.unexpected-module-code": {
        "ru": "Неожиданный код на уровне модуля",
        "en": "Unexpected code at the module level",
    },
    "parser.annotation-needs-member": {
        "ru": "После аннотации ожидается метод, структура, перечисление или константа",
        "en": "After an annotation expected a method, structure, enum or constant",
    },
    "parser.expected-module-member": {
        "ru": "Ожидается импорт, метод, структура, перечисление или константа модуля",
        "en": "Expected an import, method, structure, enum or module constant",
    },
    "parser.expected-import-name": {
        "ru": "Ожидается имя подсистемы после 'импорт'",
        "en": "Expected a subsystem name after 'импорт'",
    },
    "parser.expected-method-kw": {
        "ru": "Ожидается 'метод'",
        "en": "Expected 'метод'",
    },
    "parser.expected-method-name": {
        "ru": "Ожидается имя метода",
        "en": "Expected a method name",
    },
    "parser.expected-param-name": {
        "ru": "Ожидается имя параметра",
        "en": "Expected a parameter name",
    },
    "parser.expected-struct-name": {
        "ru": "Ожидается имя структуры",
        "en": "Expected a structure name",
    },
    "parser.expected-struct-member": {
        "ru": "Ожидается поле, конструктор или метод структуры",
        "en": "Expected a field, constructor or method of the structure",
    },
    "parser.expected-field-kw": {
        "ru": "Ожидается 'знч', 'пер' или 'исп'",
        "en": "Expected 'знч', 'пер' or 'исп'",
    },
    "parser.expected-field-name": {
        "ru": "Ожидается имя поля",
        "en": "Expected a field name",
    },
    "parser.expected-enum-name": {
        "ru": "Ожидается имя перечисления",
        "en": "Expected an enum name",
    },
    "parser.expected-enum-value": {
        "ru": "Ожидается значение перечисления",
        "en": "Expected an enum value",
    },
    "parser.expected-const-name": {
        "ru": "Ожидается имя константы модуля",
        "en": "Expected a module constant name",
    },
    "parser.expected-type-name": {
        "ru": "Ожидается имя типа",
        "en": "Expected a type name",
    },
    "parser.statement-unparsed": {
        "ru": "Не удалось разобрать оператор",
        "en": "Cannot parse the statement",
    },
    "parser.duplicate-else": {
        "ru": "Повторная ветка 'иначе'",
        "en": "Duplicate 'иначе' branch",
    },
    "parser.expected-loop-var": {
        "ru": "Ожидается имя переменной цикла",
        "en": "Expected a loop variable name",
    },
    "parser.expected-po-in-for": {
        "ru": "Ожидается 'по' в цикле 'для'",
        "en": "Expected 'по' in the 'для' loop",
    },
    "parser.expected-catch-var": {
        "ru": "Ожидается имя переменной исключения",
        "en": "Expected an exception variable name",
    },
    "parser.expected-var-name": {
        "ru": "Ожидается имя переменной",
        "en": "Expected a variable name",
    },
    "parser.decl-needs-type-or-value": {
        "ru": "Объявлению нужен тип или начальное значение",
        "en": "A declaration needs a type or an initial value",
    },
    "parser.expected-expr-after-assign": {
        "ru": "Ожидается выражение после присваивания",
        "en": "Expected an expression after the assignment",
    },
    "parser.expected-dot-in-method-ref": {
        "ru": "Ожидается '.' в ссылке на метод",
        "en": "Expected '.' in the method reference",
    },
    "parser.expected-name-in-method-ref": {
        "ru": "Ожидается имя в ссылке на метод",
        "en": "Expected a name in the method reference",
    },
    "parser.expected-name-after-colons": {
        "ru": "Ожидается имя после '::'",
        "en": "Expected a name after '::'",
    },
    "parser.expected-name-after-dot": {
        "ru": "Ожидается имя после '.'",
        "en": "Expected a name after '.'",
    },
    "parser.expected-expr": {
        "ru": "Ожидается выражение",
        "en": "Expected an expression",
    },
    "parser.expected-type-after-new": {
        "ru": "Ожидается имя типа после 'новый'",
        "en": "Expected a type name after 'новый'",
    },
    "parser.expected-gt-in-type-literal": {
        "ru": "Ожидается '>' в литерале типа",
        "en": "Expected '>' in the type literal",
    },
    "parser.expected-rparen-annotation": {
        "ru": "Ожидается ')' после параметров аннотации",
        "en": "Expected ')' after the annotation parameters",
    },
    "parser.expected-lparen-method": {
        "ru": "Ожидается '(' после имени метода",
        "en": "Expected '(' after the method name",
    },
    "parser.expected-rparen-params": {
        "ru": "Ожидается ')' после параметров",
        "en": "Expected ')' after the parameters",
    },
    "parser.expected-semicolon-struct": {
        "ru": "Ожидается ';' в конце структуры",
        "en": "Expected ';' at the end of the structure",
    },
    "parser.expected-semicolon-enum": {
        "ru": "Ожидается ';' в конце перечисления",
        "en": "Expected ';' at the end of the enum",
    },
    "parser.expected-semicolon-if": {
        "ru": "Ожидается ';' в конце 'если'",
        "en": "Expected ';' at the end of 'если'",
    },
    "parser.expected-semicolon-case": {
        "ru": "Ожидается ';' в конце 'выбор'",
        "en": "Expected ';' at the end of 'выбор'",
    },
    "parser.expected-eq-in-for": {
        "ru": "Ожидается '=' в цикле 'для'",
        "en": "Expected '=' in the 'для' loop",
    },
    "parser.expected-colon-catch": {
        "ru": "Ожидается ':' после переменной 'поймать'",
        "en": "Expected ':' after the 'поймать' variable",
    },
    "parser.expected-semicolon-try": {
        "ru": "Ожидается ';' в конце 'попытка'",
        "en": "Expected ';' at the end of 'попытка'",
    },
    "parser.expected-colon-ternary": {
        "ru": "Ожидается ':' в тернарном операторе",
        "en": "Expected ':' in the ternary operator",
    },
    "parser.expected-rbracket-index": {
        "ru": "Ожидается ']' после индекса",
        "en": "Expected ']' after the index",
    },
    "parser.expected-rparen-call": {
        "ru": "Ожидается ')' после аргументов вызова",
        "en": "Expected ')' after the call arguments",
    },
    "parser.expected-rparen-paren": {
        "ru": "Ожидается ')' после выражения в скобках",
        "en": "Expected ')' after the parenthesized expression",
    },
    "parser.expected-rbracket-array": {
        "ru": "Ожидается ']' в конце литерала массива",
        "en": "Expected ']' at the end of the array literal",
    },
    "parser.expected-rbrace-map": {
        "ru": "Ожидается '}}' в конце литерала коллекции",
        "en": "Expected '}}' at the end of the collection literal",
    },
    "parser.expected-semicolon-method": {
        "ru": "Ожидается ';' в конце метода",
        "en": "Expected ';' at the end of the method",
    },
    "parser.expected-semicolon-while": {
        "ru": "Ожидается ';' в конце 'пока'",
        "en": "Expected ';' at the end of 'пока'",
    },
    "parser.expected-semicolon-for": {
        "ru": "Ожидается ';' в конце 'для'",
        "en": "Expected ';' at the end of 'для'",
    },
    "parser.expected-semicolon-scope": {
        "ru": "Ожидается ';' в конце 'область'",
        "en": "Expected ';' at the end of 'область'",
    },
    "parser.expected-semicolon-lambda": {
        "ru": "Ожидается ';' в конце лямбды",
        "en": "Expected ';' at the end of the lambda",
    },
}
i18n.register(MESSAGES)


# --- AST -------------------------------------------------------------------------------
# Every node carries [start, end) offsets. Nodes are deliberately plain: stage 2 (symbol
# tables) and stage 3 (type inference) will walk them, so they mirror the grammar shape.


@dataclass
class Node:
    start: int
    end: int


@dataclass
class Annotation(Node):  # ruleannotation: @Name(params)
    name: str
    args: list["Expr | None"] = field(default_factory=list)


@dataclass
class TypeRef(Node):
    """rulecompoundTypeName: alternatives of type names, `?` marks nullable."""

    text: str  # normalized source text of the whole type expression
    names: list[str] = field(default_factory=list)  # root names of the alternatives
    nullable: bool = False


@dataclass
class Param(Node):  # ruleparameter
    name: str
    type: TypeRef | None
    default: "Expr | None"
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Method(Node):  # rulemethod / ruleabstractMethod
    name: str
    params: list[Param]
    return_type: TypeRef | None
    body: list["Stmt"]
    is_static: bool = False
    is_abstract: bool = False
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class ObjectField(Node):  # ruleobjectField / rulemoduleConst
    kind: str  # знч|пер|исп|конст (canonical VAL|VAR|USE|CONST)
    name: str
    type: TypeRef | None
    init: "Expr | None"
    required: bool = False
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Constructor(Node):  # ruleobjectConstructor
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Structure(Node):  # rulebslStructure / rulebslException
    kind: str  # STRUCTURE | EXCEPTION
    name: str
    members: list[Node] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class EnumItem(Node):  # rulebslEnumItem
    name: str
    is_default: bool = False


@dataclass
class Enum(Node):  # rulebslEnum
    name: str
    items: list[EnumItem] = field(default_factory=list)
    methods: list[Method] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class Import(Node):  # rulenamespaceImport
    name: str  # A::B::C


@dataclass
class Module(Node):  # rulemodule
    imports: list[Import] = field(default_factory=list)
    members: list[Node] = field(default_factory=list)  # Method | Structure | Enum | ObjectField


# --- statements ---


@dataclass
class Stmt(Node):
    pass


@dataclass
class VarDecl(Stmt):  # ruledeclareVariableStatement
    kind: str  # VAL | VAR | USE
    name: str
    type: TypeRef | None
    init: "Expr | None"


@dataclass
class UseStmt(Stmt):  # ruleuseStatement: исп <выражение>
    expr: "Expr"


@dataclass
class Assign(Stmt):  # ruleexpressionWithAssign with an assignOp
    target: "Expr"
    op: str  # = += -= *= /=
    value: "Expr | None"


@dataclass
class ExprStmt(Stmt):
    expr: "Expr"


@dataclass
class If(Stmt):  # ruleifStatement
    branches: list[tuple["Expr", list[Stmt]]]  # if/elsif pairs
    else_body: list[Stmt] | None


@dataclass
class CaseWhen(Node):  # rulewhenPartStatement
    conditions: list["Expr"]
    body: list[Stmt]


@dataclass
class Case(Stmt):  # rulecaseStatement
    subject: "Expr | None"
    whens: list[CaseWhen]
    else_body: list[Stmt] | None


@dataclass
class While(Stmt):  # rulewhileStatement
    cond: "Expr"
    body: list[Stmt]


@dataclass
class ForEach(Stmt):  # ruleforEachStatement: для Х из Коллекция
    var: str
    source: "Expr"
    body: list[Stmt]


@dataclass
class ForTo(Stmt):  # ruleforToStatement: для Х = А [вниз] по Б [шаг С]
    var: str
    start_expr: "Expr"
    down: bool
    to: "Expr"
    step: "Expr | None"
    body: list[Stmt]


@dataclass
class Try(Stmt):  # ruletryStatement
    body: list[Stmt]
    catches: list[tuple[str, "TypeRef | None", list[Stmt]]]  # (var, type, body)
    finally_body: list[Stmt] | None


@dataclass
class Scope(Stmt):  # rulescopeStatement
    body: list[Stmt]


@dataclass
class Return(Stmt):
    value: "Expr | None"


@dataclass
class Break(Stmt):
    pass


@dataclass
class Continue(Stmt):
    pass


# --- expressions ---


@dataclass
class Expr(Node):
    pass


@dataclass
class Name(Expr):  # rulestaticVariableAccess: A::B::Name
    name: str


@dataclass
class Literal(Expr):
    kind: str  # NUMBER | STRING | TRUE | FALSE | UNDEFINED | PATTERN | TYPE | QUERY | RESOLVABLE
    text: str


@dataclass
class This(Expr):
    pass


@dataclass
class GlobalAccess(Expr):
    pass


@dataclass
class Unary(Expr):
    op: str  # - + не
    operand: Expr


@dataclass
class Binary(Expr):
    op: str
    left: Expr
    right: Expr | None  # the grammar allows a dangling operator during recovery


@dataclass
class Compare(Expr):  # rulelogPrimary: chained comparisons
    first: Expr
    rest: list[tuple[str, Expr | None]] = field(default_factory=list)


@dataclass
class IsType(Expr):  # `X это [не] Тип` (rulelogFact)
    operand: Expr
    negated: bool
    type: TypeRef | None


@dataclass
class AsType(Expr):  # `X как Тип`
    operand: Expr
    type: TypeRef | None


@dataclass
class Ternary(Expr):  # `cond ? a : b` (on the expression level)
    cond: Expr
    then: Expr
    otherwise: Expr | None


@dataclass
class Coalesce(Expr):  # `a ?? b`
    left: Expr
    right: Expr | None


@dataclass
class NonNull(Expr):  # postfix `!`
    operand: Expr


@dataclass
class Member(Expr):  # featureResolving step: `.name` / `?.name`
    obj: Expr
    name: str
    safe: bool


@dataclass
class Index(Expr):  # `obj[expr]`
    obj: Expr
    index: Expr | None


@dataclass
class CallArg(Node):
    name: str | None  # named argument `Имя = значение`
    value: Expr | None


@dataclass
class Call(Expr):  # ruleparams applied to a callee
    callee: Expr
    args: list[CallArg]
    type_args: list[TypeRef] = field(default_factory=list)


@dataclass
class New(Expr):  # rulecreator: новый Тип(...)
    type: TypeRef
    args: list[CallArg] | None


@dataclass
class ArrayLit(Expr):  # rulecollectionInitializer `[...]`
    items: list[Expr]
    type_args: list[TypeRef] = field(default_factory=list)


@dataclass
class MapLit(Expr):  # `{к: з, ...}` / `{:}`; kind='set' for `{a, b}` / `{}`
    entries: list[tuple[Expr, Expr | None]]
    kind: str  # map | set
    type_args: list[TypeRef] = field(default_factory=list)


@dataclass
class Lambda(Expr):  # rulelambdaShort / rulelambdaFull
    params: list[Param]
    body_expr: "Expr | Assign | None"
    body_stmts: list[Stmt] | None


@dataclass
class Throw(Expr):  # rulethrowExpression (an expression in the grammar)
    value: Expr | None


@dataclass
class MethodRef(Expr):  # rulemethodRef: &Тип.Метод
    text: str


# --- errors and driver -------------------------------------------------------------------


@dataclass
class ParseError:
    start: int
    end: int
    message: str


_STMT_KEYWORDS = frozenset({
    "IF", "CASE", "WHILE", "FOR", "TRY", "SCOPE",
    "BREAK", "CONTINUE", "RETURN", "VAR", "VAL", "USE",
})
# Keywords that may legally start an expression statement.
_EXPR_START_KEYWORDS = frozenset({
    "THIS", "GLOBAL_EN", "GLOBAL_RU", "NEW", "NOT", "THROW", "TRUE", "FALSE",
    "UNDEFINED", "QUERY", "TYPE", "METHOD",
})
_MODULE_KEYWORDS = frozenset({"STRUCTURE", "EXCEPTION", "ENUMERATION", "CONST"})
_COMPARE_OPS = ("<", "<=", "==", ">=", ">", "!=")
_ASSIGN_OPS = ("=", "+=", "-=", "*=", "/=")


def parse_text(text: str) -> tuple[Module, list[ParseError]]:
    from xbsl.lexer import tokenize

    return _Parser(tokenize(text)).parse_module()


def parse(source) -> tuple[Module, list[ParseError]]:
    """Parse a source file; the result is cached in source.cache."""
    cached = source.cache.get("ast")
    if cached is None:
        cached = _Parser(tokens(source)).parse_module()
        source.cache["ast"] = cached
    return cached


# A word usable as a name: identifiers plus the keywords the grammar lists in
# `ruleident` (обз/импорт/по/из/Тип/Запрос... may be plain names) and `метод`.
_NAME_KEYWORDS = frozenset({
    "EXCEPTION", "ENUMERATION", "STRUCTURE", "ABSTRACT", "CONST", "REQ", "IMPORT",
    "TO", "IN", "TYPE", "QUERY", "DOWN", "STEP", "METHOD", "DEFAULT", "STATIC",
    "GLOBAL_EN",
})

# Control keywords whose CAPITALIZED forms are legal names per ruleident: `Выбор`,
# `Если`, `И`, `Или`... are identifiers, while the lowercase forms are operators only
# (the grammar keeps them as separate *_KW_UP tokens; our lexer canonicalizes both
# forms, so the parser checks the letter case of the token value).
_UPPER_NAME_KEYWORDS = frozenset({
    "WHILE", "FOR", "IF", "TRY", "CASE", "WHEN", "CATCH", "AND", "OR",
    "CONSTRUCTOR",
})

# Keywords that can never start a return value - a bare `возврат` before them.
_RETURN_STOP = frozenset({"ELSE", "WHEN", "CATCH", "FINALLY"})


class _Parser:
    def __init__(self, toks: list[Token]) -> None:
        # Comments and the BOM are trivia for the parser; UNKNOWN chars are reported once.
        self.toks = [t for t in toks if t.kind not in ("COMMENT", "BOM")]
        self.pos = 0
        self.errors: list[ParseError] = []

    # --- cursor helpers ---

    def peek(self, ahead: int = 0) -> Token:
        # A hot spot (millions of calls per project): advance() never moves pos past EOF,
        # so for ahead=0 the index is always in bounds - no min() needed.
        if ahead == 0:
            return self.toks[self.pos]
        i = min(self.pos + ahead, len(self.toks) - 1)
        return self.toks[i]

    def at_end(self) -> bool:
        return self.peek().kind == "EOF"

    def advance(self) -> Token:
        t = self.toks[self.pos]
        if t.kind != "EOF":
            self.pos += 1
        return t

    def at_kw(self, *canon: str) -> bool:
        t = self.peek()
        return t.kind == "KEYWORD" and t.canonical in canon

    def at_op(self, *vals: str) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.value in vals

    def eat_kw(self, *canon: str) -> Token | None:
        if self.at_kw(*canon):
            return self.advance()
        return None

    def eat_op(self, *vals: str) -> Token | None:
        if self.at_op(*vals):
            return self.advance()
        return None

    def expect_op(self, val: str, key: str) -> Token | None:
        t = self.eat_op(val)
        if t is None:
            self.error(i18n.t(key))
        return t

    def error(self, message: str, tok: Token | None = None) -> None:
        t = tok or self.peek()
        end = t.end if t.end > t.start else t.start + 1
        self.errors.append(ParseError(t.start, end, message))

    def snapshot(self) -> tuple[int, int]:
        return self.pos, len(self.errors)

    def rollback(self, snap: tuple[int, int]) -> None:
        self.pos, n = snap
        del self.errors[n:]


    def at_name(self) -> bool:
        t = self.peek()
        if t.kind == "IDENT":
            return True
        if t.kind != "KEYWORD":
            return False
        if t.canonical in _NAME_KEYWORDS:
            return True
        return t.canonical in _UPPER_NAME_KEYWORDS and t.value[:1].isupper()

    def eat_name(self) -> Token | None:
        if self.at_name():
            return self.advance()
        return None

    # --- module level (rulemodule) ---

    def parse_module(self) -> tuple[Module, list[ParseError]]:
        start = self.peek().start
        module = Module(start, start)
        while not self.at_end():
            before = self.pos
            self.module_member(module)
            if self.pos == before:  # nothing consumed - report and step over
                self.error(i18n.t("parser.unexpected-module-code"))
                self.advance()
        module.end = self.peek().end
        return module, self.errors

    def module_member(self, module: Module) -> None:
        if self.at_op("#"):  # ruledirective - to the end of the line
            line = self.peek().line
            self.advance()
            while not self.at_end() and self.peek().line == line:
                self.advance()
            return
        if self.at_kw("IMPORT"):
            module.imports.append(self.namespace_import())
            return
        annotations = self.annotations()
        if self.at_kw("STATIC", "METHOD", "ABSTRACT"):
            module.members.append(self.method(annotations))
        elif self.at_kw("STRUCTURE", "EXCEPTION"):
            module.members.append(self.structure(annotations))
        elif self.at_kw("ENUMERATION"):
            module.members.append(self.enum(annotations))
        elif self.at_kw("VAL", "VAR", "USE", "CONST"):
            module.members.append(self.module_const(annotations))
        elif annotations:
            self.error(i18n.t("parser.annotation-needs-member"))
        else:
            self.error(i18n.t("parser.expected-module-member"))
            self.recover_to_module_member()

    def recover_to_module_member(self) -> None:
        while not self.at_end():
            if self.at_kw("IMPORT", "METHOD", "ABSTRACT", "STATIC", "STRUCTURE",
                          "EXCEPTION", "ENUMERATION", "VAL", "VAR", "USE", "CONST"):
                return
            if self.at_op("@"):
                return
            self.advance()

    def namespace_import(self) -> Import:
        start = self.advance().start  # IMPORT
        parts = []
        while True:
            name = self.eat_name()
            if name is None:
                self.error(i18n.t("parser.expected-import-name"))
                break
            parts.append(name.value)
            if not self.eat_op("::"):
                break
        end = self.toks[self.pos - 1].end
        return Import(start, end, "::".join(parts))

    # --- annotations (ruleannotation) ---

    def annotations(self) -> list[Annotation]:
        result: list[Annotation] = []
        while self.at_op("@"):
            at = self.advance()
            parts = []
            while self.at_name():
                parts.append(self.advance().value)
                if not self.eat_op("::"):
                    break
            args: list[Expr | None] = []
            if self.at_op("(") and self.peek().line == at.line:
                args = self.annotation_args()
            end = self.toks[self.pos - 1].end
            result.append(Annotation(at.start, end, "::".join(parts), args))
            if not parts:
                # a bare `@` (RULE_AT_EMPTY) is legal; no arguments belong to it
                break
        return result

    def annotation_args(self) -> list[Expr | None]:
        # ruleparamsWithAnn: `Имя = литерал` or a literal; nested annotations allowed
        self.advance()  # (
        args: list[Expr | None] = []
        while not self.at_end() and not self.at_op(")"):
            if self.at_name() and self.peek(1).kind == "OP" and self.peek(1).value == "=":
                self.advance()
                self.advance()
            if self.at_op("@"):
                self.annotations()
                args.append(None)
            elif self.at_op(","):
                args.append(None)
            else:
                args.append(self.expression())
            if not self.eat_op(","):
                break
        self.expect_op(")", "parser.expected-rparen-annotation")
        return args

    # --- module members ---

    def method(self, annotations: list[Annotation]) -> Method:
        start = annotations[0].start if annotations else self.peek().start
        is_static = self.eat_kw("STATIC") is not None
        is_abstract = self.eat_kw("ABSTRACT") is not None
        if is_abstract:
            self.eat_kw("STATIC")
        if not self.eat_kw("METHOD"):
            self.error(i18n.t("parser.expected-method-kw"))
        name_tok = self.eat_name()
        name = name_tok.value if name_tok else ""
        if name_tok is None:
            self.error(i18n.t("parser.expected-method-name"))
        params = self.parameters()
        return_type = None
        if self.eat_op(":"):
            if not self.at_kw("VOID") or True:  # ничто is parsed as a plain type name
                return_type = self.compound_type()
        body: list[Stmt] = []
        if not is_abstract:
            body = self.statements_until_semicolon("parser.expected-semicolon-method")
        end = self.toks[self.pos - 1].end
        return Method(start, end, name, params, return_type, body,
                      is_static=is_static, is_abstract=is_abstract, annotations=annotations)

    def parameters(self) -> list[Param]:
        params: list[Param] = []
        if not self.expect_op("(", "parser.expected-lparen-method"):
            return params
        while not self.at_end() and not self.at_op(")"):
            anns = self.annotations()
            name_tok = self.eat_name()
            if name_tok is None:
                self.error(i18n.t("parser.expected-param-name"))
                break
            ptype = self.compound_type() if self.eat_op(":") else None
            default = self.expression() if self.eat_op("=") else None
            params.append(Param(
                (anns[0].start if anns else name_tok.start),
                self.toks[self.pos - 1].end,
                name_tok.value, ptype, default, anns,
            ))
            self.eat_op(",")  # the comma between parameters is optional in the grammar
        self.expect_op(")", "parser.expected-rparen-params")
        return params

    def structure(self, annotations: list[Annotation]) -> Structure:
        kw = self.advance()  # STRUCTURE | EXCEPTION
        start = annotations[0].start if annotations else kw.start
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-struct-name"))
        node = Structure(start, start, kw.canonical or "", name_tok.value if name_tok else "",
                         annotations=annotations)
        while not self.at_end() and not self.at_op(";"):
            before = self.pos
            member_anns = self.annotations()
            if self.at_kw("METHOD", "STATIC", "ABSTRACT"):
                node.members.append(self.method(member_anns))
            elif self.at_kw("CONSTRUCTOR"):
                c = self.advance()
                ctor = Constructor(c.start, c.end, member_anns)
                node.members.append(ctor)
            elif self.at_kw("REQ", "VAL", "VAR", "USE"):
                node.members.append(self.object_field(member_anns))
            else:
                self.error(i18n.t("parser.expected-struct-member"))
                self.advance()
            if self.pos == before:
                self.advance()
        self.expect_op(";", "parser.expected-semicolon-struct")
        node.end = self.toks[self.pos - 1].end
        return node

    def object_field(self, annotations: list[Annotation]) -> ObjectField:
        start = annotations[0].start if annotations else self.peek().start
        required = self.eat_kw("REQ") is not None
        kind_tok = self.eat_kw("VAL", "VAR", "USE")
        kind = kind_tok.canonical if kind_tok else "VAL"
        if kind_tok is None:
            self.error(i18n.t("parser.expected-field-kw"))
        if not required:
            required = self.eat_kw("REQ") is not None
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-field-name"))
        ftype = self.compound_type() if self.eat_op(":") else None
        init = self.expression() if self.eat_op("=") else None
        return ObjectField(start, self.toks[self.pos - 1].end, kind or "VAL",
                           name_tok.value if name_tok else "", ftype, init,
                           required=required, annotations=annotations)

    def enum(self, annotations: list[Annotation]) -> Enum:
        kw = self.advance()
        start = annotations[0].start if annotations else kw.start
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-enum-name"))
        node = Enum(start, start, name_tok.value if name_tok else "", annotations=annotations)
        while not self.at_end() and not self.at_op(";"):
            member_anns = self.annotations()
            if self.at_kw("METHOD", "STATIC", "ABSTRACT"):
                node.methods.append(self.method(member_anns))
                continue
            item = self.eat_name()
            if item is None:
                self.error(i18n.t("parser.expected-enum-value"))
                self.advance()
                continue
            is_default = self.eat_kw("DEFAULT") is not None
            node.items.append(EnumItem(item.start, self.toks[self.pos - 1].end,
                                       item.value, is_default))
            self.eat_op(",")
        self.expect_op(";", "parser.expected-semicolon-enum")
        node.end = self.toks[self.pos - 1].end
        return node

    def module_const(self, annotations: list[Annotation]) -> ObjectField:
        # rulemoduleConst - like a field, but конст is allowed as the kind
        start = annotations[0].start if annotations else self.peek().start
        kind_tok = self.advance()  # VAL | VAR | USE | CONST
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-const-name"))
        ftype = self.compound_type() if self.eat_op(":") else None
        init = self.expression() if self.eat_op("=") else None
        return ObjectField(start, self.toks[self.pos - 1].end,
                           kind_tok.canonical or "", name_tok.value if name_tok else "",
                           ftype, init, annotations=annotations)

    # --- types (rulecompoundTypeName) ---

    def compound_type(self) -> TypeRef | None:
        start_tok = self.peek()
        if self.at_kw("UNKNOWN", "VOID", "NEVER"):
            t = self.advance()
            return TypeRef(t.start, t.end, t.value, [t.value])
        names: list[str] = []
        nullable = False
        parts: list[str] = []
        while True:
            if self.at_op("?"):
                q = self.advance()
                nullable = True
                parts.append("?")
            else:
                alt = self.type_name()
                if alt is None:
                    if not names and not nullable:
                        self.error(i18n.t("parser.expected-type-name"), start_tok)
                        return None
                    break
                names.append(alt[0])
                parts.append(alt[1])
                if self.at_op("?"):
                    self.advance()
                    nullable = True
                    parts.append("?")
            if not self.eat_op("|"):
                break
            parts.append("|")
        end = self.toks[self.pos - 1].end
        return TypeRef(start_tok.start, end, "".join(parts), names, nullable)

    def type_name(self) -> tuple[str, str] | None:
        """ruletypeName -> (root name, source text); None if there is no type here."""
        if self.at_op("("):  # funcTypeName: (Типы) -> Тип
            snap = self.snapshot()
            text = self.func_type()
            if text is not None:
                return ("(func)", text)
            self.rollback(snap)
            return None
        if not self.at_name() and not self.at_kw("UNDEFINED"):
            return None
        start = self.pos
        segs = [self.advance().value]
        while self.at_op("::"):
            self.advance()
            nxt = self.eat_name()
            if nxt is None:
                break
            segs.append(nxt.value)
        # dotted segments: Справочник.Ссылка, and Неопределено is a legal segment
        while self.at_op(".") and (self.peek(1).kind == "IDENT"
                                   or (self.peek(1).kind == "KEYWORD"
                                       and self.peek(1).canonical in (_NAME_KEYWORDS | {"UNDEFINED"}))):
            self.advance()
            segs.append(self.advance().value)
        text = "".join(t.value for t in self.toks[start:self.pos])
        if self.at_op("<"):  # generic parameters
            snap = self.snapshot()
            if not self.generic_type_args(allow_named=True):
                self.rollback(snap)
            else:
                text = "".join(t.value for t in self.toks[start:self.pos])
        return (segs[0], text)

    def func_type(self) -> str | None:
        start = self.pos
        self.advance()  # (
        while not self.at_end() and not self.at_op(")"):
            if self.compound_type() is None:
                return None
            if not self.eat_op(","):
                break
        if not self.eat_op(")"):
            return None
        if not self.eat_op("->"):
            return None
        self.compound_type()  # the result type may be absent
        return "".join(t.value for t in self.toks[start:self.pos])

    def generic_type_args(self, allow_named: bool = False) -> bool:
        """`<Тип, Имя=Тип, ...>` after a name; returns False if this is not a generic."""
        self.advance()  # <
        if self.at_op(">"):  # `<>` is not a generic
            return False
        while True:
            if allow_named and self.at_name() and self.peek(1).kind == "OP" and self.peek(1).value == "=":
                self.advance()
                self.advance()
            if self.compound_type() is None:
                return False
            if self.eat_op(","):
                continue
            break
        return self.eat_op(">") is not None

    # --- statements ---

    def statements_until_semicolon(self, key: str) -> list[Stmt]:
        body: list[Stmt] = []
        while not self.at_end() and not self.at_op(";"):
            before = self.pos
            stmt = self.statement()
            if stmt is not None:
                body.append(stmt)
            if self.pos == before:
                self.error(i18n.t("parser.statement-unparsed"))
                self.recover_statement()
        if not self.eat_op(";"):
            self.error(i18n.t(key))
        return body

    def block_until(self, *stop_canon: str) -> list[Stmt]:
        """Statements until `;` or one of the stop keywords (else/when/catch...)."""
        body: list[Stmt] = []
        while not self.at_end() and not self.at_op(";") and not self.at_kw(*stop_canon):
            before = self.pos
            stmt = self.statement()
            if stmt is not None:
                body.append(stmt)
            if self.pos == before:
                self.error(i18n.t("parser.statement-unparsed"))
                self.recover_statement()
        return body

    def recover_statement(self) -> None:
        line = self.peek().line
        while not self.at_end():
            t = self.peek()
            if t.line != line:
                return
            if t.kind == "OP" and t.value == ";":
                return
            self.advance()

    def statement(self) -> Stmt | None:
        t = self.peek()
        if t.kind == "KEYWORD":
            c = t.canonical
            # A capitalized control word followed by an expression continuation is a
            # NAME (`Выбор = ...`, `Если.Поле`), not a statement keyword.
            if c in _UPPER_NAME_KEYWORDS and t.value[:1].isupper():
                nxt = self.peek(1)
                if nxt.kind == "OP" and nxt.value in (
                    "=", "+=", "-=", "*=", "/=", ".", "?.", "[", "(", "::", "!",
                ):
                    return self.expression_statement()
            if c == "IF":
                return self.if_statement()
            if c == "CASE":
                return self.case_statement()
            if c == "WHILE":
                return self.while_statement()
            if c == "FOR":
                return self.for_statement()
            if c == "TRY":
                return self.try_statement()
            if c == "SCOPE":
                return self.scope_statement()
            if c == "BREAK":
                tok = self.advance()
                return Break(tok.start, tok.end)
            if c == "CONTINUE":
                tok = self.advance()
                return Continue(tok.start, tok.end)
            if c == "RETURN":
                return self.return_statement()
            if c in ("VAR", "VAL"):
                return self.var_decl()
            if c == "USE":
                return self.use_statement()
        return self.expression_statement()

    def if_statement(self) -> If:
        start = self.advance().start  # IF
        branches: list[tuple[Expr, list[Stmt]]] = []
        cond = self.expression()
        body = self.block_until("ELSE")
        branches.append((cond, body))
        else_body: list[Stmt] | None = None
        while self.at_kw("ELSE"):
            else_tok = self.advance()
            # `иначе если` on the SAME line is an elsif; `если` on the next line opens
            # a nested if inside the else branch (the grammar: RULE_ELSE (RULE_NL)+ ...).
            if self.at_kw("IF") and self.peek().line == else_tok.line:
                self.advance()
                cond = self.expression()
                body = self.block_until("ELSE")
                branches.append((cond, body))
            else:
                else_body = self.block_until("ELSE")
                if self.at_kw("ELSE"):
                    self.error(i18n.t("parser.duplicate-else"))
                break
        self.expect_op(";", "parser.expected-semicolon-if")
        return If(start, self.toks[self.pos - 1].end, branches, else_body)

    def case_statement(self) -> Case:
        start = self.advance().start  # CASE
        subject = None
        if not self.at_kw("WHEN", "ELSE") and not self.at_op(";"):
            subject = self.expression()
        whens: list[CaseWhen] = []
        while self.at_kw("WHEN"):
            wstart = self.advance().start
            conds = [self.when_expression()]
            while self.eat_op(","):
                conds.append(self.when_expression())
            body = self.block_until("WHEN", "ELSE")
            whens.append(CaseWhen(wstart, self.toks[self.pos - 1].end, conds, body))
        else_body = None
        if self.at_kw("ELSE"):
            self.advance()
            else_body = self.block_until("WHEN")
        self.expect_op(";", "parser.expected-semicolon-case")
        return Case(start, self.toks[self.pos - 1].end, subject, whens, else_body)

    def when_expression(self) -> Expr:
        # rulewhenExpression: expression | `это [не] Тип` | `<сравнение> выражение`
        t = self.peek()
        if self.at_kw("IS"):
            self.advance()
            negated = self.eat_kw("NOT") is not None
            wtype = self.compound_type()
            return IsType(t.start, self.toks[self.pos - 1].end,
                          Name(t.start, t.start, ""), negated, wtype)
        if self.at_op(*_COMPARE_OPS):
            op = self.advance()
            right = self.expression()
            return Compare(t.start, right.end, Name(t.start, t.start, ""), [(op.value, right)])
        return self.expression()

    def while_statement(self) -> While:
        start = self.advance().start
        cond = self.expression()
        body = self.statements_until_semicolon("parser.expected-semicolon-while")
        return While(start, self.toks[self.pos - 1].end, cond, body)

    def for_statement(self) -> Stmt:
        start = self.advance().start  # FOR
        var_tok = self.eat_name()
        var = var_tok.value if var_tok else ""
        if var_tok is None:
            self.error(i18n.t("parser.expected-loop-var"))
        if self.at_kw("IN"):  # для Х из Коллекция
            self.advance()
            source = self.expression()
            body = self.statements_until_semicolon("parser.expected-semicolon-for")
            return ForEach(start, self.toks[self.pos - 1].end, var, source, body)
        self.expect_op("=", "parser.expected-eq-in-for")
        start_expr = self.expression()
        down = self.eat_kw("DOWN") is not None
        if not self.eat_kw("TO"):
            self.error(i18n.t("parser.expected-po-in-for"))
        to = self.expression()
        step = None
        if self.eat_kw("STEP"):
            step = self.expression()
        body = self.statements_until_semicolon("parser.expected-semicolon-for")
        return ForTo(start, self.toks[self.pos - 1].end, var, start_expr, down, to, step, body)

    def try_statement(self) -> Try:
        start = self.advance().start  # TRY
        body = self.block_until("CATCH", "FINALLY")
        catches: list[tuple[str, TypeRef | None, list[Stmt]]] = []
        while self.at_kw("CATCH"):
            self.advance()
            name_tok = self.eat_name()
            cname = name_tok.value if name_tok else ""
            if name_tok is None:
                self.error(i18n.t("parser.expected-catch-var"))
            self.expect_op(":", "parser.expected-colon-catch")
            ctype = self.compound_type()
            cbody = self.block_until("CATCH", "FINALLY")
            catches.append((cname, ctype, cbody))
        finally_body = None
        if self.at_kw("FINALLY"):
            self.advance()
            finally_body = self.block_until("CATCH")
        self.expect_op(";", "parser.expected-semicolon-try")
        return Try(start, self.toks[self.pos - 1].end, body, catches, finally_body)

    def scope_statement(self) -> Scope:
        start = self.advance().start
        body = self.statements_until_semicolon("parser.expected-semicolon-scope")
        return Scope(start, self.toks[self.pos - 1].end, body)


    def return_statement(self) -> Return:
        tok = self.advance()
        value = None
        if not self.at_op(";") and not self.at_end() and not self.starts_new_statement(tok.line):
            value = self.expression()
        return Return(tok.start, self.toks[self.pos - 1].end, value)

    def starts_new_statement(self, prev_line: int) -> bool:
        """A bare `возврат`: the next token opens a branch or a new statement."""
        t = self.peek()
        if t.kind == "KEYWORD" and t.canonical in _RETURN_STOP:
            return True
        if t.line == prev_line:
            return False
        if t.kind == "KEYWORD" and t.canonical in _STMT_KEYWORDS:
            return True
        return False

    def var_decl(self) -> Stmt:
        kind_tok = self.advance()  # VAR | VAL
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-var-name"))
        vtype = self.compound_type() if self.eat_op(":") else None
        init = self.expression() if self.eat_op("=") else None
        if vtype is None and init is None:
            self.error(i18n.t("parser.decl-needs-type-or-value"), name_tok or kind_tok)
        return VarDecl(kind_tok.start, self.toks[self.pos - 1].end,
                       kind_tok.canonical or "", name_tok.value if name_tok else "",
                       vtype, init)

    def use_statement(self) -> Stmt:
        # `исп Имя = выражение` / `исп Имя: Тип [= ...]` is a declaration,
        # `исп Выражение` is a use-statement over an expression (ruleuseStatement).
        kind_tok = self.advance()
        if self.at_name():
            nxt = self.peek(1)
            if nxt.kind == "OP" and nxt.value in (":", "="):
                name_tok = self.advance()
                vtype = self.compound_type() if self.eat_op(":") else None
                init = self.expression() if self.eat_op("=") else None
                return VarDecl(kind_tok.start, self.toks[self.pos - 1].end, "USE",
                               name_tok.value, vtype, init)
        expr = self.expression()
        return UseStmt(kind_tok.start, expr.end, expr)

    def expression_statement(self) -> Stmt | None:
        start_tok = self.peek()
        if start_tok.kind == "OP" and start_tok.value == ";":
            return None
        expr = self.expression()
        if expr.end == expr.start and self.pos < len(self.toks):
            return None
        if self.at_op(*_ASSIGN_OPS):
            op = self.advance()
            value = None
            if not self.at_op(";") and not self.at_end():
                value = self.expression()
            else:
                self.error(i18n.t("parser.expected-expr-after-assign"), op)
            return Assign(expr.start, self.toks[self.pos - 1].end, expr, op.value, value)
        return ExprStmt(expr.start, expr.end, expr)

    # --- expressions (the precedence cascade of the grammar) ---

    def expression(self) -> Expr:
        # ruleexpression: or-chain, then postfix `!`, `?? expr`, `? a : b`
        left = self.log_term()
        while self.at_kw("OR"):
            op = self.advance()
            right = None
            if not self.expression_ended():
                right = self.log_term()
            left = Binary(left.start, (right or left).end, op.value, left, right)
        if self.at_op("!") and not self.expression_ended():
            t = self.advance()
            left = NonNull(left.start, t.end, left)
        if self.at_op("??"):
            self.advance()
            right = self.expression()
            left = Coalesce(left.start, right.end, left, right)
        if self.at_op("?") and not self.at_op("?."):
            self.advance()
            then = self.expression()
            otherwise = None
            if self.expect_op(":", "parser.expected-colon-ternary"):
                otherwise = self.expression()
            left = Ternary(left.start, self.toks[self.pos - 1].end, left, then, otherwise)
        return left

    def expression_ended(self) -> bool:
        t = self.peek()
        return t.kind == "EOF" or (t.kind == "OP" and t.value in (";", ")", "]", "}", ","))

    def log_term(self) -> Expr:
        left = self.log_fact()
        while self.at_kw("AND"):
            op = self.advance()
            right = None
            if not self.expression_ended():
                right = self.log_fact()
            left = Binary(left.start, (right or left).end, op.value, left, right)
        return left

    def log_fact(self) -> Expr:
        # rulelogFact: [не] logPrimary [это [не] Тип | как Тип]
        if self.at_kw("NOT"):
            op = self.advance()
            operand = self.log_fact()
            return Unary(op.start, operand.end, op.value, operand)
        left = self.log_primary()
        while self.at_kw("IS", "AS"):
            kw = self.advance()
            if kw.canonical == "IS":
                negated = self.eat_kw("NOT") is not None
                t = self.compound_type()
                left = IsType(left.start, self.toks[self.pos - 1].end, left, negated, t)
                # The grammar's special branch: `x это Тип ? a : b` - the ternary right
                # after the type. compound_type() may have eaten the `?` as nullable, so
                # a lone `:` after an expression re-reads it as the ternary separator.
                if t is not None and t.nullable and t.text.endswith("?") and not self.at_op(";"):
                    snap = self.snapshot()
                    then = self.expression()
                    if self.eat_op(":"):
                        otherwise = self.expression()
                        t.nullable = False
                        t.text = t.text[:-1]
                        left = Ternary(left.start, self.toks[self.pos - 1].end,
                                       left, then, otherwise)
                    else:
                        self.rollback(snap)
            else:
                t = self.compound_type()
                left = AsType(left.start, self.toks[self.pos - 1].end, left, t)
        return left

    def log_primary(self) -> Expr:
        # rulelogPrimary: chained comparisons a < b <= c
        first = self.simple_expression()
        rest: list[tuple[str, Expr | None]] = []
        while self.at_op(*_COMPARE_OPS):
            op = self.advance()
            right = None
            if not self.expression_ended():
                right = self.simple_expression()
            rest.append((op.value, right))
        if not rest:
            return first
        last = rest[-1][1]
        return Compare(first.start, (last or first).end, first, rest)

    def simple_expression(self) -> Expr:
        left = self.term()
        while self.at_op("+", "-"):
            op = self.advance()
            right = None
            if not self.expression_ended():
                right = self.term()
            left = Binary(left.start, (right or left).end, op.value, left, right)
        return left

    def term(self) -> Expr:
        left = self.exp()
        while self.at_op("*", "/", "%"):
            op = self.advance()
            right = None
            if not self.expression_ended():
                right = self.exp()
            left = Binary(left.start, (right or left).end, op.value, left, right)
        return left

    def exp(self) -> Expr:
        left = self.fact()
        if self.at_op("**"):  # right-associative per the grammar (exp on the right)
            op = self.advance()
            right = self.exp()
            return Binary(left.start, right.end, op.value, left, right)
        return left

    def fact(self) -> Expr:
        if self.at_op("+", "-"):
            op = self.advance()
            operand = self.fact()
            return Unary(op.start, operand.end, op.value, operand)
        if self.at_op("&"):
            return self.method_ref()
        return self.feature_resolving()

    def method_ref(self) -> Expr:
        # rulemethodRef: & [this.|глобальный.] Имя[::Имя]* (.Имя|.новый)* [<Типы>]
        #               [.Имя|.новый] [ (Типы) ]  - a signature-qualified method reference
        start = self.advance().start  # &
        begun = self.pos
        if self.at_kw("THIS", "GLOBAL_EN", "GLOBAL_RU"):
            self.advance()
            if not self.eat_op("."):
                self.error(i18n.t("parser.expected-dot-in-method-ref"))
        name_tok = self.eat_name()
        if name_tok is None:
            self.error(i18n.t("parser.expected-name-in-method-ref"))
        while self.at_op("::"):
            self.advance()
            if self.eat_name() is None:
                self.error(i18n.t("parser.expected-name-after-colons"))
                break
        while self.at_op(".") and (self.peek(1).kind == "IDENT"
                                   or (self.peek(1).kind == "KEYWORD"
                                       and self.peek(1).canonical in _NAME_KEYWORDS | {"NEW"})):
            self.advance()
            self.advance()
        if self.at_op("<"):
            snap = self.snapshot()
            if not self.generic_call_args():
                self.rollback(snap)
            elif self.at_op(".") :
                self.advance()
                if self.eat_name() is None:
                    self.eat_kw("NEW")
        if self.at_op("("):  # the optional signature: (Тип, Тип)
            snap = self.snapshot()
            self.advance()
            ok = True
            while not self.at_op(")") and not self.at_end():
                if self.compound_type() is None:
                    ok = False
                    break
                if not self.eat_op(","):
                    break
            if not ok or not self.eat_op(")"):
                self.rollback(snap)
        end = self.toks[self.pos - 1].end if self.pos > begun else start + 1
        text = "".join(t.value for t in self.toks[begun:self.pos])
        return MethodRef(start, end, text)

    # --- postfix chains (rulefeatureResolving) ---

    def feature_resolving(self) -> Expr:
        expr = self.static_feature_resolving()
        while True:
            if self.at_op(".", "?."):
                dot = self.advance()
                name_tok = self.eat_name() or self.eat_kw("NEW")
                if name_tok is None:
                    self.error(i18n.t("parser.expected-name-after-dot"))
                    break
                expr = Member(expr.start, name_tok.end, expr, name_tok.value,
                              safe=(dot.value == "?."))
                expr = self.maybe_call(expr)
            elif self.at_op("["):
                lb = self.advance()
                index = None
                if not self.at_op("]"):
                    index = self.expression()
                self.expect_op("]", "parser.expected-rbracket-index")
                expr = Index(expr.start, self.toks[self.pos - 1].end, expr, index)
            elif self.at_op("!") and not self.postfix_bang_ambiguous():
                t = self.advance()
                expr = NonNull(expr.start, t.end, expr)
            else:
                break
        return expr

    def postfix_bang_ambiguous(self) -> bool:
        """`а != б`: the lexer already yields `!=` as one token, so a bare `!` is safe -
        except `! =` split across trivia can not occur; keep the hook for clarity."""
        return False

    def maybe_call(self, callee: Expr) -> Expr:
        type_args: list[TypeRef] = []
        if self.at_op("<"):
            snap = self.snapshot()
            begun = self.pos
            if self.generic_call_args():
                type_args = [TypeRef(self.toks[begun].start, self.toks[self.pos - 1].end,
                                     "".join(t.value for t in self.toks[begun:self.pos]), [])]
                if not self.at_op("("):
                    self.rollback(snap)
                    return callee
            else:
                self.rollback(snap)
                return callee
        if self.at_op("("):
            args = self.call_args()
            return Call(callee.start, self.toks[self.pos - 1].end, callee, args, type_args)
        return callee

    def generic_call_args(self) -> bool:
        self.advance()  # <
        if self.at_op(">"):
            return False
        while True:
            if self.compound_type() is None:
                return False
            if self.eat_op(","):
                continue
            break
        return self.eat_op(">") is not None

    def call_args(self) -> list[CallArg]:
        self.advance()  # (
        args: list[CallArg] = []
        while not self.at_end() and not self.at_op(")"):
            start_tok = self.peek()
            name = None
            if self.at_name() and self.peek(1).kind == "OP" and self.peek(1).value == "=" \
                    and not (self.peek(2).kind == "OP" and self.peek(2).value == "="):
                name = self.advance().value
                self.advance()  # =
            value = None
            if not self.at_op(",", ")"):
                value = self.expression()
            args.append(CallArg(start_tok.start, self.toks[self.pos - 1].end, name, value))
            if not self.eat_op(","):
                break
        self.expect_op(")", "parser.expected-rparen-call")
        return args

    # --- atoms (rulestaticFeatureResolving) ---

    def static_feature_resolving(self) -> Expr:
        t = self.peek()
        if t.kind == "KEYWORD":
            c = t.canonical
            if c == "THROW":
                self.advance()
                value = None
                if not self.expression_ended():
                    value = self.expression()
                return Throw(t.start, self.toks[self.pos - 1].end, value)
            if c == "THIS":
                self.advance()
                return This(t.start, t.end)
            if c in ("GLOBAL_EN", "GLOBAL_RU"):
                self.advance()
                return GlobalAccess(t.start, t.end)
            if c == "NEW":
                return self.creator()
            if c == "UNDEFINED":
                self.advance()
                return Literal(t.start, t.end, "UNDEFINED", t.value)
            if c in ("TRUE", "FALSE"):
                self.advance()
                return Literal(t.start, t.end, c, t.value)
            if c == "TYPE":
                return self.type_literal()
            if c == "QUERY":
                return self.query_literal()
            if c == "METHOD":
                # `метод (a) -> ...;` is a full lambda, but `Метод` is also a legal plain
                # name (ruleident): `Отправить(..., Метод, ...)` - try the lambda, roll back.
                if self.peek(1).kind == "OP" and self.peek(1).value == "(":
                    snap = self.snapshot()
                    lam = self.try_lambda_full()
                    if lam is not None:
                        return lam
                    self.rollback(snap)
                name_tok = self.advance()
                return self.maybe_call(Name(name_tok.start, name_tok.end, name_tok.value))
        if t.kind == "NUMBER":
            self.advance()
            return Literal(t.start, t.end, "NUMBER", t.value)
        if t.kind == "STRING":
            self.advance()
            return Literal(t.start, t.end, "STRING", t.value)
        if t.kind == "PATTERN":  # rulepatternLiteral: one lexer token since the "'" fix
            self.advance()
            return Literal(t.start, t.end, "PATTERN", t.value)
        if t.kind == "OP":
            if t.value == "(":
                return self.paren_or_lambda()
            if t.value == "[":
                return self.array_literal()
            if t.value == "{":
                return self.map_literal()
            if t.value == "<":  # typed collection: <Т>[...] / <К,З>{...}
                snap = self.snapshot()
                begun = self.pos
                if self.generic_call_args() and self.at_op("[", "{"):
                    text = "".join(tk.value for tk in self.toks[begun:self.pos])
                    targs = [TypeRef(t.start, self.toks[self.pos - 1].end, text, [])]
                    lit = self.array_literal() if self.at_op("[") else self.map_literal()
                    lit.type_args = targs
                    lit.start = t.start
                    return lit
                self.rollback(snap)
        if self.at_name():
            # resolvableLiteral `Идент{ ... }` (e.g. Ресурс{...}) - a braced literal
            if self.peek(1).kind == "OP" and self.peek(1).value == "{" \
                    and self.peek(1).start == t.end:
                return self.resolvable_literal()
            return self.static_feature()
        self.error(i18n.t("parser.expected-expr"))
        return Name(t.start, t.start, "")

    def paren_or_lambda(self) -> Expr:
        # `(a, b) -> ...` is a lambda; `(выражение)` is grouping
        snap = self.snapshot()
        lb = self.advance()  # (
        params: list[Param] = []
        is_lambda = True
        if not self.at_op(")"):
            while True:
                name_tok = self.eat_name()
                if name_tok is None:
                    is_lambda = False
                    break
                ptype = None
                if self.eat_op(":"):
                    ptype = self.compound_type()
                params.append(Param(name_tok.start, self.toks[self.pos - 1].end,
                                    name_tok.value, ptype, None))
                if self.eat_op(","):
                    continue
                break
        if is_lambda and self.eat_op(")") and self.at_op("->"):
            self.advance()
            body = None
            if not self.expression_ended():
                body = self.expression()
            return Lambda(lb.start, self.toks[self.pos - 1].end, params, body, None)
        self.rollback(snap)
        self.advance()  # (
        inner = self.expression()
        self.expect_op(")", "parser.expected-rparen-paren")
        return inner if inner.end > inner.start else inner

    def static_feature(self) -> Expr:
        # rulestaticFeature: A::B::Name [<...>] [(...)], or a short lambda `x -> ...`
        start_tok = self.peek()
        segs = [self.advance().value]
        while self.at_op("::"):
            self.advance()
            nxt = self.eat_name()
            if nxt is None:
                self.error(i18n.t("parser.expected-name-after-colons"))
                break
            segs.append(nxt.value)
        name = Name(start_tok.start, self.toks[self.pos - 1].end, "::".join(segs))
        if self.at_op("->"):  # lambdaShort with a single parameter
            self.advance()
            body = None
            if not self.expression_ended():
                body = self.expression()
            return Lambda(name.start, self.toks[self.pos - 1].end,
                          [Param(name.start, name.end, segs[-1], None, None)], body, None)
        return self.maybe_call(name)

    def creator(self) -> Expr:
        start = self.advance().start  # NEW
        t = self.type_name()
        if t is None:
            self.error(i18n.t("parser.expected-type-after-new"))
            return New(start, self.toks[self.pos - 1].end,
                       TypeRef(start, start, "", []), None)
        tref = TypeRef(start, self.toks[self.pos - 1].end, t[1], [t[0]])
        args = None
        if self.at_op("("):
            args = self.call_args()
        return New(start, self.toks[self.pos - 1].end, tref, args)

    def array_literal(self) -> ArrayLit:
        lb = self.advance()  # [
        items: list[Expr] = []
        while not self.at_end() and not self.at_op("]"):
            items.append(self.expression())
            if not self.eat_op(","):
                break
        self.expect_op("]", "parser.expected-rbracket-array")
        return ArrayLit(lb.start, self.toks[self.pos - 1].end, items)

    def map_literal(self) -> MapLit:
        lb = self.advance()  # {
        entries: list[tuple[Expr, Expr | None]] = []
        kind = "set"
        if self.at_op(":"):  # `{:}` - an empty map
            self.advance()
            kind = "map"
        while not self.at_end() and not self.at_op("}"):
            key = self.expression()
            if self.eat_op(":"):
                kind = "map"
                value = None
                if not self.at_op(",", "}"):
                    value = self.expression()
                entries.append((key, value))
            else:
                entries.append((key, None))
            if not self.eat_op(","):
                break
        self.expect_op("}", "parser.expected-rbrace-map")
        return MapLit(lb.start, self.toks[self.pos - 1].end, entries, kind)

    def try_lambda_full(self) -> Expr | None:
        # rulelambdaFull: метод (параметры) -> операторы ; - None if `->` never comes
        start = self.advance().start  # METHOD
        params = self.parameters()
        if not self.eat_op("->"):
            return None
        body = self.statements_until_semicolon("parser.expected-semicolon-lambda")
        return Lambda(start, self.toks[self.pos - 1].end, params, None, body)

    def type_literal(self) -> Expr:
        # ruletypeLiteral: Тип<Имя>
        start_tok = self.advance()  # TYPE
        if not self.at_op("<"):
            # `Тип` is also a legal plain name (ruleident includes RULE_TYPE)
            name = Name(start_tok.start, start_tok.end, start_tok.value)
            return self.maybe_call(name)
        self.advance()
        self.type_name()
        if not self.eat_op(">"):
            self.error(i18n.t("parser.expected-gt-in-type-literal"))
        end = self.toks[self.pos - 1].end
        return Literal(start_tok.start, end, "TYPE", "")

    def query_literal(self) -> Expr:
        # rulequeryLiteral: Запрос{ ... } - the body is a DSL, skipped by brace depth
        start_tok = self.advance()  # QUERY
        if not self.at_op("{"):
            name = Name(start_tok.start, start_tok.end, start_tok.value)
            return self.maybe_call(name)
        depth = 0
        while not self.at_end():
            t = self.advance()
            if t.kind == "OP":
                if t.value == "{":
                    depth += 1
                elif t.value == "}":
                    depth -= 1
                    if depth == 0:
                        break
        end = self.toks[self.pos - 1].end
        return Literal(start_tok.start, end, "QUERY", "")

    def resolvable_literal(self) -> Expr:
        # `Идент{ содержимое }` (Ресурс{...} and friends) - the body is opaque
        start_tok = self.advance()
        depth = 0
        while not self.at_end():
            t = self.advance()
            if t.kind == "OP":
                if t.value == "{":
                    depth += 1
                elif t.value == "}":
                    depth -= 1
                    if depth == 0:
                        break
        end = self.toks[self.pos - 1].end
        lit = Literal(start_tok.start, end, "RESOLVABLE", start_tok.value)
        return self.postfix_after_literal(lit)

    def postfix_after_literal(self, lit: Expr) -> Expr:
        # `Ресурс{...}.Ссылка` - the resolvable literal joins a member chain
        expr = lit
        while self.at_op(".", "?."):
            dot = self.advance()
            name_tok = self.eat_name()
            if name_tok is None:
                self.error(i18n.t("parser.expected-name-after-dot"))
                break
            expr = Member(expr.start, name_tok.end, expr, name_tok.value, dot.value == "?.")
            expr = self.maybe_call(expr)
        return expr

