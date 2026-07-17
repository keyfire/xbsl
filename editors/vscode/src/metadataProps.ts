// Панель свойств объекта/поля метаданных 1С:Элемент – webview-view в сайдбаре расширения,
// под деревом метаданных и документацией (как палитра свойств в конфигураторе/EDT): код не
// затеняется вкладками. Описание строк даёт describeMetaNode (metadataCore), правки
// применяются точечно через propertyEdit (formPreviewCore) – документ не переформатируется,
// undo работает. Ид и ВидЭлемента показаны только для чтения; коллекции правятся через дерево.

import * as vscode from "vscode";
import { propertyEdit } from "./formPreviewCore";
import { describeMetaNode, describeStandardAttr, findAttrOffset, insertItemEdit, MetaNodeDescription } from "./metadataCore";

const VIEW_TYPE = "xbslMetaProps";

let view: vscode.WebviewView | undefined;
// offset – смещение узла в yaml; std – стандартный реквизит (может быть синтетическим – тогда offset
// игнорируется, а правка материализует запись в Реквизиты).
let target: { uri: vscode.Uri; offset: number; std?: { kind: string; name: string } } | undefined;
let lastDesc: MetaNodeDescription | null = null;
// Поставщик кандидатов типа (из провайдера дерева) для комбобокса Тип; может отсутствовать.
let typeCandidatesFn: (() => Promise<string[]>) | undefined;

function nonce(): string {
  let s = "";
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 24; i++) {
    s += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }
  return s;
}

