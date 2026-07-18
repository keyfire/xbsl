// "Properties" v2 - the sidebar webview view (xbslProperties) of the visual form designer
// (docs/DESIGNER.md, stage 3): the typed properties of the interface component under the
// cursor of the active yaml editor, after the Flutter Property Editor pattern. The engine
// owns everything: the node comes from xbsl/formNodeAt, the component schema from
// xbsl/uiSchema, and every write is ONE xbsl/formEdit request whose text edits this module
// applies via WorkspaceEdit (native undo/redo). The panel model - sections, typed editors,
// validation, composite value_yaml assembly - is computed by formPropsCore.ts; here lives
// only the thin wiring: cursor sync, LSP calls, the webview shell and message routing.
// The older per-component panel (xbslFormProps inside the wireframe preview) and the
// metadata panel (xbslMetaProps) stay untouched until this panel replaces them.
//
// The panel is LSP-only by design: following the cursor with per-selection CLI processes
// would be unusable, so without the server it shows a hint instead.

import * as vscode from "vscode";
import {
  FormNodeDto,
  PanelModel,
  UiComponentDto,
  WritePayload,
  WritePlan,
  buildPanelModel,
  findRow,
  prepareWrite,
} from "./formPropsCore";
import { lspActive, lspRequest } from "./lspClient";
import { cspMeta, inlineJson, makeNonce } from "./webviewShared";

const VIEW_TYPE = "xbslProperties";
const SELECTION_DEBOUNCE_MS = 150;

interface Target {
  uri: vscode.Uri;
  nodeId: string;
  nodeSpanStart: number;
  type: string;
}

let view: vscode.WebviewView | undefined;
let target: Target | undefined;
let lastModel: PanelModel | null = null;
let lastHint: string | null = null;
// The sticky property: the focused row survives switching to another node of the same type
// (serial editing; panel memory only, deliberately not persisted).
const stickyByType = new Map<string, string>();
// Component schemas are static for the engine session; negative answers are cached too.
const schemaCache = new Map<string, UiComponentDto | null>();
let schemaUnavailable = false;
let seq = 0;
let debounceTimer: NodeJS.Timeout | undefined;

// -- shell ------------------------------------------------------------------------------------

function labels(): Record<string, string> {
  return {
    hintSelect: vscode.l10n.t(
      "Place the cursor on a form component in the yaml editor – its properties will show here."
    ),
    hintSlot: vscode.l10n.t("The cursor is on a slot – select a component inside it."),
    noSchema: vscode.l10n.t(
      "No schema data for this component – only the set properties are shown."
    ),
    secSet: vscode.l10n.t("Set"),
    secEvents: vscode.l10n.t("Events"),
    secAll: vscode.l10n.t("All properties"),
    search: vscode.l10n.t("Filter by name or value"),
    auto: vscode.l10n.t("Auto"),
    autoOption: vscode.l10n.t("(auto)"),
    toYaml: vscode.l10n.t("Show in yaml"),
    openInYaml: vscode.l10n.t("Open in yaml"),
    reset: vscode.l10n.t("Reset – remove the property from the yaml"),
    notSet: vscode.l10n.t("(not set)"),
    noHandler: vscode.l10n.t("(no handler)"),
    defaultPrefix: vscode.l10n.t("default:"),
    readonly: vscode.l10n.t("read-only"),
    typeLabel: vscode.l10n.t("Type"),
    valueLabel: vscode.l10n.t("Value"),
    compositeLocked: vscode.l10n.t("The value contains nested blocks – edit it in yaml."),
    typeOption: vscode.l10n.t("(type)"),
  };
}

function errorMessage(code: "empty" | "number" | "enum" | "color"): string {
  switch (code) {
    case "number":
      return vscode.l10n.t("The value must be a number.");
    case "enum":
      return vscode.l10n.t("The value must be one of the list.");
    case "color":
      return vscode.l10n.t("The color must be in the #RRGGBB form.");
    default:
      return vscode.l10n.t("An empty value is not written – use Reset to clear the property.");
  }
}

