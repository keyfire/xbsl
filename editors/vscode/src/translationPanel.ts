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
  ColumnWidths,
  DEFAULT_COLUMN_WIDTHS,
  DictionaryEdit,
  DictionaryGap,
  DictionaryRow,
  EngineConfig,
  EntryKind,
  MIN_COLUMN_WIDTHS,
  MIN_ENGINE,
  RowFilter,
  SetAnswer,
  SortDirection,
  SortKey,
  SuggestAnswer,
  TranslationTarget,
  TranslationTotals,
  editsPayload,
  filterRows,
  guardConcurrent,
  mergeRows,
  outdatedEngine,
  pageOf,
  parseEntries,
  parseGaps,
  EntriesAnswer,
  parseSetResult,
  parseSuggest,
  parseSummary,
  parseTable,
  plannedActions,
  refusalText,
  rowHint,
  rowKey,
  rowStats,
  sanitizeColumnWidths,
  setArgs,
  shortKey,
  sortRows,
  suggestArgs,
  totalsAfterWrite,
  translateArgs,
  translationTarget,
  unknownFlag,
  versionArgs,
} from "./translationCore";

const VIEW_TYPE = "xbsl.translation";
// Where the dragged column widths outlive the panel. The webview remembers them itself
// (`vsapi.setState`), but only for as long as the webview exists: that carries a window restart,
// where VS Code restores the tab, and loses everything the moment the tab is CLOSED - the next
// open builds a new webview with no state at all. The widths are a setting of the reader, not of
// one tab, so they are kept by the extension, and globally rather than per workspace: the table
// is the same table in every project.
const WIDTHS_KEY = "xbsl.translation.colWidths";
const SET_COMMAND = "xbsl.translate.set";
const PANEL_COMMAND = "xbsl.translate.dictionary";
const KEY_COMMAND = "xbsl.translate.setKey";
// SecretStorage keys, named after the environment variables the engine reads them from - the
// mapping stays obvious without a lookup table of its own.
const SECRET_YANDEX_KEY = "XBSL_TRANSLATE_YANDEX_KEY";
const SECRET_YANDEX_FOLDER = "XBSL_TRANSLATE_YANDEX_FOLDER";
const SECRET_GOOGLE_KEY = "XBSL_TRANSLATE_GOOGLE_KEY";
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

function run(cfg: EngineConfig, args: string[], cwd: string, extraEnv: NodeJS.ProcessEnv = {}): Promise<RunResult> {
  return new Promise((resolve) => {
    let child;
    try {
      // PYTHONUTF8: without it Python's stdio pipes on Windows use the ANSI codepage, and every
      // key of the dictionary is Cyrillic - the table would come back as mojibake and a write
      // would fail on an encoding error instead of saying what went wrong.
      // extraEnv: only the `--suggest` run passes anything here (the machine-translation keys) -
      // every other run leaves it empty. Either way the keys travel in the spawned process's own
      // environment and nowhere else: never a setting, never an argument on its command line.
      child = spawn(cfg.command, args, { cwd, env: { ...process.env, PYTHONUTF8: "1", ...extraEnv } });
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

// The machine-translation keys the owner put into SecretStorage, shaped as the environment the
// engine's `--suggest` run reads them from. An empty value is dropped rather than passed as an
// empty string: to the engine the two look identical (its own env lookup only asks "is it set"),
// so there is nothing to gain by passing one and a reader of the spawned process's environment
// would see a name that promises a key that is not really there.
async function secretsEnv(context: vscode.ExtensionContext): Promise<NodeJS.ProcessEnv> {
  const [yandexKey, yandexFolder, googleKey] = await Promise.all([
    context.secrets.get(SECRET_YANDEX_KEY),
    context.secrets.get(SECRET_YANDEX_FOLDER),
    context.secrets.get(SECRET_GOOGLE_KEY),
  ]);
  const env: NodeJS.ProcessEnv = {};
  if (yandexKey) {
    env.XBSL_TRANSLATE_YANDEX_KEY = yandexKey;
  }
  if (yandexFolder) {
    env.XBSL_TRANSLATE_YANDEX_FOLDER = yandexFolder;
  }
  if (googleKey) {
    env.XBSL_TRANSLATE_GOOGLE_KEY = googleKey;
  }
  return env;
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
  gaps: DictionaryGap[];
  dictionary: string;
  totals?: TranslationTotals;
}

// One reading of everything the table shows - one engine run. The three questions the table
// asks (the entries, the gaps, the totals) used to be three processes, and two of them walked
// the whole source tree separately: on a live project that was nine seconds of a machine
// doing the same pass twice. `--table` answers all three out of a single pass.
async function loadDictionary(folder: vscode.WorkspaceFolder): Promise<LoadedDictionary | undefined> {
  const cwd = folder.uri.fsPath;
  if (!tableUnsupported.has(cwd)) {
    const loaded = await loadAsTable(folder);
    if (loaded !== "no-flag") {
      return loaded;
    }
    tableUnsupported.add(cwd);
  }
  return loadInThreeRuns(folder);
}

// Folders whose engine does not know `--table` - the extension and the engine are installed
// apart, so a new panel over an older engine is the ordinary state right after a release. Only
// the NO is remembered, and only for the session: it saves one failed process per re-read, and
// an engine updated meanwhile is picked up by the next window.
const tableUnsupported = new Set<string>();

// The one-run read. Answers "no-flag" - and nothing else - when the engine did not understand
// the flag, so that only that case falls back to the three separate runs.
async function loadAsTable(folder: vscode.WorkspaceFolder): Promise<LoadedDictionary | undefined | "no-flag"> {
  const cfg = engineConfig(folder);
  const res = await run(cfg, translateArgs("table", cfg, { limit: 0 }), folder.uri.fsPath);
  if (res.error) {
    if (unknownFlag(res.error, "--table")) {
      return "no-flag";
    }
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to read the translation dictionary: {0}", engineFailed(res))
    );
    return undefined;
  }
  try {
    const table = parseTable(res.stdout);
    return {
      rows: mergeRows(table.entries, table.gaps),
      gaps: table.gaps,
      dictionary: table.dictionary,
      totals: table.totals,
    };
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to read the translation dictionary: {0}", e instanceof Error ? e.message : String(e))
    );
    return undefined;
  }
}

// The read an engine older than `--table` allows: three runs, independent, so in parallel.
async function loadInThreeRuns(folder: vscode.WorkspaceFolder): Promise<LoadedDictionary | undefined> {
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
    return {
      rows: mergeRows(entries.entries, gaps.gaps),
      gaps: gaps.gaps,
      dictionary: entries.dictionary || gaps.dictionary,
      totals,
    };
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("Failed to read the translation dictionary: {0}", e instanceof Error ? e.message : String(e))
    );
    return undefined;
  }
}

