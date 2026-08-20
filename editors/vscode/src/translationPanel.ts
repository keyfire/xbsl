// The translation dictionary as a table: every record of `xbsl-translation` next to everything
// the sources still leave uncovered, with the translation editable in place.
//
// A project that translates its sources (`xbsl translate`) keeps its own names, comment lines and
// string literals in a dictionary of several yaml files - thousands of records. Editing them by
// hand is where the mistakes come from: a key in the wrong file, a scope dropped, a record added
// twice. So the panel only draws: reading is `xbsl translate --entries` plus `--gaps`, writing is
// `--set`, and the yaml layout stays the engine's business.
//
// The same data serves the light bulb: a finding of conventions/missing-translation carries the
// exact dictionary key in its `data`, so "translate this" is one click away from the word itself.

import * as vscode from "vscode";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { spawn } from "child_process";
import { lspActive, lspRequest } from "./lspClient";
import { isXbslSource } from "./report";
import { editorColumnFor } from "./reveal";
import { cspMeta, escapeHtml, inlineJson, makeNonce } from "./webviewShared";
import {
  DictionaryEdit,
  DictionaryRow,
  EngineConfig,
  EntryKind,
  MIN_ENGINE,
  RowFilter,
  SetAnswer,
  SortDirection,
  SortKey,
  TranslationTarget,
  TranslationTotals,
  editsPayload,
  filterRows,
  mergeRows,
  outdatedEngine,
  pageOf,
  parseEntries,
  parseGaps,
  parseSetResult,
  parseSummary,
  plannedActions,
  refusalText,
  rowStats,
  setArgs,
  shortKey,
  sortRows,
  translateArgs,
  translationTarget,
  versionArgs,
} from "./translationCore";

const VIEW_TYPE = "xbsl.translation";
const SET_COMMAND = "xbsl.translate.set";
const PANEL_COMMAND = "xbsl.translate.dictionary";
// How many rows the webview is handed at once. The dictionary of a real project runs to tens of
// thousands of records, and a table of that size costs seconds of DOM building for rows nobody
// scrolls to; "show more" adds another page.
const PAGE = 200;
// Above this many characters the key cell is clamped to a few lines. A literal is a whole
// message - in a real project up to some 700 characters - and drawn in full it makes one row
// taller than the window, pushing the rest of the table out of sight; the full text stays
// reachable as the cell's tooltip.
const CLAMPED_KEY = 120;

// How the project root is found - the same resolver the deploy and the metadata tree use, handed
// over at registration (the extension owns the xbsl.projectRoot setting).
type ProjectRootFor = (folder: vscode.WorkspaceFolder) => string;

let projectRootFor: ProjectRootFor = (folder) => folder.uri.fsPath;

// The folder the panel works in: the one holding the active editor, otherwise the first of the
// workspace. A dictionary belongs to a project, and the project is the folder.
function currentFolder(resource?: vscode.Uri): vscode.WorkspaceFolder | undefined {
  const target = resource ?? vscode.window.activeTextEditor?.document.uri;
  return (target ? vscode.workspace.getWorkspaceFolder(target) : undefined) ?? vscode.workspace.workspaceFolders?.[0];
}

function engineConfig(folder: vscode.WorkspaceFolder): EngineConfig {
  const c = vscode.workspace.getConfiguration("xbsl", folder.uri);
  const python = (c.get<string>("linter.pythonPath") || "").trim();
  const command = (c.get<string>("linter.command") || "xbsl").trim();
  return {
    command: python || command,
    usePython: python.length > 0,
    root: projectRootFor(folder),
  };
}

interface RunResult {
  stdout: string;
  error?: string;
  notFound?: boolean;
}

function run(cfg: EngineConfig, args: string[], cwd: string): Promise<RunResult> {
  return new Promise((resolve) => {
    let child;
    try {
      // PYTHONUTF8: without it Python's stdio pipes on Windows use the ANSI codepage, and every
      // key of the dictionary is Cyrillic - the table would come back as mojibake and a write
      // would fail on an encoding error instead of saying what went wrong.
      child = spawn(cfg.command, args, { cwd, env: { ...process.env, PYTHONUTF8: "1" } });
    } catch (e) {
      resolve({ stdout: "", error: String(e), notFound: (e as NodeJS.ErrnoException)?.code === "ENOENT" });
      return;
    }
    let out = "";
    let err = "";
    child.on("error", (e) =>
      resolve({ stdout: "", error: String(e), notFound: (e as NodeJS.ErrnoException)?.code === "ENOENT" })
    );
    child.stdout.on("data", (d: Buffer) => (out += d.toString("utf8")));
    child.stderr.on("data", (d: Buffer) => (err += d.toString("utf8")));
    child.on("close", () => resolve({ stdout: out, error: out.trim() ? undefined : err.trim() || undefined }));
    child.stdin.end();
  });
}

