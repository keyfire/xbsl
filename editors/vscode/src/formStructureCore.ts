// Pure core of the "Form structure" view (no vscode import), unit-tested under plain Node
// (test/formStructureCore.test.ts): the shapes of the engine's xbsl/formTree payload, tree
// indexing, labels and icons, drop/insert planning, clipboard-paste arguments, multi-removal
// planning, projection of diagnostics onto node spans, the named-only filter and
// expansion-state remapping after a re-parse. All EDIT logic lives in the engine
// (xbsl/formedits.py); this module only decides WHICH operation with WHICH arguments to
// request - the vscode glue (formStructure.ts) sends xbsl/formEdit and applies the returned
// edits via WorkspaceEdit.

import { iconIdFor } from "./componentIconsCore";

// --- engine payload shapes (formmodel.node_dict / formedits over LSP) ---------------------

export interface FormSpan {
  start: number;
  end: number;
}

export interface FormNodeProperty {
  key: string;
  kind: string; // "scalar" | "binding" | "composite" | "handler"
  valuePreview: string;
}

export interface FormNode {
  id: string;
  kind: "component" | "slot";
  span: FormSpan;
  // The span without the attached leading comments (equals span when there are none);
  // optional - older engines do not send it.
  contentSpan?: FormSpan;
  children: FormNode[];
  // component fields
  type?: string | null;
  typeFull?: string | null;
  name?: string | null; // component: Имя; slot: the slot key
  slot?: string | null; // component: the parent slot name
  properties?: FormNodeProperty[];
  // slot fields
  list?: boolean;
}

// The yaml offset a click/selection should land on: the first CONTENT line of the node -
// not the comment attached above it, which the full span includes (and must include for
// moves and copies). Falls back to the span start with older engines.
export function revealOffset(node: FormNode): number {
  return node.contentSpan?.start ?? node.span.start;
}

// The offset of a node's first content character: past a list-item dash and the whitespace after
// it, to the first property key. The wireframe preview keys its blocks on the mapping start (the
// first property line), so the yaml cursor must land THERE - a cursor left on the "-" line sits
// before the node's data-off, and the preview then highlights the block above it.
export function skipToNodeKey(text: string, offset: number): number {
  let i = offset;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "-" || ch === " " || ch === "\t" || ch === "\r" || ch === "\n") {
      i++;
    } else {
      break;
    }
  }
  return i < text.length ? i : offset;
}

export interface FormTreeResponse {
  available: boolean;
  reason?: string;
  root: FormNode | null;
}

export interface FormNodeAtResponse {
  node?: FormNode | null;
  error?: string;
}

// hook 9: the property keys offered when mass-editing a multi-selection - the union of the keys
// already present on the selected components, restricted to scalar and binding properties (a
// single shared value fits those; composites and handlers do not). Sorted for a stable pick list.
export function massEditKeys(nodes: FormNode[]): string[] {
  const keys = new Set<string>();
  for (const node of nodes) {
    if (node.kind !== "component") {
      continue;
    }
    for (const prop of node.properties ?? []) {
      if (prop.kind === "scalar" || prop.kind === "binding") {
        keys.add(prop.key);
      }
    }
  }
  return [...keys].sort((a, b) => a.localeCompare(b, "ru"));
}

export interface EngineTextEdit {
  start: number;
  end: number;
  newText: string;
}

export interface FormEditResponse {
  edits?: EngineTextEdit[];
  node?: { id: string; span: FormSpan } | null;
  error?: string;
}

// The root node id of the form model (formmodel.ROOT_KEY).
export const ROOT_ID = "Наследует";

// --- indexing -----------------------------------------------------------------------------

export interface FormIndex {
  root: FormNode;
  byId: Map<string, FormNode>;
  parentOf: Map<string, string>;
}

export function indexTree(root: FormNode): FormIndex {
  const byId = new Map<string, FormNode>();
  const parentOf = new Map<string, string>();
  const walk = (node: FormNode, parent: FormNode | undefined): void => {
    byId.set(node.id, node);
    if (parent) {
      parentOf.set(node.id, parent.id);
    }
    for (const child of node.children ?? []) {
      walk(child, node);
    }
  };
  walk(root, undefined);
  return { root, byId, parentOf };
}

export function isDescendantOf(index: FormIndex, nodeId: string, ancestorId: string): boolean {
  let current: string | undefined = nodeId;
  while (current !== undefined) {
    if (current === ancestorId) {
      return true;
    }
    current = index.parentOf.get(current);
  }
  return false;
}

