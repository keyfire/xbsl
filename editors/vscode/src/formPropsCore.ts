// Pure model of the "Properties" panel v2 for form components (docs/DESIGNER.md, stage 3):
// merges the node payload of xbsl/formNodeAt with the component schema of xbsl/uiSchema into
// renderable sections, picks a typed editor per property, validates a value BEFORE the write
// and assembles composite value_yaml fragments. The module never edits yaml itself - every
// write it prepares becomes one xbsl/formEdit request (set-property/reset-property) whose
// text edits the extension applies via WorkspaceEdit; parsing existing values for display is
// the only yaml the client touches. No vscode imports - covered by plain node tests
// (test/formPropsCore.test.ts); the webview wiring lives in formProps.ts.

import { isMap, isScalar, parseDocument } from "yaml";

// -- wire shapes (camelCase, as the LSP serializes them) --------------------------------------

export interface SpanDto {
  start: number;
  end: number;
}

export interface NodePropertyDto {
  key: string;
  kind: "scalar" | "binding" | "composite" | "handler";
  valuePreview: string;
  span: SpanDto; // whole lines: key line .. end of the value block
  valueSpan: SpanDto | null; // exact scalar span; null for composites
}

export interface FormNodeDto {
  id: string;
  kind: "component" | "slot";
  span: SpanDto;
  contentSpan?: SpanDto; // span without the attached leading comments (newer engines)
  type?: string | null;
  typeFull?: string | null;
  name?: string | null;
  slot?: string | null;
  properties?: NodePropertyDto[];
}

// The xbsl/formNodeAt response: the node under the offset plus the nearest parent
// COMPONENT (slots skipped; null for the root). Older engines send the node alone.
export interface FormNodeAtPayload {
  node?: FormNodeDto | null;
  parent?: FormNodeDto | null;
  error?: string;
}

export interface UiPropDto {
  types?: string[];
  enum?: string[];
  event?: string;
  doc?: string;
  default?: string;
  nullable?: boolean;
  slot?: boolean;
  readonly?: boolean;
  since?: string;
}

export interface UiComponentDto {
  name: string;
  package?: string;
  abstract?: boolean;
  since?: string;
  doc?: string;
  props?: Record<string, UiPropDto>;
  // Value lists of the enumerations referenced by the property unions - the response-level
  // "enums" of xbsl/uiSchema, folded into the cached record by the extension. Absent on
  // older engines; the union editor then falls back to a plain text input.
  enums?: Record<string, string[]>;
}

// One top-level method of the paired module (the xbsl/moduleHandlers response entries).
export interface ModuleMethodDto {
  name: string;
  static?: boolean;
  abstract?: boolean;
  annotations?: string[];
  visibility?: string | null;
  params?: { name?: string | null; type?: string | null }[];
  returnType?: string | null;
  span?: SpanDto | null;
  nameSpan?: SpanDto | null; // the method name token - the jump target
}

// The xbsl/moduleHandlers response: available=false (module null, methods []) when the
// paired .xbsl file does not exist; error - the request-level failure.
export interface ModuleHandlersPayload {
  available?: boolean;
  module?: string | null;
  methods?: ModuleMethodDto[];
  parseErrors?: number;
  error?: string;
}

// The xbsl/addHandler response (the two-file plan; see xbsl/formhandlers.py). Offsets are
// relative to the buffers the plan was computed from. created=true - the module FILE does
// not exist: moduleText carries its FULL content and moduleEdits is empty.
export interface AddHandlerResponse {
  method?: string;
  created?: boolean;
  methodAdded?: boolean;
  yamlEdits?: EngineEditDto[];
  moduleUri?: string;
  moduleEdits?: EngineEditDto[];
  moduleText?: string;
  cursor?: { uri?: string; offset?: number } | null;
  notes?: string[];
  error?: string;
}

// The answer of xbsl/removeHandler - the mirror of AddHandlerResponse: the yaml always loses
// the binding, the module loses the method only when the caller asked (methodRemoved says what
// actually happened, notes say why it did not).
export interface RemoveHandlerResponse {
  method?: string | null;
  methodRemoved?: boolean;
  yamlEdits?: EngineEditDto[];
  moduleUri?: string;
  moduleEdits?: EngineEditDto[];
  notes?: string[];
  error?: string;
}

export interface EngineEditDto {
  start: number;
  end: number;
  newText: string;
}

