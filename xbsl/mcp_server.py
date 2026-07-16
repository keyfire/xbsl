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

import re
from html import unescape
from pathlib import Path

from xbsl import docs, report, scaffold
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
    """Страница документации с текстовой (не HTML) выжимкой – в таком виде её удобно читать модели."""
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


# --- scaffolding (метаданные) ---------------------------------------------------------
#
# Пишущие инструменты применяют изменения к диску сами (в отличие от LSP-поверхности,
# где правки применяет редактор) и возвращают {files, notes, lint}: file-scope линт
# записанных файлов входит в тот же ответ. Ошибка операции – структурированное поле
# error, а не исключение: агенту так проще ветвиться.


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
    параметр, поле (structure) or табличная-часть. UUIDs, anchoring and indentation are
    handled here; duplicates and sections invalid for the object's kind are rejected.

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


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