// --- containers ---------------------------------------------------------------------------

// Layout components that accept children even when spelled without any slot key yet. The
// per-component ui schema is the richer source (props with slot: true); this list is the
// offline fallback and the seed for schema verification (uiSchemaClient.wrapContainerTypes).
export const KNOWN_CONTAINER_TYPES: readonly string[] = [
  "Группа",
  "СтандартнаяКарточка",
  "ПроизвольныйШаблонФормы",
  "Страницы",
];

// Containers whose child-bearing slot is not Содержимое.
export const PREFERRED_SLOT_BY_TYPE: Readonly<Record<string, string>> = {
  Страницы: "Страницы",
};

// Container types the wrap operation offers when the ui schema is not generated. The engine
// wraps into a Содержимое slot, so only Содержимое-bearing types qualify.
export const WRAP_FALLBACK_CONTAINERS: readonly string[] = ["Группа", "СтандартнаяКарточка"];

// A component counts as a container when it already holds slot children, its type is a known
// layout type, or the (optional) ui-schema-backed predicate recognizes the type.
export function isContainerNode(node: FormNode, isContainerType?: (type: string) => boolean): boolean {
  if (node.kind !== "component") {
    return false;
  }
  if ((node.children ?? []).some((c) => c.kind === "slot")) {
    return true;
  }
  const type = node.type ?? "";
  if (!type) {
    // An untyped mapping (e.g. a page of Страницы) with no slots yet: not a container.
    return false;
  }
  return KNOWN_CONTAINER_TYPES.includes(type) || !!isContainerType?.(type);
}

// The slot a container accepts new children into: an existing Содержимое slot, else the
// first existing slot, else the type-specific default, else Содержимое (the engine creates
// the missing key).
export function preferredSlotName(node: FormNode): string {
  const slots = (node.children ?? []).filter((c) => c.kind === "slot");
  const content = slots.find((s) => s.name === "Содержимое");
  if (content?.name) {
    return content.name;
  }
  if (slots[0]?.name) {
    return slots[0].name;
  }
  return PREFERRED_SLOT_BY_TYPE[node.type ?? ""] ?? "Содержимое";
}

// --- labels and icons ---------------------------------------------------------------------

const PREVIEW_KEYS = ["Заголовок", "Значение", "Представление", "ПутьКДанным"];

export function nodeLabel(node: FormNode): string {
  if (node.kind === "slot") {
    return node.name ?? "?";
  }
  const type = node.type ?? "";
  const name = node.name ?? "";
  if (type && name) {
    return `${type} ${name}`;
  }
  return type || name || "(...)";
}

// A short dimmed hint next to the label: a slot shows its child count, a component - the
// preview of its most telling property.
export function nodeDescription(node: FormNode): string {
  if (node.kind === "slot") {
    return String((node.children ?? []).length);
  }
  for (const key of PREVIEW_KEYS) {
    const prop = (node.properties ?? []).find((p) => p.key === key);
    if (prop?.valuePreview) {
      return prop.valuePreview;
    }
  }
  return "";
}

// Codicon id of a tree node. The form root and slots keep their own icons; a typed
// component goes through the shared type->icon mapping (componentIconsCore) with the
// package and the schema container flag resolved by the caller - the SAME inputs the
// palette uses, so one type renders with one icon in both panels. Only untyped mappings
// (e.g. a page of Страницы) fall back to the local container/leaf heuristic: they have
// no palette counterpart to stay consistent with.
export function nodeIconId(
  node: FormNode,
  isContainerType?: (type: string) => boolean,
  packageOf?: (type: string) => string | undefined
): string {
  if (node.id === ROOT_ID) {
    return "window";
  }
  if (node.kind === "slot") {
    return "layers";
  }
  const type = node.type ?? "";
  if (type) {
    return iconIdFor(type, packageOf?.(type), isContainerType?.(type) ?? false);
  }
  return isContainerNode(node, isContainerType) ? "layout" : "symbol-field";
}

// --- drop and insert planning -------------------------------------------------------------

// Arguments of the engine's insert/move destination: the parent component, the slot name and
// the optional positioning sibling.
export interface InsertPlan {
  parentId: string;
  slot: string;
  before?: string;
  after?: string;
}

