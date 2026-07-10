"""Tier D: project enumerations in yaml type positions must be nullable.

The yaml/enum-needs-nullable rule: a `Тип` value naming a project enumeration without the
nullable marker – an object attribute, a tabular-section attribute, a component property or
a parameter `Тип: ВидПолезного`, or an input field `Тип: ПолеВвода<ВидПолезного>` – does not
compile on the server: an enumeration has no implicit default value, so the platform demands
one ('...cannot be initialized with a default value'; the fix is `ВидПолезного?` /
`ПолеВвода<ВидПолезного?>`).

Legal non-nullable forms (per the platform docs) are skipped:
- an enumeration where one of `Элементы` carries `ПоУмолчанию: Истина` has a default value
  of its own (topics/enumeration-properties), so its bare uses are never flagged;
- a node that sets `ЗначениеПоУмолчанию` next to `Тип` provides the default explicitly
  (topics/catalog-properties, topics/component-example) and is skipped; positions are found
  by a text search, so when the same value string occurs in one file both with and without
  the guard, the whole value is skipped in that file (a false negative, never a false
  positive).

Narrowing (deliberate, to keep the zero-false-positive bar): only the two exact shapes are
flagged – a value that is the bare enumeration name, and `ПолеВвода<Имя>` with the bare name
as the only argument. Unions (`ВидПолезного|Строка`), other generics (`Массив<ВидПолезного>`)
and qualified names are left alone – whether the compiler demands a default there is not
certain. Only yaml files with `ВидЭлемента` are checked; the values are taken from the parsed
yaml tree, so a `Тип: ...` line inside a literal block scalar cannot false-match. The rule is
project-wide – it needs the enumerations of the whole project (it does not run in single-file
mode).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.rules.enum_values import _project_enums
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed
from xbsllint.rules.yaml_types import _value_positions

MESSAGES = {
    "yaml/enum-needs-nullable.title": {
        "ru": "Перечисление без nullable",
        "en": "Enumeration without nullable",
    },
    "yaml/enum-needs-nullable.bare": {
        "ru": "Тип '{name}' – перечисление без '?': значения по умолчанию нет, серверная "
              "компиляция упадёт. Укажите '{name}?' либо задайте значение по умолчанию "
              "(ЗначениеПоУмолчанию рядом с Тип или ПоУмолчанию: Истина у элемента перечисления).",
        "en": "Type '{name}' – an enumeration without '?': there is no default value, the "
              "server-side compilation will fail. Use '{name}?' or provide a default "
              "(ЗначениеПоУмолчанию next to Тип or ПоУмолчанию: Истина on an enumeration element).",
    },
    "yaml/enum-needs-nullable.input": {
        "ru": "Тип 'ПолеВвода<{name}>' – аргумент-перечисление без '?': значения по умолчанию "
              "нет, серверная компиляция упадёт. Укажите 'ПолеВвода<{name}?>'.",
        "en": "Type 'ПолеВвода<{name}>' – an enumeration argument without '?': there is no "
              "default value, the server-side compilation will fail. Use 'ПолеВвода<{name}?>'.",
    },
}
i18n.register(MESSAGES)

# `ПолеВвода<Имя>` with a single bare-name argument (no '?', no union, no FQN).
_INPUT_FIELD_RE = re.compile(
    r"^\s*ПолеВвода\s*<\s*([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)\s*>\s*$"
)


def _enums_with_default(sources: list[SourceFile]) -> set[str]:
    """Имена перечислений проекта, у которых есть элемент с ПоУмолчанию: Истина."""
    names: set[str] = set()
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict):
            continue
        if data.get("ВидЭлемента") != "Перечисление" or not isinstance(data.get("Имя"), str):
            continue
        items = data.get("Элементы")
        # yaml-парсер видит платформенное 'Истина' строкой, а true - булевым
        if isinstance(items, list) and any(
            isinstance(item, dict) and item.get("ПоУмолчанию") in (True, "Истина")
            for item in items
        ):
            names.add(data["Имя"])
    return names


def _typed_nodes(node) -> Iterable[dict]:
    """All dict nodes of the parsed yaml tree that carry a string `Тип` key."""
    if isinstance(node, dict):
        if isinstance(node.get("Тип"), str):
            yield node
        for v in node.values():
            yield from _typed_nodes(v)
    elif isinstance(node, list):
        for item in node:
            yield from _typed_nodes(item)


def _enum_hit(value: str, enums: set[str]) -> tuple[str, int, str] | None:
    """(имя перечисления, смещение имени в значении, ключ сообщения) или None.

    Ловит ровно две формы: голое имя перечисления и ПолеВвода<Имя> с голым аргументом.
    """
    stripped = value.strip()
    if stripped in enums:
        return stripped, value.index(stripped), "yaml/enum-needs-nullable.bare"
    m = _INPUT_FIELD_RE.match(value)
    if m and m.group(1) in enums:
        return m.group(1), m.start(1), "yaml/enum-needs-nullable.input"
    return None


@rule(
    "yaml/enum-needs-nullable", "yaml/enum-needs-nullable.title", "D",
    scope="project", severity=Severity.WARNING,
)
def enum_needs_nullable(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    if not _HAVE_YAML:
        return []
    enums = set(_project_enums(sources)) - _enums_with_default(sources)
    if not enums:
        return []

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict) or not data.get("ВидЭлемента"):
            continue
        # значение Тип -> (имя, смещение, ключ сообщения); guarded – значения с явным дефолтом
        candidates: dict[str, tuple[str, int, str]] = {}
        guarded: set[str] = set()
        for node in _typed_nodes(data):
            value = node["Тип"]
            hit = _enum_hit(value, enums)
            if hit is None:
                continue
            if "ЗначениеПоУмолчанию" in node:
                guarded.add(value)
            else:
                candidates[value] = hit
        for value, (name, off, msg_key) in candidates.items():
            if value in guarded:
                continue  # позиции текстовые – одноимённое защищённое значение неотличимо
            positions = _value_positions(s, value)
            positions = [(line, col + off) for line, col in positions] or [(1, 1)]
            diags.extend(
                Diagnostic(s.rel, line, col, "yaml/enum-needs-nullable", Severity.WARNING,
                           i18n.t(msg_key, name=name))
                for line, col in positions
            )
    return diags