function engineFailed(res: RunResult): string {
  return res.notFound
    ? vscode.l10n.t("xbsl was not found. Install it to work with the translation dictionary.")
    : String(res.error ?? "");
}

// True when the dictionary must not be touched at all: the engine is missing, or it is older
// than the commands the panel is built on. Without this check an old engine meets `--entries`
// and answers with an argparse dump ("unrecognized arguments") that the panel would pass on as
// the reason the dictionary cannot be read - naming neither the cause nor the cure. The version
// is read the way the status bar reads it: `<engine> --version`, out of whichever stream it
// arrives in.
// Folders whose engine already answered "new enough" - one process per folder per session.
// Only the YES is remembered: the check runs before every write from the lightbulb, and an
// engine that was too old a minute ago is exactly the one the user just went to update.
const engineFit = new Set<string>();

async function engineUnfit(folder: vscode.WorkspaceFolder): Promise<boolean> {
  if (engineFit.has(folder.uri.fsPath)) {
    return false;
  }
  const cfg = engineConfig(folder);
  const res = await run(cfg, versionArgs(cfg), folder.uri.fsPath);
  if (res.notFound) {
    void vscode.window.showErrorMessage(engineFailed(res));
    return true;
  }
  const installed = outdatedEngine(`${res.stdout} ${res.error ?? ""}`);
  if (!installed) {
    engineFit.add(folder.uri.fsPath);
    return false;
  }
  void vscode.window.showErrorMessage(
    vscode.l10n.t(
      "The translation dictionary needs the xbsl engine {0} or newer, and {1} is installed. Update it: pip install -U xbsl.",
      MIN_ENGINE,
      installed
    )
  );
  return true;
}

interface LoadedDictionary {
  rows: DictionaryRow[];
  dictionary: string;
  totals?: TranslationTotals;
}

// One reading of everything the table shows. The three runs are independent, so they go in
// parallel: on a real project each of them walks the whole source tree and takes seconds.
async function loadDictionary(folder: vscode.WorkspaceFolder): Promise<LoadedDictionary | undefined> {
  const cfg = engineConfig(folder);
  const cwd = folder.uri.fsPath;
  const [entriesRun, gapsRun, summaryRun] = await Promise.all([
    run(cfg, translateArgs("entries", cfg, { limit: 0 }), cwd),
    run(cfg, translateArgs("gaps", cfg, { limit: 0 }), cwd),
    run(cfg, translateArgs("summary", cfg), cwd),
  ]);
  for (const res of [entriesRun, gapsRun]) {
    if (res.error) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("Failed to read the translation dictionary: {0}", engineFailed(res))
      );
      return undefined;
    }
  }
  try {
    const entries = parseEntries(entriesRun.stdout);
    const gaps = parseGaps(gapsRun.stdout);
    let totals: TranslationTotals | undefined;
    try {
      totals = summaryRun.error ? undefined : parseSummary(summaryRun.stdout);
    } catch {
      totals = undefined; // the coverage line is a nicety; the table must not fall with it
    }
    return { rows: mergeRows(entries.entries, gaps.gaps), dictionary: entries.dictionary || gaps.dictionary, totals };
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to read the translation dictionary: {0}", e instanceof Error ? e.message : String(e))
    );
    return undefined;
  }
}

