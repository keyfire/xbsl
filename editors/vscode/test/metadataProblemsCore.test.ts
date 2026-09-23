import * as assert from "node:assert/strict";

import {
  filesForElement, MetadataProblemCounts, problemBadge, sumCounts,
} from "../src/metadataProblemsCore";

type Test = { name: string; run: () => void };
const tests: Test[] = [];
function test(name: string, run: () => void): void { tests.push({ name, run }); }

const root = "C:/sample/project";
const main = `${root}/Main`;
const nested = `${main}/Group/Nested`;
const source = `${nested}/Record.yaml`;

test("source family includes paired code and queries, but excludes namesakes", () => {
  assert.deepStrictEqual(filesForElement(source, [
    `${nested}/Record.xbsl`, `${nested}/Record.Object.xbsl`, `${nested}/Record.xbql`,
    `${nested}/RecordArchive.xbsl`, `${nested}/Record.Xsd.2.xsd`,
    `${main}/Record.xbsl`,
  ]), [
    source, `${nested}/Record.xbsl`, `${nested}/Record.Object.xbsl`, `${nested}/Record.xbql`,
  ]);
});

test("diagnostics from all owned files roll up once through nested packages", () => {
  const counts = new MetadataProblemCounts([
    { id: source, files: filesForElement(source, [
      `${nested}/Record.xbsl`, `${nested}/Record.Object.xbsl`, `${nested}/Record.xbql`,
    ]), ancestors: [nested, `${main}/Group`, main, root] },
    { id: `${main}/RecordArchive.yaml`, files: [`${main}/RecordArchive.yaml`],
      ancestors: [main, root] },
  ]);
  counts.update(`${nested}/Record.xbsl`, [0, 1, 2]);
  counts.update(`${nested}/Record.Object.xbsl`, [0]);
  counts.update(`${nested}/Record.xbql`, [0]);
  counts.update(`${main}/RecordArchive.yaml`, [1]);
  assert.deepStrictEqual(counts.get(source), { errors: 3, warnings: 1 });
  assert.deepStrictEqual(counts.get(nested), { errors: 3, warnings: 1 });
  assert.deepStrictEqual(counts.get(`${main}/Group`), { errors: 3, warnings: 1 });
  assert.deepStrictEqual(counts.get(main), { errors: 3, warnings: 2 });
  assert.deepStrictEqual(counts.get(root), { errors: 3, warnings: 2 });
  assert.deepStrictEqual(counts.get(`${main}/RecordArchive.yaml`), { errors: 0, warnings: 1 });
});

test("new diagnostics replace old counts and clearing removes ancestor marks", () => {
  const counts = new MetadataProblemCounts([
    { id: source, files: [source, `${nested}/Record.xbsl`], ancestors: [nested, main, root] },
  ]);
  counts.update(source, [0, 0, 1]);
  counts.update(`${nested}/Record.xbsl`, [0]);
  assert.deepStrictEqual(counts.get(root), { errors: 3, warnings: 1 });
  counts.update(source.toUpperCase().replace(/\//g, "\\"), [1]);
  assert.deepStrictEqual(counts.get(source), { errors: 1, warnings: 1 });
  counts.update(source, []);
  counts.update(`${nested}/Record.xbsl`, []);
  assert.deepStrictEqual(counts.get(source), { errors: 0, warnings: 0 });
  assert.deepStrictEqual(counts.get(root), { errors: 0, warnings: 0 });
});

test("duplicate ancestor identities count one diagnostic once", () => {
  const counts = new MetadataProblemCounts([
    { id: source, files: [source], ancestors: [nested, nested, main, root, root] },
  ]);
  counts.update(source, [0]);
  assert.deepStrictEqual(counts.get(nested), { errors: 1, warnings: 0 });
  assert.deepStrictEqual(counts.get(root), { errors: 1, warnings: 0 });
});

test("rebuilding ownership drops removed files and retains current diagnostics", () => {
  const counts = new MetadataProblemCounts([
    { id: source, files: [source, `${nested}/Record.xbsl`], ancestors: [nested, main, root] },
  ]);
  counts.update(source, [0]);
  counts.update(`${nested}/Record.xbsl`, [1]);
  counts.setFamilies([{ id: source, files: [source], ancestors: [nested, main, root] }]);
  assert.deepStrictEqual(counts.get(root), { errors: 1, warnings: 0 });
  assert.deepStrictEqual(counts.get(source), { errors: 1, warnings: 0 });
  counts.dispose();
  assert.deepStrictEqual(counts.get(root), { errors: 0, warnings: 0 });
});

test("the row badge shows an icon and a number per kind of problem", () => {
  assert.strictEqual(problemBadge({ errors: 2, warnings: 1 }), "⊗ 2 ⚠ 1");
  assert.strictEqual(problemBadge({ errors: 0, warnings: 3 }), "⚠ 3");
  assert.strictEqual(problemBadge({ errors: 1, warnings: 0 }), "⊗ 1");
  assert.strictEqual(problemBadge({ errors: 0, warnings: 0 }), "");
});

test("a category adds up the rows under it and skips rows with no counts", () => {
  assert.deepStrictEqual(
    sumCounts([{ errors: 2, warnings: 1 }, undefined, { errors: 0, warnings: 4 }]),
    { errors: 2, warnings: 5 },
  );
  assert.deepStrictEqual(sumCounts([]), { errors: 0, warnings: 0 });
});

let failed = 0;
for (const item of tests) {
  try { item.run(); process.stdout.write(`ok ${item.name}\n`); }
  catch (error) { failed++; process.stderr.write(`FAIL ${item.name}\n${error}\n`); }
}
process.stdout.write(`total: ${tests.length - failed} ok, ${failed} fail\n`);
if (failed) process.exit(1);
