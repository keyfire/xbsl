"""Pure navigation core of the LSP server: a Python port of the extension's navCore.

Works with the project index built by `xbsl.indexer` (the same frozen schema the CLI dumps
under the `--index` flag): resolving definition, completion and hover, plus parsing a line
into dot-separated identifier chains. There are no LSP or editor imports here - the module
is covered by unit tests directly, and the pygls server (`xbsl.lsp`) is just a thin
transport on top of it.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

from xbsl import terms
from xbsl.templates import (
    CODE_CONTEXTS,
    OBJECT_FULL_NAME_VAR,
    QUERY_CONTEXT,
    Template,
    expand,
    offered,
)

IDENT = r"[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*"
# A character that cannot appear immediately before a recognized identifier chain.
NOT_BEFORE = r"[^.0-9A-Za-zА-Яа-яЁё_]"
# A dot that CONTINUES a chain: after a call or index (`ЗапросКБД.Выполнить().`) or after a
# property link (`Список.НастройкиСервисов.`) - the identifier-before-dot paths resolve one
# link only, so these cursors need the inferred chain type. A single `Имя.` does not match:
# the one-link paths (variables, components, project objects, query tables) own it.
CHAIN_TAIL_RE = re.compile(rf"(?:[)\]}}]|\.\s*{IDENT})\s*\.\s*(?:{IDENT})?$")

_CHAIN_RE = re.compile(rf"{IDENT}(?:\.{IDENT})*")
# A trailing comment after the value is allowed - it is not part of the name.
_HANDLER_RE = re.compile(rf"^(\s*Обработчик\s*:\s*)({IDENT})\s*(?:#.*)?$")
_BARE_NAME_RE = re.compile(IDENT)
# A `Тип:` value in yaml up to the cursor. The value is a type EXPRESSION, so the cursor may
# sit inside generic brackets or after a separator (`Тип: Таблица<Динамич`), not only at the
# first bare name. Anything outside the expression alphabet (a binding `=...`, a comment)
# breaks the match instead of guessing, as in the yaml/unknown-type rule.
_YAML_TYPE_RE = re.compile(r"(?:^|\s)Тип\s*:\s*[\w\s.,<>|?]*$")

#: `новый Имя.` right before the cursor - a constructor, where only a type name may follow.
#: Both spellings of the keyword, and the word must stand on its own (`Обновый` is a name).
_AFTER_NEW_RE = re.compile(
    rf"(?:^|[^A-Za-z0-9А-Яа-яЁё_])(?:новый|new)\s+{IDENT}\s*\.\s*(?:{IDENT})?$", re.IGNORECASE)

#: Kinds that name a TYPE - what a constructor accepts after the dot.
_TYPE_KINDS = frozenset({"family", "localType", "object", "enum", "tabular"})


class IndexLookup:
    """Precomputed lookups over the index dict built by indexer.build_index."""

    def __init__(self, index: dict) -> None:
        self.index = index
        self._objects: dict[str, dict] = {}
        for o in index.get("objects", []) or []:
            self._objects.setdefault(o.get("name", ""), o)
        self._module_methods: dict[str, list[dict]] = {}
        self._file_methods: dict[str, list[dict]] = {}
        for m in index.get("methods", []) or []:
            self._module_methods.setdefault(m.get("module", ""), []).append(m)
            self._file_methods.setdefault(m.get("path", ""), []).append(m)
        self._form_components: dict[str, list[dict]] = {}
        for c in index.get("components", []) or []:
            self._form_components.setdefault(c.get("form", ""), []).append(c)
        self._refs_by_name: dict[str, list[dict]] = {}
        for r in index.get("references", []) or []:
            self._refs_by_name.setdefault(r.get("name", ""), []).append(r)

    def objects(self) -> list[dict]:
        return list(self.index.get("objects", []) or [])

    def object_by_name(self, name: str) -> Optional[dict]:
        return self._objects.get(name)

    def methods_by_module(self, module: str) -> list[dict]:
        return self._module_methods.get(module, [])

    def method(self, module: str, name: str) -> Optional[dict]:
        for m in self.methods_by_module(module):
            if m.get("name") == name:
                return m
        return None

    def method_in_file(self, path: str, name: str) -> Optional[dict]:
        for m in self._file_methods.get(path, []):
            if m.get("name") == name:
                return m
        return None

    def components_by_form(self, form: str) -> list[dict]:
        return self._form_components.get(form, [])

    def component(self, form: str, name: str) -> Optional[dict]:
        for c in self.components_by_form(form):
            if c.get("name") == name:
                return c
        return None

    def references_by_name(self, name: str) -> list[dict]:
        return self._refs_by_name.get(name, [])

    def struct_by_name(self, name: str) -> Optional[dict]:
        """Members of a project type by its name: a module-declared structure/exception/
        enumeration, or a type described in metadata (a structure's Fields, the constants of
        a set under `<Name>.Record` / `<Name>.Data`).

        A structure declared in a module is indexed under its BARE name, while code names it
        with its module (`Каталог.Карточка`) - so a qualified name falls back to its tail."""
        members = self.index.get("struct_members") or {}
        found = members.get(name)
        if found is None and "." in name:
            found = members.get(name.rpartition(".")[2])
        return found

    def form_data_object(self, stem: str) -> Optional[tuple[str, str]]:
        """(name, written type) of the data object of a form: `("Object", "Goods.Object")`.

        A form module addresses the entity it edits by a BARE name, and nothing in the module
        declares that name - the base type of the form does, by its argument
        (`ObjectForm<Programs.Object>`). The pair is answered only when the project really has
        such an object with such a facet, so a base of any other shape yields nothing rather
        than a guess. Without this a loop over a tabular section of one's own object
        (`для Стр из Объект.Возможности`) had no element type.
        """
        record = self.struct_by_name(stem) or {}
        written = record.get("base_written")
        if not isinstance(written, str) or "<" not in written:
            return None
        argument = written.partition("<")[2].rstrip(">").strip()
        owner, _, facet = argument.rpartition(".")
        if not owner or not facet:
            return None
        found = self.object_by_name(owner)
        if not found or facet not in (found.get("family") or ()):
            return None
        return facet, argument

    def method_returns(self) -> dict[str, dict[str, str]]:
        """{name: {method: result type}} - the return types the inference needs of a PROJECT
        name, in the shape it expects of the stdlib catalogue, so that a variable initialized by
        a call of a module method is typed the way a platform call is.

        Two sources: the methods a module DECLARES with a return type, and the methods the
        platform GENERATES on an object of a kind (`generated_returns` of the index - a
        constants set `Rates` answers `Rates.Get()` with a `Rates.Record`). A declaration
        outranks a generated method of the same name: written code beats an assumption about
        the kind."""
        cached = getattr(self, "_method_returns", None)
        if cached is None:
            cached = {
                str(name): dict(by_name)
                for name, by_name in (self.index.get("generated_returns") or {}).items()
                if isinstance(by_name, dict)
            }
            # The fields of a project TYPE belong here too: the catalogue is keyed by the name
            # of what carries the member, and for a field the carrier is the structure. Without
            # them a chain stops at the first field (`Данные.Строки` answers nothing), and a
            # for-each over that field has no element type to take.
            for name, record in (self.index.get("struct_members") or {}).items():
                types = record.get("property_types") if isinstance(record, dict) else None
                if not (isinstance(types, dict) and types):
                    continue
                # Under both spellings: the record is kept under the bare name, and code in
                # another module writes the qualified one (`Каталог.Карточка`).
                owner = record.get("module")
                keys = [str(name)] + ([f"{owner}.{name}"] if owner else [])
                for key in keys:
                    cached[key] = {**cached.get(key, {}), **types}
            # A VALUE of an enumeration is a member whose type is the enumeration itself
            # (`Role.Admin` is a `Role`), and that is the one member the catalogue of a
            # project name could not state. Without it the dot after a value answered nothing,
            # and a loop over a literal list of values had no element type.
            for entry in self.index.get("objects") or []:
                values = entry.get("values") or ()
                name = entry.get("name")
                if not values or not name:
                    continue
                by_value = {str(_name_of(v)): str(name) for v in values if _name_of(v)}
                cached[str(name)] = {**cached.get(str(name), {}), **by_value}
            for module, methods in self._module_methods.items():
                # The WRITTEN form when the index has it: the head says `UserId` where the
                # module declares `UserId?`, and a caller judging the empty value needs the
                # marker. The platform catalogue keeps the written form for the same reason,
                # and every consumer takes the head itself when a lookup key is what it wants.
                by_name = {
                    m["name"]: (m.get("returns_written") or m["returns"])
                    for m in methods if m.get("returns")
                }
                if by_name:
                    cached[module] = {**cached.get(module, {}), **by_name}
            self._method_returns = cached
        return cached


def chain_at(line_text: str, character: int) -> Optional[tuple[list[str], int]]:
    """Dot-separated identifier chain at position `character` (0-based) and the segment index."""
    for m in _CHAIN_RE.finditer(line_text):
        start, end = m.start(), m.end()
        if character < start:
            break
        if character > end:
            continue
        parts = m.group(0).split(".")
        offset = start
        for i, part in enumerate(parts):
            segment_end = offset + len(part)
            if character <= segment_end:
                return parts, i
            offset = segment_end + 1  # skip the dot
        return parts, len(parts) - 1
    return None


def _paired_module_path(file_path: Optional[str]) -> Optional[str]:
    if not file_path or not file_path.lower().endswith(".yaml"):
        return None
    return file_path[: -len(".yaml")] + ".xbsl"


def _resolve(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
) -> Optional[dict]:
    """Descriptor of the symbol at the position: {kind, name, module, form, path, line} or None.

    kind is "object" | "method" | "component" | "tabular" | "localType" | "enumValue"; module
    is filled for methods, form - for components; path/line is the definition site. Both
    go-to-definition (resolve_definition) and find-usages (resolve_references) are built on
    this descriptor.
    """
    if language_id == "yaml":
        handler = _HANDLER_RE.match(line_text)
        if handler:
            start = len(handler.group(1))
            end = start + len(handler.group(2))
            if character < start or character > end:
                return None
            name = handler.group(2)
            paired = _paired_module_path(file_path)
            method = (lookup.method_in_file(paired, name) if paired else None) or lookup.method(file_stem, name)
            if not method:
                return None
            return {"kind": "method", "name": name, "module": method.get("module", ""),
                    "form": "", "path": method["path"], "line": method["line"]}

    hit = chain_at(line_text, character)
    if not hit:
        return None
    parts, at = hit
    word = parts[at]

    if at == 0:
        obj = lookup.object_by_name(word)
        if obj:
            return {"kind": "object", "name": word, "module": "", "form": "",
                    "path": obj["path"], "line": obj["line"]}
        if len(parts) == 1 and language_id == "xbsl":
            method = (lookup.method_in_file(file_path, word) if file_path else None) or lookup.method(file_stem, word)
            if method:
                return {"kind": "method", "name": word, "module": method.get("module", ""),
                        "form": "", "path": method["path"], "line": method["line"]}
        return None

    if at == 1 and parts[0] == "Компоненты":
        component = lookup.component(file_stem, word)
        if not component:
            return None
        return {"kind": "component", "name": word, "module": "", "form": file_stem,
                "path": component["path"], "line": component["line"]}
    if at == 2 and parts[0] == "Компоненты":
        method = lookup.method(parts[1], word)
        if not method:
            return None
        return {"kind": "method", "name": word, "module": method.get("module", parts[1]),
                "form": "", "path": method["path"], "line": method["line"]}
    if at != 1:
        return None  # deeper chains require type inference - out of scope for this module

    qualifier = parts[at - 1]
    obj = lookup.object_by_name(qualifier)
    if obj:
        for t in obj.get("local_types", []):
            if t.get("name") == word:
                return {"kind": "localType", "name": word, "module": "", "form": "",
                        "path": t["path"], "line": t["line"]}
        for t in obj.get("tabular", []):
            if t.get("name") == word:
                return {"kind": "tabular", "name": word, "module": "", "form": "",
                        "path": obj["path"], "line": t["line"]}
        for v in obj.get("values", []):
            if v.get("name") == word:
                return {"kind": "enumValue", "name": word, "module": "", "form": "",
                        "path": obj["path"], "line": v["line"]}
    method = lookup.method(qualifier, word)
    if method:
        return {"kind": "method", "name": word, "module": method.get("module", qualifier),
                "form": "", "path": method["path"], "line": method["line"]}
    return None


def resolve_definition(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
) -> Optional[tuple[str, int]]:
    """Target (path, line) for the position, or None if the context is not recognized."""
    d = _resolve(
        lookup,
        language_id=language_id,
        line_text=line_text,
        character=character,
        file_stem=file_stem,
        file_path=file_path,
    )
    return (d["path"], d["line"]) if d else None


def resolve_references(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
    include_declaration: bool = False,
) -> list[tuple[str, int, int, int]]:
    """Usages of the symbol at the position: a list of (path, line, col, length).

    Supported are methods (calls in their own module, `Модуль.Метод`, `Компоненты.Модуль.Метод`,
    yaml handlers), objects (chain root) and components (`Компоненты.Имя`). The declaration
    site is excluded from the list; with include_declaration it is added as a separate entry.
    Other kinds (tabular sections, local types, enumeration values) are not resolved in this
    version.
    """
    d = _resolve(
        lookup,
        language_id=language_id,
        line_text=line_text,
        character=character,
        file_stem=file_stem,
        file_path=file_path,
    )
    if d is None:
        return []
    kind, name = d["kind"], d["name"]
    length = len(name)
    out: list[tuple[str, int, int, int]] = []
    if kind == "method":
        module = d["module"]
        for r in lookup.references_by_name(name):
            q = r.get("qualifier", "")
            if q == module or (q == "" and r.get("module", "") == module):
                out.append((r.get("path", ""), int(r.get("line", 1)), int(r.get("col", 0)), length))
    elif kind == "object":
        for r in lookup.references_by_name(name):
            if r.get("qualifier", "") == "":
                out.append((r.get("path", ""), int(r.get("line", 1)), int(r.get("col", 0)), length))
    elif kind == "component":
        form = d["form"]
        for r in lookup.references_by_name(name):
            if r.get("qualifier", "") == "Компоненты" and r.get("module", "") == form:
                out.append((r.get("path", ""), int(r.get("line", 1)), int(r.get("col", 0)), length))
    else:
        return []

    decl_path, decl_line = d["path"], int(d["line"])
    out = [loc for loc in out if not (loc[0] == decl_path and loc[1] == decl_line)]
    if include_declaration:
        out.append((decl_path, decl_line, 0, 0))
    # deduplicate, keeping a stable (path, line, col) order
    seen: set = set()
    uniq: list[tuple[str, int, int, int]] = []
    for loc in sorted(out):
        if loc not in seen:
            seen.add(loc)
            uniq.append(loc)
    return uniq


def _nominal_head(written: str) -> str:
    """The type name without its generic arguments (`Таблица<ДинамическийСписок>` -> Таблица)."""
    return (written or "").split("<", 1)[0].strip()


def _method_entry(m: dict) -> dict:
    """A completion item for a project method.

    The parentheses come WITH it, the way every other list of methods offers them: a method
    accepted from here used to insert the bare name, and the author had to type the call
    himself - the same list built elsewhere put them in, so the editor behaved differently
    depending on which branch answered.
    """
    annotations = m.get("annotations") or []
    name = m.get("name", "")
    return {
        "label": name,
        "kind": "method",
        "detail": ", ".join(annotations) if annotations else "метод",
        "snippet": f"{name}($0)",
    }


def _enumeration_value_entries(lookup: IndexLookup, type_name: str) -> Optional[list[dict]]:
    """Members of a VALUE of an enumeration described in metadata: the methods of its module.

    An enumeration has no record among the structures - it is an object of the project - so the
    dot after a variable of that type answered nothing, though the module beside it declares
    exactly the methods such a value is asked for (`Вариант.Представление()`). The values
    themselves are NOT members here: they belong to the enumeration as a static root.
    """
    found = lookup.object_by_name(type_name)
    if not found or found.get("kind") != "Перечисление":
        return None
    return [_method_entry(m) for m in lookup.methods_by_module(type_name)] or None


def _project_type_entries(lookup: IndexLookup, type_name: str) -> Optional[list[dict]]:
    """Members of a variable of a PROJECT type: a structure/exception/enumeration declared in
    a module or a type described in metadata (the fields of a structure, the constants of a
    set) - fields, enumeration values and the methods of the module extending the type."""
    struct = lookup.struct_by_name(type_name)
    if not struct:
        return _enumeration_value_entries(lookup, type_name)
    # A constant is not a field: the hint says what the author writes in the yaml of the set.
    field_detail = "константа" if struct.get("kind") == "НаборКонстант" else "поле"
    entries = [
        {"label": str(x), "kind": "field", "detail": field_detail}
        for x in struct.get("properties") or []
    ]
    entries += [
        {"label": str(x), "kind": "enumMember", "detail": "значение перечисления"}
        for x in struct.get("values") or []
    ]
    entries += [
        {"label": str(x), "kind": "method", "detail": "метод", "snippet": f"{x}($0)"}
        for x in struct.get("methods") or []
    ]
    return entries or None


#: The text after the last opening parenthesis or comma - one argument of the call.
_ARGUMENT_TAIL_RE = re.compile(r"[(,]\s*([^(,]*)$")


def _at_argument_name(line_prefix: str) -> bool:
    """Is the cursor where the NAME of a named argument goes?

    After `=` the author writes the value, and the members of the type have no business there;
    a dot means a member of something else. Everything else inside the call is the name itself,
    whole or partial - including a fresh line of a multi-line call, where the argument starts at
    the indent and there is no parenthesis or comma on the line at all.
    """
    m = _ARGUMENT_TAIL_RE.search(line_prefix)
    tail = m.group(1) if m else line_prefix
    return (
        "=" not in tail and "." not in tail
        and re.fullmatch(rf"\s*(?:{IDENT})?\s*", tail) is not None
    )


def _constructor_argument_entries(lookup: IndexLookup, type_name: str) -> list[dict]:
    """The names a constructor of a project type takes: what the type carries."""
    struct = lookup.struct_by_name(type_name)
    if not struct:
        return []
    types = struct.get("property_types") or {}
    return [
        {
            "label": str(x),
            "kind": "field",
            "detail": str(types.get(x) or "поле"),
            "snippet": f"{x} = $0",
        }
        for x in struct.get("properties") or []
    ]


def _facet_entries(stdlib_members: Optional[dict], namespace: str) -> list[dict]:
    """The facet names that may follow a namespace: `Сущность.` -> Ключ, Объект, Право..."""
    prefix = f"{namespace}."
    seen = sorted({
        name[len(prefix):] for name in (stdlib_members or {})
        if name.startswith(prefix) and "." not in name[len(prefix):]
    })
    return [{"label": name, "kind": "type", "detail": "тип платформы"} for name in seen]


def _inherited_entries(
    lookup: IndexLookup, type_name: str, stdlib_members: Optional[dict],
    language: str = "ru",
) -> list[dict]:
    """Members a project type gets from the platform type it extends.

    A form is a value of a project type, yet almost everything the code calls on it -
    `OpenInModalWindow`, `Close`, the layout properties - comes from the platform type in
    its `Inherits`. Its own members come first: they are what the author wrote.
    """
    struct = lookup.struct_by_name(type_name)
    base = (struct or {}).get("base")
    members = (stdlib_members or {}).get(base) if isinstance(base, str) else None
    return _stdlib_entries(members, language) if members else []


#: Buckets of the `manager` field of an index object, with what a completion item says about
#: each: the label detail, and whether the item inserts a call's parentheses.
_MANAGER_BUCKETS = (
    ("methods", "метод вида", True),
    ("properties", "свойство вида", False),
    # data generated before properties and methods were told apart
    ("members", "член вида", False),
)


def _manager_entries(manager) -> list[dict]:
    """Completion items for the members of the kind's singleton type."""
    if not isinstance(manager, dict):
        return []
    entries: list[dict] = []
    for bucket, detail, is_call in _MANAGER_BUCKETS:
        for name in manager.get(bucket) or ():
            item = {"label": str(name), "kind": "method", "detail": detail}
            if is_call:
                item["snippet"] = f"{name}($0)"
            entries.append(item)
    return entries


