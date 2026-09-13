"""Tier D: a qualified name that leads to a namespace where its element does not lie.

`Vendor::Project::Subsystem[::Package]::Name` addresses an element absolutely (the documentation
pages on namespaces and on modular development): the qualifiers spell the placement of the
element, and the compiler looks for it there and nowhere else. When an element moves between the root of a
subsystem and a package, or from one package to another, every full name written for it goes
stale and the build answers `Неизвестный тип`. The live case: a subsystem was split into
packages, and the generated list forms kept their row type as
`Поставщик::Проект::Подсистема::ФормаСписка.ДанныеСтрокиСписка` without the segment of the
package - the linter had no reading of such a name at all (yaml/unknown-type does not parse
`::`), and the refusals came from the server build.

The partial name, `Subsystem[::Package]::Name`, is the same address without the prefix of the
project - the documentation keeps it for the elements of the project itself, a library being
reached by its full name - and it goes stale the same way. A server build refused a partial
name without the segment of the package in each position it was tried in: a type of a yaml
property (`Неизвестный тип`), a type and a query table of a module, and the table of a dynamic
list, every message spelling the name in full; the same names with the segment compiled clean.

Two rules, one per side, the way the import and the visibility rules are split:
yaml/wrong-namespace reads the string values of a yaml - of an element and of a descriptor (a
type, a table of a dynamic list, a form, the application a project descriptor names),
code/wrong-namespace reads a module and a standalone query, the query blocks included: that is
where full names are written most, in the tables of a query.

The check is narrow on purpose:

- a full name is judged when its first two qualifiers are the vendor and the name of the
  project the file belongs to: a library or another project lies outside the sources;
- a partial name is judged when its first qualifier is a subsystem of that project, and only
  when the element lies in one place - two places leave the chain open to more than one reading.
  A first qualifier that a declared library also uses - its vendor or one of its subsystems, read
  from the archive next to the sources (xbsl.libs) - is not judged, and a declared library whose
  archive is not found leaves every partial name of the project alone;
- only an element the project declares is judged, and only when no element of that name lies
  at the written namespace: a name nobody declares is unknown rather than misplaced, and a type
  declared inside a module is not an element and is left alone as well. A chain that spells a
  namespace of the project whole (`Subsystem::Package`, a package holding a namesake element)
  names the namespace, not the element;
- the lists of namespaces (`Import`, `Using`, the import line of a module) hold namespaces,
  not elements, and are not read; neither is a resource reference - a name followed by a path
  separator or a file extension, or the key of a `Resource{...}` literal. A partial name shares
  its shape with a resource key (`Подсистема::путь/файл.svg`), which is why the tail is checked.

The repair is mechanical when the element lies in one place: the namespace is replaced by the
placement of the element, and the finding carries that edit. Two elements of the name in two
places leave the choice to the author. Like the findings of the import and visibility rules
(xbsl.rules.yaml_imports), a finding carries its facts in `Diagnostic.data` for a repair to
read: `{"name": <the element>, "namespace": <the written placement>, "namespaces": [<where
the element lies>]}`, placements without the prefix of the project.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, libs, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity, TextEdit
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.rules import semantics
from xbsl.rules.yaml_imports import _layout_fact, _layout_from, _usage_keys
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _parsed,
    object_kind,
    unreadable_object,
    value_of,
    yaml,
)
from xbsl.rules.yaml_types import _key_spellings

_TEXTS = {
    "title": {
        "ru": "Полное имя ведёт не в то пространство имён",
        "en": "A full name leads to the wrong namespace",
    },
    "moved": {
        "ru": "Полное имя '{written}' ведёт в пространство имён '{namespace}', а элемент '{name}' "
              "лежит в '{actual}': компилятор его там не найдёт (\"Неизвестный тип\"). Нужен "
              "префикс '{actual}::'.",
        "en": "The full name '{written}' leads to namespace '{namespace}', while element "
              "'{name}' lies in '{actual}': the compiler does not find it there (\"Unknown "
              "type\"). The prefix must be '{actual}::'.",
    },
    "ambiguous": {
        "ru": "Полное имя '{written}' ведёт в пространство имён '{namespace}', а элементы "
              "'{name}' лежат в '{actual}': компилятор его там не найдёт (\"Неизвестный тип\"). "
              "Укажите пространство имён нужного элемента.",
        "en": "The full name '{written}' leads to namespace '{namespace}', while the elements "
              "named '{name}' lie in '{actual}': the compiler does not find it there (\"Unknown "
              "type\"). Name the namespace of the element meant.",
    },
    "partial": {
        "ru": "Частичное имя '{written}' ведёт в пространство имён '{namespace}', а элемент "
              "'{name}' лежит в '{actual}': компилятор его там не найдёт (\"Неизвестный тип\"). "
              "Нужен префикс '{actual}::'.",
        "en": "The partial name '{written}' leads to namespace '{namespace}', while element "
              "'{name}' lies in '{actual}': the compiler does not find it there (\"Unknown "
              "type\"). The prefix must be '{actual}::'.",
    },
}
MESSAGES = {
    f"{side}/wrong-namespace.{key}": text
    for side in ("yaml", "code") for key, text in _TEXTS.items()
}
i18n.register(MESSAGES)

#: A qualified name inside a string: a qualifier at least and the element. Nothing that
#: continues a name may stand before it; `$` may, a localization reference names its dictionary
#: the same way. Whether the chain is a full name of the project, a partial one or nothing of
#: the project is decided in the reduce, which knows the project and its subsystems.
_QUALIFIED_NAME = re.compile(r"(?<![\w.:])((?:[^\W\d]\w*::)+)([^\W\d]\w*)")

#: What turns a name into a resource reference: a path separator or a file extension after it.
_RESOURCE_TAIL = re.compile(r"/|\.[a-z0-9]+(?!\w)")


@lru_cache(maxsize=1)
def _namespace_list_keys() -> frozenset[str]:
    """The yaml keys whose values are namespaces rather than elements, both spellings."""
    return frozenset((*_key_spellings("Импорт"), *_usage_keys()))


dataset.register_reset(_namespace_list_keys.cache_clear)


def _yaml_qualified_names(source: SourceFile) -> list[list]:
    """Qualified names in the string values of a yaml, in file order.

    Each entry is [qualifiers, element, the offset of the chain, the offset after the first two
    qualifiers (None for a shorter chain), the end of the last qualifier, line, col, the name as
    written]: the reduce replaces the namespace from the first offset for a partial name and
    from the second for a full one. The values are taken from the composed graph, so a comment
    and a mapping key are never read, and the offsets are those of the raw text: a qualified
    name carries no character a quoted scalar would escape.
    """
    if not _HAVE_YAML or "::" not in source.text:
        return []
    root = _composed(source)
    if root is None:
        return []
    skip = _namespace_list_keys()
    found: list[list] = []
    lm = None
    stack = [root]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:  # an anchor may alias the same node twice
            continue
        seen.add(id(node))
        if isinstance(node, yaml.MappingNode):
            stack.extend(value for key, value in node.value
                         if not (isinstance(key, yaml.ScalarNode) and key.value in skip))
        elif isinstance(node, yaml.SequenceNode):
            stack.extend(node.value)
        elif isinstance(node, yaml.ScalarNode) and "::" in node.value:
            start = node.start_mark.index
            raw = source.text[start:node.end_mark.index]
            for match in _QUALIFIED_NAME.finditer(raw):
                if _RESOURCE_TAIL.match(raw, match.end()):
                    continue
                qualifiers = match.group(1)[:-2].split("::")
                chain = start + match.start(1)
                full = (chain + len(qualifiers[0]) + len(qualifiers[1]) + 4
                        if len(qualifiers) >= 3 else None)
                lm = lm or linemap(source)
                line, col = lm.linecol(start + match.start())
                found.append([qualifiers, match.group(2), chain, full,
                              start + match.end(1) - 2, line, col, match.group(0)])
    return sorted(found, key=lambda entry: entry[2])


@lru_cache(maxsize=1)
def _resource_words() -> frozenset[str]:
    """Both spellings of the resource literal, whose braces hold a file key, not a name."""
    return frozenset(terms.key_forms("Ресурс"))


dataset.register_reset(_resource_words.cache_clear)


def _code_qualified_names(source: SourceFile) -> list[list]:
    """Qualified names in the code of a module or a query, in the shape of
    `_yaml_qualified_names`.

    Tokens, not text: a name inside a string or a comment is not code. The chain is read whole
    and judged once; the import line names a namespace and the key of a resource literal names
    a file, so neither is read.
    """
    if "::" not in source.text:
        return []
    toks = [t for t in tokens(source) if t.kind not in ("COMMENT", "BOM", "EOF")]
    words = ("IDENT", "KEYWORD")
    found: list[list] = []
    i, n = 0, len(toks)
    while i < n:
        if toks[i].kind not in words or not (i + 1 < n and toks[i + 1].kind == "OP"
                                             and toks[i + 1].value == "::"):
            i += 1
            continue
        parts = [toks[i]]
        j = i + 1
        while (j + 1 < n and toks[j].kind == "OP" and toks[j].value == "::"
               and toks[j + 1].kind in words):
            parts.append(toks[j + 1])
            j += 2
        before = toks[i - 1] if i else None
        behind = toks[i - 2] if i > 1 else None
        after = toks[j] if j < n else None
        imported = before is not None and before.kind == "KEYWORD" and before.canonical == "IMPORT"
        resource = (before is not None and before.kind == "OP" and before.value == "{"
                    and behind is not None and behind.value in _resource_words())
        file_like = after is not None and after.kind == "OP" and (
            after.value == "/" or (after.value == "." and j + 1 < n
                                   and re.fullmatch(r"[a-z0-9]+", toks[j + 1].value)))
        if len(parts) >= 2 and not (imported or resource or file_like):
            qualifiers = [t.value for t in parts[:-1]]
            found.append([qualifiers, parts[-1].value, parts[0].start,
                          parts[2].start if len(parts) >= 4 else None, parts[-2].end,
                          parts[0].line, parts[0].col, source.text[parts[0].start:parts[-1].end]])
        i = j
    return found


def _element_fact(source: SourceFile) -> dict | None:
    """The placement slice of an element yaml - its name and path - or None for another yaml.

    A file that does not parse still declares its element where it lies: dropping it would
    turn a correct full name of that element into a report against a namesake elsewhere.
    """
    data, err = _parsed(source)
    if err is not None:
        name = unreadable_object(source)
        return {"k": "el", "path": str(source.path), "name": name} if name else None
    kind = object_kind(data)
    if not isinstance(data, dict) or not kind:
        return None
    name = value_of(data, "Имя", kind)
    return {"k": "el", "path": str(source.path),
            "name": name if isinstance(name, str) else source.path.stem}


def _local_types(source: SourceFile) -> list[str]:
    """The types a module declares (structures, enumerations, exceptions), or none without data."""
    try:
        return sorted(semantics._file_local_types(source))
    except DatasetError:
        return []


def _library_names(source: SourceFile) -> dict:
    """What the libraries of a project descriptor may share with a partial name of the project.

    A library is addressed by its full name, yet a first qualifier that is also its vendor or
    one of its subsystems leaves a partial name of the project to more than one reading, and
    such a name is left alone. The subsystems come from the archive next to the sources; a
    declared library whose archive is not found leaves them unknown.
    """
    names: set[str] = set()
    unknown = False
    for vendor, name, version in libs.declared_libraries(source.text):
        names.add(vendor)
        archive = libs.find_archive(source.path, vendor, name, version)
        if archive is None:
            unknown = True
        else:
            names |= libs.archive_subsystems(archive)
    return {"lib_names": sorted(names), "lib_unknown": unknown}


def _descriptor_or_element_fact(source: SourceFile) -> dict | None:
    """The layout fact of a descriptor - a project descriptor with what its libraries name - or
    the placement slice of an element yaml."""
    fact = _layout_fact(source)
    if fact is not None and fact["k"] == "proj":
        return {**fact, **_library_names(source)}
    return fact or _element_fact(source)


def _yaml_mapper(source: SourceFile) -> dict | None:
    """The map phase of yaml/wrong-namespace: a descriptor contributes its place in the layout
    and the qualified names of its values, an element yaml its placement and its qualified
    names, a module the types it declares."""
    if source.kind == "xbsl":
        local = _local_types(source)
        return {"k": "x", "local_types": local} if local else None
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    fact = _descriptor_or_element_fact(source)
    if fact is None:
        return None
    names = _yaml_qualified_names(source)
    return {**fact, "path": str(source.path), "full": names} if names else fact


def _code_mapper(source: SourceFile) -> dict | None:
    """The map phase of code/wrong-namespace: a descriptor contributes its place in the layout,
    an element yaml its placement, a module or a query its qualified names and declared types."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        return _descriptor_or_element_fact(source)
    if source.kind != "xbsl":
        return None
    try:
        names = _code_qualified_names(source)
    except DatasetError:
        return None  # no language data - the module cannot be tokenized
    local = _local_types(source)
    if not names and not local:
        return None
    return {"k": "mod", "path": str(source.path), "full": names, "local_types": local}


