// Pure logic of the unified "Properties" panel modes (docs/DESIGNER.md, stage 3: one
// properties engine for form components AND metadata objects). The module decides which
// mode an editor drives, resolves the metadata node under a cursor, converts a metadata
// node description (metadataCore) into the shared panel model (formPropsCore shapes) and
// assembles the metadata write edits out of the EXISTING primitives - propertyEdit
// (formPreviewCore) and insertItemEdit (metadataCore); no new write logic lives here or
// anywhere else on the TypeScript side. No vscode imports - covered by plain node tests
// (test/propsModes.test.ts); the webview and cursor wiring is in formProps.ts.

import { isMap, isScalar, isSeq, parseDocument } from "yaml";
import type { YAMLMap } from "yaml";
import { propertyEdit } from "./formPreviewCore";
import {
  MetaNodeDescription,
  MetaPropRow,
  TextEdit,
  describeMetaNode,
  describeStandardAttr,
  findAttrOffset,
  insertItemEdit,
} from "./metadataCore";
import { PanelModel, PanelRow, PanelSection, RowEditor } from "./formPropsCore";

// -- mode resolution ---------------------------------------------------------------------------

// What the unified properties panel should show for an editor:
//   component - an interface component yaml, the cursor drives the form node (formPropsCore);
//   metadata  - any other element yaml (ВидЭлемента present), the cursor drives the map node;
//   module    - an .xbsl module, the panel shows the paired yaml's object properties;
//   none      - not an element source; the panel keeps its last content.
export type EditorMode = "component" | "metadata" | "module" | "none";

const META_KIND_RE = /^ВидЭлемента[ \t]*:/m;

// head - the first lines of the document (the cheap slice the wiring already reads),
// full - the whole text. The component test mirrors the historical isFormYaml check of
// the panel and the preview: an interface component with inheritance.
export function classifyEditor(languageId: string, fileName: string, head: string, full: string): EditorMode {
  if (languageId === "xbsl" || /\.xbsl$/i.test(fileName)) {
    return "module";
  }
  if (languageId !== "yaml") {
    return "none";
  }
  if (head.includes("КомпонентИнтерфейса") && full.includes("Наследует")) {
    return "component";
  }
  if (META_KIND_RE.test(full)) {
    return "metadata";
  }
  return "none";
}

// The paired yaml description of a module: the same stem (X.xbsl -> X.yaml), with the
// object module suffix stripped (X.Объект.xbsl -> X.yaml). undefined for a non-.xbsl path.
export function pairedYamlPath(xbslPath: string): string | undefined {
  const m = /^(.*)\.xbsl$/i.exec(xbslPath);
  if (!m) {
    return undefined;
  }
  const stem = m[1].replace(/\.Объект$/, "");
  return `${stem}.yaml`;
}

