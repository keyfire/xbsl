// Экспериментальный LSP-режим (xbsl.lsp.enabled): вместо вызовов CLI на каждое событие
// расширение поднимает долгоживущий сервер xbsl-lsp (extra [lsp] пакета xbsl) и
// отдаёт ему диагностику, навигацию, автодополнение, hover и quick-fix. Данные Элемента и
// индекс проекта живут в памяти сервера - отклик на набор текста не платит за старт
// интерпретатора.

import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
} from "vscode-languageclient/node";
import { baselineForLint } from "./excludeAction";
import { pipInstallCommand, runInstallTask } from "./installer";
import { applyOverride, mergeOffRules } from "./ruleConfig";
import { docCode } from "./ruleDocs";

let client: LanguageClient | undefined;
let baselineArg: string | undefined;

// Активен ли LSP-режим (сервер поднят). Панель документации – тонкий клиент к серверу.
export function lspActive(): boolean {
  return client !== undefined;
}

// Передан ли серверу --baseline при старте. Если базлайна ещё не было (первое исключение
// только создаёт файл), серверу нужен перезапуск с новыми аргументами, а не xbsl/relint.
export function lspBaselinePassed(): boolean {
  return baselineArg !== undefined;
}

// Кастомный запрос к серверу (методы xbsl/docs*). Возвращает undefined, если сервер не поднят
// или запрос упал – потребитель показывает это как "данные недоступны", а не падает.
export async function lspRequest<T>(method: string, params: unknown): Promise<T | undefined> {
  if (!client) {
    return undefined;
  }
  try {
    return await client.sendRequest<T>(method, params);
  } catch {
    return undefined;
  }
}

interface SpawnPlan {
  command: string;
  args: string[];
}

// Чем запускать сервер: явная команда из настройки, иначе интерпретатор из
// xbsl.linter.pythonPath (модулем), иначе xbsl-lsp из PATH.
function spawnPlan(cfg: vscode.WorkspaceConfiguration): SpawnPlan {
  const explicit = (cfg.get<string>("lsp.command") || "").trim();
  if (explicit) {
    return { command: explicit, args: [] };
  }
  const python = (cfg.get<string>("linter.pythonPath") || "").trim();
  if (python) {
    return { command: python, args: ["-m", "xbsl.lsp"] };
  }
  return { command: "xbsl-lsp", args: [] };
}

// Собирает клиента по ТЕКУЩИМ настройкам и состоянию диска: перезапуск линтера создаёт
// клиента заново, поэтому подхватывает изменившиеся наборы правил и появившийся файл
// базлайна (аргументы старого процесса пересобрать нельзя).
function buildClient(output: vscode.OutputChannel): { client: LanguageClient; plan: SpawnPlan; args: string[] } {
  const cfg = vscode.workspace.getConfiguration("xbsl");
  const folder = vscode.workspace.workspaceFolders?.[0];
  const plan = spawnPlan(cfg);
  const args = [...plan.args];
  const projectRoot = (cfg.get<string>("projectRoot") || "").trim();
  if (projectRoot) {
    args.push("--project-root", projectRoot);
  }
  for (const [flag, key] of [
    ["--select", "linter.select"],
    ["--data-dir", "linter.dataDir"],
    ["--lang", "linter.lang"],
    // A custom templates file: the server resolves a relative path from the workspace
    // folder. An empty setting is not passed - the server then defaults to
    // .xbsl-templates.json at the workspace root, the very file the panel writes.
    ["--templates", "templates.file"],
  ] as const) {
    const value = (cfg.get<string>(key) || "").trim();
    if (value) {
      args.push(flag, value);
    }
  }
  // Выключенные в настройках правила и группы дополняют --ignore: сервер их не запускает.
  const ignore = mergeOffRules((cfg.get<string>("linter.ignore") || "").trim() || undefined);
  if (ignore) {
    args.push("--ignore", ignore);
  }
  // Существующий файл базлайна: исключённые находки гасит сервер. Отсутствующий не
  // передаём - у сервера старой версии (< 0.15) неизвестный ключ сорвал бы запуск.
  baselineArg = folder ? baselineForLint(folder.uri) : undefined;
  if (baselineArg) {
    args.push("--baseline", baselineArg);
  }

  const serverOptions: ServerOptions = {
    command: plan.command,
    args,
    options: { cwd: folder?.uri.fsPath },
  };
  // yaml ограничиваем корнем исходников, чтобы не линтить посторонние yaml репозитория.
  const yamlPattern = projectRoot ? `**/${projectRoot}/**/*.yaml` : "**/*.yaml";
  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ language: "xbsl" }, { language: "yaml", pattern: yamlPattern }],
    outputChannel: output,
    diagnosticCollectionName: "xbsl-lsp",
    middleware: {
      // Пер-правило переопределения xbsl.rules поверх диагностик сервера: скрыть off,
      // заменить уровень; у правила-стандарта значок правила становится ссылкой на документ.
      handleDiagnostics: (uri, diagnostics, next) => {
        next(
          uri,
          diagnostics
            .map((d) => applyOverride(d, uri))
            .filter((d): d is vscode.Diagnostic => d !== null)
            .map((d) => {
              if (typeof d.code === "string") {
                d.code = docCode(d.code);
              }
              return d;
            })
        );
      },
    },
  };

  return { client: new LanguageClient("xbslLsp", "XBSL LSP", serverOptions, clientOptions), plan, args };
}

