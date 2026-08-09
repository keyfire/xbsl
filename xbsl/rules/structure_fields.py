"""Tier D: a field access on a project-declared structure must exist on that structure.

The compiler knows the shape of every structure declared in the project, the linter did not:
`code/unknown-member` judges the stdlib catalog and skips project types outright. So a field
renamed in its declaration left its readers in OTHER modules untouched, the whole-project lint
stayed clean, and the failure surfaced only as `Неизвестное свойство ...` on the server apply.

What is judged - the shapes that name the structure unambiguously:

- a variable whose declaration names the structure (`пер Категория: Каталог.Карточка`,
  a parameter, a module field), the qualified spelling for another module and the bare name
  for the declaring module's own structures;
- a variable initialized by the structure's constructor (`знч Карточка = новый Каталог.Карточка(...)`);
- the variable of a `для X из Список` loop when the collection is a single-argument generic
  over such a structure (`Список: Массив<Каталог.Карточка>`) - this is the everyday shape,
  and the failure above happened in exactly it.

Zero-false-positive guards:

- one name, one meaning: if the same name is declared anywhere in the method (or at module
  level) with another type, no type at all, or by a lambda parameter, the name is not judged;
- the first hop only - in `X.Field.Something` the judged link is `Field`, the rest belongs to
  another type;
- a bare structure name that a stdlib type also carries is skipped: the linter would have to
  know which one the compiler picks, and that guess is not worth a false error;
- the structure's own methods count as members, so `Карточка.Заполнить()` is not a finding;
- Latin member spellings are left alone, like the sibling member rules.

Project scope by necessity: the declaration usually lives in another file. The mapper
publishes both halves per file - the structures declared in it and the accesses seen in it -
and the reduce joins them.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

from xbsl import i18n
from xbsl import parser as P
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.unknown_members import _COMMON_MEMBERS, _is_latin, _stdlib_members

MESSAGES = {
    "code/unknown-structure-field.title": {
        "ru": "Неизвестное поле структуры",
        "en": "Unknown field of a structure",
    },
    "code/unknown-structure-field.found": {
        "ru": "У структуры {structure} нет члена {member}",
        "en": "The structure {structure} has no member {member}",
    },
    "code/unknown-structure-field.found-hint": {
        "ru": "У структуры {structure} нет члена {member} – возможно, имелся в виду {hint}",
        "en": "The structure {structure} has no member {member} - did you mean {hint}",
    },
}
i18n.register(MESSAGES)

#: `Массив<Модуль.Структура>` - a single-argument generic; several arguments name no element.
_GENERIC_RE = re.compile(r"^[\w.]+<(.+)>$")


def _module_of(source: SourceFile) -> str:
    """The module a file belongs to: `Каталог.Объект.xbsl` and `Каталог.xbsl` are both Каталог."""
    return source.path.name[: -len(".xbsl")].split(".", 1)[0]


def _element_type(type_text: str) -> str | None:
    """The element type of a collection type, or None when it names more than one."""
    match = _GENERIC_RE.match(type_text.strip())
    if not match or "," in match.group(1):
        return None
    return match.group(1).strip()


def _nominal(type_text: str) -> str | None:
    """The written type name without the nullable mark, or None when it is compound."""
    text = type_text.strip().rstrip("?").strip()
    return text if text and "|" not in text and "<" not in text else None


def _declared_types(nodes: Iterable, module_level: bool = False) -> tuple[dict, dict, set]:
    """({name: written type}, {name: written ELEMENT type}, names that carry anything else).

    The written type is kept as text: whether it names a structure of the project is decided
    in the reduce, where the declarations of the other files are known.
    """
    typed: dict[str, str] = {}
    collections: dict[str, str] = {}
    ambiguous: set[str] = set()
    for node in nodes:
        if module_level and not isinstance(node, P.ObjectField):
            continue
        if not isinstance(node, (P.VarDecl, P.ObjectField, P.Param)):
            continue
        written = None
        type_ref = getattr(node, "type", None)
        if type_ref is not None:
            written = _nominal(type_ref.text)
            if written is None:
                element = _element_type(type_ref.text)
                if element is not None and _nominal(element):
                    collections[node.name] = _nominal(element)
        if written is None:
            init = getattr(node, "init", None) or getattr(node, "default", None)
            if isinstance(init, P.New):
                written = _nominal(init.type.text)
        if written is None:
            ambiguous.add(node.name)
            continue
        if typed.get(node.name, written) != written:
            ambiguous.add(node.name)
        typed[node.name] = written
    return typed, collections, ambiguous


def _walk(node, out: list) -> None:
    """Every node of a subtree (the rules need the shape, not a typed visitor)."""
    if isinstance(node, P.Node):
        out.append(node)
        for value in vars(node).values():
            _walk(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk(item, out)


def _accesses(source: SourceFile) -> list[dict]:
    """First-hop member accesses on variables whose declaration names a single type."""
    module, errors = parse(source)
    if errors:
        return []
    lm = linemap(source)
    module_typed, module_collections, module_ambiguous = _declared_types(
        module.members, module_level=True,
    )
    out: list[dict] = []
    methods: list[P.Method] = []
    for member in module.members:
        if isinstance(member, P.Method):
            methods.append(member)
        elif isinstance(member, P.Structure):
            methods.extend(sub for sub in member.members if isinstance(sub, P.Method))
    for method in methods:
        nodes: list = []
        _walk(method, nodes)
        typed, collections, ambiguous = _declared_types(nodes)
        typed = {**module_typed, **typed}
        collections = {**module_collections, **collections}
        ambiguous = module_ambiguous | ambiguous
        for node in nodes:
            # `для X из Список`: the loop variable takes the element type of the collection.
            if isinstance(node, P.ForEach) and isinstance(node.source, P.Name):
                element = collections.get(node.source.name)
                if element is None:
                    continue
                if typed.get(node.var, element) != element:
                    ambiguous.add(node.var)
                    continue
                typed[node.var] = element
                ambiguous.discard(node.var)
        for node in nodes:
            if not isinstance(node, P.Member) or not isinstance(node.obj, P.Name):
                continue
            name = node.obj.name
            if name in ambiguous or name not in typed or _is_latin(node.name):
                continue
            line, col = lm.linecol(node.start)
            out.append({
                "type": typed[name], "member": node.name, "line": line, "col": col,
            })
    return out


def _structure_mapper(source: SourceFile) -> dict | None:
    """The map phase: what a file DECLARES (structures) and what it ASKS (member accesses)."""
    if source.kind != "xbsl":
        return None
    module, errors = parse(source)
    if errors:
        return None
    owner = _module_of(source)
    declared: dict[str, list[str]] = {}
    for member in module.members:
        if isinstance(member, P.Structure):
            declared[member.name] = sorted({
                sub.name for sub in member.members
                if isinstance(sub, (P.ObjectField, P.Method))
            })
    fact: dict = {"owner": owner}
    if declared:
        fact["structures"] = declared
    accesses = _accesses(source)
    if accesses:
        fact["accesses"] = accesses
    return fact


@rule(
    "code/unknown-structure-field", "code/unknown-structure-field.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_structure_mapper,
)
def unknown_structure_field(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A field read through a variable of a project structure must exist on that structure."""
    structures: dict[tuple[str, str], list[str]] = {}
    for fact in facts.values():
        for name, members in (fact.get("structures") or {}).items():
            key = (fact["owner"], name)
            known = structures.get(key)
            # A module written as a pair of files (`X.xbsl`, `X.Объект.xbsl`) declares into
            # one namespace: the halves are merged rather than shadowing each other.
            structures[key] = sorted(set(known) | set(members)) if known else members
    if not structures:
        return
    stdlib = _stdlib_members()
    for rel, fact in facts.items():
        for access in fact.get("accesses") or ():
            key = _resolve(access["type"], fact["owner"], structures, stdlib)
            if key is None:
                continue
            members = structures[key]
            if access["member"] in members or access["member"] in _COMMON_MEMBERS:
                continue
            hint = difflib.get_close_matches(access["member"], members, n=1, cutoff=0.7)
            structure = f"{key[0]}.{key[1]}"
            message = (
                i18n.t("code/unknown-structure-field.found-hint",
                       structure=structure, member=access["member"], hint=hint[0])
                if hint else
                i18n.t("code/unknown-structure-field.found",
                       structure=structure, member=access["member"])
            )
            yield Diagnostic(
                rel, access["line"], access["col"], "code/unknown-structure-field",
                Severity.ERROR, message,
            )


def _resolve(
    written: str, owner: str, structures: dict, stdlib: dict,
) -> tuple[str, str] | None:
    """The declaration a written type name points at, or None when it points elsewhere.

    A qualified name names its module outright. A bare name means the structure of the
    module the access is written in - unless a stdlib type carries the same name, and then
    nothing is judged: which one the compiler picks is not for a guess to decide.
    """
    if "." in written:
        module, _, structure = written.rpartition(".")
        key = (module, structure)
        return key if key in structures else None
    if written in stdlib:
        return None
    key = (owner, written)
    return key if key in structures else None
