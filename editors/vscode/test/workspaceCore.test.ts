// Unit tests for the pure workspace-run core (src/workspaceCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import * as path from "path";
import { computeRange, FixEdit, RawDiag } from "../src/report";
import { anchorKey, fixIndex } from "../src/codeActionsCore";
import { groupReportByFile, resolveMessageLanguage } from "../src/workspaceCore";

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

function diag(p: string, line: number, col: number, rule: string, fix?: FixEdit): RawDiag {
  return { path: p, line, col, rule, severity: "warning", message: "m", fix };
}

const folder = path.resolve("ws");

// --- groupReportByFile --------------------------------------------------------------------

test("groupReportByFile: раскладка по файлам, относительные пути – от папки воркспейса", () => {
  const absolute = path.join(folder, "Модуль.xbsl");
  const grouped = groupReportByFile(
    [diag("Форма.yaml", 1, 2, "a"), diag(absolute, 3, 4, "b"), diag("Форма.yaml", 5, 6, "c")],
    folder,
    () => false
  );
  assert.strictEqual(grouped.size, 2);
  assert.deepStrictEqual(
    grouped.get(path.join(folder, "Форма.yaml"))!.map((d) => d.rule),
    ["a", "c"]
  );
  assert.deepStrictEqual(grouped.get(absolute)!.map((d) => d.rule), ["b"]);
});

test("groupReportByFile: выключенные правила выпадают, файл только с ними – целиком", () => {
  const grouped = groupReportByFile(
    [diag("Модуль.xbsl", 1, 1, "off/rule"), diag("Форма.yaml", 2, 2, "off/rule"), diag("Форма.yaml", 3, 3, "a")],
    folder,
    (rule) => rule === "off/rule"
  );
  assert.strictEqual(grouped.size, 1);
  assert.deepStrictEqual(grouped.get(path.join(folder, "Форма.yaml"))!.map((d) => d.rule), ["a"]);
});

// --- regression: fixes for a file opened AFTER a workspace run -----------------------------
// UX gap: the file is closed during the run (its diagnostic is built without the line text,
// makeDiagnostic(d, undefined)), later opened clean - `--stdin` is not run, and the Quick Fix
// snapshot must be restored from the saved raw report. The fix must be found by the anchor
// of the displayed diagnostic.

test("регрессия: сохранённый raw воркспейс-прогона даёт правку по якорю диагностики закрытого файла", () => {
  const fix: FixEdit = { start: 20, end: 23, newText: "" };
  const d = diag("Модуль.xbsl", 2, 14, "whitespace/trailing", fix);
  const grouped = groupReportByFile([d, diag("Модуль.xbsl", 5, 1, "code/unused-loop-var")], folder, () => false);

  // What is stored in workspaceResults and put into fixStore on open.
  const raw = grouped.get(path.join(folder, "Модуль.xbsl"))!;

  // A diagnostic of a file closed during the run is built without the line text.
  const span = computeRange(undefined, d.line, d.col);
  // Opening the file: the provider looks up the fix by the shown diagnostic's range.start anchor.
  const providerKey = anchorKey(span.sl + 1, span.sc + 1, d.rule);
  assert.deepStrictEqual(fixIndex(raw).get(providerKey), fix);
});

test("the message language follows the display language when the setting is empty", () => {
  assert.equal(resolveMessageLanguage("", "ru"), "ru");
  assert.equal(resolveMessageLanguage("", "ru-RU"), "ru");
  assert.equal(resolveMessageLanguage("", "en"), "en");
  assert.equal(resolveMessageLanguage("", "de"), "en"); // the engine has no German messages
  assert.equal(resolveMessageLanguage("", ""), "en");
});

test("an explicit language setting wins over the display language", () => {
  assert.equal(resolveMessageLanguage("ru", "en"), "ru");
  assert.equal(resolveMessageLanguage(" en ", "ru"), "en");
});

// -----------------------------------------------------------------------------

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
