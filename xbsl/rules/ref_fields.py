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

Unions are judged too – a second probe (2026-08-13) showed the compiler rejects a union
that carries a reference member and has no nullable member, and a MIXED union fails the
same way (a value-typed member does not provide the default):

    Пробы.yaml      [15] Default value initialization is not supported for types
                         "ЦелиДругие.Ссылка|ЦелиОдни.Ссылка". Explicitly specify a value or
                         add it to the set of types "Неопределено"
    Пробы.yaml      [23] (the same for "Строка|ЦелиОдни.Ссылка" – a mixed union)
    ФормаПробы.yaml [10] Parameter "ТипДанных" of type
                         "ПолеВвода<ЦелиДругие.Ссылка|ЦелиОдни.Ссылка>" must have a
                         default value

The `...|?` counterparts of both applied cleanly in the same run. A union is nullable when
any alternative is `?`, the `Undefined` literal (either spelling) or ends with `?` (a
nullable member injects the empty value into the whole set) – such unions are skipped. A
union whose every alternative is a plain chain but none is a reference is left alone: the
probe has not established whether a reference-free union defaults, and silence is the safe
side.

Other narrowing mirrors the code side – other generics are left alone, and
`Массив<Товары.Ссылка>` is not merely unproven but legal: the same probe applied it without
a complaint (a collection has its own default – the empty collection). A union with a
generic or a qualified `Поставщик::Проект::Объект.Ссылка` member is skipped as a whole. On
the CODE side (structure fields) unions stay skipped: the probe covered the yaml positions
only.
"""

from __future__ import annotations

import re
from functools import lru_cache
from collections.abc import Iterable

from xbsl import dataset, i18n, terms
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
    "yaml/ref-needs-nullable.union": {
        "ru": "Тип '{name}' – союз со ссылкой и без пустого значения: значения по умолчанию у "
              "такого союза нет, серверная компиляция упадёт с 'Default value initialization "
              "is not supported for types ...'. Добавьте пустое значение в состав: '{name}|?'.",
        "en": "Type '{name}' – a union with a reference member and no empty value: such a union "
              "has no default value, the server-side compilation will fail with 'Default value "
              "initialization is not supported for types ...'. Add the empty value to the set: "
              "'{name}|?'.",
    },
    "yaml/ref-needs-nullable.input-union": {
        "ru": "Тип '{field}<{name}>' – союз-аргумент со ссылкой и без пустого значения: значения "
              "по умолчанию нет, серверная компиляция упадёт с 'Parameter \"ТипДанных\" ... must "
              "have a default value'. Укажите '{field}<{name}|?>'.",
        "en": "Type '{field}<{name}>' – a union argument with a reference member and no empty "
              "value: there is no default value, the server-side compilation will fail with "
              "'Parameter \"ТипДанных\" ... must have a default value'. Use '{field}<{name}|?>'.",
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
#: An input field with ANY argument – the union check parses the inside itself.
_YAML_INPUT_ANY_RE = re.compile(r"^\s*(ПолеВвода|Edit)\s*<\s*(.+?)\s*>\s*$")
#: A union alternative the rule understands: a plain dotted chain, optionally nullable.
_YAML_UNION_ALT_RE = re.compile(
    r"^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*"
    r"(?:\.[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)*\??$"
)
#: Alternatives that inject the empty value into the union by themselves.
_NULLABLE_ALTS = frozenset({"?", "Неопределено", "Undefined"})

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


def structure_field_decls(source: SourceFile) -> list[tuple[int, bool]]:
    """_structure_field_decls over the source's tokens, cached per file.

    Three rules of the "no default value" family walk the same fields (the reference one
    here, the collection and the variable ones in type_defaults); without the cache the
    block-tracking pass repeated once per rule on every module.
    """
    cached = source.cache.get("structure_field_decls")
    if cached is None:
        cached = _structure_field_decls(code_tokens(source))
        source.cache["structure_field_decls"] = cached
    return cached


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
    if expect_ident or len(idents) < 2 or idents[-1].value not in _reference_facets():
        return None
    return idents


_REFERENCE_FACET = "Ссылка"


@lru_cache(maxsize=1)
def _reference_facets() -> frozenset[str]:
    """Both spellings of the reference facet, from the platform dictionary - a translated
    module spells the chain with the English facet, and the Russian word alone went blind
    there."""
    return frozenset(
        name for name in (_REFERENCE_FACET, terms.facet_suffix_english(_REFERENCE_FACET))
        if name
    )


dataset.register_reset(_reference_facets.cache_clear)


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

    for i, has_req in structure_field_decls(source):
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


def _union_needs_nullable(text: str) -> bool:
    """A union of plain chains with a reference member and no nullable member.

    Any alternative that is `?`, the `Undefined` literal (either spelling) or ends with `?`
    makes the whole union nullable – skipped. Any alternative outside the plain-chain shape
    (a generic, a qualified name) makes the union something the rule does not judge –
    skipped too.
    """
    if "|" not in text:
        return False
    has_ref = False
    for alt in (a.strip() for a in text.split("|")):
        if alt in _NULLABLE_ALTS or alt.endswith("?"):
            return False
        if not _YAML_UNION_ALT_RE.match(alt):
            return False
        if _YAML_REF_RE.fullmatch(alt):
            has_ref = True
    return has_ref


def _yaml_ref_shape(value: str) -> tuple[str, int, str, str] | None:
    """(reference type, offset within the value, message key, input-field spelling) or None.

    Four shapes qualify: a bare chain, a bare union, and the input-field component around
    either. The component is taken as the FILE spells it - the platform reads a form written
    in English the same way, and advising the Russian spelling there would send the author
    looking for a key that must not be in their sources.
    """
    m = _YAML_BARE_RE.match(value)
    if m:
        return m.group(1), m.start(1), "yaml/ref-needs-nullable.bare", ""
    m = _YAML_INPUT_RE.match(value)
    if m:
        return m.group(2), m.start(2), "yaml/ref-needs-nullable.input", m.group(1)
    m = _YAML_INPUT_ANY_RE.match(value)
    if m:
        if _union_needs_nullable(m.group(2)):
            return m.group(2), m.start(2), "yaml/ref-needs-nullable.input-union", m.group(1)
        return None
    stripped = value.strip()
    if _union_needs_nullable(stripped):
        offset = len(value) - len(value.lstrip())
        return stripped, offset, "yaml/ref-needs-nullable.union", ""
    return None


#: The truthy spellings a yaml boolean takes: the platform's own literal and what yaml itself
#: reads as true.
_TRUE_VALUES = frozenset({"Истина", "True", "true"})


#: The section of parameters, both spellings.
_PARAMETER_KEYS = frozenset(terms.key_forms("Параметры"))


def _parameter_mappings(root) -> set[int]:
    """Ids of the mappings that describe a PARAMETER (the `Parameters` section of an element).

    A parameter has no initialization to begin with: its value arrives from whoever raises the
    event or calls the method, so the compiler asks for no default and a reference type needs no
    `?` there. The reference corpus declares exactly that - a global client event with a
    `ПрайсЛисты.Ссылка` parameter - and the server compiles it.
    """
    out: set[int] = set()
    for mapping in _mapping_nodes(root):
        for key_node, value_node in mapping.value:
            if not isinstance(key_node, yaml.ScalarNode):
                continue
            if key_node.value not in _PARAMETER_KEYS:
                continue
            for item in getattr(value_node, "value", ()) or ():
                if isinstance(item, yaml.MappingNode):
                    out.add(id(item))
    return out


def _is_required(entries: dict) -> bool:
    """Is this mapping a field marked `Обязательное: Истина`?"""
    entry = entries.get("Обязательное")
    if entry is None or not isinstance(entry[1], yaml.ScalarNode):
        return False
    return entry[1].value.strip().strip("'\"") in _TRUE_VALUES


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
    parameters = _parameter_mappings(root)
    for mapping in _mapping_nodes(root):
        if id(mapping) in parameters:
            continue
        entries = _scalar_entries(mapping)
        entry = entries.get("Тип")
        if entry is None or not isinstance(entry[1], yaml.ScalarNode):
            continue
        if _is_required(entries):
            # A required field of a structure needs no default: the documentation of the
            # structure element states that such a field becomes a mandatory parameter of the
            # constructor even when it has an implicit initialization value - so the value
            # comes from the caller and the compiler asks for nothing.
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
