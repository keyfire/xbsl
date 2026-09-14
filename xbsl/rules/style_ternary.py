"""A ternary whose branches are the two boolean literals (style/boolean-ternary).

`Флаг ? Истина : Ложь` is the condition itself and `Флаг ? Ложь : Истина` its negation. The
platform IDE warns about both, and the rule repeats the condition the IDE applies, checked on
probe projects variant by variant:

- the two branches are `True` and `False` in either order, in either spelling (`True : False`
  in a Russian module too), each possibly wrapped in parentheses;
- the condition is anything: a name, a comparison, `не`, `это`, a call, `А и Б`, a group;
- the ternary stands anywhere an expression does: an initializer, `если`, `возврат`, an
  argument, the body of a short lambda, a group inside a bigger expression, the full
  interpolation of a string (`"%{Флаг ? Истина : Ложь}"`) - and a binding of a yaml property
  (`Видимость: '=Объект.Выполнена ? Истина : Ложь'`), where the IDE reports the whole value;
- equal branches (`Истина : Истина`), a branch that is an expression, numbers, strings and
  `Undefined` are not reported, and neither is a value in double quotes in yaml - the
  platform reads it as a string, not as a binding.

The fix writes the condition in place of the ternary, or its negation. The negation follows the
grammar, probed the same way: `не` covers a comparison (`не Количество > 0`) but not `это`, `как`,
`и`, `или` or `??` - `не Значение это Строка` is `(не Значение) это Строка`. So a condition with
`это` is negated inside (`Значение это не Строка`, as style/negated-is asks), a single `==` or `!=`
flips, a leading `не` is dropped, a condition `не` would not cover whole is wrapped in parentheses,
and a group around a name or a call is dropped. The `не` is spelled in the language of the code
around the ternary (the key of a binding when the expression has no keyword of its own). The finding carries no fix when a comment lies inside the ternary (the
rewrite would lose it), and in yaml when the value holds an escaped quote (the offsets of the text
and of the value part). A module or a binding that does not parse is not judged.
"""

from __future__ import annotations

import bisect
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token, linemap, tokenize, tokens
from xbsl.parser import parse
from xbsl.typeinfer import walk_nodes
from xbsl.rules.style_literals import _keyword
from xbsl.rules.yaml_imports import _interpolation_bodies
from xbsl.rules.yaml_schema import _HAVE_YAML, _composed, _mapping_nodes, yaml

RULE_ID = "style/boolean-ternary"

MESSAGES = {
    "style/boolean-ternary.title": {
        "ru": "Тернарный оператор с ветвями {n[Истина]} и {n[Ложь]}",
        "en": "A ternary with {n[Истина]} and {n[Ложь]} branches",
    },
    "style/boolean-ternary.condition": {
        "ru": "Тернарный оператор с ветвями '{n[Истина]}' и '{n[Ложь]}' равен своему условию – "
              "записать само условие: {replacement}",
        "en": "A ternary with '{n[Истина]}' and '{n[Ложь]}' branches equals its condition – "
              "write the condition itself: {replacement}",
    },
    "style/boolean-ternary.negation": {
        "ru": "Тернарный оператор с ветвями '{n[Ложь]}' и '{n[Истина]}' равен отрицанию своего "
              "условия – записать отрицание: {replacement}",
        "en": "A ternary with '{n[Ложь]}' and '{n[Истина]}' branches equals the negation of its "
              "condition – write the negation: {replacement}",
    },
}
i18n.register(MESSAGES)

_BOOLEAN_KINDS = frozenset({"TRUE", "FALSE"})
_OPEN = frozenset({"(", "[", "{"})
_CLOSE = frozenset({")", "]", "}"})
#: Keywords that tell the language of the code around a ternary, which the `не` of the fix follows.
#: The nearest one wins. Literals are no guide - `True` is legal in a Russian module.
_LANGUAGE_KEYWORDS = frozenset({
    "METHOD", "VAL", "VAR", "CONST", "RETURN", "IF", "ELSE", "WHILE", "FOR", "IN", "TRY", "CATCH",
    "CASE", "WHEN", "SCOPE", "USE", "NEW", "STRUCTURE", "ENUMERATION", "EXCEPTION", "IMPORT",
    "AND", "OR", "NOT", "IS", "AS", "THIS",
})
#: What `не` written in front does not reach over (the probes: `не А и Б` is `(не А) и Б`,
#: `не А это Т` is `(не А) это Т`, while `не А > 0` is `не (А > 0)`).
_BEYOND_NOT_KEYWORDS = frozenset({"AND", "OR", "IS", "AS"})
_BEYOND_NOT_OPS = frozenset({"??", "?", ":", "->", "="})
#: Tokens that keep a group without parentheses a single operand: names, literals and the links of
#: a chain.
_ATOM_KINDS = frozenset({"IDENT", "NUMBER", "STRING", "PATTERN"})
_ATOM_KEYWORDS = frozenset({"TRUE", "FALSE", "UNDEFINED", "THIS", "GLOBAL_EN", "GLOBAL_RU"})
_ATOM_OPS = frozenset({".", "?.", "::", "!"})
#: A single equality flips instead of taking `не`: `А != Б` is the negation of `А == Б` exactly.
_EQUALITY = {"==": "!=", "!=": "=="}
_COMPARISONS = frozenset({"==", "!=", "<", ">", "<=", ">="})

