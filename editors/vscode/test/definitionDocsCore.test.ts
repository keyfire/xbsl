// Unit tests for what F12 does in an XBSL file (src/definitionDocsCore.ts). Plain Node
// asserts, no vscode - run with `npm test` from editors/vscode.
//
// The rule the tests pin down: the documentation is a FALLBACK, never a replacement. A real
// definition always wins (rebinding the key must not cost the normal jump), and with neither
// a definition nor a page the command is passed on so VS Code reports the miss itself.

import * as assert from "assert";
import { chooseAction } from "../src/definitionDocsCore";

function run(name: string, fn: () => void): void {
  try {
    fn();
    console.log(`ok - ${name}`);
  } catch (e) {
    console.error(`FAIL - ${name}`);
    throw e;
  }
}

run("a definition wins over the documentation page", () => {
  assert.strictEqual(chooseAction(1, "stdlib/element/xbsl/Std/Http/HttpResponse_ru"), "reveal");
  assert.strictEqual(chooseAction(3, null), "reveal");
});

run("a platform member with no source opens its page", () => {
  assert.strictEqual(chooseAction(0, "stdlib/element/xbsl/Std/Http/HttpResponse_ru"), "docs");
});

run("neither a definition nor a page is passed on to VS Code", () => {
  assert.strictEqual(chooseAction(0, null), "passThrough");
  assert.strictEqual(chooseAction(0, undefined), "passThrough");
  assert.strictEqual(chooseAction(0, ""), "passThrough");
});

console.log("definitionDocsCore: all tests passed");