def _object_member_entries(lookup: IndexLookup, name: str) -> Optional[list[dict]]:
    obj = lookup.object_by_name(name)
    methods = lookup.methods_by_module(name)
    if not obj and not methods:
        return None
    entries: list[dict] = []
    # One name - one line. The family of an object ALREADY holds the names of its tabular
    # sections and of the types its module declares, so listing those separately offered every
    # one of them twice: once as a bare "тип" and once as what it really is. The specific line
    # is built first and the family fills in only what is left.
    seen: set[str] = set()

    def add(entry: dict) -> None:
        label = str(entry.get("label") or "")
        if not label or label in seen:
            return
        seen.add(label)
        entries.append(entry)

    if obj:
        if obj.get("kind") == "Перечисление":
            for v in obj.get("values", []):
                add({"label": v.get("name", ""), "kind": "enumMember", "detail": "значение перечисления"})
        else:
            # The family names the tabular sections and the module types too, and each of those
            # gets an exact line below - so the family yields those names to it and keeps the
            # order it always had: the types the object generates come first.
            exact = {str(_name_of(t)) for t in obj.get("tabular", [])}
            exact |= {str(_name_of(t)) for t in obj.get("local_types", [])}
            for f in obj.get("family", []):
                if str(f) not in exact:
                    add({"label": str(f), "kind": "family", "detail": "тип"})
            # Members of the kind's singleton type: what the code writes on the object name
            # itself, next to the types the object generates. A method takes the parentheses
            # snippet, a property does not; data generated before the two were told apart
            # arrives in one bucket and gets neither the snippet nor a claim about which it is.
            for entry in _manager_entries(obj.get("manager")):
                add(entry)
            # A kind whose element generates a singleton type carrying its OWN entries names
            # them on the object itself: the parameters of a client-work-parameters element are
            # read as `Имя.Параметр` (docs topics/client-work-parameters). They live in the index
            # as the members of the type of the same name, and without this the dot offered the
            # kind's methods alone - everything the code actually reads was missing.
            own = lookup.struct_by_name(name)
            if isinstance(own, dict):
                types = own.get("property_types") or {}
                for prop in own.get("properties") or ():
                    add({
                        "label": str(prop),
                        "kind": "property",
                        "detail": str(types.get(prop) or "свойство"),
                    })
            for t in obj.get("tabular", []):
                add({"label": t.get("name", ""), "kind": "tabular", "detail": "табличная часть"})
            for t in obj.get("local_types", []):
                add({"label": t.get("name", ""), "kind": "localType", "detail": "локальный тип"})
    for m in methods:
        add(_method_entry(m))
    return entries


