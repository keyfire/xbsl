// Unit tests for the filter core of the metadata tree (src/treeFilterCore.ts): the tree of
// checkboxes built from the engine's placement, the three states, the clicks, the test an item
// passes, and the stored choice. Plain Node asserts, bundled by esbuild. Run with `npm test` from
// editors/vscode.

import * as assert from "assert";
import { EngineProjectInfo, PackageTotal, packageTotals, pathKey, readPlacement } from "../src/packagesCore";
import {
  buildFilterTree,
  canonicalSelection,
  CheckState,
  chosenPackageTotals,
  chosenSubsystems,
  FilterNode,
  FilterTree,
  filterPredicate,
  followRenames,
  FolderPlace,
  isPlaceFilter,
  nodeStates,
  placeFilterOf,
  PlaceRename,
  placesByFolder,
  placeSelection,
  readSelection,
  renamedPlace,
  renamePlaceKeys,
  selectAll,
  selectedCount,
  Selection,
  summarize,
  toggleNode,
  touches,
  writeSelection,
} from "../src/treeFilterCore";

let failed = 0;
let passed = 0;

function test(name: string, fn: () => void): void {
  try {
    fn();
    passed++;
    console.log(`ok   ${name}`);
  } catch (e) {
    failed++;
    console.error(`FAIL ${name}`);
    console.error(e instanceof Error ? e.message : e);
  }
}

const P = "D:\\repo\\Демо\\Учет";
const PROJECT = "d:/repo/демо/учет"; // the key of the project: pathKey of its folder

// Subsystem `Склад`: an object in its root, package `Партии` with an object of its own and the
// nested package `Архив`. Subsystem `Продажи`: root objects only. Subsystem `Доставка`: listed by
// the engine, no object yet.
const ANSWER: EngineProjectInfo = {
  projects: [{ vendor: "Демо", name: "Учет", dir: P, subsystems: ["Доставка", "Продажи", "Склад"] }],
  packages: [
    { subsystem: "Склад", package: "Партии", dir: `${P}\\Склад\\Партии`, objects: 1 },
    { subsystem: "Склад", package: "Партии::Архив", dir: `${P}\\Склад\\Партии\\Архив`, objects: 1 },
  ],
  objects: [
    { kind: "ОбщийМодуль", name: "Заказы", path: `${P}\\Продажи\\Заказы.yaml`, subsystem: "Продажи", package: null, namespace: "Демо::Учет::Продажи" },
    { kind: "Справочник", name: "Клиенты", path: `${P}\\Продажи\\Клиенты.yaml`, subsystem: "Продажи", package: null, namespace: "Демо::Учет::Продажи" },
    { kind: "Справочник", name: "АрхивПартий", path: `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`, subsystem: "Склад", package: "Партии::Архив", namespace: "Демо::Учет::Склад::Партии::Архив" },
    { kind: "Справочник", name: "Номенклатура", path: `${P}\\Склад\\Номенклатура.yaml`, subsystem: "Склад", package: null, namespace: "Демо::Учет::Склад" },
    { kind: "Справочник", name: "ПартииТоваров", path: `${P}\\Склад\\Партии\\ПартииТоваров.yaml`, subsystem: "Склад", package: "Партии", namespace: "Демо::Учет::Склад::Партии" },
  ],
};

const ITEMS = (ANSWER.objects ?? []).map((o) => o.path);
const DESCRIPTORS = [
  { name: "Склад", dir: `${P}\\Склад` },
  { name: "Продажи", dir: `${P}\\Продажи` },
  // A descriptor inside a subsystem is a package with a descriptor it does not need.
  { name: "Партии", dir: `${P}\\Склад\\Партии` },
];

const projectOf = (p: string): string => (p.toLowerCase().startsWith(P.toLowerCase()) ? P : "");

function tree(withEngine = true): FilterTree {
  return buildFilterTree({
    projects: [{ dir: P, name: "Учет", title: "Демо::Учет" }],
    items: ITEMS,
    pathOf: (p) => p,
    projectOf,
    count: (items) => items.length,
    placement: withEngine ? readPlacement(ANSWER) : undefined,
    subsystems: DESCRIPTORS,
  });
}

