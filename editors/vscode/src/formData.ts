// The "Data" view (native TreeView in the 1C:Element Designer container, docs/DESIGNER.md
// hook 2): the data a form can bind to, following the active КомпонентИнтерфейса yaml like
// the structure view. Two sections: the component's own Свойства records (served by the
// engine's xbsl/formTree) with add/rename/retype/remove operations - each is ONE flat
// xbsl/formEdit request whose text edits are applied here via WorkspaceEdit - and, when the
// form belongs to a data object (resolved through the metadata tree index), the object's
// attributes and tabular parts served by xbsl/objectInfo. Records of both sections drag
// into the structure view (the palette pattern: our own MIME with a JSON payload; the drop
// side builds the input-component fragment) and insert into the current structure selection
// on a double activation. Pure logic (payloads, the fragment, name validation) lives in
// formDataCore.ts.

import * as vscode from "vscode";
import {
  buildFieldFragment,
  ComponentPropertyRecord,
  DataDragPayload,
  DataFormEditResponse,
  DataFormTreeResponse,
  DATA_MIME,
  encodeDataDrag,
  isMultilineText,
  ObjectInfoField,
  ObjectInfoResponse,
  ObjectInfoTabular,
  PROPERTY_PRIMITIVE_TYPES,
  propertyNameError,
} from "./formDataCore";
import { FormStructureController } from "./formStructure";
import { lspActive, lspRequest } from "./lspClient";
import { componentEnums } from "./uiSchemaClient";

const TREE_DEBOUNCE_MS = 300;
const DOUBLE_ACTIVATE_MS = 450;

// The same shallow check the structure view uses: an interface component with inheritance.
function looksLikeForm(doc: vscode.TextDocument): boolean {
  if (doc.languageId !== "yaml") {
    return false;
  }
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return head.includes("КомпонентИнтерфейса") && doc.getText().includes("Наследует");
}

export interface FormOwnerRef {
  name: string;
  kind: string;
  yamlPath: string;
}

export interface FormDataDeps {
  structure: FormStructureController;
  // The owner OBJECT of a form by the form's yaml path (the metadata tree index);
  // undefined for common forms - the object section is hidden then.
  formOwner: (yamlPath: string) => Promise<FormOwnerRef | undefined>;
}

type DataElement =
  | { kind: "section"; section: "props" | "object" }
  | { kind: "property"; record: ComponentPropertyRecord }
  | { kind: "attribute"; field: ObjectInfoField }
  | { kind: "tabular"; tabular: ObjectInfoTabular }
  | { kind: "column"; tabular: string; field: ObjectInfoField };

function payloadOf(element: DataElement): DataDragPayload | undefined {
  if (element.kind === "property" && element.record.name) {
    const type = element.record.type ?? "";
    return {
      kind: "componentProperty",
      name: element.record.name,
      type,
      multiline: isMultilineText(element.record.name, type),
    };
  }
  if (element.kind === "attribute") {
    return {
      kind: "attribute",
      name: element.field.name,
      type: element.field.type,
      multiline: isMultilineText(element.field.name, element.field.type),
    };
  }
  return undefined;
}

