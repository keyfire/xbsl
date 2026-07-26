// Unit tests for the pure Quick Fix core (src/codeActionsCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { computeRange, RawDiag } from "../src/report";
import {
  anchorKey,
  collectFixes,
  fixIndex,
  selectNonOverlapping,
} from "../src/codeActionsCore";

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

function diag(line: number, col: number, rule: string, fix?: { start: number; end: number; newText: string }): RawDiag {
  return { path: "X.xbsl", line, col, rule, severity: "warning", message: "m", fix };
}

// --- anchorKey / fixIndex ---------------------------------------------------

test("fixIndex: только диагностики с правкой, ключ по (строка, колонка, правило)", () => {
  const diags = [
    diag(2, 14, "whitespace/trailing", { start: 20, end: 23, newText: "" }),
    diag(1, 4, "typography/ellipsis", { start: 3, end: 4, newText: "..." }),
    diag(5, 9, "code/unused-loop-var"), // no fix - not indexed
  ];
  const idx = fixIndex(diags);
  assert.strictEqual(idx.size, 2);
  assert.deepStrictEqual(idx.get(anchorKey(1, 4, "typography/ellipsis")), {
    start: 3,
    end: 4,
    newText: "...",
  });
  assert.strictEqual(idx.get(anchorKey(5, 9, "code/unused-loop-var")), undefined);
});

// --- collectFixes -----------------------------------------------------------

test("collectFixes: плоский список только чинимых, порядок сохранён", () => {
  const diags = [
    diag(1, 1, "a", { start: 0, end: 1, newText: "" }),
    diag(2, 1, "b"),
    diag(3, 1, "c", { start: 5, end: 6, newText: "x" }),
  ];
  const items = collectFixes(diags);
  assert.strictEqual(items.length, 2);
  assert.deepStrictEqual(items.map((f) => f.rule), ["a", "c"]);
  assert.deepStrictEqual(items[1], { start: 5, end: 6, newText: "x", rule: "c" });
});

// --- selectNonOverlapping ---------------------------------------------------

test("selectNonOverlapping: непересекающиеся сохраняются", () => {
  const items = collectFixes([
    diag(1, 1, "a", { start: 0, end: 2, newText: "" }),
    diag(2, 1, "b", { start: 4, end: 6, newText: "" }),
  ]);
  assert.strictEqual(selectNonOverlapping(items).length, 2);
});

test("selectNonOverlapping: пересечение – побеждает более ранний старт", () => {
  const items = collectFixes([
    diag(1, 3, "b", { start: 2, end: 4, newText: "Y" }),
    diag(1, 1, "a", { start: 0, end: 3, newText: "X" }),
  ]);
  const chosen = selectNonOverlapping(items);
  assert.strictEqual(chosen.length, 1);
  assert.strictEqual(chosen[0].rule, "a");
});

test("selectNonOverlapping: касание встык (end == next.start) не считается пересечением", () => {
  const items = collectFixes([
    diag(1, 1, "a", { start: 0, end: 3, newText: "" }),
    diag(1, 4, "b", { start: 3, end: 5, newText: "" }),
  ]);
  assert.strictEqual(selectNonOverlapping(items).length, 2);
});

// --- matching contract: range.start from computeRange restores (line, col) -------------
// The provider looks up a fix by anchorKey(range.start.line+1, range.start.character+1, rule).
// It must match the key under which the fix landed in the index (d.line, d.col, d.rule).

test("anchor round-trip: computeRange(range).start+1 == (line, col) диагностики", () => {
  const lineText = "    возврат 1  "; // trailing spaces at position col 14 (1-based)
  const d = diag(2, 14, "whitespace/trailing", { start: 20, end: 22, newText: "" });
  const span = computeRange(lineText, d.line, d.col);
  const providerKey = anchorKey(span.sl + 1, span.sc + 1, "whitespace/trailing");
  assert.strictEqual(providerKey, anchorKey(d.line, d.col, d.rule));
  assert.ok(fixIndex([d]).has(providerKey));
});

test("anchor round-trip: типографский символ в комментарии", () => {
  const lineText = "// многоточие… и текст";
  const col = lineText.indexOf("…") + 1; // 1-based column of the character
  const d = diag(1, col, "typography/ellipsis", { start: col - 1, end: col, newText: "..." });
  const span = computeRange(lineText, d.line, d.col);
  assert.strictEqual(
    anchorKey(span.sl + 1, span.sc + 1, "typography/ellipsis"),
    anchorKey(d.line, d.col, d.rule)
  );
});

// -----------------------------------------------------------------------------

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
