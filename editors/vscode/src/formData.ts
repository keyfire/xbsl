// The form DATA model (docs/DESIGNER.md hook 2): the data a form can bind to. Two sections -
// the component's own Свойства records (served by the engine's xbsl/formTree) with
// add/rename/retype/remove operations, and, when the form belongs to a data object (resolved
// through the metadata tree index), the object's attributes and tabular parts served by
// xbsl/objectInfo. Each operation is ONE flat xbsl/formEdit request whose text edits are
// applied here via WorkspaceEdit.
//
// Since the designer's recomposition the section rows are painted by the form panel
// (formDesigner.ts) next to the structure pane, so this module owns no view: it hands the
// panel a flat snapshot (formDesignerCore.flattenData) and answers its actions. A record
// inserts into the current structure selection - by a double click or by a drag onto a
// structure row, both ending in structure.insertFragment / dropRecord. Pure logic (payloads,
// the fragment, name validation) lives in formDataCore.ts.

import * as vscode from "vscode";
import {
  ComponentPropertyRecord,
  DataDragPayload,
  DataFormEditResponse,
  DataFormTreeResponse,
  buildFieldFragment,
  isMultilineText,
  ObjectInfoResponse,
  PROPERTY_PRIMITIVE_TYPES,
  propertyNameError,
} from "./formDataCore";
import { DataRow, flattenData, DataModel, propertyRowId } from "./formDesignerCore";
import { FormStructureController } from "./formStructure";
import { lspActive, lspRequest } from "./lspClient";
import { componentEnums } from "./uiSchemaClient";

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

// What the panel needs to paint the data pane.
export interface DataSnapshot {
  available: boolean;
  message?: string;
  rows: DataRow[];
  selection?: string;
}

export interface DataHost {
  showData(snapshot: DataSnapshot): void;
}

export interface FormDataController {
  setHost(host: DataHost | undefined): void;
  setTarget(uri: vscode.Uri): void;
  matchesTarget(uri: vscode.Uri): boolean;
  load(): Promise<void>;
  setSelection(id: string | undefined): void;
  toggleRow(id: string, expanded: boolean): void;
  //: A single activation: a component property jumps to its yaml line.
  reveal(id: string): Promise<void>;
  //: The drag payload of a row, undefined for the rows that cannot become a field.
  payloadFor(id: string): DataDragPayload | undefined;
  //: Insert the row as an input component into the current structure selection.
  insert(id: string): Promise<void>;
  //: Menu and toolbar actions (addProperty / renameProperty / retypeProperty / removeProperty).
  runCommand(command: string, id?: string): Promise<void>;
}

class FormDataModel {
  private host?: DataHost;
  private target?: vscode.Uri;
  private records?: ComponentPropertyRecord[];
  private rootType?: string;
  private owner?: FormOwnerRef;
  private objectInfo?: ObjectInfoResponse;
  private message?: string;
  private loadSeq = 0;
  private opInFlight = false;
  private selection?: string;
  private readonly expanded = new Set<string>();
  private readonly collapsed = new Set<string>();

  constructor(private readonly deps: FormDataDeps) {}

  setHost(host: DataHost | undefined): void {
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
    this.records = undefined;
    this.owner = undefined;
    this.objectInfo = undefined;
    this.selection = undefined;
  }

  matchesTarget(uri: vscode.Uri): boolean {
    return !!this.target && uri.toString() === this.uriKey();
  }

  async load(): Promise<void> {
    const uri = this.target;
    if (!uri) {
      this.records = undefined;
      this.message = vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса) – the data panel follows the active editor.");
      this.publish();
      return;
    }
    if (!lspActive()) {
      this.records = undefined;
      this.message = vscode.l10n.t('The data panel needs the LSP mode (install the engine with the [lsp] extra: pip install "xbsl[lsp]").');
      this.publish();
      return;
    }
    const seq = ++this.loadSeq;
    const res = await lspRequest<DataFormTreeResponse>("xbsl/formTree", { uri: uri.toString() });
    if (seq !== this.loadSeq || uri !== this.target) {
      return; // superseded by a newer load or a target switch
    }
    if (!res || !res.available) {
      this.records = undefined;
      this.message = res?.reason || vscode.l10n.t("No form tree here – open a form yaml (КомпонентИнтерфейса).");
      this.publish();
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
    this.message = undefined;
    this.publish();
  }

  // --- snapshot -----------------------------------------------------------------------------

  private model(): DataModel | undefined {
    if (!this.records) {
      return undefined;
    }
    return {
      records: this.records,
      owner: this.owner && this.objectInfo ? { name: this.owner.name, kind: this.owner.kind } : undefined,
      fields: this.objectInfo?.fields ?? [],
      tabulars: this.objectInfo?.tabulars ?? [],
    };
  }