// Where a drop onto the given node lands (docs/DESIGNER.md, the accepted DnD semantics):
// a container takes the payload as its last child, a leaf places it after itself, a slot
// takes it at the slot's end. undefined - the target cannot accept a drop.
export function dropPlan(
  target: FormNode,
  index: FormIndex,
  isContainerType?: (type: string) => boolean
): InsertPlan | undefined {
  if (target.kind === "slot") {
    const parentId = index.parentOf.get(target.id);
    if (!parentId || !target.name) {
      return undefined;
    }
    return { parentId, slot: target.name };
  }
  if (target.id === ROOT_ID) {
    return { parentId: ROOT_ID, slot: preferredSlotName(target) };
  }
  if (isContainerNode(target, isContainerType)) {
    return { parentId: target.id, slot: preferredSlotName(target) };
  }
  return planAfterNode(target, index);
}

// The plan "insert right after this component in its own slot".
function planAfterNode(node: FormNode, index: FormIndex): InsertPlan | undefined {
  const slotId = index.parentOf.get(node.id);
  const slotNode = slotId ? index.byId.get(slotId) : undefined;
  const parentId = slotId ? index.parentOf.get(slotId) : undefined;
  if (!slotNode || !slotNode.name || !parentId) {
    return undefined;
  }
  return { parentId, slot: slotNode.name, after: node.id };
}

// Where a palette insertion goes for the current structure selection: a selected container
// (or slot) takes the component inside, a selected leaf places it after itself, an empty
// selection targets the root content slot.
export function insertPlanForSelection(
  selected: FormNode | undefined,
  index: FormIndex,
  isContainerType?: (type: string) => boolean
): InsertPlan | undefined {
  if (!selected) {
    return { parentId: ROOT_ID, slot: preferredSlotName(index.root) };
  }
  return dropPlan(selected, index, isContainerType);
}

// A node copied out of a "-" list slot arrives as a single-item sequence ("- Тип: ..."),
// and the engine deliberately takes only the MAPPING form (a dash means "several
// components" to it). Unwrap exactly the unambiguous one-item case by line surgery -
// reserialization would lose comments and hand-made formatting. The body is re-aligned
// with the attached comments (which sit at the dash column) so the engine's common-margin
// dedent yields the canonical relative indentation. Anything else - the mapping form,
// several items, non-yaml - travels verbatim: the engine's own messages are the
// user-facing diagnostics. Line logic only, no yaml parse: a dash at the item's own
// column cannot occur inside its body (yaml indents block content deeper than the key).
export function unwrapSingleListItem(fragment: string): string {
  const lines = fragment.split("\n");
  const lead = (line: string): number => line.length - line.trimStart().length;
  let at = -1;
  for (let k = 0; k < lines.length; k++) {
    const t = lines[k].trim();
    if (!t || t.startsWith("#")) {
      continue;
    }
    if (t.startsWith("-")) {
      at = k;
    }
    break;
  }
  if (at < 0) {
    return fragment;
  }
  // [^\n]* instead of .*: the lines of a CRLF clipboard end with \r, which "." skips
  const dash = /^([ ]*)-([ \t]*)([^\n]*)$/.exec(lines[at]);
  if (!dash) {
    return fragment;
  }
  const indent = dash[1].length;
  for (let k = at + 1; k < lines.length; k++) {
    const t = lines[k].trim();
    if (t && lead(lines[k]) <= indent && !t.startsWith("#")) {
      return fragment; // a sibling item or stray content - not a single-item fragment
    }
  }
  const rest = dash[3];
  let contentCol: number;
  if (!rest.trim()) {
    // the dash stood alone on its line; the content column comes from the first body line
    const body = lines.findIndex((l, k) => k > at && !!l.trim());
    if (body < 0) {
      return fragment;
    }
    contentCol = lead(lines[body]);
    lines.splice(at, 1);
  } else {
    contentCol = indent + 1 + dash[2].length;
    lines[at] = " ".repeat(contentCol) + rest;
  }
  const delta = contentCol - indent;
  if (delta > 0 && lines.slice(at).every((l) => !l.trim() || lead(l) >= delta)) {
    for (let k = at; k < lines.length; k++) {
      if (lines[k].trim()) {
        lines[k] = lines[k].slice(delta);
      }
    }
  }
  return lines.join("\n");
}

// Flat xbsl/formEdit arguments of the insert_fragment operation for pasting the clipboard
// yaml into the current structure selection. The target follows the palette-insertion
// rules (insertPlanForSelection): a selected container or slot takes the fragment inside,
// a leaf places it after itself, an empty selection targets the root content slot. The
// only client-side touch is unwrapSingleListItem (the copy-paste circle over list slots);
// otherwise the fragment travels verbatim - attached comments stay part of it, the engine
// validates the yaml itself and re-indents to the destination.
export function pasteFragmentArgs(
  selected: FormNode | undefined,
  index: FormIndex,
  fragment: string,
  isContainerType?: (type: string) => boolean
): Record<string, unknown> | undefined {
  const plan = insertPlanForSelection(selected, index, isContainerType);
  if (!plan) {
    return undefined;
  }
  return {
    parent: plan.parentId,
    slot: plan.slot,
    fragment: unwrapSingleListItem(fragment),
    before: plan.before,
    after: plan.after,
  };
}

