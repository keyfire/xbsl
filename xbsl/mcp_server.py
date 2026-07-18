"""The toolkit's MCP adapter (a thin wrapper over xbsl.engine and xbsl.scaffold).

Run: xbsl-mcp  (or python -m xbsl.mcp_server). Transport – stdio.
The `mcp` dependency comes from an extra:  pip install "xbsl[mcp]".

Tools: linting (lint_paths/lint_source), the 1C:Element documentation (docs_*) and
metadata scaffolding (meta_*). Every meta_* tool that writes files also lints what it
wrote and returns the diagnostics – creation and validation in one round trip.

Diagnostic message language follows env XBSL_LANG (then the system locale, then ru), since
an MCP server takes no CLI flags.

Registration in Claude Code:
    claude mcp add xbsl -- xbsl-mcp
"""

from __future__ import annotations

import difflib
import re
from html import unescape
from pathlib import Path

from xbsl import dataset, docs, formedits, formhandlers, formmodel, report, scaffold, uischema
from xbsl.cli import discover
from xbsl.engine import RULES, load, load_text, run, run_sources

_TAGS_RE = re.compile(r"<[^>]+>")

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover - hint when the dependency is absent
    raise SystemExit(
        "The 'mcp' package is missing. Install the MCP extra: pip install \"xbsl[mcp]\""
    ) from exc


mcp = FastMCP("xbsl")


def _as_set(value: list[str] | None) -> set[str] | None:
    return set(value) if value else None


@mcp.tool()
def list_rules() -> list[dict]:
    """List the available linter rules (id, title, tier, scope, severity)."""
    return [r.as_dict() for r in sorted(RULES, key=lambda x: (x.tier, x.id))]