class FormDataProvider
  implements vscode.TreeDataProvider<DataElement>, vscode.TreeDragAndDropController<DataElement>
{
  private readonly emitter = new vscode.EventEmitter<DataElement | undefined | void>();
  readonly onDidChangeTreeData = this.emitter.event;

  readonly dragMimeTypes = [DATA_MIME];
  readonly dropMimeTypes: string[] = [];

  private view?: vscode.TreeView<DataElement>;
  private target?: vscode.Uri;
  private records?: ComponentPropertyRecord[];
  private rootType?: string;
  private owner?: FormOwnerRef;
  private objectInfo?: ObjectInfoResponse;
  private loadSeq = 0;
  private loadTimer?: NodeJS.Timeout;
  private lastActivation?: { id: string; at: number };
  private hintShown = false;
  private opInFlight = false;

  constructor(private readonly deps: FormDataDeps) {}

  attachView(view: vscode.TreeView<DataElement>): void {
    this.view = view;
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
    this.records = undefined;
    this.owner = undefined;
    this.objectInfo = undefined;
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
      this.records = undefined;
      this.setMessage(vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса) – the data panel follows the active editor."));
      this.emitter.fire(undefined);
      return;
    }
    if (!lspActive()) {
      this.records = undefined;
      this.setMessage(vscode.l10n.t('The data panel needs the LSP mode (install the engine with the [lsp] extra: pip install "xbsl[lsp]").'));
      this.emitter.fire(undefined);
      return;
    }
    const seq = ++this.loadSeq;
    const res = await lspRequest<DataFormTreeResponse>("xbsl/formTree", { uri: uri.toString() });
    if (seq !== this.loadSeq || uri !== this.target) {
      return; // superseded by a newer load or a target switch
    }
    if (!res || !res.available) {
      this.records = undefined;
      this.setMessage(res?.reason || vscode.l10n.t("No form tree here – open a form yaml (КомпонентИнтерфейса)."));
      this.emitter.fire(undefined);
      return;
    }
    this.records = res.componentProperties ?? [];
    this.rootType = res.root?.type ?? undefined;
    // The owner object comes from the workspace metadata index; its attributes from the
    // engine. Either may be missing (a common form, an unreadable owner) - the object
    // section is simply not shown then.
    let owner: FormOwnerRef | undefined;
    try {
      owner = await this.deps.formOwner(uri.fsPath);
    } catch {
      owner = undefined;
    }
    let info: ObjectInfoResponse | undefined;
    if (owner) {
      info = await lspRequest<ObjectInfoResponse>("xbsl/objectInfo", { path: owner.yamlPath });
      if (info?.error) {
        info = undefined;
      }
    }
    if (seq !== this.loadSeq || uri !== this.target) {
      return;
    }
    this.owner = owner;
    this.objectInfo = info;
    this.setMessage(undefined);
    this.emitter.fire(undefined);
  }

  private setMessage(message: string | undefined): void {
    if (this.view) {
      this.view.message = message;
    }
  }

  // --- TreeDataProvider -------------------------------------------------------------------

  getChildren(element?: DataElement): DataElement[] {
    if (!this.records) {
      return [];
    }
    if (!element) {
      const sections: DataElement[] = [{ kind: "section", section: "props" }];
      if (this.owner && this.objectInfo) {
        sections.push({ kind: "section", section: "object" });
      }
      return sections;
    }
    if (element.kind === "section" && element.section === "props") {
      return (this.records ?? []).map((record): DataElement => ({ kind: "property", record }));
    }
    if (element.kind === "section" && element.section === "object") {
      return [
        ...(this.objectInfo?.fields ?? []).map((field): DataElement => ({ kind: "attribute", field })),
        ...(this.objectInfo?.tabulars ?? []).map((tabular): DataElement => ({ kind: "tabular", tabular })),
      ];
    }
    if (element.kind === "tabular") {
      return element.tabular.fields.map(
        (field): DataElement => ({ kind: "column", tabular: element.tabular.name, field })
      );
    }
    return [];
  }

  getParent(element: DataElement): DataElement | undefined {
    switch (element.kind) {
      case "section":
        return undefined;
      case "property":
        return { kind: "section", section: "props" };
      case "column": {
        const tabular = (this.objectInfo?.tabulars ?? []).find((t) => t.name === element.tabular);
        return tabular ? { kind: "tabular", tabular } : { kind: "section", section: "object" };
      }
      default:
        return { kind: "section", section: "object" };
    }
  }

  getTreeItem(element: DataElement): vscode.TreeItem {
    if (element.kind === "section") {
      const props = element.section === "props";
      const label = props ? vscode.l10n.t("Component properties") : vscode.l10n.t("Object attributes");
      const count = props
        ? (this.records ?? []).length
        : (this.objectInfo?.fields?.length ?? 0) + (this.objectInfo?.tabulars?.length ?? 0);
      const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.Expanded);
      item.id = `${this.uriKey()}#section:${element.section}`;
      item.description = props ? String(count) : `${this.owner?.name ?? ""} · ${count}`;
      item.iconPath = new vscode.ThemeIcon(props ? "symbol-property" : "database");
      item.contextValue = props ? "dataSectionProps" : "dataSectionObject";
      if (!props && this.owner) {
        item.tooltip = `${this.owner.kind} ${this.owner.name}`;
      }
      return item;
    }
    if (element.kind === "property") {
      const name = element.record.name ?? "?";
      const item = new vscode.TreeItem(name, vscode.TreeItemCollapsibleState.None);
      item.id = `${this.uriKey()}#prop:${name}`;
      item.description = element.record.type ?? "";
      item.iconPath = new vscode.ThemeIcon("symbol-property");
      // Records without Имя cannot be dragged or edited by the name-keyed operations.
      item.contextValue = element.record.name ? "dataRecord dataProperty" : "dataBroken";
      item.tooltip = this.rowTooltip(vscode.l10n.t("Component property"), element.record.type ?? "");
      item.command = { command: "xbsl.formData.activate", title: "", arguments: [element] };
      return item;
    }
    if (element.kind === "attribute") {
      const item = new vscode.TreeItem(element.field.name, vscode.TreeItemCollapsibleState.None);
      item.id = `${this.uriKey()}#attr:${element.field.name}`;
      item.description = element.field.type;
      item.iconPath = new vscode.ThemeIcon("symbol-field");
      item.contextValue = "dataRecord dataAttribute";
      item.tooltip = this.rowTooltip(vscode.l10n.t("Object attribute"), element.field.type);
      item.command = { command: "xbsl.formData.activate", title: "", arguments: [element] };
      return item;
    }
    if (element.kind === "tabular") {
      const item = new vscode.TreeItem(element.tabular.name, vscode.TreeItemCollapsibleState.Collapsed);
      item.id = `${this.uriKey()}#tc:${element.tabular.name}`;
      item.description = String(element.tabular.fields.length);
      item.iconPath = new vscode.ThemeIcon("table");
      item.contextValue = "dataTabular";
      item.tooltip = vscode.l10n.t("Tabular part (shown for reference – drag the scalar attributes)");
      return item;
    }
    const item = new vscode.TreeItem(element.field.name, vscode.TreeItemCollapsibleState.None);
    item.id = `${this.uriKey()}#tc:${element.tabular}:${element.field.name}`;
    item.description = element.field.type;
    item.iconPath = new vscode.ThemeIcon("symbol-field");
    item.contextValue = "dataColumn";
    return item;
  }

  private rowTooltip(caption: string, type: string): string {
    const parts = [caption + (type ? ` · ${type}` : "")];
    parts.push(vscode.l10n.t("Drag into the form structure, or double click (Enter twice) to insert into the structure selection."));
    return parts.join("\n\n");
  }

  // --- activation and insertion -----------------------------------------------------------

  // First activation reveals the record (a component property jumps to its yaml line), a
  // second one within the window (double click or Enter twice) inserts the input component
  // into the structure selection - the palette pattern.
  async activate(element: DataElement): Promise<void> {
    const payload = payloadOf(element);
    if (!payload) {
      return;
    }
    const now = Date.now();
    const id = `${payload.kind}:${payload.name}`;
    const double =
      !!this.lastActivation && this.lastActivation.id === id && now - this.lastActivation.at < DOUBLE_ACTIVATE_MS;
    this.lastActivation = { id, at: now };
    if (element.kind === "property") {
      const offset = element.record.nameSpan?.start ?? element.record.span.start;
      await this.revealInEditor(offset, true);
    }
    if (double) {
      await this.insert(element);
    } else if (!this.hintShown) {
      this.hintShown = true;
      vscode.window.setStatusBarMessage(
        vscode.l10n.t("XBSL: double click (or Enter twice) inserts the field into the form."),
        3000
      );
    }
  }

  async insert(element?: DataElement): Promise<void> {
    const payload = element ? payloadOf(element) : undefined;
    if (!payload) {
      return;
    }
    await this.deps.structure.insertFragment(buildFieldFragment(payload));
  }

  private async revealInEditor(offset: number, preserveFocus: boolean): Promise<void> {
    if (!this.target) {
      return;
    }
    const doc = await vscode.workspace.openTextDocument(this.target);
    const pos = doc.positionAt(Math.min(offset, doc.getText().length));
    const existing = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === this.uriKey());
    const editor = await vscode.window.showTextDocument(doc, {
      viewColumn: existing?.viewColumn ?? vscode.ViewColumn.One,
      preserveFocus,
      preview: false,
    });
    editor.selection = new vscode.Selection(pos, pos);
    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }

  // --- property operations (thin wrappers over the flat xbsl/formEdit) ---------------------

  // One operation end to end: request the edits, apply them as a single WorkspaceEdit (one
  // undo step), reload the sections, surface the engine notes (e.g. the binding-usage
  // warning of property_rename) and put the cursor on the resulting record.
  private async performOp(op: string, args: Record<string, unknown>): Promise<boolean> {
    if (this.opInFlight || !this.target) {
      return false;
    }
    if (!lspActive()) {
      void vscode.window.showWarningMessage(
        vscode.l10n.t('XBSL: form operations need the LSP mode (pip install "xbsl[lsp]").')
      );
      return false;
    }
    this.opInFlight = true;
    try {
      const doc = this.targetDocument();
      if (!doc) {
        return false;
      }
      const version = doc.version;
      // The operation arguments ride FLAT in params: over the real pygls channel a nested
      // args object arrives as a namedtuple, not a dict, which older engines could not read.
      const res = await lspRequest<DataFormEditResponse>("xbsl/formEdit", {
        uri: this.target.toString(),
        op,
        ...args,
      });
      if (!res) {
        void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the engine did not answer the form edit request."));
        return false;
      }
      if (res.error) {
        void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", res.error));
        return false;
      }
      if (doc.version !== version) {
        void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the buffer changed while the edit was being computed – try again."));
        return false;
      }
      const we = new vscode.WorkspaceEdit();
      for (const e of res.edits ?? []) {
        we.replace(doc.uri, new vscode.Range(doc.positionAt(e.start), doc.positionAt(e.end)), e.newText);
      }
      if (!(await vscode.workspace.applyEdit(we))) {
        return false;
      }
      for (const note of res.notes ?? []) {
        void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", note));
      }
      await this.load();
      if (res.node) {
        await this.revealInEditor(res.node.span.start, true);
      }
      return true;
    } finally {
      this.opInFlight = false;
    }
  }

  private existingNames(): (string | null)[] {
    return (this.records ?? []).map((r) => r.name);
  }

  private async askPropertyName(prompt: string, value: string, existing: (string | null)[]): Promise<string | undefined> {
    const name = await vscode.window.showInputBox({
      prompt,
      value,
      validateInput: (v) => {
        switch (propertyNameError(v.trim(), existing)) {
          case "empty":
            return vscode.l10n.t("A valid identifier is required (letters, digits, _).");
          case "yo":
            return vscode.l10n.t("The letter ё is not used in names (the 1C:Element naming standard).");
          case "identifier":
            return vscode.l10n.t("A valid identifier is required (letters, digits, _).");
          case "duplicate":
            return vscode.l10n.t("A property with this name already exists.");
          default:
            return undefined;
        }
      },
    });
    return name?.trim() || undefined;
  }

  // The type picker: primitives, then the enumerations of the ui schema (the engine serves
  // them per component - the form's root component is the natural source; without generated
  // data the list is just shorter), then free-form entry. The engine validates the final
  // spelling either way.
  private async pickPropertyType(current?: string): Promise<string | undefined> {
    const manualLabel = vscode.l10n.t("Enter the type manually...");
    interface TypeItem extends vscode.QuickPickItem {
      manual?: boolean;
    }
    const items: TypeItem[] = PROPERTY_PRIMITIVE_TYPES.map((t) => ({ label: t }));
    const enums = this.rootType ? await componentEnums(this.rootType) : {};
    const enumNames = Object.keys(enums);
    if (enumNames.length) {
      items.push({ label: vscode.l10n.t("Enumerations"), kind: vscode.QuickPickItemKind.Separator });
      for (const name of enumNames) {
        const values = enums[name] ?? [];
        items.push({ label: name, description: values.slice(0, 4).join(", ") + (values.length > 4 ? ", ..." : "") });
      }
    }
    items.push({ label: "", kind: vscode.QuickPickItemKind.Separator });
    items.push({ label: manualLabel, manual: true, alwaysShow: true });
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: vscode.l10n.t("Property type"),
    });
    if (!pick) {
      return undefined;
    }
    if (!pick.manual) {
      return pick.label;
    }
    const manual = await vscode.window.showInputBox({
      prompt: vscode.l10n.t("Type (e.g. Строка, Массив<Строка> or Товары.Ссылка|?)"),
      value: current ?? "",
      validateInput: (v) => (v.trim() ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _).")),
    });
    return manual?.trim() || undefined;
  }

  async addProperty(): Promise<void> {
    if (!this.records) {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса) – the data panel follows the active editor.")
      );
      return;
    }
    const name = await this.askPropertyName(
      vscode.l10n.t("Name of the new property (an identifier, without the letter ё)"),
      "НовоеСвойство",
      this.existingNames()
    );
    if (!name) {
      return;
    }
    const type = await this.pickPropertyType();
    if (!type) {
      return;
    }
    await this.performOp("property_add", { name, type });
  }

  async renameProperty(element?: DataElement): Promise<void> {
    const record = element?.kind === "property" ? element.record : undefined;
    if (!record?.name) {
      return;
    }
    const existing = this.existingNames().filter((n) => n !== record.name);
    const fresh = await this.askPropertyName(vscode.l10n.t("New name of the property"), record.name, existing);
    if (!fresh || fresh === record.name) {
      return;
    }
    await this.performOp("property_rename", { name: record.name, newName: fresh });
  }

  async retypeProperty(element?: DataElement): Promise<void> {
    const record = element?.kind === "property" ? element.record : undefined;
    if (!record?.name) {
      return;
    }
    const type = await this.pickPropertyType(record.type ?? "");
    if (!type || type === record.type) {
      return;
    }
    await this.performOp("property_retype", { name: record.name, newType: type });
  }

  async removeProperty(element?: DataElement): Promise<void> {
    const record = element?.kind === "property" ? element.record : undefined;
    if (!record?.name) {
      return;
    }
    await this.performOp("property_remove", { name: record.name });
  }

  selected(context?: DataElement): DataElement | undefined {
    return context ?? this.view?.selection[0];
  }

  // --- drag and drop (the panel is a drag source only) --------------------------------------

  handleDrag(source: readonly DataElement[], dataTransfer: vscode.DataTransfer): void {
    const payload = source.map(payloadOf).find((p) => p !== undefined);
    if (!payload) {
      return; // sections, tabular parts and their columns are not draggable
    }
    dataTransfer.set(DATA_MIME, new vscode.DataTransferItem(encodeDataDrag(payload)));
  }

  handleDrop(): void {
    // Nothing can be dropped into the data panel.
  }
}

