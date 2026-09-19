"""Re-wrap comment blocks after the translation made their lines longer.

The translator rewrites token SPANS, so a comment keeps exactly the line breaks its author
typed - and an English sentence that runs longer than the Russian one pushes the line past
the project's width limit. On a real configuration that was 423 style/line-length findings
in comments over a tree that had been clean before the pass.

So a comment BLOCK - consecutive whole-line comments sharing one indent and one marker, `//`
and `///` alike - is joined back into a paragraph and split again whenever the translation
pushed one of its lines over the limit. The limit is the one style/line-length judges by, read
from the rule itself: a second copy of it would drift. The paragraph is re-split at the width
the block already had - never above the limit, never below a readable column - so a block
written at 96 columns keeps its column instead of stretching to 120 next to its neighbours.

A `/* ... */` comment that has its lines to itself is re-wrapped by the same rules. Its marker
is written once rather than on every line: `/*` opens the first line, the lines under it carry
only an indent, and `*/` closes the last one. So the first line belongs to the paragraph under
it, a re-split paragraph opens with `/*` again, and `*/` stays with the last word. An empty
line inside the comment parts two paragraphs, as an empty `//` line does.

What is never re-flowed, because the shape carries the meaning:

- a rule or a frame line - three of a kind is a decoration, not a sentence;
- a list item, and everything under it up to the next empty comment line: the continuation
  lines belong to the item, and a re-flow would move them into the wrong one. A DASH is an
  item only where a list can begin - opening a paragraph, or under a line that announces one
  with a colon; in the middle of a paragraph the same dash is a sentence carried over from
  the line above;
- a code sample or a table row - two spaces in a row, a `|`, a backtick: those columns ARE
  the content;
- a `/** ... */` comment, a `/* ... */` one framed with a star down its left edge, and any
  comment that shares its line with code;
- a line that was ALREADY over the limit in the SOURCE - its author wrote it that way on
  purpose, and the pass has nothing to repair there.

A paragraph that fits the limit after the translation is left alone as well: re-flowing it
would be a diff without a reason, and a short block often carries a layout of its own.
"""

from __future__ import annotations

import re
import textwrap
from typing import NamedTuple

from xbsl import lexer
from xbsl.rules import style_layout

#: One physical line with its ending. The lexer breaks lines on \r\n, \r and \n alone, while
#: str.splitlines also breaks on the form feed and the Unicode separators - one such character
#: inside a comment would shift every line number after it and the two texts would not line up.
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)?")

#: Three of a kind - a rule, a frame, a row of arrows. A dot is deliberately not here: an
#: ellipsis is three dots and is ordinary text.
#: The dashes in the pattern are DATA - the characters a comment may be drawn with, the em dash
#: among them, although this repository does not write one in its own prose.
_DECOR_RE = re.compile(r"([-–—=*_~#+<>|/\\─━═┄╌│┃])\1\1")

#: A list item wherever it stands: a bullet, or a number or a single letter with a dot or a
#: bracket after it (`1.`, `2)`, `a)`). Two or three letters are not a marker - an abbreviation
#: opens a sentence. A dash is not here: see `_DASH_RE`.
_LIST_RE = re.compile(r"^(?:[*+•‣▪·]|\(?\d{1,3}[.)]|\(?[^\W\d_][.)])(?:\s|$)")

#: A dash - a list marker only where a list can BEGIN: at the head of a paragraph, or under a
#: line that announces one with a colon. In the MIDDLE of a paragraph the very same dash is the
#: middle of a sentence carried over from the line above ("... the suffix `g.`" / "- is part of
#: the RUSSIAN spelling of the date"), and taking it for an item would leave that line long
#: forever. Real sources carry both shapes, so the position decides, not the character.
_DASH_RE = re.compile(r"^[-–—](?:\s|$)")

#: Below this many characters left for the text a re-split only shreds the paragraph, so the
#: block is left as it is - a marker that deep is a layout of its own anyway.
_MIN_BODY = 20

#: The narrowest column the pass will re-split at. A block narrower than this did not keep a
#: margin - its sentences simply ended there - and squeezing a translated paragraph into a
#: ribbon that narrow helps nobody; the project limit is the width then.
_MIN_COLUMN = 72

#: The first line of a `/* ... */` comment up to its text: the indent, the marker, the space.
_BLOCK_HEAD_RE = re.compile(r"[ \t]*/\*[ \t]*")