def _yaml_type_entries(lookup: IndexLookup, stdlib_names: Optional[Any]) -> list[dict]:
    """Type names offered for a `Тип:` value in yaml.

    The same three sources the yaml/unknown-type rule accepts as the root of a type
    expression: the platform catalog (a component type - `СтандартнаяКолонкаТаблицы`,
    `ПолеВвода` - lives only there), the project objects and the module-declared types.
    """
    entries: list[dict] = []
    seen: set[str] = set()

    def add(label: str, kind: str, detail: str) -> None:
        if label and label not in seen:
            seen.add(label)
            entries.append({"label": label, "kind": kind, "detail": detail})

    for o in lookup.objects():
        kind = o.get("kind", "")
        add(o.get("name", ""), "enum" if kind == "Перечисление" else "object", kind)
    for s_name, record in (lookup.index.get("struct_members") or {}).items():
        add(str(s_name), "localType", _struct_detail(record))
    for name in _stdlib_type_names(stdlib_names):
        add(name, "object", "тип платформы")
    return entries


def _struct_detail(record: Any) -> str:
    """What a struct_members entry is: a type described in metadata names its element kind
    (a constants set is also there under `<Имя>.Запись`), the rest is declared in a module."""
    kind = record.get("kind") if isinstance(record, dict) else None
    return str(kind) if kind else "тип модуля"


