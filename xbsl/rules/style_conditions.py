"""Conditions and checks (CODE_STYLE, section 8).

- 8.1 boolean values are not compared with `Истина` / `Ложь`;
- 8.2 `Неопределено` is checked via `==` / `!=`, not via `это`;
- 8.3 the `это` operator is negated on the inside, not on the outside.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens

MESSAGES = {
    "style/boolean-compare.title": {
        "ru": "Сравнение булева значения с Истина/Ложь",
        "en": "Comparing a boolean value with Истина/Ложь",
    },
    "style/boolean-compare.msg": {
        "ru": "Сравнение с '{keyword}' – булево значение "
              "проверяется без сравнения ('если Значение', 'если не Значение'). "
              "Для nullable (Булево?) сравнение обязательно и нарушением не является.",
        "en": "Comparison with '{keyword}' – a boolean value is "
              "checked without a comparison ('{n[если]} {n[Значение]}', '{n[если]} {n[не]} {n[Значение]}'). "
              "For nullable ({n[Булево]}?) a comparison is mandatory and is not a violation.",
    },
    "style/undefined-is.title": {
        "ru": "Проверка Неопределено оператором 'это'",
        "en": "Checking Неопределено with the 'это' operator",
    },
    "style/undefined-is.msg": {
        "ru": "'Неопределено' проверяется сравнением – использовать '{op} Неопределено'.",
        "en": "'Неопределено' is checked with a comparison – use '{op} Неопределено'.",
    },
    "style/negated-is.title": {
        "ru": "Отрицание оператора 'это' снаружи",
        "en": "Negating the 'это' operator on the outside",
    },
    "style/negated-is.msg": {
        "ru": "Отрицание 'это' снаружи скобок – отрицать внутри: 'Значение это не Тип'.",
        "en": "Negating '{n[это]}' outside the parentheses – negate inside: '{n[Значение]} {n[это]} {n[не]} {n[Тип]}'.",
    },
}
i18n.register(MESSAGES)

_BOOLEAN_KEYWORDS = {"TRUE": "Истина", "FALSE": "Ложь"}
_COMPARE_OPS = ("==", "!=")


def _is_op(tok: Token, *values: str) -> bool:
    return tok.kind == "OP" and tok.value in values


def _is_kw(tok: Token, *canonicals: str) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical in canonicals


@rule("style/boolean-compare", "style/boolean-compare.title", "C",
      severity=Severity.INFO, enabled_by_default=False)
def boolean_compare(source: SourceFile) -> Iterable[Diagnostic]:
    """8.1: `если Переменная`, not `если Переменная == Истина`.

    The rule concerns values of type `Булево`. For nullable (`Булево?`) the short form
    is not allowed and a comparison with `Истина` is mandatory – these cases cannot be
    told apart by tokens, so the rule is `info` and off by default: each spot is eyeballed.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks[:-1]):
        if not _is_op(tok, *_COMPARE_OPS):
            continue
        literal = None
        if _is_kw(toks[i + 1], *_BOOLEAN_KEYWORDS):
            literal = toks[i + 1]
        elif i > 0 and _is_kw(toks[i - 1], *_BOOLEAN_KEYWORDS):
            literal = toks[i - 1]
        if literal is None:
            continue
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/boolean-compare", Severity.INFO,
            i18n.t("style/boolean-compare.msg", keyword=_BOOLEAN_KEYWORDS[literal.canonical]),
        )


@rule("style/undefined-is", "style/undefined-is.title", "C",
      severity=Severity.WARNING)
def undefined_is(source: SourceFile) -> Iterable[Diagnostic]:
    """8.2: `если Значение == Неопределено`, not `если Значение это Неопределено`."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks):
        if not _is_kw(tok, "IS"):
            continue
        j = i + 1
        negated = j < len(toks) and _is_kw(toks[j], "NOT")
        if negated:
            j += 1
        if j < len(toks) and _is_kw(toks[j], "UNDEFINED"):
            replacement = "!=" if negated else "=="
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/undefined-is", Severity.WARNING,
                i18n.t("style/undefined-is.msg", op=replacement),
            )


@rule("style/negated-is", "style/negated-is.title", "C", severity=Severity.WARNING)
def negated_is(source: SourceFile) -> Iterable[Diagnostic]:
    """8.3: `если Значение это не Строка`, not `если не (Значение это Строка)`.

    We report only the simple parenthesis with a single `это` inside: a compound negation
    (`не (X это Y и ...)`) is not rewritten mechanically and needs a manual review.
    A compound negation is left alone by design, so the rule is quiet on it.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    n = len(toks)
    for i, tok in enumerate(toks):
        if not (_is_kw(tok, "NOT") and i + 1 < n and _is_op(toks[i + 1], "(")):
            continue
        depth, j = 0, i + 1
        is_count = 0
        compound = False
        while j < n:
            t = toks[j]
            if _is_op(t, "("):
                depth += 1
            elif _is_op(t, ")"):
                depth -= 1
                if depth == 0:
                    break
            elif depth == 1:
                if _is_kw(t, "IS"):
                    is_count += 1
                elif _is_kw(t, "AND", "OR"):
                    compound = True
            j += 1
        if is_count == 1 and not compound:
            yield Diagnostic(
                source.rel, tok.line, tok.col, "style/negated-is", Severity.INFO,
                i18n.t("style/negated-is.msg"),
            )
