// The Resources section of the metadata tree: grouping resource FILES by their owning
// Resources folder (either spelling). The key of a file is its path relative to that folder -
// the very spelling a `Ресурс{...}` reference uses, so the tree teaches the correct addressing.

import * as assert from "assert";
import { groupResources } from "../src/metadataCore";
import {
  canMoveInto,
  childPath,
  isFolderName,
  isMovableResource,
  isResourcesDescriptor,
  lastSegment,
  moveTargets,
  parentPath,
  ResourceFolder,
  resourceFolderTree,
  resourcePathOf,
} from "../src/resourceFoldersCore";

function keysOf(scopes: ReturnType<typeof groupResources>): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const scope of scopes) {
    out[scope.scope] = scope.files.map((f) => f.key);
  }
  return out;
}

// Scopes come sorted by name, files sorted by key; the key is POSIX regardless of the
// separators the walk produced.
{
  const scopes = groupResources([
    "D:\\repo\\app\\Задачи\\Ресурсы\\Значки\\Флаг.svg",
    "D:\\repo\\app\\Задачи\\Ресурсы\\Обложка.svg",
    "D:\\repo\\app\\Шаги\\Ресурсы\\schema.svg",
  ]);
  assert.deepStrictEqual(keysOf(scopes), {
    "Задачи": ["Значки/Флаг.svg", "Обложка.svg"],
    "Шаги": ["schema.svg"],
  });
  assert.strictEqual(scopes[0].scope, "Задачи");
  assert.ok(scopes[0].dir.endsWith("Ресурсы"));
}

// The English spelling of the folder is the same section.
{
  const scopes = groupResources(["/repo/app/Main/Resources/logo.png"]);
  assert.deepStrictEqual(keysOf(scopes), { Main: ["logo.png"] });
}

// A file outside any resources folder does not belong to the section.
{
  assert.deepStrictEqual(groupResources(["/repo/app/Main/Файл.svg"]), []);
}

// A nested folder named like the resources folder stays INSIDE the key: the platform
// resolves the key relative to the topmost such folder of the subsystem.
{
  const scopes = groupResources(["/repo/app/Main/Ресурсы/Ресурсы/inner.svg"]);
  assert.deepStrictEqual(keysOf(scopes), { Main: ["Ресурсы/inner.svg"] });
}

// Two subsystems with the same folder name in different branches stay separate scopes only
// when their resource DIRS differ; the scope label still reads by the owning folder.
{
  const scopes = groupResources([
    "/repo/app/Main/Ресурсы/a.svg",
    "/repo/app/Main/Ресурсы/b.svg",
  ]);
  assert.strictEqual(scopes.length, 1);
  assert.strictEqual(scopes[0].files.length, 2);
}

// --- folders (resourceFoldersCore) --------------------------------------------------------------

// The shape of a folder tree without the file paths: names, counts, files by key.
function shape(folder: ResourceFolder): unknown {
  return {
    name: folder.name,
    count: folder.count,
    files: folder.files.map((f) => f.key),
    folders: folder.folders.map(shape),
  };
}

const DIR = "D:\\repo\\app\\Задачи\\Ресурсы";
const file = (key: string) => ({ key, filePath: `${DIR}\\${key.split("/").join("\\")}` });

// The files of one resources folder become folders with their nesting: the folders sorted by name,
// the files by key, every folder counting the files under it, nested folders included.
{
  const tree = resourceFolderTree([
    file("Значки/Темные/Флаг.svg"),
    file("Обложка.svg"),
    file("Значки/Флаг.svg"),
    file("Значки/Архив.svg"),
    file("Стили/main.css"),
  ]);
  assert.deepStrictEqual(shape(tree), {
    name: "",
    count: 5,
    files: ["Обложка.svg"],
    folders: [
      {
        name: "Значки",
        count: 3,
        files: ["Значки/Архив.svg", "Значки/Флаг.svg"],
        folders: [{ name: "Темные", count: 1, files: ["Значки/Темные/Флаг.svg"], folders: [] }],
      },
      { name: "Стили", count: 1, files: ["Стили/main.css"], folders: [] },
    ],
  });
  assert.strictEqual(tree.folders[0].folders[0].path, "Значки/Темные");
  // A flat folder stays flat: no folder node appears where the files lie at the top.
  assert.deepStrictEqual(shape(resourceFolderTree([file("b.svg"), file("a.svg")])), {
    name: "", count: 2, files: ["a.svg", "b.svg"], folders: [],
  });
}

