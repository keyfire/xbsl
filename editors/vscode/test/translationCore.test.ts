// Unit tests for the pure translation-panel core (src/translationCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  DictionaryEntry,
  DictionaryGap,
  DictionaryRow,
  MIN_ENGINE,
  editsPayload,
  filterRows,
  mergeRows,
  outdatedEngine,
  pageOf,
  parseEntries,
  parseGaps,
  parseSetResult,
  parseSummary,
  plannedActions,
  rowKey,
  rowStats,
  setArgs,
  shortKey,
  sortRows,
  translateArgs,
  translationTarget,
  versionArgs,
} from "../src/translationCore";

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

const CFG = { command: "xbsl", usePython: false, root: "D:\\proj\\Acme\\Задачник" };

function entry(over: Partial<DictionaryEntry> = {}): DictionaryEntry {
  return {
    key: "ЗадачиСписок",
    value: "TasksList",
    kind: "token",
    file: "D:\\proj\\xbsl-translation\\010-objects.yaml",
    line: 12,
    scope: "",
    ...over,
  };
}

function gap(over: Partial<DictionaryGap> = {}): DictionaryGap {
  return {
    key: "УдаленоДемоЗадач",
    kind: "token",
    count: 3,
    places: [
      { file: "Main\\Задачи.xbsl", line: 24 },
      { file: "Main\\Задачи.xbsl", line: 57 },
    ],
    suggestion: "",
    resource: false,
    ...over,
  };
}

// ------------------------------------------------------------------ engine arguments

test("the reading run names the root, the mode and the json format", () => {
  assert.deepStrictEqual(translateArgs("entries", CFG, { limit: 0 }), [
    "translate", "D:\\proj\\Acme\\Задачник", "--entries", "--limit", "0", "--format", "json",
  ]);
  assert.deepStrictEqual(translateArgs("gaps", CFG), [
    "translate", "D:\\proj\\Acme\\Задачник", "--gaps", "--format", "json",
  ]);
});

test("the summary run passes no mode flag at all", () => {
  assert.deepStrictEqual(translateArgs("summary", CFG), [
    "translate", "D:\\proj\\Acme\\Задачник", "--format", "json",
  ]);
});

test("limit 0 is passed, not dropped as a falsy value", () => {
  // Dropped, the engine would answer with its own default page and the table would end there.
  assert.ok(translateArgs("entries", CFG, { limit: 0 }).includes("--limit"));
  assert.ok(!translateArgs("entries", CFG, {}).includes("--limit"));
});

test("the filter, the kind and the offset reach the engine", () => {
  assert.deepStrictEqual(translateArgs("gaps", CFG, { filter: "задач", kind: "phrase", offset: 40, limit: 20 }), [
    "translate", "D:\\proj\\Acme\\Задачник", "--gaps",
    "--filter", "задач", "--kind", "phrase", "--limit", "20", "--offset", "40", "--format", "json",
  ]);
  assert.ok(!translateArgs("gaps", CFG, { kind: "any" }).includes("--kind"));
});

test("a python interpreter is invoked through -m xbsl", () => {
  assert.deepStrictEqual(translateArgs("entries", { ...CFG, command: "python", usePython: true }, { limit: 0 }), [
    "-m", "xbsl", "translate", "D:\\proj\\Acme\\Задачник", "--entries", "--limit", "0", "--format", "json",
  ]);
});

test("a write names the edits file and the explicit dictionary", () => {
  assert.deepStrictEqual(setArgs({ ...CFG, dictionary: "D:\\словарь" }, "C:\\tmp\\edits.json"), [
    "translate", "D:\\proj\\Acme\\Задачник", "--set", "C:\\tmp\\edits.json",
    "--dictionary", "D:\\словарь", "--format", "json",
  ]);
});

// --------------------------------------------------------------- the engine the panel needs

test("the version is asked of the same binary the table runs", () => {
  assert.deepStrictEqual(versionArgs(CFG), ["--version"]);
  assert.deepStrictEqual(versionArgs({ ...CFG, command: "python", usePython: true }), ["-m", "xbsl", "--version"]);
});

test("an engine without the panel's commands is named by its version", () => {
  // Older than the minimum: it would answer `--entries` with an argparse dump, so the panel
  // must say so itself.
  assert.strictEqual(outdatedEngine("xbsl 0.69.3"), "0.69.3");
  assert.strictEqual(outdatedEngine(`xbsl ${MIN_ENGINE}`), undefined);
  assert.strictEqual(outdatedEngine("xbsl 0.71.0"), undefined);
  // A pre-release of the minimum carries the commands, so it passes.
  assert.strictEqual(outdatedEngine("xbsl 0.70.0-rc1"), undefined);
  assert.strictEqual(outdatedEngine("xbsl 0.69.3-rc1"), "0.69.3-rc1");
  // The tool names itself before the number: a version elsewhere in the output is not its own.
  assert.strictEqual(outdatedEngine("warning: pymorphy3 0.9.1 is required\nxbsl 0.70.0"), undefined);
  // Output we cannot read is not a verdict: a working engine must not be locked out over it.
  assert.strictEqual(outdatedEngine("command not found"), undefined);
});

