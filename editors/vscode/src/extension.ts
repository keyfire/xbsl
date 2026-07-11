import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig, RawDiag, RawReport } from "./report";
import { lintBuffer, lintPath, makeDiagnostic, RunHandle, toDiagnostic } from "./linter";
import { registerNavigation } from "./navigation";
import { registerPalettePicker } from "./palettes";
import { FixSnapshot, PROVIDED_KINDS, XbslCodeActionProvider } from "./codeActions";

let collection: vscode.DiagnosticCollection;
let output: vscode.OutputChannel;
const debounceTimers = new Map<string, NodeJS.Timeout>();
let warnedOnce = false;

// The last version-stamped fixable diagnostics per document (uri -> snapshot), for Quick Fix.
// A stale entry (version mismatch) is ignored by the provider, so a fix offset is never
// applied to text that has changed since the lint that produced it.
const fixStore = new Map<string, FixSnapshot>();

function setFixSnapshot(uri: vscode.Uri, version: number, diags: RawDiag[]): void {
  const fixable = diags.filter((d) => d.fix);
  if (fixable.length > 0) {
    fixStore.set(uri.toString(), { version, diags: fixable });
  } else {
    fixStore.delete(uri.toString());
  }
}

// --- Workspace lint state ---------------------------------------------------------------
// One diagnostic collection, two producers:
//  * the fast `--stdin` lint owns the diagnostics of the buffer being edited (dirty);
//  * the whole-workspace run (on save, debounced, one at a time) replaces the diagnostics
//    of every other file – it sees project-scope rules a single buffer cannot.

// The last completed workspace run per workspace folder: file uri -> its diagnostics.
const workspaceResults = new Map<string, Map<string, { uri: vscode.Uri; diags: vscode.Diagnostic[] }>>();
// Debounce timers of scheduled workspace runs, per folder.
const workspaceTimers = new Map<string, NodeJS.Timeout>();
// Runs waiting in the chain (not started yet), per folder – dedupes repeated saves.
const queuedRuns = new Map<string, Promise<void>>();
// The single run in flight; a newer save of the same folder cancels it.
let activeRun: { folderKey: string; handle: RunHandle } | undefined;
// Workspace runs execute strictly one after another.
let runChain: Promise<void> = Promise.resolve();

const WORKSPACE_DEBOUNCE_MS = 500;

interface Settings {
  linter: LinterConfig;
  run: "onType" | "onSave" | "off";
  debounce: number;
  workspaceLint: boolean;
  workspaceTimeout: number;
}

function readSettings(resource?: vscode.Uri): Settings {
  const c = vscode.workspace.getConfiguration("xbsl", resource ?? null);
  const python = (c.get<string>("linter.pythonPath") || "").trim();
  const command = (c.get<string>("linter.command") || "xbsllint").trim();
  const lang = (c.get<string>("linter.lang") || "").trim();
  return {
    linter: {
      command: python || command,
      usePython: python.length > 0,
      dataDir: (c.get<string>("linter.dataDir") || "").trim() || undefined,
      lang: lang || undefined,
      select: (c.get<string>("linter.select") || "").trim() || undefined,
      ignore: (c.get<string>("linter.ignore") || "").trim() || undefined,
    },
    run: c.get<"onType" | "onSave" | "off">("linter.run") || "onType",
    debounce: c.get<number>("linter.debounce") ?? 300,
    workspaceLint: c.get<boolean>("workspaceLint") ?? true,
    workspaceTimeout: c.get<number>("workspaceLintTimeout") ?? 60000,
  };
}

// Корень исходников для прогонов по проекту и для индекса навигации: настройка
// xbsl.projectRoot (путь относительно папки воркспейса или абсолютный). Позволяет не
// линтить посторонние каталоги репозитория (примеры, копии), из-за которых проектные
// правила (уникальность Ид и т.п.) дают ложные срабатывания. Пусто или не существует –
// сама папка воркспейса.
function projectRootFor(folder: vscode.WorkspaceFolder): string {
  const raw = (vscode.workspace.getConfiguration("xbsl", folder.uri).get<string>("projectRoot") || "").trim();
  if (!raw) {
    return folder.uri.fsPath;
  }
  const abs = path.isAbsolute(raw) ? raw : path.join(folder.uri.fsPath, raw);
  if (!fs.existsSync(abs)) {
    output.appendLine(`XBSL: xbsl.projectRoot "${raw}" не найден – используется папка воркспейса.`);
    return folder.uri.fsPath;
  }
  return abs;
}

