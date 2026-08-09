"""Types, initialization and signatures (CODE_STYLE, sections 3 and 7).

- 3.1 a type is set off by a colon with a space after it;
- 3.2 no spaces around `|` in a union type;
- 3.3 `Неопределено` in a type is written with the `?` shorthand;
- 3.4 on initialization by a literal or a constructor the type is omitted;
- 7.1 optional parameters – after the required ones.
"""

from __future__ import annotations

from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import (
    TypeExpr,
    code_tokens,
    declarations,
    signatures,
    type_expr,
)

MESSAGES = {
    "style/type-colon-space.title": {
        "ru": "Пробелы вокруг двоеточия типа",
        "en": "Spaces around the type colon",
    },
    "style/type-colon-space.space-before": {
        "ru": "Пробел перед двоеточием типа – тип отделяется двоеточием сразу после имени.",
        "en": "Space before the type colon – the type is set off by a colon right after the name.",
    },
    "style/type-colon-space.no-space-after": {
        "ru": "Нет пробела после двоеточия типа.",
        "en": "No space after the type colon.",
    },
    "style/union-spaces.title": {
        "ru": "Пробелы вокруг '|' в составном типе",
        "en": "Spaces around '|' in a union type",
    },
    "style/union-spaces.found": {
        "ru": "Пробелы вокруг '|' в составном типе – писать слитно: 'Строка|Число'.",
        "en": "Spaces around '|' in a union type – write it joined: '{n[Строка]}|{n[Число]}'.",
    },
    "style/nullable-shorthand.title": {
        "ru": "{n[Неопределено]} в типе без сокращения '?'",
        "en": "{n[Неопределено]} in a type without the '?' shorthand",
    },
    "style/nullable-shorthand.undefined-word": {
        "ru": "'{n[Неопределено]}' в составном типе – записывается сокращением '?'.",
        "en": "'{n[Неопределено]}' in a union type – write it with the '?' shorthand.",
    },
    "style/nullable-shorthand.two-types": {
        "ru": "Два типа – '?' пишется слитно: '{type}?', не '...|?'.",
        "en": "Two types – '?' is written joined: '{type}?', not '...|?'.",
    },
    "style/nullable-shorthand.many-types": {
        "ru": "Три и более типов – 'Неопределено' отделяется: '...|?', не '...Тип?'.",
        "en": "Three or more types – '{n[Неопределено]}' is set apart: '...|?', not '...{n[Тип]}?'.",
    },
    "style/redundant-type.title": {
        "ru": "Избыточная аннотация типа при инициализации",
        "en": "Redundant type annotation on initialization",
    },
    "style/redundant-type.inferred": {
        "ru": "Тип '{annotation}' выводится из инициализации – аннотацию не писать.",
        "en": "Type '{annotation}' is inferred from the initializer – do not write the annotation.",
    },
    "style/optional-params-last.title": {
        "ru": "Необязательный параметр перед обязательным",
        "en": "Optional parameter before a required one",
    },
    "style/optional-params-last.required-after-optional": {
        "ru": "Обязательный параметр '{name}' после необязательного – "
              "необязательные параметры пишутся последними.",
        "en": "Required parameter '{name}' after an optional one – "
              "optional parameters come last.",
    },
}
i18n.register(MESSAGES)

# Literal -> the type inferred from it without an annotation (3.4).
_LITERAL_TYPE = {"STRING": "Строка", "NUMBER": "Число"}
_BOOLEAN_KEYWORDS = ("TRUE", "FALSE")


def _type_positions(toks: list[Token]) -> list[tuple[Token, int]]:
    """Pairs (colon, index of the first type token) for every type position in the module."""
    out: list[tuple[Token, int]] = []
    for decl in declarations(toks):
        if decl.colon is not None and decl.type_start is not None:
            out.append((decl.colon, decl.type_start))
    for sig in signatures(toks):
        for param in sig.params:
            if param.colon is not None and param.type_start is not None:
                out.append((param.colon, param.type_start))
        if sig.return_colon is not None and sig.return_type_start is not None:
            out.append((sig.return_colon, sig.return_type_start))
    return out


def _type_exprs(toks: list[Token]) -> Iterable[TypeExpr]:
    for _colon, start in _type_positions(toks):
        te = type_expr(toks, start)
        if te is not None:
            yield te


def _text(source: SourceFile, toks: list[Token]) -> str:
    return source.text[toks[0].start: toks[-1].end]


@rule("style/type-colon-space", "style/type-colon-space.title", "C", severity=Severity.WARNING)
def type_colon_space(source: SourceFile) -> Iterable[Diagnostic]:
    """3.1: `пер Переменная: Строка` – no space before `:` and a space after."""
    if source.kind != "xbsl":
        return
    text = source.text
    for colon, _start in _type_positions(code_tokens(source)):
        before = text[colon.start - 1] if colon.start > 0 else ""
        after = text[colon.end] if colon.end < len(text) else ""
        if before in (" ", "\t"):
            yield Diagnostic(
                source.rel, colon.line, colon.col, "style/type-colon-space", Severity.WARNING,
                i18n.t("style/type-colon-space.space-before"),
            )
        if after not in (" ", "\r", "\n", ""):
            yield Diagnostic(
                source.rel, colon.line, colon.col, "style/type-colon-space", Severity.WARNING,
                i18n.t("style/type-colon-space.no-space-after"),
            )


@rule("style/union-spaces", "style/union-spaces.title", "C",
      severity=Severity.WARNING)
