// Quick Fix glue (vscode): turns the fixes the linter reports (RawDiag.fix) into code actions.
// Per-diagnostic Quick Fixes show on the lightbulb; one "fix all" of kind source.fixAll.xbsl
// feeds the Source Action menu and `editor.codeActionsOnSave` (idiomatic fix-on-save).

import * as vscode from "vscode";
import { isXbslSource, RawDiag } from "./report";
import { anchorKey, collectFixes, fixIndex, FixItem, selectNonOverlapping } from "./codeActionsCore";

// A version-stamped snapshot of a document's fixable diagnostics.
export interface FixSnapshot {
  version: number;
  diags: RawDiag[];
}

// Supplied by the extension: the last version-stamped diagnostics for a document, or undefined.
export type SnapshotLookup = (uri: vscode.Uri) => FixSnapshot | undefined;

// A sub-kind of source.fixAll so both `source.fixAll` and `source.fixAll.xbsl` on-save configs match.
const FIX_ALL_KIND = vscode.CodeActionKind.SourceFixAll.append("xbsl");

export const PROVIDED_KINDS = [vscode.CodeActionKind.QuickFix, FIX_ALL_KIND];

// Only act on fixes computed against the CURRENT text: a stale snapshot has invalid offsets.
function currentDiags(
  document: vscode.TextDocument,
  lookup: SnapshotLookup
): RawDiag[] | undefined {
  const snap = lookup(document.uri);
  if (!snap || snap.version !== document.version) {
    return undefined;
  }
  return snap.diags;
}

function editsFor(document: vscode.TextDocument, fixes: FixItem[]): vscode.TextEdit[] {
  return fixes.map((f) =>
    vscode.TextEdit.replace(
      new vscode.Range(document.positionAt(f.start), document.positionAt(f.end)),
      f.newText
    )
  );
}

export class XbslCodeActionProvider implements vscode.CodeActionProvider {
  constructor(private readonly lookup: SnapshotLookup) {}

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const diags = currentDiags(document, this.lookup);
    if (!diags) {
      return [];
    }
    const only = context.only;
    const wantQuickFix = !only || only.contains(vscode.CodeActionKind.QuickFix);
    const wantFixAll = !only || only.contains(FIX_ALL_KIND);
    const actions: vscode.CodeAction[] = [];

    if (wantQuickFix) {
      const index = fixIndex(diags);
      for (const diag of context.diagnostics) {
        if (!isXbslSource(diag) || typeof diag.code !== "string") {
          continue;
        }
        const key = anchorKey(diag.range.start.line + 1, diag.range.start.character + 1, diag.code);
        const fix = index.get(key);
        if (!fix) {
          continue;
        }
        const action = new vscode.CodeAction(
          vscode.l10n.t("Fix: {0}", String(diag.code)),
          vscode.CodeActionKind.QuickFix
        );
        action.diagnostics = [diag];
        action.isPreferred = true;
        action.edit = new vscode.WorkspaceEdit();
        action.edit.replace(
          document.uri,
          new vscode.Range(document.positionAt(fix.start), document.positionAt(fix.end)),
          fix.newText
        );
        actions.push(action);
      }
    }

    if (wantFixAll) {
      const all = selectNonOverlapping(collectFixes(diags));
      if (all.length > 0) {
        const action = new vscode.CodeAction(vscode.l10n.t("Fix all (xbsl)"), FIX_ALL_KIND);
        action.edit = new vscode.WorkspaceEdit();
        action.edit.set(document.uri, editsFor(document, all));
        actions.push(action);
      }
    }
    return actions;
  }
}
