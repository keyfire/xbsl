"""Тир C-2: неиспользуемые локальные переменные (объявления знч/пер).

Метод сегментируется по выверенной блочной модели (см. code_structure). Внутри метода
собираются объявления знч/пер и все использования идентификаторов; если имя больше нигде
не встречается (в т.ч. в интерполяциях строк %{...}/${...}/%имя) – переменная не используется.

Область намеренно узкая (только знч/пер), чтобы не давать ложных срабатываний: параметры,
переменные цикла `для`, ресурсы `исп` и перехват `поймать` не проверяются (часто не
используются намеренно). Правило выверено на корпусе сайта (0 срабатываний).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import tokens
from xbsllint.rules.code_structure import _OPENERS

_IDENT_IN = re.compile(r"[^\W\d]\w*", re.UNICODE)
_INTERP = re.compile(r"[%$]\{([^}]*)\}|[%$]([^\W\d]\w*)", re.UNICODE)


def _interp_idents(value: str) -> list[str]:
    """Идентификаторы, использованные в интерполяциях строки (%{expr}, ${expr}, %имя)."""
    out: list[str] = []
    for m in _INTERP.finditer(value):
        if m.group(1) is not None:
            out += _IDENT_IN.findall(m.group(1))
        elif m.group(2):
            out.append(m.group(2))
    return out


def _method_spans(toks: list) -> list[tuple[int, int]]:
    """Диапазоны индексов токенов [начало, конец) для каждого метода верхнего уровня."""
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
    """Число использований каждого идентификатора в диапазоне: IDENT (не после точки)
    + идентификаторы из интерполяций строк (%{...}/${...}/%имя)."""
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
    """Ближайший IDENT после позиции i (пропуская комментарии), или None."""
    k = i + 1
    while k < end and toks[k].kind == "COMMENT":
        k += 1
    return toks[k] if k < end and toks[k].kind == "IDENT" else None


@rule("code/unused-local", "Неиспользуемая локальная переменная", "C", severity=Severity.WARNING)
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
                    if counts[name_tok.value] <= 1:  # только объявление, больше нигде
                        diags.append(Diagnostic(
                            source.rel, name_tok.line, name_tok.col,
                            "code/unused-local", Severity.WARNING,
                            f"Локальная переменная '{name_tok.value}' объявлена, но не используется.",
                        ))
    return diags


@rule("code/unused-loop-var", "Неиспользуемая переменная цикла", "C", severity=Severity.WARNING)
def unused_loop_var(source: SourceFile) -> Iterable[Diagnostic]:
    # Переменная цикла `для X из ...`, не используемая в теле. Выверено на корпусе –
    # воспроизводит находки серверной компиляции ("Неиспользуемая переменная") без ложных.
    if source.kind != "xbsl":
        return []
    toks = tokens(source)
    diags: list[Diagnostic] = []
    for start, end in _method_spans(toks):
        counts = _usage_counts(toks, start, end)
        for j in range(start, end):
            t = toks[j]
            if t.kind == "KEYWORD" and t.canonical == "FOR" and t.value[:1].islower():
                # переменные до `из`: X либо X, Y (через запятую)
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
                            f"Переменная цикла '{var.value}' не используется.",
                        ))
                    k += 1
                    if k < end and toks[k].kind == "OP" and toks[k].value == ",":
                        k += 1
                        continue
                    break
    return diags