function cwdFor(uri: vscode.Uri): string | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder) {
    return folder.uri.fsPath;
  }
  return uri.scheme === "file" ? path.dirname(uri.fsPath) : undefined;
}

// Files the linter understands: .xbsl modules and .yaml element descriptions.
function isLintableUri(uri: vscode.Uri): boolean {
  if (uri.scheme !== "file") {
    return false;
  }
  const p = uri.fsPath.toLowerCase();
  return p.endsWith(".xbsl") || p.endsWith(".yaml");
}

async function lintDocument(doc: vscode.TextDocument): Promise<void> {
  if (doc.languageId !== "xbsl") {
    return;
  }
  const settings = readSettings(doc.uri);
  const filename = doc.uri.scheme === "file" ? path.basename(doc.uri.fsPath) : "buffer.xbsl";
  const version = doc.version;
  const result = await lintBuffer(doc.getText(), filename, cwdFor(doc.uri), settings.linter);
  if (result.error) {
    reportProblem(result.error);
    return;
  }
  // Drop a stale result: the buffer changed while the linter was running.
  if (doc.version !== version) {
    return;
  }
  const raw = result.report?.diagnostics ?? [];
  collection.set(doc.uri, raw.map((d) => toDiagnostic(d, doc)));
  setFixSnapshot(doc.uri, version, raw);
}

function reportProblem(message: string): void {
  output.appendLine(message);
  if (!warnedOnce) {
    warnedOnce = true;
    void vscode.window.showErrorMessage(`XBSL: ${message}`, "Показать журнал").then((pick) => {
      if (pick) {
        output.show(true);
      }
    });
  }
}

function scheduleLint(doc: vscode.TextDocument, delay: number): void {
  const key = doc.uri.toString();
  const prev = debounceTimers.get(key);
  if (prev) {
    clearTimeout(prev);
  }
  debounceTimers.set(
    key,
    setTimeout(() => {
      debounceTimers.delete(key);
      void lintDocument(doc);
    }, delay)
  );
}

// --- Workspace lint ----------------------------------------------------------------------

// The last completed workspace run's diagnostics for a file: an array (possibly empty) when
// the file's folder has been linted, undefined when no run has finished yet.
function workspaceBaseline(uri: vscode.Uri): vscode.Diagnostic[] | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) {
    return undefined;
  }
  const store = workspaceResults.get(folder.uri.toString());
  if (!store) {
    return undefined;
  }
  return store.get(uri.toString())?.diags ?? [];
}

// Debounced entry point: repeated saves within the window collapse into one run.
function scheduleWorkspaceLint(folder: vscode.WorkspaceFolder): void {
  const key = folder.uri.toString();
  const prev = workspaceTimers.get(key);
  if (prev) {
    clearTimeout(prev);
  }
  workspaceTimers.set(
    key,
    setTimeout(() => {
      workspaceTimers.delete(key);
      void enqueueWorkspaceRun(folder);
    }, WORKSPACE_DEBOUNCE_MS)
  );
}

// One run at a time: runs chain up, a folder waits in the queue at most once, and a save
// that arrives while its folder is being linted cancels the now-stale run.
function enqueueWorkspaceRun(folder: vscode.WorkspaceFolder, notify = false): Promise<void> {
  const key = folder.uri.toString();
  const queued = queuedRuns.get(key);
  if (queued) {
    return queued; // not started yet – it will pick up the fresh files from disk
  }
  if (activeRun && activeRun.folderKey === key) {
    activeRun.handle.cancel(); // the result would describe files that no longer exist as such
  }
  const run = runChain.then(() => {
    queuedRuns.delete(key);
    return runWorkspaceLint(folder, notify);
  });
  queuedRuns.set(key, run);
  runChain = run.catch(() => undefined);
  return run;
}

