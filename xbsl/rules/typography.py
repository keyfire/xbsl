"""Tier B: typography in XBSL comments and string literals.

The typography rules:
- dash: en dash – (U+2013), NOT em dash — (U+2014);  scope: prose/comments;
- ellipsis: three dots ..., NOT the … character (U+2026);  scope: prose/comments;
- quotes: straight " (the widest rule – code and comments alike), neither curly nor guillemets;
  EXCEPTION: guillemets «» are fine inside UI strings shown to the user.

Hence:
- the em dash and the ellipsis character are checked in comments only (code strings are left alone);
- curly quotes “ ” ‘ ’ are checked in comments and in strings (allowed nowhere);
- guillemets « » are checked in comments only (they are legitimate in UI strings).
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens

MESSAGES = {
    "typography/em-dash.title": {
        "ru": "Длинное тире в комментарии",
        "en": "Em dash in a comment",
    },
    "typography/em-dash.found": {
        "ru": "Длинное тире U+2014 в комментарии – использовать среднее тире – (U+2013).",
        "en": "Em dash U+2014 in a comment – use an en dash – (U+2013).",
    },
    "typography/ellipsis.title": {
        "ru": "Символ многоточия в комментарии",
        "en": "Ellipsis character in a comment",
    },
    "typography/ellipsis.found": {
        "ru": "Символ многоточия U+2026 в комментарии – использовать три точки '...'.",
        "en": "Ellipsis character U+2026 in a comment – use three dots '...'.",
    },
    "typography/curly-quotes.title": {
        "ru": "Кудрявые кавычки",
        "en": "Curly quotes",
    },
    "typography/curly-quotes.found": {
        "ru": "Кудрявая кавычка U+{code} – использовать прямые кавычки \".",
        "en": "Curly quote U+{code} – use straight quotes \".",
    },
    "typography/guillemets-comment.title": {
        "ru": "Ёлочки в комментарии",
        "en": "Guillemets in a comment",
    },
    "typography/guillemets-comment.found": {
        "ru": "Ёлочка U+{code} в комментарии – в комментариях прямые кавычки \" "
              "(ёлочки допустимы только в UI-строках).",
        "en": "Guillemet U+{code} in a comment – comments use straight quotes \" "
              "(guillemets are allowed in UI strings only).",
    },
}
i18n.register(MESSAGES)

_EM_DASH = "—"  # U+2014
_ELLIPSIS = "…"  # U+2026
_CURLY = "“”‘’"  # U+201C..U+2019
_GUILLEMETS = "«»"  # U+00AB, U+00BB

# Unambiguous replacements for --fix: curly doubles/guillemets → straight ", curly singles → '.
_STRAIGHT = {"“": '"', "”": '"', "‘": "'", "’": "'", "«": '"', "»": '"'}


def _hits(source: SourceFile, kinds: tuple[str, ...], chars: str):
    # The vast majority of files contain none of the characters at all: a whole-text
    # check at C speed removes the per-character token walk (it was visible in the
    # whole-project profile).
    text = source.text
    if not any(ch in text for ch in chars):
        return
    lm = linemap(source)
    for tok in tokens(source):
        if tok.kind not in kinds:
            continue
        for idx, ch in enumerate(tok.value):
            if ch in chars:
                offset = tok.start + idx
                line, col = lm.linecol(offset)
                yield ch, line, col, offset


# The em dash and guillemets are all over existing comments, so these two rules are off by
# default and carry severity=info (enable them with --select).
@rule(
    "typography/em-dash", "typography/em-dash.title", "B",
    severity=Severity.INFO, enabled_by_default=False,
)
def em_dash(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col, offset in _hits(source, ("COMMENT",), _EM_DASH):
        yield Diagnostic(
            source.rel, line, col, "typography/em-dash", Severity.INFO,
            i18n.t("typography/em-dash.found"),
            fix=TextEdit(offset, offset + 1, "–"),  # em dash → en dash
        )


@rule("typography/ellipsis", "typography/ellipsis.title", "B", severity=Severity.WARNING)
def ellipsis_char(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for _ch, line, col, offset in _hits(source, ("COMMENT",), _ELLIPSIS):
        yield Diagnostic(
            source.rel, line, col, "typography/ellipsis", Severity.WARNING,
            i18n.t("typography/ellipsis.found"),
            fix=TextEdit(offset, offset + 1, "..."),  # … → three dots
        )


@rule("typography/curly-quotes", "typography/curly-quotes.title", "B", severity=Severity.WARNING)
def curly_quotes(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for ch, line, col, offset in _hits(source, ("COMMENT", "STRING"), _CURLY):
        yield Diagnostic(
            source.rel, line, col, "typography/curly-quotes", Severity.WARNING,
            i18n.t("typography/curly-quotes.found", code=f"{ord(ch):04X}"),
            fix=TextEdit(offset, offset + 1, _STRAIGHT[ch]),  # curly → straight " or '
        )


@rule(
    "typography/guillemets-comment", "typography/guillemets-comment.title", "B",
    severity=Severity.INFO, enabled_by_default=False,
)
def guillemets_in_comment(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    for ch, line, col, offset in _hits(source, ("COMMENT",), _GUILLEMETS):
        yield Diagnostic(
            source.rel, line, col, "typography/guillemets-comment", Severity.INFO,
            i18n.t("typography/guillemets-comment.found", code=f"{ord(ch):04X}"),
            fix=TextEdit(offset, offset + 1, _STRAIGHT[ch]),  # «» → straight " in a comment
        )