function shell(nonce: string): string {
  const L = inlineJson(labels());
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
${cspMeta(nonce)}
<style>
  body { color: var(--vscode-foreground); font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
    font-size: 13px; padding: 6px 10px 10px; margin: 0; overflow-x: hidden; overflow-wrap: anywhere; }
  .head { position: sticky; top: 0; z-index: 5; background: var(--vscode-sideBar-background, var(--vscode-editor-background));
    padding: 4px 0 6px; }
  .title { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 4px 8px; margin-bottom: 6px; }
  .ptype { font-weight: 600; word-break: break-word; min-width: 0; }
  .pname { opacity: .7; font-weight: 400; }
  .plink { background: transparent; border: 1px solid var(--vscode-panel-border); color: var(--vscode-foreground);
    border-radius: 3px; padding: 1px 8px; cursor: pointer; font-size: 11.5px; white-space: nowrap; }
  input[type=text], select, textarea { width: 100%; max-width: 100%; box-sizing: border-box;
    background: var(--vscode-input-background); color: var(--vscode-input-foreground, var(--vscode-foreground));
    border: 1px solid var(--vscode-input-border, rgba(128,128,128,.5)); border-radius: 3px;
    padding: 3px 7px; font-size: 12.5px; font-family: inherit; }
  textarea { resize: vertical; min-height: 52px; white-space: pre; }
  input[readonly] { opacity: .75; }
  .mono { font-family: var(--vscode-editor-font-family, monospace); }
  .hint { opacity: .65; font-style: italic; margin-top: 8px; }
  .note { opacity: .6; font-size: .85em; margin: 4px 0 8px; }
  details.sec { margin-bottom: 6px; }
  details.sec > summary { cursor: pointer; font-weight: 600; font-size: .9em; text-transform: uppercase;
    letter-spacing: .04em; opacity: .8; padding: 3px 0; user-select: none; }
  .row { margin: 0 0 9px; padding: 2px 4px; border-radius: 4px; border-left: 2px solid transparent; }
  .row.sel { background: var(--vscode-list-hoverBackground, rgba(128,128,128,.12));
    border-left-color: var(--vscode-focusBorder, #2f81f7); }
  .cap { display: flex; align-items: center; gap: 5px; font-size: .85em; margin-bottom: 2px; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: transparent; border: 1px solid rgba(128,128,128,.55); flex: none; }
  .set .dot { background: var(--vscode-charts-blue, #3794ff); border-color: var(--vscode-charts-blue, #3794ff); }
  .cap .name { opacity: .8; word-break: break-word; }
  .set .cap .name { opacity: 1; font-weight: 600; }
  .cap .sp { flex: 1; }
  .rbtn { background: transparent; border: none; color: var(--vscode-foreground); opacity: .55; cursor: pointer;
    padding: 0 3px; font-size: 12px; line-height: 1; }
  .rbtn:hover { opacity: 1; }
  .ro { opacity: .6; font-style: italic; font-size: .95em; }
  .grey { opacity: .55; }
  .err { color: var(--vscode-errorForeground, #f66); font-size: .85em; margin-top: 2px; min-height: 0; }
  .tri { display: flex; border: 1px solid var(--vscode-input-border, rgba(128,128,128,.5)); border-radius: 3px; overflow: hidden; }
  .tri button { flex: 1; background: transparent; border: none; color: var(--vscode-foreground); padding: 3px 0;
    cursor: pointer; font-size: 12px; opacity: .75; }
  .tri button.on { background: var(--vscode-button-background); color: var(--vscode-button-foreground); opacity: 1; }
  .pair { display: flex; flex-direction: column; gap: 4px; }
  .colorline { display: flex; gap: 6px; align-items: center; }
  .colorline input[type=color] { width: 30px; height: 24px; padding: 0; border: 1px solid var(--vscode-input-border, rgba(128,128,128,.5));
    border-radius: 3px; background: transparent; flex: none; cursor: pointer; }
  .colorline input[type=text] { flex: 1; }
  details.cmp { border: 1px solid var(--vscode-panel-border, rgba(128,128,128,.35)); border-radius: 4px; padding: 3px 7px; }
  details.cmp > summary { cursor: pointer; font-size: .95em; opacity: .85; user-select: none; }
  .cmp .sub { margin: 6px 0 4px 4px; }
  .cmp .subcap { font-size: .8em; opacity: .7; margin-bottom: 1px; }
  .valline { display: flex; gap: 5px; align-items: center; }
  .valline input, .valline .ro { flex: 1; min-width: 0; }
</style></head>
<body>
<div class="head">
  <div class="title" id="title"></div>
  <input type="text" id="search" placeholder="">
</div>
<div id="pane"></div>
<script nonce="${nonce}">
  const vsapi = acquireVsCodeApi();
  const L = ${L};
  const state = Object.assign({ search: "", open: { set: true, events: true, all: false } }, vsapi.getState() || {});
  if (!state.open) { state.open = { set: true, events: true, all: false }; }
  let model = null;
  let sticky = null;
  const pane = document.getElementById("pane");
  const titleBox = document.getElementById("title");
  const searchInput = document.getElementById("search");
  searchInput.placeholder = L.search;
  searchInput.value = state.search;
  searchInput.addEventListener("input", () => { state.search = searchInput.value; vsapi.setState(state); applyFilter(); });

  const post = (m) => vsapi.postMessage(m);
  const commit = (key, value, member) => post({ type: "commit", key, value, member });

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  // Esc restores the pre-edit value; Enter (or blur with a change) commits.
  function wireText(input, initial, onCommit, multiline) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { input.value = initial; input.blur(); e.stopPropagation(); }
      else if (e.key === "Enter" && (!multiline || e.ctrlKey)) { onCommit(input.value); e.preventDefault(); }
    });
    input.addEventListener("blur", () => { if (input.value !== initial) { onCommit(input.value); } });
  }

  function textEditor(row, multiline) {
    const input = document.createElement(multiline ? "textarea" : "input");
    if (!multiline) { input.type = "text"; }
    input.value = row.set ? row.value : "";
    if (!row.set && row.defaultValue) { input.placeholder = row.defaultValue; }
    wireText(input, input.value, (v) => commit(row.key, v), multiline);
    return input;
  }

  function triEditor(row) {
    const box = el("div", "tri");
    const current = row.set ? row.value : null;
    for (const v of [null, "Истина", "Ложь"]) {
      const b = el("button", null, v === null ? L.auto : v);
      if (v === null && row.defaultValue) { b.title = L.defaultPrefix + " " + row.defaultValue; }
      if ((v === null && current === null) || v === current) { b.classList.add("on"); }
      b.addEventListener("click", () => {
        if (v === null) { if (row.set) { post({ type: "reset", key: row.key }); } }
        else if (v !== current) { commit(row.key, v); }
      });
      box.appendChild(b);
    }
    return box;
  }

  function enumEditor(row) {
    const sel = document.createElement("select");
    const autoText = L.autoOption + (row.defaultValue ? " " + row.defaultValue : "");
    const auto = el("option", null, autoText);
    auto.value = "";
    sel.appendChild(auto);
    const options = row.editor.options.slice();
    if (row.set && row.value && !options.includes(row.value)) { options.unshift(row.value); }
    for (const o of options) {
      const opt = el("option", null, o);
      opt.value = o;
      sel.appendChild(opt);
    }
    sel.value = row.set ? row.value : "";
    sel.addEventListener("change", () => {
      if (sel.value === "") { if (row.set) { post({ type: "reset", key: row.key }); } }
      else { commit(row.key, sel.value); }
    });
    return sel;
  }

  function colorControls(initialHex, initialText, placeholder, onCommit) {
    const line = el("div", "colorline");
    const picker = document.createElement("input");
    picker.type = "color";
    if (/^#[0-9A-Fa-f]{6}$/.test(initialHex || "")) { picker.value = initialHex; }
    const text = document.createElement("input");
    text.type = "text";
    text.value = initialText;
    if (placeholder) { text.placeholder = placeholder; }
    picker.addEventListener("input", () => { text.value = picker.value; });
    picker.addEventListener("change", () => onCommit(picker.value));
    wireText(text, initialText, onCommit, false);
    line.appendChild(picker);
    line.appendChild(text);
    return line;
  }

  function colorEditor(row) {
    const initial = row.colorHex || (row.set ? row.value : "");
    return colorControls(row.colorHex, initial, !row.set && row.defaultValue ? row.defaultValue : "#RRGGBB",
      (v) => commit(row.key, v));
  }

  function unionEditor(row) {
    const pair = el("div", "pair");
    const sel = document.createElement("select");
    const none = el("option", null, L.typeOption);
    none.value = "";
    sel.appendChild(none);
    for (const t of row.editor.types) {
      const opt = el("option", null, t);
      opt.value = t;
      sel.appendChild(opt);
    }
    sel.value = row.editor.current && row.editor.types.includes(row.editor.current) ? row.editor.current : "";
    const valueBox = el("div");
    const buildValue = () => {
      valueBox.textContent = "";
      const member = sel.value;
      if (member === "Цвет") {
        valueBox.appendChild(colorControls(row.colorHex, row.colorHex || "", "#RRGGBB",
          (v) => commit(row.key, v, member)));
        return;
      }
      const input = document.createElement("input");
      input.type = "text";
      // A set scalar value belongs to no particular member - show it as the starting point;
      // a composite current value cannot seed a plain input, the user types anew.
      input.value = row.set && !row.editor.current ? row.value : "";
      if (!row.set && row.defaultValue) { input.placeholder = row.defaultValue; }
      wireText(input, input.value, (v) => commit(row.key, v, member), false);
      valueBox.appendChild(input);
    };
    sel.addEventListener("change", buildValue);
    buildValue();
    const capT = el("div", "subcap", L.typeLabel);
    const capV = el("div", "subcap", L.valueLabel);
    pair.appendChild(capT); pair.appendChild(sel);
    pair.appendChild(capV); pair.appendChild(valueBox);
    return pair;
  }

  function compositeEditor(row) {
    const details = el("details", "cmp");
    if (state.open["cmp:" + row.key]) { details.open = true; }
    details.addEventListener("toggle", () => { state.open["cmp:" + row.key] = details.open; vsapi.setState(state); });
    const summary = el("summary", null, row.value || "{...}");
    details.appendChild(summary);
    if (!row.editor.editable) {
      const note = el("div", "ro", L.compositeLocked);
      details.appendChild(note);
      return details;
    }
    const inputs = [];
    for (const f of row.editor.fields) {
      const sub = el("div", "sub");
      sub.appendChild(el("div", "subcap", f.key));
      const input = document.createElement("input");
      input.type = "text";
      input.value = f.value;
      const commitComposite = () => {
        post({ type: "commitComposite", key: row.key,
          fields: inputs.map((it) => ({ key: it.key, value: it.input.value })) });
      };
      wireText(input, f.value, commitComposite, false);
      inputs.push({ key: f.key, input });
      sub.appendChild(input);
      details.appendChild(sub);
    }
    return details;
  }

  function handlerEditor(row) {
    const line = el("div", "valline");
    if (row.set) {
      const name = el("span", "mono", row.value);
      line.appendChild(name);
      line.appendChild(gotoButton(row));
    } else {
      line.appendChild(el("span", "grey", L.noHandler));
    }
    return line;
  }

  function bindingEditor(row) {
    const line = el("div", "valline");
    const input = document.createElement("input");
    input.type = "text";
    input.className = "mono";
    input.value = row.value;
    input.readOnly = true;
    line.appendChild(input);
    line.appendChild(gotoButton(row));
    return line;
  }

  function readonlyEditor(row) {
    const line = el("div", "valline");
    const text = row.set ? row.value : (row.defaultValue ? row.defaultValue : L.notSet);
    line.appendChild(el("span", row.set ? "ro" : "ro grey", text));
    if (row.set) { line.appendChild(gotoButton(row)); }
    return line;
  }

  function gotoButton(row) {
    const b = el("button", "rbtn", "{}");
    b.title = L.openInYaml;
    b.addEventListener("click", (e) => {
      e.preventDefault();
      post({ type: "reveal", offset: row.propSpan ? row.propSpan.start : undefined });
    });
    return b;
  }

  function editorFor(row) {
    switch (row.editor.control) {
      case "tristate": return triEditor(row);
      case "enum": return enumEditor(row);
      case "number": return textEditor(row, false);
      case "text": return textEditor(row, row.editor.multiline);
      case "color": return colorEditor(row);
      case "union": return unionEditor(row);
      case "composite": return compositeEditor(row);
      case "binding": return bindingEditor(row);
      case "handler": return handlerEditor(row);
      default: return readonlyEditor(row);
    }
  }

  function buildRow(row) {
    const div = el("div", "row" + (row.set ? " set" : ""));
    div.dataset.key = row.key;
    div.dataset.hay = row.hay;
    const cap = el("div", "cap");
    cap.appendChild(el("span", "dot"));
    const name = el("span", "name", row.key);
    const tipParts = [];
    if (row.doc) { tipParts.push(row.doc); }
    if (row.event) { tipParts.push(row.event); }
    if (row.since) { tipParts.push("since " + row.since); }
    if (!row.set && row.defaultValue) { tipParts.push(L.defaultPrefix + " " + row.defaultValue); }
    if (tipParts.length) { name.title = tipParts.join("\\n"); }
    cap.appendChild(name);
    if (row.editor.control === "readonly") { cap.appendChild(el("span", "ro", "· " + L.readonly)); }
    cap.appendChild(el("span", "sp"));
    if (row.set && row.propSpan && row.editor.control !== "binding" && row.editor.control !== "handler"
        && row.editor.control !== "readonly") {
      cap.appendChild(gotoButton(row));
    }
    if (row.set) {
      const reset = el("button", "rbtn", "\\u2715");
      reset.title = L.reset;
      reset.addEventListener("click", () => post({ type: "reset", key: row.key }));
      cap.appendChild(reset);
    }
    div.appendChild(cap);
    div.appendChild(editorFor(row));
    div.appendChild(el("div", "err"));
    div.addEventListener("focusin", () => {
      post({ type: "sticky", key: row.key });
      markSticky(row.key);
    });
    return div;
  }

  function markSticky(key) {
    sticky = key;
    for (const r of pane.querySelectorAll(".row.sel")) { r.classList.remove("sel"); }
    for (const r of pane.querySelectorAll(".row")) {
      if (r.dataset.key === key) { r.classList.add("sel"); }
    }
  }

  function applyFilter() {
    const q = state.search.trim().toLowerCase();
    for (const sec of pane.querySelectorAll("details.sec")) {
      let visible = 0;
      for (const r of sec.querySelectorAll(".row")) {
        const show = !q || r.dataset.hay.includes(q);
        r.style.display = show ? "" : "none";
        if (show) { visible++; }
      }
      sec.style.display = visible ? "" : "none";
      if (q && visible) { sec.open = true; }
    }
  }

  function render() {
    pane.textContent = "";
    titleBox.textContent = "";
    if (!model) {
      searchInput.style.display = "none";
      pane.appendChild(el("div", "hint", window.__hint || L.hintSelect));
      return;
    }
    searchInput.style.display = "";
    const head = el("span", "ptype", model.type || model.nodeId);
    if (model.name) {
      head.appendChild(el("span", "pname", " · " + model.name));
    }
    const toYaml = el("button", "plink", L.toYaml);
    toYaml.addEventListener("click", () => post({ type: "reveal" }));
    titleBox.appendChild(head);
    titleBox.appendChild(toYaml);
    if (!model.schemaAvailable) {
      pane.appendChild(el("div", "note", L.noSchema));
    }
    const titles = { set: L.secSet, events: L.secEvents, all: L.secAll };
    for (const section of model.sections) {
      if (!section.rows.length) { continue; }
      const details = el("details", "sec");
      details.open = state.open[section.id] !== undefined ? state.open[section.id] : section.id !== "all";
      details.addEventListener("toggle", () => { state.open[section.id] = details.open; vsapi.setState(state); });
      details.appendChild(el("summary", null, titles[section.id] || section.id));
      for (const row of section.rows) {
        details.appendChild(buildRow(row));
      }
      pane.appendChild(details);
    }
    if (sticky) {
      markSticky(sticky);
      const first = pane.querySelector(".row.sel");
      if (first) {
        first.scrollIntoView({ block: "nearest" });
        if (document.hasFocus()) {
          const control = first.querySelector("input, select, textarea, button");
          if (control) { control.focus({ preventScroll: true }); }
        }
      }
    }
    applyFilter();
  }

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (!m) { return; }
    if (m.type === "model") {
      model = m.model || null;
      sticky = m.sticky || null;
      window.__hint = m.hint || null;
      render();
    } else if (m.type === "fieldError") {
      for (const r of pane.querySelectorAll(".row")) {
        if (r.dataset.key === m.key) {
          const err = r.querySelector(".err");
          if (err) { err.textContent = m.message; }
        }
      }
    }
  });
  render();
  post({ type: "ready" });
</script></body></html>`;
}

// -- data flow --------------------------------------------------------------------------------

function postModel(): void {
  if (!view) {
    return;
  }
  void view.webview.postMessage({
    type: "model",
    model: lastModel,
    hint: lastHint,
    sticky: target ? stickyByType.get(target.type) ?? null : null,
  });
}

function showHint(text: string): void {
  lastModel = null;
  lastHint = text;
  if (view) {
    view.description = undefined;
  }
  postModel();
}

// Cheap test before any LSP call: only interface component yamls have a form tree.
function isFormYaml(doc: vscode.TextDocument): boolean {
  if (doc.languageId !== "yaml") {
    return false;
  }
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return head.includes("КомпонентИнтерфейса") && doc.getText().includes("Наследует");
}

async function getSchema(type: string): Promise<UiComponentDto | null> {
  if (!type || schemaUnavailable) {
    return null;
  }
  const cached = schemaCache.get(type);
  if (cached !== undefined) {
    return cached;
  }
  const res = await lspRequest<{ available?: boolean; component?: UiComponentDto | null }>(
    "xbsl/uiSchema",
    { component: type }
  );
  if (!res || res.available === false) {
    schemaUnavailable = true; // the dataset has no ui schema - stop asking this session
    return null;
  }
  const schema = res.component ?? null;
  schemaCache.set(type, schema);
  return schema;
}

async function refreshForOffset(uri: vscode.Uri, offset: number): Promise<void> {
  const my = ++seq;
  if (!lspActive()) {
    showHint(
      vscode.l10n.t(
        "The properties panel needs the LSP mode (xbsl.lsp.enabled) and the xbsl engine with the form designer."
      )
    );
    return;
  }
  const res = await lspRequest<{ node?: FormNodeDto | null; error?: string }>("xbsl/formNodeAt", {
    uri: uri.toString(),
    offset,
  });
  if (seq !== my || !view) {
    return;
  }
  if (!res) {
    showHint(
      vscode.l10n.t("The engine does not answer the form requests – update the xbsl package.")
    );
    return;
  }
  if (res.error) {
    showHint(vscode.l10n.t("The yaml does not parse: {0}", res.error));
    return;
  }
  const node = res.node;
  if (!node) {
    showHint(
      vscode.l10n.t(
        "Place the cursor on a form component in the yaml editor – its properties will show here."
      )
    );
    return;
  }
  if (node.kind !== "component") {
    showHint(vscode.l10n.t("The cursor is on a slot – select a component inside it."));
    return;
  }
  const type = node.type ?? "";
  const schema = await getSchema(type);
  if (seq !== my || !view) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(uri);
  lastModel = buildPanelModel(node, schema, doc.getText());
  lastHint = null;
  target = { uri, nodeId: node.id, nodeSpanStart: node.span.start, type };
  view.description = [type, node.name ?? ""].filter(Boolean).join(" · ") || undefined;
  postModel();
}

function scheduleRefresh(uri: vscode.Uri, offset: number): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
  }
  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    void refreshForOffset(uri, offset);
  }, SELECTION_DEBOUNCE_MS);
}

function refreshFromActiveEditor(): void {
  const editor = vscode.window.activeTextEditor;
  if (editor && isFormYaml(editor.document)) {
    scheduleRefresh(editor.document.uri, editor.document.offsetAt(editor.selection.active));
  } else if (!lastModel) {
    showHint(
      vscode.l10n.t(
        "Place the cursor on a form component in the yaml editor – its properties will show here."
      )
    );
  }
}

// One write = one engine operation: the edits are computed against the buffer the server
// read, so a version change between the request and the response drops the stale edits and
// re-reads instead of writing them.
async function applyOperation(
  op: "set_property" | "reset_property",
  key: string,
  plan?: WritePlan
): Promise<void> {
  if (!target) {
    return;
  }
  const uri = target.uri;
  const doc = await vscode.workspace.openTextDocument(uri);
  const version = doc.version;
  const args: Record<string, unknown> = { node: target.nodeId, key };
  if (plan && plan.kind === "value") {
    args.value = plan.value;
  } else if (plan && plan.kind === "valueYaml") {
    args.valueYaml = plan.valueYaml;
  }
  const res = await lspRequest<{
    edits?: { start: number; end: number; newText: string }[];
    node?: { id: string; span: { start: number; end: number } } | null;
    error?: string;
  }>("xbsl/formEdit", { uri: uri.toString(), op, args });
  if (!res) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("The engine does not answer the form requests – update the xbsl package.")
    );
    return;
  }
  if (res.error) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", res.error));
    void refreshForOffset(uri, target.nodeSpanStart);
    return;
  }
  const fresh = await vscode.workspace.openTextDocument(uri);
  if (fresh.version !== version) {
    void refreshForOffset(uri, target.nodeSpanStart);
    return;
  }
  const we = new vscode.WorkspaceEdit();
  for (const e of res.edits ?? []) {
    we.replace(uri, new vscode.Range(fresh.positionAt(e.start), fresh.positionAt(e.end)), e.newText);
  }
  await vscode.workspace.applyEdit(we);
  // Node ids are positional and die with every change - re-read by the span start the
  // engine reported for the resulting node in the NEW text.
  void refreshForOffset(uri, res.node?.span?.start ?? target.nodeSpanStart);
}

function handleCommit(key: string, value: unknown, member: unknown): void {
  if (!lastModel || typeof value !== "string") {
    return;
  }
  const row = findRow(lastModel, key);
  if (!row) {
    return;
  }
  let payload: WritePayload;
  if (row.editor.control === "union") {
    payload = { form: "union", memberType: typeof member === "string" ? member : "", value };
  } else if (row.editor.control === "color") {
    payload = { form: "color", hex: value };
  } else {
    payload = { form: "scalar", value, editor: row.editor, wasSet: row.set, oldValue: row.value };
  }
  dispatchPlan(key, prepareWrite(payload));
}

function handleCommitComposite(key: string, fields: unknown): void {
  if (!Array.isArray(fields)) {
    return;
  }
  const clean = fields
    .filter((f) => f && typeof f.key === "string" && typeof f.value === "string")
    .map((f) => ({ key: f.key as string, value: f.value as string }));
  dispatchPlan(key, prepareWrite({ form: "composite", fields: clean }));
}

function dispatchPlan(key: string, plan: WritePlan): void {
  if (plan.kind === "noop") {
    return;
  }
  if (plan.kind === "error") {
    void view?.webview.postMessage({ type: "fieldError", key, message: errorMessage(plan.code) });
    return;
  }
  if (plan.kind === "reset") {
    void applyOperation("reset_property", key);
    return;
  }
  void applyOperation("set_property", key, plan);
}

async function reveal(offset: number | undefined): Promise<void> {
  if (!target) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target.uri);
  const pos = doc.positionAt(Math.min(offset ?? target.nodeSpanStart, doc.getText().length));
  const editor = await vscode.window.showTextDocument(doc, { preview: false });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// -- provider and registration ----------------------------------------------------------------

class FormPropsViewProvider implements vscode.WebviewViewProvider {
  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(v: vscode.WebviewView): void {
    view = v;
    v.webview.options = { enableScripts: true };
    v.webview.html = shell(makeNonce());
    v.onDidDispose(
      () => {
        view = undefined;
      },
      undefined,
      this.context.subscriptions
    );
    // No retainContextWhenHidden: the webview keeps its own bits via getState/setState and
    // asks for the model again with "ready" when it comes back.
    v.onDidChangeVisibility(
      () => {
        if (v.visible) {
          refreshFromActiveEditor();
        }
      },
      undefined,
      this.context.subscriptions
    );
    v.webview.onDidReceiveMessage(
      (m) => {
        if (!m) {
          return;
        }
        if (m.type === "ready") {
          postModel();
        } else if (m.type === "commit" && typeof m.key === "string") {
          handleCommit(m.key, m.value, m.member);
        } else if (m.type === "commitComposite" && typeof m.key === "string") {
          handleCommitComposite(m.key, m.fields);
        } else if (m.type === "reset" && typeof m.key === "string") {
          void applyOperation("reset_property", m.key);
        } else if (m.type === "reveal") {
          void reveal(typeof m.offset === "number" ? m.offset : undefined);
        } else if (m.type === "sticky" && typeof m.key === "string" && target) {
          stickyByType.set(target.type, m.key);
        }
      },
      undefined,
      this.context.subscriptions
    );
  }
}

async function ensureView(): Promise<void> {
  if (view) {
    view.show(true);
    return;
  }
  await vscode.commands.executeCommand(`${VIEW_TYPE}.focus`);
}

export function registerFormProps(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW_TYPE, new FormPropsViewProvider(context)),
    // The cursor is the selection source: the node under it fills the panel (two-way sync
    // with the future structure view goes through the same command below).
    vscode.window.onDidChangeTextEditorSelection((e) => {
      if (!view?.visible || e.textEditor !== vscode.window.activeTextEditor) {
        return;
      }
      if (!isFormYaml(e.textEditor.document)) {
        return;
      }
      const doc = e.textEditor.document;
      scheduleRefresh(doc.uri, doc.offsetAt(e.selections[0].active));
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (view?.visible && editor && isFormYaml(editor.document)) {
        scheduleRefresh(editor.document.uri, editor.document.offsetAt(editor.selection.active));
      }
    }),
    // Entry point for the structure view (the parallel track) and for scripts: show the
    // properties of the node at an explicit uri/offset.
    vscode.commands.registerCommand(
      "xbsl.properties.showForNode",
      async (uriArg?: unknown, offset?: unknown) => {
        const uri =
          uriArg instanceof vscode.Uri
            ? uriArg
            : typeof uriArg === "string"
              ? vscode.Uri.parse(uriArg)
              : vscode.window.activeTextEditor?.document.uri;
        if (!uri) {
          return;
        }
        await ensureView();
        await refreshForOffset(uri, typeof offset === "number" ? offset : 0);
      }
    )
  );
}
