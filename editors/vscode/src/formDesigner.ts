// The 1C:Element FORM PANEL - the designer's main surface. A form depends on its own
// properties, so its structure and its data are edited where the form is shown: the panel
// holds three areas - the structure tree on the left, the data of the form on the right and
// the wireframe frame under them, with draggable splitters between. The component palette
// stays in the sidebar next to the metadata tree and shows up only while this panel is open
// (the xbsl.formDesigner.open context key).
//
// The panel owns the LIFECYCLE of the designer: it follows the active form yaml, reloads the
// models on edits and diagnostics, and syncs the selection between the three areas, the yaml
// cursor and the "Properties" panel. The models themselves (formStructure.ts, formData.ts)
// are passive - they answer with flat row snapshots (formDesignerCore.ts) and perform the
// engine operations. The frame is rendered by formPreviewCore.ts and is a wireframe, not a
// render: the platform draws forms server-side.
//
// Trees inside a webview mean the tree work is ours: rows arrive flat, expansion, selection,
// the context menu, the keyboard and the drag and drop are implemented here. Dragging FROM
// the sidebar palette INTO a webview is not supported by the platform, which is why the
// palette inserts by a double click into the structure selection; dragging inside the panel
// (a node onto a node, a data record onto a node) works and is handled below.

import * as vscode from "vscode";
import {
  collectDataOffsets,
  collectResourceImages,
  esc,
  nearestOffset,
  renderFormPreview,
  restoredTargetUri,
  selectionForCursor,
} from "./formPreviewCore";
import { DataHost, DataSnapshot, FormDataController } from "./formData";
import { dataMenu, DEFAULT_LAYOUT, sanitizeLayout, structureMenu } from "./formDesignerCore";
import { FormStructureController, StructureHost, StructureSnapshot } from "./formStructure";
import { cspMeta, inlineJson, makeNonce } from "./webviewShared";

const VIEW_TYPE = "xbslFormPreview";
const DEBOUNCE_MS = 300;
const CURSOR_DEBOUNCE_MS = 150;
const STATE_KEY = "xbsl.formPreview.view";
const LAYOUT_KEY = "xbsl.formDesigner.layout";
//: The form the panel was showing, remembered per workspace so a restart brings the same
//: panel back (see the serializer in registerFormDesigner).
const TARGET_KEY = "xbsl.formPreview.target";
//: Set while the panel exists - the palette view in the metadata container follows it.
const OPEN_CONTEXT = "xbsl.formDesigner.open";

interface ViewState {
  zoom: number; // percent
  theme: "light" | "dark" | "editor";
}

const DEFAULT_VIEW: ViewState = { zoom: 100, theme: "light" };

let panel: vscode.WebviewPanel | undefined;
let target: vscode.Uri | undefined;
let timer: NodeJS.Timeout | undefined;
let view: ViewState = DEFAULT_VIEW;
let layout = DEFAULT_LAYOUT;
// Frame selection state. The webview keeps the visual class; this side owns the selected
// data-off so it survives re-renders (the frame html is rebuilt from scratch on every edit).
let selectedOffset: number | undefined;
let lastOffsets: number[] = [];
let freshTarget = false; // set on a target switch: the first good render derives the selection from the cursor
let cursorTimer: NodeJS.Timeout | undefined;
let suppressCursorSyncUntil = 0; // a click inside the panel moves the cursor itself - ignore the echo
let extContext: vscode.ExtensionContext | undefined;
let deps: DesignerDeps | undefined;
// The last snapshots, re-posted when a restored webview announces itself ("ready").
let lastStructure: StructureSnapshot | undefined;
let lastData: DataSnapshot | undefined;
let lastFrame: { body: string; title: string } | undefined;

export interface DesignerDeps {
  structure: FormStructureController;
  data: FormDataController;
}

// Whether the content looks like a form: an interface component with inheritance and content.
function looksLikeForm(doc: vscode.TextDocument): boolean {
  if (doc.languageId !== "yaml") {
    return false;
  }
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return head.includes("КомпонентИнтерфейса") && doc.getText().includes("Наследует");
}

// -- localized strings handed to the webview ---------------------------------------------------

function labels(): Record<string, string> {
  return {
    structure: vscode.l10n.t("Structure"),
    data: vscode.l10n.t("Data"),
    frame: vscode.l10n.t("Form"),
    light: vscode.l10n.t("Light"),
    dark: vscode.l10n.t("Dark"),
    editor: vscode.l10n.t("Editor theme"),
    refresh: vscode.l10n.t("Refresh"),
    filterNamed: vscode.l10n.t("Show named components only"),
    filterAll: vscode.l10n.t("Show all components"),
    resetFocus: vscode.l10n.t("Show the whole form"),
    addProperty: vscode.l10n.t("Add property"),
    readonly: vscode.l10n.t("This form is read-only – editing is disabled."),
    empty: vscode.l10n.t("Open a form yaml (КомпонентИнтерфейса)."),
    zoomIn: vscode.l10n.t("Zoom in"),
    zoomOut: vscode.l10n.t("Zoom out"),
  };
}

// The context-menu labels, by the short command id of formDesignerCore's menus. Kept here
// (not in the core) so the core stays free of vscode and its l10n.
function menuLabel(pane: "structure" | "data", command: string): string {
  if (pane === "data") {
    switch (command) {
      case "insert":
        return vscode.l10n.t("Insert into the form");
      case "addProperty":
        return vscode.l10n.t("Add property");
      case "renameProperty":
        return vscode.l10n.t("Rename property");
      case "retypeProperty":
        return vscode.l10n.t("Change property type");
      case "removeProperty":
        return vscode.l10n.t("Remove property");
      default:
        return command;
    }
  }
  switch (command) {
    case "openInEditor":
      return vscode.l10n.t("Show in yaml");
    case "editSelected":
      return vscode.l10n.t("Edit selected together...");
    case "moveUp":
      return vscode.l10n.t("Move up");
    case "moveDown":
      return vscode.l10n.t("Move down");
    case "wrap":
      return vscode.l10n.t("Wrap in a container...");
    case "unwrap":
      return vscode.l10n.t("Unwrap the container");
    case "duplicate":
      return vscode.l10n.t("Duplicate");
    case "rename":
      return vscode.l10n.t("Rename (Имя)");
    case "delete":
      return vscode.l10n.t("Delete component");
    case "copyYaml":
      return vscode.l10n.t("Copy the yaml fragment");
    case "pasteYaml":
      return vscode.l10n.t("Paste yaml from the clipboard");
    case "savePreset":
      return vscode.l10n.t("Save as a block preset");
    case "insertPreset":
      return vscode.l10n.t("Insert a block preset...");
    case "focusSubtree":
      return vscode.l10n.t("Focus on the subtree");
    default:
      return command;
  }
}

// -- the panel ---------------------------------------------------------------------------------

function targetDocument(): vscode.TextDocument | undefined {
  if (!target) {
    return undefined;
  }
  return vscode.workspace.textDocuments.find((d) => d.uri.toString() === target!.toString());
}

// Switching to another form drops the frame selection - offsets mean nothing across documents.
function setTarget(uri: vscode.Uri): void {
  if (target?.toString() !== uri.toString()) {
    selectedOffset = undefined;
    lastOffsets = [];
    freshTarget = true;
  }
  target = uri;
  deps?.structure.setTarget(uri);
  deps?.data.setTarget(uri);
  // Remembered for the next session: VS Code restores the tab, the serializer needs to know
  // WHICH form it was showing.
  void extContext?.workspaceState.update(TARGET_KEY, uri.toString());
}

