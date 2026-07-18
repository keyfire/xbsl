import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig, RawDiag, RawReport } from "./report";
import { registerDeploy } from "./deploy";
import { registerFormData } from "./formData";
import { registerFormPalette } from "./formPalette";
import { registerFormPreview } from "./formPreview";
import { registerFormStructure } from "./formStructure";
import { baselineForLint, registerExcludeAction } from "./excludeAction";
import { lintBuffer, lintPath, makeDiagnostic, RunHandle, toDiagnostic } from "./linter";
import { activateLsp, lspActive, lspBaselinePassed, lspRequest } from "./lspClient";
import { registerNavigation } from "./navigation";
import { registerMetadataTree } from "./metadataTree";
import { registerFormProps } from "./formProps";
import { registerDocs } from "./docsTree";
import { registerStatusBar } from "./statusBar";
import { registerTemplates, setTemplatesReload } from "./templatesPanel";
import { registerPalettePicker } from "./palettes";
import { pipInstallCommand, runInstallTask } from "./installer";
import { mergeOffRules, registerRuleConfig, ruleOverride } from "./ruleConfig";
import { groupReportByFile } from "./workspaceCore";
import { FixSnapshot, PROVIDED_KINDS, XbslCodeActionProvider } from "./codeActions";

let collection: vscode.DiagnosticCollection;
let output: vscode.OutputChannel;
const debounceTimers = new Map<string, NodeJS.Timeout>();
let warnedOnce = false;

// The latest fixable findings per document, stamped with a version (uri -> snapshot) - for Quick
// Fix. A stale entry (version mismatch) is ignored by the provider, so a fix offset is never
// applied to text that changed after the run which produced it.
const fixStore = new Map<string, FixSnapshot>();

function setFixSnapshot(uri: vscode.Uri, version: number, diags: RawDiag[]): void {
  const fixable = diags.filter((d) => d.fix);
  if (fixable.length > 0) {
    fixStore.set(uri.toString(), { version, diags: fixable });
  } else {
    fixStore.delete(uri.toString());
  }
}

// --- Workspace run state -----------------------------------------------------------------
// One diagnostic collection, two producers:
//  * the fast `--stdin` run owns the findings of the edited (dirty) buffer;
//  * the whole-workspace run (on save, debounced, one at a time) replaces the findings of all
//    other files - it sees project rules that are out of reach for a single buffer.

// One file's share of the last completed workspace run: the findings converted for the collection,
// and the raw ones they came from - the raw ones restore the Quick Fix snapshot when the file is
// opened after the run.
interface WorkspaceEntry {
  uri: vscode.Uri;
  diags: vscode.Diagnostic[];
  raw: RawDiag[];
}

// The last completed run per workspace folder: file uri -> its entry.
const workspaceResults = new Map<string, Map<string, WorkspaceEntry>>();
// Debounce timers of scheduled workspace runs, per folder.
const workspaceTimers = new Map<string, NodeJS.Timeout>();
// Runs waiting in the chain (not started yet), per folder - they deduplicate frequent saves.
const queuedRuns = new Map<string, Promise<void>>();
// The single currently executing run; a new save of the same folder cancels it.
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
  const command = (c.get<string>("linter.command") || "xbsl").trim();
  const lang = (c.get<string>("linter.lang") || "").trim();
  return {
    linter: {
      command: python || command,
      usePython: python.length > 0,
      dataDir: (c.get<string>("linter.dataDir") || "").trim() || undefined,
      lang: lang || undefined,
      select: (c.get<string>("linter.select") || "").trim() || undefined,
      // Rules and groups switched off in the settings (off) are not run at all.
      ignore: mergeOffRules((c.get<string>("linter.ignore") || "").trim() || undefined, resource),
      // An existing baseline file: excluded findings are suppressed in every run.
      baseline: baselineForLint(resource),
    },
    run: c.get<"onType" | "onSave" | "off">("linter.run") || "onType",
    debounce: c.get<number>("linter.debounce") ?? 300,
    workspaceLint: c.get<boolean>("workspaceLint") ?? true,
    workspaceTimeout: c.get<number>("workspaceLintTimeout") ?? 60000,
  };
}

