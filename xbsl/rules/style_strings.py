"""Collections and strings (CODE_STYLE, sections 4 and 5).

- 4.1 a collection literal is preferred over filling one by hand;
- 5.1 rely on the implicit conversion rather than on `.ВСтроку()`;
- 5.2 interpolation is preferred over concatenation.

All three rules describe debt in the existing code (hundreds of places), so they are `info`
and off by default – enable them with `--select`.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
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


def _tokens_by_line(toks: list[Token]) -> dict[int, list[Token]]:
    by_line: dict[int, list[Token]] = {}
    for tok in toks:
        by_line.setdefault(tok.line, []).append(tok)
    return by_line


@rule("style/redundant-tostring", "style/redundant-tostring.title", "C",
      severity=Severity.WARNING)
def redundant_tostring(source: SourceFile) -> Iterable[Diagnostic]:
    """5.1: `"Итерация №" + Счетчик`, not `... + Счетчик.ВСтроку()` – the conversion is implicit."""
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    by_line = _tokens_by_line(toks)

    for i, tok in enumerate(toks[:-2]):
        if not (_is_op(tok, ".") and toks[i + 1].kind == "IDENT" and toks[i + 1].value == _TOSTRING):
            continue
        if not _is_op(toks[i + 2], "("):
            continue
        line_toks = by_line.get(tok.line, [])
        has_plus = any(_is_op(t, "+") for t in line_toks)
        has_string = any(t.kind == "STRING" for t in line_toks)
        if has_plus and has_string:
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