def union_spaces(source: SourceFile) -> Iterable[Diagnostic]:
    """3.2: `Строка|Число|Булево`, not `Строка | Число | Булево`."""
    if source.kind != "xbsl":
        return
    text = source.text
    for te in _type_exprs(code_tokens(source)):
        for tok in te.toks:
            if not (tok.kind == "OP" and tok.value == "|"):
                continue
            before = text[tok.start - 1] if tok.start > 0 else ""
            after = text[tok.end] if tok.end < len(text) else ""
            if before in (" ", "\t") or after in (" ", "\t"):
                yield Diagnostic(
                    source.rel, tok.line, tok.col, "style/union-spaces", Severity.WARNING,
                    i18n.t("style/union-spaces.found"),
                )


@rule("style/nullable-shorthand", "style/nullable-shorthand.title", "C",
      severity=Severity.WARNING)
def nullable_shorthand(source: SourceFile) -> Iterable[Diagnostic]:
    """3.3: two types – joined (`Строка?`), three or more – via `|` (`Строка|Число|?`)."""
    if source.kind != "xbsl":
        return
    for te in _type_exprs(code_tokens(source)):
        alts = te.alternatives
        if len(alts) < 2:
            continue

        for alt in alts:
            if len(alt) == 1 and alt[0].kind == "KEYWORD" and alt[0].canonical == "UNDEFINED":
                yield Diagnostic(
                    source.rel, alt[0].line, alt[0].col, "style/nullable-shorthand", Severity.WARNING,
                    i18n.t("style/nullable-shorthand.undefined-word"),
                )

        last = alts[-1]
        first_of_last = last[0]
        if len(alts) == 2 and len(last) == 1 and last[0].kind == "OP" and last[0].value == "?":
            first_type = _text(source, alts[0])
            yield Diagnostic(
                source.rel, first_of_last.line, first_of_last.col,
                "style/nullable-shorthand", Severity.WARNING,
                i18n.t("style/nullable-shorthand.two-types", type=first_type),
            )
        elif len(last) > 1 and last[-1].kind == "OP" and last[-1].value == "?":
            yield Diagnostic(
                source.rel, last[-1].line, last[-1].col,
                "style/nullable-shorthand", Severity.WARNING,
                i18n.t("style/nullable-shorthand.many-types"),
            )


def _typed_empty_array(source: SourceFile, toks, start: int) -> str | None:
    """`<Т>[]` – an empty array literal that names its own element type.

    The platform documents the form in "Идиомы" (`знч Артикулы = <Число>[]`), and it makes the
    annotation redundant exactly like a constructor does: `пер А: Массив<Число> = <Число>[]`
    states the type twice. Only the ARRAY form is recognised - the empty set and map spellings
    are not in the documentation, and guessing at them would risk a false positive on code the
    rule has no evidence about.
    """
    depth = 0
    for i in range(start, len(toks)):
        tok = toks[i]
        if tok.kind != "OP":
            continue
        if tok.value == "<":
            depth += 1
        elif tok.value == ">":
            depth -= 1
            if depth:
                continue
            rest = toks[i + 1:i + 3]
            if len(rest) == 2 and [t.value for t in rest] == ["[", "]"]:
                element = _text(source, toks[start + 1:i])
                return "Массив<%s>" % element
            return None
    return None


@rule("style/redundant-type", "style/redundant-type.title", "C",
      severity=Severity.WARNING)
def redundant_type(source: SourceFile) -> Iterable[Diagnostic]:
    """3.4: on initialization by a literal or a constructor the type is inferred and omitted.

    We report only when the annotation is bound to match the inferred type: a string or a
    number literal against the type `Строка`/`Число`, `Истина`/`Ложь` against `Булево`, the
    constructor `новый Т(...)` against the same `Т`. Empty literals `[]`/`{}` are left alone –
    the type cannot be inferred for them and the annotation is required.
    """
    if source.kind != "xbsl":
        return
    toks = code_tokens(source)
    for decl in declarations(toks):
        if decl.type_start is None or decl.value_start is None:
            continue
        te = type_expr(toks, decl.type_start)
        if te is None or len(te.alternatives) != 1:
            continue
        annotation = _text(source, te.toks)
        if annotation.endswith("?"):  # nullable is wider than the inferred type – annotation needed
            continue

        value = toks[decl.value_start]
        inferred: str | None = None
        if value.kind in _LITERAL_TYPE:
            inferred = _LITERAL_TYPE[value.kind]
        elif value.kind == "KEYWORD" and value.canonical in _BOOLEAN_KEYWORDS:
            inferred = "Булево"
        elif value.kind == "KEYWORD" and value.canonical == "NEW":
            ctor = type_expr(toks, decl.value_start + 1)
            inferred = _text(source, ctor.toks) if ctor is not None else None
        elif value.kind == "OP" and value.value == "<":
            inferred = _typed_empty_array(source, toks, decl.value_start)

        if inferred is None:
            continue
        if annotation.replace(" ", "") != inferred.replace(" ", ""):
            continue
        yield Diagnostic(
            source.rel, decl.colon.line, decl.colon.col, "style/redundant-type", Severity.WARNING,
            i18n.t("style/redundant-type.inferred", annotation=annotation),
        )


@rule("style/optional-params-last", "style/optional-params-last.title", "C",
      severity=Severity.WARNING)
def optional_params_last(source: SourceFile) -> Iterable[Diagnostic]:
    """7.1: parameters with a default value come after the required ones."""
    if source.kind != "xbsl":
        return
    for sig in signatures(code_tokens(source)):
        seen_default = False
        for param in sig.params:
            if param.has_default:
                seen_default = True
            elif seen_default:
                yield Diagnostic(
                    source.rel, param.name.line, param.name.col,
                    "style/optional-params-last", Severity.WARNING,
                    i18n.t("style/optional-params-last.required-after-optional",
                           name=param.name.value),
                )
