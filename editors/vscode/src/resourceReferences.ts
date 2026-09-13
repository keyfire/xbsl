// "Find All References" on a resource file or a folder of the metadata tree. The engine finds the
// places that name it, reading the sources the way a move of the resource does
// (xbsl/metaResourceReferences, or the CLI resource-references). The editor's own References view
// lists them like the result of "Find All References": by file, with a preview of the line, and F4
// goes to the next place. The view comes from a built-in extension; without it a quick pick lists
// the places instead.

import * as vscode from "vscode";
import { queryEngine } from "./engineMeta";
import { pathKey } from "./packagesCore";
import { ResourceNodeLike, ResourceTreeAccess } from "./resourceFolders";
import { isResourcesDescriptor, resourcePathOf } from "./resourceFoldersCore";
import {
  EngineResourceReference,
  groupByFile,
  linePreview,
  nearestPlace,
  PlaceIndex,
  rangeFragment,
  ReferenceFile,
  ResourceReferencesAnswer,
  stepPlace,
} from "./resourceReferencesCore";

// The contract of the References view, in the shape this module uses. The built-in extension
// vscode.references-view returns it from its activation (its references-view.d.ts types it).
interface SymbolTree {
  setInput(input: SymbolTreeInput<unknown>): void;
}

interface SymbolTreeInput<T> {
  readonly contextValue: string;
  readonly title: string;
  // The view opens this document and needs a word at this position: the first place serves.
  readonly location: vscode.Location;
  resolve(): vscode.ProviderResult<SymbolTreeModel<T>>;
  with(location: vscode.Location): SymbolTreeInput<T>;
}

interface SymbolTreeModel<T> {
  message: string | undefined;
  provider: vscode.TreeDataProvider<T>;
  navigation?: {
    nearest(uri: vscode.Uri, position: vscode.Position): T | undefined;
    next(from: T): T;
    previous(from: T): T;
    location(item: T): vscode.Location | undefined;
  };
  highlights?: { getEditorHighlights(item: T, uri: vscode.Uri): vscode.Range[] | undefined };
  dnd?: { getDragUri(item: T): vscode.Uri | undefined };
}

interface ResourceQuery {
  root: string; // the root the engine looks for the places under
  target: string; // the file or the folder, a file system path
  key: string; // its path under the resources folder - the name the messages use
}

function askEngine(query: ResourceQuery): Thenable<ResourceReferencesAnswer | undefined> {
  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: vscode.l10n.t("XBSL: looking for what names {0}...", query.key),
    },
    () => queryEngine<ResourceReferencesAnswer>(
      "xbsl/metaResourceReferences", { root: query.root, path: query.target },
      "resource-references", [query.root, query.target], query.root
    )
  );
}

function rangeOf(reference: EngineResourceReference): vscode.Range {
  const { start, end } = reference.range;
  return new vscode.Range(start.line, start.character, end.line, end.character);
}

function sameFile(path: string, uri: vscode.Uri): boolean {
  return pathKey(path) === pathKey(uri.fsPath);
}

// What a place is, when it is not a plain reference: the row says it in grey, the tooltip explains.
function kindDescription(kind: string): string | undefined {
  switch (kind) {
    case "ambiguous":
      return vscode.l10n.t("key in several folders");
    case "string":
      return vscode.l10n.t("by a string");
    case "computed":
      return vscode.l10n.t("computed name");
    default:
      return undefined;
  }
}

function kindTooltip(kind: string): string | undefined {
  switch (kind) {
    case "ambiguous":
      return vscode.l10n.t("Another resources folder this file sees holds the same key, so the reference may lead to either file.");
    case "string":
      return vscode.l10n.t("A string with the path: the file is looked up by it at run time.");
    case "computed":
      return vscode.l10n.t("A string with the folder and a computed file name: at run time it may name this file.");
    default:
      return undefined;
  }
}

class FileItem {
  readonly places: PlaceItem[];

  constructor(readonly file: ReferenceFile, readonly index: number) {
    this.places = file.references.map((reference, place) => new PlaceItem(this, reference, place));
  }

  get uri(): vscode.Uri {
    return vscode.Uri.file(this.file.path);
  }
}

class PlaceItem {
  constructor(readonly parent: FileItem, readonly reference: EngineResourceReference, readonly index: number) {}

  get location(): vscode.Location {
    return new vscode.Location(this.parent.uri, rangeOf(this.reference));
  }
}

type Item = FileItem | PlaceItem;

class PlacesProvider implements vscode.TreeDataProvider<Item> {
  constructor(private readonly files: FileItem[]) {}

  getTreeItem(item: Item): vscode.TreeItem {
    if (item instanceof FileItem) {
      const row = new vscode.TreeItem(item.uri, vscode.TreeItemCollapsibleState.Expanded);
      row.contextValue = "xbslResourceReferenceFile";
      row.description = true; // the folder of the file, the way the view shows every file
      row.iconPath = vscode.ThemeIcon.File;
      return row;
    }
    const { reference } = item;
    const preview = linePreview(reference.text, reference.range.start.character, reference.range.end.character);
    const row = new vscode.TreeItem({ label: preview.label, highlights: [preview.highlight] });
    row.contextValue = "xbslResourceReferencePlace";
    row.description = kindDescription(reference.kind);
    const where = `${vscode.workspace.asRelativePath(item.parent.file.path)}:${reference.range.start.line + 1}`;
    const why = kindTooltip(reference.kind);
    row.tooltip = why ? `${why}\n${where}` : where;
    row.command = { command: "vscode.open", title: "", arguments: [item.parent.uri, { selection: item.location.range }] };
    return row;
  }