// Neighbours of a component inside its slot - the source of Alt+Up/Down move arguments.
export interface SiblingInfo {
  parentId: string; // the parent COMPONENT of the slot
  slot: string;
  prev?: FormNode;
  next?: FormNode;
}

export function siblingInfo(node: FormNode, index: FormIndex): SiblingInfo | undefined {
  const slotId = index.parentOf.get(node.id);
  const slotNode = slotId ? index.byId.get(slotId) : undefined;
  const parentId = slotId ? index.parentOf.get(slotId) : undefined;
  if (!slotNode || slotNode.kind !== "slot" || !slotNode.name || !parentId) {
    return undefined;
  }
  const kids = slotNode.children ?? [];
  const i = kids.findIndex((c) => c.id === node.id);
  if (i < 0) {
    return undefined;
  }
  return {
    parentId,
    slot: slotNode.name,
    prev: i > 0 ? kids[i - 1] : undefined,
    next: i + 1 < kids.length ? kids[i + 1] : undefined,
  };
}

// A move (own nodes dragged) is invalid when the drop target sits inside one of the dragged
// subtrees or the target is unknown.
export function validMoveTarget(index: FormIndex, sourceIds: string[], targetId: string): boolean {
  if (!index.byId.has(targetId)) {
    return false;
  }
  return !sourceIds.some((src) => isDescendantOf(index, targetId, src));
}

// --- multi-removal planning ---------------------------------------------------------------

export interface RemovalPlan {
  // Component ids to remove, descendants of other selected nodes dropped, ordered by span
  // start DESCENDING (later nodes first - earlier ids stay valid between sequential edits).
  ids: string[];
  // true - apply one node at a time (re-requesting the edit after each apply): the engine
  // computes "the last child takes the slot key line" per call, so per-node edits computed
  // against the SAME text would leave an empty slot key behind when the selection covers a
  // whole slot. false - the per-node edits are disjoint and merge into one WorkspaceEdit
  // (a single undo step).
  sequential: boolean;
}

export function planRemoval(selectedIds: string[], index: FormIndex): RemovalPlan {
  const components = selectedIds
    .map((id) => index.byId.get(id))
    .filter((n): n is FormNode => !!n && n.kind === "component" && n.id !== ROOT_ID);
  const idSet = new Set(components.map((n) => n.id));
  const top = components.filter((n) => {
    let parent = index.parentOf.get(n.id);
    while (parent !== undefined) {
      if (idSet.has(parent)) {
        return false;
      }
      parent = index.parentOf.get(parent);
    }
    return true;
  });
  top.sort((a, b) => b.span.start - a.span.start);
  let sequential = false;
  const bySlot = new Map<string, number>();
  for (const n of top) {
    const slotId = index.parentOf.get(n.id);
    if (slotId) {
      bySlot.set(slotId, (bySlot.get(slotId) ?? 0) + 1);
    }
  }
  for (const [slotId, count] of bySlot) {
    const slotNode = index.byId.get(slotId);
    const total = slotNode?.children?.length ?? 0;
    if (total >= 2 && count === total) {
      sequential = true; // the whole slot goes away - only sequential edits stay parseable
    }
  }
  return { ids: top.map((n) => n.id), sequential };
}

// Whether engine edits (possibly gathered from several operations) overlap - overlapping
// batches must fall back to sequential application.
export function editsOverlap(edits: EngineTextEdit[]): boolean {
  const sorted = [...edits].sort((a, b) => a.start - b.start || a.end - b.end);
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i - 1].end > sorted[i].start) {
      return true;
    }
  }
  return false;
}

// --- diagnostics projection ---------------------------------------------------------------

export interface DiagInput {
  start: number; // character offset of the diagnostic range start
  severity: number; // vscode.DiagnosticSeverity: 0 error .. 3 hint
  message: string;
}

export interface NodeDiagBadge {
  count: number;
  severity: number; // the strongest (numerically smallest) severity
  firstMessage: string;
}

