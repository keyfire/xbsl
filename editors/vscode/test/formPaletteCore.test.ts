// Unit tests for the pure component-palette core (src/formPaletteCore.ts). No test runner
// and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test`.

import * as assert from "assert";
import {
  buildPalette,
  bumpUsage,
  containersFromCatalog,
  containersFromRecords,
  concreteCatalog,
  FREQUENT_LIMIT,
  hasContentSlot,
  packageSegment,
  UiCatalogResponse,
  UiComponentRecord,
} from "../src/formPaletteCore";

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

const CATALOG: UiCatalogResponse = {
  available: true,
  version: "9.2",
  components: {
    Надпись: { package: "Стд::Интерфейс::ОбщиеКомпоненты", doc: "Текст на форме." },
    Кнопка: { package: "Стд::Интерфейс::ОбщиеКомпоненты", doc: "Кнопка.", since: "9.0" },
    Группа: { package: "Стд::Интерфейс::ОбщиеКомпоненты" },
    Таблица: { package: "Стд::Интерфейс::Списки" },
    ПолеВвода: { package: "Стд::Интерфейс::Формы" },
    Компонент: { package: "Стд::Интерфейс", abstract: true },
  },
};

test("packageSegment takes the last :: segment", () => {
  assert.strictEqual(packageSegment("Стд::Интерфейс::ОбщиеКомпоненты"), "ОбщиеКомпоненты");
  assert.strictEqual(packageSegment("Стд::Интерфейс"), "Интерфейс");
  assert.strictEqual(packageSegment(undefined), "");
});

test("abstract components are dropped from the insertable set", () => {
  const concrete = concreteCatalog(CATALOG);
  assert.ok(concrete.has("Надпись"));
  assert.ok(!concrete.has("Компонент"));
});

test("sections: frequent, favorites, project, then packages sorted by segment", () => {
  const sections = buildPalette(
    CATALOG,
    ["МояКарточка", "АктивнаяПлашка"],
    ["Кнопка", "МояКарточка", "Неизвестный"],
    { Надпись: 3, Кнопка: 1, Компонент: 9, Чужой: 5 }
  );
  assert.deepStrictEqual(
    sections.map((s) => s.kind),
    ["frequent", "favorites", "project", "package", "package", "package"]
  );
  // Frequent: only known components, sorted by count; the abstract and unknown ones ignored.
  assert.deepStrictEqual(sections[0].items.map((i) => i.name), ["Надпись", "Кнопка"]);
  // Favorites: known ones only, ru-sorted.
  assert.deepStrictEqual(sections[1].items.map((i) => i.name), ["Кнопка", "МояКарточка"]);
  assert.strictEqual(sections[1].items[1].origin, "project");
  // Project: ru-sorted.
  assert.deepStrictEqual(sections[2].items.map((i) => i.name), ["АктивнаяПлашка", "МояКарточка"]);
  // Packages: segments ru-sorted, items ru-sorted, records carried over.
  assert.deepStrictEqual(sections.slice(3).map((s) => s.packageLabel), ["ОбщиеКомпоненты", "Списки", "Формы"]);
  assert.deepStrictEqual(sections[3].items.map((i) => i.name), ["Группа", "Кнопка", "Надпись"]);
  const button = sections[3].items.find((i) => i.name === "Кнопка");
  assert.strictEqual(button?.doc, "Кнопка.");
  assert.strictEqual(button?.since, "9.0");
  assert.strictEqual(button?.packageName, "Стд::Интерфейс::ОбщиеКомпоненты");
});

test("frequent is capped and empty sections are omitted", () => {
  const usage: Record<string, number> = {};
  const components: Record<string, { package?: string }> = {};
  for (let i = 0; i < 12; i++) {
    const name = `Компонент${String.fromCharCode(1040 + i)}`; // А, Б, В ...
    components[name] = { package: "Стд::Интерфейс" };
    usage[name] = i + 1;
  }
  const sections = buildPalette({ available: true, components }, [], [], usage);
  assert.strictEqual(sections[0].kind, "frequent");
  assert.strictEqual(sections[0].items.length, FREQUENT_LIMIT);
  // The most used comes first.
  assert.strictEqual(sections[0].items[0].name, `Компонент${String.fromCharCode(1040 + 11)}`);
  assert.ok(!sections.some((s) => s.kind === "favorites"));
  assert.ok(!sections.some((s) => s.kind === "project"));
});

