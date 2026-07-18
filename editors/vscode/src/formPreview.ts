// 1C:Element form preview - a standalone webview panel with the form wireframe from yaml
// (rendering - formPreviewCore.ts): follows the active yaml editor, live updates, zoom and
// theme (light/dark/editor) in the toolbar, switchable tabs. A click selects a component -
// the block highlights, the cursor lands on its yaml line (without stealing focus) and the
// designer's "Properties" view shows the node through the xbsl.properties.showForNode
// command; Ctrl+click leads to yaml. The selection also follows the yaml cursor (debounced,
// highlight only - no focus moves and no properties calls) and survives re-renders: the
// extension remaps the selected offset against the fresh render (formPreviewCore helpers).
// The editor title button is visible only for form yamls - the xbsl.formYaml context key.

import * as vscode from "vscode";
import { collectDataOffsets, esc, nearestOffset, renderFormPreview, selectionForCursor } from "./formPreviewCore";

const VIEW_TYPE = "xbslFormPreview";
const DEBOUNCE_MS = 300;
const CURSOR_DEBOUNCE_MS = 150;
const STATE_KEY = "xbsl.formPreview.view";

interface ViewState {
  zoom: number; // percent
  theme: "light" | "dark" | "editor";
}

const DEFAULT_VIEW: ViewState = { zoom: 125, theme: "light" };

let panel: vscode.WebviewPanel | undefined;
let target: vscode.Uri | undefined;
let timer: NodeJS.Timeout | undefined;
let view: ViewState = DEFAULT_VIEW;
// Selection sync state. The webview keeps the visual class; this side owns the selected
// data-off so it survives full re-renders (the html is rebuilt from scratch on every edit).
let selectedOffset: number | undefined;
let lastOffsets: number[] = [];
let freshTarget = false; // set on a target switch: the first good render derives the selection from the cursor
let cursorTimer: NodeJS.Timeout | undefined;
let suppressCursorSyncUntil = 0; // a preview click moves the cursor itself - ignore the echo

// Whether the content looks like a form: an interface component with inheritance and content.
function looksLikeForm(doc: vscode.TextDocument): boolean {
  if (doc.languageId !== "yaml") {
    return false;
  }
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return head.includes("КомпонентИнтерфейса") && doc.getText().includes("Наследует");
}

// -- preview panel ----------------------------------------------------------------------------