#: The wrapper an expression outside a module is parsed in: a yaml binding, the full interpolation
#: of a string. The parser reads modules, and the offsets inside are shifted back.
_WRAP_PREFIX = "метод Проба()\n    возврат "
_WRAP_SUFFIX = "\n;\n"


def _is_op(tok: Token, *values: str) -> bool:
    return tok.kind == "OP" and tok.value in values


def _is_kw(tok: Token, canonicals: frozenset[str]) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical in canonicals


def _matching_close(toks: Sequence[Token], i: int) -> int:
    """The index of the bracket closing the one at `i`, or -1."""
    depth = 0
    for k in range(i, len(toks)):
        tok = toks[k]
        if tok.kind != "OP":
            continue
        if tok.value in _OPEN:
            depth += 1
        elif tok.value in _CLOSE:
            depth -= 1
            if depth == 0:
                return k
    return -1


def _widen_left(toks: Sequence[Token], i: int, j: int) -> int:
    """Move `i` left over the opening brackets whose closing ones lie inside [i, j].

    The parser drops the parentheses of a group, so a node that starts with a group
    (`(Флаг) ? Истина : Ложь`) starts INSIDE it; the tokens tell where the text really begins.
    """
    depth = low = 0
    for k in range(i, j + 1):
        tok = toks[k]
        if tok.kind == "OP" and tok.value in _OPEN:
            depth += 1
        elif tok.kind == "OP" and tok.value in _CLOSE:
            depth -= 1
            low = min(low, depth)
    missing, inner, k = -low, 0, i - 1
    while missing and k >= 0:
        tok = toks[k]
        if tok.kind == "OP" and tok.value in _CLOSE:
            inner += 1
        elif tok.kind == "OP" and tok.value in _OPEN:
            if inner:
                inner -= 1
            else:
                missing -= 1
                i = k
        k -= 1
    return i


def _strip_group(toks: Sequence[Token], i: int, j: int) -> tuple[int, int, bool]:
    """[i, j] without the parentheses that wrap the whole of it, and whether there were any."""
    grouped = False
    while j > i and _is_op(toks[i], "(") and _is_op(toks[j], ")") and _matching_close(toks, i) == j:
        i, j, grouped = i + 1, j - 1, True
    return i, j, grouped


def _top_level(toks: Sequence[Token], i: int, j: int) -> list[int]:
    """Indices of the tokens of [i, j] outside every bracket."""
    out: list[int] = []
    depth = 0
    for k in range(i, j + 1):
        tok = toks[k]
        if tok.kind == "OP" and tok.value in _CLOSE:
            depth -= 1
            continue
        if depth == 0:
            out.append(k)
        if tok.kind == "OP" and tok.value in _OPEN:
            depth += 1
    return out


def _is_atom(toks: Sequence[Token], i: int, j: int) -> bool:
    """A name, a literal or a chain of links: nothing a neighbouring operator could split."""
    for k in _top_level(toks, i, j):
        tok = toks[k]
        if tok.kind in _ATOM_KINDS or _is_kw(tok, _ATOM_KEYWORDS):
            continue
        if tok.kind == "OP" and (tok.value in _ATOM_OPS or tok.value in _OPEN):
            continue
        return False
    return True


@dataclass
class _Ternary:
    """A reported ternary as token indices: it starts with its condition, which ends at `cond_end`."""

    start: int
    end: int
    cond_end: int
    negated: bool


