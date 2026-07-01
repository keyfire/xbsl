"""Тир B: пробелы, переводы строк, кодировка (по сырому тексту, без разбора кода)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap

_TRAILING_RE = re.compile(r"[ \t]+(?=\r|\n|$)")


@rule("whitespace/trailing", "Хвостовые пробелы", "B", severity=Severity.WARNING)
def trailing_whitespace(source: SourceFile) -> Iterable[Diagnostic]:
    lm = linemap(source)
    for m in _TRAILING_RE.finditer(source.text):
        line, col = lm.linecol(m.start())
        yield Diagnostic(
            source.rel, line, col, "whitespace/trailing", Severity.WARNING,
            "Хвостовые пробелы в конце строки.",
        )


@rule("whitespace/mixed-newline", "Смешанные переводы строк", "B", severity=Severity.WARNING)
def mixed_newline(source: SourceFile) -> Iterable[Diagnostic]:
    if source.newline == "mixed":
        yield Diagnostic(
            source.rel, 1, 1, "whitespace/mixed-newline", Severity.WARNING,
            "В файле смешаны переводы строк (CRLF и LF) – привести к одному виду.",
        )


@rule("encoding/utf8", "Файл не в UTF-8", "B", severity=Severity.ERROR)
def encoding_utf8(source: SourceFile) -> Iterable[Diagnostic]:
    if source.decode_error:
        yield Diagnostic(
            source.rel, 1, 1, "encoding/utf8", Severity.ERROR,
            f"Файл не читается как UTF-8: {source.decode_error}",
        )