function post(message: unknown): void {
  void panel?.webview.postMessage(message);
}

// Resource images resolved to data URIs (filename -> data URI, or null when not found in the
// project). Cached for the session - resource files rarely change while editing a form.
const resourceCache = new Map<string, string | null>();
const IMG_MIME: Record<string, string> = {
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
};

async function resolveResource(name: string): Promise<string | null> {
  const cached = resourceCache.get(name);
  if (cached !== undefined) {
    return cached;
  }
  let uri: string | null = null;
  try {
    const found = await vscode.workspace.findFiles(`**/Ресурсы/${name}`, undefined, 1);
    if (found.length) {
      const bytes = await vscode.workspace.fs.readFile(found[0]);
      const ext = name.slice(name.lastIndexOf(".")).toLowerCase();
      const mime = IMG_MIME[ext] ?? "application/octet-stream";
      uri = `data:${mime};base64,${Buffer.from(bytes).toString("base64")}`;
    }
  } catch {
    uri = null; // an unreadable resource keeps the placeholder
  }
  resourceCache.set(name, uri);
  return uri;
}

async function resolveResources(names: string[]): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  await Promise.all(
    names.map(async (name) => {
      const uri = await resolveResource(name);
      if (uri) {
        out[name] = uri;
      }
    })
  );
  return out;
}

// A monotonic render generation: an async render (it resolves resource images) must not clobber
// the webview with a stale result after a newer render started.
let renderSeq = 0;

async function renderFrame(): Promise<void> {
  if (!panel || !target) {
    return;
  }
  const doc = targetDocument();
  if (!doc) {
    return;
  }
  const my = ++renderSeq;
  const text = doc.getText();
  // Resolve resource images (Изображение: info.svg) to data URIs so the wireframe shows them.
  const resources = await resolveResources(collectResourceImages(text));
  if (my !== renderSeq || !panel || !target) {
    return; // a newer render started, or the panel closed, while resolving
  }
  const result = renderFormPreview(text, resources);
  let body: string;
  let title = "";
  if (result.ok) {
    body = result.html;
    title = result.title;
    panel.title = vscode.l10n.t("Form: {0}", result.title);
    lastOffsets = collectDataOffsets(result.html);
    if (selectedOffset !== undefined) {
      // The edit may have shifted the node - keep the selection on the nearest offset.
      selectedOffset = nearestOffset(lastOffsets, selectedOffset);
    } else if (freshTarget) {
      // First good render of this form: light up the node under the yaml cursor.
      const editor = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === target!.toString());
      if (editor) {
        selectedOffset = selectionForCursor(lastOffsets, doc.offsetAt(editor.selection.active));
      }
    }
    freshTarget = false;
  } else {
    // A transient parse error while typing: keep the selection, it remaps on the next
    // successful render; there is nothing to match the cursor against meanwhile.
    lastOffsets = [];
    if (result.reason === "parse") {
      body = `<p class="note">${esc(vscode.l10n.t("The yaml does not parse: {0}", result.detail ?? ""))}</p>`;
    } else {
      body = `<p class="note">${esc(vscode.l10n.t("No form content here (Наследует → Содержимое) – open a form yaml."))}</p>`;
    }
  }
  lastFrame = { body, title };
  post({ type: "frame", body, title, selected: selectedOffset ?? null });
}

function reload(): void {
  void deps?.structure.load();
  void deps?.data.load();
  void renderFrame();
}

function scheduleReload(): void {
  if (timer) {
    clearTimeout(timer);
  }
  timer = setTimeout(() => {
    timer = undefined;
    reload();
  }, DEBOUNCE_MS);
}

// Show a location in the yaml editor. On selection and edits the focus stays in the panel
// (preserveFocus); on an explicit "Show in yaml" / Ctrl+click it moves to the editor.
async function revealOffsetInEditor(offset: number, preserveFocus: boolean): Promise<void> {
  if (!target) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target);
  const pos = doc.positionAt(Math.min(offset, doc.getText().length));
  const existing = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === target!.toString());
  const editor = await vscode.window.showTextDocument(doc, {
    viewColumn: existing?.viewColumn ?? vscode.ViewColumn.One,
    preserveFocus,
    preview: false,
  });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// A click in the frame: the cursor onto the node's yaml line (no focus steal) and the node's
// properties into the sidebar "Properties" view; the structure row lights up too.
function selectFrameNode(offset: number): void {
  if (!target) {
    return;
  }
  void vscode.commands.executeCommand("xbsl.properties.showForNode", target.toString(), offset);
  void revealOffsetInEditor(offset, true);
  void syncStructureToOffset(offset);
}

// Yaml offset -> structure row: the panel asks the model (xbsl/formNodeAt) and reveals the row.
async function syncStructureToOffset(offset: number): Promise<void> {
  const id = await deps?.structure.nodeIdAt(offset);
  if (id && panel) {
    deps?.structure.setSelection([id]);
    post({ type: "revealRow", pane: "structure", id });
  }
}

// Yaml cursor -> frame highlight: the containing node is the closest data-off at or below the
// cursor. Purely visual follow - no focus moves and no properties-panel calls.
function syncCursorAt(cursor: number): void {
  if (!panel) {
    return;
  }
  if (lastOffsets.length) {
    const off = selectionForCursor(lastOffsets, cursor);
    if (off !== selectedOffset) {
      selectedOffset = off;
      post({ type: "highlight", offset: off ?? null });
    }
  }
  void syncStructureToOffset(cursor);
}

function isViewState(v: unknown): v is ViewState {
  const s = v as ViewState;
  return !!s && typeof s.zoom === "number" && (s.theme === "light" || s.theme === "dark" || s.theme === "editor");
}

// uri is passed when called from the metadata tree (the form is already open on the left) -
// then the target is taken from it, not from the active editor; the editor title button passes
// no uri, the target is the active yaml.
function openPanel(context: vscode.ExtensionContext, uri?: vscode.Uri): void {
  let docUri = uri;
  if (!docUri) {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "yaml") {
      void vscode.window.showInformationMessage(
        vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) to design it.")
      );
      return;
    }
    docUri = editor.document.uri;
  }
  const column = uri ? vscode.ViewColumn.One : vscode.ViewColumn.Beside;
  if (!panel) {
    adoptPanel(
      context,
      vscode.window.createWebviewPanel(VIEW_TYPE, "XBSL", column, {
        enableScripts: true,
        retainContextWhenHidden: true,
        localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "resources")],
      })
    );
  } else {
    // Reveal in the intended column (One from the tree, Beside from the title button), not the
    // panel's own stale column - otherwise a persistent panel drifts relative to the yaml.
    panel.reveal(column, true);
  }
  setTarget(docUri);
  reload();
}

