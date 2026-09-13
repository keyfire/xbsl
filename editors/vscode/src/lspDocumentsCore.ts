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

// A document filter of the language client: the shape vscode-languageclient takes as is.
export interface DocumentFilterShape {
  language: string;
  pattern?: string;
}

// The two forms of the dictionary the engine discovers: a directory of yaml files at any depth,
// or a single file (DICTIONARY_DIR and DICTIONARY_FILE in xbsl/translation/dictionary.py;
// tests/test_lsp.py holds these patterns to those names).
export const DICTIONARY_PATTERNS = ["**/xbsl-translation/**/*.yaml", "**/xbsl-translation.yaml"] as const;

export function lspDocumentSelector(projectRoot: string): DocumentFilterShape[] {
  // xbql is the standalone query of a virtual table: the server serves it for completion (the
  // whole file is one query) and publishes no diagnostics for it.
  const selector: DocumentFilterShape[] = [{ language: "xbsl" }, { language: "xbql" }];
  const root = projectRoot.trim();
  if (!root) {
    // The whole folder is the project, and the dictionary is simply one more yaml in it.
    selector.push({ language: "yaml", pattern: "**/*.yaml" });
    return selector;
  }
  selector.push({ language: "yaml", pattern: `**/${root}/**/*.yaml` });
  for (const pattern of DICTIONARY_PATTERNS) {
    selector.push({ language: "yaml", pattern });
  }
  return selector;
}
