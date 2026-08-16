"""Project index for editor navigation (CLI flag --index).

`xbsl --index <root>` prints to stdout a JSON snapshot of the project: objects (kind,
tabular sections, local types declared in modules, the derived member family, enumeration
values), method declarations of every module (together with their annotations), and named
form interface components. Editors use the index for go-to-definition and completion.

The index shape is frozen (fields may be added but not renamed):

    meta       - {root: absolute path in POSIX form, version: linter version};
    objects    - yaml elements with ВидЭлемента: name/kind/path/line, tabular sections,
                 local types of the object's modules (`<Имя>.xbsl`, `<Имя>.<Часть>.xbsl`),
                 the member family and the singleton-type members (`manager`) for dot
                 completion, enumeration values (`Перечисление` only);
    methods    - method and constructor declarations of all modules, annotations without `@`,
                 the parameter list as written, the return type head and the description
                 comment above the declaration;
    components - yaml nodes for КомпонентИнтерфейса that have both Имя and Тип;
    references - usages of indexable names (objects, methods, components) in modules and
                 in yaml handlers: name/qualifier/module/path/line/col - for "find usages"
                 (resolving a concrete target against this list is up to the navigation core);
    struct_members    - members of a project TYPE by its name: the structures, exceptions and
                 enumerations declared in modules, plus the types described in metadata
                 (a structure's Fields, a constants set's Constants under `<Name>.Record`
                 and `<Name>.Data`) - {properties, methods, values, kind};
    generated_returns - {type name: {method: result type}} for the methods the PLATFORM
                 generates on a project object (a constants set `Rates` answers `Rates.Get()`
                 with a `Rates.Record`): the stdlib catalogue knows nothing about a project
                 object, so without them a chain over such a call stays untyped.

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
from xbsl import dataset, metamodel, terms
from xbsl.dataset import PLACEHOLDER
from xbsl.engine import SourceFile, find_sources, load
from xbsl.lexer import Token, linemap, tokens
from xbsl.parser import parse
from xbsl.rules._syntax import (
    _skip_balanced,
    _type_head,
    code_tokens,
    signatures,
    type_expr,
)
from xbsl.rules.semantics import (
    _file_local_type_decls,
    _manager_member_types,
    _manager_members,
    _offered_member_family,
    _row_type_names,
)
from xbsl.rules.yaml_schema import _HAVE_YAML, _NAME_LINE_RE, _parsed, object_kind, value_of


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


#: A placeholder of a template string: the platform substitutes the call arguments for them.
_PLACEHOLDER_RE = re.compile(r"\$(\d+)")
#: A key of a MAPPING section (Strings/Templates of a dictionary) with its value as written.
_MAPPING_KEY_RE = re.compile(r"(?m)^([ \t]+)([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*)[ \t]*:[ \t]*(.*)$")


def _mapping_entries(s: SourceFile, key: str) -> list[tuple[str, int, str]]:
    """(name, line, value) of the top-level keys of a MAPPING section.

    The Strings and Templates of a dictionary are written as `Key: value`, not as a list of
    items with a Name, so _section_item_lines does not see them. Only the keys at the minimal
    indent of the section count - a deeper one would belong to a nested structure.
    """
    span = _section_span(s.text, key)
    if span is None:
        return []
    lo, hi = span
    found = [m for m in _MAPPING_KEY_RE.finditer(s.text, lo, hi)]
    if not found:
        return []
    level = min(len(m.group(1)) for m in found)
    lm = linemap(s)
    out: list[tuple[str, int, str]] = []
    for m in found:
        if len(m.group(1)) != level:
            continue
        value = m.group(3).strip()
        # The quotes of a yaml scalar are its form, not its text: a hover shows the string
        # itself, the way the page shows it.
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out.append((m.group(2), lm.linecol(m.start(2))[0], value))
    return out


def _dictionary_methods(s: SourceFile, name: str, path: str) -> list[dict]:
    """The keys of a LocalizedStrings element as the methods they compile into.

    A dictionary has no module: the platform turns every key of Strings into a parameterless
    method and every key of Templates into one taking the substitutions the text names
    ($0, $1 ...), and the code calls them as Dictionary.Key(). Without this the
    index knows no such members at all - go to definition answers "not found", completion
    after the dot offers nothing, and the text itself is nowhere to be seen while writing
    code. The value becomes the description, so hovering a key shows the string it stands for.
    """
    out: list[dict] = []
    for section, templated in (("Строки", False), ("Шаблоны", True)):
        for key, line, value in _mapping_entries(s, section):
            # The arity is the HIGHEST placeholder plus one: a text may repeat $0 or start at
            # $1, and it is the numbering the platform substitutes by, not the count.
            slots = [int(g) for g in _PLACEHOLDER_RE.findall(value)] if templated else []
            arity = max(slots) + 1 if slots else 0
            out.append({
                "module": name,
                "name": key,
                "path": path,
                "line": line,
                "annotations": [],
                # Types alone: the platform does not publish the parameter names of a
                # generated method, and inventing them would put a made-up name in the hover.
                "params": ", ".join(["Строка"] * arity),
                "returns": "Строка",
                "returns_written": "Строка",
                "doc": value,
            })
    return out


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


def _named_items(s: SourceFile, data: dict, key: str, kind: str | None = None) -> list[dict]:
    """{name, line} of named items of a top-level list section (`TabularParts`, `Elements`).

    The section key and the name of an item are read in EITHER spelling: an English project is
    legal code the platform reads the same way, and while only the Russian keys were tried such a
    project produced an empty index - the tree, the navigation and the dot completion had nothing
    to work with.
    """
    items = value_of(data, key, kind)
    if not isinstance(items, list):
        return []
    queues = _section_item_lines(s, key)
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("Имя") or item.get("Name")
        if not isinstance(name, str) or not name:
            continue
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


#: Whitespace run - a parameter list broken over several lines reads as one line in a hover.
_WS_RE = re.compile(r"\s+")
# Comment markers stripped from a description: line (`//`) and block (`/* */`, leading `*`).
_COMMENT_MARK_RE = re.compile(r"^\s*(?://+|/\*+|\*+/?)|\*+/\s*$")
# A section banner (`--- Configuration ---`, `=== Internals ===`) sits above the first method
# of a section but describes the SECTION: as a method description it would mislead.
_BANNER_RE = re.compile(r"^[-=*#~]{2,}.*[-=*#~]{2,}$|^[-=*#~\s]+$")


def _signature_info(s: SourceFile) -> dict[tuple[str, int], tuple[str, str, str]]:
    """(return type head, return type as written, parameter list) per (method, declaration line).

    The return type is what lets the editor type `val X = Module.Method(...)`: the catalogue
    of stdlib member types has nothing to say about a project method, so its return type has
    to come from the project index. The head is nominal (`Array<String>` -> `Array`), like
    every other inferred type - it is the key a member lookup needs.

    The WRITTEN form is kept beside it, and the difference is the nullable marker: a head says
    `UserId` where the module declares `UserId?`, so every value coming out of the project
    looked non-empty. Judging a non-null operator or a comparison with the empty value is
    exactly a question about that marker, and the head cannot answer it - the platform
    catalogue keeps the written form for the same reason.

    The parameter list is kept verbatim (defaults included) - the hover shows the call the way
    the module declares it.
    """
    out: dict[tuple[str, int], tuple[str, str, str]] = {}
    toks = code_tokens(s)
    n = len(toks)
    for sig in signatures(toks):
        head = written = None
        if sig.return_type_start is not None:
            head = _type_head(toks, sig.return_type_start)
            written = _type_written(s, toks, sig.return_type_start)
        params = ""
        i = next(
            (k for k in range(n) if toks[k].start >= sig.name.end
             and toks[k].kind == "OP" and toks[k].value == "("),
            None,
        )
        if i is not None:
            end = _skip_balanced(toks, i, "(", ")")
            if 0 < end <= n:
                params = _WS_RE.sub(" ", s.text[toks[i].start:toks[end - 1].end]).strip()
        out[(sig.name.value, sig.name.line)] = (head or "", written or "", params)
    return out


def _type_written(s: SourceFile, toks: list[Token], start: int) -> str | None:
    """The type expression exactly as the source spells it, `UserId?` and all."""
    te = type_expr(toks, start)
    if te is None or te.end <= start:
        return None
    return _WS_RE.sub("", s.text[toks[start].start:toks[te.end - 1].end]).strip() or None


def _doc_above(toks: list, i: int, annotations: list[str]) -> str:
    """The comment block written directly above the declaration at index i, `//` stripped.

    The annotations belong to the declaration, so the block is looked for above THEM: the
    author writes the description over `@OnServer method ...`, not between the two. Only
    consecutive lines count (a blank line ends the block), which keeps a section banner
    further up out of a method's description. Empty when there is no comment.
    """
    k = i - 1
    for _ in annotations:  # back over `@Имя` / `@Имя(...)`, comments between them skipped
        while k >= 0 and toks[k].kind == "COMMENT":
            k -= 1
        if k >= 0 and toks[k].kind == "OP" and toks[k].value == ")":
            depth = 1
            k -= 1
            while k >= 0 and depth:
                if toks[k].kind == "OP":
                    depth += 1 if toks[k].value == ")" else -1 if toks[k].value == "(" else 0
                k -= 1
        if not (k >= 1 and toks[k].kind == "IDENT" and toks[k - 1].kind == "OP" and toks[k - 1].value == "@"):
            break
        k -= 2
    top_line = toks[k + 1].line if k + 1 < len(toks) else toks[i].line
    lines: list[str] = []
    while k >= 0 and toks[k].kind == "COMMENT" and toks[k].end_line == top_line - 1:
        text = _COMMENT_MARK_RE.sub("", toks[k].value).strip()
        if _BANNER_RE.match(text):
            break
        lines.append(text)
        top_line = toks[k].line
        k -= 1
    return "\n".join(reversed(lines)).strip()


def _method_decls(s: SourceFile) -> list[dict]:
    """{name, line, annotations, params, returns, doc} of method and constructor declarations."""
    decls: list[dict] = []
    toks = tokens(s)
    n = len(toks)
    sigs = _signature_info(s)
    for i, t in enumerate(toks):
        if t.kind != "KEYWORD" or t.canonical not in ("METHOD", "CONSTRUCTOR"):
            continue
        if not t.value[:1].islower():
            continue  # the declaration keyword is written in lowercase (as in the handlers rule)
        j = i + 1
        while j < n and toks[j].kind == "COMMENT":
            j += 1
        if j < n and toks[j].kind == "IDENT":
            annotations = _annotations_before(toks, i)
            returns, returns_written, params = sigs.get(
                (toks[j].value, toks[j].line), ("", "", ""))
            decls.append({
                "name": toks[j].value,
                "line": toks[j].line,
                "annotations": annotations,
                "params": params,
                "returns": returns,
                "returns_written": returns_written,
                "doc": _doc_above(toks, i, annotations),
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


# --- types described in metadata --------------------------------------------------------

#: Per element kind: the yaml section that lists the members of the type the element describes,
#: and the names the platform gives that type (`{}` stands for the name of the element).
#:
#: A structure and a storable structure name the type after themselves and list its members in
#: Fields (docs topics/structure-properties, topics/storable-structure-properties). A constants
#: set generates two types carrying the constants as properties (docs topics/constants-set-types):
#: `<Name>.Record` - "the data of one record of the constants set", the value of `Get()`;
#: `<Name>.Data` - "the names and types of the properties match those of the constants", the
#: value a write handler receives. The set's own name is a singleton type with methods, not with
#: the constants, and stays out of here.
_METADATA_MEMBER_SECTIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Структура": ("Поля", (PLACEHOLDER,)),
    "ХранимаяСтруктура": ("Поля", (PLACEHOLDER,)),
    "НаборКонстант": ("Константы", (PLACEHOLDER + ".Запись", PLACEHOLDER + ".Данные")),
    # Client work parameters: "for every parameter described in the element a property OF THE SAME
    # NAME is generated on that object" (docs topics/client-work-parameters), and the same names
    # fill the service type the handler returns. Without this the dot after such an element offered
    # the kind's own methods alone - the parameters, which is what the code actually reads, were
    # missing.
    "ПараметрыРаботыКлиента": ("Параметры", (PLACEHOLDER, PLACEHOLDER + ".Параметры")),
    # An interface component names its own data in Properties, and a VALUE of that type - the
    # form a constructor call returns - carries them (docs topics/component-properties). Without
    # this a variable holding a form offered nothing after the dot: neither its own properties,
    # nor the methods of its module, nor the members of the platform type it inherits.
    "КомпонентИнтерфейса": ("Свойства", (PLACEHOLDER,)),
}

#: The fallback for `generated_returns` when the data carries no manager_member_types section:
#: methods the PLATFORM generates on a project object, with the type they return (`{}` stands for
#: the name of the element). The catalogue of stdlib member types is keyed by type name and knows
#: nothing about a project object, so without this a variable initialized by `Rates.Get()` stays
#: untyped and the dot after it offers nothing.
#:
#: `Get(): <Name>.Record` of a constants set - docs topics/constants-set-properties (the example
#: reads one record of a set and writes it back) and topics/constants-set-types (Record holds one
#: record of the set). Data generated by the current extractor answers for every kind and takes
#: precedence over this row.
_GENERATED_RETURNS: dict[str, dict[str, str]] = {
    "НаборКонстант": {"Получить": "{}.Запись"},
}


def _tabular_items(s: SourceFile, data: dict, kind: str) -> list[dict]:
    """Tabular sections with the attributes each one holds.

    A tabular section is a TYPE of its own (`Catalog.Lines`), and its attributes are
    what the dot after a row offers - the plain name-and-line record could not answer that.
    """
    items = _named_items(s, data, "ТабличныеЧасти", kind)
    described = value_of(data, "ТабличныеЧасти", kind)
    by_name: dict[str, list[str]] = {}
    if isinstance(described, list):
        for part in described:
            if not isinstance(part, dict):
                continue
            part_name = part.get("Имя") or part.get("Name")
            rows = value_of(part, "Реквизиты", kind)
            if not isinstance(part_name, str) or not isinstance(rows, list):
                continue
            names = [
                str(r.get("Имя") or r.get("Name")) for r in rows
                if isinstance(r, dict) and (r.get("Имя") or r.get("Name"))
            ]
            if names:
                by_name[part_name] = sorted(names)
    for item in items:
        fields = by_name.get(item.get("name", ""))
        if fields:
            item["attributes"] = fields
    return items


def _typed_items(s: SourceFile, data: dict, key: str, kind: str) -> list[dict]:
    """Named items of a section with the type each one declares.

    The type is what a chain over the member needs: `Goods.Object.Price` answers `Number` only
    when the attribute carries its declared type into the index.
    """
    items = _named_items(s, data, key, kind)
    described = value_of(data, key, kind)
    by_name: dict[str, str] = {}
    if isinstance(described, list):
        for entry in described:
            if not isinstance(entry, dict):
                continue
            name = entry.get("Имя") or entry.get("Name")
            written = entry.get("Тип") or entry.get("Type")
            if isinstance(name, str) and isinstance(written, str):
                by_name[name] = written
    for item in items:
        written = by_name.get(item.get("name", ""))
        if written:
            item["type"] = written
    return items


def _kind_facet_members() -> dict[str, dict[str, dict[str, list[str]]]]:
    """{kind: {facet: members}} - what the catalogue gives the types a KIND generates.

    The pages describe them by kind (`Справочник.Ссылка`, `Документ.Объект`), while the code
    names them by the object (`Catalog.Reference`). The join happens per project object; here
    only the kind side is collected, once per process.
    """
    catalog = dataset.load_json("stdlib.json")
    facets = {**(catalog.get("facet_members") or {}), **(catalog.get("type_members") or {})}
    out: dict[str, dict[str, dict[str, list[str]]]] = {}
    for name, members in facets.items():
        kind, _, facet = name.partition(".")
        if not facet or "." in facet or not metamodel.canonical_kind(kind):
            continue
        out.setdefault(metamodel.canonical_kind(kind), {})[facet] = {
            "properties": list(members.get("properties") or ()),
            "methods": list(members.get("methods") or ()),
            "returns": dict((catalog.get("member_types") or {}).get(name) or {}),
        }
    return out


def _with_object_name(spelling: str, name: str) -> str:
    """A result type spelled for a template, with the object's own name put in.

    Replaced textually rather than through `str.format`: the spelling comes from a
    documentation page and may carry braces of its own.
    """
    return spelling.replace(PLACEHOLDER, name)


def _generated_type_spellings(pattern: str, name: str, kind: str) -> tuple[str, ...]:
    """Every spelling of a type the platform generates for an element of the kind.

    A project written in English calls such a type by an English name, and the type is looked
    up by the name the code actually writes - registering the Russian spelling alone left the
    dot after the element with nothing in an English project. The pair of a facet
    (`ConstantsSet.Record`) is declared by the platform; the remaining suffixes are ordinary
    property names, where the dictionary holds the pair.
    """
    own = _with_object_name(pattern, name)
    if PLACEHOLDER + "." not in pattern:
        return (own,)
    suffix = pattern.split(".", 1)[1]
    spellings = [suffix]
    faceted = terms.english(f"{kind}.{suffix}", "facets")
    if faceted and "." in faceted:
        spellings.append(faceted.split(".", 1)[1])
    spellings.extend(terms.forms(suffix, "properties"))
    return tuple(dict.fromkeys(f"{name}.{s}" for s in spellings))


def _field_types(members) -> dict[str, str]:
    """{field: the type it declares, as written} of a structure declared in a module.

    The written form matters, not the nominal head: `Array<Catalog.Card>` is what tells a
    for-each loop what its variable is, and the head (`Array`) has already thrown that away.
    A field without a declared type is left out - a guess would be worse than silence.
    """
    out: dict[str, str] = {}
    for f in members:
        if not isinstance(f, P.ObjectField):
            continue
        type_ref = getattr(f, "type", None)
        text = getattr(type_ref, "text", None)
        if isinstance(text, str) and text.strip():
            out[f.name] = text.strip()
    return out


def _inherited_type(data: dict, kind: str) -> str | None:
    """The platform type an element extends (`Наследует.Тип` of a component), without arguments.

    A form is a value of a PROJECT type whose members are its own; everything else it answers to
    - `OpenInModalWindow`, `Close`, the layout properties - belongs to the platform type
    it inherits, and only the base names it.
    """
    inherits = value_of(data, "Наследует", kind)
    if not isinstance(inherits, dict):
        return None
    base = value_of(inherits, "Тип", kind)
    if not isinstance(base, str) or not base.strip():
        return None
    head = base.split("<", 1)[0].strip()
    return head or None


def _metadata_members(data: dict, kind: str) -> tuple[list[str], dict[str, str]]:
    """(names, {name: declared type}) of the member section of a metadata element.

    The section key is read in either spelling (the sources are bilingual, and the pair comes
    from the metamodel record of the kind); an item names itself with Name in either spelling
    and types itself with Type. The type is kept as written, generic parameter included - see
    _field_types for why the nominal head is not enough.
    """
    section = _METADATA_MEMBER_SECTIONS[kind][0]
    items = value_of(data, section, kind)
    if not isinstance(items, list):
        return [], {}
    names: set[str] = set()
    types: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("Имя") or item.get("Name")
        if not (isinstance(name, str) and name):
            continue
        names.add(name)
        written = item.get("Тип") or item.get("Type")
        if isinstance(written, str) and written.strip():
            types[name] = written.strip()
    return sorted(names), types


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
        # The module that DECLARES the type: another module names it qualified
        # (`Каталог.Карточка`), and the type inference has to find the same record by either
        # spelling. The record is kept under the bare name; the qualified one is derived.
        owner = s.path.name[: -len(".xbsl")].split(".", 1)[0]
        for m in module.members:
            if isinstance(m, P.Structure):
                rec = {
                    "properties": sorted(
                        f.name for f in m.members if isinstance(f, P.ObjectField)
                    ),
                    "methods": sorted(
                        f.name for f in m.members if isinstance(f, P.Method)
                    ),
                    # The type of a field AS WRITTEN, the generic parameter included: what
                    # types `для X из Данные.Строки` is the ELEMENT of the collection, and the
                    # nominal head the rest of the inference works in has already lost it.
                    "property_types": _field_types(m.members),
                    "module": owner,
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
                    if k == "module":
                        continue  # two namesakes have two modules; the first one keeps the key
                    if isinstance(v, dict):
                        # namesakes: a field known to one of them is known to the pair
                        known.setdefault(k, {}).update(v)
                    else:
                        known[k] = sorted(set(known.get(k, ())) | set(v))

    objects: list[dict] = []
    components: list[dict] = []
    # Keys of the dictionaries, collected while their yaml is parsed and joined to the module
    # methods below: for the caller they are members of the same kind (Dictionary.Key()).
    dictionary_methods: list[dict] = []
    # {type name: (element kind, member names)} of the types DESCRIBED IN METADATA - collected
    # here, where the parsed yaml is at hand, and joined to struct_members once the module
    # methods are known.
    metadata_types: dict[str, tuple[str, list[str], dict[str, str], str | None]] = {}
    if _HAVE_YAML:
        for s in yaml_sources:
            data, err = _parsed(s)
            if err is not None or not isinstance(data, dict):
                continue
            kind = object_kind(data)
            name = value_of(data, "Имя", kind)
            if not isinstance(name, str) or not isinstance(kind, str):
                continue
            entry: dict = {
                "name": name,
                "kind": kind,
                "path": rel(s.path),
                "line": _top_name_line(s, name),
                "tabular": _tabular_items(s, data, kind),
                "attributes": _typed_items(s, data, "Реквизиты", kind),
                # Register fields live in their own sections - the query completion
                # needs them next to the attributes.
                "dimensions": _named_items(s, data, "Измерения", kind),
                "resources": _named_items(s, data, "Ресурсы", kind),
                "local_types": local_types.get(name, []),
            }
            # What an editor OFFERS after the object name: the types the kind generates as the
            # catalogue knows them - not the safety net the member rules judge by. See
            # semantics._offered_member_family for why the two lists differ.
            entry["family"] = sorted(
                set(_offered_member_family(kind))
                | {t["name"] for t in entry["tabular"]}
                | {t["name"] for t in entry["local_types"]}
                # the row type a dynamic list names for itself (ИмяТипаДанныхСтроки)
                | _row_type_names(data)
            )
            # Members of the kind's singleton type: `Get` of a constants set, `Notify` of a
            # global client event, `FindByCode` of a catalog - properties and methods apart,
            # so a completion list knows which of them takes parentheses.
            entry["manager"] = {
                bucket: list(names)
                for bucket, names in _manager_members().get(kind, {}).items()
            }
            if kind == "Перечисление":
                entry["values"] = _named_items(s, data, "Элементы")
            if kind in _METADATA_MEMBER_SECTIONS:
                members, member_types = _metadata_members(data, kind)
                inherited = _inherited_type(data, kind)
                for pattern in _METADATA_MEMBER_SECTIONS[kind][1]:
                    for spelling in _generated_type_spellings(pattern, name, kind):
                        metadata_types[spelling] = (kind, members, member_types, inherited)
            objects.append(entry)
            if kind == "КомпонентИнтерфейса":
                components.extend(_form_components(s, data, name, entry["path"]))
            elif kind == "ЛокализованныеСтроки":
                dictionary_methods.extend(_dictionary_methods(s, name, entry["path"]))

    methods: list[dict] = dictionary_methods
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
                "params": decl["params"],
                "returns": decl["returns"],
                "returns_written": decl["returns_written"],
                "doc": decl["doc"],
            })

    # The types described in METADATA join the module-declared ones in struct_members: that is
    # the single place navigation and completion read the members of a project type from, and it
    # used to hold only what a module DECLARES (a structure written in code) - so a constructor
    # call of a StorableStructure written in yaml offered nothing after the dot. The methods are
    # those of the module extending the type: a structure is extended by `<Name>.xbsl`, the
    # record of a constants set by `<Name>.Record.xbsl` - in both cases the module name of the
    # index equals the name of the type.
    module_method_names: dict[str, set[str]] = defaultdict(set)
    for m in methods:
        module_method_names[m["module"]].add(m["name"])
    for type_name, (kind, member_names, member_types, inherited) in metadata_types.items():
        record: dict = {"properties": member_names, "kind": kind}
        if inherited:
            record["base"] = inherited
        if member_types:
            record["property_types"] = member_types
        own_methods = module_method_names.get(type_name)
        if own_methods:
            record["methods"] = sorted(own_methods)
        known = struct_members.get(type_name)
        if known is None:
            struct_members[type_name] = record
            continue
        # A namesake declared in code: the member lists merge (as two code namesakes do), and
        # the record keeps saying which metadata kind describes the type.
        known["kind"] = kind
        for key in ("properties", "methods"):
            if record.get(key):
                known[key] = sorted(set(known.get(key, ())) | set(record[key]))
        if member_types:
            known.setdefault("property_types", {}).update(member_types)

    # The methods the platform generates on a project object, with the type they return: from
    # the data when it has them (every kind), from the built-in row when it does not.
    from_data = _manager_member_types()
    generated_returns: dict[str, dict[str, str]] = {}
    for o in objects:
        table = from_data.get(o["kind"]) or _GENERATED_RETURNS.get(o["kind"])
        if table:
            generated_returns[o["name"]] = {
                member: _with_object_name(result, o["name"])
                for member, result in table.items()
            }

    # The types an OBJECT of the project generates carry its own data: `Catalog.Object` holds
    # the attributes and the tabular sections written in its yaml, `Catalog.Reference` what the
    # kind gives a reference, and a tabular section is a type of its own with its attributes.
    # The catalogue describes these by KIND (`Справочник.Ссылка`), and their members are joined
    # with the object's own here - without this a variable holding an object answered nothing.
    kind_facets = _kind_facet_members()
    facet_returns: dict[str, dict[str, str]] = {}
    for o in objects:
        own_attrs = [a["name"] for a in o.get("attributes") or []]
        # The TYPE of each own member, so a chain over it goes on: an attribute answers what its
        # yaml declares, a tabular section answers an array of its own row type.
        own_types = {
            a["name"]: a["type"] for a in o.get("attributes") or [] if a.get("type")
        }
        own_types.update({
            x["name"]: f"Массив<{o['name']}.{x['name']}>" for x in o.get("tabular") or []
        })
        tabular = [x["name"] for x in o.get("tabular") or []]
        registers = [x["name"] for x in (o.get("dimensions") or []) + (o.get("resources") or [])]
        by_facet = kind_facets.get(o["kind"]) or {}
        for facet, members in by_facet.items():
            name = f"{o['name']}.{facet}"
            if name in struct_members:
                continue
            props = sorted(set(members.get("properties") or ()) | set(
                own_attrs + tabular + registers if facet in ("Объект", "Данные", "Запись") else []
            ))
            facet_methods = sorted(set(members.get("methods") or ()))
            record: dict = {"properties": props, "kind": o["kind"]}
            if own_types and facet in ("Объект", "Данные", "Запись"):
                record["property_types"] = dict(sorted(own_types.items()))
            if facet_methods:
                record["methods"] = facet_methods
            struct_members[name] = record
            # What a member of such a type ANSWERS, with the object's own name put in: the
            # catalogue spells it by kind (`Справочник.Ссылка.ЗагрузитьОбъект: Справочник.Объект?`),
            # and a chain over the call needs the concrete name to go on.
            answers = {
                member: result.replace(o["kind"], o["name"], 1)
                for member, result in (members.get("returns") or {}).items()
                if result
            }
            if answers:
                facet_returns[name] = answers
        for part in o.get("tabular") or []:
            name = f"{o['name']}.{part['name']}"
            rows = part.get("attributes") or []
            if name not in struct_members and rows:
                struct_members[name] = {"properties": list(rows), "kind": o["kind"]}

    for type_name, answers in facet_returns.items():
        generated_returns[type_name] = {**generated_returns.get(type_name, {}), **answers}

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
        "generated_returns": generated_returns,
    }
