// Pure core of which documents the LSP client hands to the server (no vscode import), so it can
// be unit-tested under plain Node.
//
// Modules and standalone queries go to the server wherever they are opened. Yaml is narrowed by
// xbsl.projectRoot: a repository also carries yaml nobody wrote for the platform, and the copies
// of the sources (examples, worktrees) that make project rules fire across directories. The
// translation dictionary is the one yaml the narrowing must not cut off: it sits next to the
// project or above it, outside the root, and without it `translation/english-shape` spoke in the
// CLI and in CI but never in the Problems panel.
//
// A glob cannot tell the dictionary of this project from any other directory of the same name.
// The server can: it judges a yaml document outside a narrowed root only when the document is a
// file of the dictionary that serves the root (in_project_scope in xbsl/lsp.py), and its
// whole-project pass runs the file rules over that dictionary as well.
//
// The yaml of a narrowed root is selected by a pattern anchored at the root directory, the way the
// server resolves `--project-root`: an absolute root as it is, a relative one below the workspace
// folder. lspClient.ts turns it into vscode.RelativePattern, and VS Code compares the base of such a
// pattern with the path of a document the way it compares paths everywhere - without regard to case
// except on Linux. A root typed as `d:\projects\TASKS` therefore selects the yaml of
// `D:\Projects\Tasks`, which the server takes for the same directory. A string pattern cannot do
// that: VS Code matches it case-sensitively, against a path with the drive letter in lower case.
//
// A relative root with no workspace folder has no directory to anchor at, and keeps a string
// pattern built from its directory names (rootYamlPattern): the drive letter is dropped, `.` steps
// vanish, `..` takes the step before it, and the names are joined with `/`, which the glob matches
// against either separator. That pattern marks the root wherever it lies; a same-named directory
// elsewhere is turned away by the server, as a copy of the sources under the same relative path is.

import * as path from "path";

// A glob anchored at a directory, in a shape the core builds without the vscode module.
export interface BasePattern {
  base: string;
  pattern: string;
}

// A document filter of the language client.
export interface DocumentFilterShape {
  language: string;
  pattern?: string | BasePattern;
}

// The two forms of the dictionary the engine discovers: a directory of yaml files at any depth,
// or a single file (DICTIONARY_DIR and DICTIONARY_FILE in xbsl/translation/dictionary.py;
// tests/test_lsp.py holds these patterns to those names).
export const DICTIONARY_PATTERNS = ["**/xbsl-translation/**/*.yaml", "**/xbsl-translation.yaml"] as const;

// Every yaml of the workspace: the selector without a narrowed root.
export const ALL_YAML = "**/*.yaml";

// The directory names a root path consists of, in order. A drive (`D:`) or the leading
// separators of a UNC or POSIX path carry nothing a pattern can use, a `.` step names nothing,
// and `..` cancels the step before it; a leading `..` has nothing to cancel and is dropped, since
// the tail below it still marks the root.
export function rootSegments(projectRoot: string): string[] {
  const segments: string[] = [];
  for (const step of projectRoot.trim().replace(/^[A-Za-z]:/, "").split(/[\\/]+/)) {
    if (!step || step === ".") {
      continue;
    }
    if (step === "..") {
      segments.pop();
      continue;
    }
    segments.push(step);
  }
  return segments;
}

// The yaml pattern of a narrowed root. `[`, `]`, `*` and `?` in a directory name are matched
// literally by a class of one character. Braces cannot be: the glob splits a pattern into path
// segments before it reads classes, and an unpaired brace stops that split for the rest of the
// pattern. A name with a brace, like a root with no segments at all (`.`, a bare drive), falls
// back to every yaml - the server still judges only the yaml of its root.
export function rootYamlPattern(projectRoot: string): string {
  const segments = rootSegments(projectRoot);
  if (segments.length === 0 || segments.some((segment) => /[{}]/.test(segment))) {
    return ALL_YAML;
  }
  const literal = (segment: string): string => segment.replace(/[[\]*?]/g, (ch) => `[${ch}]`);
  return `**/${segments.map(literal).join("/")}/**/*.yaml`;
}

// The directory a narrowed root names: below the workspace folder when the root is relative, as
// the server resolves it. Undefined without a root, and for a relative root with no folder open.
export function rootBase(projectRoot: string, folder?: string): string | undefined {
  const root = projectRoot.trim();
  if (!root) {
    return undefined;
  }
  if (folder) {
    return path.resolve(folder, root);
  }
  return path.isAbsolute(root) ? path.resolve(root) : undefined;
}

// The folder a narrowed root names when it is not on disk; undefined without a root or when the
// folder exists. Without that folder the server checks no yaml of the project, and nothing says
// so: a project renamed after the setting was written loses its yaml findings silently.
export function missingRoot(
  projectRoot: string, folder: string | undefined, exists: (dir: string) => boolean,
): string | undefined {
  const base = rootBase(projectRoot, folder);
  return base !== undefined && !exists(base) ? base : undefined;
}

// `folder` is the first workspace folder, the one the server resolves a relative root against.
export function lspDocumentSelector(projectRoot: string, folder?: string): DocumentFilterShape[] {
  // xbql is the standalone query of a virtual table: the server serves it for completion (the
  // whole file is one query) and publishes no diagnostics for it.
  const selector: DocumentFilterShape[] = [{ language: "xbsl" }, { language: "xbql" }];
  const base = rootBase(projectRoot, folder);
  const pattern = base !== undefined ? { base, pattern: ALL_YAML } : rootYamlPattern(projectRoot);
  selector.push({ language: "yaml", pattern });
  if (pattern === ALL_YAML) {
    // The whole folder is the project, and the dictionary is simply one more yaml in it.
    return selector;
  }
  for (const dictionary of DICTIONARY_PATTERNS) {
    selector.push({ language: "yaml", pattern: dictionary });
  }
  return selector;
}