function node(t: FilterTree, id: string): FilterNode {
  const walk = (nodes: FilterNode[]): FilterNode | undefined => {
    for (const n of nodes) {
      const found = n.id === id ? n : walk(n.children);
      if (found) {
        return found;
      }
    }
    return undefined;
  };
  const found = walk(t.projects);
  assert.ok(found, `no node ${id}`);
  return found;
}

const id = (kind: string, place: string): string => `${PROJECT}|${kind}|${place}`;
const SUB = id("subsystem", "Склад");
const BATCHES = id("package", "Склад::Партии");
const ARCHIVE = id("package", "Склад::Партии::Архив");
const BATCHES_LOOSE = id("loose", "Склад::Партии");
const STOCK_LOOSE = id("loose", "Склад");
const SALES = id("subsystem", "Продажи");

function statesOf(t: FilterTree, selection: Selection, ids: string[]): CheckState[] {
  const states = nodeStates(t, selection);
  return ids.map((n) => states.get(n) ?? "unchecked");
}

function keysOf(selection: Selection): string[] {
  return [...(selection.get(PROJECT) ?? [])].sort();
}

function passing(selection: Selection, withEngine = true): string[] {
  const passes = filterPredicate({
    selection,
    projects: [P],
    projectOf,
    placement: withEngine ? readPlacement(ANSWER) : undefined,
    subsystems: DESCRIPTORS,
  });
  assert.ok(passes, "a choice was made, the filter must be on");
  return ITEMS.filter(passes).map((p) => p.slice(P.length + 1));
}

test("the tree: subsystems, packages with the nesting, loose items only where both kinds meet", () => {
  const t = tree();
  const [project] = t.projects;
  assert.strictEqual(project.packagesKnown, true);
  assert.strictEqual(project.count, 5);
  assert.deepStrictEqual(project.children.map((n) => [n.name, n.count, n.children.length]), [
    ["Доставка", 0, 0],
    ["Продажи", 2, 0], // root objects and no package - a leaf, no loose item
    ["Склад", 3, 2],
  ]);
  assert.deepStrictEqual(node(t, SUB).children.map((n) => [n.kind, n.place, n.count]), [
    ["package", "Склад::Партии", 2],
    ["loose", "Склад", 1],
  ]);
  assert.deepStrictEqual(node(t, BATCHES).children.map((n) => [n.kind, n.place, n.count]), [
    ["package", "Склад::Партии::Архив", 1],
    ["loose", "Склад::Партии", 1],
  ]);
  assert.strictEqual(node(t, BATCHES).title, "Демо::Учет::Склад::Партии");
});

test("checking a subsystem checks everything under it", () => {
  const t = tree();
  const chosen = toggleNode(t, new Map(), SUB);
  assert.deepStrictEqual(keysOf(chosen), ["Склад::*"]);
  assert.deepStrictEqual(statesOf(t, chosen, [SUB, BATCHES, ARCHIVE, BATCHES_LOOSE, STOCK_LOOSE]), [
    "checked", "checked", "checked", "checked", "checked",
  ]);
  assert.deepStrictEqual(statesOf(t, chosen, [id("project", ""), SALES]), ["mixed", "unchecked"]);
  // Unchecking takes everything under it away again, and the project leaves the choice.
  assert.deepStrictEqual(writeSelection(toggleNode(t, chosen, SUB)), {});
});

test("an unchecked subsystem with one package checked is partial, and only that package passes", () => {
  const t = tree();
  const chosen = toggleNode(t, new Map(), ARCHIVE);
  assert.deepStrictEqual(keysOf(chosen), ["Склад::Партии::Архив::*"]);
  assert.deepStrictEqual(statesOf(t, chosen, [SUB, BATCHES, ARCHIVE, BATCHES_LOOSE, STOCK_LOOSE]), [
    "mixed", "mixed", "checked", "unchecked", "unchecked",
  ]);
  assert.deepStrictEqual(passing(chosen), ["Склад\\Партии\\Архив\\АрхивПартий.yaml"]);
  // A click on the partial subsystem checks all of it.
  assert.deepStrictEqual(keysOf(toggleNode(t, chosen, SUB)), ["Склад::*"]);
});

