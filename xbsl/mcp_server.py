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

import argparse
import difflib
import inspect
import os
import re
from html import unescape
from pathlib import Path
from typing import Any

from xbsl import __version__
from xbsl import (
    baseline as baseline_data, dataset, docs, environment, formedits, formhandlers,
    formmodel, i18n, metamodel, report, scaffold, uischema,
)
from xbsl.cli import _filter_requested, discover_with_context
from xbsl.engine import RULES, active_rules, load, load_text, run, run_sources

_TAGS_RE = re.compile(r"<[^>]+>")

# mcp 2.0 renamed the ergonomic server class and moved it: FastMCP from mcp.server.fastmcp
# became MCPServer in mcp.server.mcpserver, and the old module is gone rather than aliased -
# an untouched server meets the rename as a ModuleNotFoundError the moment the environment
# resolves mcp to 2.x. Nothing else the server uses changed: @tool() registration, the private
# _tool_manager that _forbid_unknown_arguments reaches into (checked on 2.0.0 - ToolManager,
# list_tools() and fn_metadata.arg_model are all still there) and run() over stdio.
try:
    from mcp.server.mcpserver import MCPServer as McpServer  # mcp 2.x
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as McpServer  # mcp 1.x
    except ImportError as exc:  # pragma: no cover - hint when the dependency is absent
        raise SystemExit(
            "The 'mcp' package is missing. Install the MCP extra: pip install \"xbsl[mcp]\""
        ) from exc


def _new_server():
    """The server object, with the version passed wherever the class takes one.

    The version parameter is 2.x only, and without it serverInfo comes out empty there;
    1.x had no such parameter and stamped the version of the mcp package itself.
    """
    options = {}
    if "version" in inspect.signature(McpServer).parameters:
        options["version"] = __version__
    return McpServer("xbsl", **options)


mcp = _new_server()


def _as_set(value: list[str] | None) -> set[str] | None:
    return set(value) if value else None


def _forbid_unknown_arguments() -> None:
    """Make a misspelled argument an ERROR instead of a silent no-op.

    FastMCP builds a pydantic model per tool, and pydantic IGNORES unknown keys by default:
    a caller who guesses a name (`rules` for `select`, `doc_id` for `id`) gets the tool's
    DEFAULT behaviour and reads it as "the parameter does not work" - the filter looked
    broken while it was simply never passed. With extra="forbid" the offending name is
    reported back. Called once, after every tool is registered; the private manager is
    reached defensively, since a silent ignore is the status quo, not a regression.
    """
    manager = getattr(mcp, "_tool_manager", None)
    lister = getattr(manager, "list_tools", None)
    if lister is None:
        return
    for tool in lister():
        model = getattr(getattr(tool, "fn_metadata", None), "arg_model", None)
        config = getattr(model, "model_config", None)
        if config is None:
            continue
        config["extra"] = "forbid"
        model.model_rebuild(force=True)


@mcp.tool()
def list_rules() -> list[dict]:
    """List the available linter rules (id, title, tier, scope, severity)."""
    return [r.as_dict() for r in sorted(RULES, key=lambda x: (x.tier, x.id))]


@mcp.tool()
def version_info() -> dict:
    """The environment answering: engine version, interpreter, data version, plugins.

    Two environments with diverged plugin versions (the editor's LSP, the agent's MCP)
    answer differently on the same file - this names which one is talking.
    """
    return environment.snapshot()


def _through_baseline(
    diags: list, files: list[Path], path: str | None, disabled: bool, rules: set[str],
    asked: list[Path],
) -> tuple[list, dict]:
    """The findings the baseline leaves, plus the summary keys describing what it took.

    Written as a helper rather than inline so the tool can name its parameter `baseline`
    without shadowing the module it needs.

    `rules` is what this server actually carries: a plugin older than the one CI runs knows
    fewer rules, and without the set their entries were reported as stale - the two answered
    differently about one baseline. `asked` is what the caller named: the entries of other
    files are out of this run's reach, and a request for two files used to be answered with
    the whole baseline called stale.
    """
    if disabled:
        return diags, {}
    found = Path(path) if path else baseline_data.discover(files)
    if found is None:
        return diags, {}
    data = baseline_data.load(found)
    roots = baseline_data.roots_of(asked, found.parent)
    kept, suppressed, unused, stale = baseline_data.apply(
        diags, data, found.parent, rules, roots,
    )
    summary = {
        "baseline": str(found),
        "baselined": suppressed,
        "baseline_unused": unused,
        "baseline_stale": len(stale),
    }
    not_checked = baseline_data.not_checked_entries(data, rules, roots)
    if not_checked:
        split = baseline_data.not_checked_split(not_checked)
        summary["baseline_not_checked"] = len(not_checked)
        summary["baseline_not_checked_rules"] = split["rules"]
        summary["baseline_not_checked_paths"] = split["paths"]
    return kept, summary


# Paths. The server's working directory is where the CLIENT started it, not where the caller
# works: a session in a git worktree that passed `vendor/app/Main` had its files created in
# the main checkout, and the answer's relative paths looked right. So every meta_* tool, and
# lint_paths with them, takes `root` - the caller's project or repository root - resolves
# relative paths against it (an absolute path stands as it is) and answers with absolute
# paths plus the root they were counted from, so the two trees can be told apart without a
# find. Without `root` the server's own working directory serves, as before. The tools whose
# operand IS a root (project_info, add_form, rename_object ...) take it as their first,
# required parameter; the tools addressing a file take it as the optional last one.

_ROOT_NOTE = (
    "root – the caller's project or repository root, an absolute path: relative paths above\n"
    "resolve against it, and the answer names it as `root` next to absolute file paths.\n"
    "Without it the server's own working directory serves, which for a session started\n"
    "elsewhere (a git worktree) is another checkout - so pass it."
)


