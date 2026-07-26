// Unit tests for the pure templates-panel core (src/templatesCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  TemplateRow,
  groupByCategory,
  parseTemplatesList,
  parseTemplatesResult,
  templatesArgs,
  toEnvelope,
  triggerOf,
  upsert,
  validateDraft,
} from "../src/templatesCore";

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

function row(over: Partial<TemplateRow> = {}): TemplateRow {
  return {
    name: "есл[и] - Если",
    trigger: "если",
    prefix: "есл",
    title: "Если",
    description: "/Стандартные/Управляющие/Если",
    category: "/Стандартные/Управляющие",
    contexts: ["STATEMENT_CONTEXT"],
    environments: ["SERVER_ENVIRONMENT", "CLIENT_ENVIRONMENT"],
    pattern: "если ${Редактировать(\"\")}\n;",
    preview: "если \n;",
    isAutoinsertable: false,
    builtin: true,
    ...over,
  };
}

// ------------------------------------------------------------------ engine arguments

test("--file goes after the action, not before it", () => {
  const args = templatesArgs("list", { command: "xbsl", usePython: false, templatesFile: "т.json" }, ["--format", "json"]);
  assert.deepStrictEqual(args, ["templates", "list", "--format", "json", "--file", "т.json"]);
});

test("a python interpreter is invoked through -m xbsl", () => {
  const args = templatesArgs("save", { command: "python", usePython: true });
  assert.deepStrictEqual(args, ["-m", "xbsl", "templates", "save"]);
});

test("without a configured file the engine picks its own default", () => {
  assert.deepStrictEqual(templatesArgs("export", { command: "xbsl", usePython: false }, ["--output", "о.json"]),
    ["templates", "export", "--output", "о.json"]);
});

// ---------------------------------------------------------------- response parsing

test("the list is parsed into rows and the file path", () => {
  const list = parseTemplatesList(JSON.stringify({ templates: [row()], file: ".xbsl-templates.json" }));
  assert.strictEqual(list.templates.length, 1);
  assert.strictEqual(list.file, ".xbsl-templates.json");
});

test("an engine error is raised, not swallowed as an empty list", () => {
  assert.throws(() => parseTemplatesList(JSON.stringify({ error: "файл не читается" })), /не читается/);
  assert.throws(() => parseTemplatesResult(JSON.stringify({ error: "сломан" })), /сломан/);
});

test("output without a templates list is rejected", () => {
  assert.throws(() => parseTemplatesList(JSON.stringify({ иное: 1 })));
});

// -------------------------------------------------------------------------- list

test("templates are grouped by category and sorted inside it", () => {
  const groups = groupByCategory([
    row({ name: "п", trigger: "пока", category: "/Стандартные/Управляющие" }),
    row({ name: "м", trigger: "метод", category: "/Стандартные/Объявления" }),
    row({ name: "е", trigger: "если", category: "/Стандартные/Управляющие" }),
  ]);
  assert.deepStrictEqual(groups.map((g) => g.category), ["/Стандартные/Объявления", "/Стандартные/Управляющие"]);
  assert.deepStrictEqual(groups[1].templates.map((t) => t.trigger), ["если", "пока"]);
});

test("a template without a category still lands in the list", () => {
  assert.strictEqual(groupByCategory([row({ category: "" })])[0].category, "/");
});

// ------------------------------------------------------------------- abbreviation

test("the trigger drops the optional-tail brackets", () => {
  assert.strictEqual(triggerOf("мет[од] - Метод"), "метод");
  assert.strictEqual(triggerOf("Возврат"), "Возврат");
  assert.strictEqual(triggerOf("зпр[с] - Запрос - с параметром"), "зпрс");
});

// ------------------------------------------------------------------ draft validation

function draft(over: Record<string, unknown> = {}) {
  return {
    name: "нов[ый] - Новый",
    description: "/Мои/Новый",
    pattern: "код",
    contexts: ["STATEMENT_CONTEXT"],
    environments: ["SERVER_ENVIRONMENT"],
    isAutoinsertable: false,
    ...over,
  };
}

test("a valid draft passes", () => {
  assert.strictEqual(validateDraft(draft(), [row()]), undefined);
});

test("empty name, empty pattern and empty choices are reported", () => {
  assert.strictEqual(validateDraft(draft({ name: "  " }), []), "empty-name");
  assert.strictEqual(validateDraft(draft({ pattern: " " }), []), "empty-pattern");
  assert.strictEqual(validateDraft(draft({ contexts: [] }), []), "no-context");
  assert.strictEqual(validateDraft(draft({ environments: [] }), []), "no-environment");
});

test("a name taken by another template is rejected", () => {
  assert.strictEqual(validateDraft(draft({ name: "есл[и] - Если" }), [row()]), "duplicate-name");
});

test("editing a template keeps its own name available", () => {
  // An edit without a rename must not be caught as a duplicate of itself.
  assert.strictEqual(validateDraft(draft({ name: "есл[и] - Если" }), [row()], "есл[и] - Если"), undefined);
});

// ----------------------------------------------------------------------- envelope

test("the envelope repeats the shape the engine reads", () => {
  const data = JSON.parse(toEnvelope([row()]));
  assert.strictEqual(data.templates[0].type, "xbsl.template");
  assert.strictEqual(data.templates[0].name, "есл[и] - Если");
  assert.deepStrictEqual(data.templates[0].context, {
    moduleEnvironments: ["SERVER_ENVIRONMENT", "CLIENT_ENVIRONMENT"],
    moduleContexts: ["STATEMENT_CONTEXT"],
  });
});

test("upsert replaces by name and appends a new one", () => {
  const rows = [row({ name: "а - А" }), row({ name: "б - Б" })];
  const edited = upsert(rows, draft({ name: "б - Б", pattern: "новый" }), "б - Б");
  assert.deepStrictEqual(edited.map((r) => r.name), ["а - А", "б - Б"]);
  assert.strictEqual(edited[1].pattern, "новый");
  assert.deepStrictEqual(upsert(rows, draft({ name: "в - В" })).map((r) => r.name), ["а - А", "б - Б", "в - В"]);
});

test("a rename replaces the original record instead of cloning it", () => {
  const edited = upsert([row({ name: "а - А" })], draft({ name: "новое - Новое" }), "а - А");
  assert.deepStrictEqual(edited.map((r) => r.name), ["новое - Новое"]);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  process.exit(1);
}
