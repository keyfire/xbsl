"""Prose a resource file carries: comments, and the title of a drawing.

A `.css`, `.js`, `.html` or `.svg` next to the sources used to be copied byte for byte, so a
Russian comment travelled into the English tree untouched and `--strict` called the file
covered - it counted nothing there, and nothing is never a gap. A project that moves the static
part of its html inserts out of the modules and into files like these moves the comments along
with them, and the pile grows.

What this module hands to the translator:

- `/* */` and `//` in `.css` and `.js`, read line by line, exactly as a module comment is read;
- `<!-- -->` in `.html` and `.svg`, the same way;
- the text of `<title>` and `<desc>` in `.svg` - not a comment at all, but the words a screen
  reader speaks and a browser shows in a tooltip;
- the comments of an embedded `<style>` or `<script>`, which are css and js inside markup.

Everything else stays byte for byte: selectors, property names and their values, attributes,
identifiers, the text of the page. A payload goes through the PHRASES plane of the dictionary,
the same plane a module comment goes through, so one sentence written in a module and in a
stylesheet needs one pair.

The reading is a scan of the text, not a pattern over the lines. A comment marker means
nothing inside a string (`content: "/*"`), inside an unquoted `url(...)`, inside a template
literal, or inside a regular expression - `var re = /[/*]/;` would hand the rest of the file
to a pattern-matching reader as one comment. Markup goes through the standard library's html
parser, which knows that `<!--` inside an attribute value opens nothing.

Two borders are drawn on purpose. A comment that carries a licence is left alone: its wording
is a legal text, and a translation of it says something the original does not. A minified
`.css`/`.js` is left alone whole: it is build output, its only comment is the banner the
minifier kept, and the file is not where anybody edits anything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from html.parser import HTMLParser

from xbsl.translation.code import (
    _BLOCK_FIRST_RE, _BLOCK_LINE_RE, _LINE_COMMENT_RE, comment_lines, has_cyrillic,
)
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport

#: Resource suffixes this module reads. Everything else is copied as it is.
SUFFIXES = (".css", ".js", ".html", ".svg")

#: The lines of a markup comment: the opening one carries `<!--`, the rest carry indentation.
_MARKUP_FIRST_RE = re.compile(r"^(<!--+\s*)(.*?)(\s*(?:--+>)?\s*)$")
_MARKUP_LINE_RE = re.compile(r"^(\s*)(.*?)(\s*(?:--+>)?\s*)$")

#: Words that make a comment a licence. `/*!` is the marker minifiers keep a banner by.
_LICENCE_MARKERS = (
    "copyright", "(c)", "©", "spdx-license-identifier", "@license", "@preserve",
    "all rights reserved", "лицензи",
    "все права защищен",
)

#: A line this long says the file went through a minifier: nobody writes one by hand.
_MINIFIED_LINE = 500

#: Elements of a drawing whose text a person reads or hears.
_SPOKEN_TAGS = ("title", "desc")


def resource_payloads(suffix: str, text: str) -> list[tuple[int, int, str]]:
    """(start, end, payload) of every span of prose in a resource file, in order.

    One reading for two callers: the translating pass rewrites these spans, and the orphan
    pass keys the same payloads to decide whether a dictionary entry is still in use. Two
    readings of one thing drift apart, and the pair written from a comment then reads as an
    orphan of a file that still carries it.
    """
    suffix = suffix.lower()
    if suffix in (".css", ".js"):
        if _looks_minified(text):
            return []
        spans = _script_payloads(text, suffix == ".js", 0)
    elif suffix in (".html", ".svg"):
        spans = _markup_payloads(text)
    else:
        return []
    return [span for span in spans if span[2]]


def translate_resource(
    text: str, suffix: str, dictionary: Dictionary, report: FileReport | None = None
) -> str:
    """Rewrite the prose of a resource file through the phrases plane; count what is missing.

    A payload without Cyrillic is already English and is passed over - counting it would put
    every brace-closing note of a stylesheet into the coverage. The rest is a phrase like any
    other: translated when the dictionary answers, reported as a gap when it does not.
    """
    if not has_cyrillic(text):
        return text
    pieces: list[str] = []
    cursor = 0
    line_starts = _line_starts(text)
    for start, end, payload in resource_payloads(suffix, text):
        if not has_cyrillic(payload) or start < cursor:
            continue
        translated = dictionary.phrase(payload)
        if translated is None:
            if report is not None:
                line, col = _place(line_starts, start)
                report.note_phrase(payload, line, col)
            continue
        if report is not None:
            report.phrases_done += 1
        if translated == payload:
            continue
        pieces.append(text[cursor:start])
        pieces.append(translated)
        cursor = end
    if not pieces:
        return text
    pieces.append(text[cursor:])
    return "".join(pieces)


# --- css and js ---------------------------------------------------------------------------


def _script_payloads(text: str, javascript: bool, base: int) -> list[tuple[int, int, str]]:
    """The comment payloads of a stylesheet or a script, shifted by `base`."""
    out: list[tuple[int, int, str]] = []
    for start, end, line_comment in _comment_spans(text, javascript):
        body = text[start:end]
        if _is_licence(body):
            continue
        first, rest = ((_LINE_COMMENT_RE, _LINE_COMMENT_RE) if line_comment
                       else (_BLOCK_FIRST_RE, _BLOCK_LINE_RE))
        for offset, _index, payload in comment_lines(body, first, rest):
            at = base + start + offset
            out.append((at, at + len(payload), payload))
    return out


#: What may stand before a `/` that opens a regular expression. After a name, a number or a
#: closing bracket the slash divides; after an operator, a comma or an opening bracket a
#: value is expected, and a value spelled with slashes is a pattern.
_REGEX_ALLOWED_BEFORE = set("(,=:[!&|?{};+-*%~^<>")
#: Keywords a regular expression may follow directly - there a value is expected as well.
_REGEX_KEYWORDS = frozenset(
    "return typeof case in of new delete void do else yield await instanceof throw".split()
)


def _comment_spans(text: str, javascript: bool) -> Iterator[tuple[int, int, bool]]:
    """(start, end, is a line comment) of every comment, strings and patterns walked over.

    The scan is what keeps a marker inside data from opening a comment. Quoted strings are
    read through to their end; so are a script's template literals, whose `${...}` holds code
    again and may hold a comment of its own; so are regular expressions, where a character
    class may spell `/*` outright. An unquoted `url(...)` of a stylesheet is read to its
    closing bracket, because the address inside it is not quoted and carries slashes.
    """
    index = 0
    length = len(text)
    #: The template literals entered, each with the braces open inside its substitution.
    #: None means the scan is inside the literal itself, a number means inside `${...}`.
    nest: list[int | None] = []
    while index < length:
        char = text[index]
        if nest and nest[-1] is None:  # inside a template literal: only its own syntax counts
            if char == "\\":
                index += 2
            elif char == "`":
                nest.pop()
                index += 1
            elif text.startswith("${", index):
                nest[-1] = 0
                index += 2
            else:
                index += 1
            continue
        if char == "/" and index + 1 < length:
            nxt = text[index + 1]
            if nxt == "*":
                end = text.find("*/", index + 2)
                end = length if end == -1 else end + 2
                yield index, end, False
                index = end
                continue
            if nxt == "/" and javascript:
                end = _line_end(text, index)
                yield index, end, True
                index = end
                continue
            if javascript and _regex_starts_here(text, index):
                index = _regex_end(text, index)
                continue
        if char in "\"'":
            index = _quoted_end(text, index)
            continue
        if javascript and char == "`":
            nest.append(None)
            index += 1
            continue
        if javascript and nest and char in "{}":
            open_braces = nest[-1] or 0
            if char == "{":
                nest[-1] = open_braces + 1
            elif open_braces:
                nest[-1] = open_braces - 1
            else:
                nest[-1] = None  # the substitution closed: back inside the literal
            index += 1
            continue
        if not javascript and char in "uU" and _url_starts_here(text, index):
            end = text.find(")", index)
            index = length if end == -1 else end + 1
            continue
        index += 1


def _line_end(text: str, at: int) -> int:
    """The index of the line break that ends the line `at` stands on, or the end of text."""
    end = text.find("\n", at)
    return len(text) if end == -1 else end


def _regex_starts_here(text: str, at: int) -> bool:
    """Does the `/` at `at` open a regular expression rather than divide?"""
    index = at - 1
    while index >= 0 and text[index] in " \t\r\n":
        index -= 1
    if index < 0:
        return True
    if text[index] in _REGEX_ALLOWED_BEFORE:
        return True
    end = index + 1
    while index >= 0 and (text[index].isalnum() or text[index] == "_"):
        index -= 1
    return text[index + 1:end] in _REGEX_KEYWORDS


def _regex_end(text: str, at: int) -> int:
    """The index just past a regular expression literal that opens at `at`."""
    index = at + 1
    length = len(text)
    in_class = False
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char in "\r\n":
            return at + 1  # unterminated: not a pattern after all, step over the slash alone
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index + 1
        index += 1
    return at + 1


def _quoted_end(text: str, at: int) -> int:
    """The index just past the quoted string that opens at `at`."""
    quote = text[at]
    index = at + 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char in "\r\n":
            return index  # unterminated: a line break ends it in both languages
        index += 1
    return length


def _url_starts_here(text: str, at: int) -> bool:
    """An unquoted `url(` of a stylesheet, whose address carries slashes of its own."""
    if not text[at:at + 4].lower() == "url(":
        return False
    if at and (text[at - 1].isalnum() or text[at - 1] in "_-"):
        return False
    rest = text[at + 4:].lstrip(" \t\r\n")
    return not rest.startswith(("\"", "'"))


def _looks_minified(text: str) -> bool:
    """Build output rather than a source: one line holds what a person writes in fifty."""
    return max((len(line) for line in text.splitlines()), default=0) > _MINIFIED_LINE


def _is_licence(body: str) -> bool:
    """A comment whose wording is legal text - translating it would change what it says."""
    if body.startswith(("/*!", "//!")):
        return True
    lowered = body.lower()
    return any(marker in lowered for marker in _LICENCE_MARKERS)


# --- html and svg -------------------------------------------------------------------------


def _markup_payloads(text: str) -> list[tuple[int, int, str]]:
    """Comments, the spoken elements of a drawing, and the comments of embedded code."""
    reader = _Markup(text)
    try:
        reader.feed(text)
        reader.close()
    except Exception:  # a fragment the parser refuses - what it read before that still holds
        pass
    reader.found.sort()
    return reader.found


class _Markup(HTMLParser):
    """A pass over markup that keeps OFFSETS, so the spans it finds can be rewritten.

    The parser reports a place as a line and a column; the raw text of a start tag is what
    turns that into the offset where the element's content begins. Character references are
    left folded (`convert_charrefs=False`) - the payload has to be the text as the file
    spells it, or the rewrite would put a decoded `&amp;` back into the markup.
    """

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=False)
        self.text = text
        self.starts = _line_starts(text)
        self.found: list[tuple[int, int, str]] = []
        self._open: tuple[str, int] | None = None

    # --- places ---

    def _at(self) -> int:
        line, col = self.getpos()
        return self.starts[line - 1] + col if line - 1 < len(self.starts) else len(self.text)

    # --- what is read ---

    def handle_comment(self, data: str) -> None:
        at = self._at()
        if not self.text.startswith("<!--", at):
            return  # a bogus comment (`<!foo>`): not a span this module rewrites
        body = self.text[at:at + 4 + len(data) + 3]
        if _is_licence(body):
            return
        for offset, _index, payload in comment_lines(body, _MARKUP_FIRST_RE, _MARKUP_LINE_RE):
            start = at + offset
            self.found.append((start, start + len(payload), payload))

    def handle_starttag(self, tag: str, attrs) -> None:
        raw = self.get_starttag_text() or ""
        if raw.endswith("/>"):
            return  # an empty element holds no content to read
        if tag in _SPOKEN_TAGS or tag in ("style", "script"):
            self._open = (tag, self._at() + len(raw))

    def handle_startendtag(self, tag: str, attrs) -> None:
        return

    def handle_endtag(self, tag: str) -> None:
        if self._open is None or self._open[0] != tag:
            return
        _name, start = self._open
        self._open = None
        end = self._at()
        if end <= start:
            return
        body = self.text[start:end]
        if tag == "style":
            self.found.extend(_script_payloads(body, False, start))
        elif tag == "script":
            self.found.extend(_script_payloads(body, True, start))
        else:
            self.found.extend(_spoken_payloads(body, start))


def _spoken_payloads(body: str, base: int) -> list[tuple[int, int, str]]:
    """The text of `<title>`/`<desc>`, line by line with the indentation left in place."""
    out: list[tuple[int, int, str]] = []
    offset = 0
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            at = base + offset + (len(line) - len(line.lstrip()))
            out.append((at, at + len(stripped), stripped))
        offset += len(line)
    return out


# --- places -------------------------------------------------------------------------------


def _line_starts(text: str) -> list[int]:
    """The offset each line of `text` begins at."""
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _place(starts: list[int], at: int) -> tuple[int, int]:
    """(line, column), both counted from one - the shape a report prints."""
    low, high = 0, len(starts) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if starts[middle] <= at:
            low = middle
        else:
            high = middle - 1
    return low + 1, at - starts[low] + 1