def _stdlib_type_names(stdlib_names: Optional[Any]) -> list[str]:
    """Bare type names of the catalog: a facet (`ДвоичныйОбъект.Ссылка`) is a member of its
    aggregate rather than a name of its own, and the catalog's non-name markers are dropped."""
    return [
        str(n) for n in stdlib_names or ()
        if _BARE_NAME_RE.fullmatch(str(n))
    ]


def _match_end(prefix: str, pattern: str) -> Optional[re.Match]:
    return re.search(rf"(?:^|{NOT_BEFORE}){pattern}$", prefix)


# Standard (query-selectable) fields per object kind. Kinds and field names are in Russian
# on purpose: linter metadata is Russian-canonical (semantics._member_family and the type
# families are Russian everywhere). Only CODE keywords are bilingual; the Запрос{...} block
# is recognized by the lexer (query_ranges at the caller, which passes in_query). Object
# attributes come from the index (the "attributes" field).
_STANDARD_QUERY_FIELDS = {
    "Справочник": ["Ссылка", "Код", "Наименование", "ПометкаУдаления", "Предопределённый"],
    "Документ": ["Ссылка", "Номер", "Дата", "Проведён", "ПометкаУдаления"],
}


def _name_of(item) -> str:
    return item.get("name", "") if isinstance(item, dict) else str(item)



