// Pure navigation logic (no vscode import) so it can be covered by unit tests on plain Node:
// the model of the project index built by the linter, line context parsing (regular expressions,
// no full-blown parser) and index lookups for go-to-definition and completion.
//
// Index schema (fixed): { meta: {root, version}, objects: [...], methods: [...],
// components: [...] }. All paths are POSIX and relative to meta.root; lines are numbered from one;
// "values" is filled only for enumerations.

export interface IndexTabular {
  name: string;
  line: number; // one-based, inside the object's yaml
}

export interface IndexLocalType {
  name: string;
  path: string; // POSIX, relative to meta.root
  line: number;
}

export interface IndexValue {
  name: string;
  line: number; // one-based, inside the enumeration's yaml
}

export interface IndexObject {
  name: string;
  kind: string; // "Справочник" | "Перечисление" | "РегистрСведений" | ...
  path: string; // the object's yaml
  line: number;
  tabular: IndexTabular[];
  local_types: IndexLocalType[];
  family: string[]; // "Ссылка", "Объект", ...
  values: IndexValue[]; // enumerations only
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

export interface IndexReference {
  name: string; // name of the used symbol
  qualifier: string; // identifier before the dot ("" - chain root or a bare call)
  module: string; // module where the usage occurs (file stem)
  path: string; // POSIX, relative to meta.root
  line: number; // one-based
  col: number; // zero-based (for the range in the editor)
}

export interface ProjectIndex {
  meta: { root: string; version?: string };
  objects: IndexObject[];
  methods: IndexMethod[];
  components: IndexComponent[];
  references: IndexReference[];
}

// The exact spelling of the linter-side CLI indexing command may still change.
// It is defined ONLY here, as an ordered list of candidates: the loader tries them in turn,
// and if none produced a valid index, navigation just stays silent.
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

// Strict about the envelope (so that a linter report or an error page is rejected and the caller
// moves on to the next command variant) and lenient about individual entries.
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
  // references are optional: an old linter does not emit them - then "find usages" stays silent.
  const references: IndexReference[] = list((data as { references?: unknown }).references)
    .filter(named)
    .map((r) => {
      const raw = r as Record<string, unknown>;
      return {
        name: String(raw.name),
        qualifier: String(raw.qualifier ?? ""),
        module: String(raw.module ?? ""),
        path: String(raw.path ?? ""),
        line: num(raw.line),
        col: Math.max(0, Math.trunc(Number(raw.col)) || 0),
      };
    });
  return {
    meta: { root: data.meta.root, version: data.meta.version === undefined ? undefined : String(data.meta.version) },
    objects,
    methods,
    components,
    references,
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

// Precomputed lookup structures over the parsed index.
export class IndexLookup {
  readonly index: ProjectIndex;
  private readonly objectMap = new Map<string, IndexObject>();
  private readonly moduleMethods = new Map<string, IndexMethod[]>();
  private readonly fileMethods = new Map<string, IndexMethod[]>();
  private readonly formComponents = new Map<string, IndexComponent[]>();
  private readonly refsByName = new Map<string, IndexReference[]>();

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
    for (const r of index.references) {
      push(this.refsByName, r.name, r);
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

  // A method by its module file path (POSIX relative to meta.root) - a reliable way to say
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

  referencesByName(name: string): IndexReference[] {
    return this.refsByName.get(name) ?? [];
  }
}

// ---------------------------------------------------------------------------
// Line context parsing
// ---------------------------------------------------------------------------

const IDENT = "[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*";
// A character that cannot immediately precede a recognized identifier chain
// (otherwise we are looking at the middle of something bigger).
const NOT_BEFORE = "[^.0-9A-Za-zА-Яа-яЁё_]";

export interface ChainHit {
  parts: string[]; // dot-separated identifier chain covering the position
  at: number; // index of the segment under the cursor
}

// Finds the dot-separated identifier chain covering `character` (zero-based) and the segment
// the cursor is on. Returns null if the position is not on an identifier.
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
  line: number; // one-based
}

export interface DefinitionQuery {
  languageId: string; // "xbsl" | "yaml"
  lineText: string;
  character: number; // cursor column, zero-based
  fileStem: string; // file name without the extension ("ФормаСписка")
  filePath?: string; // path of the current file (POSIX relative to meta.root), when known
}

interface HandlerValue {
  name: string;
  start: number;
  end: number;
}

// A handler line in yaml: `Обработчик: ИмяМетода`.
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

// Kind of a resolved symbol. Usages (resolveReferences) are supported for method/object/component.
export type SymbolKind = "object" | "method" | "component" | "tabular" | "localType" | "enumValue";

export interface SymbolDescriptor {
  kind: SymbolKind;
  name: string;
  module: string; // for a method - its module, otherwise ""
  form: string; // for a component - its form, otherwise ""
  path: string; // definition site (POSIX relative to meta.root)
  line: number; // one-based
}

// Resolves the symbol under the position into a descriptor (what it is and where it is defined),
// or null when the context is not recognized - better to stay silent than jump to the wrong place.
// The shared foundation of go-to-definition and find-usages.
export function resolveSymbol(lookup: IndexLookup, q: DefinitionQuery): SymbolDescriptor | null {
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
      return method
        ? { kind: "method", name: handler.name, module: method.module, form: "", path: method.path, line: method.line }
        : null;
    }
  }