// The node the properties panel should show for a formNodeAt payload: a component shows
// itself; a slot shows its owner component (viaSlot carries the slot name for the honest
// panel header). undefined - nothing to show: no node at the offset, or a slot without
// parent info (an older engine), which keeps the "select a component" hint.
export function panelTarget(
  payload: FormNodeAtPayload
): { node: FormNodeDto; viaSlot?: string } | undefined {
  const node = payload.node;
  if (!node) {
    return undefined;
  }
  if (node.kind === "component") {
    return { node };
  }
  const parent = payload.parent;
  if (parent && parent.kind === "component") {
    return { node: parent, viaSlot: node.name ?? node.id };
  }
  return undefined;
}

// -- panel model ------------------------------------------------------------------------------

export interface CompositeField {
  key: string;
  value: string;
  scalar: boolean; // false - a nested block; such composites are not editable field-by-field
}

export type RowEditor =
  | { control: "tristate" }
  | { control: "enum"; options: string[] }
  | { control: "number" }
  | { control: "text"; multiline: boolean }
  | { control: "color" }
  // enums: value lists for the members that are enumerations (only such members carry a
  // key) - the paired editor shows a dropdown for them instead of a text input.
  | { control: "union"; types: string[]; current?: string; enums?: Record<string, string[]> }
  | { control: "composite"; fields: CompositeField[]; editable: boolean }
  | { control: "binding" }
  // choices - the handler dropdown content computed from the paired module's methods
  // (absent inside chooseEditor; buildPanelModel enriches the row when it has the
  // xbsl/moduleHandlers payload).
  | { control: "handler"; choices?: HandlerChoices }
  // An open combobox (typing allowed, the list only suggests) - the Тип rows of the
  // metadata mode; the candidates come from the metadata tree provider (propsModes.ts).
  | { control: "combo"; options: string[] }
  | { control: "readonly" };

export interface PanelRow {
  key: string;
  set: boolean; // the key is present in yaml
  value: string; // exact scalar value; for composites - the preview (the Тип name)
  editor: RowEditor;
  doc?: string; // schema doc snippet - the row tooltip (hook 4)
  defaultValue?: string; // schema default - grey placeholder on unset rows
  since?: string;
  event?: string; // handler signature from the schema
  colorHex?: string; // #rrggbb when the current composite is an АбсолютныйЦвет
  propSpan?: SpanDto; // span of the set property - the "open in yaml" target
  slot?: boolean; // the schema marks this key a slot - it holds child components (structure view)
  hay: string; // lowercased "name + value" haystack for the panel filter
}

export type SectionId = "set" | "events" | "all" | "readonly";

export interface PanelSection {
  id: SectionId;
  rows: PanelRow[];
}

export interface PanelModel {
  nodeId: string;
  type: string;
  name: string;
  nodeSpanStart: number;
  schemaAvailable: boolean;
  sections: PanelSection[];
  // #rrggbb of every АбсолютныйЦвет present anywhere in the form yaml - the color editor
  // offers them as one-click swatches (hook 7). Absent in metadata mode.
  formColors?: string[];
  // Binding autocomplete for the binding editor (hook 6): the expressions already used in the
  // form yaml, plus =Объект.<attribute> of the owner object (merged in by the extension after an
  // xbsl/objectInfo call). Absent in metadata mode.
  formBindings?: string[];
  // The project's enumerations, name -> values - the binding editor completes =Имя.Значение after
  // a dot (hook 6). Attached by the extension; absent in metadata mode.
  projectEnums?: Record<string, string[]>;
  // true - the metadata mode of the unified panel (propsModes.buildMetaPanelModel): the
  // webview renders the rows flat, without the section chrome and the component legend.
  meta?: boolean;
  // true - the form is read-only (a library .xlib form, a git/diff view, a read-only file). The
  // webview disables its editors and shows a banner; writes are refused (hook 11).
  readonly?: boolean;
}

// Whether a document uri names a read-only form source: anything other than a real on-disk file
// (or an unsaved buffer) - git:/diff/output and any virtual scheme a library viewer might use. The
// caller adds the file-permission check for the "file" scheme (hook 11). Pure, so it is tested.
export function isReadonlyScheme(scheme: string): boolean {
  return scheme !== "file" && scheme !== "untitled" && scheme !== "vscode-userdata";
}

// -- event handlers (hook 1) --------------------------------------------------------------
//
// The dropdown of an event row offers the methods of the paired module: the ones whose
// parameter count fits the event signature come first (XBSL binds handlers by name and
// allows a method to take FEWER parameters than the event passes), the rest stay
// reachable below. The signature grammar is the engine's normalized form; the parser here
// mirrors xbsl/formhandlers.parse_event_signature so both sides agree on the argument
// count.

