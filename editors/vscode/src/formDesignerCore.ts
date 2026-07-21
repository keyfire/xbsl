// Pure core of the form designer panel (no vscode import), unit-tested under plain Node
// (test/formDesignerCore.test.ts). The panel paints its own trees inside a webview, so the
// structure and data models have to arrive there as FLAT rows: a webview cannot ask for
// children lazily the way a native TreeView does. This module turns the engine's tree index
// into those rows (honouring the expansion memory, the named-only filter and the focused
// subtree), builds the rows of the data pane, composes the context menu of a row and clamps
// the pane layout. Every EDIT still goes through the engine - see formStructureCore.ts.

import { ComponentPropertyRecord, ObjectInfoField, ObjectInfoTabular } from "./formDataCore";
import {
  FormIndex,
  FormNode,
  isContainerNode,
  NodeDiagBadge,
  nodeDescription,
  nodeIconId,
  nodeLabel,
  ROOT_ID,
} from "./formStructureCore";

// --- structure rows ---------------------------------------------------------------------------

export interface RowBadge {
  count: number;
  //: vscode.DiagnosticSeverity: 0 error .. 3 hint
  severity: number;
}

export interface StructureRow {
  id: string;
  //: Nesting level, 0 for the (effective) root - the webview indents by it.
  depth: number;
  label: string;
  description: string;
  //: Codicon id, the same mapping the palette uses (componentIconsCore).
  icon: string;
  kind: "root" | "slot" | "component";
  container: boolean;
  hasChildren: boolean;
  expanded: boolean;
  //: Whether the row can be picked up by the panel's own drag and drop.
  draggable: boolean;
  badge?: RowBadge;
  tooltip: string;
}

export interface FlattenOptions {
  //: Ids the user expanded / collapsed by hand; everything else follows the default
  //: (slots and the effective root are open, components are closed).
  expanded: ReadonlySet<string>;
  collapsed: ReadonlySet<string>;
  //: The named-only filter, when on: ids allowed to show.
  visibleIds?: ReadonlySet<string>;
  //: The focused subtree root; the form root when absent.
  rootId?: string;
  badges?: ReadonlyMap<string, NodeDiagBadge>;
  isContainerType?: (type: string) => boolean;
  packageOf?: (type: string) => string | undefined;
  //: Localized tooltip of a slot row (the caller owns the l10n catalog).
  slotTooltip?: (name: string) => string;
}

export function isRowExpanded(node: FormNode, isRoot: boolean, options: FlattenOptions): boolean {
  if (options.collapsed.has(node.id)) {
    return false;
  }
  if (options.expanded.has(node.id)) {
    return true;
  }
  return node.kind === "slot" || isRoot;
}

// The structure tree as the flat row list the webview paints: a pre-order walk that stops
// descending into a collapsed row. A row still reports hasChildren when collapsed - the
// twisty must be there to open it.
export function flattenStructure(index: FormIndex, options: FlattenOptions): StructureRow[] {
  const rootId = options.rootId && index.byId.has(options.rootId) ? options.rootId : index.root.id;
  const root = index.byId.get(rootId) ?? index.root;
  const rows: StructureRow[] = [];
  const childrenOf = (node: FormNode): FormNode[] => {
    const kids = node.children ?? [];
    return options.visibleIds ? kids.filter((c) => options.visibleIds!.has(c.id)) : kids;
  };
  const walk = (node: FormNode, depth: number): void => {
    const kids = childrenOf(node);
    const expanded = isRowExpanded(node, node.id === rootId, options);
    rows.push(structureRow(node, depth, kids.length > 0, expanded, options));
    if (!expanded) {
      return;
    }
    for (const child of kids) {
      walk(child, depth + 1);
    }
  };
  walk(root, 0);
  return rows;
}

function structureRow(
  node: FormNode,
  depth: number,
  hasChildren: boolean,
  expanded: boolean,
  options: FlattenOptions
): StructureRow {
  const badge = options.badges?.get(node.id);
  const base = nodeDescription(node);
  const kind: StructureRow["kind"] = node.id === ROOT_ID ? "root" : node.kind === "slot" ? "slot" : "component";
  const tooltipParts: string[] = [];
  if (node.kind === "slot") {
    tooltipParts.push(options.slotTooltip?.(node.name ?? "") ?? node.name ?? "");
  } else {
    tooltipParts.push(node.typeFull || node.type || "");
  }
  if (badge) {
    tooltipParts.push(badge.firstMessage);
  }
  return {
    id: node.id,
    depth,
    label: nodeLabel(node),
    description: badge ? `${base ? base + " · " : ""}(${badge.count})` : base,
    icon: nodeIconId(node, options.isContainerType, options.packageOf),
    kind,
    container: isContainerNode(node, options.isContainerType),
    hasChildren,
    expanded,
    draggable: kind === "component",
    badge: badge ? { count: badge.count, severity: badge.severity } : undefined,
    tooltip: tooltipParts.filter(Boolean).join("\n\n"),
  };
}

