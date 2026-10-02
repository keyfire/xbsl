import * as vscode from "vscode";
import { singleProjectCheck } from "./projectCheckCore";
import { ProjectCheckProgress } from "./projectCheckProgressCore";

export const REINDEX_PROJECT = "xbsl.reindexProject";

export function registerProjectCheck(context: vscode.ExtensionContext,
  check: (report: (event: ProjectCheckProgress) => void) => Promise<void>): void {
  const item = vscode.window.createStatusBarItem("xbsl.reindexProject", vscode.StatusBarAlignment.Left, 49);
  const title = vscode.l10n.t("Reindex and check the project");
  item.name = "XBSL: " + title;
  item.accessibilityInformation = { label: "XBSL: " + title, role: "button" };
  let busy = false;
  let current = "";
  const state = (value: boolean): void => {
    busy = value;
    item.text = busy ? "$(sync~spin)" : "$(refresh)";
    item.tooltip = busy && current ? title + "\n" + current : title;
    item.command = busy ? undefined : REINDEX_PROJECT;
    if (vscode.workspace.workspaceFolders?.length) { item.show(); } else { item.hide(); }
  };
  const run = singleProjectCheck(async () => {
    try {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "XBSL: " + title, cancellable: false },
        async (progress) => {
          const started = Date.now();
          let message = vscode.l10n.t("Waiting for project progress...");
          let percentage = 0;
          const refresh = (event?: ProjectCheckProgress): void => {
            if (event?.message) { message = event.message; }
            const seconds = Math.floor((Date.now() - started) / 1000);
            const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
            current = message + " | " + vscode.l10n.t("Elapsed: {0}", time);
            let increment = 0;
            if (event?.percentage !== undefined && Number.isFinite(event.percentage)) {
              const next = Math.max(percentage, Math.min(100, Math.max(0, event.percentage)));
              increment = next - percentage;
              percentage = next;
            }
            progress?.report({ message: current, increment });
            state(true);
          };
          refresh();
          const clock = setInterval(() => refresh(), 1000);
          try { await check((event) => refresh(event)); }
          finally { clearInterval(clock); }
        },
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      void vscode.window.showErrorMessage(vscode.l10n.t("XBSL: project check failed: {0}", message));
    } finally { current = ""; }
  }, state);
  context.subscriptions.push(item, vscode.commands.registerCommand(REINDEX_PROJECT, run),
    vscode.workspace.onDidChangeWorkspaceFolders(() => state(busy)));
  state(false);
}