// The dictionary alone, without a pass over the project: what `--set` just changed. This is the
// read after a write - it costs a fraction of the full one, because nothing here looks at the
// sources.
// `quiet` is for the first paint of a reload: the full read follows it immediately and reports
// whatever went wrong, and two message boxes about one broken dictionary say nothing the first
// one did not.
async function readEntries(
  folder: vscode.WorkspaceFolder,
  quiet = false
): Promise<EntriesAnswer | undefined> {
  const cfg = engineConfig(folder);
  const res = await run(cfg, translateArgs("entries", cfg, { limit: 0 }), folder.uri.fsPath);
  const failed = (reason: string): undefined => {
    if (!quiet) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("Failed to read the translation dictionary: {0}", reason)
      );
    }
    return undefined;
  };
  if (res.error) {
    return failed(engineFailed(res));
  }
  try {
    return parseEntries(res.stdout);
  } catch (e) {
    return failed(e instanceof Error ? e.message : String(e));
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

// One `--suggest` run: the machine-translation service fills as much of the untranslated
// remainder as its keys allow, cached entries included. Nothing is written by this call - the
// answer is offered to the table as suggestions, and a write still goes through `writeEdits`,
// the same path a hand-typed cell uses.
async function runSuggest(
  context: vscode.ExtensionContext,
  folder: vscode.WorkspaceFolder,
  provider: string | undefined
): Promise<SuggestAnswer | undefined> {
  const cfg = engineConfig(folder);
  const extraEnv = await secretsEnv(context);
  try {
    const res = await run(cfg, suggestArgs(cfg, provider), folder.uri.fsPath, extraEnv);
    if (res.error) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("Failed to get suggestions from the translation service: {0}", engineFailed(res))
      );
      return undefined;
    }
    return parseSuggest(res.stdout);
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t(
        "Failed to get suggestions from the translation service: {0}",
        e instanceof Error ? e.message : String(e)
      )
    );
    return undefined;
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
  // The reader's own column widths, set by dragging a header border, wider than the panel's
  // ordinary read/sort/filter state but kept in the very same object on purpose: it already
  // survives a panel reopen exactly the way search/sort/filter do, through the same webview
  // state and the same round trip to the extension - a second persistence path would only be a
  // second place for the two copies to drift apart.
  colWidths: ColumnWidths;
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
  colWidths: DEFAULT_COLUMN_WIDTHS,
};

class TranslationPanel {
  public static current: TranslationPanel | undefined;
  private rows: DictionaryRow[] = [];
  // The gaps of the last full read, kept apart from the rows they were merged into: after a
  // cell is written the dictionary half is re-read (cheap - it is yaml) and merged with these
  // again, so a written key does not cost another pass over the project.
  private gaps: DictionaryGap[] = [];
  private dictionary = "";
  private totals: TranslationTotals | undefined;
  // Whether the engine is running right now. The webview needs it: an empty table during the
  // first read must say "the engine is working", not "there is no dictionary".
  private loading = false;
  // Whether the tab is already gone. A read of the dictionary takes seconds and a write takes
  // one, and the reader is free to close the panel in the middle of either: every answer that
  // comes back after that would be delivered to a webview that no longer exists, and VS Code
  // answers such a delivery with a thrown "Webview is disposed" - which surfaced as a modal
  // blaming the command that had started the read.
  private disposed = false;
  private state: ViewState = { ...DEFAULT_STATE };
  private readonly disposables: vscode.Disposable[] = [];
  // The machine-translation service's guesses, by rowKey - filled only after "suggest" is asked
  // for, and offered only where the cell is still empty (`post` checks that). Kept apart from
  // `rows` so a plain re-read of the dictionary never throws away a suggestion nobody accepted or
  // rejected yet.
  private readonly machineSuggestions = new Map<string, string>();
  // The service's own report from the last "suggest" run: cached/requested/refused, and the
  // refusal reasons already formatted (empty when there were none). Shown in the panel's summary
  // line, not only the status-bar message the run also posts - that one is gone in five seconds,
  // far from the panel, and these are the numbers the whole cache module exists to answer: did a
  // click just pay twice for the same text. Kept until the NEXT suggest run replaces it - a plain
  // reload does not touch it, and a failed run leaves the previous report standing rather than
  // wiping it with nothing.
  // `suggested` is the row count of the answer, counted apart from cached/requested/refused
  // because a string literal is never one of those three: it is filled by local substitution,
  // never by a call to the service, so it can offer a suggestion while all three service
  // counters stand at zero. Without this field that state is indistinguishable from "nothing
  // to ask" - a lie the summary line must not tell while a suggestion sits on screen unaccepted.
  private lastMachine:
    | { cached: number; requested: number; refused: number; refusalText: string; suggested: number }
    | undefined;
  // A click while the previous suggest run is still going must not start the engine a second
  // time: `--suggest` reaches a paid external service, and unlike "re-read" (two cheap local
  // reads), a repeat run here spends the service's quota again. The button is also disabled on
  // the client for the same span (see the webview script's `busy` handling) - this is the guard
  // that holds even if a message still gets through.
  private readonly guardedSuggest = guardConcurrent(() => this.suggestJob());

  private constructor(
    private readonly panel: vscode.WebviewPanel,
    private readonly folder: vscode.WorkspaceFolder,
    private readonly context: vscode.ExtensionContext
  ) {
    // Sanitized on the way IN as well as on the way out: what is stored was sanitized when it was
    // written, but a store survives extension versions - a width saved by a build that knew other
    // columns must not reach the table unchecked.
    this.state = {
      ...this.state,
      colWidths: sanitizeColumnWidths(context.globalState.get(WIDTHS_KEY)),
    };
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage((m) => void this.onMessage(m), null, this.disposables);
  }

