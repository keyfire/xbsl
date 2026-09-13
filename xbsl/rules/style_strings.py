"""Collections and strings (CODE_STYLE, sections 4 and 5).

- 4.1 a collection literal is preferred over filling one by hand;
- 5.1 rely on the implicit conversion rather than on `.ВСтроку()`;
- 5.2 interpolation is preferred over concatenation.

All three are file rules, reported as warnings and on by default.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, declarations, type_expr

MESSAGES = {
    "style/collection-literal.title": {
        "ru": "Ручное наполнение коллекции вместо литерала",
        "en": "Manual collection fill instead of a literal",
    },
    "style/collection-literal.filled": {
        "ru": "Коллекция '{name}' наполняется вызовами '{method}' сразу после "
              "создания – записать литералом коллекции.",
        "en": "Collection '{name}' is filled with '{method}' calls right after "
              "creation – write it as a collection literal.",
    },
    "style/redundant-tostring.title": {
        "ru": "'.ВСтроку()' в конкатенации",
        "en": "'.{n[ВСтроку]}()' in a concatenation",
    },
    "style/redundant-tostring.concat": {
        "ru": "'.ВСтроку()' в конкатенации со строкой – преобразование выполняется неявно.",
        "en": "'.{n[ВСтроку]}()' in a concatenation with a string – the conversion is implicit.",
    },
    "style/interpolation.title": {
        "ru": "Конкатенация вместо интерполяции",
        "en": "Concatenation instead of interpolation",
    },
    # Braces are doubled: every template goes through str.format (see xbsl/i18n.py).
    "style/interpolation.concat": {
        "ru": "Конкатенация строки со значением – использовать интерполяцию "
              "('%Имя', '${{выражение}}').",
        "en": "Concatenation of a string with a value – use interpolation "
              "('%{n[Имя]}', '${{{n[Выражение]}}}').",
    },
}
i18n.register(MESSAGES)

# Collection constructors and the methods that fill them (4.1).
_COLLECTION_FILL = {
    "Массив": ("Добавить",),
    "Множество": ("Добавить",),
    "Соответствие": ("Вставить",),
    "Список": ("Добавить",),
}
_TOSTRING = "ВСтроку"


@lru_cache(maxsize=1)
def _tostring_names() -> frozenset[str]:
    """The conversion method in both spellings, the English half from the dictionary.

    A translated tree calls it `ToString`, and a rule that knows the Russian name alone never
    sees that tree. Without the data the set stays Russian, as everywhere else.
    """
    english = terms.common_english(_TOSTRING)
    return frozenset({_TOSTRING, english}) if english else frozenset({_TOSTRING})


dataset.register_reset(_tostring_names.cache_clear)


def _is_op(tok: Token, *values: str) -> bool:
    return tok.kind == "OP" and tok.value in values


@rule("style/collection-literal", "style/collection-literal.title", "C",
      severity=Severity.WARNING)
def collection_literal(source: SourceFile) -> Iterable[Diagnostic]:
    """4.1: `пер Кнопки = [Да, Нет]` instead of a constructor and a `.Добавить()` chain.

    We report only when the declaration is immediately followed by filling the same
    variable: inside a loop `.Добавить()` is fine, and the rule leaves such places alone.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for decl in declarations(toks):
        if decl.value_start is None or len(decl.names) != 1:
            continue
        value = toks[decl.value_start]
        if not (value.kind == "KEYWORD" and value.canonical == "NEW"):
            continue
        ctor = type_expr(toks, decl.value_start + 1)
        if ctor is None or ctor.toks[0].kind != "IDENT":
            continue
        fill_methods = _COLLECTION_FILL.get(ctor.toks[0].value)
        if fill_methods is None:
            continue
        # a constructor with no arguments: `()` right after the type
        k = ctor.end
        if not (k + 1 < len(toks) and _is_op(toks[k], "(") and _is_op(toks[k + 1], ")")):
            continue

        name = decl.names[0].value
        j = k + 2
        if not (
            j + 2 < len(toks)
            and toks[j].kind == "IDENT" and toks[j].value == name
            and _is_op(toks[j + 1], ".")
            and toks[j + 2].kind == "IDENT" and toks[j + 2].value in fill_methods
        ):
            continue

        yield Diagnostic(
            source.rel, decl.keyword.line, decl.keyword.col,
            "style/collection-literal", Severity.WARNING,
            i18n.t("style/collection-literal.filled", name=name, method=toks[j + 2].value),
        )


