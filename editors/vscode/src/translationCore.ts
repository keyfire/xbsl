// Pure core of the translation dictionary panel (no vscode import), so plain Node can test it:
// the engine's command line, its answers, the merge of dictionary ENTRIES with the GAPS report
// into one table, and the filtering, sorting and paging the panel draws.
//
// Nothing here reads or writes yaml. The dictionary is a directory of yaml files with a layout
// of its own (targets, scopes, resource keys), and the engine already owns it: `xbsl translate
// --entries` lists it, `--gaps` says what it does not cover yet, `--set` writes. A panel that
// parsed those files itself would be a second implementation of the format - the one that goes
// stale first.

import { compareVersions } from "./updateCheckCore";

// The three planes of the dictionary, as the engine names them: `tokens` (project names),
// `phrases` (whole comment lines) and `literals` (the text between the quotes of a string
// literal). A literal is the odd one: its key and its value are written the way the SOURCE
// writes them - an inner quote is \", a backslash is \\ - because the value goes back
// between two quotes, and the engine refuses anything that could not stand there.
export type EntryKind = "token" | "phrase" | "literal";

// A record of the dictionary as `--entries` reports it: the key (a project name, a whole
// comment line, or the body of a string literal), its translation and where the record lives.
export interface DictionaryEntry {
  key: string;
  value: string;
  kind: EntryKind;
  file: string; // the dictionary yaml holding the record (absolute)
  line: number;
  scope?: string; // the owner a scoped name is translated inside of
}

// One occurrence of an untranslated surface: a source file (relative to the project root) and
// the line in it.
export interface GapPlace {
  file: string;
  line: number;
}

// What `--gaps` reports about a key the dictionary does not cover.
export interface DictionaryGap {
  key: string;
  kind: EntryKind;
  count: number;
  places: GapPlace[];
  suggestion?: string; // the platform's own spelling, when it has one
  resource?: boolean;
}

// A row of the panel's table: a dictionary record, a gap, or a record that is also a gap.
// `value` empty means the gap - the only difference the table draws between the two.
export interface DictionaryRow {
  kind: EntryKind;
  key: string;
  value: string;
  suggestion: string;
  // The machine-translation service's own guess. Unlike `suggestion` (filled in by `mergeRows`
  // from every `--gaps` read), this arrives only after the panel is told to ask for one and is
  // merged in at render time - a plain read of the dictionary never spends a service call nobody
  // asked for.
  machineSuggestion?: string;
  // The one ghost the translation cell actually shows, resolved by `rowHint` and attached only
  // for the page being drawn - `suggestion` and `machineSuggestion` used to live in two separate
  // columns and could both be on screen together; now they share the one field a hand-typed
  // answer already fills, so a priority has to be picked before either reaches the table.
  hint?: string;
  hintFromMachine?: boolean;
  count: number; // occurrences in the sources; 0 when the gaps report says nothing about it
  place?: GapPlace; // the first occurrence, for the jump to the source
  file: string; // the dictionary yaml holding the record; empty for a gap
  line: number;
  scope: string;
  resource: boolean;
}

export interface EngineConfig {
  command: string; // the executable: "xbsl", or a Python interpreter when usePython is set
  usePython: boolean; // when set, the engine is invoked as `<command> -m xbsl`
  root: string; // the project directory (the one with Проект.yaml) - the `translate` argument
  dictionary?: string; // an explicit dictionary path; empty - the engine discovers it itself
}

export type TranslateMode = "entries" | "gaps" | "summary";

export interface TranslateQuery {
  filter?: string;
  kind?: EntryKind | "any";
  limit?: number; // 0 - everything; undefined - the engine's own default
  offset?: number;
}

// The command line of a reading run: `xbsl translate <root> --entries|--gaps ... --format json`.
export function translateArgs(mode: TranslateMode, cfg: EngineConfig, query: TranslateQuery = {}): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("translate", cfg.root);
  if (mode !== "summary") {
    args.push(`--${mode}`);
  }
  if (cfg.dictionary) {
    args.push("--dictionary", cfg.dictionary);
  }
  if (query.filter) {
    args.push("--filter", query.filter);
  }
  if (query.kind && query.kind !== "any") {
    args.push("--kind", query.kind);
  }
  // limit 0 means "everything" and MUST be passed: dropped as falsy it would leave the engine
  // on its own default page and the table would silently end after it.
  if (query.limit !== undefined) {
    args.push("--limit", String(query.limit));
  }
  if (query.offset) {
    args.push("--offset", String(query.offset));
  }
  args.push("--format", "json");
  return args;
}

