// Unit tests for the pure baseline-exclusion core (src/baselineCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { addExclusion, parseBaseline, toPosix } from "../src/baselineCore";

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

const RULE = "naming/number";
const MSG = "Имя 'Полезное' в единственном числе.";

test("exclusion into a missing file creates the engine-shaped payload", () => {
  const text = addExclusion(undefined, "acme/site/Полезное.yaml", RULE, MSG, "историческое имя");
  const data = JSON.parse(text);
  assert.deepStrictEqual(data.files["acme/site/Полезное.yaml"][RULE][MSG], {
    count: 1,
    reason: "историческое имя",
  });
  assert.strictEqual(data.meta.tool, "xbsl");
  assert.strictEqual(data.meta.format, 1);
  assert.ok(text.endsWith("\n"));
});

test("a bare count entry is bumped and gets the reason", () => {
  const existing = JSON.stringify({ files: { "А.yaml": { [RULE]: { [MSG]: 2 } } } });
  const data = JSON.parse(addExclusion(existing, "А.yaml", RULE, MSG, "так надо"));
  assert.deepStrictEqual(data.files["А.yaml"][RULE][MSG], { count: 3, reason: "так надо" });
});

test("a repeat exclusion overwrites the reason (the last decision wins)", () => {
  const one = addExclusion(undefined, "А.yaml", RULE, MSG, "старая причина");
  const data = JSON.parse(addExclusion(one, "А.yaml", RULE, MSG, "новая причина"));
  assert.deepStrictEqual(data.files["А.yaml"][RULE][MSG], { count: 2, reason: "новая причина" });
});

test("other entries survive and file keys are sorted", () => {
  const existing = JSON.stringify({
    files: { "Я.yaml": { [RULE]: { [MSG]: 1 } } },
    meta: { tool: "xbsllint", format: 1 },
  });
  const text = addExclusion(existing, "А.yaml", "project/identifier", "Сообщение.", "причина");
  const data = JSON.parse(text);
  assert.deepStrictEqual(Object.keys(data.files), ["А.yaml", "Я.yaml"]);
  assert.strictEqual(data.files["Я.yaml"][RULE][MSG], 1);
});

test("the output shape matches the engine formatting (indent 1)", () => {
  const text = addExclusion(undefined, "А.yaml", RULE, MSG, "причина");
  assert.ok(text.startsWith('{\n "meta"') || text.startsWith('{\n "files"'));
});

test("parseBaseline rejects a file without 'files'", () => {
  assert.throws(() => parseBaseline("{}"));
  assert.throws(() => parseBaseline("[1, 2]"));
});

test("parseBaseline of empty text gives a fresh payload", () => {
  const data = parseBaseline(undefined);
  assert.deepStrictEqual(data.files, {});
  const same = parseBaseline("  ");
  assert.deepStrictEqual(same.files, {});
});

test("toPosix flips Windows separators only", () => {
  assert.strictEqual(toPosix("acme\\site\\Полезное.yaml"), "acme/site/Полезное.yaml");
  assert.strictEqual(toPosix("acme/site/Полезное.yaml"), "acme/site/Полезное.yaml");
});

console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
