// Metadata scaffolding: a thin client of the xbsl engine. The single source of templates and
// edits is the engine's xbsl.scaffold module; the extension only gathers parameters in the UI
// and applies the returned changes via WorkspaceEdit (undo and dirty buffers survive).
//
// Two transports with an identical result (full new file texts):
//   - LSP mode: the custom xbsl/meta* request (the server reads open buffers);
//   - CLI mode: `xbsl <subcommand> ... --dry-run` (the engine reads the disk, so before
//     editing an existing file a dirty buffer is offered to be saved).

import { spawn } from "child_process";
import * as vscode from "vscode";
import { lspActive, lspRequest } from "./lspClient";
import { pipInstallCommand, runInstallTask } from "./installer";

export interface ScaffoldFile {
  path: string;
  created: boolean;
  content: string;
  cursor?: { line: number; character: number } | null;
}

export interface ScaffoldResult {
  files?: ScaffoldFile[];
  notes?: string[];
  error?: string;
}

interface CliPlan {
  command: string;
  args: string[];
}

function cliPlan(subcommand: string, args: string[]): CliPlan {
  const cfg = vscode.workspace.getConfiguration("xbsl");
  const python = (cfg.get<string>("linter.pythonPath") || "").trim();
  if (python) {
    return { command: python, args: ["-m", "xbsl", subcommand, ...args, "--dry-run"] };
  }
  const command = (cfg.get<string>("linter.command") || "xbsl").trim();
  return { command, args: [subcommand, ...args, "--dry-run"] };
}

function runCli(plan: CliPlan, cwd: string | undefined): Promise<ScaffoldResult | undefined> {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(plan.command, plan.args, { cwd });
    } catch {
      resolve(undefined);
      return;
    }
    let out = "";
    child.stdout.on("data", (d: Buffer) => (out += d.toString("utf8")));
    child.stderr.on("data", () => undefined);
    child.on("error", () => resolve(undefined));
    child.on("close", () => {
      try {
        resolve(JSON.parse(out) as ScaffoldResult);
      } catch {
        resolve(undefined); // non-JSON: an old engine without subcommands or a startup crash
      }
    });
    child.stdin?.end();
  });
}

// Message about scaffolding being unavailable: an old engine or the engine is not installed.
function reportUnavailable(): void {
  const install = vscode.l10n.t("Install/upgrade the engine");
  void vscode.window
    .showErrorMessage(
      vscode.l10n.t("XBSL: metadata commands need the xbsl engine 0.16+ (pip install --upgrade xbsl)."),
      install
    )
    .then((pick) => {
      if (pick === install) {
        runInstallTask("xbsl", pipInstallCommand("xbsl"), "workbench.action.reloadWindow");
      }
    });
}

// Scaffolding operation call: LSP when the server is active, otherwise CLI. undefined - the
// engine is unavailable (the message is already shown); {error} - the operation refused
// (shown by the caller).
export async function callMeta(
  lspMethod: string,
  lspParams: Record<string, unknown>,
  cliSubcommand: string,
  cliArgs: string[],
  cwd?: string
): Promise<ScaffoldResult | undefined> {
  if (lspActive()) {
    const viaLsp = await lspRequest<ScaffoldResult>(lspMethod, lspParams);
    if (viaLsp) {
      return viaLsp;
    }
    // The server is up but the method is missing - the engine is older than the extension.
  }
  const viaCli = await runCli(cliPlan(cliSubcommand, cliArgs), cwd);
  if (viaCli) {
    return viaCli;
  }
  reportUnavailable();
  return undefined;
}

// In CLI mode the engine reads files from disk: an unsaved buffer of the file being edited
// must be saved before the call, otherwise applying the full new text would wipe the edits.
export async function ensureSavedForCli(paths: string[]): Promise<boolean> {
  if (lspActive()) {
    return true; // the LSP server sees the buffers, saving is not needed
  }
  const dirty = vscode.workspace.textDocuments.filter(
    (doc) => doc.isDirty && paths.some((p) => doc.uri.fsPath === p)
  );
  if (!dirty.length) {
    return true;
  }
  const save = vscode.l10n.t("Save and continue");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t("XBSL: the file has unsaved changes; save it before the metadata edit."),
    { modal: true },
    save
  );
  if (pick !== save) {
    return false;
  }
  for (const doc of dirty) {
    await doc.save();
  }
  return true;
}

// Applying the result: new files are created, edited ones are replaced entirely by a single
// WorkspaceEdit (reversible via undo). Returns the list of affected paths.
export async function applyScaffold(result: ScaffoldResult): Promise<string[]> {
  if (result.error) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", result.error));
    return [];
  }
  const files = result.files ?? [];
  const we = new vscode.WorkspaceEdit();
  for (const file of files) {
    const uri = vscode.Uri.file(file.path);
    if (file.created) {
      we.createFile(uri, { contents: Buffer.from(file.content, "utf8"), ignoreIfExists: false });
    } else {
      const doc = await vscode.workspace.openTextDocument(uri);
      const full = new vscode.Range(doc.positionAt(0), doc.positionAt(doc.getText().length));
      we.replace(uri, full, file.content);
    }
  }
  await vscode.workspace.applyEdit(we);
  // Edits of existing files are saved (file creation via WorkspaceEdit already writes to disk).
  for (const file of files.filter((f) => !f.created)) {
    const doc = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === file.path);
    if (doc?.isDirty) {
      await doc.save();
    }
  }
  for (const note of result.notes ?? []) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: {0}", note));
  }
  return files.map((f) => f.path);
}
