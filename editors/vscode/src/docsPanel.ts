// Панель документации 1С:Элемент – webview со страницей справки (как синтакс-помощник в EDT).
// Содержимое (очищенный HTML) приходит от LSP-сервера линтера; картинки подставляются data-URI,
// внутренние ссылки ведут к другим страницам в этой же панели, кнопка ведёт к первоисточнику на
// сайте документации. Панель одна: открытие новой страницы заменяет содержимое.

import * as vscode from "vscode";
import { docsAsset, docsForSymbol, docsPage, DocPage } from "./docsClient";

const VIEW_TYPE = "xbslDocs";
let panel: vscode.WebviewPanel | undefined;

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

// Картинки страницы (`<img src="assets/...">`) заменяем на data-URI, вытянув байты у сервера.
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

function shell(bodyHtml: string, sourceUrl: string | undefined, n: string): string {
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
    padding: 10px 12px; overflow-x: auto; }
  .doc pre code { background: none; padding: 0; }
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
      e.preventDefault();
      vsapi.postMessage({ type: "open", id: href.slice(1).split("#")[0] });
    } else if (href.startsWith("ext:")) {
      e.preventDefault();
      vsapi.postMessage({ type: "external", url: href.slice(4) });
    }
  });
</script></body></html>`;
}

function ensurePanel(context: vscode.ExtensionContext): vscode.WebviewPanel {
  if (panel) {
    panel.reveal(panel.viewColumn ?? vscode.ViewColumn.Beside, true);
    return panel;
  }
  panel = vscode.window.createWebviewPanel(
    VIEW_TYPE,
    vscode.l10n.t("Documentation"),
    { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
    { enableScripts: true, retainContextWhenHidden: true }
  );
  panel.onDidDispose(() => (panel = undefined), undefined, context.subscriptions);
  panel.webview.onDidReceiveMessage((m) => {
    if (!m) {
      return;
    }
    if (m.type === "open" && typeof m.id === "string") {
      void openPage(context, m.id);
    } else if (m.type === "external" && typeof m.url === "string") {
      void vscode.env.openExternal(vscode.Uri.parse(m.url));
    }
  }, undefined, context.subscriptions);
  return panel;
}

async function render(context: vscode.ExtensionContext, page: DocPage): Promise<void> {
  const p = ensurePanel(context);
  p.title = page.title || vscode.l10n.t("Documentation");
  p.webview.html = shell(await inlineImages(page.html), page.url || undefined, nonce());
}

export async function openPage(context: vscode.ExtensionContext, id: string): Promise<void> {
  const page = await docsPage(id);
  if (!page) {
    const p = ensurePanel(context);
    p.webview.html = shell(`<p class="empty">${esc(vscode.l10n.t("Page not found."))}</p>`, undefined, nonce());
    return;
  }
  await render(context, page);
}

// Правый клик на переменной/типе в редакторе: спросить сервер, к какой странице ведёт символ.
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
  // Уверенной страницы нет (метод-секция, неизвестный тип) – предлагаем кандидатов на выбор.
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