// Writing goes through the engine: the edits are handed over as the file `--set` reads, and the
// file is removed afterwards whatever happened.
export async function writeEdits(
  folder: vscode.WorkspaceFolder,
  edits: DictionaryEdit[]
): Promise<SetAnswer | undefined> {
  const cfg = engineConfig(folder);
  const file = path.join(os.tmpdir(), `xbsl-translate-${process.pid}-${Date.now()}.json`);
  try {
    fs.writeFileSync(file, editsPayload(edits), "utf8");
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to write the translation: {0}", e instanceof Error ? e.message : String(e))
    );
    return undefined;
  }
  try {
    const res = await run(cfg, setArgs(cfg, file), folder.uri.fsPath);
    if (res.error) {
      void vscode.window.showErrorMessage(vscode.l10n.t("Failed to write the translation: {0}", engineFailed(res)));
      return undefined;
    }
    const answer = parseSetResult(res.stdout);
    // The engine turns an edit away when the value could not stand between the quotes of a
    // string literal, and it says so in the same answer that reports what it DID write - the
    // run is not a failure. Passed over, the entry would silently be missing from the
    // dictionary while the status line congratulated the author on an update.
    if (answer.refused.length > 0) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("The engine refused the translation: {0}", refusalText(answer.refused))
      );
    }
    return answer;
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to write the translation: {0}", e instanceof Error ? e.message : String(e))
    );
    return undefined;
  } finally {
    try {
      fs.rmSync(file, { force: true });
    } catch {
      /* a leftover in the temp directory is not worth a message */
    }
  }
}

// Opens a file at a line: the occurrence of an untranslated word in the sources, or the record in
// the dictionary yaml. The editor group is the one the sources already live in - the panel keeps
// its own.
async function openAt(file: string, line: number, root?: string): Promise<void> {
  const full = path.isAbsolute(file) ? file : path.join(root ?? "", file);
  try {
    const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(full));
    const at = new vscode.Position(Math.max(0, line - 1), 0);
    await vscode.window.showTextDocument(doc, {
      viewColumn: editorColumnFor(doc.uri, vscode.ViewColumn.One),
      selection: new vscode.Range(at, at),
    });
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to open {0}: {1}", full, e instanceof Error ? e.message : String(e))
    );
  }
}

// What the user is looking at: the filter, the order and how much of the table has been unfolded.
// It lives in the extension (the webview keeps a copy for a restart) so that a write can redraw
// the table without losing the place.
interface ViewState extends RowFilter {
  sortBy: SortKey;
  sortDir: SortDirection;
  shown: number;
}

const DEFAULT_STATE: ViewState = {
  search: "",
  gapsOnly: false,
  kind: "any",
  // Gaps carry occurrences, records do not, so "the most frequent first" puts what is worth
  // fixing at the top without a mode of its own.
  sortBy: "count",
  sortDir: "desc",
  shown: PAGE,
};

class TranslationPanel {
  public static current: TranslationPanel | undefined;
  private rows: DictionaryRow[] = [];
  private dictionary = "";
  private totals: TranslationTotals | undefined;
  // Whether the engine is running right now. The webview needs it: an empty table during the
  // first read must say "the engine is working", not "there is no dictionary".
  private loading = false;
  private state: ViewState = { ...DEFAULT_STATE };
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(private readonly panel: vscode.WebviewPanel, private readonly folder: vscode.WorkspaceFolder) {
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage((m) => void this.onMessage(m), null, this.disposables);
  }