@mcp.tool()
def lint_paths(
    paths: list[str],
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> dict:
    """Check files/directories on disk.

    paths  – list of paths (.xbsl/.yaml files or directories, traversed recursively);
    select – limit the rule set (id or tier letter A/B/C/D);
    ignore – exclude rules.
    Returns {diagnostics: [...], summary: {...}}.
    """
    files = discover(paths)
    diags = run(files, select=_as_set(select), ignore=_as_set(ignore))
    return report.report(diags, len(files))


@mcp.tool()
def lint_source(
    filename: str,
    content: str,
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> dict:
    """Check in-memory content (e.g. before writing the file).

    filename – name with an extension (.xbsl/.yaml); sets the kind and appears in positions;
    content  – the source text.
    Only per-file rules run (cross-file rules need the whole project).
    """
    src = load_text(filename, content)
    diags = run_sources(
        [src], select=_as_set(select), ignore=_as_set(ignore), scopes=("file",)
    )
    return report.report(diags, 1)


def _page_as_text(doc_id: str | None) -> dict:
    """A documentation page with a plain-text (not HTML) extract - the form a model reads best."""
    page = docs.page(doc_id) if doc_id else None
    if page is None:
        return {}
    page = dict(page)
    page["text"] = unescape(_TAGS_RE.sub(" ", page.pop("html"))).strip()
    return page


@mcp.tool()
def docs_search(query: str, limit: int = 10) -> list[dict]:
    """Full-text search over the 1C:Element documentation.

    Covers stdlib types, their methods, properties and parameters. Returns ranked hits
    (best first): id, title, qualified name, kind, availability and a text snippet. Pass a hit's
    id to docs_page to read the full article. Empty list if the docs data is not installed.
    """
    return docs.search(query, limit=limit)


@mcp.tool()
def docs_page(id: str) -> dict:
    """Read a documentation page by its id (obtained from docs_search or docs_symbol).

    Returns id, kind, title, qualified name, availability and the article as plain text.
    Empty object if there is no such page (or the docs data is not installed).
    """
    return _page_as_text(id)


@mcp.tool()
def docs_symbol(name: str) -> dict:
    """Find the documentation page for a symbol by name (a type or member, e.g. "Массив", "Запрос").

    Prefers an exact title match, then a qualified-name match, then the top search hit. Returns the
    same shape as docs_page, or an empty object if nothing matches.
    """
    return _page_as_text(docs.for_symbol(name))


@mcp.tool()
def type_members(name: str) -> dict:
    """Members of a stdlib type in one compact answer: what can follow the dot and what
    the calls return.

    Returns {type, properties, methods: {name: return-type root or null}, facets?} - much
    cheaper than reading the full docs page when only the member list matters. `name`
    takes both name forms (Массив / Array) and entity facets (ДвоичныйОбъект.Ссылка);
    for an aggregate the `facets` list names its record/reference types. An unknown name
    returns {"error", "close_matches"}.
    """
    try:
        catalog = dataset.load_json("stdlib.json")
    except dataset.DatasetError:
        return {"error": "данные Элемента не установлены"}
    facet_members = catalog.get("facet_members") or {}
    members = {**(catalog.get("type_members") or {}), **facet_members}
    rec = members.get(name)
    if rec is None:
        return {
            "error": f"тип '{name}' не найден в каталоге stdlib",
            "close_matches": difflib.get_close_matches(name, members, n=5, cutoff=0.6),
        }
    returns = (catalog.get("member_types") or {}).get(name, {})
    out = {
        "type": name,
        "properties": rec.get("properties", []),
        "methods": {m: returns.get(m) for m in rec.get("methods", [])},
    }
    facets = sorted(k for k in facet_members if k.startswith(name + "."))
    if facets:
        out["facets"] = facets
    return out


@mcp.tool()
def ui_schema(component: str | None = None) -> dict:
    """The interface component ui schema (the visual designer's palette and typed properties).

    Without arguments - the catalog: every component with its package, an abstract flag
    (no constructor: cannot be inserted from the palette), a container flag (the props
    carry a slot Содержимое - a wrap/drop target) and a one-line doc, WITHOUT property
    lists. With `component` - the full schema of that component: properties with value
    type unions, resolved enum values, event handler signatures, slot flags (the
    property accepts components/commands), doc snippets and documented defaults, plus
    "enums" - the value lists of the enumerations referenced by the property unions; an
    unknown name yields close_matches. {"available": false} when the ui schema dataset
    is not generated (tools/extract_uischema.py).
    """
    if component:
        return uischema.component(component)
    return uischema.catalog()


# --- scaffolding (metadata) ------------------------------------------------------------
#
# The writing tools apply their changes to disk themselves (unlike the LSP surface, where
# the editor applies the edits) and return {files, notes, lint}: a file-scope lint of the
# written files ships in the same response. An operation failure is a structured error
# field, not an exception: that makes branching easier for an agent.


def _apply_and_lint(result: scaffold.ScaffoldResult) -> dict:
    written = scaffold.apply_result(result)
    sources = [load(Path(p)) for p in written]
    diags = run_sources(sources, scopes=("file",))
    out = {
        "files": [
            {"path": str(c.path), "created": c.created} for c in result.changes
        ],
        "notes": result.notes,
        "lint": report.report(diags, len(sources)),
    }
    if result.renames:
        out["renames"] = [
            {"from": str(r.old_path), "to": str(r.new_path)} for r in result.renames
        ]
    return out


def _meta(op, *args, **kwargs) -> dict:
    try:
        return _apply_and_lint(op(*args, **kwargs))
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}


@mcp.tool()
def meta_project_info(root: str) -> dict:
    """Map the 1C:Element sources under a root: projects, subsystems, objects by kind.

    Also reports which object kinds meta_new_object can create and which section kinds
    meta_add_field accepts per object kind. Use before creating objects to pick the
    directory and to check for name clashes.
    """
    try:
        return scaffold.project_info(Path(root))
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}


@mcp.tool()
def meta_object_info(root: str, name: str | None = None, yaml_path: str | None = None) -> dict:
    """Describe one configuration object: everything needed to write its forms and code.

    Fields (with the standard ones the platform adds: Наименование / Номер+Дата, and for
    registers Период / Регистратор / ВидЗаписи), tabular sections with their own fields,
    hierarchy, existing forms, suggested form layout, namespace, plus:

    - access – the КонтрольДоступа summary (null means no section: РазрешеноАдминистраторам)
      and access_rights – the rights this kind has;
    - access_handlers – whether the object's module declares ВычислитьРазрешенияДоступа
      (level 1, needed for РазрешенияВычисляются) and ВычислитьРазрешенияДоступаДляОбъектов
      (level 2, needed for РазрешенияВычисляютсяДляКаждогоОбъекта);
    - register – for registers only: register_kind (Остатки/Обороты), periodicity, and
      needs_record_type – whether a movement needs ВидЗаписи (Приход/Расход): only a
      РегистрНакопления of kind Остатки does.

    Pass either the object name (searched under root; ambiguity is an error) or the
    explicit path to its .yaml.
    """
    try:
        return scaffold.object_info(
            Path(root), name=name, yaml_path=Path(yaml_path) if yaml_path else None
        )
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}


