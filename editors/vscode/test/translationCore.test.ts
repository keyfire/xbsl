// Unit tests for the pure translation-panel core (src/translationCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  ColumnWidths,
  DEFAULT_COLUMN_WIDTHS,
  DictionaryEntry,
  DictionaryGap,
  DictionaryRow,
  MIN_COLUMN_WIDTHS,
  MIN_ENGINE,
  editsPayload,
  filterRows,
  guardConcurrent,
  mergeRows,
  outdatedEngine,
  pageOf,
  parseEntries,
  parseGaps,
  parseSetResult,
  parseSuggest,
  parseSummary,
  plannedActions,
  refusalText,
  resetColumnWidth,
  resizeColumn,
  rowHint,
  rowKey,
  rowStats,
  sanitizeColumnWidths,
  setArgs,
  shortKey,
  sortRows,
  suggestArgs,
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
  // 0.70.0 answers the table commands but knows no literals plane: the panel over it would
  // draw a dictionary that looks complete while every string literal stays invisible.
  assert.strictEqual(outdatedEngine("xbsl 0.70.0"), "0.70.0");
  assert.strictEqual(outdatedEngine(`xbsl ${MIN_ENGINE}`), undefined);
  assert.strictEqual(outdatedEngine("xbsl 0.72.1"), undefined);
  // A pre-release of the minimum carries the commands, so it passes.
  assert.strictEqual(outdatedEngine("xbsl 0.72.0-rc1"), undefined);
  assert.strictEqual(outdatedEngine("xbsl 0.71.0-rc1"), "0.71.0-rc1");
  // The tool names itself before the number: a version elsewhere in the output is not its own.
  assert.strictEqual(outdatedEngine("warning: pymorphy3 0.9.1 is required\nxbsl 0.72.0"), undefined);
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
    changed: 1, added: 2, removed: 0, refused: [],
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
  const totals = parseSummary(JSON.stringify({
    totals: { surfaces: 100, translated: 99, missing: 1, coverage: 0.99, literals_translated: 8, missing_literals: 3 },
  }));
  assert.deepStrictEqual(totals, {
    surfaces: 100, translated: 99, missing: 1, coverage: 0.99, literalsTranslated: 8, literalsMissing: 3,
  });
  // The literals stand apart from the coverage on purpose: a project can be at 100% of its
  // names and still ship Cyrillic messages, and the header must be able to say so.
  assert.strictEqual(totals.coverage, 0.99);
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

// ------------------------------------------------------------------- the literals plane

test("a literal record is read as its own kind, written the way the source writes it", () => {
  // The engine's answer to `translate --entries --kind literal`: the key and the value are the
  // text between the quotes, so an inner quote arrives as \" - and must survive untouched.
  const answer = parseEntries(
    JSON.stringify({
      dictionary: "D:\\proj\\xbsl-translation",
      total: 1,
      entries: [entry({ key: 'Заявка \\"срочная\\" принята', value: 'A \\"rush\\" request accepted', kind: "literal" })],
    })
  );
  assert.strictEqual(answer.entries[0].kind, "literal");
  assert.strictEqual(answer.entries[0].key, 'Заявка \\"срочная\\" принята');
  assert.strictEqual(answer.entries[0].value, 'A \\"rush\\" request accepted');
});

test("a literal gap arrives without a platform spelling", () => {
  // The platform tables spell NAMES; between the quotes stands as often a whole message, so
  // the engine offers nothing there and the empty cell must stay empty.
  const answer = parseGaps(
    JSON.stringify({ total: 1, gaps: [gap({ key: "Шаги задачи", kind: "literal", count: 2, suggestion: "" })] })
  );
  assert.strictEqual(answer.gaps[0].kind, "literal");
  assert.strictEqual(answer.gaps[0].suggestion, "");
  assert.strictEqual(mergeRows([], answer.gaps)[0].suggestion, "");
});

test("a name and a literal of the same text are two rows", () => {
  const rows = mergeRows([], [gap({ key: "Товары", kind: "token" }), gap({ key: "Товары", kind: "literal" })]);
  assert.strictEqual(rows.length, 2);
  assert.notStrictEqual(rowKey("token", "Товары"), rowKey("literal", "Товары"));
});

