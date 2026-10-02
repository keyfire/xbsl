import * as vscode from "vscode";
import { singleProjectCheck } from "./projectCheckCore";

export const REINDEX_PROJECT = "xbsl.reindexProject";

export function registerProjectCheck(context: vscode.ExtensionContext, check: () => Promise<void>): void {
  const item = vscode.window.createStatusBarItem("xbsl.reindexProject", vscode.StatusBarAlignment.Left, 49);
  const title = vscode.l10n.t("Reindex and check the project");
  item.name = "XBSL: " + title;
  item.accessibilityInformation = { label: "XBSL: " + title, role: "button" };
  let busy = false;
  const state = (value: boolean): void => {
    busy = value;
    item.text = busy ? "$(sync~spin)" : "$(refresh)";
    item.tooltip = busy ? vscode.l10n.t("XBSL: reindexing and checking the project...") : title;
    item.command = busy ? undefined : REINDEX_PROJECT;
    if (vscode.workspace.workspaceFolders?.length) { item.show(); } else { item.hide(); }
  };
  const run = singleProjectCheck(async () => {
    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: "XBSL: " + title }, check,
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void vscode.window.showErrorMessage(vscode.l10n.t("XBSL: project check failed: {0}", message));
    }
  }, state);
  context.subscriptions.push(item, vscode.commands.registerCommand(REINDEX_PROJECT, run),
    vscode.workspace.onDidChangeWorkspaceFolders(() => state(busy)));
  state(false);
}