#: Operators that keep a concatenation chain going when it is walked leftwards at one bracket
#: depth: the additive signs are the chain itself, the multiplicative ones bind inside one of
#: its operands, the dot joins the links of a member chain, and the postfix `!` (the persistent
#: operation) stays inside the operand it follows. Anything else - an assignment, a comma, a
#: comparison, an arrow, the safe access `?.` - ends the chain.
_CHAIN_OPS = frozenset({"+", "-", "*", "/", "%", "**", ".", "!"})
#: Keywords that stand as an operand of a chain (`новый`, `этот`, the literals) rather than end it.
_OPERAND_KEYWORDS = frozenset({"NEW", "THIS", "TRUE", "FALSE", "UNDEFINED"})
_OPENERS = frozenset({"(", "[", "{"})
_CLOSERS = frozenset({")", "]", "}"})


def _group_start(toks: list[Token], close: int) -> int | None:
    """The index of the opener matching the closer at `close`, or None when there is none."""
    depth = 0
    for j in range(close, -1, -1):
        if _is_op(toks[j], *_CLOSERS):
            depth += 1
        elif _is_op(toks[j], *_OPENERS):
            depth -= 1
            if depth == 0:
                return j
    return None


def _receiver_start(toks: list[Token], end: int) -> int | None:
    """The first token of the value a member call is made on; `end` is the token before the dot.

    Walked back link by link: a call or an index takes its `(...)`/`[...]` group and the name
    before it, a dot takes the previous link, a postfix `!` takes the value it follows, a
    constructor takes its `новый`. A bracketed group with no name before it is a parenthesized
    expression, and the receiver starts at the bracket. A link reached through the safe access
    `?.` is not joined, so such a receiver is left alone. None when the tokens do not form a
    chain at all.
    """
    i = end
    while i >= 0:
        tok = toks[i]
        if _is_op(tok, "!"):
            i -= 1  # `Значение!` is the value itself, asserted to be defined
            continue
        if _is_op(tok, ")", "]"):
            opener = _group_start(toks, i)
            if opener is None:
                return None
            before = toks[opener - 1] if opener > 0 else None
            if before is not None and (before.kind == "IDENT" or _is_op(before, ")", "]")):
                i = opener - 1  # `Имя(...)`, `Имя[...]`, `Имя()[...]`: the name is a link
                continue
            return opener
        if tok.kind == "IDENT":
            if i > 0 and _is_op(toks[i - 1], "."):
                i -= 2
                continue
            if i > 0 and toks[i - 1].kind == "KEYWORD" and toks[i - 1].canonical == "NEW":
                return i - 1
            return i
        if tok.kind in ("STRING", "NUMBER") or (
            tok.kind == "KEYWORD" and tok.canonical in _OPERAND_KEYWORDS
        ):
            return i
        return None
    return None


def _string_before(toks: list[Token], plus: int) -> bool:
    """Whether a string literal stands among the operands to the left of the `+` at `plus`.

    The walk stays in one chain at one bracket depth: a bracketed group is skipped whole (a
    literal inside a call's arguments does not make the call's result a string), and the first
    token that cannot belong to a chain - an unmatched opener, an operator outside the chain
    set, a keyword of a statement - ends it.
    """
    depth = 0
    for j in range(plus - 1, -1, -1):
        tok = toks[j]
        if tok.kind == "OP":
            if tok.value in _CLOSERS:
                depth += 1
            elif tok.value in _OPENERS:
                if depth == 0:
                    return False
                depth -= 1
            elif depth == 0 and tok.value not in _CHAIN_OPS:
                return False
        elif depth == 0:
            if tok.kind == "STRING":
                return True
            if tok.kind == "KEYWORD" and tok.canonical not in _OPERAND_KEYWORDS:
                return False
    return False