test("nested packages: a package takes its nested ones, unchecking one opens the whole key up", () => {
  const t = tree();
  const batches = toggleNode(t, new Map(), BATCHES);
  assert.deepStrictEqual(keysOf(batches), ["Склад::Партии::*"]);
  assert.deepStrictEqual(passing(batches), [
    "Склад\\Партии\\Архив\\АрхивПартий.yaml",
    "Склад\\Партии\\ПартииТоваров.yaml",
  ]);
  const withoutArchive = toggleNode(t, toggleNode(t, new Map(), SUB), ARCHIVE);
  assert.deepStrictEqual(keysOf(withoutArchive), ["Склад", "Склад::Партии"]);
  assert.deepStrictEqual(statesOf(t, withoutArchive, [SUB, BATCHES, ARCHIVE, BATCHES_LOOSE, STOCK_LOOSE]), [
    "mixed", "mixed", "unchecked", "checked", "checked",
  ]);
  assert.deepStrictEqual(passing(withoutArchive), ["Склад\\Номенклатура.yaml", "Склад\\Партии\\ПартииТоваров.yaml"]);
  // Checking the last unchecked node folds the keys back into the whole subsystem.
  assert.deepStrictEqual(keysOf(toggleNode(t, withoutArchive, ARCHIVE)), ["Склад::*"]);
});

test("the loose item: the root objects alone, and a place is checked only with it", () => {
  const t = tree();
  const root = toggleNode(t, new Map(), STOCK_LOOSE);
  assert.deepStrictEqual(keysOf(root), ["Склад"]);
  assert.deepStrictEqual(statesOf(t, root, [SUB, BATCHES, STOCK_LOOSE]), ["mixed", "unchecked", "checked"]);
  assert.deepStrictEqual(passing(root), ["Склад\\Номенклатура.yaml"]);
  // A resource file goes by its folder: the resources of the root pass, those of a package do not.
  const passes = filterPredicate({ selection: root, projects: [P], projectOf, placement: readPlacement(ANSWER), subsystems: [] })!;
  assert.strictEqual(passes(`${P}\\Склад\\Ресурсы\\Схема.svg`), true);
  assert.strictEqual(passes(`${P}\\Склад\\Партии\\Ресурсы\\Схема.svg`), false);
  // The package checked as well: every item of the subsystem is checked - so is the subsystem.
  const both = toggleNode(t, root, BATCHES);
  assert.deepStrictEqual(statesOf(t, both, [SUB]), ["checked"]);
  assert.deepStrictEqual(keysOf(both), ["Склад::*"]);
});

test("a key no checkbox stands for is dropped: a renamed package, a deleted subsystem", () => {
  const t = tree();
  const stored = readSelection({
    [PROJECT]: ["Склад::Лоты::*", "Удалено::*", "Продажи::*", "Склад::Партии"],
    "d:/elsewhere/проект": ["Касса::*"],
  });
  assert.deepStrictEqual(writeSelection(canonicalSelection(t, stored)), {
    "d:/elsewhere/проект": ["Касса::*"], // a project the tree does not draw keeps its choice
    [PROJECT]: ["Продажи::*", "Склад::Партии"],
  });
  // The root key of a subsystem that has no packages is its whole key.
  assert.deepStrictEqual(keysOf(canonicalSelection(t, readSelection({ [PROJECT]: ["Продажи"] }))), ["Продажи::*"]);
});

test("nothing chosen - no filter at all", () => {
  assert.strictEqual(filterPredicate({ selection: new Map(), projects: [P], projectOf, subsystems: [] }), undefined);
  // Keys of a project the tree does not draw are no choice here either.
  const elsewhere = readSelection({ "d:/elsewhere/проект": ["Касса::*"] });
  assert.strictEqual(filterPredicate({ selection: elsewhere, projects: [P], projectOf, subsystems: [] }), undefined);
  // With a choice, an item outside every subsystem does not pass.
  const passes = filterPredicate({
    selection: readSelection({ [PROJECT]: ["Продажи::*"] }), projects: [P], projectOf, placement: readPlacement(ANSWER), subsystems: [],
  })!;
  assert.strictEqual(passes(`${P}\\Продажи\\Заказы.yaml`), true);
  assert.strictEqual(passes(`${P}\\Проект.xbsl`), false);
});