def _find(module: P.Module, toks: Sequence[Token]) -> list[_Ternary]:
    """The ternaries with two different boolean literal branches."""
    starts = [tok.start for tok in toks]
    ends = [tok.end for tok in toks]
    found: list[_Ternary] = []
    for node in walk_nodes(module):
        if not isinstance(node, P.Ternary):
            continue
        then, otherwise = node.then, node.otherwise
        if not (isinstance(then, P.Literal) and isinstance(otherwise, P.Literal)):
            continue
        if {then.kind, otherwise.kind} != _BOOLEAN_KINDS:
            continue
        first = bisect.bisect_left(starts, node.cond.start)
        last = bisect.bisect_left(ends, node.end)
        if first >= len(toks) or last >= len(toks) or toks[last].end != node.end:
            continue
        # The `?` is found from the branch: the condition node may end past it (`Х это Т ? ...`
        # is read with the `?` taken for the nullable mark first).
        q = bisect.bisect_left(starts, then.start) - 1
        while q > first and _is_op(toks[q], "("):
            q -= 1
        if q <= first or not _is_op(toks[q], "?"):
            continue
        begin = _widen_left(toks, first, q - 1)
        found.append(_Ternary(begin, last, q - 1, then.kind == "FALSE"))
    return found


def _text(text: str, toks: Sequence[Token], i: int, j: int) -> str:
    return text[toks[i].start:toks[j].end]


def _operand(text: str, toks: Sequence[Token], i: int, j: int) -> str:
    """[i, j] as written, a group around a single operand dropped."""
    inner_i, inner_j, grouped = _strip_group(toks, i, j)
    if grouped and _is_atom(toks, inner_i, inner_j):
        return _text(text, toks, inner_i, inner_j)
    return _text(text, toks, i, j)


def _negation(text: str, toks: Sequence[Token], i: int, j: int, english: bool) -> str:
    """The negation of the condition [i, j], written the way the platform reads it."""
    negation = _keyword("NOT", english)
    inner_i, inner_j, grouped = _strip_group(toks, i, j)
    inner = _text(text, toks, inner_i, inner_j)
    whole = _text(text, toks, i, j)
    if grouped and _is_atom(toks, inner_i, inner_j):
        return f"{negation} {inner}"

    def regroup(body: str) -> str:
        """The body inside the parentheses the condition was written with, if any."""
        return text[toks[i].start:toks[inner_i].start] + body + text[toks[inner_j].end:toks[j].end]

    top = _top_level(toks, inner_i, inner_j)
    beyond = [k for k in top if _is_kw(toks[k], _BEYOND_NOT_KEYWORDS)
              or (toks[k].kind == "OP" and toks[k].value in _BEYOND_NOT_OPS)]
    if len(beyond) == 1 and toks[beyond[0]].canonical == "IS" and inner_i < beyond[0] < inner_j:
        at = beyond[0]
        head = text[toks[inner_i].start:toks[at].end]
        if toks[at + 1].kind == "KEYWORD" and toks[at + 1].canonical == "NOT":
            if at + 1 < inner_j:
                return regroup(f"{head} {text[toks[at + 2].start:toks[inner_j].end]}")
        else:
            return regroup(f"{head} {negation}{text[toks[at].end:toks[inner_j].end]}")
    if beyond:
        return f"{negation} {whole if grouped else f'({inner})'}"
    if toks[inner_i].kind == "KEYWORD" and toks[inner_i].canonical == "NOT" and inner_i < inner_j:
        return _operand(text, toks, inner_i + 1, inner_j)
    compared = [k for k in top if toks[k].kind == "OP" and toks[k].value in _COMPARISONS]
    if len(compared) == 1 and toks[compared[0]].value in _EQUALITY and inner_i < compared[0] < inner_j:
        op = toks[compared[0]]
        return regroup(text[toks[inner_i].start:op.start] + _EQUALITY[op.value]
                       + text[op.end:toks[inner_j].end])
    return f"{negation} {whole if grouped else inner}"


def _replacement(text: str, toks: Sequence[Token], ternary: _Ternary, english: bool) -> str:
    if ternary.negated:
        return _negation(text, toks, ternary.start, ternary.cond_end, english)
    return _operand(text, toks, ternary.start, ternary.cond_end)


def _english_at(toks: Sequence[Token], index: int, floor: int, end: int) -> bool | None:
    """Whether the code at the token is written in English, by the nearest telling keyword.

    The search goes back to `floor` first (the keywords the code wrote before the ternary), then
    forward to `end` (a binding holds nothing but the expression); None when neither has one.
    """
    for k in [*range(index, floor - 1, -1), *range(index + 1, end)]:
        tok = toks[k]
        if tok.kind == "KEYWORD" and tok.canonical in _LANGUAGE_KEYWORDS:
            return tok.value.isascii()
    return None


def _message(replacement: str, negated: bool) -> str:
    shown = " ".join(replacement.split())
    key = "style/boolean-ternary.negation" if negated else "style/boolean-ternary.condition"
    return i18n.t(key, replacement=shown)