  public static async show(filter?: Partial<ViewState>, resource?: vscode.Uri): Promise<void> {
    const folder = currentFolder(resource);
    if (!folder) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: no open folder - there is no project to show the dictionary of.")
      );
      return;
    }
    if (TranslationPanel.current) {
      TranslationPanel.current.panel.reveal(vscode.ViewColumn.Active);
      if (filter) {
        TranslationPanel.current.applyState(filter);
      }
      return;
    }
    // Asked before the tab is created: an empty panel over an unusable engine is worse than no
    // panel at all - it looks like the project has no dictionary.
    if (await engineUnfit(folder)) {
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      VIEW_TYPE,
      vscode.l10n.t("XBSL: translation dictionary"),
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    await TranslationPanel.adopt(panel, folder, filter);
  }

  // Take over a panel - a fresh one, or one VS Code restored after a restart. The dictionary is
  // re-read either way: it is a file on disk that anything could have changed meanwhile.
  public static async adopt(
    panel: vscode.WebviewPanel,
    folder: vscode.WorkspaceFolder,
    filter?: Partial<ViewState>
  ): Promise<void> {
    TranslationPanel.current?.dispose();
    const created = new TranslationPanel(panel, folder);
    TranslationPanel.current = created;
    if (filter) {
      created.state = { ...created.state, ...filter };
    }
    panel.webview.html = created.html();
    await created.reload();
  }

  private applyState(patch: Partial<ViewState>): void {
    this.state = { ...this.state, ...patch };
    this.post();
  }

  // Re-reads the dictionary from the engine and redraws. Progress is shown in the window: the
  // three runs walk the whole project and a silent panel looks stuck.
  public async reload(): Promise<void> {
    this.loading = true;
    this.panel.webview.postMessage({ type: "busy", on: true });
    try {
      const loaded = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Window,
          title: vscode.l10n.t("XBSL: reading the translation dictionary..."),
        },
        () => loadDictionary(this.folder)
      );
      if (loaded) {
        this.rows = loaded.rows;
        this.dictionary = loaded.dictionary;
        this.totals = loaded.totals;
      }
    } finally {
      this.loading = false;
    }
    this.post();
  }

  // The page the webview draws, plus everything the header says about it.
  private post(): void {
    const filtered = sortRows(filterRows(this.rows, this.state), this.state.sortBy, this.state.sortDir);
    this.panel.webview.postMessage({
      type: "rows",
      rows: pageOf(filtered, this.state.shown),
      stats: rowStats(filtered, this.state.shown),
      loaded: this.rows.length,
      dictionary: this.dictionary,
      totals: this.totals,
      state: this.state,
      busy: this.loading,
    });
  }

  private async onMessage(msg: {
    type: string;
    key?: string;
    kind?: EntryKind;
    value?: string;
    file?: string;
    line?: number;
    state?: Partial<ViewState>;
  }): Promise<void> {
    if (msg.type === "state" && msg.state) {
      this.applyState(msg.state);
      return;
    }
    if (msg.type === "reload") {
      await this.reload();
      return;
    }
    if (msg.type === "set" && msg.key !== undefined && msg.kind) {
      await this.write(msg.kind, msg.key, msg.value ?? "");
      return;
    }
    if (msg.type === "place" && msg.file) {
      await openAt(msg.file, msg.line ?? 1, projectRootFor(this.folder));
      return;
    }
    if (msg.type === "dict" && msg.file) {
      await openAt(msg.file, msg.line ?? 1);
    }
  }

  // An edited cell. On failure the table is NOT thrown away: the message says what happened and
  // the row is redrawn from the data still in hand, so a typo in one cell does not cost the page.
  private async write(kind: EntryKind, key: string, value: string): Promise<void> {
    this.loading = true;
    this.panel.webview.postMessage({ type: "busy", on: true });
    let result: SetAnswer | undefined;
    try {
      result = await writeEdits(this.folder, [{ key, value: value.trim(), kind }]);
    } finally {
      this.loading = false;
    }
    if (!result || result.refused.length > 0) {
      // Failed or refused: the message is already up, and the cell keeps what the author
      // typed, so a wrong quote costs the keystroke and not the whole page.
      this.post();
      return;
    }
    await this.reload();
  }

  private html(): string {
    const nonce = makeNonce();
    const t = {
      title: vscode.l10n.t("Translation dictionary"),
      lead: vscode.l10n.t(
        "The project's own names, comment lines and string literals as `xbsl translate` sees them: what the dictionary already covers and what it does not. An edited cell is written by the engine into the dictionary yaml."
      ),
      search: vscode.l10n.t("Search by key or translation"),
      gapsOnly: vscode.l10n.t("only untranslated"),
      kindAny: vscode.l10n.t("names, comments and literals"),
      kindToken: vscode.l10n.t("names"),
      kindPhrase: vscode.l10n.t("comments"),
      kindLiteral: vscode.l10n.t("literals"),
      reload: vscode.l10n.t("Re-read"),
      more: vscode.l10n.t("Show more"),
      colKind: vscode.l10n.t("Kind"),
      colKey: vscode.l10n.t("Key"),
      colValue: vscode.l10n.t("Translation"),
      colCount: vscode.l10n.t("Occurrences"),
      colPlace: vscode.l10n.t("Where it occurs"),
      colFile: vscode.l10n.t("Dictionary file"),
      token: vscode.l10n.t("name"),
      phrase: vscode.l10n.t("comment"),
      literal: vscode.l10n.t("literal"),
      busy: vscode.l10n.t("the engine is reading the project..."),
      empty: vscode.l10n.t("Nothing matches the filter."),
      noDictionary: vscode.l10n.t(
        "No dictionary found. `xbsl translate` looks for an xbsl-translation directory next to the project or above it."
      ),
      stats: vscode.l10n.t("rows: {0}, untranslated: {1}, shown: {2}"),
      coverage: vscode.l10n.t("coverage {0}% ({1} of {2} surfaces)"),
      // Counted apart from the coverage, the way the engine counts them: the coverage weighs
      // names and comment lines, and a project whose messages are still Cyrillic must not be
      // able to read 100% off this line.
      literals: vscode.l10n.t("literals: {0} translated, {1} left"),
      hintTitle: vscode.l10n.t("the platform's spelling - click to insert"),
      placeTitle: vscode.l10n.t("open the source at this line"),
      fileTitle: vscode.l10n.t("open the dictionary record"),
    };
    return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">${cspMeta(nonce)}
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px;
         font-size: var(--vscode-font-size); }
  h1 { font-size: 15px; margin: 0 0 4px; }
  p.lead { color: var(--vscode-descriptionForeground); margin: 0 0 12px; max-width: 90ch; }
  .bar { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  input[type=search] { flex: 1 1 240px; padding: 4px 6px; background: var(--vscode-input-background);
    color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); }
  select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border, transparent); padding: 3px 6px; }
  button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; padding: 4px 12px; cursor: pointer; border-radius: 2px; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  table { border-collapse: collapse; width: 100%; }
  th { text-align: left; font-weight: 600; padding: 4px 8px; position: sticky; top: 0; cursor: pointer;
       background: var(--vscode-editor-background); user-select: none;
       border-bottom: 1px solid var(--vscode-panel-border); }
  th .dir { color: var(--vscode-descriptionForeground); }
  td { padding: 3px 8px; vertical-align: top;
       border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); }
  td.kind { color: var(--vscode-descriptionForeground); white-space: nowrap; }
  td.key { font-family: var(--vscode-editor-font-family); word-break: break-word; }
  /* A string literal is a whole message; drawn in full its row is taller than the window and
     hides the rest of the table. Four lines with an ellipsis, the whole text in the tooltip. */
  td.key .clamp { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical;
    overflow: hidden; }
  td.count { text-align: right; white-space: nowrap; }
  .scope { color: var(--vscode-descriptionForeground); }
  .cell { position: relative; }
  .cell input { width: 100%; box-sizing: border-box; padding: 2px 4px; font-family: inherit;
    background: var(--vscode-input-background); color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, transparent); }
  .cell .ghost { position: absolute; left: 6px; top: 3px; color: var(--vscode-descriptionForeground);
    cursor: pointer; pointer-events: auto; }
  .cell input:focus ~ .ghost { display: none; }
  a { color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; }
  a:hover { text-decoration: underline; }
  .dim { color: var(--vscode-descriptionForeground); }
  .foot { margin-top: 10px; display: flex; gap: 12px; align-items: center; }
