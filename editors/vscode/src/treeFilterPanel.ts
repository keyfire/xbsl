// The form of the metadata tree filter: a tree of checkboxes over the subsystems and packages of
// the projects, in a webview panel of its own. The panel is a thin view - every click goes to the
// extension, treeFilterCore computes the new choice and the three states, and the webview only
// paints them. The choice being edited lives here until "Apply"; the tree keeps the applied one.
//
// The panel does not come back after a restart (no serializer): it is a dialog over the tree,
// and the choice it would restore is already applied or deliberately dropped.

import * as vscode from "vscode";
import {
  canonicalSelection,
  FilterNode,
  FilterTree,
  hasChoice,
  nodeStates,
  packagesKnown,
  PlaceRename,
  renamePlaceKeys,
  selectAll,
  selectedCount,
  Selection,
  toggleNode,
} from "./treeFilterCore";
import { cspMeta, escapeHtml, makeNonce } from "./webviewShared";

const VIEW_TYPE = "xbsl.treeFilter";

export interface TreeFilterHost {
  // The tree of checkboxes as the model and the engine's last answer draw it; `pending` - the
  // engine is asked and has not answered yet.
  form(): Promise<{ tree: FilterTree; pending: boolean }>;
  selection(): Selection; // the choice the tree is filtered by now
  apply(selection: Selection): Promise<void>;
  readonly onDidChange: vscode.Event<void>; // the files or the engine's answer changed
}

interface WebNode {
  id: string;
  kind: string;
  label: string;
  count: number;
  title?: string;
  children: WebNode[];
}

export class TreeFilterPanel {
  private static current: TreeFilterPanel | undefined;
  private tree: FilterTree = { projects: [] };
  private working: Selection = new Map();
  private pending = false;
  private loaded = false; // the tree was read at least once
  private ready = false; // the script of the webview listens
  private disposed = false;
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(private readonly panel: vscode.WebviewPanel, private readonly host: TreeFilterHost) {
    panel.onDidDispose(() => this.dispose(), null, this.disposables);
    panel.webview.onDidReceiveMessage((m) => void this.onMessage(m), null, this.disposables);
    host.onDidChange(() => void this.reload(false), null, this.disposables);
    panel.webview.html = this.html();
  }