// Source root for project-wide runs and for the navigation index: the xbsl.projectRoot setting
// (a path relative to the workspace folder, or absolute). Lets us avoid linting unrelated
// repository directories (examples, copies) that make project rules (Ид uniqueness and the like)
// produce false positives. Empty or non-existent - the workspace folder itself.
function projectRootFor(folder: vscode.WorkspaceFolder): string {
  const raw = (vscode.workspace.getConfiguration("xbsl", folder.uri).get<string>("projectRoot") || "").trim();
  if (!raw) {
    return folder.uri.fsPath;
  }
  const abs = path.isAbsolute(raw) ? raw : path.join(folder.uri.fsPath, raw);
  if (!fs.existsSync(abs)) {
    output.appendLine(vscode.l10n.t('XBSL: xbsl.projectRoot "{0}" not found – using the workspace folder.', raw));
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
  // A path relative to the workspace folder (the run's cwd), not a bare name: it is what matches
  // findings against baseline entries, and structure/xbsl-pair sees the real neighbor.
  const folder = vscode.workspace.getWorkspaceFolder(doc.uri);
  const filename =
    doc.uri.scheme !== "file"
      ? "buffer.xbsl"
      : folder
        ? path.relative(folder.uri.fsPath, doc.uri.fsPath)
        : path.basename(doc.uri.fsPath);
  const version = doc.version;
  const result = await lintBuffer(doc.getText(), filename, cwdFor(doc.uri), settings.linter);
  if (result.error) {
    reportProblem(result.error, result.notFound);
    return;
  }
  // Discard a stale result: the buffer changed while the linter was running.
  if (doc.version !== version) {
    return;
  }
  const raw = (result.report?.diagnostics ?? []).filter((d) => ruleOverride(d.rule, doc.uri) !== "off");
  collection.set(doc.uri, raw.map((d) => toDiagnostic(d, doc)));
  setFixSnapshot(doc.uri, version, raw);
}

function reportProblem(message: string, notFound = false): void {
  output.appendLine(message);
  if (warnedOnce) {
    return;
  }
  warnedOnce = true;
  const install = notFound ? vscode.l10n.t("Install xbsl") : undefined;
  const showLog = vscode.l10n.t("Show log");
  const buttons = install ? [install, showLog] : [showLog];
  void vscode.window.showErrorMessage(`XBSL: ${message}`, ...buttons).then((pick) => {
    if (install && pick === install) {
      runInstallTask("xbsl", pipInstallCommand("xbsl"), "xbsl.restartLinter");
    } else if (pick) {
      output.show(true);
    }
  });
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

// --- Workspace run -----------------------------------------------------------------------

// The last completed run's result for a file: an entry (possibly with no findings) if the file's
// folder has already been checked, and undefined if no run has completed yet.
function workspaceBaseline(uri: vscode.Uri): Pick<WorkspaceEntry, "diags" | "raw"> | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) {
    return undefined;
  }
  const store = workspaceResults.get(folder.uri.toString());
  if (!store) {
    return undefined;
  }
  return store.get(uri.toString()) ?? { diags: [], raw: [] };
}

// Debounced entry point: repeated saves within the window collapse into a single run.
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

