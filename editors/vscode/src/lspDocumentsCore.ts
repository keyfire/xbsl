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
// The pattern of the root is built from the path the setting names, not pasted from it. VS Code
// matches a string pattern against the fsPath of the document, case-sensitively, and that fsPath
// carries the drive letter in LOWER case (d:\projects\tasks). A root written the way Explorer
// copies it, `D:\Projects\tasks`, became `**/D:\Projects\tasks/**/*.yaml` and matched no file at
// all, and so did `./src/app` and a root ending in a separator: the server understood each of them,
// but no yaml of the project reached it. So the drive letter is dropped, `.` steps vanish, `..`
// takes the step before it, and the directory names are joined with `/`, which the glob matches
// against either separator. What is left marks the root wherever it lies; a same-named directory
// elsewhere is turned away by the server, as a copy of the sources under the same relative path is.

// A document filter of the language client: the shape vscode-languageclient takes as is.
export interface DocumentFilterShape {
  language: string;
  pattern?: string;
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

export function lspDocumentSelector(projectRoot: string): DocumentFilterShape[] {
  // xbql is the standalone query of a virtual table: the server serves it for completion (the
  // whole file is one query) and publishes no diagnostics for it.
  const selector: DocumentFilterShape[] = [{ language: "xbsl" }, { language: "xbql" }];
  const pattern = rootYamlPattern(projectRoot);
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
