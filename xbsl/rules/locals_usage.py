"""Tier C-2: unused local variables (знч/пер declarations).

A method is segmented by the verified block model (see code_structure). Inside a method the
знч/пер declarations and every identifier use are collected; if a name occurs nowhere else
(including string interpolations %{...}/${...}/%name) – the variable is unused.

The scope is deliberately narrow (знч/пер only), to avoid false positives: parameters, `для`
loop variables, `исп` resources and `поймать` catches are not checked (they are often left
unused on purpose).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules.code_structure import _OPENERS

MESSAGES = {
    "code/unused-local.title": {
        "ru": "Неиспользуемая локальная переменная",
        "en": "Unused local variable",
    },
    "code/unused-local.declared": {
        "ru": "Локальная переменная '{name}' объявлена, но не используется.",
        "en": "Local variable '{name}' is declared but not used.",
    },
    "code/unused-loop-var.title": {
        "ru": "Неиспользуемая переменная цикла",
        "en": "Unused loop variable",
    },
    "code/unused-loop-var.unused": {
        "ru": "Переменная цикла '{name}' не используется.",
        "en": "Loop variable '{name}' is not used.",
    },
}
i18n.register(MESSAGES)

_IDENT_IN = re.compile(r"[^\W\d]\w*", re.UNICODE)
_INTERP = re.compile(r"[%$]\{([^}]*)\}|[%$]([^\W\d]\w*)", re.UNICODE)


def _interp_idents(value: str) -> list[str]:
    """Identifiers used in a string's interpolations (%{expr}, ${expr}, %name)."""
    out: list[str] = []
    for m in _INTERP.finditer(value):
        if m.group(1) is not None:
            out += _IDENT_IN.findall(m.group(1))
        elif m.group(2):
            out.append(m.group(2))
    return out


def _method_spans(toks: list) -> list[tuple[int, int]]:
    """Token index ranges [start, end) for each top-level method."""
    spans: list[tuple[int, int]] = []
    depth = 0
    start: int | None = None
    prev: tuple | None = None
    for i, t in enumerate(toks):
        if t.kind == "COMMENT":
            continue
        opener = t.kind == "KEYWORD" and t.canonical in _OPENERS and t.value[:1].islower()
        if opener:
            is_else_if = (
                t.canonical == "IF"
                and prev is not None
                and prev[0] == "KEYWORD"
                and prev[1] == "ELSE"
                and prev[2] == t.line
            )
            if not is_else_if:
                if depth == 0 and t.canonical == "METHOD":
                    start = i
                depth += 1
        elif t.kind == "OP" and t.value == ";":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    spans.append((start, i + 1))
                    start = None
        prev = (t.kind, t.canonical if t.kind == "KEYWORD" else t.value, t.line)
    return spans


def _usage_counts(toks: list, start: int, end: int) -> Counter:
    """Number of uses of each identifier in the range: IDENT (not after a dot)
    + identifiers from string interpolations (%{...}/${...}/%name)."""
    counts: Counter = Counter()
    prev = None
    for j in range(start, end):
        t = toks[j]
        if t.kind == "IDENT":
            if not (prev is not None and prev.kind == "OP" and prev.value in (".", "?.")):
                counts[t.value] += 1
        elif t.kind == "STRING":
            for nm in _interp_idents(t.value):
                counts[nm] += 1
        if t.kind != "COMMENT":
            prev = t
    return counts


def _next_ident(toks: list, i: int, end: int):
    """The nearest IDENT after position i (skipping comments), or None."""
    k = i + 1
    while k < end and toks[k].kind == "COMMENT":
        k += 1
    return toks[k] if k < end and toks[k].kind == "IDENT" else None


@rule("code/unused-local", "code/unused-local.title", "C", severity=Severity.WARNING)
def unused_local(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    toks = tokens(source)
    diags: list[Diagnostic] = []
    for start, end in _method_spans(toks):
        counts = _usage_counts(toks, start, end)
        seen: set[str] = set()
        for j in range(start, end):
            t = toks[j]
            if t.kind == "KEYWORD" and t.canonical in ("VAL", "VAR") and t.value[:1].islower():
                name_tok = _next_ident(toks, j, end)
                if name_tok is not None and name_tok.value not in seen:
                    seen.add(name_tok.value)
                    if counts[name_tok.value] <= 1:  # declaration only, nowhere else
                        diags.append(Diagnostic(
                            source.rel, name_tok.line, name_tok.col,
                            "code/unused-local", Severity.WARNING,
                            i18n.t("code/unused-local.declared", name=name_tok.value),
                        ))
    return diags


@rule("code/unused-loop-var", "code/unused-loop-var.title", "C", severity=Severity.WARNING)
def unused_loop_var(source: SourceFile) -> Iterable[Diagnostic]:
    # A `для X из ...` loop variable that is not used in the body. Reproduces the server-side
    # compilation finding ("Неиспользуемая переменная").
    if source.kind != "xbsl":
        return []
    toks = tokens(source)
    diags: list[Diagnostic] = []
    for start, end in _method_spans(toks):
        counts = _usage_counts(toks, start, end)
        for j in range(start, end):
            t = toks[j]
            if t.kind == "KEYWORD" and t.canonical == "FOR" and t.value[:1].islower():
                # variables before `из`: X, or X, Y (comma-separated)
                k = j + 1
                while k < end:
                    while k < end and toks[k].kind == "COMMENT":
                        k += 1
                    if k >= end or toks[k].kind != "IDENT":
                        break
                    var = toks[k]
                    if counts[var.value] <= 1:
                        diags.append(Diagnostic(
                            source.rel, var.line, var.col,
                            "code/unused-loop-var", Severity.WARNING,
                            i18n.t("code/unused-loop-var.unused", name=var.value),
                        ))
                    k += 1
                    if k < end and toks[k].kind == "OP" and toks[k].value == ",":
                        k += 1
                        continue
                    break
    return diags
