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