function shell(n: string): string {
  const labels = {
    hint: vscode.l10n.t("Select an object or a field in the tree to see and edit its properties."),
    auto: vscode.l10n.t("Auto"),
    autoOption: vscode.l10n.t("(auto)"),
    toYaml: vscode.l10n.t("Show in yaml"),
    note: vscode.l10n.t("An empty value or (auto) removes the property from the yaml."),
    readonly: vscode.l10n.t("read-only"),
  };
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<style>
  body { color: var(--vscode-foreground); font-family: var(--vscode-font-family, "Segoe UI", sans-serif);
    font-size: 13px; padding: 8px 12px; margin: 0; overflow-x: hidden; overflow-wrap: anywhere; }
  .ptitle { display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 6px 8px; margin-bottom: 10px; }
  .ptype { font-weight: 600; word-break: break-word; overflow-wrap: anywhere; min-width: 0; }
  .plink { background: transparent; border: 1px solid var(--vscode-panel-border); color: var(--vscode-foreground);
    border-radius: 3px; padding: 2px 8px; cursor: pointer; font-size: 11.5px; white-space: nowrap; }
  .prow { margin-bottom: 9px; }
  .pkey { font-size: .85em; opacity: .75; margin-bottom: 2px; word-break: break-word; overflow-wrap: anywhere; }
  .pkey .ro { opacity: .6; font-style: italic; }
  input[type=text], select { width: 100%; max-width: 100%; box-sizing: border-box; background: var(--vscode-input-background);
    color: var(--vscode-input-foreground, var(--vscode-foreground)); border: 1px solid var(--vscode-input-border, rgba(128,128,128,.5));
    border-radius: 3px; padding: 3px 7px; font-size: 12.5px; }
  input[readonly] { opacity: .7; }
  .tri { display: flex; border: 1px solid var(--vscode-input-border, rgba(128,128,128,.5)); border-radius: 3px; overflow: hidden; }
  .tri button { flex: 1; background: transparent; border: none; color: var(--vscode-foreground); padding: 3px 0; cursor: pointer; font-size: 12px; opacity: .75; }
  .tri button.on { background: var(--vscode-button-background); color: var(--vscode-button-foreground); opacity: 1; }
  .pnote { opacity: .55; font-size: .85em; margin-top: 12px; }
  .phint { opacity: .65; font-style: italic; }
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
<div id="pane"></div>
<script nonce="${n}">
  const vsapi = acquireVsCodeApi();
  const L = ${JSON.stringify(labels)};
  const pane = document.getElementById("pane");

  function field(row) {
    const send = (value) => vsapi.postMessage({ type: "setProp", key: row.key, value });
    if (row.readonly) {
      const input = document.createElement("input");
      input.type = "text"; input.value = row.value; input.readOnly = true;
      return input;
    }
    if (row.control === "tristate") {
      const box = document.createElement("div");
      box.className = "tri";
      for (const v of [null, "Истина", "Ложь"]) {
        const b = document.createElement("button");
        b.textContent = v === null ? L.auto : v;
        if ((v === null && !row.value) || v === row.value) { b.classList.add("on"); }
        b.addEventListener("click", () => send(v));
        box.appendChild(b);
      }
      return box;
    }
    if (row.control === "select") {
      const sel = document.createElement("select");
      const auto = document.createElement("option");
      auto.value = ""; auto.textContent = L.autoOption;
      sel.appendChild(auto);
      for (const o of row.options || []) {
        const opt = document.createElement("option");
        opt.value = o; opt.textContent = o;
        sel.appendChild(opt);
      }
      sel.value = row.value || "";
      sel.addEventListener("change", () => send(sel.value === "" ? null : sel.value));
      return sel;
    }
    if (row.control === "combo") {
      // Свой комбобокс: по фокусу показываем ВСЕ кандидаты (нативный datalist фильтрует по текущему
      // значению и показал бы только его), при наборе фильтруем; значение можно и ввести вручную.
      const wrap = document.createElement("div");
      wrap.className = "combo";
      const input = document.createElement("input");
      input.type = "text"; input.value = row.value;
      const list = document.createElement("div");
      list.className = "combo-list"; list.style.display = "none";
      const opts = row.options || [];
      let last = row.value; // защита от повторной отправки того же значения
      const commit = (v) => { if (v !== last) { last = v; send(v === "" ? null : v); } };
      const build = (showAll) => {
        const q = showAll ? "" : input.value.trim().toLowerCase();
        list.textContent = "";
        const matches = opts.filter((o) => !q || o.toLowerCase().includes(q));
        if (!matches.length) { list.style.display = "none"; return; }
        for (const o of matches) {
          const it = document.createElement("div");
          it.className = "combo-opt" + (o === input.value ? " cur" : "");
          it.textContent = o;
          // mousedown (до blur), чтобы клик успел выбрать пункт.
          it.addEventListener("mousedown", (e) => { e.preventDefault(); input.value = o; list.style.display = "none"; commit(o); });
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
        if (e.key === "Enter") { list.style.display = "none"; commit(input.value); }
        else if (e.key === "Escape") { list.style.display = "none"; }
      });
      input.addEventListener("blur", () => { setTimeout(() => { list.style.display = "none"; commit(input.value); }, 150); });
      wrap.appendChild(input); wrap.appendChild(list);
      return wrap;
    }
    const input = document.createElement("input");
    input.type = "text"; input.value = row.value;
    const commit = () => { if (input.value !== row.value) { send(input.value === "" ? null : input.value); } };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { commit(); } });
    input.addEventListener("blur", commit);
    return input;
  }

  function render(desc) {
    pane.textContent = "";
    if (!desc) {
      const hint = document.createElement("div");
      hint.className = "phint"; hint.textContent = L.hint;
      pane.appendChild(hint);
      return;
    }
    const title = document.createElement("div");
    title.className = "ptitle";
    const type = document.createElement("span");
    type.className = "ptype"; type.textContent = desc.title || "?";
    const toYaml = document.createElement("button");
    toYaml.className = "plink"; toYaml.textContent = L.toYaml;
    toYaml.addEventListener("click", () => vsapi.postMessage({ type: "reveal" }));
    title.appendChild(type); title.appendChild(toYaml);
    pane.appendChild(title);
    for (const row of desc.rows) {
      const div = document.createElement("div");
      div.className = "prow";
      const cap = document.createElement("div");
      cap.className = "pkey"; cap.textContent = row.key;
      if (row.readonly) { const ro = document.createElement("span"); ro.className = "ro"; ro.textContent = " · " + L.readonly; cap.appendChild(ro); }
      div.appendChild(cap);
      div.appendChild(field(row));
      pane.appendChild(div);
    }
    const note = document.createElement("div");
    note.className = "pnote"; note.textContent = L.note;
    pane.appendChild(note);
  }

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (m && m.type === "props") { render(m.desc); }
  });
  render(null);
  vsapi.postMessage({ type: "ready" });
