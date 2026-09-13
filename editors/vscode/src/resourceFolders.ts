// The folders of resources in the metadata tree: the commands of the section and the drop of a
// resource onto a folder. A thin client of the engine: a move, a rename and a deletion are
// computed there (xbsl/metaMoveResource, xbsl/metaRenameResourceFolder,
// xbsl/metaDeleteResourceFolder, or the CLI twins) together with every key they rewrite, and
// applied here through one WorkspaceEdit (engineMeta.applyScaffold).
//
// The one write of its own is "Add resource files": it copies the files the user picked into a
// folder. Nothing in the sources names a file before it is there, so there is no key to rewrite
// and nothing for the engine to compute.

import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { applyScaffold, callMeta, ensureSourcesSavedForCli, ScaffoldResult } from "./engineMeta";
import { ResourceFile } from "./metadataCore";
import { pathKey } from "./packagesCore";
import {
  canMoveInto,
  childPath,
  isFolderName,
  isMovableResource,
  isResourcesDescriptor,
  lastSegment,
  moveTargets,
  ResourceFolder,
  ResourceRef,
  resourceFolderTree,
  resourcePathOf,
} from "./resourceFoldersCore";

// A tree node as this module sees it: what it stands for, and its label for a prompt.
export interface ResourceNodeLike {
  resource?: ResourceRef;
  label?: string | vscode.TreeItemLabel;
}

// What the commands need from the tree (metadataTree.ts hands it over).
export interface ResourceTreeAccess {
  rootFor(fsPath: string): string | undefined; // the root the engine looks for references under
  refresh(): void;
  requestReveal(pred: (node: ResourceNodeLike) => boolean): void;
}

// The files of a resources folder as they lie on disk: the "Move resources" pick and the move
// targets are read fresh rather than from a tree drawn a moment ago.
async function resourceFilesOf(dir: string): Promise<ResourceFile[]> {
  const files: ResourceFile[] = [];
  const walk = async (folder: string, prefix: string): Promise<void> => {
    let entries: fs.Dirent[];
    try {
      entries = await fs.promises.readdir(folder, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.name.startsWith(".")) {
        continue;
      }
      const key = childPath(prefix, entry.name);
      const full = path.join(folder, entry.name);
      if (entry.isDirectory()) {
        await walk(full, key);
      } else if (entry.isFile()) {
        files.push({ key, filePath: full });
      }
    }
  };
  await walk(dir, "");
  return files;
}

async function askFolderName(prompt: string, value = ""): Promise<string | undefined> {
  const name = await vscode.window.showInputBox({
    prompt,
    value,
    validateInput: (text) =>
      isFolderName(text) ? undefined : vscode.l10n.t("A folder name is one name, without path separators."),
  });
  return name?.trim() || undefined;
}

const revealPath = (fsPath: string) => (node: ResourceNodeLike): boolean =>
  !!node.resource && pathKey(resourcePathOf(node.resource)) === pathKey(fsPath);

// Apply what the engine computed and show where it landed.
async function applyAndReveal(access: ResourceTreeAccess, result: ScaffoldResult, landed?: string): Promise<boolean> {
  const applied = await applyScaffold(result);
  if (!applied.length && result.error) {
    return false;
  }
  if (landed) {
    access.requestReveal(revealPath(landed));
  } else {
    access.refresh();
  }
  return true;
}

// Every resource to the target folder, one engine call each: a move reads the whole project,
// and the next one has to see the files where the previous one put them.
async function moveResources(access: ResourceTreeAccess, refs: ResourceRef[], targetDir: string): Promise<void> {
  if (!(await ensureSourcesSavedForCli())) {
    return;
  }
  for (const ref of refs) {
    const resourcePath = resourcePathOf(ref);
    const root = access.rootFor(resourcePath);
    if (!root) {
      continue;
    }
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: vscode.l10n.t("XBSL: moving {0}...", ref.path) },
      () => callMeta(
        "xbsl/metaMoveResource", { root, path: resourcePath, targetDir },
        "move-resource", [root, resourcePath, targetDir]
      )
    );
    if (!result || !(await applyAndReveal(access, result, path.join(targetDir, lastSegment(ref.path))))) {
      return;
    }
  }
}