// --- data rows --------------------------------------------------------------------------------

export type DataRowKind = "section" | "property" | "attribute" | "tabular" | "column";

export interface DataRow {
  id: string;
  depth: number;
  label: string;
  description: string;
  icon: string;
  kind: DataRowKind;
  hasChildren: boolean;
  expanded: boolean;
  //: Whether the row can become an input component (dragged into the structure, inserted
  //: by a double click). A record with no Имя and the reference-only rows cannot.
  insertable: boolean;
  tooltip: string;
}

export interface DataModel {
  //: The component's own Свойства records (xbsl/formTree).
  records: readonly ComponentPropertyRecord[];
  //: The form's owner object, when the form belongs to one.
  owner?: { name: string; kind: string };
  fields: readonly ObjectInfoField[];
  tabulars: readonly ObjectInfoTabular[];
}

export interface DataLabels {
  propsSection: string;
  objectSection: string;
  propertyTooltip: string;
  attributeTooltip: string;
  tabularTooltip: string;
  insertHint: string;
}

export const PROPS_SECTION_ID = "sec:props";
export const OBJECT_SECTION_ID = "sec:object";

// The id of a component-property row. A record with no Имя still needs a stable id (it is
// shown, just not insertable), so it falls back to its position.
export function propertyRowId(record: ComponentPropertyRecord, index: number): string {
  return record.name ? `prop:${record.name}` : `prop#${index}`;
}

// The data pane as flat rows: the component's own properties section always, the owner
// object's section when the form has one. Collapsed sections keep their children out, the
// same rule the structure pane follows.
export function flattenData(
  model: DataModel,
  expanded: ReadonlySet<string>,
  collapsed: ReadonlySet<string>,
  labels: DataLabels
): DataRow[] {
  const rows: DataRow[] = [];
  //: Sections open by default, tabular parts closed - they are shown for reference.
  const open = (id: string, byDefault: boolean): boolean =>
    collapsed.has(id) ? false : expanded.has(id) || byDefault;

  const propsOpen = open(PROPS_SECTION_ID, true);
  rows.push({
    id: PROPS_SECTION_ID,
    depth: 0,
    label: labels.propsSection,
    description: String(model.records.length),
    icon: "symbol-property",
    kind: "section",
    hasChildren: model.records.length > 0,
    expanded: propsOpen,
    insertable: false,
    tooltip: "",
  });
  if (propsOpen) {
    model.records.forEach((record, i) => {
      const type = record.type ?? "";
      rows.push({
        id: propertyRowId(record, i),
        depth: 1,
        label: record.name ?? "?",
        description: type,
        icon: "symbol-property",
        kind: "property",
        hasChildren: false,
        expanded: false,
        insertable: !!record.name,
        tooltip: rowTooltip(labels.propertyTooltip, type, !!record.name, labels),
      });
    });
  }

  if (!model.owner) {
    return rows;
  }
  const objectOpen = open(OBJECT_SECTION_ID, true);
  rows.push({
    id: OBJECT_SECTION_ID,
    depth: 0,
    label: labels.objectSection,
    description: `${model.owner.name} · ${model.fields.length + model.tabulars.length}`,
    icon: "database",
    kind: "section",
    hasChildren: model.fields.length + model.tabulars.length > 0,
    expanded: objectOpen,
    insertable: false,
    tooltip: `${model.owner.kind} ${model.owner.name}`,
  });
  if (!objectOpen) {
    return rows;
  }
  for (const field of model.fields) {
    rows.push({
      id: `attr:${field.name}`,
      depth: 1,
      label: field.name,
      description: field.type,
      icon: "symbol-field",
      kind: "attribute",
      hasChildren: false,
      expanded: false,
      insertable: true,
      tooltip: rowTooltip(labels.attributeTooltip, field.type, true, labels),
    });
  }
  for (const tabular of model.tabulars) {
    const id = `tab:${tabular.name}`;
    const tabularOpen = open(id, false);
    rows.push({
      id,
      depth: 1,
      label: tabular.name,
      description: String(tabular.fields.length),
      icon: "table",
      kind: "tabular",
      hasChildren: tabular.fields.length > 0,
      expanded: tabularOpen,
      insertable: false,
      tooltip: labels.tabularTooltip,
    });
    if (!tabularOpen) {
      continue;
    }
    for (const field of tabular.fields) {
      rows.push({
        id: `col:${tabular.name}:${field.name}`,
        depth: 2,
        label: field.name,
        description: field.type,
        icon: "symbol-field",
        kind: "column",
        hasChildren: false,
        expanded: false,
        insertable: false,
        tooltip: "",
      });
    }
  }
  return rows;
}