@mcp.tool()
def meta_new_project(
    root: str,
    vendor: str,
    name: str,
    representation: str | None = None,
    version: str = "1.0.0",
    compatibility: str = "9.0",
    subsystem: str = "Основное",
    library: bool = False,
) -> dict:
    """Scaffold a new 1C:Element project: Проект.yaml, Проект.xbsl and the first subsystem.

    Files land in <root>/<vendor>/<name>/. library=True marks a library project
    (deployable only as an Импорт dependency).
    """
    return _meta(
        scaffold.op_new_project,
        Path(root), vendor, name,
        representation=representation, version=version,
        compatibility=compatibility, subsystem=subsystem, library=library,
    )


@mcp.tool()
def meta_new_object(
    directory: str,
    kind: str,
    name: str,
    scope: str | None = None,
    environment: str | None = None,
    access: str | None = None,
    routes: str | None = None,
    report_spec: dict | None = None,
) -> dict:
    """Create a configuration object: <Имя>.yaml (+ <Имя>.xbsl for kinds with a module).

    directory – the subsystem folder; kind – one of meta_project_info().creatable_kinds
    (Справочник, Документ, Перечисление, ОбщийМодуль, HttpСервис, Отчет, КлючДоступа,
    ПланОбмена, НаборКонстант, ВиртуальнаяТаблица, Обработка, ЗапланированноеЗадание,
    контракты, права, команды ...). Kinds whose module has a mandatory handler get it
    stubbed; ВиртуальнаяТаблица gets a paired empty .xbql (its query is mandatory).
    Anything the platform will not infer is reported in notes.
    scope overrides ОбластьВидимости; environment – Окружение (ОбщийМодуль/Структура);
    access – КонтрольДоступа (РазрешеноАутентифицированным etc.); routes – HttpСервис
    routes like "GET /, POST /, GET /{id}" (handlers are stubbed in the module);
    report_spec – for Отчет: {source, rows: [...], columns: [...], measures: [{expr, title}], title}.
    """
    return _meta(
        scaffold.op_new_object,
        Path(directory), kind, name,
        scope=scope, environment=environment, access=access,
        routes=routes, report=report_spec,
    )


@mcp.tool()
def meta_add_field(
    yaml_path: str,
    field_kind: str,
    name: str,
    type: str = "Строка",
    tabular: str | None = None,
) -> dict:
    """Add a section item to an object: реквизит, измерение, ресурс, значение (enum),
    параметр, поле (structure), константа, свойство (contract), табличная-часть, операция
    (Обработка: also writes the @Обработчик method into the module), индекс (Имя + Поля with
    a stub field to replace), параметр-запроса (Отчет) or строка / шаблон (ЛокализованныеСтроки:
    key-value mapping sections, `type` carries the VALUE, defaulting to the key itself).
    UUIDs, anchoring and indentation are handled here; duplicates and sections invalid for
    the object's kind are rejected.

    tabular – target tabular-section name when adding a реквизит into it.
    """
    return _meta(
        scaffold.op_add_field, Path(yaml_path), field_kind, name, type_=type, tabular=tabular
    )


@mcp.tool()
def meta_add_route(yaml_path: str, routes: str) -> dict:
    """Add routes to an existing HttpСервис: url templates in the yaml plus handler stubs
    in the module. Existing routes are skipped (reported in notes); handler names never
    collide with the ones already declared.
    """
    return _meta(scaffold.op_add_route, Path(yaml_path), routes)


