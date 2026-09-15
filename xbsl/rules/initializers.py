"""Tier C: a declaration's initializer the compiler demands or refuses.

Two rules read declarations alone and need nothing beyond the file. Each finding is a compile
error: the server refuses the build and the stand keeps running the previous one. The forms and
their controls were probed against the IDE language server.

`code/required-field-default` - a structure or exception field marked `обз` that also carries a
default value (`обз пер Номер: Число = 5`). A required field is always passed to the constructor,
the default could never be used, and the compiler refuses the declaration rather than ignore it.
The keyword order does not matter (`пер обз ...` is the same field). The fix removes `= ...` only when the field declares its type explicitly - the
constructor supplies the value either way and the field retains its type.

`code/declaration-needs-init` - a declaration that has to be initialized and is not:

- a local `пер` or `знч` whose written type is a union of two or more different types with no
  empty member (`пер Смесь: Число|Строка`) - such a type has no default value; the same union
  written with `?` or `Undefined`, or a union that repeats one type (`Строка|Строка`), has one;
- a structure or exception field of such a type that is not `обз` - nothing would build its
  value either;
- a `исп` variable declared by type alone (`исп Поток: ПотокЧтения`) - the resource has to be
  opened right in the declaration;
- a module constant without a value (`конст ПУСТАЯ: Число`).

Types are told apart by their text, both spellings of a platform name meeting in one form; a
union with the unknown type, and a declaration whose type is a single name, are left to
`code/var-needs-init` and the compiler: a single type may well have a default value.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Iterator
from functools import cache, lru_cache

from xbsl import dataset, i18n, terms
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules._recovery import healthy_module
from xbsl.typeinfer import canonical_name

MESSAGES = {
    "code/required-field-default.title": {
        "ru": "Обязательное поле со значением по умолчанию",
        "en": "Required field with a default value",
    },
    "code/required-field-default.found": {
        "ru": "Поле '{name}' объявлено через 'обз': его значение всегда передаётся в "
              "конструктор, и значение по умолчанию не используется – компилятор такое "
              "объявление отвергает. Уберите значение по умолчанию либо снимите 'обз'.",
        "en": "Field '{name}' is declared with '{n[обз]}': its value is always passed to the "
              "constructor and the default value is never used - the compiler rejects such a "
              "declaration. Remove the default value or drop '{n[обз]}'.",
    },
    "code/declaration-needs-init.title": {
        "ru": "Объявление без обязательного значения",
        "en": "Declaration without a required value",
    },
    "code/declaration-needs-init.union": {
        "ru": "Переменная '{name}' составного типа '{type}' объявлена без значения: у такого "
              "типа нет значения по умолчанию, и компилятор объявление отвергает. Задайте "
              "значение либо добавьте в тип '?'.",
        "en": "Variable '{name}' of the union type '{type}' is declared without a value: such a "
              "type has no default value, and the compiler rejects the declaration. Give it a "
              "value or add '?' to the type.",
    },
    "code/declaration-needs-init.field": {
        "ru": "Поле '{name}' составного типа '{type}' не 'обз' и не имеет значения по "
              "умолчанию: построить его значение нечем, и компилятор объявление отвергает. "
              "Задайте значение, пометьте поле 'обз' либо добавьте в тип '?'.",
        "en": "Field '{name}' of the union type '{type}' is not '{n[обз]}' and has no default "
              "value: nothing can build its value, and the compiler rejects the declaration. "
              "Give it a value, mark the field '{n[обз]}' or add '?' to the type.",
    },
    "code/declaration-needs-init.use": {
        "ru": "Переменная '{name}' объявлена через 'исп' без значения: ресурс открывается в "
              "самом объявлении, и компилятор без него объявление отвергает – "
              "'исп {name} = <выражение>'.",
        "en": "Variable '{name}' is declared with '{n[исп]}' without a value: the resource is "
              "opened in the declaration itself, and the compiler rejects it without one - "
              "'{n[исп]} {name} = <expression>'.",
    },
    "code/declaration-needs-init.const": {
        "ru": "Константа '{name}' объявлена без значения: значение константы задаётся при "
              "объявлении, и компилятор без него объявление отвергает.",
        "en": "Constant '{name}' is declared without a value: a constant gets its value in the "
              "declaration, and the compiler rejects it without one.",
    },
}
i18n.register(MESSAGES)

_EQUALS_BEFORE = re.compile(r"\s*=\s*\Z")
_TYPE_WORD = re.compile(r"[^\W\d]\w*(?:\.[^\W\d]\w*)*")


# --- code/required-field-default ---------------------------------------------------------


def _fields(module: P.Module) -> Iterator[P.ObjectField]:
    for member in module.members:
        if isinstance(member, P.Structure):
            yield from (m for m in member.members if isinstance(m, P.ObjectField))


def _default_removal(text: str, field: P.ObjectField) -> TextEdit | None:
    """` = <value>` after the type or the name, when nothing but that stands between them."""
    init = field.init
    if init is None or field.type is None:
        return None  # removing an inferred field's value would also erase its type
    head_end = field.type.end
    if not _EQUALS_BEFORE.fullmatch(text[head_end:init.start]):
        return None
    return TextEdit(head_end, init.end, "")


@rule("code/required-field-default", "code/required-field-default.title", "C",
      severity=Severity.ERROR)
def required_field_default(source: SourceFile) -> Iterable[Diagnostic]:
    """A required field with a default value - the compiler rejects the declaration."""
    if source.kind != "xbsl":
        return
    module = healthy_module(source)
    lm = linemap(source)
    for field in _fields(module):
        if not field.required or field.init is None:
            continue
        line, col = lm.linecol(field.init.start)
        yield Diagnostic(
            source.rel, line, col, "code/required-field-default", Severity.ERROR,
            i18n.t("code/required-field-default.found", name=field.name),
            fix=_default_removal(source.text, field),
        )


# --- code/declaration-needs-init ---------------------------------------------------------


@lru_cache(maxsize=1)
def _keyword_forms() -> tuple[frozenset[str], frozenset[str]]:
    """Both spellings of the empty value and of the unknown type."""
    keywords = dataset.load_json("language.json")["keywords"]
    empty = frozenset(terms.forms("Неопределено", "types"))
    empty |= frozenset(keywords["UNDEFINED"]["forms"])
    return empty, frozenset(keywords["UNKNOWN"]["forms"])


dataset.register_reset(_keyword_forms.cache_clear)


def _alternatives(text: str) -> list[str]:
    """The members of a written union, split at `|` outside angle brackets and parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in "<(":
            depth += 1
        elif char in ">)":
            depth -= 1
        if char == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts]