  snapshot(): DataSnapshot {
    const model = this.model();
    if (!model) {
      return { available: false, message: this.message, rows: [] };
    }
    return {
      available: true,
      rows: flattenData(model, this.expanded, this.collapsed, {
        propsSection: vscode.l10n.t("Component properties"),
        objectSection: vscode.l10n.t("Object attributes"),
        propertyTooltip: vscode.l10n.t("Component property"),
        attributeTooltip: vscode.l10n.t("Object attribute"),
        tabularTooltip: vscode.l10n.t("Tabular part (shown for reference – drag the scalar attributes)"),
        insertHint: vscode.l10n.t("Drag onto the form structure, or double click, to insert the field."),
      }),
      selection: this.selection,
    };
  }

  private publish(): void {
    this.host?.showData(this.snapshot());
  }

  setSelection(id: string | undefined): void {
    this.selection = id;
  }

  toggleRow(id: string, expanded: boolean): void {
    if (expanded) {
      this.expanded.add(id);
      this.collapsed.delete(id);
    } else {
      this.collapsed.add(id);
      this.expanded.delete(id);
    }
    this.publish();
  }

  // --- rows ---------------------------------------------------------------------------------

  private recordFor(id: string): ComponentPropertyRecord | undefined {
    if (id.startsWith("prop:")) {
      const name = id.slice("prop:".length);
      return (this.records ?? []).find((r) => r.name === name);
    }
    if (id.startsWith("prop#")) {
      const at = Number(id.slice("prop#".length));
      const record = (this.records ?? [])[at];
      // Position ids only address the nameless records - a named one would have a name id.
      return record && !record.name ? record : undefined;
    }
    return undefined;
  }

  payloadFor(id: string): DataDragPayload | undefined {
    const record = this.recordFor(id);
    if (record?.name) {
      const type = record.type ?? "";
      return {
        kind: "componentProperty",
        name: record.name,
        type,
        multiline: isMultilineText(record.name, type),
      };
    }
    if (id.startsWith("attr:")) {
      const name = id.slice("attr:".length);
      const field = (this.objectInfo?.fields ?? []).find((f) => f.name === name);
      if (field) {
        return {
          kind: "attribute",
          name: field.name,
          type: field.type,
          multiline: isMultilineText(field.name, field.type),
        };
      }
    }
    return undefined;
  }

  // A component property row jumps to its yaml line; the object's own attributes live in
  // another file and are not navigated from here.
  async reveal(id: string): Promise<void> {
    const record = this.recordFor(id);
    if (!record) {
      return;
    }
    await this.revealInEditor(record.nameSpan?.start ?? record.span.start, true);
  }

  async insert(id: string): Promise<void> {
    const payload = this.payloadFor(id);
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

  async renameProperty(id?: string): Promise<void> {
    const record = id ? this.recordFor(id) : undefined;
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

  async retypeProperty(id?: string): Promise<void> {
    const record = id ? this.recordFor(id) : undefined;
    if (!record?.name) {
      return;
    }
    const type = await this.pickPropertyType(record.type ?? "");
    if (!type || type === record.type) {
      return;
    }
    await this.performOp("property_retype", { name: record.name, newType: type });
  }

  async removeProperty(id?: string): Promise<void> {
    const record = id ? this.recordFor(id) : undefined;
    if (!record?.name) {
      return;
    }
    await this.performOp("property_remove", { name: record.name });
  }
}

export function registerFormData(context: vscode.ExtensionContext, deps: FormDataDeps): FormDataController {
  const model = new FormDataModel(deps);
  const selected = (id?: string): string | undefined => id;

  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.formData.refresh", () => void model.load()),
    vscode.commands.registerCommand("xbsl.formData.insert", (id?: string) => {
      if (id) {
        void model.insert(id);
      }
    }),
    vscode.commands.registerCommand("xbsl.formData.addProperty", () => void model.addProperty()),
    vscode.commands.registerCommand("xbsl.formData.renameProperty", (id?: string) => void model.renameProperty(selected(id))),
    vscode.commands.registerCommand("xbsl.formData.retypeProperty", (id?: string) => void model.retypeProperty(selected(id))),
    vscode.commands.registerCommand("xbsl.formData.removeProperty", (id?: string) => void model.removeProperty(selected(id)))
  );

  return {
    setHost: (host) => model.setHost(host),
    setTarget: (uri) => model.setTarget(uri),
    matchesTarget: (uri) => model.matchesTarget(uri),
    load: () => model.load(),
    setSelection: (id) => model.setSelection(id),
    toggleRow: (id, expanded) => model.toggleRow(id, expanded),
    reveal: (id) => model.reveal(id),
    payloadFor: (id) => model.payloadFor(id),
    insert: (id) => model.insert(id),
    runCommand: async (command, id) => {
      switch (command) {
        case "insert":
          if (id) {
            await model.insert(id);
          }
          return;
        case "addProperty":
          await model.addProperty();
          return;
        case "renameProperty":
          await model.renameProperty(id);
          return;
        case "retypeProperty":
          await model.retypeProperty(id);
          return;
        case "removeProperty":
          await model.removeProperty(id);
          return;
        default:
          return;
      }
    },
  };
}
