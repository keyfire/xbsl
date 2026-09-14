// Pure core of the workspace-run bookkeeping (no vscode import), so it can be unit-tested
// under plain Node: lays the raw diagnostics of one whole-workspace run out per file. The
// extension stores these RawDiag lists alongside the converted diagnostics, so a file opened
// AFTER the run can still get its Quick Fix snapshot (the run itself stamps only the
// documents that are open at the time).

import * as path from "path";
import { RawDiag, RawReport } from "./report";

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

// --- What a workspace run reads --------------------------------------------------------------
//
// A workspace run reads the project root and, when it lies outside the root, the translation
// dictionary that serves the project. The dictionary is a run of its own rather than a second path
// of the same run: handed to the project rules, it would change their verdict on the project, since
// `code/unused-method` counts every word of every source as a mention and the dictionary names
// every method. The LSP server keeps the dictionary away from the project rules for the same reason
// (dictionary_sources in xbsl/lsp.py). A run over the dictionary alone finds what the file rules
// find: the project rules have no element to judge there.
//
// What the run read also bounds what its silence means. A file the run read and did not mention is
// clean; a document it never read - a module opened outside the root - owes its findings to the
// check of its buffer, and a run that wiped them would leave that module blank until the next
// keystroke.

// The two names the engine discovers the dictionary by (DICTIONARY_DIR and DICTIONARY_FILE in
// xbsl/translation/dictionary.py; tests/test_lsp_roots.py holds these to those names).
export const DICTIONARY_DIR = "xbsl-translation";
export const DICTIONARY_FILE = "xbsl-translation.yaml";

// What lies at a path, as far as the discovery cares.
export type PathKind = "dir" | "file" | undefined;

// The dictionary the engine discovers for a project root: a directory or a single file of the
// names above, in the root or in the nearest of its parents that has one (dictionary.discover).
export function discoverDictionary(root: string, kind: (p: string) => PathKind): string | undefined {
  let current = kind(root) === "dir" ? root : path.dirname(root);
  for (;;) {
    const asDir = path.join(current, DICTIONARY_DIR);
    if (kind(asDir) === "dir") {
      return asDir;
    }
    const asFile = path.join(current, DICTIONARY_FILE);
    if (kind(asFile) === "file") {
      return asFile;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      return undefined;
    }
    current = parent;
  }
}

// The steps from `base` down to `target`: empty for the base itself, undefined for a target outside
// it. The comparison is the platform's - case-insensitive on Windows, where VS Code spells the drive
// letter of a document in lower case while the setting may spell it in upper case.
function stepsBelow(target: string, base: string): string[] | undefined {
  const relative = path.relative(base, target);
  if (relative === "") {
    return [];
  }
  if (path.isAbsolute(relative) || relative === ".." || relative.startsWith(`..${path.sep}`)) {
    return undefined;
  }
  return relative.split(path.sep);
}

// Whether a file lies at `base` or below it outside hidden directories, which the engine skips when
// it collects sources (find_sources in xbsl/engine.py).
function collectedBelow(target: string, base: string): boolean {
  const steps = stepsBelow(target, base);
  return steps !== undefined && !steps.some((step) => step.startsWith("."));
}

// The reach of one workspace run: the project root, plus the dictionary when it was checked by a
// run of its own.
export interface RunScope {
  root: string;
  dictionary?: string;
}

// The dictionary a workspace run checks apart from the root: one outside the root. A dictionary
// inside the root is already read by the run over the root, as it is by the CLI.
export function dictionaryOutsideRoot(root: string, dictionary: string | undefined): string | undefined {
  return dictionary !== undefined && stepsBelow(dictionary, root) === undefined ? dictionary : undefined;
}

// Whether the run of this scope read the file, so that its silence about the file means "clean".
export function readByRun(fsPath: string, scope: RunScope): boolean {
  return collectedBelow(fsPath, scope.root)
    || (scope.dictionary !== undefined && collectedBelow(fsPath, scope.dictionary));
}

// Whether a file is a yaml of the dictionary. The check of an open buffer takes these along with
// modules: the engine judges the dictionary by its file rules, and without this the dictionary got
// no findings as it was typed.
export function isDictionaryFile(fsPath: string, dictionary: string | undefined): boolean {
  return dictionary !== undefined
    && fsPath.toLowerCase().endsWith(".yaml")
    && collectedBelow(fsPath, dictionary);
}

// The reports of the runs over the root and over the dictionary, as one report.
export function mergeReports(reports: RawReport[]): RawReport {
  const diagnostics = reports.flatMap((report) => report.diagnostics ?? []);
  const summaries = reports.flatMap((report) => (report.summary ? [report.summary] : []));
  if (summaries.length === 0) {
    return { diagnostics };
  }
  const total = (field: "files" | "diagnostics" | "errors" | "warnings"): number =>
    summaries.reduce((sum, summary) => sum + (summary[field] ?? 0), 0);
  return {
    diagnostics,
    summary: {
      files: total("files"),
      diagnostics: total("diagnostics"),
      errors: total("errors"),
      warnings: total("warnings"),
    },
  };
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
