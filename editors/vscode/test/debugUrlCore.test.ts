// Unit tests for the debuggee address (src/debugUrlCore.ts). No test runner and no vscode:
// plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.
//
// What the tests pin down: one address has to attach the browser client of every server the
// extension meets. Newer clients read only `debug-server-url`, older ones read only
// `debug-server-host`/`debug-server-port`, and both take the session from `debug-session-id`. A client that finds none of its own
// parameters runs the application without attaching, and a client breakpoint never stops.

import * as assert from "assert";
import { debuggeeUrl } from "../src/debugUrlCore";

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

const APP = "https://element.example.com/applications/probe";
const SESSION = "fccab5af-f8dc-4337-82e7-868ffa972c9f";

function params(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

test("a current client finds the debug server address and the session", () => {
  const q = params(debuggeeUrl(APP, "wss://element.example.com/debug", SESSION));
  assert.strictEqual(q.get("debug-server-url"), "wss://element.example.com/debug");
  assert.strictEqual(q.get("debug-session-id"), SESSION);
});

test("the debug server address is encoded, so its own query survives", () => {
  const address = "wss://element.example.com/debug?zone=a&b=1";
  const url = debuggeeUrl(APP, address, SESSION);
  assert.ok(url.includes(`debug-server-url=${encodeURIComponent(address)}`), url);
  assert.strictEqual(params(url).get("debug-server-url"), address);
});

test("an older client still finds host and port", () => {
  const q = params(debuggeeUrl(APP, "wss://cloud.example.com/debug", SESSION));
  assert.strictEqual(q.get("debug-server-host"), "cloud.example.com");
  assert.strictEqual(q.get("debug-server-port"), "443");
  assert.strictEqual(q.get("debug-session-id"), SESSION);
});

test("the port comes from the address, or from its scheme when the address has none", () => {
  assert.strictEqual(params(debuggeeUrl(APP, "ws://localhost:8080/", SESSION)).get("debug-server-port"), "8080");
  assert.strictEqual(params(debuggeeUrl(APP, "ws://localhost/", SESSION)).get("debug-server-port"), "80");
  assert.strictEqual(params(debuggeeUrl(APP, "wss://element.example.com:8443/debug", SESSION)).get("debug-server-port"), "8443");
});

test("an application address with a query of its own gets the parameters appended", () => {
  const url = debuggeeUrl(`${APP}?lang=en`, "wss://element.example.com/debug", SESSION);
  assert.ok(url.startsWith(`${APP}?lang=en&`), url);
  assert.strictEqual(params(url).get("lang"), "en");
  assert.strictEqual(params(url).get("debug-session-id"), SESSION);
});

test("the sign-in mode travels as force_auth, the parameter the platform reads", () => {
  const q = params(debuggeeUrl(APP, "wss://element.example.com/debug", SESSION, "anonymous"));
  assert.strictEqual(q.get("force_auth"), "anonymous");
  assert.strictEqual(q.get("auth-mode"), null);
});

test("without a sign-in mode the address carries no sign-in parameter", () => {
  const q = params(debuggeeUrl(APP, "wss://element.example.com/debug", SESSION));
  assert.strictEqual(q.get("force_auth"), null);
  assert.strictEqual(q.get("auth-mode"), null);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