// The command line of a write: the edits file is `[{key, value, kind}]`, an empty value removes
// the record.
export function setArgs(cfg: EngineConfig, editsFile: string): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("translate", cfg.root, "--set", editsFile);
  if (cfg.dictionary) {
    args.push("--dictionary", cfg.dictionary);
  }
  args.push("--format", "json");
  return args;
}

// --- the engine the panel needs -------------------------------------------------------------

// `translate --entries`, `--gaps` and `--set` are the whole panel, and the engine only learned
// them in 0.70.0. An older one answers an argparse dump ("unrecognized arguments"), which names
// neither the cause nor the cure - and the extension and the engine are installed apart, so a
// new panel over an old engine is the ordinary state right after a release.
//
// 0.72.0 rather than 0.71.0 because `--suggest`, the machine-translation run behind the panel's
// suggestions button, only arrived there. On an older engine the same argparse dump would answer
// it, unreadable as ever - a panel that offers the button is worse than one that refuses to open
// and names the cure.
export const MIN_ENGINE = "0.72.0";

// The command line that asks the engine its version - the same binary the table runs, so a
// Python interpreter is asked through `-m xbsl`.
export function versionArgs(cfg: EngineConfig): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("--version");
  return args;
}

// The version out of the `--version` output, whichever stream carried it. The tool NAMES
// itself first ("xbsl 0.70.0 (...)"), and the number is read only after that name: a bare
// pattern picked up any version-looking number in the output - a warning about a dependency
// was enough to report the wrong version and lock the panel.
export function engineVersion(out: string): string | undefined {
  const match = /\bxbsl\s+v?(\d+\.\d+(?:\.\d+)?[A-Za-z0-9.+-]*)/i.exec(out ?? "");
  return match ? match[1] : undefined;
}

// The installed version when it is too old for the panel, undefined when it will do. Output we
// cannot read counts as "it will do": a version that failed to parse must not lock a working
// engine out of the dictionary. Comparison goes by the numeric CORE, so a pre-release of the
// minimum passes - it carries the commands, and "update the engine" would be advice pip cannot
// follow.
export function outdatedEngine(out: string, minimum: string = MIN_ENGINE): string | undefined {
  const version = engineVersion(out);
  if (!version) {
    return undefined;
  }
  return compareVersions(versionCore(version), versionCore(minimum)) < 0 ? version : undefined;
}

// `0.70.0-rc1` and `0.70.0+local` are the 0.70.0 engine: the suffix says how it was built, not
// what it can do.
function versionCore(version: string): string {
  const match = /^\d+(?:\.\d+)*/.exec(version);
  return match ? match[0] : version;
}

export interface EntriesAnswer {
  dictionary: string;
  total: number;
  entries: DictionaryEntry[];
}

export interface GapsAnswer {
  dictionary: string;
  total: number;
  gaps: DictionaryGap[];
}

// An edit the engine would not write. Only a literal is ever refused: its value is pasted back
// between two quotes, so a bare quote, a dangling backslash or a newline would end the literal
// early and stop the module from compiling. The engine checks that WHILE the value is in hand
// rather than at the next load, and names the reason in the reader's language.
export interface RefusedEdit {
  key: string;
  kind: EntryKind;
  reason: string;
}

export interface SetAnswer {
  changed: number;
  added: number;
  removed: number;
  refused: RefusedEdit[];
}

function decode(stdout: string): Record<string, unknown> {
  const data = JSON.parse(stdout) as Record<string, unknown> | null;
  if (data && typeof data.error === "string") {
    throw new Error(data.error);
  }
  if (!data || typeof data !== "object") {
    throw new Error("xbsl translate: unexpected output");
  }
  return data;
}

export function parseEntries(stdout: string): EntriesAnswer {
  const data = decode(stdout);
  if (!Array.isArray(data.entries)) {
    throw new Error("xbsl translate --entries: no 'entries' array in the answer");
  }
  return {
    dictionary: String(data.dictionary ?? ""),
    total: Number(data.total ?? (data.entries as unknown[]).length),
    entries: data.entries as DictionaryEntry[],
  };
}

