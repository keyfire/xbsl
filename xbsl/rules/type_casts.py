"""Tier D: casts the compiler calls needless - `code/redundant-cast` and `code/cast-to-non-null`.

The editor of the platform warns about two kinds of `<выражение> как <Тип>`:

- the expression is ALREADY of that type (or of one the type holds), the redundant type cast.
  `Найдена!.Ссылка как Товары.Ссылка`, where the query row reads the reference of the
  very catalog, is the everyday shape;
- the expression is that type OR the empty value, and the cast does nothing but drop the empty
  value - "Следует использовать настойчивую операцию '!'". `Строка.Товар как Товары.Ссылка`
  over a field declared `Товары.Ссылка?` says the same as `Строка.Товар!`, and the operator
  says it without naming the type again.

Neither is an error, and both hide what the code means: a cast reads as a conversion, and a
reader looks for the case where the value is of another type - there is none. The fixes are
mechanical: the cast is removed, or replaced by `!`.

The comparison is the compiler's own (see `typeinfer.cast_verdict`), and the hard part is the
type of the operand. Most of what a live project casts comes from the project itself - a column
of a query over a catalog, a field of a structure declared in another module, the result of a
common module's method - so the rules are PROJECT rules: the mapper publishes per file what the
catalog needs (the elements of the yaml, the declarations of the modules) and, for a module
that casts at all, its text; the reduce builds the project catalog and types the operands
there. A file rule could see neither the yaml of the table a query reads nor the declaration of
a structure in another module, and without them the inference names nothing.

What keeps both rules at zero false findings:

- an operand the inference cannot name is not judged - a union with an unknown part, a type
  parameter, a column of a query the reading does not understand;
- the operand is typed by its declarations, the way the compiler types it for this check: a
  condition checked before the cast narrows nothing (see `typeinfer.CastSite`);
- a type the project does not declare in a way the catalog reads stays unknown, and so does a
  relation between two types the catalog cannot prove (the contract an element implements is
  the one relation of the project it knows).
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable
from pathlib import PurePosixPath

from xbsl import i18n, lexer
from xbsl import parser as P
from xbsl import typeinfer
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, is_query_file, rule
from xbsl.lexer import linemap
from xbsl.parser import parse
from xbsl.rules.environment import _pair_stem
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "code/redundant-cast.title": {
        "ru": "Избыточное приведение типа",
        "en": "Redundant type cast",
    },
    "code/redundant-cast.found": {
        "ru": "Избыточное приведение: выражение уже имеет тип '{source}', и 'как {target}' "
              "ничего не меняет – уберите приведение.",
        "en": "Redundant cast: the expression is already of type '{source}', and "
              "'{n[как]} {target}' changes nothing - remove the cast.",
    },
    "code/redundant-cast.wider": {
        "ru": "Избыточное приведение: значение типа '{source}' уже относится к типу '{target}' – "
              "приведение уберите, если этот тип не нужен объявлению или перегрузке.",
        "en": "Redundant cast: a value of type '{source}' already is a '{target}' - remove the "
              "cast unless a declaration or an overload needs that type.",
    },
    "code/cast-to-non-null.title": {
        "ru": "Приведение вместо настойчивой операции '!'",
        "en": "A cast in place of the non-null operator '!'",
    },
    "code/cast-to-non-null.found": {
        "ru": "Выражение имеет тип '{source}', и 'как {target}' только отбрасывает "
              "Неопределено – используйте настойчивую операцию '!'.",
        "en": "The expression is of type '{source}', and '{n[как]} {target}' only drops "
              "{n[Неопределено]} - use the non-null operator '!'.",
    },
}
i18n.register(MESSAGES)

_REDUNDANT = "code/redundant-cast"
_NON_NULL = "code/cast-to-non-null"

#: The project descriptor: its folder is the boundary of one catalog.
_PROJECT_FILES = frozenset({"Проект.yaml", "Project.yaml"})


# --- the mapper: what one file contributes -------------------------------------------------------

def _typed_members(data: dict, key: str, kind: str | None) -> dict[str, str | None]:
    """{name: written type or None} of a list section of an element (`Attributes` and the like)."""
    items = value_of(data, key, kind)
    out: dict[str, str | None] = {}
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("Имя") or item.get("Name")
        if not isinstance(name, str) or not name:
            continue
        written = item.get("Тип") if "Тип" in item else item.get("Type")
        out[name] = written.strip() if isinstance(written, str) and written.strip() else None
    return out


def _contracts(data: dict, kind: str | None) -> list[str]:
    """The entity contracts the element lists under its type settings, as written."""
    settings = value_of(data, "НастройкиТипов", kind)
    out: list[str] = []
    if not isinstance(settings, dict):
        return out
    for facet in settings.values():
        if not isinstance(facet, dict):
            continue
        listed = facet.get("Контракты") if "Контракты" in facet else facet.get("Contracts")
        if isinstance(listed, list):
            out.extend(item.strip() for item in listed if isinstance(item, str) and item.strip())
    return out


def _yaml_names(node, out: set[str]) -> None:
    if isinstance(node, dict):
        for key in ("Имя", "Name"):
            value = node.get(key)
            if isinstance(value, str) and value:
                out.add(value)
        for value in node.values():
            _yaml_names(value, out)
    elif isinstance(node, list):
        for item in node:
            _yaml_names(item, out)


def _element_fact(source: SourceFile) -> dict | None:
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    kind = object_kind(data)
    name = value_of(data, "Имя", kind)
    if not kind or not isinstance(name, str) or not name:
        return None
    tabular: dict[str, dict[str, str | None]] = {}
    parts = value_of(data, "ТабличныеЧасти", kind)
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_name = part.get("Имя") or part.get("Name")
            if isinstance(part_name, str) and part_name:
                tabular[part_name] = _typed_members(part, "Реквизиты", kind)
    values = _typed_members(data, "Элементы", kind) if kind == "Перечисление" else {}
    names: set[str] = set()
    _yaml_names(data, names)
    return {
        "name": name,
        "kind": kind,
        "attributes": _typed_members(data, "Реквизиты", kind),
        "dimensions": _typed_members(data, "Измерения", kind),
        "resources": _typed_members(data, "Ресурсы", kind),
        "properties": _typed_members(data, "Свойства", kind),
        "fields": _typed_members(data, "Поля", kind),
        "tabular": tabular,
        "values": sorted(values),
        "contracts": _contracts(data, kind),
        "names": sorted(names),
    }


def _walk_casts(node) -> bool:
    if isinstance(node, (list, tuple)):
        return any(_walk_casts(item) for item in node)
    if not isinstance(node, P.Node):
        return False
    if isinstance(node, P.AsType):
        return True
    return any(_walk_casts(getattr(node, f.name, None)) for f in dataclasses.fields(node))


def _written(type_ref) -> str | None:
    text = getattr(type_ref, "text", None)
    return text.strip() if isinstance(text, str) and text.strip() else None


def _module_fact(source: SourceFile) -> dict | None:
    module, errors = parse(source)
    methods: dict[str, list[str | None]] = {}
    structures: dict[str, dict] = {}
    enums: dict[str, list[str]] = {}
    fields: dict[str, str | None] = {}
    for member in module.members:
        if isinstance(member, P.Method):
            methods.setdefault(member.name, []).append(_written(member.return_type))
        elif isinstance(member, P.Structure):
            own_methods: dict[str, list[str | None]] = {}
            for inner in member.members:
                if isinstance(inner, P.Method):
                    own_methods.setdefault(inner.name, []).append(_written(inner.return_type))
            structures[member.name] = {
                "fields": {f.name: _written(f.type) for f in member.members
                           if isinstance(f, P.ObjectField)},
                "methods": own_methods,
            }
        elif isinstance(member, P.Enum):
            enums[member.name] = [item.name for item in member.items]
        elif isinstance(member, P.ObjectField):
            fields[member.name] = _written(member.type)
    fact: dict = {
        "module": PurePosixPath(source.rel.replace("\\", "/")).stem,
        "methods": methods,
        "structures": structures,
        "enums": enums,
        "fields": fields,
    }
    # The text travels only for a module that casts at all: the reduce types its operands, and
    # a module with no cast has nothing to judge.
    if not errors and _walk_casts(module.members):
        fact["text"] = source.text
    return fact


def _casts_mapper(source: SourceFile) -> dict | None:
    """The per-file half of both rules (they share it - see `_findings`)."""
    cached = source.cache.get("type_casts_fact")
    if cached is not None:
        return cached or None
    fact: dict | None = None
    path = source.rel.replace("\\", "/")
    if source.kind == "yaml" and _HAVE_YAML:
        if PurePosixPath(path).name in _PROJECT_FILES:
            fact = {"k": "project", "root": str(PurePosixPath(path).parent)}
        else:
            element = _element_fact(source)
            if element is not None:
                fact = {"k": "yaml", "stem": _pair_stem(source.rel), "element": element}
    elif source.kind == "xbsl" and not is_query_file(source.path):
        module = _module_fact(source)
        if module is not None:
            fact = {"k": "xbsl", "stem": _pair_stem(source.rel), **module}
    if fact is not None:
        # What the reduce keys its memo by: the same facts twice (the two rules of the module
        # reduce one set of facts) are typed once.
        fact["digest"] = hashlib.sha1(source.text.encode("utf-8")).hexdigest()
    source.cache["type_casts_fact"] = fact or {}
    return fact


# --- the reduce: the catalog, the operands, the verdicts -------------------------------------------

_last: tuple[object, dict[str, list[Diagnostic]]] | None = None
_parsed_texts: dict[str, object] = {}


def _fingerprint(facts: dict[str, dict]) -> object:
    return tuple(sorted((rel, fact.get("digest") or "") for rel, fact in facts.items()))


def _findings(facts: dict[str, dict]) -> dict[str, list[Diagnostic]]:
    """The findings of BOTH rules at once: each rule runs the reduce with the same facts, and
    the typing of every cast of the project is the expensive half."""
    global _last
    key = _fingerprint(facts)
    if _last is not None and _last[0] == key:
        return _last[1]
    found: dict[str, list[Diagnostic]] = {_REDUNDANT: [], _NON_NULL: []}
    for group in _projects(facts).values():
        _judge_project(group, found)
    _last = (key, found)
    return found


def _projects(facts: dict[str, dict]) -> dict[str, dict[str, dict]]:
    """The facts split by project: a run over a folder of several projects keeps their names
    apart (two libraries may both declare a catalog of one name)."""
    roots = sorted({fact["root"] for fact in facts.values() if fact.get("k") == "project"},
                   key=len, reverse=True)
    groups: dict[str, dict[str, dict]] = {}
    for rel, fact in facts.items():
        path = rel.replace("\\", "/")
        owner = next((root for root in roots if path.startswith(root + "/")), "")
        groups.setdefault(owner, {})[rel] = fact
    return groups


def _judge_project(group: dict[str, dict], found: dict[str, list[Diagnostic]]) -> None:
    elements: dict[str, dict] = {}
    duplicated: set[str] = set()
    pairs: dict[str, dict] = {}
    for fact in group.values():
        if fact.get("k") != "yaml":
            continue
        element = fact["element"]
        name = element["name"]
        if name in elements:
            duplicated.add(name)
        elements[name] = element
        pairs[fact["stem"]] = element
    for name in duplicated:
        elements.pop(name, None)
    modules: dict[str, dict] = {}
    for fact in group.values():
        if fact.get("k") == "xbsl":
            if fact["module"] in modules:
                duplicated.add(fact["module"])
            modules[fact["module"]] = fact
    for name in duplicated:
        modules.pop(name, None)
    catalog = typeinfer.ProjectCatalog(elements, modules)
    for rel, fact in sorted(group.items()):
        if fact.get("k") != "xbsl" or "text" not in fact or fact["module"] in duplicated:
            continue
        _judge_module(rel, fact, pairs, catalog, found)


def _parsed_module(fact: dict):
    digest = fact["digest"]
    module = _parsed_texts.get(digest)
    if module is None:
        module, _errors = P.parse_text(fact["text"])
        if len(_parsed_texts) > 512:
            _parsed_texts.clear()
        _parsed_texts[digest] = module
    return module


def _own_names(stem: str, pairs: dict[str, dict]) -> tuple[dict[str, str], frozenset[str]]:
    """What a module reads by a bare name from its paired yaml: ({typed name: type}, opaque).

    An object module (`Товары.Объект.xbsl`) reads the attributes of its element; the module of
    a component reads its properties. Every other name of the paired yaml is something of the
    module whose type is not read here, and it must not resolve to a namesake elsewhere.
    """
    base, dot, facet = stem.rpartition(".")
    element = pairs.get(base) if dot and facet in ("Объект", "Object") else pairs.get(stem)
    if element is None:
        return {}, frozenset()
    typed: dict[str, str] = {}
    if dot and facet in ("Объект", "Object"):
        for section in ("attributes",):
            for name, written in (element.get(section) or {}).items():
                if written:
                    typed[name] = written
    elif element.get("kind") == "КомпонентИнтерфейса":
        for name, written in (element.get("properties") or {}).items():
            if written:
                typed[name] = written
    opaque = frozenset(set(element.get("names") or ()) - set(typed))
    return typed, opaque


def _judge_module(rel: str, fact: dict, pairs: dict[str, dict],
                  catalog: typeinfer.ProjectCatalog, found: dict[str, list[Diagnostic]]) -> None:
    text = fact["text"]
    module = _parsed_module(fact)
    own, opaque = _own_names(fact["stem"], pairs)
    scope = typeinfer.ModuleScope(fact["module"], text, catalog, own, opaque)
    try:
        sites = typeinfer.ModuleTyper(scope).run(module)
    except RecursionError:
        return
    lines = linemap(_TextSource(text))
    tokens: list | None = None
    for site in sites:
        if site.source is None or site.target is None:
            continue
        verdict = typeinfer.cast_verdict(site.source, site.target, catalog.assignable)
        if verdict is None:
            continue
        if tokens is None:
            tokens = [t for t in lexer.tokenize(text) if t.kind not in ("COMMENT", "BOM", "EOF")]
        node = site.node
        line, col = lines.linecol(node.start)
        operand = node.operand
        target = _target_text(text, node)
        if verdict == "redundant":
            exact = site.source == site.target
            key = "code/redundant-cast.found" if exact else "code/redundant-cast.wider"
            found[_REDUNDANT].append(Diagnostic(
                rel, line, col, _REDUNDANT, Severity.WARNING,
                i18n.t(key, source=site.source.text(), target=target),
                fix=_removal(text, tokens, node, operand) if exact else None,
            ))
        else:
            found[_NON_NULL].append(Diagnostic(
                rel, line, col, _NON_NULL, Severity.WARNING,
                i18n.t("code/cast-to-non-null.found", source=site.source.text(), target=target),
                fix=_non_null(text, tokens, node, operand),
            ))


class _TextSource:
    """The minimal source the line map needs: the text and a cache."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.cache: dict = {}