</style></head><body>
<h1>${escapeHtml(t.title)}</h1>
<p class="lead">${escapeHtml(t.lead)}</p>
<div class="bar">
  <input type="search" id="q" placeholder="${escapeHtml(t.search)}">
  <label><input type="checkbox" id="gaps"> ${escapeHtml(t.gapsOnly)}</label>
  <select id="kind">
    <option value="any">${escapeHtml(t.kindAny)}</option>
    <option value="token">${escapeHtml(t.kindToken)}</option>
    <option value="phrase">${escapeHtml(t.kindPhrase)}</option>
    <option value="literal">${escapeHtml(t.kindLiteral)}</option>
  </select>
  <button id="reload">${escapeHtml(t.reload)}</button>
</div>
<div class="dim" id="stats"></div>
<table>
  <thead><tr>
    <th data-sort="kind">${escapeHtml(t.colKind)}</th>
    <th data-sort="key">${escapeHtml(t.colKey)}</th>
    <th data-sort="value">${escapeHtml(t.colValue)}</th>
    <th data-sort="count">${escapeHtml(t.colCount)}</th>
    <th data-sort="place">${escapeHtml(t.colPlace)}</th>
    <th data-sort="file">${escapeHtml(t.colFile)}</th>
  </tr></thead>
  <tbody id="rows"></tbody>
