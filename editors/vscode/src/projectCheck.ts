import * as vscode from "vscode";
import { singleProjectCheck } from "./projectCheckCore";
import { ProjectCheckProgress, projectCheckSummary } from "./projectCheckProgressCore";

export const REINDEX_PROJECT = "xbsl.reindexProject";

export function registerProjectCheck(context: vscode.ExtensionContext,
  check: (report: (event: ProjectCheckProgress) => void) => Promise<void>): void {
  const item = vscode.window.createStatusBarItem("xbsl.reindexProject", vscode.StatusBarAlignment.Left, 49);
  const title = vscode.l10n.t("Reindex and check the project");
  item.name = "XBSL: " + title;
  item.accessibilityInformation = { label: "XBSL: " + title, role: "button" };
  let busy = false;
  let current = "";
  let summary = "";
  const state = (value: boolean): void => {
    busy = value;
    const text = busy ? "$(sync~spin) " + summary : "$(refresh)";
    const tooltip = busy && current ? title + "\n" + current : title;
    if (item.text !== text) { item.text = text; }
    if (item.tooltip !== tooltip) { item.tooltip = tooltip; }
    item.command = busy ? undefined : REINDEX_PROJECT;
    if (vscode.workspace.workspaceFolders?.length) { item.show(); } else { item.hide(); }
  };
  const run = singleProjectCheck(async () => {
    const started = Date.now();
    let message = vscode.l10n.t("Waiting for project progress...");
    summary = vscode.l10n.t("Waiting for project progress...");
    const refresh = (event?: ProjectCheckProgress): void => {
      if (event?.message) {
        message = event.message;
        if (event.kind !== "end") {
          summary = projectCheckSummary(message) || vscode.l10n.t("Checking project...");
        }
      }
      const seconds = Math.floor((Date.now() - started) / 1000);
      const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
      current = message + " | " + vscode.l10n.t("Elapsed: {0}", time);
      state(true);
    };
    refresh();
    const clock = setInterval(() => refresh(), 1000);
    try {
      await check((event) => refresh(event));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void vscode.window.showErrorMessage(vscode.l10n.t("XBSL: project check failed: {0}", message));
    } finally {
      clearInterval(clock);
      current = "";
      summary = "";
    }
  }, state);
  context.subscriptions.push(item, vscode.commands.registerCommand(REINDEX_PROJECT, run),
    vscode.workspace.onDidChangeWorkspaceFolders(() => state(busy)));
  state(false);
}
