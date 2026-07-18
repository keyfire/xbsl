// The "Form structure" view (native TreeView in the 1C:Element Designer container): the node
// tree of the active КомпонентИнтерфейса yaml, served by the engine's xbsl/formTree LSP request.
// Two-way selection sync with the editor (cursor - node via xbsl/formNodeAt, click - cursor
// at the node span), keyboard/context-menu operations and drag-and-drop. Every operation is
// ONE xbsl/formEdit request; the returned text edits are applied here via WorkspaceEdit (a
// single undo step) - the extension never computes yaml edits itself (the repository rule).
// Pure logic (planning, projection, remapping) lives in formStructureCore.ts.

import * as vscode from "vscode";
import { buildFieldFragment, DATA_MIME, decodeDataDrag } from "./formDataCore";
import {
  addPreset,
  BLOCK_PRESETS_KEY,
  BlockPreset,
  removePreset,
  sanitizePresets,
} from "./blockPresetsCore";
import { lspActive, lspRequest } from "./lspClient";
import { isReadonlyDoc } from "./readonly";
import {
  decodePaletteDrag,
  decodeStructureDrag,
  dropPlan,
  editsOverlap,
  encodeStructureDrag,
  EngineTextEdit,
  FormEditResponse,
  FormIndex,
  FormNode,
  FormNodeAtResponse,
  FormSpan,
  FormTreeResponse,
  indexTree,
  insertPlanForSelection,
  InsertPlan,
  isContainerNode,
  isDescendantOf,
  massEditKeys,
  nodeDescription,
  nodeIconId,
  nodeLabel,
  NodeDiagBadge,
  PALETTE_MIME,
  pasteFragmentArgs,
  planRemoval,
  projectDiagnostics,
  remapIds,
  revealOffset,
  skipToNodeKey,
  ROOT_ID,
  siblingInfo,
  STRUCTURE_MIME,
  validMoveTarget,
  visibleWithNamedFilter,
} from "./formStructureCore";
import {
  cachedComponentPackage,
  cachedContainerTypes,
  contentContainerTypes,
  warmContainers,
} from "./uiSchemaClient";

const TREE_DEBOUNCE_MS = 300;
const CURSOR_DEBOUNCE_MS = 150;
const DIAG_DEBOUNCE_MS = 200;
const DOUBLE_ACTIVATE_MS = 450;
const FOCUSED_CONTEXT = "xbsl.formStructure.focusedSubtree";
const NAMED_CONTEXT = "xbsl.formStructure.namedOnly";
// Soft hook into the properties panel (formProps.ts): executed only when the command is
// contributed; the structure view carries no hard dependency on it.
const PROPS_HOOK_COMMAND = "xbsl.properties.showForNode";
const IDENTIFIER = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;

// The same shallow check the form preview uses: an interface component with inheritance.
function looksLikeForm(doc: vscode.TextDocument): boolean {
  if (doc.languageId !== "yaml") {
    return false;
  }
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return head.includes("КомпонентИнтерфейса") && doc.getText().includes("Наследует");
}

interface ExpansionMemory {
  expanded: Set<string>;
  collapsed: Set<string>;
}

export interface FormStructureController {
  // Palette insertion into the current structure selection; true when the edit applied.
  insertComponentType(type: string): Promise<boolean>;
  // Called for components inserted through the structure view's own DnD (the palette bumps
  // its usage counters from here).
  setInsertListener(listener: (type: string) => void): void;
  // Repaint tree visuals (e.g. after the ui-schema container set is learned).
  repaint(): void;
  // Data-panel insertion (hook 2): a ready component fragment into the current structure
  // selection; true when the edit applied.
  insertFragment(fragment: string): Promise<boolean>;
}