export function registerFormData(context: vscode.ExtensionContext, deps: FormDataDeps): void {
  const provider = new FormDataProvider(deps);
  const view = vscode.window.createTreeView<DataElement>("xbslFormData", {
    treeDataProvider: provider,
    dragAndDropController: provider,
    showCollapseAll: true,
  });
  provider.attachView(view);

  const followEditor = (editor: vscode.TextEditor | undefined): void => {
    if (editor && editor.document.uri.scheme === "file" && looksLikeForm(editor.document)) {
      provider.setTarget(editor.document.uri);
    } else if (!provider.hasTarget()) {
      void provider.load(); // shows the "open a form yaml" hint
    }
  };

  context.subscriptions.push(
    view,
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
    vscode.commands.registerCommand("xbsl.formData.refresh", () => void provider.load()),
    vscode.commands.registerCommand("xbsl.formData.activate", (el: DataElement) => void provider.activate(el)),
    vscode.commands.registerCommand("xbsl.formData.insert", (el?: DataElement) => void provider.insert(provider.selected(el))),
    vscode.commands.registerCommand("xbsl.formData.addProperty", () => void provider.addProperty()),
    vscode.commands.registerCommand("xbsl.formData.renameProperty", (el?: DataElement) => void provider.renameProperty(provider.selected(el))),
    vscode.commands.registerCommand("xbsl.formData.retypeProperty", (el?: DataElement) => void provider.retypeProperty(provider.selected(el))),
    vscode.commands.registerCommand("xbsl.formData.removeProperty", (el?: DataElement) => void provider.removeProperty(provider.selected(el)))
  );

  followEditor(vscode.window.activeTextEditor);
}