test("the literal kind narrows the table and reaches the engine", () => {
  const rows = [row(), row({ key: "Заявка принята", kind: "literal", value: "" })];
  assert.deepStrictEqual(filterRows(rows, { kind: "literal" }).map((r) => r.key), ["Заявка принята"]);
  assert.strictEqual(filterRows(rows, { kind: "any" }).length, 2);
  assert.deepStrictEqual(translateArgs("gaps", CFG, { kind: "literal", limit: 5 }), [
    "translate", "D:\\proj\\Acme\\Задачник", "--gaps", "--kind", "literal", "--limit", "5", "--format", "json",
  ]);
});

test("a literal counts in the header like every other row", () => {
  const rows = [row(), row({ key: "Заявка принята", kind: "literal", value: "" })];
  assert.deepStrictEqual(rowStats(filterRows(rows, {}), 200), { total: 2, gaps: 1, shown: 2 });
});

// --------------------------------------------------------------- a refused literal write

test("a refused edit is read out of the write answer, not swallowed as a success", () => {
  // The engine answers with the refusal AND with what it did write - a batch is not all or
  // nothing. Read as a plain success, the status line would report an update over an entry
  // that never landed.
  const answer = parseSetResult(
    JSON.stringify({
      changed: 0,
      added: 1,
      removed: 0,
      refused: [
        { key: "Шаги задачи", kind: "literal", reason: "обратный слеш в конце: он съест закрывающую кавычку" },
      ],
    })
  );
  assert.strictEqual(answer.added, 1);
  assert.strictEqual(answer.refused.length, 1);
  assert.strictEqual(answer.refused[0].kind, "literal");
  assert.deepStrictEqual(parseSetResult(JSON.stringify({ changed: 1, added: 0, removed: 0 })).refused, []);
});

test("the refusal message names the entry and the reason the engine gave", () => {
  const text = refusalText([
    { key: "Заявка принята", kind: "literal", reason: "кавычка закрывает литерал раньше времени" },
  ]);
  assert.ok(text.includes("Заявка принята"));
  assert.ok(text.includes("кавычка закрывает литерал раньше времени"));
  // Several refusals of one batch read as one line.
  assert.ok(
    refusalText([
      { key: "Товары", kind: "literal", reason: "перевод строки" },
      { key: "Заявки", kind: "literal", reason: "перевод строки" },
    ]).includes("; ")
  );
});

test("a long literal does not push the reason out of the message", () => {
  // In a real project a literal runs to hundreds of characters; untrimmed it would fill the
  // message box and leave the only actionable half - the reason - off the screen.
  const long = "Задача ".repeat(100);
  const text = refusalText([{ key: long, kind: "literal", reason: "перевод строки" }]);
  assert.ok(text.length < 120);
  assert.ok(text.endsWith("перевод строки"));
});

// ------------------------------------------------------ machine-translation suggestions

test("the suggest run passes the mode flag and the provider, never a key", () => {
  const args = suggestArgs({ command: "xbsl", usePython: false, root: "C:/p" }, "google");
  assert.ok(args.includes("--suggest"), "the mode flag is passed");
  assert.ok(args.includes("--provider") && args.includes("google"), "the provider is passed");
  // The key travels in the environment of the spawned process, never on its command line -
  // a process list is visible to every other process on the machine.
  assert.ok(!args.some((a) => a.includes("XBSL_TRANSLATE")), "no key ever lands in the arguments");
});

test("without a provider the engine is left to pick its own", () => {
  assert.ok(!suggestArgs(CFG).includes("--provider"));
});

test("an explicit dictionary reaches the suggest run, like every other run", () => {
  assert.ok(suggestArgs({ ...CFG, dictionary: "D:\\словарь" }).includes("--dictionary"));
});