// Lays file diagnostics onto tree nodes: each diagnostic belongs to the DEEPEST node whose
// span contains its start offset. Findings outside the form tree (top-level yaml keys) are
// not projected. No ancestor roll-up: a collapsed container shows only its own findings.
export function projectDiagnostics(index: FormIndex, diags: DiagInput[]): Map<string, NodeDiagBadge> {
  const out = new Map<string, NodeDiagBadge>();
  for (const d of diags) {
    if (d.start < index.root.span.start || d.start >= index.root.span.end) {
      continue;
    }
    let node: FormNode = index.root;
    let descended = true;
    while (descended) {
      descended = false;
      for (const child of node.children ?? []) {
        if (d.start >= child.span.start && d.start < child.span.end) {
          node = child;
          descended = true;
          break;
        }
      }
    }
    const badge = out.get(node.id);
    if (!badge) {
      out.set(node.id, { count: 1, severity: d.severity, firstMessage: d.message });
    } else {
      badge.count += 1;
      if (d.severity < badge.severity) {
        badge.severity = d.severity;
      }
    }
  }
  return out;
}

// --- named-only filter --------------------------------------------------------------------

// Ids visible under the "named components only" filter: components with Имя, every ancestor
// of such a component (slots included) and the root.
export function visibleWithNamedFilter(index: FormIndex): Set<string> {
  const visible = new Set<string>();
  const walk = (node: FormNode): boolean => {
    let keep = node.kind === "component" && !!node.name;
    for (const child of node.children ?? []) {
      if (walk(child)) {
        keep = true;
      }
    }
    if (keep) {
      visible.add(node.id);
    }
    return keep;
  };
  walk(index.root);
  visible.add(index.root.id);
  return visible;
}

// --- expansion-state remapping ------------------------------------------------------------

// Node ids are positional and shift on every edit. Expansion state is kept by id and carried
// over best-effort: an id that survived stays; a vanished id of a NAMED component follows the
// (unique) name; a vanished slot id follows its remapped parent component.
export function remapIds(ids: Iterable<string>, oldIndex: FormIndex | undefined, newIndex: FormIndex): Set<string> {
  const out = new Set<string>();
  const uniqueNames = new Map<string, string | null>(); // name -> id, null = ambiguous
  for (const [id, node] of newIndex.byId) {
    if (node.kind === "component" && node.name) {
      uniqueNames.set(node.name, uniqueNames.has(node.name) ? null : id);
    }
  }
  // Where an old component id points now: the same id when the occupant still matches by
  // name, otherwise the (unique) name is followed; a nameless survivor keeps its place.
  const componentTarget = (oldId: string): string | undefined => {
    const oldNode = oldIndex?.byId.get(oldId);
    const samePlace = newIndex.byId.get(oldId);
    if (samePlace && (!oldNode?.name || samePlace.name === oldNode.name)) {
      return oldId;
    }
    if (oldNode?.kind === "component" && oldNode.name) {
      const mapped = uniqueNames.get(oldNode.name);
      if (mapped) {
        return mapped;
      }
    }
    return samePlace ? oldId : undefined;
  };
  for (const id of ids) {
    const oldNode = oldIndex?.byId.get(id);
    if (!oldNode) {
      if (newIndex.byId.has(id)) {
        out.add(id); // no history to compare against - trust the surviving id
      }
      continue;
    }
    if (oldNode.kind === "component") {
      const mapped = componentTarget(id);
      if (mapped) {
        out.add(mapped);
      }
      continue;
    }
    // A slot: re-attach to the remapped parent component by the slot key.
    const parentId = oldIndex?.parentOf.get(id);
    const mappedParent = parentId ? componentTarget(parentId) : undefined;
    const candidate = mappedParent && oldNode.name ? `${mappedParent}/${oldNode.name}` : undefined;
    if (candidate && newIndex.byId.has(candidate)) {
      out.add(candidate);
    } else if (newIndex.byId.has(id)) {
      out.add(id);
    }
  }
  return out;
}

// Drag and drop needs no payload codec any more: both ends of a drag live inside the form
// panel's webview (a structure node onto a node, a data record onto a node), so the dragged
// row id travels in the panel's own script and arrives here as a plain message. The former
// MIME types and their JSON codecs served the native trees, which the panel replaced.
//
// The palette is the exception: it stays a native tree, and a workbench drag cannot hand its
// payload to a webview. It still declares a drag mime (VS Code refuses to start a drag without
// one) but the TYPE travels out of band - the palette tells the panel what is being dragged, and
// the panel matches it with the drop it receives. See formDesigner.notePaletteDrag.
export const PALETTE_MIME = "application/vnd.xbsl.palette-component";