function rowTooltip(caption: string, type: string, insertable: boolean, labels: DataLabels): string {
  const head = caption + (type ? ` · ${type}` : "");
  return insertable ? `${head}\n\n${labels.insertHint}` : head;
}

// --- context menus ----------------------------------------------------------------------------

export interface MenuItem {
  //: Short command id; the panel prefixes it with xbsl.formStructure. / xbsl.formData.
  command: string;
  //: A divider is drawn above this item.
  separatorBefore?: boolean;
}

// The structure row's context menu. The single source of the row actions: the panel only
// maps these ids to labels and back to commands, so an action cannot exist in the menu and
// be missing from the command table.
export function structureMenu(row: StructureRow, selectionCount = 1): MenuItem[] {
  const items: MenuItem[] = [];
  if (row.kind === "component") {
    items.push({ command: "openInEditor" });
    if (selectionCount > 1) {
      items.push({ command: "editSelected" });
    }
    items.push({ command: "moveUp", separatorBefore: true }, { command: "moveDown" });
    items.push({ command: "wrap", separatorBefore: true });
    if (row.container) {
      items.push({ command: "unwrap" });
    }
    items.push({ command: "duplicate" }, { command: "rename" }, { command: "delete" });
    items.push({ command: "copyYaml", separatorBefore: true }, { command: "pasteYaml" });
    items.push({ command: "savePreset", separatorBefore: true }, { command: "insertPreset" });
    items.push({ command: "focusSubtree", separatorBefore: true });
    return items;
  }
  // A slot or the form root: nothing to move or rename, but both accept insertions.
  items.push({ command: "openInEditor" });
  items.push({ command: "pasteYaml", separatorBefore: true }, { command: "insertPreset" });
  return items;
}

// The data row's context menu. Object attributes and tabular parts are read-only here (the
// metadata tree owns them) - only the component's own properties can be edited.
export function dataMenu(row: DataRow): MenuItem[] {
  if (row.kind === "property") {
    const items: MenuItem[] = [];
    if (row.insertable) {
      items.push({ command: "insert" });
    }
    items.push(
      { command: "renameProperty", separatorBefore: items.length > 0 },
      { command: "retypeProperty" },
      { command: "removeProperty" }
    );
    items.push({ command: "addProperty", separatorBefore: true });
    return items;
  }
  if (row.kind === "attribute") {
    return [{ command: "insert" }];
  }
  if (row.id === PROPS_SECTION_ID) {
    return [{ command: "addProperty" }];
  }
  return [];
}

// --- pane layout ------------------------------------------------------------------------------

export interface DesignerLayout {
  //: Width of the structure pane, percent of the panel width.
  left: number;
  //: Height of the trees row, percent of the panel height.
  top: number;
}

export const DEFAULT_LAYOUT: DesignerLayout = { left: 52, top: 42 };

const MIN_SHARE = 15;
const MAX_SHARE = 85;

function clampShare(value: unknown, fallback: number): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.min(MAX_SHARE, Math.max(MIN_SHARE, Math.round(n)));
}

// A stored layout is user data from a previous session (or from another version of the
// panel): anything unusable falls back to the default, and a splitter dragged to the edge
// is clamped so a pane can never become unreachable.
export function sanitizeLayout(raw: unknown): DesignerLayout {
  const value = (raw ?? {}) as Partial<DesignerLayout>;
  return {
    left: clampShare(value.left, DEFAULT_LAYOUT.left),
    top: clampShare(value.top, DEFAULT_LAYOUT.top),
  };
}
