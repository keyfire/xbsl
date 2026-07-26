"""Reference types must not rely on a default value – the code side and the yaml side.

A reference type has no default value on the platform, so every position that needs one
must say so explicitly. Two rules of the same family live here:

- code/ref-field-needs-req (tier C) – a structure field in a module;
- yaml/ref-needs-nullable (tier A) – a `Тип` value in a yaml description.

The code side. A structure field whose type is a project-object
reference (`Программа.Ссылка`, `Справочник.Товары.Ссылка` – the last segment of the dotted
chain is `Ссылка`) has no default value on the platform, so the server-side apply fails with
"cannot be initialized with a default value". The correct forms are:

- `обз пер Ссылка: Программа.Ссылка` – the field is required in the constructor;
- `пер Ссылка: Программа.Ссылка?` – a nullable type has the default `Неопределено`;
- `пер Ссылка: Программа.Ссылка = <выражение>` – an explicit initializer.

Detection is token-based: inside a `структура ... ;` block (nesting-aware – fields are taken
only at the top level of the structure body, not inside its methods or constructors) every
`пер`/`знч` declaration is checked; a declaration is flagged when its type annotation is a
plain dotted chain ending in `Ссылка`, with no `?`, no `= ...` initializer and no `обз`
before the declaration keyword.

Deliberate narrowings (skip rather than guess – no false positives):

- union types (`А.Ссылка|Б.Ссылка`, `А.Ссылка|?`) are skipped: the platform's defaulting
  rules for unions are not encoded here, and a `|?` union is nullable anyway;
- generics (`Массив<Программа.Ссылка>`) are skipped: the field itself is a collection, not
  a direct reference, and collections have default values;
- a bare `Ссылка` (a one-segment chain) is skipped: it is a local type name, not a
  project-object reference;
- an alternative that is not a plain IDENT(.IDENT)* chain is skipped.

The yaml side (yaml/ref-needs-nullable). The same reference type in a `Тип` value – an
object attribute, a component property, a structure field or an input field
`ПолеВвода<Товары.Ссылка>` – is rejected by the compiler for the same reason, in four
positions and both flavours of the message:

    СпрРеквизитБезЗнака.yaml  [9:14]  Default value initialization is not supported for
                                      type СпрЦель.Ссылка
    ФормаСвойствоБезЗнака.yaml [15:14] (the same, a component property)
    ФормаПолеБезЗнака.yaml    [13:17] Parameter "ТипДанных" of type
                                      "ПолеВвода<СпрЦель.Ссылка>" must have a default value
    СпрСтдСсылка.yaml         [9:14]  ... for type ДвоичныйОбъект.Ссылка

The nullable counterparts of all four applied cleanly, so the marker is what the compiler
is after. A stdlib reference (`ДвоичныйОбъект.Ссылка`) behaves exactly like a project one –
hence the rule needs no project knowledge and stays file-scoped (tier A, instant in the
editor). Positions match the compiler's on the attribute and the property; on the input
field the compiler points at the component node while the rule points at the argument
inside the value – the place to actually edit.

Narrowing mirrors the code side – exactly two shapes are flagged, a bare chain and
`ПолеВвода<chain>` with a single bare argument. Other generics are left alone, and
`Массив<Товары.Ссылка>` is not merely unproven but legal: the same probe applied it without
a complaint (a collection has its own default – the empty collection). Unions and qualified
`Поставщик::Проект::Объект.Ссылка` names are skipped as well.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import Token
from xbsl.rules._syntax import code_tokens, type_expr
from xbsl.rules.code_structure import _OPENERS
from xbsl.rules.yaml_schema import (
    _composed,
    _HAVE_YAML,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
)

if _HAVE_YAML:
    import yaml

MESSAGES = {
    "code/ref-field-needs-req.title": {
        "ru": "Поле-ссылка структуры без 'обз'",
        "en": "Structure reference field without 'обз'",
    },
    "code/ref-field-needs-req.missing": {
        "ru": "Поле структуры '{name}' имеет ссылочный тип '{type}' без 'обз', '?' и "
              "инициализатора – применение сборки падает с 'cannot be initialized with "
              "a default value'. Правильно: 'обз {kw} {name}: {type}'.",
        "en": "Structure field '{name}' has the reference type '{type}' without 'обз', '?' "
              "or an initializer – applying the build fails with 'cannot be initialized "
              "with a default value'. Correct: 'обз {kw} {name}: {type}'.",
    },
    "yaml/ref-needs-nullable.title": {
        "ru": "Ссылочный тип без nullable",
        "en": "Reference type without nullable",
    },
    "yaml/ref-needs-nullable.bare": {
        "ru": "Тип '{name}' – ссылка без '?': значения по умолчанию у ссылки нет, серверная "
              "компиляция упадёт с 'Default value initialization is not supported'. "
              "Укажите '{name}?'.",
        "en": "Type '{name}' – a reference without '?': a reference has no default value, the "
              "server-side compilation will fail with 'Default value initialization is not "
              "supported'. Use '{name}?'.",
    },
    "yaml/ref-needs-nullable.input": {
        "ru": "Тип '{field}<{name}>' – аргумент-ссылка без '?': значения по умолчанию нет, "
              "серверная компиляция упадёт с 'Parameter \"ТипДанных\" ... must have a default "
              "value'. Укажите '{field}<{name}?>'.",
        "en": "Type '{field}<{name}>' – a reference argument without '?': there is no default "
              "value, the server-side compilation will fail with 'Parameter \"ТипДанных\" ... "
              "must have a default value'. Use '{field}<{name}?>'.",
    },
}
i18n.register(MESSAGES)

#: A plain dotted chain of at least two segments ending in `Ссылка` – the reference shape.
_YAML_REF_RE = re.compile(
    r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*"
    r"(?:\.[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)*\.Ссылка"
)
_YAML_BARE_RE = re.compile(rf"^\s*({_YAML_REF_RE.pattern})\s*$")
_YAML_INPUT_RE = re.compile(rf"^\s*(ПолеВвода|Edit)\s*<\s*({_YAML_REF_RE.pattern})\s*>\s*$")

_FIELD_KEYWORDS = ("VAR", "VAL")


def _structure_field_decls(toks: list[Token]) -> list[tuple[int, bool]]:
    """Indices of `пер`/`знч` keywords at the top level of structure bodies.

    Returns (index, has_req) pairs; has_req – the declaration is preceded by `обз`.
    Block tracking mirrors code_structure: a lowercase opener keyword pushes a block,
    `;` pops one; `иначе если` on one line continues the same `если` block. Query-block
    contents and comments are already stripped by code_tokens, so a `;` inside a query
    cannot break the balance.
    """
    out: list[tuple[int, bool]] = []
    stack: list[str] = []
    prev: Token | None = None
    for i, t in enumerate(toks):
        if t.kind == "KEYWORD" and t.canonical in _OPENERS and t.value[:1].islower():
            is_else_if = (
                t.canonical == "IF"
                and prev is not None
                and prev.kind == "KEYWORD"
                and prev.canonical == "ELSE"
                and prev.line == t.line
            )
            if not is_else_if:
                stack.append(t.canonical)
        elif t.kind == "OP" and t.value == ";":
            if stack:
                stack.pop()
        elif (
            t.kind == "KEYWORD"
            and t.canonical in _FIELD_KEYWORDS
            and t.value[:1].islower()
            and stack
            and stack[-1] == "STRUCTURE"
        ):
            has_req = prev is not None and prev.kind == "KEYWORD" and prev.canonical == "REQ"
            out.append((i, has_req))
        prev = t
    return out


def _decl_names(toks: list[Token], start: int) -> tuple[list[Token], int]:
    """The name tokens of a declaration (`Имя` or `Имя1, Имя2`) and the index past them."""
    names: list[Token] = []
    j, n = start, len(toks)
    while j < n and toks[j].kind == "IDENT":
        names.append(toks[j])
        k = j + 1
        if k < n and toks[k].kind == "OP" and toks[k].value == ",":
            j = k + 1
            continue
        return names, k
    return names, j


def _plain_ref_chain(alt: list[Token]) -> list[Token] | None:
    """The IDENT tokens of a plain dotted chain ending in `Ссылка`, else None.

    The alternative must strictly alternate IDENT and '.', have at least two segments
    and no other tokens (`?`, `<...>`, `Неопределено` – not a plain reference chain).
    """
    idents: list[Token] = []
    expect_ident = True
    for t in alt:
        if expect_ident:
            if t.kind != "IDENT":
                return None
            idents.append(t)
        elif not (t.kind == "OP" and t.value == "."):
            return None
        expect_ident = not expect_ident
    if expect_ident or len(idents) < 2 or idents[-1].value != "Ссылка":
        return None
    return idents


@rule(
    "code/ref-field-needs-req", "code/ref-field-needs-req.title", "C",
    severity=Severity.ERROR,
)
def ref_field_needs_req(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return []
    toks = code_tokens(source)
    n = len(toks)
    diags: list[Diagnostic] = []

    for i, has_req in _structure_field_decls(toks):
        if has_req:
            continue
        names, j = _decl_names(toks, i + 1)
        if not names or j >= n or not (toks[j].kind == "OP" and toks[j].value == ":"):
            continue
        te = type_expr(toks, j + 1)
        if te is None or len(te.alternatives) != 1:
            continue  # no type, or a union – skip (see the module docstring)
        if te.end < n and toks[te.end].kind == "OP" and toks[te.end].value == "=":
            continue  # an explicit initializer
        chain = _plain_ref_chain(te.alternatives[0])
        if chain is None:
            continue
        type_text = ".".join(t.value for t in chain)
        for name in names:
            diags.append(Diagnostic(
                source.rel, name.line, name.col, "code/ref-field-needs-req",
                Severity.ERROR,
                i18n.t(
                    "code/ref-field-needs-req.missing",
                    name=name.value, type=type_text, kw=toks[i].value,
                ),
            ))
    return diags


def _yaml_ref_shape(value: str) -> tuple[str, int, str, str] | None:
    """(reference type, offset within the value, message key, input-field spelling) or None.

    Exactly two shapes qualify: a bare chain and ПолеВвода<chain> with a bare argument. The
    component is taken as the FILE spells it - the platform reads a form written in English
    the same way, and advising `ПолеВвода` there would send the author looking for a key that
    must not be in their sources.
    """
    m = _YAML_BARE_RE.match(value)
    if m:
        return m.group(1), m.start(1), "yaml/ref-needs-nullable.bare", ""
    m = _YAML_INPUT_RE.match(value)
    if m:
        return m.group(2), m.start(2), "yaml/ref-needs-nullable.input", m.group(1)
    return None


@rule("yaml/ref-needs-nullable", "yaml/ref-needs-nullable.title", "A", severity=Severity.ERROR)
def yaml_ref_needs_nullable(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML or ".Ссылка" not in source.text:
        return  # the fast path: composing the graph is a second parse of the file
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return  # structural files (Проект/Подсистема/Ресурсы) carry no types
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return
    for mapping in _mapping_nodes(root):
        entry = _scalar_entries(mapping).get("Тип")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        value_node = entry[1]
        if value_node.style in ("|", ">"):  # a block scalar is text, not a type
            continue
        hit = _yaml_ref_shape(value_node.value)
        if hit is None:
            continue
        name, offset, msg_key, field = hit
        quote = 1 if value_node.style in ("'", '"') else 0
        yield Diagnostic(
            source.rel,
            value_node.start_mark.line + 1,
            value_node.start_mark.column + 1 + offset + quote,
            "yaml/ref-needs-nullable", Severity.ERROR,
            i18n.t(msg_key, name=name, field=field),
        )