test("a python interpreter runs the suggest mode through -m xbsl", () => {
  assert.deepStrictEqual(suggestArgs({ ...CFG, command: "python", usePython: true }), [
    "-m", "xbsl", "translate", CFG.root, "--suggest", "--format", "json",
  ]);
});

// The engine's actual --suggest --format json answer: `rows` was the brief's placeholder name,
// the command prints `suggestions`, and refusals live nested under `machine` with their reason -
// the panel is written for what the engine prints, not for the brief's first draft of it.
test("the suggest answer is read from 'suggestions', the field the engine actually prints", () => {
  const answer = parseSuggest(JSON.stringify({
    dictionary: "D:\\словарь",
    machine: { cached: 3, requested: 2, refused: 1, refusals: [] },
    suggestions: [{ key: "АдресСайта", value: "SiteAddress", kind: "token" }],
  }));
  assert.strictEqual(answer.dictionary, "D:\\словарь");
  assert.strictEqual(answer.cached, 3, "counts parsed");
  assert.strictEqual(answer.requested, 2, "counts parsed");
  assert.strictEqual(answer.refused, 1, "counts parsed");
  assert.strictEqual(answer.rows.length, 1);
  assert.strictEqual(answer.rows[0].value, "SiteAddress", "the suggestion is parsed");
  assert.strictEqual(answer.rows[0].kind, "token");
});

test("a refusal carries its reason, not just the count - it explains what the number cannot", () => {
  const answer = parseSuggest(JSON.stringify({
    machine: {
      cached: 0, requested: 1, refused: 1,
      refusals: [{ kind: "token", key: "Товар", reason: "имя уже занято другим переводом" }],
    },
    suggestions: [],
  }));
  assert.strictEqual(answer.refusals.length, 1);
  assert.strictEqual(answer.refusals[0].key, "Товар");
  assert.strictEqual(answer.refusals[0].reason, "имя уже занято другим переводом");
  // The same message builder as a refused --set edit: the shape is identical, and the reader
  // does not care which run refused the entry.
  assert.ok(refusalText(answer.refusals).includes("имя уже занято другим переводом"));
});

test("an engine error from --suggest is raised, not read as an empty answer", () => {
  // `_machine_refused`: no provider is configured, or the choice is ambiguous - reported
  // before the dictionary is even touched.
  assert.throws(() => parseSuggest(JSON.stringify({ error: "ни один сервис не настроен" })), /не настроен/);
});

test("a missing 'machine' or 'suggestions' answers as nothing found, not a crash", () => {
  const answer = parseSuggest(JSON.stringify({}));
  assert.deepStrictEqual(answer.rows, []);
  assert.deepStrictEqual(answer.refusals, []);
  assert.strictEqual(answer.cached, 0);
  assert.strictEqual(answer.requested, 0);
  assert.strictEqual(answer.refused, 0);
});

// ------------------------------------------------------ the one ghost the empty cell offers

test("rowHint: the platform's own spelling wins when both sources have one", () => {
  const r = row({ value: "", suggestion: "Product", machineSuggestion: "Item" });
  assert.deepStrictEqual(rowHint(r), { value: "Product", fromMachine: false });
});

test("rowHint: the machine suggestion is offered only when the platform has none", () => {
  const r = row({ value: "", suggestion: "", machineSuggestion: "Item" });
  assert.deepStrictEqual(rowHint(r), { value: "Item", fromMachine: true });
});

test("rowHint: a translated row offers nothing, whatever else it still carries", () => {
  // The two used to live in separate columns and could sit next to a real answer; now they
  // share the one field a hand-typed value already fills, so a written row must silence both.
  const r = row({ value: "Product", suggestion: "Product", machineSuggestion: "Item" });
  assert.strictEqual(rowHint(r), undefined);
});

test("rowHint: nothing to offer when neither source has anything", () => {
  assert.strictEqual(rowHint(row({ value: "", suggestion: "" })), undefined);
});

// -------------------------------------------------- the light bulb on a literal finding

test("a literal finding becomes a literal dictionary entry", () => {
  assert.deepStrictEqual(translationTarget({ translation: { kind: "literal", key: "Заявка принята" } }), {
    kind: "literal",
    key: "Заявка принята",
  });
});