test("without the engine: subsystems by descriptors, nothing dropped, a whole subsystem by folder", () => {
  const t = tree(false);
  const [project] = t.projects;
  assert.strictEqual(project.packagesKnown, false);
  assert.deepStrictEqual(project.children.map((n) => [n.name, n.count, n.children.length]), [
    ["Продажи", 2, 0],
    ["Склад", 3, 0],
  ]);
  // A package chosen while the engine answered: shown as partial, kept through a click elsewhere.
  const stored = readSelection({ [PROJECT]: ["Склад::Партии::*", "Доставка::*"] });
  assert.deepStrictEqual(statesOf(t, stored, [SUB, SALES]), ["mixed", "unchecked"]);
  const clicked = toggleNode(t, stored, SALES);
  assert.deepStrictEqual(keysOf(clicked), ["Доставка::*", "Продажи::*", "Склад::Партии::*"]);
  assert.deepStrictEqual(passing(clicked, false), ["Продажи\\Заказы.yaml", "Продажи\\Клиенты.yaml"]);
  // A click on the partial subsystem takes it whole.
  assert.deepStrictEqual(keysOf(toggleNode(t, clicked, SUB)), ["Доставка::*", "Продажи::*", "Склад::*"]);
});

test("select all, the count of the chosen objects, the nodes the grouped tree keeps", () => {
  const t = tree();
  const all = selectAll(t, new Map());
  assert.deepStrictEqual(keysOf(all), ["Доставка::*", "Продажи::*", "Склад::*"]);
  assert.strictEqual(selectedCount(t, all), 5);
  const partial = toggleNode(t, all, ARCHIVE);
  assert.strictEqual(selectedCount(t, partial), 4);
  const keys = partial.get(PROJECT)!;
  assert.deepStrictEqual(
    ["Склад", "Склад::Партии", "Склад::Партии::Архив", "Продажи"].map((place) => touches(keys, place)),
    [true, true, false, true]
  );
});

// The Subsystems branch of the grouping by classes, wired the way buildRoots wires it: the objects
// that passed the filter, their package totals, then the subsystems and packages that stay.
function branchUnder(selection: Selection): Array<[string, Array<[string, number, unknown[]]>]> {
  const placement = readPlacement(ANSWER)!;
  const keys = selection.get(PROJECT)!;
  const passes = filterPredicate({ selection, projects: [P], projectOf, placement, subsystems: DESCRIPTORS })!;
  const totals = packageTotals(ITEMS.filter(passes), (p) => p, placement, P, (items) => items.length);
  const shape = (list: PackageTotal[]): Array<[string, number, unknown[]]> =>
    list.map((total) => [total.group.name, total.objects, shape(total.children)]);
  return chosenSubsystems(placement.projects[0].subsystems, keys).map((sub) => [
    sub.name,
    shape(chosenPackageTotals(totals.get(pathKey(sub.dir)) ?? [], sub.name, keys)),
  ]);
}

test("the Subsystems branch under a filter by one package: that package under its subsystem, the rest hidden", () => {
  const t = tree();
  // The nested package alone: its subsystem and the enclosing package stay as the way to it.
  assert.deepStrictEqual(branchUnder(toggleNode(t, new Map(), ARCHIVE)), [
    ["Склад", [["Партии", 1, [["Архив", 1, []]]]]],
  ]);
  // The objects of the enclosing package alone: the nested package, unchecked, goes.
  assert.deepStrictEqual(branchUnder(toggleNode(t, new Map(), BATCHES_LOOSE)), [
    ["Склад", [["Партии", 1, []]]],
  ]);
  // The root objects of a subsystem alone: the subsystem stays, none of its packages does.
  assert.deepStrictEqual(branchUnder(toggleNode(t, new Map(), STOCK_LOOSE)), [["Склад", []]]);
  // A whole subsystem keeps all of its packages with their full numbers.
  assert.deepStrictEqual(branchUnder(toggleNode(t, new Map(), SUB)), [
    ["Склад", [["Партии", 2, [["Архив", 1, []]]]]],
  ]);
});

