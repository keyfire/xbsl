// Whether a form document is read-only, shared by the designer surfaces that write (the
// properties panel and the structure view). A read-only source - a library (.xlib) form, a
// git/diff view, a read-only file - is inspected, not edited (docs/DESIGNER.md hook 11).

import * as vscode from "vscode";
import { isReadonlyScheme } from "./formPropsCore";

export async function isReadonlyDoc(uri: vscode.Uri): Promise<boolean> {
  if (isReadonlyScheme(uri.scheme)) {
    return true;
  }
  try {
    const stat = await vscode.workspace.fs.stat(uri);
    return ((stat.permissions ?? 0) & vscode.FilePermission.Readonly) !== 0;
  } catch {
    return false; // an unstattable uri is treated as writable - the write itself will fail if not
  }
}
