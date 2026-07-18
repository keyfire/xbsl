// The "Component palette" view (native TreeView in the 1C:Element Designer container):
// insertable interface components from the engine's xbsl/uiSchema catalog plus the project's own
// КомпонентИнтерфейса elements. Sections: Frequent (insertion counters in globalState),
// Favorites (starred, globalState), Project, then platform packages by the last package
// segment. Insertion goes through the structure view (a double activation - double click or
// Enter twice - or the inline "+" button, or DnD into the structure tree); without generated
// ui-schema data the palette degrades to a hint node plus the project section. Pure section
// building lives in formPaletteCore.ts.

import * as vscode from "vscode";
import { docsSearch } from "./docsClient";
import { openPage } from "./docsPanel";
import { lspActive } from "./lspClient";
import {
  buildPalette,
  PaletteItemModel,
  PaletteSectionModel,
  bumpUsage,
} from "./formPaletteCore";
import { encodePaletteDrag, PALETTE_MIME } from "./formStructureCore";
import { FormStructureController } from "./formStructure";
import { resetUiSchemaCache, uiCatalog, warmContainers } from "./uiSchemaClient";

const FAVORITES_KEY = "xbsl.formPalette.favorites";
const USAGE_KEY = "xbsl.formPalette.usage";
const DOUBLE_ACTIVATE_MS = 450;

export interface ProjectComponentRef {
  name: string;
  yamlPath: string;
}

export interface FormPaletteDeps {
  projectComponents: () => Promise<ProjectComponentRef[]>;
  structure: FormStructureController;
}

type PaletteElement =
  | { kind: "section"; model: PaletteSectionModel }
  | { kind: "component"; sectionId: string; item: PaletteItemModel }
  | { kind: "hint" };

