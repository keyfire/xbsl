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
  type?: string | null;
  typeFull?: string | null;
  name?: string | null;
  slot?: string | null;
  properties?: NodePropertyDto[];
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
  | { control: "union"; types: string[]; current?: string }
  | { control: "composite"; fields: CompositeField[]; editable: boolean }
  | { control: "binding" }
  | { control: "handler" }
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
  hay: string; // lowercased "name + value" haystack for the panel filter
}

export type SectionId = "set" | "events" | "all";

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

// The typed editor of one property row. schemaProp - the ui schema record (may be absent:
// an unknown property or no schema at all); prop - the set yaml property (absent for rows
// of the "all" section that are not written yet).
export function chooseEditor(
  schemaProp: UiPropDto | undefined,
  prop: NodePropertyDto | undefined,
  value: string,
  fields?: CompositeField[],
  allScalar?: boolean
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
      return { control: "union", types: real, current };
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

function makeRow(
  key: string,
  prop: NodePropertyDto | undefined,
  schemaProp: UiPropDto | undefined,
  docText: string
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
  const editor = chooseEditor(schemaProp, prop, value, fields, allScalar);
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
export function buildPanelModel(
  node: FormNodeDto,
  schema: UiComponentDto | null | undefined,
  docText: string
): PanelModel {
  const props = node.properties ?? [];
  const schemaProps: Record<string, UiPropDto> = schema?.props ?? {};
  const hasSchema = !!schema;
  const byKey = new Map(props.map((p) => [p.key, p]));

  const isEventRow = (p: NodePropertyDto): boolean =>
    hasSchema && (!!schemaProps[p.key]?.event || p.kind === "handler");

  const sections: PanelSection[] = [];
  sections.push({
    id: "set",
    rows: props
      .filter((p) => !isEventRow(p))
      .map((p) => makeRow(p.key, p, schemaProps[p.key], docText)),
  });

  if (hasSchema) {
    const eventKeys = Object.keys(schemaProps).filter((k) => schemaProps[k].event);
    const unknownHandlers = props
      .filter((p) => p.kind === "handler" && !schemaProps[p.key])
      .map((p) => p.key);
    sections.push({
      id: "events",
      rows: [...eventKeys, ...unknownHandlers].map((k) =>
        makeRow(k, byKey.get(k), schemaProps[k], docText)
      ),
    });

    const allKeys = Object.keys(schemaProps)
      .filter((k) => !schemaProps[k].event && !schemaProps[k].slot)
      .sort((a, b) => a.localeCompare(b, "ru"));
    sections.push({
      id: "all",
      rows: allKeys.map((k) => makeRow(k, byKey.get(k), schemaProps[k], docText)),
    });
  }

  return {
    nodeId: node.id,
    type: node.type ?? "",
    name: node.name ?? "",
    nodeSpanStart: node.span.start,
    schemaAvailable: hasSchema,
    sections,
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
  | { form: "union"; memberType: string; value: string };

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
