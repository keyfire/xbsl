"""Wrap the code lines the translation pushed over the width limit.

The translator rewrites token spans, and an English name is usually longer than the Russian one:
a line of code that fitted the limit in the source may run past it after the pass. On a live
project of about four hundred modules that left 26 lines of code and seven comments after code
over the limit, and the source had none of them.

Such a line is broken the way the style guide wraps an expression, and only where the grammar
itself parts the expression:

- after a comma between arguments, parameters or collection items, so the comma ends the line;
- after the opening bracket of such a list;
- before an operator, which then opens the next line: `or`, `and`, `??`, a comparison, the `?`
  and the `:` of a conditional expression.

The parse tree names these places, not the tokens alone: a comma between type arguments looks
exactly like one between call arguments, and the colon of a type annotation like the one of a
conditional expression. The pass takes the outermost level that lets the line fit and, among the
places of that level, the last one that does, so the first piece keeps as much of the line as the
limit allows. The next piece is indented one step deeper than its line; a sibling in a list whose
bracket opened on an earlier line keeps the indent of its line instead. A new line never starts
with an opening parenthesis, which the platform may read as the start of a new statement.

A line stays as it is when:

- style/line-length reports it in the source already, so its author wanted it that way;
- it carries a comment. A comment after code stays with it, as in the comment pass (rewrap.py):
  on a line of its own the rest of the comment would stand right above the next declaration,
  and comment/doc-marker would take it for the description of that declaration;
- it starts or ends inside a multi-line string or comment, or touches a query block;
- its overflow falls inside a string literal, which style/line-length does not report;
- no choice of places gives pieces that all fit.

The pass moves line breaks and nothing else, and it checks that: the tokens of the module and
the tree the parser builds from them must come out the same, or the lines keep their shape.
"""

from __future__ import annotations

import bisect
import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from xbsl import lexer
from xbsl import parser as P
from xbsl.engine import SourceFile, is_query_file
from xbsl.rules import _syntax, style_layout
from xbsl.translation import rewrap
from xbsl.typeinfer import walk_nodes

#: The byte order mark: it stands where an indent would, so the pass takes it off and puts
#: it back.
_BOM = chr(0xFEFF)

#: The indent of a continuation line: one step of the style guide.
_STEP = "    "

#: The brackets that hold a list, by the opening one. An angle bracket is not here: only the
#: parse tree tells a type argument from a comparison.
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_CLOSING = frozenset(_PAIRS.values())

#: The rank of a place, lowest first: the structure of the line itself, then the operators from
#: the one that binds the loosest. A break at a loose operator leaves whole operands on each line.
_LIST, _TERNARY, _OR, _AND, _COALESCE, _COMPARE = range(-1, 5)

_LOGICAL = {"OR": _OR, "AND": _AND}
_COMPARISONS = frozenset({"==", "!=", "<", ">", "<=", ">="})


class _Place(NamedTuple):
    """A token a new line may start with."""

    rank: int
    #: For the `:` of a conditional expression - the offset of its `?`. The colon is a place only
    #: when its `?` does not stand inside the same piece: otherwise the break would leave
    #: `cond ? a` over `: b`, while the `?` is the better place.
    question: int = -1


def wrap_code(text: str, original: str, limit: int | None = None,
              path: Path | None = None) -> tuple[str, str]:
    """Break the code lines of `text` that the translation pushed over the limit.

    `original` is the text the translation started from, line for line. Returns the new text and
    the source lined up with it: a line broken in three repeats its source line three times. The
    comment pass that follows judges every line by its source line, and the two texts have to
    keep lining up for it.
    """
    if limit is None:
        limit = style_layout.MAX_LINE
    path = path or Path("module.xbsl")
    mark = _BOM if text.startswith(_BOM) else ""
    body = text[len(mark):]
    start = original.lstrip(_BOM)
    lines = rewrap._split_keepends(body)
    source = [line.rstrip("\r\n") for line in rewrap._split_keepends(start)]
    if (is_query_file(path) or len(lines) != len(source)
            or not any(len(line.rstrip("\r\n")) > limit for line in lines)):
        return text, original
    found = _wrap_lines(body, lines, start, limit, path)
    if not found:
        return text, original
    if not _same_program(body, _joined(lines, found)):
        # One bad break must not cost the others: each line is tried on its own then.
        found = {number: pieces for number, pieces in found.items()
                 if _same_program(body, _joined(lines, {number: pieces}))}
    aligned = []
    for index, line in enumerate(source):
        aligned.extend([line] * len(found.get(index, [line])))
    return mark + _joined(lines, found), "".join(line + "\n" for line in aligned)


