// The Resources section of the metadata tree as folders - the pure half, no vscode (node tests
// run it; the nodes live in metadataTree.ts, the commands in resourceFolders.ts).
//
// A resource key is a path under the Resources folder of a subsystem or a package
// (`Styles/main.css`), and the folders in it are the author's grouping. The section draws that
// grouping instead of a flat list of keys: a node per folder with its nesting and the number of
// files under it. Every write that changes a key - a move, a rename, a deletion - is the engine's
// (scaffold.op_move_resource and its two neighbours): the keys naming the files are rewritten
// there, never here. This module only decides what the tree shows and offers.

import { RESOURCE_DIR_NAMES, ResourceFile } from "./metadataCore";
import { joinDir, pathKey } from "./packagesCore";

export interface ResourceFolder {
  name: string; // the last segment of the path; "" for the resources folder itself
  path: string; // POSIX, relative to the resources folder; "" for the folder itself
  folders: ResourceFolder[]; // sorted by name
  files: ResourceFile[]; // the files lying right in this folder, sorted by key
  count: number; // the files here and in every nested folder
}

const byText = (a: string, b: string): number => a.localeCompare(b, "ru");

/** Arrange the files of ONE resources folder into its folders.
 *
 * A folder exists in the tree while a file lies under it: an empty folder is not kept by git nor
 * packed into a build, and the tree is drawn from the files. The description of a folder is the
 * number of files under it, nested folders included - the way a package counts its objects.
 */
export function resourceFolderTree(files: ResourceFile[]): ResourceFolder {
  const root: ResourceFolder = { name: "", path: "", folders: [], files: [], count: 0 };
  const byPath = new Map<string, ResourceFolder>([["", root]]);
  const folderAt = (folderPath: string): ResourceFolder => {
    const known = byPath.get(folderPath);
    if (known) {
      return known;
    }
    const cut = folderPath.lastIndexOf("/");
    const parent = folderAt(cut < 0 ? "" : folderPath.slice(0, cut));
    const created: ResourceFolder = {
      name: folderPath.slice(cut + 1), path: folderPath, folders: [], files: [], count: 0,
    };
    parent.folders.push(created);
    byPath.set(folderPath, created);
    return created;
  };
  for (const file of files) {
    folderAt(parentPath(file.key)).files.push(file);
  }
  const settle = (folder: ResourceFolder): number => {
    folder.folders.sort((a, b) => byText(a.name, b.name));
    folder.files.sort((a, b) => byText(a.key, b.key));
    folder.count = folder.files.length + folder.folders.reduce((sum, nested) => sum + settle(nested), 0);
    return folder.count;
  };
  settle(root);
  return root;
}

// What a node of the section stands for: the resources folder itself, a folder in it or a file.
export interface ResourceRef {
  dir: string; // the resources folder, in the separators of the tree's paths
  path: string; // "" - the folder itself; "Styles" - a folder in it; "Styles/main.css" - a file
  folder: boolean;
}

// The folder a key or a folder path lies in: `Styles/Dark/main.css` -> `Styles/Dark`, `a.svg` -> "".
export function parentPath(resourcePath: string): string {
  const cut = resourcePath.lastIndexOf("/");
  return cut < 0 ? "" : resourcePath.slice(0, cut);
}

export function lastSegment(resourcePath: string): string {
  return resourcePath.slice(resourcePath.lastIndexOf("/") + 1);
}

// A path under a folder: `Styles` + `Dark` -> `Styles/Dark`, the resources folder + `Dark` -> `Dark`.
export function childPath(folderPath: string, name: string): string {
  return folderPath ? `${folderPath}/${name}` : name;
}

// The file system path a node stands for.
export function resourcePathOf(ref: ResourceRef): string {
  return ref.path ? ref.path.split("/").reduce(joinDir, ref.dir) : ref.dir;
}

// The description of the resources (`Resources/Resources.yaml`, either spelling) sets the
// visibility of the whole folder: it is not a resource, and it stays where it is.
export function isResourcesDescriptor(ref: ResourceRef): boolean {
  if (ref.folder || ref.path.includes("/") || !ref.path.toLowerCase().endsWith(".yaml")) {
    return false;
  }
  return RESOURCE_DIR_NAMES.includes(ref.path.slice(0, -".yaml".length));
}

// A node that "Move to folder" and a drag may carry: a file or a folder inside the resources
// folder, the description excepted.
export function isMovableResource(ref: ResourceRef | undefined): ref is ResourceRef {
  return !!ref && ref.path !== "" && !isResourcesDescriptor(ref);
}

/** Whether a resource may land in a folder: the same resources folder, a folder that is not the
 * one it lies in already, and - for a folder - neither the folder itself nor a folder inside it.
 *
 * A folder of ANOTHER resources folder is not a place a resource moves to (the engine refuses it
 * with its reason), so it is not offered either.
 */
export function canMoveInto(source: ResourceRef, target: ResourceRef): boolean {
  if (!target.folder || !isMovableResource(source) || pathKey(source.dir) !== pathKey(target.dir)) {
    return false;
  }
  if (parentPath(source.path) === target.path) {
    return false;
  }
  return !source.folder || (target.path !== source.path && !target.path.startsWith(source.path + "/"));
}

// The folders "Move to folder" offers for a resource: the resources folder itself first, then
// every folder of the tree in its order, those the resource cannot move into left out.
export function moveTargets(tree: ResourceFolder, source: ResourceRef): string[] {
  const out: string[] = [];
  const visit = (folder: ResourceFolder): void => {
    if (canMoveInto(source, { dir: source.dir, path: folder.path, folder: true })) {
      out.push(folder.path);
    }
    folder.folders.forEach(visit);
  };
  visit(tree);
  return out;
}

// The one check the name prompt makes itself - a name is one segment. Everything else about a
// name (the characters a key cannot carry, a taken name) is the engine's to refuse.
export function isFolderName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed !== "" && !/[\\/]/.test(trimmed);
}
