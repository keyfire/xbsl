"""Where the comments of a source are: one walk for every rule that judges prose.

Three kinds of file carry comments the prose rules read, and each keeps them differently.
A module has COMMENT tokens - a line comment, a block comment spanning several lines, a
doc comment. An element description has `#` comments, and no lexer of the engine cuts them
out: a `#` opens a comment only outside a scalar, and where the scalars are only the yaml
composer knows (a block scalar is free to start a line with `#`, and a value is free to
hold one). A resource file has the comment segments of `restext`.

The rules of `comment/` and the typography rules that judge a comment want the same thing
from all three: the text of every comment LINE with its position in the file, so that a
finding points at the line and a fix lands on the characters that are really there. The
walk is cached on the source - five rules ask for it per file.

What a line carries is the RAW text: for a module and an element description that includes
the marker (`//`, `/*`, `*`, `#`), for a resource file the body between the delimiters, as
`restext` reports it. A rule that cares where a sentence starts strips the marker itself
(`lead`); a rule that only looks for a character does not have to.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import NamedTuple

from xbsl import restext
from xbsl.engine import SourceFile
from xbsl.lexer import linemap, tokens
from xbsl.rules.yaml_schema import _composed, _HAVE_YAML, _parsed

if _HAVE_YAML:
    import yaml


class CommentLine(NamedTuple):
    """One physical line of a comment: where it is and what it says."""

    line: int  # 1-based line number
    column: int  # 1-based column of `text[0]`
    offset: int  # character offset of `text[0]` in `source.text`
    text: str  # the raw text of the line, from the marker to the end of the line


#: The marker a comment line starts with, in any of the formats the engine reads: `//`,
#: `/*`, a `*` continuing a block comment (`*/` closing it), `#`, `<!--`; then a list bullet.
#: What follows is the prose of the line.
_LEAD = re.compile(r"^\s*(?://+|/\*+|\*+/?|#+|<!--|-->)?\s*(?:[-*•]\s+)?")


def lead(text: str) -> int:
    """Length of the marker and the spaces before the prose of a comment line."""
    return _LEAD.match(text).end()


def _split(start: int, value: str, lm, out: list[CommentLine]) -> None:
    """One comment of several lines into its lines, offsets kept."""
    offset = start
    for part in value.split("\n"):
        line, column = lm.linecol(offset)
        out.append(CommentLine(line, column, offset, part))
        offset += len(part) + 1


def _module_lines(source: SourceFile) -> list[CommentLine]:
    lm = linemap(source)
    out: list[CommentLine] = []
    for tok in tokens(source):
        if tok.kind == "COMMENT":
            _split(tok.start, tok.value, lm, out)
    return out


def _resource_lines(source: SourceFile) -> list[CommentLine]:
    lm = linemap(source)
    out: list[CommentLine] = []
    text = source.text
    for segment in restext.segments(source):
        if segment.kind == restext.COMMENT:
            _split(segment.start, text[segment.start:segment.end], lm, out)
    return out


def _scalar_ranges(root) -> list[tuple[int, int]]:
    """(start, end) character ranges of every scalar of the composed graph, sorted.

    A `#` inside one of them is data, not a comment - a value may hold the character, and a
    block scalar may start a whole line with it.
    """
    ranges: list[tuple[int, int]] = []
    stack = [root]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if node is None or id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, yaml.ScalarNode):
            ranges.append((node.start_mark.index, node.end_mark.index))
            continue
        for item in node.value:
            if isinstance(item, tuple):
                stack.extend(item)
            else:
                stack.append(item)
    ranges.sort()
    return ranges


def _yaml_lines(source: SourceFile) -> list[CommentLine]:
    """The `#` comments of an element description, trailing ones included.

    A file that does not parse gives nothing: without the scalars a comment cannot be told
    from a value, and a broken file has other rules to report it. A file of comments alone
    composes to nothing as well - and there every `#` line is a comment.
    """
    if not _HAVE_YAML:
        return []
    root = _composed(source)
    if root is None:
        _data, error = _parsed(source)
        if error is not None:
            return []
    ranges = _scalar_ranges(root) if root is not None else []
    starts = [r[0] for r in ranges]
    text = source.text
    lm = linemap(source)
    out: list[CommentLine] = []
    position = 0
    for raw in text.split("\n"):
        end = position + len(raw)
        index = raw.find("#")
        while index >= 0:
            offset = position + index
            preceded = index == 0 or raw[index - 1] in " \t"
            inside = bisect_right(starts, offset) - 1
            in_scalar = inside >= 0 and ranges[inside][0] <= offset < ranges[inside][1]
            if preceded and not in_scalar:
                line, column = lm.linecol(offset)
                out.append(CommentLine(line, column, offset, raw[index:]))
                break
            index = raw.find("#", index + 1)
        position = end + 1
    return out


def lines(source: SourceFile) -> list[CommentLine]:
    """Every comment line of the file, in file order; empty for a kind without comments."""
    key = "comment_lines"
    if key not in source.cache:
        if source.kind == "xbsl":
            found = _module_lines(source)
        elif source.kind == "yaml":
            found = _yaml_lines(source)
        elif source.kind in restext.KINDS:
            found = _resource_lines(source)
        else:
            found = []
        source.cache[key] = found
    return source.cache[key]
