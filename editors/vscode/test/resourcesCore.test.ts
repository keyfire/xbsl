// The Resources section of the metadata tree: grouping resource FILES by their owning
// Resources folder (either spelling). The key of a file is its path relative to that folder -
// the very spelling a `Ресурс{...}` reference uses, so the tree teaches the correct addressing.

import * as assert from "assert";
import { groupResources } from "../src/metadataCore";

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
    "D:\\repo\\e1c\\site\\Сайт\\Ресурсы\\Валюты\\EUR.svg",
    "D:\\repo\\e1c\\site\\Сайт\\Ресурсы\\Обновить.svg",
    "D:\\repo\\e1c\\site\\Основное\\Ресурсы\\nav-queries.svg",
  ]);
  assert.deepStrictEqual(keysOf(scopes), {
    "Основное": ["nav-queries.svg"],
    "Сайт": ["Валюты/EUR.svg", "Обновить.svg"],
  });
  assert.strictEqual(scopes[0].scope, "Основное");
  assert.ok(scopes[1].dir.endsWith("Ресурсы"));
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

console.log("resourcesCore: ok");
