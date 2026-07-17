"""Project index for editor navigation (CLI flag --index).

`xbsl --index <root>` prints to stdout a JSON snapshot of the project: objects (kind,
tabular sections, local types declared in modules, the derived member family, enumeration
values), method declarations of every module (together with their annotations), and named
form interface components. Editors use the index for go-to-definition and completion.

The index shape is frozen (fields may be added but not renamed):

    meta       - {root: absolute path in POSIX form, version: linter version};
    objects    - yaml elements with ВидЭлемента: name/kind/path/line, tabular sections,
                 local types of the object's modules (`<Имя>.xbsl`, `<Имя>.<Часть>.xbsl`),
                 the member family for dot completion, enumeration values
                 (Перечисление only);
    methods    - method and constructor declarations of all modules, annotations without `@`;
    components - yaml nodes for КомпонентИнтерфейса that have both Имя and Тип;
    references - usages of indexable names (objects, methods, components) in modules and
                 in yaml handlers: name/qualifier/module/path/line/col - for "find usages"
                 (resolving a concrete target against this list is up to the navigation core).

Paths are written in POSIX form relative to meta.root; lines are numbered from one (the
object's `Имя` key in yaml, a method or structure declaration, an enumeration item, a
component node). Positions in yaml are found by text search over the source text (the
parser keeps no positions, see _value_positions in yaml_types.py); a position that is not
found degrades to line 1 - index building never fails because of this.
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from pathlib import Path

from xbsl import __version__
from xbsl import parser as P
from xbsl.engine import SourceFile, find_sources, load
from xbsl.lexer import linemap, tokens
from xbsl.parser import parse
from xbsl.rules.semantics import _file_local_type_decls, _member_family, _row_type_names
from xbsl.rules.yaml_schema import _HAVE_YAML, _NAME_LINE_RE, _parsed


# --- positions in yaml (text search, like _value_positions in yaml_types.py) -----------

def _name_entries(s: SourceFile) -> list[tuple[int, int, str]]:
    """(offset, indent, value) of every line with an `Имя:` key in the file, in document order."""
    cached = s.cache.get("index-name-entries")
    if cached is None:
        cached = [
            (m.start(), len(m.group(1)), m.group(3))
            for m in _NAME_LINE_RE.finditer(s.text)
        ]
        s.cache["index-name-entries"] = cached
    return cached


def _top_name_line(s: SourceFile, name: str) -> int:
    """Line of the object's top-level `Имя:` key (1 if the key is not found)."""
    for off, indent, value in _name_entries(s):
        if indent == 0 and value == name:
            return linemap(s).linecol(off)[0]
    return 1


def _section_span(text: str, key: str) -> tuple[int, int] | None:
    """Offsets of a top-level section body (`ТабличныеЧасти:` ... the next key at the same level)."""
    m = re.search(rf"(?m)^{key}:[ \t]*(?:#.*)?\r?$", text)
    if m is None:
        return None
    end = re.compile(r"(?m)^[^\s#-]").search(text, m.end())
    return m.end(), end.start() if end else len(text)


def _section_item_lines(s: SourceFile, key: str) -> dict[str, deque[int]]:
    """Per item name: lines of item-level `Имя:` keys within a top-level section.

    Item-level keys are the keys with the minimal indent inside the section; the `Имя` of a
    nested attribute lies deeper and is not selected. The queues keep same-named items in
    document order; the calling code takes one line per parsed item.
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
    """{name, line} of named items of a top-level list section (ТабличныеЧасти/Элементы)."""
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


# --- declarations in modules (token-based) ----------------------------------------------

def _annotations_before(toks: list, i: int) -> list[str]:
    """Annotation names above the declaration keyword at index i, in text order, without `@`.

    The walk goes backwards over `@Имя` and `@Имя(...)` pairs (comments between them are
    skipped, argument parentheses are balanced); the first non-matching token stops the walk.
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
    """{name, line, annotations} of method and constructor declarations of a single module."""
    decls: list[dict] = []
    toks = tokens(s)
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical not in ("METHOD", "CONSTRUCTOR"):
            continue
        if not t.value[:1].islower():
            continue  # the declaration keyword is written in lowercase (as in the handlers rule)
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


# --- references (usages) for "find usages" navigation -----------------------------------

def _prev_significant(toks: list, i: int) -> int:
    """Index of the nearest significant token to the left of i (comments are skipped), or -1."""
    j = i - 1
    while j >= 0 and toks[j].kind == "COMMENT":
        j -= 1
    return j


def _next_significant(toks: list, i: int, n: int) -> int:
    """Index of the nearest significant token to the right of i (comments are skipped), or n."""
    j = i + 1
    while j < n and toks[j].kind == "COMMENT":
        j += 1
    return j


