import * as assert from "node:assert/strict";

import { METADATA_DRAG_MIME, MetadataDragTickets } from "../src/metadataDragCore";

type Test = { name: string; run: () => void };
const tests: Test[] = [];
function test(name: string, run: () => void): void { tests.push({ name, run }); }

test("drag data uses a custom MIME outside VS Code's reserved tree namespace", () => {
  assert.equal(METADATA_DRAG_MIME, "application/vnd.xbsl.metadata-items");
  assert.ok(!METADATA_DRAG_MIME.startsWith("application/vnd.code.tree."));
});

test("the drag payload serializes only flat source ids", () => {
  let nonce = 0;
  const tickets = new MetadataDragTickets(() => 100, () => `ticket-${++nonce}`);
  const payload = tickets.issue(["object:a", "resource:b"])!;
  assert.deepStrictEqual(JSON.parse(payload), {
    ticket: "ticket-1", ids: ["object:a", "resource:b"],
  });
  assert.deepStrictEqual(tickets.consume(payload), ["object:a", "resource:b"]);
});

test("a ticket cannot be reused or changed to another source", () => {
  const tickets = new MetadataDragTickets(() => 100, () => "one");
  const payload = tickets.issue(["object:a"])!;
  assert.equal(tickets.consume(JSON.stringify({ ticket: "one", ids: ["object:b"] })), undefined);
  assert.deepStrictEqual(tickets.consume(payload), ["object:a"]);
  assert.equal(tickets.consume(payload), undefined);
});

test("malformed and expired data never becomes a source", () => {
  let now = 100;
  const tickets = new MetadataDragTickets(() => now, () => "old");
  assert.equal(tickets.consume("not json"), undefined);
  assert.equal(tickets.consume(JSON.stringify({ ticket: "missing", ids: ["x"] })), undefined);
  const payload = tickets.issue(["object:a"])!;
  now += 31_000;
  assert.equal(tickets.consume(payload), undefined);
  tickets.clear();
  assert.equal(tickets.consume(payload), undefined);
});

test("duplicate or non-string ids are rejected", () => {
  const tickets = new MetadataDragTickets(() => 100, () => "one");
  assert.equal(tickets.issue(["same", "same"]), undefined);
  assert.equal(tickets.issue([]), undefined);
  assert.equal(tickets.consume(JSON.stringify({ ticket: "one", ids: [1] })), undefined);
});

let failed = 0;
for (const item of tests) {
  try { item.run(); process.stdout.write(`ok ${item.name}\n`); }
  catch (error) { failed++; process.stderr.write(`FAIL ${item.name}\n${error}\n`); }
}
process.stdout.write(`total: ${tests.length - failed} ok, ${failed} fail\n`);
if (failed) process.exit(1);