test("the Subsystems branch without the engine: a descriptor inside a subsystem goes with that subsystem", () => {
  const whole = readSelection({ [PROJECT]: ["Склад::*"] }).get(PROJECT)!;
  assert.deepStrictEqual(chosenSubsystems(DESCRIPTORS, whole).map((s) => s.name), ["Склад", "Партии"]);
  const sales = readSelection({ [PROJECT]: ["Продажи::*"] }).get(PROJECT)!;
  assert.deepStrictEqual(chosenSubsystems(DESCRIPTORS, sales).map((s) => s.name), ["Продажи"]);
  // The descriptor has no checkbox of its own: its name alone keeps nothing.
  assert.deepStrictEqual(chosenSubsystems(DESCRIPTORS, new Set(["Партии::*"])), []);
});

test("filtering by one node: a subsystem whole, a package with its nested packages", () => {
  const t = tree();
  const stock = placeSelection(PROJECT, "Склад");
  assert.deepStrictEqual(keysOf(stock), ["Склад::*"]);
  assert.deepStrictEqual(statesOf(t, stock, [SUB, BATCHES, ARCHIVE, BATCHES_LOOSE, STOCK_LOOSE, SALES]), [
    "checked", "checked", "checked", "checked", "checked", "unchecked",
  ]);
  const batches = placeSelection(PROJECT, "Склад::Партии");
  assert.deepStrictEqual(passing(batches), [
    "Склад\\Партии\\Архив\\АрхивПартий.yaml",
    "Склад\\Партии\\ПартииТоваров.yaml",
  ]);
  // The form writes the very same choice: stored, it is not rewritten.
  assert.deepStrictEqual(writeSelection(canonicalSelection(t, batches)), writeSelection(batches));
});

test("the filter is exactly one node: by that node's own button or by the same checkboxes in the form", () => {
  const t = tree();
  const only = (selection: Selection): string[] | undefined => {
    const filter = placeFilterOf(t, selection);
    return filter && [filter.project, ...[...filter.places].sort()];
  };
  assert.deepStrictEqual(only(placeSelection(PROJECT, "Склад::Партии")), [PROJECT, "Склад::Партии"]);
  assert.deepStrictEqual(only(placeSelection(PROJECT, "Склад")), [PROJECT, "Склад"]);
  // Checking the nested package and the objects of the package one by one is the same filter.
  assert.deepStrictEqual(only(toggleNode(t, toggleNode(t, new Map(), ARCHIVE), BATCHES_LOOSE)), [PROJECT, "Склад::Партии"]);
  // Two places, the root objects of a subsystem alone, nothing at all - no node is the filter.
  assert.strictEqual(only(toggleNode(t, placeSelection(PROJECT, "Склад::Партии"), SALES)), undefined);
  assert.strictEqual(only(toggleNode(t, new Map(), STOCK_LOOSE)), undefined);
  assert.strictEqual(only(new Map()), undefined);
  const archive: FolderPlace = { project: PROJECT, place: "Склад::Партии::Архив", kind: "package" };
  assert.strictEqual(isPlaceFilter(placeFilterOf(t, placeSelection(PROJECT, "Склад::Партии::Архив")), archive), true);
  assert.strictEqual(isPlaceFilter(placeFilterOf(t, placeSelection(PROJECT, "Склад::Партии")), archive), false);
  assert.strictEqual(isPlaceFilter(undefined, archive), false);
});

test("a subsystem whose only item is one package: the filter by either is the filter by both", () => {
  const Q = "D:\\repo\\Демо\\Доставка";
  const answer: EngineProjectInfo = {
    projects: [{ vendor: "Демо", name: "Доставка", dir: Q, subsystems: ["Логистика"] }],
    packages: [{ subsystem: "Логистика", package: "Маршруты", dir: `${Q}\\Логистика\\Маршруты`, objects: 1 }],
    objects: [
      { kind: "Справочник", name: "Маршруты", path: `${Q}\\Логистика\\Маршруты\\Маршруты.yaml`, subsystem: "Логистика", package: "Маршруты", namespace: "Демо::Доставка::Логистика::Маршруты" },
    ],
  };
  const lone = buildFilterTree({
    projects: [{ dir: Q, name: "Доставка" }],
    items: (answer.objects ?? []).map((o) => o.path),
    pathOf: (p) => p,
    projectOf: () => Q,
    count: (items) => items.length,
    placement: readPlacement(answer),
    subsystems: [],
  });
  const project = pathKey(Q);
  const filter = placeFilterOf(lone, placeSelection(project, "Логистика::Маршруты"))!;
  assert.deepStrictEqual([...filter.places].sort(), ["Логистика", "Логистика::Маршруты"]);
  assert.deepStrictEqual([...placeFilterOf(lone, placeSelection(project, "Логистика"))!.places].sort(), [
    "Логистика", "Логистика::Маршруты",
  ]);
});