function depthStep(prev: string, ch: string, depth: number): number {
  if (ch === "<" || ch === "(") {
    return depth + 1;
  }
  if (ch === ")" || (ch === ">" && prev !== "-")) {
    return depth - 1;
  }
  return depth;
}

function splitTop(s: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let prev = "";
  let current = "";
  for (const ch of s) {
    depth = depthStep(prev, ch, depth);
    if (ch === "," && depth === 0) {
      parts.push(current.trim());
      current = "";
    } else {
      current += ch;
    }
    prev = ch;
  }
  const tail = current.trim();
  if (tail) {
    parts.push(tail);
  }
  return parts;
}

// Whether the leading "(" closes only at the very end (the whole string is wrapped).
function isWrapped(s: string): boolean {
  let depth = 0;
  let prev = "";
  for (let i = 0; i < s.length; i++) {
    const ch = s.charAt(i);
    const next = depthStep(prev, ch, depth);
    if (next < depth && next === 0) {
      return i === s.length - 1;
    }
    depth = next;
    prev = ch;
  }
  return false;
}

export interface EventSignature {
  args: string[];
  ret: string | null;
}

// (argument types, return type) of a ui-schema event signature: "(Кнопка,
// СобытиеПриНажатии)->ничто" or the nullable wrapping "((ОписаниеЗадания)->Булево)?".
// undefined for an unparseable string - the caller then cannot judge compatibility.
export function parseEventSignature(signature: string | null | undefined): EventSignature | undefined {
  let s = (signature ?? "").trim();
  if (s.endsWith("?")) {
    s = s.slice(0, -1).trim();
  }
  if (s.startsWith("(") && s.endsWith(")") && isWrapped(s)) {
    const inner = s.slice(1, -1).trim();
    if (inner.includes("->")) {
      s = inner;
    }
  }
  if (!s.startsWith("(")) {
    return undefined;
  }
  let depth = 0;
  let prev = "";
  let argsEnd = -1;
  for (let i = 0; i < s.length; i++) {
    const ch = s.charAt(i);
    const next = depthStep(prev, ch, depth);
    if (next < depth && next === 0) {
      argsEnd = i;
      break;
    }
    depth = next;
    prev = ch;
  }
  if (argsEnd < 0 || s.slice(argsEnd + 1, argsEnd + 3) !== "->") {
    return undefined;
  }
  return { args: splitTop(s.slice(1, argsEnd)), ret: s.slice(argsEnd + 3).trim() || null };
}

export interface HandlerChoices {
  // Methods whose parameter count <= the event's argument count, module order.
  compatible: string[];
  // The remaining callable methods (module order); ALL methods when the signature is
  // unknown and compatibility cannot be judged.
  rest: string[];
  // The bound method is nowhere in the module (a broken binding or the module file is
  // missing); false when the module state is unknown (older engine, failed request).
  currentMissing: boolean;
}

// The dropdown content of one event row. Abstract methods are skipped (no body - not a
// handler); everything else stays selectable, the split only ranks.
export function handlerChoices(
  eventSignature: string | undefined,
  currentMethod: string | undefined,
  handlers: ModuleHandlersPayload | undefined
): HandlerChoices {
  const methods = (handlers?.methods ?? []).filter((m) => m.name && !m.abstract);
  const names = methods.map((m) => m.name);
  const parsed = eventSignature ? parseEventSignature(eventSignature) : undefined;
  let compatible: string[] = [];
  let rest = names;
  if (parsed) {
    compatible = methods.filter((m) => (m.params ?? []).length <= parsed.args.length).map((m) => m.name);
    const chosen = new Set(compatible);
    rest = names.filter((n) => !chosen.has(n));
  }
  const known = handlers !== undefined && !handlers.error;
  const currentMissing = !!currentMethod && known && !names.includes(currentMethod);
  return { compatible, rest, currentMissing };
}

// The engine's default handler name (<Имя узла | Тип узла><КлючСобытия>) - the InputBox
// suggestion of the "create handler" flow. The engine stays the authority: an empty input
// sends NO method and the engine derives (and uniquifies) the name itself.
export function defaultHandlerName(
  node: { name?: string | null; type?: string | null },
  key: string
): string {
  return `${node.name || node.type || ""}${key}`;
}

// Flat xbsl/addHandler request params; empty optionals are omitted, not sent as "".
export function buildAddHandlerParams(
  uri: string,
  nodeId: string,
  key: string,
  method?: string,
  signature?: string
): Record<string, string> {
  const params: Record<string, string> = { uri, node: nodeId, key };
  const trimmed = (method ?? "").trim();
  if (trimmed) {
    params.method = trimmed;
  }
  if (signature) {
    params.signature = signature;
  }
  return params;
}