// One run at a time: runs line up into a chain, a folder is queued at most once, and a save
// while its folder is being checked cancels the now-outdated run.
function enqueueWorkspaceRun(folder: vscode.WorkspaceFolder, notify = false): Promise<void> {
  const key = folder.uri.toString();
  const queued = queuedRuns.get(key);
  if (queued) {
    return queued; // not started yet - it will pick up the fresh files from disk anyway
  }
  if (activeRun && activeRun.folderKey === key) {
    activeRun.handle.cancel(); // its result would describe files that no longer exist in that shape
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
    output.appendLine(vscode.l10n.t('XBSL: the workspace run "{0}" was canceled – the files changed.', folder.name));
    return;
  }
  if (result.error) {
    // A soft failure: a huge workspace or a broken linter must not spray popup windows
    // on every save.
    if (notify) {
      reportProblem(result.error, result.notFound);
    } else {
      output.appendLine(vscode.l10n.t('XBSL: the workspace run "{0}" failed: {1}', folder.name, result.error));
    }
    return;
  }
  if (result.report) {
    applyWorkspaceReport(folder, result.report);
    const s = result.report.summary;
    const stats = s ? vscode.l10n.t("{0} findings in {1} files", s.diagnostics, s.files) : vscode.l10n.t("done");
    output.appendLine(vscode.l10n.t('XBSL: workspace run "{0}": {1}, {2} ms.', folder.name, stats, Date.now() - started));
  }
}

// Distributes the run's findings across the folder's files, replacing whatever was there before.
// The exception is dirty buffers: their findings belong to the live `--stdin` run until the buffer
// is saved (a run over the files on disk simply does not see them).
function applyWorkspaceReport(folder: vscode.WorkspaceFolder, report: RawReport): void {
  const folderKey = folder.uri.toString();
  const openDocs = new Map<string, vscode.TextDocument>();
  for (const doc of vscode.workspace.textDocuments) {
    openDocs.set(doc.uri.toString(), doc);
  }
  const grouped = groupReportByFile(
    report.diagnostics ?? [],
    folder.uri.fsPath,
    (rule) => ruleOverride(rule, folder.uri) === "off"
  );
  const fresh = new Map<string, WorkspaceEntry>();
  for (const [fsPath, raws] of grouped) {
    const uri = vscode.Uri.file(fsPath);
    const key = uri.toString();
    const doc = openDocs.get(key);
    const clean = doc && !doc.isDirty ? doc : undefined;
    const entry = fresh.get(key) ?? { uri, diags: [], raw: [] };
    for (const d of raws) {
      entry.diags.push(clean ? toDiagnostic(d, clean) : makeDiagnostic(d, undefined));
      entry.raw.push(d);
    }
    fresh.set(key, entry);
  }
  workspaceResults.set(folderKey, fresh);
  for (const [key, entry] of fresh) {
    const doc = openDocs.get(key);
    if (doc && doc.isDirty) {
      continue;
    }
    collection.set(entry.uri, entry.diags);
    // Offsets of the disk run only fit a clean open buffer; stamp it with the buffer's version.
    if (doc) {
      setFixSnapshot(entry.uri, doc.version, entry.raw);
    }
  }
  // Files with no findings left: everything in this folder that the fresh run did not mention
  // is now clean.
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

// Manual command: check all workspace folders, with a progress indicator and a visible error.
async function lintProject(): Promise<void> {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: no open folder to check."));
    return;
  }
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Window, title: vscode.l10n.t("XBSL: checking the project...") },
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

