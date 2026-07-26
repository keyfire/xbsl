// Tests for the block-presets store helpers (hook 8). Pure list operations - no vscode.

import * as assert from "assert";
import {
  addPreset,
  BLOCK_PRESETS_MAX,
  BlockPreset,
  removePreset,
  sanitizePresets,
} from "../src/blockPresetsCore";

let passed = 0;
let failed = 0;
function test(name: string, fn: () => void): void {
  try {
    fn();
    passed++;
    console.log("ok  ", name);
  } catch (e) {
    failed++;
    console.log("FAIL", name);
    console.log("     ", (e as Error).message);
  }
}

const p = (name: string, fragment = "Тип: Кнопка\n", type = "Кнопка"): BlockPreset => ({ name, fragment, type });

test("addPreset prepends and trims the name", () => {
  const list = addPreset([], p("  Карточка  "));
  assert.deepStrictEqual(list.map((x) => x.name), ["Карточка"]);
});

test("addPreset replaces a same-name preset and moves it to the front", () => {
  let list = [p("A"), p("B"), p("C")];
  list = addPreset(list, { name: "B", fragment: "Тип: Надпись\n", type: "Надпись" });
  assert.deepStrictEqual(list.map((x) => x.name), ["B", "A", "C"]);
  assert.strictEqual(list[0].type, "Надпись"); // the new content wins
  assert.strictEqual(list.length, 3); // no duplicate B
});

test("addPreset rejects a blank name (list unchanged)", () => {
  const list = [p("A")];
  assert.strictEqual(addPreset(list, p("   ")), list);
});

test("addPreset caps the list at the max, newest first", () => {
  let list: BlockPreset[] = [];
  for (let i = 0; i < BLOCK_PRESETS_MAX + 5; i++) {
    list = addPreset(list, p("n" + i));
  }
  assert.strictEqual(list.length, BLOCK_PRESETS_MAX);
  assert.strictEqual(list[0].name, "n" + (BLOCK_PRESETS_MAX + 4)); // the last added leads
});

test("removePreset drops by name only", () => {
  const list = [p("A"), p("B")];
  assert.deepStrictEqual(removePreset(list, "A").map((x) => x.name), ["B"]);
  assert.deepStrictEqual(removePreset(list, "Z").map((x) => x.name), ["A", "B"]);
});

test("sanitizePresets keeps only well-formed, distinct records", () => {
  const raw = [
    { name: "A", fragment: "Тип: Кнопка\n", type: "Кнопка" },
    { name: "A", fragment: "dup", type: "X" }, // duplicate name dropped
    { name: "  ", fragment: "blank name" }, // blank name dropped
    { name: "B", fragment: "   " }, // blank fragment dropped
    { name: "C", fragment: "Тип: Надпись\n" }, // type optional
    "garbage",
    null,
  ];
  const clean = sanitizePresets(raw);
  assert.deepStrictEqual(clean.map((x) => x.name), ["A", "C"]);
  assert.strictEqual(clean[1].type, undefined);
});

test("sanitizePresets returns [] for non-arrays", () => {
  assert.deepStrictEqual(sanitizePresets(undefined), []);
  assert.deepStrictEqual(sanitizePresets({ a: 1 }), []);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  process.exit(1);
}