#: A row of a tabular section always answers these, whatever the section declares.
_TABULAR_ROW_FIELDS = ("Ссылка", "НомерСтроки")


def _tabular_query_entries(lookup: "IndexLookup", named: str) -> Optional[list[dict]]:
    """Fields of `<Объект>.<ТабличнаяЧасть>` in a query, or None when that is not one.

    A query reads a tabular section as a table of its own (`ИЗ Товары.Состав КАК С`), and its
    fields are known exactly - the section's own attributes plus the row's standard ones. A
    dotted name that is NOT a section (a virtual table of a register) answers None here and
    goes on to the ordinary path, which knows no such object and stays silent as before.
    """
    if "." not in named:
        return None
    owner, _, section = named.rpartition(".")
    table = lookup.object_by_name(owner)
    if not table:
        return None
    found = next(
        (t for t in (table.get("tabular") or []) if _name_of(t) == section), None
    )
    if found is None:
        return None
    entries = [{"label": f, "kind": "field", "detail": "стандартное поле"}
               for f in _TABULAR_ROW_FIELDS]
    for attribute in (found.get("attributes") or []) if isinstance(found, dict) else []:
        name = _name_of(attribute)
        if name:
            entries.append({"label": name, "kind": "field", "detail": "реквизит"})
    return entries

def _query_field_entries(
    kind: str, attributes: list, tabular: list,
    dimensions: list = (), resources: list = (),
) -> list[dict]:
    """Table fields in a query: standard fields of the kind + the object's own sections
    (attributes, register dimensions and resources, tabular sections), deduplicated by name."""
    seen: set = set()
    entries: list[dict] = []

    def add(label: str, detail: str) -> None:
        if label and label not in seen:
            seen.add(label)
            entries.append({"label": label, "kind": "field", "detail": detail})

    for f in _STANDARD_QUERY_FIELDS.get(kind, []):
        add(f, "стандартное поле")
    for d in dimensions:
        add(_name_of(d), "измерение")
    for r in resources:
        add(_name_of(r), "ресурс")
    for a in attributes:
        add(_name_of(a), "реквизит")
    for t in tabular:
        add(_name_of(t), "табличная часть")
    return entries