</table>
<div class="foot">
  <button id="more">${escapeHtml(t.more)}</button>
  <span class="dim" id="dict"></span>
</div>
<script nonce="${nonce}">
const vsapi = acquireVsCodeApi();
const TEXT = ${inlineJson(t)};
const PAGE = ${PAGE};
const CLAMPED_KEY = ${CLAMPED_KEY};
const $ = (id) => document.getElementById(id);
// The extension's state comes inlined (a panel opened from a finding is already filtered by its
// key); what the webview itself remembers wins over it, which is exactly the restore after a
// window restart - a fresh panel has nothing remembered.
let state = Object.assign(${inlineJson(this.state)}, vsapi.getState() || {});
let busy = true;
let last = { rows: [], stats: { total: 0, gaps: 0, shown: 0 }, loaded: 0, dictionary: "", totals: null };

function pushState(patch) {
  state = Object.assign({}, state, patch);
  vsapi.setState(state);
  vsapi.postMessage({ type: "state", state: state });
}

function syncControls() {
  if ($("q").value !== (state.search || "")) { $("q").value = state.search || ""; }
  $("gaps").checked = Boolean(state.gapsOnly);
  $("kind").value = state.kind || "any";
  for (const th of document.querySelectorAll("th[data-sort]")) {
    const mark = th.querySelector(".dir");
    if (mark) { mark.remove(); }
    if (th.dataset.sort === state.sortBy) {
      const dir = document.createElement("span");
      dir.className = "dir";
      dir.textContent = state.sortDir === "desc" ? " \\u2193" : " \\u2191";
      th.appendChild(dir);
    }
  }
}

function linkCell(td, text, title, onClick) {
  const a = document.createElement("a");
  a.textContent = text;
  a.title = title;
  a.addEventListener("click", onClick);
  td.appendChild(a);
}

function valueCell(td, row) {
  const box = document.createElement("div");
  box.className = "cell";
  const input = document.createElement("input");
  input.type = "text";
  input.value = row.value;
  input.spellcheck = false;
  const submit = () => {
    if (input.value === row.value) { return; }
    vsapi.postMessage({ type: "set", kind: row.kind, key: row.key, value: input.value });
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { input.blur(); }
    if (e.key === "Escape") { input.value = row.value; input.blur(); }
  });
  input.addEventListener("blur", submit);
  box.appendChild(input);
  // The platform's own spelling, grey, over the empty cell: a click puts it in and writes it.
  if (!row.value && row.suggestion) {
    const ghost = document.createElement("span");
    ghost.className = "ghost";
    ghost.textContent = row.suggestion;
    ghost.title = TEXT.hintTitle;
    ghost.addEventListener("click", () => {
      input.value = row.suggestion;
      // The row now holds what was written, so the blur that follows the click does not send
      // the very same word a second time.
      row.value = row.suggestion;
      vsapi.postMessage({ type: "set", kind: row.kind, key: row.key, value: row.suggestion });
    });
    box.appendChild(ghost);
  }
  td.appendChild(box);
}