// ---------------------------------------------------------------- response parsing

test("entries, gaps and the write result are parsed", () => {
  const entries = parseEntries(JSON.stringify({ dictionary: "D:\\словарь", total: 1, entries: [entry()] }));
  assert.strictEqual(entries.total, 1);
  assert.strictEqual(entries.dictionary, "D:\\словарь");
  assert.strictEqual(parseGaps(JSON.stringify({ total: 2, gaps: [gap()] })).gaps[0].count, 3);
  assert.deepStrictEqual(parseSetResult(JSON.stringify({ changed: 1, added: 2, removed: 0 })), {
    changed: 1, added: 2, removed: 0,
  });
});

test("an engine error is raised, not swallowed as an empty table", () => {
  assert.throws(() => parseEntries(JSON.stringify({ error: "словарь не найден" })), /не найден/);
  assert.throws(() => parseGaps(JSON.stringify({ error: "сломан" })), /сломан/);
  assert.throws(() => parseSetResult(JSON.stringify({ error: "не записать" })), /не записать/);
});

test("output without the expected array is rejected", () => {
  assert.throws(() => parseEntries(JSON.stringify({ total: 3 })));
  assert.throws(() => parseGaps(JSON.stringify({ entries: [] })));
});

test("the coverage totals are read for the header line", () => {
  const totals = parseSummary(JSON.stringify({ totals: { surfaces: 100, translated: 99, missing: 1, coverage: 0.99 } }));
  assert.deepStrictEqual(totals, { surfaces: 100, translated: 99, missing: 1, coverage: 0.99 });
  // A report without totals is not a failure: the table lives without the coverage line.
  assert.strictEqual(parseSummary(JSON.stringify({ problems: [] })).surfaces, 0);
});

// ----------------------------------------------------------------------- the table

test("entries and gaps become one table", () => {
  const rows = mergeRows([entry()], [gap()]);
  assert.strictEqual(rows.length, 2);
  const record = rows.find((r) => r.key === "ЗадачиСписок");
  const missing = rows.find((r) => r.key === "УдаленоДемоЗадач");
  assert.strictEqual(record?.value, "TasksList");
  assert.strictEqual(record?.count, 0);
  assert.strictEqual(missing?.value, "");
  assert.strictEqual(missing?.count, 3);
  // The first place is what the table shows and what the jump follows.
  assert.deepStrictEqual(missing?.place, { file: "Main\\Задачи.xbsl", line: 24 });
});

test("a name and a comment line of the same text are two rows", () => {
  const rows = mergeRows([], [gap({ key: "Итого", kind: "token" }), gap({ key: "Итого", kind: "phrase" })]);
  assert.strictEqual(rows.length, 2);
  assert.notStrictEqual(rowKey("token", "Итого"), rowKey("phrase", "Итого"));
});

test("a record the sources still show as a gap keeps its record and takes the occurrences", () => {
  const rows = mergeRows(
    [entry({ key: "Значок", value: "Icon" })],
    [gap({ key: "Значок", count: 7, suggestion: "Icon", resource: true })]
  );
  assert.strictEqual(rows.length, 1);
  assert.strictEqual(rows[0].value, "Icon");
  assert.strictEqual(rows[0].count, 7);
  assert.strictEqual(rows[0].resource, true);
  assert.strictEqual(rows[0].file, "D:\\proj\\xbsl-translation\\010-objects.yaml");
});

function row(over: Partial<DictionaryRow> = {}): DictionaryRow {
  return {
    kind: "token",
    key: "Задача",
    value: "Task",
    suggestion: "",
    count: 0,
    file: "010-objects.yaml",
    line: 5,
    scope: "",
    resource: false,
    ...over,
  };
}

// -------------------------------------------------------------------------- filter

test("the search looks at the key and at the translation, case-insensitively", () => {
  const rows = [row({ key: "Задача", value: "Task" }), row({ key: "Товар", value: "Product" })];
  assert.deepStrictEqual(filterRows(rows, { search: "зада" }).map((r) => r.key), ["Задача"]);
  assert.deepStrictEqual(filterRows(rows, { search: "PRODUCT" }).map((r) => r.key), ["Товар"]);
  assert.strictEqual(filterRows(rows, { search: "  " }).length, 2);
});

test("only untranslated keeps the empty cells", () => {
  const rows = [row(), row({ key: "Пусто", value: "" })];
  assert.deepStrictEqual(filterRows(rows, { gapsOnly: true }).map((r) => r.key), ["Пусто"]);
});

test("the kind narrows the table, 'any' does not", () => {
  const rows = [row(), row({ key: "строка комментария", kind: "phrase" })];
  assert.deepStrictEqual(filterRows(rows, { kind: "phrase" }).map((r) => r.kind), ["phrase"]);
  assert.strictEqual(filterRows(rows, { kind: "any" }).length, 2);
});

test("the filters add up", () => {
  const rows = [
    row({ key: "Задача", value: "" }),
    row({ key: "Задача этапа", value: "Task" }),
    row({ key: "Товар", value: "" }),
  ];
  assert.deepStrictEqual(filterRows(rows, { search: "задача", gapsOnly: true }).map((r) => r.key), ["Задача"]);
});