  getChildren(item?: Item): Item[] {
    if (item === undefined) {
      return this.files;
    }
    return item instanceof FileItem ? item.places : [];
  }

  getParent(item: Item): Item | undefined {
    return item instanceof PlaceItem ? item.parent : undefined;
  }
}

function modelOf(query: ResourceQuery, answer: ResourceReferencesAnswer): SymbolTreeModel<Item> {
  const references = answer.references ?? [];
  const grouped = groupByFile(references);
  const files = grouped.map((file, index) => new FileItem(file, index));
  const placeAt = ([file, place]: PlaceIndex): PlaceItem => files[file].places[place];
  const step = (from: Item, forward: boolean): PlaceItem => {
    if (from instanceof FileItem) {
      return forward ? from.places[0] : placeAt(stepPlace(grouped, [from.index, 0], false));
    }
    return placeAt(stepPlace(grouped, [from.parent.index, from.index], forward));
  };
  return {
    message: vscode.l10n.t("{0} – places: {1}, files: {2}", query.key, String(references.length), String(files.length)),
    provider: new PlacesProvider(files),
    navigation: {
      nearest: (uri, position) => {
        const at = nearestPlace(grouped, (path) => sameFile(path, uri), position);
        return at ? placeAt(at) : undefined;
      },
      next: (from) => step(from, true),
      previous: (from) => step(from, false),
      location: (item) =>
        item instanceof PlaceItem ? item.location : new vscode.Location(item.uri, new vscode.Position(0, 0)),
    },
    highlights: {
      getEditorHighlights: (item, uri) => {
        const file = item instanceof FileItem ? item : item.parent;
        return sameFile(file.file.path, uri) ? file.places.map((place) => place.location.range) : undefined;
      },
    },
    dnd: {
      getDragUri: (item) =>
        item instanceof FileItem ? item.uri : item.parent.uri.with({ fragment: rangeFragment(item.reference.range) }),
    },
  };
}

class ReferencesInput implements SymbolTreeInput<Item> {
  readonly contextValue = "xbslResourceReferences";
  readonly title = vscode.l10n.t("Resource references");

  constructor(
    readonly location: vscode.Location,
    private readonly query: ResourceQuery,
    private answer?: ResourceReferencesAnswer
  ) {}

  // The first showing takes the answer the command already has; a refresh of the view asks the
  // engine again, since the sources may have changed since.
  async resolve(): Promise<SymbolTreeModel<Item> | undefined> {
    const answer = this.answer ?? (await askEngine(this.query));
    this.answer = undefined;
    if (answer?.error) {
      void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", answer.error));
    }
    return answer?.references?.length ? modelOf(this.query, answer) : undefined;
  }

  with(location: vscode.Location): ReferencesInput {
    return new ReferencesInput(location, this.query);
  }
}

async function referencesView(): Promise<SymbolTree | undefined> {
  const extension = vscode.extensions.getExtension<SymbolTree>("vscode.references-view");
  if (!extension) {
    return undefined;
  }
  try {
    const api = extension.isActive ? extension.exports : await extension.activate();
    return typeof api?.setInput === "function" ? api : undefined;
  } catch {
    return undefined;
  }
}

// Without the References view: the places in a quick pick, grouped by file, and the pick opens one.
async function pickPlace(query: ResourceQuery, references: EngineResourceReference[]): Promise<void> {
  interface Place extends vscode.QuickPickItem {
    reference?: EngineResourceReference;
  }
  const items: Place[] = [];
  for (const file of groupByFile(references)) {
    items.push({ label: vscode.workspace.asRelativePath(file.path), kind: vscode.QuickPickItemKind.Separator });
    for (const reference of file.references) {
      const { label } = linePreview(reference.text, reference.range.start.character, reference.range.end.character);
      items.push({
        label,
        description: String(reference.range.start.line + 1),
        detail: kindDescription(reference.kind),
        reference,
      });
    }
  }
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t("Places that name {0}", query.key),
    matchOnDescription: true,
  });
  if (pick?.reference) {
    await vscode.commands.executeCommand("vscode.open", vscode.Uri.file(pick.reference.path), {
      selection: rangeOf(pick.reference),
    });
  }
}

async function findReferences(access: ResourceTreeAccess, node?: ResourceNodeLike): Promise<void> {
  const resource = node?.resource;
  if (!resource?.path || isResourcesDescriptor(resource)) {
    return; // the resources folder itself and its description are named by no key
  }
  const target = resourcePathOf(resource);
  const root = access.rootFor(target);
  if (!root) {
    return;
  }
  const query: ResourceQuery = { root, target, key: resource.path };
  const answer = await askEngine(query);
  if (!answer) {
    return;
  }
  if (answer.error) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", answer.error));
    return;
  }
  const references = answer.references ?? [];
  if (!references.length) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: nothing in the sources names {0}.", resource.path));
    return;
  }
  const view = await referencesView();
  if (!view) {
    await pickPlace(query, references);
    return;
  }
  const first = groupByFile(references)[0].references[0];
  view.setInput(new ReferencesInput(new vscode.Location(vscode.Uri.file(first.path), rangeOf(first).start), query, answer));
}

export function registerResourceReferenceCommands(context: vscode.ExtensionContext, access: ResourceTreeAccess): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.metadata.findResourceReferences", (n?: ResourceNodeLike) => findReferences(access, n))
  );
}
