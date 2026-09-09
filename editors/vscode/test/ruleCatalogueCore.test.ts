// Unit tests for the rule-catalogue parser (src/ruleCatalogueCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { parseRuleCatalogue } from "../src/ruleCatalogueCore";

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

const JSON_OUT = JSON.stringify([
  {
    id: "style/line-length", title: "Строка длиннее 120 символов", tier: "B", scope: "file",
    severity: "warning", enabled_by_default: true, off_reason: "",
    params: [{
      name: "max-length", value: 100, default: 120,
      env: "XBSL_STYLE_LINE_LENGTH_MAX_LENGTH", doc: "предельная длина строки в символах",
    }],
  },
  {
    id: "yaml/duplicate-subtree", title: "Поддерево повторяет поддерево другого файла",
    tier: "A", scope: "project", severity: "warning", enabled_by_default: false,
    off_reason: "мера одинаковости - решение проекта",
  },
]);

// The human listing of an engine that does not know `--list-rules --format json`.
const TEXT_OUT = [
  "A off yaml/duplicate-subtree         warning Поддерево повторяет поддерево другого файла",
  "       выключено, потому что: мера одинаковости - решение проекта",
  "       параметр min-nodes = 40 (умолчание 40, env XBSL_YAML_DUPLICATE_SUBTREE_MIN_NODES) – размер",
  "B     style/line-length              warning Строка длиннее 120 символов",
].join("\n");

test("the json answer carries the parameters and the off reason", () => {
  const map = parseRuleCatalogue(JSON_OUT);
  const line = map.get("style/line-length");
  assert.strictEqual(line?.tier, "B");
  assert.strictEqual(line?.level, "warning");
  assert.strictEqual(line?.offByDefault, false);
  // the value in force and the shipped default are separate: the panel marks an overridden one
  assert.deepStrictEqual(line?.params?.map((p) => [p.name, p.value, p.default]), [["max-length", 100, 120]]);
  const dup = map.get("yaml/duplicate-subtree");
  assert.strictEqual(dup?.offByDefault, true);
  assert.strictEqual(dup?.offReason, "мера одинаковости - решение проекта");
  assert.strictEqual(dup?.params, undefined); // a rule without parameters carries no empty list
});

test("an older engine prints the listing and still gives every rule", () => {
  const map = parseRuleCatalogue(TEXT_OUT);
  assert.deepStrictEqual([...map.keys()].sort(), ["style/line-length", "yaml/duplicate-subtree"]);
  assert.strictEqual(map.get("yaml/duplicate-subtree")?.offByDefault, true);
  assert.strictEqual(map.get("yaml/duplicate-subtree")?.title, "Поддерево повторяет поддерево другого файла");
  // the continuation lines are prose in the language of the run - they are not rules
  assert.strictEqual(map.get("style/line-length")?.params, undefined);
});

test("a run that answered nothing leaves an empty catalogue, not a broken one", () => {
  assert.strictEqual(parseRuleCatalogue("").size, 0);
  assert.strictEqual(parseRuleCatalogue("Traceback (most recent call last):").size, 0);
  assert.strictEqual(parseRuleCatalogue("[]").size, 0);
});

console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