def _spelling(name: str, language: str) -> str:
    """The member name in the language the project is written in.

    The catalogue keys TYPES under both spellings but holds the members of each under their
    Russian names only - the distribution documents them in Russian, and that is where the
    catalogue comes from. An English project therefore used to be offered a Russian member
    list after every dot. The compiler dictionary (`terms_full.json`) carries the pair for
    each such name, so the label is translated at the last step, where the reader is known;
    a name the dictionary does not know stays as it is rather than being invented.
    """
    if language != "en":
        return name
    return terms.common_english(name) or name


def _stdlib_entries(members, language: str = "ru") -> list[dict]:
    """Members of a stdlib type: properties and methods apart (methods get their own kind and insert parentheses).

    The dataset provides {"properties": [...], "methods": [...]}; the former flat list of
    names (properties and methods mixed) is understood for compatibility with old data.
    """
    if not isinstance(members, dict):
        return [
            {"label": _spelling(str(x), language), "kind": "field", "detail": "член"}
            for x in members or []
        ]
    entries = [
        {"label": _spelling(str(x), language), "kind": "field", "detail": "свойство"}
        for x in members.get("properties") or []
    ]
    entries += [
        {"label": (name := _spelling(str(x), language)), "kind": "method",
         "detail": "метод", "snippet": f"{name}($0)"}
        for x in members.get("methods") or []
    ]
    return entries


def _object_resolver(lookup: IndexLookup):
    """Feed `${ИмяОбъектаМетаданного(Справочник)}` from the index: the catalogs of this project.

    The kind is the `ВидЭлемента` of the yaml, exactly as the index stores it, so a template
    names the kind the way the platform does. The full-name variable inserts `Вид.Имя`, which
    is how a type is written in code.
    """

    def resolve(variable: str, kind: str) -> list[str]:
        if not kind:
            return []
        names = [
            n for n in sorted(
                o.get("name", "") for o in lookup.objects() if o.get("kind") == kind
            ) if n
        ]
        if variable == OBJECT_FULL_NAME_VAR:
            return [f"{kind}.{n}" for n in names]
        return names

    return resolve


def _template_entries(
    templates: Optional[Sequence[Template]],
    lookup: IndexLookup,
    in_query: bool,
) -> list[dict]:
    """Template completions for the cursor: the trigger as the label, the code as a snippet."""
    if not templates:
        return []
    contexts = (QUERY_CONTEXT,) if in_query else CODE_CONTEXTS
    resolver = _object_resolver(lookup)
    return [
        {
            "label": t.trigger,
            "kind": "snippet",
            "detail": t.title,
            "snippet": expand(t.pattern, resolver),
        }
        for t in offered(templates, contexts=contexts)
    ]


