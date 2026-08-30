"""Tier D: yaml enumeration defaults against the project enum declarations.

The yaml/enum-default-value rule: `DefaultValue` of a field typed with a PROJECT
enumeration must be the bare name of a declared value. Two failure shapes are reported: the
qualified spelling `ИмяТипа.Значение` - the property is read as a value of the enumeration
itself, so the type prefix does not compile and the build is rejected with
'Неизвестный элемент перечисления' - and a bare name that is not among the enumeration's
`Элементы[].Имя`. Both shapes were confirmed by a server compilation probe (30.08.2026) on a
constants-set constant; the linter used to stay silent and the error surfaced only at apply
time, after a full build.

All `Type` + `DefaultValue` nodes are judged, not constants alone: the metamodel types
the pair identically everywhere. A constants-set constant (`ConstantsSetConstantDescriptor`)
extends the very `RegularAttributeDescriptor` that catalog attributes use, and every
descriptor carrying both keys spells them the same - `Type` a TypeSet reference,
`DefaultValue` an EObject block (the regular, processing and combined attribute
descriptors, field, property and storable-structure-field descriptors, the parameter
descriptors). The two DefaultValue properties typed differently
(ReportControlElementSingleDateSettings holds a date string, ReportControlElementSwitcher a
boolean) carry no `Type` key at all, so the gate never sees them.

Narrowing (deliberate, to keep the zero-false-positive bar):
- only a `Type` that is the bare enumeration name, with or without the nullable marker, is
  judged; unions, generics and namespace-qualified names are left alone - how the compiler
  reads a default there is not proven;
- only string defaults shaped as a bare name or `Имя.Имя` are judged; numbers, booleans and
  any other spelling are skipped;
- a dotted default whose prefix is NOT the field's type name is skipped - only the qualified
  form of the type itself is the proven mistake;
- positions are textual, so a default value string is judged only when every occurrence of
  that string under the default-value key in the file belongs to a judged node of ONE type;
  otherwise the value is skipped in that file (a false negative, never a false positive).

An English tree is read through the same bilingual key canonization (`Type`/`DefaultValue`),
and a Russian value under an English declaration is reported: it names no declared element,
and the server compilation fails on it the same way. The rule is project-wide - it needs the
enumerations of the whole project (it does not run in single-file mode).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.enum_nullable import _typed_nodes
from xbsl.rules.enum_values import _enum_declaration
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind
from xbsl.rules.yaml_types import _key_spellings, _value_positions

MESSAGES = {
    "yaml/enum-default-value.title": {
        "ru": "Значение по умолчанию перечисления",
        "en": "Enumeration default value",
    },
    "yaml/enum-default-value.qualified": {
        "ru": "ЗначениеПоУмолчанию '{value}' – значение перечисления пишется голым именем, "
              "без имени типа: сборка отвергнет запись с точкой "
              "(\"Неизвестный элемент перечисления\"). Укажите '{plain}'.",
        "en": "{n[ЗначениеПоУмолчанию]} '{value}' – an enumeration value is written as the "
              "bare value name, without the type prefix: the build rejects the dotted "
              "spelling. Use '{plain}'.",
    },
    "yaml/enum-default-value.unknown": {
        "ru": "ЗначениеПоУмолчанию '{value}' – у перечисления '{enum}' нет такого значения: "
              "сборка отвергнет запись (\"Неизвестный элемент перечисления\").",
        "en": "{n[ЗначениеПоУмолчанию]} '{value}' – enumeration '{enum}' has no such value: "
              "the build rejects the spelling.",
    },
}
i18n.register(MESSAGES)

_NAME = r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*"
# The default shapes the rule judges: a bare value name or one dotted pair.
_CANDIDATE_RE = re.compile(rf"{_NAME}(?:\.{_NAME})?\Z")
_BARE_NAME_RE = re.compile(rf"{_NAME}\Z")


def _bare_type_name(value: str) -> str | None:
    """The bare type name of a judged `Type` value, the nullable marker stripped, or None.

    Anything beyond a single name with an optional trailing question mark - a union, a
    generic, a namespace-qualified name - answers None and takes the node out of the check.
    """
    stripped = value.strip()
    if stripped.endswith("?"):
        stripped = stripped[:-1].rstrip()
    return stripped if _BARE_NAME_RE.fullmatch(stripped) else None


def _default_value_strings(node) -> Iterable[str]:
    """Every string value under a default-value key anywhere in the parsed tree.

    Counted in full - the typed nodes alone would miss a same-text default on a node the
    walk skips, and the textual positions would then point at the wrong line.
    """
    spellings = _key_spellings("ЗначениеПоУмолчанию")
    if isinstance(node, dict):
        for key, value in node.items():
            if key in spellings and isinstance(value, str):
                yield value
            yield from _default_value_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _default_value_strings(item)


def _enum_default_mapper(source: SourceFile) -> dict | None:
    """The map phase: an enumeration yaml contributes (name, its declared values); every
    object yaml contributes its judged `Type` + `DefaultValue` pairs with positions.
    Which type names are project enumerations is the reduce's call."""
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    fact: dict = {}
    declared = _enum_declaration(data)
    if declared is not None:
        fact["enum"] = declared
    if object_kind(data):
        judged: dict[str, tuple[set[str], int]] = {}  # default string -> (type names, nodes)
        for node, keys in _typed_nodes(data):
            default_key = keys.get("ЗначениеПоУмолчанию")
            if default_key is None:
                continue
            default = node[default_key]
            if not isinstance(default, str) or not _CANDIDATE_RE.fullmatch(default):
                continue
            type_name = _bare_type_name(node[keys["Тип"]])
            if type_name is None:
                continue
            types, count = judged.setdefault(default, (set(), 0))
            judged[default] = (types | {type_name}, count + 1)
        cands = []
        totals = Counter(_default_value_strings(data)) if judged else Counter()
        for default, (types, count) in judged.items():
            if len(types) > 1 or totals[default] != count:
                continue  # positions are textual - a same-text default elsewhere is ambiguous
            positions = _value_positions(source, default, key="ЗначениеПоУмолчанию") or [(1, 1)]
            cands.append((next(iter(types)), default, positions))
        if cands:
            fact["cands"] = cands
    if not fact:
        return None
    fact["k"] = "y"
    return fact


@rule(
    "yaml/enum-default-value", "yaml/enum-default-value.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_enum_default_mapper,
)
def enum_default_value(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    enums: dict[str, set[str]] = {}
    for fact in facts.values():
        if "enum" in fact:
            name, values = fact["enum"]
            enums[name] = set(values)
    if not enums:
        return
    for rel, fact in facts.items():
        for type_name, default, positions in fact.get("cands", ()):
            values = enums.get(type_name)
            if values is None:
                continue
            prefix, dot, rest = default.partition(".")
            if dot:
                if prefix != type_name:
                    continue  # a foreign prefix - not the proven qualified form
                message = i18n.t("yaml/enum-default-value.qualified", value=default, plain=rest)
            elif default not in values:
                message = i18n.t("yaml/enum-default-value.unknown", value=default, enum=type_name)
            else:
                continue
            for line, col in positions:
                yield Diagnostic(
                    rel, line, col, "yaml/enum-default-value", Severity.ERROR, message,
                )
