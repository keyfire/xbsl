"""Tier C: an interpolation expression the platform never evaluates.

A doubled interpolation sign right before a brace - `"%%{Выражение}"` - is read as an escaped
sign: the pair is swallowed, the brace stays ordinary text, and the value carries the literal
`%{Выражение}` instead of the computed one. Nothing says so: the compiler accepts the line and
the grammar is happy, so the only evidence is behaviour. Written the way it was meant, the
first sign is escaped - `"\\%%{Выражение}"` - or the string is built by concatenation.

The rule is a file rule on purpose: one literal is all it takes to decide.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens

MESSAGES = {
    "code/dead-interpolation.title": {
        "ru": "Интерполяция погашена удвоенным знаком",
        "en": "Interpolation killed by a doubled sign",
    },
    "code/dead-interpolation.found": {
        "ru": "Пара \"{sign}{sign}\" перед \"{{\" читается как экранированный знак: выражение "
              "не вычисляется, и в значение уходит текст \"{sign}{{...}}\". Экранируйте первый "
              "знак – \"\\{sign}{sign}{{...}}\" – или соберите строку конкатенацией.",
        "en": "The pair \"{sign}{sign}\" before \"{{\" reads as an escaped sign: the expression "
              "is not evaluated and the value carries the text \"{sign}{{...}}\". Escape the "
              "first sign - \"\\{sign}{sign}{{...}}\" - or build the string by concatenation.",
    },
}

i18n.register(MESSAGES)

#: The interpolation signs of the platform: %{expr} converts the value with `ToString`,
#: ${expr} with `Presentation`. A pair of either sign before the brace is what is swallowed.
SIGNS = ("%", "$")


@rule("code/dead-interpolation", "code/dead-interpolation.title", "C",
      severity=Severity.ERROR)
def dead_interpolation(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    text = source.text
    if not any(sign * 2 + "{" in text for sign in SIGNS):
        return  # the whole-text check at C speed keeps the token walk off most files
    lm = linemap(source)
    for tok in tokens(source):
        if tok.kind != "STRING":
            continue
        for sign in SIGNS:
            needle = sign * 2 + "{"
            idx = tok.value.find(needle)
            while idx >= 0:
                # An escaped first sign is the CORRECT spelling of "a literal sign, then an
                # interpolation" - `"\\%%{Value}"` - and must not be reported.
                if idx == 0 or tok.value[idx - 1] != "\\":
                    offset = tok.start + idx
                    line, col = lm.linecol(offset)
                    yield Diagnostic(
                        source.rel, line, col, "code/dead-interpolation", Severity.ERROR,
                        i18n.t("code/dead-interpolation.found", sign=sign),
                        # The fix is the escape the author meant: insert the backslash, keep
                        # the rest of the literal untouched.
                        fix=TextEdit(offset, offset, "\\"),
                    )
                idx = tok.value.find(needle, idx + 1)