// The xbsl/addHandler response parsed into an application plan for the extension: which
// buffers change how, where the module file comes from and where the cursor lands.
export interface HandlerApplyPlan {
  method: string;
  yamlEdits: EngineEditDto[];
  moduleUri: string;
  // true - create the module file with moduleText as its full content; false - apply
  // moduleEdits to the existing module buffer (both may be no-ops when the method exists).
  createFile: boolean;
  moduleText: string;
  moduleEdits: EngineEditDto[];
  cursorOffset?: number;
  notes: string[];
}

export function planHandlerApply(
  res: AddHandlerResponse
): { plan: HandlerApplyPlan } | { error: string } {
  if (res.error) {
    return { error: res.error };
  }
  if (!res.moduleUri || !res.method) {
    return { error: "неполный ответ xbsl/addHandler (нет moduleUri/method)" };
  }
  const createFile = res.created === true;
  if (createFile && typeof res.moduleText !== "string") {
    return { error: "неполный ответ xbsl/addHandler (created без moduleText)" };
  }
  return {
    plan: {
      method: res.method,
      yamlEdits: res.yamlEdits ?? [],
      moduleUri: res.moduleUri,
      createFile,
      moduleText: res.moduleText ?? "",
      moduleEdits: createFile ? [] : res.moduleEdits ?? [],
      cursorOffset: typeof res.cursor?.offset === "number" ? res.cursor.offset : undefined,
      notes: res.notes ?? [],
    },
  };
}

// -- yaml value extraction (read-only; writes go through the engine) --------------------------

const NUMBER_RE = /^-?\d+(?:\.\d+)?$/;
// Mirrors the engine's bare-scalar rule (formedits._encode_scalar) for fragment values.
const BARE_SCALAR_RE = /^[=$A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.,()<> =/-]*$/;
const YAML_AMBIGUOUS = new Set(["true", "false", "yes", "no", "on", "off", "null", "~"]);

function dedent(block: string): string {
  const lines = block.split("\n");
  let common: number | undefined;
  for (const line of lines) {
    if (!line.trim()) {
      continue;
    }
    const indent = line.length - line.trimStart().length;
    common = common === undefined ? indent : Math.min(common, indent);
  }
  if (!common) {
    return block;
  }
  return lines.map((l) => (l.trim() ? l.slice(common) : l)).join("\n");
}

// The parsed VALUE of a property block (the property span slice re-parsed as a one-key
// mapping). Returns undefined when the slice does not parse - the caller falls back to
// the engine's preview.
function parsePropValue(docText: string, prop: NodePropertyDto): unknown {
  const raw = docText.slice(prop.span.start, prop.span.end);
  try {
    const doc = parseDocument(dedent(raw), { uniqueKeys: false });
    const root = doc.contents;
    if (!isMap(root) || root.items.length !== 1) {
      return undefined;
    }
    return root.items[0].value ?? undefined;
  } catch {
    return undefined;
  }
}

// The exact decoded string of a scalar property (quotes and escapes resolved) - the engine's
// valuePreview is truncated and whitespace-collapsed, unusable for editing.
export function extractScalarValue(docText: string, prop: NodePropertyDto): string {
  const value = parsePropValue(docText, prop);
  if (isScalar(value) && value.value !== null && value.value !== undefined) {
    return String(value.value);
  }
  return prop.valuePreview;
}

// Fields of a composite property (Шрифт, Цвет...): scalar entries become editable fields,
// nested blocks lock the field-by-field editor (allScalar=false - "open in yaml" only,
// rebuilding the fragment would drop what the panel cannot render).
export function parseCompositeFields(
  docText: string,
  prop: NodePropertyDto
): { fields: CompositeField[]; allScalar: boolean } {
  const value = parsePropValue(docText, prop);
  if (!isMap(value)) {
    return { fields: [], allScalar: false };
  }
  const fields: CompositeField[] = [];
  let allScalar = true;
  for (const item of value.items) {
    const key = isScalar(item.key) ? String(item.key.value) : "";
    if (!key) {
      allScalar = false;
      continue;
    }
    if (isScalar(item.value) && item.value.value !== null && item.value.value !== undefined) {
      fields.push({ key, value: String(item.value.value), scalar: true });
    } else {
      fields.push({ key, value: "{...}", scalar: false });
      allScalar = false;
    }
  }
  return { fields, allScalar: allScalar && fields.length > 0 };
}

// -- color spellings --------------------------------------------------------------------------
//
// The yaml form of an absolute color is the composite {Тип: АбсолютныйЦвет, Значение: RGB(...)}
// with the RGB argument as RRGGBB hex (see demo/) or as three decimal components.

