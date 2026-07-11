// Pure navigation logic (no vscode import) so it can be unit-tested under plain Node:
// the model of the project index produced by the linter, line-context parsing (regex,
// no full parser) and index lookups for go-to-definition and completion.
//
// Index schema (frozen): { meta: {root, version}, objects: [...], methods: [...],
// components: [...] }. All paths are POSIX and relative to meta.root; lines are 1-based;
// "values" is populated for enums only.

export interface IndexTabular {
  name: string;
  line: number; // 1-based, inside the object's yaml
}

export interface IndexLocalType {
  name: string;
  path: string; // POSIX, relative to meta.root
  line: number;
}

export interface IndexValue {
  name: string;
  line: number; // 1-based, inside the enum's yaml
}

export interface IndexObject {
  name: string;
  kind: string; // "Справочник" | "Перечисление" | "РегистрСведений" | ...
  path: string; // the object's yaml
  line: number;
  tabular: IndexTabular[];
  local_types: IndexLocalType[];
  family: string[]; // "Ссылка", "Объект", ...
  values: IndexValue[]; // enums only
}

export interface IndexMethod {
  module: string;
  name: string;
  path: string;
  line: number;
  annotations: string[];
}

export interface IndexComponent {
  form: string;
  name: string;
  type: string;
  path: string; // the form's yaml
  line: number;
}

export interface ProjectIndex {
  meta: { root: string; version?: string };
  objects: IndexObject[];
  methods: IndexMethod[];
  components: IndexComponent[];
}

// The exact CLI spelling of the index command may still change on the linter side.
// It is defined ONLY here, as an ordered list of candidates: the loader tries each one
// in turn and, when none of them yields a valid index, navigation just stays silent.
export const INDEX_COMMAND_VARIANTS: ReadonlyArray<(root: string) => string[]> = [
  (root) => ["index", root],
  (root) => ["--index", root],
];

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function num(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
}

function named(entry: unknown): entry is { name: string } {
  const e = entry as { name?: unknown };
  return !!e && typeof e.name === "string" && e.name.length > 0;
}

// Strict on the envelope (so a lint report or an error page is rejected and the caller
// falls back to the next command variant), lenient on individual entries.
export function parseIndex(text: string): ProjectIndex {
  const data = JSON.parse(text) as {
    meta?: { root?: unknown; version?: unknown };
    objects?: unknown;
    methods?: unknown;
    components?: unknown;
  };
  if (!data || typeof data !== "object" || !data.meta || typeof data.meta.root !== "string" || !Array.isArray(data.objects)) {
    throw new Error("нет meta.root или objects – это не индекс проекта");
  }
  const objects: IndexObject[] = (data.objects as unknown[]).filter(named).map((o) => {
    const raw = o as Record<string, unknown>;
    return {
      name: String(raw.name),
      kind: String(raw.kind ?? ""),
      path: String(raw.path ?? ""),
      line: num(raw.line),
      tabular: list(raw.tabular)
        .filter(named)
        .map((t) => ({ name: (t as { name: string }).name, line: num((t as Record<string, unknown>).line) })),
      local_types: list(raw.local_types)
        .filter(named)
        .map((t) => {
          const lt = t as Record<string, unknown>;
          return { name: String(lt.name), path: String(lt.path ?? ""), line: num(lt.line) };
        }),
      family: list(raw.family).map((f) => String(f)),
      values: list(raw.values)
        .filter(named)
        .map((v) => ({ name: (v as { name: string }).name, line: num((v as Record<string, unknown>).line) })),
    };
  });
  const methods: IndexMethod[] = list(data.methods)
    .filter(named)
    .map((m) => {
      const raw = m as Record<string, unknown>;
      return {
        module: String(raw.module ?? ""),
        name: String(raw.name),
        path: String(raw.path ?? ""),
        line: num(raw.line),
        annotations: list(raw.annotations).map((a) => String(a)),
      };
    });
  const components: IndexComponent[] = list(data.components)
    .filter(named)
    .map((c) => {
      const raw = c as Record<string, unknown>;
      return {
        form: String(raw.form ?? ""),
        name: String(raw.name),
        type: String(raw.type ?? ""),
        path: String(raw.path ?? ""),
        line: num(raw.line),
      };
    });
  return {
    meta: { root: data.meta.root, version: data.meta.version === undefined ? undefined : String(data.meta.version) },
    objects,
    methods,
    components,
  };
}

function push<T>(map: Map<string, T[]>, key: string, value: T): void {
  const bucket = map.get(key);
  if (bucket) {
    bucket.push(value);
  } else {
    map.set(key, [value]);
  }
}

// Precomputed lookups over a parsed index.
export class IndexLookup {
  readonly index: ProjectIndex;
  private readonly objectMap = new Map<string, IndexObject>();
  private readonly moduleMethods = new Map<string, IndexMethod[]>();
  private readonly fileMethods = new Map<string, IndexMethod[]>();
  private readonly formComponents = new Map<string, IndexComponent[]>();