function render() {
  const data = last;
  const body = $("rows");
  body.textContent = "";
  for (const row of data.rows) {
    const tr = body.insertRow();
    const kind = tr.insertCell();
    kind.className = "kind";
    kind.textContent = row.kind === "phrase" ? TEXT.phrase : row.kind === "literal" ? TEXT.literal : TEXT.token;
    const key = tr.insertCell();
    key.className = "key";
    const text = document.createElement("div");
    text.textContent = row.key;
    if (row.key.length > CLAMPED_KEY) {
      // Clamped rather than trimmed: the key is what the engine is asked about, and the tooltip
      // keeps every character of it in reach without costing the table its shape.
      text.className = "clamp";
      text.title = row.key;
    }
    key.appendChild(text);
    if (row.scope) {
      const scope = document.createElement("div");
      scope.className = "scope";
      scope.textContent = row.scope;
      key.appendChild(scope);
    }
    valueCell(tr.insertCell(), row);
    const count = tr.insertCell();
    count.className = "count";
    count.textContent = row.count ? String(row.count) : "";
    const place = tr.insertCell();
    if (row.place) {
      linkCell(place, row.place.file + ":" + row.place.line, TEXT.placeTitle, () =>
        vsapi.postMessage({ type: "place", file: row.place.file, line: row.place.line }));
    }
    const file = tr.insertCell();
    if (row.file) {
      const name = row.file.split(/[\\\\/]/).pop();
      linkCell(file, name, TEXT.fileTitle, () =>
        vsapi.postMessage({ type: "dict", file: row.file, line: row.line }));
    }
  }
  if (!data.rows.length) {
    const tr = body.insertRow();
    const cell = tr.insertCell();
    cell.colSpan = 6;
    cell.className = "dim";
    // While the engine walks the project an empty table must not read as "there is no
    // dictionary": that answer takes seconds to earn.
    cell.textContent = busy ? TEXT.busy : data.loaded ? TEXT.empty : TEXT.noDictionary;
  }
  const stats = TEXT.stats
    .replace("{0}", data.stats.total).replace("{1}", data.stats.gaps).replace("{2}", data.stats.shown);
  let totals = data.totals
    ? " \\u00b7 " + TEXT.coverage
        .replace("{0}", (data.totals.coverage * 100).toFixed(2))
        .replace("{1}", data.totals.translated)
        .replace("{2}", data.totals.surfaces)
    : "";
  // Only when the project has literals at all: on one that does not, the clause would be a
  // column of zeroes saying nothing.
  if (data.totals && (data.totals.literalsTranslated || data.totals.literalsMissing)) {
    totals += " \\u00b7 " + TEXT.literals
      .replace("{0}", data.totals.literalsTranslated)
      .replace("{1}", data.totals.literalsMissing);
  }
  $("stats").textContent = busy ? TEXT.busy : stats + totals;
  $("dict").textContent = data.dictionary || "";
  $("more").style.display = data.stats.shown < data.stats.total ? "" : "none";
}

$("q").addEventListener("input", () => pushState({ search: $("q").value, shown: PAGE }));
$("gaps").addEventListener("change", () => pushState({ gapsOnly: $("gaps").checked, shown: PAGE }));
$("kind").addEventListener("change", () => pushState({ kind: $("kind").value, shown: PAGE }));
$("reload").addEventListener("click", () => vsapi.postMessage({ type: "reload" }));
$("more").addEventListener("click", () => pushState({ shown: state.shown + PAGE }));
for (const th of document.querySelectorAll("th[data-sort]")) {
  th.addEventListener("click", () => {
    const by = th.dataset.sort;
    const dir = state.sortBy === by && state.sortDir === "desc" ? "asc" : "desc";
    pushState({ sortBy: by, sortDir: dir, shown: PAGE });
  });
}

window.addEventListener("message", (e) => {
  const data = e.data;
  if (!data) { return; }
  if (data.type === "busy") {
    busy = data.on;
    render();
    return;
  }
  if (data.type === "rows") {
    busy = Boolean(data.busy);
    last = data;
    state = Object.assign({}, state, data.state);
    vsapi.setState(state);
    syncControls();
    render();
  }
});

