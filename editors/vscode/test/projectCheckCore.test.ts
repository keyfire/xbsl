import * as assert from "node:assert/strict";
import { singleProjectCheck } from "../src/projectCheckCore";

async function main(): Promise<void> {
  const states: boolean[] = [];
  let calls = 0;
  let finish!: () => void;
  const gate = new Promise<void>((resolve) => { finish = resolve; });
  const run = singleProjectCheck(async () => { calls++; await gate; }, (busy) => states.push(busy));
  const first = run();
  const second = run();
  assert.equal(first, second, "repeated invocation must share the pending project check");
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.deepEqual(states, [true], "busy state must last until the project pass completes");
  finish();
  await first;
  assert.deepEqual(states, [true, false]);

  let fail = true;
  const recovery: boolean[] = [];
  const retry = singleProjectCheck(async () => {
    if (fail) { throw new Error("index unavailable"); }
  }, (busy) => recovery.push(busy));
  await assert.rejects(retry(), /index unavailable/);
  fail = false;
  await retry();
  assert.deepEqual(recovery, [true, false, true, false], "a failed pass must permit a fresh retry");
  process.stdout.write("projectCheckCore: 3 checks passed\n");
}
void main().catch((error) => { process.stderr.write(String(error)); process.exitCode = 1; });