def _target_text(text: str, node) -> str:
    written = getattr(getattr(node, "type", None), "text", None)
    return written or text[node.operand.end:node.end].split(None, 1)[-1]


#: Operands that stay one primary expression without parentheses: a name, a member chain, a
#: call, an index, a `!`, a literal - the parentheses around such an operand group nothing.
_PRIMARY = (P.Name, P.Member, P.Call, P.Index, P.NonNull, P.Literal, P.This)


def _grouping_parens(text: str, tokens: list, node) -> tuple[int, int] | None:
    """The offsets of `(` and `)` that group exactly the cast, or None.

    A parenthesis a call opens is not a grouping one: `Ф(X как Т)` keeps both. What stands
    before the `(` tells them apart - a name or the closing `>` of the arguments of a generic
    call makes it a call; an operator, a keyword or the start of the text makes it a group.
    Only spaces may stand between the parentheses and the cast: a group spread over lines keeps
    its line breaks, and the edit then removes the cast alone.
    """
    left = node.start - 1
    while left >= 0 and text[left] in " \t":
        left -= 1
    right = node.end
    while right < len(text) and text[right] in " \t":
        right += 1
    if left < 0 or right >= len(text) or text[left] != "(" or text[right] != ")":
        return None
    index = next((i for i, token in enumerate(tokens) if token.start == left), None)
    if index is None:
        return None
    before = tokens[index - 1] if index > 0 else None
    if before is not None:
        if before.kind == "IDENT":
            return None
        if before.kind == "OP" and before.value in (">", ")", "]", "!"):
            return None
    return left, right


