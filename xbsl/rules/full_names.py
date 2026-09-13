"""Tier D: a full name that leads to a namespace where its element does not lie.

`Vendor::Project::Subsystem[::Package]::Name` addresses an element absolutely (the documentation
pages on namespaces and on modular development): the qualifiers spell the placement of the
element, and the compiler looks for it there and nowhere else. When an element moves between the root of a
subsystem and a package, or from one package to another, every full name written for it goes
stale and the build answers `Неизвестный тип`. The live case: a subsystem was split into
packages, and the generated list forms kept their row type as
`Поставщик::Проект::Подсистема::ФормаСписка.ДанныеСтрокиСписка` without the segment of the
package - the linter had no reading of such a name at all (yaml/unknown-type does not parse
`::`), and the refusals came from the server build.

Two rules, one per side, the way the import and the visibility rules are split:
yaml/wrong-namespace reads the string values of a yaml - of an element and of a descriptor (a
type, a table of a dynamic list, a form, the application a project descriptor names),
code/wrong-namespace reads a module and a standalone query, the query blocks included: that is
where full names are written most, in the tables of a query.

The check is narrow on purpose:

- only a name whose first two qualifiers are the vendor and the name of the project the file
  belongs to is judged. A library or another project lies outside the sources, and a partial
  name (`Подсистема::Имя`) shares its shape with a resource key (`Подсистема::путь/файл.svg`);
- only an element the project declares is judged, and only when no element of that name lies
  at the written namespace: a name nobody declares is unknown rather than misplaced, and a type
  declared inside a module is not an element and is left alone as well;
- the lists of namespaces (`Import`, `Using`, the import line of a module) hold namespaces,
  not elements, and are not read; neither is a resource reference - a name followed by a path
  separator or a file extension, or the key of a `Resource{...}` literal.

The repair is mechanical when the element lies in one place: the namespace is replaced by the
placement of the element, and the finding carries that edit. Two elements of the name in two
places leave the choice to the author.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
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
}
MESSAGES = {
    f"{side}/wrong-namespace.{key}": text
    for side in ("yaml", "code") for key, text in _TEXTS.items()
}
i18n.register(MESSAGES)

#: A full name inside a string: three qualifiers at least - the vendor, the project, the
#: subsystem - and the element. Nothing that continues a name may stand before it; `$` may,
#: a localization reference names its dictionary the same way.
_FULL_NAME = re.compile(r"(?<![\w.:])((?:[^\W\d]\w*::){3,})([^\W\d]\w*)")

#: What turns a name into a resource reference: a path separator or a file extension after it.
_RESOURCE_TAIL = re.compile(r"/|\.[a-z0-9]+(?!\w)")


@lru_cache(maxsize=1)
def _namespace_list_keys() -> frozenset[str]:
    """The yaml keys whose values are namespaces rather than elements, both spellings."""
    return frozenset((*_key_spellings("Импорт"), *_usage_keys()))


dataset.register_reset(_namespace_list_keys.cache_clear)


def _yaml_full_names(source: SourceFile) -> list[list]:
    """Full names in the string values of a yaml, in file order.

    Each entry is [qualifiers, element, start and end of the namespace to replace, line, col,
    the name as written]. The values are taken from the composed graph, so a comment and a
    mapping key are never read, and the offsets are those of the raw text: a qualified name
    carries no character a quoted scalar would escape.
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
            for match in _FULL_NAME.finditer(raw):
                if _RESOURCE_TAIL.match(raw, match.end()):
                    continue
                qualifiers = match.group(1)[:-2].split("::")
                head = len(qualifiers[0]) + len(qualifiers[1]) + 4
                lm = lm or linemap(source)
                line, col = lm.linecol(start + match.start())
                found.append([qualifiers, match.group(2), start + match.start(1) + head,
                              start + match.end(1) - 2, line, col, match.group(0)])
    return sorted(found, key=lambda entry: entry[2])


@lru_cache(maxsize=1)
def _resource_words() -> frozenset[str]:
    """Both spellings of the resource literal, whose braces hold a file key, not a name."""
    return frozenset(terms.key_forms("Ресурс"))


dataset.register_reset(_resource_words.cache_clear)


def _code_full_names(source: SourceFile) -> list[list]:
    """Full names in the code of a module or a query, in the shape of `_yaml_full_names`.

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
        if len(parts) >= 4 and not (imported or resource or file_like):
            qualifiers = [t.value for t in parts[:-1]]
            found.append([qualifiers, parts[-1].value, parts[2].start, parts[-2].end,
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


def _yaml_mapper(source: SourceFile) -> dict | None:
    """The map phase of yaml/wrong-namespace: a descriptor contributes its place in the layout
    and the full names of its values, an element yaml its placement and its full names, a
    module the types it declares."""
    if source.kind == "xbsl":
        local = _local_types(source)
        return {"k": "x", "local_types": local} if local else None
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    fact = _layout_fact(source) or _element_fact(source)
    if fact is None:
        return None
    names = _yaml_full_names(source)
    return {**fact, "path": str(source.path), "full": names} if names else fact


def _code_mapper(source: SourceFile) -> dict | None:
    """The map phase of code/wrong-namespace: a descriptor contributes its place in the layout,
    an element yaml its placement, a module or a query its full names and declared types."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        return _layout_fact(source) or _element_fact(source)
    if source.kind != "xbsl":
        return None
    try:
        names = _code_full_names(source)
    except DatasetError:
        return None  # no language data - the module cannot be tokenized
    local = _local_types(source)
    if not names and not local:
        return None
    return {"k": "mod", "path": str(source.path), "full": names, "local_types": local}


def _judge(facts: dict[str, dict], rule_id: str) -> Iterable[Diagnostic]:
    """The reduce of both rules: a full name of this project against where its element lies."""
    layout = _layout_from(facts)
    if not layout.projects:
        return  # without the project descriptor the vendor and the project are unknown
    local_types: set[str] = set()
    placement: dict[tuple[Path, str], set[str]] = {}
    for fact in facts.values():
        local_types.update(fact.get("local_types", ()))
        if fact["k"] != "el" or not fact["name"]:
            continue
        place = layout.place(Path(fact["path"]))
        if place is not None and place.project_dir is not None:
            placement.setdefault((place.project_dir, fact["name"]), set()).add(place.key)
    for rel, fact in facts.items():
        if not fact.get("full"):
            continue
        project_dir = layout.project_dir_of(Path(fact["path"]))
        identity = layout.identity(project_dir)
        if project_dir is None or identity is None:
            continue
        own = "::".join(identity)
        for qualifiers, name, start, end, line, col, written in fact["full"]:
            if qualifiers[:2] != list(identity) or name in local_types:
                continue
            owners = placement.get((project_dir, name))
            if not owners or "::".join(qualifiers[2:]) in owners:
                continue
            actual = [f"{own}::{key}" for key in sorted(owners)]
            key = "moved" if len(owners) == 1 else "ambiguous"
            yield Diagnostic(
                rel, line, col, rule_id, Severity.ERROR,
                i18n.t(f"{rule_id}.{key}", written=written, namespace="::".join(qualifiers),
                       name=name, actual="/".join(actual)),
                fix=TextEdit(start, end, sorted(owners)[0]) if len(owners) == 1 else None,
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