class FormStructureProvider
  implements vscode.TreeDataProvider<FormNode>, vscode.TreeDragAndDropController<FormNode>
{
  private readonly emitter = new vscode.EventEmitter<FormNode | undefined | void>();
  readonly onDidChangeTreeData = this.emitter.event;

  readonly dropMimeTypes = [STRUCTURE_MIME, PALETTE_MIME, DATA_MIME];
  readonly dragMimeTypes = [STRUCTURE_MIME];

  private view?: vscode.TreeView<FormNode>;
  private target?: vscode.Uri;
  private index?: FormIndex;
  private loadSeq = 0;
  private loadTimer?: NodeJS.Timeout;
  private cursorTimer?: NodeJS.Timeout;
  private diagTimer?: NodeJS.Timeout;
  private suppressCursorSyncUntil = 0;
  private lastActivation?: { id: string; at: number };
  private opInFlight = false;
  private focusRootId?: string;
  private namedOnly = false;
  private visibleIds?: Set<string>;
  private diagBadges = new Map<string, NodeDiagBadge>();
  private readonly memory = new Map<string, ExpansionMemory>();
  private insertListener?: (type: string) => void;

  // hook 8: block presets live in globalState; the provider is the only writer.
  constructor(private readonly presetStore?: vscode.Memento) {}

  attachView(view: vscode.TreeView<FormNode>): void {
    this.view = view;
  }

  setInsertListener(listener: (type: string) => void): void {
    this.insertListener = listener;
  }

  // --- target management ------------------------------------------------------------------

  private uriKey(): string {
    return this.target?.toString() ?? "";
  }

  private targetDocument(): vscode.TextDocument | undefined {
    const key = this.uriKey();
    return key ? vscode.workspace.textDocuments.find((d) => d.uri.toString() === key) : undefined;
  }

  setTarget(uri: vscode.Uri): void {
    if (this.uriKey() === uri.toString()) {
      this.scheduleLoad();
      return;
    }
    this.target = uri;
    this.index = undefined;
    this.setFocusRoot(undefined);
    void this.load();
  }

  matchesTarget(uri: vscode.Uri): boolean {
    return !!this.target && uri.toString() === this.uriKey();
  }

  hasTarget(): boolean {
    return !!this.target;
  }

  scheduleLoad(): void {
    if (this.loadTimer) {
      clearTimeout(this.loadTimer);
    }
    this.loadTimer = setTimeout(() => {
      this.loadTimer = undefined;
      void this.load();
    }, TREE_DEBOUNCE_MS);
  }

  async load(): Promise<void> {
    if (!this.view?.visible) {
      return; // loaded lazily once the view shows up (onDidChangeVisibility)
    }
    const uri = this.target;
    if (!uri) {
      this.index = undefined;
      this.setMessage(vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса) – the structure follows the active editor."));
      this.emitter.fire(undefined);
      return;
    }
    if (!lspActive()) {
      this.index = undefined;
      this.setMessage(vscode.l10n.t('The structure view needs the LSP mode (install the engine with the [lsp] extra: pip install "xbsl[lsp]").'));
      this.emitter.fire(undefined);
      return;
    }
    const seq = ++this.loadSeq;
    const res = await lspRequest<FormTreeResponse>("xbsl/formTree", { uri: uri.toString() });
    if (seq !== this.loadSeq || uri !== this.target) {
      return; // superseded by a newer load or a target switch
    }
    if (!res || !res.available || !res.root) {
      this.index = undefined;
      this.setMessage(res?.reason || vscode.l10n.t("No form tree here – open a form yaml (КомпонентИнтерфейса)."));
      this.emitter.fire(undefined);
      return;
    }
    const fresh = indexTree(res.root);
    const mem = this.memoryFor();
    mem.expanded = remapIds(mem.expanded, this.index, fresh);
    mem.collapsed = remapIds(mem.collapsed, this.index, fresh);
    if (this.focusRootId && !fresh.byId.has(this.focusRootId)) {
      const remapped = remapIds([this.focusRootId], this.index, fresh);
      this.setFocusRoot(remapped.size ? [...remapped][0] : undefined, fresh);
    }
    this.index = fresh;
    this.visibleIds = this.namedOnly ? visibleWithNamedFilter(fresh) : undefined;
    this.setMessage(undefined);
    this.updateDiagnostics();
    this.emitter.fire(undefined);
    // Learn the schema container set and the package map even when the palette was never
    // opened: component icons and drop planning read them synchronously.
    if (!cachedContainerTypes()) {
      warmContainers(() => this.emitter.fire(undefined));
    }
  }

  private setMessage(message: string | undefined): void {
    if (this.view) {
      this.view.message = message;
    }
  }

  private memoryFor(): ExpansionMemory {
    const key = this.uriKey();
    let mem = this.memory.get(key);
    if (!mem) {
      mem = { expanded: new Set(), collapsed: new Set() };
      this.memory.set(key, mem);
    }
    return mem;
  }

  noteExpanded(node: FormNode): void {
    const mem = this.memoryFor();
    mem.expanded.add(node.id);
    mem.collapsed.delete(node.id);
  }

  noteCollapsed(node: FormNode): void {
    const mem = this.memoryFor();
    mem.collapsed.add(node.id);
    mem.expanded.delete(node.id);
  }

  // --- filter and subtree focus -----------------------------------------------------------

  private effectiveRootId(): string {
    return this.focusRootId ?? this.index?.root.id ?? ROOT_ID;
  }

  setFocusRoot(id: string | undefined, index?: FormIndex): void {
    this.focusRootId = id;
    const node = id ? (index ?? this.index)?.byId.get(id) : undefined;
    if (this.view) {
      this.view.description = node ? nodeLabel(node) : undefined;
    }
    void vscode.commands.executeCommand("setContext", FOCUSED_CONTEXT, !!id);
    this.emitter.fire(undefined);
  }

  setNamedOnly(value: boolean): void {
    this.namedOnly = value;
    this.visibleIds = value && this.index ? visibleWithNamedFilter(this.index) : undefined;
    void vscode.commands.executeCommand("setContext", NAMED_CONTEXT, value);
    this.emitter.fire(undefined);
  }

  repaint(): void {
    this.emitter.fire(undefined);
  }

  // --- diagnostics badges (hook 3) --------------------------------------------------------

  scheduleDiagnostics(): void {
    if (this.diagTimer) {
      clearTimeout(this.diagTimer);
    }
    this.diagTimer = setTimeout(() => {
      this.diagTimer = undefined;
      this.updateDiagnostics();
      this.emitter.fire(undefined);
    }, DIAG_DEBOUNCE_MS);
  }

  private updateDiagnostics(): void {
    this.diagBadges = new Map();
    const doc = this.targetDocument();
    if (!this.index || !this.target || !doc) {
      return;
    }
    const diags = vscode.languages.getDiagnostics(this.target).map((d) => ({
      start: doc.offsetAt(d.range.start),
      severity: d.severity,
      message: d.message,
    }));
    this.diagBadges = projectDiagnostics(this.index, diags);
  }

  // --- TreeDataProvider -------------------------------------------------------------------

  private childrenOf(node: FormNode): FormNode[] {
    const kids = node.children ?? [];
    if (!this.visibleIds) {
      return kids;
    }
    return kids.filter((c) => this.visibleIds!.has(c.id));
  }

  getChildren(node?: FormNode): FormNode[] {
    if (!this.index) {
      return [];
    }
    if (!node) {
      const root = this.index.byId.get(this.effectiveRootId()) ?? this.index.root;
      return [root];
    }
    return this.childrenOf(node);
  }

  getParent(node: FormNode): FormNode | undefined {
    if (!this.index || node.id === this.effectiveRootId()) {
      return undefined;
    }
    const parentId = this.index.parentOf.get(node.id);
    return parentId ? this.index.byId.get(parentId) : undefined;
  }

  getTreeItem(node: FormNode): vscode.TreeItem {
    const kids = this.childrenOf(node);
    const mem = this.memoryFor();
    const defaultExpanded = node.kind === "slot" || node.id === this.effectiveRootId();
    const expanded = mem.collapsed.has(node.id) ? false : mem.expanded.has(node.id) || defaultExpanded;
    const state = !kids.length
      ? vscode.TreeItemCollapsibleState.None
      : expanded
        ? vscode.TreeItemCollapsibleState.Expanded
        : vscode.TreeItemCollapsibleState.Collapsed;
    const item = new vscode.TreeItem(nodeLabel(node), state);
    item.id = `${this.uriKey()}#${node.id}`;
    const badge = this.diagBadges.get(node.id);
    const base = nodeDescription(node);
    item.description = badge ? `${base ? base + " · " : ""}(${badge.count})` : base || undefined;
    const isContainerType = (type: string) => cachedContainerTypes()?.has(type) ?? false;
    if (badge) {
      const icon = badge.severity === 0 ? "error" : badge.severity === 1 ? "warning" : "info";
      const color =
        badge.severity === 0
          ? new vscode.ThemeColor("list.errorForeground")
          : badge.severity === 1
            ? new vscode.ThemeColor("list.warningForeground")
            : new vscode.ThemeColor("charts.blue");
      item.iconPath = new vscode.ThemeIcon(icon, color);
    } else {
      item.iconPath = new vscode.ThemeIcon(nodeIconId(node, isContainerType, cachedComponentPackage));
    }
    const tooltipParts = [node.kind === "component" ? node.typeFull || node.type || "" : vscode.l10n.t("Slot {0}", node.name ?? "")];
    if (badge) {
      tooltipParts.push(badge.firstMessage);
    }
    item.tooltip = tooltipParts.filter(Boolean).join("\n\n") || undefined;
    if (node.id === ROOT_ID) {
      item.contextValue = "formRoot";
    } else if (node.kind === "slot") {
      item.contextValue = "formSlot";
    } else {
      item.contextValue = isContainerNode(node, isContainerType) ? "formNode formContainer" : "formNode";
    }
    item.command = { command: "xbsl.formStructure.select", title: "", arguments: [node] };
    return item;
  }

  // --- selection sync ---------------------------------------------------------------------

  scheduleCursorSync(offset: number): void {
    if (Date.now() < this.suppressCursorSyncUntil || !this.view?.visible) {
      return;
    }
    if (this.cursorTimer) {
      clearTimeout(this.cursorTimer);
    }
    this.cursorTimer = setTimeout(() => {
      this.cursorTimer = undefined;
      void this.syncCursor(offset);
    }, CURSOR_DEBOUNCE_MS);
  }

  private async syncCursor(offset: number): Promise<void> {
    if (!this.target || !this.index || !this.view?.visible) {
      return;
    }
    const res = await lspRequest<FormNodeAtResponse>("xbsl/formNodeAt", {
      uri: this.target.toString(),
      offset,
    });
    const id = res?.node?.id;
    if (!id) {
      return;
    }
    const node = this.index.byId.get(id);
    if (!node) {
      this.scheduleLoad(); // the tree is stale relative to the buffer
      return;
    }
    if (this.visibleIds && !this.visibleIds.has(id)) {
      return; // hidden by the named-only filter
    }
    if (this.focusRootId && !isDescendantOf(this.index, id, this.focusRootId)) {
      return; // outside the focused subtree
    }
    try {
      await this.view.reveal(node, { select: true, focus: false });
    } catch {
      // reveal may refuse while the tree rebuilds - not critical
    }
  }

  // Click on a node: cursor onto the node's yaml without stealing focus; a second activation
  // in quick succession (double click / double Enter) moves focus to the editor. The cursor
  // lands on the first content line, not on a comment attached above the node. The properties
  // panel is filled DIRECTLY through its command - the programmatic selection change above
  // is not a reliable channel for it (events are debounced and may be gated).
  async select(node: FormNode): Promise<void> {
    const now = Date.now();
    const double = !!this.lastActivation && this.lastActivation.id === node.id && now - this.lastActivation.at < DOUBLE_ACTIVATE_MS;
    this.lastActivation = { id: node.id, at: now };
    // Land the cursor on the node's first property line (not its list-item dash), so the preview
    // highlights this block and not the one above it (the dash sits before the block's data-off).
    let offset = revealOffset(node);
    if (this.target) {
      try {
        const doc = await vscode.workspace.openTextDocument(this.target);
        offset = skipToNodeKey(doc.getText(), offset);
      } catch {
        // keep the raw offset if the document cannot be opened
      }
    }
    await this.revealInEditor(offset, !double);
    void this.notifyPropsPanel(offset);
  }

  async revealInEditor(offset: number, preserveFocus: boolean): Promise<void> {
    if (!this.target) {
      return;
    }
    this.suppressCursorSyncUntil = Date.now() + 300;
    const doc = await vscode.workspace.openTextDocument(this.target);
    const pos = doc.positionAt(offset);
    const existing = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === this.uriKey());
    const editor = await vscode.window.showTextDocument(doc, {
      viewColumn: existing?.viewColumn ?? vscode.ViewColumn.One,
      preserveFocus,
      preview: false,
    });
    editor.selection = new vscode.Selection(pos, pos);
    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }

  // --- operations (thin wrappers over xbsl/formEdit) --------------------------------------

  selectedNodes(contextNode?: FormNode, multi?: FormNode[]): FormNode[] {
    if (multi?.length) {
      return multi;
    }
    if (contextNode) {
      return [contextNode];
    }
    return [...(this.view?.selection ?? [])];
  }

  private async requestEdit(op: string, args: Record<string, unknown>): Promise<FormEditResponse | undefined> {
    if (!this.target) {
      return undefined;
    }
    if (!lspActive()) {
      void vscode.window.showWarningMessage(
        vscode.l10n.t('XBSL: form operations need the LSP mode (pip install "xbsl[lsp]").')
      );
      return undefined;
    }
    // The operation arguments ride FLAT in params: over the real pygls channel a nested
    // args object arrives as a namedtuple, not a dict, which older engines could not read.
    const res = await lspRequest<FormEditResponse>("xbsl/formEdit", {
      uri: this.target.toString(),
      op,
      ...args,
    });
    if (!res) {
      void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the engine did not answer the form edit request."));
      return undefined;
    }
    if (res.error) {
      void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", res.error));
      return undefined;
    }
    return res;
  }

  private async applyEdits(doc: vscode.TextDocument, edits: EngineTextEdit[]): Promise<boolean> {
    // hook 11: a read-only form (a library .xlib, a git/diff view) is inspected, not edited. The
    // WorkspaceEdit below would fail anyway; refusing here gives a clear message instead.
    if (await isReadonlyDoc(doc.uri)) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: this form is read-only – editing is disabled.")
      );
      return false;
    }
    const we = new vscode.WorkspaceEdit();
    for (const e of edits) {
      we.replace(doc.uri, new vscode.Range(doc.positionAt(e.start), doc.positionAt(e.end)), e.newText);
    }
    return vscode.workspace.applyEdit(we);
  }

  // One operation end to end: request the edits, apply them as a single WorkspaceEdit (one
  // undo step), reload the tree and reveal the resulting node.
  async performOp(op: string, args: Record<string, unknown>): Promise<{ id: string; span: FormSpan } | undefined> {
    if (this.opInFlight) {
      return undefined;
    }
    this.opInFlight = true;
    try {
      const doc = this.targetDocument();
      if (!doc) {
        return undefined;
      }
      const version = doc.version;
      const res = await this.requestEdit(op, args);
      if (!res) {
        return undefined;
      }
      if (doc.version !== version) {
        void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the buffer changed while the edit was being computed – try again."));
        return undefined;
      }
      if (!(await this.applyEdits(doc, res.edits ?? []))) {
        return undefined;
      }
      await this.load();
      if (res.node) {
        await this.revealNodeById(res.node.id);
        await this.revealInEditor(res.node.span.start, true);
      }
      return res.node ?? undefined;
    } finally {
      this.opInFlight = false;
    }
  }

  private async revealNodeById(id: string): Promise<void> {
    const node = this.index?.byId.get(id);
    if (node && this.view?.visible) {
      try {
        await this.view.reveal(node, { select: true, focus: false });
      } catch {
        // not critical
      }
    }
  }

  async moveNode(node: FormNode, direction: "up" | "down"): Promise<void> {
    if (!this.index || node.kind !== "component" || node.id === ROOT_ID) {
      return;
    }
    const info = siblingInfo(node, this.index);
    const sibling = direction === "up" ? info?.prev : info?.next;
    if (!info || !sibling) {
      return; // already at the edge of its slot
    }
    const position = direction === "up" ? { before: sibling.id } : { after: sibling.id };
    await this.performOp("move", { node: node.id, newParent: info.parentId, slot: info.slot, ...position });
  }

  // Multi-delete: disjoint per-node removals merge into ONE WorkspaceEdit (a single undo
  // step); when the selection empties a whole slot the removals are applied one by one - the
  // engine folds "the last child takes the slot key" only per call (see planRemoval).
  async deleteNodes(nodes: FormNode[]): Promise<void> {
    if (!this.index) {
      return;
    }
    const plan = planRemoval(nodes.map((n) => n.id), this.index);
    if (!plan.ids.length) {
      return;
    }
    if (plan.ids.length === 1) {
      await this.performOp("remove", { node: plan.ids[0] });
      return;
    }
    if (this.opInFlight) {
      return;
    }
    this.opInFlight = true;
    try {
      if (!plan.sequential) {
        const doc = this.targetDocument();
        if (!doc) {
          return;
        }
        const version = doc.version;
        const all: EngineTextEdit[] = [];
        let ok = true;
        for (const id of plan.ids) {
          const res = await this.requestEdit("remove", { node: id });
          if (!res || doc.version !== version) {
            ok = false;
            break;
          }
          all.push(...(res.edits ?? []));
        }
        if (ok && !editsOverlap(all)) {
          if (await this.applyEdits(doc, all)) {
            await this.load();
          }
          return;
        }
        // fall through to the sequential path on any surprise
      }
      for (const id of plan.ids) {
        const doc = this.targetDocument();
        if (!doc) {
          return;
        }
        const res = await this.requestEdit("remove", { node: id });
        if (!res || !(await this.applyEdits(doc, res.edits ?? []))) {
          break;
        }
      }
      await this.load();
    } finally {
      this.opInFlight = false;
    }
  }

  async renameNode(node: FormNode): Promise<void> {
    if (node.kind !== "component" || node.id === ROOT_ID) {
      return;
    }
    const value = await vscode.window.showInputBox({
      prompt: vscode.l10n.t("Component name (empty removes Имя)"),
      value: node.name ?? "",
      validateInput: (v) =>
        !v.trim() || IDENTIFIER.test(v.trim())
          ? undefined
          : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
    });
    if (value === undefined) {
      return;
    }
    const trimmed = value.trim();
    if (!trimmed && !node.name) {
      return; // nothing to remove
    }
    await this.performOp("rename", { node: node.id, newName: trimmed });
  }

  async wrapNode(node: FormNode): Promise<void> {
    if (node.kind !== "component" || node.id === ROOT_ID) {
      return;
    }
    const candidates = await contentContainerTypes();
    const pick = await vscode.window.showQuickPick(candidates, {
      placeHolder: vscode.l10n.t("Container type to wrap into (a Содержимое slot)"),
    });
    if (!pick) {
      return;
    }
    await this.performOp("wrap", { node: node.id, container: pick });
  }

  // The node's yaml subtree as text, re-read from the live buffer (the tree may lag behind
  // typing). The block includes the node's children - its span runs to the end of the value
  // block. The engine's insert_fragment normalizes the indentation on paste, so this raw slice
  // is a ready fragment. Shared by copyNode and the block presets (hook 8).
  private async nodeFragment(node: FormNode): Promise<string | undefined> {
    if (!this.target) {
      return undefined;
    }
    const res = await lspRequest<FormNodeAtResponse>("xbsl/formNodeAt", {
      uri: this.target.toString(),
      offset: node.span.start,
    });
    const span = res?.node?.id === node.id && res.node?.span ? res.node.span : node.span;
    const doc = await vscode.workspace.openTextDocument(this.target);
    return doc.getText(new vscode.Range(doc.positionAt(span.start), doc.positionAt(span.end)));
  }

  async copyNode(node: FormNode): Promise<void> {
    const text = await this.nodeFragment(node);
    if (text === undefined) {
      return;
    }
    await vscode.env.clipboard.writeText(text);
    vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL: the node yaml is copied to the clipboard."), 2000);
  }

  // --- block presets (hook 8) -------------------------------------------------------------

  private loadPresets(): BlockPreset[] {
    return sanitizePresets(this.presetStore?.get(BLOCK_PRESETS_KEY));
  }

  private async storePresets(list: BlockPreset[]): Promise<void> {
    await this.presetStore?.update(BLOCK_PRESETS_KEY, list);
  }

  // Save a component subtree under a name: extract its fragment, ask for a name (defaulting to
  // the node's Имя or type), and add it to the store. A re-save under an existing name replaces
  // that preset.
  async saveAsPreset(node: FormNode): Promise<void> {
    if (!this.presetStore || node.kind !== "component" || node.id === ROOT_ID) {
      return;
    }
    const fragment = await this.nodeFragment(node);
    if (fragment === undefined || !fragment.trim()) {
      return;
    }
    const suggested = (node.name || node.type || "").trim();
    const name = await vscode.window.showInputBox({
      title: vscode.l10n.t("Save block preset"),
      prompt: vscode.l10n.t("A name for the block preset – reused across forms and sessions."),
      value: suggested,
      validateInput: (v) => (v.trim() ? undefined : vscode.l10n.t("Enter a name.")),
    });
    if (name === undefined || !name.trim()) {
      return;
    }
    const existed = this.loadPresets().some((p) => p.name === name.trim());
    const updated = addPreset(this.loadPresets(), {
      name,
      fragment,
      type: node.type ?? undefined,
    });
    await this.storePresets(updated);
    vscode.window.setStatusBarMessage(
      existed
        ? vscode.l10n.t('XBSL: block preset "{0}" updated.', name.trim())
        : vscode.l10n.t('XBSL: block preset "{0}" saved.', name.trim()),
      2500
    );
  }

  // Insert a saved preset into the current structure selection (the palette-insertion target
  // rules), the same path as pasteFromClipboard but with the fragment from the pick.
  async insertPreset(node?: FormNode): Promise<void> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – a block preset inserts into the structure selection.")
      );
      return;
    }
    const presets = this.loadPresets();
    if (!presets.length) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: no block presets yet – save one from a component's context menu (Save as block preset).")
      );
      return;
    }
    const pick = await vscode.window.showQuickPick(
      presets.map((p) => ({ label: p.name, description: p.type, preset: p })),
      { title: vscode.l10n.t("Insert block preset"), placeHolder: vscode.l10n.t("Pick a block preset") }
    );
    if (!pick) {
      return;
    }
    const selected = this.selectedNodes(node)[0];
    const args = pasteFragmentArgs(selected, this.index, pick.preset.fragment, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!args) {
      return;
    }
    const inserted = await this.performOp("insert_fragment", args);
    if (inserted) {
      void this.notifyPropsPanel(inserted.span.start);
    }
  }

  // Delete saved presets (a multi-pick with a confirmation-free removal - presets are cheap to
  // recreate and this is the only way to prune them).
  async managePresets(): Promise<void> {
    if (!this.presetStore) {
      return;
    }
    const presets = this.loadPresets();
    if (!presets.length) {
      void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: no block presets to manage."));
      return;
    }
    const picks = await vscode.window.showQuickPick(
      presets.map((p) => ({ label: p.name, description: p.type, name: p.name })),
      {
        title: vscode.l10n.t("Delete block presets"),
        placeHolder: vscode.l10n.t("Pick presets to delete"),
        canPickMany: true,
      }
    );
    if (!picks || !picks.length) {
      return;
    }
    let list = this.loadPresets();
    for (const p of picks) {
      list = removePreset(list, p.name);
    }
    await this.storePresets(list);
    vscode.window.setStatusBarMessage(vscode.l10n.t("XBSL: {0} block preset(s) deleted.", picks.length), 2500);
  }

  // --- multi-select mass property edit (hook 9) -------------------------------------------

  // Set (or clear) one property on every selected component at once. The key is picked from the
  // union of keys already present on the selection, or typed for a new one; an empty value clears
  // the property where present. Each write is one engine set_property/reset_property applied in
  // sequence (node ids stay valid - a property edit does not restructure the tree), so the buffer
  // stays in sync between writes exactly as a single edit would.
  async editSelected(node?: FormNode, multi?: FormNode[]): Promise<void> {
    if (!this.target || !this.index) {
      return;
    }
    const selected = this.selectedNodes(node, multi).filter(
      (n) => n.kind === "component" && n.id !== ROOT_ID
    );
    if (selected.length < 2) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: select two or more components in the structure to edit them together.")
      );
      return;
    }
    const key = await this.pickMassEditKey(selected);
    if (!key) {
      return;
    }
    const value = await vscode.window.showInputBox({
      title: vscode.l10n.t("Edit {0} on {1} components", key, selected.length),
      prompt: vscode.l10n.t("The new value (a literal or a =binding) – empty clears the property where it is set."),
    });
    if (value === undefined) {
      return; // cancelled (an empty string is a deliberate clear)
    }
    const clearing = value.trim() === "";
    // Clearing only touches nodes that actually carry the key (reset on a missing property would
    // just error); setting applies to all. Ids are captured now - stable across property writes.
    const targets = clearing
      ? selected.filter((n) => (n.properties ?? []).some((p) => p.key === key))
      : selected;
    let ok = 0;
    for (const target of targets) {
      const res = clearing
        ? await this.performOp("reset_property", { node: target.id, key })
        : await this.performOp("set_property", { node: target.id, key, value });
      if (res) {
        ok++;
      }
    }
    vscode.window.setStatusBarMessage(
      clearing
        ? vscode.l10n.t("XBSL: {0} cleared on {1} component(s).", key, ok)
        : vscode.l10n.t("XBSL: {0} set on {1} component(s).", key, ok),
      2500
    );
  }

  // The property to mass-edit: a pick from the union of the selection's existing scalar/binding
  // keys, or a typed identifier for a key none of them has yet.
  private async pickMassEditKey(selected: FormNode[]): Promise<string | undefined> {
    const OTHER = " other";
    const keys = massEditKeys(selected);
    let chosen: string | undefined;
    if (keys.length) {
      const items: (vscode.QuickPickItem & { value?: string })[] = keys.map((k) => ({ label: k, value: k }));
      items.push({ label: vscode.l10n.t("$(edit) Other property..."), value: OTHER });
      const pick = await vscode.window.showQuickPick(items, {
        title: vscode.l10n.t("Property to edit on the selection"),
        placeHolder: vscode.l10n.t("Pick a property (or add another)"),
      });
      if (!pick) {
        return undefined;
      }
      chosen = pick.value;
    } else {
      chosen = OTHER;
    }
    if (chosen !== OTHER) {
      return chosen;
    }
    const typed = await vscode.window.showInputBox({
      title: vscode.l10n.t("Property name"),
      prompt: vscode.l10n.t("The name of the property to set on the selected components."),
      validateInput: (v) =>
        /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/.test(v.trim())
          ? undefined
          : vscode.l10n.t("A property name is an identifier (letters, digits, underscore)."),
    });
    return typed?.trim() || undefined;
  }

  // Paste the clipboard yaml as a component (the counterpart of copyYaml; works across
  // forms and projects). The target follows the palette-insertion rules; the engine
  // validates the fragment (one mapping with a Тип key) and its message is shown as is.
  async pasteFromClipboard(node?: FormNode): Promise<void> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the clipboard yaml is pasted into the structure selection.")
      );
      return;
    }
    const fragment = await vscode.env.clipboard.readText();
    const selected = this.selectedNodes(node)[0];
    const args = pasteFragmentArgs(selected, this.index, fragment, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!args) {
      return;
    }
    const inserted = await this.performOp("insert_fragment", args);
    if (inserted) {
      void this.notifyPropsPanel(inserted.span.start);
    }
  }

  // --- palette insertion ------------------------------------------------------------------

  async insertComponentType(type: string): Promise<boolean> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the palette inserts into the structure selection.")
      );
      return false;
    }
    const selected = this.view?.selection[0];
    const plan = insertPlanForSelection(selected, this.index, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!plan) {
      return false;
    }
    const node = await this.insertByPlan(plan, type);
    return !!node;
  }

  private async insertByPlan(plan: InsertPlan, type: string): Promise<{ id: string; span: FormSpan } | undefined> {
    const node = await this.performOp("insert", {
      parent: plan.parentId,
      slot: plan.slot,
      type,
      before: plan.before,
      after: plan.after,
    });
    if (node) {
      void this.notifyPropsPanel(node.span.start);
    }
    return node;
  }

  private async notifyPropsPanel(offset: number): Promise<void> {
    if (!this.target) {
      return;
    }
    const commands = await vscode.commands.getCommands(true);
    if (commands.includes(PROPS_HOOK_COMMAND)) {
      // The properties panel takes positional (uri, offset) - see formProps.ts.
      void vscode.commands.executeCommand(PROPS_HOOK_COMMAND, this.target.toString(), offset);
    }
  }

  // --- data-panel insertion (hook 2) --------------------------------------------------------

  // A ready yaml fragment (an input component built by the data panel) into the current
  // structure selection - the same target semantics as the palette insertion.
  async insertFragment(fragment: string): Promise<boolean> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the field is inserted into the structure selection.")
      );
      return false;
    }
    const selected = this.view?.selection[0];
    const plan = insertPlanForSelection(selected, this.index, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!plan) {
      return false;
    }
    const node = await this.insertFragmentByPlan(plan, fragment);
    return !!node;
  }

  private async insertFragmentByPlan(plan: InsertPlan, fragment: string): Promise<{ id: string; span: FormSpan } | undefined> {
    const node = await this.performOp("insert_fragment", {
      parent: plan.parentId,
      slot: plan.slot,
      fragment,
      before: plan.before,
      after: plan.after,
    });
    if (node) {
      void this.notifyPropsPanel(node.span.start);
    }
    return node;
  }

  // --- drag and drop ----------------------------------------------------------------------

  handleDrag(source: readonly FormNode[], dataTransfer: vscode.DataTransfer): void {
    const ids = source
      .filter((n) => n.kind === "component" && n.id !== ROOT_ID)
      .sort((a, b) => a.span.start - b.span.start)
      .map((n) => n.id);
    if (!ids.length || !this.target) {
      return; // nothing draggable in the selection - the transfer stays empty
    }
    dataTransfer.set(STRUCTURE_MIME, new vscode.DataTransferItem(encodeStructureDrag({ uri: this.uriKey(), ids })));
  }

  async handleDrop(target: FormNode | undefined, dataTransfer: vscode.DataTransfer): Promise<void> {
    if (!this.index || !this.target) {
      return;
    }
    const isContainerType = (t: string) => cachedContainerTypes()?.has(t) ?? false;
    const dropTarget = target ?? this.index.root;
    const plan = dropPlan(dropTarget, this.index, isContainerType);
    if (!plan) {
      return;
    }
    const paletteRaw = dataTransfer.get(PALETTE_MIME);
    if (paletteRaw) {
      const payload = decodePaletteDrag(await paletteRaw.asString());
      if (!payload) {
        return;
      }
      const node = await this.insertByPlan(plan, payload.componentType);
      if (node) {
        this.insertListener?.(payload.componentType);
      }
      return;
    }
    // A record dragged from the data panel (hook 2): the drop point takes an input
    // component with the binding, built as one ready fragment.
    const dataRaw = dataTransfer.get(DATA_MIME);
    if (dataRaw) {
      const payload = decodeDataDrag(await dataRaw.asString());
      if (!payload) {
        return;
      }
      await this.insertFragmentByPlan(plan, buildFieldFragment(payload));
      return;
    }
    const structureRaw = dataTransfer.get(STRUCTURE_MIME);
    if (!structureRaw) {
      return;
    }
    const payload = decodeStructureDrag(await structureRaw.asString());
    if (!payload || payload.uri !== this.uriKey()) {
      return; // a drag from another document or not our payload
    }
    if (!validMoveTarget(this.index, payload.ids, dropTarget.id)) {
      return; // dropping into a dragged subtree
    }
    // The engine moves one node per operation; ids shift after every edit, so the drop takes
    // the first (top-most) dragged node - precise multi-ordering is keyboard-first (Alt+Up/Down).
    const nodeId = payload.ids[0];
    if (!nodeId || nodeId === plan.before || nodeId === plan.after || nodeId === plan.parentId) {
      return; // positioning a node relative to itself is a no-op
    }
    await this.performOp("move", {
      node: nodeId,
      newParent: plan.parentId,
      slot: plan.slot,
      before: plan.before,
      after: plan.after,
    });
  }
}