const HEX_RE = /^#?([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})$/;
const RGB_HEX_RE = /^RGB\(\s*([0-9A-Fa-f]{6})\s*\)$/;
const RGB_DEC_RE = /^RGB\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)$/;

// "#rrggbb" (or "rgb"/"#rgb" shorthands) -> the value_yaml fragment; undefined on bad input.
export function colorYaml(hexRaw: string): string | undefined {
  const m = HEX_RE.exec(hexRaw.trim());
  if (!m) {
    return undefined;
  }
  let hex = m[1];
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((c) => c + c)
      .join("");
  }
  return "Тип: АбсолютныйЦвет\nЗначение: RGB(" + hex + ")";
}

// #rrggbb of an АбсолютныйЦвет composite, undefined when the fields spell something else.
export function hexFromColorFields(fields: CompositeField[]): string | undefined {
  const type = fields.find((f) => f.key === "Тип")?.value;
  if (type !== "АбсолютныйЦвет") {
    return undefined;
  }
  const raw = fields.find((f) => f.key === "Значение")?.value ?? "";
  const hexMatch = RGB_HEX_RE.exec(raw);
  if (hexMatch) {
    return "#" + hexMatch[1].toLowerCase();
  }
  const dec = RGB_DEC_RE.exec(raw);
  if (dec) {
    const parts = [dec[1], dec[2], dec[3]].map((d) => Number(d));
    if (parts.some((n) => n > 255)) {
      return undefined;
    }
    return "#" + parts.map((n) => n.toString(16).padStart(2, "0")).join("");
  }
  return undefined;
}

// "#rgb" / "rrggbb" / "#RRGGBB" -> canonical "#rrggbb"; undefined on anything else. The color
// swatches (hook 7) store and compare colors in this one spelling so equal shades collapse.
export function normalizeHex(raw: string): string | undefined {
  const m = HEX_RE.exec(raw.trim());
  if (!m) {
    return undefined;
  }
  let hex = m[1];
  if (hex.length === 3) {
    hex = hex
      .split("")
      .map((c) => c + c)
      .join("");
  }
  return "#" + hex.toLowerCase();
}

// Every АбсолютныйЦвет value anywhere in the form yaml, as #rrggbb, first-seen order,
// deduplicated and capped. Feeds the color editor's "colors used in this form" swatches
// (hook 7): reusing an existing shade keeps a form on a small, deliberate palette.
const RGB_SCAN_RE = /RGB\(\s*(?:([0-9A-Fa-f]{6})|(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3}))\s*\)/g;

export function collectFormColors(docText: string, limit = 16): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of docText.matchAll(RGB_SCAN_RE)) {
    let hex: string | undefined;
    if (m[1]) {
      hex = "#" + m[1].toLowerCase();
    } else {
      const parts = [m[2], m[3], m[4]].map((d) => Number(d));
      if (parts.every((n) => n <= 255)) {
        hex = "#" + parts.map((n) => n.toString(16).padStart(2, "0")).join("");
      }
    }
    if (hex && !seen.has(hex)) {
      seen.add(hex);
      out.push(hex);
      if (out.length >= limit) {
        break;
      }
    }
  }
  return out;
}

// Every binding expression (=Объект.Поле, =не Активен, =Метод(Объект.Х) ...) present anywhere
// in the form yaml, deduplicated, first-seen order, capped. The binding editor (hook 6) offers
// them as autocomplete so a developer reuses the form's own data hookups instead of retyping.
// A binding sits at a value position - right after a key colon, plain (Ключ: =...) or flow
// ({Ключ: =...}) - and spells as "=" followed by expression characters (the engine's bare
// scalar set: identifiers, dots, commas, parens, comparisons, slashes, single spaces).
// Anchoring on the colon keeps a stray "=" in prose or a URL out of the suggestions.
const BINDING_SCAN_RE = /:\s*(=[A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.,()<>/ =-]*)/g;

export function collectFormBindings(docText: string, limit = 24): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of docText.matchAll(BINDING_SCAN_RE)) {
    // Trim a trailing run of ambiguous tail chars (spaces, an "=" from "== ...", a stray
    // separator) so "=Объект.Срок " and "=Объект.Срок }" both fold to "=Объект.Срок".
    const binding = m[1].replace(/[\s=]+$/, "");
    if (binding.length < 2 || seen.has(binding)) {
      continue;
    }
    seen.add(binding);
    out.push(binding);
    if (out.length >= limit) {
      break;
    }
  }
  return out;
}

