// "Properties" - the ONE sidebar webview view (xbslProperties) of the designer container
// (docs/DESIGNER.md, stage 3: one properties engine that replaced both earlier panels).
// The panel follows the active editor, the last signal wins; three fill modes:
//   component - an interface component yaml: the typed properties of the form node under
//     the cursor, after the Flutter Property Editor pattern. The engine owns everything:
//     the node comes from xbsl/formNodeAt, the component schema from xbsl/uiSchema, and
//     every write is ONE xbsl/formEdit request whose text edits this module applies via
//     WorkspaceEdit (native undo/redo). The panel model - sections, typed editors,
//     validation, composite value_yaml assembly, handler dropdown content - is computed
//     by formPropsCore.ts. The EVENTS rows are interactive (hook 1): the dropdown binds
//     an existing method of the paired module (a plain set_property), "(no handler)"
//     resets the key, and "(create a handler...)" drives xbsl/addHandler - one multi-file
//     WorkspaceEdit writes the yaml binding and the module stub together, then the cursor
//     jumps to the method. This mode is LSP-only by design: following the cursor with
//     per-selection CLI processes would be unusable, so without the server it shows a hint.
//   metadata - any other element yaml (or a selection in the metadata tree, or an .xbsl
//     module through its paired yaml): the scalar properties of the object/field map under
//     the cursor. The rows come from describeMetaNode/describeStandardAttr (metadataCore)
//     through the shared model (propsModes.ts); writes are targeted local replacements -
//     propertyEdit/insertItemEdit assembled by metaPropertyEdits (no engine involved).
//   the structure view and the preview land here through xbsl.properties.showForNode, the
//     metadata tree - through xbsl.metadata.props (which also reveals the panel).
// Here lives only the thin wiring: mode resolution per editor (propsModes.classifyEditor),
// cursor sync, LSP calls, the webview shell and message routing.

import * as vscode from "vscode";
import {
  AddHandlerResponse,
  FormNodeAtPayload,
  ModuleHandlersPayload,
  PanelModel,
  UiComponentDto,
  WritePayload,
  WritePlan,
  buildAddHandlerParams,
  buildPanelModel,
  defaultHandlerName,
  findRow,
  panelTarget,
  planHandlerApply,
  prepareWrite,
} from "./formPropsCore";
import {
  MetaSelector,
  buildMetaPanelModel,
  classifyEditor,
  describeMetaSelection,
  metaPropertyEdits,
  pairedYamlPath,
} from "./propsModes";
import { findAttrOffset } from "./metadataCore";
import { lspActive, lspRequest } from "./lspClient";
import { cspMeta, inlineJson, makeNonce } from "./webviewShared";

const VIEW_TYPE = "xbslProperties";
const SELECTION_DEBOUNCE_MS = 150;
const IDENTIFIER = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;

// The panel target of the last fill. The component target carries what one xbsl/formEdit
// call needs; the metadata target - the node offset for propertyEdit plus the standard
// attribute identity when the panel shows one (possibly synthetic - see metaPropertyEdits).
type Target =
  | { kind: "component"; uri: vscode.Uri; nodeId: string; nodeSpanStart: number; type: string }
  | { kind: "metadata"; uri: vscode.Uri; offset: number; std?: { kind: string; name: string } };

