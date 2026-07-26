// 1C:Element documentation panel - a webview with a help page (like the syntax assistant in
// EDT). The content (sanitized HTML) comes from the linter's LSP server; images are inlined
// as data URIs, internal links lead to other pages within the same panel, a button leads to
// the primary source on the documentation site. There is one panel: opening a new page
// replaces the content.

import * as vscode from "vscode";
import { docsAsset, docsForSymbol, docsPage, DocPage } from "./docsClient";

const VIEW_TYPE = "xbslDocs";
//: The article shown last, remembered per workspace so a restart brings it back.
const PAGE_KEY = "xbsl.docsPanel.page";
let panel: vscode.WebviewPanel | undefined;

// Page open listener (the "Contents" tree uses it to position itself on the document).
let openListener: ((id: string) => void) | undefined;
export function setDocsOpenListener(fn: (id: string) => void): void {
  openListener = fn;
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] as string));
}

function nonce(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 24; i++) {
    s += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }
  return s;
}

// Page images (`<img src="assets/...">`) are replaced with data URIs, pulling bytes from the server.
async function inlineImages(html: string): Promise<string> {
  const ids = new Set<string>();
  for (const m of html.matchAll(/<img src="(assets\/[^"]+)"/g)) {
    ids.add(m[1]);
  }
  for (const id of ids) {
    const a = await docsAsset(id);
    if (a) {
      html = html.split(`"${id}"`).join(`"data:${a.mime};base64,${a.base64}"`);
    }
  }
  return html;
}

function shell(bodyHtml: string, sourceUrl: string | undefined, anchor: string | undefined, n: string): string {
  const source = sourceUrl
    ? `<a class="src" href="ext:${esc(sourceUrl)}">${esc(vscode.l10n.t("Primary source"))}</a>`
    : "";
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'nonce-${n}';">
<style>
  body { color: var(--vscode-foreground); background: var(--vscode-editor-background);
    font-family: var(--vscode-font-family, "Segoe UI", sans-serif); font-size: 14px; line-height: 1.5;
    padding: 0 18px 24px; margin: 0; }
  .bar { position: sticky; top: 0; z-index: 5; display: flex; justify-content: flex-end; gap: 8px;
    padding: 8px 0; background: var(--vscode-editor-background); border-bottom: 1px solid var(--vscode-panel-border); }
  .src { color: var(--vscode-textLink-foreground); text-decoration: none; font-size: 12.5px;
    border: 1px solid var(--vscode-panel-border); border-radius: 3px; padding: 2px 10px; cursor: pointer; }
  .src:hover { background: rgba(128,128,128,.12); }
  .doc { max-width: 860px; }
  .doc h1 { font-size: 1.55em; margin: 14px 0 8px; }
  .doc h2 { font-size: 1.2em; margin: 22px 0 6px; padding-bottom: 3px; border-bottom: 1px solid var(--vscode-panel-border); }
  .doc h3 { font-size: 1.05em; margin: 16px 0 4px; }
  .doc h4 { font-size: .98em; margin: 12px 0 4px; opacity: .9; }
  .doc code { font-family: var(--vscode-editor-font-family, monospace); font-size: .9em;
    background: rgba(128,128,128,.16); padding: .1em .35em; border-radius: 3px; }
  .doc pre { background: var(--vscode-textCodeBlock-background, rgba(128,128,128,.12)); border-radius: 6px;
    padding: 10px 12px; overflow-x: auto; margin: 0; }
  .doc pre code { background: none; padding: 0; }
  .code-wrap { position: relative; margin: 8px 0; }
  .copy-btn { position: absolute; top: 6px; right: 6px; z-index: 1; cursor: pointer;
    font-family: var(--vscode-font-family, "Segoe UI", sans-serif); font-size: 11.5px;
    color: var(--vscode-foreground); background: var(--vscode-editor-background);
    border: 1px solid var(--vscode-panel-border); border-radius: 4px; padding: 2px 8px; opacity: .55; }
  .code-wrap:hover .copy-btn { opacity: 1; }
  .copy-btn:hover { background: rgba(128,128,128,.18); }
  .doc a { color: var(--vscode-textLink-foreground); text-decoration: none; }
  .doc a:hover { text-decoration: underline; }
  .doc img { max-width: 100%; height: auto; border-radius: 4px; }
  .doc table { border-collapse: collapse; margin: 8px 0; }
  .doc th, .doc td { border: 1px solid var(--vscode-panel-border); padding: 4px 10px; text-align: left; }
  .doc hr { border: none; border-top: 1px solid var(--vscode-panel-border); margin: 16px 0; }
  .empty { opacity: .7; font-style: italic; padding: 24px 0; }
</style></head>
<body>
<div class="bar">${source}</div>
<div class="doc">${bodyHtml}</div>
<script nonce="${n}">
  const vsapi = acquireVsCodeApi();
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a) { return; }
    const href = a.getAttribute("href") || "";
    if (href.startsWith("#")) {
      const rest = href.slice(1);
      if (rest.includes("/")) {           // a link to another page (possibly with an anchor)
        e.preventDefault();
        const h = rest.indexOf("#");
        vsapi.postMessage({ type: "open", id: h < 0 ? rest : rest.slice(0, h), anchor: h < 0 ? undefined : rest.slice(h + 1) });
      }                                   // otherwise - an anchor of this very page: native scrolling
    } else if (href.startsWith("ext:")) {
      e.preventDefault();
      vsapi.postMessage({ type: "external", url: href.slice(4) });
    }
  });
  const anchor = ${JSON.stringify(anchor || "")};
  if (anchor) {
    const el = document.getElementById(anchor);
    if (el) { el.scrollIntoView({ block: "start" }); }
  }
  // A copy-to-clipboard button in the top right corner of every code block.
  const L = { copy: ${JSON.stringify(vscode.l10n.t("Copy"))}, copied: ${JSON.stringify(vscode.l10n.t("Copied"))} };
  for (const pre of document.querySelectorAll(".doc pre")) {
    const wrap = document.createElement("div");
    wrap.className = "code-wrap";
    pre.parentNode.insertBefore(wrap, pre);
    wrap.appendChild(pre);
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.textContent = L.copy;
    btn.addEventListener("click", () => {
      const code = pre.querySelector("code");
      vsapi.postMessage({ type: "copy", text: code ? code.textContent : pre.textContent });
      btn.textContent = L.copied;
      setTimeout(() => { btn.textContent = L.copy; }, 1200);
    });
    wrap.appendChild(btn);
  }
