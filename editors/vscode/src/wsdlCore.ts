// The WSDL descriptions of a SOAP service client - the pure half, no vscode (node tests run it).
//
// A SOAP service client declares no operations of its own: the platform generates the client
// type from a WSDL description loaded into the project. The IDE keeps that description beside the
// element as `<Name>.Wsdl.1.wsdl`, and a description that refers to another WSDL brings
// `<Name>.Wsdl.2.wsdl`, and so on. A file may not be renamed - the platform finds it by the name.
// The documentation spells the file `<Name>.Wsdl.1`, without the extension, but a build that
// carries such a file fails to apply with "WSDL not found", so the tree lists the names the
// platform reads.
// Imported XML schemas use the same stem and number series: `<Name>.Wsdl.2.xsd`.
//
// A SOAP service (the server side) has no such file: the platform builds its WSDL from the
// element and serves it at `?wsdl`.

import { SERIALIZER_KIND_SPELLINGS } from "./metadataCore";

const SOAP_CLIENT_KIND = "КлиентSoapСервиса";

// `Wsdl.<number>.wsdl` after the element name and a dot; the platform numbers from one.
const WSDL_TAIL = /^Wsdl\.([1-9]\d*)\.(?:wsdl|xsd)$/;

/** Does an element of this kind keep WSDL descriptions beside it?
 *
 * The kind is taken in either spelling: the Russian one and the one the serializer writes into
 * `ElementKind:` of an English project.
 */
export function carriesWsdl(kind: string): boolean {
  return kind === SOAP_CLIENT_KIND || SERIALIZER_KIND_SPELLINGS.get(kind) === SOAP_CLIENT_KIND;
}

/** The WSDL descriptions of the element `name` among the files of its folder, by their number.
 *
 * `name` is the element's file name without `.yaml` - the name its modules are paired by too.
 * The names are compared exactly as written: a description is tied to its element by the name
 * alone, and a near miss is not offered as one.
 */
export function wsdlFiles(name: string, files: string[]): string[] {
  const prefix = name + ".";
  const found: Array<{ filePath: string; number: number }> = [];
  for (const filePath of files) {
    const base = filePath.slice(Math.max(filePath.lastIndexOf("\\"), filePath.lastIndexOf("/")) + 1);
    if (!base.startsWith(prefix)) {
      continue;
    }
    const match = WSDL_TAIL.exec(base.slice(prefix.length));
    if (match) {
      found.push({ filePath, number: Number(match[1]) });
    }
  }
  return found.sort((a, b) => a.number - b.number).map((f) => f.filePath);
}