test("without the ui schema: a hint node plus the project-backed sections", () => {
  const sections = buildPalette(
    { available: false },
    ["МояКарточка"],
    ["МояКарточка", "Кнопка"],
    { МояКарточка: 2, Надпись: 5 }
  );
  assert.deepStrictEqual(
    sections.map((s) => s.kind),
    ["hint", "frequent", "favorites", "project"]
  );
  // Platform names vanish from frequent/favorites - only project components stay insertable.
  assert.deepStrictEqual(sections[1].items.map((i) => i.name), ["МояКарточка"]);
  assert.deepStrictEqual(sections[2].items.map((i) => i.name), ["МояКарточка"]);
});

test("container candidates come straight from catalog flags when the data has them", () => {
  const catalog: UiCatalogResponse = {
    available: true,
    components: {
      СтандартнаяКарточка: { package: "Стд::Интерфейс::ОбщиеКомпоненты", container: true },
      Группа: { package: "Стд::Интерфейс::ОбщиеКомпоненты", container: true },
      Кнопка: { package: "Стд::Интерфейс::ОбщиеКомпоненты" },
      БазовыйКонтейнер: { package: "Стд::Интерфейс", container: true, abstract: true },
    },
  };
  // ru-sorted, the abstract container dropped (it cannot be written as a wrapper type)
  assert.deepStrictEqual(containersFromCatalog(catalog), ["Группа", "СтандартнаяКарточка"]);
  // older data without the flag: undefined - the caller falls back to the full records
  assert.strictEqual(containersFromCatalog(CATALOG), undefined);
  assert.strictEqual(containersFromCatalog({ available: true, components: {} }), undefined);
  // every flagged container abstract counts as no data too
  assert.strictEqual(
    containersFromCatalog({
      available: true,
      components: { БазовыйКонтейнер: { container: true, abstract: true } },
    }),
    undefined
  );
});

test("container candidates come from records with a Содержимое slot", () => {
  assert.ok(hasContentSlot({ props: { Содержимое: { slot: true } } }));
  assert.ok(!hasContentSlot({ props: { Содержимое: {} } }));
  assert.ok(!hasContentSlot({ props: { Страницы: { slot: true } } }));
  assert.ok(!hasContentSlot(undefined));

  const records = new Map<string, UiComponentRecord | undefined>([
    ["Группа", { props: { Содержимое: { slot: true } } }],
    ["Кнопка", { props: { Заголовок: {} } }],
    ["СтандартнаяКарточка", { props: { Содержимое: { slot: true } } }],
    ["Сломанный", undefined],
  ]);
  assert.deepStrictEqual(containersFromRecords(records, ["Группа"]), ["Группа", "СтандартнаяКарточка"]);
  assert.deepStrictEqual(containersFromRecords(new Map(), ["Группа", "СтандартнаяКарточка"]), [
    "Группа",
    "СтандартнаяКарточка",
  ]);
});

test("bumpUsage increments without mutating the source", () => {
  const usage = { Надпись: 1 };
  const next = bumpUsage(usage, "Надпись");
  assert.strictEqual(next["Надпись"], 2);
  assert.strictEqual(usage["Надпись"], 1);
  assert.strictEqual(bumpUsage({}, "Кнопка")["Кнопка"], 1);
});

// The schema names packages in Russian (it is derived from the Russian documentation), so an
// English editor used to get a Russian palette. The pairs now come from the engine (uiterms).
const EN_CATALOG = {
  available: true,
  components: {
    Card: { package: "Стд::Интерфейс::ОбщиеКомпоненты" },
    List: { package: "Стд::Интерфейс::Списки" },
  },
  packages: {
    "Стд::Интерфейс::ОбщиеКомпоненты": "Std::Interface::CommonComponents",
    "Стд::Интерфейс::Списки": "Std::Interface::Lists",
  },
} as never;

test("группы палитры следуют языку интерфейса", () => {
  const labels = (english?: boolean) =>
    buildPalette(EN_CATALOG, [], [], {}, english)
      .filter((s) => s.kind === "package")
      .map((s) => s.packageLabel)
      .join(",");
  assert.strictEqual(labels(), "ОбщиеКомпоненты,Списки");
  assert.strictEqual(labels(true), "CommonComponents,Lists");
});

test("пакет без пары остаётся как есть", () => {
  const catalog = { available: true, components: { X: { package: "Стд::Прочее" } } } as never;
  const labels = buildPalette(catalog, [], [], {}, true)
    .filter((s) => s.kind === "package")
    .map((s) => s.packageLabel);
  assert.deepStrictEqual(labels, ["Прочее"]);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