def _judge(facts: dict[str, dict], rule_id: str) -> Iterable[Diagnostic]:
    """The reduce of both rules: a qualified name of this project against where its element lies."""
    layout = _layout_from(facts)
    if not layout.projects:
        return  # without the project descriptor the vendor and the project are unknown
    local_types: set[str] = set()
    placement: dict[tuple[Path, str], set[str]] = {}
    subsystems: dict[Path, set[str]] = {}
    for fact in facts.values():
        local_types.update(fact.get("local_types", ()))
        if fact["k"] == "sub":
            project_dir = layout.project_dir_of(Path(fact["dir"]))
            if project_dir is not None:
                subsystems.setdefault(project_dir, set()).add(fact["name"])
            continue
        if fact["k"] != "el" or not fact["name"]:
            continue
        place = layout.place(Path(fact["path"]))
        if place is not None and place.project_dir is not None:
            placement.setdefault((place.project_dir, fact["name"]), set()).add(place.key)
            subsystems.setdefault(place.project_dir, set()).add(place.subsystem)
    # Every namespace an element of the project lies in, the enclosing packages included: a
    # chain that spells one whole names the namespace rather than an element.
    namespaces = {
        (project_dir, "::".join(parts[:end]))
        for (project_dir, _name), keys in placement.items() for key in keys
        for parts in (key.split("::"),) for end in range(1, len(parts) + 1)
    }
    libraries = {Path(f["dir"]): f for f in facts.values() if f["k"] == "proj"}
    for rel, fact in facts.items():
        if not fact.get("full"):
            continue
        project_dir = layout.project_dir_of(Path(fact["path"]))
        identity = layout.identity(project_dir)
        if project_dir is None or identity is None:
            continue
        own = "::".join(identity)
        described = libraries.get(project_dir, {})
        # A first qualifier a partial name may not start with: the vendor of the project and
        # whatever its libraries name; an unread library leaves no partial name judged.
        foreign = {identity[0], *described.get("lib_names", ())}
        partial_judged = not described.get("lib_unknown", False)
        for qualifiers, name, chain, full_start, end, line, col, written in fact["full"]:
            if name in local_types:
                continue
            full = len(qualifiers) >= 3 and qualifiers[:2] == list(identity)
            if full:
                written_key, start = "::".join(qualifiers[2:]), full_start
            elif (partial_judged and qualifiers[0] in subsystems.get(project_dir, ())
                    and qualifiers[0] not in foreign):
                written_key, start = "::".join(qualifiers), chain
            else:
                continue
            owners = placement.get((project_dir, name))
            if not owners or written_key in owners:
                continue
            if (project_dir, f"{written_key}::{name}") in namespaces:
                continue
            if not full and len(owners) > 1:
                continue  # a partial name of an element in several places is left to the author
            if full:
                actual = [f"{own}::{key}" for key in sorted(owners)]
                key = "moved" if len(owners) == 1 else "ambiguous"
                namespace = "::".join(qualifiers)
            else:
                actual, key, namespace = sorted(owners), "partial", written_key
            yield Diagnostic(
                rel, line, col, rule_id, Severity.ERROR,
                i18n.t(f"{rule_id}.{key}", written=written, namespace=namespace,
                       name=name, actual="/".join(actual)),
                fix=TextEdit(start, end, sorted(owners)[0]) if len(owners) == 1 else None,
                data={"name": name, "namespace": written_key, "namespaces": sorted(owners)},
            )


@rule(
    "yaml/wrong-namespace", "yaml/wrong-namespace.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_yaml_mapper,
)
def yaml_wrong_namespace(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    yield from _judge(facts, "yaml/wrong-namespace")


@rule(
    "code/wrong-namespace", "code/wrong-namespace.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_code_mapper,
)
def code_wrong_namespace(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    yield from _judge(facts, "code/wrong-namespace")