async function runWorkspaceLint(folder: vscode.WorkspaceFolder, notify: boolean): Promise<void> {
  const settings = readSettings(folder.uri);
  const handle = lintPath(projectRootFor(folder), folder.uri.fsPath, settings.linter, settings.workspaceTimeout);
  activeRun = { folderKey: folder.uri.toString(), handle };
  const started = Date.now();
  const result = await handle.result;
  activeRun = undefined;
  if (result.canceled) {
    output.appendLine(`XBSL: прогон workspace "${folder.name}" отменён – файлы изменились.`);
    return;
  }
  if (result.error) {
    // Graceful failure: a huge workspace or a broken linter must not spam popups on every save.
    if (notify) {
      reportProblem(result.error);
    } else {
      output.appendLine(`XBSL: прогон workspace "${folder.name}" не удался: ${result.error}`);
    }
    return;
  }
  if (result.report) {
    applyWorkspaceReport(folder, result.report);
    const s = result.report.summary;
    const stats = s ? `${s.diagnostics} замечаний в ${s.files} файлах` : "готово";
    output.appendLine(`XBSL: прогон workspace "${folder.name}": ${stats}, ${Date.now() - started} мс.`);
  }
}

// Lays the workspace run's diagnostics out over the folder's files, replacing whatever was
// there before. Dirty buffers are the exception: their diagnostics belong to the live
// `--stdin` lint until the buffer is saved (a run over files on disk cannot see them).
function applyWorkspaceReport(folder: vscode.WorkspaceFolder, report: RawReport): void {
  const folderKey = folder.uri.toString();
  const openDocs = new Map<string, vscode.TextDocument>();
  for (const doc of vscode.workspace.textDocuments) {
    openDocs.set(doc.uri.toString(), doc);
  }
  const fresh = new Map<string, { uri: vscode.Uri; diags: vscode.Diagnostic[] }>();
  const rawByKey = new Map<string, RawDiag[]>();
  for (const d of report.diagnostics ?? []) {
    // The linter echoes paths as given (we pass the folder absolute, so they come back
    // absolute with OS separators); relative ones are resolved against the folder.
    const fsPath = path.isAbsolute(d.path) ? d.path : path.join(folder.uri.fsPath, d.path);
    const uri = vscode.Uri.file(fsPath);
    const key = uri.toString();
    const doc = openDocs.get(key);
    const diag = doc && !doc.isDirty ? toDiagnostic(d, doc) : makeDiagnostic(d, undefined);
    const entry = fresh.get(key) ?? { uri, diags: [] };
    entry.diags.push(diag);
    fresh.set(key, entry);
    (rawByKey.get(key) ?? rawByKey.set(key, []).get(key)!).push(d);
  }
  workspaceResults.set(folderKey, fresh);
  for (const [key, entry] of fresh) {
    const doc = openDocs.get(key);
    if (doc && doc.isDirty) {
      continue;
    }
    collection.set(entry.uri, entry.diags);
    // Offsets from a disk run match only a clean open buffer; stamp with that buffer's version.
    if (doc) {
      setFixSnapshot(entry.uri, doc.version, rawByKey.get(key) ?? []);
    }
  }
  // Files whose diagnostics are all gone: everything in this folder that the fresh run
  // did not mention is clean now.
  const stale: vscode.Uri[] = [];
  collection.forEach((uri) => {
    const key = uri.toString();
    if (fresh.has(key)) {
      return;
    }
    if (vscode.workspace.getWorkspaceFolder(uri)?.uri.toString() !== folderKey) {
      return;
    }
    const doc = openDocs.get(key);
    if (doc && doc.isDirty) {
      return;
    }
    stale.push(uri);
  });
  for (const uri of stale) {
    collection.delete(uri);
  }
}

function scheduleWorkspaceLintAll(): void {
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const settings = readSettings(folder.uri);
    if (settings.workspaceLint && settings.run !== "off") {
      scheduleWorkspaceLint(folder);
    }
  }
}

// The manual command: lint every workspace folder, with progress and a visible error.
async function lintProject(): Promise<void> {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    void vscode.window.showInformationMessage("XBSL: нет открытой папки для проверки.");
    return;
  }
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: "XBSL: проверка проекта..." },
    async () => {
      await Promise.all(folders.map((folder) => enqueueWorkspaceRun(folder, true)));
    }
  );
}

function lintOpenDocuments(): void {
  for (const doc of vscode.workspace.textDocuments) {
    if (doc.languageId === "xbsl") {
      void lintDocument(doc);
    }
  }
}

