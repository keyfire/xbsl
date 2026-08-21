// Reveal a document position so a NARROW editor scrolls horizontally to the line's content -
// past the indentation - instead of leaving deeply-indented text off-screen (docs/DESIGNER.md).
// VS Code has no "set horizontal scroll offset" API, but revealRange scrolls horizontally to a
// range; revealing from the first non-whitespace character brings the content into view.

import * as vscode from "vscode";

import { neighborColumn, revealStartColumn } from "./formDesignerCore";

// The editor group a source file belongs in, for panels with no column of their own to keep
// clear (translationPanel.ts's dictionary jumps - a sidebar view, not an editor tab). Order:
// the group this very document is open in, then the one holding another source file (yaml or
// xbsl), then the active text editor, and only then the caller's fallback.
//
// The form designer panel does NOT use this - its own column is never a safe fallback (that
// fallback tier is exactly how a form's yaml used to land behind its own panel), so its
// reveals go through neighborColumnFor below instead, which excludes that column outright.
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

// The editor group already holding an open tab of this document, if any. An implicit reveal
// (the cursor merely following a click, not an explicit ask - see shouldRevealInEditor in
// formDesignerCore.ts) may bring that tab forward, but must not open the document from
// closed: the panel and its source travel together, yet the pairing never ADDS a tab.
export function tabColumnOf(uri: vscode.Uri): vscode.ViewColumn | undefined {
  const key = uri.toString();
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      if (tab.input instanceof vscode.TabInputText && (tab.input as vscode.TabInputText).uri.toString() === key) {
        return group.viewColumn;
      }
    }
  }
  return undefined;
}

// The column a form's own source opens in NEXT TO ITS PANEL - the default column resolver for
// every reveal of a form's yaml (Designer.revealOffsetInEditor, the structure and data panes'
// revealInEditor) and for a freshly created module (formProps.ts, handler creation). The panel
// column is excluded unconditionally: the whole point of this helper, over editorColumnFor, is
// that it has no fallback tier that can ever land there. See neighborColumn in
// formDesignerCore.ts for the tiering; Beside splits the editor area when no existing group
// (the source's own tab, a source-language group) qualifies.
//
// The "same document" tier reuses tabColumnOf rather than scanning visibleTextEditors: a tab
// can exist in a group without being that group's FRONT tab (backgrounded behind a sibling),
// invisible to visibleTextEditors but very much an existing tab - missing it here would split
// a duplicate tab beside, right after the gate (shouldRevealInEditor, built on the same
// tabColumnOf) decided a reveal was safe BECAUSE that tab already exists.
export function neighborColumnFor(uri: vscode.Uri, panelColumn: vscode.ViewColumn | undefined): vscode.ViewColumn {
  const source = vscode.window.visibleTextEditors.find(
    (e) => e.viewColumn !== undefined && SOURCE_LANGUAGES.includes(e.document.languageId)
  )?.viewColumn;
  return neighborColumn(tabColumnOf(uri), source, panelColumn) ?? vscode.ViewColumn.Beside;
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