def _documents_root(fn):
    """Append the shared note on `root` to a tool description.

    FastMCP reads __doc__ when @mcp.tool() registers the function, so this decorator sits
    under it; the note is one text for the whole family rather than a copy per tool.
    """
    fn.__doc__ = f"{(fn.__doc__ or '').rstrip()}\n\n{_ROOT_NOTE}\n"
    return fn


def _base(root: str | None) -> Path:
    """The directory relative paths resolve against: the caller's root, else the server's cwd."""
    return Path(os.path.abspath(root)) if root else Path.cwd()


def _under(base: Path, path: str | Path | None) -> Path | None:
    """`path` against the base; an absolute path stands as it is, an absent one stays absent."""
    if path is None or path == "":
        return None
    return Path(os.path.normpath(os.path.join(base, path)))


@mcp.tool()
@_documents_root
def lint_paths(
    paths: list[str],
    select: list[str] | None = None,
    ignore: list[str] | None = None,
    enable: list[str] | None = None,
    baseline: str | None = None,
    no_baseline: bool = False,
    root: str | None = None,
) -> dict:
    """Check files/directories on disk.

    paths       – list of paths (.xbsl/.yaml files or directories, traversed recursively);
    select      – limit the rule set (id or tier letter A/B/C/D);
    ignore      – exclude rules;
    enable      – add a rule that is OFF by default ON TOP of the defaults (the CLI --enable);
                  `select` answers with that rule ALONE, this one with everything plus it -
                  the way a project asks for its translation gaps or its typography;
    baseline    – a baseline file to apply; without it the project's own `.xbsllint-baseline`
                  is looked up above the checked files, exactly as the CLI does;
    no_baseline – report the frozen findings too.
    A path inside a project pulls the whole project in as context (the cross-file rules need
    it), the diagnostics are reported for the requested paths only.
    Returns {diagnostics: [...], summary: {...}}; when a baseline applied, the summary also
    carries `baseline` (the file), `baselined` (findings it suppressed), `baseline_unused`
    and `baseline_stale`, so "clean" here means the same as it does in a terminal and in CI.
    Entries this server could not judge - their rule is not in its set (an older plugin, a
    narrower selection) or their file is not among the requested paths - are counted apart
    as `baseline_not_checked` (split into `_rules` and `_paths`) and are NOT called stale.
    The summary also names what judged: `engine`, `plugins` (with versions) and `rules`
    {active, total, plugin} - the first place two environments disagreeing about one tree
    differ.
    """
    base = _base(root)
    asked = [str(_under(base, p)) for p in paths]
    named = _under(base, baseline)
    files, requested = discover_with_context(asked)
    chosen = (_as_set(select), _as_set(ignore), _as_set(enable))
    diags = _filter_requested(
        run(files, select=chosen[0], ignore=chosen[1], enable=chosen[2]), requested,
    )
    counted = requested if requested is not None else files
    active = active_rules(*chosen)
    diags, extra = _through_baseline(
        diags, counted, str(named) if named else None, no_baseline, {r.id for r in active},
        [Path(p) for p in asked],
    )
    payload = report.report(diags, len(counted))
    payload["summary"].update(environment.provenance(active))
    payload["summary"].update(extra)
    payload["summary"]["root"] = str(base)
    return payload


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
    chosen = (_as_set(select), _as_set(ignore))
    diags = run_sources([src], select=chosen[0], ignore=chosen[1], scopes=("file",))
    payload = report.report(diags, 1)
    payload["summary"].update(
        environment.provenance([r for r in active_rules(*chosen) if r.scope == "file"]),
    )
    return payload


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

    A multi-word query answers with the pages carrying every word; when no page carries them
    all, it relaxes to the pages carrying the most of them - so asking in a phrase is safe.
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
def ui_schema(component: str | None = None, brief: bool = False, property: str | None = None) -> dict:
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

    Names the palette does not carry are answered too - a command (ОбычнаяКоманда), a
    command interface fragment, ЭлементСпискаЗначений: their properties come from the
    compiler's metamodel or from the type catalog, and such a record says `source` (plus
    `metadata_kind` when the name is an element kind, the view metadata_schema serves).

    The full schema of a big component costs thousands of tokens; when the question is
    "does property X exist / what values does enum Y take", pass `brief=true` - one line
    per property (the type union with enum values inline, nullable/slot markers, event
    signatures). One property in full - `property="Имя"` (overrides `brief`).
    """
    if component and property:
        return uischema.component_property(component, property)
    if component and brief:
        return uischema.component_brief(component)
    if component:
        return uischema.component(component)
    return uischema.catalog()


@mcp.tool()
def metadata_schema(
    kind: str | None = None,
    sections: list[str] | None = None,
    names: list[str] | None = None,
) -> dict:
    """The properties a configuration element of a kind (ВидЭлемента) may declare.

    Without arguments - the kinds the metamodel covers. With `kind` - its properties, each
    with a value kind (boolean | number | string | enum | type | block | list), the declared
    type, the platform default, the version it appeared in and the alternate spellings the
    compiler still accepts, plus "enums" - the values of the enumerations they reference.
    `block` and `list` are the nested structures (КонтрольДоступа, Реквизиты), written as
    yaml blocks rather than a scalar. Use it before writing an element yaml by hand:
    it answers "what else may a Справочник declare" without guessing.

    An item of a collection is asked for by its path: `sections` are the collection keys from
    the root down (["Реквизиты"], ["ТабличныеЧасти", "Реквизиты"]) and `names` are the `Имя`
    of the item on each level. The name matters where the platform dispatches by it - the
    built-in `Код`, `Наименование` and `Владелец` of a Справочник have classes of their own,
    so their properties differ from an ordinary attribute's.
    {"available": false} when the metamodel dataset is not generated
    (tools/extract_metamodel.py).
    """
    if not metamodel.available():
        return {"available": False}
    if not kind:
        return {"available": True, "kinds": list(metamodel.kinds())}
    cls = metamodel.class_for_kind(kind)
    if sections:
        path = tuple(zip(sections, list(names or []) + [None] * (len(sections) - len(names or []))))
        cls = metamodel.item_class(kind, path)
        if not cls:
            return {"available": True, "kind": kind, "props": {}}
        props = metamodel.properties_of_class(cls)
    elif cls is None and metamodel.has_class(kind):
        # The name of a descriptor CLASS instead of an element kind
        # (`ConstantsSetConstantDescriptor`): it is what the answers here call things, so a
        # caller that read it in a previous answer asks with it - and used to get an empty
        # result with no hint that the same properties live under sections=["Константы"].
        cls = kind
        props = metamodel.properties_of_class(cls)
    else:
        props = metamodel.properties(kind)
    enums = {
        name: list(metamodel.enum_values(name))
        for name in {p.get("enum") for p in props.values() if p.get("enum")}
    }
    answer = {
        "available": True,
        "kind": kind,
        "class": cls,
        "props": props,
        "enums": enums,
    }
    if not props:
        # An empty answer has two very different causes - the platform has no such kind, or
        # THESE data files do not know it yet (a server started before the data was
        # regenerated answers from its own copy). The reader cannot tell them apart, so the
        # empty answer names the data it speaks for and the kinds it does know.
        answer["data"] = environment.snapshot()["data"]
        answer["known_kinds"] = list(metamodel.kinds())
    return answer


# --- scaffolding (metadata) ------------------------------------------------------------
#
# The writing tools apply their changes to disk themselves (unlike the LSP surface, where
# the editor applies the edits) and return {root, files, notes, lint}: a file-scope lint of
# the written files ships in the same response. An operation failure is a structured error
# field, not an exception: that makes branching easier for an agent.
#
def _absolute(payload: dict, base: Path) -> dict:
    """The answer with every file path absolute and the root they were counted from named."""
    for entry in payload.get("files", ()):
        entry["path"] = str(_under(base, entry["path"]))
    for entry in payload.get("renames", ()):
        entry["from"] = str(_under(base, entry["from"]))
        entry["to"] = str(_under(base, entry["to"]))
    if "deletes" in payload:
        payload["deletes"] = [str(_under(base, p)) for p in payload["deletes"]]
    return {"root": str(base), **payload}


def _failed(exc: Exception, base: Path) -> dict:
    return {"error": str(exc), "root": str(base)}


def _apply_and_lint(result: scaffold.ScaffoldResult, base: Path) -> dict:
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
    return _absolute(out, base)


def _meta(base: Path, op, *args, **kwargs) -> dict:
    try:
        return _apply_and_lint(op(*args, **kwargs), base)
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)


@mcp.tool()
def meta_project_info(root: str, kind: str | None = None, subsystem: str | None = None,
                      brief: bool = False) -> dict:
    """Map the 1C:Element sources under a root: projects, subsystems, objects by kind.

    root – the caller's project or repository root, an absolute path (a relative one is taken
    against the server's working directory, which a session started elsewhere does not
    share); the answer repeats the absolute path read as `root`, and every path in it is
    absolute.
    kind / subsystem – list only the objects of that kind (`Catalog`) or of that
    subsystem; brief – leave the list out and answer with the counts alone. A real project
    does not fit here whole (the site sources are 105 KB of listing), so ask narrowly: the
    counts by kind (`object_counts`) come with every answer, filtered or not, and `filter`
    states what was left out.

    Also reports which object kinds meta_new_object can create and which section kinds
    meta_add_field accepts per object kind. Use before creating objects to pick the
    directory and to check for name clashes.
    """
    base = _base(root)
    try:
        info = scaffold.project_info(base, kind=kind, subsystem=subsystem, brief=brief)
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    return {"root": str(base), **info}


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

    root – the caller's project or repository root (absolute); a relative yaml_path resolves
    against it, and the answer names the absolute `root` and `path`.
    Pass either the object name (searched under root; ambiguity is an error) or the
    explicit path to its .yaml.
    """
    base = _base(root)
    try:
        info = scaffold.object_info(base, name=name, yaml_path=_under(base, yaml_path))
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    return {"root": str(base), **info}


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
    root – the caller's repository root, an absolute path (a relative one is taken against
    the server's working directory, which a session started elsewhere does not share); the
    answer names it as `root` next to the absolute paths written.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_new_project,
        base, vendor, name,
        representation=representation, version=version,
        compatibility=compatibility, subsystem=subsystem, library=library,
    )