def _module_references(s: SourceFile, referable: set[str], module: str, path: str) -> list[dict]:
    """Usages of indexable names in an .xbsl module: calls, member accesses, chain roots.

    For every identifier token whose value is in referable and which is a call (before `(`),
    a member access (after `.`) or a chain root (before `.`), we emit
    {name, qualifier, module, path, line, col}: qualifier is the identifier before the dot
    (otherwise ""). The name in a method/constructor declaration is skipped - that is a
    definition, not a usage; an annotation name (after `@`) is not counted as a reference.
    Positions: line 1-based, col 0-based (for the editor).
    """
    refs: list[dict] = []
    toks = tokens(s)
    n = len(toks)
    for i, t in enumerate(toks):
        if t.kind != "IDENT" or t.value not in referable:
            continue
        p = _prev_significant(toks, i)
        f = _next_significant(toks, i, n)
        prev = toks[p] if p >= 0 else None
        nxt = toks[f] if f < n else None
        if prev is not None and prev.kind == "OP" and prev.value == "@":
            continue  # annotation name, not a reference
        if prev is not None and prev.kind == "KEYWORD" and prev.canonical in ("METHOD", "CONSTRUCTOR"):
            continue  # a method/constructor declaration is a definition
        after_dot = prev is not None and prev.kind == "OP" and prev.value == "."
        before_dot = nxt is not None and nxt.kind == "OP" and nxt.value == "."
        is_call = nxt is not None and nxt.kind == "OP" and nxt.value == "("
        if not (after_dot or before_dot or is_call):
            continue
        qualifier = ""
        if after_dot:
            q = _prev_significant(toks, p)
            if q >= 0 and toks[q].kind == "IDENT":
                qualifier = toks[q].value
        refs.append({
            "name": t.value,
            "qualifier": qualifier,
            "module": module,
            "path": path,
            "line": t.line,
            "col": t.col - 1,
        })
    return refs


# Handler line in yaml: `Обработчик: ИмяМетода` - the value points to a method of the paired module.
_HANDLER_REF_RE = re.compile(
    r"(?m)^[ \t]*Обработчик:[ \t]*(['\"]?)([A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*)\1[ \t]*(?:#.*)?\r?$"
)


def _handler_references(s: SourceFile, module: str, path: str) -> list[dict]:
    """Method usages via `Обработчик:` in yaml (a method of the form's/object's paired module)."""
    refs: list[dict] = []
    lm = linemap(s)
    for m in _HANDLER_REF_RE.finditer(s.text):
        line, col = lm.linecol(m.start(2))
        refs.append({
            "name": m.group(2),
            "qualifier": "",
            "module": module,
            "path": path,
            "line": line,
            "col": col - 1,
        })
    return refs


# --- form components ------------------------------------------------------------------------

def _component_nodes(node) -> list[tuple[str, str]]:
    """(Имя, Тип) of every yaml node that has both keys; depth-first walk in document order."""
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
    """Named components of a single form together with the lines of their `Имя:` keys."""
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


# --- index ----------------------------------------------------------------------------------

def _discover(root: Path) -> list[Path]:
    """Source files under the root (or the root itself if it is a file), sorted."""
    if root.is_file():
        return [root] if root.suffix in (".xbsl", ".yaml") else []
    return find_sources(root, "*.yaml") + find_sources(root, "*.xbsl")


def build_index(root: Path) -> dict:
    """Project index under root, ready to be printed as JSON (see the module docstring)."""
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

    # Local types by owning object: module files `<Имя>.xbsl` and `<Имя>.<Часть>.xbsl`
    # (matched by name, per the invariant "the name in yaml matches the file name" - as in
    # _project_object_info).
    local_types: dict[str, list[dict]] = defaultdict(list)
    for s in xbsl_sources:
        owner = s.path.name[: -len(".xbsl")].split(".", 1)[0]
        module_path = rel(s.path)
        for name, line in _file_local_type_decls(s):
            local_types[owner].append({"name": name, "path": module_path, "line": line})

    # Members of the module-declared types (structures, exceptions, enumerations) across
    # the project: the dot completion for variables of project types. Namesakes merge -
    # completion is a hint, not a proof.
    struct_members: dict[str, dict] = {}
    for s in xbsl_sources:
        module, errors = parse(s)
        if errors:
            continue
        for m in module.members:
            if isinstance(m, P.Structure):
                rec = {
                    "properties": sorted(
                        f.name for f in m.members if isinstance(f, P.ObjectField)
                    ),
                    "methods": sorted(
                        f.name for f in m.members if isinstance(f, P.Method)
                    ),
                }
            elif isinstance(m, P.Enum):
                rec = {
                    "values": sorted(i.name for i in m.items),
                    "methods": sorted(x.name for x in m.methods),
                }
            else:
                continue
            known = struct_members.get(m.name)
            if known is None:
                struct_members[m.name] = rec
            else:
                for k, v in rec.items():
                    known[k] = sorted(set(known.get(k, ())) | set(v))

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
                "attributes": _named_items(s, data, "Реквизиты"),
                # Register fields live in their own sections - the query completion
                # needs them next to the attributes.
                "dimensions": _named_items(s, data, "Измерения"),
                "resources": _named_items(s, data, "Ресурсы"),
                "local_types": local_types.get(name, []),
            }
            entry["family"] = sorted(
                set(_member_family(kind))
                | {t["name"] for t in entry["tabular"]}
                | {t["name"] for t in entry["local_types"]}
                # the row type a dynamic list names for itself (ИмяТипаДанныхСтроки)
                | _row_type_names(data)
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

    # Usages (for "find usages"): names of objects, components and methods encountered as a
    # call/member/chain root in modules, plus methods in yaml handlers. Resolving a concrete
    # target (a method of module X, an object, a form component) is done by the navigation
    # core against this list.
    referable = (
        {o["name"] for o in objects}
        | {c["name"] for c in components}
        | {m["name"] for m in methods}
    )
    references: list[dict] = []
    for s in xbsl_sources:
        module = s.path.name[: -len(".xbsl")]
        references.extend(_module_references(s, referable, module, rel(s.path)))
    for s in yaml_sources:
        references.extend(_handler_references(s, s.path.stem, rel(s.path)))

    return {
        "meta": {"root": base.as_posix(), "version": __version__},
        "objects": objects,
        "methods": methods,
        "components": components,
        "references": references,
        "struct_members": struct_members,
    }