test("a literal is never offered the platform's spelling in one click", () => {
  // A table answer between the quotes would be a guess dressed as an authority, so the
  // suggestion is dropped where the finding is read and the menu stays the dialog and the panel.
  const target = translationTarget({ translation: { kind: "literal", key: "Товары", suggestion: "Products" } });
  assert.deepStrictEqual(target, { kind: "literal", key: "Товары" });
  assert.deepStrictEqual(plannedActions(target!), [{ action: "ask" }, { action: "open" }]);
  // Even handed a suggestion outright - the menu is built from the kind, not from luck.
  assert.deepStrictEqual(plannedActions({ kind: "literal", key: "Товары", suggestion: "Products" }), [
    { action: "ask" },
    { action: "open" },
  ]);
  // A name still gets it: only the literal is left without.
  assert.deepStrictEqual(plannedActions({ kind: "token", key: "Товары", suggestion: "Products" })[0], {
    action: "apply",
    value: "Products",
  });
});

// --------------------------------------------------------- draggable column widths

test("resizeColumn: dragging a border right widens exactly that column", () => {
  const next = resizeColumn(DEFAULT_COLUMN_WIDTHS, "place", 40);
  assert.strictEqual(next.place, DEFAULT_COLUMN_WIDTHS.place + 40);
  // Every other column is untouched - not just unequal to some other value, the very same
  // numbers the drag started from, so a person resizing one column can never see a neighbor
  // twitch on its own.
  const untouched: ColumnWidths = { ...next, place: DEFAULT_COLUMN_WIDTHS.place };
  assert.deepStrictEqual(untouched, DEFAULT_COLUMN_WIDTHS);
});

test("resizeColumn: dragging left narrows it, within its own floor", () => {
  const next = resizeColumn(DEFAULT_COLUMN_WIDTHS, "file", -30);
  assert.strictEqual(next.file, DEFAULT_COLUMN_WIDTHS.file - 30);
});

test("resizeColumn: a drag past the minimum stops AT the minimum, not below it", () => {
  // A reader can drag the mouse as far left as they like - the column itself must never follow
  // past its own floor, the one thing that keeps a column from disappearing under a neighbor.
  const next = resizeColumn(DEFAULT_COLUMN_WIDTHS, "count", -1000);
  assert.strictEqual(next.count, MIN_COLUMN_WIDTHS.count);
});

test("resizeColumn: already sitting below its own floor, a further narrowing drag still clamps up to it", () => {
  const cramped: ColumnWidths = { ...DEFAULT_COLUMN_WIDTHS, kind: 10 };
  const next = resizeColumn(cramped, "kind", -5);
  assert.strictEqual(next.kind, MIN_COLUMN_WIDTHS.kind);
});

test("resetColumnWidth: restores one column's own default, the others keep whatever the reader set", () => {
  const dragged: ColumnWidths = { ...DEFAULT_COLUMN_WIDTHS, key: 600, file: 95 };
  const next = resetColumnWidth(dragged, "key");
  assert.strictEqual(next.key, DEFAULT_COLUMN_WIDTHS.key);
  assert.strictEqual(next.file, 95, "a column nobody double-clicked keeps the reader's own width");
});

test("sanitizeColumnWidths: nothing saved yet (undefined, null, or not an object) reads back as the defaults", () => {
  assert.deepStrictEqual(sanitizeColumnWidths(undefined), DEFAULT_COLUMN_WIDTHS);
  assert.deepStrictEqual(sanitizeColumnWidths(null), DEFAULT_COLUMN_WIDTHS);
  assert.deepStrictEqual(sanitizeColumnWidths("not an object"), DEFAULT_COLUMN_WIDTHS);
  assert.deepStrictEqual(sanitizeColumnWidths(42), DEFAULT_COLUMN_WIDTHS);
});

test("sanitizeColumnWidths: a valid saved width above the floor is trusted as it is", () => {
  const saved = { kind: 120, key: 400, count: 70, place: 300, file: 110 };
  assert.deepStrictEqual(sanitizeColumnWidths(saved), saved);
});