#: The last line of it from the end of its text: the space before the closing marker and the
#: marker itself.
_BLOCK_TAIL_RE = re.compile(r"[ \t]*\*/$")

#: What stands before the text of a line under the opening marker.
_INDENT_RE = re.compile(r"[ \t]*")

#: Stands in for the space before `*/` while the paragraph is wrapped: the wrap never breaks a
#: line at it, so the closing marker lands on the line of the last word and is measured there.
_HOLD = "\x00"


def rewrap_comments(text: str, original: str, limit: int | None = None) -> str:
    """Re-split the comment blocks of `text` that the translation pushed over the limit.

    `original` is the text the translation started from, line for line: only it can say
    which lines were long before the pass and must be left alone.
    """
    if limit is None:
        limit = style_layout.MAX_LINE
    # A byte order mark is not code, but it stands where an indent would: left in place it makes
    # the first comment line of the file read as one that follows a statement, and that line
    # drops out of its own paragraph. It is taken off for the pass and put back after it.
    mark = "﻿" if text.startswith("﻿") else ""
    if mark:
        return mark + rewrap_comments(text[1:], original.lstrip("﻿"), limit)
    lines = _split_keepends(text)
    source = [line.rstrip("\r\n") for line in _split_keepends(original)]
    if len(lines) != len(source):
        # The translator edits spans inside lines, so the two texts line up one to one. When
        # they do not, the source can no longer tell which line its author wrote long on
        # purpose - and changing lines blindly is worse than leaving them.
        return text
    toks = lexer.tokenize(text)
    prefixes = _comment_prefixes(toks, lines)
    blocks = _block_comments(toks, lines)
    if not prefixes and not blocks:
        return text
    newline = _newline_of(lines)
    out: list[str] = []
    index = 0
    while index < len(lines):
        last = blocks.get(index + 1)
        if last is not None:
            out.extend(_rewrap_block_comment(
                lines[index:last], source[index:last], limit, newline))
            index = last
            continue
        if index + 1 not in prefixes:
            out.append(lines[index])
            index += 1
            continue
        end = index
        while end < len(lines) and end + 1 in prefixes:
            end += 1
        out.extend(_rewrap_block(
            lines[index:end], source[index:end],
            [prefixes[number] for number in range(index + 1, end + 1)], limit, newline))
        index = end
    return "".join(out)


def _newline_of(lines: list[str]) -> str:
    """The line ending of the file - the one every line the pass ADDS has to carry.

    The last line of a file often ends without one, and a block of a single line at the very
    end has no ending to copy from at all: taking the empty ending of that line for the breaks
    BETWEEN the new lines would glue the whole paragraph back into one line.
    """
    for line in lines:
        ending = _ending(line)
        if ending:
            return ending
    return "\n"


def _split_keepends(text: str) -> list[str]:
    lines = [match.group(0) for match in _LINE_RE.finditer(text)]
    if lines and lines[-1] == "":  # finditer closes with an empty match at the end of the text
        lines.pop()
    return lines


def _comment_prefixes(toks: list[lexer.Token], lines: list[str]) -> dict[int, str]:
    """For every line a WHOLE-line `//` comment opens: what stands before the text of it.

    The prefix is the indent, the marker and the space after it - the part every line of a
    re-split paragraph repeats, and the part that tells one block from the next.

    The lexer answers, not a regular expression over the line, and it answers three things at
    once. Two slashes inside a STRING are data: a line of a multi-line literal may well begin
    with them, and no comment opens there. A `/* ... */` comment is a shape of its own and has
    a reading of its own (`_block_comments`). And a comment that follows CODE is not a
    whole-line one at all: re-flowing it would move the text away from the statement it
    explains and repeat the statement itself on every line the wrap produced.
    """
    found: dict[int, str] = {}
    for tok in toks:
        if tok.kind != "COMMENT" or tok.subkind != "line":
            continue
        indent = lines[tok.line - 1][: tok.col - 1]
        if indent.strip():
            continue
        body = tok.value.lstrip("/")
        marker = tok.value[: len(tok.value) - len(body)]
        found[tok.line] = indent + marker + body[: len(body) - len(body.lstrip(" \t"))]
    return found


