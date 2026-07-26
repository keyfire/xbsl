// "Exclude the finding" from the finding's lightbulb: asks for a reason and records the
// finding's identity (file + rule + message) into the baseline file - the same one CI uses
// to mute exclusions (`xbsl ... --baseline`). Works in both modes: over CLI run diagnostics
// and over LSP server diagnostics - the provider only needs the finding itself and the
// document, and the picture is refreshed by the passed relint callback.

import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import { addExclusion, toPosix } from "./baselineCore";
import { isXbslSource } from "./report";

const EXCLUDE_COMMAND = "xbsl.excludeFinding";
const DEFAULT_BASELINE = ".xbsllint-baseline";

// Baseline file of a workspace folder: the xbsl.baseline setting (absolute or relative to
// the folder), an empty setting - <folder>/.xbsllint-baseline. A path is always returned:
// an exclusion can be written into a file that does not exist yet.
export function baselineTarget(folder: vscode.WorkspaceFolder): string {
  const raw = (vscode.workspace.getConfiguration("xbsl", folder.uri).get<string>("baseline") || "").trim();
  const rel = raw || DEFAULT_BASELINE;
  return path.isAbsolute(rel) ? rel : path.join(folder.uri.fsPath, rel);
}

// Baseline file for linter runs: only an existing one (the linter responds to a missing
// file with an error, and before the first exclusion the file may not exist at all).
export function baselineForLint(resource?: vscode.Uri): string | undefined {
  const folder = resource
    ? vscode.workspace.getWorkspaceFolder(resource)
    : vscode.workspace.workspaceFolders?.[0];
  if (!folder) {
    return undefined;
  }
  const target = baselineTarget(folder);
  return fs.existsSync(target) ? target : undefined;
}

function ruleIdOf(diag: vscode.Diagnostic): string | undefined {
  const code = diag.code;
  if (typeof code === "string") {
    return code;
  }
  if (code && typeof code === "object" && typeof (code as { value?: unknown }).value === "string") {
    return (code as { value: string }).value;
  }
  return undefined;
}

class ExcludeActionProvider implements vscode.CodeActionProvider {
  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    if (document.uri.scheme !== "file") {
      return [];
    }
    const actions: vscode.CodeAction[] = [];
    for (const diag of context.diagnostics) {
      if (!isXbslSource(diag)) {
        continue;
      }
      const rule = ruleIdOf(diag);
      if (!rule) {
        continue;
      }
      // "This finding", not "the check": a single identity is excluded (file + rule +
      // message), the rule keeps applying to the rest of the project.
      const action = new vscode.CodeAction(
        vscode.l10n.t("Exclude this finding (to the baseline): {0}", rule),
        vscode.CodeActionKind.QuickFix
      );
      action.diagnostics = [diag];
      action.command = {
        command: EXCLUDE_COMMAND,
        title: action.title,
        arguments: [document.uri, rule, diag.message],
      };
      actions.push(action);
    }
    return actions;
  }
}

async function excludeFinding(
  uri: vscode.Uri,
  rule: string,
  message: string,
  relint: (uri: vscode.Uri) => void | Promise<void>
): Promise<void> {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (!folder) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("XBSL: the file is outside the workspace – there is no baseline to record the exclusion in.")
    );
    return;
  }
  const reason = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Why is the code right as it is? The reason is recorded in the baseline."),
    placeHolder: vscode.l10n.t("e.g.: a historical name, renaming would break the data"),
    ignoreFocusOut: true,
    validateInput: (value) =>
      value.trim() === "" ? vscode.l10n.t("An exclusion needs a reason – the next reader will look for it.") : undefined,
  });
  if (reason === undefined) {
    return; // input cancelled - the exclusion is not recorded
  }
  const target = baselineTarget(folder);
  const relPath = toPosix(path.relative(path.dirname(target), uri.fsPath));
  let text: string | undefined;
  try {
    text = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : undefined;
    fs.writeFileSync(target, addExclusion(text, relPath, rule, message, reason.trim()), "utf8");
  } catch (e) {
    void vscode.window.showErrorMessage(
      vscode.l10n.t("XBSL: failed to write the baseline {0}: {1}", target, e instanceof Error ? e.message : String(e))
    );
    return;
  }
  void vscode.window.setStatusBarMessage(
    vscode.l10n.t("XBSL: the finding is excluded, the reason is recorded in {0}", path.basename(target)),
    5000
  );
  await relint(uri);
}

// relint: how to refresh diagnostics after recording an exclusion (in CLI mode - a full rerun
// of the runs, in LSP mode - an xbsl/relint request or a server restart when there was no
// baseline yet).
export function registerExcludeAction(
  context: vscode.ExtensionContext,
  relint: (uri: vscode.Uri) => void | Promise<void>
): void {
  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      [
        { scheme: "file", language: "xbsl" },
        { scheme: "file", language: "yaml" },
      ],
      new ExcludeActionProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    ),
    vscode.commands.registerCommand(EXCLUDE_COMMAND, (uri: vscode.Uri, rule: string, message: string) =>
      excludeFinding(uri, rule, message, relint)
    )
  );
}