  public static async show(host: TreeFilterHost): Promise<void> {
    const open = TreeFilterPanel.current;
    if (open) {
      // Called again while the form is open: the choice being edited stays.
      open.panel.reveal(vscode.ViewColumn.Active);
      await open.reload(false);
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      VIEW_TYPE,
      vscode.l10n.t("Filter by subsystems and packages"),
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true }
    );
    const created = new TreeFilterPanel(panel, host);
    TreeFilterPanel.current = created;
    await created.reload(true);
  }

  /** Keys of packages renamed from the tree move in the choice being edited too, at the moment
   * they move in the applied one: otherwise the next reload drops the old key from this choice,
   * and "Apply" writes a filter without the package. */
  public static followRenames(renames: readonly PlaceRename[]): void {
    const open = TreeFilterPanel.current;
    if (open) {
      open.working = renames.reduce((selection, rename) => renamePlaceKeys(selection, rename), open.working);
    }
  }

  // Read the tree again. The choice being edited is written back against it, so a package deleted
  // meanwhile leaves the choice here the same way it leaves the stored one.
  private async reload(fromApplied: boolean): Promise<void> {
    const { tree, pending } = await this.host.form();
    if (this.disposed) {
      return;
    }
    this.tree = tree;
    this.pending = pending;
    this.loaded = true;
    this.working = canonicalSelection(tree, fromApplied ? this.host.selection() : this.working);
    this.post("tree");
  }

  private async onMessage(msg: { type?: string; id?: unknown }): Promise<void> {
    switch (msg?.type) {
      case "ready":
        this.ready = true;
        this.post("tree");
        return;
      case "toggle":
        if (typeof msg.id === "string") {
          this.working = toggleNode(this.tree, this.working, msg.id);
          this.post("states");
        }
        return;
      case "all":
        this.working = selectAll(this.tree, this.working);
        this.post("states");
        return;
      case "none":
        this.working = new Map();
        this.post("states");
        return;
      case "apply":
        await this.host.apply(canonicalSelection(this.tree, this.working));
        this.panel.dispose();
        return;
      case "reset":
        await this.host.apply(new Map());
        this.panel.dispose();
        return;
      case "cancel":
        this.panel.dispose();
        return;
    }
  }

  private webNodes(): WebNode[] {
    const toWeb = (node: FilterNode): WebNode => ({
      id: node.id,
      kind: node.kind,
      label: node.kind === "loose" ? vscode.l10n.t("Objects outside packages") : node.name,
      count: node.count,
      title: node.title,
      children: node.children.map(toWeb),
    });
    // One project needs no level of its own: its subsystems are the top of the form.
    const top = this.tree.projects.length === 1 ? this.tree.projects[0].children : this.tree.projects;
    return top.map(toWeb);
  }

  private post(kind: "tree" | "states"): void {
    if (!this.ready || !this.loaded || this.disposed) {
      return;
    }
    const projects = this.tree.projects.map((p) => p.project);
    const chosen = hasChoice(this.working, projects);
    const message: Record<string, unknown> = {
      type: kind,
      states: Object.fromEntries(nodeStates(this.tree, this.working)),
      status: chosen
        ? vscode.l10n.t("Objects selected: {0}", selectedCount(this.tree, this.working))
        : vscode.l10n.t("Nothing is selected: the tree is shown without a filter."),
      applied: hasChoice(this.host.selection(), projects),
    };
    if (kind === "tree") {
      message.nodes = this.webNodes();
      message.empty = vscode.l10n.t("No subsystems found.");
      message.note = this.pending
        ? vscode.l10n.t("The packages are on the way: the xbsl engine has not answered yet.")
        : packagesKnown(this.tree)
          ? ""
          : vscode.l10n.t("Packages are not available: the xbsl engine did not list them, so only subsystems are shown.");
    }
    void this.panel.webview.postMessage(message);
  }

  private dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    if (TreeFilterPanel.current === this) {
      TreeFilterPanel.current = undefined;
    }
    this.panel.dispose();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }

  private html(): string {
    const nonce = makeNonce();
    const t = {
      title: vscode.l10n.t("Filter by subsystems and packages"),
      lead: vscode.l10n.t("The metadata tree keeps the checked subsystems and packages. Nothing checked means no filter."),
      tree: vscode.l10n.t("Subsystems and packages"),
      selectAll: vscode.l10n.t("Select all"),
      clearAll: vscode.l10n.t("Clear all"),
      apply: vscode.l10n.t("Apply"),
      reset: vscode.l10n.t("Reset the filter"),
      cancel: vscode.l10n.t("Cancel"),
    };
    return `<!DOCTYPE html><html><head><meta charset="utf-8">${cspMeta(nonce)}
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size);
    color: var(--vscode-foreground); padding: 12px 16px; max-width: 760px; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  p { margin: 0; }
  .lead { color: var(--vscode-descriptionForeground); margin-bottom: 10px; }
  .bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 8px 0; }
  button { font: inherit; border: none; border-radius: 2px; padding: 4px 12px; cursor: pointer;
    background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  button:hover { background: var(--vscode-button-secondaryHoverBackground); }
  button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
  button.primary:hover { background: var(--vscode-button-hoverBackground); }
  button:disabled { opacity: .5; cursor: default; }
  button:focus-visible, input:focus-visible { outline: 1px solid var(--vscode-focusBorder); outline-offset: 1px; }
  .note { color: var(--vscode-editorWarning-foreground); margin: 4px 0 8px; }
  .empty, .status { color: var(--vscode-descriptionForeground); margin: 8px 0; }
  ul { list-style: none; margin: 0; padding: 0; }
  #tree { border: 1px solid var(--vscode-panel-border, rgba(128, 128, 128, .35)); max-height: 62vh;
    overflow: auto; padding: 4px 0; }
  .row { display: flex; align-items: center; gap: 4px; padding: 2px 8px 2px 4px; }
  .row:hover { background: var(--vscode-list-hoverBackground); }
  .twisty { display: inline-block; width: 14px; text-align: center; flex: none; user-select: none;
    color: var(--vscode-descriptionForeground); cursor: pointer; }
  li[aria-expanded="true"] > .row > .twisty { transform: rotate(90deg); }
  label { display: inline-flex; align-items: center; gap: 6px; flex: 1; min-width: 0; cursor: pointer; }
  input[type=checkbox] { margin: 0; accent-color: var(--vscode-button-background); }
  .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .name.loose { font-style: italic; color: var(--vscode-descriptionForeground); }
  .count { color: var(--vscode-descriptionForeground); font-variant-numeric: tabular-nums; margin-left: 12px; }
</style></head><body>
<h1>${escapeHtml(t.title)}</h1>
<p class="lead">${escapeHtml(t.lead)}</p>
<div class="bar">
  <button id="all">${escapeHtml(t.selectAll)}</button>
  <button id="none">${escapeHtml(t.clearAll)}</button>
</div>
<p class="note" id="note" hidden></p>
<p class="empty" id="empty" hidden></p>
<ul id="tree" role="tree" aria-multiselectable="true" aria-label="${escapeHtml(t.tree)}"></ul>
<p class="status" id="status" aria-live="polite"></p>
<div class="bar">
  <button id="apply" class="primary">${escapeHtml(t.apply)}</button>
  <button id="reset">${escapeHtml(t.reset)}</button>
  <button id="cancel">${escapeHtml(t.cancel)}</button>
</div>
<script nonce="${nonce}">
  const vscodeApi = acquireVsCodeApi();
  const treeEl = document.getElementById("tree");
  const saved = vscodeApi.getState();
  // Folded nodes survive a new answer of the engine, which rebuilds the whole list.
  const collapsed = new Set(saved && saved.collapsed ? saved.collapsed : []);
  const remember = () => vscodeApi.setState({ collapsed: Array.from(collapsed) });
  const send = (type, id) => vscodeApi.postMessage({ type, id });
  let first = true;

  const isOpen = (li) => li.getAttribute("aria-expanded") === "true";
  function setOpen(li, open) {
    li.setAttribute("aria-expanded", String(open));
    li.querySelector(":scope > ul").hidden = !open;
    if (open) { collapsed.delete(li.dataset.id); } else { collapsed.add(li.dataset.id); }
    remember();
  }
  const visibleBoxes = () =>
    Array.from(treeEl.querySelectorAll("input[type=checkbox]")).filter((box) => box.offsetParent !== null);

  // Space toggles the focused checkbox natively; the arrows walk and fold the tree, Enter applies.
  function onKey(event) {
    const box = event.currentTarget;
    const li = box.closest("li");
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      const boxes = visibleBoxes();
      const next = boxes[boxes.indexOf(box) + (event.key === "ArrowDown" ? 1 : -1)];
      if (next) { next.focus(); }
    } else if (event.key === "ArrowRight") {
      if (li.hasAttribute("aria-expanded") && !isOpen(li)) { setOpen(li, true); }
    } else if (event.key === "ArrowLeft") {
      if (li.hasAttribute("aria-expanded") && isOpen(li)) {
        setOpen(li, false);
      } else {
        const parent = li.parentElement.closest("li");
        if (parent) { parent.querySelector("input").focus(); }
      }
    } else if (event.key === "Enter") {
      send("apply");
    } else {
      return;
    }
    event.preventDefault();
  }

  function item(node, level) {
    const li = document.createElement("li");
    li.setAttribute("role", "treeitem");
    li.setAttribute("aria-level", String(level));
    li.dataset.id = node.id;
    const row = document.createElement("div");
    row.className = "row";
    row.style.paddingLeft = (4 + (level - 1) * 18) + "px";
    if (node.title) { row.title = node.title; }
    const twisty = document.createElement("span");
    twisty.className = "twisty";
    twisty.setAttribute("aria-hidden", "true");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.dataset.id = node.id;
    box.addEventListener("change", () => send("toggle", node.id));
    box.addEventListener("keydown", onKey);
    const name = document.createElement("span");
    name.className = node.kind === "loose" ? "name loose" : "name";
    name.textContent = node.label;
    label.append(box, name);
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(node.count);
    row.append(twisty, label, count);
    li.append(row);
    if (node.children.length) {
      const open = !collapsed.has(node.id);
      li.setAttribute("aria-expanded", String(open));
      twisty.textContent = "\\u25B8";
      twisty.addEventListener("click", () => setOpen(li, !isOpen(li)));
      const group = document.createElement("ul");
      group.setAttribute("role", "group");
      group.hidden = !open;
      node.children.forEach((child) => group.append(item(child, level + 1)));
      li.append(group);
    }
    return li;
  }

  function paintStates(msg) {
    for (const box of treeEl.querySelectorAll("input[type=checkbox]")) {
      const state = msg.states[box.dataset.id] || "unchecked";
      box.checked = state === "checked";
      box.indeterminate = state === "mixed";
      box.closest("li").setAttribute("aria-checked", state === "mixed" ? "mixed" : String(state === "checked"));
    }
    document.getElementById("status").textContent = msg.status;
    document.getElementById("reset").disabled = !msg.applied;
  }

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || !msg.states) { return; }
    if (msg.type === "tree") {
      const focused = document.activeElement && document.activeElement.dataset
        ? document.activeElement.dataset.id : undefined;
      treeEl.textContent = "";
      msg.nodes.forEach((node) => treeEl.append(item(node, 1)));
      const note = document.getElementById("note");
      note.textContent = msg.note;
      note.hidden = !msg.note;
      const empty = document.getElementById("empty");
      empty.textContent = msg.empty;
      empty.hidden = msg.nodes.length > 0;
      treeEl.hidden = msg.nodes.length === 0;
      const again = focused ? treeEl.querySelector('input[data-id="' + CSS.escape(focused) + '"]') : null;
      if (again) {
        again.focus();
      } else if (first && visibleBoxes().length) {
        visibleBoxes()[0].focus();
      }
      first = false;
    }
    paintStates(msg);
  });

  document.getElementById("all").addEventListener("click", () => send("all"));
  document.getElementById("none").addEventListener("click", () => send("none"));
  document.getElementById("apply").addEventListener("click", () => send("apply"));
  document.getElementById("reset").addEventListener("click", () => send("reset"));
  document.getElementById("cancel").addEventListener("click", () => send("cancel"));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { send("cancel"); }
  });
  send("ready");
</script></body></html>`;
  }
}
