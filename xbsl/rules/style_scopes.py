"""A scope that is the only statement of its block (style/redundant-scope).

`область ... ;` opens a nested scope: what it declares lives until its `;`. When the scope is
the only statement of its block, it ends where the block ends, and it limits nothing. The
platform IDE warns about such a scope, and the rule repeats the condition the IDE applies,
checked on probe projects variant by variant:

- the block is any list of statements: the body of a method (a structure's method too) or of a
  full lambda, a branch of `если`, `иначе если` and `иначе`, a branch of `когда` and the `иначе`
  of `выбор`, the body of `пока`, `для ... из` and `для ... по`, the blocks of `попытка`,
  `поймать` and `вконце`, the body of another scope;
- the scope may be empty, hold only a comment or hold only `исп`; a comment next to it in the
  block is not a statement and does not save it;
- a scope with any statement next to it is not reported.

The fix takes the scope away: the line of `область` and the line of its `;` are removed and the
body moves one indent to the left; a line comment written after either of them keeps a line of
its own. Nothing the body declares can collide on the way - the block has no other statements, and
a declaration that repeats a parameter is a compile error inside the scope as well. The finding
carries no fix when the layout is not the usual one (code or a block comment on the line of
`область` or of its `;`, a body line indented less than the first one) or when a string of the
body spans lines (its text would move along). A module that does not parse is not judged.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Iterator, Sequence

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import Token, linemap, tokens
from xbsl.parser import parse
from xbsl.typeinfer import walk_nodes

RULE_ID = "style/redundant-scope"

MESSAGES = {
    "style/redundant-scope.title": {
        "ru": "Область – единственная инструкция блока",
        "en": "A scope that is the only statement of its block",
    },
    "style/redundant-scope.found": {
        "ru": "'{n[область]}' – единственная инструкция своего блока и ничего не ограничивает: "
              "её тело можно записать прямо в блок.",
        "en": "'{n[область]}' is the only statement of its block and limits nothing: its body "
              "can stand in the block directly.",
    },
}
i18n.register(MESSAGES)

_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)?")
_BLANK = " \t"


def _bodies(module: P.Module) -> Iterator[list[P.Stmt]]:
    """Every list of statements of the module."""
    for node in walk_nodes(module):
        if isinstance(node, P.Method):
            if not node.is_abstract:
                yield node.body
        elif isinstance(node, P.Lambda):
            if node.body_stmts is not None:
                yield node.body_stmts
        elif isinstance(node, P.If):
            for _cond, body in node.branches:
                yield body
            if node.else_body is not None:
                yield node.else_body
        elif isinstance(node, P.Case):
            if node.else_body is not None:
                yield node.else_body
        elif isinstance(node, (P.CaseWhen, P.While, P.ForEach, P.ForTo, P.Scope)):
            yield node.body
        elif isinstance(node, P.Try):
            yield node.body
            for _var, _type, body in node.catches:
                yield body
            if node.finally_body is not None:
                yield node.finally_body


def _line_start(text: str, offset: int) -> int:
    return max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1


def _line_end(text: str, offset: int) -> int:
    """The offset right past the line break of the line holding `offset` (the text end at the last line)."""
    match = _LINE_RE.match(text, _line_start(text, offset))
    return match.end() if match is not None else len(text)


def _rest_of_line(text: str, raw: Sequence[Token], starts: Sequence[int], start: int,
                  end: int) -> str | None:
    """What follows a token up to the line break: "" for nothing, the text of a line comment, or
    None for anything else (code, a block comment)."""
    rest = text[start:end].rstrip("\r\n")
    if not rest.strip(_BLANK):
        return ""
    at = start + len(rest) - len(rest.lstrip(_BLANK))
    k = bisect.bisect_left(starts, at)
    comment = raw[k] if k < len(raw) and starts[k] == at else None
    if comment is None or comment.kind != "COMMENT" or comment.subkind != "line":
        return None
    return rest.strip(_BLANK)


def _fix(text: str, raw: Sequence[Token], starts: Sequence[int], scope: P.Scope,
         keyword: Token) -> TextEdit | None:
    """The removal of the scope with its body moved one indent to the left, or None.

    A line comment after `область` or after its `;` stays: it takes a line of its own at the
    indent of the scope, before the body or after it.
    """
    semicolon = scope.end - 1
    if text[semicolon:scope.end] != ";":
        return None
    head = _line_start(text, keyword.start)
    head_end = _line_end(text, keyword.start)
    tail = _line_start(text, semicolon)
    tail_end = _line_end(text, semicolon)
    if tail < head_end:
        return None
    indent = text[head:keyword.start]
    if indent.strip(_BLANK) or text[tail:semicolon] != indent:
        return None
    opening = _rest_of_line(text, raw, starts, keyword.end, head_end)
    closing = _rest_of_line(text, raw, starts, scope.end, tail_end)
    if opening is None or closing is None:
        return None
    for k in range(bisect.bisect_left(starts, head_end), bisect.bisect_left(starts, tail)):
        if raw[k].kind == "STRING" and raw[k].end_line != raw[k].line:
            return None
    head_break = text[keyword.start:head_end][len(text[keyword.start:head_end].rstrip("\r\n")):]
    tail_break = text[semicolon:tail_end][len(text[semicolon:tail_end].rstrip("\r\n")):]
    lines = [m.group(0) for m in _LINE_RE.finditer(text, head_end, tail) if m.group(0)]
    unit = None
    moved: list[str] = [f"{indent}{opening}{head_break}"] if opening else []
    for line in lines:
        content = line.rstrip("\r\n")
        if not content.strip(_BLANK):
            moved.append(line[len(content):])
            continue
        if unit is None:
            lead = content[:len(content) - len(content.lstrip(_BLANK))]
            if not lead.startswith(indent) or len(lead) == len(indent):
                return None
            unit = lead[len(indent):]
        if not content.startswith(indent + unit):
            return None
        moved.append(indent + line[len(indent) + len(unit):])
    if closing:
        moved.append(f"{indent}{closing}{tail_break or head_break}")
    return TextEdit(head, tail_end, "".join(moved))


@rule(RULE_ID, "style/redundant-scope.title", "C", severity=Severity.WARNING)
def lone_scope(source: SourceFile) -> Iterable[Diagnostic]:
    """A scope that is the only statement of its block - see the module docstring."""
    if source.kind != "xbsl" or is_query_file(source.path):
        return
    text = source.text
    if "область" not in text and "scope" not in text:
        return
    module, errors = parse(source)
    if errors:
        return
    raw = tokens(source)
    starts = [tok.start for tok in raw]
    lm = linemap(source)
    for body in _bodies(module):
        if len(body) != 1 or not isinstance(body[0], P.Scope):
            continue
        scope = body[0]
        k = bisect.bisect_left(starts, scope.start)
        keyword = raw[k] if k < len(raw) else None
        if keyword is None or keyword.kind != "KEYWORD" or keyword.canonical != "SCOPE":
            continue
        line, col = lm.linecol(scope.start)
        yield Diagnostic(source.rel, line, col, RULE_ID, Severity.WARNING,
                         i18n.t("style/redundant-scope.found"), fix=_fix(text, raw, starts, scope, keyword))
