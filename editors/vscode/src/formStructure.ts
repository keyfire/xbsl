// The form STRUCTURE model: the node tree of a КомпонентИнтерфейса yaml, served by the
// engine's xbsl/formTree LSP request, plus every operation over it. Since the designer's
// recomposition the tree is painted by the form panel (formDesigner.ts) inside its webview,
// so this module owns no view of its own: it keeps the model (index, expansion memory,
// filter, focused subtree, diagnostic badges, the panel's selection mirror), hands the panel
// a flat snapshot (formDesignerCore.flattenStructure) and performs the operations. The panel
// drives the lifecycle - it follows the active editor and tells the model when to load.
//
// Every operation is ONE xbsl/formEdit request; the returned text edits are applied here via
// WorkspaceEdit (a single undo step) - the extension never computes yaml edits itself (the
// repository rule). Pure logic (planning, projection, remapping) lives in formStructureCore.ts.

import * as vscode from "vscode";
import { buildFieldFragment, DataDragPayload } from "./formDataCore";
import {
  addPreset,
  BLOCK_PRESETS_KEY,
  BlockPreset,
  removePreset,
  sanitizePresets,
} from "./blockPresetsCore";
import { flattenStructure, StructureRow } from "./formDesignerCore";
import { lspActive, lspRequest } from "./lspClient";
import { isReadonlyDoc } from "./readonly";
import { revealContent } from "./reveal";
import {
  dropPlan,
  editsOverlap,
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
  nodeLabel,
  NodeDiagBadge,
  pasteFragmentArgs,
  planRemoval,
  projectDiagnostics,
  remapIds,
  revealOffset,
  skipToNodeKey,
  ROOT_ID,
  siblingInfo,
  validMoveTarget,
  visibleWithNamedFilter,
} from "./formStructureCore";
import {
  cachedComponentPackage,
  cachedContainerTypes,
  contentContainerTypes,
  warmContainers,
} from "./uiSchemaClient";

const FOCUSED_CONTEXT = "xbsl.formStructure.focusedSubtree";
const NAMED_CONTEXT = "xbsl.formStructure.namedOnly";
// Soft hook into the properties panel (formProps.ts): executed only when the command is
// contributed; the structure model carries no hard dependency on it.
const PROPS_HOOK_COMMAND = "xbsl.properties.showForNode";
const IDENTIFIER = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;

// What the panel needs to paint the structure pane: the rows plus the pane-level state.
export interface StructureSnapshot {
  available: boolean;
  //: The hint shown instead of rows (no form open, no LSP, unparseable yaml).
  message?: string;
  rows: StructureRow[];
  selection: string[];
  //: The label of the focused subtree, when the pane is narrowed to one branch.
  focusLabel?: string;
  namedOnly: boolean;
  readonly: boolean;
}

// The panel side of the structure pane. formDesigner.ts implements it; without a panel the
// model is idle (it neither loads nor paints).
export interface StructureHost {
  showStructure(snapshot: StructureSnapshot): void;
  //: Scroll the row into view and select it (a programmatic reveal - cursor sync, an
  //: operation result), without moving the focus into the panel.
  revealStructure(id: string): void;
}

interface ExpansionMemory {
  expanded: Set<string>;
  collapsed: Set<string>;
}

export interface FormStructureController {
  //: The form panel registers itself here on creation and clears it on dispose.
  setHost(host: StructureHost | undefined): void;
  setTarget(uri: vscode.Uri): void;
  matchesTarget(uri: vscode.Uri): boolean;
  hasTarget(): boolean;
  load(): Promise<void>;
  scheduleDiagnostics(): void;
  //: Selection mirrored from the panel (the panel owns the pointer/keyboard selection).
  setSelection(ids: string[]): void;
  toggleRow(id: string, expanded: boolean): void;
  //: A row was activated in the panel: cursor onto its yaml (focus stays in the panel
  //: unless focusEditor) and the properties panel filled.
  activate(id: string, focusEditor: boolean): Promise<void>;
  //: The yaml offset a row points at - the panel highlights the matching frame block.
  offsetOf(id: string): Promise<number | undefined>;
  //: The node under a yaml offset (xbsl/formNodeAt) - the reverse sync.
  nodeIdAt(offset: number): Promise<string | undefined>;
  //: A drop inside the structure pane: dragged rows, or a record from the data pane.
  dropNodes(sourceIds: string[], targetId: string): Promise<void>;
  dropRecord(payload: DataDragPayload, targetId: string): Promise<void>;
  //: Palette insertion into the current structure selection; true when the edit applied.
  insertComponentType(type: string): Promise<boolean>;
  //: Repaint the pane (e.g. after the ui-schema container set is learned).
  repaint(): void;
  //: Data-panel insertion: a ready component fragment into the current structure selection.
  insertFragment(fragment: string): Promise<boolean>;
}