// -- composite fragment assembly --------------------------------------------------------------

// One fragment value as yaml: bare where unambiguous, JSON double quotes otherwise -
// mirrors the engine's _encode_scalar so panel writes look hand-made.
export function encodeFragmentScalar(value: string): string {
  if (NUMBER_RE.test(value)) {
    return value;
  }
  if (
    value &&
    value === value.trim() &&
    !YAML_AMBIGUOUS.has(value.toLowerCase()) &&
    BARE_SCALAR_RE.test(value)
  ) {
    return value;
  }
  return JSON.stringify(value);
}

// The value_yaml fragment of a composite rebuilt from its scalar fields. A single field is
// spelled as a flow mapping: the engine writes ONE-line fragments inline after the key, and
// only a flow collection stays valid yaml there.
export function buildCompositeYaml(fields: { key: string; value: string }[]): string {
  const lines = fields.map((f) => `${f.key}: ${encodeFragmentScalar(f.value)}`);
  if (lines.length === 1) {
    return `{${lines[0]}}`;
  }
  return lines.join("\n");
}

// -- editor choice ----------------------------------------------------------------------------

function isMultiline(value: string): boolean {
  return value.includes("\n") || value.length > 60;
}

function compositeEditor(fields: CompositeField[], allScalar: boolean): RowEditor {
  return { control: "composite", fields, editable: allScalar };
}

// Value lists for the union members that are enumerations, cut out of the component's
// enums map; undefined when none of the members has one (or the map is absent).
function unionEnums(
  members: string[],
  componentEnums: Record<string, string[]> | undefined
): Record<string, string[]> | undefined {
  if (!componentEnums) {
    return undefined;
  }
  const out: Record<string, string[]> = {};
  for (const member of members) {
    const values = componentEnums[member];
    if (values && values.length) {
      out[member] = values;
    }
  }
  return Object.keys(out).length ? out : undefined;
}

// The typed editor of one property row. schemaProp - the ui schema record (may be absent:
// an unknown property or no schema at all); prop - the set yaml property (absent for rows
// of the "all" section that are not written yet); componentEnums - the per-component
// enumeration values of the uiSchema response (absent on older engines).
export function chooseEditor(
  schemaProp: UiPropDto | undefined,
  prop: NodePropertyDto | undefined,
  value: string,
  fields?: CompositeField[],
  allScalar?: boolean,
  componentEnums?: Record<string, string[]>
): RowEditor {
  if (prop?.kind === "binding") {
    return { control: "binding" };
  }
  if (schemaProp?.readonly || schemaProp?.slot) {
    return { control: "readonly" };
  }
  if (schemaProp?.event || prop?.kind === "handler") {
    return { control: "handler" };
  }
  if (schemaProp) {
    if (schemaProp.enum && schemaProp.enum.length > 0) {
      return { control: "enum", options: schemaProp.enum };
    }
    const real = (schemaProp.types ?? []).filter((t) => t !== "Авто");
    if (real.length === 1) {
      const t = real[0];
      if (t === "Булево") {
        return { control: "tristate" };
      }
      if (t === "Число") {
        return { control: "number" };
      }
      if (t === "Цвет") {
        return { control: "color" };
      }
      if (prop?.kind === "composite") {
        return compositeEditor(fields ?? [], allScalar ?? false);
      }
      return { control: "text", multiline: isMultiline(value) };
    }
    if (real.length > 1) {
      const current = fields?.find((f) => f.key === "Тип")?.value;
      const enums = unionEnums(real, componentEnums);
      return enums
        ? { control: "union", types: real, current, enums }
        : { control: "union", types: real, current };
    }
    // types is empty or ["Авто"] alone - fall through to the kind-based choice
  }
  if (prop?.kind === "composite") {
    return compositeEditor(fields ?? [], allScalar ?? false);
  }
  if (value === "Истина" || value === "Ложь") {
    return { control: "tristate" };
  }
  if (value !== "" && NUMBER_RE.test(value)) {
    return { control: "number" };
  }
  return { control: "text", multiline: isMultiline(value) };
}

// -- panel model assembly ---------------------------------------------------------------------

// The engine's universal child-slot keys (xbsl/formmodel.py CHILD_SLOTS): a property with one of
// these keys holds child components (or a content binding) and is not a plain clearable value,
// whatever the per-component schema says. Kept in sync with the engine by hand (a short, stable list).
const CHILD_SLOT_KEYS = new Set([
  "Содержимое",
  "Страницы",
  "Колонки",
  "Команды",
  "КомандыСтроки",
  "Шапка",
  "Подвал",
]);