test("the nodes that can filter: the places of the form by their folders, none for a nested descriptor", () => {
  const places = placesByFolder(tree());
  assert.deepStrictEqual(places.get(pathKey(`${P}\\Склад`)), { project: PROJECT, place: "Склад", kind: "subsystem" });
  assert.deepStrictEqual(places.get(pathKey("d:/REPO/Демо/Учет/Склад/Партии/Архив/")), {
    project: PROJECT, place: "Склад::Партии::Архив", kind: "package",
  });
  assert.strictEqual(places.size, 5); // three subsystems, two packages
  const described = placesByFolder(tree(false));
  assert.deepStrictEqual([...described.values()].map((p) => p.place).sort(), ["Продажи", "Склад"]);
  assert.strictEqual(described.get(pathKey(`${P}\\Склад\\Партии`)), undefined);
});

test("the label of a project: partial subsystems marked, the rest counted", () => {
  const keys = new Set(["Склад::Партии::*", "Продажи::*", "Доставка::*", "Касса", "Отчеты::*"]);
  assert.deepStrictEqual(summarize(keys), {
    items: [
      { name: "Доставка", partial: false },
      { name: "Касса", partial: true },
      { name: "Отчеты", partial: false },
    ],
    more: 2,
  });
  assert.deepStrictEqual(summarize(new Set(["Склад"])).items, [{ name: "Склад", partial: true }]);
});

// --- a package renamed by the command of the tree -------------------------------------------

// The engine's answer after "Rename package" turned `Склад::Партии` into `Склад::Лоты`: the folder
// moved with its nested package and the objects of both.
const moveFolder = (p: string): string => p.replace(`${P}\\Склад\\Партии`, `${P}\\Склад\\Лоты`);
const RENAMED: EngineProjectInfo = {
  projects: ANSWER.projects,
  packages: (ANSWER.packages ?? []).map((pkg) => ({ ...pkg, package: pkg.package.replace(/^Партии/, "Лоты"), dir: moveFolder(pkg.dir) })),
  objects: (ANSWER.objects ?? []).map((o) => ({
    ...o,
    path: moveFolder(o.path),
    package: o.package ? o.package.replace(/^Партии/, "Лоты") : o.package,
    namespace: o.namespace?.replace("Склад::Партии", "Склад::Лоты"),
  })),
};
// The answer after the package was deleted instead.
const DELETED: EngineProjectInfo = {
  projects: ANSWER.projects,
  packages: [],
  objects: (ANSWER.objects ?? []).filter((o) => !o.package),
};

function treeOf(answer: EngineProjectInfo): FilterTree {
  return buildFilterTree({
    projects: [{ dir: P, name: "Учет", title: "Демо::Учет" }],
    items: (answer.objects ?? []).map((o) => o.path),
    pathOf: (p) => p,
    projectOf,
    count: (items) => items.length,
    placement: readPlacement(answer),
    subsystems: DESCRIPTORS,
  });
}

const TO_LOTS: PlaceRename = { project: PROJECT, from: "Склад::Партии", to: "Склад::Лоты" };

test("the key of a renamed place: the last segment replaced", () => {
  assert.strictEqual(renamedPlace("Склад::Партии", "Лоты"), "Склад::Лоты");
  assert.strictEqual(renamedPlace("Склад::Партии::Архив", "Старое"), "Склад::Партии::Старое");
  assert.strictEqual(renamedPlace("Склад", "Запасы"), "Запасы");
});