def _joined(lines: list[str], found: dict[int, list[str]]) -> str:
    """The text with the lines of `found` replaced by their pieces."""
    newline = rewrap._newline_of(lines)
    out = []
    for index, line in enumerate(lines):
        pieces = found.get(index)
        if pieces is None:
            out.append(line)
            continue
        ending = rewrap._ending(line)
        out.extend(piece + (ending if number == len(pieces) else ending or newline)
                   for number, piece in enumerate(pieces, start=1))
    return "".join(out)


def _wrap_lines(body: str, lines: list[str], start: str, limit: int,
                path: Path) -> dict[int, list[str]]:
    """{line index: its pieces} for every line the pass can break."""
    reported = _reported(start, limit)
    unit = SourceFile(path=path, kind="xbsl", data=b"", text=body, had_bom=False, newline="")
    toks = lexer.tokens(unit)
    module, _errors = P.parse(unit)
    places = _places(toks, module)
    queries = _syntax.query_ranges(unit)
    strings = [(tok.start, tok.end) for tok in toks if tok.kind == "STRING"]
    spanned: set[int] = set()
    code: dict[int, list[lexer.Token]] = {}
    comments: dict[int, list[lexer.Token]] = {}
    depth: dict[int, int] = {}
    level = 0
    for tok in toks:
        if tok.kind in ("EOF", "BOM"):
            continue
        if tok.end_line > tok.line:
            spanned.update(range(tok.line, tok.end_line + 1))
        if tok.kind == "COMMENT":
            comments.setdefault(tok.line, []).append(tok)
            continue
        if _inside(queries, tok.start):
            continue
        depth[tok.start] = level
        code.setdefault(tok.line, []).append(tok)
        if tok.kind == "OP" and tok.value in _PAIRS:
            level += 1
        elif tok.kind == "OP" and tok.value in _CLOSING:
            level = max(level - 1, 0)

    found: dict[int, list[str]] = {}
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for index, line in enumerate(lines):
        offset = offsets[index]
        raw = line.rstrip("\r\n")
        number = index + 1
        row = code.get(number)
        if (len(raw) <= limit or index in reported or number in spanned or number in comments
                or not row
                or any(offset <= lo < offset + len(raw) or lo <= offset < hi for lo, hi in queries)
                or _inside(strings, offset + limit)):
            continue
        pieces = _wrap_row(body, raw, row, places, depth, strings, limit)
        if pieces:
            found[index] = pieces
    return found


def _reported(text: str, limit: int) -> set[int]:
    """The lines of the source that style/line-length reports, by index.

    Only such a line is long on purpose. A line whose overflow falls inside a string literal is
    not reported, and after the translation the overflow may well move out of the string: the
    English names inside an interpolation are often the shorter ones.
    """
    lines = rewrap._split_keepends(text)
    long = [index for index, line in enumerate(lines) if len(line.rstrip("\r\n")) > limit]
    if not long:
        return set()
    strings = [(tok.start, tok.end) for tok in lexer.tokenize(text) if tok.kind == "STRING"]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return {index for index in long if not _inside(strings, offsets[index] + limit)}


def _inside(spans: list[tuple[int, int]], offset: int) -> bool:
    return any(lo <= offset < hi for lo, hi in spans)