// Wiring of a panel - the same for a freshly created one and for one VS Code restored after a
// restart (deserializeWebviewPanel), so a restored panel is a live designer, not a leftover tab.
function adoptPanel(context: vscode.ExtensionContext, created: vscode.WebviewPanel): void {
  panel = created;
  panel.webview.html = shell(panel.webview, context.extensionUri);
  void vscode.commands.executeCommand("setContext", OPEN_CONTEXT, true);
  deps?.structure.setHost(structureHost);
  deps?.data.setHost(dataHost);
  panel.onDidDispose(
    () => {
      panel = undefined;
      lastStructure = undefined;
      lastData = undefined;
      lastFrame = undefined;
      deps?.structure.setHost(undefined);
      deps?.data.setHost(undefined);
      void vscode.commands.executeCommand("setContext", OPEN_CONTEXT, false);
      void context.workspaceState.update(TARGET_KEY, undefined);
    },
    undefined,
    context.subscriptions
  );
  panel.webview.onDidReceiveMessage((m) => void handleMessage(context, m), undefined, context.subscriptions);
}

const structureHost: StructureHost = {
  showStructure(snapshot) {
    lastStructure = snapshot;
    post({ type: "structure", snapshot });
  },
  revealStructure(id) {
    post({ type: "revealRow", pane: "structure", id });
  },
};

const dataHost: DataHost = {
  showData(snapshot) {
    lastData = snapshot;
    post({ type: "data", snapshot });
  },
};

// -- messages from the webview -----------------------------------------------------------------

async function handleMessage(context: vscode.ExtensionContext, m: any): Promise<void> {
  if (!m || !deps) {
    return;
  }
  switch (m.type) {
    case "ready":
      // A restored (or reloaded) webview asks for everything it should be showing.
      post({ type: "labels", labels: labels(), layout, view });
      if (lastStructure) {
        post({ type: "structure", snapshot: lastStructure });
      }
      if (lastData) {
        post({ type: "data", snapshot: lastData });
      }
      if (lastFrame) {
        post({ type: "frame", ...lastFrame, selected: selectedOffset ?? null });
      }
      return;
    case "rowSelect":
      suppressCursorSyncUntil = Date.now() + 300;
      if (m.pane === "structure") {
        deps.structure.setSelection(Array.isArray(m.ids) ? m.ids : []);
        if (typeof m.primary === "string") {
          await deps.structure.activate(m.primary, false);
          const offset = await deps.structure.offsetOf(m.primary);
          if (offset !== undefined && lastOffsets.length) {
            selectedOffset = selectionForCursor(lastOffsets, offset);
            post({ type: "highlight", offset: selectedOffset ?? null });
          }
        }
      } else {
        deps.data.setSelection(typeof m.primary === "string" ? m.primary : undefined);
        if (typeof m.primary === "string") {
          await deps.data.reveal(m.primary);
        }
      }
      return;
    case "rowToggle":
      if (typeof m.id === "string") {
        if (m.pane === "structure") {
          deps.structure.toggleRow(m.id, !!m.expanded);
        } else {
          deps.data.toggleRow(m.id, !!m.expanded);
        }
      }
      return;
    case "rowActivate":
      if (typeof m.id === "string") {
        if (m.pane === "structure") {
          await deps.structure.activate(m.id, true); // a double click moves the focus to the yaml
        } else {
          await deps.data.insert(m.id); // a double click inserts the field into the form
        }
      }
      return;
    case "rowMenu": {
      // The menu composition lives in the tested core; here it only gets its labels.
      const pane: "structure" | "data" = m.pane === "data" ? "data" : "structure";
      const id = String(m.id ?? "");
      let items: { command: string; separatorBefore?: boolean }[] = [];
      if (pane === "structure") {
        const row = lastStructure?.rows.find((r) => r.id === id);
        items = row ? structureMenu(row, lastStructure?.selection.length || 1) : [];
      } else {
        const row = lastData?.rows.find((r) => r.id === id);
        items = row ? dataMenu(row) : [];
      }
      if (!items.length) {
        return;
      }
      post({
        type: "menu",
        pane,
        id,
        x: m.x,
        y: m.y,
        items: items.map((i) => ({ ...i, label: menuLabel(pane, i.command) })),
      });
      return;
    }
    case "command":
      if (typeof m.command === "string") {
        if (m.pane === "data") {
          await deps.data.runCommand(m.command, typeof m.id === "string" ? m.id : undefined);
        } else {
          await vscode.commands.executeCommand(
            `xbsl.formStructure.${m.command}`,
            typeof m.id === "string" ? m.id : undefined
          );
        }
      }
      return;
    case "drop": {
      if (typeof m.target !== "string" || !m.payload) {
        return;
      }
      if (m.payload.kind === "nodes" && Array.isArray(m.payload.ids)) {
        await deps.structure.dropNodes(m.payload.ids, m.target);
      } else if (m.payload.kind === "record" && typeof m.payload.id === "string") {
        const payload = deps.data.payloadFor(m.payload.id);
        if (payload) {
          await deps.structure.dropRecord(payload, m.target);
        }
      }
      return;
    }
    case "frameSelect":
      if (typeof m.offset === "number") {
        // The webview highlighted the block already; remember the choice and keep the
        // cursor-move echo from re-posting a highlight.
        selectedOffset = m.offset;
        suppressCursorSyncUntil = Date.now() + 300;
        if (cursorTimer) {
          clearTimeout(cursorTimer);
          cursorTimer = undefined;
        }
        selectFrameNode(m.offset);
      }
      return;
    case "frameReveal":
      if (typeof m.offset === "number") {
        await revealOffsetInEditor(m.offset, false);
      }
      return;
    case "frameDeselect":
      selectedOffset = undefined;
      return;
    case "view": {
      // Zoom and theme are applied inside the webview; here we only remember the choice.
      const next = { zoom: Number(m.zoom), theme: m.theme } as ViewState;
      if (isViewState(next)) {
        view = next;
        void context.globalState.update(STATE_KEY, view);
      }
      return;
    }
    case "layout":
      layout = sanitizeLayout({ left: m.left, top: m.top });
      void context.globalState.update(LAYOUT_KEY, layout);
      return;
    default:
      return;
  }
}

function updateContext(editor: vscode.TextEditor | undefined): void {
  const isForm = !!editor && looksLikeForm(editor.document);
  void vscode.commands.executeCommand("setContext", "xbsl.formYaml", isForm);
}

