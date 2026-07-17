// Статус-бар (справа внизу): версия расширения и движка xbsl + режим дополнения (обычный CLI /
// LSP). Нужно, чтобы при разработке сразу видеть, какая сборка активна, и не путать старую с новой.
// Версию линтера получаем вызовом "<линтер> --version"; при неудаче показываем "?".

import * as vscode from "vscode";
import { spawn } from "child_process";
import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig } from "./report";

const SHOW_INFO = "xbsl.showVersionInfo";
const AGE_REFRESH_MS = 60_000;

// Сборку опознаём коротким хешем установленного бандла: у всех дев-сборок одна версия (0.12.0),
// а хеш меняется вместе с кодом. Дату и время сборки не показываем - статус-бар попадает в
// скриншоты и гифки README, а знать нужно лишь одно: та же это сборка или уже новая.
function buildId(context: vscode.ExtensionContext): { hash: string; builtAt: number } | undefined {
  try {
    const file = path.join(context.extensionPath, "dist", "extension.js");
    const hash = createHash("sha256").update(fs.readFileSync(file)).digest("hex").slice(0, 6);
    return { hash, builtAt: fs.statSync(file).mtime.getTime() };
  } catch {
    return undefined;
  }
}

// Свежесть сборки словами, без абсолютного времени: "только что", "12 мин назад", "3 ч назад".
function builtAgo(builtAt: number): string {
  const minutes = Math.max(0, Math.floor((Date.now() - builtAt) / 60_000));
  if (minutes < 1) {
    return vscode.l10n.t("just now");
  }
  if (minutes < 60) {
    return vscode.l10n.t("{0} min ago", minutes);
  }
  const hours = Math.floor(minutes / 60);
  return hours < 24 ? vscode.l10n.t("{0} h ago", hours) : vscode.l10n.t("{0} d ago", Math.floor(hours / 24));
}

function linterVersion(cfg: LinterConfig): Promise<string | undefined> {
  return new Promise((resolve) => {
    const args = [...(cfg.usePython ? ["-m", "xbsl"] : []), "--version"];
    let child;
    try {
      child = spawn(cfg.command, args);
    } catch {
      resolve(undefined);
      return;
    }
    let out = "";
    const grab = (d: Buffer): void => {
      out += d.toString("utf8");
    };
    child.stdout.on("data", grab);
    child.stderr.on("data", grab); // некоторые инструменты печатают версию в stderr
    child.on("error", () => resolve(undefined));
    child.on("close", () => {
      const m = /(\d+\.\d+(?:\.\d+)?[A-Za-z0-9.+-]*)/.exec(out);
      resolve(m ? m[1] : undefined);
    });
    child.stdin?.end();
  });
}

export function registerStatusBar(
  context: vscode.ExtensionContext,
  getLinter: (resource?: vscode.Uri) => LinterConfig
): { setLspMode: (on: boolean) => void } {
  const extVersion = String(context.extension.packageJSON.version ?? "?");
  const build = buildId(context);
  const hash = build ? build.hash : "?";
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  item.command = SHOW_INFO;
  let linter = "…";
  // Режим показываем ФАКТИЧЕСКИЙ, а не по настройке: сервер мог не подняться (нет extra [lsp]),
  // и тогда дополнение идёт по-старому, через CLI-индекс. Ставит его extension после запуска.
  let lspOn = false;

  const line = (): string =>
    vscode.l10n.t(
      "Extension XBSL {0} (build {3}, built {4}) · engine xbsl {1} · completion: {2}",
      extVersion,
      linter,
      lspOn ? vscode.l10n.t("LSP") : vscode.l10n.t("CLI index"),
      hash,
      build ? builtAgo(build.builtAt) : "?"
    );

  const render = (): void => {
    // "engine", а не "lint": с 0.16 это инструментарий целиком (линт, LSP, скаффолдинг),
    // и тултип рядом говорит "движок xbsl" - подписи должны совпадать.
    item.text = `$(versions) XBSL ${extVersion} · ${hash} · engine ${linter}`;
    item.tooltip = line();
    item.show();
  };

  const refresh = async (): Promise<void> => {
    render();
    linter = (await linterVersion(getLinter())) ?? "?";
    render();
  };

  // Иначе свежесть в подсказке застынет на том, чем была при запуске окна.
  const ageTimer = setInterval(render, AGE_REFRESH_MS);

  context.subscriptions.push(
    item,
    { dispose: () => clearInterval(ageTimer) },
    vscode.commands.registerCommand(SHOW_INFO, () => void vscode.window.showInformationMessage(line())),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("xbsl.linter") || e.affectsConfiguration("xbsl.lsp")) {
        void refresh();
      }
    })
  );
  void refresh();
  return {
    setLspMode: (on: boolean): void => {
      lspOn = on;
      render();
    },
  };
}