def _places(toks: list[lexer.Token], module: P.Module) -> dict[int, _Place]:
    """Every token a line may be broken before, by its offset, as the parse tree places them."""
    code = [tok for tok in toks if tok.kind not in ("COMMENT", "EOF", "BOM")]
    starts = [tok.start for tok in code]
    places: dict[int, _Place] = {}

    def first(lo: int, hi: int, test: Callable[[lexer.Token], bool]) -> lexer.Token | None:
        index = bisect.bisect_left(starts, lo)
        while index < len(code) and code[index].start < hi:
            if test(code[index]):
                return code[index]
            index += 1
        return None

    def op(*values: str) -> Callable[[lexer.Token], bool]:
        return lambda tok: tok.kind == "OP" and tok.value in values

    def listed(opening: lexer.Token | None, items: list[int]) -> None:
        """After the bracket of a list, and after every comma that parts two of its items."""
        if opening is None or not items:
            return
        index = bisect.bisect_left(starts, opening.start) + 1
        if index < len(code) and code[index].start == items[0]:
            places.setdefault(items[0], _Place(_LIST))
        rest = set(items[1:])
        nested = 0
        while index < len(code):
            tok = code[index]
            if tok.kind == "OP" and tok.value in _PAIRS:
                nested += 1
            elif tok.kind == "OP" and tok.value in _CLOSING:
                if nested == 0:
                    return
                nested -= 1
            elif (nested == 0 and tok.kind == "OP" and tok.value == ","
                  and index + 1 < len(code) and code[index + 1].start in rest):
                places.setdefault(code[index + 1].start, _Place(_LIST))
            index += 1

    def before(offset: int) -> lexer.Token | None:
        index = bisect.bisect_left(starts, offset) - 1
        return code[index] if index >= 0 else None

    for node in walk_nodes(module):
        if isinstance(node, P.Call) and node.args:
            listed(first(node.callee.end, node.args[0].start, op("(")),
                   [arg.start for arg in node.args])
        elif isinstance(node, P.New) and node.args:
            listed(first(node.type.end, node.args[0].start, op("(")),
                   [arg.start for arg in node.args])
        elif isinstance(node, P.Method) and node.params:
            opening = before(node.params[0].start)
            if opening is not None and opening.kind == "OP" and opening.value == "(":
                listed(opening, [param.start for param in node.params])
        elif isinstance(node, P.ArrayLit) and node.items:
            listed(first(node.start, node.items[0].start, op("[")),
                   [item.start for item in node.items])
        elif isinstance(node, P.MapLit) and node.entries:
            listed(first(node.start, node.entries[0][0].start, op("{")),
                   [key.start for key, _value in node.entries])
        elif isinstance(node, P.Binary) and node.right is not None:
            tok = first(node.left.end, node.right.start,
                        lambda t: t.kind == "KEYWORD" and t.canonical in _LOGICAL)
            if tok is not None:
                places.setdefault(tok.start, _Place(_LOGICAL[str(tok.canonical)]))
        elif isinstance(node, P.Compare):
            left: P.Expr = node.first
            for _op, right in node.rest:
                if right is None:
                    break
                tok = first(left.end, right.start, op(*_COMPARISONS))
                if tok is not None:
                    places.setdefault(tok.start, _Place(_COMPARE))
                left = right
        elif isinstance(node, P.Coalesce) and node.right is not None:
            tok = first(node.left.end, node.right.start, op("??"))
            if tok is not None:
                places.setdefault(tok.start, _Place(_COALESCE))
        elif isinstance(node, P.Ternary):
            question = first(node.cond.end, node.then.start, op("?"))
            if question is None:
                continue
            places.setdefault(question.start, _Place(_TERNARY))
            if node.otherwise is not None:
                colon = first(node.then.end, node.otherwise.start, op(":"))
                if colon is not None:
                    places.setdefault(colon.start, _Place(_TERNARY, question.start))
    return places


