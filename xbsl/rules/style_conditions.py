"""Conditions and checks (CODE_STYLE, section 8).

- 8.1 boolean values are not compared with `Истина` / `Ложь`;
- 8.2 `Неопределено` is checked via `==` / `!=`, not via `это`;
- 8.3 the `это` operator is negated on the inside, not on the outside.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import dataset, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import _skip_balanced, code_tokens, declarations, signatures, type_expr

MESSAGES = {
    "style/boolean-compare.title": {
        "ru": "Сравнение булева значения с {n[Истина]}/{n[Ложь]}",
        "en": "Comparing a boolean value with {n[Истина]}/{n[Ложь]}",
    },
    "style/boolean-compare.msg": {
        "ru": "Сравнение с '{keyword}' – булево значение "
              "проверяется без сравнения ('если Значение', 'если не Значение'). "
              "Если значение nullable (Булево?) или составное (Авто|Булево), сравнение "
              "обязательно: объявите тип явно, и правило замолчит.",
        "en": "Comparison with '{keyword}' – a boolean value is "
              "checked without a comparison ('{n[если]} {n[Значение]}', '{n[если]} {n[не]} {n[Значение]}'). "
              "When the value is nullable ({n[Булево]}?) or composite ({n[Авто]}|{n[Булево]}), "
              "the comparison is mandatory: state the type outright and the rule goes quiet.",
    },
    "style/undefined-is.title": {
        "ru": "Проверка {n[Неопределено]} оператором '{n[это]}'",
        "en": "Checking {n[Неопределено]} with the '{n[это]}' operator",
    },
    "style/undefined-is.msg": {
        "ru": "'{n[Неопределено]}' проверяется сравнением – использовать '{op} {n[Неопределено]}'.",
        "en": "'{n[Неопределено]}' is checked with a comparison – use '{op} {n[Неопределено]}'.",
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
# The type whose short form compiles. Both spellings: an English-written project is
# judged by the same rules as a Russian one.
_BOOLEAN_TYPE_NAMES = frozenset({"булево", "boolean"})

_member_texts_cache: dict[str, frozenset[str]] | None = None


def _is_op(tok: Token, *values: str) -> bool:
    return tok.kind == "OP" and tok.value in values


def _is_kw(tok: Token, *canonicals: str) -> bool:
    return tok.kind == "KEYWORD" and tok.canonical in canonicals


def _member_type_texts() -> dict[str, frozenset[str]]:
    """Member name -> every result type the catalog declares for it, in full spelling.

    Keyed by the bare member name and not by its owner type on purpose: a file rule cannot
    know what `Компоненты.КонтейнерФайл` is - the component's type lives in the paired yaml -
    while the name alone already answers the only question asked here, whether the value
    can be a plain `Булево`. A name declared as a union anywhere in the catalog is left
    alone: a false alarm on legal code costs more than a missed style nit.
    """
    global _member_texts_cache
    if _member_texts_cache is None:
        try:
            data = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - no data, no filtering
            data = {}
        texts: dict[str, set[str]] = {}
        for members in (data.get("member_types") or {}).values():
            for name, raw in members.items():
                texts.setdefault(name, set()).add(raw)
        _member_texts_cache = {name: frozenset(v) for name, v in texts.items()}
    return _member_texts_cache


def _plain_boolean(text: str) -> bool:
    """`Булево` and nothing else: no `?`, no union - only then the short form compiles."""
    return text.strip().casefold() in _BOOLEAN_TYPE_NAMES


def _member_needs_comparison(name: str) -> bool:
    """Does the catalog give this member a type that cannot be checked without a comparison?"""
    texts = _member_type_texts().get(name)
    return bool(texts) and not all(_plain_boolean(text) for text in texts)


def _chain_tail(toks: list[Token], end: int) -> Token | None:
    """The last link of the operand ending at `end`: the called method or the property read.

    `Компоненты.КонтейнерФайл.ПолучитьПеременную("dtReady")` answers `ПолучитьПеременную`,
    `Компоненты.ЗначениеБулево.Видимость` answers `Видимость`. The links before the last one
    do not matter: the type of the whole operand is the type of its last link.
    """
    if end < 0:
        return None
    tok = toks[end]
    if _is_op(tok, ")"):
        depth = 0
        i = end
        while i >= 0:
            if _is_op(toks[i], ")"):
                depth += 1
            elif _is_op(toks[i], "("):
                depth -= 1
                if depth == 0:
                    break
            i -= 1
        if i <= 0 or toks[i - 1].kind != "IDENT":
            return None
        return toks[i - 1]
    if tok.kind == "IDENT":
        return tok
    return None


def _type_needs_comparison(toks: list[Token], type_start: int) -> bool | None:
    """The annotation at `type_start`: is it anything other than a plain `Булево`?"""
    expr = type_expr(toks, type_start)
    if expr is None:
        return None
    return not _plain_boolean("".join(tok.value for tok in expr.toks))


def _param_needs_comparison(toks: list[Token], name: str, offset: int) -> bool | None:
    """The declared type of the enclosing method's parameter, when `name` is one."""
    enclosing = None
    for signature in signatures(toks):
        if signature.keyword.start > offset:
            break
        enclosing = signature
    if enclosing is None:
        return None
    for param in enclosing.params:
        if param.name.value == name and param.type_start is not None:
            return _type_needs_comparison(toks, param.type_start)
    return None


