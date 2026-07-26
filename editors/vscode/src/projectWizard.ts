// "New 1C:Element project" wizard (command xbsl.project.new): a small getting-started flow built
// from native prompts (InputBox / QuickPick, no webview). It gathers the project name, the vendor,
// the project kind and the target location, then scaffolds the project through the engine
// (meta_new_project / xbsl new-project) and opens the generated Проект.yaml. The pure input
// validation and argument assembly live in projectWizardCore (unit-tested).

import * as path from "path";
import * as vscode from "vscode";
import { applyScaffold, callMeta } from "./engineMeta";
import { buildNewProjectCall, checkProjectIdentifier, IdentifierReason } from "./projectWizardCore";

// The generated project file (the engine's PROJECT_FILE) - what the wizard opens afterwards.
const PROJECT_FILE = "Проект.yaml";
// Remembered vendor: it repeats across a developer's projects, so it prefills the next prompt.
const LAST_VENDOR_KEY = "xbsl.project.lastVendor";

function identifierMessage(reason: IdentifierReason): string {
  switch (reason) {
    case "empty":
      return vscode.l10n.t("A value is required.");
    case "yo":
      return vscode.l10n.t("The letter ё is not allowed in a project identifier.");
    case "lowercase":
      return vscode.l10n.t("The identifier must start with a capital letter.");
    case "identifier":
    default:
      return vscode.l10n.t("A valid identifier is required (letters, digits, _), starting with a capital letter.");
  }
}

// Inline validation for the InputBox (undefined = accepted).
function identifierError(raw: string): string | undefined {
  const check = checkProjectIdentifier(raw);
  return check.ok ? undefined : identifierMessage(check.reason);
}

// Prompt for a project identifier; returns the trimmed value, or undefined when cancelled. The
// InputBox will not submit a value that fails identifierError, so the result is already valid.
async function askIdentifier(prompt: string, value: string): Promise<string | undefined> {
  const raw = await vscode.window.showInputBox({
    prompt,
    value,
    ignoreFocusOut: true,
    validateInput: identifierError,
  });
  if (raw === undefined) {
    return undefined;
  }
  const check = checkProjectIdentifier(raw);
  return check.ok ? check.value : undefined;
}

// Application vs library project (the engine's library flag). Returns undefined when cancelled;
// false and true are both meaningful answers, so callers must test for undefined explicitly.
async function pickLibrary(): Promise<boolean | undefined> {
  const items: Array<vscode.QuickPickItem & { library: boolean }> = [
    {
      label: vscode.l10n.t("Application"),
      description: vscode.l10n.t("Deployed as a standalone application"),
      library: false,
    },
    {
      label: vscode.l10n.t("Library"),
      description: vscode.l10n.t("Attached to other projects via Импорт"),
      library: true,
    },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t("Project kind"),
    ignoreFocusOut: true,
  });
  return pick?.library;
}

// A folder open dialog for the parent directory of the new project.
async function browseForRoot(): Promise<string | undefined> {
  const picked = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: vscode.l10n.t("Select project location"),
  });
  return picked?.[0]?.fsPath;
}

interface RootPick extends vscode.QuickPickItem {
  dir?: string;
  browse?: boolean;
}

// Choose the parent directory that will receive <vendor>/<name>. Offers the open workspace folders
// plus a "Browse..." entry (the folder dialog). With no workspace open, goes straight to the dialog.
async function pickRoot(): Promise<string | undefined> {
  const folders = vscode.workspace.workspaceFolders ?? [];
  if (folders.length === 0) {
    return browseForRoot();
  }
  const items: RootPick[] = [
    ...folders.map((f) => ({ label: f.name, description: f.uri.fsPath, dir: f.uri.fsPath })),
    { label: vscode.l10n.t("Browse..."), browse: true },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t("Where to create the project folder"),
    ignoreFocusOut: true,
  });
  if (!pick) {
    return undefined;
  }
  return pick.browse ? browseForRoot() : pick.dir;
}

// Open the generated Проект.yaml and, when the project landed outside the open workspace, offer to
// open its folder (a fresh project is usually not yet part of the current window).
async function openProject(createdPaths: string[]): Promise<void> {
  const projectYaml = createdPaths.find((p) => path.basename(p) === PROJECT_FILE);
  if (!projectYaml) {
    return;
  }
  const uri = vscode.Uri.file(projectYaml);
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(doc, { preview: false });

  if (vscode.workspace.getWorkspaceFolder(uri)) {
    void vscode.commands.executeCommand("xbsl.metadata.refresh"); // the tree now has a new project
    return;
  }
  const projectDir = path.dirname(projectYaml);
  const open = vscode.l10n.t("Open project folder");
  const pick = await vscode.window.showInformationMessage(
    vscode.l10n.t("XBSL: the project was created in {0}.", projectDir),
    open
  );
  if (pick === open) {
    await vscode.commands.executeCommand("vscode.openFolder", vscode.Uri.file(projectDir));
  }
}

async function runWizard(context: vscode.ExtensionContext): Promise<void> {
  const name = await askIdentifier(vscode.l10n.t("Project name (identifier, capitalized)"), "");
  if (!name) {
    return;
  }
  const lastVendor = context.globalState.get<string>(LAST_VENDOR_KEY) ?? "";
  const vendor = await askIdentifier(vscode.l10n.t("Vendor (Поставщик, identifier)"), lastVendor);
  if (!vendor) {
    return;
  }
  const library = await pickLibrary();
  if (library === undefined) {
    return;
  }
  const root = await pickRoot();
  if (!root) {
    return;
  }

  const { lspParams, cliArgs } = buildNewProjectCall({ root, vendor, name, library });
  const result = await callMeta("xbsl/metaNewProject", lspParams, "new-project", cliArgs, root);
  if (!result) {
    return; // the engine is unavailable - the message is already shown by callMeta
  }
  const created = await applyScaffold(result);
  if (!created.length) {
    return; // a refusal (e.g. the project already exists) - applyScaffold reported it
  }
  await context.globalState.update(LAST_VENDOR_KEY, vendor);
  await openProject(created);
}

export function registerProjectWizard(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.project.new", () => runWizard(context))
  );
}