@rule("style/redundant-tostring", "style/redundant-tostring.title", "C",
      severity=Severity.WARNING)
def redundant_tostring(source: SourceFile) -> Iterable[Diagnostic]:
    """5.1: `Текст + Счетчик`, not `Текст + Счетчик.ВСтроку()` – the conversion is implicit.

    The call is redundant only where the platform performs it anyway. The addition table of
    the documentation lists one form with a string, `Строка + Объект`, whose right operand is
    converted with the parameterless `ВСтроку()`; there is no `Число + Строка`. So the rule
    reports a call whose result is the right operand of a `+` at its own bracket depth with a
    string literal among the operands to its left - `"a" + X.ВСтроку()`, `"a" + Y + X.ВСтроку()`,
    `"w:" + (A + B).ВСтроку() + "px"` (the chain is left-associative, so the value the last `+`
    adds to is a string already). What stays quiet: a number first, `X.ВСтроку() + "px"` or
    `(A + B).ВСтроку() + "px"`, is an addition the language does not define without the call,
    and a `+` inside the receiver's own brackets is not a concatenation of the result; a call
    passed as an argument, `Ф(X.ВСтроку())`, is not an operand of a `+` at all; a call with an
    argument, or one followed by a member of its own (`X.ВСтроку().Длина`), is not the implicit
    conversion. A string VARIABLE on the left cannot be told from a number by tokens, so the
    rule judges by a literal alone - a narrowing rather than a guess.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    names = _tostring_names()
    for i, tok in enumerate(toks):
        if not (
            0 < i and i + 3 < len(toks)
            and _is_op(tok, ".")
            and toks[i + 1].kind == "IDENT" and toks[i + 1].value in names
            and _is_op(toks[i + 2], "(") and _is_op(toks[i + 3], ")")
        ):
            continue
        if i + 4 < len(toks) and _is_op(toks[i + 4], ".", "["):
            continue  # a link of a longer chain, not the operand of a `+`
        start = _receiver_start(toks, i - 1)
        if start is None or start == 0 or not _is_op(toks[start - 1], "+"):
            continue
        if not _string_before(toks, start - 1):
            continue
        yield Diagnostic(
            source.rel, toks[i + 1].line, toks[i + 1].col,
            "style/redundant-tostring", Severity.WARNING,
            i18n.t("style/redundant-tostring.concat"),
        )


@rule("style/interpolation", "style/interpolation.title", "C",
      severity=Severity.WARNING)
def interpolation(source: SourceFile) -> Iterable[Diagnostic]:
    """5.2: `"Итерация №%Счетчик"` instead of `"Итерация №" + Счетчик`.

    We report only the joining of a string literal with a value: `"a" + "b"` is a wrap of
    long text, not a substitution, and the rule leaves it alone. A whole concatenation
    chain gets one message: `"a" + X + "b" + Y` is rewritten as a single interpolation.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    reported = [False]  # one flag per level of bracket depth

    for i, tok in enumerate(toks):
        if _is_op(tok, "(", "[", "{"):
            reported.append(False)
            continue
        if _is_op(tok, ")", "]", "}"):
            if len(reported) > 1:
                reported.pop()
            continue
        if _is_op(tok, ",", ";", "="):  # a new operand/statement – a new chain
            reported[-1] = False
            continue
        if not _is_op(tok, "+") or i == 0 or i + 1 >= len(toks) or reported[-1]:
            continue

        left, right = toks[i - 1], toks[i + 1]
        left_str, right_str = left.kind == "STRING", right.kind == "STRING"
        if left_str == right_str:
            continue  # both literals (wrapped text) or neither (not about strings)
        value = right if left_str else left
        if value.kind not in ("IDENT", "NUMBER") and not _is_op(value, ")"):
            continue
        reported[-1] = True
        yield Diagnostic(
            source.rel, tok.line, tok.col, "style/interpolation", Severity.WARNING,
            i18n.t("style/interpolation.concat"),
        )
