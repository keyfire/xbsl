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

// The component name a yaml path stands for: the platform names the file after the element, so a
// path of `.../КарточкаЗадачи.yaml` is the component `КарточкаЗадачи`. The designer keys its cache
// of nested components by that name and drops the entry when the file is edited - without which
// the frame kept showing the previous version of the component until a manual refresh.
export function componentNameOfPath(path: string): string | undefined {
  const file = path.split(/[\\/]/).pop() ?? "";
  return file.toLowerCase().endsWith(".yaml") && file.length > ".yaml".length
    ? file.slice(0, -".yaml".length)
    : undefined;
}

// The last path segment when it carries the given extension (any case), or nothing.
function fileWithExtension(path: string, extension: string): string | undefined {
  const file = path.split(/[\\/]/).pop() ?? "";
  return file.toLowerCase().endsWith(extension) && file.length > extension.length ? file : undefined;
}

// The module file of a form: the platform pairs the yaml with a module of the same base name in
// the same directory, so the mapping swaps the extension and nothing else. Whether the file
// exists is the caller's business - the designer dims its bottom tab when it does not.
export function modulePathOfForm(path: string): string | undefined {
  return fileWithExtension(path, ".yaml") !== undefined ? path.slice(0, -".yaml".length) + ".xbsl" : undefined;
}

// The way back: the yaml a module file belongs to. As mechanical as modulePathOfForm - whether
// that yaml is a form is the caller's check (looksLikeFormText).
export function formPathOfModule(path: string): string | undefined {
  return fileWithExtension(path, ".xbsl") !== undefined ? path.slice(0, -".xbsl".length) + ".yaml" : undefined;
}

// Whether a yaml text is a form: an interface component (the kind marker sits in the head
// lines) that inherits a base. Shared by the designer (which yamls open as a form panel) and
// by the module editor's title button (whose sibling yaml decides if the button shows).
export function looksLikeFormText(text: string): boolean {
  const head = text.split(/\r?\n/, 50).join("\n");
  const kind = head.includes("КомпонентИнтерфейса") || head.includes("InterfaceComponent");
  return kind && (text.includes("Наследует") || text.includes("Inherits"));
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

// Open every collapsed ancestor of a node, so a reveal from outside the pane (a click in the
// form frame, the yaml cursor, the result of an operation) can actually land on it: a row under
// a collapsed group is not in the flattened rows at all. Mutates the expansion memory and
// answers whether anything had to be opened.
export function expandAncestors(
  index: FormIndex,
  id: string,
  expanded: Set<string>,
  collapsed: Set<string>
): boolean {
  if (!index.byId.has(id)) {
    return false;
  }
  let changed = false;
  let parent = index.parentOf.get(id);
  while (parent !== undefined) {
    if (collapsed.delete(parent)) {
      changed = true;
    }
    if (!expanded.has(parent)) {
      expanded.add(parent);
      changed = true;
    }
    parent = index.parentOf.get(parent);
  }
  return changed;
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

/** The column a jump-to-node scrolls to: the content with ONE indent level still visible.
 *
 * Revealing the content itself pins it to the very edge and the nesting becomes unreadable -
 * a form node sits eight levels deep, and the eye needs the step it hangs from. A top-level
 * line keeps column zero.
 */
export function revealStartColumn(indent: number, tabSize: number): number {
  const unit = Number.isFinite(tabSize) && tabSize > 0 ? Math.floor(tabSize) : 4;
  return Math.max(0, indent - unit);
}

/** Whether a reveal request should actually bring a paired source document forward.
 *
 * A form panel travels with its sources (the yaml, and separately the module), but the
 * pairing never ADDS a tab: a closed source stays closed until the developer actually asks
 * for it. That only matters for an IMPLICIT reveal - the cursor merely following a click on
 * a form field, a row in a pane, or the result of an edit operation, with nothing explicitly
 * asked of the document. An explicit request ("Show in yaml", Ctrl+click, "Open in editor")
 * always opens, tab or no tab, any column - it is a direct ask, not a follow.
 *
 * For an implicit follow, the tab also has to sit somewhere other than the panel's own
 * column: revealing it there would just cover the panel the click was aimed at, which is not
 * what "following" means either.
 */
export function shouldRevealInEditor(explicit: boolean, tabColumn: number | undefined, panelColumn: number | undefined): boolean {
  return explicit || (tabColumn !== undefined && tabColumn !== panelColumn);
}

/** The column a freshly created module opens in, next to the panel that triggered its
 * creation - never IN the panel's own column, which would put the new code behind the very
 * form that just asked for it. Reuses the module's own tab if one is already open elsewhere,
 * else joins wherever yaml/xbsl sources already live, else answers `undefined` - the caller
 * splits a new group beside the active one (there is no existing candidate to reuse).
 *
 * The panel's column is excluded at EVERY tier, not just the first: a source group that
 * happens to share the panel's column is exactly as unusable as the module's own tab would be
 * there - either way the result lands behind the panel.
 */
export function neighborColumn(
  sameDocColumn: number | undefined,
  sourceColumn: number | undefined,
  panelColumn: number | undefined
): number | undefined {
  if (sameDocColumn !== undefined && sameDocColumn !== panelColumn) {
    return sameDocColumn;
  }
  if (sourceColumn !== undefined && sourceColumn !== panelColumn) {
    return sourceColumn;
  }
  return undefined;
}
