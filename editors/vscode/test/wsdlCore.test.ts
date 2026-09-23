// Unit tests for the WSDL descriptions of a SOAP service client (src/wsdlCore.ts): which kinds keep
// them and which files beside the element are its descriptions. Plain Node asserts, bundled by
// esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import { carriesWsdl, wsdlFiles } from "../src/wsdlCore";

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

const DIR = "D:\\repo\\Демо\\Учет\\Склад";
const at = (name: string): string => `${DIR}\\${name}`;

test("carriesWsdl: a SOAP service client in either spelling, a SOAP service does not", () => {
  assert.strictEqual(carriesWsdl("КлиентSoapСервиса"), true);
  assert.strictEqual(carriesWsdl("SoapServiceClient"), true);
  // The server side: the platform builds its WSDL from the element, no file lies beside it.
  assert.strictEqual(carriesWsdl("SoapСервис"), false);
  assert.strictEqual(carriesWsdl("SoapService"), false);
  assert.strictEqual(carriesWsdl("Справочник"), false);
});

test("wsdlFiles: the description beside the element, the rest of the folder left out", () => {
  const files = [
    at("КлиентСклада.yaml"),
    at("КлиентСклада.xbsl"),
    at("КлиентСклада.Wsdl.1.wsdl"),
    // The spelling of the documentation: the platform does not find a file named so.
    at("КлиентСклада.Wsdl.1"),
    // Another element whose name starts the same way, and a name that does not part with a dot.
    at("КлиентСкладаАрхив.Wsdl.1.wsdl"),
    at("КлиентСклада_Wsdl.1.wsdl"),
    at("КлиентСклада.Xsd.1.xsd"),
    at("Номенклатура.yaml"),
  ];
  assert.deepStrictEqual(wsdlFiles("КлиентСклада", files), [at("КлиентСклада.Wsdl.1.wsdl")]);
  assert.deepStrictEqual(wsdlFiles("КлиентСкладаАрхив", files), [at("КлиентСкладаАрхив.Wsdl.1.wsdl")]);
  assert.deepStrictEqual(wsdlFiles("Номенклатура", files), []);
});

test("wsdlFiles: several descriptions come by their number, not by the text of the name", () => {
  const files = [
    at("КлиентСклада.Wsdl.10.wsdl"),
    at("КлиентСклада.Wsdl.2.wsdl"),
    at("КлиентСклада.Wsdl.1.wsdl"),
    at("КлиентСклада.Wsdl.0.wsdl"),
    at("КлиентСклада.Wsdl.x.wsdl"),
  ];
  assert.deepStrictEqual(wsdlFiles("КлиентСклада", files), [
    at("КлиентСклада.Wsdl.1.wsdl"),
    at("КлиентСклада.Wsdl.2.wsdl"),
    at("КлиентСклада.Wsdl.10.wsdl"),
  ]);
});

test("wsdlFiles: either path separator, names compared as written", () => {
  const posix = "/repo/Демо/Учет/Склад/КлиентСклада.Wsdl.1.wsdl";
  assert.deepStrictEqual(wsdlFiles("КлиентСклада", [posix]), [posix]);
  assert.deepStrictEqual(wsdlFiles("клиентсклада", [posix]), []);
  assert.deepStrictEqual(wsdlFiles("КлиентСклада", ["/repo/КлиентСклада.wsdl.1.WSDL"]), []);
});

test("wsdlFiles: imported XSD schemas use the Wsdl stem and share its number order", () => {
  const files = [
    at("КлиентСклада.Wsdl.10.xsd"),
    at("КлиентСклада.Wsdl.2.xsd"),
    at("КлиентСклада.Wsdl.1.wsdl"),
    at("КлиентСклада.Xsd.3.xsd"),
    at("КлиентСклада.Wsdl.0.xsd"),
    at("КлиентСкладаАрхив.Wsdl.3.xsd"),
  ];
  assert.deepStrictEqual(wsdlFiles("КлиентСклада", files), [
    at("КлиентСклада.Wsdl.1.wsdl"),
    at("КлиентСклада.Wsdl.2.xsd"),
    at("КлиентСклада.Wsdl.10.xsd"),
  ]);
});

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