@mcp.tool()
@_documents_root
def meta_new_object(
    directory: str,
    kind: str,
    name: str,
    scope: str | None = None,
    environment: str | None = None,
    access: str | None = None,
    routes: str | None = None,
    report_spec: dict | None = None,
    presentation: str | None = None,
    root: str | None = None,
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
    report_spec – for Report: {source, rows: [...], columns: [...], measures: [{expr, title}], title};
    presentation – Presentation of the element. Beware of what the kind means by it: a
    report or a command carries a CAPTION there, while a catalog, a document, an exchange
    plan and a settings storage carry the NAME of a string attribute whose value the
    platform shows for a record (a caption written there fails to compile). Pass it:
    without one the very first lint of the new file answers naming/presentation.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_new_object,
        _under(base, directory), kind, name,
        scope=scope, environment=environment, access=access,
        routes=routes, report=report_spec, presentation=presentation,
    )


@mcp.tool()
@_documents_root
def meta_add_field(
    yaml_path: str,
    field_kind: str,
    name: str,
    type: str | None = None,
    tabular: str | None = None,
    props: dict[str, Any] | None = None,
    root: str | None = None,
) -> dict:
    """Add a section item to an object: реквизит, измерение, ресурс, значение (enum),
    параметр, поле (structure), константа, свойство (contract), табличная-часть, операция
    (Обработка: also writes the @Обработчик method into the module), индекс (Имя + Поля with
    a stub field to replace), параметр-запроса (Отчет) or строка / шаблон (ЛокализованныеСтроки:
    key-value mapping sections, `type` carries the VALUE, defaulting to the key itself).
    UUIDs, anchoring and indentation are handled here; duplicates and sections invalid for
    the object's kind are rejected.

    type – the item's type, "Строка" when omitted. A BUILT-IN attribute is added by its
    name ("Номер" / "Дата" of a document, "Код" / "Наименование" / "Владелец" of a catalog)
    and is judged by its own metamodel class - the one metadata_schema answers with for that
    name: no "Ид", a "Тип" only where the class declares one ("Наименование" has none), the
    class default when omitted ("Номер" - "Строка", "Дата" - "ДатаВремя"), a closed set
    enforced ("Номер" takes "Строка" or "Число"), and "Владелец" needs the owner's reference
    type explicitly.

    tabular – target tabular-section name when adding a реквизит into it.

    props – the item's other properties as {"Property": value}: DefaultValue, Presentation,
    MaxLength and whatever else the item's class declares (ask metadata_schema with
    sections=["<section>"] and names=["<name>"] for the list - a built-in "Номер" declares
    "Длина", "Уникальность" and "Автонумерация" where a regular attribute does not). Names
    are checked against that class in either language; Name/Type/Id belong to the parameters
    above, not here. A scalar is written as a yaml scalar (quoted where a bare one would be
    ambiguous). A nested block is a dict - {"Автонумерация": {"Префикс": "ЗА", "Формат":
    {"ДлинаПрефикса": 2}}} - or dotted keys ({"Автонумерация.Префикс": "ЗА"}), checked the
    same way level by level; a list property ("СерииНумерации") is a list of scalars. A
    block the metamodel describes as opaque ("Представление") is refused with its class
    named - it still goes into the yaml by hand. To change the properties of an item that
    already exists use meta_set_field_property.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_add_field, _under(base, yaml_path), field_kind, name, type_=type,
        tabular=tabular, props=props,
    )


@mcp.tool()
@_documents_root
def meta_set_field_property(
    yaml_path: str,
    field_kind: str,
    name: str,
    props: dict[str, Any],
    tabular: str | None = None,
    root: str | None = None,
) -> dict:
    """Set properties on a section item that already exists (a constant, an attribute, a
    dimension, an enumeration value...): an existing property is replaced in place, a new
    one is appended to the item.

    The metadata counterpart of meta_set_component_property, which serves interface
    components only. Names are checked against the item's metamodel class - a built-in
    "Номер" or "Код" by its own class, as in meta_add_field (both languages accepted, written
    in the project's own); Name is refused - renaming is meta_rename_object, which updates the
    references too. Values take the shapes meta_add_field takes: a nested block as a dict or
    dotted keys replaces whatever stands under that key whole; a scalar over an existing
    block is refused rather than flattened into it.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_set_field_property,
        _under(base, yaml_path), field_kind, name, props, tabular=tabular,
    )