export function parseGaps(stdout: string): GapsAnswer {
  const data = decode(stdout);
  if (!Array.isArray(data.gaps)) {
    throw new Error("xbsl translate --gaps: no 'gaps' array in the answer");
  }
  return {
    dictionary: String(data.dictionary ?? ""),
    total: Number(data.total ?? (data.gaps as unknown[]).length),
    gaps: data.gaps as DictionaryGap[],
  };
}

// The coverage line of the panel's header: the report `xbsl translate <root>` gives without
// any flag. It is the same number CI gates on, so the panel and the pipeline cannot disagree.
export interface TranslationTotals {
  surfaces: number;
  translated: number;
  missing: number;
  coverage: number; // 0..1
  // The literals are counted apart from the coverage, the way the engine counts them: a name
  // has one right spelling and a sentence between quotes has not, so they are not one number.
  // Kept out of the header a project could read "coverage 100%" with its messages still in
  // Cyrillic - the exact blind spot the literals plane was added to end.
  literalsTranslated: number;
  literalsMissing: number;
}

export function parseSummary(stdout: string): TranslationTotals {
  const data = decode(stdout);
  const totals = (data.totals ?? {}) as Record<string, unknown>;
  return {
    surfaces: Number(totals.surfaces ?? 0),
    translated: Number(totals.translated ?? 0),
    missing: Number(totals.missing ?? 0),
    coverage: Number(totals.coverage ?? 0),
    literalsTranslated: Number(totals.literals_translated ?? 0),
    literalsMissing: Number(totals.missing_literals ?? 0),
  };
}

export function parseSetResult(stdout: string): SetAnswer {
  const data = decode(stdout);
  const refused = Array.isArray(data.refused) ? (data.refused as RefusedEdit[]) : [];
  return {
    changed: Number(data.changed ?? 0),
    added: Number(data.added ?? 0),
    removed: Number(data.removed ?? 0),
    // A refusal is not an engine error: the run may have written the other edits of the same
    // file and still turned one away. Read as a plain success it would be swallowed - the
    // status line would report "the dictionary is updated" over an entry that never landed.
    refused: refused.filter((item) => item && typeof item.key === "string"),
  };
}

// The refusals as one line for a message box: which entry, and why the engine would not take
// it. The key is trimmed - a literal runs to hundreds of characters and would push the reason,
// the only actionable half, off the screen.
export function refusalText(refused: RefusedEdit[]): string {
  return refused.map((item) => `"${shortKey(item.key, 60)}": ${item.reason}`).join("; ");
}

// --- machine-translation suggestions --------------------------------------------------------

// The command line of a machine-translation run: `xbsl translate <root> --suggest --provider
// <name> --format json`. The key is NEVER an argument - it travels in the environment of the
// spawned process instead, so a process list never carries it. `--provider` is passed only when
// the caller chose one; left out, the engine picks the one service it finds configured (and
// refuses when that is ambiguous or absent - `parseSuggest` reads that refusal from `error`).
export function suggestArgs(cfg: EngineConfig, provider?: string): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("translate", cfg.root, "--suggest");
  if (cfg.dictionary) {
    args.push("--dictionary", cfg.dictionary);
  }
  if (provider) {
    args.push("--provider", provider);
  }
  args.push("--format", "json");
  return args;
}

// One row of what the machine-translation run offers: a suggested value for a key still
// missing from the dictionary. Nothing is written until the reader accepts it through the
// panel's existing "set" message - a suggestion is a suggestion.
export interface SuggestRow {
  key: string;
  value: string;
  kind: EntryKind;
}

export interface SuggestAnswer {
  dictionary: string;
  rows: SuggestRow[];
  cached: number; // answered from the dictionary's own cache, no service call spent
  requested: number; // asked of the external service this run
  refused: number;
  // What the count alone cannot say: which entry, and why the service or the engine turned it
  // away. Read with the same builder a refused --set edit uses - the shape is identical, and a
  // reader does not care which run produced the refusal.
  refusals: RefusedEdit[];
}