  constructor(index: ProjectIndex) {
    this.index = index;
    for (const o of index.objects) {
      if (!this.objectMap.has(o.name)) {
        this.objectMap.set(o.name, o);
      }
    }
    for (const m of index.methods) {
      push(this.moduleMethods, m.module, m);
      push(this.fileMethods, m.path, m);
    }
    for (const c of index.components) {
      push(this.formComponents, c.form, c);
    }
  }

  objects(): IndexObject[] {
    return this.index.objects;
  }

  objectByName(name: string): IndexObject | undefined {
    return this.objectMap.get(name);
  }

  methodsByModule(module: string): IndexMethod[] {
    return this.moduleMethods.get(module) ?? [];
  }

  method(module: string, name: string): IndexMethod | undefined {
    return this.methodsByModule(module).find((m) => m.name === name);
  }

  // Method by the module file path (POSIX relative to meta.root) – a robust way to say
  // "in the current file" that does not depend on how the module name is derived.
  methodInFile(path: string, name: string): IndexMethod | undefined {
    return (this.fileMethods.get(path) ?? []).find((m) => m.name === name);
  }

  componentsByForm(form: string): IndexComponent[] {
    return this.formComponents.get(form) ?? [];
  }

  component(form: string, name: string): IndexComponent | undefined {
    return this.componentsByForm(form).find((c) => c.name === name);
  }
}

// ---------------------------------------------------------------------------
// Line-context parsing
// ---------------------------------------------------------------------------

const IDENT = "[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*";
// A character that may not directly precede an identifier chain we recognize
// (would mean we are looking at the middle of something bigger).
const NOT_BEFORE = "[^.0-9A-Za-zА-Яа-яЁё_]";

export interface ChainHit {
  parts: string[]; // dotted identifier chain covering the position
  at: number; // index of the segment under the cursor
}