@mcp.tool()
@_documents_root
def meta_add_route(yaml_path: str, routes: str = "", template: str = "", methods: str = "",
                   root: str | None = None) -> dict:
    """Add routes to an existing HttpСервис: url templates in the yaml plus handler stubs
    in the module. Existing routes are skipped (reported in notes); handler names never
    collide with the ones already declared.

    Two ways to say the same thing: `routes` as text ("GET /orders, POST /orders"), or a
    single `template` with its `methods` (comma separated) - the second is what "add a
    method to this template" looks like, and an EXISTING template is extended with the
    missing verbs only. The verbs: GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS.
    """
    base = _base(root)
    if not routes:
        try:
            routes = scaffold.routes_for(template, [m for m in methods.split(",")])
        except scaffold.ScaffoldError as exc:
            return {"ok": False, **_failed(exc, base)}
    return _meta(base, scaffold.op_add_route, _under(base, yaml_path), routes)


@mcp.tool()
@_documents_root
def meta_add_localization(yaml_path: str, language: str, root: str | None = None) -> dict:
    """Add a translation file (the Localization section) to a LocalizedStrings element:
    Localization/<Code>/<Name>.yaml next to the element. The file repeats the
    Strings/Templates sections with the default-language values for the translator to
    replace in place.

    language – Russian/English (either project spelling) or the folder code Ru/En. The
    language must be declared in LocalizationLanguages of the project descriptor and must
    differ from DefaultLanguage. Candidates come from meta_localization_info.
    """
    base = _base(root)
    return _meta(base, scaffold.op_add_localization, _under(base, yaml_path), language)


@mcp.tool()
@_documents_root
def meta_localization_info(yaml_path: str, root: str | None = None) -> dict:
    """The localization picture of a LocalizedStrings element: the declared languages, the
    default one, the translations already present and the candidate languages a translation
    can be added for (folder codes Ru/En with their display names). `file` names the
    absolute path read."""
    base = _base(root)
    path = _under(base, yaml_path)
    try:
        info = scaffold.localization_info(path)
    except (scaffold.ScaffoldError, OSError) as exc:
        return _failed(exc, base)
    return {"root": str(base), "file": str(path), **info}


