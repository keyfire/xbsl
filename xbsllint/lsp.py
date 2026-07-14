"""The xbsllint LSP server (`xbsllint-lsp`, the [lsp] extra).

Consolidates what the VS Code extension previously did over CLI calls into one
long-living process: the language data and the project index are loaded once and stay
resident, so every keystroke does not pay the interpreter and dataset start-up cost.

Capabilities:
    - live per-file diagnostics on open/change (file-scope rules, debounced);
    - project-wide diagnostics on save (file + project rules over the sources root);
    - go to definition, completion and hover over the resident project index;
    - quick-fix code actions for diagnostics that carry a mechanical fix.

The sources root defaults to the workspace folder; pass `--project-root PATH` (absolute
or relative to the folder) when the repository holds the project deeper inside (the
analog of the extension's `xbsl.projectRoot` setting). Other flags: `--select`,
`--ignore`, `--enable` (comma-separated rule sets), `--data-dir` (the Element data
root). Flags rather than initializationOptions keep the server equally easy to spawn
from VS Code, Neovim or JetBrains.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Optional

try:
    from lsprotocol import types as lsp
    from pygls.server import LanguageServer
except ImportError:  # pragma: no cover - the extra is not installed
    lsp = None
    LanguageServer = None

from xbsllint import __version__, dataset, engine, i18n, indexer
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.lsp_nav import IndexLookup, resolve_completions, resolve_definition, resolve_hover
from xbsllint.rules._syntax import local_var_types, query_aliases, query_ranges, query_row_columns

FILE_DEBOUNCE_S = 0.3
PROJECT_DEBOUNCE_S = 0.7

_SEVERITY = {"error": 1, "warning": 2, "info": 3}  # DiagnosticSeverity
_COMPLETION_KINDS = {
    "object": 7,  # Class
    "enum": 13,
    "family": 7,
    "field": 5,  # Field
    "tabular": 5,  # Field
    "localType": 22,  # Struct
    "enumMember": 20,
    "method": 2,  # Method
    "component": 6,  # Variable
}


class _State:
    def __init__(self) -> None:
        self.root: Optional[Path] = None
        self.project_root_arg: Optional[str] = None
        self.select: Optional[set[str]] = None
        self.ignore: Optional[set[str]] = None
        self.enable: Optional[set[str]] = None
        self.lookup: Optional[IndexLookup] = None
        self.dirty: set[str] = set()  # uri изменён после сохранения
        self.published: set[str] = set()  # uri, которым публиковали диагностики
        self.file_timers: dict[str, threading.Timer] = {}
        self.project_timer: Optional[threading.Timer] = None
        self.project_lock = threading.Lock()


STATE = _State()


def _rule_set(raw: object) -> Optional[set[str]]:
    if not raw:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = [str(p).strip() for p in raw]
    else:
        return None
    return {p for p in parts if p} or None


def _offset_to_position(text: str, offset: int) -> tuple[int, int]:
    offset = max(0, min(offset, len(text)))
    line = text.count("\n", 0, offset)
    start = text.rfind("\n", 0, offset) + 1
    return line, offset - start


def _word_end(line_text: str, col0: int) -> int:
    end = col0
    while end < len(line_text) and (line_text[end].isalnum() or line_text[end] == "_"):
        end += 1
    return max(end, col0 + 1)


def _to_lsp_diag(d: Diagnostic, doc_text: Optional[str]) -> "lsp.Diagnostic":
    line0 = max(0, d.line - 1)
    col0 = max(0, d.col - 1)
    end_col = col0 + 1
    if doc_text is not None:
        lines = doc_text.split("\n")
        if line0 < len(lines):
            end_col = _word_end(lines[line0], col0)
    data = None
    if d.fix is not None and doc_text is not None:
        sl, sc = _offset_to_position(doc_text, d.fix.start)
        el, ec = _offset_to_position(doc_text, d.fix.end)
        data = {"fix": {"startLine": sl, "startCol": sc, "endLine": el, "endCol": ec, "new": d.fix.new}}
    return lsp.Diagnostic(
        range=lsp.Range(lsp.Position(line0, col0), lsp.Position(line0, end_col)),
        message=d.message,
        severity=lsp.DiagnosticSeverity(_SEVERITY.get(d.severity.value, 2)),
        source="xbsllint",
        code=d.rule_id,
        data=data,
    )


def _make_server() -> "LanguageServer":
    server = LanguageServer("xbsllint-lsp", f"v{__version__}")

    def uri_to_path(uri: str) -> Optional[Path]:
        from pygls import uris

        p = uris.to_fs_path(uri)
        return Path(p) if p else None

    def path_to_uri(path: Path) -> str:
        from pygls import uris

        return uris.from_fs_path(str(path)) or path.as_uri()

    def language_of(path: Path) -> str:
        return "xbsl" if path.suffix.lower() == ".xbsl" else "yaml"

    def rel_posix(path: Path) -> Optional[str]:
        if STATE.root is None:
            return None
        try:
            return path.resolve().relative_to(STATE.root.resolve()).as_posix()
        except ValueError:
            return None

    # --- диагностика ------------------------------------------------------------------

    def lint_buffer(uri: str) -> None:
        doc = server.workspace.get_text_document(uri)
        path = uri_to_path(uri)
        if path is None:
            return
        src = engine.load_text(path.name, doc.source)
        diags = engine.run_sources([src], select=STATE.select, ignore=STATE.ignore,
                                   enable=STATE.enable, scopes=("file",))
        server.publish_diagnostics(uri, [_to_lsp_diag(d, doc.source) for d in diags])
        STATE.published.add(uri)

    def schedule_buffer_lint(uri: str) -> None:
        t = STATE.file_timers.pop(uri, None)
        if t:
            t.cancel()
        timer = threading.Timer(FILE_DEBOUNCE_S, lambda: lint_buffer(uri))
        timer.daemon = True
        STATE.file_timers[uri] = timer
        timer.start()

    def project_lint() -> None:
        root = STATE.root
        if root is None:
            return
        if not STATE.project_lock.acquire(blocking=False):
            schedule_project_lint()  # прогон уже идёт – повторим после
            return
        try:
            files = engine.find_sources(root, "*.xbsl") + engine.find_sources(root, "*.yaml")
            sources = [engine.load(p) for p in files]
            diags = engine.run_sources(sources, select=STATE.select, ignore=STATE.ignore, enable=STATE.enable)
            by_uri: dict[str, list] = {}
            texts: dict[str, str] = {}
            for d in diags:
                p = Path(d.path)
                if not p.is_absolute():
                    p = root / p
                uri = path_to_uri(p)
                if uri not in texts:
                    try:
                        texts[uri] = p.read_text(encoding="utf-8-sig")
                    except OSError:
                        texts[uri] = ""
                by_uri.setdefault(uri, []).append(_to_lsp_diag(d, texts[uri]))
            open_dirty = {u for u in STATE.dirty}
            for uri in set(STATE.published) | set(by_uri):
                if uri in open_dirty:
                    continue  # за грязным буфером остаётся его живая пофайловая картина
                server.publish_diagnostics(uri, by_uri.get(uri, []))
            STATE.published = set(by_uri) | (STATE.published & open_dirty)
            # индекс перестраиваем в том же фоновом проходе
            try:
                STATE.lookup = IndexLookup(indexer.build_index(root))
            except Exception as e:  # noqa: BLE001 - индекс не должен ронять диагностику
                server.show_message_log(f"xbsllint-lsp: индекс не построен: {e}")
        finally:
            STATE.project_lock.release()

    def schedule_project_lint() -> None:
        if STATE.project_timer:
            STATE.project_timer.cancel()
        timer = threading.Timer(PROJECT_DEBOUNCE_S, lambda: threading.Thread(target=project_lint, daemon=True).start())
        timer.daemon = True
        STATE.project_timer = timer
        timer.start()

    # --- жизненный цикл ---------------------------------------------------------------
    # initialize зарезервирован pygls; параметры сервер берёт из аргументов запуска,
    # а папку воркспейса - из server.workspace после рукопожатия.

    @server.feature(lsp.INITIALIZED)
    def _initialized(_params: lsp.InitializedParams) -> None:
        folder: Optional[Path] = None
        ws = server.workspace
        if ws is not None:
            if ws.folders:
                first = next(iter(ws.folders.values()))
                folder = uri_to_path(first.uri)
            elif ws.root_path:
                folder = Path(ws.root_path)
        if STATE.project_root_arg:
            p = Path(STATE.project_root_arg)
            STATE.root = p if p.is_absolute() else (folder / p if folder else p)
        else:
            STATE.root = folder
        schedule_project_lint()

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    def _did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        schedule_buffer_lint(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    def _did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        STATE.dirty.add(params.text_document.uri)
        schedule_buffer_lint(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    def _did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        STATE.dirty.discard(params.text_document.uri)
        schedule_project_lint()

    @server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
    def _did_close(params: lsp.DidCloseTextDocumentParams) -> None:
        STATE.dirty.discard(params.text_document.uri)

    # --- навигация ---------------------------------------------------------------------

    def nav_query(uri: str, position: lsp.Position) -> Optional[dict]:
        if STATE.lookup is None:
            return None
        path = uri_to_path(uri)
        if path is None:
            return None
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        if position.line >= len(lines):
            return None
        return {
            "language_id": language_of(path),
            "line_text": lines[position.line].rstrip("\r"),
            "character": position.character,
            "file_stem": path.stem,
            "file_path": rel_posix(path),
        }

    @server.feature(lsp.TEXT_DOCUMENT_DEFINITION)
    def _definition(params: lsp.DefinitionParams) -> Optional[lsp.Location]:
        q = nav_query(params.text_document.uri, params.position)
        if q is None or STATE.lookup is None or STATE.root is None:
            return None
        target = resolve_definition(STATE.lookup, **q)
        if not target:
            return None
        rel, line = target
        pos = lsp.Position(max(0, line - 1), 0)
        return lsp.Location(uri=path_to_uri(STATE.root / rel), range=lsp.Range(pos, pos))

    @server.feature(
        lsp.TEXT_DOCUMENT_COMPLETION,
        lsp.CompletionOptions(trigger_characters=[".", ":"]),
    )
    def _completion(params: lsp.CompletionParams) -> Optional[lsp.CompletionList]:
        if STATE.lookup is None:
            return None
        uri = params.text_document.uri
        path = uri_to_path(uri)
        if path is None:
            return None
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        if params.position.line >= len(lines):
            return None
        prefix = lines[params.position.line][: params.position.character]
        # Контекст курсора разбираем лексером, а не по тексту: ключевые слова двуязычны.
        # Внутри блока Запрос{...} (canonical QUERY) – поля таблицы; типы локальных переменных
        # (canonical VAR/NEW) дают члены их типа после точки.
        offset = sum(len(lines[k]) + 1 for k in range(params.position.line)) + params.position.character
        try:
            src = engine.load_text(path.name, doc.source)
            in_query = any(a <= offset < b for a, b in query_ranges(src))
            query_tables = query_aliases(src, offset) if in_query else {}
            local_vars = local_var_types(src, offset)
            query_rows = query_row_columns(src, offset)
        except Exception:  # noqa: BLE001 - дополнение не должно падать из-за разбора
            in_query, query_tables, local_vars, query_rows = False, {}, {}, {}
        try:
            stdlib_members = dataset.load_json("stdlib.json").get("type_members") or {}
        except Exception:  # noqa: BLE001 - датасет мог не подгрузиться, дополнение не роняем
            stdlib_members = {}
        entries = resolve_completions(
            STATE.lookup,
            language_id=language_of(path),
            line_prefix=prefix,
            file_stem=path.stem,
            in_query=in_query,
            stdlib_members=stdlib_members,
            local_vars=local_vars,
            query_tables=query_tables,
            query_rows=query_rows,
        )
        if entries is None:
            return None
        items = [
            lsp.CompletionItem(
                label=e["label"],
                kind=lsp.CompletionItemKind(_COMPLETION_KINDS.get(e["kind"], 1)),
                detail=e.get("detail"),
                insert_text=e.get("snippet"),
                insert_text_format=lsp.InsertTextFormat.Snippet if e.get("snippet") else None,
            )
            for e in entries
        ]
        return lsp.CompletionList(is_incomplete=False, items=items)

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    def _hover(params: lsp.HoverParams) -> Optional[lsp.Hover]:
        q = nav_query(params.text_document.uri, params.position)
        if q is None or STATE.lookup is None:
            return None
        text = resolve_hover(STATE.lookup, **q)
        if not text:
            return None
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=text))

    # --- code actions (быстрые правки из fix) -------------------------------------------

    @server.feature(lsp.TEXT_DOCUMENT_CODE_ACTION)
    def _code_action(params: lsp.CodeActionParams) -> Optional[list[lsp.CodeAction]]:
        actions: list[lsp.CodeAction] = []
        for d in params.context.diagnostics:
            fix = (d.data or {}).get("fix") if isinstance(d.data, dict) else None
            if not fix:
                continue
            edit = lsp.TextEdit(
                range=lsp.Range(
                    lsp.Position(fix["startLine"], fix["startCol"]),
                    lsp.Position(fix["endLine"], fix["endCol"]),
                ),
                new_text=fix["new"],
            )
            title = f"Fix: {d.code}" if i18n.current_lang() == "en" else f"Исправить: {d.code}"
            actions.append(
                lsp.CodeAction(
                    title=title,
                    kind=lsp.CodeActionKind.QuickFix,
                    diagnostics=[d],
                    edit=lsp.WorkspaceEdit(changes={params.text_document.uri: [edit]}),
                )
            )
        return actions or None

    return server


def main() -> None:
    if LanguageServer is None:
        raise SystemExit(
            "xbsllint-lsp: нужен extra [lsp] – установите пакет как `pip install \"xbsllint[lsp]\"` (pygls)."
        )
    parser = argparse.ArgumentParser(prog="xbsllint-lsp", description="LSP-сервер xbsllint (stdio)")
    parser.add_argument("--project-root", help="корень исходников (абсолютный или относительно папки воркспейса)")
    parser.add_argument("--select", help="только эти правила (через запятую)")
    parser.add_argument("--ignore", help="исключить правила (через запятую)")
    parser.add_argument("--enable", help="включить правила поверх набора по умолчанию")
    parser.add_argument("--data-dir", help="корень данных Элемента (папка с index.json)")
    parser.add_argument("--lang", choices=i18n.LANGS, help="язык текста замечаний")
    args = parser.parse_args()
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    i18n.set_lang(args.lang)  # None сохраняет порядок env/локаль
    STATE.project_root_arg = args.project_root
    STATE.select = _rule_set(args.select)
    STATE.ignore = _rule_set(args.ignore)
    STATE.enable = _rule_set(args.enable)
    _make_server().start_io()


if __name__ == "__main__":
    main()
