// Unit tests for the packages core (src/packagesCore.ts): the arrangement of the engine's
// placement answer into the tree and the plan of a scaffolding result with renames. Plain Node
// asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  allPackages,
  bucketItems,
  deletionPrompt,
  EngineProjectInfo,
  folderPlace,
  readPlacement,
  scaffoldSteps,
  vacatedDirs,
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

// The contract sample of `xbsl project-info`: subsystem `Склад` with a root object, a package
// and a nested package, subsystem `Продажи` without packages, and `Доставка` - a subsystem the
// engine lists though it has a descriptor and no object yet.
const ANSWER: EngineProjectInfo = {
  projects: [{ vendor: "Демо", name: "Учет", dir: P, subsystems: ["Доставка", "Продажи", "Склад"] }],
  packages: [
    { subsystem: "Склад", package: "Партии", dir: `${P}\\Склад\\Партии`, objects: 1 },
    { subsystem: "Склад", package: "Партии::Архив", dir: `${P}\\Склад\\Партии\\Архив`, objects: 1 },
  ],
  objects: [
    { kind: "ОбщийМодуль", name: "Заказы", path: `${P}\\Продажи\\Заказы.yaml`, subsystem: "Продажи", package: null, namespace: "Демо::Учет::Продажи" },
    { kind: "Справочник", name: "АрхивПартий", path: `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`, subsystem: "Склад", package: "Партии::Архив", namespace: "Демо::Учет::Склад::Партии::Архив" },
    { kind: "Справочник", name: "Номенклатура", path: `${P}\\Склад\\Номенклатура.yaml`, subsystem: "Склад", package: null, namespace: "Демо::Учет::Склад" },
    { kind: "Справочник", name: "ПартииТоваров", path: `${P}\\Склад\\Партии\\ПартииТоваров.yaml`, subsystem: "Склад", package: "Партии", namespace: "Демо::Учет::Склад::Партии" },
  ],
};

test("readPlacement: subsystems with folders, packages nested, namespaces spelled", () => {
  const placement = readPlacement(ANSWER, [`${P}\\Доставка`])!;
  assert.ok(placement);
  const [project] = placement.projects;
  assert.strictEqual(project.dir, P);
  assert.deepStrictEqual(project.subsystems.map((s) => [s.name, s.dir]), [
    ["Доставка", `${P}\\Доставка`],
    ["Продажи", `${P}\\Продажи`],
    ["Склад", `${P}\\Склад`],
  ]);
  const stock = project.subsystems[2];
  assert.strictEqual(stock.namespace, "Демо::Учет::Склад");
  assert.deepStrictEqual(stock.packages.map((g) => [g.name, g.key, g.namespace]), [
    ["Партии", "Партии", "Демо::Учет::Склад::Партии"],
  ]);
  assert.deepStrictEqual(stock.packages[0].children.map((g) => [g.name, g.key, g.dir]), [
    ["Архив", "Партии::Архив", `${P}\\Склад\\Партии\\Архив`],
  ]);
  assert.deepStrictEqual(allPackages(stock.packages).map((g) => g.key), ["Партии", "Партии::Архив"]);
});

test("readPlacement: an answer without packages is no placement at all", () => {
  assert.strictEqual(readPlacement(undefined), undefined);
  assert.strictEqual(readPlacement({ error: "boom" }), undefined);
  // An engine older than the packages model: the objects carry no `package` field.
  const old: EngineProjectInfo = {
    projects: ANSWER.projects,
    objects: [{ kind: "Справочник", name: "Номенклатура", path: `${P}\\Склад\\Номенклатура.yaml`, subsystem: "Склад" }],
  };
  assert.strictEqual(readPlacement(old), undefined);
});

test("readPlacement: a subsystem folder comes from its packages when it has no root object", () => {
  const onlyPackages: EngineProjectInfo = {
    projects: [{ vendor: "Демо", name: "Учет", dir: P, subsystems: ["Склад"] }],
    packages: [{ subsystem: "Склад", package: "Партии::Архив", dir: `${P}\\Склад\\Партии\\Архив`, objects: 1 }],
    objects: [
      { kind: "Справочник", name: "АрхивПартий", path: `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`, subsystem: "Склад", package: "Партии::Архив", namespace: "Демо::Учет::Склад::Партии::Архив" },
    ],
  };
  const stock = readPlacement(onlyPackages)!.projects[0].subsystems[0];
  assert.strictEqual(stock.dir, `${P}\\Склад`);
  // The enclosing package is missing from this answer: the nested one hangs on the subsystem.
  assert.deepStrictEqual(stock.packages.map((g) => g.key), ["Партии::Архив"]);
});

