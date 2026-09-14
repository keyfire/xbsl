import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { CiStatus } from "./ciStatusCore";
import { ciSettings, LinterConfig, RawDiag, RawReport } from "./report";
import { registerDeploy } from "./deploy";
import { registerDebug } from "./debug";
import { createFormDataModel, registerFormDataCommands } from "./formData";
import { registerFormPalette } from "./formPalette";
import { DesignerAccess, registerFormDesigner } from "./formDesigner";
import { createFormStructureModel, registerFormStructureCommands } from "./formStructure";
import { baselineForLint, registerExcludeAction } from "./excludeAction";
import { lintBuffer, lintPath, makeDiagnostic, toDiagnostic } from "./linter";
import {
  activateLsp,
  lspActive,
  lspBaselinePassed,
  lspRequest,
  setAfterServerStart,
} from "./lspClient";
import { registerMetadataTree } from "./metadataTree";
import { registerProjectWizard } from "./projectWizard";
import { metaKeyAliases } from "./uiSchemaClient";
import { setMetaKeyAliases } from "./metadataCore";
import { registerFormProps } from "./formProps";
import { registerFormSearch } from "./formSearch";
import { registerDocs } from "./docsTree";
import { registerHoverDocs } from "./hoverDocs";
import { registerDefinitionDocs } from "./definitionDocs";
import { registerStatusBar } from "./statusBar";
import { registerUpdateCheck } from "./updateCheck";
import { registerTemplates, setTemplatesReload } from "./templatesPanel";
import { registerTranslation } from "./translationPanel";
import { registerPalettePicker } from "./palettes";
import { pipInstallCommand, runInstallTask } from "./installer";
import { engineRuleArgs, primeRuleCatalogue, registerRuleConfig, ruleOverride } from "./ruleConfig";
import { registerRulesPanel } from "./rulesPanel";
import {
  dictionaryOutsideRoot,
  discoverDictionary,
  groupReportByFile,
  isDictionaryFile,
  mergeReports,
  PathKind,
  readByRun,
  resolveMessageLanguage,
  RunScope,
} from "./workspaceCore";
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
//  * the fast `--stdin` run owns the findings of the edited (dirty) buffer - a module, or a file
//    of the translation dictionary;
//  * the whole-workspace run (on save, debounced, one at a time) replaces the findings of the
//    files it read - the project root and the dictionary that serves it (see RunScope); it sees
//    project rules that are out of reach for a single buffer. A document it did not read keeps
//    what the check of its buffer found.

// One file's share of the last completed workspace run: the findings converted for the collection,
// and the raw ones they came from - the raw ones restore the Quick Fix snapshot when the file is
// opened after the run.
interface WorkspaceEntry {
  uri: vscode.Uri;
  diags: vscode.Diagnostic[];
  raw: RawDiag[];
}

// The last completed run of a workspace folder: what it read, and the entry of every file it
// reported on (file uri -> entry).
interface WorkspaceRun {
  scope: RunScope;
  entries: Map<string, WorkspaceEntry>;
}

