"""The project index for editor navigation (the CLI --index flag).

`xbsllint --index <root>` dumps a JSON snapshot of the project to stdout: the objects (kind,
tabular sections, module-declared local types, the generated member family, enumeration
values), the method declarations of every module (with their annotations), and the named
interface components of the forms. Editors consume it for go-to-definition and completion.

The shape is frozen (fields may be added, never renamed):

    meta       – {root: absolute POSIX path, version: the linter version};
    objects    – yaml elements with ВидЭлемента: name/kind/path/line, tabular sections,
                 local types of the object's modules (`<Имя>.xbsl`, `<Имя>.<Часть>.xbsl`),
                 the member family for dot completion, enum values (Перечисление only);
    methods    – method/constructor declarations of all modules, annotations without `@`;
    components – nodes with both Имя and Тип in the yaml of a КомпонентИнтерфейса.

Paths are POSIX and relative to meta.root; lines are 1-based (the object's `Имя` key in
yaml, the declaration of a method or structure, an enumeration element, a component node).
yaml positions are found by a text search over the original source (the parser keeps no
positions, see _value_positions in yaml_types.py); a position that cannot be found degrades
to line 1 – building the index never fails on it.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path

from xbsllint import __version__
from xbsllint.engine import SourceFile, load
from xbsllint.lexer import linemap, tokens
from xbsllint.rules.semantics import _file_local_type_decls, _member_family
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

# A `Имя:` key line: indent (a list-item dash counts as indent), an optionally quoted value,
# an optional trailing comment; `\r?` keeps CRLF files matching (`$` anchors before `\n`).
_NAME_LINE_RE = re.compile(
    r"(?m)^([ \t]*(?:-[ \t]+)?)Имя:[ \t]*(['\"]?)([^\r\n#]*?)\2[ \t]*(?:#.*)?\r?$"
)


# --- yaml positions (text search, mirroring _value_positions in yaml_types.py) ---------

def _name_entries(s: SourceFile) -> list[tuple[int, int, str]]:
    """(offset, indent, value) of every `Имя:` key line of the file, in document order."""
    cached = s.cache.get("index-name-entries")
    if cached is None:
        cached = [
            (m.start(), len(m.group(1)), m.group(3))
            for m in _NAME_LINE_RE.finditer(s.text)
        ]
        s.cache["index-name-entries"] = cached
    return cached


def _top_name_line(s: SourceFile, name: str) -> int:
    """The line of the top-level `Имя:` key of the object (1 when not found)."""
    for off, indent, value in _name_entries(s):
        if indent == 0 and value == name:
            return linemap(s).linecol(off)[0]
    return 1


def _section_span(text: str, key: str) -> tuple[int, int] | None:
    """The offsets of a top-level section body (`ТабличныеЧасти:` ... the next top-level key)."""
    m = re.search(rf"(?m)^{key}:[ \t]*\r?$", text)
    if m is None:
        return None
    end = re.compile(r"(?m)^[^\s#-]").search(text, m.end())
    return m.end(), end.start() if end else len(text)


def _section_item_lines(s: SourceFile, key: str) -> dict[str, deque[int]]:
    """Per item name: the lines of the item-level `Имя:` keys of a top-level section.

    Item-level keys are the ones at the minimal indentation inside the section – the `Имя` of
    a nested attribute lies deeper and is left out. Queues keep same-named items in document
    order; the caller pops one line per parsed item.
    """
    span = _section_span(s.text, key)
    if span is None:
        return {}
    lo, hi = span
    inside = [(off, indent, value) for off, indent, value in _name_entries(s) if lo <= off < hi]
    if not inside:
        return {}
    level = min(indent for _, indent, _ in inside)
    lm = linemap(s)
    queues: dict[str, deque[int]] = defaultdict(deque)
    for off, indent, value in inside:
        if indent == level:
            queues[value].append(lm.linecol(off)[0])
    return queues


def _named_items(s: SourceFile, data: dict, key: str) -> list[dict]:
    """{name, line} of the named items of a top-level list section (ТабличныеЧасти/Элементы)."""
    items = data.get(key)
    if not isinstance(items, list):
        return []
    queues = _section_item_lines(s, key)
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("Имя"), str):
            name = item["Имя"]
            q = queues.get(name)
            out.append({"name": name, "line": q.popleft() if q else 1})
    return out


# --- module declarations (over tokens) -------------------------------------------------

def _annotations_before(toks: list, i: int) -> list[str]:
    """The annotation names above a declaration keyword at index i, in source order, without `@`.

    Walks backwards over `@Имя` and `@Имя(...)` pairs (comments in between are skipped, the
    argument parentheses are balanced); the first token that does not fit stops the walk.
    """
    names: list[str] = []
    k = i - 1
    while k >= 0:
        while k >= 0 and toks[k].kind == "COMMENT":
            k -= 1
        if k >= 0 and toks[k].kind == "OP" and toks[k].value == ")":
            depth = 1
            k -= 1
            while k >= 0 and depth:
                if toks[k].kind == "OP":
                    if toks[k].value == ")":
                        depth += 1
                    elif toks[k].value == "(":
                        depth -= 1
                k -= 1
            while k >= 0 and toks[k].kind == "COMMENT":
                k -= 1
        if (
            k >= 1
            and toks[k].kind == "IDENT"
            and toks[k - 1].kind == "OP"
            and toks[k - 1].value == "@"
        ):
            names.append(toks[k].value)
            k -= 2
            continue
        break
    names.reverse()
    return names


def _method_decls(s: SourceFile) -> list[dict]:
    """{name, line, annotations} of the method/constructor declarations of one module."""
    decls: list[dict] = []
    toks = tokens(s)
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical not in ("METHOD", "CONSTRUCTOR"):
            continue
        if not t.value[:1].islower():
            continue  # a declaration keyword is lowercase (as in the handlers rule)
        j = i + 1
        while j < n and toks[j].kind == "COMMENT":
            j += 1
        if j < n and toks[j].kind == "IDENT":
            decls.append({
                "name": toks[j].value,
                "line": toks[j].line,
                "annotations": _annotations_before(toks, i),
            })
    return decls


# --- form components --------------------------------------------------------------------

def _component_nodes(node) -> list[tuple[str, str]]:
    """(Имя, Тип) of every yaml node carrying both, depth-first in document order."""
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        name, typ = node.get("Имя"), node.get("Тип")
        if isinstance(name, str) and isinstance(typ, str):
            found.append((name, typ))
        for value in node.values():
            found.extend(_component_nodes(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_component_nodes(item))
    return found


def _form_components(s: SourceFile, data: dict, form: str, path: str) -> list[dict]:
    """The named components of one form, with the lines of their `Имя:` keys."""
    lm = linemap(s)
    queues: dict[str, deque[int]] = defaultdict(deque)
    for off, indent, value in _name_entries(s):
        if indent > 0:  # the top-level Имя is the form itself, not a component
            queues[value].append(lm.linecol(off)[0])
    out: list[dict] = []
    for name, typ in _component_nodes(data):
        q = queues.get(name)
        out.append({
            "form": form,
            "name": name,
            "type": typ,
            "path": path,
            "line": q.popleft() if q else 1,
        })
    return out


# --- the index ---------------------------------------------------------------------------

def _discover(root: Path) -> list[Path]:
    """Source files under the root (or the root itself when it is a file), sorted."""
    if root.is_file():
        return [root] if root.suffix in (".xbsl", ".yaml") else []
    return sorted(root.rglob("*.yaml")) + sorted(root.rglob("*.xbsl"))


def build_index(root: Path) -> dict:
    """The JSON-ready index of the project under root (see the module docstring)."""
    base = (root if root.is_dir() else root.parent).resolve()
    sources = [load(p) for p in _discover(root)]
    yaml_sources = [s for s in sources if s.kind == "yaml"]
    xbsl_sources = [s for s in sources if s.kind == "xbsl"]

    def rel(p: Path) -> str:
        rp = p.resolve()
        try:
            return rp.relative_to(base).as_posix()
        except ValueError:
            return rp.as_posix()

    # Local types per owner object: the module files `<Имя>.xbsl` and `<Имя>.<Часть>.xbsl`
    # (matched by name, per the yaml/name-matches-file invariant – as _project_object_info).
    local_types: dict[str, list[dict]] = defaultdict(list)
    for s in xbsl_sources:
        owner = s.path.name[: -len(".xbsl")].split(".", 1)[0]
        module_path = rel(s.path)
        for name, line in _file_local_type_decls(s):
            local_types[owner].append({"name": name, "path": module_path, "line": line})

    objects: list[dict] = []
    components: list[dict] = []
    if _HAVE_YAML:
        for s in yaml_sources:
            data, err = _parsed(s)
            if err is not None or not isinstance(data, dict):
                continue
            name, kind = data.get("Имя"), data.get("ВидЭлемента")
            if not isinstance(name, str) or not isinstance(kind, str):
                continue
            entry: dict = {
                "name": name,
                "kind": kind,
                "path": rel(s.path),
                "line": _top_name_line(s, name),
                "tabular": _named_items(s, data, "ТабличныеЧасти"),
                "local_types": local_types.get(name, []),
            }
            entry["family"] = sorted(
                set(_member_family(kind))
                | {t["name"] for t in entry["tabular"]}
                | {t["name"] for t in entry["local_types"]}
            )
            if kind == "Перечисление":
                entry["values"] = _named_items(s, data, "Элементы")
            objects.append(entry)
            if kind == "КомпонентИнтерфейса":
                components.extend(_form_components(s, data, name, entry["path"]))

    methods: list[dict] = []
    for s in xbsl_sources:
        module = s.path.name[: -len(".xbsl")]
        module_path = rel(s.path)
        for decl in _method_decls(s):
            methods.append({
                "module": module,
                "name": decl["name"],
                "path": module_path,
                "line": decl["line"],
                "annotations": decl["annotations"],
            })

    return {
        "meta": {"root": base.as_posix(), "version": __version__},
        "objects": objects,
        "methods": methods,
        "components": components,
    }
