// Status bar (bottom right): the extension and xbsl engine versions + the completion mode
// (plain CLI / LSP). Needed to see at a glance during development which build is active and
// not confuse an old one with a new one. The linter version comes from calling
// "<linter> --version"; on failure "?" is shown.

import * as vscode from "vscode";
import { spawn } from "child_process";
import { createHash } from "crypto";
import * as fs from "fs";
import * as path from "path";
import { CiStatus, ciIndicator, shortJob } from "./ciStatusCore";
import { LinterConfig } from "./report";
import { compareVersions } from "./updateCheckCore";

const SHOW_INFO = "xbsl.showVersionInfo";
const SHOW_CI = "xbsl.showCiRuleSet";
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

// The version of a companion tool, from `<binary> --version`; undefined when it does not run.
function toolVersion(command: string, args: string[]): Promise<string | undefined> {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(command, args);
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

function linterVersion(cfg: LinterConfig): Promise<string | undefined> {
  return toolVersion(cfg.command, [...(cfg.usePython ? ["-m", "xbsl"] : []), "--version"]);
}

// elemctl is what deploy and debugging both run, and neither works without it - so the status
// bar answers "is it there and which one" in the same place it answers that about the engine.
function elemctlVersion(): Promise<string | undefined> {
  const configured = (vscode.workspace.getConfiguration("xbsl").get<string>("deploy.elemctlPath")
    || "").trim();
  return toolVersion(configured || "elemctl", ["--version"]);
}

export function registerStatusBar(
  context: vscode.ExtensionContext,
  getLinter: (resource?: vscode.Uri) => LinterConfig
): {
  setLspMode: (on: boolean) => void;
  setLatestVersion: (latest?: string) => void;
  setCiStatus: (status?: CiStatus) => void;
} {
  const extVersion = String(context.extension.packageJSON.version ?? "?");
  const build = buildId(context);
  const hash = build ? build.hash : "?";
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  item.command = SHOW_INFO;
  // A second item, to the left of the versions one and shown only when the parity was asked
  // for: WHICH rule set the panel judges by is a property of the workspace, not of the build,
  // and a finding is looked at far more often than a version.
  const ciItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
  ciItem.command = SHOW_CI;
  let ci: CiStatus | undefined;
  let linter = "…";
  // undefined - not asked yet; "" - asked and not found (deploy and debugging will not work).
  let elemctl: string | undefined;
  // The ACTUAL mode is shown, not the configured one: the server may have failed to start
  // (no [lsp] extra), and then completion works the old way, via the CLI index. It is set
  // by extension.ts after startup.
  let lspOn = false;
  // The version published to Open VSX, when it is newer than the installed one. The
  // extension is side-loaded from a vsix, so nothing else in the editor would ever say it.
  let update: string | undefined;

  // Appended to the tooltip rather than woven into its sentence: the sentence already has a
  // translation, and adding a placeholder to it would drop that translation on every language.
  const elemctlPart = (): string => {
    if (elemctl === undefined) {
      return "";
    }
    return " · " + (elemctl
      ? vscode.l10n.t("elemctl {0}", elemctl)
      : vscode.l10n.t("elemctl: not found"));
  };

  const line = (): string => {
    const base = vscode.l10n.t(
      "Extension XBSL {0} (build {3}, built {4}) · engine xbsl {1} · completion: {2}",
      extVersion,
      linter,
      lspOn ? vscode.l10n.t("LSP") : vscode.l10n.t("CLI index"),
      hash,
      build ? builtAgo(build.builtAt) : "?"
    ) + elemctlPart();
    return update
      ? `${base}
` + vscode.l10n.t("A newer extension is published: {0}", update)
      : base;
  };

  const render = (): void => {
    // "engine", not "lint": since 0.16 this is the whole toolkit (lint, LSP, scaffolding),
    // and the tooltip next to it says "engine xbsl" - the captions must match.
    const mark = update ? "$(arrow-up) " : "";
    item.text = `${mark}$(versions) XBSL ${extVersion} · ${hash} · engine ${linter}`;
    item.tooltip = line();
    item.show();
  };

  // The sentence about the parity: the server's own lines, plus the one thing the server has
  // no word for - what the editor does INSTEAD when the job's set was not taken.
  const ciLines = (): string[] => {
    const view = ciIndicator(ci);
    if (view.state === "refused") {
      return [
        vscode.l10n.t(
          "The rule set of the CI job was NOT taken - the Problems panel judges by the rules of the settings."
        ),
        ...view.details,
      ];
    }
    return view.details;
  };

  const renderCi = (): void => {
    const view = ciIndicator(ci);
    if (view.state === "off") {
      ciItem.hide();
      return;
    }
    const taken = view.state === "adopted";
    ciItem.text = taken
      ? `$(checklist) CI: ${shortJob(view.job)}`
      : `$(warning) ${vscode.l10n.t("CI: not taken")}`;
    ciItem.tooltip = ciLines().join("\n");
    // The warning colour is for the state that used to be silent: asked for and not taken.
    ciItem.backgroundColor = taken
      ? undefined
      : new vscode.ThemeColor("statusBarItem.warningBackground");
    ciItem.show();
  };

  const refresh = async (): Promise<void> => {
    render();
    linter = (await linterVersion(getLinter())) ?? "?";
    render();
    elemctl = (await elemctlVersion()) ?? "";
    render();
  };

  // Otherwise the freshness in the tooltip would freeze at whatever it was at window startup.
  const ageTimer = setInterval(render, AGE_REFRESH_MS);

  context.subscriptions.push(
    item,
    ciItem,
    { dispose: () => clearInterval(ageTimer) },
    vscode.commands.registerCommand(SHOW_INFO, () => void vscode.window.showInformationMessage(line())),
    // A click goes where the answer is: the pipeline file that names the job (the include it
    // actually stands in, when one brought it). With nothing taken there is no file to open,
    // and the message carries the reason instead.
    vscode.commands.registerCommand(SHOW_CI, () => {
      const view = ciIndicator(ci);
      const text = ciLines().join("\n");
      if (!view.open) {
        void vscode.window.showInformationMessage(text || vscode.l10n.t("CI: not taken"));
        return;
      }
      void vscode.window.showTextDocument(vscode.Uri.file(view.open));
    }),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("xbsl.linter") || e.affectsConfiguration("xbsl.lsp")
          || e.affectsConfiguration("xbsl.deploy.elemctlPath")) {
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
    setLatestVersion: (latest?: string): void => {
      update = latest && compareVersions(latest, extVersion) > 0 ? latest : undefined;
      render();
    },
    // Set from the answer of the server (xbsl/ciStatus) - after the start and after every
    // restart, because a restart is exactly what a changed parity setting causes.
    setCiStatus: (status?: CiStatus): void => {
      ci = status;
      renderCi();
    },
  };
}