@mcp.tool()
@_documents_root
def meta_add_method(
    module_path: str,
    name: str,
    params: str = "",
    returns: str = "",
    annotations: str = "",
    after: str = "",
    before: str = "",
    body: str = "",
    root: str | None = None,
) -> dict:
    """Insert a method into an existing .xbsl module without tearing annotation blocks apart.

    Use this instead of editing the module by a text anchor: an anchor like "метод Имя" lands
    between an annotation block and the method it belongs to, so the new method inherits the
    neighbour's @НаСервере/@Локально while the neighbour loses them - valid syntax the linter
    cannot see, which surfaces only as unrelated compiler errors on deploy. The insertion
    point here is always a method border, annotations included.

    Placement: `after` or `before` name an existing method (mutually exclusive), otherwise the
    method is appended. `annotations` is a whitespace-separated list, `@` optional; `body` is a
    single line put in place of the `// TODO` stub.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_add_method, _under(base, module_path), name,
        params=params, returns=returns or None, annotations=annotations or None,
        after=after or None, before=before or None, body=body or None,
    )


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

    root – the caller's project or repository root (absolute): the object is searched under
    it by name, a relative yaml_path resolves against it, and the answer names it as `root`
    next to the absolute paths written.
    forms – subset of ["object", "list", "list-cards", "report", "processing"]; default:
    object+list for data objects, report for Report, processing for Processing. The generated
    forms carry real content: input fields per attribute, dynamic-list columns,
    tabular-section tables, hierarchy support; the processing form wires the operation
    commands (MainCommand/UsualCommands from the Commands type).

    "list-cards" builds the list form as a card grid (ПроизвольныйСписок with a matrix
    КонтейнерСтрок) instead of a table, and adds the row component СтрокаСписка<Имя>: the
    card shows a title, a photo (ДвоичныйОбъект.Ссылка attribute) and up to three more
    fields – notes report what landed on the card and what did not. It replaces "list"
    (same form file), so passing both is an error. card_min_width – grid column width
    (default 400, 250 with a photo); card_placeholder – image expression used when the photo
    is empty, e.g. "Ресурс{Аккаунт.svg}.Ссылка".

    Existing form files are skipped unless overwrite=true.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_add_form,
        base, name=name,
        yaml_path=_under(base, yaml_path),
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

    root – the caller's project or repository root (absolute): the project descriptor is
    searched under it, a relative project_yaml resolves against it, and the answer names it
    as `root` next to the absolute path written.
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
    base = _base(root)
    return _meta(
        base, scaffold.op_add_dependency,
        base, vendor, name, version,
        project_yaml=_under(base, project_yaml),
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

    root – the caller's project or repository root (absolute): the object is searched under
    it by name, a relative yaml_path resolves against it, and the answer names it as `root`
    next to the absolute path written.
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
    base = _base(root)
    return _meta(
        base, scaffold.op_set_access,
        base, name=name,
        yaml_path=_under(base, yaml_path),
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

    root – the caller's project or repository root (absolute): the references are rewritten
    under it, a relative yaml_path resolves against it, and the answer names it as `root`
    next to absolute paths.
    Renames the object's files (yaml, modules, its forms `<Имя>Форма*`, the card-list row
    component `СтрокаСписка<Имя>`) and rewrites references: yaml type/table/form keys,
    `=` bindings, .xbsl code (string literals are left intact) and composite form names.
    Attributes, components or dynamic-list fields that merely share the old name are NOT
    touched. new_presentation/old_presentation update Заголовок/Представление values of the
    object and its forms (defaults: the new name). yaml_path resolves ambiguity when several
    objects share old_name. dry_run=true returns the plan (renames, files, notes) without
    writing anything.
    """
    base = _base(root)
    try:
        result = scaffold.op_rename_object(
            base, old_name, new_name,
            new_presentation=new_presentation, old_presentation=old_presentation,
            yaml_path=_under(base, yaml_path),
        )
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    if dry_run:
        return _absolute(result.as_dict(content=False), base)
    return _apply_and_lint(result, base)


@mcp.tool()
def meta_delete_object(
    root: str,
    name: str | None = None,
    yaml_path: str | None = None,
    dry_run: bool = True,
) -> dict:
    """Delete a configuration object whole: the yaml/module pair, its forms `<Имя>Форма*`
    and the card-list row component `СтрокаСписка<Имя>`, with their pairs. A subsystem in
    1C:Element is the folder the files live in, so the membership goes away with the files.
    Every REMAINING mention of the name across the project is listed by file and line
    (string literals and comments included - a router string, seeding, dictionary keys)
    and deliberately NOT edited: which mention is dead code is the author's call.
    root – the caller's project or repository root (absolute): the object is searched under
    it, a relative yaml_path resolves against it, and the answer names it as `root` next to
    absolute paths. yaml_path resolves ambiguity between namesakes. Deletion is irreversible,
    so dry_run defaults to TRUE - the first call returns the plan; repeat with
    dry_run=false to perform it.
    """
    base = _base(root)
    try:
        result = scaffold.op_delete_object(
            base, name, yaml_path=_under(base, yaml_path),
        )
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    if dry_run:
        payload = _absolute(result.as_dict(content=False), base)
        payload["dry-run"] = True
        return payload
    scaffold.apply_result(result)
    return _absolute(result.as_dict(content=False), base)


@mcp.tool()
@_documents_root
def meta_add_subsystem(
    parent_dir: str,
    name: str,
    representation: str | None = None,
    auto_interface: bool = True,
    uses: list[str] | None = None,
    root: str | None = None,
) -> dict:
    """Create a subsystem: a folder with Подсистема.yaml. uses – names of other subsystems
    for the Использование block; representation – the navigation caption.
    """
    base = _base(root)
    return _meta(
        base, scaffold.op_add_subsystem,
        _under(base, parent_dir), name,
        representation=representation, auto_interface=auto_interface, uses=uses,
    )


# --- the form designer (the component model of interface forms) --------------------------
#
# meta_component_tree reads; the editing tools compute precise text edits over the form
# model (xbsl.formmodel / xbsl.formedits), apply them to the file and lint what they
# wrote - the same contract as the writing meta_* tools. Node ids are positional paths
# ("Наследует/Содержимое[0]") and stay valid only until the next edit: re-read the tree
# after every change. meta_remove_components / meta_move_components are the batch
# spellings: one call, one edit pass over several nodes. The remaining designer
# operations (wrap/unwrap/duplicate/rename) are exposed through the CLI
# (`xbsl form-edit`) and the LSP for now.


