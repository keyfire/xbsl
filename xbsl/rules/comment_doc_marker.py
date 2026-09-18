"""Tier B: the comment above a declaration that the development environment does not show.

The rule comment/doc-marker.

In a module the environment reads a documentation comment by its marker alone: the lines that
start with `///` and stand before a declaration - before its annotations, where it has any.
That text goes into the hover over a call and over the declaration itself, into the signature
help and into the documentation of a completion item. A `//` block in the very same place is
an ordinary comment to the environment, and so is a `/* ... */` one, however carefully it
lists the parameters: neither reaches the reader who meets the method by its call.

What can be documented is what the language lets be declared outside a method body: a method,
a structure, an exception, an enumeration and its items, a field, a constructor, a module
constant. A parameter has no comment of its own - it is described inside the comment of its
method.

The rule reports the comment block that stands RIGHT ABOVE such a declaration, with no blank
line in between - the place an author already uses for the description - when its lines start
with `//`. The fix respells every such line as `///` and touches nothing else: the text, the
indentation and the lines that are `///` already stay as they are. A block comment in that
place is reported without a fix, because turning it into lines is a rewrite, not a respelling.

A comment separated from the declaration by a blank line is a note about the section of the
module, not about the declaration, and is left alone; so is a comment inside a method body.

Off by default: a module written before the project knew about the marker has such a block
above almost every method.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.parser import Enum, Structure, parse

MESSAGES = {
    "comment/doc-marker.title": {
        "ru": "Комментарий над объявлением среда разработки не покажет",
        "en": "The comment above a declaration is not shown by the environment",
    },
    "comment/doc-marker.off": {
        "ru": "в модулях, написанных до знакомства с маркером, срабатывает почти над каждым методом",
        "en": "fires above almost every method of a module written before it knew about the marker",
    },
    "comment/doc-marker.line": {
        "ru": "Среда разработки читает документирующим комментарием только строки `///` перед "
              "объявлением: они попадают в подсказку при наведении, в подсказку сигнатуры и в "
              "автодополнение. Блок `//` на том же месте для неё обычный комментарий – замените "
              "`//` на `///`.",
        "en": "The environment reads as a documentation comment only the `///` lines before a "
              "declaration: they go into the hover, the signature help and the completion. A "
              "`//` block in the same place is an ordinary comment to it - write `///` instead "
              "of `//`.",
    },
    "comment/doc-marker.block": {
        "ru": "Среда разработки читает документирующим комментарием только строки `///` перед "
              "объявлением. Блок `/* ... */` в подсказку не попадает – перепишите описание "
              "строками `///`.",
        "en": "The environment reads as a documentation comment only the `///` lines before a "
              "declaration. A `/* ... */` block never reaches the hover - rewrite the description "
              "as `///` lines.",
    },
}
i18n.register(MESSAGES)


def _declarations(module) -> Iterable:
    """Every node that can carry a documentation comment, nested ones included."""
    for member in module.members:
        yield member
        if isinstance(member, Structure):
            yield from member.members
        elif isinstance(member, Enum):
            yield from member.items
            yield from member.methods


@rule(
    "comment/doc-marker", "comment/doc-marker.title", "B",
    severity=Severity.WARNING, enabled_by_default=False, off_reason="comment/doc-marker.off",
)
def doc_marker(source: SourceFile) -> Iterable[Diagnostic]:
    """A `//` or `/* */` block right above a declaration - see the module docstring."""
    if source.kind != "xbsl" or "//" not in source.text and "/*" not in source.text:
        return
    module, _errors = parse(source)
    if module is None:
        return
    lm = linemap(source)
    text_lines = source.text.split("\n")
    # Own-line comment tokens by the line they END on: a block comment is found by its last
    # line, which is the one that touches the declaration.
    by_last_line: dict[int, object] = {}
    for tok in tokens(source):
        if tok.kind != "COMMENT":
            continue
        if text_lines[tok.line - 1][: tok.col - 1].strip():
            continue  # a trailing comment after code
        by_last_line[tok.line + tok.value.count("\n")] = tok
    if not by_last_line:
        return
    seen: set[int] = set()
    for decl in _declarations(module):
        line, _col = lm.linecol(decl.start)
        if text_lines[line - 1][: _col - 1].strip():
            continue  # a declaration that does not start its line (an enumeration item in a row)
        block = []
        cursor = line - 1
        while cursor in by_last_line:
            tok = by_last_line[cursor]
            block.append(tok)
            cursor = tok.line - 1
        if not block:
            continue
        block.reverse()
        plain = [tok for tok in block if tok.subkind == "line" and not tok.value.startswith("///")]
        blocks = [tok for tok in block if tok.subkind != "line"]
        head = (plain or blocks or [None])[0]
        if head is None or head.start in seen:
            continue
        seen.add(head.start)
        if blocks:
            first = blocks[0]
            yield Diagnostic(
                source.rel, first.line, first.col, "comment/doc-marker", Severity.WARNING,
                i18n.t("comment/doc-marker.block"),
            )
            continue
        start = plain[0].start
        end = plain[-1].start + len(plain[-1].value)
        piece = source.text[start:end]
        respelled = "\n".join(
            part[: len(part) - len(part.lstrip())] + "/" + part.lstrip()
            if part.lstrip().startswith("//") and not part.lstrip().startswith("///") else part
            for part in piece.split("\n")
        )
        yield Diagnostic(
            source.rel, plain[0].line, plain[0].col, "comment/doc-marker", Severity.WARNING,
            i18n.t("comment/doc-marker.line"),
            fix=TextEdit(start, end, respelled),
        )
