"""Where prose lives inside a project's resource files (.css, .js, .svg, .html).

A subsystem ships its resources as they are: the platform serves the files under `Resources`
to the browser untouched. So the typography of a project reaches the reader through them
exactly as it reaches him through a module, and the rules of `xbsl/rules/typography.py`
need to know which parts of such a file are prose. Two parts are:

- `comment` - what the author wrote for the next reader (all four formats);
- `text` - what the user reads on the screen: the character data of `<title>`, `<desc>`
  and `<text>` in an SVG, the text nodes of an HTML page.

Everything else stays out, because it is code rather than prose: selectors, property names,
identifiers, string literals, tag names, attribute names and attribute values.

A regular expression cannot tell the two apart, and a minified bundle shows why within the
first screen. There `/` opens a regular expression about as often as it divides, `//` sits
inside every URL of every string, and a pattern may well contain `/*`; in markup a `<` in a
text node is not a tag, and the body of `<script>` is not text anybody reads. So each format
gets a scanner. CSS and JS are walked by a state machine written here - strings, template
literals, regular expressions and comments; SVG and HTML go through the standard library's
HTMLParser, which reports the position of every construct it recognizes.

The scan is expensive on a vendor bundle (a megabyte and a half of minified JS is a normal
resource), and four rules of the group ask for it, so the result is cached on the source.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import NamedTuple

#: Suffix -> kind of the resource files this module reads. `SourceFile.kind` carries the
#: same words, so a rule tells a resource from a module by the kind alone.
SUFFIX_KINDS = {".css": "css", ".js": "js", ".svg": "svg", ".html": "html"}

#: The kinds themselves - what a rule checks `source.kind` against.
KINDS = frozenset(SUFFIX_KINDS.values())

#: A comment: prose for the next reader.
COMMENT = "comment"
#: Character data the user reads on the screen.
TEXT = "text"


class Segment(NamedTuple):
    """A stretch of prose in the file, as offsets into the decoded text."""

    kind: str  # COMMENT | TEXT
    start: int
    end: int


# --- CSS and JS ---------------------------------------------------------------------------

#: What may start a construct in JS code: a comment, a string, a template, a `/` that is
#: either a division or the opening of a regular expression.
_JS_NEXT = re.compile(r"//|/\*|[/\"'`]")
#: The same, plus braces - used only while an interpolation `${...}` of a template literal
#: is open, where a `}` closes the interpolation rather than a block.
_JS_NEXT_BRACED = re.compile(r"//|/\*|[/\"'`{}]")
#: Inside a template literal: its end, an interpolation, or an escape.
_JS_TEMPLATE = re.compile(r"`|\$\{|\\.", re.S)
#: In CSS only a block comment and a string can start anything: `//` is not a comment there.
_CSS_NEXT = re.compile(r"/\*|[\"']")

#: A word after which a `/` opens a regular expression rather than dividing. Everything else
#: that ends an expression - a name, a number, a closing `)` or `]`, a string - divides.
_REGEX_AFTER_WORD = frozenset({
    "case", "delete", "do", "else", "in", "instanceof", "new", "of", "return",
    "throw", "typeof", "void", "yield", "await",
})
#: A closing bracket after which a `/` divides. A `}` is left out on purpose: it ends a block
#: far more often than an object literal, and `if (x) {} /re/.test(y)` is the live form.
_DIVIDE_AFTER = frozenset(")]")
_WORD_TAIL = re.compile(r"[A-Za-z_$][\w$]*$")


def _starts_regex(code: str, after_value: bool) -> bool:
    """Whether a `/` at the end of `code` opens a regular expression.

    `code` is the source since the previous construct; `after_value` says that the previous
    construct was a value of its own (a string, a template, a regular expression), which a
    `/` divides. Where the two say nothing - the code is empty and nothing preceded - the
    answer is "a regular expression": the file starts there.
    """
    tail = code.rstrip()
    if not tail:
        return not after_value
    last = tail[-1]
    if last in _DIVIDE_AFTER:
        return False
    word = _WORD_TAIL.search(tail)
    if word:
        return word.group(0) in _REGEX_AFTER_WORD
    if last.isdigit():
        return False
    return True


def _skip_quoted(text: str, i: int, quote: str) -> int:
    """Index just past the string that opens at `text[i]`, or `i + 1` when it never closes.

    A JS or CSS string does not survive a raw line break, so a newline before the closing
    quote means the quote was not opening a string at all (a broken file, or an apostrophe
    somewhere the scanner has no business being). Giving up right after it keeps the rest of
    the file readable instead of swallowing it.
    """
    j = i + 1
    n = len(text)
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == quote:
            return j + 1
        if ch == "\n":
            return i + 1
        j += 1
    return i + 1


def _skip_regex(text: str, i: int) -> int:
    """Index just past the regular expression that opens at `text[i]`, or 0 when it does not.

    Zero means "this `/` was a division after all": a regular expression cannot hold a raw
    line break, so meeting one proves the guess wrong. The caller then walks on from just
    after the slash, which is what a division deserves.
    """
    j = i + 1
    n = len(text)
    in_class = False
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "\n":
            return 0
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        elif ch == "/" and not in_class:
            return j + 1
        j += 1
    return 0


def _scan_css(text: str) -> list[Segment]:
    """Block comments of a stylesheet; a `/*` inside a string is not one."""
    out: list[Segment] = []
    i = 0
    while True:
        m = _CSS_NEXT.search(text, i)
        if m is None:
            return out
        if m.group() == "/*":
            end = text.find("*/", m.end())
            body_end = len(text) if end < 0 else end
            out.append(Segment(COMMENT, m.end(), body_end))
            i = body_end if end < 0 else end + 2
        else:
            i = _skip_quoted(text, m.start(), m.group())


def _scan_js(text: str) -> list[Segment]:
    """Comments of a script, with strings, templates and regular expressions walked past.

    One loop in two modes. In code the scanner jumps from construct to construct; inside a
    template literal it looks for the closing backtick and for an interpolation `${...}`,
    whose body is ordinary code again and may hold comments of its own. Braces are counted
    only while an interpolation is open - in a megabyte of minified code every brace would
    otherwise cost an iteration for nothing.
    """
    out: list[Segment] = []
    i = 0
    n = len(text)
    templates: list[int] = []  # the brace depth at which each open interpolation started
    depth = 0
    code_start = 0             # where the code since the previous construct begins
    after_value = False        # the previous construct was a value, so a `/` divides
    in_template = False
    while i < n:
        if in_template:
            m = _JS_TEMPLATE.search(text, i)
            if m is None:
                return out
            token = m.group()
            i = m.end()
            if token.startswith("\\"):
                continue
            in_template = False
            code_start = i
            if token == "`":
                after_value = True
            else:  # `${` - the interpolation body is code
                templates.append(depth)
                after_value = False
            continue
        m = (_JS_NEXT_BRACED if templates else _JS_NEXT).search(text, i)
        if m is None:
            return out
        token = m.group()
        code = text[code_start:m.start()]
        if token in ("//", "/*"):
            closer = "\n" if token == "//" else "*/"
            end = text.find(closer, m.end())
            body_end = n if end < 0 else end
            out.append(Segment(COMMENT, m.end(), body_end))
            i = body_end if end < 0 else end + len(closer)
            code_start = i
            after_value = False
            continue
        if token in "\"'":
            i = _skip_quoted(text, m.start(), token)
            code_start = i
            after_value = True
            continue
        if token == "`":
            in_template = True
            i = m.end()
            continue
        if token == "{":
            depth += 1
            i = code_start = m.end()
            after_value = False
            continue
        if token == "}":
            i = code_start = m.end()
            if templates and depth == templates[-1]:
                templates.pop()
                in_template = True
                i = m.end()  # the `}` closed the interpolation; the template goes on
                continue
            depth = max(0, depth - 1)
            after_value = False
            continue
        # A bare `/`: either a division or the opening of a regular expression.
        if _starts_regex(code, after_value):
            end = _skip_regex(text, m.start())
            if end:
                i = code_start = end
                after_value = True
                continue
        i = code_start = m.end()
        after_value = True
    return out


# --- SVG and HTML -------------------------------------------------------------------------

#: Tags of an SVG whose character data the user reads. `<text>` covers `<tspan>` and
#: `<textPath>` as well - they live inside it, so the depth counter is already up.
_SVG_TEXT_TAGS = frozenset({"title", "desc", "text"})
#: Tags of an HTML page whose body is code rather than text.
_HTML_CODE_TAGS = frozenset({"script", "style"})
#: The four characters a comment is wrapped in on the opening side: `<!--`.
_COMMENT_OPEN = 4


class _Markup(HTMLParser):
    """Comments and readable character data of a markup file, with their offsets.

    HTMLParser reports a line and a column; the offsets are computed from the line starts of
    the same text, so a fix lands on the characters that are really in the file.
    """

    def __init__(self, text: str, *, text_tags: frozenset[str] | None) -> None:
        super().__init__(convert_charrefs=False)
        self.text = text
        self.text_tags = text_tags  # None - every text node is read (an HTML page)
        self.segments: list[Segment] = []
        self._line_start = [0]
        for m in re.finditer("\n", text):
            self._line_start.append(m.end())
        self._text_depth = 0
        self._code_depth = 0

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_start[line - 1] + col

    def _reads_data(self) -> bool:
        if self._code_depth:
            return False
        return True if self.text_tags is None else self._text_depth > 0

    def handle_comment(self, data: str) -> None:
        start = self._offset() + _COMMENT_OPEN
        self.segments.append(Segment(COMMENT, start, start + len(data)))

    def handle_data(self, data: str) -> None:
        if data.strip() and self._reads_data():
            start = self._offset()
            self.segments.append(Segment(TEXT, start, start + len(data)))

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _HTML_CODE_TAGS:
            self._code_depth += 1
        elif self.text_tags is not None and tag in self.text_tags:
            self._text_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_CODE_TAGS:
            self._code_depth = max(0, self._code_depth - 1)
        elif self.text_tags is not None and tag in self.text_tags:
            self._text_depth = max(0, self._text_depth - 1)


def _scan_markup(text: str, *, text_tags: frozenset[str] | None) -> list[Segment]:
    parser = _Markup(text, text_tags=text_tags)
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken file is judged by the compiler, not by us
        return parser.segments
    return parser.segments


# --- the entry point ----------------------------------------------------------------------

def _scan(kind: str, text: str) -> list[Segment]:
    if kind == "css":
        return _scan_css(text)
    if kind == "js":
        return _scan_js(text)
    if kind == "svg":
        return _scan_markup(text, text_tags=_SVG_TEXT_TAGS)
    if kind == "html":
        return _scan_markup(text, text_tags=None)
    return []


def segments(source) -> list[Segment]:
    """The prose of one resource file, cached on the source.

    A source that is not a resource has none: the module and the element description are
    read by the lexer and by the yaml loader, each with its own rules.
    """
    if source.kind not in KINDS:
        return []
    found = source.cache.get("restext")
    if found is None:
        found = _scan(source.kind, source.text)
        source.cache["restext"] = found
    return found