const META_KIND_VALUE_RE = /^ВидЭлемента[ \t]*:[ \t]*["']?([^"'\s#]+)/m;

// ВидЭлемента of an element yaml - the key of its metadata schema; undefined when absent.
export function metaKindOf(text: string): string | undefined {
  return META_KIND_VALUE_RE.exec(text)?.[1];
}

// Whether the offset points at the document's root map (the object itself).
export function isRootNode(text: string, offset: number): boolean {
  let root: unknown;
  try {
    root = parseDocument(text, { uniqueKeys: false }).contents ?? undefined;
  } catch {
    return false;
  }
  return isMap(root) ? (root as YAMLMap).range?.[0] === offset : false;
}

// The way from the element's root down to the node at `offset`, as the metamodel needs it: the
// key of every collection passed through and the `Имя` of the item picked inside it. The root
// itself answers with an empty path (the kind's own schema); a node that is not an item of a
// collection - a nested block like КонтрольДоступа - answers undefined, since the metamodel
// addresses only collection items this way.
export interface MetaSchemaPath {
  sections: string[];
  names: string[];
}

export function metaSchemaPathAt(text: string, offset: number): MetaSchemaPath | undefined {
  let root: unknown;
  try {
    root = parseDocument(text, { uniqueKeys: false }).contents ?? undefined;
  } catch {
    return undefined;
  }
  if (!isMap(root)) {
    return undefined;
  }
  const path: MetaSchemaPath = { sections: [], names: [] };
  let map = root as YAMLMap;
  for (;;) {
    if (map.range?.[0] === offset) {
      return path;
    }
    const step = collectionStepAt(map, offset);
    if (!step) {
      return undefined;
    }
    path.sections.push(step.section);
    path.names.push(step.name);
    map = step.item;
  }
}

// The collection item of `map` that contains `offset`: which key it sits under and its `Имя`.
function collectionStepAt(
  map: YAMLMap,
  offset: number
): { section: string; name: string; item: YAMLMap } | undefined {
  for (const pair of map.items) {
    const key = (pair.key as { value?: unknown } | null)?.value;
    if (typeof key !== "string" || !isSeq(pair.value)) {
      continue;
    }
    for (const entry of (pair.value as { items: unknown[] }).items) {
      if (!isMap(entry)) {
        continue;
      }
      const item = entry as YAMLMap;
      const range = item.range;
      if (!range || offset < range[0] || offset > (range[2] ?? range[1])) {
        continue;
      }
      return { section: key, name: stringValue(item, "Имя") ?? "", item };
    }
  }
  return undefined;
}

function stringValue(map: YAMLMap, key: string): string | undefined {
  for (const pair of map.items) {
    if ((pair.key as { value?: unknown } | null)?.value === key) {
      const value = (pair.value as { value?: unknown } | null)?.value;
      return typeof value === "string" ? value : undefined;
    }
  }
  return undefined;
}

// -- metadata node resolution ------------------------------------------------------------------

function deepestMapAt(node: unknown, offset: number): YAMLMap | undefined {
  if (isMap(node)) {
    const map = node as YAMLMap;
    for (const item of map.items) {
      const inner = deepestMapAt(item.value, offset);
      if (inner) {
        return inner;
      }
    }
    const range = map.range;
    if (range && range[0] <= offset && offset <= (range[2] ?? range[1])) {
      return map;
    }
    return undefined;
  }
  if (isSeq(node)) {
    for (const item of node.items) {
      const inner = deepestMapAt(item, offset);
      if (inner) {
        return inner;
      }
    }
  }
  return undefined;
}

// Start offset of the deepest yaml map containing the cursor - the node describeMetaNode
// should present (a field under the cursor, or the object itself on the top-level lines).
// Outside every map (e.g. offset 0 before leading comments) the root map answers.
export function metaNodeOffsetAt(text: string, offset: number): number | undefined {
  let root: unknown;
  try {
    root = parseDocument(text, { uniqueKeys: false }).contents ?? undefined;
  } catch {
    return undefined;
  }
  const found = deepestMapAt(root, offset);
  if (found?.range) {
    return found.range[0];
  }
  const rootRange = isMap(root) ? (root as YAMLMap).range : undefined;
  return rootRange ? rootRange[0] : undefined;
}

// What a metadata refresh should describe: an exact node offset (the tree sends map starts),
// a cursor position (the editor mode - resolved to the containing map), or a standard
// attribute of a kind (possibly synthetic - absent from yaml until materialized).
export interface MetaSelector {
  offset?: number;
  cursor?: number;
  std?: { kind: string; name: string };
}

export function describeMetaSelection(text: string, sel: MetaSelector): MetaNodeDescription | undefined {
  if (sel.std) {
    return describeStandardAttr(text, sel.std.kind, sel.std.name);
  }
  const nodeOffset = sel.offset !== undefined ? sel.offset : metaNodeOffsetAt(text, sel.cursor ?? 0);
  return nodeOffset === undefined ? undefined : describeMetaNode(text, nodeOffset);
}

// -- the metadata schema of an element kind ----------------------------------------------------
//
// What the engine answers to xbsl/metadataSchema: the properties the platform metamodel declares
// for a ВидЭлемента. `kind` here is the property's value kind (boolean | number | string | enum |
// type | block | list), not the element kind - `block` and `list` are the nested structures
// (КонтрольДоступа, Реквизиты), which the tree edits, not the panel.

export interface MetaSchemaProp {
  kind?: string;
  type?: string;
  enum?: string; // the enumeration whose values are in MetaSchema.enums
  default?: string;
  since?: string;
  required?: boolean;
  deprecated?: boolean; // an old spelling kept for compatibility - not offered
  priority?: number;
  item?: string;
  impl?: string;
  alias?: string[];
  types?: string;
}

export interface MetaSchema {
  kind: string;
  props: Record<string, MetaSchemaProp>;
  enums: Record<string, string[]>;
}

const SCALAR_PROP_KINDS = new Set(["boolean", "number", "string", "enum", "type"]);

// -- metadata rows in the shared panel model ---------------------------------------------------

function metaRowEditor(row: MetaPropRow, typeCandidates: string[] | undefined): RowEditor {
  if (row.readonly) {
    return { control: "readonly" };
  }
  switch (row.control) {
    case "tristate":
      return { control: "tristate" };
    case "select":
      return { control: "enum", options: row.options ?? [] };
    case "combo":
      // The Тип combobox: candidates come from the metadata tree provider (the core does
      // not know the project contents); the list is open - a value can be typed manually.
      return { control: "combo", options: typeCandidates ?? row.options ?? [] };
    default:
      return { control: "text", multiline: false };
  }
}

// The editor a schema property deserves. A structure (block/list) gets a read-only row: it is
// worth SEEING that a Справочник has ТабличныеЧасти, but editing them belongs to the tree.
function schemaRowEditor(
  prop: MetaSchemaProp,
  schema: MetaSchema,
  typeCandidates: string[] | undefined
): RowEditor {
  switch (prop.kind) {
    case "boolean":
      return { control: "tristate" };
    case "number":
      return { control: "number" };
    case "enum":
      return { control: "enum", options: (prop.enum && schema.enums[prop.enum]) || [] };
    case "type":
      return { control: "combo", options: typeCandidates ?? [] };
    case "string":
      return { control: "text", multiline: false };
    default:
      return { control: "readonly" };
  }
}

function schemaRow(
  key: string,
  prop: MetaSchemaProp,
  schema: MetaSchema,
  set: MetaPropRow | undefined,
  typeCandidates: string[] | undefined
): PanelRow {
  const value = set?.value ?? "";
  const readonly = set?.readonly;
  return {
    key,
    set: set !== undefined,
    value,
    editor: readonly ? { control: "readonly" } : schemaRowEditor(prop, schema, typeCandidates),
    defaultValue: prop.default,
    since: prop.since,
    hay: `${key} ${value}`.toLowerCase(),
  };
}

// The panel header already names the kind and the object ("Перечисление · Товары") - a
// ВидЭлемента row would repeat it, in whichever spelling the file uses.
const KIND_KEYS = new Set(["ВидЭлемента", "ElementKind"]);

// The metadata node description rendered through the shared panel model. With a schema of the
// element kind the layout matches the component mode - the EDITABLE properties written in the
// file first, every applicable one below - so an unset Представление or Иерархический is
// discoverable instead of invisible. Everything the panel cannot edit (Ид, the tree-owned
// structures - collections with their size, blocks) sits once in its own "readonly" section
// instead of being interleaved with the editable rows and repeated per section. Without a
// schema (a nested node, an unknown kind, no generated data) the panel degrades to the set
// rows, split the same way. A synthetic standard attribute (offset -1, no record in yaml)
// shows the schema's property set with everything unset - its handwritten spec rows are only
// the no-schema fallback; editing materializes the record (metaPropertyEdits below).
export function buildMetaPanelModel(
  desc: MetaNodeDescription,
  typeCandidates?: string[],
  schema?: MetaSchema
): PanelModel {
  const synthetic = desc.offset < 0;
  const nameRow = desc.rows.find((r) => r.key === "Имя");
  const name = nameRow && nameRow.value !== desc.title ? nameRow.value : "";
  const visible = synthetic && schema ? [] : desc.rows.filter((r) => !KIND_KEYS.has(r.key));
  const byKey = new Map(visible.map((r) => [r.key, r]));
  const toRow = (r: MetaPropRow): PanelRow => {
    const prop = schema?.props[r.key];
    return {
      key: r.key,
      set: !synthetic,
      value: r.value,
      // A known property is edited by its declared type (a dropdown for an enumeration, a
      // switch for a flag); an unknown one keeps the value-shaped editor.
      editor: prop && !r.readonly && SCALAR_PROP_KINDS.has(prop.kind ?? "")
        ? schemaRowEditor(prop, schema as MetaSchema, typeCandidates)
        : metaRowEditor(r, typeCandidates),
      defaultValue: prop?.default,
      since: prop?.since,
      hay: `${r.key} ${r.value}`.toLowerCase(),
    };
  };
  const rows: PanelRow[] = visible.filter((r) => !r.readonly).map(toRow);
  const readonlyRows: PanelRow[] = visible.filter((r) => r.readonly).map(toRow);
  const sections: PanelSection[] = [{ id: "set", rows }];
  if (schema) {
    const all: PanelRow[] = [];
    for (const [key, prop] of Object.entries(schema.props)) {
      if (prop.deprecated || KIND_KEYS.has(key)) {
        continue;
      }
      const set = byKey.get(key);
      if (set?.readonly) {
        continue; // already in the readonly section - never twice
      }
      // A collection present in yaml (Элементы, Реквизиты ...) has no scalar row, but it
      // is set - show its size instead of "(not set)". Editing stays with the tree.
      const count = desc.collections?.[key];
      if (count !== undefined && !byKey.has(key)) {
        readonlyRows.push({
          key,
          set: true,
          value: String(count),
          editor: { control: "readonly" } as RowEditor,
          defaultValue: prop.default,
          since: prop.since,
          hay: `${key} ${count}`.toLowerCase(),
        });
        continue;
      }
      const row = schemaRow(key, prop, schema, set, typeCandidates);
      if ((row.editor as { control: string }).control === "readonly") {
        readonlyRows.push(row); // a tree-owned structure (block/list) - visible, not editable
        continue;
      }
      all.push(row);
    }
    sections.push({ id: "all" as const, rows: all });
  }
  if (readonlyRows.length > 0) {
    sections.push({ id: "readonly" as const, rows: readonlyRows });
  }
  return {
    meta: true,
    nodeId: "",
    type: desc.title,
    name,
    nodeSpanStart: Math.max(desc.offset, 0),
    schemaAvailable: !!schema,
    sections,
  };
}

// -- metadata writes ---------------------------------------------------------------------------

// The write target of the metadata mode: the node offset in yaml, plus the standard
// attribute name when the panel shows one (offset is ignored then - the record is found,
// or materialized, by Имя).
export interface MetaEditTarget {
  offset: number;
  std?: { name: string };
}

const STRING_TYPES = new Set(["Строка", "Строка?"]);

// Text edits of one metadata property write (value null removes the key). Composed from the
// existing primitives only. A synthetic standard attribute materializes: an edit appends
// { Имя: <name>, <key>: <value> } to Реквизиты. Тип changed to a non-string one also drops
// the string-specific Многострочная property (an edit over the same source text, on a
// different line - it does not overlap the type edit).
export function metaPropertyEdits(
  text: string,
  target: MetaEditTarget,
  key: string,
  value: string | null
): TextEdit[] {
  if (target.std) {
    const off = findAttrOffset(text, target.std.name);
    if (off === undefined) {
      if (value === null) {
        return []; // nothing to remove from a non-existent record
      }
      return [insertItemEdit(text, "Реквизиты", [`Имя: ${target.std.name}`, `${key}: ${value}`])];
    }
    const edit = propertyEdit(text, off, key, value);
    return edit ? [edit] : [];
  }
  const edit = propertyEdit(text, target.offset, key, value);
  if (!edit) {
    return [];
  }
  const edits = [edit];
  if (key === "Тип" && value !== null && !STRING_TYPES.has(value)) {
    const strip = propertyEdit(text, target.offset, "Многострочная", null);
    if (strip) {
      edits.push(strip);
    }
  }
  return edits;
}
