"""Apply the mechanical fixes a rule attached to its findings (--fix).

A fixable finding carries either a span edit (Diagnostic.fix, a TextEdit into the file's
decoded text) or, for whole-file rules like whitespace/mixed-newline, no span edit – the
fixer recognizes it by id and normalizes newlines. Only unambiguous, reversible mechanical
fixes are attached (trailing whitespace, typography characters, newline style); anything
that needs judgment is left to the author.

The edits of one file are applied together: overlapping spans are resolved deterministically
(earliest start wins, ties by longest span), the survivors applied last-to-first so offsets
stay valid, and the result re-encoded preserving the original BOM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from xbsl.diagnostics import Diagnostic
from xbsl.engine import SourceFile

# Rules fixed over the whole file rather than by a span edit.
_MIXED_NEWLINE = "whitespace/mixed-newline"
FULL_FILE_FIX_RULES = frozenset({_MIXED_NEWLINE})

_NEWLINE_RE = re.compile(r"\r\n|\r|\n")


@dataclass
class FixResult:
    text: str            # the fixed text
    applied: int         # number of findings actually fixed
    changed: bool        # text differs from the original


def is_fixable(diag: Diagnostic) -> bool:
    return diag.fix is not None or diag.rule_id in FULL_FILE_FIX_RULES


def _dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    # Prefer CRLF, then LF, then CR on ties – a stable, platform-neutral order.
    return max((("\r\n", crlf), ("\n", lf), ("\r", cr)), key=lambda kv: kv[1])[0]


def _select_edits(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Non-overlapping span-fix diagnostics: earliest start wins, ties by longest span."""
    spans = sorted(
        (d for d in diags if d.fix is not None),
        key=lambda d: (d.fix.start, -(d.fix.end - d.fix.start)),
    )
    chosen: list[Diagnostic] = []
    last_end = -1
    for d in spans:
        if d.fix.start >= last_end:
            chosen.append(d)
            last_end = d.fix.end
    return chosen


def fix_source(source: SourceFile, diags: list[Diagnostic]) -> FixResult:
    """Compute the fixed text for one file from its diagnostics (does not write to disk)."""
    text = source.text
    edits = _select_edits(diags)
    for d in sorted(edits, key=lambda d: d.fix.start, reverse=True):
        text = text[: d.fix.start] + d.fix.new + text[d.fix.end :]
    applied = len(edits)

    if any(d.rule_id == _MIXED_NEWLINE for d in diags):
        # Newlines may be offset by the span edits above; recompute the dominant style on the
        # edited text (span edits never touch line breaks, so the dominant style is unchanged).
        nl = _dominant_newline(text)
        normalized = _NEWLINE_RE.sub(nl, text)
        if normalized != text:
            text = normalized
        applied += 1

    return FixResult(text=text, applied=applied, changed=text != source.text)


def encode(source: SourceFile, text: str) -> bytes:
    """Encode the fixed text back to bytes, preserving the original UTF-8 BOM."""
    return text.encode("utf-8-sig" if source.had_bom else "utf-8")