function shell(body: string, nonce: string): string {
  const themeOptions = [
    { value: "light", label: vscode.l10n.t("Light") },
    { value: "dark", label: vscode.l10n.t("Dark") },
    { value: "editor", label: vscode.l10n.t("Editor theme") },
  ]
    .map((o) => `<option value="${o.value}"${o.value === view.theme ? " selected" : ""}>${esc(o.label)}</option>`)
    .join("");
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body.theme-editor {
    --fp-bg: var(--vscode-editor-background); --fp-fg: var(--vscode-foreground);
    --fp-border: var(--vscode-panel-border); --fp-soft: rgba(128,128,128,.16);
    --fp-input-bg: var(--vscode-input-background); --fp-input-border: var(--vscode-input-border, rgba(128,128,128,.5));
    --fp-btn-bg: var(--vscode-button-background); --fp-btn-fg: var(--vscode-button-foreground);
    --fp-link: var(--vscode-textLink-foreground); --fp-focus: var(--vscode-focusBorder);
    --fp-sel-bg: rgba(64,128,255,.12);
  }
  body.theme-light {
    --fp-bg: #ffffff; --fp-fg: #1f2328; --fp-border: #d5d9de; --fp-soft: rgba(31,35,40,.07);
    --fp-input-bg: #ffffff; --fp-input-border: #c3c9d0;
    --fp-btn-bg: #ffdd00; --fp-btn-fg: #1c1c1f; --fp-link: #1668dc; --fp-focus: #1668dc;
    --fp-sel-bg: rgba(22,104,220,.08);
  }
  body.theme-dark {
    --fp-bg: #1e1e1e; --fp-fg: #e6e6e6; --fp-border: #474747; --fp-soft: rgba(230,230,230,.09);
    --fp-input-bg: #2b2b2b; --fp-input-border: #5a5a5a;
    --fp-btn-bg: #ffdd00; --fp-btn-fg: #1c1c1f; --fp-link: #58a6ff; --fp-focus: #2f81f7;
    --fp-sel-bg: rgba(47,129,247,.16);
  }
  body { background: var(--fp-bg); color: var(--fp-fg); font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
    font-size: 14px; padding: 0 14px 14px; margin: 0; }
  .bar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 6px; padding: 6px 0;
    background: var(--fp-bg); border-bottom: 1px solid var(--fp-border); margin-bottom: 10px; }
  .bar select, .bar button { background: var(--fp-bg); color: var(--fp-fg); border: 1px solid var(--fp-border);
    border-radius: 3px; padding: 2px 8px; cursor: pointer; font-size: 12px; }
  .bar .zv { min-width: 44px; text-align: center; font-size: 12px; opacity: .8; }
  .bar .sp { flex: 1; }
  #canvas { overflow-x: auto; }
  .form-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; }
  .form-title { font-size: 1.35em; font-weight: 600; }
  .form-type { opacity: .55; font-size: .85em; }
  .cmdbar { display: flex; gap: 6px; padding: 6px 0 10px; border-bottom: 1px solid var(--fp-border); margin-bottom: 10px; flex-wrap: wrap; }
  .col { display: flex; flex-direction: column; gap: 7px; align-items: flex-start; }
  .row { display: flex; flex-direction: row; gap: 9px; align-items: flex-start; flex-wrap: wrap; }
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
  .img { width: 110px; height: 74px; display: flex; align-items: center; justify-content: center; border: 1px solid var(--fp-border); border-radius: 4px; font-size: 24px; background: var(--fp-soft); }
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
<body class="theme-${view.theme}">
<div class="bar">
  <select id="theme">${themeOptions}</select>
  <span class="sp"></span>
  <button id="zo" title="&#8722;">&#8722;</button><span class="zv" id="zv">${view.zoom}%</span><button id="zi" title="+">+</button>
