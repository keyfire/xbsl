// Reveal a document position so a NARROW editor scrolls horizontally to the line's content -
// past the indentation - instead of leaving deeply-indented text off-screen (docs/DESIGNER.md).
// VS Code has no "set horizontal scroll offset" API, but revealRange scrolls horizontally to a
// range; revealing from the first non-whitespace character brings the content into view.

import * as vscode from "vscode";

import { revealStartColumn } from "./formDesignerCore";

// The editor group a form's yaml belongs in. The designer opens yamls constantly (a click in the
// structure, an operation result, a new form from the metadata tree), and each of them must join
// the group where the sources already live instead of splitting the layout next to the form
// panel. Order: the group this very document is open in, then the one holding another source
// file (yaml or xbsl), then the active text editor, and only then the caller's fallback.
const SOURCE_LANGUAGES = ["yaml", "xbsl"];

export function editorColumnFor(uri: vscode.Uri, fallback: vscode.ViewColumn): vscode.ViewColumn {
  const key = uri.toString();
  const visible = vscode.window.visibleTextEditors.filter((e) => e.viewColumn !== undefined);
  const same = visible.find((e) => e.document.uri.toString() === key);
  if (same?.viewColumn) {
    return same.viewColumn;
  }
  const source = visible.find((e) => SOURCE_LANGUAGES.includes(e.document.languageId));
  if (source?.viewColumn) {
    return source.viewColumn;
  }
  return vscode.window.activeTextEditor?.viewColumn ?? visible[0]?.viewColumn ?? fallback;
}

export function revealContent(editor: vscode.TextEditor, position: vscode.Position): void {
  const line = editor.document.lineAt(position.line);
  const size = typeof editor.options.tabSize === "number" ? editor.options.tabSize : 4;
  const column = revealStartColumn(line.firstNonWhitespaceCharacterIndex, size);
  editor.revealRange(
    new vscode.Range(new vscode.Position(position.line, column), line.range.end),
    vscode.TextEditorRevealType.InCenterIfOutsideViewport
  );
}