def _form_write(base: Path, yaml_path: str, op: str, args: dict) -> dict:
    try:
        outcome = formedits.op_component_edit(_under(base, yaml_path), op, args)
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    out = _apply_and_lint(outcome.result, base)
    if outcome.node is not None:
        out["node"] = outcome.node
    return out


@mcp.tool()
@_documents_root
def meta_component_tree(
    yaml_path: str,
    node_id: str = "",
    name: str = "",
    max_depth: int = 0,
    properties: bool = True,
    root: str | None = None,
) -> dict:
    """The node tree of an interface component (ВидЭлемента: КомпонентИнтерфейса).

    Returns {root, file} - components and slots with ids, types, names, source spans and
    properties (scalars, =/$ bindings, composite values, При*/После*/Перед* handlers).
    Children live in the slots Содержимое / Страницы / Колонки / Команды / КомандыСтроки /
    Шапка / Подвал; other nested values are properties. Use the node ids with
    meta_add_component / meta_move_component / meta_remove_component / the batch
    meta_move_components / meta_remove_components / meta_set_component_property;
    ids are positional, so re-read the tree after any edit. `file` is the absolute path of
    the file read; the base directory is not repeated, since `root` here is the tree.

    componentProperties lists the records of the top-level Свойства section (the
    component's own properties: name, type and their spans) - they are not tree nodes.

    A big form does not fit one answer (a real one reached a quarter of a million
    characters), so the tree can be asked for in parts. All four narrowings compose:

    * node_id - the subtree under that node instead of the whole form;
    * name - the subtree of the component with this `Name` (what a person knows; the
      ids are positional). Several matches come back in "roots", not "root";
    * max_depth - how many levels below the root to unfold (0 - no limit, 1 - the
      root and its children); a node whose children were left out carries
      "childrenOmitted";
    * properties=False - names and ids only, each component reporting
      "propertyCount". This is the biggest cut: properties are most of the bytes.

    componentProperties comes back with the whole form only - it belongs to the
    element, not to a node.
    """
    base = _base(root)
    path = _under(base, yaml_path)
    try:
        form = formedits.load_form(path)
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    if node_id and name:
        return {"error": "Укажите либо node_id, либо name – это два способа выбрать один узел",
                "file": str(path)}
    depth = None if not max_depth or max_depth < 0 else max_depth
    shape = {"max_depth": depth, "properties": bool(properties)}
    if name:
        found = formmodel.find_by_name(form.root, name)
        if not found:
            return {"error": f"Компонент с именем \"{name}\" в форме не найден", "file": str(path)}
        return {"roots": [formmodel.node_dict(n, **shape) for n in found], "file": str(path)}
    if node_id:
        try:
            node = formmodel.get_node(form, node_id)
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc), "file": str(path)}
        return {"root": formmodel.node_dict(node, **shape), "file": str(path)}
    return {
        "root": formmodel.node_dict(form.root, **shape),
        "componentProperties": formmodel.component_properties_dicts(form),
        "file": str(path),
    }


@mcp.tool()
@_documents_root
def meta_add_component(
    yaml_path: str,
    parent_id: str,
    slot: str,
    type: str | None = None,
    name: str | None = None,
    before: str | None = None,
    after: str | None = None,
    root: str | None = None,
) -> dict:
    """Insert a new component (Тип and/or Имя) into a slot of the parent node.

    parent_id comes from meta_component_tree; slot is one of the child-bearing keys
    (Содержимое, Страницы, Колонки, Команды, КомандыСтроки, Шапка, Подвал). By default
    the component lands at the end of the slot; before/after position it against a
    sibling node id. A missing slot is created; a slot holding a single nested mapping
    is converted to the "-" list form. The edit touches only the affected lines -
    formatting and comments elsewhere survive.
    """
    return _form_write(_base(root), yaml_path, "insert", {
        "parent": parent_id, "slot": slot, "type": type, "name": name,
        "before": before, "after": after,
    })


@mcp.tool()
@_documents_root
def meta_insert_fragment(
    yaml_path: str,
    parent_id: str,
    slot: str,
    fragment: str,
    before: str | None = None,
    after: str | None = None,
    root: str | None = None,
) -> dict:
    """Paste a ready yaml block of ONE component (a copied subtree) into a slot.

    fragment - the component block as copied from another form: `Тип: ...` plus its
    nested keys, optionally with attached comments above; the component type is NOT
    checked against any catalog (project components are valid). A list, several
    components or a fragment without a top-level Тип are rejected with a clear error.
    The block is re-indented to the destination; slot rules match meta_add_component
    (missing slot created, a single-mapping slot converts to the list form).
    """
    return _form_write(_base(root), yaml_path, "insert_fragment", {
        "parent": parent_id, "slot": slot, "fragment": fragment,
        "before": before, "after": after,
    })


@mcp.tool()
@_documents_root
def meta_move_component(
    yaml_path: str,
    node_id: str,
    new_parent_id: str,
    slot: str,
    before: str | None = None,
    after: str | None = None,
    root: str | None = None,
) -> dict:
    """Move a node into another (or the same) slot; comments above the node travel along.

    Moving into the node's own subtree is rejected. When the node is the last child, the
    emptied slot key is removed together with it; the destination follows the same slot
    rules as meta_add_component (missing slot created, singleton slot converted to a
    list). before/after position the node against a sibling in the destination slot.
    """
    return _form_write(_base(root), yaml_path, "move", {
        "node": node_id, "new_parent": new_parent_id, "slot": slot,
        "before": before, "after": after,
    })


@mcp.tool()
@_documents_root
def meta_remove_component(yaml_path: str, node_id: str, root: str | None = None) -> dict:
    """Remove a node (with its attached comments); the last child of a slot removes the
    slot key line as well. The root node (Наследует) cannot be removed.
    """
    return _form_write(_base(root), yaml_path, "remove", {"node": node_id})


