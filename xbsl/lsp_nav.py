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

_CHAIN_RE = re.compile(rf"{IDENT}(?:\.{IDENT})*")
# A trailing comment after the value is allowed - it is not part of the name.
_HANDLER_RE = re.compile(rf"^(\s*Обработчик\s*:\s*)({IDENT})\s*(?:#.*)?$")
_BARE_NAME_RE = re.compile(IDENT)
# A `Тип:` value in yaml up to the cursor. The value is a type EXPRESSION, so the cursor may
# sit inside generic brackets or after a separator (`Тип: Таблица<Динамич`), not only at the
# first bare name. Anything outside the expression alphabet (a binding `=...`, a comment)
# breaks the match instead of guessing, as in the yaml/unknown-type rule.
_YAML_TYPE_RE = re.compile(r"(?:^|\s)Тип\s*:\s*[\w\s.,<>|?]*$")


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
        """Members of a module-declared type (structure/exception/enumeration)."""
        return (self.index.get("struct_members") or {}).get(name)


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


def _method_entry(m: dict) -> dict:
    annotations = m.get("annotations") or []
    return {
        "label": m.get("name", ""),
        "kind": "method",
        "detail": ", ".join(annotations) if annotations else "метод",
    }


def _project_type_entries(lookup: IndexLookup, type_name: str) -> Optional[list[dict]]:
    """Members of a variable of a PROJECT type: a module-declared structure/exception/
    enumeration (fields, enum values, methods) or a yaml structure object (attributes)."""
    struct = lookup.struct_by_name(type_name)
    if struct:
        entries = [
            {"label": str(x), "kind": "field", "detail": "поле"}
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
    obj = lookup.object_by_name(type_name)
    if obj and obj.get("kind") in ("Структура", "ХранимаяСтруктура"):
        entries = [
            {"label": a.get("name", ""), "kind": "field", "detail": "реквизит"}
            for a in obj.get("attributes") or []
        ]
        return entries or None
    return None


def _object_member_entries(lookup: IndexLookup, name: str) -> Optional[list[dict]]:
    obj = lookup.object_by_name(name)
    methods = lookup.methods_by_module(name)
    if not obj and not methods:
        return None
    entries: list[dict] = []
    if obj:
        if obj.get("kind") == "Перечисление":
            for v in obj.get("values", []):
                entries.append({"label": v.get("name", ""), "kind": "enumMember", "detail": "значение перечисления"})
        else:
            for f in obj.get("family", []):
                entries.append({"label": str(f), "kind": "family", "detail": "тип"})
            for t in obj.get("tabular", []):
                entries.append({"label": t.get("name", ""), "kind": "tabular", "detail": "табличная часть"})
            for t in obj.get("local_types", []):
                entries.append({"label": t.get("name", ""), "kind": "localType", "detail": "локальный тип"})
    for m in methods:
        entries.append(_method_entry(m))
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
    for s_name in lookup.index.get("struct_members") or {}:
        add(str(s_name), "localType", "тип модуля")
    for name in _stdlib_type_names(stdlib_names):
        add(name, "object", "тип платформы")
    return entries


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


def _stdlib_entries(members) -> list[dict]:
    """Members of a stdlib type: properties and methods apart (methods get their own kind and insert parentheses).

    The dataset provides {"properties": [...], "methods": [...]}; the former flat list of
    names (properties and methods mixed) is understood for compatibility with old data.
    """
    if not isinstance(members, dict):
        return [{"label": str(x), "kind": "field", "detail": "член"} for x in members or []]
    entries = [
        {"label": str(x), "kind": "field", "detail": "свойство"}
        for x in members.get("properties") or []
    ]
    entries += [
        {"label": str(x), "kind": "method", "detail": "метод", "snippet": f"{x}($0)"}
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
    stdlib_names: Optional[Any] = None,
    templates: Optional[Sequence["Template"]] = None,
) -> Optional[list[dict]]:
    """Completion items [{label, kind, detail}] for the context, or None if it is unknown."""
    # A dot after a call: `ЗапросКБД.Выполнить().` - the caller inferred the chain type
    # (expr_type), the identifier-before-dot paths below cannot see through the brackets.
    if expr_type and re.search(rf"[)\]}}]\s*\.\s*(?:{IDENT})?$", line_prefix):
        members = (stdlib_members or {}).get(expr_type)
        if members:
            return _stdlib_entries(members)
    m = _match_end(line_prefix, rf"Компоненты\.({IDENT})\.(?:{IDENT})?")
    if m:
        return [_method_entry(x) for x in lookup.methods_by_module(m.group(1))]
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
            table = lookup.object_by_name((query_tables or {}).get(token, token))
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
                return _stdlib_entries(members)
            return _project_type_entries(lookup, var_type)
        entries = _object_member_entries(lookup, token)
        if entries is not None:
            return entries
        # Not a project object and not a variable - so a stdlib type or a global (КонтекстДоступа.):
        # members come from the linter dataset's type_members, keyed there under both name forms.
        members = (stdlib_members or {}).get(token)
        return _stdlib_entries(members) if members else None
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
        for s_name in (lookup.index.get("struct_members") or {}):
            add(s_name, "localType", "тип модуля")
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
    annotations = " ".join("@" + a for a in (m.get("annotations") or []))
    head = f"**метод {m.get('module', '')}.{m.get('name', '')}**"
    if annotations:
        head += f" {annotations}"
    return f"{head}\n\n`{m.get('path', '')}:{m.get('line', 1)}`"


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