// The engine's actual `--suggest --format json` answer:
// `{"dictionary": "...", "machine": {"cached", "requested", "refused", "refusals": [...]},
//   "suggestions": [{"key", "value", "kind"}]}`.
export function parseSuggest(stdout: string): SuggestAnswer {
  const data = decode(stdout);
  const machine = (data.machine ?? {}) as Record<string, unknown>;
  const refusals = Array.isArray(machine.refusals)
    ? (machine.refusals as RefusedEdit[]).filter((item) => item && typeof item.key === "string")
    : [];
  return {
    dictionary: String(data.dictionary ?? ""),
    rows: Array.isArray(data.suggestions) ? (data.suggestions as SuggestRow[]) : [],
    cached: Number(machine.cached ?? 0),
    requested: Number(machine.requested ?? 0),
    refused: Number(machine.refused ?? 0),
    refusals,
  };
}

// Wraps an async job so a call that arrives while the PREVIOUS call is still running does
// nothing and settles to `undefined` at once, instead of starting the job again. Unlike a serial
// queue (every job still gets its turn, just delayed), the repeat is dropped outright - and that
// difference is the point here: `--suggest` reaches a paid external service, so a second click
// while the first run is still in flight must spend the service's quota zero extra times, not
// twice with a delay. The guard releases on every outcome, success or a thrown error alike -
// a failed run must not leave the button unusable for good.
export function guardConcurrent<T>(job: () => Promise<T>): () => Promise<T | undefined> {
  let running = false;
  return async () => {
    if (running) {
      return undefined;
    }
    running = true;
    try {
      return await job();
    } finally {
      running = false;
    }
  };
}

// A row's identity in the table and in the messages of the panel. A name and a comment line can
// read the same and mean different records, so the kind is part of the key.
export function rowKey(kind: EntryKind, key: string): string {
  return `${kind}\u0000${key}`;
}

export interface RowHint {
  value: string;
  fromMachine: boolean;
}

// The single ghost the translation cell offers for a still-empty row: the platform's own
// spelling first - an official term table, not a guess - and the machine-translation service's
// guess only when the platform has none. A row that already carries a value offers nothing: the
// hint used to live in its own column and could sit next to a real answer; now the two share the
// one field a hand-typed answer fills, so an unwritten guess must never be mistaken for it.
export function rowHint(row: DictionaryRow): RowHint | undefined {
  if (row.value) {
    return undefined;
  }
  if (row.suggestion) {
    return { value: row.suggestion, fromMachine: false };
  }
  if (row.machineSuggestion) {
    return { value: row.machineSuggestion, fromMachine: true };
  }
  return undefined;
}

// The table the panel draws: every dictionary record plus every gap. A key that is both (the
// record exists but the sources still show it as uncovered - a resource key, a stale value)
// keeps its record and takes the occurrences from the gap, so one line says everything about it.
export function mergeRows(entries: DictionaryEntry[], gaps: DictionaryGap[]): DictionaryRow[] {
  const rows = new Map<string, DictionaryRow>();
  for (const entry of entries) {
    rows.set(rowKey(entry.kind, entry.key), {
      kind: entry.kind,
      key: entry.key,
      value: entry.value ?? "",
      suggestion: "",
      count: 0,
      file: entry.file ?? "",
      line: Number(entry.line ?? 0),
      scope: entry.scope ?? "",
      resource: false,
    });
  }
  for (const gap of gaps) {
    const id = rowKey(gap.kind, gap.key);
    const known = rows.get(id);
    const place = gap.places && gap.places.length > 0 ? gap.places[0] : undefined;
    if (known) {
      known.count = gap.count ?? 0;
      known.place = place;
      known.suggestion = gap.suggestion ?? "";
      known.resource = Boolean(gap.resource);
      continue;
    }
    rows.set(id, {
      kind: gap.kind,
      key: gap.key,
      value: "",
      suggestion: gap.suggestion ?? "",
      count: gap.count ?? 0,
      place,
      file: "",
      line: 0,
      scope: "",
      resource: Boolean(gap.resource),
    });
  }
  return [...rows.values()];
}

export interface RowFilter {
  search?: string;
  gapsOnly?: boolean;
  kind?: EntryKind | "any";
}