  public static async show(
    context: vscode.ExtensionContext,
    filter?: Partial<ViewState>,
    resource?: vscode.Uri
  ): Promise<void> {
    const folder = currentFolder(resource);
    if (!folder) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: no open folder - there is no project to show the dictionary of.")
      );
      return;
    }
    // `disposed` is checked, not just the pointer: revealing a panel whose tab is already gone
    // throws "Webview is disposed" at the command, and the reader sees a modal instead of the
    // table. A panel in that state is simply not a panel any more - the command opens a new one.
    if (TranslationPanel.current && !TranslationPanel.current.disposed) {
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
    await TranslationPanel.adopt(context, panel, folder, filter);
  }

  // Take over a panel - a fresh one, or one VS Code restored after a restart. The dictionary is
  // re-read either way: it is a file on disk that anything could have changed meanwhile.
  public static async adopt(
    context: vscode.ExtensionContext,
    panel: vscode.WebviewPanel,
    folder: vscode.WorkspaceFolder,
    filter?: Partial<ViewState>
  ): Promise<void> {
    TranslationPanel.current?.dispose();
    const created = new TranslationPanel(panel, folder, context);
    TranslationPanel.current = created;
    if (filter) {
      created.state = { ...created.state, ...filter };
    }
    panel.webview.html = created.html();
    await created.reload();
  }

  // Every message to the webview goes through here. A panel that is gone silently drops what it
  // would have said: there is nobody to say it to, and the work that produced it (a dictionary
  // written to disk, for one) has already happened either way.
  private send(message: unknown): void {
    if (!this.disposed) {
      void this.panel.webview.postMessage(message);
    }
  }

  private applyState(patch: Partial<ViewState>): void {
    const next = { ...this.state, ...patch };
    // A width the webview sends is already clamped by the drag arithmetic that produced it, but
    // `vsapi.getState()` is a plain JSON blob a person (or an older build of this very panel)
    // could have left in any shape at all - sanitized here, on the one path every width re-enters
    // through, rather than trusted because the client-side drag code usually behaves.
    if (patch.colWidths) {
      next.colWidths = sanitizeColumnWidths(patch.colWidths);
      // Stored on the same path the panel itself learns about a width - the webview mails this
      // once, on mouseup, so this is one write per finished drag and not one per mouse move.
      void this.context.globalState.update(WIDTHS_KEY, next.colWidths);
    }
    this.state = next;
    this.post();
  }

  // Re-reads the dictionary from the engine and redraws. Progress is shown in the window: the
  // three runs walk the whole project and a silent panel looks stuck.
  public async reload(): Promise<void> {
    this.loading = true;
    this.send({ type: "busy", on: true });
    try {
      await this.paintDictionary();
      if (this.disposed) {
        return;
      }
      const loaded = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Window,
          title: vscode.l10n.t("XBSL: reading the translation dictionary..."),
        },
        () => loadDictionary(this.folder)
      );
      if (this.disposed) {
        return;
      }
      if (loaded) {
        this.rows = loaded.rows;
        this.gaps = loaded.gaps;
        this.dictionary = loaded.dictionary;
        this.totals = loaded.totals;
      }
    } finally {
      this.loading = false;
    }
    this.post();
  }

  // The first paint of an opening panel: the dictionary alone, which is a read of yaml files and
  // costs a fraction of the pass. The rows are on screen while the engine still walks the
  // project, and the gaps, the occurrences and the header line join them when it answers. Only
  // when there is nothing on screen yet - a re-read over a full table keeps what the reader is
  // looking at until the fresh answer replaces it.
  private async paintDictionary(): Promise<void> {
    if (this.rows.length > 0) {
      return;
    }
    const entries = await readEntries(this.folder, true);
    if (!entries || this.disposed || this.rows.length > 0) {
      return;
    }
    this.rows = mergeRows(entries.entries, []);
    this.dictionary = entries.dictionary || this.dictionary;
    this.post();
  }

  // The page the webview draws, plus everything the header says about it.
  private post(): void {
    const filtered = sortRows(filterRows(this.rows, this.state), this.state.sortBy, this.state.sortDir);
    // The machine suggestion is folded in only for this page, not stored back into `rows`: it is
    // a ghost like the platform's own hint, gone the moment the cell it belongs to is no longer
    // empty. `rowHint` then picks the one the cell actually shows - the platform's spelling and
    // the machine service's guess used to live in separate columns and could both be on screen;
    // now they share the one field a hand-typed answer fills, so the priority is resolved here,
    // before either reaches the webview.
    const page = pageOf(filtered, this.state.shown).map((row) => {
      const guess = this.machineSuggestions.get(rowKey(row.kind, row.key));
      const withGuess = guess && row.value === "" ? { ...row, machineSuggestion: guess } : row;
      const hint = rowHint(withGuess);
      return hint ? { ...withGuess, hint: hint.value, hintFromMachine: hint.fromMachine } : withGuess;
    });
    this.send({
      type: "rows",
      rows: page,
      stats: rowStats(filtered, this.state.shown),
      loaded: this.rows.length,
      dictionary: this.dictionary,
      totals: this.totals,
      machine: this.lastMachine,
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
    if (msg.type === "suggest") {
      await this.guardedSuggest();
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
    this.send({ type: "busy", on: true });
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
    await this.afterWrite(kind, key, value.trim());
  }

  // What one written cell changes, without asking the engine to walk the project again. The
  // dictionary half IS re-read - it is a read of yaml files and takes a moment - so the row
  // gets the record it landed in and the jump to it works at once; the gaps and the header are
  // stepped forward arithmetically instead. A full pass after every cell cost seconds each
  // time, for an answer that differs from this one in nothing the author typed.
  private async afterWrite(kind: EntryKind, key: string, value: string): Promise<void> {
    const known = this.rows.find((row) => rowKey(row.kind, row.key) === rowKey(kind, key));
    this.totals = totalsAfterWrite(this.totals, {
      kind,
      count: known?.count ?? 0,
      hadValue: Boolean(known?.value),
      hasValue: value.length > 0,
    });
    const entries = await readEntries(this.folder);
    if (this.disposed) {
      return;
    }
    if (entries) {
      this.rows = mergeRows(entries.entries, this.gaps);
      this.dictionary = entries.dictionary || this.dictionary;
    } else if (known) {
      // The re-read failed and said so. The table still shows what was written - the value is
      // on disk either way, and a row snapping back to empty would read as a lost edit.
      known.value = value;
    }
    this.post();
  }

  // Asks the machine-translation service to fill as much of the untranslated remainder as its
  // keys allow. Nothing in the dictionary changes here - the table only grows a suggestion next
  // to every gap the service answered, and accepting one is the same "set" message a hand-typed
  // cell already sends. Only ever run through `guardedSuggest` - never call this directly, or the
  // one-run-at-a-time guarantee it exists for is gone.
  private async suggestJob(): Promise<void> {
    const c = vscode.workspace.getConfiguration("xbsl", this.folder.uri);
    const provider = (c.get<string>("translation.provider") || "").trim() || undefined;
    this.loading = true;
    this.send({ type: "busy", on: true });
    let answer: SuggestAnswer | undefined;
    try {
      answer = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: vscode.l10n.t("XBSL: asking the translation service...") },
        () => runSuggest(this.context, this.folder, provider)
      );
    } finally {
      this.loading = false;
    }
    if (!answer) {
      this.post();
      return;
    }
    for (const row of answer.rows) {
      this.machineSuggestions.set(rowKey(row.kind, row.key), row.value);
    }
    // The dictionary this very run resolved - normally the same one the table already shows in
    // its footer, but it is THIS answer that says where an accepted suggestion is actually about
    // to land, so the footer is kept in step with it rather than left to repeat a stale guess.
    if (answer.dictionary) {
      this.dictionary = answer.dictionary;
    }
    // The panel's own record of this run, read by `post()` into the summary line - the status
    // bar message below says the same numbers once and is gone in five seconds; this is what
    // stays put next to the table until a later suggest run overwrites it.
    this.lastMachine = {
      cached: answer.cached,
      requested: answer.requested,
      refused: answer.refused,
      refusalText: answer.refusals.length > 0 ? refusalText(answer.refusals) : "",
      suggested: answer.rows.length,
    };
    void vscode.window.setStatusBarMessage(
      vscode.l10n.t(
        "XBSL: translation service - {0} cached, {1} requested, {2} refused",
        answer.cached,
        answer.requested,
        answer.refused
      ),
      5000
    );
    // The count alone hides WHAT did not translate; the reason is the only actionable half of
    // a refusal - the same shape `write` already reads out of a refused --set edit.
    if (answer.refusals.length > 0) {
      void vscode.window.showWarningMessage(
        vscode.l10n.t("The translation service refused some entries: {0}", refusalText(answer.refusals))
      );
    }
    this.post();
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
      suggestBtn: vscode.l10n.t("Suggest via translation service"),
      more: vscode.l10n.t("Show more"),
      // Five columns, five one-line headers - the title floor a header used to carry above its
      // own sort words is gone (it said nothing the words below it did not already say), so
      // every heading below is the sort control itself, not a caption over one. Only "key and
      // translation" still names two sort orders at once (`colKey`/`colValue`); every other
      // column sorts by the one thing its own name already says.
      colKind: vscode.l10n.t("Kind"),
      colKey: vscode.l10n.t("Key"),
      colValue: vscode.l10n.t("Translation"),
      colCount: vscode.l10n.t("Occurrences"),
      colPlace: vscode.l10n.t("Where it occurs"),
      colFile: vscode.l10n.t("Dictionary file"),
      // Shown on a hover over a border handle - the one thing about it that is not visible on
      // its own (a resize cursor says "drag me", nothing says "or double-click me").
      resetWidthTitle: vscode.l10n.t("double-click to reset this column's width"),
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
      // The machine-translation service's own report from the last "suggest" run, folded into
      // the same summary line as coverage/literals rather than left only in the status-bar
      // message that already carries it - that one is gone in five seconds and is nowhere near
      // the table. cached/requested/refused are the numbers the whole point of the cache module
      // is to answer, so they live where a person is already looking.
      machineStats: vscode.l10n.t("machine translation: {0} cached, {1} requested, {2} refused"),
      // What "0 cached, 0 requested, 0 refused" actually means: the run found no name or
      // comment gap left to fill, not that the button silently failed - said in words instead
      // of three zeroes, which read the same whether the click worked or did nothing at all.
      // Correct only when nothing was suggested either - see `machineLocalOnly` below for the
      // one case where it would still be a lie.
      machineNothing: vscode.l10n.t("machine translation: nothing to ask - already in the dictionary"),
      // The one gap `machineNothing` cannot cover: a string literal is never counted in
      // cached/requested/refused, because it is never asked of the service at all - it is
      // filled by local substitution. All three counters can stand at zero while a literal
      // suggestion just appeared on screen, unaccepted; saying "nothing to ask" there would be
      // false the moment a reader compares it to the table. This is that same zero-counter state
      // told honestly, once a suggestion actually exists to report.
      machineLocalOnly: vscode.l10n.t("machine translation: {0} suggested without asking the service"),
      machineRefusalsTitle: vscode.l10n.t("the translation service refused some entries:"),
      // The keyboard path is named in the tooltip itself, not only offered by the mouse - Enter
      // works while the field is still empty, exactly when the ghost above is showing.
      hintTitle: vscode.l10n.t("the platform's spelling - click the checkmark or press Enter to insert it"),
      machineHintTitle: vscode.l10n.t("the translation service's guess - click the checkmark or press Enter to insert it"),
    };
    return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">${cspMeta(nonce)}
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px;
         font-size: var(--vscode-font-size); }
  h1 { font-size: 15px; margin: 0 0 4px; }
  /* 110ch, not 90: the line is there so a wide panel does not stretch one sentence across a
     whole monitor, and the cap only has to be wider than half the text for it to settle on two
     lines. The Russian caption is 201 characters, the English one 209, and at 90ch both took a
     third line carrying four words. */
  p.lead { color: var(--vscode-descriptionForeground); margin: 0 0 12px; max-width: 110ch; }
  .bar { display: flex; gap: 12px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; }
  input[type=search] { flex: 1 1 240px; padding: 4px 6px; background: var(--vscode-input-background);
    color: var(--vscode-input-foreground); border: 1px solid var(--vscode-input-border, transparent); }
  select { background: var(--vscode-dropdown-background); color: var(--vscode-dropdown-foreground);
    border: 1px solid var(--vscode-dropdown-border, transparent); padding: 3px 6px; }
  /* A checkbox and its label text obey different default alignment rules - the checkbox is a
     replaced element sitting on the text line's baseline, the text is not, and no amount of
     centering the OUTER row fixes that by itself. Flexing this one pair and zeroing the
     checkbox's own default margin (a few px the browser adds on its own, asked for by no rule
     here) is the fix; the footer pair below gets the identical treatment. */
  label.check { display: inline-flex; align-items: center; gap: 6px; }
  label.check input[type=checkbox] { margin: 0; }
  button {
    background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground);
    border: none; padding: 4px 12px; cursor: pointer; border-radius: 2px; font: inherit; margin: 0;
    /* The actual cause of the footer button sitting off from its text, found this round: with
       appearance left at its default "auto", the browser keeps drawing the button with the native
       widget's own vertical metrics, which padding and line-height do not fully describe or
       override - align-items: center on the flex row around it can only center a box it can
       measure, and the native chrome was not fully that box. Turning appearance off leaves sizing
       to the declared padding and border alone; box-sizing: border-box makes "4px 12px" the whole
       height, nothing left implicit for the flex row to guess at. The earlier attempt (matching
       font alone) is why this one checks out both the button and the checkbox at three widths in
       the report, not just at the width it was first seen wrong. */
    appearance: none; -webkit-appearance: none; box-sizing: border-box;
  }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button:disabled { opacity: 0.5; cursor: default; }
  /* separate, not collapse: position: sticky on a <th> renders unreliably with border-collapse
     (chunks of the header detach and paint over scrolled body rows) - border-spacing 0 keeps the
     same seamless look, the sticky behavior is what actually needed the switch.
     table-layout: fixed, not auto - a reader's own dragged width has to be the LAST word on a
     column's size, never quietly reopened by its content. auto only ever treated a column's width
     as a suggestion, which is exactly what let one unbreakable label push its column - and the
     whole table - wider than the panel instead of being cut with an ellipsis, the defect a review
     of the previous round caught with the very same test caption used here. Every column's actual
     pixel width comes from its own <col> in the colgroup below, written by the script from
     state.colWidths (or the column's default, the first time nothing is saved yet) - nothing in
     this stylesheet sets a per-column width, on purpose, so there is exactly one place it can
     come from. The table's OWN width is also set by that same script (applyColgroup, the sum of
     the five columns) - measured this round: table-layout: fixed only takes a <col>'s width as
     literal, load-bearing pixels when the table has an explicit width to anchor to; left at the
     default auto, every column was still being sized by its own content regardless of what the
     colgroup said, the exact defect this whole rule exists to close, reappearing through the one
     gap left open. */
  table { border-collapse: separate; border-spacing: 0; table-layout: fixed; }
  colgroup col { width: 80px; } /* overwritten per-column by the script before first paint */
  /* thead sticky too, alongside each th - redundant, not load-bearing on its own (a sticky th
     already carries its whole box as one unit with no help needed), kept only because some
     engines are documented to behave more reliably when both the row and its cells declare
     position: sticky. */
  thead { position: sticky; top: 0; z-index: 1; }
  /* Every header is one line now by construction - the title floor a header used to carry above
     its own sort words said nothing the words below it did not already say, so removing it also
     removed the only thing that could ever have wrapped this row onto a second line. white-space:
     nowrap is the safety net for the one input the CSS itself does not control - a person can
     still drag a column narrower than its own header word - overflow: hidden with no ellipsis
     here on purpose: a header clipped mid-word is still legible as "the same word, just tight";
     turning it into "..." would cost the one thing a header uniquely needs, the ability to tell
     two adjacent sort words apart without a hover. */
  th { text-align: left; font-weight: 600; padding: 4px 10px 4px 8px; position: sticky; top: 0; z-index: 1;
       background: var(--vscode-editor-background); user-select: none; white-space: nowrap; overflow: hidden;
       border-bottom: 1px solid var(--vscode-panel-border); }
  .sortlbl { cursor: pointer; color: var(--vscode-descriptionForeground); }
  .sortlbl:hover { color: var(--vscode-foreground); text-decoration: underline; }
  .sortlbl.active { color: var(--vscode-foreground); text-decoration: underline; }
  /* Between the key column's two sort words - deliberately not shaped like either of them
     (no pointer cursor, no hover color) so it never reads as a third click target. */
  .sep { color: var(--vscode-descriptionForeground); padding: 0 4px; }
  .dir { color: var(--vscode-descriptionForeground); }
  /* The drag handle: a narrow strip pinned to the header cell's OWN right edge, as a sibling of
     the sort words next to it, never their parent or their child. A mousedown that lands here
     cannot reach a .sortlbl's own click listener at all - there is no shared ancestor between
     "started the drag" and "should fire the sort" for it to bubble through. That is the actual
     separation between click-sorts and drag-resizes; the "just dragged" flag the script also sets
     is only the second, defensive line of it, for the one case a browser still sends a synthetic
     click after the mouseup that ended a drag. th needs no extra position rule for this to anchor
     correctly - position: sticky above already puts th in the "positioned" category, the same one
     position: relative would have, so an absolutely positioned child measures from th's own box. */
  th .handle { position: absolute; top: 0; right: -4px; bottom: 0; width: 8px; cursor: col-resize; z-index: 2; }
  /* The mark that says "here": a hairline down the middle of the grab strip, drawn ALWAYS and not
     only under the pointer. A handle visible on hover alone is a control nobody finds - the widths
     are draggable, and the reader has to run the mouse along the header to discover where. Inset
     from both ends so it reads as a grip of the header rather than as a border of the cell, and
     painted in the panel border colour, which is what the row of headers is already separated
     from the body by. */
  th .handle::after { content: ""; position: absolute; left: 3px; top: 5px; bottom: 5px; width: 1px;
       background: var(--vscode-widget-border, rgba(128,128,128,.35)); }
  th .handle:hover::after, th .handle.dragging::after { top: 0; bottom: 0;
       background: var(--vscode-focusBorder, var(--vscode-textLink-foreground)); }
  th .handle:hover, th .handle.dragging { background: var(--vscode-focusBorder, var(--vscode-textLink-foreground)); opacity: 0.5; }
  td { padding: 3px 8px; vertical-align: top;
       border-bottom: 1px solid var(--vscode-widget-border, rgba(128,128,128,.25)); }
  /* A dictionary record fills two table rows, not one: the kind/key/count/place/file line, then
     the translation input right under it, spanning the full row width. The pair reads as one line
     item - tight between its own two rows, a full border only after the second.
     line-height is shared explicitly by every top-row cell so their first lines start flush with
     each other - vertical-align: top alone is not enough between cells of different font-family
     (kind is the UI font, key the editor font): each font's own "normal" line height differs,
     which is what carried the kind word a few pixels below the key beside it. */
  tr.top td { border-bottom: none; padding-top: 6px; padding-bottom: 2px; line-height: 18px; }
  tr.bottom td { padding-top: 0; padding-bottom: 8px; }
  /* Every one of the five columns gets the same rule, not just the ones that looked likely to
     overflow today: with table-layout: fixed above, a cell can no longer grow past its column's
     set width no matter what it holds - overflow: hidden here is what turns that from a silent,
     hard cut into nothing at all visible. Where the text itself should also get a "...", that
     rule sits on the element that actually CONTAINS the text (a child div or the link itself),
     never on the cell - overflow/text-overflow do not inherit, and a bare cell-level rule would
     still clip the text, just without the mark that says there is more of it. */
  td.kind, td.key, td.count, td.place, td.file { overflow: hidden; }
  td.kind > div, td.count > div, td.file > div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  td.kind { color: var(--vscode-descriptionForeground); }
  /* The key column keeps its own different answer, on purpose: it is the widest, most important
     column, and hiding an untranslated key behind "..." is a worse trade than a taller row -
     word-break: break-word lets even an unbreakable 40-character name wrap onto more lines
     in place instead of pushing the column wider (table-layout: fixed already forbids that) or
     bleeding into the next one. Only a literal past CLAMPED_KEY characters is capped as well, at
     four lines - the one shape that could otherwise run taller than the window and hide the rest
     of the table under it. */
  td.key { font-family: var(--vscode-editor-font-family); word-break: break-word; }
  td.key .clamp { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
  td.count { color: var(--vscode-descriptionForeground); font-size: 0.94em; }
  /* place: a link, not plain text - the ellipsis rule sits on the <a> itself, the element that
     actually overflows, and display: block is what lets an ordinarily inline <a> obey
     white-space/text-overflow at all. Truncated only VISUALLY: the link keeps the row's full
     file and line as its href-equivalent click target regardless of how much of the text is
     showing, and the full path is what the title attribute carries as a tooltip. */
  td.place { color: var(--vscode-descriptionForeground); font-size: 0.94em; }
  td.place a { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  td.file { color: var(--vscode-descriptionForeground); font-size: 0.94em; }
  .scope { color: var(--vscode-descriptionForeground); }
  .cell { position: relative; }
  .cell input { width: 100%; box-sizing: border-box; padding: 4px 6px; font-family: inherit;
    background: var(--vscode-input-background); color: var(--vscode-input-foreground);
    border: 1px solid var(--vscode-input-border, transparent); }
  /* The suggestion itself is the native placeholder - it takes the editor's own placeholder
     color and vanishes by itself the moment anything is typed, no script needed for that part. */
  .cell input::placeholder { color: var(--vscode-input-placeholderForeground, var(--vscode-descriptionForeground)); }
  .cell input.hashint { padding-right: 26px; } /* room on the right for the accept checkmark */
  .cell .accept { position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
    cursor: pointer; color: var(--vscode-textLink-foreground); font-weight: 700; user-select: none; }
  .cell .accept:hover { text-decoration: underline; }
  a { color: var(--vscode-textLink-foreground); text-decoration: none; cursor: pointer; }
  a:hover { text-decoration: underline; }
  .dim { color: var(--vscode-descriptionForeground); }
  .foot { margin-top: 10px; display: flex; gap: 12px; align-items: center; }
</style></head><body>
<h1>${escapeHtml(t.title)}</h1>
<p class="lead">${escapeHtml(t.lead)}</p>
<div class="bar">
  <input type="search" id="q" placeholder="${escapeHtml(t.search)}">
  <label class="check"><input type="checkbox" id="gaps">${escapeHtml(t.gapsOnly)}</label>
  <select id="kind">
    <option value="any">${escapeHtml(t.kindAny)}</option>
    <option value="token">${escapeHtml(t.kindToken)}</option>
    <option value="phrase">${escapeHtml(t.kindPhrase)}</option>
    <option value="literal">${escapeHtml(t.kindLiteral)}</option>
  </select>
  <button id="reload">${escapeHtml(t.reload)}</button>
  <button id="suggest">${escapeHtml(t.suggestBtn)}</button>
</div>
<div class="dim" id="stats"></div>
<table>
  <colgroup>
    <col data-col="kind"><col data-col="key"><col data-col="count"><col data-col="place"><col data-col="file">
  </colgroup>
  <thead><tr>
    <th data-col="kind">${escapeHtml(t.colKind)}<span class="handle" data-col="kind" title="${escapeHtml(t.resetWidthTitle)}"></span></th>
    <th data-col="key">
      <span class="sortlbl" data-sort="key">${escapeHtml(t.colKey)}</span><span class="sep">&middot;</span><span class="sortlbl" data-sort="value">${escapeHtml(t.colValue)}</span>
      <span class="handle" data-col="key" title="${escapeHtml(t.resetWidthTitle)}"></span>
    </th>
    <th data-col="count">
      <span class="sortlbl" data-sort="count">${escapeHtml(t.colCount)}</span>
      <span class="handle" data-col="count" title="${escapeHtml(t.resetWidthTitle)}"></span>
    </th>
    <th data-col="place">
      <span class="sortlbl" data-sort="place">${escapeHtml(t.colPlace)}</span>
      <span class="handle" data-col="place" title="${escapeHtml(t.resetWidthTitle)}"></span>
    </th>
    <th data-col="file">
      <span class="sortlbl" data-sort="file">${escapeHtml(t.colFile)}</span>
      <span class="handle" data-col="file" title="${escapeHtml(t.resetWidthTitle)}"></span>
    </th>
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
const COLS = ["kind", "key", "count", "place", "file"];
const DEFAULT_WIDTHS = ${inlineJson(DEFAULT_COLUMN_WIDTHS)};
const MIN_WIDTHS = ${inlineJson(MIN_COLUMN_WIDTHS)};
const $ = (id) => document.getElementById(id);
// The extension's state comes inlined (a panel opened from a finding is already filtered by its
// key); what the webview itself remembers wins over it, which is exactly the restore after a
// window restart - a fresh panel has nothing remembered. colWidths rides along inside this same
// object, not a state of its own - it already gets everything state gets for free: the restore
// above, and the round trip to the extension every pushState below already makes.
let state = Object.assign(${inlineJson(this.state)}, vsapi.getState() || {});
let busy = true;
let last = { rows: [], stats: { total: 0, gaps: 0, shown: 0 }, loaded: 0, dictionary: "", totals: null };

function pushState(patch) {
  state = Object.assign({}, state, patch);
  vsapi.setState(state);
  vsapi.postMessage({ type: "state", state: state });
}

// A column's width, read defensively: state.colWidths normally already came from a sanitized
// state (the extension runs every incoming colWidths through the same clamp this reads with),
// but the very first paint of a freshly restored panel draws from vsapi.getState() alone, before
// that round trip has happened even once - a number outside [min, +inf) or missing entirely
// falls back the same way sanitizeColumnWidths does on the extension side, so that first paint
// can never be narrower than the floor or wider than nothing at all.
function widthOf(col) {
  const v = state.colWidths && state.colWidths[col];
  return typeof v === "number" && isFinite(v) && v > 0 ? Math.max(MIN_WIDTHS[col], v) : DEFAULT_WIDTHS[col];
}

// table-layout: fixed only treats a <col>'s width as literal, load-bearing pixels when the
// TABLE itself also has an explicit width to anchor to - left at the default "auto", measurement
// during this round showed every column still being resized by its own content regardless of
// what the colgroup said (a 320px key column rendering at 128px), the exact defect a table with
// no set width reproduces even though every rule that caused the earlier auto-layout version of
// it is gone. Setting the table's own width to the sum of the five columns, recomputed here
// alongside them, is what makes a dragged width the actual last word on a column's size.
function applyColgroup() {
  let total = 0;
  for (const col of COLS) {
    const w = widthOf(col);
    document.querySelector('col[data-col="' + col + '"]').style.width = w + "px";
    total += w;
  }
  document.querySelector("table").style.width = total + "px";
}

function syncControls() {
  if ($("q").value !== (state.search || "")) { $("q").value = state.search || ""; }
  $("gaps").checked = Boolean(state.gapsOnly);
  $("kind").value = state.kind || "any";
  // Five columns, five independent sort handles now (only "key"/"value" still share one column) -
  // "[data-sort]" catches every one of them, header or word alike.
  for (const el of document.querySelectorAll("[data-sort]")) {
    const mark = el.querySelector(".dir");
    if (mark) { mark.remove(); }
    el.classList.remove("active");
    if (el.dataset.sort === state.sortBy) {
      el.classList.add("active");
      const dir = document.createElement("span");
      dir.className = "dir";
      dir.textContent = state.sortDir === "desc" ? " \\u2193" : " \\u2191";
      el.appendChild(dir);
    }
  }
  applyColgroup();
}

// A display trim, never a data change: the directory of a source path or a dictionary file is
// almost always one of a handful of project folders, so it carries little of its own next to the
// file name - and unlike a column's pixel width, there is no slider for how much of a path is
// "enough", so this drops it outright rather than guessing a cutoff. The full path a caller still
// needs (the click target, the tooltip) always reads the original string, never this trimmed one.
function baseName(p) {
  // Four backslashes here, not two: this text lives inside the OUTER TypeScript template
  // literal (html()'s own return value), which collapses \\\\ to \\ the same way any string
  // literal collapses an escape - the inner webview script that actually runs this regex needs
  // to see \\\\/]/ as \\/]/, matching a backslash OR a forward slash. Two backslashes here
  // reaches the browser as one, a regex that only ever matches "/" - it silently returned every
  // Windows-style path unchanged, found only by measuring the real generated output on a real
  // Windows path rather than a hand-typed one.
  const parts = String(p).split(/[\\\\/]/);
  return parts[parts.length - 1] || String(p);
}

function linkCell(td, text, title, onClick) {
  const a = document.createElement("a");
  a.textContent = text;
  a.title = title;
  // Kept out of Tab order on purpose: this is a secondary jump-to-source action, and a person
  // walking the table by keyboard is after the translation inputs, one per row - a stray link
  // between two of them would cost an extra Tab for no reason.
  a.tabIndex = -1;
  a.addEventListener("click", onClick);
  td.appendChild(a);
}

// The translation input, full width under the key. An empty cell may carry a hint - the
// platform's own spelling or the machine service's guess, already resolved to one by rowHint on
// the extension side (row.hint / row.hintFromMachine) - shown as the input's native placeholder
// (the editor's own placeholder color, and gone by itself the moment anything is typed) plus a
// checkmark on the right that accepts it. The checkmark works by mouse; Enter does the same
// while the field is still empty, so a row is reachable end to end without the mouse.
function valueCell(td, row) {
  const box = document.createElement("div");
  box.className = "cell";
  const input = document.createElement("input");
  input.type = "text";
  input.value = row.value;
  input.spellcheck = false;
  const hint = row.hint || "";
  let icon;
  const accept = () => {
    if (!hint) { return; }
    input.value = hint;
    // The row now holds what was written, so the blur that follows does not send the very same
    // word a second time.
    row.value = hint;
    vsapi.postMessage({ type: "set", kind: row.kind, key: row.key, value: hint });
    if (icon) { icon.style.display = "none"; }
  };
  const submit = () => {
    if (input.value === row.value) { return; }
    vsapi.postMessage({ type: "set", kind: row.kind, key: row.key, value: input.value });
  };
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      if (hint && !input.value) { accept(); }
      input.blur();
      return;
    }
    if (e.key === "Escape") { input.value = row.value; input.blur(); }
  });
  input.addEventListener("blur", submit);
  input.addEventListener("input", () => {
    // The placeholder hides itself; the checkmark is a real element and has to be told.
    if (icon) { icon.style.display = input.value ? "none" : ""; }
  });
  if (hint) {
    input.placeholder = hint;
    input.classList.add("hashint");
  }
  box.appendChild(input);
  if (hint) {
    icon = document.createElement("span");
    icon.className = "accept";
    icon.textContent = "\\u2713";
    icon.title = row.hintFromMachine ? TEXT.machineHintTitle : TEXT.hintTitle;
    icon.addEventListener("click", accept);
    box.appendChild(icon);
  }
  td.appendChild(box);
}

