import * as vscode from "vscode";
import { spawn } from "child_process";
import {
  buildArgs,
  buildPathArgs,
  computeRange,
  LinterConfig,
  parseReport,
  RawDiag,
  RawReport,
  severityCode,
} from "./report";

export interface RunResult {
  report?: RawReport;
  // A human-readable problem (spawn failure, non-JSON output, data error) – shown to the user once.
  error?: string;
  // The run was cancelled (a newer one superseded it) – not an error, just ignore the result.
  canceled?: boolean;
}

// A running linter process: the eventual result plus a way to cancel it early.
export interface RunHandle {
  result: Promise<RunResult>;
  cancel: () => void;
}

interface RunOptions {
  cwd?: string;
  stdin?: string;
  // Kill the process after this many milliseconds (0 / undefined – no limit).
  timeoutMs?: number;
}

const DECODER_LIMIT = 8 * 1024 * 1024; // guard against a runaway process

function runProcess(command: string, args: string[], opts: RunOptions): RunHandle {
  let cancel: () => void = () => undefined;
  const result = new Promise<RunResult>((resolve) => {
    let child;
    try {
      child = spawn(command, args, { cwd: opts.cwd });
    } catch (e) {
      resolve({ error: describeSpawnError(command, e) });
      return;
    }
    let out = "";
    let err = "";
    let tooBig = false;
    let canceled = false;
    let timedOut = false;
    let timer: NodeJS.Timeout | undefined;
    if (opts.timeoutMs && opts.timeoutMs > 0) {
      timer = setTimeout(() => {
        timedOut = true;
        child.kill();
      }, opts.timeoutMs);
    }
    cancel = () => {
      canceled = true;
      child.kill();
    };
    child.on("error", (e) => {
      if (timer) {
        clearTimeout(timer);
      }
      resolve({ error: describeSpawnError(command, e) });
    });
    child.stdout.on("data", (d: Buffer) => {
      if (out.length < DECODER_LIMIT) {
        out += d.toString("utf8");
      } else {
        tooBig = true;
      }
    });
    child.stderr.on("data", (d: Buffer) => {
      err += d.toString("utf8");
    });
    child.on("close", (code) => {
      if (timer) {
        clearTimeout(timer);
      }
      if (canceled) {
        resolve({ canceled: true });
        return;
      }
      if (timedOut) {
        resolve({ error: `линтер не уложился в ${opts.timeoutMs} мс и был остановлен` });
        return;
      }
      if (tooBig) {
        resolve({ error: "linter produced too much output" });
        return;
      }
      // Exit code 1 just means "errors among the diagnostics" – still valid JSON on stdout.
      // A real failure (missing data, crash) leaves stdout empty / non-JSON; surface stderr.
      try {
        resolve({ report: parseReport(out) });
      } catch {
        const detail = (err || out || `exit code ${code}`).trim();
        resolve({ error: detail });
      }
    });
    if (child.stdin) {
      child.stdin.on("error", () => {
        /* ignore EPIPE if the child exits early */
      });
      child.stdin.end(opts.stdin !== undefined ? Buffer.from(opts.stdin, "utf8") : undefined);
    }
  });
  return { result, cancel: () => cancel() };
}

function describeSpawnError(command: string, e: unknown): string {
  const err = e as NodeJS.ErrnoException;
  if (err && err.code === "ENOENT") {
    return `не найден исполняемый файл линтера "${command}". Установите xbsllint (pip install xbsllint) или задайте xbsl.linter.command / xbsl.linter.pythonPath.`;
  }
  return `не удалось запустить линтер "${command}": ${err && err.message ? err.message : String(e)}`;
}

// Check one buffer via `xbsllint --stdin` (per-file rules only).
export function lintBuffer(
  text: string,
  filename: string,
  cwd: string | undefined,
  cfg: LinterConfig
): Promise<RunResult> {
  return runProcess(cfg.command, buildArgs(filename, cfg), { cwd, stdin: text }).result;
}

// Check a whole path on disk via `xbsllint <path>` (includes cross-file rules).
// Returns a handle so the caller can cancel a run that a newer save has made stale.
export function lintPath(
  target: string,
  cwd: string | undefined,
  cfg: LinterConfig,
  timeoutMs?: number
): RunHandle {
  return runProcess(cfg.command, buildPathArgs(target, cfg), { cwd, timeoutMs });
}

// Builds a diagnostic; lineText (when known) lets us widen the anchor to the word under it.
export function makeDiagnostic(d: RawDiag, lineText: string | undefined): vscode.Diagnostic {
  const span = computeRange(lineText, d.line, d.col);
  const range = new vscode.Range(span.sl, span.sc, span.el, span.ec);
  const diag = new vscode.Diagnostic(range, d.message, severityCode(d.severity));
  diag.source = "xbsllint";
  diag.code = d.rule;
  return diag;
}

export function toDiagnostic(d: RawDiag, doc: vscode.TextDocument): vscode.Diagnostic {
  const li = Math.min(Math.max(0, d.line - 1), Math.max(0, doc.lineCount - 1));
  const lineText = doc.lineCount > 0 ? doc.lineAt(li).text : undefined;
  return makeDiagnostic(d, lineText);
}
