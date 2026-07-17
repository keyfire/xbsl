"""Tier D: enumeration values against the project enum declarations.

The code/unknown-enum-value rule: a member access on a project enumeration –
`ВидСообщения.Важное` in code or `=ВидСообщения.Важное` in a yaml binding – must name a
declared value of that enumeration (yaml `Элементы[].Имя`), a built-in member reachable
through the name (see _enum_builtin_members) or a method of the enumeration's own paired
module. Only enumerations declared as project objects (`ВидЭлемента: Перечисление`) are
checked; module-local `перечисление` declarations are left alone – their values live in code
the compiler already sees locally.

Zero-false-positive guards. In code, an identifier may shadow the enumeration (a local
variable, a parameter, a loop variable – the platform resolves the name to the nearest
binding), so a module where the enum name is ever declared or assigned (`знч/пер/конст/обз/
поймать/для <Имя>`, `<Имя> =`, `<Имя>:`, `<Имя> ->`) is skipped for that name; comments and
`Запрос{...}` blocks are excluded via code_tokens; an access whose root is itself preceded by
`.` is a member of another object, not the enumeration. In yaml only binding values (strings
starting with `=`) are scanned, and a file where the enum name occurs as any `Имя:` (a field,
a property, an attribute of the form data) is skipped for that name. The rule is project-wide:
it needs the enumerations of the whole project.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules._syntax import code_tokens, signatures
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed

MESSAGES = {
    "code/unknown-enum-value.title": {
        "ru": "Неизвестное значение перечисления",
        "en": "Unknown enumeration value",
    },
    "code/unknown-enum-value.unknown": {
        "ru": "Неизвестное значение перечисления '{name}' – у перечисления '{root}' нет элемента '{seg}'.",
        "en": "Unknown enumeration value '{name}' – enumeration '{root}' has no element '{seg}'.",
    },
}
i18n.register(MESSAGES)


@lru_cache(maxsize=1)
def _enum_builtin_members() -> frozenset[str]:
    """Members reachable through the bare enumeration name, from the stdlib catalog.

    Two sources, because the name stands for two things. `Стд::Перечисление` is the base type
    of an element, so its members answer `СостояниеЗаказов.Открыт.Представление`. And the name
    itself resolves to the type object `Стд::Тип<ТипЗначения>`, whose enum-only members answer
    `СостояниеЗаказов.ПоИмени("Открыт")` and `.Элементы()` - the docs spell them
    `<ValueType это Перечисление>`. Taken from the catalog rather than listed by hand: the
    platform grows members, and a stale list would report them as unknown values.
    """
    members: set[str] = set()
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return frozenset({"Представление", "ВСтроку", "ПолучитьТип", "Индекс"})
    for type_name in ("Перечисление", "Тип"):
        entry = (catalog.get("type_members") or {}).get(type_name) or {}
        if isinstance(entry, dict):
            members |= {str(x) for x in entry.get("properties") or ()}
            members |= {str(x) for x in entry.get("methods") or ()}
        else:
            members |= {str(x) for x in entry}
    return frozenset(members)


def _static_method_names(s: SourceFile) -> list[str]:
    """Names of the methods a module declares - the paired module of an enumeration adds
    them to the members reachable through the enumeration name."""
    return sorted({sig.name.value for sig in signatures(code_tokens(s))})


# Declaration keywords that bind a name (shadowing the enumeration in the whole module).
_DECL_KW = ("VAL", "VAR", "CONST", "REQ", "CATCH", "FOR")


def _project_enums(sources: list[SourceFile]) -> dict[str, set[str]]:
    """Имя перечисления проекта -> имена его элементов (yaml Элементы[].Имя)."""
    enums: dict[str, set[str]] = {}
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is not None or not isinstance(data, dict):
            continue
        if data.get("ВидЭлемента") != "Перечисление" or not isinstance(data.get("Имя"), str):
            continue
        values: set[str] = set()
        items = data.get("Элементы")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("Имя"), str):
                    values.add(item["Имя"])
        enums[data["Имя"]] = values
    return enums


def _shadowed_names(toks: list) -> set[str]:
    """Names bound anywhere in the module: declarations, assignments, annotations, lambdas.

    Wider than necessary on purpose – a shadowed name only makes the rule skip, never report.
    """
    names: set[str] = set()
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical in _DECL_KW:
            for j in range(i + 1, min(i + 3, n)):
                if toks[j].kind == "IDENT":
                    names.add(toks[j].value)
                    break
        elif t.kind == "IDENT" and i + 1 < n and toks[i + 1].kind == "OP":
            # `Объект.Имя = ...` is a member assignment, not a binding of the bare name
            member = i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value == "."
            if not member and toks[i + 1].value in ("=", ":", "->"):
                names.add(t.value)
    return names


def _code_accesses(s: SourceFile) -> dict[tuple[str, str], list[tuple[int, int]]]:
    """Bare `Root.Seg` accesses of a module with the local skips settled:
    (root, seg) -> positions of the seg. Which roots are enumerations is the reduce's
    knowledge - here every non-shadowed dotted access is a candidate."""
    toks = code_tokens(s)
    shadowed = _shadowed_names(toks)
    n = len(toks)
    out: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value in shadowed:
            continue
        if i > 0 and toks[i - 1].kind == "OP" and toks[i - 1].value in (".", "::"):
            # After `.` - a member of another object, not the enumeration. After `::` - a
            # namespace-qualified root: a library enumeration may share a project one's
            # name, and its values are not ours to judge.
            continue
        if not (i + 2 < n and toks[i + 1].kind == "OP" and toks[i + 1].value == "."
                and toks[i + 2].kind == "IDENT"):
            continue
        seg = toks[i + 2]
        if seg.value in _enum_builtin_members():
            continue
        out.setdefault((t.value, seg.value), []).append((seg.line, seg.col))
    return out


def _binding_values(node) -> Iterable[str]:
    """All binding strings (`=выражение`) in the parsed yaml tree."""
    if isinstance(node, dict):
        for v in node.values():
            yield from _binding_values(v)
    elif isinstance(node, list):
        for item in node:
            yield from _binding_values(item)
    elif isinstance(node, str) and node.startswith("="):
        yield node


def _name_values(node) -> set[str]:
    """All string values of `Имя` keys in the parsed yaml tree (fields, properties...)."""
    names: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "Имя" and isinstance(v, str):
                names.add(v)
            names |= _name_values(v)
    elif isinstance(node, list):
        for item in node:
            names |= _name_values(item)
    return names


def _yaml_accesses(s: SourceFile, data: dict) -> dict[tuple[str, str], list[tuple[int, int]]]:
    """Dotted pairs of the binding strings with positions; roots that occur as any local
    `Имя:` are skipped here (the file's own knowledge)."""
    local_names = _name_values(data)
    pairs: set[tuple[str, str]] = set()
    for binding in _binding_values(data):
        for root, seg in re.findall(
            r"(?<![\wА-Яа-яЁё.])([А-ЯЁ][\wА-Яа-яЁё]*)\.([А-Яа-яЁёA-Za-z_][\wА-Яа-яЁё]*)",
            binding,
        ):
            if root in local_names or seg in _enum_builtin_members():
                continue
            pairs.add((root, seg))
    out: dict[tuple[str, str], list[tuple[int, int]]] = {}
    lm = linemap(s) if pairs else None
    for root, seg in sorted(pairs):
        pat = re.compile(r"(?<![\wА-Яа-яЁё.])" + re.escape(f"{root}.{seg}") + r"(?![\wА-Яа-яЁё])")
        out[(root, seg)] = [lm.linecol(m.start()) for m in pat.finditer(s.text)] or [(1, 1)]
    return out


def _enum_values_mapper(source: SourceFile) -> dict | None:
    """The map phase: an enumeration yaml contributes its declared values; every module
    and every object yaml contributes its dotted-access candidates with positions."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        accesses = _code_accesses(source)
        methods = _static_method_names(source)
        if not accesses and not methods:
            return None
        # The owner is the stem before the first dot (`Товар.Объект.xbsl` belongs to Товар),
        # the same pairing the other project rules use.
        owner = source.path.name[: -len(".xbsl")].split(".", 1)[0]
        return {
            "k": "x", "owner": owner, "methods": methods,
            "acc": [(r, s2, pos) for (r, s2), pos in accesses.items()],
        }
    if source.kind != "yaml":
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    fact: dict = {}
    if data.get("ВидЭлемента") == "Перечисление" and isinstance(data.get("Имя"), str):
        values = [
            item["Имя"] for item in (data.get("Элементы") or [])
            if isinstance(item, dict) and isinstance(item.get("Имя"), str)
        ] if isinstance(data.get("Элементы"), list) else []
        fact["enum"] = (data["Имя"], values)
    if data.get("ВидЭлемента"):
        accesses = _yaml_accesses(source, data)
        if accesses:
            fact["acc"] = [(r, s2, pos) for (r, s2), pos in accesses.items()]
    if not fact:
        return None
    fact["k"] = "y"
    return fact


@rule(
    "code/unknown-enum-value", "code/unknown-enum-value.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_enum_values_mapper,
)
def unknown_enum_value(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    enums: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "y" and "enum" in fact:
            name, values = fact["enum"]
            enums[name] = set(values)
    if not enums:
        return []
    # An enumeration may carry a module, and its methods are addressed through the very same
    # name: `ПродуктыПеречисление.ПолучитьНазвание(Продукт)` is a call, not a value.
    for fact in facts.values():
        if fact["k"] == "x" and fact["owner"] in enums:
            enums[fact["owner"]].update(fact["methods"])

    diags: list[Diagnostic] = []
    for rel, fact in facts.items():
        for root, seg, positions in fact.get("acc", ()):
            values = enums.get(root)
            if values is None or seg in values:
                continue
            for line, col in positions:
                diags.append(Diagnostic(
                    rel, line, col, "code/unknown-enum-value", Severity.WARNING,
                    i18n.t("code/unknown-enum-value.unknown",
                           name=f"{root}.{seg}", root=root, seg=seg),
                ))
    return diags