function makeRow(
  key: string,
  prop: NodePropertyDto | undefined,
  schemaProp: UiPropDto | undefined,
  docText: string,
  componentEnums?: Record<string, string[]>,
  handlers?: ModuleHandlersPayload
): PanelRow {
  let value = "";
  let fields: CompositeField[] | undefined;
  let allScalar: boolean | undefined;
  let colorHex: string | undefined;
  if (prop) {
    if (prop.kind === "composite") {
      const parsed = parseCompositeFields(docText, prop);
      fields = parsed.fields;
      allScalar = parsed.allScalar;
      colorHex = hexFromColorFields(parsed.fields);
      value = prop.valuePreview;
    } else {
      value = extractScalarValue(docText, prop);
    }
  }
  let editor = chooseEditor(schemaProp, prop, value, fields, allScalar, componentEnums);
  if (editor.control === "handler") {
    // The dropdown content rides on the row: the webview stays a dumb renderer.
    editor = {
      control: "handler",
      choices: handlerChoices(schemaProp?.event, prop !== undefined ? value : undefined, handlers),
    };
  }
  const hayParts = [key, value];
  if (colorHex) {
    hayParts.push(colorHex);
  }
  for (const f of fields ?? []) {
    hayParts.push(f.value);
  }
  return {
    key,
    set: prop !== undefined,
    value,
    editor,
    doc: schemaProp?.doc,
    defaultValue: schemaProp?.default,
    since: schemaProp?.since,
    event: schemaProp?.event,
    colorHex,
    propSpan: prop?.span,
    // A slot: the schema flag OR one of the engine's universal child-slot keys (formmodel.py
    // CHILD_SLOTS). The latter catches a slot bound to a method (Содержимое: =Метод()) that the
    // per-component schema does not flag, but the engine still refuses to clear as a plain value.
    slot: schemaProp?.slot || CHILD_SLOT_KEYS.has(key),
    hay: hayParts.join(" ").toLowerCase(),
  };
}

// Sections of the panel (see the module docstring of formProps.ts for the layout):
//   set    - keys present in yaml, file order, events excluded;
//   events - event properties of the schema (schema order) plus set handlers the schema
//            does not know; only with a schema;
//   all    - every non-event, non-slot schema property alphabetically, set or not; only
//            with a schema. Set rows repeat here with the same editor - the panel model
//            is stateless, each row instance is complete.
// Without a schema the panel degrades to the set section alone (kind-based editors).
// handlers - the xbsl/moduleHandlers payload of the paired module: event rows grow a
// dropdown of its methods; undefined (older engine, failed request) keeps the dropdown
// minimal ((no handler) / current / create).
export function buildPanelModel(
  node: FormNodeDto,
  schema: UiComponentDto | null | undefined,
  docText: string,
  handlers?: ModuleHandlersPayload
): PanelModel {
  const props = node.properties ?? [];
  const schemaProps: Record<string, UiPropDto> = schema?.props ?? {};
  const componentEnums = schema?.enums;
  const hasSchema = !!schema;
  const byKey = new Map(props.map((p) => [p.key, p]));

  const isEventRow = (p: NodePropertyDto): boolean =>
    hasSchema && (!!schemaProps[p.key]?.event || p.kind === "handler");

  const sections: PanelSection[] = [];
  // The set section is sorted alphabetically, NOT in file order: the engine may re-insert a
  // re-set property anywhere in the yaml block, and a panel that followed file order would then
  // make the row jump around. A stable alphabetical order keeps every row in one place (the "all"
  // section is alphabetical for the same reason).
  sections.push({
    id: "set",
    rows: props
      .filter((p) => !isEventRow(p))
      .map((p) => makeRow(p.key, p, schemaProps[p.key], docText, componentEnums, handlers))
      .sort((a, b) => a.key.localeCompare(b.key, "ru")),
  });

  if (hasSchema) {
    const eventKeys = Object.keys(schemaProps).filter((k) => schemaProps[k].event);
    const unknownHandlers = props
      .filter((p) => p.kind === "handler" && !schemaProps[p.key])
      .map((p) => p.key);
    sections.push({
      id: "events",
      rows: [...eventKeys, ...unknownHandlers].map((k) =>
        makeRow(k, byKey.get(k), schemaProps[k], docText, componentEnums, handlers)
      ),
    });

    const allKeys = Object.keys(schemaProps)
      .filter((k) => !schemaProps[k].event && !schemaProps[k].slot)
      .sort((a, b) => a.localeCompare(b, "ru"));
    sections.push({
      id: "all",
      rows: allKeys.map((k) => makeRow(k, byKey.get(k), schemaProps[k], docText, componentEnums, handlers)),
    });
  }

  return {
    nodeId: node.id,
    type: node.type ?? "",
    name: node.name ?? "",
    nodeSpanStart: node.span.start,
    schemaAvailable: hasSchema,
    sections,
    formColors: collectFormColors(docText),
    formBindings: collectFormBindings(docText),
  };
}