class FormPaletteProvider
  implements vscode.TreeDataProvider<PaletteElement>, vscode.TreeDragAndDropController<PaletteElement>
{
  private readonly emitter = new vscode.EventEmitter<PaletteElement | undefined | void>();
  readonly onDidChangeTreeData = this.emitter.event;

  readonly dragMimeTypes = [PALETTE_MIME];
  readonly dropMimeTypes: string[] = [];

  private sections?: PaletteSectionModel[];
  private loading?: Promise<void>;
  private lastActivation?: { name: string; at: number };
  private hintShown = false;

  constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly deps: FormPaletteDeps
  ) {}

  // --- state ------------------------------------------------------------------------------

  private favorites(): string[] {
    return this.context.globalState.get<string[]>(FAVORITES_KEY) ?? [];
  }

  private usage(): Record<string, number> {
    return this.context.globalState.get<Record<string, number>>(USAGE_KEY) ?? {};
  }

  isFavorite(name: string): boolean {
    return this.favorites().includes(name);
  }

  async setFavorite(name: string, value: boolean): Promise<void> {
    const current = new Set(this.favorites());
    if (value) {
      current.add(name);
    } else {
      current.delete(name);
    }
    await this.context.globalState.update(FAVORITES_KEY, [...current]);
    await this.rebuild();
  }

  async noteInserted(name: string): Promise<void> {
    await this.context.globalState.update(USAGE_KEY, bumpUsage(this.usage(), name));
    await this.rebuild();
  }

  // --- loading ----------------------------------------------------------------------------

  private async ensureLoaded(): Promise<void> {
    if (this.sections) {
      return;
    }
    if (!this.loading) {
      this.loading = this.rebuild().finally(() => {
        this.loading = undefined;
      });
    }
    await this.loading;
  }

  async rebuild(): Promise<void> {
    const catalog = lspActive() ? await uiCatalog() : { available: false as const };
    let project: string[] = [];
    try {
      project = (await this.deps.projectComponents()).map((c) => c.name);
    } catch {
      // no workspace model - the platform sections still work
    }
    this.sections = buildPalette(catalog, project, this.favorites(), this.usage());
    if (catalog.available) {
      // Learn the Содержимое-slot container set in the background: the structure view then
      // paints container icons and plans drops for types beyond the static fallback list.
      warmContainers(() => this.deps.structure.repaint());
    }
    this.emitter.fire(undefined);
  }

  refresh(): void {
    resetUiSchemaCache();
    this.sections = undefined;
    void this.ensureLoaded();
  }

  // The first paint may race the LSP handshake: sections built without the catalog are
  // rebuilt once the view shows up again with a live server.
  reloadIfDegraded(): void {
    if (this.sections?.some((s) => s.kind === "hint") && lspActive()) {
      void this.rebuild();
    }
  }

  // --- TreeDataProvider -------------------------------------------------------------------

  async getChildren(element?: PaletteElement): Promise<PaletteElement[]> {
    if (!element) {
      await this.ensureLoaded();
      return (this.sections ?? []).map((model): PaletteElement =>
        model.kind === "hint" ? { kind: "hint" } : { kind: "section", model }
      );
    }
    if (element.kind === "section") {
      return element.model.items.map((item): PaletteElement => ({
        kind: "component",
        sectionId: element.model.id,
        item,
      }));
    }
    return [];
  }

  getTreeItem(element: PaletteElement): vscode.TreeItem {
    if (element.kind === "hint") {
      const item = new vscode.TreeItem(
        vscode.l10n.t("Component catalog data is not generated"),
        vscode.TreeItemCollapsibleState.None
      );
      item.id = "palette:hint";
      item.iconPath = new vscode.ThemeIcon("info");
      item.tooltip = vscode.l10n.t(
        "The ui schema (uischema.json) is missing from the Element dataset. Generate it from your distribution documentation (tools/extract_uischema.py) – the platform component sections will appear here. The structure view works regardless."
      );
      item.contextValue = "palettehint";
      return item;
    }
    if (element.kind === "section") {
      const model = element.model;
      const label =
        model.kind === "frequent"
          ? vscode.l10n.t("Frequent")
          : model.kind === "favorites"
            ? vscode.l10n.t("Favorites")
            : model.kind === "project"
              ? vscode.l10n.t("Project components")
              : model.packageLabel || vscode.l10n.t("Components");
      const expanded = model.kind !== "package";
      const item = new vscode.TreeItem(
        label,
        expanded ? vscode.TreeItemCollapsibleState.Expanded : vscode.TreeItemCollapsibleState.Collapsed
      );
      item.id = `palette:section:${model.id}`;
      item.description = String(model.items.length);
      item.iconPath = new vscode.ThemeIcon(
        model.kind === "frequent"
          ? "history"
          : model.kind === "favorites"
            ? "star-full"
            : model.kind === "project"
              ? "project"
              : "package"
      );
      item.contextValue = "palettesection";
      return item;
    }
    const { item: model, sectionId } = element;
    const item = new vscode.TreeItem(model.name, vscode.TreeItemCollapsibleState.None);
    item.id = `palette:item:${sectionId}:${model.name}`;
    item.iconPath = new vscode.ThemeIcon(model.origin === "project" ? "window" : "symbol-field");
    if (sectionId === "frequent" || sectionId === "favorites") {
      item.description =
        model.origin === "project"
          ? vscode.l10n.t("project")
          : model.packageName?.split("::").filter(Boolean).pop() ?? "";
    }
    const tip = new vscode.MarkdownString();
    tip.appendMarkdown(`**${model.name}**`);
    if (model.since) {
      tip.appendMarkdown(` · ${vscode.l10n.t("since version {0}", model.since)}`);
    }
    if (model.doc) {
      tip.appendMarkdown(`\n\n${model.doc}`);
    }
    tip.appendMarkdown(`\n\n${vscode.l10n.t("Double click / Enter twice inserts into the structure selection.")}`);
    item.tooltip = tip;
    item.contextValue = `palettecomponent ${this.isFavorite(model.name) ? "palettefav" : "palettenonfav"}`;
    item.command = { command: "xbsl.formPalette.activate", title: "", arguments: [element] };
    return item;
  }

  // --- activation and insertion -----------------------------------------------------------

  // First activation arms the item, a second one within the window (double click or Enter
  // twice) inserts - a plain single click must not modify the yaml.
  async activate(element: PaletteElement): Promise<void> {
    if (element.kind !== "component") {
      return;
    }
    const now = Date.now();
    const double =
      !!this.lastActivation &&
      this.lastActivation.name === element.item.name &&
      now - this.lastActivation.at < DOUBLE_ACTIVATE_MS;
    this.lastActivation = { name: element.item.name, at: now };
    if (double) {
      await this.insert(element);
    } else if (!this.hintShown) {
      this.hintShown = true;
      vscode.window.setStatusBarMessage(
        vscode.l10n.t("XBSL: double click (or Enter twice) inserts the component into the form."),
        3000
      );
    }
  }

  async insert(element?: PaletteElement): Promise<void> {
    if (!element || element.kind !== "component") {
      return;
    }
    if (await this.deps.structure.insertComponentType(element.item.name)) {
      await this.noteInserted(element.item.name);
    }
  }

  async openDocs(element?: PaletteElement): Promise<void> {
    if (!element || element.kind !== "component") {
      return;
    }
    const name = element.item.name;
    const hits = await docsSearch(name, 12);
    const best = hits.find((h) => h.title === name) ?? hits.find((h) => h.qualified?.endsWith(name)) ?? hits[0];
    if (!best) {
      void vscode.window.showInformationMessage(vscode.l10n.t('XBSL: no documentation for "{0}".', name));
      return;
    }
    await openPage(this.context, best.id);
  }

  // --- drag and drop (the palette is a drag source only) ----------------------------------

  handleDrag(source: readonly PaletteElement[], dataTransfer: vscode.DataTransfer): void {
    const component = source.find((el): el is Extract<PaletteElement, { kind: "component" }> => el.kind === "component");
    if (!component) {
      return; // sections and the hint are not draggable
    }
    dataTransfer.set(
      PALETTE_MIME,
      new vscode.DataTransferItem(encodePaletteDrag({ componentType: component.item.name }))
    );
  }

  handleDrop(): void {
    // Nothing can be dropped into the palette.
  }
}

