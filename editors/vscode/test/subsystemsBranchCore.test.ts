// Unit tests for the packages the Subsystems branch hangs under a subsystem
// (packagesCore.packageTotals): the nesting of the engine's packages and the number of objects
// each one shows. Plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  EnginePlacement,
  EngineProjectInfo,
  PackageGroup,
  PackageTotal,
  packageTotals,
  pathKey,
  readPlacement,
} from "../src/packagesCore";

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

// Subsystem `Склад`: a root object, package `Партии` with two objects and a nested `Архив` with
// one; `Продажи` - a root object and no packages; `Доставка` - listed, no object yet.
const ANSWER: EngineProjectInfo = {
  projects: [{ vendor: "Демо", name: "Учет", dir: P, subsystems: ["Доставка", "Продажи", "Склад"] }],
  packages: [
    { subsystem: "Склад", package: "Партии", dir: `${P}\\Склад\\Партии`, objects: 2 },
    { subsystem: "Склад", package: "Партии::Архив", dir: `${P}\\Склад\\Партии\\Архив`, objects: 1 },
  ],
  objects: [
    { kind: "ОбщийМодуль", name: "Заказы", path: `${P}\\Продажи\\Заказы.yaml`, subsystem: "Продажи", package: null, namespace: "Демо::Учет::Продажи" },
    { kind: "Справочник", name: "АрхивПартий", path: `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`, subsystem: "Склад", package: "Партии::Архив", namespace: "Демо::Учет::Склад::Партии::Архив" },
    { kind: "Справочник", name: "Номенклатура", path: `${P}\\Склад\\Номенклатура.yaml`, subsystem: "Склад", package: null, namespace: "Демо::Учет::Склад" },
    { kind: "Справочник", name: "ПартииТоваров", path: `${P}\\Склад\\Партии\\ПартииТоваров.yaml`, subsystem: "Склад", package: "Партии", namespace: "Демо::Учет::Склад::Партии" },
    { kind: "КомпонентИнтерфейса", name: "ПартииТоваровФормаСписка", path: `${P}\\Склад\\Партии\\ПартииТоваровФормаСписка.yaml`, subsystem: "Склад", package: "Партии", namespace: "Демо::Учет::Склад::Партии" },
  ],
};

const ITEMS = [
  `${P}\\Склад\\Номенклатура.yaml`,
  `${P}\\Склад\\Партии\\ПартииТоваров.yaml`,
  `${P}\\Склад\\Партии\\ПартииТоваровФормаСписка.yaml`,
  `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`,
  `${P}\\Продажи\\Заказы.yaml`,
  // Created after the answer was given: placed by its folder, like the grouping by subsystems does.
  `${P}\\Склад\\Партии\\Архив\\НовыйСправочник.yaml`,
];

const everyItem = (items: string[]): number => items.length;

// [label, key, objects, children] - the shape a test compares.
type Shape = [string, string, number, Shape[]];
const shape = (totals: PackageTotal[]): Shape[] =>
  totals.map((t) => [t.group.name, t.group.key, t.objects, shape(t.children)]);

test("packageTotals: packages nest under their subsystem, a count includes the nested ones", () => {
  const totals = packageTotals(ITEMS, (p) => p, readPlacement(ANSWER), P, everyItem);
  assert.deepStrictEqual(shape(totals.get(pathKey(`${P}\\Склад`)) ?? []), [
    ["Партии", "Партии", 4, [["Архив", "Партии::Архив", 2, []]]],
  ]);
  const stock = totals.get(pathKey(`${P}\\Склад`))![0];
  assert.strictEqual(stock.group.namespace, "Демо::Учет::Склад::Партии");
  assert.strictEqual(stock.group.dir, `${P}\\Склад\\Партии`);
  assert.strictEqual(stock.children[0].group.namespace, "Демо::Учет::Склад::Партии::Архив");
});

test("packageTotals: a subsystem without packages has none, keys ignore separators and case", () => {
  const totals = packageTotals(ITEMS, (p) => p, readPlacement(ANSWER, [`${P}\\Доставка`]), "d:/REPO/Демо/Учет/", everyItem);
  assert.deepStrictEqual([...totals.keys()].sort(), [
    pathKey(`${P}\\Доставка`),
    pathKey(`${P}\\Продажи`),
    pathKey(`${P}\\Склад`),
  ].sort());
  assert.deepStrictEqual(totals.get(pathKey(`${P}\\Продажи`)), []);
  assert.deepStrictEqual(totals.get(pathKey(`${P}\\Доставка`)), []);
  assert.strictEqual(totals.get(pathKey("d:/repo/демо/учет/склад"))?.length, 1);
});

test("packageTotals: count gets the items lying directly in the package", () => {
  const seen: string[][] = [];
  // A count that leaves out forms, as the tree does for a form beside its owner.
  const withoutForms = (items: string[]): number => {
    seen.push(items.map((p) => p.slice(p.lastIndexOf("\\") + 1)));
    return items.filter((p) => !p.includes("Форма")).length;
  };
  const totals = packageTotals(ITEMS, (p) => p, readPlacement(ANSWER), P, withoutForms);
  assert.deepStrictEqual(shape(totals.get(pathKey(`${P}\\Склад`)) ?? []), [
    ["Партии", "Партии", 3, [["Архив", "Партии::Архив", 2, []]]],
  ]);
  assert.deepStrictEqual(seen.sort(), [
    ["АрхивПартий.yaml", "НовыйСправочник.yaml"],
    ["ПартииТоваров.yaml", "ПартииТоваровФормаСписка.yaml"],
  ]);
});

test("packageTotals: no answer, or an answer that does not know the project - no packages", () => {
  assert.strictEqual(packageTotals(ITEMS, (p) => p, undefined, P, everyItem).size, 0);
  assert.strictEqual(packageTotals(ITEMS, (p) => p, readPlacement(ANSWER), "D:\\repo\\Другой", everyItem).size, 0);
  // An engine older than the packages model answers without placement at all.
  const old: EngineProjectInfo = {
    projects: ANSWER.projects,
    objects: [{ kind: "Справочник", name: "Номенклатура", path: `${P}\\Склад\\Номенклатура.yaml`, subsystem: "Склад" }],
  };
  assert.strictEqual(packageTotals(ITEMS, (p) => p, readPlacement(old), P, everyItem).size, 0);
});

test("packageTotals: packages and nested packages come sorted by name", () => {
  const group = (name: string, key: string, children: PackageGroup[] = []): PackageGroup => ({
    name, key, dir: `${P}\\Склад\\${key.replace(/::/g, "\\")}`, namespace: `Демо::Учет::Склад::${key}`, children,
  });
  const placement: EnginePlacement = {
    objects: new Map(),
    projects: [{
      dir: P,
      subsystems: [{
        name: "Склад",
        dir: `${P}\\Склад`,
        namespace: "Демо::Учет::Склад",
        packages: [
          group("Партии", "Партии", [group("Возвраты", "Партии::Возвраты"), group("Архив", "Партии::Архив")]),
          group("Лоты", "Лоты"),
        ],
      }],
    }],
  };
  const totals = packageTotals<string>([], (p) => p, placement, P, everyItem);
  assert.deepStrictEqual(shape(totals.get(pathKey(`${P}\\Склад`)) ?? []), [
    ["Лоты", "Лоты", 0, []],
    ["Партии", "Партии", 0, [["Архив", "Партии::Архив", 0, []], ["Возвраты", "Партии::Возвраты", 0, []]]],
  ]);
});

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
