// Установка недостающих инструментов прямо из расширения: терминальная задача VS Code
// (ход установки виден пользователю), по успешному завершению вызывается команда
// продолжения (перезапуск проверки или перезагрузка окна для LSP-режима).

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

// Команда pip с учётом настройки интерпретатора: задан xbsl.linter.pythonPath - ставим в него.
export function pipInstallCommand(spec: string): string {
  const python = (vscode.workspace.getConfiguration("xbsl").get<string>("linter.pythonPath") || "").trim();
  return python ? `"${python}" -m pip install --upgrade "${spec}"` : `pip install --upgrade "${spec}"`;
}
