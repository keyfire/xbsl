"""Code layout (CODE_STYLE, sections 1 and 6).

- 1.1 the indent is 4 spaces, tabs are forbidden;
- 1.2 the maximum line length is 120 characters (string literals aside);
- 1.3 compound statements are closed by `;` on its own line;
- 6.1 operators move to the start of a line (except `+` in a concatenation);
- 6.2 commas stay at the end of the lines when parameters are wrapped.

`Запрос{ ... }` blocks are a separate DSL, the code rules do not touch them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules._syntax import (
    code_tokens,
    in_query,
    inside,
    line_span,
    lines,
    spans_of,
)

MESSAGES = {
    "style/tab-indent.title": {
        "ru": "Табуляция в отступе",
        "en": "Tab in the indentation",
    },
    "style/tab-indent.found": {
        "ru": "Табуляция в отступе – отступ задаётся четырьмя пробелами.",
        "en": "Tab in the indentation – the indent is four spaces.",
    },
    "style/line-length.title": {
        "ru": "Строка длиннее 120 символов",
        "en": "Line longer than 120 characters",
    },
    "style/line-length.over": {
        "ru": "Длина строки {length} > {limit} символов – перенести выражение.",
        "en": "Line length {length} > {limit} characters – wrap the expression.",
    },
    "style/semicolon-line.title": {
        "ru": "';' не на отдельной строке",
        "en": "';' not on its own line",
    },
    "style/semicolon-line.own-line": {
        "ru": "';' закрывает составную инструкцию и пишется на отдельной строке "
              "с отступом самой инструкции.",
        "en": "';' closes a compound statement and goes on its own line, "
              "indented like the statement itself.",
    },
    "style/wrap-operator.title": {
        "ru": "Операция в конце перенесённой строки",
        "en": "Operator at the end of a wrapped line",
    },
    "style/wrap-operator.trailing": {
        "ru": "Операция '{op}' в конце перенесённой строки – "
              "переносить операцию в начало следующей строки.",
        "en": "Operator '{op}' at the end of a wrapped line – "
              "move the operator to the start of the next line.",
    },
    "style/wrap-comma.title": {
        "ru": "Запятая в начале перенесённой строки",
        "en": "Comma at the start of a wrapped line",
    },
    "style/wrap-comma.leading": {
        "ru": "Запятая в начале перенесённой строки – запятые остаются в конце строк.",
        "en": "Comma at the start of a wrapped line – commas stay at the end of the lines.",
    },
}
i18n.register(MESSAGES)

MAX_LINE = 120

_INDENT_RE = re.compile(r"^[ \t]*")

# Operators that must sit at the start of a new line when an expression is wrapped.
# `+` is excluded: the docs explicitly allow it at the end of a line for string concatenation.
_WRAP_OPS = frozenset({"==", "!=", "<=", ">=", "*", "/", "%", "??", "**"})
_WRAP_KEYWORDS = frozenset({"AND", "OR", "NOT"})


@rule("style/tab-indent", "style/tab-indent.title", "B", severity=Severity.WARNING)
def tab_indent(source: SourceFile) -> Iterable[Diagnostic]:
    """1.1: the indent is 4 spaces, tabs are forbidden."""
    if source.kind != "xbsl":
        return
    strings = spans_of(source, ("STRING",))
    for num, text in enumerate(lines(source), start=1):
        indent = _INDENT_RE.match(text).group(0)
        pos = indent.find("\t")
        if pos < 0:
            continue
        start, _ = line_span(source, num)
        if inside(strings, start):  # a line inside a multi-line literal
            continue
        yield Diagnostic(
            source.rel, num, pos + 1, "style/tab-indent", Severity.WARNING,
            i18n.t("style/tab-indent.found"),
        )


@rule(
    "style/line-length", "style/line-length.title", "B",
    severity=Severity.INFO, enabled_by_default=False,
)
def line_length(source: SourceFile) -> Iterable[Diagnostic]:
    """1.2: the maximum line length is 120 characters.

    String literals are excluded: the docs allow long lines when splitting them hurts
    readability, and in this project that is HTML/CSS/SVG in inserts. The marker – the
    character at position 121 lies inside a string literal.
    """
    if source.kind != "xbsl":
        return
    strings = spans_of(source, ("STRING",))
    for num, text in enumerate(lines(source), start=1):
        if len(text) <= MAX_LINE:
            continue
        start, _ = line_span(source, num)
        overflow = start + MAX_LINE
        if inside(strings, overflow) or in_query(source, overflow):
            continue
        yield Diagnostic(
            source.rel, num, MAX_LINE + 1, "style/line-length", Severity.INFO,
            i18n.t("style/line-length.over", length=len(text), limit=MAX_LINE),
        )


@rule("style/semicolon-line", "style/semicolon-line.title", "C", severity=Severity.WARNING)
def semicolon_own_line(source: SourceFile) -> Iterable[Diagnostic]:
    """1.3: `;` closes a compound statement and is written on its own line."""
    if source.kind != "xbsl":
        return
    for tok in code_tokens(source):
        if not (tok.kind == "OP" and tok.value == ";"):
            continue
        before = lines(source)[tok.line - 1][: tok.col - 1]
        if before.strip():
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/semicolon-line", Severity.WARNING,
                i18n.t("style/semicolon-line.own-line"),
            )


@rule("style/wrap-operator", "style/wrap-operator.title", "C", severity=Severity.WARNING)
def wrap_operator(source: SourceFile) -> Iterable[Diagnostic]:
    """6.1: when an expression is wrapped the operator goes at the start of a new line (except `+`)."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks[:-1]):
        if toks[i + 1].line == tok.end_line:
            continue  # not the last token on the line
        is_op = tok.kind == "OP" and tok.value in _WRAP_OPS
        is_kw = tok.kind == "KEYWORD" and tok.canonical in _WRAP_KEYWORDS
        if is_op or is_kw:
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/wrap-operator", Severity.WARNING,
                i18n.t("style/wrap-operator.trailing", op=tok.value),
            )


@rule("style/wrap-comma", "style/wrap-comma.title", "C", severity=Severity.WARNING)
def wrap_comma(source: SourceFile) -> Iterable[Diagnostic]:
    """6.2: when a parameter list is wrapped, commas stay at the end of the lines."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks):
        if not (tok.kind == "OP" and tok.value == ","):
            continue
        if i > 0 and toks[i - 1].end_line == tok.line:
            continue  # the comma continues the line – all good
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/wrap-comma", Severity.WARNING,
            i18n.t("style/wrap-comma.leading"),
        )
