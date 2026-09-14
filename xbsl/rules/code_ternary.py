"""A ternary after `это Тип` that the grammar hands to the operand of `и`/`или` (code/ternary-and-or).

The grammar of the platform reads a ternary at the level of the whole expression, after `и` and
`или`: `А и Б ? X : Y` is `(А и Б) ? X : Y`. One form is the exception. A type check may carry
a ternary of its own right after the type - `Х это Тип ? X : Y` - and that ternary belongs to the
check, so it binds tighter than the `и`/`или` standing to its left:
`А и Х это Строка ? Х как Строка : ""` is `А и (Х это Строка ? Х как Строка : "")`.

The operand of `и` then is the value of the ternary, and when the branches are not boolean the
compiler refuses the line ("Incompatible types of logical operator operands"). The language server
of the IDE confirmed both halves on probe projects in every compatibility mode of the platform
enumeration - the grammar is the same in all of them: the plain `Флаг и Второй ? 1 : 0` compiles,
the form after `это` (also with `это не`, a union type, a chain of several `и`) is refused, a group
around the condition compiles, and so does the form with branches the compiler types as boolean.

So the rule reports the form after `это` standing on the right of `и`/`или` without parentheses,
unless both branches are boolean for sure: `True`/`False`, a comparison, a type check, `не`,
`и`/`или`, or a value the module types as a non-empty `Boolean`. When a branch is known not to be
boolean the only reading that compiles is `(А и Х это Тип) ? X : Y`, and the fix puts the
condition in parentheses; with a branch the module cannot type the finding stays without a fix.
A type with `Undefined` or `?` does not start the form (the grammar takes the ternary there at
the level of the expression), and a module that does not parse is not judged.

The rule used to report every `А и Б ? X : Y` as the trap. The claim came from a build that failed
on the form after `это`, and it held for no other form: shipped libraries compile the plain one in
the older compatibility modes they declare.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator, Sequence

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token, linemap, tokens
from xbsl.parser import parse
from xbsl.rules.style_ternary import _matching_close, _widen_left
from xbsl.typeinfer import TypeEnv, expression_type, method_env, walk_nodes

RULE_ID = "code/ternary-and-or"

MESSAGES = {
    "code/ternary-and-or.title": {
        "ru": "Тернарный оператор после проверки типа в операнде 'и'/'или'",
        "en": "A ternary after a type check in an operand of 'and'/'or'",
    },
    "code/ternary-and-or.compound": {
        "ru": "Тернарный оператор после '{n[это]} Тип' принадлежит проверке, а не условию с '{word}': "
              "'А {word} Х {n[это]} Т ? X : Y' читается как 'А {word} (Х {n[это]} Т ? X : Y)', и с "
              "небулевыми ветвями компилятор строку отвергает. Взять условие в скобки: "
              "'(А {word} Х {n[это]} Т) ? X : Y'.",
        "en": "A ternary after '{n[это]} Type' belongs to the type check, not to the condition with "
              "'{word}': 'A {word} X {n[это]} T ? X : Y' reads as 'A {word} (X {n[это]} T ? X : Y)', "
              "and with non-boolean branches the compiler refuses the line. Put the condition in "
              "parentheses: '(A {word} X {n[это]} T) ? X : Y'.",
    },
}
i18n.register(MESSAGES)

_LOGICAL = frozenset({"и", "или", "and", "or"})
_BOOLEAN = "Булево"
#: Words of a checked type after which the grammar does not take the ternary into the check.
_UNDEFINED_WORDS = frozenset({"неопределено", "undefined"})


def _is_logical(node: object) -> bool:
    return isinstance(node, P.Binary) and node.op.casefold() in _LOGICAL and node.right is not None


def _boolean(node: object, env: TypeEnv) -> bool | None:
    """True - the value is a boolean for sure, False - it is not, None - the module cannot say."""
    if isinstance(node, P.Literal):
        return node.kind in ("TRUE", "FALSE")
    if isinstance(node, (P.Compare, P.IsType)) or _is_logical(node):
        return True
    if isinstance(node, P.Unary):
        return True if node.op.casefold() in ("не", "not") else False
    if isinstance(node, (P.New, P.ArrayLit, P.MapLit, P.Lambda)):
        return False
    if isinstance(node, P.Ternary):
        sides = (_boolean(node.then, env), _boolean(node.otherwise, env))
        if False in sides:
            return False
        return True if sides == (True, True) else None
    inferred = expression_type(node, env)
    if inferred is None:
        return None
    return inferred.name == _BOOLEAN and not inferred.nullable


def _check_form(ternary: P.Ternary) -> bool:
    """Whether the ternary is the one the grammar attaches to a type check."""
    check = ternary.cond
    if not isinstance(check, P.IsType) or check.type is None:
        return False
    written = check.type.text
    if "?" in written:
        return False
    return not any(word.casefold() in _UNDEFINED_WORDS for word in check.type.names)


class _Tokens:
    def __init__(self, source: SourceFile) -> None:
        self.toks = [tok for tok in tokens(source) if tok.kind not in ("COMMENT", "BOM", "EOF")]
        self.starts = [tok.start for tok in self.toks]
        self.ends = [tok.end for tok in self.toks]

    def span(self, node: P.Node) -> tuple[int, int] | None:
        """The token indices of a node, the parentheses the parser dropped at its start included."""
        first = bisect.bisect_left(self.starts, node.start)
        last = bisect.bisect_left(self.ends, node.end)
        if first >= len(self.toks) or last >= len(self.toks) or self.toks[last].end != node.end:
            return None
        return _widen_left(self.toks, first, last), last

    def grouped(self, node: P.Node) -> bool:
        """Whether parentheses wrap the node whole."""
        span = self.span(node)
        if span is None:
            return True  # an unreadable span is judged as grouped: no finding
        first, last = span
        return (first > 0 and self.toks[first - 1].kind == "OP" and self.toks[first - 1].value == "("
                and _matching_close(self.toks, first - 1) == last + 1)

    def question(self, ternary: P.Ternary) -> int | None:
        """The index of the `?` of the ternary: right before its first branch and its parentheses."""
        q = bisect.bisect_left(self.starts, ternary.then.start) - 1
        while q > 0 and self.toks[q].kind == "OP" and self.toks[q].value == "(":
            q -= 1
        tok = self.toks[q] if q >= 0 else None
        return q if tok is not None and tok.kind == "OP" and tok.value == "?" else None


def _scopes(module: P.Module) -> Iterator[tuple[object, P.Method | None]]:
    """(a node holding code, the method that types its names) for every member of the module."""
    for member in module.members:
        if isinstance(member, P.Method):
            yield member, member
        elif isinstance(member, P.Structure):
            for inner in member.members:
                yield inner, inner if isinstance(inner, P.Method) else None
        elif isinstance(member, P.Enum):
            for method in member.methods:
                yield method, method
        else:
            yield member, None


def _findings(source: SourceFile, module: P.Module) -> Iterator[tuple[P.Binary, P.Binary, P.Ternary, TypeEnv, _Tokens]]:
    """(the outermost `и`/`или`, the one holding the ternary, the ternary, the names, the tokens)."""
    toks = _Tokens(source)
    for holder, method in _scopes(module):
        nodes = walk_nodes(holder)
        inner: set[int] = set()
        for node in nodes:
            if _is_logical(node) and _is_logical(node.right) and not toks.grouped(node.right):
                inner.add(id(node.right))
        env: TypeEnv | None = None
        for node in nodes:
            if not _is_logical(node) or id(node) in inner:
                continue
            tail = node
            while _is_logical(tail.right) and not toks.grouped(tail.right):
                tail = tail.right
            ternary = tail.right
            if not isinstance(ternary, P.Ternary) or not _check_form(ternary):
                continue
            if toks.grouped(ternary):
                continue
            if env is None:
                env = method_env(method) if method is not None else TypeEnv({})
            yield node, tail, ternary, env, toks


@rule(RULE_ID, "code/ternary-and-or.title", "C", severity=Severity.ERROR)
def ternary_after_type_check(source: SourceFile) -> Iterable[Diagnostic]:
    """A ternary after `это Тип` on the right of `и`/`или` - see the module docstring."""
    if source.kind != "xbsl" or is_query_file(source.path) or "?" not in source.text:
        return
    module, errors = parse(source)
    if errors:
        return
    lm = linemap(source)
    for top, tail, ternary, env, toks in _findings(source, module):
        sides = (_boolean(ternary.then, env), _boolean(ternary.otherwise, env))
        if sides == (True, True):
            continue
        span = toks.span(top)
        q = toks.question(ternary)
        fix = None
        if False in sides and span is not None and q is not None and q > span[0]:
            start, end = toks.toks[span[0]].start, toks.toks[q - 1].end
            fix = TextEdit(start, end, f"({source.text[start:end]})")
        at = toks.toks[span[0]].start if span is not None else top.start
        line, col = lm.linecol(at)
        yield Diagnostic(source.rel, line, col, RULE_ID, Severity.ERROR,
                         i18n.t("code/ternary-and-or.compound", word=tail.op), fix=fix)