function render() {
  const data = last;
  const body = $("rows");
  body.textContent = "";
  for (const row of data.rows) {
    // A record is two table rows, not one: the top line (kind, key, occurrences, place, file)
    // and, right under the key, the translation input at the full width of the row - the columns
    // stay five, the record just reads over two lines instead of squeezing everything into one.
    const top = body.insertRow();
    top.className = "top";
    const kind = top.insertCell();
    kind.className = "kind";
    // Wrapped in a div rather than set as the cell's bare text - a bare text node and a
    // block-level div align differently under vertical-align: top even at an identical
    // line-height, and that mismatch (not the row's own height) was what let the kind label
    // drift a few pixels below the key beside it. The key cell already wraps its text the
    // same way; this just matches it.
    const kindText = document.createElement("div");
    kindText.textContent = row.kind === "phrase" ? TEXT.phrase : row.kind === "literal" ? TEXT.literal : TEXT.token;
    kind.appendChild(kindText);

    const key = top.insertCell();
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

    const count = top.insertCell();
    count.className = "count";
    if (row.count) {
      const countText = document.createElement("div");
      countText.textContent = String(row.count);
      count.appendChild(countText);
    }

    const place = top.insertCell();
    place.className = "place";
    if (row.place) {
      // The directory is dropped on screen - almost always the same handful of project folders,
      // so it carries little of its own next to the file name - but never from the click target
      // or the tooltip: baseName is a display trim, not a data change, and row.place.file (the
      // full path) is still exactly what travels in the "place" message below.
      const shown = baseName(row.place.file) + ":" + row.place.line;
      linkCell(place, shown, row.place.file + ":" + row.place.line, () =>
        vsapi.postMessage({ type: "place", file: row.place.file, line: row.place.line }));
    }

    const file = top.insertCell();
    file.className = "file";
    if (row.file) {
      const fileText = document.createElement("div");
      fileText.textContent = baseName(row.file);
      fileText.title = row.file;
      file.appendChild(fileText);
    }

    const bottom = body.insertRow();
    bottom.className = "bottom";
    const valueTd = bottom.insertCell();
    valueTd.colSpan = 5;
    valueCell(valueTd, row);
  }
  if (!data.rows.length) {
    const tr = body.insertRow();
    const cell = tr.insertCell();
    cell.colSpan = 5;
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
  // The machine-translation service's last report, next to coverage/literals rather than only
  // in the status-bar message that also carries it - that one is gone in five seconds. Three
  // service counters at zero do not by themselves mean the run found nothing: a string literal
  // is filled by local substitution and never touches cached/requested/refused, so a literal
  // suggestion can be sitting in the table while all three read zero. m.suggested (the answer's
  // own row count) is the one number that tells the two states apart - it is checked first.
  if (data.machine) {
    const m = data.machine;
    const nothingAsked = m.cached === 0 && m.requested === 0 && m.refused === 0;
    totals += " \\u00b7 " + (nothingAsked && m.suggested > 0
      ? TEXT.machineLocalOnly.replace("{0}", m.suggested)
      : nothingAsked
        ? TEXT.machineNothing
        : TEXT.machineStats.replace("{0}", m.cached).replace("{1}", m.requested).replace("{2}", m.refused));
  }
  $("stats").textContent = busy ? TEXT.busy : stats + totals;
  // The refusal reasons stay reachable after the warning notification that first announced them
  // is dismissed - a hover on the line that already carries the count, not a second UI surface.
  $("stats").title = (data.machine && data.machine.refusalText) ? TEXT.machineRefusalsTitle + " " + data.machine.refusalText : "";
  $("dict").textContent = data.dictionary || "";
  $("more").style.display = data.stats.shown < data.stats.total ? "" : "none";
  // The busy flag already covers a plain re-read too (cheap, local - clicking it twice costs
  // nothing), but "suggest" reaches a paid external service: while one run is still going the
  // button must not be clickable at all, so a second click never even reaches the extension.
  $("suggest").disabled = busy;
}

$("q").addEventListener("input", () => pushState({ search: $("q").value, shown: PAGE }));
$("gaps").addEventListener("change", () => pushState({ gapsOnly: $("gaps").checked, shown: PAGE }));
$("kind").addEventListener("change", () => pushState({ kind: $("kind").value, shown: PAGE }));
$("reload").addEventListener("click", () => vsapi.postMessage({ type: "reload" }));
$("suggest").addEventListener("click", () => vsapi.postMessage({ type: "suggest" }));
$("more").addEventListener("click", () => pushState({ shown: state.shown + PAGE }));
// Column-width dragging. Declared before the sort handles below because their click handler
// reads justDragged - both only ever RUN later, on an actual mouse event, well after this whole
// script has finished its first pass, so the order here is for a reader's sake, not the engine's.
// Live during the drag (state.colWidths and the colgroup are both updated on every mousemove, so
// the column visibly tracks the pointer), but pushState - the call that both persists to
// vsapi.setState and tells the extension - fires only once, on mouseup: a mousemove firing dozens
// of times a second is cheap to redraw locally and expensive to mail to the extension host that
// many times for a number it has no use for mid-drag anyway.
let dragging = null; // { col, startX, startWidth, handle } | null
let justDragged = false;

function beginDrag(handle, clientX) {
  const col = handle.dataset.col;
  dragging = { col: col, startX: clientX, startWidth: widthOf(col), handle: handle };
  handle.classList.add("dragging");
  document.body.style.cursor = "col-resize";
  document.body.style.userSelect = "none";
}

function dragTo(clientX) {
  if (!dragging) { return; }
  const next = Math.max(MIN_WIDTHS[dragging.col], dragging.startWidth + (clientX - dragging.startX));
  state = Object.assign({}, state, {
    colWidths: Object.assign({}, state.colWidths, { [dragging.col]: next }),
  });
  applyColgroup();
}

function endDrag() {
  if (!dragging) { return; }
  dragging.handle.classList.remove("dragging");
  dragging = null;
  document.body.style.cursor = "";
  document.body.style.userSelect = "";
  justDragged = true;
  // Cleared on the next tick, after any synthetic click the mouseup itself produces has already
  // had its chance to run and be swallowed by the sort handler above - a plain click starting
  // fresh after that is a new, unrelated click and must sort normally again.
  setTimeout(() => { justDragged = false; }, 0);
  pushState({ colWidths: state.colWidths });
}

for (const el of document.querySelectorAll(".handle")) {
  el.addEventListener("mousedown", (e) => {
    // preventDefault stops a stray text selection while dragging; stopPropagation is not load-
    // bearing here (the handle is a sibling of .sortlbl, not inside it, so this mousedown could
    // never reach a sort click handler regardless) but costs nothing and documents the intent.
    e.preventDefault();
    e.stopPropagation();
    beginDrag(el, e.clientX);
  });
  el.addEventListener("dblclick", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const col = el.dataset.col;
    pushState({ colWidths: Object.assign({}, state.colWidths, { [col]: DEFAULT_WIDTHS[col] }) });
    applyColgroup();
  });
}
document.addEventListener("mousemove", (e) => dragTo(e.clientX));
document.addEventListener("mouseup", endDrag);

