// Status bar (bottom right): the extension and xbsl engine versions + the completion mode
// (plain CLI / LSP). Needed to see at a glance during development which build is active and
// not confuse an old one with a new one. The linter version comes from calling
// "<linter> --version"; on failure "?" is shown.

import * as vscode from "vscode";
import { spawn } from "child_process";
import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";
import { LinterConfig } from "./report";

const SHOW_INFO = "xbsl.showVersionInfo";
const AGE_REFRESH_MS = 60_000;

// A build is identified by a short hash of the installed bundle: all dev builds share one
// version (0.12.0), while the hash changes with the code. Build date and time are not shown -
// the status bar ends up in README screenshots and gifs, and only one thing matters: whether
// this is the same build or a new one.
function buildId(context: vscode.ExtensionContext): { hash: string; builtAt: number } | undefined {
  try {
    const file = path.join(context.extensionPath, "dist", "extension.js");
    const hash = createHash("sha256").update(fs.readFileSync(file)).digest("hex").slice(0, 6);
    return { hash, builtAt: fs.statSync(file).mtime.getTime() };
  } catch {
    return undefined;
  }
}

// Build freshness in words, without absolute time: "just now", "12 min ago", "3 h ago".
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
    child.stderr.on("data", grab); // some tools print the version to stderr
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
  // The ACTUAL mode is shown, not the configured one: the server may have failed to start
  // (no [lsp] extra), and then completion works the old way, via the CLI index. It is set
  // by extension.ts after startup.
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
    // "engine", not "lint": since 0.16 this is the whole toolkit (lint, LSP, scaffolding),
    // and the tooltip next to it says "engine xbsl" - the captions must match.
    item.text = `$(versions) XBSL ${extVersion} · ${hash} · engine ${linter}`;
    item.tooltip = line();
    item.show();
  };

  const refresh = async (): Promise<void> => {
    render();
    linter = (await linterVersion(getLinter())) ?? "?";
    render();
  };

  // Otherwise the freshness in the tooltip would freeze at whatever it was at window startup.
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