export async function activateLsp(
  context: vscode.ExtensionContext,
  output: vscode.OutputChannel,
  chosenExplicitly = true
): Promise<boolean> {
  const built = buildClient(output);
  client = built.client;
  try {
    await client.start();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    output.appendLine(vscode.l10n.t('XBSL LSP: the server failed to start ({0}): {1}', built.plan.command, msg));
    client = undefined;
    if (!chosenExplicitly) {
      return false;  // режим не выбирали - молча работаем как раньше (CLI), подробности в панели вывода
    }
    const install = vscode.l10n.t("Install xbsl[lsp]");
    void vscode.window
      .showErrorMessage(
        vscode.l10n.t(
          'XBSL: failed to start xbsl-lsp. Install the engine with the [lsp] extra (pip install "xbsl[lsp]") or set the command in the xbsl.lsp.command setting. The extension keeps working in the regular mode (CLI).'
        ),
        install
      )
      .then((pick) => {
        if (pick === install) {
          runInstallTask("xbsl[lsp]", pipInstallCommand("xbsl[lsp]"), "workbench.action.reloadWindow");
        }
      });
    return false;
  }
  output.appendLine(vscode.l10n.t('XBSL LSP: server started ({0} {1}).', built.plan.command, built.args.join(" ")));

  context.subscriptions.push(
    { dispose: () => void client?.stop() },
    // Команды сохраняют привычные идентификаторы и в LSP-режиме. Перезапуск пересоздаёт
    // клиента, а не дёргает restart(): аргументы сервера собираются заново.
    vscode.commands.registerCommand("xbsl.restartLinter", async () => {
      const old = client;
      client = undefined;
      if (old) {
        await old.stop().catch(() => undefined);
      }
      const fresh = buildClient(output);
      try {
        await fresh.client.start();
        client = fresh.client;
        void vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL LSP: server restarted"), 3000);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        output.appendLine(vscode.l10n.t('XBSL LSP: the server failed to start ({0}): {1}', fresh.plan.command, msg));
        void vscode.window.showErrorMessage(vscode.l10n.t("XBSL LSP: the server did not restart – see the XBSL output panel."));
      }
    }),
    vscode.commands.registerCommand("xbsl.lintProject", () => {
      void vscode.window.showInformationMessage(
        vscode.l10n.t(
          'XBSL LSP: project-wide diagnostics run on the server on every save; force them with the "XBSL: restart the linter" command.'
        )
      );
    })
  );
  return true;
}