  const hit = chainAt(q.lineText, q.character);
  if (!hit) {
    return null;
  }
  const word = hit.parts[hit.at];

  if (hit.at === 0) {
    // A single word or a chain root naming a project object -> its yaml.
    const obj = lookup.objectByName(word);
    if (obj) {
      return { kind: "object", name: word, module: "", form: "", path: obj.path, line: obj.line };
    }
    // A bare method name inside its own module.
    if (hit.parts.length === 1 && q.languageId === "xbsl") {
      const method =
        (q.filePath ? lookup.methodInFile(q.filePath, word) : undefined) ?? lookup.method(q.fileStem, word);
      if (method) {
        return { kind: "method", name: word, module: method.module, form: "", path: method.path, line: method.line };
      }
    }
    return null;
  }

  // Компоненты.X -> the component node in the current form's yaml.
  if (hit.at === 1 && hit.parts[0] === "Компоненты") {
    const component = lookup.component(q.fileStem, word);
    return component
      ? { kind: "component", name: word, module: "", form: q.fileStem, path: component.path, line: component.line }
      : null;
  }
  // Компоненты.X.Метод -> a method of module X.
  if (hit.at === 2 && hit.parts[0] === "Компоненты") {
    const method = lookup.method(hit.parts[1], word);
    return method
      ? { kind: "method", name: word, module: method.module, form: "", path: method.path, line: method.line }
      : null;
  }
  if (hit.at !== 1) {
    return null; // deeper chains require type inference - beyond the scope of this parsing
  }

  const qualifier = hit.parts[hit.at - 1];
  const obj = lookup.objectByName(qualifier);
  if (obj) {
    const localType = obj.local_types.find((t) => t.name === word);
    if (localType) {
      return { kind: "localType", name: word, module: "", form: "", path: localType.path, line: localType.line };
    }
    const tabular = obj.tabular.find((t) => t.name === word);
    if (tabular) {
      return { kind: "tabular", name: word, module: "", form: "", path: obj.path, line: tabular.line };
    }
    const value = obj.values.find((v) => v.name === word);
    if (value) {
      return { kind: "enumValue", name: word, module: "", form: "", path: obj.path, line: value.line };
    }
  }
  // Модуль.Метод (covers manager modules whose name matches an object name).
  const method = lookup.method(qualifier, word);
  return method
    ? { kind: "method", name: word, module: method.module, form: "", path: method.path, line: method.line }
    : null;
}

// Determines the navigation target for the given position, or returns null when the context is not recognized.
export function resolveDefinition(lookup: IndexLookup, q: DefinitionQuery): Target | null {
  const d = resolveSymbol(lookup, q);
  return d ? { path: d.path, line: d.line } : null;
}

export interface RefLocation {
  path: string; // POSIX, relative to meta.root
  line: number; // one-based
  col: number; // zero-based
  length: number; // length of the highlighted name (0 - for the declaration line)
}

export interface ReferencesQuery extends DefinitionQuery {
  includeDeclaration?: boolean;
}