// Forget everything and start over: used by the restart command and on configuration changes.
function resetAndRelint(): void {
  warnedOnce = false;
  activeRun?.handle.cancel();
  for (const t of workspaceTimers.values()) {
    clearTimeout(t);
  }
  workspaceTimers.clear();
  workspaceResults.clear();
  fixStore.clear();
  collection.clear();
  lintOpenDocuments();
  scheduleWorkspaceLintAll();
}

export function activate(context: vscode.ExtensionContext): void {
  collection = vscode.languages.createDiagnosticCollection("xbsl");
  output = vscode.window.createOutputChannel("XBSL");
  context.subscriptions.push(collection, output);

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => {
      if (doc.languageId !== "xbsl") {
        return;
      }
      const settings = readSettings(doc.uri);
      if (settings.run === "off") {
        return;
      }
      // A clean buffer whose file a workspace run has already covered needs no `--stdin`
      // pass: it would see only the per-file rules and wipe the project-scope ones.
      if (settings.workspaceLint && !doc.isDirty && workspaceBaseline(doc.uri) !== undefined) {
        return;
      }
      void lintDocument(doc);
    }),
    vscode.workspace.onDidChangeTextDocument((e) => {
      const doc = e.document;
      if (doc.languageId !== "xbsl") {
        return;
      }
      const settings = readSettings(doc.uri);
      if (settings.run === "onType") {
        scheduleLint(doc, settings.debounce);
      }
    }),
    vscode.workspace.onDidSaveTextDocument((doc) => {
      const settings = readSettings(doc.uri);
      if (settings.run === "off") {
        return;
      }
      const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
      if (settings.workspaceLint && folder && isLintableUri(doc.uri)) {
        // The file on disk is current now – the whole-workspace run replaces the buffer
        // diagnostics with the full set (per-file and project-scope rules together).
        scheduleWorkspaceLint(folder);
        return;
      }
      if (doc.languageId === "xbsl") {
        void lintDocument(doc);
      }
    }),
    vscode.workspace.onDidCloseTextDocument((doc) => {
      const key = doc.uri.toString();
      const t = debounceTimers.get(key);
      if (t) {
        clearTimeout(t);
        debounceTimers.delete(key);
      }
      fixStore.delete(key);
      // The file is still part of the project: put the last workspace run's diagnostics
      // back (the closed buffer may have been dirty, its `--stdin` results die with it).
      const baseline = workspaceBaseline(doc.uri);
      if (baseline !== undefined && readSettings(doc.uri).workspaceLint) {
        collection.set(doc.uri, baseline);
      } else {
        collection.delete(doc.uri);
      }
    }),
    vscode.workspace.onDidChangeWorkspaceFolders((e) => {
      for (const folder of e.removed) {
        const key = folder.uri.toString();
        workspaceResults.delete(key);
        const t = workspaceTimers.get(key);
        if (t) {
          clearTimeout(t);
          workspaceTimers.delete(key);
        }
      }
      for (const folder of e.added) {
        const settings = readSettings(folder.uri);
        if (settings.workspaceLint && settings.run !== "off") {
          scheduleWorkspaceLint(folder);
        }
      }
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("xbsl")) {
        resetAndRelint();
      }
    }),
    vscode.commands.registerCommand("xbsl.lintProject", () => lintProject()),
    vscode.commands.registerCommand("xbsl.restartLinter", () => resetAndRelint()),
    vscode.languages.registerCodeActionsProvider(
      { language: "xbsl" },
      new XbslCodeActionProvider((uri) => fixStore.get(uri.toString())),
      { providedCodeActionKinds: PROVIDED_KINDS }
    )
  );

  registerNavigation(context, output, (resource) => readSettings(resource).linter, projectRootFor);
  registerPalettePicker(context);

  lintOpenDocuments();
  scheduleWorkspaceLintAll();
}

export function deactivate(): void {
  for (const t of debounceTimers.values()) {
    clearTimeout(t);
  }
  debounceTimers.clear();
  for (const t of workspaceTimers.values()) {
    clearTimeout(t);
  }
  workspaceTimers.clear();
  activeRun?.handle.cancel();
  collection?.dispose();
  output?.dispose();
}