let view: vscode.WebviewView | undefined;
let target: Target | undefined;
// Supplier of type candidates (from the metadata tree provider) for the Тип combobox of
// the metadata mode; may be absent - the combobox then degrades to a plain input.
let typeCandidatesFn: (() => Promise<string[]>) | undefined;
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
    hintIdle: vscode.l10n.t(
      "Open an element yaml or module, or select a node in the metadata tree – the properties will show here."
    ),
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
    createHandler: vscode.l10n.t("(create a handler...)"),
    groupCompatible: vscode.l10n.t("Suitable methods"),
    groupOther: vscode.l10n.t("Other methods"),
    gotoMethod: vscode.l10n.t("Go to the handler method"),
    missingMethod: vscode.l10n.t("The method is not in the module"),
    dotSet: vscode.l10n.t("Set in yaml"),
    dotDefault: vscode.l10n.t("Not set – the platform default applies"),
    dotHandler: vscode.l10n.t("A handler is assigned"),
    dotNoHandler: vscode.l10n.t("No handler"),
    legend: vscode.l10n.t(
      "A filled dot – the property is set in yaml, an outlined one – the platform default applies."
    ),
    emptyNote: vscode.l10n.t("An empty value is not written – use Reset to clear the property."),
    defaultPrefix: vscode.l10n.t("default:"),
    readonly: vscode.l10n.t("read-only"),
    typeLabel: vscode.l10n.t("Type"),
    valueLabel: vscode.l10n.t("Value"),
    compositeLocked: vscode.l10n.t("The value contains nested blocks – edit it in yaml."),
    typeOption: vscode.l10n.t("(type)"),
    valueOption: vscode.l10n.t("(value)"),
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
  .legend { opacity: .55; font-size: .85em; margin-top: 10px; }
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
  .combo { position: relative; }
  .combo-list { position: absolute; left: 0; right: 0; top: 100%; margin-top: 2px; z-index: 20;
    max-height: 220px; overflow-y: auto; background: var(--vscode-dropdown-background, var(--vscode-input-background));
    border: 1px solid var(--vscode-dropdown-border, var(--vscode-input-border, rgba(128,128,128,.5)));
    border-radius: 3px; box-shadow: 0 2px 8px rgba(0,0,0,.28); }
  .combo-opt { padding: 3px 8px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12.5px; }
  .combo-opt:hover { background: var(--vscode-list-hoverBackground, rgba(128,128,128,.18)); }
  .combo-opt.cur { background: var(--vscode-list-activeSelectionBackground, rgba(38,146,222,.35)); color: var(--vscode-list-activeSelectionForeground, inherit); }
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

  // An open combobox (the metadata Тип rows): on focus ALL candidates are shown (a native
  // datalist filters by the current value and would show only it), typing filters; a value
  // can also be typed manually. An empty commit clears the property (the metadata route
  // treats it as a removal - the historical panel semantics).
  function comboEditor(row) {
    const wrap = el("div", "combo");
    const input = document.createElement("input");
    input.type = "text";
    input.value = row.set ? row.value : "";
    const list = el("div", "combo-list");
    list.style.display = "none";
    const opts = row.editor.options || [];
    let last = input.value; // guard against re-sending the same value
    const commitValue = (v) => { if (v !== last) { last = v; commit(row.key, v); } };
    const build = (showAll) => {
      const q = showAll ? "" : input.value.trim().toLowerCase();
      list.textContent = "";
      const matches = opts.filter((o) => !q || o.toLowerCase().includes(q));
      if (!matches.length) { list.style.display = "none"; return; }
      for (const o of matches) {
        const it = el("div", "combo-opt" + (o === input.value ? " cur" : ""), o);
        // mousedown (before blur) so the click manages to pick the item.
        it.addEventListener("mousedown", (e) => { e.preventDefault(); input.value = o; list.style.display = "none"; commitValue(o); });
        list.appendChild(it);
      }
      list.style.display = "block";
      const cur = list.querySelector(".combo-opt.cur");
      if (cur) { cur.scrollIntoView({ block: "nearest" }); }
    };
    input.addEventListener("focus", () => build(true));
    input.addEventListener("click", () => build(true));
    input.addEventListener("input", () => build(false));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { list.style.display = "none"; commitValue(input.value); }
      else if (e.key === "Escape") { list.style.display = "none"; }
    });
    input.addEventListener("blur", () => { setTimeout(() => { list.style.display = "none"; commitValue(input.value); }, 150); });
    wrap.appendChild(input); wrap.appendChild(list);
    return wrap;
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
      // An enumeration member gets a dropdown of its values (row.editor.enums comes from
      // the engine's per-component enums map; absent on older engines - plain input then).
      const options = row.editor.enums ? row.editor.enums[member] : undefined;
      if (options && options.length) {
        const values = document.createElement("select");
        const none = el("option", null, L.valueOption);
        none.value = "";
        values.appendChild(none);
        for (const o of options) {
          const opt = el("option", null, o);
          opt.value = o;
          values.appendChild(opt);
        }
        // A set scalar value belongs to no particular member; preselect it only when it
        // is one of this member's values.
        const current = row.set && !row.editor.current ? row.value : "";
        values.value = options.includes(current) ? current : "";
        values.addEventListener("change", () => {
          if (values.value !== "") { commit(row.key, values.value, member); }
        });
        valueBox.appendChild(values);
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

  // An event row: a dropdown of the paired module's methods. "(no handler)" resets the
  // property, "(create a handler...)" starts the two-file stub flow in the extension;
  // choosing an existing method is a plain set_property.
  const CREATE_HANDLER = " create"; // no method name can collide with this value
  function handlerEditor(row) {
    const line = el("div", "valline");
    const sel = document.createElement("select");
    sel.className = "mono";
    const addOption = (parent, value, text, title) => {
      const opt = el("option", null, text);
      opt.value = value;
      if (title) { opt.title = title; }
      parent.appendChild(opt);
    };
    addOption(sel, "", L.noHandler);
    const choices = row.editor.choices || { compatible: [], rest: [], currentMissing: false };
    const listed = new Set();
    // A bound method the module does not have stays selectable (and marked) - the row
    // must render the truth of the yaml, not silently pick another method.
    if (row.set && row.value && (choices.currentMissing
        || (!choices.compatible.includes(row.value) && !choices.rest.includes(row.value)))) {
      addOption(sel, row.value, row.value + (choices.currentMissing ? " ⚠" : ""),
        choices.currentMissing ? L.missingMethod : undefined);
      listed.add(row.value);
    }
    if (choices.compatible.length) {
      const fit = document.createElement("optgroup");
      fit.label = L.groupCompatible;
      for (const name of choices.compatible) { addOption(fit, name, name); listed.add(name); }
      sel.appendChild(fit);
      if (choices.rest.length) {
        const other = document.createElement("optgroup");
        other.label = L.groupOther;
        for (const name of choices.rest) { addOption(other, name, name); listed.add(name); }
        sel.appendChild(other);
      }
    } else {
      for (const name of choices.rest) {
        if (!listed.has(name)) { addOption(sel, name, name); listed.add(name); }
      }
    }
    addOption(sel, CREATE_HANDLER, L.createHandler);
    sel.value = row.set && row.value ? row.value : "";
    let prev = sel.value;
    sel.addEventListener("change", () => {
      const v = sel.value;
      if (v === CREATE_HANDLER) {
        sel.value = prev; // the flow may be cancelled - do not leave "(create...)" shown
        post({ type: "createHandler", key: row.key });
        return;
      }
      if (v === "") {
        if (row.set) { post({ type: "reset", key: row.key }); } else { prev = v; }
        return;
      }
      prev = v;
      if (!row.set || v !== row.value) { commit(row.key, v); }
    });
    line.appendChild(sel);
    if (row.set && row.value) {
      const go = el("button", "rbtn", "\\u2192");
      go.title = L.gotoMethod;
      go.addEventListener("click", (e) => {
        e.preventDefault();
        post({ type: "gotoHandler", key: row.key, method: row.value });
      });
      line.appendChild(go);
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
      case "combo": return comboEditor(row);
      default: return readonlyEditor(row);
    }
  }

  function buildRow(row) {
    const div = el("div", "row" + (row.set ? " set" : ""));
    div.dataset.key = row.key;
    div.dataset.hay = row.hay;
    const cap = el("div", "cap");
    // The set/default indicator explains itself on hover; handler rows (events) word it
    // in handler terms.
    const dot = el("span", "dot");
    dot.title = row.editor.control === "handler"
      ? (row.set ? L.dotHandler : L.dotNoHandler)
      : (row.set ? L.dotSet : L.dotDefault);
    cap.appendChild(dot);
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
    // Handler rows keep the yaml jump here: their value line carries the method jump.
    if (row.set && row.propSpan && row.editor.control !== "binding"
        && row.editor.control !== "readonly") {
      cap.appendChild(gotoButton(row));
    }
    // Read-only rows (Ид, ВидЭлемента, slots) cannot be edited - deleting them from the
    // panel would be the only "edit" left, so they get no reset either.
    if (row.set && row.editor.control !== "readonly") {
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
    const secs = pane.querySelectorAll("details.sec");
    if (!secs.length) {
      // The metadata mode renders the rows flat, without section chrome.
      for (const r of pane.querySelectorAll(".row")) {
        r.style.display = !q || r.dataset.hay.includes(q) ? "" : "none";
      }
      return;
    }
    for (const sec of secs) {
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
      pane.appendChild(el("div", "hint", window.__hint || L.hintIdle));
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
    if (model.meta) {
      // The metadata mode: one flat row list - the sections, the events and the legend are
      // component-mode concepts; the search works over the same rows.
      for (const section of model.sections) {
        for (const row of section.rows) {
          pane.appendChild(buildRow(row));
        }
      }
      applyFilter();
      return;
    }
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
    // Footer: the indicator legend next to the empty-value hint.
    pane.appendChild(el("div", "legend", L.legend + " " + L.emptyNote));
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
    // The sticky row is a component-mode habit (serial editing across same-type nodes);
    // metadata nodes share no type, so the memory does not apply.
    sticky: target?.kind === "component" ? stickyByType.get(target.type) ?? null : null,
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

// The fill mode an editor drives (a cheap text test - no LSP calls): component yamls go
// to the form-node flow, other element yamls and .xbsl modules to the metadata flow.
function classifyDoc(doc: vscode.TextDocument): ReturnType<typeof classifyEditor> {
  const head = doc.getText(new vscode.Range(0, 0, Math.min(50, doc.lineCount), 0));
  return classifyEditor(doc.languageId, doc.fileName, head, doc.getText());
}

async function getSchema(type: string): Promise<UiComponentDto | null> {
  if (!type || schemaUnavailable) {
    return null;
  }
  const cached = schemaCache.get(type);
  if (cached !== undefined) {
    return cached;
  }
  const res = await lspRequest<{
    available?: boolean;
    component?: UiComponentDto | null;
    enums?: Record<string, string[]>;
  }>("xbsl/uiSchema", { component: type });
  if (!res || res.available === false) {
    schemaUnavailable = true; // the dataset has no ui schema - stop asking this session
    return null;
  }
  // The response-level enums (values of the enumerations referenced by the property
  // unions) are folded into the cached record - the panel model reads schema.enums.
  const schema = res.component ? { ...res.component, enums: res.enums } : null;
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
  const res = await lspRequest<FormNodeAtPayload>("xbsl/formNodeAt", {
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
  if (!res.node) {
    showHint(
      vscode.l10n.t(
        "Place the cursor on a form component in the yaml editor – its properties will show here."
      )
    );
    return;
  }
  // A slot hit shows its owner component (the engine sends the parent along); the slot
  // hint remains only for older engines whose response carries no parent.
  const shown = panelTarget(res);
  if (!shown) {
    showHint(vscode.l10n.t("The cursor is on a slot – select a component inside it."));
    return;
  }
  const node = shown.node;
  const type = node.type ?? "";
  const schema = await getSchema(type);
  if (seq !== my || !view) {
    return;
  }
  // The paired module's methods feed the event dropdowns. Not cached: the module changes
  // independently of the yaml, and the request is as cheap as formNodeAt above. undefined
  // (older engine, failed request) degrades the dropdowns, nothing more.
  const handlers = await lspRequest<ModuleHandlersPayload>("xbsl/moduleHandlers", {
    uri: uri.toString(),
  });
  if (seq !== my || !view) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(uri);
  lastModel = buildPanelModel(node, schema, doc.getText(), handlers && !handlers.error ? handlers : undefined);
  lastHint = null;
  target = { kind: "component", uri, nodeId: node.id, nodeSpanStart: node.span.start, type };
  const titleParts = [type, node.name ?? ""].filter(Boolean);
  if (shown.viaSlot) {
    titleParts.push(vscode.l10n.t("Slot {0}", shown.viaSlot));
  }
  view.description = titleParts.join(" · ") || undefined;
  postModel();
}

// -- metadata mode ----------------------------------------------------------------------------

function idleHint(): string {
  return vscode.l10n.t(
    "Open an element yaml or module, or select a node in the metadata tree – the properties will show here."
  );
}

// The metadata fill: the rows come from the pure core (describeMetaSelection over the open
// buffer), the Тип combobox candidates from the metadata tree provider. No LSP involved -
// the mode works in the CLI mode too, exactly like the historical metadata panel.
async function refreshMetadata(uri: vscode.Uri, sel: MetaSelector): Promise<void> {
  const my = ++seq;
  let doc: vscode.TextDocument;
  try {
    doc = await vscode.workspace.openTextDocument(uri);
  } catch {
    return;
  }
  if (seq !== my || !view) {
    return;
  }
  const text = doc.getText();
  const desc = describeMetaSelection(text, sel);
  if (!desc) {
    showHint(idleHint());
    return;
  }
  let candidates: string[] | undefined;
  if (typeCandidatesFn && desc.rows.some((r) => r.control === "combo")) {
    candidates = await typeCandidatesFn();
    if (seq !== my || !view) {
      return;
    }
  }
  lastModel = buildMetaPanelModel(desc, candidates);
  lastHint = null;
  target = { kind: "metadata", uri, offset: desc.offset, std: sel.std };
  view.description = [lastModel.type, lastModel.name].filter(Boolean).join(" · ") || undefined;
  postModel();
}

// A module shows its paired yaml's object properties (the same stem; X.Объект.xbsl -> X).
async function refreshForModule(uri: vscode.Uri): Promise<void> {
  const pair = pairedYamlPath(uri.fsPath);
  const pairUri = pair ? vscode.Uri.file(pair) : undefined;
  if (pairUri) {
    try {
      await vscode.workspace.fs.stat(pairUri);
      await refreshMetadata(pairUri, { cursor: 0 });
      return;
    } catch {
      // fall through to the hint - the pair does not exist
    }
  }
  showHint(
    vscode.l10n.t("The module has no paired yaml description – the object properties cannot be shown.")
  );
}

// A tree signal or an explicit command outranks a pending cursor refresh: the debounced
// editor fill must not overwrite the fresher target ("the last signal wins").
function cancelScheduledRefresh(): void {
  if (debounceTimer) {
    clearTimeout(debounceTimer);
    debounceTimer = undefined;
  }
}

function scheduleRefresh(uri: vscode.Uri, offset: number, mode: "component" | "metadata"): void {
  cancelScheduledRefresh();
  debounceTimer = setTimeout(() => {
    debounceTimer = undefined;
    if (mode === "component") {
      void refreshForOffset(uri, offset);
    } else {
      void refreshMetadata(uri, { cursor: offset });
    }
  }, SELECTION_DEBOUNCE_MS);
}

function refreshFromActiveEditor(): void {
  const editor = vscode.window.activeTextEditor;
  const mode = editor ? classifyDoc(editor.document) : "none";
  if (editor && (mode === "component" || mode === "metadata")) {
    scheduleRefresh(editor.document.uri, editor.document.offsetAt(editor.selection.active), mode);
  } else if (editor && mode === "module") {
    void refreshForModule(editor.document.uri);
  } else if (!lastModel) {
    showHint(idleHint());
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
  if (target?.kind !== "component") {
    return;
  }
  const tgt = target; // snapshot: a concurrent refresh may retarget the panel mid-flight
  const uri = tgt.uri;
  const doc = await vscode.workspace.openTextDocument(uri);
  const version = doc.version;
  // The operation arguments ride FLAT in params (uri, op, node, key, value...): over the
  // real pygls channel a nested args object arrives as a namedtuple, not a dict, which
  // older engines could not read at all.
  const params: Record<string, unknown> = { uri: uri.toString(), op, node: tgt.nodeId, key };
  if (plan && plan.kind === "value") {
    params.value = plan.value;
  } else if (plan && plan.kind === "valueYaml") {
    params.valueYaml = plan.valueYaml;
  }
  const res = await lspRequest<{
    edits?: { start: number; end: number; newText: string }[];
    node?: { id: string; span: { start: number; end: number } } | null;
    error?: string;
  }>("xbsl/formEdit", params);
  if (!res) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("The engine does not answer the form requests – update the xbsl package.")
    );
    return;
  }
  if (res.error) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", res.error));
    void refreshForOffset(uri, tgt.nodeSpanStart);
    return;
  }
  const fresh = await vscode.workspace.openTextDocument(uri);
  if (fresh.version !== version) {
    void refreshForOffset(uri, tgt.nodeSpanStart);
    return;
  }
  const we = new vscode.WorkspaceEdit();
  for (const e of res.edits ?? []) {
    we.replace(uri, new vscode.Range(fresh.positionAt(e.start), fresh.positionAt(e.end)), e.newText);
  }
  await vscode.workspace.applyEdit(we);
  // Node ids are positional and die with every change - re-read by the span start the
  // engine reported for the resulting node in the NEW text.
  void refreshForOffset(uri, res.node?.span?.start ?? tgt.nodeSpanStart);
}

// One metadata write: existing targeted edits (metaPropertyEdits over propertyEdit and
// insertItemEdit) applied as a WorkspaceEdit, then a re-read of the same node. value null
// removes the key - the Reset button, the Авто tristate and an emptied editor all land here.
async function applyMetaProp(key: string, value: string | null): Promise<void> {
  if (target?.kind !== "metadata") {
    return;
  }
  const tgt = target;
  const doc = await vscode.workspace.openTextDocument(tgt.uri);
  const text = doc.getText();
  const edits = metaPropertyEdits(text, { offset: tgt.offset, std: tgt.std }, key, value);
  if (!edits.length) {
    return;
  }
  const we = new vscode.WorkspaceEdit();
  for (const e of edits) {
    we.replace(tgt.uri, new vscode.Range(doc.positionAt(e.start), doc.positionAt(e.end)), e.newText);
  }
  await vscode.workspace.applyEdit(we);
  // The property lines live below the node start, so the node offset survives the edit;
  // a standard attribute is re-found by name (it may have just materialized).
  await refreshMetadata(tgt.uri, tgt.std ? { std: tgt.std } : { offset: tgt.offset });
}

function handleCommit(key: string, value: unknown, member: unknown): void {
  if (!lastModel || typeof value !== "string") {
    return;
  }
  // The metadata mode: the historical panel semantics - an empty value removes the key
  // ("not set" = the key is absent from yaml); everything else is a plain scalar write.
  if (target?.kind === "metadata") {
    void applyMetaProp(key, value === "" ? null : value);
    return;
  }
  const row = findRow(lastModel, key);
  if (!row) {
    return;
  }
  let payload: WritePayload;
  if (row.editor.control === "union") {
    const memberType = typeof member === "string" ? member : "";
    payload = {
      form: "union",
      memberType,
      value,
      // The value list of an enumeration member gates the write (dropdown or not).
      options: row.editor.enums?.[memberType],
    };
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
  // The metadata mode reveals the node line; a synthetic standard attribute (no node in
  // yaml) falls back to the materialized record by name, or the object start.
  const fallback =
    target.kind === "component"
      ? target.nodeSpanStart
      : target.std
        ? findAttrOffset(doc.getText(), target.std.name) ?? 0
        : Math.max(target.offset, 0);
  const pos = doc.positionAt(Math.min(offset ?? fallback, doc.getText().length));
  const editor = await vscode.window.showTextDocument(doc, { preview: false });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// -- event handlers (hook 1: create/bind/jump) --------------------------------------------------

// The paired module of a component yaml (the engine's module_path_for: same stem, .xbsl).
function moduleUriFor(yamlUri: vscode.Uri): vscode.Uri {
  return yamlUri.with({ path: yamlUri.path.replace(/\.[^./\\]*$/, "") + ".xbsl" });
}

async function openAtOffset(uri: vscode.Uri, offset: number): Promise<void> {
  const doc = await vscode.workspace.openTextDocument(uri);
  const pos = doc.positionAt(Math.min(offset, doc.getText().length));
  const editor = await vscode.window.showTextDocument(doc, { preview: false });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// "Go to the handler method": jump to the method name in the paired module; a method the
// module does not have gets a warning with an offer to create exactly that stub.
async function gotoHandler(key: string, method: string): Promise<void> {
  if (target?.kind !== "component" || !method) {
    return;
  }
  const handlers = await lspRequest<ModuleHandlersPayload>("xbsl/moduleHandlers", {
    uri: target.uri.toString(),
  });
  if (!handlers || handlers.error) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("The engine does not answer the form requests – update the xbsl package.")
    );
    return;
  }
  const found = handlers.methods?.find((m) => m.name === method);
  if (handlers.available && handlers.module && found) {
    const span = found.nameSpan ?? found.span;
    await openAtOffset(vscode.Uri.parse(handlers.module), span?.start ?? 0);
    return;
  }
  const create = vscode.l10n.t("Create the handler");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t('The method "{0}" is not in the paired module – create it?', method),
    create
  );
  if (pick === create) {
    const row = lastModel ? findRow(lastModel, key) : undefined;
    await runAddHandler(key, method, row?.event);
  }
}

// "(create a handler...)": suggest the engine's default name in an InputBox. Decision
// documented: a NON-EMPTY input is sent as the explicit method (an existing name means
// "bind to it" per the engine contract); an EMPTY input sends no method at all - the
// engine derives <Имя|Тип><Ключ> itself and uniquifies it against the module.
async function createHandler(key: string): Promise<void> {
  if (target?.kind !== "component" || !lastModel) {
    return;
  }
  const row = findRow(lastModel, key);
  const value = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Handler method name (empty – the engine derives it from the node and the event)"),
    value: defaultHandlerName({ name: lastModel.name, type: lastModel.type }, key),
    validateInput: (v) =>
      !v.trim() || IDENTIFIER.test(v.trim())
        ? undefined
        : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (value === undefined) {
    return; // cancelled
  }
  await runAddHandler(key, value.trim() || undefined, row?.event);
}

// One xbsl/addHandler round trip applied as a single multi-file WorkspaceEdit: the yaml
// gets the binding, the module gets the stub (or the whole new file), the cursor lands on
// the method name. Versions of both buffers are pinned around the request - the engine
// computed the edits against them.
async function runAddHandler(key: string, method?: string, signature?: string): Promise<void> {
  if (target?.kind !== "component") {
    return;
  }
  const tgt = target; // snapshot: a concurrent refresh may retarget the panel mid-flight
  if (!lspActive()) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t(
        "The properties panel needs the LSP mode (xbsl.lsp.enabled) and the xbsl engine with the form designer."
      )
    );
    return;
  }
  const uri = tgt.uri;
  const yamlVersion = (await vscode.workspace.openTextDocument(uri)).version;
  let moduleVersion: number | undefined;
  try {
    moduleVersion = (await vscode.workspace.openTextDocument(moduleUriFor(uri))).version;
  } catch {
    // the module file does not exist yet - the response will carry its full content
  }
  const res = await lspRequest<AddHandlerResponse>(
    "xbsl/addHandler",
    buildAddHandlerParams(uri.toString(), tgt.nodeId, key, method, signature)
  );
  if (!res) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("The engine does not answer the form requests – update the xbsl package.")
    );
    return;
  }
  const outcome = planHandlerApply(res);
  if ("error" in outcome) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: {0}", outcome.error));
    return;
  }
  const plan = outcome.plan;
  const moduleUri = vscode.Uri.parse(plan.moduleUri);
  const yamlDoc = await vscode.workspace.openTextDocument(uri);
  if (yamlDoc.version !== yamlVersion) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("XBSL: the buffer changed while the edit was being computed – try again.")
    );
    return;
  }
  const we = new vscode.WorkspaceEdit();
  for (const e of plan.yamlEdits) {
    we.replace(uri, new vscode.Range(yamlDoc.positionAt(e.start), yamlDoc.positionAt(e.end)), e.newText);
  }
  if (plan.createFile) {
    // created=true: the file does not exist, moduleText IS its full content.
    we.createFile(moduleUri, { ignoreIfExists: false });
    we.insert(moduleUri, new vscode.Position(0, 0), plan.moduleText);
  } else if (plan.moduleEdits.length) {
    const moduleDoc = await vscode.workspace.openTextDocument(moduleUri);
    if (moduleVersion !== undefined && moduleDoc.version !== moduleVersion) {
      void vscode.window.showWarningMessage(
        vscode.l10n.t("XBSL: the buffer changed while the edit was being computed – try again.")
      );
      return;
    }
    for (const e of plan.moduleEdits) {
      we.replace(
        moduleUri,
        new vscode.Range(moduleDoc.positionAt(e.start), moduleDoc.positionAt(e.end)),
        e.newText
      );
    }
  }
  if (!(await vscode.workspace.applyEdit(we))) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the workspace edit was not applied."));
    return;
  }
  if (plan.cursorOffset !== undefined) {
    await openAtOffset(moduleUri, plan.cursorOffset);
  }
  for (const note of plan.notes) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: {0}", note));
  }
  void refreshForOffset(uri, tgt.nodeSpanStart);
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
    // First fill right away from the active editor's cursor - the panel must not wait
    // for the next selection event to show anything.
    refreshFromActiveEditor();
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
          if (target?.kind === "metadata") {
            void applyMetaProp(m.key, null);
          } else {
            void applyOperation("reset_property", m.key);
          }
        } else if (m.type === "createHandler" && typeof m.key === "string") {
          void createHandler(m.key);
        } else if (m.type === "gotoHandler" && typeof m.key === "string" && typeof m.method === "string") {
          void gotoHandler(m.key, m.method);
        } else if (m.type === "reveal") {
          void reveal(typeof m.offset === "number" ? m.offset : undefined);
        } else if (m.type === "sticky" && typeof m.key === "string" && target?.kind === "component") {
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
    // Expand the sidebar section without stealing focus from the caller (tree, preview).
    view.show(true);
    return;
  }
  // The view is not created yet - focusing the section makes VS Code call the provider;
  // the content arrives with the "ready" message from the webview.
  await vscode.commands.executeCommand(`${VIEW_TYPE}.focus`);
}