export function registerFormStructure(context: vscode.ExtensionContext): FormStructureController {
  const provider = new FormStructureProvider(context.globalState);
  const view = vscode.window.createTreeView<FormNode>("xbslFormStructure", {
    treeDataProvider: provider,
    dragAndDropController: provider,
    canSelectMany: true,
    showCollapseAll: true,
  });
  provider.attachView(view);
  void vscode.commands.executeCommand("setContext", FOCUSED_CONTEXT, false);
  void vscode.commands.executeCommand("setContext", NAMED_CONTEXT, false);

  const followEditor = (editor: vscode.TextEditor | undefined): void => {
    if (editor && editor.document.uri.scheme === "file" && looksLikeForm(editor.document)) {
      provider.setTarget(editor.document.uri);
    } else if (!provider.hasTarget()) {
      void provider.load(); // shows the "open a form yaml" hint
    }
  };

  context.subscriptions.push(
    view,
    view.onDidExpandElement((e) => provider.noteExpanded(e.element)),
    view.onDidCollapseElement((e) => provider.noteCollapsed(e.element)),
    view.onDidChangeVisibility((e) => {
      if (e.visible) {
        followEditor(vscode.window.activeTextEditor);
        void provider.load();
      }
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => followEditor(editor)),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (provider.matchesTarget(e.document.uri)) {
        provider.scheduleLoad();
      }
    }),
    vscode.languages.onDidChangeDiagnostics((e) => {
      if (e.uris.some((u) => provider.matchesTarget(u))) {
        provider.scheduleDiagnostics();
      }
    }),
    vscode.window.onDidChangeTextEditorSelection((e) => {
      if (e.textEditor.document.uri.scheme === "file" && provider.matchesTarget(e.textEditor.document.uri)) {
        provider.scheduleCursorSync(e.textEditor.document.offsetAt(e.selections[0].active));
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.refresh", () => void provider.load()),
    vscode.commands.registerCommand("xbsl.formStructure.select", (node: FormNode) => void provider.select(node)),
    vscode.commands.registerCommand("xbsl.formStructure.openInEditor", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.revealInEditor(revealOffset(target), false);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.moveUp", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.moveNode(target, "up");
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.moveDown", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.moveNode(target, "down");
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.delete", (node?: FormNode, multi?: FormNode[]) => {
      void provider.deleteNodes(provider.selectedNodes(node, multi));
    }),
    vscode.commands.registerCommand("xbsl.formStructure.rename", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.renameNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.duplicate", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void provider.performOp("duplicate", { node: target.id });
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.wrap", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.wrapNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.unwrap", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void provider.performOp("unwrap", { node: target.id });
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.copyYaml", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target) {
        void provider.copyNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.pasteYaml", (node?: FormNode) => {
      void provider.pasteFromClipboard(node);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.savePreset", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void provider.saveAsPreset(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.insertPreset", (node?: FormNode) => {
      void provider.insertPreset(node);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.managePresets", () => void provider.managePresets()),
    vscode.commands.registerCommand("xbsl.formStructure.editSelected", (node?: FormNode, multi?: FormNode[]) => {
      void provider.editSelected(node, multi);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.focusSubtree", (node?: FormNode) => {
      const target = provider.selectedNodes(node)[0];
      if (target && target.kind === "component") {
        provider.setFocusRoot(target.id);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.resetFocus", () => provider.setFocusRoot(undefined)),
    vscode.commands.registerCommand("xbsl.formStructure.filterNamed", () => provider.setNamedOnly(true)),
    vscode.commands.registerCommand("xbsl.formStructure.filterAll", () => provider.setNamedOnly(false))
  );

  followEditor(vscode.window.activeTextEditor);

  return {
    insertComponentType: (type: string) => provider.insertComponentType(type),
    setInsertListener: (listener) => provider.setInsertListener(listener),
    repaint: () => provider.repaint(),
    insertFragment: (fragment: string) => provider.insertFragment(fragment),
  };
}