// The panel filter: a row stays visible when the query occurs in its name OR its current
// value (case-insensitive). The webview applies the same test over the precomputed hay.
export function rowMatchesFilter(row: PanelRow, query: string): boolean {
  const q = query.trim().toLowerCase();
  return !q || row.hay.includes(q);
}

// -- write preparation and validation ---------------------------------------------------------

export type WritePayload =
  | { form: "scalar"; value: string; editor: RowEditor; wasSet: boolean; oldValue: string }
  | { form: "color"; hex: string }
  | { form: "composite"; fields: { key: string; value: string }[] }
  // options - the value list of an enumeration member (editor.enums[memberType]); when
  // present the value must be one of them.
  | { form: "union"; memberType: string; value: string; options?: string[] };

export type WritePlan =
  | { kind: "value"; value: string }
  | { kind: "valueYaml"; valueYaml: string }
  | { kind: "reset" }
  | { kind: "noop" }
  | { kind: "error"; code: "empty" | "number" | "enum" | "color" };

// Turns a committed editor value into the argument of ONE set-property call - or rejects it
// before anything reaches the engine. An empty value is never written: a set property is
// cleared by Reset, an unset row with an empty value is a no-op.
export function prepareWrite(payload: WritePayload): WritePlan {
  if (payload.form === "scalar") {
    const value = payload.value;
    if (value === payload.oldValue) {
      return { kind: "noop" };
    }
    if (value.trim() === "") {
      return payload.wasSet ? { kind: "error", code: "empty" } : { kind: "noop" };
    }
    // A binding expression (=Объект.Поле ...) is written verbatim - the platform evaluates it
    // at runtime, so the literal type checks (number/enum) below do not apply (hook 6).
    if (value.trim().charAt(0) === "=") {
      return { kind: "value", value };
    }
    if (payload.editor.control === "number" && !NUMBER_RE.test(value.trim())) {
      return { kind: "error", code: "number" };
    }
    if (payload.editor.control === "enum" && !payload.editor.options.includes(value)) {
      return { kind: "error", code: "enum" };
    }
    return { kind: "value", value };
  }
  if (payload.form === "color") {
    const yaml = colorYaml(payload.hex);
    return yaml ? { kind: "valueYaml", valueYaml: yaml } : { kind: "error", code: "color" };
  }
  if (payload.form === "composite") {
    if (!payload.fields.length || payload.fields.some((f) => f.value.trim() === "")) {
      return { kind: "error", code: "empty" };
    }
    return { kind: "valueYaml", valueYaml: buildCompositeYaml(payload.fields) };
  }
  // union
  const value = payload.value;
  if (value.trim() === "") {
    return { kind: "error", code: "empty" };
  }
  if (payload.options && !payload.options.includes(value)) {
    return { kind: "error", code: "enum" };
  }
  if (payload.memberType === "Цвет") {
    const yaml = colorYaml(value);
    return yaml ? { kind: "valueYaml", valueYaml: yaml } : { kind: "error", code: "color" };
  }
  if (payload.memberType === "Число" && !NUMBER_RE.test(value.trim())) {
    return { kind: "error", code: "number" };
  }
  if (
    payload.memberType === "Булево" &&
    value !== "Истина" &&
    value !== "Ложь"
  ) {
    return { kind: "error", code: "enum" };
  }
  return { kind: "value", value };
}

// The row a commit refers to (the model is the single source of editor semantics - the
// webview sends only key and value). Sections may repeat a key; the instances are built
// from the same data, the first hit is authoritative.
export function findRow(model: PanelModel, key: string): PanelRow | undefined {
  for (const section of model.sections) {
    const row = section.rows.find((r) => r.key === key);
    if (row) {
      return row;
    }
  }
  return undefined;
}

// A serial queue: jobs run strictly one after another, never overlapping. Property writes go
// through it so rapid clicks (a tri-state toggled several times) cannot run concurrently and
// splice edits over one another. A failing job does not break the chain for the next one.
export function createSerialQueue(): (job: () => Promise<void>) => Promise<void> {
  let chain: Promise<unknown> = Promise.resolve();
  return (job) => {
    const run = chain.then(job, job);
    chain = run.catch(() => undefined);
    return run;
  };
}
