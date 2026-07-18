// Unit tests for the pure data-panel core (src/formDataCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test`.

import * as assert from "assert";
import {
  buildFieldFragment,
  DATA_MIME,
  decodeDataDrag,
  encodeDataDrag,
  isMultilineText,
  PROPERTY_PRIMITIVE_TYPES,
  propertyNameError,
} from "../src/formDataCore";

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

// --- buildFieldFragment ---------------------------------------------------------------------

test("a boolean attribute becomes a Флажок bound to =Объект.Имя", () => {
  const fragment = buildFieldFragment({ kind: "attribute", name: "Проведен", type: "Булево" });
  assert.strictEqual(fragment, ["Тип: Флажок", "Заголовок: Проведен", "Значение: =Объект.Проведен"].join("\n"));
});

test("a boolean component property binds as =Имя (no Объект prefix)", () => {
  const fragment = buildFieldFragment({ kind: "componentProperty", name: "ТолькоЧтение", type: "Булево" });
  assert.ok(fragment.includes("Значение: =ТолькоЧтение"));
  assert.ok(!fragment.includes("Объект."));
});

test("a string attribute becomes a stretched ПолеВвода with a title", () => {
  const fragment = buildFieldFragment({ kind: "attribute", name: "Наименование", type: "Строка" });
  assert.strictEqual(
    fragment,
    [
      "Тип: ПолеВвода<Строка>",
      "Заголовок: Наименование",
      "Значение: =Объект.Наименование",
      "РастягиватьПоГоризонтали: Истина",
    ].join("\n")
  );
});

test("the fragment opens with the top-level Тип key (the insert_fragment contract)", () => {
  for (const type of ["Булево", "Строка", "Число", ""]) {
    const fragment = buildFieldFragment({ kind: "attribute", name: "Поле", type });
    assert.ok(fragment.startsWith("Тип: "), `starts with Тип for '${type}'`);
  }
});

test("an empty type falls back to Строка (engine parity)", () => {
  const fragment = buildFieldFragment({ kind: "attribute", name: "Регистратор", type: "" });
  assert.ok(fragment.includes("Тип: ПолеВвода<Строка>"));
});

test("generic, union and reference types go into ПолеВвода verbatim", () => {
  const cases = ["Массив<Строка>", "Строка|Число", "Товары.Ссылка", "ВидЦен?", "Товары.Ссылка|?"];
  for (const type of cases) {
    const fragment = buildFieldFragment({ kind: "attribute", name: "Поле", type });
    assert.ok(fragment.includes(`Тип: ПолеВвода<${type}>`), `verbatim for '${type}'`);
  }
});

test("a nullable boolean is NOT a Флажок (engine parity: only the exact Булево)", () => {
  const fragment = buildFieldFragment({ kind: "attribute", name: "Флаг", type: "Булево?" });
  assert.ok(fragment.includes("Тип: ПолеВвода<Булево?>"));
});

test("multiline adds the НастройкиВводаСтроки block", () => {
  const fragment = buildFieldFragment({
    kind: "attribute",
    name: "Описание",
    type: "Строка",
    multiline: true,
  });
  assert.deepStrictEqual(fragment.split("\n").slice(-2), ["НастройкиВводаСтроки:", "    Многострочная: Истина"]);
});

test("multiline is ignored for a boolean", () => {
  const fragment = buildFieldFragment({ kind: "attribute", name: "Описание", type: "Булево", multiline: true });
  assert.ok(!fragment.includes("НастройкиВводаСтроки"));
});

test("a component property of a project type binds as =Имя", () => {
  const fragment = buildFieldFragment({ kind: "componentProperty", name: "Владелец", type: "Товары.Ссылка|?" });
  assert.ok(fragment.includes("Тип: ПолеВвода<Товары.Ссылка|?>"));
  assert.ok(fragment.includes("Значение: =Владелец"));
});

// --- isMultilineText --------------------------------------------------------------------------

test("Описание/Комментарий of a string (or unknown) type are multiline, the rest are not", () => {
  assert.strictEqual(isMultilineText("Описание", "Строка"), true);
  assert.strictEqual(isMultilineText("Комментарий", ""), true);
  assert.strictEqual(isMultilineText("Описание", "Число"), false);
  assert.strictEqual(isMultilineText("Наименование", "Строка"), false);
});

// --- propertyNameError -------------------------------------------------------------------------

test("property names: identifier only, no ё, no duplicates", () => {
  assert.strictEqual(propertyNameError("", []), "empty");
  assert.strictEqual(propertyNameError("Итог", []), undefined);
  assert.strictEqual(propertyNameError("_итог2", []), undefined);
  assert.strictEqual(propertyNameError("2Итог", []), "identifier");
  assert.strictEqual(propertyNameError("Итог сумм", []), "identifier");
  assert.strictEqual(propertyNameError("Счёт", []), "yo");
  assert.strictEqual(propertyNameError("Ёмкость", []), "yo");
  assert.strictEqual(propertyNameError("Итог", ["Итог", null]), "duplicate");
  assert.strictEqual(propertyNameError("Итог2", ["Итог", null]), undefined);
});

// --- drag payload ------------------------------------------------------------------------------

test("the drag payload round-trips through encode/decode", () => {
  const payload = { kind: "attribute" as const, name: "Описание", type: "Строка", multiline: true };
  assert.deepStrictEqual(decodeDataDrag(encodeDataDrag(payload)), payload);
  const property = { kind: "componentProperty" as const, name: "Итог", type: "Число" };
  assert.deepStrictEqual(decodeDataDrag(encodeDataDrag(property)), property);
});

test("foreign or malformed payloads decode to undefined", () => {
  assert.strictEqual(decodeDataDrag("not json"), undefined);
  assert.strictEqual(decodeDataDrag("{}"), undefined);
  assert.strictEqual(decodeDataDrag('{"kind":"other","name":"X","type":""}'), undefined);
  assert.strictEqual(decodeDataDrag('{"kind":"attribute","name":"","type":""}'), undefined);
  assert.strictEqual(decodeDataDrag('{"kind":"attribute","name":"X"}'), undefined);
  assert.strictEqual(decodeDataDrag('{"kind":"attribute","name":"X","type":"","multiline":"yes"}'), undefined);
});

// --- constants ---------------------------------------------------------------------------------

test("the MIME matches the view id and the primitives are the picker's fixed set", () => {
  assert.strictEqual(DATA_MIME, "application/vnd.code.tree.xbslformdata");
  assert.deepStrictEqual([...PROPERTY_PRIMITIVE_TYPES], ["Строка", "Число", "Булево", "Дата"]);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