// The panel's own filtering, over the rows already loaded. It repeats what the engine's
// --filter does (a substring of the key or of the translation) on purpose: a keystroke must
// not cost a process start, and the answer must be the same either way.
export function filterRows(rows: DictionaryRow[], filter: RowFilter = {}): DictionaryRow[] {
  const needle = (filter.search ?? "").trim().toLowerCase();
  const kind = filter.kind && filter.kind !== "any" ? filter.kind : undefined;
  return rows.filter((row) => {
    if (filter.gapsOnly && row.value !== "") {
      return false;
    }
    if (kind && row.kind !== kind) {
      return false;
    }
    if (!needle) {
      return true;
    }
    return row.key.toLowerCase().includes(needle) || row.value.toLowerCase().includes(needle);
  });
}

export type SortKey = "kind" | "key" | "value" | "count" | "place" | "file";
export type SortDirection = "asc" | "desc";

// --- resizable columns ------------------------------------------------------------------

// The five real columns of the table (kind is never sorted, but is still a column a person can
// drag wider or narrower - "литерал" and "комментарий" are not the same width).
export type ColumnKey = "kind" | "key" | "count" | "place" | "file";
export type ColumnWidths = Record<ColumnKey, number>;

// Where a column starts, and what "reset" (a double-click on its border) returns it to. Not a
// ceiling for anything: a module name is one unbroken word of whatever length the project gave
// it ("ОбновлениеКарточекЗадач" and longer are real), so no default here is a promise the
// column will ever be "enough" - only a sane place to start before the reader's own drag takes
// over.
export const DEFAULT_COLUMN_WIDTHS: ColumnWidths = {
  kind: 80,
  key: 320,
  count: 90,
  place: 260,
  file: 140,
};

// Below this a column's own content stops being usable at all - a floor a drag cannot cross,
// not a comfort target.
export const MIN_COLUMN_WIDTHS: ColumnWidths = {
  kind: 60,
  key: 200,
  count: 56,
  place: 120,
  file: 80,
};

// One border dragged by `deltaX` pixels (positive widens). The only thing that can stop it is
// the column's own floor - never a guess about what "should" be enough, because nothing bounds
// how long a real module name gets.
export function resizeColumn(widths: ColumnWidths, column: ColumnKey, deltaX: number): ColumnWidths {
  const next = widths[column] + deltaX;
  return { ...widths, [column]: Math.max(MIN_COLUMN_WIDTHS[column], next) };
}

// A double-click on a border: the one escape hatch when a drag went somewhere the reader did
// not want. Touches only the one column - the others keep whatever the reader already set.
export function resetColumnWidth(widths: ColumnWidths, column: ColumnKey): ColumnWidths {
  return { ...widths, [column]: DEFAULT_COLUMN_WIDTHS[column] };
}

const COLUMN_KEYS: ColumnKey[] = ["kind", "key", "count", "place", "file"];

// What the panel reads back out of its own persisted state on reopen. Never trusted blindly - a
// state left over from an older version of the panel, or edited by hand, must not be able to
// hand a column a width of zero, a negative number or NaN; every value is clamped to its own
// minimum, and anything missing or malformed falls back to the default outright rather than
// carrying a broken layout forward.
export function sanitizeColumnWidths(value: unknown): ColumnWidths {
  const source = (value && typeof value === "object" ? value : {}) as Partial<Record<ColumnKey, unknown>>;
  const result = {} as ColumnWidths;
  for (const column of COLUMN_KEYS) {
    const raw = source[column];
    result[column] =
      typeof raw === "number" && Number.isFinite(raw) && raw > 0
        ? Math.max(MIN_COLUMN_WIDTHS[column], raw)
        : DEFAULT_COLUMN_WIDTHS[column];
  }
  return result;
}

function placeText(row: DictionaryRow): string {
  return row.place ? `${row.place.file}:${String(row.place.line).padStart(6, "0")}` : "";
}

function compareBy(by: SortKey, a: DictionaryRow, b: DictionaryRow): number {
  switch (by) {
    case "count":
      return a.count - b.count;
    case "kind":
      return a.kind.localeCompare(b.kind);
    case "value":
      return a.value.localeCompare(b.value, "ru");
    case "place":
      return placeText(a).localeCompare(placeText(b), "ru");
    case "file":
      return a.file.localeCompare(b.file, "ru");
    default:
      return a.key.localeCompare(b.key, "ru");
  }
}