def _removal(text: str, tokens: list, node, operand) -> TextEdit | None:
    """`X как Т` -> `X`; `(X как Т).Член` -> `X.Член` when X is one primary expression."""
    if node.end <= operand.end:
        return None
    parens = _grouping_parens(text, tokens, node)
    if parens is not None and isinstance(operand, _PRIMARY):
        return TextEdit(parens[0], parens[1] + 1, text[operand.start:operand.end])
    return TextEdit(operand.end, node.end, "")


def _non_null(text: str, tokens: list, node, operand) -> TextEdit | None:
    """`X как Т` -> `X!`; an operand that is not one primary expression keeps its value in
    parentheses: `(А ?? Б)!`."""
    if node.end <= operand.end:
        return None
    operand_text = text[operand.start:operand.end]
    replacement = operand_text + "!" if isinstance(operand, _PRIMARY) else f"({operand_text})!"
    parens = _grouping_parens(text, tokens, node)
    if parens is not None and isinstance(operand, _PRIMARY):
        after = parens[1] + 1
        # `(X как Т)== У` must not become `X!== У`: glued to `=`, the `!` reads as `!=`.
        if after >= len(text) or text[after] != "=":
            return TextEdit(parens[0], parens[1] + 1, replacement)
    return TextEdit(node.start, node.end, replacement)


@rule(
    _REDUNDANT, "code/redundant-cast.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_casts_mapper,
)
def redundant_cast(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`X как Т` where X is already of the type Т holds - the cast changes nothing."""
    return list(_findings(facts)[_REDUNDANT])


@rule(
    _NON_NULL, "code/cast-to-non-null.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_casts_mapper,
)
def cast_to_non_null(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """`X как Т` where X is `Т?` - the cast only drops the empty value, `X!` says the same."""
    return list(_findings(facts)[_NON_NULL])
