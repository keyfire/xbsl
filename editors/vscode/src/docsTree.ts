// The "Documentation" view in the 1C:Element activity bar: the "Contents" tree of the Element
// help (sections -> types -> members) plus commands for search, opening a page and showing
// documentation for the symbol under the cursor. Data comes from the linter's LSP server
// (docsClient), pages are shown by docsPanel. The tree is built from a flat node list
// (id, parent) once and is re-read by the refresh button.

import * as vscode from "vscode";
import { DocNode, docsSearch, docsTree } from "./docsClient";
import { isXbslSource } from "./report";
import { openForSymbol, openPage, registerDocsPanel, setDocsOpenListener } from "./docsPanel";
import { ruleDoc, ruleOfCode } from "./ruleDocs";

const KIND_ICON: Record<string, string> = {
  section: "book",
  category: "symbol-namespace",
  link: "symbol-file",
  heading: "symbol-string",
};

// Heading nodes (sections inside a page) are colored to tell them apart from pages and categories.
const HEADING_COLOR = new vscode.ThemeColor("charts.blue");

const ROOT = -1; // key of the top-level tab sections group (their parent = null)

class DocsTreeProvider implements vscode.TreeDataProvider<number> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;
  private nodes = new Map<number, DocNode>();
  private children = new Map<number, number[]>();
  private byPage = new Map<string, number>();
  private view: vscode.TreeView<number> | undefined;
  private loaded = false;

  attach(view: vscode.TreeView<number>): void {
    this.view = view;
  }

  refresh(): void {
    this.loaded = false;
    this.changed.fire();
  }

  private async ensure(): Promise<void> {
    if (this.loaded) {
      return;
    }
    this.nodes.clear();
    this.children.clear();
    this.byPage.clear();
    for (const n of await docsTree()) {
      this.nodes.set(n.node, n);
      // For positioning (reveal): page -> the LINK node, not its headings (they share the same page).
      if (n.page && n.kind !== "heading") {
        this.byPage.set(n.page, n.node);
      }
      const key = n.parent ?? ROOT;
      const bucket = this.children.get(key);
      if (bucket) {
        bucket.push(n.node);
      } else {
        this.children.set(key, [n.node]);
      }
    }
    this.loaded = true;
  }

  // getParent is required for reveal: VS Code expands the chain of ancestors down to the node.
  async getParent(id: number): Promise<number | undefined> {
    await this.ensure();
    const n = this.nodes.get(id);
    return n && n.parent != null ? n.parent : undefined;
  }

  // Position the tree on a page (when it is open and such a node exists).
  async revealPage(pageId: string): Promise<void> {
    if (!this.view || !this.view.visible) {
      return; // the tree is not open - do not force it upon the user
    }
    await this.ensure();
    const node = this.byPage.get(pageId);
    if (node === undefined) {
      return; // the page is not in the tree (e.g. a type member) - nothing to position on
    }
    try {
      await this.view.reveal(node, { select: true, focus: false, expand: true });
    } catch {
      // the node may have vanished on refresh - silently skip
    }
  }

  async getChildren(element?: number): Promise<number[]> {
    await this.ensure();
    return this.children.get(element ?? ROOT) ?? [];
  }

  getTreeItem(id: number): vscode.TreeItem {
    const node = this.nodes.get(id);
    const hasChildren = (this.children.get(id) ?? []).length > 0;
    const kind = node?.kind ?? "link";
    const item = new vscode.TreeItem(
      node?.label ?? String(id),
      hasChildren ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
    );
    item.iconPath = new vscode.ThemeIcon(
      KIND_ICON[kind] ?? "symbol-file",
      kind === "heading" ? HEADING_COLOR : undefined
    );
    // A click opens the page for link and heading nodes (a heading - at its anchor);
    // a category/section merely expands.
    if (node?.page) {
      item.command = {
        command: "xbsl.docs.open",
        title: "",
        arguments: node.anchor ? [node.page, node.anchor] : [node.page],
      };
    }
    return item;
  }
}

// Documentation search: query string -> ranked hits -> a pick -> opening the page.
async function searchDocs(context: vscode.ExtensionContext): Promise<void> {
  const query = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Search the Element documentation"),
    placeHolder: vscode.l10n.t("method, property, type ..."),
  });
  if (!query) {
    return;
  }
  const hits = await docsSearch(query, 30);
  if (hits.length === 0) {
    void vscode.window.showInformationMessage(vscode.l10n.t('XBSL: nothing found for "{0}".', query));
    return;
  }
  const pick = await vscode.window.showQuickPick(
    hits.map((h) => ({
      label: h.title,
      description: h.qualified,
      detail: h.snippet || undefined,
      id: h.id,
    })),
    { placeHolder: vscode.l10n.t("Open a documentation page"), matchOnDescription: true, matchOnDetail: true }
  );
  if (pick) {
    await openPage(context, pick.id);
  }
}

// Action on a standard-backed rule diagnostic: open its document in the panel (and the tree).
class RuleDocActionProvider implements vscode.CodeActionProvider {
  provideCodeActions(
    _doc: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    const seen = new Set<string>();
    for (const d of context.diagnostics) {
      if (!isXbslSource(d)) {
        continue; // linter diagnostics only
      }
      const rule = ruleOfCode(d.code);
      const doc = ruleDoc(rule);
      if (!rule || !doc || seen.has(rule)) {
        continue;
      }
      seen.add(rule);
      const action = new vscode.CodeAction(
        vscode.l10n.t("XBSL: documentation for the rule {0}", rule),
        vscode.CodeActionKind.QuickFix
      );
      action.command = { command: "xbsl.docs.open", title: "", arguments: [doc.page, doc.anchor] };
      action.diagnostics = [d];
      actions.push(action);
    }
    return actions;
  }
}

export function registerDocs(context: vscode.ExtensionContext): void {
  const provider = new DocsTreeProvider();
  const view = vscode.window.createTreeView("xbslDocs", { treeDataProvider: provider });
  provider.attach(view);
  registerDocsPanel(context); // the panel survives a restart with the page it was showing
  // Opening a page in the panel positions the tree on that document.
  setDocsOpenListener((id) => void provider.revealPage(id));
  context.subscriptions.push(
    view,
    // The naming/* and project/* rules fire on .yaml, hence the provider also covers yaml.
    vscode.languages.registerCodeActionsProvider(
      [{ language: "xbsl" }, { language: "yaml" }],
      new RuleDocActionProvider(),
      { providedCodeActionKinds: [vscode.CodeActionKind.QuickFix] }
    ),
    vscode.commands.registerCommand("xbsl.docs.open", (id: string, anchor?: string) => openPage(context, id, anchor)),
    vscode.commands.registerCommand("xbsl.docs.search", () => searchDocs(context)),
    vscode.commands.registerCommand("xbsl.docs.showForSymbol", () => openForSymbol(context)),
    vscode.commands.registerCommand("xbsl.docs.refresh", () => provider.refresh())
  );
}