test("renaming moves the keys of the place: its objects, its whole key, its nested packages", () => {
  const stored = readSelection({
    [PROJECT]: ["Склад::Партии", "Склад::Партии::Архив::*", "Склад::ПартииПоставщиков::*", "Продажи::*", "Склад"],
    "d:/elsewhere/проект": ["Склад::Партии::*"],
  });
  assert.deepStrictEqual(writeSelection(renamePlaceKeys(stored, TO_LOTS)), {
    "d:/elsewhere/проект": ["Склад::Партии::*"], // another project keeps its own package of that name
    [PROJECT]: ["Продажи::*", "Склад", "Склад::Лоты", "Склад::Лоты::Архив::*", "Склад::ПартииПоставщиков::*"],
  });
  assert.deepStrictEqual(keysOf(stored).includes("Склад::Партии"), true, "the given choice is not changed in place");
  // A nested package renamed: the enclosing package keeps its keys.
  const nested = readSelection({ [PROJECT]: ["Склад::Партии", "Склад::Партии::Архив::*"] });
  assert.deepStrictEqual(
    keysOf(renamePlaceKeys(nested, { project: PROJECT, from: "Склад::Партии::Архив", to: "Склад::Партии::Старое" })),
    ["Склад::Партии", "Склад::Партии::Старое::*"]
  );
  // Nothing of the place chosen: the same choice comes back.
  const other = readSelection({ [PROJECT]: ["Продажи::*"] });
  assert.strictEqual(renamePlaceKeys(other, TO_LOTS), other);
});

test("the filter by a renamed package survives the answer that shows the new name", () => {
  const byPackage = placeSelection(PROJECT, "Склад::Партии");
  // The answer before the rename still lists the old package: the keys stay, the rename waits.
  const early = followRenames(tree(), byPackage, [TO_LOTS]);
  assert.strictEqual(early.selection, byPackage);
  assert.deepStrictEqual([early.followed, early.waiting], [[], [TO_LOTS]]);
  // The answer with the new name. Read against it as they are, the keys name no checkbox: the
  // canonical form drops them, and the filter by that one package switches off.
  const renamed = treeOf(RENAMED);
  assert.deepStrictEqual(writeSelection(canonicalSelection(renamed, byPackage)), {});
  const moved = followRenames(renamed, byPackage, [TO_LOTS]);
  assert.deepStrictEqual([moved.followed, moved.waiting], [[TO_LOTS], []]);
  assert.deepStrictEqual(keysOf(moved.selection), ["Склад::Лоты::*"]);
  assert.deepStrictEqual(writeSelection(canonicalSelection(renamed, moved.selection)), writeSelection(moved.selection));
  // The filter lets the objects of the renamed package through, the nested package included, and
  // the renamed node is the one whose button clears the filter.
  const passes = filterPredicate({ selection: moved.selection, projects: [P], projectOf, placement: readPlacement(RENAMED), subsystems: [] })!;
  assert.deepStrictEqual((RENAMED.objects ?? []).map((o) => o.path).filter(passes).map((p) => p.slice(P.length + 1)), [
    "Склад\\Лоты\\Архив\\АрхивПартий.yaml",
    "Склад\\Лоты\\ПартииТоваров.yaml",
  ]);
  assert.deepStrictEqual([...placeFilterOf(renamed, moved.selection)!.places], ["Склад::Лоты"]);
});

test("a rename no answer can confirm: forgotten when the package is gone, kept while nothing is known", () => {
  const byPackage = placeSelection(PROJECT, "Склад::Партии");
  // Deleted before the answer came: the tree lists neither name, so the rename is forgotten and the
  // keys leave with the canonical form, like those of any deleted package.
  const deleted = followRenames(treeOf(DELETED), byPackage, [TO_LOTS]);
  assert.deepStrictEqual([deleted.followed, deleted.waiting], [[], []]);
  assert.strictEqual(deleted.selection, byPackage);
  // Without the engine the tree knows no packages at all: the rename waits for an answer.
  assert.deepStrictEqual(followRenames(tree(false), byPackage, [TO_LOTS]).waiting, [TO_LOTS]);
  // A project the tree does not draw waits as well.
  const elsewhere: PlaceRename = { project: "d:/elsewhere/проект", from: "Касса::Смены", to: "Касса::Сессии" };
  assert.deepStrictEqual(followRenames(treeOf(RENAMED), byPackage, [elsewhere]).waiting, [elsewhere]);
});

test("the stored choice: malformed values read as nothing, the keys come back sorted", () => {
  assert.strictEqual(readSelection(undefined).size, 0);
  assert.strictEqual(readSelection(["Склад::*"]).size, 0);
  assert.deepStrictEqual(writeSelection(readSelection({ a: "Склад::*", b: [1, "", "Продажи::*", "Склад"] })), {
    b: ["Продажи::*", "Склад"],
  });
});

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