</div>
<div id="canvas"><div id="root" style="zoom:${view.zoom / 100}">${body}</div></div>
<script nonce="${nonce}">
  const vsapi = acquireVsCodeApi();
  let zoom = ${view.zoom};
  const state = vsapi.getState() || { tabs: {}, sel: undefined };

  const applyView = () => {
    document.getElementById("root").style.zoom = zoom / 100;
    document.getElementById("zv").textContent = zoom + "%";
    vsapi.postMessage({ type: "view", zoom, theme: document.getElementById("theme").value });
  };
  document.getElementById("zi").addEventListener("click", () => { zoom = Math.min(300, zoom + 25); applyView(); });
  document.getElementById("zo").addEventListener("click", () => { zoom = Math.max(50, zoom - 25); applyView(); });
  document.getElementById("theme").addEventListener("change", (e) => {
    document.body.className = "theme-" + e.target.value;
    applyView();
  });

  // Visual selection only: the class, the saved state and (optionally) the scroll. Telling
  // the extension is the caller's business - a highlight pushed FROM the extension must not
  // echo back, or the cursor sync would loop.
  function applySelection(off, scroll) {
    for (const el of document.querySelectorAll("#canvas .sel")) { el.classList.remove("sel"); }
    state.sel = off;
    vsapi.setState(state);
    if (off === undefined || off === null) {
      return;
    }
    const el = document.querySelector('#canvas [data-off="' + off + '"]');
    if (!el) { return; }
    el.classList.add("sel");
    if (scroll) { el.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest(".bar")) { return; }
    const tab = e.target.closest(".tabbtn");
    if (tab) {
      const tabs = tab.closest(".tabs");
      for (const b of tabs.querySelectorAll(":scope > .tabbar > .tabbtn")) { b.classList.toggle("act", b === tab); }
      for (const p of tabs.querySelectorAll(":scope > .tabpage")) { p.classList.toggle("act", p.dataset.tab === tab.dataset.tab); }
      const owner = tabs.getAttribute("data-off");
      if (owner) { state.tabs[owner] = tab.dataset.tab; vsapi.setState(state); }
    }
    const el = e.target.closest("[data-off]");
    if (el) {
      const off = Number(el.dataset.off);
      if (e.ctrlKey || e.metaKey) {
        vsapi.postMessage({ type: "reveal", offset: off });
      } else {
        // No scroll on a preview click - the block is already under the pointer.
        applySelection(off, false);
        vsapi.postMessage({ type: "select", offset: off });
      }
      e.stopPropagation();
    } else if (e.target.closest("#canvas")) {
      applySelection(undefined, false);
      vsapi.postMessage({ type: "deselect" });
    }
  });

  // Selection pushed by the extension (the yaml cursor moved): highlight and scroll into view.
  window.addEventListener("message", (event) => {
    const m = event.data;
    if (m && m.type === "highlight") {
      applySelection(m.offset === null ? undefined : m.offset, true);
    }
  });

  // After a re-render: restore active tabs from the saved state, then the selection the
  // extension remapped against the fresh offsets (inlined - a postMessage could arrive
  // before the webview is ready).
  for (const [owner, idx] of Object.entries(state.tabs || {})) {
    const tabs = document.querySelector('#canvas .tabs[data-off="' + owner + '"]');
    if (!tabs) { continue; }
    for (const b of tabs.querySelectorAll(":scope > .tabbar > .tabbtn")) { b.classList.toggle("act", b.dataset.tab === idx); }
    for (const p of tabs.querySelectorAll(":scope > .tabpage")) { p.classList.toggle("act", p.dataset.tab === idx); }
  }
  const initialSel = ${selectedOffset ?? null};
  applySelection(initialSel === null ? undefined : initialSel, initialSel !== null);
