// Tokenizes snippets with the shipped TextMate grammar (syntaxes/xbsl.tmLanguage.json) through
// vscode-textmate + vscode-oniguruma - the same engine VS Code runs - and checks the scopes.
// No test runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test`
// from editors/vscode.

import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import * as oniguruma from "vscode-oniguruma";
import * as vsctm from "vscode-textmate";

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

const ROOT = process.cwd();
const GRAMMAR = path.join(ROOT, "syntaxes", "xbsl.tmLanguage.json");
const WASM = path.join(ROOT, "node_modules", "vscode-oniguruma", "release", "onig.wasm");

interface Token {
  text: string;
  scopes: string[];
}

async function loadGrammar(): Promise<vsctm.IGrammar> {
  const bytes = fs.readFileSync(WASM);
  const wasm = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  const onigLib = oniguruma.loadWASM(wasm).then(() => ({
    createOnigScanner: (patterns: string[]) => new oniguruma.OnigScanner(patterns),
    createOnigString: (s: string) => new oniguruma.OnigString(s),
  }));
  const registry = new vsctm.Registry({
    onigLib,
    loadGrammar: async (scopeName: string) =>
      scopeName === "source.xbsl"
        ? vsctm.parseRawGrammar(fs.readFileSync(GRAMMAR, "utf8"), GRAMMAR)
        : null,
  });
  const grammar = await registry.loadGrammar("source.xbsl");
  if (!grammar) {
    throw new Error("the xbsl grammar did not load");
  }
  return grammar;
}

/** Tokens of every line, tokenized in sequence the way an editor does it. */
function tokenize(grammar: vsctm.IGrammar, source: string): Token[][] {
  const lines: Token[][] = [];
  let ruleStack = vsctm.INITIAL;
  for (const line of source.split("\n")) {
    const result = grammar.tokenizeLine(line, ruleStack);
    lines.push(
      result.tokens.map((t) => ({ text: line.slice(t.startIndex, t.endIndex), scopes: t.scopes })),
    );
    ruleStack = result.ruleStack;
  }
  return lines;
}

function tokenOf(line: Token[], text: string): Token {
  const found = line.find((t) => t.text === text);
  assert.ok(found, `no token ${JSON.stringify(text)} in ${JSON.stringify(line.map((t) => t.text))}`);
  return found;
}

function hasScope(token: Token, scope: string): boolean {
  return token.scopes.includes(scope);
}

// A pattern literal the way a real module writes one: an ODD number of double quotes inside
// the apostrophes (a quoted key, a colon, a quoted value) and backslash escapes. Read as
// double-quoted strings, the quotes leave one of them open, and the method after the literal
// used to be highlighted as the tail of a string.
const PATTERN = String.raw`'(?<Key>"[^"]*(?:pwd|token)[^"]*"\s*:\s*)"(?:\\.|[^"\\])*"'`;
const PATTERN_THEN_METHOD = [
  "метод Скрыть(Тело: Строка): Строка",
  `    возврат Тело.Заменить(${PATTERN}, "***")`,
  ";",
  "",
  "@НаСервере",
  "метод Следующий(Значение: Строка): Строка",
  '    возврат "%{Значение}"',
  ";",
].join("\n");

(async () => {
  const grammar = await loadGrammar();

  test("a pattern literal with double quotes inside does not swallow the next method", () => {
    const lines = tokenize(grammar, PATTERN_THEN_METHOD);
    const keyword = tokenOf(lines[5], "метод");
    assert.ok(hasScope(keyword, "storage.type.xbsl"), `scopes: ${keyword.scopes.join(" ")}`);
    assert.ok(!hasScope(keyword, "string.quoted.double.xbsl"));
    const decorator = tokenOf(lines[4], "@НаСервере");
    assert.ok(hasScope(decorator, "storage.type.annotation.xbsl"));
    const back = tokenOf(lines[6], "возврат");
    assert.ok(hasScope(back, "keyword.control.xbsl"));
  });

  test("the pattern literal itself is a single-quoted string with its escapes", () => {
    const lines = tokenize(grammar, PATTERN_THEN_METHOD);
    const inside = lines[1].filter((t) => hasScope(t, "string.quoted.single.xbsl"));
    assert.ok(inside.length > 0, "no single-quoted string scope on the pattern line");
    assert.strictEqual(inside.map((t) => t.text).join(""), PATTERN);
    assert.ok(inside.some((t) => hasScope(t, "constant.character.escape.xbsl")));
    // The double-quoted argument after the pattern is still a double-quoted string.
    const stars = tokenOf(lines[1], "***");
    assert.ok(hasScope(stars, "string.quoted.double.xbsl"));
  });

  test("an unclosed pattern ends with its line", () => {
    const lines = tokenize(grammar, ["знч Шаблон = '[a-z", "метод Дальше()", ";"].join("\n"));
    const keyword = tokenOf(lines[1], "метод");
    assert.ok(hasScope(keyword, "storage.type.xbsl"));
    assert.ok(!hasScope(keyword, "string.quoted.single.xbsl"));
  });

  test("an apostrophe inside a double-quoted string is not a pattern", () => {
    const lines = tokenize(grammar, ['знч Текст = "it\'s"', "метод Дальше()", ";"].join("\n"));
    const keyword = tokenOf(lines[1], "метод");
    assert.ok(hasScope(keyword, "storage.type.xbsl"));
    assert.ok(!hasScope(keyword, "string.quoted.single.xbsl"));
  });

  test("an escaped quote inside a double-quoted string keeps the string together", () => {
    const source = [String.raw`возврат "%{Имя}\"***\""`, "метод Дальше()", ";"].join("\n");
    const lines = tokenize(grammar, source);
    const keyword = tokenOf(lines[1], "метод");
    assert.ok(hasScope(keyword, "storage.type.xbsl"));
    assert.ok(!hasScope(keyword, "string.quoted.double.xbsl"));
  });

  console.log(`${passed} passed, ${failed} failed`);
  if (failed > 0) {
    process.exit(1);
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