// "Create folder" on the resources folder or on a folder in it. An empty folder is not kept -
// git does not track one and a build packs files only - so the folder is born with its first
// files, the way "Create package" goes on to the first object: resources of this folder moved
// into it, or files added from disk.
async function createFolder(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  const parent = node?.resource;
  if (!parent?.folder) {
    return;
  }
  const name = await askFolderName(vscode.l10n.t("Name of the new resource folder"));
  if (!name) {
    return;
  }
  const folderPath = childPath(parent.path, name);
  const target = resourcePathOf({ dir: parent.dir, path: folderPath, folder: true });
  if (fs.existsSync(target)) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the folder {0} already exists.", target));
    return;
  }
  const files = (await resourceFilesOf(parent.dir)).filter(
    (file) => !isResourcesDescriptor({ dir: parent.dir, path: file.key, folder: false })
  );
  const move = { label: `$(arrow-right) ${vscode.l10n.t("Move resources into it...")}`, add: false };
  const add = { label: `$(add) ${vscode.l10n.t("Add files from disk...")}`, add: true };
  const pick = await vscode.window.showQuickPick(files.length ? [move, add] : [add], {
    placeHolder: vscode.l10n.t("An empty folder is not kept: what goes into {0} first?", folderPath),
  });
  if (!pick) {
    return;
  }
  if (pick.add) {
    await addFilesTo(access, target);
    return;
  }
  const chosen = await vscode.window.showQuickPick(
    files.map((file) => ({ label: file.key, key: file.key })),
    { canPickMany: true, placeHolder: vscode.l10n.t("Resources to move into {0}", folderPath) }
  );
  if (chosen?.length) {
    await moveResources(access, chosen.map((c) => ({ dir: parent.dir, path: c.key, folder: false })), target);
  }
}

// "Add resource files": the picked files are copied into the folder under their own names.
async function addFilesTo(access: ResourceTreeAccess, targetDir: string): Promise<void> {
  const picked = await vscode.window.showOpenDialog({
    canSelectMany: true,
    openLabel: vscode.l10n.t("Add to resources"),
  });
  if (!picked?.length) {
    return;
  }
  const names = picked.map((uri) => path.basename(uri.fsPath));
  const taken = names.filter(
    (name, index) => fs.existsSync(path.join(targetDir, name)) || names.indexOf(name) !== index
  );
  if (taken.length) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("XBSL: the name {0} is taken in {1} - nothing was added.", taken.join(", "), targetDir)
    );
    return;
  }
  const edit = new vscode.WorkspaceEdit();
  for (const uri of picked) {
    edit.createFile(vscode.Uri.file(path.join(targetDir, path.basename(uri.fsPath))), {
      contents: await vscode.workspace.fs.readFile(uri),
    });
  }
  if (!(await vscode.workspace.applyEdit(edit))) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the editor did not apply the changes."));
    return;
  }
  access.requestReveal(revealPath(path.join(targetDir, names[0])));
}

async function addFiles(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  if (node?.resource?.folder) {
    await addFilesTo(access, resourcePathOf(node.resource));
  }
}

// "Move to folder": the folders of the same resources folder the resource may move into, and a
// new folder under any of them.
async function moveToFolder(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  const source = node?.resource;
  if (!isMovableResource(source)) {
    return;
  }
  const tree = resourceFolderTree(await resourceFilesOf(source.dir));
  const rootLabel = vscode.l10n.t("(the Resources folder)");
  const targets = moveTargets(tree, source);
  interface Target extends vscode.QuickPickItem {
    folderPath?: string;
    newFolder?: boolean;
  }
  const items: Target[] = [
    ...targets.map((folderPath) => ({ label: folderPath || rootLabel, folderPath })),
    { label: `$(new-folder) ${vscode.l10n.t("New folder...")}`, newFolder: true },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t("Where to move {0}", source.path),
  });
  if (!pick) {
    return;
  }
  let folderPath = pick.folderPath;
  if (pick.newFolder) {
    // Any folder may hold the new one - the one the resource lies in included.
    const parents = [""];
    const visit = (folder: ResourceFolder): void => {
      if (folder.path && !(source.folder && (folder.path === source.path || folder.path.startsWith(source.path + "/")))) {
        parents.push(folder.path);
      }
      folder.folders.forEach(visit);
    };
    visit(tree);
    const parent = await vscode.window.showQuickPick(
      parents.map((p) => ({ label: p || rootLabel, folderPath: p })),
      { placeHolder: vscode.l10n.t("Where the new folder goes") }
    );
    if (!parent) {
      return;
    }
    const name = await askFolderName(vscode.l10n.t("Name of the new resource folder"));
    if (!name) {
      return;
    }
    folderPath = childPath(parent.folderPath, name);
  }
  if (folderPath !== undefined) {
    await moveResources(access, [source], resourcePathOf({ dir: source.dir, path: folderPath, folder: true }));
  }
}