</script></body></html>`;
}

// Wiring of the documentation panel - shared by a freshly created panel and by one VS Code
// restored after a restart (see registerDocsPanel).
function adoptPanel(context: vscode.ExtensionContext, created: vscode.WebviewPanel): vscode.WebviewPanel {
  panel = created;
  panel.onDidDispose(() => (panel = undefined), undefined, context.subscriptions);
  panel.webview.onDidReceiveMessage((m) => {
    if (!m) {
      return;
    }
    if (m.type === "open" && typeof m.id === "string") {
      void openPage(context, m.id, typeof m.anchor === "string" ? m.anchor : undefined);
    } else if (m.type === "external" && typeof m.url === "string") {
      void vscode.env.openExternal(vscode.Uri.parse(m.url));
    } else if (m.type === "copy" && typeof m.text === "string") {
      void vscode.env.clipboard.writeText(m.text);
    }
  }, undefined, context.subscriptions);
  return panel;
}

function ensurePanel(context: vscode.ExtensionContext): vscode.WebviewPanel {
  if (panel) {
    panel.reveal(panel.viewColumn ?? vscode.ViewColumn.Beside, true);
    return panel;
  }
  return adoptPanel(
    context,
    vscode.window.createWebviewPanel(
      VIEW_TYPE,
      vscode.l10n.t("Documentation"),
      { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { enableScripts: true, retainContextWhenHidden: true }
    )
  );
}

// Session restore: VS Code drops a webview tab on restart unless a serializer claims it. The
// page shown last is remembered per workspace (openPage below), so the restored tab comes back
// with the same article instead of an empty shell.
export function registerDocsPanel(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.window.registerWebviewPanelSerializer(VIEW_TYPE, {
      async deserializeWebviewPanel(restored: vscode.WebviewPanel, state: unknown): Promise<void> {
        adoptPanel(context, restored);
        const saved = (state as { id?: unknown })?.id ?? context.workspaceState.get(PAGE_KEY);
        const id = typeof saved === "string" && saved.trim() ? saved.trim() : undefined;
        if (!id) {
          restored.dispose(); // nothing to show - do not leave an empty tab behind
          return;
        }
        await openPage(context, id);
      },
    })
  );
}

async function render(context: vscode.ExtensionContext, page: DocPage, anchor?: string): Promise<void> {
  const p = ensurePanel(context);
  p.title = page.title || vscode.l10n.t("Documentation");
  p.webview.html = shell(await inlineImages(page.html), page.url || undefined, anchor, nonce());
  void context.workspaceState.update(PAGE_KEY, page.id); // what the serializer reopens after a restart
  openListener?.(page.id); // position the "Contents" tree on this document
}

export async function openPage(context: vscode.ExtensionContext, id: string, anchor?: string): Promise<void> {
  const page = await docsPage(id);
  if (!page) {
    const p = ensurePanel(context);
    p.webview.html = shell(`<p class="empty">${esc(vscode.l10n.t("Page not found."))}</p>`, undefined, undefined, nonce());
    return;
  }
  await render(context, page, anchor);
}

// Right click on a variable/type in the editor: ask the server which page the symbol leads to.
export async function openForSymbol(context: vscode.ExtensionContext): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor || editor.document.languageId !== "xbsl") {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: open an .xbsl file and place the cursor on a type or variable."));
    return;
  }
  const pos = editor.selection.active;
  const res = await docsForSymbol(editor.document.uri.toString(), { line: pos.line, character: pos.character });
  if (!res || !res.name) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: no symbol under the cursor."));
    return;
  }
  if (res.page) {
    await render(context, res.page);
    return;
  }
  // No confident page (a section method, an unknown type) - offer candidates to choose from.
  const candidates = res.candidates ?? [];
  if (candidates.length === 0) {
    void vscode.window.showInformationMessage(vscode.l10n.t('XBSL: no documentation for "{0}".', res.name));
    return;
  }
  const pick = await vscode.window.showQuickPick(
    candidates.map((h) => ({ label: h.title, description: h.qualified, detail: h.snippet || undefined, id: h.id })),
    {
      placeHolder: vscode.l10n.t('Documentation for "{0}"', res.name),
      matchOnDescription: true,
      matchOnDetail: true,
    }
  );
  if (pick) {
    await openPage(context, pick.id);
  }
}
