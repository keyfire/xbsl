"""LSP-сервер xbsl (`xbsl-lsp`, extra [lsp]).

Сводит в один долгоживущий процесс то, что расширение VS Code раньше делало вызовами
CLI: данные языка и индекс проекта загружаются один раз и остаются в памяти, поэтому
каждое нажатие клавиши не платит за старт интерпретатора и загрузку датасета.

Возможности:
    - живая пофайловая диагностика при открытии и изменении (правила области file, с задержкой);
    - диагностика по всему проекту при сохранении (правила file и project по корню исходников);
    - переход к определению, дополнение и hover по индексу проекта, который держим в памяти;
    - quick fix (code action) для замечаний, к которым приложена механическая правка.

Корень исходников по умолчанию – папка воркспейса; если проект лежит в репозитории глубже,
передайте `--project-root PATH` (абсолютный или относительно этой папки) – это аналог настройки
`xbsl.projectRoot` расширения. Прочие ключи: `--select`, `--ignore`, `--enable` (наборы правил
через запятую), `--data-dir` (корень данных Элемента), `--baseline` (файл базлайна – исключённые
находки гасятся и здесь, как в CLI). Ключи, а не initializationOptions, позволяют одинаково
просто запускать сервер из VS Code, Neovim или JetBrains.
"""

from __future__ import annotations

import argparse
import base64
import threading
from pathlib import Path
from typing import Optional

try:
    from lsprotocol import types as lsp
    from pygls.server import LanguageServer
except ImportError:  # pragma: no cover - extra не установлен
    lsp = None
    LanguageServer = None

from xbsl import __version__, baseline, dataset, docs, engine, i18n, indexer, scaffold
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.lsp_nav import (
    IndexLookup,
    resolve_completions,
    resolve_definition,
    resolve_hover,
    resolve_references,
)
from xbsl.rules._syntax import local_var_types, query_aliases, query_ranges, query_row_columns


def _word_at(line_text: str, character: int) -> str:
    """Идентификатор под курсором в строке (буквы/цифры/подчёркивание), либо пустая строка."""
    n = len(line_text)
    if n == 0:
        return ""
    c = max(0, min(character, n))
    is_word = lambda ch: ch.isalnum() or ch == "_"
    start = c
    while start > 0 and is_word(line_text[start - 1]):
        start -= 1
    end = c
    while end < n and is_word(line_text[end]):
        end += 1
    return line_text[start:end]


def _param(params: object, name: str, default: object = None) -> object:
    """Значение поля из параметров кастомного LSP-запроса (объект pygls или dict)."""
    if params is None:
        return default
    if isinstance(params, dict):
        return params.get(name, default)
    return getattr(params, name, default)


def _opt_str(params: object, name: str) -> Optional[str]:
    value = _param(params, name)
    return str(value) if value is not None else None

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
        self.baseline_arg: Optional[str] = None
        self.baseline: Optional[Path] = None
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


def apply_baseline_file(diags: list[Diagnostic], path: Optional[Path]) -> tuple[list[Diagnostic], Optional[str]]:
    """Гасит исключённые базлайном находки: (оставшиеся, текст проблемы или None).

    Файл читается на каждый прогон: он мал, а внешние правки (запись исключения из
    расширения, git pull) подхватываются без перезапуска сервера. Отсутствующий файл –
    не ошибка: он появится с первым исключением; повреждённый – проблема, о ней сообщаем.
    """
    if path is None or not path.is_file():
        return diags, None
    try:
        data = baseline.load(path)
    except baseline.BaselineError as exc:
        return diags, str(exc)
    kept, _suppressed, _unused = baseline.apply(diags, data, path.parent)
    return kept, None


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
        source="xbsl",
        code=d.rule_id,
        data=data,
    )


