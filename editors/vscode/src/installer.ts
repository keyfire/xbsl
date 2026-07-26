// Installing missing tools right from the extension: a VS Code terminal task (the install
// progress is visible to the user), on successful completion a continuation command is
// invoked (restarting the check or reloading the window for LSP mode).

import * as vscode from "vscode";

export function runInstallTask(name: string, commandLine: string, onSuccessCommand?: string): void {
  const task = new vscode.Task(
    { type: "shell", task: name },
    vscode.TaskScope.Workspace,
    name,
    "xbsl",
    new vscode.ShellExecution(commandLine)
  );
  void vscode.tasks.executeTask(task);
  if (!onSuccessCommand) {
    return;
  }
  const sub = vscode.tasks.onDidEndTaskProcess((e) => {
    if (e.execution.task.name !== name) {
      return;
    }
    sub.dispose();
    if (e.exitCode === 0) {
      void vscode.window.setStatusBarMessage(
        vscode.l10n.t("XBSL: installation finished, restarting the check"),
        5000
      );
      void vscode.commands.executeCommand(onSuccessCommand);
    }
  });
}

// pip command honoring the interpreter setting: xbsl.linter.pythonPath set - install into it.
export function pipInstallCommand(spec: string): string {
  const python = (vscode.workspace.getConfiguration("xbsl").get<string>("linter.pythonPath") || "").trim();
  return python ? `"${python}" -m pip install --upgrade "${spec}"` : `pip install --upgrade "${spec}"`;
}
