// Project deploy to a 1C:Element platform stand via `elemctl deploy`: build from sources,
// upload, apply, restart and an honest verification of the apply - all in a VS Code terminal
// task so the progress and the final report stay in sight (on an apply failure elemctl
// returns a non-zero code - the platform's Running status is not trusted as success).
// The extension only assembles the command line and asks for confirmation: the target stand
// is defined by the working folder's .env or the xbsl.deploy.* settings.

import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { pipInstallCommand, runInstallTask } from "./installer";

const TASK_NAME = "elemctl deploy";

interface DeploySettings {
  bin: string;
  envFile: string;
  appId: string;
  extraArgs: string;
}

function readDeploySettings(resource: vscode.Uri): DeploySettings {
  const c = vscode.workspace.getConfiguration("xbsl", resource);
  return {
    bin: (c.get<string>("deploy.elemctlPath") || "elemctl").trim() || "elemctl",
    envFile: (c.get<string>("deploy.envFile") || "").trim(),
    appId: (c.get<string>("deploy.appId") || "").trim(),
    extraArgs: (c.get<string>("deploy.extraArgs") || "").trim(),
  };
}

// Deploy folder: the active editor's folder, the only workspace folder, or the user's pick.
async function pickFolder(): Promise<vscode.WorkspaceFolder | undefined> {
  const active = vscode.window.activeTextEditor?.document.uri;
  if (active) {
    const folder = vscode.workspace.getWorkspaceFolder(active);
    if (folder) {
      return folder;
    }
  }
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length <= 1) {
    return folders[0];
  }
  return vscode.window.showWorkspaceFolderPick();
}

// APP_ID / ELEMENT_APP_ID assignment in a .env file - the sources elemctl itself reads.
const ENV_APP_ID_RE = /^\s*(?:export\s+)?(?:ELEMENT_APP_ID|APP_ID)\s*=\s*\S/m;

function envFileHasAppId(folder: vscode.WorkspaceFolder, s: DeploySettings): boolean {
  const file = s.envFile
    ? path.isAbsolute(s.envFile) ? s.envFile : path.join(folder.uri.fsPath, s.envFile)
    : path.join(folder.uri.fsPath, ".env");
  try {
    return ENV_APP_ID_RE.test(fs.readFileSync(file, "utf8"));
  } catch {
    return false; // no file - no app id in it
  }
}

// Without an app id elemctl stops with a bare "не задан app-id" long after the confirmation.
// Ask up front instead: where to take the id from, and remember the answer in the folder
// settings so the next deploy does not ask again.
async function ensureAppId(folder: vscode.WorkspaceFolder, s: DeploySettings): Promise<boolean> {
  if (s.appId || envFileHasAppId(folder, s) || process.env.ELEMENT_APP_ID || process.env.APP_ID) {
    return true;
  }
  const value = await vscode.window.showInputBox({
    title: vscode.l10n.t("Application id for the deploy"),
    prompt: vscode.l10n.t(
      "elemctl needs the target application id (APP_ID). Take it from `elemctl apps list` or from the application card in the platform console; it will be saved to the xbsl.deploy.appId setting."
    ),
    placeHolder: "0198c0de-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    ignoreFocusOut: true,
    validateInput: (v) => (v.trim() ? undefined : vscode.l10n.t("The application id must not be empty.")),
  });
  if (value === undefined) {
    return false; // canceled - the deploy is canceled with it
  }
  s.appId = value.trim();
  await vscode.workspace
    .getConfiguration("xbsl", folder.uri)
    .update("deploy.appId", s.appId, vscode.ConfigurationTarget.WorkspaceFolder);
  return true;
}

// Quick check that elemctl exists: only ENOENT leads to the install offer,
// other problems will be shown by the task's own terminal.
function elemctlMissing(bin: string, cwd: string): Promise<boolean> {
  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(bin, ["--version"], { cwd });
    } catch (e) {
      resolve((e as NodeJS.ErrnoException)?.code === "ENOENT");
      return;
    }
    child.on("error", (e) => resolve((e as NodeJS.ErrnoException)?.code === "ENOENT"));
    child.on("close", () => resolve(false));
  });
}

