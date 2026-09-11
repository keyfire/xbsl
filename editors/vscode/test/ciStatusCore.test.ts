// Unit tests for the pure CI-parity indicator (src/ciStatusCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.
//
// The state that matters most is the one that used to be silent: the parity was asked for and
// NOT taken, so the panel judges by the settings while the reader believes it agrees with the
// merge request. The indicator must be loud there and absent where nothing was asked for.

import * as assert from "assert";
import { ciIndicator, shortJob } from "../src/ciStatusCore";

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

test("nothing was asked for - nothing is shown", () => {
  assert.strictEqual(ciIndicator(undefined).state, "off");
  assert.strictEqual(ciIndicator({}).state, "off");
  assert.strictEqual(ciIndicator({ enabled: false, adopted: false }).state, "off");
});

test("the job's set was taken - the bar names the job", () => {
  const view = ciIndicator({
    enabled: true,
    adopted: true,
    job: "xbsl-lint",
    file: "/repo/.gitlab-ci.yml",
    source: "/repo/ci/lint.yml",
    line: "Rule set as in CI: /repo/.gitlab-ci.yml (include /repo/ci/lint.yml), job xbsl-lint",
    hint: "The linter also runs in: English to S3",
    note: "",
  });

  assert.strictEqual(view.state, "adopted");
  assert.strictEqual(view.job, "xbsl-lint");
  // the include the command stands in is what a click opens - not the file that includes it
  assert.strictEqual(view.open, "/repo/ci/lint.yml");
  assert.deepStrictEqual(view.details, [
    "Rule set as in CI: /repo/.gitlab-ci.yml (include /repo/ci/lint.yml), job xbsl-lint",
    "The linter also runs in: English to S3",
  ]);
});

test("without an include the root pipeline file is what a click opens", () => {
  const view = ciIndicator({
    enabled: true,
    adopted: true,
    job: "lint",
    file: "/repo/.gitlab-ci.yml",
    source: null,
    line: "Rule set as in CI: /repo/.gitlab-ci.yml, job lint",
  });

  assert.strictEqual(view.open, "/repo/.gitlab-ci.yml");
});

test("asked for and not taken - the state that used to be silent", () => {
  const view = ciIndicator({
    enabled: true,
    adopted: false,
    error: "No CI file next to the project (.gitlab-ci.yml); name one: --as-ci <file>",
  });

  assert.strictEqual(view.state, "refused");
  assert.strictEqual(view.open, undefined); // there is no file to open - that IS the answer
  assert.deepStrictEqual(view.details, [
    "No CI file next to the project (.gitlab-ci.yml); name one: --as-ci <file>",
  ]);
});

test("a long job name does not push the rest of the bar out", () => {
  assert.strictEqual(shortJob("xbsl-lint"), "xbsl-lint");
  assert.strictEqual(shortJob("  lint  "), "lint");
  assert.strictEqual(
    shortJob("lint the sources of the whole application"),
    "lint the sources of t..."
  );
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
