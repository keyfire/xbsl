// Unit tests for the pure update-check core (src/updateCheckCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.
//
// The rule the tests pin down: a false alarm is worse than a missed update. Anything the
// core cannot read - a strange version, a changed API answer - must end in "no update",
// never in a notification and never in a throw during activation.

import * as assert from "assert";
import {
  compareVersions,
  isNewer,
  parseVersion,
  publishedVersion,
  shouldCheck,
  updateAvailable,
} from "../src/updateCheckCore";

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

test("a newer version is recognized digit by digit, not by string order", () => {
  assert.strictEqual(isNewer("0.46.0", "0.45.0"), true);
  assert.strictEqual(isNewer("0.9.0", "0.10.0"), false, "0.9 must not beat 0.10");
  assert.strictEqual(isNewer("1.0.0", "0.99.99"), true);
  assert.strictEqual(isNewer("0.45.1", "0.45.0"), true);
  assert.strictEqual(isNewer("0.45.0", "0.45.0"), false);
});

test("a two-part version is read as x.y.0", () => {
  assert.deepStrictEqual(parseVersion("0.46")?.numbers, [0, 46, 0]);
  assert.strictEqual(isNewer("0.46", "0.45.9"), true);
});

test("a release beats its own pre-release, and a pre-release does not beat the release", () => {
  assert.strictEqual(isNewer("0.46.0", "0.46.0-rc1"), true);
  assert.strictEqual(isNewer("0.46.0-rc1", "0.46.0"), false);
});

test("an unreadable version never claims an update", () => {
  assert.strictEqual(isNewer("dev", "0.45.0"), false);
  assert.strictEqual(isNewer("0.46.0", "unknown"), false);
  assert.strictEqual(compareVersions("", ""), 0);
  assert.strictEqual(parseVersion("не версия"), undefined);
});

test("the published version is taken from the answer, and a changed shape is silent", () => {
  assert.strictEqual(publishedVersion({ version: "0.46.0" }), "0.46.0");
  assert.strictEqual(publishedVersion({ version: 46 }), undefined);
  assert.strictEqual(publishedVersion({ latest: "0.46.0" }), undefined);
  assert.strictEqual(publishedVersion(undefined), undefined);
  assert.strictEqual(publishedVersion("0.46.0"), undefined);
});

test("the automatic check is rare: once per interval, and the first run always checks", () => {
  const day = 24 * 60 * 60 * 1000;
  assert.strictEqual(shouldCheck({ intervalMs: day, now: 1_000 }), true);
  assert.strictEqual(shouldCheck({ lastCheckedAt: 1_000, intervalMs: day, now: 1_000 + day }), true);
  assert.strictEqual(shouldCheck({ lastCheckedAt: 1_000, intervalMs: day, now: 2_000 }), false);
});

test("an update is announced only when there is one", () => {
  assert.strictEqual(updateAvailable({ installed: "0.45.0", latest: "0.46.0" }), true);
  assert.strictEqual(updateAvailable({ installed: "0.46.0", latest: "0.46.0" }), false);
  assert.strictEqual(updateAvailable({ installed: "0.46.0" }), false);
  // A locally built extension carries the same version as the release it was built from -
  // an older published version must not be offered as an "update".
  assert.strictEqual(updateAvailable({ installed: "0.47.0", latest: "0.46.0" }), false);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
