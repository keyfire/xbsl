// Pure core of the workspace-run bookkeeping (no vscode import), so it can be unit-tested
// under plain Node: lays the raw diagnostics of one whole-workspace run out per file. The
// extension stores these RawDiag lists alongside the converted diagnostics, so a file opened
// AFTER the run can still get its Quick Fix snapshot (the run itself stamps only the
// documents that are open at the time).

import * as path from "path";
import { RawDiag } from "./report";

// Groups the run's diagnostics by the absolute path of their file, dropping the rules the
// user turned off. The linter echoes paths as given (the extension passes the folder
// absolute, so they come back absolute with OS separators); relative ones are resolved
// against the folder.
export function groupReportByFile(
  diagnostics: RawDiag[],
  folderFsPath: string,
  isOff: (rule: string) => boolean
): Map<string, RawDiag[]> {
  const out = new Map<string, RawDiag[]>();
  for (const d of diagnostics) {
    if (isOff(d.rule)) {
      continue;
    }
    const fsPath = path.isAbsolute(d.path) ? d.path : path.join(folderFsPath, d.path);
    const list = out.get(fsPath);
    if (list) {
      list.push(d);
    } else {
      out.set(fsPath, [d]);
    }
  }
  return out;
}

// The language of the engine's messages when the setting is empty: the VS Code display
// language, NOT the OS locale. Without this the engine falls back to XBSL_LANG / the
// system locale, so an English editor on a Russian system showed Russian diagnostics next
// to an English UI. Only ru and en exist in the engine; any other display language reads
// as English (the international default), and an explicit setting always wins.
export function resolveMessageLanguage(setting: string, displayLanguage: string): string {
  const explicit = (setting || "").trim();
  if (explicit) {
    return explicit;
  }
  return (displayLanguage || "").toLowerCase().startsWith("ru") ? "ru" : "en";
}
