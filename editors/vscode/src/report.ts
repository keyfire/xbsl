// Pure helpers (no vscode import) so they can be unit-tested under plain Node:
// parsing the linter's JSON, mapping severity, building CLI args and computing a range.

// A mechanical fix the linter attached to a finding: replace the file's [start, end) with
// newText. Offsets are 0-based character offsets into the file text sent to the linter
// (matches vscode.TextDocument.positionAt for all non-astral characters, which covers XBSL).
export interface FixEdit {
  start: number;
  end: number;
  newText: string;
}

export interface RawDiag {
  path: string;
  line: number; // 1-based
  col: number; // 1-based
  rule: string;
  severity: string; // "error" | "warning" | "info"
  message: string;
  fix?: FixEdit; // present only for mechanically fixable findings (span fixes)
}

export interface RawReport {
  diagnostics: RawDiag[];
  summary?: { files: number; diagnostics: number; errors: number; warnings: number };
}

export interface LinterConfig {
  command: string; // executable: "xbsl", or a Python interpreter when usePython is set
  usePython: boolean; // when true, invoke `<command> -m xbsl`
  dataDir?: string;
  lang?: string; // "ru" | "en"
  select?: string;
  ignore?: string;
  baseline?: string; // an EXISTING baseline file: excluded findings are suppressed
}

// Whether the diagnostic is ours: the new engine signs them with source "xbsl", the engine
// before the rename - "xbsllint"; both are accepted so actions work with an old installed
// engine too.
export function isXbslSource(diag: { source?: string }): boolean {
  return diag.source === "xbsl" || diag.source === "xbsllint";
}

export function parseReport(stdout: string): RawReport {
  const data = JSON.parse(stdout);
  if (!data || !Array.isArray(data.diagnostics)) {
    throw new Error("linter output has no 'diagnostics' array");
  }
  return data as RawReport;
}

// Maps to the numeric values of vscode.DiagnosticSeverity: Error 0, Warning 1, Information 2, Hint 3.
export function severityCode(severity: string): 0 | 1 | 2 | 3 {
  switch (severity) {
    case "error":
      return 0;
    case "warning":
      return 1;
    case "info":
      return 2;
    default:
      return 2;
  }
}

export function buildArgs(filename: string, cfg: LinterConfig): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("--stdin", "--filename", filename, "--format", "json");
  if (cfg.lang) {
    args.push("--lang", cfg.lang);
  }
  if (cfg.dataDir) {
    args.push("--data-dir", cfg.dataDir);
  }
  if (cfg.select) {
    args.push("--select", cfg.select);
  }
  if (cfg.ignore) {
    args.push("--ignore", cfg.ignore);
  }
  if (cfg.baseline) {
    args.push("--baseline", cfg.baseline);
  }
  return args;
}

// Command line for checking a whole path on disk (the "lint project" command).
export function buildPathArgs(target: string, cfg: LinterConfig): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("--format", "json");
  if (cfg.lang) {
    args.push("--lang", cfg.lang);
  }
  if (cfg.dataDir) {
    args.push("--data-dir", cfg.dataDir);
  }
  if (cfg.select) {
    args.push("--select", cfg.select);
  }
  if (cfg.ignore) {
    args.push("--ignore", cfg.ignore);
  }
  if (cfg.baseline) {
    args.push("--baseline", cfg.baseline);
  }
  args.push(target);
  return args;
}

export interface Span {
  sl: number; // 0-based start line
  sc: number; // 0-based start character
  el: number;
  ec: number;
}

// The linter anchors a diagnostic at a single 1-based point. VS Code needs a range, so we widen
// the anchor to the word under it (or a single character), converting to 0-based coordinates.
export function computeRange(lineText: string | undefined, line1: number, col1: number): Span {
  const sl = Math.max(0, line1 - 1);
  const sc0 = Math.max(0, col1 - 1);
  if (lineText === undefined) {
    return { sl, sc: sc0, el: sl, ec: sc0 + 1 };
  }
  const start = Math.min(sc0, lineText.length);
  const rest = lineText.slice(start);
  const word = /^[_A-Za-zА-Яа-яЁё0-9]+/.exec(rest);
  let ec: number;
  if (word && word[0].length > 0) {
    ec = start + word[0].length;
  } else if (start < lineText.length) {
    ec = start + 1;
  } else {
    ec = start;
  }
  return { sl, sc: start, el: sl, ec: Math.max(ec, start) };
}