def _wrap_row(body: str, raw: str, row: list[lexer.Token], places: dict[int, _Place],
              depth: dict[int, int], strings: list[tuple[int, int]], limit: int) -> list[str] | None:
    """The pieces of one line of code, or None when no break makes every piece fit."""
    lead = raw[: row[0].col - 1]
    if lead.strip(" "):
        return None  # a tab in the indent: the width of the line is not the count of its characters
    pieces: list[str] = []
    first = 0
    end = row[-1].end
    while True:
        head = row[first].start
        if _fits(lead, head, end, strings, limit):
            pieces.append(lead + body[head:end])
            return pieces
        best: tuple[tuple[int, int], int] | None = None
        level = 0
        for index in range(first + 1, len(row)):
            prev = row[index - 1]
            if prev.kind == "OP" and prev.value in _PAIRS:
                level += 1
            elif prev.kind == "OP" and prev.value in _CLOSING:
                level -= 1
                if level < 0:
                    break  # the rest belongs to a list opened on an earlier line
            place = places.get(row[index].start)
            if (place is None or place.question > head
                    or (row[index].kind == "OP" and row[index].value == "(")
                    or not _fits(lead, head, prev.end, strings, limit)):
                continue
            key = (level, place.rank)
            if best is None or key <= best[0]:
                best = (key, index)
        if best is None:
            return None
        (level, _rank), index = best
        pieces.append(lead + body[head:row[index - 1].end])
        opener = places.get(row[first].start)
        continuing = depth[row[first].start] > 0 or (opener is not None and opener.rank > _LIST)
        if level > 0 or not continuing:
            lead += _STEP
        first = index


def _fits(lead: str, start: int, end: int, strings: list[tuple[int, int]], limit: int) -> bool:
    """Does `lead` plus the text from `start` to `end` hold the limit, as style/line-length judges?

    The rule does not report a line whose overflow falls inside a string literal, so neither
    does this check.
    """
    if len(lead) + end - start <= limit:
        return True
    return len(lead) < limit and _inside(strings, start + limit - len(lead))


def _same_program(before: str, after: str) -> bool:
    """Do the two texts differ in line breaks and spaces only - for the lexer and the parser?"""
    old, new = lexer.tokenize(before), lexer.tokenize(after)
    if _code_of(old) != _code_of(new) or _words_of(old) != _words_of(new):
        return False
    old_tree, old_errors = P.parse_tokens(old)
    new_tree, new_errors = P.parse_tokens(new)
    return (_shape(old_tree) == _shape(new_tree)
            and [error.message for error in old_errors] == [error.message for error in new_errors])


def _code_of(toks: list[lexer.Token]) -> list[tuple[str, str, str | None]]:
    return [(tok.kind, tok.value, tok.canonical) for tok in toks if tok.kind != "COMMENT"]


def _words_of(toks: list[lexer.Token]) -> str:
    """The comments with every break, marker and space removed - what a wrap must not change."""
    return "".join("".join(tok.value.lstrip("/").split()) for tok in toks if tok.kind == "COMMENT")


def _shape(tree: P.Node) -> list[object]:
    """The parse tree written out without offsets, parents before children.

    Built with an explicit stack: a long chain of operators nests deeper than the recursion
    limit would allow.
    """
    out: list[object] = []
    stack: list[object] = [tree]
    while stack:
        item = stack.pop()
        if isinstance(item, (list, tuple)):
            out.append(("seq", len(item)))
            stack.extend(reversed(item))
        elif isinstance(item, P.Node):
            out.append(type(item).__name__)
            stack.extend(reversed([getattr(item, name) for name in _fields(type(item))]))
        else:
            out.append(item)
    return out


_FIELDS: dict[type, tuple[str, ...]] = {}


def _fields(cls: type) -> tuple[str, ...]:
    """The fields of a node class that are not offsets."""
    names = _FIELDS.get(cls)
    if names is None:
        names = _FIELDS[cls] = tuple(field.name for field in dataclasses.fields(cls)
                                     if field.name not in ("start", "end"))
    return names
