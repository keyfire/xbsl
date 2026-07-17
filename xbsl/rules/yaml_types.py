"""Tier D: type expressions in yaml against the stdlib catalog and the project objects.

The yaml/unknown-type rule mirrors code/unknown-type and code/unknown-object-type on the yaml
side of a project: every string value of a `Тип` key is a type expression – the component type
of a form node (`Группа`, `ПолеВвода<Строка>`), the type of an attribute, a tabular-section
attribute, a property or a client-work parameter (`Число`, `Товары.Ссылка?`), a wrapper value
(`АбсолютныйЦвет`), a form base (`ФормаОбъекта<Товары.Объект>`)... The expression is parsed at
the string level:

    выражение     := альтернатива ('|' альтернатива)*
    альтернатива  := '' | цепочка ['<' выражение (',' выражение)* '>'] ['?']
    цепочка       := Имя ('.' Имя)*

(an empty alternative and a trailing `?` are the nullable marker). For every chain the root
must be known – a stdlib symbol, a project object or a module-declared local type; when the
root is a project object of a checked kind, the second segment must belong to the family of
types the object generates (the same table as code/unknown-object-type, including the
automatic forms: `Акция.АвтоматическаяФормаСписка.ДанныеСтрокиСписка`).

Zero-false-positive guards: only yaml files with `ВидЭлемента` are checked; the values are
taken from the parsed yaml tree, so a `Тип: ...` line inside a literal block scalar cannot
false-match; a value that does not parse as a type expression (a binding `=...`, an unexpected
character) is skipped rather than guessed. Positions are found by a text search for the value;
the rule is project-wide – it needs the objects of the whole project (as code/unknown-type,
it does not run in single-file mode).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.semantics import (
    _checked_kinds,
    _file_local_types,
    _member_family,
    _row_type_names,
    _stdlib_names,
)
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed

MESSAGES = {
    "yaml/unknown-type.title": {
        "ru": "Неизвестный тип в yaml",
        "en": "Unknown type in yaml",
    },
    "yaml/unknown-type.unknown": {
        "ru": "Неизвестный тип '{name}' – нет ни в stdlib, ни среди объектов проекта или локальных типов.",
        "en": "Unknown type '{name}' – not in stdlib, nor among the project objects or local types.",
    },
    "yaml/unknown-type.member": {
        "ru": "Неизвестный тип '{name}' – у объекта '{root}' ({kind}) нет производного типа, "
              "табличной части или структуры модуля с именем '{seg}'.",
        "en": "Unknown type '{name}' – object '{root}' ({kind}) has no derived type, "
              "tabular section or module structure named '{seg}'.",
    },
}
i18n.register(MESSAGES)

_NAME_RE = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*")

# Keyword type literals allowed as a whole alternative (`ФормаЗаписи<X.Запись, неизвестно>`).
_TYPE_KEYWORDS = frozenset({"неизвестно"})


def _parse_type_string(value: str) -> list[list[str]] | None:
    """The dotted name chains of a yaml type expression, or None when it does not parse."""
    chains: list[list[str]] = []
    s, n = value, len(value)
    i = 0

    def skip_ws() -> None:
        nonlocal i
        while i < n and s[i] == " ":
            i += 1

    def parse_alt() -> bool:
        nonlocal i
        m = _NAME_RE.match(s, i)
        if not m:
            return False
        chain = [m.group(0)]
        i = m.end()
        while i < n and s[i] == ".":
            m = _NAME_RE.match(s, i + 1)
            if not m:
                return False
            chain.append(m.group(0))
            i = m.end()
        if chain[0] not in _TYPE_KEYWORDS:
            chains.append(chain)
        skip_ws()
        if i < n and s[i] == "<":
            i += 1
            while True:
                if not parse_expr():
                    return False
                skip_ws()
                if i < n and s[i] == ",":
                    i += 1
                    continue
                break
            if i >= n or s[i] != ">":
                return False
            i += 1
        skip_ws()
        if i < n and s[i] == "?":
            i += 1
        return True

    def parse_expr() -> bool:
        nonlocal i
        while True:
            skip_ws()
            if i < n and s[i] == "?":  # a bare '?' alternative – the nullable marker
                i += 1
            elif i < n and (s[i].isalpha() or s[i] == "_"):
                if not parse_alt():
                    return False
            elif i >= n or s[i] in "|>,":
                pass  # an empty alternative (`Строка|`) – also the nullable marker
            else:
                return False
            skip_ws()
            if i < n and s[i] == "|":
                i += 1
                continue
            return True

    if not parse_expr():
        return None
    skip_ws()
    if i != n:
        return None
    return chains


def _type_values(node) -> Iterable[str]:
    """All string values of `Тип` keys in the parsed yaml tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "Тип" and isinstance(v, str):
                yield v
            yield from _type_values(v)
    elif isinstance(node, list):
        for item in node:
            yield from _type_values(item)