test("bucketItems: the engine's placement first, the folder for what it does not place", () => {
  const placement = readPlacement(ANSWER)!;
  const [project] = placement.projects;
  const items = [
    `${P}\\Склад\\Номенклатура.yaml`,
    `${P}\\Склад\\Партии\\ПартииТоваров.yaml`,
    `${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`,
    // An object created after the answer, and a resource file of the package.
    `${P}\\Склад\\Партии\\НовыйСправочник.yaml`,
    `${P}\\Склад\\Партии\\Ресурсы\\Схема.svg`,
    `${P}\\Проект.xbsl`,
  ];
  const buckets = bucketItems(items, (p) => p, project, placement);
  const stock = project.subsystems.find((s) => s.name === "Склад")!;
  const slot = buckets.subsystems.get(stock)!;
  assert.deepStrictEqual(slot.root, [`${P}\\Склад\\Номенклатура.yaml`]);
  assert.deepStrictEqual(slot.packages.get("Партии"), [
    `${P}\\Склад\\Партии\\ПартииТоваров.yaml`,
    `${P}\\Склад\\Партии\\НовыйСправочник.yaml`,
    `${P}\\Склад\\Партии\\Ресурсы\\Схема.svg`,
  ]);
  assert.deepStrictEqual(slot.packages.get("Партии::Архив"), [`${P}\\Склад\\Партии\\Архив\\АрхивПартий.yaml`]);
  assert.deepStrictEqual(buckets.outside, [`${P}\\Проект.xbsl`]);
});

test("folderPlace: paths compare regardless of separators and case", () => {
  const [project] = readPlacement(ANSWER)!.projects;
  const found = folderPlace(project, "d:/REPO/Демо/Учет/Склад/Партии/Архив/Новый.yaml")!;
  assert.strictEqual(found.subsystem.name, "Склад");
  assert.strictEqual(found.packageKey, "Партии::Архив");
  assert.strictEqual(folderPlace(project, "D:\\elsewhere\\Файл.yaml"), undefined);
});

test("scaffoldSteps: renames first, an edit of a renamed file is read at its old path", () => {
  const steps = scaffoldSteps({
    renames: [{ from: "D:\\p\\Склад\\Номенклатура.yaml", to: "D:\\p\\Склад\\Партии\\Номенклатура.yaml" }],
    files: [
      { path: "D:\\p\\Склад\\Партии\\Номенклатура.yaml", created: false, content: "a" },
      { path: "D:\\p\\Продажи\\Заказы.xbsl", created: false, content: "b" },
      { path: "D:\\p\\Склад\\Новый.yaml", created: true, content: "c" },
    ],
    deletes: ["D:\\p\\Склад\\Старый.yaml"],
  });
  assert.deepStrictEqual(steps.map((s) => s.kind), ["rename", "replace", "replace", "create", "delete"]);
  const renamedEdit = steps[1] as { readFrom: string; path: string };
  assert.strictEqual(renamedEdit.readFrom, "D:\\p\\Склад\\Номенклатура.yaml");
  assert.strictEqual(renamedEdit.path, "D:\\p\\Склад\\Партии\\Номенклатура.yaml");
  assert.strictEqual((steps[2] as { readFrom: string }).readFrom, "D:\\p\\Продажи\\Заказы.xbsl");
});

test("deletionPrompt: the files are the engine's plan, the notes are cut for a dialog", () => {
  // The plan of delete-object for a virtual table and a SOAP service client: the query and the
  // WSDL descriptions are in it, and the tree deletes the list as the engine made it.
  const deletes = [
    "D:\\p\\Склад\\КлиентКурсовВалют.Wsdl.1.wsdl",
    "D:\\p\\Склад\\КлиентКурсовВалют.Wsdl.2.wsdl",
    "D:\\p\\Склад\\КлиентКурсовВалют.yaml",
    "D:/p/Склад/ЗадачиСписокТаблица.xbql",
  ];
  const notes = ["Удаляется файлов: 4", "Оставшихся упоминаний: 3", "a.xbsl:1", "b.xbsl:2", "c.yaml:3"];
  const prompt = deletionPrompt({ deletes, notes }, 3);
  assert.deepStrictEqual(prompt.files, [
    "КлиентКурсовВалют.Wsdl.1.wsdl",
    "КлиентКурсовВалют.Wsdl.2.wsdl",
    "КлиентКурсовВалют.yaml",
    "ЗадачиСписокТаблица.xbql",
  ]);
  assert.strictEqual(prompt.detail, "Удаляется файлов: 4\nОставшихся упоминаний: 3\na.xbsl:1\n... +2");
  assert.strictEqual(deletionPrompt({ deletes, notes: notes.slice(0, 2) }, 3).detail, notes.slice(0, 2).join("\n"));
  assert.deepStrictEqual(deletionPrompt({}), { files: [], detail: "" });
});

test("vacatedDirs: the parents no renamed file lands in, deepest first", () => {
  const renames = [
    { from: "D:\\p\\Склад\\Партии\\Архив\\А.yaml", to: "D:\\p\\Склад\\Лоты\\Архив\\А.yaml" },
    { from: "D:\\p\\Склад\\Партии\\Б.yaml", to: "D:\\p\\Склад\\Лоты\\Б.yaml" },
  ];
  assert.deepStrictEqual(vacatedDirs(renames), ["D:\\p\\Склад\\Партии\\Архив", "D:\\p\\Склад\\Партии"]);
  // A move INTO a package of the same folder vacates nothing.
  assert.deepStrictEqual(
    vacatedDirs([{ from: "D:\\p\\Склад\\А.yaml", to: "D:\\p\\Склад\\Партии\\А.yaml" }]),
    []
  );
});

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