// "Rename folder": the engine renames the files and every key naming them.
async function renameFolder(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  const folder = node?.resource;
  if (!folder?.folder || !folder.path) {
    return;
  }
  const current = lastSegment(folder.path);
  const name = await askFolderName(vscode.l10n.t("New name of the resource folder {0}", folder.path), current);
  if (!name || name === current) {
    return;
  }
  const folderDir = resourcePathOf(folder);
  const root = access.rootFor(folderDir);
  if (!root || !(await ensureSourcesSavedForCli())) {
    return;
  }
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: vscode.l10n.t("XBSL: renaming the resource folder {0}...", folder.path) },
    () => callMeta(
      "xbsl/metaRenameResourceFolder", { root, folderDir, newName: name },
      "rename-resource-folder", [root, folderDir, name]
    )
  );
  if (result) {
    await applyAndReveal(access, result, path.join(path.dirname(folderDir), name));
  }
}

// "Delete folder": the engine's plan first - the files and every place that names them - shown
// in a confirmation, then applied as it was shown.
async function deleteFolder(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  const folder = node?.resource;
  if (!folder?.folder || !folder.path) {
    return;
  }
  const folderDir = resourcePathOf(folder);
  const root = access.rootFor(folderDir);
  if (!root || !(await ensureSourcesSavedForCli())) {
    return;
  }
  const plan = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: vscode.l10n.t("XBSL: looking for what names {0}...", folder.path) },
    () => callMeta(
      "xbsl/metaDeleteResourceFolder", { root, folderDir },
      "delete-resource-folder", [root, folderDir]
    )
  );
  if (!plan) {
    return;
  }
  if (plan.error) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", plan.error));
    return;
  }
  const del = vscode.l10n.t("Delete");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t(
      "XBSL: delete the resource folder {0} with its files ({1})? The places that name them are listed below and are not edited.",
      folder.path, String(plan.deletes?.length ?? 0)
    ),
    { modal: true, detail: (plan.notes ?? []).join("\n") },
    del
  );
  if (pick !== del) {
    return;
  }
  // The notes were read in the confirmation: applying does not repeat them one popup each.
  await applyAndReveal(access, { ...plan, notes: [] });
}

/** The drop of resources onto a folder of the section. False - the drag carried no resource, the
 * object move goes on. A drop is easy to make by accident and a move edits files across the
 * project, so it is confirmed first, the way an object move is. */
export async function dropResources(
  access: ResourceTreeAccess, dragged: ResourceNodeLike[], target: ResourceNodeLike | undefined
): Promise<boolean> {
  const sources = dragged.filter((node) => isMovableResource(node.resource));
  if (!sources.length) {
    return false;
  }
  const destination = target?.resource;
  if (!destination?.folder) {
    return true;
  }
  // A folder of another resources folder is not a place to move to: the engine says why.
  const moving = sources.filter(
    (node) => pathKey(node.resource!.dir) !== pathKey(destination.dir) || canMoveInto(node.resource!, destination)
  );
  if (!moving.length) {
    return true;
  }
  const move = vscode.l10n.t("Move");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t(
      "XBSL: move {0} to {1}? The resource keys that name the files are updated across the project.",
      moving.map((node) => node.resource!.path).join(", "),
      destination.path || vscode.l10n.t("(the Resources folder)")
    ),
    { modal: true },
    move
  );
  if (pick === move) {
    await moveResources(access, moving.map((node) => node.resource!), resourcePathOf(destination));
  }
  return true;
}

export function registerResourceFolderCommands(context: vscode.ExtensionContext, access: ResourceTreeAccess): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.metadata.addResourceFolder", (n?: ResourceNodeLike) => createFolder(access, n)),
    vscode.commands.registerCommand("xbsl.metadata.addResourceFiles", (n?: ResourceNodeLike) => addFiles(access, n)),
    vscode.commands.registerCommand("xbsl.metadata.moveResource", (n?: ResourceNodeLike) => moveToFolder(access, n)),
    vscode.commands.registerCommand("xbsl.metadata.renameResourceFolder", (n?: ResourceNodeLike) => renameFolder(access, n)),
    vscode.commands.registerCommand("xbsl.metadata.deleteResourceFolder", (n?: ResourceNodeLike) => deleteFolder(access, n))
  );
}
