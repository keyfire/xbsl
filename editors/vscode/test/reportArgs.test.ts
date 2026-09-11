// Unit tests for the command lines the extension builds (src/report.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { buildArgs, buildPathArgs, ciJobArgs, ciSettings, LinterConfig } from "../src/report";

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

const BASE: LinterConfig = { command: "xbsl", usePython: false };

function reader(values: Record<string, unknown>) {
  return { get: <T,>(key: string): T | undefined => values[key] as T | undefined };
}

test("without the setting nothing about CI reaches the engine", () => {
  assert.deepStrictEqual(ciJobArgs(BASE), []);
  assert.ok(!buildPathArgs("/repo/src", BASE).includes("--as-ci"));
});

test("the flag stands before a path with a closing --", () => {
  // `--as-ci` takes an OPTIONAL file name: right before the path the engine would read the
  // path as the name of the pipeline file and lint nothing at all.
  const args = buildPathArgs("/repo/src", { ...BASE, asCi: true });
  assert.deepStrictEqual(args.slice(-3), ["--as-ci", "--", "/repo/src"]);
});

test("a buffer run needs no separator - it has no path", () => {
  const args = buildArgs("Форма.yaml", { ...BASE, asCi: true });
  assert.deepStrictEqual(args.slice(-1), ["--as-ci"]);
  assert.ok(!args.includes("--"));
});

test("a named job goes as its own flag, which carries a value", () => {
  const args = buildPathArgs("/repo/src", { ...BASE, asCi: true, asCiJob: "english" });
  assert.deepStrictEqual(args.slice(-3), ["--as-ci-job", "english", "/repo/src"]);
  assert.ok(!args.includes("--as-ci"), "the job flag implies it - passing both is noise");
});

test("a filled job name switches the mode on by itself", () => {
  assert.deepStrictEqual(ciSettings(reader({ "linter.asCiJob": " english " })),
                         { asCi: true, asCiJob: "english" });
  assert.deepStrictEqual(ciSettings(reader({ "linter.asCi": true })),
                         { asCi: true, asCiJob: undefined });
  assert.deepStrictEqual(ciSettings(reader({})), { asCi: false, asCiJob: undefined });
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