def _block_comments(toks: list[lexer.Token], lines: list[str]) -> dict[int, int]:
    """{first line: last line} of every `/* ... */` comment that has its lines to itself.

    A comment that shares its first line with code before it, or its last line with code after
    it, stays where it is: a re-split would carry the code along. So does a `/** ... */`
    comment, and one that the file ends inside.
    """
    found: dict[int, int] = {}
    for tok in toks:
        if tok.kind != "COMMENT" or tok.subkind != "block" or tok.flags.get("unterminated"):
            continue
        before = lines[tok.line - 1][: tok.col - 1]
        after = lines[tok.end_line - 1].rstrip("\r\n")[tok.end_col - 1:]
        if before.strip() or after.strip():
            continue
        found[tok.line] = tok.end_line
    return found


class _Parts(NamedTuple):
    """One comment line taken apart: what stands before its text, the text, what follows it."""

    head: str
    text: str
    tail: str


def _rewrap_block(lines: list[str], source: list[str], prefixes: list[str], limit: int,
                  newline: str) -> list[str]:
    """Split a run of `//` lines by their marker, then re-flow the paragraphs inside."""
    parts = [_Parts(prefix, line.rstrip("\r\n")[len(prefix):].rstrip(), "")
             for line, prefix in zip(lines, prefixes)]
    out = _rewrap_groups(lines, source, prefixes, parts, limit, newline)
    # The pass moves the line breaks of a comment and NOTHING else. Checking that here, once,
    # is what makes a mistake in the branches above impossible to ship: a block whose words
    # came out different is put back the way its author wrote it.
    return out if _words(out) == _words(lines) else list(lines)


def _words(lines: list[str]) -> str:
    """The text of a comment block with every break and marker removed - what must not change."""
    return "".join("".join(line.lstrip().lstrip("/").split()) for line in lines)


def _rewrap_block_comment(lines: list[str], source: list[str], limit: int,
                          newline: str) -> list[str]:
    """Re-flow the paragraphs of one `/* ... */` comment, given as its whole lines.

    The paragraphs are found and split as in a run of `//` lines. Only the markers differ: the
    first line keeps `/*` in front of its text, and the last one keeps `*/` after it.
    """
    parts = [_block_parts(line, first=number == 0, last=number == len(lines) - 1)
             for number, line in enumerate(lines)]
    under = [part.text for part in parts[1:] if part.text]
    if under and all(text.startswith("*") for text in under):
        return list(lines)  # a frame of stars down the left edge
    groups = [_first_line_group(parts), *(part.head for part in parts[1:])]
    out = _rewrap_groups(lines, source, groups, parts, limit, newline)
    # The same safety net as for a `//` run. The markers stand once in the whole comment, so
    # a re-split may change its whitespace and nothing else.
    return out if _content(out) == _content(lines) else list(lines)


def _content(lines: list[str]) -> str:
    """A block comment with every space and break removed - what a re-split must not change."""
    return "".join("".join(lines).split())


def _block_parts(line: str, *, first: bool, last: bool) -> _Parts:
    """A line of a `/* ... */` comment taken apart.

    The first line has the indent and the opening marker before its text, any other line has
    only its indent. The last line has the closing marker after the text, with the space
    before it.
    """
    body = line.rstrip("\r\n")
    opening = (_BLOCK_HEAD_RE if first else _INDENT_RE).match(body)
    head = opening.group(0) if opening else ""
    text = body[len(head):].rstrip()
    closing = _BLOCK_TAIL_RE.search(text) if last else None
    if closing is None:
        return _Parts(head, text, "")
    return _Parts(head, text[: closing.start()], closing.group(0))


def _first_line_group(parts: list[_Parts]) -> str:
    """The group of the first line of a `/* ... */` comment - the indent its re-split takes.

    The first line joins the line under it when that line goes on with the same paragraph:
    its text starts under the opening marker, or under the first word after the marker. Any
    other indent there opens a list or a sample. The first line is then a paragraph alone, and
    its re-split lines are indented as the marker is.
    """
    indent = _INDENT_RE.match(parts[0].head)
    column = indent.group(0) if indent else ""
    under = parts[1] if len(parts) > 1 else None
    if under is not None and under.text and len(under.head) in (len(column), len(parts[0].head)):
        return under.head
    return column


