// Pure core of the baseline exclusions (no vscode import), unit-tested under plain Node:
// parsing the linter's baseline JSON and adding one excluded finding with its reason.
//
// The file format belongs to the engine (xbsl/baseline.py): {meta, files: {path:
// {rule: {message: count | {count, reason}}}}}, identity paths POSIX-relative to the
// baseline file's directory. This module mirrors it: bare counts stay bare, an exclusion
// made from the editor always carries a reason. Keys are kept sorted the way the engine
// writes them, so a hand-run `--write-baseline` and an editor exclusion produce
// merge-friendly diffs.

export interface BaselineEntry {
  count: number;
  reason?: string;
}

type MessageMap = Record<string, number | BaselineEntry>;
type RuleMap = Record<string, MessageMap>;

export interface BaselineFile {
  meta?: unknown;
  files: Record<string, RuleMap>;
}

// Mirrors the meta the engine writes (xbsl/baseline.py, build()).
const META = {
  tool: "xbsl",
  format: 1,
  note:
    "исключённые находки: путь -> правило -> сообщение -> количество или" +
    " {count, reason}; файл создаётся xbsl --write-baseline, исключение" +
    " с причиной добавляет расширение VS Code (или правка руками)",
};

export function parseBaseline(text: string | undefined): BaselineFile {
  if (text === undefined || text.trim() === "") {
    return { meta: META, files: {} };
  }
  const data = JSON.parse(text) as BaselineFile;
  if (!data || typeof data !== "object" || !data.files || typeof data.files !== "object") {
    throw new Error("baseline file has no 'files' object");
  }
  return data;
}

function entryCount(value: number | BaselineEntry | undefined): number {
  if (typeof value === "number") {
    return value;
  }
  if (value && typeof value === "object" && typeof value.count === "number") {
    return value.count;
  }
  return 0;
}

function sorted<T>(obj: Record<string, T>): Record<string, T> {
  const out: Record<string, T> = {};
  for (const key of Object.keys(obj).sort()) {
    out[key] = obj[key];
  }
  return out;
}

// Adds one excluded finding: bumps the identity's count and records the reason (a repeat
// exclusion of the same identity overwrites it – the last decision wins). Returns the new
// file text; the input text may be undefined (no baseline yet – a fresh file is created).
export function addExclusion(
  text: string | undefined,
  relPosixPath: string,
  rule: string,
  message: string,
  reason: string
): string {
  const data = parseBaseline(text);
  const perRule: RuleMap = data.files[relPosixPath] ?? {};
  const perMessage: MessageMap = perRule[rule] ?? {};
  perMessage[message] = { count: entryCount(perMessage[message]) + 1, reason };
  perRule[rule] = perMessage;
  data.files[relPosixPath] = perRule;
  data.files = sorted(data.files);
  if (!data.meta) {
    data.meta = META;
  }
  // The engine writes json.dumps(indent=1) + "\n" – JSON.stringify(data, null, 1) matches.
  return JSON.stringify(data, null, 1) + "\n";
}

// Windows path separators are not identity separators: the engine stores POSIX paths.
export function toPosix(p: string): string {
  return p.replace(/\\/g, "/");
}