test("sanitizeColumnWidths: a positive number below the floor is raised to it, not thrown away", () => {
  // Still a real, deliberate-looking number - not garbage the way a negative or a NaN is - so it
  // reads as "as narrow as this column goes", the same place a live drag would have stopped it,
  // rather than snapping all the way back out to the default.
  const next = sanitizeColumnWidths({ file: 3 });
  assert.strictEqual(next.file, MIN_COLUMN_WIDTHS.file);
});

test("sanitizeColumnWidths: zero, negative, NaN, a string and a missing key all fall back to the default", () => {
  const next = sanitizeColumnWidths({ kind: 0, key: -50, count: Number.NaN, place: "260" });
  assert.strictEqual(next.kind, DEFAULT_COLUMN_WIDTHS.kind);
  assert.strictEqual(next.key, DEFAULT_COLUMN_WIDTHS.key);
  assert.strictEqual(next.count, DEFAULT_COLUMN_WIDTHS.count);
  assert.strictEqual(next.place, DEFAULT_COLUMN_WIDTHS.place);
  // "file" was never mentioned at all - a blob left over from before this column existed.
  assert.strictEqual(next.file, DEFAULT_COLUMN_WIDTHS.file);
});

test("sanitizeColumnWidths: an unknown extra key (a newer version's column) is dropped, not carried through", () => {
  const next = sanitizeColumnWidths({ ...DEFAULT_COLUMN_WIDTHS, futureColumn: 999 });
  assert.deepStrictEqual(next, DEFAULT_COLUMN_WIDTHS);
  assert.strictEqual((next as Record<string, unknown>).futureColumn, undefined);
});

test("a drag's result is already safe to persist as it stands - sanitizing it again changes nothing", () => {
  const dragged = resizeColumn(DEFAULT_COLUMN_WIDTHS, "key", 500);
  assert.deepStrictEqual(sanitizeColumnWidths(dragged), dragged);
});

// --------------------------------------------------------- the suggest button's own guard

async function runAsyncTests(): Promise<void> {
  // A click while the previous run is still going must not start the job again - `--suggest`
  // reaches a paid external service, and a delayed second click is exactly the case a serial
  // queue would still let through (just later); this guard has to drop it outright.
  {
    let starts = 0;
    let release: (value: string) => void = () => undefined;
    const pending = new Promise<string>((resolve) => {
      release = resolve;
    });
    const guarded = guardConcurrent(() => {
      starts += 1;
      return pending;
    });
    const first = guarded();
    const second = guarded(); // fired before `first` has settled
    try {
      assert.strictEqual(starts, 1, "the job ran only once - the second call never started it");
      release("done");
      assert.strictEqual(await first, "done");
      assert.strictEqual(await second, undefined, "the dropped call resolves at once, not queued for a turn of its own");
      passed += 1;
      console.log("ok   guardConcurrent drops a call that arrives while the previous one is still running");
    } catch (e) {
      failed += 1;
      console.error("FAIL guardConcurrent drops a call that arrives while the previous one is still running");
      console.error(e instanceof Error ? e.message : e);
    }
  }

  // The button must come back to life after ANY outcome, a refusal included - a failed run must
  // not leave it stuck disabled forever.
  {
    let starts = 0;
    const guarded = guardConcurrent(async () => {
      starts += 1;
      if (starts === 1) {
        throw new Error("сервис отказал");
      }
      return "ok";
    });
    try {
      await assert.rejects(guarded(), /сервис отказал/);
      assert.strictEqual(await guarded(), "ok", "the guard is free again after the failed run");
      assert.strictEqual(starts, 2);
      passed += 1;
      console.log("ok   guardConcurrent releases on a rejection too, so the next call still runs");
    } catch (e) {
      failed += 1;
      console.error("FAIL guardConcurrent releases on a rejection too, so the next call still runs");
      console.error(e instanceof Error ? e.message : e);
    }
  }
}

void runAsyncTests().then(() => {
  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) {
    process.exit(1);
  }
});