@mcp.tool()
def meta_add_form(
    root: str,
    name: str | None = None,
    yaml_path: str | None = None,
    forms: list[str] | None = None,
    overwrite: bool = False,
    card_min_width: int | None = None,
    card_placeholder: str | None = None,
) -> dict:
    """Generate interface forms for an object and register them in its Интерфейс section.

    forms – subset of ["object", "list", "list-cards", "report"]; default: object+list for
    data objects, report for Отчет. The generated forms carry real content: input fields per
    attribute, dynamic-list columns, tabular-section tables, hierarchy support.

    "list-cards" builds the list form as a card grid (ПроизвольныйСписок with a matrix
    КонтейнерСтрок) instead of a table, and adds the row component СтрокаСписка<Имя>: the
    card shows a title, a photo (ДвоичныйОбъект.Ссылка attribute) and up to three more
    fields – notes report what landed on the card and what did not. It replaces "list"
    (same form file), so passing both is an error. card_min_width – grid column width
    (default 400, 250 with a photo); card_placeholder – image expression used when the photo
    is empty, e.g. "Ресурс{Аккаунт.svg}.Ссылка".

    Existing form files are skipped unless overwrite=true.
    """
    return _meta(
        scaffold.op_add_form,
        Path(root), name=name,
        yaml_path=Path(yaml_path) if yaml_path else None,
        forms=forms, overwrite=overwrite,
        card_min_width=card_min_width, card_placeholder=card_placeholder,
    )


@mcp.tool()
def meta_add_dependency(
    root: str,
    vendor: str,
    name: str,
    version: str,
    project_yaml: str | None = None,
) -> dict:
    """Attach a library to the project – the Библиотеки section of Проект.yaml.

    version is the library's RELEASE version (digits and dots, e.g. "2.0"), not a build
    version ("1.0-42"): a release is issued in the control panel and that step has no API.
    Different versions of one library within a project are not allowed, so attaching an
    already attached library updates its version in place.

    The library's vendor/name/version and the qualified names of the types it exports come
    from parsing its archive: `elemctl inspect <file.xlib>`. Currently attached libraries
    are listed by meta_project_info (projects[].libraries).

    After attaching, types with ОбластьВидимости: Глобально are addressed as
    vendor::name::Подсистема[::Пакет]::ИмяТипа; the qualified subsystem name goes into
    Использование of a subsystem and into импорт.
    """
    return _meta(
        scaffold.op_add_dependency,
        Path(root), vendor, name, version,
        project_yaml=Path(project_yaml) if project_yaml else None,
    )


@mcp.tool()
def meta_set_access(
    root: str,
    name: str | None = None,
    yaml_path: str | None = None,
    default: str | None = None,
    permissions: dict | None = None,
    calc_by: list[str] | None = None,
) -> dict:
    """Set КонтрольДоступа.Разрешения on an object (a precise yaml edit, kind-aware).

    default – the method for the ПоУмолчанию right (the common case); permissions – methods
    for individual rights, e.g. {"Чтение": "РазрешеноВсем"} (custom rights of a ПравоНаЭлемент
    are written as "ПравоНаX.ИмяПрава"). Methods: РазрешеноВсем, РазрешеноАутентифицированным,
    РазрешеноАдминистраторам, РазрешенияВычисляются, РазрешенияВычисляютсяДляКаждогоОбъекта.
    calc_by fills РасчетРазрешенийПо – mandatory for РазрешенияВычисляютсяДляКаждогоОбъекта
    (per-object/RLS rights).

    Rights per kind and the current state come from meta_object_info (access / access_rights)
    and meta_project_info (access_default per object; no section means the platform applies
    РазрешеноАдминистраторам). The computed-permission handlers are business logic and are NOT
    written here – notes remind which ones the object then needs.
    """
    return _meta(
        scaffold.op_set_access,
        Path(root), name=name,
        yaml_path=Path(yaml_path) if yaml_path else None,
        default=default,
        permissions={str(k): str(v) for k, v in permissions.items()} if permissions else None,
        calc_by=calc_by,
    )