// Sorting with a tie-break by the key, so the order is total: the table is redrawn after every
// write, and rows that swap places under the cursor lose the line you were editing.
export function sortRows(rows: DictionaryRow[], by: SortKey = "count", dir: SortDirection = "desc"): DictionaryRow[] {
  const sign = dir === "desc" ? -1 : 1;
  return [...rows].sort((a, b) => {
    const primary = compareBy(by, a, b);
    if (primary !== 0) {
      return primary * sign;
    }
    return a.key.localeCompare(b.key, "ru") || a.kind.localeCompare(b.kind);
  });
}

// One page of the table. The dictionary of a real project runs to tens of thousands of records,
// and a webview handed all of them at once spends seconds building the DOM.
export function pageOf(rows: DictionaryRow[], limit: number): DictionaryRow[] {
  return limit > 0 ? rows.slice(0, limit) : rows;
}

export interface RowStats {
  total: number; // rows after the filter
  gaps: number; // untranslated among them
  shown: number; // rows the panel has actually been given
}

export function rowStats(filtered: DictionaryRow[], shown: number): RowStats {
  return {
    total: filtered.length,
    gaps: filtered.filter((row) => row.value === "").length,
    shown: Math.min(shown, filtered.length),
  };
}

export interface DictionaryEdit {
  key: string;
  value: string;
  kind: EntryKind;
}

// The file `--set` reads. An empty value is not dropped: that is how a record is removed.
export function editsPayload(edits: DictionaryEdit[]): string {
  return JSON.stringify(edits.map((e) => ({ key: e.key, value: e.value, kind: e.kind })));
}

// --- the finding of conventions/missing-translation ---------------------------------------

// What the rule attaches to its diagnostic: the exact dictionary key, its kind and the
// platform's first guess. The message cannot carry this - it is bilingual and it elides a long
// comment line - so the repair reads the data, never the text.
export interface TranslationTarget {
  kind: EntryKind;
  key: string;
  suggestion?: string;
}

// Kinds a suggestion can belong to. The platform tables spell NAMES; between the quotes of a
// literal stands as often a whole sentence, and a table answer there would be a guess dressed
// as an authority - so the engine offers none, and a suggestion arriving on a literal anyway
// is dropped here rather than shown as a one-click repair.
function suggestible(kind: EntryKind): boolean {
  return kind !== "literal";
}

export function translationTarget(data: unknown): TranslationTarget | undefined {
  if (!data || typeof data !== "object") {
    return undefined;
  }
  const carried = (data as { translation?: unknown }).translation;
  if (!carried || typeof carried !== "object") {
    return undefined;
  }
  const { kind, key, suggestion } = carried as { kind?: unknown; key?: unknown; suggestion?: unknown };
  if (!isEntryKind(kind) || typeof key !== "string" || key === "") {
    return undefined;
  }
  const target: TranslationTarget = { kind, key };
  if (typeof suggestion === "string" && suggestion !== "" && suggestible(kind)) {
    target.suggestion = suggestion;
  }
  return target;
}

function isEntryKind(value: unknown): value is EntryKind {
  return value === "token" || value === "phrase" || value === "literal";
}

// What the light bulb offers for such a finding, in the order it offers it. The suggestion is
// first and only when there is one: a one-click repair beats a dialog, and an empty guess
// would put an action that writes nothing at the top of the menu.
export type TranslationActionKind = "apply" | "ask" | "open";

export interface PlannedAction {
  action: TranslationActionKind;
  value?: string; // the suggestion an "apply" writes without asking
}

export function plannedActions(target: TranslationTarget): PlannedAction[] {
  const actions: PlannedAction[] = [];
  if (target.suggestion && suggestible(target.kind)) {
    actions.push({ action: "apply", value: target.suggestion });
  }
  actions.push({ action: "ask" }, { action: "open" });
  return actions;
}

// A key short enough for a menu title or a status line: a comment line runs to a whole
// sentence, and an untrimmed one pushes everything else out of the light bulb.
export function shortKey(key: string, max = 48): string {
  const flat = key.replace(/\s+/g, " ").trim();
  return flat.length <= max ? flat : `${flat.slice(0, max - 3)}...`;
}