def _rewrap_groups(lines: list[str], source: list[str], groups: list[str], parts: list[_Parts],
                   limit: int, newline: str) -> list[str]:
    """Split the lines into runs of one group, then re-flow the paragraphs of each run.

    The group of a line is what the lines of its re-split paragraph are indented with, and it
    also tells one block from the next: lines of two groups never share a paragraph.
    """
    out: list[str] = []
    start = 0
    while start < len(lines):
        end = start + 1
        while end < len(lines) and groups[end] == groups[start]:
            end += 1
        run = slice(start, end)
        out.extend(_rewrap_paragraphs(
            lines[run], source[run], parts[run], groups[start], limit, newline))
        start = end
    return out


def _rewrap_paragraphs(
    lines: list[str], source: list[str], parts: list[_Parts], prefix: str, limit: int,
    newline: str,
) -> list[str]:
    out: list[str] = []
    paragraph: list[int] = []
    #: Set by a list item: the lines under it are its continuation until an empty comment
    #: line closes the item.
    inside_item = False
    for index, part in enumerate(parts):
        # Where a list can BEGIN: no paragraph is running yet, or the line above announced
        # one with a colon. Only there does a dash open an item - see `_DASH_RE`.
        opens = not paragraph or parts[index - 1].text.rstrip().endswith(":")
        why = _protected(part.text, source[index], limit, opens=opens)
        if why == "blank":
            inside_item = False
        if why or inside_item:
            out.extend(_wrap_paragraph(paragraph, lines, source, parts, prefix, limit, newline))
            paragraph = []
            out.append(lines[index])
            inside_item = inside_item or why == "list"
            continue
        paragraph.append(index)
    out.extend(_wrap_paragraph(paragraph, lines, source, parts, prefix, limit, newline))
    return out


def _protected(payload: str, source_line: str, limit: int, *, opens: bool) -> str:
    """Why this line must stay as it is, or an empty string when it is ordinary prose.

    `opens` says a list COULD begin on this line: nothing else tells an item apart from a
    sentence that a dash carried over from the line above.
    """
    if not payload:
        return "blank"
    if len(source_line) > limit:
        return "source-long"
    if _DECOR_RE.search(payload):
        return "frame"
    if _LIST_RE.match(payload) or (opens and _DASH_RE.match(payload)):
        return "list"
    if "  " in payload or "|" in payload or "`" in payload:
        return "table"
    return ""


def _wrap_paragraph(
    indexes: list[int], lines: list[str], source: list[str], parts: list[_Parts],
    prefix: str, limit: int, newline: str,
) -> list[str]:
    if not indexes:
        return []
    kept = [lines[index] for index in indexes]
    if not any(len(lines[index].rstrip("\r\n")) > limit for index in indexes):
        return kept
    # The column the block already had is kept, so a paragraph written at 96 does not stretch
    # to 120 next to the untouched blocks around it - the limit only caps it.
    width = min(max(*(len(source[index]) for index in indexes), _MIN_COLUMN), limit)
    # The first line keeps what stood before its text - the opening marker of a block comment
    # stays in front - and the lines after it take the indent of the group. The last line keeps
    # what stood after its text, which is the closing marker.
    head, tail = parts[indexes[0]].head, parts[indexes[-1]].tail
    if width - max(len(head), len(prefix)) < _MIN_BODY:
        return kept
    space = tail[: len(tail) - len(tail.lstrip())]
    held = _HOLD * len(space) + tail[len(space):]
    wrapped = textwrap.wrap(
        " ".join(parts[index].text for index in indexes) + held, width=width,
        initial_indent=head, subsequent_indent=prefix,
        # A long word is a name or a link: breaking it would break what it names.
        break_long_words=False, break_on_hyphens=False,
    )
    if not wrapped:
        return kept
    if held:
        wrapped[-1] = wrapped[-1][: len(wrapped[-1]) - len(held)] + tail
    # `lead` is the break BETWEEN the new lines and has to be a real one - the last line of
    # a file may carry none. `last` keeps the ending the block had: a break added at the end
    # of a file would be a change of its own.
    lead = _ending(lines[indexes[0]]) or newline
    last = _ending(lines[indexes[-1]])
    return [piece + (last if number == len(wrapped) else lead)
            for number, piece in enumerate(wrapped, start=1)]


def _ending(line: str) -> str:
    stripped = line.rstrip("\r\n")
    return line[len(stripped):]
