// Unit tests for the shared component icon mapping (src/componentIconsCore.ts). No test
// runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from
// editors/vscode.

import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import { GENERIC_COMPONENT_ICON, iconIdFor, usedIconIds } from "../src/componentIconsCore";

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

// --- exact names ----------------------------------------------------------------------------

test("exact type names get their dedicated icons", () => {
  assert.strictEqual(iconIdFor("Кнопка"), "inspect");
  assert.strictEqual(iconIdFor("Гиперссылка"), "link");
  assert.strictEqual(iconIdFor("Надпись"), "symbol-string");
  assert.strictEqual(iconIdFor("ПолеВвода"), "symbol-field");
  assert.strictEqual(iconIdFor("ВыборЗначения"), "symbol-field");
  assert.strictEqual(iconIdFor("ВыборДатыВремени"), "calendar");
  assert.strictEqual(iconIdFor("Флажок"), "check");
  assert.strictEqual(iconIdFor("Переключатель"), "circle-filled");
  assert.strictEqual(iconIdFor("Картинка"), "file-media");
  assert.strictEqual(iconIdFor("Видео"), "device-camera-video");
  assert.strictEqual(iconIdFor("Дерево"), "list-tree");
  assert.strictEqual(iconIdFor("КонтейнерHtml"), "code");
  assert.strictEqual(iconIdFor("Вставка"), "code");
  assert.strictEqual(iconIdFor("ПанельКоманд"), "tools");
  assert.strictEqual(iconIdFor("ГрафическаяСхема"), "type-hierarchy");
  assert.strictEqual(iconIdFor("Страницы"), "browser");
  assert.strictEqual(iconIdFor("СтандартнаяКарточка"), "layout");
  assert.strictEqual(iconIdFor("ПроизвольныйШаблонФормы"), "editor-layout");
});

test("exact names beat their families", () => {
  // diagrams: the family gives graph, the specific kinds get their own shapes
  assert.strictEqual(iconIdFor("КруговаяДиаграмма"), "pie-chart");
  assert.strictEqual(iconIdFor("ДиаграммаГанта"), "project");
  assert.strictEqual(iconIdFor("ВоронкообразнаяДиаграмма"), "filter");
  assert.strictEqual(iconIdFor("ДиаграммаСпидометр"), "dashboard");
  assert.strictEqual(iconIdFor("ЛепестковаяДиаграмма"), "target");
  assert.strictEqual(iconIdFor("XYДиаграмма"), "graph-scatter");
  // groups: the flavors override the layout family
  assert.strictEqual(iconIdFor("СтековаяГруппа"), "layers");
  assert.strictEqual(iconIdFor("РазделяющаяГруппа"), "split-horizontal");
  // file components override the *Список* family
  assert.strictEqual(iconIdFor("СписокФайлов"), "files");
  assert.strictEqual(iconIdFor("ВыборФайлов"), "files");
});

// --- families -------------------------------------------------------------------------------

test("families match by camel-case word, in table order", () => {
  assert.strictEqual(iconIdFor("Диаграмма"), "graph");
  assert.strictEqual(iconIdFor("СтолбчатаяДиаграмма"), "graph");
  assert.strictEqual(iconIdFor("Группа"), "layout");
  assert.strictEqual(iconIdFor("ГруппаКолонок"), "layout");
  assert.strictEqual(iconIdFor("Форма"), "window");
  assert.strictEqual(iconIdFor("ФормаВыбора"), "window");
  assert.strictEqual(iconIdFor("Таблица"), "table");
  assert.strictEqual(iconIdFor("ТаблицаЗначений"), "table");
  assert.strictEqual(iconIdFor("ПроизвольныйСписок"), "list-flat");
  assert.strictEqual(iconIdFor("СписокВыбора"), "list-flat");
  assert.strictEqual(iconIdFor("Меню"), "menu");
  assert.strictEqual(iconIdFor("КонтекстноеМеню"), "menu");
});

test("family needles do not fire inside unrelated words", () => {
  // "Форма" must not catch Форматирование (the word continues in lowercase)
  assert.strictEqual(iconIdFor("Форматирование"), GENERIC_COMPONENT_ICON);
  // lowercase occurrences are different words entirely
  assert.strictEqual(iconIdFor("Подгруппировка"), GENERIC_COMPONENT_ICON);
});