def _declared_needs_comparison(toks: list[Token], name: str, before: int) -> bool | None:
    """What the nearest declaration of `name` above `before` says; None - no declaration.

    The type comes either from the annotation (`знч Готово: Булево?`) or from the
    initializer's last link (`знч Готово = Контейнер.ПолучитьПеременную(...)`) - both forms
    occur in the same code, and only together do they cover the observed cases. A name that
    is not declared inside the method may still be a parameter, and a parameter carries its
    type outright.
    """
    found = None
    for decl in declarations(toks):
        if decl.keyword.start >= toks[before].start:
            break
        if any(tok.value == name for tok in decl.names):
            found = decl
    if found is None:
        return _param_needs_comparison(toks, name, toks[before].start)
    if found.type_start is not None:
        return _type_needs_comparison(toks, found.type_start)
    if found.value_start is None:
        return None
    end = _value_end(toks, found.value_start)
    tail = _chain_tail(toks, end) if end is not None else None
    if tail is None or (end is not None and toks[end].kind == "IDENT" and end == found.value_start
                        and not _is_op(toks[min(end + 1, len(toks) - 1)], ".")):
        return None  # a bare name copied into another name: one hop is enough
    return _member_needs_comparison(tail.value)


def _value_end(toks: list[Token], start: int) -> int | None:
    """Index of the last token of the initializer chain that starts at `start`."""
    n = len(toks)
    if start >= n or toks[start].kind not in ("IDENT", "KEYWORD"):
        return None
    i, last = start + 1, start
    while i < n:
        if _is_op(toks[i], "("):
            i = _skip_balanced(toks, i, "(", ")")
            last = i - 1
            continue
        if _is_op(toks[i], ".") and i + 1 < n and toks[i + 1].kind == "IDENT":
            last = i + 1
            i += 2
            continue
        break
    return last


@rule("style/boolean-compare", "style/boolean-compare.title", "C",
      severity=Severity.WARNING)
def boolean_compare(source: SourceFile) -> Iterable[Diagnostic]:
    """8.1: `если Переменная`, not `если Переменная == Истина`.

    The rule concerns values of type `Булево` and only them. A comparison is MANDATORY -
    and therefore no violation - as soon as the value is nullable (`Булево?`) or composite
    (`Авто|Булево`, what every component property is): the short form does not compile
    there ("Boolean expression is expected"). Such operands are told apart by the catalog,
    which keeps the full spelling of a member's type, and by the local declaration - the
    annotation or the initializer's last link. What the file cannot type at all is
    reported: an unknown name is the usual violation this rule exists for.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for i, tok in enumerate(toks[:-1]):
        if not _is_op(tok, *_COMPARE_OPS):
            continue
        literal = None
        operand_end = None
        if _is_kw(toks[i + 1], *_BOOLEAN_KEYWORDS):
            literal, operand_end = toks[i + 1], i - 1
        elif i > 0 and _is_kw(toks[i - 1], *_BOOLEAN_KEYWORDS):
            # `Истина == Значение`: the operand is on the right, its end is the chain tail.
            literal, operand_end = toks[i - 1], _value_end(toks, i + 1)
        if literal is None or operand_end is None or operand_end < 0:
            continue
        if _comparison_is_required(toks, operand_end):
            continue
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/boolean-compare", Severity.WARNING,
            i18n.t("style/boolean-compare.msg", keyword=_BOOLEAN_KEYWORDS[literal.canonical]),
        )


def _comparison_is_required(toks: list[Token], operand_end: int) -> bool:
    """Is the operand of a type that cannot be checked without a comparison?"""
    tail = _chain_tail(toks, operand_end)
    if tail is None:
        return False
    is_link = _is_op(toks[operand_end], ")") or (
        operand_end > 0 and _is_op(toks[operand_end - 1], ".")
    )
    if is_link:
        return _member_needs_comparison(tail.value)
    declared = _declared_needs_comparison(toks, tail.value, operand_end)
    return bool(declared)


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