// The paths of a node: POSIX inside the key, the separators of the resources folder outside it.
{
  assert.strictEqual(parentPath("Значки/Темные/Флаг.svg"), "Значки/Темные");
  assert.strictEqual(parentPath("Флаг.svg"), "");
  assert.strictEqual(lastSegment("Значки/Темные"), "Темные");
  assert.strictEqual(childPath("", "Значки"), "Значки");
  assert.strictEqual(childPath("Значки", "Темные"), "Значки/Темные");
  assert.strictEqual(
    resourcePathOf({ dir: DIR, path: "Значки/Темные/Флаг.svg", folder: false }),
    `${DIR}\\Значки\\Темные\\Флаг.svg`
  );
  assert.strictEqual(resourcePathOf({ dir: "/repo/app/Main/Resources", path: "Icons", folder: true }),
    "/repo/app/Main/Resources/Icons");
  assert.strictEqual(resourcePathOf({ dir: DIR, path: "", folder: true }), DIR);
}

// The description of the resources is not a resource: it neither moves nor is offered to.
{
  assert.ok(isResourcesDescriptor({ dir: DIR, path: "Ресурсы.yaml", folder: false }));
  assert.ok(isResourcesDescriptor({ dir: DIR, path: "Resources.yaml", folder: false }));
  assert.ok(!isResourcesDescriptor({ dir: DIR, path: "Значки/Ресурсы.yaml", folder: false }));
  assert.ok(!isResourcesDescriptor({ dir: DIR, path: "Ресурсы.yaml", folder: true }));
  assert.ok(!isMovableResource({ dir: DIR, path: "Ресурсы.yaml", folder: false }));
  assert.ok(!isMovableResource({ dir: DIR, path: "", folder: true }));
  assert.ok(!isMovableResource(undefined));
  assert.ok(isMovableResource({ dir: DIR, path: "Значки", folder: true }));
}

// Where a resource may go: another folder of the same resources folder, never the one it lies
// in, never a folder of another resources folder, and a folder never into itself.
{
  const icon = { dir: DIR, path: "Значки/Флаг.svg", folder: false };
  const icons = { dir: DIR, path: "Значки", folder: true };
  const at = (folderPath: string, dir = DIR) => ({ dir, path: folderPath, folder: true });
  assert.ok(canMoveInto(icon, at("")));
  assert.ok(canMoveInto(icon, at("Стили")));
  assert.ok(!canMoveInto(icon, at("Значки")));
  assert.ok(!canMoveInto(icon, { dir: DIR, path: "Обложка.svg", folder: false }));
  assert.ok(!canMoveInto(icon, at("Стили", "D:\\repo\\app\\Шаги\\Ресурсы")));
  // Compared as paths: the letter case and the separators of the folder do not matter.
  assert.ok(canMoveInto(icon, at("Стили", "d:/REPO/app/Задачи/Ресурсы")));
  assert.ok(!canMoveInto(icons, at("Значки")));
  assert.ok(!canMoveInto(icons, at("Значки/Темные")));
  assert.ok(!canMoveInto(icons, at("")));
  assert.ok(canMoveInto(icons, at("Стили")));

  const tree = resourceFolderTree([
    file("Значки/Темные/Флаг.svg"), file("Значки/Флаг.svg"), file("Стили/main.css"), file("Обложка.svg"),
  ]);
  assert.deepStrictEqual(moveTargets(tree, icon), ["", "Значки/Темные", "Стили"]);
  assert.deepStrictEqual(moveTargets(tree, icons), ["Стили"]);
  assert.deepStrictEqual(moveTargets(tree, { dir: DIR, path: "Обложка.svg", folder: false }),
    ["Значки", "Значки/Темные", "Стили"]);
}

// The prompt checks one thing - a name is one segment; the engine refuses the rest.
{
  assert.ok(isFolderName("Значки"));
  assert.ok(isFolderName("  Значки "));
  assert.ok(!isFolderName(""));
  assert.ok(!isFolderName("   "));
  assert.ok(!isFolderName("Значки/Темные"));
  assert.ok(!isFolderName("Значки\\Темные"));
}

console.log("resourcesCore: ok");
