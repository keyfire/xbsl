"""The xbsl LSP server (`xbsl-lsp`, extra [lsp]).

Consolidates into one long-lived process what the VS Code extension used to do via CLI
calls: the language data and the project index are loaded once and stay in memory, so
every keystroke does not pay for interpreter startup and dataset loading.

Features:
    - live per-file diagnostics on open and change (file-scope rules, debounced);
    - whole-project diagnostics on save (file and project rules over the source root);
    - go-to-definition, completion and hover over the in-memory project index;
    - quick fix (code action) for findings that carry a mechanical fix.

The source root defaults to the workspace folder; if the project lives deeper in the
repository, pass `--project-root PATH` (absolute or relative to that folder) - the
equivalent of the extension's `xbsl.projectRoot` setting. Other flags: `--select`,
`--ignore`, `--enable` (comma-separated rule sets), `--data-dir` (Element data root),
`--baseline` (baseline file - excluded findings are suppressed here too, as in the CLI).
Flags, rather than initializationOptions, make it equally easy to launch the server from
VS Code, Neovim or JetBrains.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

try:
    from lsprotocol import types as lsp
    from pygls.server import LanguageServer
except ImportError:  # pragma: no cover - the extra is not installed
    lsp = None
    LanguageServer = None

from xbsl import (
    __version__, baseline, bindingcomplete, dataset, docs, engine, formedits, formhandlers,
    formmodel, formsearch, i18n, indexer, metamodel, scaffold, templates, terms, uischema,
)
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.templates import Template, TemplateError
from xbsl.lsp_nav import (
    CHAIN_TAIL_RE,
    IndexLookup,
    chain_at,
    resolve_completions,
    resolve_definition,
    resolve_hover,
    resolve_references,
)
from xbsl.rules._syntax import (
    chain_type_at,
    local_var_types,
    query_aliases,
    query_ranges,
    query_row_columns,
)


def _word_at(line_text: str, character: int) -> str:
    """Identifier under the cursor in the line (letters/digits/underscore), or an empty string."""
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
    """Field value from custom LSP request params (a pygls object or a dict)."""
    if params is None:
        return default
    if isinstance(params, dict):
        return params.get(name, default)
    return getattr(params, name, default)


def _opt_str(params: object, name: str) -> Optional[str]:
    value = _param(params, name)
    return str(value) if value is not None else None


def _opt_str_list(params: object, name: str) -> list[str]:
    """A flat array parameter - the shape custom requests use for anything list-like."""
    value = _param(params, name)
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value]


def open_doc_source(open_docs: dict, path: Path) -> Optional[str]:
    """The source text of the open editor document for `path`, or None when it is not open.

    The open-document map is keyed by the client's uri string, which is normalized differently
    from the server's own (VS Code sends `file:///d%3A/...`, pygls builds `file:///d:/...`), so a
    plain `uri in open_docs` check misses and the caller would fall back to the STALE file on
    disk - fatal for edit offsets computed for the live buffer. Match by the resolved filesystem
    path instead (case-insensitive), which both uri spellings agree on.
    """
    from pygls import uris

    own = uris.from_fs_path(str(path))
    if own and own in open_docs:
        return getattr(open_docs[own], "source", None)
    target = os.path.normcase(os.path.normpath(str(path)))
    for key, doc in open_docs.items():
        fp = uris.to_fs_path(key)
        if fp and os.path.normcase(os.path.normpath(fp)) == target:
            return getattr(doc, "source", None)
    return None


def _plain_params(value: object) -> object:
    """Recursively convert LSP request params into plain Python data.

    pygls deserializes the params of a CUSTOM request into nested namedtuples
    (``pygls.protocol._dict_to_object``): they have neither ``__dict__`` nor
    pair-wise iteration, so both ``vars()`` and ``dict()`` on them raise
    TypeError. Dicts arrive from direct calls (tests, other clients) and pass
    through; objects with ``__dict__`` cover SimpleNamespace-like spellings.
    """
    if isinstance(value, dict):
        return {str(k): _plain_params(v) for k, v in value.items()}
    if isinstance(value, tuple) and hasattr(value, "_asdict"):  # namedtuple
        return {str(k): _plain_params(v) for k, v in value._asdict().items()}
    if isinstance(value, (list, tuple)):
        return [_plain_params(v) for v in value]
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {str(k): _plain_params(v) for k, v in vars(value).items()}
    return value


# Operation-argument keys xbsl/formEdit accepts directly in params (the flat form the
# VS Code panels send). camelCase spellings are normalized by formedits.apply_operation.
_FORM_EDIT_ARG_KEYS = (
    "node", "key", "value", "valueYaml", "parent", "slot", "type", "name",
    "before", "after", "newParent", "container", "newName",
    # wave-3 operations: insert_fragment and property_retype
    "fragment", "newType",
    # wave-5 batch operations (move_nodes/remove_nodes): an ARRAY of node-id strings.
    # An array of scalars survives the pygls params deserialization as is (only nested
    # OBJECTS become namedtuples) - _plain_params passes the strings through untouched.
    "nodes",
)

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
    "snippet": 15,  # Snippet - a code template
}

#: Templates are offered ahead of everything else, the way EDT lists them first: the editor
#: sorts by sortText, and without one it would rank a template against names alphabetically.
_SORT_TEMPLATE = "0"
_SORT_REST = "1"
#: Within the ordinary names, the ones written in the project's own language come first.
_SORT_OWN_LANGUAGE = "0"
_SORT_OTHER_LANGUAGE = "1"

_CYRILLIC = re.compile(r"[А-Яа-яЁё]")
#: `ЯзыкРазработки` of Проект.yaml; the platform standard asks for Russian, so that is the
#: default when the file says nothing.
_DEV_LANGUAGE_RE = re.compile(r"(?m)^ЯзыкРазработки:\s*(\S+)")


@lru_cache(maxsize=8)
def _project_language(root: Optional[str]) -> str:
    """"ru" or "en" - the language the project's sources are written in.

    The platform is bilingual and every stdlib member has both spellings, so completion would
    otherwise offer a Russian project the English half of the catalog interleaved with its own
    names. Read from the nearest Проект.yaml under the workspace root.
    """
    if not root:
        return "ru"
    for candidate in sorted(Path(root).rglob("Проект.yaml"))[:1]:
        match = _DEV_LANGUAGE_RE.search(candidate.read_text(encoding="utf-8", errors="replace"))
        if match:
            return "ru" if _CYRILLIC.search(match.group(1)) else "en"
    return "ru"


def _label_language(label: str) -> str:
    return "ru" if _CYRILLIC.search(label) else "en"


def _sort_text(entry: dict, project_language: str) -> str:
    """sortText: templates first, then the names of the project's own language."""
    if entry["kind"] == "snippet":
        return _SORT_TEMPLATE + entry["label"]
    own = _label_language(entry["label"]) == project_language
    return _SORT_REST + (_SORT_OWN_LANGUAGE if own else _SORT_OTHER_LANGUAGE) + entry["label"]


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
        # The builtin templates plus the user's file, merged once at startup. The file is
        # re-read on the xbsl/templatesReload request, so the panel's edits show up without
        # a restart of the server.
        self.templates_arg: Optional[str] = None
        self.templates_path: Optional[Path] = None
        self.templates: list[Template] = []
        self.dirty: set[str] = set()  # keys changed since the last save
        # key -> the uri diagnostics were published at (see uri_key)
        self.published: dict[str, str] = {}
        # Project-scope findings of the last whole-project pass, by key (see uri_key). A
        # per-file pass (on open and on every keystroke) runs file rules only - without this
        # the project findings of the opened file would vanish from the Problems panel until
        # the next save, which is exactly how it looked to the user.
        self.project_diags: dict[str, list[Diagnostic]] = {}
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
    """Suppresses findings excluded by the baseline: (remaining, problem text or None).

    The file is read on every run: it is small, and external edits (an exclusion written
    by the extension, git pull) are picked up without restarting the server. A missing
    file is not an error: it will appear with the first exclusion; a corrupted one is a
    problem and is reported.
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


def _doc_key(path: Optional[Path], uri: str) -> str:
    """The canonical key of a document - never the uri string itself.

    One file has two spellings: the editor sends `file:///d%3A/...` (the drive colon
    percent-encoded) while the server builds `file:///d:/...`, and on Windows the path is
    case-insensitive besides. Comparing the strings silently never matches, so everything
    keyed per document (the project findings of a file, what has been published, which
    buffers are dirty) is keyed by the normalized path instead.
    """
    return os.path.normcase(str(path)) if path is not None else uri


def _resolve_templates_path(arg: Optional[str], folder: Optional[Path]) -> Optional[Path]:
    """The user's templates file: the explicit --templates, or the CLI default.

    A relative --templates is resolved from the workspace folder. Without the flag the
    server falls back to `.xbsl-templates.json` at the workspace root - the same default
    the CLI uses from its cwd, and the place the panel writes to: what the panel saves,
    the next Ctrl+Space must see.
    """
    if arg:
        p = Path(arg)
        return p if p.is_absolute() else (folder / p if folder else p)
    return folder / templates.DEFAULT_FILE if folder else None


def _make_server() -> "LanguageServer":
    server = LanguageServer("xbsl-lsp", f"v{__version__}")

    def uri_to_path(uri: str) -> Optional[Path]:
        from pygls import uris

        p = uris.to_fs_path(uri)
        return Path(p) if p else None

    def path_to_uri(path: Path) -> str:
        from pygls import uris

        return uris.from_fs_path(str(path)) or path.as_uri()

    def uri_key(uri: str) -> str:
        return _doc_key(uri_to_path(uri), uri)

    def language_of(path: Path) -> str:
        return "xbsl" if path.suffix.lower() == ".xbsl" else "yaml"

    def rel_posix(path: Path) -> Optional[str]:
        if STATE.root is None:
            return None
        try:
            return path.resolve().relative_to(STATE.root.resolve()).as_posix()
        except ValueError:
            return None

    # --- diagnostics ------------------------------------------------------------------

    def lint_buffer(uri: str) -> None:
        doc = server.workspace.get_text_document(uri)
        path = uri_to_path(uri)
        if path is None:
            return
        # Full path, not just the name: findings are matched against baseline entries
        # by it, and structure/xbsl-pair sees the module's real neighbor.
        src = engine.load_text(str(path), doc.source)
        diags = engine.run_sources([src], select=STATE.select, ignore=STATE.ignore,
                                   enable=STATE.enable, scopes=("file",))
        diags, problem = apply_baseline_file(diags, STATE.baseline)
        if problem:
            server.show_message_log(f"xbsl-lsp: базлайн не применён: {problem}")
        # The project findings of this file survive the per-file pass: they come from the
        # last whole-project run (already baselined there) and are refreshed on save.
        # Their positions may lag behind an edited buffer - that beats losing them.
        diags = diags + STATE.project_diags.get(uri_key(uri), [])
        server.publish_diagnostics(uri, [_to_lsp_diag(d, doc.source) for d in diags])
        STATE.published[uri_key(uri)] = uri

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
            schedule_project_lint()  # a run is already in progress - retry afterwards
            return
        try:
            files = engine.find_sources(root, "*.xbsl") + engine.find_sources(root, "*.yaml")
            sources = [engine.load(p) for p in files]
            diags = engine.run_sources(sources, select=STATE.select, ignore=STATE.ignore, enable=STATE.enable)
            diags, problem = apply_baseline_file(diags, STATE.baseline)
            if problem:
                server.show_message_log(f"xbsl-lsp: базлайн не применён: {problem}")
            # Everything is collected by the canonical key; the uri is carried alongside,
            # because publishing needs a uri and the key is not one.
            by_key: dict[str, list] = {}
            uri_of: dict[str, str] = {}
            texts: dict[str, str] = {}
            project_ids = {r.id for r in engine.RULES if r.scope == "project"}
            project_diags: dict[str, list[Diagnostic]] = {}
            for d in diags:
                p = Path(d.path)
                if not p.is_absolute():
                    p = root / p
                uri = path_to_uri(p)
                key = uri_key(uri)
                uri_of.setdefault(key, uri)
                if key not in texts:
                    try:
                        texts[key] = p.read_text(encoding="utf-8-sig")
                    except OSError:
                        texts[key] = ""
                by_key.setdefault(key, []).append(_to_lsp_diag(d, texts[key]))
                if d.rule_id in project_ids:
                    project_diags.setdefault(key, []).append(d)
            STATE.project_diags = project_diags
            open_dirty = set(STATE.dirty)
            for key in set(STATE.published) | set(by_key):
                if key in open_dirty:
                    continue  # a dirty buffer keeps its live per-file picture
                # An open document is answered at the uri the editor itself used.
                server.publish_diagnostics(
                    STATE.published.get(key) or uri_of[key], by_key.get(key, []),
                )
            kept = {k: u for k, u in STATE.published.items() if k in open_dirty}
            STATE.published = {k: STATE.published.get(k) or uri_of[k] for k in by_key} | kept
            # the index is rebuilt in the same background pass
            try:
                STATE.lookup = IndexLookup(indexer.build_index(root))
            except Exception as e:  # noqa: BLE001 - the index must not break diagnostics
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

    # --- lifecycle ----------------------------------------------------------------------
    # initialize is reserved by pygls; the server takes its parameters from the launch
    # arguments, and the workspace folder - from server.workspace after the handshake.

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
            # A relative path is resolved from the workspace folder (not the source root):
            # the baseline lives at the repository root, as CI sees it.
            b = Path(STATE.baseline_arg)
            STATE.baseline = b if b.is_absolute() else (folder / b if folder else b)
        STATE.templates_path = _resolve_templates_path(STATE.templates_arg, folder)
        load_templates()
        schedule_project_lint()

    def load_templates() -> None:
        """The builtin set plus the user's file, if it has one.

        A broken user file must not cost the author the builtin templates - it is reported
        and skipped, exactly as a broken baseline is.
        """
        STATE.templates = templates.load_builtin()
        path = STATE.templates_path
        if path is None or not path.exists():
            return
        try:
            STATE.templates = templates.merge(STATE.templates, templates.load_file(path))
        except (TemplateError, OSError, UnicodeDecodeError) as e:
            server.show_message_log(f"xbsl-lsp: шаблоны не загружены: {e}")

    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    def _did_open(params: lsp.DidOpenTextDocumentParams) -> None:
        schedule_buffer_lint(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
    def _did_change(params: lsp.DidChangeTextDocumentParams) -> None:
        STATE.dirty.add(uri_key(params.text_document.uri))
        schedule_buffer_lint(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    def _did_save(params: lsp.DidSaveTextDocumentParams) -> None:
        STATE.dirty.discard(uri_key(params.text_document.uri))
        schedule_project_lint()

    @server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
    def _did_close(params: lsp.DidCloseTextDocumentParams) -> None:
        STATE.dirty.discard(uri_key(params.text_document.uri))

    @server.feature("xbsl/relint")
    def _relint(params: object = None) -> dict:
        # The client changed external state (wrote an exclusion to the baseline) - re-read:
        # a project run plus the buffer the exclusion came from (its diagnostics live separately).
        uri = _param(params, "uri")
        if uri:
            schedule_buffer_lint(str(uri))
        schedule_project_lint()
        return {"ok": True}

    # --- navigation --------------------------------------------------------------------

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
        # Templates need no index - they must work in a file opened outside a project too,
        # so an absent index degrades to an empty one rather than silencing completion.
        lookup = STATE.lookup if STATE.lookup is not None else IndexLookup({})
        uri = params.text_document.uri
        path = uri_to_path(uri)
        if path is None:
            return None
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        if params.position.line >= len(lines):
            return None
        prefix = lines[params.position.line][: params.position.character]
        # The cursor context is parsed by the lexer, not by text: keywords are bilingual.
        # Inside a Запрос{...} block (canonical QUERY) - table fields; local variable types
        # (canonical VAR/NEW) give the members of their type after the dot.
        offset = sum(len(lines[k]) + 1 for k in range(params.position.line)) + params.position.character
        try:
            catalog = dataset.load_json("stdlib.json")
        except Exception:  # noqa: BLE001 - the dataset may have failed to load, do not break completion
            catalog = {}
        # Entity facets (Пользователи.Объект) complete like any other type; method
        # returns feed the chain-type inference of variables and dotted calls.
        stdlib_members = {
            **(catalog.get("type_members") or {}),
            **(catalog.get("facet_members") or {}),
        }
        returns = catalog.get("member_types") or {}
        try:
            src = engine.load_text(path.name, doc.source)
            in_query = any(a <= offset < b for a, b in query_ranges(src))
            query_tables = query_aliases(src, offset) if in_query else {}
            local_vars = local_var_types(
                src, offset, returns=returns, static_roots=stdlib_members.keys(),
            )
            query_rows = query_row_columns(src, offset)
            # `ЗапросКБД.Выполнить().` or `Список.НастройкиСервисов.` - the dot continues
            # a chain, the inferred chain type gives the members (the identifier-before-dot
            # path resolves one link only). Not inside Запрос{...}: there a dotted name is
            # a table reference and belongs to the query paths.
            expr_type = None
            if not in_query and CHAIN_TAIL_RE.search(prefix):
                expr_type = chain_type_at(
                    src, offset, var_types=local_vars,
                    returns=returns, static_roots=stdlib_members.keys(),
                )
        except Exception:  # noqa: BLE001 - completion must not fail because of parsing
            in_query, query_tables, local_vars, query_rows = False, {}, {}, {}
            expr_type = None
        entries = resolve_completions(
            lookup,
            language_id=language_of(path),
            line_prefix=prefix,
            file_stem=path.stem,
            in_query=in_query,
            stdlib_members=stdlib_members,
            # The full name catalog, not just the types that have members: a component type
            # without a member page (`АвтоматическаяГруппа`) is still a valid `Тип:` value.
            stdlib_names=catalog.get("names") or [],
            stdlib_globals=catalog.get("globals") or [],
            local_vars=local_vars,
            query_tables=query_tables,
            query_rows=query_rows,
            expr_type=expr_type,
            templates=STATE.templates,
        )
        if entries is None:
            return None
        project_language = _project_language(str(STATE.root) if STATE.root else None)
        items = [
            lsp.CompletionItem(
                label=e["label"],
                kind=lsp.CompletionItemKind(_COMPLETION_KINDS.get(e["kind"], 1)),
                detail=e.get("detail"),
                insert_text=e.get("snippet"),
                insert_text_format=lsp.InsertTextFormat.Snippet if e.get("snippet") else None,
                sort_text=_sort_text(e, project_language),
            )
            for e in entries
        ]
        return lsp.CompletionList(is_incomplete=False, items=items)

    def _variable_type(params: object) -> Optional[tuple[str, str]]:
        """(variable name, inferred type) for a local variable under the cursor, or None."""
        uri = _param(params, "uri") or getattr(getattr(params, "text_document", None), "uri", None)
        pos = _param(params, "position")
        if pos is None:
            pos = getattr(params, "position", None)
        if not uri or pos is None:
            return None
        path = uri_to_path(uri)
        if path is None or language_of(path) != "xbsl":
            return None
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        line_no = int(_param(pos, "line", getattr(pos, "line", 0)) or 0)
        char = int(_param(pos, "character", getattr(pos, "character", 0)) or 0)
        if line_no >= len(lines):
            return None
        line = lines[line_no]
        m = next(
            (m for m in re.finditer(r"[\wА-Яа-яЁё]+", line) if m.start() <= char <= m.end()),
            None,
        )
        if m is None:
            return None
        word = m.group(0)
        offset = sum(len(lines[k]) + 1 for k in range(line_no)) + m.end()
        try:
            catalog = dataset.load_json("stdlib.json")
            members = {
                **(catalog.get("type_members") or {}),
                **(catalog.get("facet_members") or {}),
            }
            src = engine.load_text(path.name, doc.source)
            local_vars = local_var_types(
                src, offset,
                returns=catalog.get("member_types") or {},
                static_roots=members.keys(),
            )
        except Exception:  # noqa: BLE001 - hover must not fail because of parsing
            return None
        var_type = local_vars.get(word)
        if var_type is None:
            return None
        return word, var_type

    def _variable_hover(params: lsp.HoverParams) -> Optional[str]:
        """The inferred type of a local variable under the cursor (`Ответ: ОтветHttp`)."""
        hit = _variable_type(params)
        if hit is None:
            return None
        word, var_type = hit
        return f"**{word}: {var_type}**\n\nлокальная переменная"

    def _hover_type_root(params: object) -> Optional[str]:
        """The stdlib type root to document for the hover target: a local variable's inferred type,
        or the TYPE of a component member (Компоненты.ФлажокЗапрещенВход -> Флажок). The doc link in
        the hover then points at that type. None when the target has no documented type."""
        hit = _variable_type(params)
        if hit is not None:
            return re.split(r"[<?]", hit[1], maxsplit=1)[0].strip() or None
        uri = _param(params, "uri")
        pos = _param(params, "position")
        if not uri or pos is None or STATE.lookup is None:
            return None
        path = uri_to_path(uri)
        if path is None or language_of(path) != "xbsl":
            return None
        doc = server.workspace.get_text_document(uri)
        lines = doc.source.split("\n")
        line_no = int(_param(pos, "line", 0) or 0)
        char = int(_param(pos, "character", 0) or 0)
        if line_no >= len(lines):
            return None
        hit2 = chain_at(lines[line_no].rstrip("\r"), char)
        if not hit2:
            return None
        parts, at = hit2
        if at == 1 and parts[0] == "Компоненты":
            comp = STATE.lookup.component(path.stem, parts[1])
            ctype = comp.get("type") if comp else None
            if ctype:
                return re.split(r"[<?]", ctype, maxsplit=1)[0].strip() or None
        return None

    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    def _hover(params: lsp.HoverParams) -> Optional[lsp.Hover]:
        q = nav_query(params.text_document.uri, params.position)
        if q is None or STATE.lookup is None:
            return None
        text = resolve_hover(STATE.lookup, **q) or _variable_hover(params)
        if not text:
            return None
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=text))

    @server.feature("xbsl/hoverDoc")
    def _hover_doc(params: object) -> dict:
        # The documentation page to show in the hover of a symbol whose type is known: a
        # type/member name directly under the cursor, or the ROOT of a local variable's inferred
        # type (`Ответ: ОтветHttp` -> ОтветHttp). Answers {pageId, symbol, summary} - the one
        # sentence that opens the page, so the hover says WHAT the type is before offering to
        # read about it. {"pageId": null} when no page exists. The client turns pageId into a
        # trusted command link (a server MarkupContent link is untrusted and would not be
        # clickable).
        def answer(pid: str, name: str) -> dict:
            try:
                text = docs.summary(pid)
            except Exception:  # noqa: BLE001 - a missing summary must not lose the link
                text = ""
            return {"pageId": pid, "symbol": name, "summary": text}

        try:
            uri = _param(params, "uri")
            pos = _param(params, "position")
            if uri and pos is not None:
                name, _query = docs_symbol_at(
                    uri, int(_param(pos, "line", 0) or 0), int(_param(pos, "character", 0) or 0)
                )
                if name:
                    pid = docs.for_symbol(name)
                    if pid:
                        return answer(pid, name)
            root = _hover_type_root(params)
            if root:
                pid = docs.for_symbol(root)
                if pid:
                    return answer(pid, root)
        except Exception:  # noqa: BLE001 - the hover must never fail
            return {"pageId": None, "symbol": None}
        return {"pageId": None, "symbol": None}

    # --- code actions (quick fixes from fix) --------------------------------------------

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

    # --- documentation (the extension's help panel is a thin client of these methods) -----

    def docs_symbol_at(uri: str, line: int, character: int) -> tuple[Optional[str], str]:
        """(name for exact resolution, query for candidates) at the cursor position.

        The name is the local variable's type or the word under the cursor. The query is
        extended with the receiver before the dot (`Задание.Настроить` -> "Задание Настроить")
        so that method-section candidates are ranked by the right type rather than by a
        random guide topic.
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
        except Exception:  # noqa: BLE001 - parsing must not break the request
            var_type = None
        return (var_type or word), query

    @server.feature("xbsl/templatesReload")
    def _templates_reload(_params: object = None) -> dict:
        # The panel wrote the user's file - re-read it, so the next Ctrl+Space already offers
        # the edited template (a restart of the server would lose the built index with it).
        load_templates()
        return {"ok": True, "count": len(STATE.templates)}

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
        # No confident page (a method section, an unknown type) - return candidates to choose from.
        return {"name": name, "page": None, "candidates": docs.search(query, limit=8)}

    @server.feature("xbsl/docsByName")
    def _docs_by_name(params: object) -> dict:
        # A type/symbol name -> its documentation page id, title and a one-line summary. Feeds the
        # metadata-tree category tooltip (a brief description plus a link into the docs panel).
        name = str(_param(params, "name", "") or "")
        pid = docs.for_symbol(name) if name else None
        if not pid:
            return {}
        rec = docs.page(pid) or {}
        return {"id": pid, "title": rec.get("title") or name, "summary": docs.summary(pid)}

    # --- ui schema (the designer's palette and properties panel are thin clients) --------

    @server.feature("xbsl/uiSchema")
    def _ui_schema(params: object = None) -> dict:
        # Without parameters - the palette catalog (components, no property lists);
        # with {"component": name} - the full schema of one component. Both degrade to
        # {"available": False} when the dataset has no ui schema (the docsAvailable pattern).
        name = _opt_str(params, "component")
        if name:
            return uischema.component(name)
        return uischema.catalog()

    @server.feature("xbsl/metadataSchema")
    def _metadata_schema(params: object = None) -> dict:
        # The uiSchema counterpart for configuration elements: without parameters - the kinds
        # covered; with {"kind": "Справочник"} - the properties applicable to that kind, so the
        # panel can offer the ones a file does not set yet. Degrades to {"available": False}
        # without generated data. Names follow the project's development language, the way
        # completion does - the panel matches them against the keys written in the yaml.
        if not metamodel.available():
            return {"available": False}
        lang = _project_language(str(STATE.root) if STATE.root else None)
        kind = _opt_str(params, "kind")
        if not kind:
            return {"available": True, "kinds": list(metamodel.kinds())}
        # A nested node asks with its path: `sections` are the collection keys from the root down
        # (Реквизиты, ТабличныеЧасти/Реквизиты), `names` are the `Имя` of the item on each level -
        # the metamodel dispatches by it, so `Код` gets its own class, not the ordinary attribute
        # one. Flat arrays on purpose: nested objects do not survive the pygls deserialization.
        sections = _opt_str_list(params, "sections")
        names = _opt_str_list(params, "names")
        cls = metamodel.class_for_kind(kind)
        if sections:
            path = tuple(zip(sections, list(names) + [None] * (len(sections) - len(names))))
            cls = metamodel.item_class(kind, path)
            if not cls:
                return {"available": True, "kind": kind, "props": {}}
            props = metamodel.localized(metamodel.properties_of_class(cls), lang)
        else:
            props = metamodel.localized(metamodel.properties(kind), lang)
        if not props:
            return {"available": True, "kind": kind, "class": cls, "props": {}}
        enums = {}
        for record in props.values():
            name = record.get("enum")
            if name and name not in enums:
                values = metamodel.enum_values(name)
                enums[name] = [
                    (terms.english(v, "enums") or v) if lang == "en" else v for v in values
                ]
        return {
            "available": True,
            "kind": kind,
            "class": cls,
            "props": props,
            "enums": enums,
        }

    # --- metadata scaffolding (the extension's tree is a thin client of these methods) ----
    #
    # The server only computes the changes (xbsl.scaffold) and returns the complete new
    # file texts; the client applies them via WorkspaceEdit - this preserves undo and
    # dirty buffers. Files being edited are read from open editor buffers, not from disk.

    def _buffer_reader(path: Path) -> str:
        # Return the LIVE editor buffer (with unsaved edits), NOT the file on disk: form
        # operations compute text offsets against this text and the client applies the resulting
        # edits to the same live document, so a stale disk copy here corrupts the yaml. Matched
        # by filesystem path (see open_doc_source - the uri string spellings differ).
        open_docs = getattr(server.workspace, "text_documents", None) or {}
        src = open_doc_source(open_docs, path)
        return src if src is not None else engine.load(path).text

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
        # kinds - kinds creatable from a name alone (the tree menu); kinds that need data
        # from the caller (e.g. Отчет - a source and a layout) are not included here but
        # are present in allKinds.
        return {
            "version": __version__,
            "kinds": scaffold.bare_kinds(),
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

    # --- form designer (the structure view is a thin client of these methods) ------------
    #
    # Like the meta* family, the server only computes; the editor applies the edits via
    # WorkspaceEdit (native undo/redo) and re-reads the tree afterwards - node ids are
    # positional and valid only until the next change. Dirty buffers come through
    # _buffer_reader. xbsl/formTree carries the tree with COMPACT properties (key, kind,
    # valuePreview - no spans): enough for the tree view; the full per-property spans
    # come from xbsl/formNodeAt for one node at a time, together with the nearest parent
    # COMPONENT (slots skipped) so the properties panel can serve a slot hit.

    def _form_path(params: object) -> Path:
        uri = _param(params, "uri")
        path = uri_to_path(str(uri)) if uri else None
        if path is None:
            raise scaffold.ScaffoldError(f"Некорректный uri: {uri}")
        return path

    def _form_reader(path: Path) -> str:
        try:
            return _buffer_reader(path)
        except RuntimeError:
            # pygls raises until the workspace exists (a request racing the handshake,
            # or a handler driven directly in tests) - fall back to the file on disk.
            return engine.load(path).text

    @server.feature("xbsl/formTree")
    def _form_tree(params: object) -> dict:
        try:
            form = formedits.load_form(_form_path(params), reader=_form_reader)
        except scaffold.ScaffoldError as exc:
            return {"available": False, "reason": str(exc), "root": None}
        return {
            "available": True,
            "root": formmodel.node_dict(form.root, property_spans=False),
            # The component's own Свойства records (the "Data" panel), NOT tree nodes.
            "componentProperties": formmodel.component_properties_dicts(form),
        }

    @server.feature("xbsl/formNodeAt")
    def _form_node_at(params: object) -> dict:
        try:
            form = formedits.load_form(_form_path(params), reader=_form_reader)
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        node = formmodel.node_at(form, int(_param(params, "offset", 0) or 0))
        if node is None:
            return {"node": None}
        parent = formmodel.parent_component(form, node)
        return {
            "node": formmodel.node_dict(node, property_spans=True, deep=False),
            # The nearest parent COMPONENT without children (null for the root): a slot
            # hit resolves to its owner, a component hit skips its slot.
            "parent": (
                formmodel.node_dict(parent, property_spans=True, deep=False)
                if parent is not None else None
            ),
        }

    @server.feature("xbsl/formEdit")
    def _form_edit(params: object) -> dict:
        # {uri, op, args} or {uri, op, <arguments flat in params>} ->
        # {edits: [{start, end, newText}], node: {id, span} | null, notes?: [str]};
        # offsets are relative to the CURRENT buffer text the edits were computed from.
        # Over the real pygls channel a nested args object arrives as a namedtuple,
        # not a dict (see _plain_params) - both shapes and both spellings are accepted.
        # The property_* operations return a pseudo node id "Свойства/<Имя>" that only
        # carries the record span for the cursor jump.
        raw_args = _plain_params(_param(params, "args"))
        args: dict = raw_args if isinstance(raw_args, dict) else {}
        for key in _FORM_EDIT_ARG_KEYS:
            if key not in args:
                value = _plain_params(_param(params, key))
                if value is not None:
                    args[key] = value
        try:
            text = _form_reader(_form_path(params))
            result = formedits.apply_operation(
                text, str(_param(params, "op", "") or ""), args,
            )
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": str(exc)}
        out = {"edits": result.edits_dicts(), "node": result.node_dict()}
        if result.notes:
            out["notes"] = list(result.notes)
        return out

    @server.feature("xbsl/searchForms")
    def _search_forms(params: object) -> dict:
        # Structural search across forms (hook 10). The extension gathers the form texts (live
        # buffers) and sends two parallel arrays plus the query; the engine zips and matches them.
        # {paths: [str], texts: [str], query: str} -> {matches: [{path, nodeId, name, type, line}]}.
        paths = _param(params, "paths", []) or []
        texts = _param(params, "texts", []) or []
        query = str(_param(params, "query", "") or "")
        forms = [{"path": str(p), "text": str(t)} for p, t in zip(paths, texts)]
        return {"matches": formsearch.search_forms(forms, query)}

    @server.feature("xbsl/bindingComplete")
    def _binding_complete(params: object) -> dict:
        # Component-reference completions for the form binding editor (flat params
        # {uri, prefix}): =Компоненты.<part> –> the form's components, =Компоненты.<comp>.<part>
        # –> members of that component's TYPE. The other binding contexts (=Объект.<attr>,
        # enum values, bindings already used in the form) are the editor's own. The form is
        # taken from the uri stem, the components from the project index and the members from
        # the stdlib dataset. Never raises: any failure degrades to an empty list, like the
        # neighboring defensive endpoints.
        try:
            uri = _param(params, "uri")
            prefix = str(_param(params, "prefix", "") or "")
            path = uri_to_path(str(uri)) if uri else None
            if path is None or STATE.lookup is None:
                return {"completions": []}
            try:
                catalog = dataset.load_json("stdlib.json")
            except Exception:  # noqa: BLE001 - the dataset may be missing, do not break completion
                catalog = {}
            members = {
                **(catalog.get("type_members") or {}),
                **(catalog.get("facet_members") or {}),
            }
            completions = bindingcomplete.complete_binding(
                prefix, form_stem=path.stem, components=STATE.lookup, members=members,
            )
            return {"completions": completions}
        except Exception:  # noqa: BLE001 - a custom request must never crash the server
            return {"completions": []}

    # --- event handlers (hook 1: the properties panel's event rows) ----------------------
    #
    # Compute only, flat request params (top-level scalars - nested params break on the
    # pygls deserialization); the editor applies a multi-file WorkspaceEdit.

    @server.feature("xbsl/moduleHandlers")
    def _module_handlers(params: object) -> dict:
        # {uri} - the component yaml or the module itself. Returns {available, module:
        # uri|null, methods: [...], parseErrors}: available=False (module: null,
        # methods: []) when the paired .xbsl file does not exist.
        try:
            path = _form_path(params)
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        module_path = (
            path if path.suffix.lower() == ".xbsl" else formhandlers.module_path_for(path)
        )
        if not module_path.is_file():
            return {"available": False, "module": None, "methods": []}
        try:
            methods, errors = formhandlers.module_methods(_form_reader(module_path))
        except OSError as exc:
            return {"error": str(exc)}
        return {
            "available": True,
            "module": path_to_uri(module_path),
            "methods": methods,
            "parseErrors": errors,
        }

    @server.feature("xbsl/addHandler")
    def _add_handler(params: object) -> dict:
        """Flat params {uri, node, key, method?, signature?} -> the two-file plan.

        Response: method - the final handler name; created - the module FILE does not
        exist yet: moduleText carries its full content (the client creates the file)
        and moduleEdits is []; methodAdded - a stub was appended (False - bound to an
        existing method); yamlEdits - edits of the yaml buffer (empty when the key
        already binds the method); moduleEdits - edits of the existing module buffer;
        cursor - {uri, offset} of the handler method name (the jump target); notes -
        optional warnings. Offsets are relative to the buffers the plan was computed
        from; the client applies everything as one multi-file WorkspaceEdit.
        """
        try:
            yaml_path = _form_path(params)
            module_path = formhandlers.module_path_for(yaml_path)
            yaml_text = _form_reader(yaml_path)
            module_text = _form_reader(module_path) if module_path.is_file() else None
            plan = formhandlers.add_handler(
                yaml_text, module_text,
                str(_param(params, "node", "") or ""),
                str(_param(params, "key", "") or ""),
                method_name=_opt_str(params, "method"),
                event_signature=_opt_str(params, "signature"),
            )
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": str(exc)}
        module_uri = path_to_uri(module_path)
        edits = lambda items: [
            {"start": e.start, "end": e.end, "newText": e.new_text} for e in items
        ]
        out = {
            "method": plan.method,
            "created": plan.created,
            "methodAdded": plan.method_added,
            "yamlEdits": edits(plan.yaml_edits),
            "moduleUri": module_uri,
            "moduleEdits": edits(plan.module_edits),
            "cursor": {"uri": module_uri, "offset": plan.cursor_offset},
        }
        if plan.created:
            out["moduleText"] = plan.new_module_text
        if plan.notes:
            out["notes"] = list(plan.notes)
        return out

    @server.feature("xbsl/removeHandler")
    def _remove_handler(params: object) -> dict:
        """Flat params {uri, node, key, dropMethod?} -> the two-file plan.

        The mirror of xbsl/addHandler: yamlEdits always unbind the event key, and with
        dropMethod the module loses the handler method itself (its annotations and the
        blank line that separated it). method - the name the key was bound to;
        methodRemoved - whether the module was touched; notes - why it was not (the key
        held an expression, the module has no such method). Offsets are relative to the
        buffers the plan was computed from; the client applies both as one WorkspaceEdit.
        """
        try:
            yaml_path = _form_path(params)
            module_path = formhandlers.module_path_for(yaml_path)
            yaml_text = _form_reader(yaml_path)
            module_text = _form_reader(module_path) if module_path.is_file() else None
            plan = formhandlers.remove_handler(
                yaml_text, module_text,
                str(_param(params, "node", "") or ""),
                str(_param(params, "key", "") or ""),
                drop_method=bool(_param(params, "dropMethod", False)),
            )
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": str(exc)}
        edits = lambda items: [
            {"start": e.start, "end": e.end, "newText": e.new_text} for e in items
        ]
        out = {
            "method": plan.method,
            "methodRemoved": plan.method_removed,
            "yamlEdits": edits(plan.yaml_edits),
            "moduleUri": path_to_uri(module_path),
            "moduleEdits": edits(plan.module_edits),
        }
        if plan.notes:
            out["notes"] = list(plan.notes)
        return out

    # --- object info (the "Data" panel: attributes of the form's object) -----------------

    @server.feature("xbsl/objectInfo")
    def _object_info(params: object) -> dict:
        # The mirror of MCP meta_object_info: flat {root?, name?, path?} -> the same
        # JSON (fields, tabulars, forms, access, register...). root defaults to the
        # server's source root; open module buffers are read through the buffer reader.
        raw_path = _opt_str(params, "path")
        try:
            return scaffold.object_info(
                _meta_root(params),
                name=_opt_str(params, "name"),
                yaml_path=Path(raw_path) if raw_path else None,
                reader=_buffer_reader,
            )
        except scaffold.ScaffoldError as exc:
            return {"error": str(exc)}
        except OSError as exc:
            return {"error": str(exc)}

    return server


def main() -> None:
    if LanguageServer is None:
        raise SystemExit(
            "xbsl-lsp: нужен extra [lsp] – установите пакет как `pip install \"xbsl[lsp]\"` (pygls)."
        )
    parser = i18n.ArgumentParser(prog="xbsl-lsp", description=i18n.t("cli.help.lsp.description"))
    parser.add_argument("--project-root", help=i18n.t("cli.help.lsp.project-root"))
    parser.add_argument("--select", help=i18n.t("cli.help.lsp.select"))
    parser.add_argument("--ignore", help=i18n.t("cli.help.lsp.ignore"))
    parser.add_argument("--enable", help=i18n.t("cli.help.lsp.enable"))
    parser.add_argument("--baseline", help=i18n.t("cli.help.lsp.baseline"))
    parser.add_argument("--templates", help=i18n.t("cli.help.lsp.templates"))
    parser.add_argument("--data-dir", help=i18n.t("cli.help.lsp.data-dir"))
    parser.add_argument("--lang", choices=i18n.LANGS, help=i18n.t("cli.help.lsp.lang"))
    args = parser.parse_args()
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    i18n.set_lang(args.lang)  # None keeps the env/locale precedence
    STATE.project_root_arg = args.project_root
    STATE.baseline_arg = args.baseline
    STATE.templates_arg = args.templates
    STATE.select = _rule_set(args.select)
    STATE.ignore = _rule_set(args.ignore)
    STATE.enable = _rule_set(args.enable)
    _make_server().start_io()


if __name__ == "__main__":
    main()
