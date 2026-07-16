import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig, RawDiag, RawReport } from "./report";
import { registerDeploy } from "./deploy";
import { registerFormPreview } from "./formPreview";
import { baselineForLint, registerExcludeAction } from "./excludeAction";
import { lintBuffer, lintPath, makeDiagnostic, RunHandle, toDiagnostic } from "./linter";
import { activateLsp, lspActive, lspBaselinePassed, lspRequest } from "./lspClient";
import { registerNavigation } from "./navigation";
import { registerMetadataTree } from "./metadataTree";
import { registerMetadataProps } from "./metadataProps";
import { registerDocs } from "./docsTree";
import { registerStatusBar } from "./statusBar";
import { registerPalettePicker } from "./palettes";
import { pipInstallCommand, runInstallTask } from "./installer";
import { mergeOffRules, registerRuleConfig, ruleOverride } from "./ruleConfig";
import { groupReportByFile } from "./workspaceCore";
import { FixSnapshot, PROVIDED_KINDS, XbslCodeActionProvider } from "./codeActions";

let collection: vscode.DiagnosticCollection;
let output: vscode.OutputChannel;
const debounceTimers = new Map<string, NodeJS.Timeout>();
let warnedOnce = false;

// Последние исправимые находки по каждому документу со штампом версии (uri -> снимок) – для
// Quick Fix. Устаревшую запись (версия не совпала) провайдер игнорирует, поэтому смещение
// исправления никогда не применяется к тексту, изменившемуся после породившего его прогона.
const fixStore = new Map<string, FixSnapshot>();

function setFixSnapshot(uri: vscode.Uri, version: number, diags: RawDiag[]): void {
  const fixable = diags.filter((d) => d.fix);
  if (fixable.length > 0) {
    fixStore.set(uri.toString(), { version, diags: fixable });
  } else {
    fixStore.delete(uri.toString());
  }
}

// --- Состояние прогона по воркспейсу -----------------------------------------------------
// Одна коллекция находок, два поставщика:
//  * быстрый прогон `--stdin` владеет находками редактируемого (грязного) буфера;
//  * прогон по всему воркспейсу (при сохранении, с задержкой, по одному за раз) заменяет
//    находки всех остальных файлов – ему видны проектные правила, недоступные одному буферу.

// Доля одного файла в последнем завершённом прогоне по воркспейсу: находки, преобразованные
// для коллекции, и исходные, из которых они получены – по исходным восстанавливается снимок
// Quick Fix, когда файл открывают уже после прогона.
interface WorkspaceEntry {
  uri: vscode.Uri;
  diags: vscode.Diagnostic[];
  raw: RawDiag[];
}

// Последний завершённый прогон по каждой папке воркспейса: uri файла -> его запись.
const workspaceResults = new Map<string, Map<string, WorkspaceEntry>>();
// Таймеры задержки запланированных прогонов по воркспейсу, по папкам.
const workspaceTimers = new Map<string, NodeJS.Timeout>();
// Прогоны, ожидающие в цепочке (ещё не начатые), по папкам – убирают дубли частых сохранений.
const queuedRuns = new Map<string, Promise<void>>();
// Единственный выполняющийся прогон; новое сохранение той же папки его отменяет.
let activeRun: { folderKey: string; handle: RunHandle } | undefined;
// Прогоны по воркспейсу выполняются строго один за другим.
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
      // Правила и группы, выключенные в настройках (off), не запускаются вовсе.
      ignore: mergeOffRules((c.get<string>("linter.ignore") || "").trim() || undefined, resource),
      // Существующий файл базлайна: исключённые находки гасятся в каждом прогоне.
      baseline: baselineForLint(resource),
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

