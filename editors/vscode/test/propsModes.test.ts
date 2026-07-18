// Unit tests for the pure logic of the unified properties panel modes (src/propsModes.ts).
// No test runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test`
// from editors/vscode.

import * as assert from "assert";
import { parseDocument } from "yaml";
import { parseInternals } from "../src/metadataCore";
import {
  buildMetaPanelModel,
  classifyEditor,
  describeMetaSelection,
  metaNodeOffsetAt,
  metaPropertyEdits,
  pairedYamlPath,
} from "../src/propsModes";

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

// Apply a batch of edits computed against ONE source text (descending starts keep the
// earlier offsets valid) - what the extension's WorkspaceEdit does.
function applyAll(text: string, edits: { start: number; end: number; newText: string }[]): string {
  const sorted = [...edits].sort((a, b) => b.start - a.start);
  let out = text;
  for (const e of sorted) {
    out = out.slice(0, e.start) + e.newText + out.slice(e.end);
  }
  return out;
}

function parses(text: string): boolean {
  return parseDocument(text, { uniqueKeys: false }).errors.length === 0;
}

function headOf(text: string): string {
  return text.split("\n").slice(0, 50).join("\n");
}

const CATALOG = `ВидЭлемента: Справочник
Ид: aaa
Имя: Товары
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: bbb
        Имя: Описание
        Тип: Строка
        Многострочная: Истина
    -
        Ид: ccc
        Имя: Цена
        Тип: Число
ТабличныеЧасти:
    -
        Ид: ddd
        Имя: Строки
        Реквизиты:
            -
                Ид: eee
                Имя: Количество
                Тип: Число
`;

const FORM = `ВидЭлемента: КомпонентИнтерфейса
Ид: fff
Имя: Карточка
Наследует:
    Тип: Форма
    Содержимое:
        -
            Тип: Надпись
`;

// --- classifyEditor -----------------------------------------------------------------------

test("classifyEditor: a component yaml drives the component mode", () => {
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\Карточка.yaml", headOf(FORM), FORM), "component");
});

test("classifyEditor: an element yaml without a form drives the metadata mode", () => {
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\Товары.yaml", headOf(CATALOG), CATALOG), "metadata");
});

test("classifyEditor: a yaml without ВидЭлемента drives nothing", () => {
  const plain = "Имя: Просто\nЗначение: 1\n";
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\other.yaml", headOf(plain), plain), "none");
});

test("classifyEditor: an .xbsl module by language id or by extension", () => {
  assert.strictEqual(classifyEditor("xbsl", "C:\\p\\Товары.Объект.xbsl", "", ""), "module");
  assert.strictEqual(classifyEditor("plaintext", "C:\\p\\Товары.xbsl", "", ""), "module");
});

test("classifyEditor: non-yaml languages drive nothing", () => {
  assert.strictEqual(classifyEditor("markdown", "C:\\p\\readme.md", "", "ВидЭлемента: X"), "none");
});

// --- pairedYamlPath -----------------------------------------------------------------------

test("pairedYamlPath: same stem, the object module suffix is stripped", () => {
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.xbsl"), "C:\\p\\Задачи.yaml");
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.Объект.xbsl"), "C:\\p\\Задачи.yaml");
  assert.strictEqual(pairedYamlPath("/a/b/Карточка.xbsl"), "/a/b/Карточка.yaml");
});

test("pairedYamlPath: a non-module path has no pair", () => {
  assert.strictEqual(pairedYamlPath("C:\\p\\readme.md"), undefined);
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.yaml"), undefined);
});

// --- metaNodeOffsetAt ---------------------------------------------------------------------

test("metaNodeOffsetAt: a cursor inside a field resolves to that field's map", () => {
  const internals = parseInternals(CATALOG)!;
  const cursor = CATALOG.indexOf("Цена");
  assert.strictEqual(metaNodeOffsetAt(CATALOG, cursor), internals.attributes[1].offset);
});

test("metaNodeOffsetAt: a nested tabular attribute wins as the deepest map", () => {
  const internals = parseInternals(CATALOG)!;
  const cursor = CATALOG.indexOf("Количество");
  assert.strictEqual(metaNodeOffsetAt(CATALOG, cursor), internals.tabulars[0].children![0].offset);
});

test("metaNodeOffsetAt: the top lines and section headers resolve to the object", () => {
  const internals = parseInternals(CATALOG)!;
  assert.strictEqual(metaNodeOffsetAt(CATALOG, 0), internals.rootOffset);
  assert.strictEqual(metaNodeOffsetAt(CATALOG, CATALOG.indexOf("Реквизиты")), internals.rootOffset);
});

test("metaNodeOffsetAt: offset 0 before leading comments falls back to the root map", () => {
  const commented = "# generated\n" + CATALOG;
  const internals = parseInternals(commented)!;
  assert.ok(internals.rootOffset > 0);
  assert.strictEqual(metaNodeOffsetAt(commented, 0), internals.rootOffset);
});

// --- describeMetaSelection ----------------------------------------------------------------

test("describeMetaSelection: a cursor describes the field under it", () => {
  const desc = describeMetaSelection(CATALOG, { cursor: CATALOG.indexOf("Число") })!;
  assert.strictEqual(desc.title, "Цена");
});

