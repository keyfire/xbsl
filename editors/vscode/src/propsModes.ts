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
import { PanelModel, PanelRow, RowEditor } from "./formPropsCore";

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

// The metadata node description rendered through the shared panel model: one flat row list
// (sections, events and the legend are component-mode concepts), the header shows
// ВидЭлемента/Имя. A synthetic standard attribute (offset -1, no record in yaml) renders
// every row as "not set" - editing materializes the record (metaPropertyEdits below).
export function buildMetaPanelModel(
  desc: MetaNodeDescription,
  typeCandidates?: string[]
): PanelModel {
  const synthetic = desc.offset < 0;
  const nameRow = desc.rows.find((r) => r.key === "Имя");
  const name = nameRow && nameRow.value !== desc.title ? nameRow.value : "";
  const rows: PanelRow[] = desc.rows.map((r) => ({
    key: r.key,
    set: !synthetic,
    value: r.value,
    editor: metaRowEditor(r, typeCandidates),
    hay: `${r.key} ${r.value}`.toLowerCase(),
  }));
  return {
    meta: true,
    nodeId: "",
    type: desc.title,
    name,
    nodeSpanStart: Math.max(desc.offset, 0),
    schemaAvailable: true,
    sections: [{ id: "set", rows }],
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