// A metadata tree node as the panel target: an object/field with a yaml offset or a
// standard attribute of a kind (the tree's XbslNode matches this shape structurally).
export interface PropsNode {
  yamlPath?: string;
  offset?: number;
  stdKind?: string;
  stdName?: string;
}

function metaSelectorFor(node: PropsNode): MetaSelector | undefined {
  if (!node.yamlPath) {
    return undefined;
  }
  if (node.stdKind && node.stdName) {
    return { std: { kind: node.stdKind, name: node.stdName } };
  }
  if (node.offset !== undefined) {
    return { offset: node.offset };
  }
  return undefined;
}

// Silent update on metadata tree selection change (mouse, arrows, programmatic reveal):
// the panel follows the selection only when already visible - selecting does not open
// files and does not disturb the sidebar. The tree signal wins over a pending cursor
// refresh (the selection often reveals the yaml, which fires cursor events of its own).
export function updatePropsFromSelection(node: PropsNode | undefined): void {
  if (!node || !view || !view.visible) {
    return;
  }
  const sel = metaSelectorFor(node);
  if (sel && node.yamlPath) {
    cancelScheduledRefresh();
    void refreshMetadata(vscode.Uri.file(node.yamlPath), sel);
  }
}

// typeCandidates (from the metadata tree provider) fills the Тип combobox of the metadata
// mode; without it the Тип field degrades to a plain text input.
export function registerFormProps(
  context: vscode.ExtensionContext,
  typeCandidates?: () => Promise<string[]>
): void {
  typeCandidatesFn = typeCandidates;
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW_TYPE, new FormPropsViewProvider(context)),
    // The cursor is the selection source: the node under it fills the panel (the structure
    // view and the preview go through the showForNode command below, the metadata tree
    // through xbsl.metadata.props). Deliberately NOT gated on activeTextEditor: the
    // selection also changes programmatically while focus sits in a tree or a webview,
    // and the panel must follow those too.
    vscode.window.onDidChangeTextEditorSelection((e) => {
      if (!view?.visible) {
        return;
      }
      const doc = e.textEditor.document;
      const mode = classifyDoc(doc);
      if (mode === "component" || mode === "metadata") {
        scheduleRefresh(doc.uri, doc.offsetAt(e.selections[0].active), mode);
      }
    }),
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!view?.visible || !editor) {
        return;
      }
      const mode = classifyDoc(editor.document);
      if (mode === "component" || mode === "metadata") {
        scheduleRefresh(editor.document.uri, editor.document.offsetAt(editor.selection.active), mode);
      } else if (mode === "module") {
        void refreshForModule(editor.document.uri);
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
    ),
    // Entry point for the metadata tree (a click or the "Properties" context item):
    // reveal the panel and fill it with the node. Without a node (the command palette)
    // the panel opens and follows the active editor.
    vscode.commands.registerCommand("xbsl.metadata.props", async (node?: PropsNode) => {
      await ensureView();
      cancelScheduledRefresh();
      const sel = node ? metaSelectorFor(node) : undefined;
      if (node?.yamlPath && sel) {
        await refreshMetadata(vscode.Uri.file(node.yamlPath), sel);
      } else {
        refreshFromActiveEditor();
      }
    })
  );
}