</script></body></html>`;
}

function nonce(): string {
  let s = "";
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 24; i++) {
    s += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }
  return s;
}

function targetDocument(): vscode.TextDocument | undefined {
  if (!target) {
    return undefined;
  }
  return vscode.workspace.textDocuments.find((d) => d.uri.toString() === target!.toString());
}

// Switching to another form drops the selection - offsets mean nothing across documents.
function setTarget(uri: vscode.Uri): void {
  if (target?.toString() !== uri.toString()) {
    selectedOffset = undefined;
    lastOffsets = [];
    freshTarget = true;
  }
  target = uri;
}

function render(): void {
  if (!panel || !target) {
    return;
  }
  const doc = targetDocument();
  if (!doc) {
    return;
  }
  const result = renderFormPreview(doc.getText());
  let body: string;
  if (result.ok) {
    body = result.html;
    panel.title = vscode.l10n.t("Preview: {0}", result.title);
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
  panel.webview.html = shell(body, nonce());
}

function scheduleRender(): void {
  if (timer) {
    clearTimeout(timer);
  }
  timer = setTimeout(() => {
    timer = undefined;
    render();
  }, DEBOUNCE_MS);
}

// Show a location in the yaml editor. On selection and edits the focus stays in the panel
// (preserveFocus); on an explicit "Show in yaml" / Ctrl+click it moves to the editor.
async function revealOffset(offset: number, preserveFocus: boolean): Promise<void> {
  if (!target) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target);
  const pos = doc.positionAt(offset);
  const existing = vscode.window.visibleTextEditors.find((e) => e.document.uri.toString() === target!.toString());
  const editor = await vscode.window.showTextDocument(doc, {
    viewColumn: existing?.viewColumn ?? vscode.ViewColumn.One,
    preserveFocus,
    preview: false,
  });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// Component selection: cursor onto the node's yaml line (no focus steal) + the node's
// properties into the designer's sidebar "Properties" view (formProps.ts owns the panel;
// the command takes positional uri, offset).
function selectNode(offset: number): void {
  if (target) {
    void vscode.commands.executeCommand("xbsl.properties.showForNode", target.toString(), offset);
  }
  void revealOffset(offset, true);
}

// Yaml cursor -> wireframe highlight: the containing node is the closest data-off at or
// below the cursor. Purely visual follow - no focus moves and no properties-panel calls,
// unlike a click inside the preview.
function syncCursorAt(cursor: number): void {
  if (!panel || lastOffsets.length === 0) {
    return;
  }
  const off = selectionForCursor(lastOffsets, cursor);
  if (off === selectedOffset) {
    return;
  }
  selectedOffset = off;
  void panel.webview.postMessage({ type: "highlight", offset: off ?? null });
}

function isViewState(v: unknown): v is ViewState {
  const s = v as ViewState;
  return !!s && typeof s.zoom === "number" && (s.theme === "light" || s.theme === "dark" || s.theme === "editor");
}

// uri is passed when called from the tree (the form is already open on the left) - then the
// target is taken from it, not from the active editor; the title button passes no uri, the
// target is the active yaml.
function openPreview(context: vscode.ExtensionContext, uri?: vscode.Uri): void {
  let docUri = uri;
  if (!docUri) {
    const editor = vscode.window.activeTextEditor;
    if (!editor || editor.document.languageId !== "yaml") {
      void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: open a form yaml (КомпонентИнтерфейса) to preview it."));
      return;
    }
    docUri = editor.document.uri;
  }
  setTarget(docUri);
  if (!panel) {
    panel = vscode.window.createWebviewPanel(VIEW_TYPE, "XBSL", vscode.ViewColumn.Beside, {
      enableScripts: true,
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => {
      panel = undefined;
    }, undefined, context.subscriptions);
    panel.webview.onDidReceiveMessage((m) => {
      if (!m) {
        return;
      }
      if (m.type === "reveal" && typeof m.offset === "number") {
        void revealOffset(m.offset, false);
      } else if (m.type === "select" && typeof m.offset === "number") {
        // A preview click: the webview highlighted the block already; remember the choice
        // and keep the cursor-move echo (revealOffset below) from re-posting a highlight.
        selectedOffset = m.offset;
        suppressCursorSyncUntil = Date.now() + 300;
        if (cursorTimer) {
          clearTimeout(cursorTimer);
          cursorTimer = undefined;
        }
        selectNode(m.offset);
      } else if (m.type === "deselect") {
        selectedOffset = undefined;
      } else if (m.type === "view") {
        // Zoom and theme are applied inside the webview; here we only remember the choice.
        const next = { zoom: Number(m.zoom), theme: m.theme } as ViewState;
        if (isViewState(next)) {
          view = next;
          void context.globalState.update(STATE_KEY, view);
        }
      }
    }, undefined, context.subscriptions);
  } else {
    panel.reveal(panel.viewColumn ?? vscode.ViewColumn.Beside, true);
  }
  render();
}

function updateContext(editor: vscode.TextEditor | undefined): void {
  const isForm = !!editor && looksLikeForm(editor.document);
  void vscode.commands.executeCommand("setContext", "xbsl.formYaml", isForm);
}

export function registerFormPreview(context: vscode.ExtensionContext): void {
  const saved = context.globalState.get(STATE_KEY);
  if (isViewState(saved)) {
    view = saved;
  }
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.previewForm", (arg?: unknown) =>
      openPreview(context, arg instanceof vscode.Uri ? arg : undefined)
    ),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      updateContext(editor);
      // The panel follows the active form yaml - like the Markdown preview.
      if (panel && editor && looksLikeForm(editor.document)) {
        setTarget(editor.document.uri);
        scheduleRender();
      }
    }),
    vscode.workspace.onDidChangeTextDocument((e) => {
      if (panel && target && e.document.uri.toString() === target.toString()) {
        scheduleRender();
      }
    }),
    // The wireframe follows the yaml selection (debounced): the block of the node under
    // the cursor highlights and scrolls into view.
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
}