// --------------------------------------------------------------------------- order

test("by default the most frequent gaps come first", () => {
  const rows = sortRows([row({ key: "Редкое", value: "", count: 1 }), row({ key: "Частое", value: "", count: 9 }), row()]);
  assert.deepStrictEqual(rows.map((r) => r.key), ["Частое", "Редкое", "Задача"]);
});

test("the direction turns the order around", () => {
  const rows = [row({ key: "Б" }), row({ key: "А" })];
  assert.deepStrictEqual(sortRows(rows, "key", "asc").map((r) => r.key), ["А", "Б"]);
  assert.deepStrictEqual(sortRows(rows, "key", "desc").map((r) => r.key), ["Б", "А"]);
});

test("equal values are broken by the key, so a redraw does not shuffle the table", () => {
  const rows = [row({ key: "Яблоко", count: 2 }), row({ key: "Ананас", count: 2 }), row({ key: "Берёза", count: 2 })];
  assert.deepStrictEqual(sortRows(rows, "count", "desc").map((r) => r.key), ["Ананас", "Берёза", "Яблоко"]);
});

test("sorting leaves the source array alone", () => {
  const rows = [row({ key: "Б" }), row({ key: "А" })];
  sortRows(rows, "key", "asc");
  assert.deepStrictEqual(rows.map((r) => r.key), ["Б", "А"]);
});

// ------------------------------------------------------------------- page and stats

test("a page is cut to the asked size, 0 means everything", () => {
  const rows = [row({ key: "1" }), row({ key: "2" }), row({ key: "3" })];
  assert.strictEqual(pageOf(rows, 2).length, 2);
  assert.strictEqual(pageOf(rows, 0).length, 3);
  assert.strictEqual(pageOf(rows, 10).length, 3);
});

test("the header counts the rows, the gaps among them and what is shown", () => {
  const rows = [row(), row({ key: "П", value: "" }), row({ key: "Р", value: "" })];
  assert.deepStrictEqual(rowStats(rows, 2), { total: 3, gaps: 2, shown: 2 });
  assert.deepStrictEqual(rowStats(rows, 200), { total: 3, gaps: 2, shown: 3 });
});

// --------------------------------------------------------------------------- write

test("the edits file is the shape the engine reads", () => {
  const payload = JSON.parse(editsPayload([{ key: "Задача", value: "Task", kind: "token" }]));
  assert.deepStrictEqual(payload, [{ key: "Задача", value: "Task", kind: "token" }]);
});

test("an empty value survives the payload - that is how a record is removed", () => {
  assert.deepStrictEqual(JSON.parse(editsPayload([{ key: "Задача", value: "", kind: "token" }])), [
    { key: "Задача", value: "", kind: "token" },
  ]);
});

// ------------------------------------------------------------ the finding of the rule

test("the dictionary key is taken from the diagnostic data", () => {
  assert.deepStrictEqual(translationTarget({ translation: { kind: "token", key: "Товар" } }), {
    kind: "token",
    key: "Товар",
  });
  assert.deepStrictEqual(
    translationTarget({ translation: { kind: "phrase", key: "строка", suggestion: "line" } }),
    { kind: "phrase", key: "строка", suggestion: "line" }
  );
});

test("a diagnostic without the translation data offers nothing", () => {
  assert.strictEqual(translationTarget(undefined), undefined);
  assert.strictEqual(translationTarget({ fix: { start: 1, end: 2, newText: "x" } }), undefined);
  assert.strictEqual(translationTarget({ translation: { kind: "word", key: "Товар" } }), undefined);
  assert.strictEqual(translationTarget({ translation: { kind: "token", key: "" } }), undefined);
  assert.strictEqual(translationTarget({ translation: { kind: "token" } }), undefined);
});

test("an empty suggestion is not carried as a suggestion", () => {
  assert.deepStrictEqual(translationTarget({ translation: { kind: "token", key: "Товар", suggestion: "" } }), {
    kind: "token",
    key: "Товар",
  });
});

test("a suggestion puts the one-click repair first", () => {
  assert.deepStrictEqual(plannedActions({ kind: "token", key: "Товар", suggestion: "Product" }), [
    { action: "apply", value: "Product" },
    { action: "ask" },
    { action: "open" },
  ]);
});

test("without a suggestion the menu is the dialog and the panel", () => {
  assert.deepStrictEqual(plannedActions({ kind: "phrase", key: "строка комментария" }), [
    { action: "ask" },
    { action: "open" },
  ]);
});

test("a long key is trimmed for the menu title", () => {
  const long = "очень длинная строка комментария, которую словарь ещё не покрывает";
  assert.ok(shortKey(long).length <= 48);
  assert.ok(shortKey(long).endsWith("..."));
  assert.strictEqual(shortKey("Товар"), "Товар");
  // A comment line broken over the source keeps one line in the menu.
  assert.strictEqual(shortKey("две\n  строки"), "две строки");
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  process.exit(1);
}