// Finds the dotted identifier chain covering `character` (0-based) and the segment
// the cursor is on. Returns null when the position is not on an identifier.
export function chainAt(lineText: string, character: number): ChainHit | null {
  const re = new RegExp(`${IDENT}(?:\\.${IDENT})*`, "g");
  for (let m = re.exec(lineText); m; m = re.exec(lineText)) {
    const start = m.index;
    const end = start + m[0].length;
    if (character < start) {
      break;
    }
    if (character > end) {
      continue;
    }
    const parts = m[0].split(".");
    let offset = start;
    for (let i = 0; i < parts.length; i++) {
      const segmentEnd = offset + parts[i].length;
      if (character <= segmentEnd) {
        return { parts, at: i };
      }
      offset = segmentEnd + 1; // skip the dot
    }
    return { parts, at: parts.length - 1 };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Go to definition
// ---------------------------------------------------------------------------

export interface Target {
  path: string; // POSIX, relative to meta.root
  line: number; // 1-based
}

export interface DefinitionQuery {
  languageId: string; // "xbsl" | "yaml"
  lineText: string;
  character: number; // 0-based cursor column
  fileStem: string; // file name without the extension ("ГлавнаяСтраница")
  filePath?: string; // POSIX path of the current file relative to meta.root, when known
}

interface HandlerValue {
  name: string;
  start: number;
  end: number;
}

// yaml handler line: `Обработчик: ИмяМетода`.
function matchHandlerLine(lineText: string): HandlerValue | null {
  const m = new RegExp(`^(\\s*Обработчик\\s*:\\s*)(${IDENT})\\s*$`).exec(lineText);
  if (!m) {
    return null;
  }
  return { name: m[2], start: m[1].length, end: m[1].length + m[2].length };
}

function pairedModulePath(filePath: string | undefined): string | undefined {
  if (!filePath || !/\.yaml$/i.test(filePath)) {
    return undefined;
  }
  return filePath.replace(/\.yaml$/i, ".xbsl");
}

// Resolves the definition target for the given position, or null when the context is
// not recognized – silence is better than jumping to the wrong place.
export function resolveDefinition(lookup: IndexLookup, q: DefinitionQuery): Target | null {
  // yaml: the value of `Обработчик:` is a method of the paired .xbsl module.
  if (q.languageId === "yaml") {
    const handler = matchHandlerLine(q.lineText);
    if (handler) {
      if (q.character < handler.start || q.character > handler.end) {
        return null;
      }
      const paired = pairedModulePath(q.filePath);
      const method =
        (paired ? lookup.methodInFile(paired, handler.name) : undefined) ?? lookup.method(q.fileStem, handler.name);
      return method ? { path: method.path, line: method.line } : null;
    }
  }

  const hit = chainAt(q.lineText, q.character);
  if (!hit) {
    return null;
  }
  const word = hit.parts[hit.at];

  if (hit.at === 0) {
    // A bare word or the root of a chain that names a project object -> its yaml.
    const obj = lookup.objectByName(word);
    if (obj) {
      return { path: obj.path, line: obj.line };
    }
    // A bare method name inside its own module.
    if (hit.parts.length === 1 && q.languageId === "xbsl") {
      const method =
        (q.filePath ? lookup.methodInFile(q.filePath, word) : undefined) ?? lookup.method(q.fileStem, word);
      if (method) {
        return { path: method.path, line: method.line };
      }
    }
    return null;
  }

  // Компоненты.X -> the component node in the current form's yaml.
  if (hit.at === 1 && hit.parts[0] === "Компоненты") {
    const component = lookup.component(q.fileStem, word);
    return component ? { path: component.path, line: component.line } : null;
  }
  // Компоненты.X.Метод -> a method of module X.
  if (hit.at === 2 && hit.parts[0] === "Компоненты") {
    const method = lookup.method(hit.parts[1], word);
    return method ? { path: method.path, line: method.line } : null;
  }
  if (hit.at !== 1) {
    return null; // deeper chains need type inference – out of scope
  }

  const qualifier = hit.parts[hit.at - 1];
  const obj = lookup.objectByName(qualifier);
  if (obj) {
    const localType = obj.local_types.find((t) => t.name === word);
    if (localType) {
      return { path: localType.path, line: localType.line };
    }
    const tabular = obj.tabular.find((t) => t.name === word);
    if (tabular) {
      return { path: obj.path, line: tabular.line };
    }
    const value = obj.values.find((v) => v.name === word);
    if (value) {
      return { path: obj.path, line: value.line };
    }
  }
  // Модуль.Метод (covers manager modules whose name coincides with the object name).
  const method = lookup.method(qualifier, word);
  return method ? { path: method.path, line: method.line } : null;
}

// ---------------------------------------------------------------------------
// Completion
// ---------------------------------------------------------------------------

export type CompletionKind =
  | "object"
  | "enum"
  | "family"
  | "tabular"
  | "localType"
  | "enumMember"
  | "method"
  | "component";

export interface CompletionEntry {
  label: string;
  kind: CompletionKind;
  detail?: string;
}

export interface CompletionQuery {
  languageId: string; // "xbsl" | "yaml"
  linePrefix: string; // line text before the cursor
  fileStem: string;
}

function matchEnd(prefix: string, pattern: string): RegExpExecArray | null {
  return new RegExp(`(?:^|${NOT_BEFORE})${pattern}$`).exec(prefix);
}

function methodEntry(m: IndexMethod): CompletionEntry {
  return {
    label: m.name,
    kind: "method",
    detail: m.annotations.length > 0 ? m.annotations.join(", ") : "метод",
  };
}

function objectMemberEntries(lookup: IndexLookup, name: string): CompletionEntry[] | null {
  const obj = lookup.objectByName(name);
  const methods = lookup.methodsByModule(name);
  if (!obj && methods.length === 0) {
    return null;
  }
  const entries: CompletionEntry[] = [];
  if (obj) {
    if (obj.kind === "Перечисление") {
      for (const v of obj.values) {
        entries.push({ label: v.name, kind: "enumMember", detail: "значение перечисления" });
      }
    } else {
      for (const f of obj.family) {
        entries.push({ label: f, kind: "family", detail: "тип" });
      }
      for (const t of obj.tabular) {
        entries.push({ label: t.name, kind: "tabular", detail: "табличная часть" });
      }
      for (const t of obj.local_types) {
        entries.push({ label: t.name, kind: "localType", detail: "локальный тип" });
      }
    }
  }
  for (const m of methods) {
    entries.push(methodEntry(m));
  }
  return entries;
}

// Returns completion entries for the recognized context, or null when the position is
// not one we understand (then the built-in word-based suggestions take over).
export function resolveCompletions(lookup: IndexLookup, q: CompletionQuery): CompletionEntry[] | null {
  const prefix = q.linePrefix;

  // Компоненты.X.<...> -> methods of module X.
  let m = matchEnd(prefix, `Компоненты\\.(${IDENT})\\.(?:${IDENT})?`);
  if (m) {
    return lookup.methodsByModule(m[1]).map(methodEntry);
  }
  // Компоненты.<...> -> components of the current form.
  m = matchEnd(prefix, `Компоненты\\.(?:${IDENT})?`);
  if (m) {
    return lookup.componentsByForm(q.fileStem).map((c) => ({
      label: c.name,
      kind: "component" as const,
      detail: c.type,
    }));
  }
  // <Объект>.<...> / <Модуль>.<...> -> family + tabular + local types (+ module methods);
  // for an enum – its values.
  m = matchEnd(prefix, `(${IDENT})\\.(?:${IDENT})?`);
  if (m) {
    return objectMemberEntries(lookup, m[1]);
  }
  // yaml: `Тип: <...>` -> project object names.
  if (q.languageId === "yaml" && new RegExp(`(?:^|\\s)Тип\\s*:\\s*(?:${IDENT})?$`).test(prefix)) {
    return lookup.objects().map((o) => ({
      label: o.name,
      kind: o.kind === "Перечисление" ? ("enum" as const) : ("object" as const),
      detail: o.kind,
    }));
  }
  return null;
}