// All usages of the symbol under the position. Supported: methods (calls within their own module,
// `Модуль.Метод`, `Компоненты.Модуль.Метод`, yaml handlers), objects (chain root) and components
// (`Компоненты.Имя`). The declaration site is excluded; with includeDeclaration it is added separately.
export function resolveReferences(lookup: IndexLookup, q: ReferencesQuery): RefLocation[] {
  const d = resolveSymbol(lookup, q);
  if (!d) {
    return [];
  }
  const length = d.name.length;
  const hits: RefLocation[] = [];
  const add = (r: IndexReference): void => {
    hits.push({ path: r.path, line: r.line, col: r.col, length });
  };
  const refs = lookup.referencesByName(d.name);
  if (d.kind === "method") {
    for (const r of refs) {
      if (r.qualifier === d.module || (r.qualifier === "" && r.module === d.module)) {
        add(r);
      }
    }
  } else if (d.kind === "object") {
    for (const r of refs) {
      if (r.qualifier === "") {
        add(r);
      }
    }
  } else if (d.kind === "component") {
    for (const r of refs) {
      if (r.qualifier === "Компоненты" && r.module === d.form) {
        add(r);
      }
    }
  } else {
    return [];
  }

  // Exclude the declaration site from the usages; when requested, add it back as a separate entry.
  let out = hits.filter((h) => !(h.path === d.path && h.line === d.line));
  if (q.includeDeclaration) {
    out.push({ path: d.path, line: d.line, col: 0, length: 0 });
  }
  // Deduplicate and order by (path, line, col).
  const seen = new Set<string>();
  const uniq: RefLocation[] = [];
  for (const h of out.sort((a, b) => a.path.localeCompare(b.path) || a.line - b.line || a.col - b.col)) {
    const key = `${h.path}:${h.line}:${h.col}`;
    if (!seen.has(key)) {
      seen.add(key);
      uniq.push(h);
    }
  }
  return uniq;
}

// ---------------------------------------------------------------------------
// Completion
// ---------------------------------------------------------------------------

export type CompletionKind =
  | "object"
  | "enum"
  | "family"
  | "field"
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
  linePrefix: string; // line text up to the cursor
  fileStem: string;
  textBefore?: string; // document text up to the cursor - to recognize a query context
  attributesOf?: (objectName: string) => string[] | undefined; // object attributes from yaml (injected)
}

// Standard (selectable in a query) fields by object kind; attributes and tabular sections are added
// separately (attributes are known to the caller - via attributesOf, they are not in the index).
const STANDARD_QUERY_FIELDS: Record<string, string[]> = {
  Справочник: ["Ссылка", "Код", "Наименование", "ПометкаУдаления", "Предопределённый"],
  Документ: ["Ссылка", "Номер", "Дата", "Проведён", "ПометкаУдаления"],
};

// Is the cursor inside a query block? Take the last query keyword before the cursor and count the
// brace balance after it. The keyword is bilingual (Запрос / Query); this is a heuristic for the
// plain mode (no lexer) - in the LSP mode the query context is determined by the linter's lexer
// (canonical QUERY).
export function isInQuery(textBefore: string): boolean {
  const re = /(?:Запрос|Query)\s*\{/g;
  let open = -1;
  let m: RegExpExecArray | null;
  while ((m = re.exec(textBefore))) {
    open = m.index + m[0].length;
  }
  if (open < 0) {
    return false;
  }
  let depth = 1;
  for (let i = open; i < textBefore.length; i++) {
    if (textBefore[i] === "{") {
      depth++;
    } else if (textBefore[i] === "}") {
      depth--;
      if (depth === 0) {
        return false;
      }
    }
  }
  return true;
}

// Table fields for completion inside a query: standard fields of the kind + attributes + tabular
// sections. Name duplicates are removed (an attribute may duplicate a standard name, e.g. Наименование).
export function queryFieldEntries(kind: string, attributes: string[], tabular: string[]): CompletionEntry[] {
  const seen = new Set<string>();
  const entries: CompletionEntry[] = [];
  const add = (label: string, detail: string): void => {
    if (label && !seen.has(label)) {
      seen.add(label);
      entries.push({ label, kind: "field", detail });
    }
  };
  for (const f of STANDARD_QUERY_FIELDS[kind] ?? []) {
    add(f, "стандартное поле");
  }
  for (const a of attributes) {
    add(a, "реквизит");
  }
  for (const t of tabular) {
    add(t, "табличная часть");
  }
  return entries;
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

// Returns completion entries for a recognized context, or null when the position is not understood
// (then the built-in word-based suggestions take over).
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
  // <Объект>.<...> / <Модуль>.<...> -> the type family + tabular sections + local types
  // (+ module methods); for an enumeration - its values.
  m = matchEnd(prefix, `(${IDENT})\\.(?:${IDENT})?`);
  if (m) {
    // Inside a Запрос{...} block after <Таблица>. - table fields (standard + attributes + tabular
    // sections), not object/manager members. Attributes are supplied by the caller (attributesOf),
    // they are not in the index.
    if (q.textBefore && isInQuery(q.textBefore)) {
      const table = lookup.objectByName(m[1]);
      if (!table) {
        return null; // unknown table - stay silent (do not show object members)
      }
      return queryFieldEntries(table.kind, q.attributesOf?.(m[1]) ?? [], table.tabular.map((t) => t.name));
    }
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