// Arguments of `elemctl deploy`. --env-file is a global elemctl flag, it goes strictly BEFORE
// the subcommand. --project-dir is passed only when xbsl.projectRoot narrowed the root:
// without it elemctl searches for the project downward from the working folder itself.
function buildDeployArgs(s: DeploySettings, folder: vscode.WorkspaceFolder, projectRoot: string): string[] {
  const args: string[] = [];
  if (s.envFile) {
    const abs = path.isAbsolute(s.envFile) ? s.envFile : path.join(folder.uri.fsPath, s.envFile);
    args.push("--env-file", abs);
  }
  args.push("deploy");
  if (projectRoot !== folder.uri.fsPath) {
    args.push("--project-dir", projectRoot);
  }
  if (s.appId) {
    args.push("--app-id", s.appId);
  }
  if (s.extraArgs) {
    args.push(...s.extraArgs.split(/\s+/).filter(Boolean));
  }
  return args;
}

// Command line for showing to the user; execution goes through ShellExecution(command, args),
// where VS Code itself places the quotes by the rules of the specific shell.
function displayCommand(bin: string, args: string[]): string {
  return [bin, ...args].map((a) => (/\s/.test(a) ? `"${a}"` : a)).join(" ");
}

async function deploy(projectRootFor: (folder: vscode.WorkspaceFolder) => string): Promise<void> {
  if (vscode.tasks.taskExecutions.some((e) => e.task.name === TASK_NAME)) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: a deploy is already running."));
    return;
  }
  const folder = await pickFolder();
  if (!folder) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: no open folder to deploy."));
    return;
  }
  const settings = readDeploySettings(folder.uri);
  if (settings.envFile) {
    const abs = path.isAbsolute(settings.envFile)
      ? settings.envFile
      : path.join(folder.uri.fsPath, settings.envFile);
    if (!fs.existsSync(abs)) {
      void vscode.window.showErrorMessage(
        vscode.l10n.t('XBSL: the .env file "{0}" is not found (the xbsl.deploy.envFile setting).', abs)
      );
      return;
    }
  }
  if (await elemctlMissing(settings.bin, folder.uri.fsPath)) {
    const install = vscode.l10n.t("Install elemctl");
    const pick = await vscode.window.showErrorMessage(
      vscode.l10n.t(
        'elemctl ("{0}") not found. Install it (pip install elemctl) or set the path in the xbsl.deploy.elemctlPath setting.',
        settings.bin
      ),
      install
    );
    if (pick === install) {
      runInstallTask("elemctl", pipInstallCommand("elemctl"));
    }
    return;
  }
  if (!(await ensureAppId(folder, settings))) {
    return;
  }
  const args = buildDeployArgs(settings, folder, projectRootFor(folder));
  const confirm = vscode.l10n.t("Deploy");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t("XBSL: deploy the project to the stand?"),
    {
      modal: true,
      detail: vscode.l10n.t("Command: {0}\nFolder: {1}", displayCommand(settings.bin, args), folder.uri.fsPath),
    },
    confirm
  );
  if (pick !== confirm) {
    return;
  }
  const task = new vscode.Task(
    { type: "shell", task: TASK_NAME },
    folder,
    TASK_NAME,
    "xbsl",
    new vscode.ShellExecution(settings.bin, args, { cwd: folder.uri.fsPath })
  );
  task.presentationOptions = {
    reveal: vscode.TaskRevealKind.Always,
    panel: vscode.TaskPanelKind.Dedicated,
    clear: true,
    showReuseMessage: false,
  };
  const sub = vscode.tasks.onDidEndTaskProcess((e) => {
    if (e.execution.task.name !== TASK_NAME) {
      return;
    }
    sub.dispose();
    if (e.exitCode === 0) {
      void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: the deploy finished – the build is applied."));
    } else {
      void vscode.window.showErrorMessage(
        vscode.l10n.t("XBSL: the deploy failed (exit code {0}) – see the terminal for details.", e.exitCode ?? 1)
      );
    }
  });
  void vscode.tasks.executeTask(task);
}

export function registerDeploy(
  context: vscode.ExtensionContext,
  projectRootFor: (folder: vscode.WorkspaceFolder) => string
): void {
  context.subscriptions.push(vscode.commands.registerCommand("xbsl.deploy", () => deploy(projectRootFor)));
}