test("describeMetaSelection: an exact offset describes that node", () => {
  const internals = parseInternals(CATALOG)!;
  const desc = describeMetaSelection(CATALOG, { offset: internals.rootOffset })!;
  assert.strictEqual(desc.title, "Справочник");
});

test("describeMetaSelection: a synthetic standard attribute keeps offset -1", () => {
  const desc = describeMetaSelection(CATALOG, { std: { kind: "Справочник", name: "Код" } })!;
  assert.strictEqual(desc.offset, -1);
  assert.deepStrictEqual(desc.rows.map((r) => r.key), ["Тип", "Длина", "Уникальность"]);
});

// --- buildMetaPanelModel ------------------------------------------------------------------

test("buildMetaPanelModel: the object header carries ВидЭлемента and Имя", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(describeMetaSelection(CATALOG, { offset: internals.rootOffset })!);
  assert.strictEqual(model.meta, true);
  assert.strictEqual(model.type, "Справочник");
  assert.strictEqual(model.name, "Товары");
  assert.strictEqual(model.sections.length, 1);
});

test("buildMetaPanelModel: row editors map onto the shared controls", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { offset: internals.attributes[0].offset })!,
    ["Строка", "Число"]
  );
  const byKey = Object.fromEntries(model.sections[0].rows.map((r) => [r.key, r]));
  assert.strictEqual(byKey["Ид"].editor.control, "readonly");
  assert.strictEqual(byKey["Имя"].editor.control, "text");
  assert.strictEqual(byKey["Многострочная"].editor.control, "tristate");
  assert.strictEqual(byKey["Тип"].editor.control, "combo");
  assert.deepStrictEqual((byKey["Тип"].editor as { options: string[] }).options, ["Строка", "Число"]);
  assert.ok(model.sections[0].rows.every((r) => r.set));
  assert.strictEqual(byKey["Имя"].hay, "имя описание");
  // The field header does not repeat the name: title IS the name.
  assert.strictEqual(model.type, "Описание");
  assert.strictEqual(model.name, "");
});

test("buildMetaPanelModel: the object select rows become enum editors", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(describeMetaSelection(CATALOG, { offset: internals.rootOffset })!);
  const scope = model.sections[0].rows.find((r) => r.key === "ОбластьВидимости")!;
  assert.strictEqual(scope.editor.control, "enum");
  assert.deepStrictEqual((scope.editor as { options: string[] }).options, ["ВПроекте", "ВПодсистеме"]);
});

test("buildMetaPanelModel: a synthetic standard attribute renders every row as not set", () => {
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { std: { kind: "Справочник", name: "Код" } })!
  );
  assert.strictEqual(model.type, "Код");
  assert.strictEqual(model.name, "");
  assert.ok(model.sections[0].rows.every((r) => !r.set));
});

// --- metaPropertyEdits --------------------------------------------------------------------

test("metaPropertyEdits: a scalar write replaces the value in place", () => {
  const internals = parseInternals(CATALOG)!;
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: internals.attributes[1].offset! }, "Имя", "Стоимость")
  );
  assert.ok(parses(out));
  assert.deepStrictEqual(parseInternals(out)!.attributes.map((a) => a.name), ["Описание", "Стоимость"]);
});

test("metaPropertyEdits: value null removes the key line", () => {
  const internals = parseInternals(CATALOG)!;
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: internals.rootOffset }, "ОбластьВидимости", null)
  );
  assert.ok(parses(out));
  assert.ok(!out.includes("ОбластьВидимости"));
});

test("metaPropertyEdits: Тип changed off Строка also drops Многострочная", () => {
  const internals = parseInternals(CATALOG)!;
  const edits = metaPropertyEdits(CATALOG, { offset: internals.attributes[0].offset! }, "Тип", "Число");
  assert.strictEqual(edits.length, 2);
  const out = applyAll(CATALOG, edits);
  assert.ok(parses(out));
  const attr = parseInternals(out)!.attributes[0];
  assert.strictEqual(attr.type, "Число");
  assert.ok(!out.includes("Многострочная"));
});

test("metaPropertyEdits: Тип kept a string does not touch Многострочная", () => {
  const internals = parseInternals(CATALOG)!;
  const edits = metaPropertyEdits(CATALOG, { offset: internals.attributes[0].offset! }, "Тип", "Строка?");
  assert.strictEqual(edits.length, 1);
  const out = applyAll(CATALOG, edits);
  assert.ok(parses(out));
  assert.ok(out.includes("Многострочная"));
});

test("metaPropertyEdits: a synthetic standard attribute materializes into Реквизиты", () => {
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", "250")
  );
  assert.ok(parses(out));
  const added = parseInternals(out)!.attributes.find((a) => a.name === "Наименование");
  assert.ok(added, "the record must appear in Реквизиты");
  assert.ok(out.includes("Длина: 250"));
});

test("metaPropertyEdits: removing from a non-materialized standard attribute is a no-op", () => {
  assert.deepStrictEqual(
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", null),
    []
  );
});

test("metaPropertyEdits: a materialized standard attribute edits its record by name", () => {
  const materialized = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", "250")
  );
  const out = applyAll(
    materialized,
    metaPropertyEdits(materialized, { offset: -1, std: { name: "Наименование" } }, "Длина", "500")
  );
  assert.ok(parses(out));
  assert.ok(out.includes("Длина: 500"));
  assert.ok(!out.includes("Длина: 250"));
});

// -----------------------------------------------------------------------------

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
