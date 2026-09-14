// Unit tests for the pure workspace-run core (src/workspaceCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import * as path from "path";
import { computeRange, FixEdit, RawDiag } from "../src/report";
import { anchorKey, fixIndex } from "../src/codeActionsCore";
import {
  DICTIONARY_DIR,
  DICTIONARY_FILE,
  dictionaryOutsideRoot,
  discoverDictionary,
  groupReportByFile,
  isDictionaryFile,
  mergeReports,
  PathKind,
  readByRun,
  resolveMessageLanguage,
} from "../src/workspaceCore";
import { DICTIONARY_PATTERNS } from "../src/lspDocumentsCore";
import { needsServerRestart, SERVER_ARG_SETTINGS } from "../src/lspRestartCore";

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

test("groupReportByFile: раскладка по файлам, относительные пути – от рабочей папки", () => {
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

test("регрессия: сохранённый raw проверки всего проекта даёт правку по якорю диагностики закрытого файла", () => {
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

// --- what a workspace run reads: the root and the dictionary outside it -----------------------

const repository = path.resolve("repo");
const projectRoot = path.join(repository, "src", "app");
const dictionaryDir = path.join(repository, DICTIONARY_DIR);

// A disk of the given directories and files: every parent of an entry is a directory too.
function disk(dirs: string[], files: string[] = []): (p: string) => PathKind {
  const directories = new Set<string>();
  for (const entry of [...dirs, ...files.map((f) => path.dirname(f))]) {
    for (let current = entry; ; current = path.dirname(current)) {
      directories.add(current);
      if (path.dirname(current) === current) {
        break;
      }
    }
  }
  const plain = new Set(files);
  return (p) => (plain.has(p) ? "file" : directories.has(p) ? "dir" : undefined);
}

test("the dictionary is discovered next to the root or above it, the way the engine finds it", () => {
  assert.strictEqual(discoverDictionary(projectRoot, disk([projectRoot, dictionaryDir])), dictionaryDir);
  // the nearest one wins: a dictionary inside the root is found before the one above
  const inside = path.join(projectRoot, DICTIONARY_DIR);
  assert.strictEqual(discoverDictionary(projectRoot, disk([inside, dictionaryDir])), inside);
});

test("a single-file dictionary is discovered, and a directory of the file's name is not taken for it", () => {
  const single = path.join(repository, DICTIONARY_FILE);
  assert.strictEqual(discoverDictionary(projectRoot, disk([projectRoot], [single])), single);
  assert.strictEqual(discoverDictionary(projectRoot, disk([projectRoot, single])), undefined);
  assert.strictEqual(discoverDictionary(projectRoot, disk([projectRoot])), undefined);
});

test("the names match the patterns the LSP client selects the dictionary by", () => {
  assert.deepStrictEqual([...DICTIONARY_PATTERNS], [`**/${DICTIONARY_DIR}/**/*.yaml`, `**/${DICTIONARY_FILE}`]);
});

test("only a dictionary outside the root is checked apart: the run over the root reads one inside it", () => {
  assert.strictEqual(dictionaryOutsideRoot(projectRoot, dictionaryDir), dictionaryDir);
  assert.strictEqual(dictionaryOutsideRoot(projectRoot, path.join(projectRoot, DICTIONARY_DIR)), undefined);
  assert.strictEqual(dictionaryOutsideRoot(projectRoot, undefined), undefined);
});

test("a run reads the root and the dictionary checked apart, and nothing else", () => {
  const scope = { root: projectRoot, dictionary: dictionaryDir };
  assert.ok(readByRun(path.join(projectRoot, "Main", "Tasks.xbsl"), scope));
  assert.ok(readByRun(path.join(dictionaryDir, "batch", "020-entries.yaml"), scope));
  // a copy of the sources, a sibling with a longer name, a hidden directory the engine skips
  assert.ok(!readByRun(path.join(repository, "examples", "src", "app", "Main", "Tasks.xbsl"), scope));
  assert.ok(!readByRun(path.join(repository, "src", "application", "Tasks.xbsl"), scope));
  assert.ok(!readByRun(path.join(projectRoot, ".backup", "Tasks.xbsl"), scope));
  // without the dictionary run its files are not the run's to clear
  assert.ok(!readByRun(path.join(dictionaryDir, "010-entries.yaml"), { root: projectRoot }));
});

test("a single-file dictionary is read as that one file", () => {
  const single = path.join(repository, DICTIONARY_FILE);
  assert.ok(readByRun(single, { root: projectRoot, dictionary: single }));
  assert.ok(!readByRun(path.join(repository, "other.yaml"), { root: projectRoot, dictionary: single }));
});

if (process.platform === "win32") {
  test("on Windows the drive letter and the case of a directory do not split one path in two", () => {
    // VS Code hands a document over as d:\..., the setting may say D:\...
    const lower = projectRoot.replace(/^[A-Z]:/, (drive) => drive.toLowerCase());
    assert.ok(readByRun(path.join(lower, "Main", "Tasks.xbsl"), { root: projectRoot.toUpperCase() }));
  });
}

test("the buffer check takes the yaml files of the dictionary and nothing next to them", () => {
  assert.ok(isDictionaryFile(path.join(dictionaryDir, "010-entries.yaml"), dictionaryDir));
  assert.ok(isDictionaryFile(path.join(dictionaryDir, "batch", "020-entries.YAML"), dictionaryDir));
  assert.ok(!isDictionaryFile(path.join(dictionaryDir, "README.md"), dictionaryDir));
  assert.ok(!isDictionaryFile(path.join(repository, `my-${DICTIONARY_DIR}`, "010-entries.yaml"), dictionaryDir));
  assert.ok(!isDictionaryFile(path.join(projectRoot, "Tasks.yaml"), dictionaryDir));
  assert.ok(!isDictionaryFile(path.join(dictionaryDir, "010-entries.yaml"), undefined));
});

test("the reports of the two runs add up to one", () => {
  const merged = mergeReports([
    { diagnostics: [diag("a.xbsl", 1, 1, "x")], summary: { files: 10, diagnostics: 1, errors: 0, warnings: 1 } },
    { diagnostics: [diag("b.yaml", 2, 2, "y"), diag("c.yaml", 3, 3, "y")], summary: { files: 5, diagnostics: 2, errors: 1, warnings: 1 } },
  ]);
  assert.deepStrictEqual(merged.diagnostics.map((d) => d.path), ["a.xbsl", "b.yaml", "c.yaml"]);
  assert.deepStrictEqual(merged.summary, { files: 15, diagnostics: 3, errors: 1, warnings: 2 });
  assert.strictEqual(mergeReports([{ diagnostics: [] }]).summary, undefined);
});

// --- lspRestartCore: a settings change that re-arguments the server -----------------------

test("a projectRoot change asks for a server restart", () => {
  assert.ok(needsServerRestart((s) => s === "xbsl.projectRoot"));
});

test("every setting of the command line asks for a restart", () => {
  for (const section of SERVER_ARG_SETTINGS) {
    assert.ok(needsServerRestart((s) => s === section), section);
  }
});

test("a setting that does not reach the command line leaves the server alone", () => {
  // these are applied by the client (or by the server on request), so a restart would only
  // cost the project index
  for (const section of ["xbsl.workspaceLint", "xbsl.deploy.appId", "xbsl.docs.language"]) {
    assert.ok(!needsServerRestart((s) => s === section), section);
  }
});

test("asking for the CI job's rule set asks for a server restart", () => {
  // the flag reaches the server as an ARGUMENT, so a setting switched on in a live window
  // would otherwise do nothing at all until the next reload - which is the failure this
  // whole module exists to prevent
  assert.ok(needsServerRestart((s) => s === "xbsl.linter.asCi"));
  assert.ok(needsServerRestart((s) => s === "xbsl.linter.asCiJob"));
});

test("an unrelated extension's settings are ignored", () => {
  assert.ok(!needsServerRestart((s) => s.startsWith("editor.")));
});

// -----------------------------------------------------------------------------
// The summary stays below every test: a test registered after it would run without a say in
// the exit code.

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