</script></body></html>`;
}

async function targetText(): Promise<string | undefined> {
  if (!target) {
    return undefined;
  }
  const doc = await vscode.workspace.openTextDocument(target.uri);
  return doc.getText();
}

async function render(): Promise<void> {
  if (!view) {
    return;
  }
  const text = await targetText();
  lastDesc = !text || !target
    ? null
    : (target.std ? describeStandardAttr(text, target.std.kind, target.std.name) : describeMetaNode(text, target.offset)) ?? null;
  // Строки-типы (комбобокс) наполняем кандидатами из провайдера дерева – ядро состав проекта не знает.
  if (lastDesc && typeCandidatesFn && lastDesc.rows.some((r) => r.control === "combo")) {
    const candidates = await typeCandidatesFn();
    for (const row of lastDesc.rows) {
      if (row.control === "combo") {
        row.options = candidates;
      }
    }
  }
  // У view заголовок секции задан манифестом; выбранный узел показываем описанием.
  view.description = lastDesc ? lastDesc.title : undefined;
  void view.webview.postMessage({ type: "props", desc: lastDesc });
}

async function applyProp(key: string, value: string | null): Promise<void> {
  if (!target) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target.uri);
  const text = doc.getText();
  const we = new vscode.WorkspaceEdit();

  // Стандартный реквизит: материализован (есть в Реквизиты) – правим его запись; синтетический –
  // при правке дописываем запись { Имя: <имя>, <ключ>: <значение> } в Реквизиты (материализация).
  if (target.std) {
    const off = findAttrOffset(text, target.std.name);
    if (off === undefined) {
      if (value === null) {
        return; // снимать у несуществующей записи нечего
      }
      const ins = insertItemEdit(text, "Реквизиты", [`Имя: ${target.std.name}`, `${key}: ${value}`]);
      we.insert(target.uri, doc.positionAt(ins.start), ins.newText);
    } else {
      const edit = propertyEdit(text, off, key, value);
      if (!edit) {
        return;
      }
      we.replace(target.uri, new vscode.Range(doc.positionAt(edit.start), doc.positionAt(edit.end)), edit.newText);
    }
    await vscode.workspace.applyEdit(we);
    await render();
    return;
  }

  const edit = propertyEdit(text, target.offset, key, value);
  if (!edit) {
    return;
  }
  we.replace(target.uri, new vscode.Range(doc.positionAt(edit.start), doc.positionAt(edit.end)), edit.newText);
  // Сменили Тип на не-строковый – убрать строкоспецифичное свойство Многострочная (правка по тому же
  // исходному тексту, на другой строке – с правкой типа не пересекается).
  const newIsString = value === "Строка" || value === "Строка?";
  if (key === "Тип" && value !== null && !newIsString) {
    const strip = propertyEdit(text, target.offset, "Многострочная", null);
    if (strip) {
      we.replace(target.uri, new vscode.Range(doc.positionAt(strip.start), doc.positionAt(strip.end)), strip.newText);
    }
  }
  await vscode.workspace.applyEdit(we);
  await render();
}

async function revealTarget(): Promise<void> {
  if (!target) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(target.uri);
  // Синтетический стандартный реквизит (нет узла) – показываем начало объекта; иначе строку узла.
  const offset = target.std ? findAttrOffset(doc.getText(), target.std.name) ?? 0 : Math.max(target.offset, 0);
  const pos = doc.positionAt(offset);
  const editor = await vscode.window.showTextDocument(doc, { preview: false });
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

class MetaPropsViewProvider implements vscode.WebviewViewProvider {
  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(v: vscode.WebviewView): void {
    view = v;
    v.webview.options = { enableScripts: true };
    v.webview.html = shell(nonce());
    v.onDidDispose(
      () => {
        view = undefined;
      },
      undefined,
      this.context.subscriptions
    );
    v.webview.onDidReceiveMessage(
      (m) => {
        if (!m) {
          return;
        }
        if (m.type === "setProp" && typeof m.key === "string") {
          void applyProp(m.key, typeof m.value === "string" ? m.value : null);
        } else if (m.type === "reveal") {
          void revealTarget();
        } else if (m.type === "ready") {
          void view?.webview.postMessage({ type: "props", desc: lastDesc });
        }
      },
      undefined,
      this.context.subscriptions
    );
  }
}

async function ensureView(): Promise<void> {
  if (view) {
    // Разворачиваем секцию в сайдбаре, не забирая фокус у дерева.
    view.show(true);
    return;
  }
  // View ещё не создан – фокусировка секции заставит VS Code вызвать провайдера;
  // содержимое приедет по сообщению "ready" из webview.
  await vscode.commands.executeCommand(`${VIEW_TYPE}.focus`);
}

// Открыть панель свойств для узла дерева (yamlPath + offset). typeCandidates (из провайдера
// дерева) наполняет комбобокс Тип; без него поле Тип остаётся вводом текста.
export function registerMetadataProps(
  context: vscode.ExtensionContext,
  typeCandidates?: () => Promise<string[]>
): void {
  typeCandidatesFn = typeCandidates;
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW_TYPE, new MetaPropsViewProvider(context), {
      webviewOptions: { retainContextWhenHidden: true },
    }),
    vscode.commands.registerCommand(
      "xbsl.metadata.props",
      async (node?: { yamlPath?: string; offset?: number; stdKind?: string; stdName?: string }) => {
        if (!node?.yamlPath) {
          return;
        }
        if (node.stdKind && node.stdName) {
          target = { uri: vscode.Uri.file(node.yamlPath), offset: node.offset ?? -1, std: { kind: node.stdKind, name: node.stdName } };
        } else if (node.offset !== undefined) {
          target = { uri: vscode.Uri.file(node.yamlPath), offset: node.offset };
        } else {
          return;
        }
        await ensureView();
        await render();
      }
    )
  );
}
