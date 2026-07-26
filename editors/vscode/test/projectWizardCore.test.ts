// Unit tests for the pure project-wizard core (src/projectWizardCore.ts). No test runner and no
// vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { buildNewProjectCall, checkProjectIdentifier } from "../src/projectWizardCore";

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

// --- checkProjectIdentifier ----------------------------------------------------------------

test("a capitalized identifier passes and is trimmed", () => {
  assert.deepStrictEqual(checkProjectIdentifier("  МойПроект  "), { ok: true, value: "МойПроект" });
  assert.deepStrictEqual(checkProjectIdentifier("Acme_Site1"), { ok: true, value: "Acme_Site1" });
});

test("a blank value is rejected as empty", () => {
  assert.deepStrictEqual(checkProjectIdentifier("   "), { ok: false, reason: "empty" });
  assert.deepStrictEqual(checkProjectIdentifier(""), { ok: false, reason: "empty" });
});

test("the letter ё is rejected with its own reason (before the identifier check)", () => {
  assert.deepStrictEqual(checkProjectIdentifier("Ёлка"), { ok: false, reason: "yo" });
  assert.deepStrictEqual(checkProjectIdentifier("Планёрка"), { ok: false, reason: "yo" });
});

test("non-identifier characters are rejected", () => {
  assert.deepStrictEqual(checkProjectIdentifier("Мой Проект"), { ok: false, reason: "identifier" });
  assert.deepStrictEqual(checkProjectIdentifier("Site-1"), { ok: false, reason: "identifier" });
  assert.deepStrictEqual(checkProjectIdentifier("1Site"), { ok: false, reason: "identifier" });
});

test("a lowercase start is rejected (PascalCase is required)", () => {
  assert.deepStrictEqual(checkProjectIdentifier("мойПроект"), { ok: false, reason: "lowercase" });
  assert.deepStrictEqual(checkProjectIdentifier("site"), { ok: false, reason: "lowercase" });
  assert.deepStrictEqual(checkProjectIdentifier("_Site"), { ok: false, reason: "lowercase" });
});

// --- buildNewProjectCall -------------------------------------------------------------------

test("assembles the minimal application call (positional args, no flags)", () => {
  const { lspParams, cliArgs } = buildNewProjectCall({
    root: "C:/repos",
    vendor: "Acme",
    name: "Site",
    library: false,
  });
  assert.deepStrictEqual(lspParams, { root: "C:/repos", vendor: "Acme", name: "Site", library: false });
  assert.deepStrictEqual(cliArgs, ["C:/repos", "Acme", "Site"]);
});

test("the library flag is added to both transports", () => {
  const { lspParams, cliArgs } = buildNewProjectCall({
    root: "/tmp",
    vendor: "Acme",
    name: "Kit",
    library: true,
  });
  assert.strictEqual(lspParams.library, true);
  assert.deepStrictEqual(cliArgs, ["/tmp", "Acme", "Kit", "--library"]);
});

test("a representation is passed as a flag and an lsp param; blank is dropped", () => {
  const withRep = buildNewProjectCall({
    root: "/tmp",
    vendor: "Acme",
    name: "Site",
    representation: "Acme website",
    library: false,
  });
  assert.strictEqual(withRep.lspParams.representation, "Acme website");
  assert.deepStrictEqual(withRep.cliArgs, ["/tmp", "Acme", "Site", "--representation", "Acme website"]);

  const blankRep = buildNewProjectCall({
    root: "/tmp",
    vendor: "Acme",
    name: "Site",
    representation: "   ",
    library: false,
  });
  assert.ok(!("representation" in blankRep.lspParams));
  assert.deepStrictEqual(blankRep.cliArgs, ["/tmp", "Acme", "Site"]);
});

test("representation and library combine, representation first", () => {
  const { cliArgs } = buildNewProjectCall({
    root: "/tmp",
    vendor: "Acme",
    name: "Kit",
    representation: "Acme kit",
    library: true,
  });
  assert.deepStrictEqual(cliArgs, ["/tmp", "Acme", "Kit", "--representation", "Acme kit", "--library"]);
});

// -----------------------------------------------------------------------------

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