def _make_server() -> "LanguageServer":
    server = LanguageServer("xbsl-lsp", f"v{__version__}")

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
        # Полный путь, а не имя: по нему находки сопоставляются с записями базлайна,
        # а structure/xbsl-pair видит настоящего соседа модуля.
        src = engine.load_text(str(path), doc.source)
        diags = engine.run_sources([src], select=STATE.select, ignore=STATE.ignore,
                                   enable=STATE.enable, scopes=("file",))
        diags, problem = apply_baseline_file(diags, STATE.baseline)
        if problem:
            server.show_message_log(f"xbsl-lsp: базлайн не применён: {problem}")
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
            diags, problem = apply_baseline_file(diags, STATE.baseline)
            if problem:
                server.show_message_log(f"xbsl-lsp: базлайн не применён: {problem}")
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
                server.show_message_log(f"xbsl-lsp: индекс не построен: {e}")
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
    # а папку воркспейса – из server.workspace после рукопожатия.

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
        if STATE.baseline_arg:
            # Относительный путь – от папки воркспейса (не от корня исходников): базлайн
            # лежит в корне репозитория, как его видит CI.
            b = Path(STATE.baseline_arg)
            STATE.baseline = b if b.is_absolute() else (folder / b if folder else b)
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

    @server.feature("xbsl/relint")
    def _relint(params: object = None) -> dict:
        # Клиент изменил внешнее состояние (записал исключение в базлайн) – перечитываем:
        # прогон по проекту плюс буфер, из которого исключали (его диагностика живёт отдельно).
        uri = _param(params, "uri")
        if uri:
            schedule_buffer_lint(str(uri))
        schedule_project_lint()
        return {"ok": True}

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

    @server.feature(lsp.TEXT_DOCUMENT_REFERENCES)
    def _references(params: lsp.ReferenceParams) -> Optional[list[lsp.Location]]:
        q = nav_query(params.text_document.uri, params.position)
        if q is None or STATE.lookup is None or STATE.root is None:
            return None
        ctx = getattr(params, "context", None)
        include_declaration = bool(getattr(ctx, "include_declaration", False)) if ctx else False
        locs = resolve_references(STATE.lookup, include_declaration=include_declaration, **q)
        result = [
            lsp.Location(
                uri=path_to_uri(STATE.root / rel),
                range=lsp.Range(
                    lsp.Position(max(0, line - 1), max(0, col)),
                    lsp.Position(max(0, line - 1), max(0, col + length)),
                ),
            )
            for rel, line, col, length in locs
        ]
        return result or None

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

    # --- документация (панель справки в расширении – тонкий клиент к этим методам) --------

    def docs_symbol_at(uri: str, line: int, character: int) -> tuple[Optional[str], str]:
        """(имя для точного резолва, запрос для кандидатов) по позиции курсора.

        Имя – тип локальной переменной либо слово под курсором. Запрос дополняем приёмником перед
        точкой (`Задание.Настроить` -> "Задание Настроить"), чтобы кандидаты-секции метода
        ранжировались по нужному типу, а не по случайному топику руководства.
        """
        path = uri_to_path(uri)
        if path is None:
            return None, ""
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        if line >= len(lines):
            return None, ""
        line_text = lines[line].rstrip("\r")
        word = _word_at(line_text, character)
        if not word:
            return None, ""
        n = len(line_text)
        start = max(0, min(character, n))
        while start > 0 and (line_text[start - 1].isalnum() or line_text[start - 1] == "_"):
            start -= 1
        query = word
        if start >= 1 and line_text[start - 1] == ".":
            receiver = _word_at(line_text, start - 1)
            if receiver and receiver != word:
                query = f"{receiver} {word}"
        offset = sum(len(lines[k]) + 1 for k in range(line)) + character
        try:
            src = engine.load_text(path.name, doc.source)
            var_type = local_var_types(src, offset).get(word)
        except Exception:  # noqa: BLE001 - разбор не должен ронять запрос
            var_type = None
        return (var_type or word), query

    @server.feature("xbsl/docsAvailable")
    def _docs_available(_params: object = None) -> dict:
        return {"available": docs.available()}

    @server.feature("xbsl/docsSearch")
    def _docs_search(params: object) -> dict:
        query = str(_param(params, "query", "") or "")
        limit = int(_param(params, "limit", 20) or 20)
        return {"hits": docs.search(query, limit=limit)}

    @server.feature("xbsl/docsPage")
    def _docs_page(params: object) -> dict:
        return docs.page(str(_param(params, "id", "") or "")) or {}

    @server.feature("xbsl/docsTree")
    def _docs_tree(_params: object = None) -> dict:
        return {"nodes": docs.tree()}

    @server.feature("xbsl/docsAsset")
    def _docs_asset(params: object) -> dict:
        a = docs.asset(str(_param(params, "id", "") or ""))
        if not a:
            return {}
        return {"id": a["id"], "mime": a["mime"], "base64": base64.b64encode(a["bytes"]).decode("ascii")}

    @server.feature("xbsl/docsForSymbol")
    def _docs_for_symbol(params: object) -> dict:
        uri = _param(params, "uri")
        pos = _param(params, "position")
        if not uri or pos is None:
            return {}
        name, query = docs_symbol_at(
            uri, int(_param(pos, "line", 0) or 0), int(_param(pos, "character", 0) or 0)
        )
        if not name:
            return {}
        pid = docs.for_symbol(name)
        if pid:
            return {"name": name, "page": docs.page(pid), "candidates": []}
        # Уверенной страницы нет (метод-секция, неизвестный тип) – отдаём кандидатов на выбор.
        return {"name": name, "page": None, "candidates": docs.search(query, limit=8)}

    # --- скаффолдинг метаданных (дерево расширения – тонкий клиент этих методов) ----------
    #
    # Сервер только вычисляет изменения (xbsl.scaffold) и возвращает полные новые тексты
    # файлов; применяет их клиент через WorkspaceEdit – так сохраняются undo и грязные
    # буферы. Правимые файлы читаются из открытых буферов редактора, а не с диска.

    def _buffer_reader(path: Path) -> str:
        uri = path_to_uri(path)
        open_docs = getattr(server.workspace, "text_documents", None) or {}
        if uri in open_docs:
            return open_docs[uri].source
        return engine.load(path).text

    def _meta_op(op, *args, **kwargs) -> dict:
        try:
            return op(*args, **kwargs).as_dict()
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": str(exc)}

    def _meta_root(params: object) -> Path:
        raw = _param(params, "root")
        if raw:
            return Path(str(raw))
        if STATE.root is not None:
            return STATE.root
        return Path.cwd()

    @server.feature("xbsl/metaCapabilities")
    def _meta_capabilities(_params: object = None) -> dict:
        # kinds – виды, создаваемые без дополнительных параметров (для меню дерева);
        # Отчет требует описания источника и макета, поэтому отдаётся отдельно.
        bare = sorted(k for k in scaffold.KIND_SPECS if k != "Отчет")
        return {
            "version": __version__,
            "kinds": bare,
            "allKinds": sorted(scaffold.KIND_SPECS),
            "fieldKinds": {k: list(v) for k, v in scaffold.KIND_SECTIONS.items()},
            "formKinds": list(scaffold.FORM_KINDS),
        }

    @server.feature("xbsl/metaNewObject")
    def _meta_new_object(params: object) -> dict:
        return _meta_op(
            scaffold.op_new_object,
            Path(str(_param(params, "directory"))),
            str(_param(params, "kind")),
            str(_param(params, "name")),
            scope=_opt_str(params, "scope"),
            environment=_opt_str(params, "environment"),
            access=_opt_str(params, "access"),
            routes=_opt_str(params, "routes"),
        )

    @server.feature("xbsl/metaAddField")
    def _meta_add_field(params: object) -> dict:
        return _meta_op(
            scaffold.op_add_field,
            Path(str(_param(params, "path"))),
            str(_param(params, "fieldKind")),
            str(_param(params, "name")),
            type_=_opt_str(params, "type") or "Строка",
            tabular=_opt_str(params, "tabular"),
            reader=_buffer_reader,
        )

    @server.feature("xbsl/metaAddForm")
    def _meta_add_form(params: object) -> dict:
        raw_forms = _param(params, "forms")
        forms = [str(f) for f in raw_forms] if raw_forms else None
        path = _opt_str(params, "path")
        min_width = _param(params, "cardMinWidth")
        return _meta_op(
            scaffold.op_add_form,
            _meta_root(params),
            name=_opt_str(params, "name"),
            yaml_path=Path(path) if path else None,
            forms=forms,
            overwrite=bool(_param(params, "overwrite", False)),
            card_min_width=int(min_width) if min_width else None,
            card_placeholder=_opt_str(params, "cardPlaceholder"),
            reader=_buffer_reader,
        )

    @server.feature("xbsl/metaAddRoute")
    def _meta_add_route(params: object) -> dict:
        return _meta_op(
            scaffold.op_add_route,
            Path(str(_param(params, "path"))),
            str(_param(params, "routes")),
            reader=_buffer_reader,
        )

    @server.feature("xbsl/metaAddSubsystem")
    def _meta_add_subsystem(params: object) -> dict:
        uses = _param(params, "uses")
        return _meta_op(
            scaffold.op_add_subsystem,
            Path(str(_param(params, "parentDir"))),
            str(_param(params, "name")),
            representation=_opt_str(params, "representation"),
            auto_interface=bool(_param(params, "autoInterface", True)),
            uses=[str(u) for u in uses] if uses else None,
        )

    return server