export function registerFormPalette(context: vscode.ExtensionContext, deps: FormPaletteDeps): void {
  const provider = new FormPaletteProvider(context, deps);
  const view = vscode.window.createTreeView<PaletteElement>("xbslFormPalette", {
    treeDataProvider: provider,
    dragAndDropController: provider,
  });
  // DnD inserts land in the structure view; count them into Frequent from here.
  deps.structure.setInsertListener((type) => void provider.noteInserted(type));

  context.subscriptions.push(
    view,
    view.onDidChangeVisibility((e) => {
      if (e.visible) {
        provider.reloadIfDegraded();
      }
    }),
    vscode.commands.registerCommand("xbsl.formPalette.refresh", () => provider.refresh()),
    vscode.commands.registerCommand("xbsl.formPalette.activate", (el: PaletteElement) => void provider.activate(el)),
    vscode.commands.registerCommand("xbsl.formPalette.insert", (el?: PaletteElement) => void provider.insert(el)),
    vscode.commands.registerCommand("xbsl.formPalette.addFavorite", (el?: PaletteElement) => {
      if (el?.kind === "component") {
        void provider.setFavorite(el.item.name, true);
      }
    }),
    vscode.commands.registerCommand("xbsl.formPalette.removeFavorite", (el?: PaletteElement) => {
      if (el?.kind === "component") {
        void provider.setFavorite(el.item.name, false);
      }
    }),
    vscode.commands.registerCommand("xbsl.formPalette.openDocs", (el?: PaletteElement) => void provider.openDocs(el))
  );
}