@mcp.tool()
@_documents_root
def meta_remove_components(yaml_path: str, node_ids: list[str],
                           root: str | None = None) -> dict:
    """Remove several nodes in ONE operation (each with its attached comments).

    node_ids come from meta_component_tree, in any order; repeated ids and ids nested
    inside another removed node are skipped silently. A slot losing ALL its children is
    removed whole (the slot key line goes too). The root node (Наследует) cannot be
    removed. One call = one edit pass, instead of re-reading the tree between removals.
    """
    return _form_write(_base(root), yaml_path, "remove_nodes", {"nodes": node_ids})


@mcp.tool()
@_documents_root
def meta_move_components(
    yaml_path: str,
    node_ids: list[str],
    new_parent_id: str,
    slot: str,
    before: str | None = None,
    after: str | None = None,
    root: str | None = None,
) -> dict:
    """Move several nodes into one slot in ONE operation, keeping their DOCUMENT order.

    The nodes land as consecutive siblings ordered as they stand in the file (the order
    of node_ids does not matter); nodes from different parents are welcome; repeated ids
    and ids nested inside another moved node are skipped silently. A source slot losing
    all its children is removed whole; the destination follows the same slot rules as
    meta_add_component. before/after position the run against a sibling in the
    destination slot and must not name a moved node. The returned node is the FIRST of
    the moved run.
    """
    return _form_write(_base(root), yaml_path, "move_nodes", {
        "nodes": node_ids, "new_parent": new_parent_id, "slot": slot,
        "before": before, "after": after,
    })


