// Pure core for Quick Fix (no vscode import), so it can be unit-tested under plain Node.
// The vscode glue (positionAt, WorkspaceEdit, the provider) lives in codeActions.ts.

import { FixEdit, RawDiag } from "./report";

// A concrete fix to apply: the offset span, the replacement and the rule it came from
// (for the action title).
export interface FixItem {
  start: number;
  end: number;
  newText: string;
  rule: string;
}

// A stable key for a diagnostic anchor: the editor recovers (line, col, rule) from a
// vscode.Diagnostic (range start + code) and looks the fix up by the same key.
export function anchorKey(line1: number, col1: number, rule: string): string {
  return `${line1}:${col1}:${rule}`;
}

// Map of anchor key -> fix, for the diagnostics of one document that carry a fix.
export function fixIndex(diags: RawDiag[]): Map<string, FixEdit> {
  const out = new Map<string, FixEdit>();
  for (const d of diags) {
    if (d.fix) {
      out.set(anchorKey(d.line, d.col, d.rule), d.fix);
    }
  }
  return out;
}

// All span fixes of a document as flat items (order preserved).
export function collectFixes(diags: RawDiag[]): FixItem[] {
  const out: FixItem[] = [];
  for (const d of diags) {
    if (d.fix) {
      out.push({ start: d.fix.start, end: d.fix.end, newText: d.fix.newText, rule: d.rule });
    }
  }
  return out;
}

// Non-overlapping selection for "fix all" / fix-on-save: earliest start wins, ties by the
// longer span. Mirrors the engine's fixer so the editor and `xbsl --fix` agree.
export function selectNonOverlapping(fixes: FixItem[]): FixItem[] {
  const sorted = [...fixes].sort(
    (a, b) => a.start - b.start || b.end - b.start - (a.end - a.start)
  );
  const chosen: FixItem[] = [];
  let lastEnd = -1;
  for (const f of sorted) {
    if (f.start >= lastEnd) {
      chosen.push(f);
      lastEnd = f.end;
    }
  }
  return chosen;
}