def resolve_completions(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_prefix: str,
    file_stem: str,
    in_query: bool = False,
    stdlib_members: Optional[dict] = None,
    stdlib_globals: Optional[list] = None,
    local_vars: Optional[dict] = None,
    query_tables: Optional[dict] = None,
    query_rows: Optional[dict] = None,
    expr_type: Optional[str] = None,
    ctor_type: Optional[str] = None,
    stdlib_names: Optional[Any] = None,
    templates: Optional[Sequence["Template"]] = None,
    project_language: str = "ru",
) -> Optional[list[dict]]:
    """Completion items [{label, kind, detail}] for the context, or None if it is unknown."""
    # A dot that continues a chain - after a call (`ЗапросКБД.Выполнить().`) or a property
    # link (`Список.НастройкиСервисов.`): the caller inferred the chain type (expr_type),
    # the identifier-before-dot paths below cannot see past the first link.
    # Inside `новый Тип(` the author writes the NAMES of what the type carries, and those names
    # are the one thing an editor can supply there. Before the chain paths: a name is being typed,
    # not a member of something.
    if ctor_type and _at_argument_name(line_prefix):
        named = _constructor_argument_entries(lookup, ctor_type)
        if named:
            return named
    m = _match_end(line_prefix, rf"Компоненты\.({IDENT})\.(?:{IDENT})?")
    if m:
        # The methods of the component's own module come first - they are what the form's
        # author wrote - and after them the members of the TYPE the component has. Only the
        # module half used to answer, so a component without a module of its own (the usual
        # case: a group, a table, an input) left the dot silent, though the yaml states its
        # type and the catalogue describes that type in full.
        # The written type is usually GENERIC (`Таблица<ДинамическийСписок>` is the everyday
        # shape of a list form), and the catalogue is keyed by the nominal head, so the head is
        # what the lookup asks for. And when neither half has anything, the branch must NOT
        # answer - the chain below knows the components as a root of its own and answers there.
        entries = [_method_entry(x) for x in lookup.methods_by_module(m.group(1))]
        component = lookup.component(file_stem, m.group(1))
        written = (component or {}).get("type", "")
        of_type = ((stdlib_members or {}).get(written)
                   or (stdlib_members or {}).get(_nominal_head(written)))
        if of_type:
            entries += _stdlib_entries(of_type, project_language)
        if entries:
            return entries
    if expr_type and CHAIN_TAIL_RE.search(line_prefix):
        members = (stdlib_members or {}).get(expr_type)
        if members:
            return _stdlib_entries(members, project_language)
        project = _project_type_entries(lookup, expr_type)
        if project:
            return project + _inherited_entries(
                lookup, expr_type, stdlib_members, project_language)
    m = _match_end(line_prefix, rf"Компоненты\.(?:{IDENT})?")
    if m:
        return [
            {"label": c.get("name", ""), "kind": "component", "detail": c.get("type", "")}
            for c in lookup.components_by_form(file_stem)
        ]
    m = _match_end(line_prefix, rf"({IDENT})\.(?:{IDENT})?")
    if m:
        token = m.group(1)
        # In a Запрос{...} block after <Таблица>. - table fields (standard + attributes +
        # tabular sections), not object/manager members. The query context and the alias map
        # (`ИЗ Акция КАК А` - that is exactly how projects address tables) are determined by
        # the caller: the query language is parsed by the lexer.
        if in_query:
            named = (query_tables or {}).get(token, token)
            section = _tabular_query_entries(lookup, named)
            if section is not None:
                return section
            table = lookup.object_by_name(named)
            if not table:
                return None
            return _query_field_entries(
                table.get("kind", ""), table.get("attributes", []), table.get("tabular", []),
                table.get("dimensions", []), table.get("resources", []),
            )
        # A loop variable over a query result (`для С из Результат`) - its members are the
        # selection columns: the names are computed by the caller from ВЫБРАТЬ ... КАК aliases.
        columns = (query_rows or {}).get(token)
        if columns:
            return [{"label": str(c), "kind": "field", "detail": "колонка запроса"} for c in columns]
        # A variable in scope shadows everything else: `пер Список = новый Массив<...>()` is
        # about the members of Массив, even if the stdlib has a type named Список (a component)
        # or the project has an object with that name. Types of visible variables are computed
        # by the caller (the lexer, bilingual). A project type resolves over the index:
        # a module-declared structure/enum or a yaml structure object.
        if local_vars and token in local_vars:
            var_type = local_vars[token]
            members = (stdlib_members or {}).get(var_type)
            if members:
                return _stdlib_entries(members, project_language)
            return _project_type_entries(lookup, var_type)
        entries = _object_member_entries(lookup, token)
        if entries is not None:
            # After `новый Имя.` only a TYPE can stand, and the members of the object are not
            # all types: the methods of its module and the members of its manager have no
            # business in a constructor and only pushed the types out of sight.
            if _AFTER_NEW_RE.search(line_prefix):
                return [e for e in entries if e["kind"] in _TYPE_KINDS] or None
            return entries
        # Not a project object and not a variable - so a stdlib type or a global (КонтекстДоступа.):
        # members come from the linter dataset's type_members, keyed there under both name forms.
        members = (stdlib_members or {}).get(token)
        if members:
            return _stdlib_entries(members, project_language)
        # A NAMESPACE of facets (`Сущность.Право`, `Сущность.Объект`): the catalogue keys such a
        # type by both segments, and the first one alone is not a type at all - the dot after it
        # used to answer nothing, though the names that may follow are known exactly.
        return _facet_entries(stdlib_members, token) or None
    if language_id == "yaml" and _YAML_TYPE_RE.search(line_prefix):
        return _yaml_type_entries(lookup, stdlib_names or stdlib_members) or None
    # A bare name (no dot before it): the top-level scope - code templates, visible variables,
    # the module's own methods, project objects and module types, stdlib types and globals.
    # The editor filters by the typed prefix itself.
    if language_id == "xbsl" and re.search(
        rf"(?:^|[^.\wА-Яа-яЁё])(?:{IDENT})?$", line_prefix,
    ):
        # Templates come first and outrank the rest (lsp.py sorts by kind): a construct the
        # author is typing out is a likelier target than a name that merely starts the same.
        # They are outside the dedup below on purpose - several templates legitimately share
        # a trigger (`мет` reaches every flavour of a method), told apart by their title.
        entries: list[dict] = _template_entries(templates, lookup, in_query)
        seen: set = set()

        def add(label: str, kind: str, detail: str, snippet: Optional[str] = None) -> None:
            if label and label not in seen:
                seen.add(label)
                e = {"label": label, "kind": kind, "detail": detail}
                if snippet:
                    e["snippet"] = snippet
                entries.append(e)

        for v, t in (local_vars or {}).items():
            add(v, "field", f"переменная: {t}")
        for m in lookup.methods_by_module(file_stem):
            name = m.get("name", "")
            add(name, "method", "метод модуля", f"{name}($0)")
        for o in lookup.objects():
            kind = o.get("kind", "")
            add(o.get("name", ""), "enum" if kind == "Перечисление" else "object", kind)
        for s_name, record in (lookup.index.get("struct_members") or {}).items():
            add(s_name, "localType", _struct_detail(record))
        for g in stdlib_globals or ():
            add(str(g), "method", "глобальный контекст", f"{g}($0)")
        for t_name in _stdlib_type_names(stdlib_names or stdlib_members):
            add(t_name, "object", "тип stdlib")
        return entries or None
    return None


def _hover_object(obj: dict) -> str:
    lines = [f"**{obj.get('kind', 'Объект')} {obj.get('name', '')}**", "", f"`{obj.get('path', '')}`"]
    if obj.get("kind") == "Перечисление" and obj.get("values"):
        names = ", ".join(v.get("name", "") for v in obj["values"][:12])
        lines += ["", f"Значения: {names}"]
    else:
        if obj.get("tabular"):
            lines += ["", "Табличные части: " + ", ".join(t.get("name", "") for t in obj["tabular"])]
        if obj.get("local_types"):
            lines += ["", "Локальные типы: " + ", ".join(t.get("name", "") for t in obj["local_types"])]
    return "\n".join(lines)


