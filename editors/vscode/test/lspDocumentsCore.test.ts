// Unit tests for the pure document selection of the LSP client (src/lspDocumentsCore.ts). No
// test runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from
// editors/vscode.
//
// The glob matching itself belongs to VS Code and is not re-created here; what these tests hold
// is which filters the client asks for, and that a narrowed root adds the dictionary and nothing
// broader. The patterns were matched against file paths by the matcher of an installed VS Code
// once, when the root forms below were introduced; these tests keep the patterns those checks saw.

import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import {
  ALL_YAML,
  BasePattern,
  DICTIONARY_PATTERNS,
  DocumentFilterShape,
  lspDocumentSelector,
  missingRoot,
  rootBase,
  rootSegments,
  rootYamlPattern,
} from "../src/lspDocumentsCore";

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

function yamlPatterns(selector: DocumentFilterShape[]): DocumentFilterShape["pattern"][] {
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
    assert.ok(typeof pattern === "string" && pattern.includes("xbsl-translation"), `${pattern}`);
  }
});

test("the setting is trimmed before it becomes a pattern", () => {
  assert.strictEqual(yamlPatterns(lspDocumentSelector("  src/app  "))[0], "**/src/app/**/*.yaml");
});

test("both forms of the dictionary are selected: a directory at any depth and a single file", () => {
  assert.deepStrictEqual([...DICTIONARY_PATTERNS], ["**/xbsl-translation/**/*.yaml", "**/xbsl-translation.yaml"]);
});

test("backslashes, a `./` step and a trailing separator give the pattern of the plain root", () => {
  // `./src/app` and `src/app/` used to become `**/./src/app/**` and `**/src/app//**`: no file has
  // a directory named `.` or an empty one, so no yaml of the project reached the server
  for (const root of ["src\\app", "./src/app", ".\\src\\app", "src/app/", "src\\app\\", "src//app"]) {
    assert.strictEqual(rootYamlPattern(root), "**/src/app/**/*.yaml", root);
  }
});

test("the string pattern of an absolute root drops its drive, which VS Code spells in lower case", () => {
  // the fsPath VS Code matches is d:\Projects\tasks\...: `**/D:\Projects\tasks/**` matched nothing
  const expected = "**/Projects/tasks/src/app/**/*.yaml";
  for (const root of ["D:\\Projects\\tasks\\src\\app", "d:\\Projects\\tasks\\src\\app", "D:/Projects/tasks/src/app/"]) {
    assert.strictEqual(rootYamlPattern(root), expected, root);
  }
});

test("a UNC root and a POSIX root keep every directory name", () => {
  assert.strictEqual(rootYamlPattern("\\\\server\\share\\src\\app"), "**/server/share/src/app/**/*.yaml");
  assert.strictEqual(rootYamlPattern("/home/dev/tasks/src/app"), "**/home/dev/tasks/src/app/**/*.yaml");
});

test("`..` cancels the step before it, and a leading `..` leaves the tail that marks the root", () => {
  assert.deepStrictEqual(rootSegments("src/app/../shared"), ["src", "shared"]);
  assert.deepStrictEqual(rootSegments("../tasks/src/app"), ["tasks", "src", "app"]);
  assert.deepStrictEqual(rootSegments("D:\\Projects\\tasks\\src\\.\\app"), ["Projects", "tasks", "src", "app"]);
});

test("a bracket, a star or a question mark in a directory name is matched literally", () => {
  assert.strictEqual(rootYamlPattern("D:\\Projects\\tasks [old]\\src"), "**/Projects/tasks [[]old[]]/src/**/*.yaml");
  assert.strictEqual(rootYamlPattern("/srv/what?/a*b"), "**/srv/what[?]/a[*]b/**/*.yaml");
});

test("Cyrillic, spaces and dots in directory names pass through as they are", () => {
  assert.strictEqual(
    rootYamlPattern("D:\\Проекты\\Склады 2.1\\src\\app"),
    "**/Проекты/Склады 2.1/src/app/**/*.yaml"
  );
});