// Forget everything and start over: used by the restart command and on settings changes.
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

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  collection = vscode.languages.createDiagnosticCollection("xbsl");
  output = vscode.window.createOutputChannel("XBSL");
  context.subscriptions.push(collection, output);

  // Shared by both modes: the palette, rule configuration from a finding, deploy to a stand,
  // form preview.
  registerPalettePicker(context);
  registerRuleConfig(context);
  // Excluding a finding into the baseline (the light bulb). After writing: in the CLI mode
  // everything is re-read from scratch; in the LSP mode the server re-reads the baseline on
  // every run - xbsl/relint is enough, and if the file did not exist at server start, the
  // server is restarted with the new --baseline argument.
  registerExcludeAction(context, async (uri) => {
    if (lspActive()) {
      if (lspBaselinePassed()) {
        await lspRequest("xbsl/relint", { uri: uri.toString() });
      } else {
        await vscode.commands.executeCommand("xbsl.restartLinter");
      }
      return;
    }
    resetAndRelint();
  });
  registerDeploy(context, projectRootFor);
  registerFormPreview(context);
  const metadataTree = registerMetadataTree(context, projectRootFor);
  // The unified "Properties" panel (docs/DESIGNER.md, stage 3): follows the active editor -
  // form yamls fill it with the component under the cursor (through the LSP server; the CLI
  // mode shows a hint), other element yamls and modules with the metadata object (local
  // targeted edits, no server needed). The metadata tree feeds it its Тип candidates and
  // targets it via xbsl.metadata.props.
  registerFormProps(context, metadataTree.typeCandidates);
  // Element documentation: the help tree, search and showing the page for the symbol under the
  // cursor. Data comes from the linter's LSP server; in the CLI mode (no server) the commands say so.
  registerDocs(context);
  // Visual form designer panels: the structure tree of the active form yaml and the component
  // palette. Both are thin clients of the engine (xbsl/formTree, xbsl/formEdit, xbsl/uiSchema);
  // the providers load data lazily, only when their views are visible.
  const formStructure = registerFormStructure(context);
  registerFormPalette(context, {
    projectComponents: metadataTree.interfaceComponents,
    structure: formStructure,
  });
  // The "Data" panel of the form designer (docs/DESIGNER.md, hook 2): the component's own
  // Свойства records plus the attributes of the form's owner object; records drag into the
  // structure view as ready input components.
  registerFormData(context, {
    structure: formStructure,
    formOwner: metadataTree.formOwnerByPath,
  });
  // Code templates: the management panel works in both modes (data and writes go through the
  // engine), while template suggestions on Ctrl+Space come from the LSP server.
  registerTemplates(context);
  // Extension/linter versions and the completion mode in the status bar (before the LSP branch -
  // visible in both modes).
  const statusBar = registerStatusBar(context, (resource) => readSettings(resource).linter);

  // LSP mode (the default): everything is done by the long-lived xbsl-lsp server - it also
  // provides hover and type-based completion. On a failed start we continue in the plain (CLI)
  // mode; the failure is reported only when the mode was chosen explicitly, otherwise those who
  // installed the linter without the [lsp] extra would get an error popup out of nowhere.
  const lspSetting = vscode.workspace.getConfiguration("xbsl").inspect<boolean>("lsp.enabled");
  const lspChosen =
    lspSetting?.workspaceFolderValue ?? lspSetting?.workspaceValue ?? lspSetting?.globalValue;
  if (lspChosen ?? lspSetting?.defaultValue ?? true) {
    if (await activateLsp(context, output, lspChosen !== undefined)) {
      statusBar.setLspMode(true);
      // The server picks up template edits on request - no restart, no index loss.
      setTemplatesReload(async () => {
        await lspRequest("xbsl/templatesReload", {});
      });
      return;
    }
  }

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => {
      if (doc.languageId !== "xbsl") {
        return;
      }
      const settings = readSettings(doc.uri);
      if (settings.run === "off") {
        return;
      }
      // A clean buffer whose file is already covered by a workspace run needs no `--stdin` pass:
      // it would only see the per-file rules and would wipe the project ones. Instead, the Quick
      // Fix snapshot is restored from the stored run - a run stamps only the documents open at
      // that moment, and closing a document deletes the snapshot. The buffer is clean, so the
      // run's disk offsets are valid for it.
      if (settings.workspaceLint && !doc.isDirty) {
        const baseline = workspaceBaseline(doc.uri);
        if (baseline !== undefined) {
          setFixSnapshot(doc.uri, doc.version, baseline.raw);
          return;
        }
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
        // The file on disk is now up to date - the whole-workspace run will replace the buffer's
        // findings with the full set (per-file and project rules together).
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
      // The file is still part of the project: bring back the findings of the last workspace run
      // (the closed buffer may have been dirty, its `--stdin` results die with it).
      const baseline = workspaceBaseline(doc.uri);
      if (baseline !== undefined && readSettings(doc.uri).workspaceLint) {
        collection.set(doc.uri, baseline.diags);
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
