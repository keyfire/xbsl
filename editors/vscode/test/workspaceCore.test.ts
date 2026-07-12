// Unit tests for the pure workspace-run core (src/workspaceCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import * as path from "path";
import { computeRange, FixEdit, RawDiag } from "../src/report";
import { anchorKey, fixIndex } from "../src/codeActionsCore";
import { groupReportByFile } from "../src/workspaceCore";

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

// --- регрессия: правки для файла, открытого ПОСЛЕ воркспейс-прогона ------------------------
// UX-щель: файл закрыт во время прогона (его диагностика построена без текста строки,
// makeDiagnostic(d, undefined)), позже открыт чистым – `--stdin` не гоняется, и снапшот
// Quick Fix обязан восстанавливаться из сохранённого сырого отчёта. Правка должна
// находиться по якорю показанной диагностики.

test("регрессия: сохранённый raw воркспейс-прогона даёт правку по якорю диагностики закрытого файла", () => {
  const fix: FixEdit = { start: 20, end: 23, newText: "" };
  const d = diag("Модуль.xbsl", 2, 14, "whitespace/trailing", fix);
  const grouped = groupReportByFile([d, diag("Модуль.xbsl", 5, 1, "code/unused-loop-var")], folder, () => false);

  // То, что хранится в workspaceResults и на открытии кладётся в fixStore.
  const raw = grouped.get(path.join(folder, "Модуль.xbsl"))!;

  // Диагностика файла, закрытого при прогоне, строится без текста строки.
  const span = computeRange(undefined, d.line, d.col);
  // Открытие файла: провайдер ищет правку по якорю range.start показанной диагностики.
  const providerKey = anchorKey(span.sl + 1, span.sc + 1, d.rule);
  assert.deepStrictEqual(fixIndex(raw).get(providerKey), fix);
});

// -----------------------------------------------------------------------------

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