test("a string pattern of a root with a brace or with no directory at all takes every yaml", () => {
  // a brace cannot be matched literally; the server still judges only the yaml of its root
  for (const root of ["D:\\Projects\\tasks{1}\\src", ".", "./", "D:\\", "/"]) {
    assert.strictEqual(rootYamlPattern(root), ALL_YAML, root);
  }
  // with no folder open such a relative root has no base either, and the selector takes every yaml
  for (const root of [".", "./", "app{1}/src"]) {
    assert.deepStrictEqual(lspDocumentSelector(root), lspDocumentSelector(""), root);
  }
});

// --- the root anchored at its directory ---------------------------------------------------------

const folder = path.resolve("workspace");

function rootFilter(projectRoot: string, workspaceFolder?: string): DocumentFilterShape["pattern"] {
  return lspDocumentSelector(projectRoot, workspaceFolder).filter((filter) => filter.language === "yaml")[0].pattern;
}

test("with a workspace folder a relative root is anchored at the directory the server resolves", () => {
  const expected: BasePattern = { base: path.join(folder, "src", "app"), pattern: ALL_YAML };
  for (const root of ["src/app", "src\\app".replace(/\\/g, path.sep), "./src/app/", "src/app/../app"]) {
    assert.deepStrictEqual(rootFilter(root, folder), expected, root);
  }
  // the dictionary still comes with it: it lies outside the root
  assert.deepStrictEqual(yamlPatterns(lspDocumentSelector("src/app", folder)).slice(1), [...DICTIONARY_PATTERNS]);
});

test("an absolute root is anchored at itself, with a folder open or without one", () => {
  const absolute = path.resolve("elsewhere", "Tasks");
  const expected: BasePattern = { base: absolute, pattern: ALL_YAML };
  assert.deepStrictEqual(rootFilter(absolute, folder), expected);
  assert.deepStrictEqual(rootFilter(absolute), expected);
  assert.deepStrictEqual(rootFilter(absolute + path.sep), expected);
});

test("a root outside the folder is anchored where `..` leads", () => {
  assert.strictEqual(rootBase("../shared/app", folder), path.resolve(folder, "..", "shared", "app"));
});

test("the base is the path as written: case is left to VS Code, which ignores it except on Linux", () => {
  assert.strictEqual(rootBase("SRC/App", folder), path.join(folder, "SRC", "App"));
});

test("a directory name with a brace needs no fallback once the root has a base", () => {
  assert.deepStrictEqual(rootFilter("app{1}/src", folder), { base: path.join(folder, "app{1}", "src"), pattern: ALL_YAML });
});

test("the folder itself as the root is still a narrowed root", () => {
  // `--project-root .` narrows the yaml the server judges, so the dictionary patterns stay
  assert.deepStrictEqual(rootFilter(".", folder), { base: folder, pattern: ALL_YAML });
  assert.strictEqual(lspDocumentSelector(".", folder).length, 5);
});

test("without a root the folder changes nothing: every yaml goes to the server", () => {
  assert.deepStrictEqual(lspDocumentSelector("", folder), lspDocumentSelector(""));
  assert.deepStrictEqual(lspDocumentSelector("  ", folder), lspDocumentSelector(""));
});

test("a relative root with no folder open keeps the pattern of its directory names", () => {
  assert.strictEqual(rootFilter("src/app"), "**/src/app/**/*.yaml");
  assert.strictEqual(rootBase("src/app"), undefined);
});

test("a root that is not on disk is named, so the silent loss of yaml findings is not silent", () => {
  const folder = path.resolve("workspace");
  const present = new Set([path.resolve(folder, "e1c/Project")]);
  const exists = (dir: string): boolean => present.has(dir);
  assert.strictEqual(missingRoot("e1c/Old", folder, exists), path.resolve(folder, "e1c/Old"));
  assert.strictEqual(missingRoot("e1c/Project", folder, exists), undefined);
  assert.strictEqual(missingRoot("", folder, exists), undefined);
});

test("the language client stays on the major version that passes a RelativePattern through", () => {
  // vscode-languageclient 9 hands a filter pattern to vscode.languages.match unchanged. The
  // protocol types it as a string, so a major version of the client may convert it: check
  // asDocumentSelector in protocolConverter.js before moving this range.
  const manifest = JSON.parse(fs.readFileSync(path.resolve("package.json"), "utf8"));
  assert.match(manifest.dependencies["vscode-languageclient"], /^\^?9\./);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