class FormStructureModel {
  private host?: StructureHost;
  private target?: vscode.Uri;
  private index?: FormIndex;
  private message?: string;
  private readonlyForm = false;
  private loadSeq = 0;
  private diagTimer?: NodeJS.Timeout;
  private suppressCursorSyncUntil = 0;
  private opInFlight = false;
  private focusRootId?: string;
  private namedOnly = false;
  private visibleIds?: Set<string>;
  private selection: string[] = [];
  private diagBadges = new Map<string, NodeDiagBadge>();
  private readonly memory = new Map<string, ExpansionMemory>();

  // hook 8: block presets live in globalState; the model is the only writer.
  constructor(private readonly presetStore?: vscode.Memento) {}

  setHost(host: StructureHost | undefined): void {
    this.host = host;
    if (host) {
      this.publish();
    }
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
      return;
    }
    this.target = uri;
    this.index = undefined;
    this.selection = [];
    this.setFocusRoot(undefined);
  }

  matchesTarget(uri: vscode.Uri): boolean {
    return !!this.target && uri.toString() === this.uriKey();
  }

  hasTarget(): boolean {
    return !!this.target;
  }

  async load(): Promise<void> {
    const uri = this.target;
    if (!uri) {
      this.index = undefined;
      this.message = vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса) – the structure follows the active editor.");
      this.publish();
      return;
    }
    if (!lspActive()) {
      this.index = undefined;
      this.message = vscode.l10n.t('The structure view needs the LSP mode (install the engine with the [lsp] extra: pip install "xbsl[lsp]").');
      this.publish();
      return;
    }
    const seq = ++this.loadSeq;
    const res = await lspRequest<FormTreeResponse>("xbsl/formTree", { uri: uri.toString() });
    if (seq !== this.loadSeq || uri !== this.target) {
      return; // superseded by a newer load or a target switch
    }
    if (!res || !res.available || !res.root) {
      this.index = undefined;
      this.message = res?.reason || vscode.l10n.t("No form tree here – open a form yaml (КомпонентИнтерфейса).");
      this.publish();
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
    // The selection is positional too: ids shift on every edit, so it rides through the same
    // remapping - otherwise a rename would silently empty the palette's insertion target.
    this.selection = [...remapIds(this.selection, this.index, fresh)];
    this.index = fresh;
    this.visibleIds = this.namedOnly ? visibleWithNamedFilter(fresh) : undefined;
    this.message = undefined;
    // hook 11: a library form or a git/diff view is inspected, not edited - the panel shows
    // a banner and the write path refuses.
    this.readonlyForm = await isReadonlyDoc(uri);
    this.updateDiagnostics();
    this.publish();
    // Learn the schema container set and the package map even when the palette was never
    // opened: component icons and drop planning read them synchronously.
    if (!cachedContainerTypes()) {
      warmContainers(() => this.publish());
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

  toggleRow(id: string, expanded: boolean): void {
    const mem = this.memoryFor();
    if (expanded) {
      mem.expanded.add(id);
      mem.collapsed.delete(id);
    } else {
      mem.collapsed.add(id);
      mem.expanded.delete(id);
    }
    this.publish();
  }

  // --- snapshot -----------------------------------------------------------------------------

  snapshot(): StructureSnapshot {
    if (!this.index) {
      return {
        available: false,
        message: this.message,
        rows: [],
        selection: [],
        namedOnly: this.namedOnly,
        readonly: this.readonlyForm,
      };
    }
    const mem = this.memoryFor();
    const focusNode = this.focusRootId ? this.index.byId.get(this.focusRootId) : undefined;
    return {
      available: true,
      rows: flattenStructure(this.index, {
        expanded: mem.expanded,
        collapsed: mem.collapsed,
        visibleIds: this.visibleIds,
        rootId: this.focusRootId,
        badges: this.diagBadges,
        isContainerType: (t) => cachedContainerTypes()?.has(t) ?? false,
        packageOf: cachedComponentPackage,
        slotTooltip: (name) => vscode.l10n.t("Slot {0}", name),
      }),
      selection: [...this.selection],
      focusLabel: focusNode ? nodeLabel(focusNode) : undefined,
      namedOnly: this.namedOnly,
      readonly: this.readonlyForm,
    };
  }

  private publish(): void {
    this.host?.showStructure(this.snapshot());
  }

  repaint(): void {
    this.publish();
  }

  // --- filter and subtree focus -----------------------------------------------------------

  setFocusRoot(id: string | undefined, index?: FormIndex): void {
    this.focusRootId = id;
    void vscode.commands.executeCommand("setContext", FOCUSED_CONTEXT, !!id);
    if (index !== undefined || this.index) {
      this.publish();
    }
  }

  setNamedOnly(value: boolean): void {
    this.namedOnly = value;
    this.visibleIds = value && this.index ? visibleWithNamedFilter(this.index) : undefined;
    void vscode.commands.executeCommand("setContext", NAMED_CONTEXT, value);
    this.publish();
  }

  // --- diagnostics badges (hook 3) --------------------------------------------------------

  scheduleDiagnostics(): void {
    if (this.diagTimer) {
      clearTimeout(this.diagTimer);
    }
    this.diagTimer = setTimeout(() => {
      this.diagTimer = undefined;
      this.updateDiagnostics();
      this.publish();
    }, 200);
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

  // --- selection ---------------------------------------------------------------------------

  setSelection(ids: string[]): void {
    this.selection = ids.filter((id) => this.index?.byId.has(id));
  }

  private selected(): FormNode[] {
    return this.selection.map((id) => this.index?.byId.get(id)).filter((n): n is FormNode => !!n);
  }

  // The nodes an action applies to: the row it was invoked on, else the panel selection.
  selectedNodes(id?: string): FormNode[] {
    const node = id ? this.index?.byId.get(id) : undefined;
    if (node) {
      // An action on a row outside the selection acts on that row alone; inside it - on the
      // whole selection (the native tree behaved the same way).
      return this.selection.includes(node.id) ? this.selected() : [node];
    }
    return this.selected();
  }

  // Row activated in the panel: land the cursor on the node's first property line (not its
  // list-item dash), so the frame highlights this block and not the one above it. The
  // properties panel is filled DIRECTLY through its command.
  async activate(id: string, focusEditor: boolean): Promise<void> {
    const node = this.index?.byId.get(id);
    if (!node) {
      return;
    }
    const offset = await this.contentOffset(node);
    await this.revealInEditor(offset, !focusEditor);
    void this.notifyPropsPanel(offset);
  }

  private async contentOffset(node: FormNode): Promise<number> {
    let offset = revealOffset(node);
    if (this.target) {
      try {
        const doc = await vscode.workspace.openTextDocument(this.target);
        offset = skipToNodeKey(doc.getText(), offset);
      } catch {
        // keep the raw offset if the document cannot be opened
      }
    }
    return offset;
  }

  async offsetOf(id: string): Promise<number | undefined> {
    const node = this.index?.byId.get(id);
    return node ? this.contentOffset(node) : undefined;
  }

  async nodeIdAt(offset: number): Promise<string | undefined> {
    if (!this.target || !this.index || Date.now() < this.suppressCursorSyncUntil) {
      return undefined;
    }
    const res = await lspRequest<FormNodeAtResponse>("xbsl/formNodeAt", {
      uri: this.target.toString(),
      offset,
    });
    const id = res?.node?.id;
    if (!id || !this.index.byId.has(id)) {
      return undefined;
    }
    if (this.visibleIds && !this.visibleIds.has(id)) {
      return undefined; // hidden by the named-only filter
    }
    if (this.focusRootId && !isDescendantOf(this.index, id, this.focusRootId)) {
      return undefined; // outside the focused subtree
    }
    return id;
  }

  async revealInEditor(offset: number, preserveFocus: boolean): Promise<void> {
    if (!this.target) {
      return;
    }
    this.suppressCursorSyncUntil = Date.now() + 300;
    const doc = await vscode.workspace.openTextDocument(this.target);
    const pos = doc.positionAt(Math.min(offset, doc.getText().length));
    const existing = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === this.uriKey());
    const editor = await vscode.window.showTextDocument(doc, {
      viewColumn: existing?.viewColumn ?? vscode.ViewColumn.One,
      preserveFocus,
      preview: false,
    });
    editor.selection = new vscode.Selection(pos, pos);
    revealContent(editor, pos);
  }

  // --- operations (thin wrappers over xbsl/formEdit) --------------------------------------

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
        this.setSelection([res.node.id]);
        this.publish();
        this.host?.revealStructure(res.node.id);
        await this.revealInEditor(res.node.span.start, true);
      }
      return res.node ?? undefined;
    } finally {
      this.opInFlight = false;
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
            this.setSelection([]);
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
      this.setSelection([]);
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
  async insertPreset(id?: string): Promise<void> {
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
    const selected = this.selectedNodes(id)[0];
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
  async editSelected(id?: string): Promise<void> {
    if (!this.target || !this.index) {
      return;
    }
    const selected = this.selectedNodes(id).filter((n) => n.kind === "component" && n.id !== ROOT_ID);
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
    const OTHER = " other";
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
  async pasteFromClipboard(id?: string): Promise<void> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the clipboard yaml is pasted into the structure selection.")
      );
      return;
    }
    const fragment = await vscode.env.clipboard.readText();
    const selected = this.selectedNodes(id)[0];
    const args = pasteFragmentArgs(selected, this.index, fragment, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!args) {
      return;
    }
    const inserted = await this.performOp("insert_fragment", args);
    if (inserted) {
      void this.notifyPropsPanel(inserted.span.start);
    }
  }

  // --- palette and data-panel insertion ---------------------------------------------------

  async insertComponentType(type: string): Promise<boolean> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the palette inserts into the structure selection.")
      );
      return false;
    }
    const plan = insertPlanForSelection(this.selected()[0], this.index, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!plan) {
      return false;
    }
    return !!(await this.insertByPlan(plan, type));
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

  // A ready yaml fragment (an input component built by the data pane) into the current
  // structure selection - the same target semantics as the palette insertion.
  async insertFragment(fragment: string): Promise<boolean> {
    if (!this.index || !this.target) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) – the field is inserted into the structure selection.")
      );
      return false;
    }
    const plan = insertPlanForSelection(this.selected()[0], this.index, (t) => cachedContainerTypes()?.has(t) ?? false);
    if (!plan) {
      return false;
    }
    return !!(await this.insertFragmentByPlan(plan, fragment));
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

  // --- drops inside the panel --------------------------------------------------------------

  // Where a drop onto the row lands: a container takes it as the last child, a leaf places it
  // after itself, a slot at its end - the semantics the native tree had (dropPlan).
  private planForDrop(targetId: string): InsertPlan | undefined {
    if (!this.index) {
      return undefined;
    }
    const target = this.index.byId.get(targetId) ?? this.index.root;
    return dropPlan(target, this.index, (t) => cachedContainerTypes()?.has(t) ?? false);
  }

  async dropNodes(sourceIds: string[], targetId: string): Promise<void> {
    if (!this.index) {
      return;
    }
    const plan = this.planForDrop(targetId);
    if (!plan || !validMoveTarget(this.index, sourceIds, targetId)) {
      return; // dropping into a dragged subtree
    }
    // The engine moves one node per operation; ids shift after every edit, so the drop takes
    // the first (top-most) dragged node - precise multi-ordering is keyboard-first (Alt+Up/Down).
    const nodeId = sourceIds[0];
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

  // A record dragged from the data pane: the drop point takes an input component with the
  // binding, built as one ready fragment.
  async dropRecord(payload: DataDragPayload, targetId: string): Promise<void> {
    const plan = this.planForDrop(targetId);
    if (!plan) {
      return;
    }
    await this.insertFragmentByPlan(plan, buildFieldFragment(payload));
  }
}