export function registerFormDesigner(context: vscode.ExtensionContext, designerDeps: DesignerDeps): void {
  extContext = context;
  deps = designerDeps;
  const saved = context.globalState.get(STATE_KEY);
  if (isViewState(saved)) {
    view = saved;
  }
  layout = sanitizeLayout(context.globalState.get(LAYOUT_KEY));

  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.previewForm", (arg?: unknown) =>
      openPanel(context, arg instanceof vscode.Uri ? arg : undefined)
    ),
    // Session restore: without a serializer VS Code drops the tab on restart and the form has
    // to be opened by hand again. The restored panel is wired exactly like a fresh one.
    vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
      async deserializeWebviewPanel(restored: vscode.WebviewPanel, state: unknown): Promise<void> {
        restored.webview.options = {
          enableScripts: true,
          localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, "resources")],
        };
        adoptPanel(context, restored);
        const uri = restoredTargetUri(state, context.workspaceState.get(TARGET_KEY));
        if (!uri) {
          restored.dispose(); // nothing to show - do not leave an empty tab behind
          return;
        }
        const parsed = vscode.Uri.parse(uri);
        try {
          // On a fresh start the yaml is not loaded yet, and rendering reads the document, not
          // the disk - without this the restored tab would come back empty.
          await vscode.workspace.openTextDocument(parsed);
        } catch {
          restored.dispose(); // the form is gone (renamed, deleted) - nothing to restore
          return;
        }
        setTarget(parsed);
        reload();
      },
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      updateContext(editor);
      // The panel follows the active form yaml - like the Markdown preview.
      if (panel && editor && editor.document.uri.scheme === "file" && looksLikeForm(editor.document)) {
        setTarget(editor.document.uri);
        scheduleReload();
      }
    }),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (panel && target && e.document.uri.toString() === target.toString()) {
        scheduleReload();
      }
    }),
    vscode.languages.onDidChangeDiagnostics((e) => {
      if (panel && target && e.uris.some((u) => u.toString() === target!.toString())) {
        designerDeps.structure.scheduleDiagnostics();
      }
    }),
    // The frame and the structure follow the yaml selection (debounced): the block of the node
    // under the cursor highlights and its structure row is revealed.
    vscode.window.onDidChangeTextEditorSelection((e) => {
      if (!panel || !target || e.textEditor.document.uri.toString() !== target.toString()) {
        return;
      }
      if (Date.now() < suppressCursorSyncUntil) {
        return;
      }
      const active = e.selections[0]?.active;
      if (!active) {
        return;
      }
      const cursor = e.textEditor.document.offsetAt(active);
      if (cursorTimer) {
        clearTimeout(cursorTimer);
      }
      cursorTimer = setTimeout(() => {
        cursorTimer = undefined;
        syncCursorAt(cursor);
      }, CURSOR_DEBOUNCE_MS);
    })
  );
  updateContext(vscode.window.activeTextEditor);
  void vscode.commands.executeCommand("setContext", OPEN_CONTEXT, false);
}

// -- the webview shell ---------------------------------------------------------------------------