def main() -> None:
    if LanguageServer is None:
        raise SystemExit(
            "xbsl-lsp: нужен extra [lsp] – установите пакет как `pip install \"xbsl[lsp]\"` (pygls)."
        )
    parser = argparse.ArgumentParser(prog="xbsl-lsp", description="LSP-сервер xbsl (stdio)")
    parser.add_argument("--project-root", help="корень исходников (абсолютный или относительно папки воркспейса)")
    parser.add_argument("--select", help="только эти правила (через запятую)")
    parser.add_argument("--ignore", help="исключить правила (через запятую)")
    parser.add_argument("--enable", help="включить правила поверх набора по умолчанию")
    parser.add_argument(
        "--baseline",
        help="файл базлайна (абсолютный или относительно папки воркспейса) – исключённые "
             "находки гасятся; отсутствующий файл не ошибка, он появится с первым исключением",
    )
    parser.add_argument("--data-dir", help="корень данных Элемента (папка с index.json)")
    parser.add_argument("--lang", choices=i18n.LANGS, help="язык текста замечаний")
    args = parser.parse_args()
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    i18n.set_lang(args.lang)  # None сохраняет порядок env/локаль
    STATE.project_root_arg = args.project_root
    STATE.baseline_arg = args.baseline
    STATE.select = _rule_set(args.select)
    STATE.ignore = _rule_set(args.ignore)
    STATE.enable = _rule_set(args.enable)
    _make_server().start_io()


if __name__ == "__main__":
    main()