def _hover_method(m: dict) -> str:
    """Hover card of a project method: the signature line, the author's description comment
    above it (that is where a module says what its method does) and the source position."""
    annotations = " ".join("@" + a for a in (m.get("annotations") or []))
    signature = f"{m.get('module', '')}.{m.get('name', '')}{m.get('params') or '()'}"
    if m.get("returns"):
        signature += f": {m['returns']}"
    head = f"**метод {signature}**"
    if annotations:
        head += f" {annotations}"
    lines = [head]
    if m.get("doc"):
        lines += ["", str(m["doc"])]
    lines += ["", f"`{m.get('path', '')}:{m.get('line', 1)}`"]
    return "\n".join(lines)


def stdlib_member_hover(
    owner: str, member: str, *,
    stdlib_members: Optional[dict] = None,
    member_types: Optional[dict] = None,
    member_signatures: Optional[dict] = None,
) -> Optional[str]:
    """Hover card of a PLATFORM member: `**метод HttpClient.WithProxy(): HttpClient**`.

    The owner is the type the member is read on - a variable's inferred type or a type used
    statically (`JsonSerialization`, `AccessContext`). Kind and result come from the dataset
    tables (`type_members`, `member_types`); a member the catalogue does not know yields
    None, so a wrong name shows nothing rather than an invented signature. The card itself is
    Russian, like the other hover and completion labels of this module.

    Parameters come from `member_signatures` - the signature the documentation prints, one
    per overload. Without them the card used to show a method as `Имя()`, which reads like a
    method that takes nothing; a dataset generated before they existed still renders that
    way, just without the parameters, rather than breaking.
    """
    if not owner or not member:
        return None
    table = (stdlib_members or {}).get(owner)
    if not isinstance(table, dict):
        return None
    result = ((member_types or {}).get(owner) or {}).get(member)
    tail = f": {result}" if result else ""
    place = f"тип платформы `{owner}`"
    if member in (table.get("methods") or ()):
        signatures = ((member_signatures or {}).get(owner) or {}).get(member) or []
        if len(signatures) == 1:
            return f"**метод {owner}.{signatures[0]}**\n\n{place}"
        if signatures:
            # Overloads are listed in full: picking one of them would answer the question
            # ("what do I pass?") with half the truth. A list, not bare lines - a single
            # newline is a soft break in Markdown and would glue the overloads together.
            lines = "\n".join(f"- `{owner}.{sig}`" for sig in signatures)
            return f"**метод {owner}.{member}**\n\n{lines}\n\n{place}"
        return f"**метод {owner}.{member}(){tail}**\n\n{place}"
    if member in (table.get("properties") or ()):
        return f"**свойство {owner}.{member}{tail}**\n\n{place}"
    return None


def stdlib_global_hover(
    name: str, *,
    stdlib_globals: Optional[Any] = None,
    availability: Optional[dict] = None,
    stdlib_members: Optional[dict] = None,
) -> Optional[str]:
    """Hover card of a name from the GLOBAL catalog - `Сообщить`, `Макс`, `КлиентHttp`.

    Globals sit next to the types rather than inside one, so the member branch - which needs
    a receiver to the left of a dot - never sees them, and the card over `Выполнить()` was
    empty. A global that the catalogue also knows as a type is named a type (all three of
    those - `ЗагрузкаФайлов`, `КлиентHttp`, `КлиентскоеПриложение` - carry members and a
    constructor); everything else in the catalog is a function, `Корень` included - it is
    the square root, not an object. The environment comes from `global_availability`, the
    same table the `code/global-unavailable` rule is judged by, so the card answers the
    question that actually gets asked here - may I call this on the client?
    """
    if not name or name not in set(stdlib_globals or ()):
        return None
    is_type = isinstance((stdlib_members or {}).get(name), dict)
    kind, call = ("тип платформы", "") if is_type else ("глобальная функция", "()")
    where = (availability or {}).get(name)
    tail = f"доступно: {where}" if where else "глобальный контекст платформы"
    return f"**{kind} {name}{call}**\n\n{tail}"


def resolve_hover(
    lookup: IndexLookup,
    *,
    language_id: str,
    line_text: str,
    character: int,
    file_stem: str,
    file_path: Optional[str] = None,
) -> Optional[str]:
    """Hover text in Markdown for the position, or None. Same contexts as definition."""
    hit = chain_at(line_text, character)
    if not hit:
        return None
    parts, at = hit
    word = parts[at]

    if at == 0:
        obj = lookup.object_by_name(word)
        if obj:
            return _hover_object(obj)
        if len(parts) == 1 and language_id == "xbsl":
            method = (lookup.method_in_file(file_path, word) if file_path else None) or lookup.method(file_stem, word)
            if method:
                return _hover_method(method)
        return None
    if at == 1 and parts[0] == "Компоненты":
        c = lookup.component(file_stem, word)
        return f"**Компонент {c.get('name', '')}: {c.get('type', '')}**\n\n`{c.get('path', '')}`" if c else None
    if at == 2 and parts[0] == "Компоненты":
        method = lookup.method(parts[1], word)
        return _hover_method(method) if method else None
    if at != 1:
        return None

    qualifier = parts[at - 1]
    obj = lookup.object_by_name(qualifier)
    if obj:
        for t in obj.get("tabular", []):
            if t.get("name") == word:
                return f"**Табличная часть {qualifier}.{word}**\n\n`{obj.get('path', '')}:{t.get('line', 1)}`"
        for t in obj.get("local_types", []):
            if t.get("name") == word:
                return f"**Локальный тип {qualifier}.{word}**\n\n`{t.get('path', '')}:{t.get('line', 1)}`"
        for v in obj.get("values", []):
            if v.get("name") == word:
                return f"**Значение перечисления {qualifier}.{word}**\n\n`{obj.get('path', '')}:{v.get('line', 1)}`"
    method = lookup.method(qualifier, word)
    return _hover_method(method) if method else None
