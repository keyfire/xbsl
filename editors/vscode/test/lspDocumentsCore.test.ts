// Unit tests for the pure document selection of the LSP client (src/lspDocumentsCore.ts). No
// test runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from
// editors/vscode.
//
// The glob matching itself belongs to VS Code and is not re-created here; what these tests hold
// is which filters the client asks for, and that a narrowed root adds the dictionary and nothing
// broader.

import * as assert from "assert";
import { DICTIONARY_PATTERNS, DocumentFilterShape, lspDocumentSelector } from "../src/lspDocumentsCore";

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

function yamlPatterns(selector: DocumentFilterShape[]): (string | undefined)[] {
  return selector.filter((filter) => filter.language === "yaml").map((filter) => filter.pattern);
}

test("without a narrowed root every yaml goes to the server, the dictionary among them", () => {
  assert.deepStrictEqual(lspDocumentSelector(""), [
    { language: "xbsl" },
    { language: "xbql" },
    { language: "yaml", pattern: "**/*.yaml" },
  ]);
  assert.deepStrictEqual(lspDocumentSelector("   "), lspDocumentSelector(""));
});

test("a narrowed root keeps its own yaml and adds the dictionary next to it", () => {
  assert.deepStrictEqual(yamlPatterns(lspDocumentSelector("src/app")), [
    "**/src/app/**/*.yaml",
    "**/xbsl-translation/**/*.yaml",
    "**/xbsl-translation.yaml",
  ]);
});

test("a narrowed root still lets modules and queries through wherever they are", () => {
  const selector = lspDocumentSelector("src/app");
  assert.deepStrictEqual(
    selector.filter((filter) => filter.language !== "yaml"),
    [{ language: "xbsl" }, { language: "xbql" }]
  );
});

test("a narrowed root asks for no yaml beyond the root and the dictionary", () => {
  // an ordinary yaml outside the root stays with the editor: no catch-all pattern comes back
  const patterns = yamlPatterns(lspDocumentSelector("src/app"));
  assert.ok(!patterns.includes("**/*.yaml"));
  for (const pattern of patterns.slice(1)) {
    assert.ok(pattern !== undefined && pattern.includes("xbsl-translation"), `${pattern}`);
  }
});

test("the setting is trimmed before it becomes a pattern", () => {
  assert.strictEqual(yamlPatterns(lspDocumentSelector("  src/app  "))[0], "**/src/app/**/*.yaml");
});

test("both forms of the dictionary are selected: a directory at any depth and a single file", () => {
  assert.deepStrictEqual([...DICTIONARY_PATTERNS], ["**/xbsl-translation/**/*.yaml", "**/xbsl-translation.yaml"]);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