export function registerFormStructure(context: vscode.ExtensionContext): FormStructureController {
  const model = new FormStructureModel(context.globalState);
  void vscode.commands.executeCommand("setContext", FOCUSED_CONTEXT, false);
  void vscode.commands.executeCommand("setContext", NAMED_CONTEXT, false);

  // Commands are invoked from the panel (a row id rides along), from the command palette and
  // from keybindings; without an id they act on the panel's selection.
  const first = (id?: string): FormNode | undefined => model.selectedNodes(id)[0];

  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.formStructure.refresh", () => void model.load()),
    vscode.commands.registerCommand("xbsl.formStructure.openInEditor", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.revealInEditor(revealOffset(target), false);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.moveUp", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.moveNode(target, "up");
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.moveDown", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.moveNode(target, "down");
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.delete", (id?: string) => {
      void model.deleteNodes(model.selectedNodes(id));
    }),
    vscode.commands.registerCommand("xbsl.formStructure.rename", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.renameNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.duplicate", (id?: string) => {
      const target = first(id);
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void model.performOp("duplicate", { node: target.id });
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.wrap", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.wrapNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.unwrap", (id?: string) => {
      const target = first(id);
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void model.performOp("unwrap", { node: target.id });
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.copyYaml", (id?: string) => {
      const target = first(id);
      if (target) {
        void model.copyNode(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.pasteYaml", (id?: string) => {
      void model.pasteFromClipboard(id);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.savePreset", (id?: string) => {
      const target = first(id);
      if (target && target.kind === "component" && target.id !== ROOT_ID) {
        void model.saveAsPreset(target);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.insertPreset", (id?: string) => {
      void model.insertPreset(id);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.managePresets", () => void model.managePresets()),
    vscode.commands.registerCommand("xbsl.formStructure.editSelected", (id?: string) => {
      void model.editSelected(id);
    }),
    vscode.commands.registerCommand("xbsl.formStructure.focusSubtree", (id?: string) => {
      const target = first(id);
      if (target && target.kind === "component") {
        model.setFocusRoot(target.id);
      }
    }),
    vscode.commands.registerCommand("xbsl.formStructure.resetFocus", () => model.setFocusRoot(undefined)),
    vscode.commands.registerCommand("xbsl.formStructure.filterNamed", () => model.setNamedOnly(true)),
    vscode.commands.registerCommand("xbsl.formStructure.filterAll", () => model.setNamedOnly(false))
  );

  return {
    setHost: (host) => model.setHost(host),
    setTarget: (uri) => model.setTarget(uri),
    matchesTarget: (uri) => model.matchesTarget(uri),
    hasTarget: () => model.hasTarget(),
    load: () => model.load(),
    scheduleDiagnostics: () => model.scheduleDiagnostics(),
    setSelection: (ids) => model.setSelection(ids),
    toggleRow: (id, expanded) => model.toggleRow(id, expanded),
    activate: (id, focusEditor) => model.activate(id, focusEditor),
    offsetOf: (id) => model.offsetOf(id),
    nodeIdAt: (offset) => model.nodeIdAt(offset),
    dropNodes: (ids, targetId) => model.dropNodes(ids, targetId),
    dropRecord: (payload, targetId) => model.dropRecord(payload, targetId),
    insertComponentType: (type) => model.insertComponentType(type),
    repaint: () => model.repaint(),
    insertFragment: (fragment) => model.insertFragment(fragment),
  };
}