@dataclass
class _Found:
    """A ternary of the file: where it is, what replaces it and whether the text may be rewritten."""

    start: int  # offset in the file
    end: int
    replacement: str
    negated: bool
    fixable: bool


def _scan(text: str, toks_all: Sequence[Token], module: P.Module, shift: int, exact: bool,
          english: bool | None, wrapped: bool) -> Iterator[_Found]:
    """The ternaries of one piece of code and of the string interpolations inside it.

    `text` is the text the tokens index, `shift` turns an offset of it into an offset of the file,
    and `exact` says whether the file holds the piece character for character (a yaml value with
    an escaped quote does not). `english` is what is known of the language from outside - the key
    of a binding, the module around an interpolation; `wrapped` marks an expression parsed inside
    the wrapper, whose own keywords say nothing.
    """
    toks = [tok for tok in toks_all if tok.kind not in ("COMMENT", "BOM", "EOF")]
    starts = [tok.start for tok in toks]
    comments = [tok.start for tok in toks_all if tok.kind == "COMMENT"]
    floor = bisect.bisect_left(starts, len(_WRAP_PREFIX)) if wrapped else 0
    for ternary in _find(module, toks):
        start, end = toks[ternary.start].start, toks[ternary.end].end
        language = _english_at(toks, ternary.start, floor, len(toks))
        replacement = _replacement(text, toks, ternary, bool(english if language is None else language))
        k = bisect.bisect_left(comments, start)
        commented = k < len(comments) and comments[k] < end
        yield _Found(start + shift, end + shift, replacement, ternary.negated, exact and not commented)
    for node in walk_nodes(module):
        if not (isinstance(node, P.Literal) and node.kind == "STRING"):
            continue
        for offset, body in _interpolation_bodies(node.text, blank_strings=False):
            if "?" not in body:
                continue
            index = bisect.bisect_left(starts, node.start)
            language = _english_at(toks, index - 1, floor, index) if index > floor else None
            yield from _expression(body, node.start + offset + shift, exact,
                                   english if language is None else language)


def _expression(body: str, at: int, exact: bool, english: bool | None) -> Iterator[_Found]:
    """The ternaries of an expression that lies in the file at offset `at`."""
    wrapped = f"{_WRAP_PREFIX}{body}{_WRAP_SUFFIX}"
    toks = tokenize(wrapped)
    module, errors = P.parse_tokens(toks)
    if errors:
        return
    yield from _scan(wrapped, toks, module, at - len(_WRAP_PREFIX), exact, english, True)


def _module(source: SourceFile) -> Iterator[_Found]:
    if "?" not in source.text:
        return
    module, errors = parse(source)
    if errors:
        return
    yield from _scan(source.text, tokens(source), module, 0, True, None, False)


def _yaml(source: SourceFile) -> Iterator[tuple[_Found, int]]:
    """The ternaries of the bindings, each with the offset of its yaml value (the IDE's place)."""
    text = source.text
    if "?" not in text or "=" not in text or not _HAVE_YAML:
        return
    root = _composed(source)
    if root is None:
        return
    for mapping in _mapping_nodes(root):
        for key_node, node in mapping.value:
            if not isinstance(node, yaml.ScalarNode) or node.style not in (None, "", "'"):
                continue
            value = node.value
            if not value.startswith("=") or "?" not in value or "\n" in value:
                continue
            if node.start_mark.line != node.end_mark.line:
                continue
            quoted = node.style == "'"
            content = node.start_mark.index + (1 if quoted else 0)
            exact = text[content:node.end_mark.index - (1 if quoted else 0)] == value
            english = isinstance(key_node, yaml.ScalarNode) and str(key_node.value).isascii()
            for found in _expression(value[1:], content + 1, exact, english):
                yield found, node.start_mark.index


@rule(RULE_ID, "style/boolean-ternary.title", "C", severity=Severity.WARNING)
def boolean_ternary(source: SourceFile) -> Iterable[Diagnostic]:
    """A ternary with the `True` and `False` branches - see the module docstring."""
    if source.kind == "xbsl" and not is_query_file(source.path):
        placed = ((found, found.start) for found in _module(source))
    elif source.kind == "yaml":
        placed = _yaml(source)
    else:
        return
    lm = None
    for found, anchor in placed:
        if lm is None:
            lm = linemap(source)
        line, col = lm.linecol(anchor)
        fix = TextEdit(found.start, found.end, found.replacement) if found.fixable else None
        yield Diagnostic(source.rel, line, col, RULE_ID, Severity.WARNING,
                         _message(found.replacement, found.negated), fix=fix)