function shell(webview: vscode.Webview, extensionUri: vscode.Uri): string {
  const nonce = makeNonce();
  const codicons = webview.asWebviewUri(
    vscode.Uri.joinPath(extensionUri, "resources", "codicons", "codicon.css")
  );
  const themeOptions = [
    { value: "light", label: vscode.l10n.t("Light") },
    { value: "dark", label: vscode.l10n.t("Dark") },
    { value: "editor", label: vscode.l10n.t("Editor theme") },
  ]
    .map((o) => `<option value="${o.value}"${o.value === view.theme ? " selected" : ""}>${esc(o.label)}</option>`)
    .join("");
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
${cspMeta(nonce, { style: webview.cspSource, font: webview.cspSource, img: `data: ${webview.cspSource}` })}
<link rel="stylesheet" href="${codicons}">
<style>
  html, body { height: 100%; }
  body { background: var(--vscode-editor-background); color: var(--vscode-foreground);
    font-family: var(--vscode-font-family, "Segoe UI", sans-serif); font-size: 13px; margin: 0;
    display: flex; flex-direction: column; overflow: hidden; }
  /* --- panes and splitters --- */
  /* The two splitters own the sizes: the trees row and the structure pane carry an explicit
     percentage (flex: none keeps it), the data pane and the frame take what is left. */
  #wrap { flex: 1; display: flex; flex-direction: column; min-height: 0; }
  #top { display: flex; flex: none; min-height: 60px; }
  .pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; overflow: hidden; }
  #structure { flex: none; min-width: 120px; }
  #data { flex: 1; min-width: 120px; }
  #frame { flex: 1; min-height: 60px; }
  .pane-head { display: flex; align-items: center; gap: 4px; padding: 3px 6px; font-size: 11px;
    text-transform: uppercase; letter-spacing: .04em; opacity: .85; background: var(--vscode-sideBarSectionHeader-background, transparent);
    border-bottom: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35)); flex: none; }
  .pane-head .sp { flex: 1; }
  .pane-head .cap { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .pane-head .sub { opacity: .6; text-transform: none; letter-spacing: 0; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .hbtn { background: transparent; border: none; color: var(--vscode-foreground); opacity: .7;
    cursor: pointer; padding: 1px 3px; border-radius: 3px; line-height: 1; }
  .hbtn:hover { opacity: 1; background: var(--vscode-toolbar-hoverBackground, rgba(128,128,128,.2)); }
  .hbtn.on { opacity: 1; color: var(--vscode-charts-blue, #3794ff); }
  .pane-head select { background: var(--vscode-dropdown-background, transparent); color: var(--vscode-dropdown-foreground, inherit);
    border: 1px solid var(--vscode-dropdown-border, rgba(128,128,128,.4)); border-radius: 3px;
    font-size: 11px; font-family: inherit; padding: 0 2px; }
  .split-v { width: 5px; cursor: col-resize; flex: none; background: transparent; }
  .split-h { height: 5px; cursor: row-resize; flex: none; background: transparent; }
  .split-v:hover, .split-h:hover, .split-v.act, .split-h.act { background: var(--vscode-focusBorder); }
  .split-v { border-left: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35)); }
  .split-h { border-top: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35)); }
  /* --- tree rows --- */
  /* Tree rows are .trow, not .row: the wireframe below uses .row for a horizontal group
     (formPreviewCore) and both live in this one document. */
  .rows { flex: 1; overflow: auto; padding: 2px 0 6px; outline: none; }
  .trow { display: flex; align-items: center; gap: 4px; padding: 1px 6px 1px 0; white-space: nowrap;
    cursor: pointer; user-select: none; }
  .trow:hover { background: var(--vscode-list-hoverBackground, rgba(128,128,128,.12)); }
  .trow.sel { background: var(--vscode-list-inactiveSelectionBackground, rgba(128,128,128,.22)); }
  .rows:focus-within .trow.sel { background: var(--vscode-list-activeSelectionBackground, rgba(38,146,222,.4));
    color: var(--vscode-list-activeSelectionForeground, inherit); }
  .trow.drop { outline: 1px dashed var(--vscode-focusBorder); outline-offset: -1px; }
  .trow .tw { width: 16px; flex: none; opacity: .8; font-size: 14px; }
  .trow .ic { flex: none; opacity: .9; font-size: 15px; }
  .trow .lbl { overflow: hidden; text-overflow: ellipsis; }
  .trow .desc { opacity: .6; font-size: .9em; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .trow.sev0 .ic, .trow.sev0 .desc { color: var(--vscode-list-errorForeground, #f66); opacity: 1; }
  .trow.sev1 .ic, .trow.sev1 .desc { color: var(--vscode-list-warningForeground, #cca700); opacity: 1; }
  .trow.broken .lbl { opacity: .6; font-style: italic; }
  .msg { padding: 8px 10px; opacity: .75; font-style: italic; }
  .robanner { margin: 0; padding: 4px 8px; font-size: .95em;
    background: var(--vscode-inputValidation-warningBackground, rgba(210,150,20,.15));
    border-bottom: 1px solid var(--vscode-inputValidation-warningBorder, rgba(210,150,20,.5)); }
  /* --- context menu --- */
  .ctx { position: fixed; z-index: 100; min-width: 190px; padding: 3px 0; display: none;
    background: var(--vscode-menu-background, var(--vscode-editorWidget-background, #252526));
    color: var(--vscode-menu-foreground, var(--vscode-foreground));
    border: 1px solid var(--vscode-menu-border, var(--vscode-panel-border, rgba(128,128,128,.4)));
    border-radius: 4px; box-shadow: 0 2px 10px rgba(0,0,0,.36); }
  .ctx .item { padding: 3px 14px; cursor: pointer; white-space: nowrap; }
  .ctx .item:hover { background: var(--vscode-menu-selectionBackground, rgba(38,146,222,.4));
    color: var(--vscode-menu-selectionForeground, inherit); }
  .ctx .sep { height: 1px; margin: 3px 6px; background: var(--vscode-menu-separatorBackground, rgba(128,128,128,.35)); }
  /* --- the wireframe frame (its own light/dark/editor theme, like a form on a page) --- */
  #frame .theme-editor {
    --fp-bg: var(--vscode-editor-background); --fp-fg: var(--vscode-foreground);
    --fp-border: var(--vscode-panel-border); --fp-soft: rgba(128,128,128,.16);
    --fp-input-bg: var(--vscode-input-background); --fp-input-border: var(--vscode-input-border, rgba(128,128,128,.5));
    --fp-btn-bg: var(--vscode-button-background); --fp-btn-fg: var(--vscode-button-foreground);
    --fp-link: var(--vscode-textLink-foreground); --fp-focus: var(--vscode-focusBorder);
    --fp-sel-bg: rgba(64,128,255,.12);
  }
  #frame .theme-light {
    --fp-bg: #ffffff; --fp-fg: #1f2328; --fp-border: #d5d9de; --fp-soft: rgba(31,35,40,.07);
    --fp-input-bg: #ffffff; --fp-input-border: #c3c9d0;
    --fp-btn-bg: #ffdd00; --fp-btn-fg: #1c1c1f; --fp-link: #1668dc; --fp-focus: #1668dc;
    --fp-sel-bg: rgba(22,104,220,.08);
  }
  #frame .theme-dark {
    --fp-bg: #1e1e1e; --fp-fg: #e6e6e6; --fp-border: #474747; --fp-soft: rgba(230,230,230,.09);
    --fp-input-bg: #2b2b2b; --fp-input-border: #5a5a5a;
    --fp-btn-bg: #ffdd00; --fp-btn-fg: #1c1c1f; --fp-link: #58a6ff; --fp-focus: #2f81f7;
    --fp-sel-bg: rgba(47,129,247,.16);
  }
  #canvas { flex: 1; overflow: auto; background: var(--fp-bg); color: var(--fp-fg); padding: 0 14px 14px; }
  .form-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; padding-top: 10px; }
  .form-title { font-size: 1.35em; font-weight: 600; }
  .form-type { opacity: .55; font-size: .85em; }
  .cmdbar { display: flex; gap: 6px; padding: 6px 0 10px; border-bottom: 1px solid var(--fp-border); margin-bottom: 10px; flex-wrap: wrap; }
  .col { display: flex; flex-direction: column; gap: 7px; align-items: flex-start; }
  #canvas .row { display: flex; flex-direction: row; gap: 9px; align-items: flex-start; flex-wrap: wrap; }
  .form-body { align-items: stretch; }
  .grp, .card, .unknown, .tabs { position: relative; padding: 11px 9px 9px; border-radius: 4px; min-width: 40px; }
  .grp { border: 1px dashed rgba(128,128,128,.45); }
  .card { border: 1px solid var(--fp-border); border-radius: 8px; padding: 13px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
  .card.banner { background: var(--fp-soft); }
  .unknown { border: 1px solid rgba(128,128,128,.55); }
  .tag { position: absolute; top: -8px; left: 8px; font-size: 9px; opacity: .65; background: var(--fp-bg); padding: 0 4px; border-radius: 3px; white-space: nowrap; }
  .ph { opacity: .45; font-style: italic; }
  .chip { font-family: var(--vscode-editor-font-family, monospace); font-size: .85em; background: var(--fp-soft); padding: 0 4px; border-radius: 3px; }
  .sechead { font-weight: 600; font-size: 1.1em; margin-top: 4px; }
  .fld { display: inline-flex; flex-direction: column; gap: 3px; min-width: 160px; }
  .fld-cap { font-size: .85em; opacity: .75; }
  .inp { border: 1px solid var(--fp-input-border); background: var(--fp-input-bg); border-radius: 4px; padding: 5px 9px; display: flex; justify-content: space-between; gap: 8px; }
  .dd { opacity: .6; }
  .chk { display: inline-block; }
  .btn { border: 1px solid var(--fp-border); background: transparent; color: var(--fp-fg); border-radius: 4px; padding: 5px 14px; font-size: inherit; cursor: pointer; }
  /* Primary button - the native Element yellow (--themeColorPrimaryBtnBg #fd0, text #1c1c1f). */
  .btn.primary { background: var(--fp-btn-bg); color: var(--fp-btn-fg); border-color: var(--fp-btn-bg); }
  .btn.link { border-color: transparent; color: var(--fp-link); padding-left: 4px; padding-right: 4px; }
  .img { width: 110px; height: 74px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--fp-border); border-radius: 4px; font-size: 24px; background: var(--fp-soft); overflow: hidden; }
  .img .rimg { max-width: 100%; max-height: 100%; object-fit: contain; }
  .htmlbox { border: 1px dashed rgba(128,128,128,.6); border-radius: 4px; min-height: 48px; min-width: 140px; position: relative; padding: 11px 9px 9px;
    background: repeating-linear-gradient(45deg, transparent, transparent 6px, var(--fp-soft) 6px, var(--fp-soft) 12px); }
  table.tbl { border-collapse: collapse; }
  .tbl th, .tbl td { border: 1px solid var(--fp-border); padding: 4px 12px; font-size: .92em; text-align: left; }
  .tbl th { background: var(--fp-soft); }
  .tbl td { opacity: .5; }
  .tabs { border: none; padding: 0; }
  .tabbar { display: flex; gap: 2px; border-bottom: 1px solid var(--fp-border); }
  .tabbtn { border: 1px solid transparent; border-bottom: none; background: transparent; color: var(--fp-fg); padding: 5px 14px; cursor: pointer; border-radius: 4px 4px 0 0; opacity: .7; font-size: inherit; }
  .tabbtn.act { border-color: var(--fp-border); opacity: 1; font-weight: 600; }
  .tabpage { display: none; padding-top: 10px; }
  .tabpage.act { display: block; }
  #canvas [data-off]:hover { outline: 1px solid var(--fp-focus); outline-offset: 1px; }
  /* Selected node: a strong focus-colored frame plus a light tint. The tint is an overlay
     (::after), so blocks with their own background (primary button, banner) keep it. */
  #canvas .sel { outline: 2px solid var(--fp-focus, var(--vscode-focusBorder)) !important; outline-offset: 1px; position: relative; }
  #canvas .sel::after { content: ""; position: absolute; inset: 0; background: var(--fp-sel-bg); border-radius: inherit; pointer-events: none; }
  .note { opacity: .7; font-style: italic; margin-top: 12px; }
</style></head>
<body>
<div id="wrap">
  <div id="top">
    <div class="pane" id="structure">
      <div class="pane-head">
        <span class="cap" id="structure-cap"></span>
        <span class="sub" id="structure-sub"></span>
        <span class="sp"></span>
        <button class="hbtn" id="btn-filter" title=""><span class="codicon codicon-filter"></span></button>
        <button class="hbtn" id="btn-unfocus" title="" style="display:none"><span class="codicon codicon-list-tree"></span></button>
        <button class="hbtn" id="btn-refresh" title=""><span class="codicon codicon-refresh"></span></button>
      </div>
      <div id="structure-ro" class="robanner" style="display:none"></div>
      <div class="rows" id="structure-rows" tabindex="0"></div>
    </div>
    <div class="split-v" id="vsplit"></div>
    <div class="pane" id="data">
      <div class="pane-head">
        <span class="cap" id="data-cap"></span>
        <span class="sp"></span>
        <button class="hbtn" id="btn-addprop" title=""><span class="codicon codicon-add"></span></button>
      </div>
      <div class="rows" id="data-rows" tabindex="0"></div>
    </div>
  </div>
  <div class="split-h" id="hsplit"></div>
  <div class="pane" id="frame">
    <div class="pane-head">
      <span class="cap" id="frame-cap"></span>
      <span class="sub" id="frame-sub"></span>
      <span class="sp"></span>
      <select id="theme">${themeOptions}</select>
      <button class="hbtn" id="zo" title="">&#8722;</button><span class="sub" id="zv">${view.zoom}%</span><button class="hbtn" id="zi" title="">+</button>
    </div>
    <div id="canvas" class="theme-${view.theme}"><div id="root"></div></div>
  </div>
</div>
<div class="ctx" id="ctx"></div>
<script nonce="${nonce}">
${panelScript()}
</script></body></html>`;
}

// The webview script. Written with string concatenation (no template literals): the whole
// block lives inside a TS template literal, where a backtick or a dollar-brace would be
// interpolated by the extension instead of reaching the browser.
function panelScript(): string {
  return String.raw`
  const vsapi = acquireVsCodeApi();
  const state = Object.assign({ tabs: {}, sel: undefined, uri: "" }, vsapi.getState() || {});
  let L = ${inlineJson(labels())};
  let layout = ${inlineJson(layout)};
  let zoom = ${view.zoom};
  let structure = { available: false, rows: [], selection: [], namedOnly: false, readonly: false };
  let data = { available: false, rows: [] };
  let menuFor = null;

  const el = (id) => document.getElementById(id);
  const structureRows = el("structure-rows");
  const dataRows = el("data-rows");
  const canvas = el("canvas");
  const root = el("root");
  const ctx = el("ctx");

  function post(msg) { vsapi.postMessage(msg); }
  function save() { vsapi.setState(state); }

  // --- labels and layout ---------------------------------------------------------------------

  function applyLabels() {
    el("structure-cap").textContent = L.structure;
    el("data-cap").textContent = L.data;
    el("frame-cap").textContent = L.frame;
    el("btn-refresh").title = L.refresh;
    el("btn-unfocus").title = L.resetFocus;
    el("btn-addprop").title = L.addProperty;
    el("btn-filter").title = structure.namedOnly ? L.filterAll : L.filterNamed;
    el("zi").title = L.zoomIn;
    el("zo").title = L.zoomOut;
  }

  function applyLayout() {
    el("structure").style.width = layout.left + "%";
    el("top").style.height = layout.top + "%";
  }

  // --- tree rendering --------------------------------------------------------------------------

  function rowElement(row, pane, selected) {
    const div = document.createElement("div");
    let cls = "trow";
    if (selected) { cls += " sel"; }
    if (row.badge && row.badge.severity <= 1) { cls += " sev" + row.badge.severity; }
    if (pane === "data" && row.kind === "property" && !row.insertable) { cls += " broken"; }
    div.className = cls;
    div.dataset.id = row.id;
    div.dataset.pane = pane;
    div.style.paddingLeft = (2 + row.depth * 13) + "px";
    if (row.tooltip) { div.title = row.tooltip; }
    const tw = document.createElement("span");
    tw.className = "tw";
    if (row.hasChildren) {
      // Only a row that HAS children carries the twisty marker: on a leaf the same 16px is a
      // plain indent, and a click there must select the row like any other click on it.
      tw.className += " codicon codicon-chevron-" + (row.expanded ? "down" : "right");
      tw.dataset.twisty = "1";
    }
    div.appendChild(tw);
    const ic = document.createElement("span");
    ic.className = "ic codicon codicon-" + row.icon;
    div.appendChild(ic);
    const lbl = document.createElement("span");
    lbl.className = "lbl";
    lbl.textContent = row.label;
    div.appendChild(lbl);
    if (row.description) {
      const desc = document.createElement("span");
      desc.className = "desc";
      desc.textContent = row.description;
      div.appendChild(desc);
    }
    const draggable = pane === "structure" ? row.draggable : row.insertable;
    if (draggable) { div.draggable = true; }
    return div;
  }

  function renderTree(container, snapshot, pane) {
    container.replaceChildren();
    if (!snapshot.available || !snapshot.rows.length) {
      const msg = document.createElement("div");
      msg.className = "msg";
      msg.textContent = snapshot.message || L.empty;
      container.appendChild(msg);
      return;
    }
    const selection = pane === "structure" ? (snapshot.selection || []) : (snapshot.selection ? [snapshot.selection] : []);
    const frag = document.createDocumentFragment();
    for (const row of snapshot.rows) {
      frag.appendChild(rowElement(row, pane, selection.indexOf(row.id) >= 0));
    }
    container.appendChild(frag);
  }

  function renderStructure() {
    renderTree(structureRows, structure, "structure");
    el("structure-sub").textContent = structure.focusLabel || "";
    el("btn-unfocus").style.display = structure.focusLabel ? "" : "none";
    el("btn-filter").className = "hbtn" + (structure.namedOnly ? " on" : "");
    el("btn-filter").title = structure.namedOnly ? L.filterAll : L.filterNamed;
    const banner = el("structure-ro");
    banner.style.display = structure.readonly ? "" : "none";
    banner.textContent = L.readonly;
  }

  function rowById(pane, id) {
    const rows = pane === "structure" ? structure.rows : data.rows;
    for (const row of rows) { if (row.id === id) { return row; } }
    return null;
  }

  function selectedIds(pane) {
    if (pane === "structure") { return structure.selection || []; }
    return data.selection ? [data.selection] : [];
  }

  function setSelection(pane, ids, primary) {
    if (pane === "structure") { structure.selection = ids; } else { data.selection = primary; }
    const container = pane === "structure" ? structureRows : dataRows;
    for (const node of container.querySelectorAll(".trow")) {
      node.classList.toggle("sel", ids.indexOf(node.dataset.id) >= 0);
    }
    post({ type: "rowSelect", pane: pane, ids: ids, primary: primary });
  }

  // --- pointer interaction ----------------------------------------------------------------------

  function onTreeClick(e, pane) {
    hideMenu();
    const rowEl = e.target.closest(".trow");
    if (!rowEl) { return; }
    const id = rowEl.dataset.id;
    const row = rowById(pane, id);
    if (!row) { return; }
    if (e.target.dataset && e.target.dataset.twisty === "1") {
      if (row.hasChildren) { post({ type: "rowToggle", pane: pane, id: id, expanded: !row.expanded }); }
      return;
    }
    let ids = [id];
    if (pane === "structure" && (e.ctrlKey || e.metaKey)) {
      const current = selectedIds(pane).slice();
      const at = current.indexOf(id);
      if (at >= 0) { current.splice(at, 1); } else { current.push(id); }
      ids = current;
    } else if (pane === "structure" && e.shiftKey) {
      const anchor = selectedIds(pane)[0];
      const order = structure.rows.map((r) => r.id);
      const from = order.indexOf(anchor);
      const to = order.indexOf(id);
      if (from >= 0 && to >= 0) { ids = order.slice(Math.min(from, to), Math.max(from, to) + 1); }
    }
    setSelection(pane, ids, id);
  }

  function onTreeDouble(e, pane) {
    const rowEl = e.target.closest(".trow");
    if (!rowEl) { return; }
    const row = rowById(pane, rowEl.dataset.id);
    if (!row) { return; }
    if (row.hasChildren && !(pane === "data" && row.insertable)) {
      post({ type: "rowToggle", pane: pane, id: row.id, expanded: !row.expanded });
      return;
    }
    post({ type: "rowActivate", pane: pane, id: row.id });
  }

  structureRows.addEventListener("click", (e) => onTreeClick(e, "structure"));
  dataRows.addEventListener("click", (e) => onTreeClick(e, "data"));
  structureRows.addEventListener("dblclick", (e) => onTreeDouble(e, "structure"));
  dataRows.addEventListener("dblclick", (e) => onTreeDouble(e, "data"));

  // --- context menu ------------------------------------------------------------------------------

  function hideMenu() { ctx.style.display = "none"; menuFor = null; }

  function onContext(e, pane) {
    const rowEl = e.target.closest(".trow");
    e.preventDefault();
    if (!rowEl) { hideMenu(); return; }
    const id = rowEl.dataset.id;
    if (selectedIds(pane).indexOf(id) < 0) { setSelection(pane, [id], id); }
    post({ type: "rowMenu", pane: pane, id: id, x: e.clientX, y: e.clientY });
  }

  structureRows.addEventListener("contextmenu", (e) => onContext(e, "structure"));
  dataRows.addEventListener("contextmenu", (e) => onContext(e, "data"));
  document.addEventListener("mousedown", (e) => { if (!e.target.closest(".ctx")) { hideMenu(); } }, true);
  window.addEventListener("blur", hideMenu);

  function showMenu(msg) {
    ctx.replaceChildren();
    for (const item of msg.items) {
      if (item.separatorBefore) {
        const sep = document.createElement("div");
        sep.className = "sep";
        ctx.appendChild(sep);
      }
      const div = document.createElement("div");
      div.className = "item";
      div.textContent = item.label;
      div.dataset.command = item.command;
      ctx.appendChild(div);
    }
    menuFor = { pane: msg.pane, id: msg.id };
    ctx.style.display = "block";
    // Keep the menu inside the panel: flip it when it would hang off the edge.
    const w = ctx.offsetWidth, h = ctx.offsetHeight;
    ctx.style.left = Math.max(0, Math.min(msg.x, window.innerWidth - w - 4)) + "px";
    ctx.style.top = Math.max(0, Math.min(msg.y, window.innerHeight - h - 4)) + "px";
  }

  ctx.addEventListener("click", (e) => {
    const item = e.target.closest(".item");
    if (!item || !menuFor) { return; }
    post({ type: "command", pane: menuFor.pane, command: item.dataset.command, id: menuFor.id });
    hideMenu();
  });

  // --- keyboard -------------------------------------------------------------------------------

  function moveSelection(pane, delta) {
    const rows = pane === "structure" ? structure.rows : data.rows;
    if (!rows.length) { return; }
    const current = selectedIds(pane)[0];
    let at = rows.findIndex((r) => r.id === current);
    at = at < 0 ? 0 : Math.min(rows.length - 1, Math.max(0, at + delta));
    const row = rows[at];
    setSelection(pane, [row.id], row.id);
    const node = (pane === "structure" ? structureRows : dataRows).querySelector('.trow[data-id="' + cssEscape(row.id) + '"]');
    if (node) { node.scrollIntoView({ block: "nearest" }); }
  }

  function cssEscape(value) { return String(value).replace(/["\\]/g, "\\$&"); }

  function onKey(e, pane) {
    const id = selectedIds(pane)[0];
    const row = id ? rowById(pane, id) : null;
    if (e.key === "ArrowDown") { moveSelection(pane, 1); e.preventDefault(); return; }
    if (e.key === "ArrowUp" && !e.altKey) { moveSelection(pane, -1); e.preventDefault(); return; }
    if (e.key === "ArrowRight" && row) {
      if (row.hasChildren && !row.expanded) { post({ type: "rowToggle", pane: pane, id: row.id, expanded: true }); }
      else { moveSelection(pane, 1); }
      e.preventDefault();
      return;
    }
    if (e.key === "ArrowLeft" && row) {
      if (row.hasChildren && row.expanded) { post({ type: "rowToggle", pane: pane, id: row.id, expanded: false }); }
      else { moveSelection(pane, -1); }
      e.preventDefault();
      return;
    }
    if (e.key === "Escape") { hideMenu(); return; }
    if (!row) { return; }
    if (e.key === "Enter") { post({ type: "rowActivate", pane: pane, id: row.id }); e.preventDefault(); return; }
    if (pane === "data") {
      if (e.key === "Delete") { post({ type: "command", pane: pane, command: "removeProperty", id: row.id }); e.preventDefault(); }
      if (e.key === "F2") { post({ type: "command", pane: pane, command: "renameProperty", id: row.id }); e.preventDefault(); }
      return;
    }
    if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      post({ type: "command", pane: pane, command: e.key === "ArrowUp" ? "moveUp" : "moveDown", id: row.id });
      e.preventDefault();
      return;
    }
    if (e.key === "Delete") { post({ type: "command", pane: pane, command: "delete", id: row.id }); e.preventDefault(); return; }
    if (e.key === "F2") { post({ type: "command", pane: pane, command: "rename", id: row.id }); e.preventDefault(); return; }
    if ((e.ctrlKey || e.metaKey) && (e.key === "c" || e.key === "с")) {
      post({ type: "command", pane: pane, command: "copyYaml", id: row.id });
      e.preventDefault();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && (e.key === "v" || e.key === "м")) {
      post({ type: "command", pane: pane, command: "pasteYaml", id: row.id });
      e.preventDefault();
    }
  }

  structureRows.addEventListener("keydown", (e) => onKey(e, "structure"));
  dataRows.addEventListener("keydown", (e) => onKey(e, "data"));

  // --- drag and drop ------------------------------------------------------------------------------

  // The payload rides in a module variable, not only in the DataTransfer: both ends of the drag
  // live in THIS document, and a variable survives the browser's own type restrictions.
  let dragPayload = null;
  let dropRow = null;

  function markDrop(node) {
    if (dropRow === node) { return; }
    if (dropRow) { dropRow.classList.remove("drop"); }
    dropRow = node;
    if (dropRow) { dropRow.classList.add("drop"); }
  }

  function onDragStart(e, pane) {
    const rowEl = e.target.closest(".trow");
    if (!rowEl) { return; }
    const row = rowById(pane, rowEl.dataset.id);
    if (!row) { return; }
    if (pane === "structure") {
      if (!row.draggable) { e.preventDefault(); return; }
      const ids = selectedIds(pane).indexOf(row.id) >= 0 ? selectedIds(pane) : [row.id];
      dragPayload = { kind: "nodes", ids: ids };
    } else {
      if (!row.insertable) { e.preventDefault(); return; }
      dragPayload = { kind: "record", id: row.id };
    }
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", row.label);
  }

  structureRows.addEventListener("dragstart", (e) => onDragStart(e, "structure"));
  dataRows.addEventListener("dragstart", (e) => onDragStart(e, "data"));
  document.addEventListener("dragend", () => { dragPayload = null; markDrop(null); });

  structureRows.addEventListener("dragover", (e) => {
    if (!dragPayload || structure.readonly) { return; }
    const rowEl = e.target.closest(".trow");
    if (!rowEl) { markDrop(null); return; }
    // A node cannot be dropped into itself; the extension re-checks the whole subtree.
    if (dragPayload.kind === "nodes" && dragPayload.ids.indexOf(rowEl.dataset.id) >= 0) { markDrop(null); return; }
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    markDrop(rowEl);
  });
  structureRows.addEventListener("dragleave", (e) => { if (!e.relatedTarget || !structureRows.contains(e.relatedTarget)) { markDrop(null); } });
  structureRows.addEventListener("drop", (e) => {
    const rowEl = e.target.closest(".trow");
    e.preventDefault();
    markDrop(null);
    if (!rowEl || !dragPayload) { return; }
    post({ type: "drop", target: rowEl.dataset.id, payload: dragPayload });
    dragPayload = null;
  });

  // --- header buttons ------------------------------------------------------------------------------

  el("btn-refresh").addEventListener("click", () => post({ type: "command", pane: "structure", command: "refresh" }));
  el("btn-filter").addEventListener("click", () =>
    post({ type: "command", pane: "structure", command: structure.namedOnly ? "filterAll" : "filterNamed" })
  );
  el("btn-unfocus").addEventListener("click", () => post({ type: "command", pane: "structure", command: "resetFocus" }));
  el("btn-addprop").addEventListener("click", () => post({ type: "command", pane: "data", command: "addProperty" }));

  // --- the frame ------------------------------------------------------------------------------------

  function applyView() {
    root.style.zoom = zoom / 100;
    el("zv").textContent = zoom + "%";
    post({ type: "view", zoom: zoom, theme: el("theme").value });
  }
  el("zi").addEventListener("click", () => { zoom = Math.min(300, zoom + 25); applyView(); });
  el("zo").addEventListener("click", () => { zoom = Math.max(50, zoom - 25); applyView(); });
  el("theme").addEventListener("change", (e) => { canvas.className = "theme-" + e.target.value; applyView(); });

  // Visual selection only: the class, the saved state and (optionally) the scroll. Telling the
  // extension is the caller's business - a highlight pushed FROM the extension must not echo
  // back, or the cursor sync would loop.
  function applyFrameSelection(off, scroll) {
    for (const node of canvas.querySelectorAll(".sel")) { node.classList.remove("sel"); }
    state.sel = off;
    save();
    if (off === undefined || off === null) { return; }
    const node = canvas.querySelector('[data-off="' + off + '"]');
    if (!node) { return; }
    node.classList.add("sel");
    if (scroll) { node.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  }

  canvas.addEventListener("click", (e) => {
    hideMenu();
    const tab = e.target.closest(".tabbtn");
    if (tab) {
      const tabs = tab.closest(".tabs");
      for (const b of tabs.querySelectorAll(":scope > .tabbar > .tabbtn")) { b.classList.toggle("act", b === tab); }
      for (const p of tabs.querySelectorAll(":scope > .tabpage")) { p.classList.toggle("act", p.dataset.tab === tab.dataset.tab); }
      const owner = tabs.getAttribute("data-off");
      if (owner) { state.tabs[owner] = tab.dataset.tab; save(); }
    }
    const node = e.target.closest("[data-off]");
    if (node) {
      const off = Number(node.dataset.off);
      if (e.ctrlKey || e.metaKey) {
        post({ type: "frameReveal", offset: off });
      } else {
        applyFrameSelection(off, false);
        post({ type: "frameSelect", offset: off });
      }
      e.stopPropagation();
    } else {
      applyFrameSelection(undefined, false);
      post({ type: "frameDeselect" });
    }
  });

  function renderFrame(msg) {
    root.innerHTML = msg.body;
    el("frame-sub").textContent = msg.title || "";
    for (const entry of Object.entries(state.tabs || {})) {
      const tabs = canvas.querySelector('.tabs[data-off="' + entry[0] + '"]');
      if (!tabs) { continue; }
      for (const b of tabs.querySelectorAll(":scope > .tabbar > .tabbtn")) { b.classList.toggle("act", b.dataset.tab === entry[1]); }
      for (const p of tabs.querySelectorAll(":scope > .tabpage")) { p.classList.toggle("act", p.dataset.tab === entry[1]); }
    }
    applyFrameSelection(msg.selected === null ? undefined : msg.selected, false);
  }

  // --- splitters --------------------------------------------------------------------------------

  function dragSplitter(node, axis) {
    node.addEventListener("pointerdown", (e) => {
      node.setPointerCapture(e.pointerId);
      node.classList.add("act");
      const move = (ev) => {
        const box = el("wrap").getBoundingClientRect();
        if (axis === "x") {
          layout.left = Math.min(85, Math.max(15, ((ev.clientX - box.left) / box.width) * 100));
        } else {
          layout.top = Math.min(85, Math.max(15, ((ev.clientY - box.top) / box.height) * 100));
        }
        applyLayout();
      };
      const up = () => {
        node.classList.remove("act");
        node.removeEventListener("pointermove", move);
        node.removeEventListener("pointerup", up);
        post({ type: "layout", left: layout.left, top: layout.top });
      };
      node.addEventListener("pointermove", move);
      node.addEventListener("pointerup", up);
    });
  }
  dragSplitter(el("vsplit"), "x");
  dragSplitter(el("hsplit"), "y");

  // --- messages from the extension -----------------------------------------------------------------

  window.addEventListener("message", (event) => {
    const m = event.data;
    if (!m) { return; }
    if (m.type === "labels") {
      L = m.labels;
      layout = m.layout;
      zoom = m.view.zoom;
      canvas.className = "theme-" + m.view.theme;
      el("theme").value = m.view.theme;
      root.style.zoom = zoom / 100;
      el("zv").textContent = zoom + "%";
      applyLabels();
      applyLayout();
    } else if (m.type === "structure") {
      structure = m.snapshot;
      renderStructure();
    } else if (m.type === "data") {
      data = m.snapshot;
      renderTree(dataRows, data, "data");
    } else if (m.type === "frame") {
      renderFrame(m);
    } else if (m.type === "highlight") {
      applyFrameSelection(m.offset === null ? undefined : m.offset, true);
    } else if (m.type === "revealRow") {
      const container = m.pane === "structure" ? structureRows : dataRows;
      if (m.pane === "structure") { structure.selection = [m.id]; } else { data.selection = m.id; }
      for (const node of container.querySelectorAll(".trow")) { node.classList.toggle("sel", node.dataset.id === m.id); }
      const node = container.querySelector('.trow[data-id="' + cssEscape(m.id) + '"]');
      if (node) { node.scrollIntoView({ block: "nearest" }); }
    } else if (m.type === "menu") {
      showMenu(m);
    }
  });

  applyLabels();
  applyLayout();
  post({ type: "ready" });
`;
}