@mcp.tool()
@_documents_root
def meta_set_component_property(
    yaml_path: str,
    node_id: str,
    key: str,
    value: str | None = None,
    value_yaml: str | None = None,
    root: str | None = None,
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
        return _form_write(_base(root), yaml_path, "reset_property",
                           {"node": node_id, "key": key})
    return _form_write(_base(root), yaml_path, "set_property", {
        "node": node_id, "key": key, "value": value, "value_yaml": value_yaml,
    })


@mcp.tool()
@_documents_root
def meta_add_handler(
    yaml_path: str,
    node_id: str,
    key: str,
    method: str | None = None,
    signature: str | None = None,
    root: str | None = None,
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
    was created; methodAdded - a stub was appended; module - the absolute path of the module.
    """
    base = _base(root)
    try:
        outcome = formhandlers.op_add_handler(
            _under(base, yaml_path), node_id, key, method=method, signature=signature,
        )
    except scaffold.ScaffoldError as exc:
        return _failed(exc, base)
    out = _apply_and_lint(outcome.result, base)
    out["method"] = outcome.plan.method
    out["created"] = outcome.plan.created
    out["methodAdded"] = outcome.plan.method_added
    out["module"] = str(_under(base, outcome.module_path))
    return out


# --- translation dictionary -----------------------------------------------------------------
#
# Filling a dictionary of several thousand entries by reading the files is hopeless: they are
# megabytes, and a wrong guess about an existing spelling costs a collision the platform only
# reports at apply time. These four tools answer in pages instead: what is missing (most
# frequent first, with a place to look at and the platform's own spelling as a hint), what the
# dictionary already says about a word, and a way to write entries back without touching yaml
# by hand.
#
# A root with no dictionary is refused, not answered with an empty one: passed the repository
# root instead of the project directory, the tools reported coverage 0.0 and every name of the
# project as a gap - a report that looked like work. The refusal (load_for_tools) spells where
# a dictionary is looked for, and every answer names the absolute `dictionary` it read.


@mcp.tool()
def translate_status(root: str) -> dict:
    """Coverage of the project's translation dictionary: how much is done and what is left.

    root – the project directory (the one with the project descriptor), next to which - or
    above which - the xbsl-translation dictionary sits; a root without one is refused with
    the places looked at, and the answer names the absolute `dictionary` read.
    Returns the totals only - a cheap health check before deciding what to fill.
    Two units live here, so read the names: `missing_tokens`, `missing_phrases`,
    `literals_translated` and `missing_literals` count DISTINCT entries - what a dictionary line
    would cover - while `translated`, `missing` and `surfaces` count OCCURRENCES, the places the
    pass touched. `literals_translated` and `missing_literals` are the two halves of one number:
    how many different literal texts the plane names and how many it does not.
    `literal_occurrences` is the odd one out and says so: it counts rewritten SPANS, the size
    of the change rather than the size of the dictionary.
    """
    from xbsl.translation import cli as translate_cli

    project, dictionary, error = translate_cli.load_for_tools(root)
    if error:
        return {"error": error}
    from xbsl.translation import project as project_module

    report_obj = project_module.translate_project(project, dictionary, None)
    totals = report_obj.totals()
    return {
        "coverage": totals["coverage"],
        "translated": totals["translated"],
        "missing": totals["missing"],
        "missing_tokens": totals["missing_tokens"],
        "missing_phrases": totals["missing_phrases"],
        "literals_translated": totals["literals_translated"],
        "missing_literals": totals["missing_literals"],
        "literal_occurrences": totals["literal_occurrences"],
        "platform_gaps": totals["platform_gaps"],
        "problems": report_obj.problems[:20],
        "dictionary": str(translate_cli.dictionary_path_for(project)),
    }


@mcp.tool()
def translate_gaps(
    root: str,
    kind: str = "any",
    filter: str = "",
    limit: int = 50,
    offset: int = 0,
    compact: bool = False,
) -> dict:
    """What the dictionary does not cover yet, most frequent first.

    root   – the project directory (the one with the project descriptor); a root without a
             dictionary next to or above it is refused with the places looked at, and the
             answer names the absolute `dictionary` read;
    kind   – 'token' (names), 'phrase' (comment lines), 'literal' (string literals) or 'any';
    filter – a substring of the key;
    limit/offset – the page (limit 0 means all, which can be thousands of rows);
    compact – each row is only {key, kind, count}: the shape of a translator's worklist.
    A full page of hundreds of gaps does not fit an answer - places and suggestions are
    the bulk - while the keys alone do; ask for one full row by `filter` when needed.
    Every full row carries the count, up to a few places to look at, and `suggestion` - the
    platform's own spelling where it has one. A suggestion is a HINT, not an answer: a name
    the project declared may need a different word; a literal never carries one, because
    between the quotes stands as often a sentence as a name.
    The key of a literal row is the text between the quotes exactly as the source writes it,
    escaping included (an inner quote reads \\"), and that is the spelling to send back to
    translate_set - on both sides of the entry.
    """
    from xbsl.translation import cli as translate_cli
    from xbsl.translation import entries as entries_module

    refusal = entries_module.kind_refusal(kind)
    if refusal:
        return {"error": refusal}
    project, dictionary, error = translate_cli.load_for_tools(root)
    if error:
        return {"error": error}
    needle = (filter or "").casefold()
    rows = [
        gap for gap in entries_module.gaps_of_project(project, dictionary)
        if (kind in ("any", gap.kind)) and (not needle or needle in gap.key.casefold())
    ]
    page = rows[offset:offset + limit] if limit else rows[offset:]
    out = {"total": len(rows), "dictionary": str(translate_cli.dictionary_path_for(project))}
    if compact:
        out["gaps"] = [{"key": gap.key, "kind": gap.kind, "count": gap.count} for gap in page]
        return out
    out["gaps"] = [
        {**gap.as_dict(), "places": [f"{f}:{ln}" for f, ln in gap.places[:3]]}
        for gap in page
    ]
    return out


@mcp.tool()
def translate_entries(
    root: str,
    filter: str = "",
    kind: str = "any",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """What the dictionary already says - the way to keep a new entry consistent with it.

    root   – the project directory (a root without a dictionary next to or above it is
             refused with the places looked at);
    filter – a substring of the key OR of the value (look up a root before inventing a word);
    kind   – 'token', 'phrase', 'literal' or 'any'.
    Every row names the file and line it lives on, so an entry can be corrected in place.
    """
    from xbsl.translation import cli as translate_cli
    from xbsl.translation import entries as entries_module

    refusal = entries_module.kind_refusal(kind)
    if refusal:
        return {"error": refusal}
    project, _dictionary, error = translate_cli.load_for_tools(root)
    if error:
        return {"error": error}
    path = translate_cli.dictionary_path_for(project)
    needle = (filter or "").casefold()
    rows = [
        entry for entry in entries_module.read_entries(path)
        if (kind in ("any", entry.kind))
        and (not needle or needle in entry.key.casefold() or needle in entry.value.casefold())
    ]
    page = rows[offset:offset + limit] if limit else rows[offset:]
    return {"total": len(rows), "dictionary": str(path),
            "entries": [entry.as_dict() for entry in page]}


@mcp.tool()
def translate_set(root: str, edits: list[dict] | None = None, edits_file: str = "",
                  target: str = "", comment: str = "") -> dict:
    """Write entries into the dictionary: add new ones, correct existing ones, remove a value.

    root   – the project directory (a root without a dictionary next to or above it is
             refused with the places looked at - the tools never start a dictionary);
    edits_file – a FILE with the batch, and the way to send one of any size: either the
             dictionary's own yaml format (tokens/phrases/literals sections, the same
             quoting as the dictionary files, an empty value removes the entry) or the
             JSON list below. Combines with inline `edits` (the file goes first).
    edits  – [{key, value, kind}]; `kind` is 'token' (default), 'phrase' or 'literal'. The key
             AND the value of a literal are the text between the quotes exactly as the source
             writes it - interpolations and escaping alike: an inner quote is \\", a backslash
             is \\\\, a line break is \\n. Escape once, the way the code already does, never
             twice; the code inside an interpolation is translated by the ordinary pass, and a
             value that is not a literal body comes back in `refused` instead of being
             written. An empty value REMOVES the entry - a half-filled stub is not a
             translation.
    target – the file NEW entries go to (default 090-manual.yaml). An entry that already
             exists is corrected where it lives, whatever the target says.
    comment – the head line a NEWLY created file gets: say what the batch is for ("Names of
             the feature icons"), since only the caller knows. Without it the file gets a
             neutral line naming no author.
    The answer carries `collisions` when a value written here is ALREADY the translation of
    another name of the same scope: two names under one word is what the platform refuses on
    apply, and the entry is written rather than blocked - a qualified key (`<Owner>.<Name>`)
    is exactly how one word is deliberately given to two owners.
    A key may be qualified (`<Owner>.<Name>`) to hold inside one namespace only - that is how
    a word gets one spelling as a dictionary key or a component property and another globally.
    """
    from xbsl.translation import cli as translate_cli
    from xbsl.translation import entries as entries_module

    project, _dictionary, error = translate_cli.load_for_tools(root)
    if error:
        return {"error": error}
    path = translate_cli.dictionary_path_for(project)
    batch: list[dict] = []
    if edits_file:
        try:
            batch.extend(entries_module.read_edits_file(Path(edits_file)))
        except (OSError, ValueError) as exc:
            return {"error": i18n.t("translate.set-unreadable", error=exc)}
    batch.extend(edits or [])
    result = entries_module.write_entries(
        path, batch, target=target or entries_module.DEFAULT_TARGET,
        comment=comment,
    )
    return {**result, "dictionary": str(path)}


_forbid_unknown_arguments()


def main() -> None:
    # The server takes no flags, but --help must still answer as a command: without a parser
    # `xbsl mcp --help` started the server and waited on stdin - a hang, not a help screen.
    i18n.ArgumentParser(
        prog="xbsl-mcp",
        description=i18n.t("cli.help.mcp.description"),
        epilog=i18n.t("cli.help.mcp.epilog"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args()
    mcp.run()


if __name__ == "__main__":
    main()