// The last completed run per workspace folder.
const workspaceResults = new Map<string, WorkspaceRun>();
// Debounce timers of scheduled workspace runs, per folder.
const workspaceTimers = new Map<string, NodeJS.Timeout>();
// Runs waiting in the chain (not started yet), per folder - they deduplicate frequent saves.
const queuedRuns = new Map<string, Promise<void>>();
// The single currently executing run (its processes); a new save of the same folder cancels it.
let activeRun: { folderKey: string; cancel: () => void } | undefined;
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
  const lang = resolveMessageLanguage(c.get<string>("linter.lang") || "", vscode.env.language);
  return {
    linter: {
      command: python || command,
      usePython: python.length > 0,
      dataDir: (c.get<string>("linter.dataDir") || "").trim() || undefined,
      lang: lang || undefined,
      // What runs at all comes from the one table (xbsl.rules) plus the legacy strings:
      // "off" keys are not run, keys with a level are switched on even when off by default.
      ...engineRuleArgs(resource),
      // An existing baseline file: excluded findings are suppressed in every run.
      baseline: baselineForLint(resource),
      // The rule set of the project's CI job instead of the defaults, read by the engine
      // from the pipeline file: naming a job is asking for that job's set.
      ...ciSettings(c),
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
// produce false positives. Empty or non-existent - the workspace folder itself. `quiet` is for the
// checks that run on every keystroke: a missing root is reported by the runs, not once per key.
function projectRootFor(folder: vscode.WorkspaceFolder, quiet = false): string {
  const raw = (vscode.workspace.getConfiguration("xbsl", folder.uri).get<string>("projectRoot") || "").trim();
  if (!raw) {
    return folder.uri.fsPath;
  }
  const abs = path.isAbsolute(raw) ? raw : path.join(folder.uri.fsPath, raw);
  if (!fs.existsSync(abs)) {
    if (!quiet) {
      output.appendLine(vscode.l10n.t('XBSL: xbsl.projectRoot "{0}" not found – using the workspace folder.', raw));
    }
    return folder.uri.fsPath;
  }
  return abs;
}

function pathKind(p: string): PathKind {
  try {
    const stat = fs.statSync(p);
    return stat.isDirectory() ? "dir" : stat.isFile() ? "file" : undefined;
  } catch {
    return undefined;
  }
}

// What the next workspace run of the folder reads: its project root, and the translation
// dictionary when that lies outside the root.
function runScopeFor(folder: vscode.WorkspaceFolder, quiet = false): RunScope {
  const root = projectRootFor(folder, quiet);
  return { root, dictionary: dictionaryOutsideRoot(root, discoverDictionary(root, pathKind)) };
}

// The workspace folder whose project a file of the translation dictionary serves, or undefined for
// any other file. The file's own folder is asked first; a dictionary may also sit above every
// folder, next to the project a narrower folder holds.
function dictionaryFolderOf(uri: vscode.Uri): vscode.WorkspaceFolder | undefined {
  if (uri.scheme !== "file" || !uri.fsPath.toLowerCase().endsWith(".yaml")) {
    return undefined;
  }
  const own = vscode.workspace.getWorkspaceFolder(uri);
  const others = (vscode.workspace.workspaceFolders ?? []).filter(
    (folder) => folder.uri.toString() !== own?.uri.toString()
  );
  for (const folder of own ? [own, ...others] : others) {
    const root = projectRootFor(folder, true);
    if (isDictionaryFile(uri.fsPath, discoverDictionary(root, pathKind))) {
      return folder;
    }
  }
  return undefined;
}

// The documents the `--stdin` check takes: modules, and the files of the translation dictionary.
// The dictionary is judged by file rules alone (translation/english-shape among them), which is
// exactly what a buffer check runs - so its findings follow the typing, as they do in LSP mode,
// and the workspace run refreshes them on save.
function isBufferLintable(doc: vscode.TextDocument): boolean {
  return doc.languageId === "xbsl" || dictionaryFolderOf(doc.uri) !== undefined;
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
  if (!isBufferLintable(doc)) {
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

// The last completed run's result for a file: an entry (possibly with no findings) if a completed
// run read the file, and undefined otherwise - no run has completed yet, or no run reads the file
// (a module opened outside the root), whose findings then come from the check of its buffer. The
// run of the file's own folder is asked first; a dictionary above every folder is read by the run
// of the folder it serves.
function workspaceBaseline(uri: vscode.Uri): Pick<WorkspaceEntry, "diags" | "raw"> | undefined {
  if (uri.scheme !== "file") {
    return undefined;
  }
  const own = vscode.workspace.getWorkspaceFolder(uri)?.uri.toString();
  const runs = [...workspaceResults].sort(([a], [b]) => Number(b === own) - Number(a === own));
  for (const [, run] of runs) {
    if (readByRun(uri.fsPath, run.scope)) {
      return run.entries.get(uri.toString()) ?? { diags: [], raw: [] };
    }
  }
  return undefined;
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
    activeRun.cancel(); // its result would describe files that no longer exist in that shape
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
  const scope = runScopeFor(folder);
  const cwd = folder.uri.fsPath;
  const project = lintPath(scope.root, cwd, settings.linter, settings.workspaceTimeout);
  // A dictionary outside the root is checked by a run of its own, side by side with the project:
  // the same run would hand it to the project rules (see RunScope).
  const dictionary = scope.dictionary
    ? lintPath(scope.dictionary, cwd, settings.linter, settings.workspaceTimeout)
    : undefined;
  activeRun = {
    folderKey: folder.uri.toString(),
    cancel: () => {
      project.cancel();
      dictionary?.cancel();
    },
  };
  const started = Date.now();
  const [result, dictionaryResult] = await Promise.all([project.result, dictionary?.result]);
  activeRun = undefined;
  if (result.canceled || dictionaryResult?.canceled) {
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
  if (!result.report) {
    return;
  }
  let report = result.report;
  let read: RunScope = { root: scope.root };
  if (dictionaryResult?.report) {
    report = mergeReports([report, dictionaryResult.report]);
    read = scope;
  } else if (dictionaryResult?.error) {
    // The project half still stands. The dictionary is left out of what the run read, so its
    // files keep the findings they had instead of being cleared by a run that never got to them.
    output.appendLine(
      vscode.l10n.t('XBSL: the workspace run "{0}" failed: {1}', `${folder.name}: ${scope.dictionary}`, dictionaryResult.error)
    );
  }
  applyWorkspaceReport(folder, report, read);
  const s = report.summary;
  const stats = s ? vscode.l10n.t("{0} findings in {1} files", s.diagnostics, s.files) : vscode.l10n.t("done");
  output.appendLine(vscode.l10n.t('XBSL: workspace run "{0}": {1}, {2} ms.', folder.name, stats, Date.now() - started));
}

// Distributes the run's findings across the files it read, replacing whatever was there before.
// The exceptions are dirty buffers - their findings belong to the live `--stdin` run until the
// buffer is saved (a run over the files on disk simply does not see them) - and the documents the
// run did not read, whose findings came from the check of their buffers alone.
function applyWorkspaceReport(folder: vscode.WorkspaceFolder, report: RawReport, scope: RunScope): void {
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
  workspaceResults.set(folderKey, { scope, entries: fresh });
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
  // Files with no findings left: everything the fresh run read and did not mention is now clean.
  // The run's silence says nothing about a document it did not read - a module opened outside the
  // root keeps what the check of its buffer found - nor about a file of another folder's run.
  const stale: vscode.Uri[] = [];
  collection.forEach((uri) => {
    const key = uri.toString();
    if (fresh.has(key)) {
      return;
    }
    if (uri.scheme !== "file" || !readByRun(uri.fsPath, scope)) {
      return;
    }
    const owner = vscode.workspace.getWorkspaceFolder(uri);
    if (owner && owner.uri.toString() !== folderKey) {
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
    if (isBufferLintable(doc)) {
      void lintDocument(doc);
    }
  }
}

// Forget everything and start over: used by the restart command and on settings changes.
function resetAndRelint(): void {
  warnedOnce = false;
  activeRun?.cancel();
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
  registerRulesPanel(context);
  // Tier per rule for the xbsl.rules table - one run of the engine, its result is cached.
  const lint = readSettings().linter;
  primeRuleCatalogue(lint.command, lint.usePython ? ["-m", "xbsl"] : []);
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
  // Debugging shares the deploy settings (the elemctl binary, the application id): the same
  // application is deployed and then debugged, so the two used to ask for the same values twice
  // while they lived in separate extensions.
  registerDebug(context);
  // Getting-started wizard: scaffold a new 1C:Element project through the engine (native prompts,
  // no webview). Available in both modes, so it is registered before the LSP early return.
  registerProjectWizard(context);
  // panelColumnFor is a lazy closure, not `designer.panelColumnFor` directly: the designer
  // registers AFTER the tree and this panel (below), so `designer` does not exist yet at these
  // calls - the closure only reads it once a click actually happens, by which time it is
  // assigned. The tree needs it to keep a source out of the group its form panel occupies.
  let designer: DesignerAccess | undefined;
  const metadataTree = registerMetadataTree(context, projectRootFor, (uri) => designer?.panelColumnFor(uri));
  // The element keys the platform spells two ways (`Attributes` / `Реквизиты`): asked once and
  // handed to the yaml reader, otherwise an English project shows empty branches in the tree.
  // Failure is not fatal - without the pairs the reader keeps working on Russian keys.
  void metaKeyAliases().then((aliases) => {
    if (!Object.keys(aliases).length) {
      return;
    }
    setMetaKeyAliases(aliases);
    // The tree is usually built before the answer arrives - redraw it with the pairs in hand.
    void vscode.commands.executeCommand("xbsl.metadata.refresh");
  });
  // The unified "Properties" panel (docs/DESIGNER.md, stage 3): follows the active editor -
  // form yamls fill it with the component under the cursor (through the LSP server; the CLI
  // mode shows a hint), other element yamls and modules with the metadata object (local
  // targeted edits, no server needed). The metadata tree feeds it its Тип candidates and
  // targets it via xbsl.metadata.props.
  registerFormProps(
    context,
    metadataTree.typeCandidates,
    metadataTree.formOwnerByPath,
    metadataTree.projectEnums,
    (uri) => designer?.panelColumnFor(uri)
  );
  // Element documentation: the help tree, search and showing the page for the symbol under the
  // cursor. Data comes from the linter's LSP server; in the CLI mode (no server) the commands say so.
  registerDocs(context);
  registerHoverDocs(context);
  // F12 over a member of the platform has nowhere to jump (the index holds the project only),
  // so the key falls back to the documentation page instead of answering "no definition".
  registerDefinitionDocs(context);
  // The visual form designer. The structure and data MODELS are thin clients of the engine
  // (xbsl/formTree, xbsl/formEdit, xbsl/objectInfo); the form panel paints both of them next to
  // the wireframe frame and drives their lifecycle, and the palette (in the metadata container)
  // inserts into the panel's structure selection.
  // Each open form panel gets a pair of models of its own (two forms side by side keep their own
  // tree, selection and expansion); the pane commands and the palette act on the panel in front.
  designer = registerFormDesigner(context, () => {
    const structure = createFormStructureModel(context.globalState);
    return {
      structure,
      data: createFormDataModel({ structure, formOwner: metadataTree.formOwnerByPath }),
    };
  });
  registerFormStructureCommands(context, () => designer.activeStructure());
  registerFormDataCommands(context, () => designer.activeData());
  registerFormPalette(context, {
    projectComponents: metadataTree.interfaceComponents,
    structure: () => designer.activeStructure(),
  });
  // Structural search across the project's forms (hook 10): find components by type and property
  // predicates, jump to the match. A thin client of the engine's xbsl/searchForms.
  registerFormSearch(context, { interfaceComponents: metadataTree.interfaceComponents });
  // Code templates: the management panel works in both modes (data and writes go through the
  // engine), while template suggestions on Ctrl+Space come from the LSP server.
  registerTemplates(context);
  // The translation dictionary: the panel and the light bulb of a missing-translation finding.
  // Both work in either mode - reading and writing go through `xbsl translate`, and the key of a
  // finding comes with the diagnostic (the LSP `data` field, the same field of the CLI report).
  registerTranslation(context, projectRootFor);
  // Extension/linter versions and the completion mode in the status bar (before the LSP branch -
  // visible in both modes).
  const statusBar = registerStatusBar(context, (resource) => readSettings(resource).linter);
  // "Is this the latest extension?" - the editor never answers it here: the extension is
  // installed from a vsix and VS Code asks the Marketplace, while the CI publishes to Open VSX.
  // The check is quiet (the status bar lights up), rare (once a day) and switchable.
  registerUpdateCheck(context, (latest) => statusBar.setLatestVersion(latest));

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
      // WHICH rule set the panel judges by - asked of the server, not read off the settings:
      // the settings say what was requested, and only the server knows what came of it. With
      // no pipeline file it goes on judging by the settings' own rules and says so in the
      // output channel alone, which is not where anyone looks while reading a finding.
      // Re-asked after every restart: a changed parity setting is what causes one.
      setAfterServerStart(() => {
        void lspRequest<CiStatus>("xbsl/ciStatus", {}).then((status) =>
          statusBar.setCiStatus(status)
        );
      });
      // The server picks up template edits on request - no restart, no index loss.
      setTemplatesReload(async () => {
        await lspRequest("xbsl/templatesReload", {});
      });
      return;
    }
  }

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((doc) => {
      if (!isBufferLintable(doc)) {
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
      if (!isBufferLintable(doc)) {
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
      // A dictionary above every folder is saved into the run of the folder it serves.
      const folder = vscode.workspace.getWorkspaceFolder(doc.uri) ?? dictionaryFolderOf(doc.uri);
      if (settings.workspaceLint && folder && isLintableUri(doc.uri)) {
        // The file on disk is now up to date - the whole-workspace run will replace the buffer's
        // findings with the full set (per-file and project rules together).
        scheduleWorkspaceLint(folder);
        // ...if the run reads the file at all. A module outside the root is checked on its own,
        // or with "linter.run": "onSave" it would never be checked.
        if (!isBufferLintable(doc) || readByRun(doc.uri.fsPath, runScopeFor(folder, true))) {
          return;
        }
      }
      if (isBufferLintable(doc)) {
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
  activeRun?.cancel();
  collection?.dispose();
  output?.dispose();
}