// The five sort handles: two words share the key/translation header, one apiece owns the other
// three - every one of them carries its own "[data-sort]", header word or plain header alike.
// justDragged is checked first: a border drag ends with a mouseup over the header cell, exactly
// where a sort word can also sit, and a browser is free to follow that mouseup with a synthetic
// click on whatever element is under the pointer. The drag handle being a sibling of these words,
// never their parent, already keeps a drag's OWN mousedown from ever starting a click on one -
// this flag is the second, separate guard, for the click event a completed drag can still leave
// behind.
for (const el of document.querySelectorAll("[data-sort]")) {
  el.addEventListener("click", () => {
    if (justDragged) { return; }
    const by = el.dataset.sort;
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
    this.disposed = true;
    // Only when the pointer still names THIS panel: `adopt` disposes the previous one before
    // putting the new one in place, and the old panel's own dispose event arrives after that -
    // clearing the pointer then would orphan the panel the reader is looking at.
    if (TranslationPanel.current === this) {
      TranslationPanel.current = undefined;
    }
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

// --- the machine-translation key -------------------------------------------------------------

interface KeyChoice extends vscode.QuickPickItem {
  secret: string;
}

// What the command offers to set: the two keys and the one id Yandex Translate needs besides its
// key. No default and no example value is offered anywhere here - the owner types the real one.
function keyChoices(): KeyChoice[] {
  return [
    { label: vscode.l10n.t("Yandex Translate: API key"), secret: SECRET_YANDEX_KEY },
    { label: vscode.l10n.t("Yandex Translate: folder ID"), secret: SECRET_YANDEX_FOLDER },
    { label: vscode.l10n.t("Google Translate: API key"), secret: SECRET_GOOGLE_KEY },
  ];
}

// Puts one machine-translation credential into SecretStorage - never into a setting, never onto
// the engine's command line. The owner types it here, with the input hidden; the code that spawns
// the engine only ever reads it back (`secretsEnv`). An empty answer clears the credential rather
// than storing an empty string, so "forgot the key" and "cleared the key" read the same way.
async function setMachineKey(context: vscode.ExtensionContext): Promise<void> {
  const picked = await vscode.window.showQuickPick(keyChoices(), {
    title: vscode.l10n.t("Which key to set?"),
    ignoreFocusOut: true,
  });
  if (!picked) {
    return;
  }
  const value = await vscode.window.showInputBox({
    title: picked.label,
    password: true,
    ignoreFocusOut: true,
    prompt: vscode.l10n.t("Stored in SecretStorage; never written to a setting or a command line."),
  });
  if (value === undefined) {
    return; // cancelled - whatever was stored before is left untouched
  }
  const trimmed = value.trim();
  if (trimmed === "") {
    await context.secrets.delete(picked.secret);
    void vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL: the key is cleared."), 5000);
    return;
  }
  await context.secrets.store(picked.secret, trimmed);
  void vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL: the key is saved."), 5000);
}

export function registerTranslation(context: vscode.ExtensionContext, rootFor: ProjectRootFor): void {
  projectRootFor = rootFor;
  context.subscriptions.push(
    vscode.commands.registerCommand(PANEL_COMMAND, (filter?: Partial<ViewState>, resource?: vscode.Uri) =>
      TranslationPanel.show(context, filter, resource)
    ),
    vscode.commands.registerCommand(SET_COMMAND, (uri: vscode.Uri, target: TranslationTarget, value?: string) =>
      setTranslation(uri, target, value)
    ),
    vscode.commands.registerCommand(KEY_COMMAND, () => setMachineKey(context)),
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
        await TranslationPanel.adopt(context, restored, folder);
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