def _canonical(member: str) -> str:
    """A union member with every type name in one spelling, so both spellings compare equal."""
    return _TYPE_WORD.sub(lambda m: canonical_name(m.group(0)) or m.group(0), member)


def _union_without_default(written: P.TypeRef | None) -> bool:
    """Whether a written type is a union of different types with no empty member."""
    if written is None or written.nullable or "|" not in written.text:
        return False
    empty, unknown = _keyword_forms()
    members = _alternatives(written.text)
    if any(not m or m.endswith("?") or m in empty or m in unknown for m in members):
        return False
    return len({_canonical(m) for m in members}) >= 2


def _local_declarations(module: P.Module) -> Iterator[P.VarDecl]:
    """Every local declaration of the file, lambda bodies included."""
    stack: list[object] = [module]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, P.VarDecl):
            yield node
            stack.append(node.init)
        elif isinstance(node, P.Node) and not isinstance(node, (P.TypeRef, P.Literal)):
            stack.extend(getattr(node, name) for name in _node_fields(type(node)))


@cache
def _node_fields(cls: type) -> tuple[str, ...]:
    """Field names of a node class; declared ones, as the compiled parser has no `__dict__`."""
    return tuple(f.name for f in dataclasses.fields(cls))


@rule("code/declaration-needs-init", "code/declaration-needs-init.title", "C",
      severity=Severity.ERROR)
def declaration_needs_init(source: SourceFile) -> Iterable[Diagnostic]:
    """A declaration the compiler cannot give a value to - an initializer is required."""
    if source.kind != "xbsl":
        return
    module = healthy_module(source)
    found: list[tuple[int, str, dict[str, str]]] = []
    for member in module.members:
        if isinstance(member, P.ObjectField) and member.kind == "CONST" and member.init is None:
            found.append((member.start, "const", {"name": member.name}))
    for field in _fields(module):
        if field.init is None and not field.required and _union_without_default(field.type):
            assert field.type is not None
            found.append((field.start, "field", {"name": field.name,
                                                 "type": field.type.text}))
    for decl in _local_declarations(module):
        if decl.init is not None:
            continue
        if decl.kind == "USE":
            found.append((decl.start, "use", {"name": decl.name}))
        elif _union_without_default(decl.type):
            assert decl.type is not None
            found.append((decl.start, "union", {"name": decl.name,
                                                "type": decl.type.text}))
    if not found:
        return
    lm = linemap(source)
    for start, key, fields in sorted(found, key=lambda item: item[0]):
        line, col = lm.linecol(start)
        yield Diagnostic(source.rel, line, col, "code/declaration-needs-init", Severity.ERROR,
                         i18n.t(f"code/declaration-needs-init.{key}", **fields))