@mcp.tool()
def meta_rename_object(
    root: str,
    old_name: str,
    new_name: str,
    new_presentation: str | None = None,
    old_presentation: str | None = None,
    yaml_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Rename a configuration object and update every reference across the sources.

    Renames the object's files (yaml, modules, its forms `<Имя>Форма*`, the card-list row
    component `СтрокаСписка<Имя>`) and rewrites references: yaml type/table/form keys,
    `=` bindings, .xbsl code (string literals are left intact) and composite form names.
    Attributes, components or dynamic-list fields that merely share the old name are NOT
    touched. new_presentation/old_presentation update Заголовок/Представление values of the
    object and its forms (defaults: the new name). yaml_path resolves ambiguity when several
    objects share old_name. dry_run=true returns the plan (renames, files, notes) without
    writing anything.
    """
    try:
        result = scaffold.op_rename_object(
            Path(root), old_name, new_name,
            new_presentation=new_presentation, old_presentation=old_presentation,
            yaml_path=Path(yaml_path) if yaml_path else None,
        )
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}
    if dry_run:
        return result.as_dict(content=False)
    return _apply_and_lint(result)


@mcp.tool()
def meta_add_subsystem(
    parent_dir: str,
    name: str,
    representation: str | None = None,
    auto_interface: bool = True,
    uses: list[str] | None = None,
) -> dict:
    """Create a subsystem: a folder with Подсистема.yaml. uses – names of other subsystems
    for the Использование block; representation – the navigation caption.
    """
    return _meta(
        scaffold.op_add_subsystem,
        Path(parent_dir), name,
        representation=representation, auto_interface=auto_interface, uses=uses,
    )


# --- the form designer (the component model of interface forms) --------------------------
#
# meta_component_tree reads; the four editing tools compute precise text edits over the
# form model (xbsl.formmodel / xbsl.formedits), apply them to the file and lint what they
# wrote - the same contract as the writing meta_* tools. Node ids are positional paths
# ("Наследует/Содержимое[0]") and stay valid only until the next edit: re-read the tree
# after every change. The remaining designer operations (wrap/unwrap/duplicate/rename)
# are exposed through the CLI (`xbsl form-edit`) and the LSP for now.


def _form_write(yaml_path: str, op: str, args: dict) -> dict:
    try:
        outcome = formedits.op_component_edit(Path(yaml_path), op, args)
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}
    out = _apply_and_lint(outcome.result)
    if outcome.node is not None:
        out["node"] = outcome.node
    return out


@mcp.tool()
def meta_component_tree(yaml_path: str) -> dict:
    """The node tree of an interface component (ВидЭлемента: КомпонентИнтерфейса).

    Returns {root} - components and slots with ids, types, names, source spans and
    properties (scalars, =/$ bindings, composite values, При*/После*/Перед* handlers).
    Children live in the slots Содержимое / Страницы / Колонки / Команды / КомандыСтроки /
    Шапка / Подвал; other nested values are properties. Use the node ids with
    meta_add_component / meta_move_component / meta_remove_component /
    meta_set_component_property; ids are positional, so re-read the tree after any edit.

    componentProperties lists the records of the top-level Свойства section (the
    component's own properties: name, type and their spans) - they are not tree nodes.
    """
    try:
        form = formedits.load_form(Path(yaml_path))
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}
    return {
        "root": formmodel.node_dict(form.root),
        "componentProperties": formmodel.component_properties_dicts(form),
    }


@mcp.tool()
def meta_add_component(
    yaml_path: str,
    parent_id: str,
    slot: str,
    type: str | None = None,
    name: str | None = None,
    before: str | None = None,
    after: str | None = None,
) -> dict:
    """Insert a new component (Тип and/or Имя) into a slot of the parent node.

    parent_id comes from meta_component_tree; slot is one of the child-bearing keys
    (Содержимое, Страницы, Колонки, Команды, КомандыСтроки, Шапка, Подвал). By default
    the component lands at the end of the slot; before/after position it against a
    sibling node id. A missing slot is created; a slot holding a single nested mapping
    is converted to the "-" list form. The edit touches only the affected lines -
    formatting and comments elsewhere survive.
    """
    return _form_write(yaml_path, "insert", {
        "parent": parent_id, "slot": slot, "type": type, "name": name,
        "before": before, "after": after,
    })


@mcp.tool()
def meta_insert_fragment(
    yaml_path: str,
    parent_id: str,
    slot: str,
    fragment: str,
    before: str | None = None,
    after: str | None = None,
) -> dict:
    """Paste a ready yaml block of ONE component (a copied subtree) into a slot.

    fragment - the component block as copied from another form: `Тип: ...` plus its
    nested keys, optionally with attached comments above; the component type is NOT
    checked against any catalog (project components are valid). A list, several
    components or a fragment without a top-level Тип are rejected with a clear error.
    The block is re-indented to the destination; slot rules match meta_add_component
    (missing slot created, a single-mapping slot converts to the list form).
    """
    return _form_write(yaml_path, "insert_fragment", {
        "parent": parent_id, "slot": slot, "fragment": fragment,
        "before": before, "after": after,
    })


@mcp.tool()
def meta_move_component(
    yaml_path: str,
    node_id: str,
    new_parent_id: str,
    slot: str,
    before: str | None = None,
    after: str | None = None,
) -> dict:
    """Move a node into another (or the same) slot; comments above the node travel along.

    Moving into the node's own subtree is rejected. When the node is the last child, the
    emptied slot key is removed together with it; the destination follows the same slot
    rules as meta_add_component (missing slot created, singleton slot converted to a
    list). before/after position the node against a sibling in the destination slot.
    """
    return _form_write(yaml_path, "move", {
        "node": node_id, "new_parent": new_parent_id, "slot": slot,
        "before": before, "after": after,
    })


@mcp.tool()
def meta_remove_component(yaml_path: str, node_id: str) -> dict:
    """Remove a node (with its attached comments); the last child of a slot removes the
    slot key line as well. The root node (Наследует) cannot be removed.
    """
    return _form_write(yaml_path, "remove", {"node": node_id})


@mcp.tool()
def meta_set_component_property(
    yaml_path: str,
    node_id: str,
    key: str,
    value: str | None = None,
    value_yaml: str | None = None,
) -> dict:
    """Set, replace or remove a property of a component node.

    value - a scalar or a binding ("=Объект.Поле", "$Строки.Ключ"): quoted automatically
    when yaml requires it. value_yaml - a composite value as a ready yaml fragment, e.g.
    "Тип: АбсолютныйЦвет\\nЗначение: RGB(F4F6F7)" (single-line flow fragments are written
    inline). Passing NEITHER removes the key (a composite value goes with its whole
    block). Slot keys (Содержимое etc.) are rejected - children are edited with the
    component tools. A new property lands right after Тип.
    """
    if value is None and value_yaml is None:
        return _form_write(yaml_path, "reset_property", {"node": node_id, "key": key})
    return _form_write(yaml_path, "set_property", {
        "node": node_id, "key": key, "value": value, "value_yaml": value_yaml,
    })


@mcp.tool()
def meta_add_handler(
    yaml_path: str,
    node_id: str,
    key: str,
    method: str | None = None,
    signature: str | None = None,
) -> dict:
    """Bind an event property of a component node to a handler method of the paired module.

    Writes BOTH files: the yaml gets `key: Метод` on the node, the module (same stem,
    .xbsl; created when absent) gets a method stub appended - parameters ("Источник",
    "Событие") and their types come from the event signature. method - an explicit
    handler name: when such a method already exists in the module, only the yaml
    changes (binding to an existing handler). Without method the name is
    <Имя|Тип узла><Ключ> uniquified with a number, and a stub is always added.
    signature - the "(Кнопка, СобытиеПриНажатии)->ничто" string (see ui_schema); when
    omitted it is looked up in the local dataset by the node's type, and without the
    dataset the stub is parameterless. Generic type parameters are grounded through the
    node's own Тип (ПолеВвода<Строка> -> СобытиеПриИзменении<Строка>).

    Returns files+notes+lint plus: method - the final name; created - the module file
    was created; methodAdded - a stub was appended.
    """
    try:
        outcome = formhandlers.op_add_handler(
            Path(yaml_path), node_id, key, method=method, signature=signature,
        )
    except scaffold.ScaffoldError as exc:
        return {"error": str(exc)}
    out = _apply_and_lint(outcome.result)
    out["method"] = outcome.plan.method
    out["created"] = outcome.plan.created
    out["methodAdded"] = outcome.plan.method_added
    out["module"] = str(outcome.module_path)
    return out


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