syncControls();
render();
// A restored panel asks for its own filter back: the extension drew the table before the webview
// said what it was showing before the restart.
vsapi.postMessage({ type: "state", state: state });
</script></body></html>`;
  }

  private dispose(): void {
    TranslationPanel.current = undefined;
    this.panel.dispose();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

// --- the light bulb on a missing-translation finding ---------------------------------------

// The finding of conventions/missing-translation carries the dictionary key in `data`, so the
// repair does not have to guess it out of a bilingual message. Both modes deliver it: the LSP
// server sends `data` with the diagnostic, and the CLI report carries the same field.
class TranslationActionProvider implements vscode.CodeActionProvider {
  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    for (const diag of context.diagnostics) {
      if (!isXbslSource(diag)) {
        continue;
      }
      const target = translationTarget((diag as { data?: unknown }).data);
      if (!target) {
        continue;
      }
      for (const planned of plannedActions(target)) {
        actions.push(buildAction(document.uri, target, planned.action, planned.value, diag));
      }
    }
    return actions;
  }
}

function buildAction(
  uri: vscode.Uri,
  target: TranslationTarget,
  kind: "apply" | "ask" | "open",
  value: string | undefined,
  diag: vscode.Diagnostic
): vscode.CodeAction {
  const name = shortKey(target.key);
  const title =
    kind === "apply"
      ? vscode.l10n.t("Translate as \"{0}\"", String(value))
      : kind === "ask"
        ? vscode.l10n.t("Translate \"{0}\"...", name)
        : vscode.l10n.t("Open the translation dictionary");
  const action = new vscode.CodeAction(title, vscode.CodeActionKind.QuickFix);
  action.diagnostics = [diag];
  action.isPreferred = kind === "apply";
  action.command =
    kind === "open"
      ? { command: PANEL_COMMAND, title, arguments: [{ search: target.key, gapsOnly: false, kind: target.kind }, uri] }
      : { command: SET_COMMAND, title, arguments: [uri, target, value] };
  return action;
}

// Writes one record. Without a ready value the word is asked for, prefilled with the platform's
// spelling when the rule offered one.
async function setTranslation(uri: vscode.Uri, target: TranslationTarget, value?: string): Promise<void> {
  const folder = currentFolder(uri);
  if (!folder) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("XBSL: the file is outside the workspace - there is no project dictionary to write into.")
    );
    return;
  }
  // The light bulb reaches the engine without the panel, so the same check stands here - and
  // before the input box, so nobody types a word that has nowhere to go.
  if (await engineUnfit(folder)) {
    return;
  }
  let word = value;
  if (word === undefined) {
    word = await vscode.window.showInputBox({
      title: vscode.l10n.t("Translation of \"{0}\"", shortKey(target.key, 80)),
      prompt:
        target.kind === "literal"
          // The value goes back between two quotes of the source, so it is typed the way the
          // source writes it. Said here rather than left to the engine's refusal: the rule is
          // easy to obey and hard to guess.
          ? vscode.l10n.t(
              "The text is written between the quotes of the literal: an inner quote is \\\", a backslash is \\\\."
            )
          : vscode.l10n.t("The word is written into the project's translation dictionary."),
      value: target.suggestion ?? "",
      ignoreFocusOut: true,
      validateInput: (v) => (v.trim() === "" ? vscode.l10n.t("A translation cannot be empty.") : undefined),
    });
  }
  if (word === undefined) {
    return; // the input was cancelled - nothing is written
  }
  const written = word.trim();
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: vscode.l10n.t("XBSL: writing the translation...") },
    () => writeEdits(folder, [{ key: target.key, value: written, kind: target.kind }])
  );
  // A refusal is already on screen with the engine's reason; nothing was written, so there is
  // nothing to re-check and no update to announce.
  if (!result || result.refused.length > 0) {
    return;
  }
  void vscode.window.setStatusBarMessage(
    vscode.l10n.t("XBSL: the dictionary is updated (added {0}, changed {1})", result.added, result.changed),
    5000
  );
  // The finding lives on until the project is checked again: the dictionary is another file, and
  // nothing in the edited document changed. The server re-reads the dictionary by itself (its
  // cache is stamped with the files' mtime), so a project run is enough - no restart.
  if (lspActive()) {
    await lspRequest("xbsl/relint", { uri: uri.toString() });
  } else {
    await vscode.commands.executeCommand("xbsl.restartLinter");
  }
  await TranslationPanel.current?.reload();
}

export function registerTranslation(context: vscode.ExtensionContext, rootFor: ProjectRootFor): void {
  projectRootFor = rootFor;
  context.subscriptions.push(
    vscode.commands.registerCommand(PANEL_COMMAND, (filter?: Partial<ViewState>, resource?: vscode.Uri) =>
      TranslationPanel.show(filter, resource)
    ),
    vscode.commands.registerCommand(SET_COMMAND, (uri: vscode.Uri, target: TranslationTarget, value?: string) =>
      setTranslation(uri, target, value)
    ),
    // Session restore: without a serializer VS Code drops the tab on restart. The panel holds
    // nothing but the filter (the webview keeps that itself) - the dictionary is re-read.
    vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
      async deserializeWebviewPanel(restored: vscode.WebviewPanel): Promise<void> {
        const folder = currentFolder();
        // The engine could have been downgraded between the sessions - a restored tab must say
        // so as plainly as a freshly opened one, and not stay hanging empty.
        if (!folder || (await engineUnfit(folder))) {
          restored.dispose();
          return;
        }
        await TranslationPanel.adopt(restored, folder);
      },
    }),
    vscode.languages.registerCodeActionsProvider(
      [
        { scheme: "file", language: "xbsl" },
        { scheme: "file", language: "yaml" },
      ],
      new TranslationActionProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    )
  );
}