// Файлы, понятные линтеру: модули .xbsl и описания элементов .yaml.
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
  // Путь относительно папки воркспейса (cwd прогона), а не голое имя: по нему находки
  // сопоставляются с записями базлайна, а structure/xbsl-pair видит настоящего соседа.
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
  // Отбрасываем устаревший результат: буфер изменился, пока работал линтер.
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
  const install = notFound ? vscode.l10n.t("Install xbsllint") : undefined;
  const showLog = vscode.l10n.t("Show log");
  const buttons = install ? [install, showLog] : [showLog];
  void vscode.window.showErrorMessage(`XBSL: ${message}`, ...buttons).then((pick) => {
    if (install && pick === install) {
      runInstallTask("xbsllint", pipInstallCommand("xbsllint"), "xbsl.restartLinter");
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

// --- Прогон по воркспейсу ----------------------------------------------------------------

// Результат последнего завершённого прогона для файла: запись (возможно, без находок), если
// папку файла уже проверяли, и undefined, если ни один прогон ещё не завершился.
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

// Точка входа с задержкой: повторные сохранения внутри окна схлопываются в один прогон.
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

// По одному прогону за раз: прогоны выстраиваются в цепочку, папка стоит в очереди не более
// одного раза, а сохранение во время проверки её папки отменяет ставший неактуальным прогон.
function enqueueWorkspaceRun(folder: vscode.WorkspaceFolder, notify = false): Promise<void> {
  const key = folder.uri.toString();
  const queued = queuedRuns.get(key);
  if (queued) {
    return queued; // ещё не начат – он и так возьмёт с диска свежие файлы
  }
  if (activeRun && activeRun.folderKey === key) {
    activeRun.handle.cancel(); // его результат описывал бы файлы, которых в таком виде уже нет
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
    // Мягкий отказ: огромный воркспейс или сломанный линтер не должны при каждом сохранении
    // сыпать всплывающими окнами.
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

// Раскладывает находки прогона по файлам папки, заменяя всё, что было там раньше. Исключение –
// грязные буферы: их находки принадлежат живому прогону `--stdin`, пока буфер не сохранён
// (прогон по файлам на диске их попросту не видит).
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
    // Смещения дискового прогона годятся только для чистого открытого буфера; штампуем его версией.
    if (doc) {
      setFixSnapshot(entry.uri, doc.version, entry.raw);
    }
  }
  // Файлы, у которых находок не осталось: всё в этой папке, чего свежий прогон не упомянул,
  // теперь чисто.
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

// Ручная команда: проверить все папки воркспейса, с индикатором хода и видимой ошибкой.
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

// Забыть всё и начать заново: используется командой перезапуска и при изменении настроек.
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

  // Общие для обоих режимов: палитра, настройка правил с находки, деплой на стенд,
  // предпросмотр форм.
  registerPalettePicker(context);
  registerRuleConfig(context);
  // Исключение находки в базлайн (лампочка). После записи: в CLI-режиме перечитываем всё
  // с нуля; в LSP-режиме сервер перечитывает базлайн на каждом прогоне - достаточно
  // xbsl/relint, а если файла при старте сервера не было, перезапускаем его с новым
  // аргументом --baseline.
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
  registerMetadataProps(context, metadataTree.typeCandidates);
  // Документация Элемента: дерево справки, поиск и показ страницы по символу под курсором.
  // Данные тянет от LSP-сервера линтера; в CLI-режиме (сервер не поднят) команды сообщают об этом.
  registerDocs(context);
  // Версии расширения/линтера и режим дополнения в статус-баре (до LSP-ветки – виден в обоих режимах).
  const statusBar = registerStatusBar(context, (resource) => readSettings(resource).linter);

  // LSP-режим (по умолчанию): всё делает долгоживущий сервер xbsllint-lsp - он же даёт hover и
  // дополнение по типам. При неудачном старте продолжаем в обычном режиме (CLI); о неудаче
  // сообщаем, только если режим выбран явно, иначе у поставивших линтер без extra [lsp] всплывало
  // бы окно с ошибкой на ровном месте.
  const lspSetting = vscode.workspace.getConfiguration("xbsl").inspect<boolean>("lsp.enabled");
  const lspChosen =
    lspSetting?.workspaceFolderValue ?? lspSetting?.workspaceValue ?? lspSetting?.globalValue;
  if (lspChosen ?? lspSetting?.defaultValue ?? true) {
    if (await activateLsp(context, output, lspChosen !== undefined)) {
      statusBar.setLspMode(true);
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
      // Чистому буферу, чей файл уже покрыт прогоном по воркспейсу, проход `--stdin` не нужен:
      // он увидел бы только пофайловые правила и стёр бы проектные. Снимок Quick Fix вместо
      // этого восстанавливается из сохранённого прогона – прогон штампует только те документы,
      // что были открыты в тот момент, а закрытие документа снимок удаляет. Буфер чист, поэтому
      // дисковые смещения прогона для него верны.
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
        // Файл на диске теперь актуален – прогон по всему воркспейсу заменит находки буфера
        // полным набором (пофайловые и проектные правила вместе).
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
      // Файл по-прежнему часть проекта: возвращаем находки последнего прогона по воркспейсу
      // (закрытый буфер мог быть грязным, его результаты `--stdin` умирают вместе с ним).
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