def _value_positions(source: SourceFile, value: str) -> list[tuple[int, int]]:
    """(line, col) of every `Тип: <значение>` occurrence in the source text."""
    pat = re.compile(  # \r?: the file may be CRLF, `$` in multiline mode anchors before \n
        r"(?m)^[ \t]*(?:- +)?Тип:[ \t]*(['\"]?)(" + re.escape(value) + r")\1[ \t]*(?:#.*)?\r?$"
    )
    lm = linemap(source)
    return [lm.linecol(m.start(2)) for m in pat.finditer(source.text)]


def _yaml_type_mapper(source: SourceFile) -> dict | None:
    """The map phase. A yaml file contributes its object record (name, kind, tabular
    sections) and its candidate type chains (single plain stdlib names are settled here);
    an xbsl file contributes the local types it declares - the reduce assembles the
    project model and judges the candidates."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        local = _file_local_types(source)
        if not local:
            return None
        owner = source.path.name[: -len(".xbsl")].split(".", 1)[0]
        return {"k": "x", "owner": owner, "local_types": sorted(local)}
    if source.kind != "yaml":
        return None
    stdlib = _stdlib_names()
    if not stdlib:
        return None  # the catalog is not generated – skip the check
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict) or not data.get("ВидЭлемента"):
        return None
    nm = data.get("Имя")
    # The row type a dynamic list names for itself (ИмяТипаДанныхСтроки) is a member of
    # the form just like a tabular section - see semantics._row_type_names.
    tab_members: list[str] = sorted(_row_type_names(data))
    parts = data.get("ТабличныеЧасти")
    if isinstance(parts, list):
        tab_members += [
            p["Имя"] for p in parts
            if isinstance(p, dict) and isinstance(p.get("Имя"), str)
        ]
    cands: list[tuple[list[str], list[tuple[int, int]]]] = []
    for value in dict.fromkeys(_type_values(data)):  # unique, in document order
        chains = _parse_type_string(value)
        if not chains:
            continue
        positions: list[tuple[int, int]] | None = None
        for chain in chains:
            if len(chain) == 1 and chain[0] in stdlib:
                continue  # a plain stdlib name - settled right here
            if positions is None:
                positions = _value_positions(source, value) or [(1, 1)]
            cands.append((chain, positions))
    if not cands and not isinstance(nm, str):
        return None
    return {
        "k": "y",
        "name": nm if isinstance(nm, str) else None,
        "kind": data["ВидЭлемента"],
        "tab_members": tab_members,
        "cands": cands,
    }


@rule(
    "yaml/unknown-type", "yaml/unknown-type.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_yaml_type_mapper,
)
def unknown_yaml_type(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    stdlib = _stdlib_names()
    if not stdlib:
        return
    # The project model from the facts: object records plus the local types of their modules.
    objects: dict[str, dict] = {}
    all_local: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "y" and fact["name"]:
            objects[fact["name"]] = {
                "kind": fact["kind"], "members": set(fact["tab_members"]),
            }
    for fact in facts.values():
        if fact["k"] != "x":
            continue
        all_local.update(fact["local_types"])
        rec = objects.get(fact["owner"])
        if rec is not None:
            rec["members"].update(fact["local_types"])
    known = set(stdlib) | set(objects) | all_local
    checked = _checked_kinds()
    for rel, fact in facts.items():
        if fact["k"] != "y":
            continue
        for chain, positions in fact["cands"]:
            root = chain[0]
            message: str | None = None
            if root not in known:
                message = i18n.t("yaml/unknown-type.unknown", name=".".join(chain))
            elif len(chain) >= 2:
                rec = objects.get(root)
                if rec is not None and rec["kind"] in checked:
                    seg = chain[1]
                    if seg not in _member_family(rec["kind"]) and seg not in rec["members"]:
                        message = i18n.t(
                            "yaml/unknown-type.member",
                            name=f"{root}.{seg}", root=root,
                            kind=rec["kind"], seg=seg,
                        )
            if message is None:
                continue
            for line, col in positions:
                yield Diagnostic(rel, line, col, "yaml/unknown-type", Severity.WARNING, message)
