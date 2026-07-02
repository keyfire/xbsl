"""Тир B: типографика в комментариях и строковых литералах XBSL.

Правила типографики:
- тире: среднее – (U+2013), НЕ длинное — (U+2014);  область: проза/комментарии;
- многоточие: три точки ..., НЕ символ … (U+2026);  область: проза/комментарии;
- кавычки: прямые "  (шире всего – и в коде, и в комментариях), НЕ кудрявые и НЕ ёлочки;
  ИСКЛЮЧЕНИЕ: в UI-строках, выводимых пользователю, ёлочки «» допустимы.

Поэтому:
- длинное тире и символ многоточия проверяем в комментариях (в строках кода – как есть);
- кудрявые кавычки “ ” ‘ ’ – и в комментариях, и в строках (не допускаются нигде);
- ёлочки « » – только в комментариях (в UI-строках допустимы).
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap, tokens

_EM_DASH = "—"  # U+2014
_ELLIPSIS = "…"  # U+2026
_CURLY = "“”‘’"  # U+201C..U+2019
_GUILLEMETS = "«»"  # U+00AB, U+00BB


def _hits(source: SourceFile, kinds: tuple[str, ...], chars: str):
    lm = linemap(source)
    for tok in tokens(source):
        if tok.kind not in kinds:
            continue
        for idx, ch in enumerate(tok.value):
            if ch in chars:
                line, col = lm.linecol(tok.start + idx)
                yield ch, line, col


# Длинное тире и ёлочки массово встречаются в существующих комментариях кода, поэтому
# эти два правила по умолчанию выключены и имеют severity=info (включаются через --select).
@rule(
    "typography/em-dash", "Длинное тире в комментарии", "B",
    severity=Severity.INFO, enabled_by_default=False,
)
def em_dash(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col in _hits(source, ("COMMENT",), _EM_DASH):
        yield Diagnostic(
            source.rel, line, col, "typography/em-dash", Severity.INFO,
            "Длинное тире U+2014 в комментарии – использовать среднее тире – (U+2013).",
        )


@rule("typography/ellipsis", "Символ многоточия в комментарии", "B", severity=Severity.WARNING)
def ellipsis_char(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col in _hits(source, ("COMMENT",), _ELLIPSIS):
        yield Diagnostic(
            source.rel, line, col, "typography/ellipsis", Severity.WARNING,
            "Символ многоточия U+2026 в комментарии – использовать три точки '...'.",
        )


@rule("typography/curly-quotes", "Кудрявые кавычки", "B", severity=Severity.WARNING)
def curly_quotes(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for ch, line, col in _hits(source, ("COMMENT", "STRING"), _CURLY):
        yield Diagnostic(
            source.rel, line, col, "typography/curly-quotes", Severity.WARNING,
            f"Кудрявая кавычка U+{ord(ch):04X} – использовать прямые кавычки \".",
        )


@rule(
    "typography/guillemets-comment", "Ёлочки в комментарии", "B",
    severity=Severity.INFO, enabled_by_default=False,
)
def guillemets_in_comment(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for ch, line, col in _hits(source, ("COMMENT",), _GUILLEMETS):
        yield Diagnostic(
            source.rel, line, col, "typography/guillemets-comment", Severity.INFO,
            f"Ёлочка U+{ord(ch):04X} в комментарии – в комментариях прямые кавычки \" "
            "(ёлочки допустимы только в UI-строках).",
        )
