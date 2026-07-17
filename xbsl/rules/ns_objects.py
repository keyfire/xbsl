"""Tier D: namespace-qualified project-object references in type positions.

The code/unknown-ns-object rule: a type-position chain whose root is the Russian name of an
object kind used as a namespace – `Справочник.Программа.Ссылка`, `Перечисление.Категория`,
`Массив<Документ.Заказ.Объект>` in code, the same expressions in yaml `Тип` values – must
name a project object of exactly that kind in the second segment. The third segment, when
present, must belong to the family of types the object generates – the same table as
code/unknown-object-type: the catalog object_members plus the safety-net union, the object's
tabular sections and its module-declared structures. Deeper segments are not checked.

The checked namespaces are the data-object kinds whose Russian name doubles as a namespace
root: Справочник, Документ, РегистрСведений, РегистрНакопления, Перечисление, ПланОбмена
(a subset of semantics._checked_kinds()). Both sides of a project are covered: xbsl modules
via the token-level type positions (semantics._type_ref_starts/_type_chains) and yaml `Тип`
values via the string-level parser (yaml_types._parse_type_string), including nesting in
generics (`Массив<Справочник.X.Ссылка>`).

Zero-false-positive guards: the stdlib itself carries dotted generic types with the same
roots (`Справочник.Ссылка`, `Документ.Объект` – "a reference to some catalog"), so a chain
whose first two segments name such a stdlib type is a generic, not an object reference, and
is skipped; without the stdlib catalog the rule does not run at all. Chains shorter than two
segments (`знч Х: Справочник`) are the stdlib root types and are left alone.

Limitation, stated on purpose: objects supplied by external libraries (.xlib) are not
visible among the project sources – on a project that plugs in libraries via the dependency
manifest the rule would flag their objects as unknown (false positives). The current corpus
uses no libraries; when that practice appears the rule must learn the manifest
(Проект.yaml) instead of guessing.

The rule is project-wide (it needs the objects of the whole project), so in single-file
mode it does not run. Verified on the real corpus: the namespace form does not occur in
type positions there at all – 0 diagnostics.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules.semantics import (
    _file_local_types,
    _member_family,
    _row_type_names,
    _stdlib_names,
    _type_chains,
    _type_ref_starts,
)
from xbsl.rules.yaml_schema import _parsed
from xbsl.rules.yaml_types import _parse_type_string, _type_values, _value_positions

MESSAGES = {
    "code/unknown-ns-object.title": {
        "ru": "Неизвестный объект в пространстве имён вида",
        "en": "Unknown object in a kind namespace",
    },
    "code/unknown-ns-object.object": {
        "ru": "Неизвестный тип '{name}' – в проекте нет объекта вида '{kind}' с именем '{seg}'.",
        "en": "Unknown type '{name}' – the project has no object of kind '{kind}' named '{seg}'.",
    },
    "code/unknown-ns-object.kind": {
        "ru": "Неизвестный тип '{name}' – объект '{seg}' имеет вид '{actual}', а не '{kind}'.",
        "en": "Unknown type '{name}' – object '{seg}' is of kind '{actual}', not '{kind}'.",
    },
    "code/unknown-ns-object.member": {
        "ru": "Неизвестный тип '{name}' – у объекта '{root}' ({kind}) нет производного типа, "
              "табличной части или структуры модуля с именем '{seg}'.",
        "en": "Unknown type '{name}' – object '{root}' ({kind}) has no derived type, "
              "tabular section or module structure named '{seg}'.",
    },
}
i18n.register(MESSAGES)

# Object kinds whose Russian name serves as a namespace root in type expressions.
# Kept to the data-object kinds (cf. semantics._BASE_CHECKED_KINDS and the catalog
# object_members keys): interface/module kinds are never referenced through a namespace.
_NS_KINDS = frozenset({
    "Справочник", "Документ", "РегистрСведений", "РегистрНакопления",
    "Перечисление", "ПланОбмена",
})


def _chain_problem(
    segs: list[str], objects: dict[str, dict],
) -> tuple[int, str] | None:
    """(index of the offending segment, message) for a namespace chain, or None when fine.

    The stdlib guard (Справочник.Ссылка is a dotted generic, not an object reference)
    runs in the map phase - here the chain is already known to name an object.
    """
    kind = segs[0]
    name = segs[1]
    rec = objects.get(name)
    if rec is None:
        return 1, i18n.t(
            "code/unknown-ns-object.object",
            name=f"{kind}.{name}", kind=kind, seg=name,
        )
    if rec["kind"] != kind:
        return 1, i18n.t(
            "code/unknown-ns-object.kind",
            name=f"{kind}.{name}", kind=kind, seg=name, actual=rec["kind"],
        )
    if len(segs) >= 3:
        member = segs[2]
        if member not in _member_family(kind) and member not in rec["members"]:
            return 2, i18n.t(
                "code/unknown-ns-object.member",
                name=f"{kind}.{name}.{member}", root=name, kind=kind, seg=member,
            )
    return None


def _ns_tokens(s: SourceFile) -> list:
    """The module tokens with capitalized kind-name keywords reclassified as identifiers.

    The lexer marks `Перечисление` as a keyword (the enum declaration word) regardless of
    case, so the chain builder would not start a chain at it. In a type position the
    capitalized form is the namespace root – reclassify it as a name. Declaration anchors
    react to lowercase keywords only, so the reclassification cannot invent declarations.
    """
    return [
        replace(t, kind="IDENT", canonical=None)
        if t.kind == "KEYWORD" and t.value in _NS_KINDS else t
        for t in tokens(s)
    ]


def _ns_candidate(segs: list[str], stdlib: frozenset[str]) -> list[str] | None:
    """The namespace-form chain trimmed to its meaningful head, or None.

    A chain qualifies when its root is a kind name and the second segment is present;
    a dotted stdlib generic (Справочник.Ссылка) is settled right here."""
    if len(segs) < 2 or segs[0] not in _NS_KINDS:
        return None
    if f"{segs[0]}.{segs[1]}" in stdlib:
        return None
    return segs[:3]


def _ns_mapper(source: SourceFile) -> dict | None:
    """The map phase: a yaml contributes its object record (for the namespace model) and
    its candidate chains; a module contributes its local types (object members) and its
    candidate chains with per-segment positions. The object model lives in the reduce."""
    stdlib = _stdlib_names()
    if not stdlib:
        return None  # the catalog is not generated – the dotted-generic guard needs it
    if source.kind == "yaml":
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict):
            return None
        fact: dict = {}
        nm = data.get("Имя")
        if data.get("ВидЭлемента") and isinstance(nm, str):
            # ИмяТипаДанныхСтроки динамического списка - такой же член формы, как
            # табличная часть (см. semantics._row_type_names).
            members = sorted(_row_type_names(data))
            if isinstance(data.get("ТабличныеЧасти"), list):
                members += [
                    p["Имя"] for p in data["ТабличныеЧасти"]
                    if isinstance(p, dict) and isinstance(p.get("Имя"), str)
                ]
            fact["obj"] = (nm, data["ВидЭлемента"], members)
        if data.get("ВидЭлемента"):
            cands = []
            for value in dict.fromkeys(_type_values(data)):  # unique, in document order
                chains = _parse_type_string(value)
                if not chains:
                    continue
                positions: list[tuple[int, int]] | None = None
                for chain in chains:
                    segs = _ns_candidate(chain, stdlib)
                    if segs is None:
                        continue
                    if positions is None:
                        positions = _value_positions(source, value) or [(1, 1)]
                    # a yaml value has one textual position for every segment
                    cands.append((segs, positions, positions))
            if cands:
                fact["cands"] = cands
        if not fact:
            return None
        fact["k"] = "y"
        return fact
    if source.kind != "xbsl":
        return None
    toks = _ns_tokens(source)
    cands = []
    for start in _type_ref_starts(toks):
        chains, _ = _type_chains(toks, start)
        for chain in chains:
            segs = _ns_candidate([t.value for t in chain], stdlib)
            if segs is None:
                continue
            pos = [(t.line, t.col) for t in chain[:3]]
            pos1 = [pos[1]] if len(pos) > 1 else [(chain[0].line, chain[0].col)]
            pos2 = [pos[2]] if len(pos) > 2 else pos1
            cands.append((segs, pos1, pos2))
    local = _file_local_types(source)
    if not cands and not local:
        return None
    owner = source.path.name[: -len(".xbsl")].split(".", 1)[0]
    return {"k": "x", "owner": owner, "local_types": sorted(local), "cands": cands}


@rule(
    "code/unknown-ns-object", "code/unknown-ns-object.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_ns_mapper,
)
def unknown_ns_object(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    # The object model: yaml records plus the local types of the objects' modules.
    objects: dict[str, dict] = {}
    for fact in facts.values():
        if fact["k"] == "y" and "obj" in fact:
            name, kind, members = fact["obj"]
            objects[name] = {"kind": kind, "members": set(members)}
    for fact in facts.values():
        if fact["k"] == "x":
            rec = objects.get(fact["owner"])
            if rec is not None:
                rec["members"].update(fact["local_types"])
    if not objects:
        return
    for rel, fact in facts.items():
        for segs, pos1, pos2 in fact.get("cands", ()):
            problem = _chain_problem(segs, objects)
            if problem is None:
                continue
            idx, message = problem
            for line, col in (pos1 if idx == 1 else pos2):
                yield Diagnostic(
                    rel, line, col, "code/unknown-ns-object",
                    Severity.WARNING, message,
                )