// --- package fallback and the generic icon ---------------------------------------------------

test("unmatched names fall back to the ui-schema package, then to the generic icon", () => {
  assert.strictEqual(iconIdFor("Аккордеон", "Стд::Интерфейс::Списки"), "list-flat");
  assert.strictEqual(iconIdFor("Индикатор", "Стд::Интерфейс::Диаграммы"), "graph");
  assert.strictEqual(iconIdFor("Вложение", "Стд::Интерфейс::Файлы"), "file");
  assert.strictEqual(iconIdFor("Регулятор", "Стд::Интерфейс::Формы"), "window");
  assert.strictEqual(iconIdFor("ОбычнаяКоманда", "Стд::Интерфейс::Команды"), "tools");
  // an unknown package and no package at all end at the generic icon
  assert.strictEqual(iconIdFor("Аватар", "Стд::Интерфейс::ОбщиеКомпоненты"), GENERIC_COMPONENT_ICON);
  assert.strictEqual(iconIdFor("НечтоНеизвестное"), GENERIC_COMPONENT_ICON);
  // a name match outranks the package
  assert.strictEqual(iconIdFor("КруговаяДиаграмма", "Стд::Интерфейс::Списки"), "pie-chart");
});

test("the container flag refines only the generic fallback", () => {
  assert.strictEqual(iconIdFor("НечтоНеизвестное", undefined, true), "layout");
  assert.strictEqual(iconIdFor("НечтоНеизвестное", undefined, false), GENERIC_COMPONENT_ICON);
  // mapped names ignore the flag - the mapping already told the truth
  assert.strictEqual(iconIdFor("Кнопка", undefined, true), "inspect");
  assert.strictEqual(iconIdFor("Вложение", "Стд::Интерфейс::Файлы", true), "file");
});

// --- every produced id is a real codicon ------------------------------------------------------

// The authoritative list ships with @vscode/codicons (not a dependency of this extension);
// when the package is around (e.g. a future dependency or a hoisted install) the test reads
// it, otherwise it falls back to a subset transcribed from the official reference
// (code.visualstudio.com/api/references/icons-in-labels). An id outside the list would
// silently render as an EMPTY icon in a TreeItem - exactly the bug this test pins down.
const FALLBACK_KNOWN_CODICONS = [
  "browser", "calendar", "check", "circle-filled", "code", "dashboard",
  "device-camera-video", "editor-layout", "file", "file-media", "files", "filter",
  "graph", "graph-line", "graph-scatter", "inspect", "layers", "layout", "link",
  "list-flat", "list-tree", "menu", "pie-chart", "project", "split-horizontal",
  "symbol-event", "symbol-field", "symbol-misc", "symbol-string", "table", "target",
  "tools", "type-hierarchy", "versions", "window",
];

function knownCodicons(): { names: Set<string>; source: string } {
  const candidates = [
    path.join(__dirname, "..", "node_modules", "@vscode", "codicons", "src", "template", "mapping.json"),
    path.join(process.cwd(), "node_modules", "@vscode", "codicons", "src", "template", "mapping.json"),
  ];
  for (const candidate of candidates) {
    try {
      const mapping = JSON.parse(fs.readFileSync(candidate, "utf8")) as Record<string, unknown>;
      return { names: new Set(Object.keys(mapping)), source: "mapping.json" };
    } catch {
      // not installed here - try the next location or the fallback
    }
  }
  return { names: new Set(FALLBACK_KNOWN_CODICONS), source: "fallback list" };
}

test("all used codicon names exist in the known codicon list", () => {
  const { names, source } = knownCodicons();
  const unknown = usedIconIds().filter((id) => !names.has(id));
  assert.deepStrictEqual(unknown, [], `unknown codicons (${source}): ${unknown.join(", ")}`);
  // the structure view's own base icons are part of the same contract
  for (const id of ["window", "layers", "symbol-field", "layout"]) {
    assert.ok(names.has(id), `base icon missing from the known list: ${id}`);
  }
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
