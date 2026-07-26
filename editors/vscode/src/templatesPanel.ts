import * as vscode from "vscode";
import { spawn } from "child_process";
import {
  CONTEXTS,
  ENVIRONMENTS,
  EngineConfig,
  TemplateDraft,
  TemplateRow,
  groupByCategory,
  parseTemplatesList,
  parseTemplatesResult,
  templatesArgs,
  toEnvelope,
  upsert,
  validateDraft,
} from "./templatesCore";

// Code templates management panel - an analog of the "Параметры - Шаблоны" dialog in 1C:EDT:
// the list on the left, the editor on the right, add/edit/delete and import/export buttons.
//
// Data and writing go through the engine (`xbsl templates ...`) so the panel works the same
// in both extension modes (LSP and CLI) and keeps no writing logic of its own.

const TEMPLATES_VIEW_TYPE = "xbsl.templates";
const DEFAULT_TEMPLATES_FILE = ".xbsl-templates.json";

// Re-reading of the set by the running LSP server. The panel is registered before the mode
// is chosen, and the client appears later - hence a hook, not a direct call. In CLI mode
// there is nothing to re-read: template completion does not work there (see README).
let reloadEngine: () => Promise<void> = async () => undefined;

export function setTemplatesReload(fn: () => Promise<void>): void {
  reloadEngine = fn;
}

function engineConfig(): EngineConfig {
  const c = vscode.workspace.getConfiguration("xbsl");
  const python = (c.get<string>("linter.pythonPath") || "").trim();
  const command = (c.get<string>("linter.command") || "xbsl").trim();
  return {
    command: python || command,
    usePython: python.length > 0,
    templatesFile: (c.get<string>("templates.file") || "").trim() || undefined,
  };
}

function workspaceFolder(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

interface RunResult {
  stdout: string;
  error?: string;
  notFound?: boolean;
}

function run(args: string[], stdin?: string): Promise<RunResult> {
  const cfg = engineConfig();
  return new Promise((resolve) => {
    let child;
    try {
      // PYTHONUTF8: without it Python's stdio pipes on Windows use the ANSI codepage,
      // and the Cyrillic of template names breaks both ways (list - mojibake in the
      // panel, save - a UnicodeError instead of writing the file).
      child = spawn(cfg.command, args, {
        cwd: workspaceFolder(),
        env: { ...process.env, PYTHONUTF8: "1" },
      });
    } catch (e) {
      resolve({ stdout: "", error: String(e), notFound: (e as NodeJS.ErrnoException)?.code === "ENOENT" });
      return;
    }
    let out = "";
    let err = "";
    child.on("error", (e) =>
      resolve({ stdout: "", error: String(e), notFound: (e as NodeJS.ErrnoException)?.code === "ENOENT" }),
    );
    child.stdout.on("data", (d: Buffer) => (out += d.toString("utf8")));
    child.stderr.on("data", (d: Buffer) => (err += d.toString("utf8")));
    child.on("close", () => resolve({ stdout: out, error: out.trim() ? undefined : err.trim() || undefined }));
    if (stdin !== undefined) {
      child.stdin.end(stdin, "utf8");
    } else {
      child.stdin.end();
    }
  });
}

async function loadTemplates(): Promise<{ rows: TemplateRow[]; file: string } | undefined> {
  const res = await run(templatesArgs("list", engineConfig(), ["--format", "json"]));
  if (res.error) {
    void vscode.window.showErrorMessage(
      res.notFound
        ? vscode.l10n.t("xbsl was not found. Install it to manage code templates.")
        : vscode.l10n.t("Failed to read the templates: {0}", res.error),
    );
    return undefined;
  }
  try {
    const list = parseTemplatesList(res.stdout);
    return { rows: list.templates, file: list.file };
  } catch (e) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to read the templates: {0}", String(e)));
    return undefined;
  }
}

// Edits are written by the engine; after the write the LSP server re-reads the file,
// otherwise Ctrl+Space would offer the previous set until a restart.
async function saveTemplates(rows: Array<TemplateRow | TemplateDraft>): Promise<boolean> {
  const res = await run(templatesArgs("save", engineConfig()), toEnvelope(rows));
  if (res.error) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to save the templates: {0}", res.error));
    return false;
  }
  try {
    parseTemplatesResult(res.stdout);
  } catch (e) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to save the templates: {0}", String(e)));
    return false;
  }
  await reloadEngine();
  return true;
}

const VALIDATION_TEXT: Record<string, string> = {
  "empty-name": "The name is required: <abbreviation> - <title>",
  "empty-pattern": "The template text is required",
  "duplicate-name": "A template with this name already exists",
  "no-context": "Choose at least one call context",
  "no-environment": "Choose at least one environment",
};

class TemplatesPanel {
  public static current: TemplatesPanel | undefined;
  private rows: TemplateRow[] = [];
  private file = DEFAULT_TEMPLATES_FILE;
  private readonly disposables: vscode.Disposable[] = [];

  private constructor(private readonly panel: vscode.WebviewPanel) {
    this.panel.onDidDispose(() => this.dispose(), null, this.disposables);
    this.panel.webview.onDidReceiveMessage((m) => void this.onMessage(m), null, this.disposables);
  }

  public static async show(): Promise<void> {
    if (TemplatesPanel.current) {
      TemplatesPanel.current.panel.reveal(vscode.ViewColumn.Active);
      await TemplatesPanel.current.refresh();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      TEMPLATES_VIEW_TYPE,
      vscode.l10n.t("XBSL: code templates"),
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    await TemplatesPanel.adopt(panel);
  }

  // Take over a panel - a freshly created one, or one VS Code restored after a restart.
  public static async adopt(panel: vscode.WebviewPanel): Promise<void> {
    TemplatesPanel.current?.dispose();
    TemplatesPanel.current = new TemplatesPanel(panel);
    await TemplatesPanel.current.refresh();
  }

  public async refresh(): Promise<void> {
    const loaded = await loadTemplates();
    if (!loaded) {
      return;
    }
    this.rows = loaded.rows;
    this.file = loaded.file || DEFAULT_TEMPLATES_FILE;
    this.panel.webview.html = this.html();
  }

  private async onMessage(msg: { type: string; draft?: TemplateDraft; name?: string; original?: string }): Promise<void> {
    if (msg.type === "save" && msg.draft) {
      const problem = validateDraft(msg.draft, this.rows, msg.original);
      if (problem) {
        this.panel.webview.postMessage({ type: "invalid", text: vscode.l10n.t(VALIDATION_TEXT[problem]) });
        return;
      }
      if (await saveTemplates(upsert(this.rows, msg.draft, msg.original))) {
        await this.refresh();
      }
      return;
    }
    if (msg.type === "delete" && msg.name) {
      await this.deleteTemplate(msg.name);
      return;
    }
    if (msg.type === "import") {
      await importTemplates();
      await this.refresh();
      return;
    }
    if (msg.type === "export") {
      await exportTemplates();
      return;
    }
    if (msg.type === "reset") {
      await this.resetToBuiltin();
    }
  }

  private async deleteTemplate(name: string): Promise<void> {
    const row = this.rows.find((r) => r.name === name);
    if (!row) {
      return;
    }
    // A builtin template cannot be deleted - it ships with the engine. One overridden by an
    // edit can be restored to its original form by removing the record from the user's file.
    const question = row.builtin
      ? vscode.l10n.t("'{0}' is a builtin template and cannot be deleted.", row.title)
      : vscode.l10n.t("Delete the template '{0}'?", row.title);
    if (row.builtin) {
      void vscode.window.showInformationMessage(question);
      return;
    }
    const yes = vscode.l10n.t("Delete");
    if ((await vscode.window.showWarningMessage(question, { modal: true }, yes)) !== yes) {
      return;
    }
    if (await saveTemplates(this.rows.filter((r) => r.name !== name))) {
      await this.refresh();
    }
  }

  private async resetToBuiltin(): Promise<void> {
    const custom = this.rows.filter((r) => !r.builtin).length;
    if (!custom) {
      void vscode.window.showInformationMessage(vscode.l10n.t("The set is already the builtin one."));
      return;
    }
    const yes = vscode.l10n.t("Restore");
    const answer = await vscode.window.showWarningMessage(
      vscode.l10n.t("Restore the builtin set? {0} of your own template(s) will be lost.", custom),
      { modal: true },
      yes,
    );
    if (answer !== yes) {
      return;
    }
    if (await saveTemplates([])) {
      await this.refresh();
    }
  }

  private html(): string {
    const w = this.panel.webview;
    const nonce = String(Math.random()).slice(2);
    const groups = groupByCategory(this.rows);
    const data = JSON.stringify({
      groups,
      rows: this.rows,
      contexts: CONTEXTS,
      environments: ENVIRONMENTS,
      file: this.file,
      text: {
        contexts: {
          STATEMENT_CONTEXT: vscode.l10n.t("Statement"),
          DECLARATION_CONTEXT: vscode.l10n.t("Declaration"),
          QUERY_CONTEXT: vscode.l10n.t("Query"),
        },
        environments: {
          SERVER_ENVIRONMENT: vscode.l10n.t("Server"),
          CLIENT_ENVIRONMENT: vscode.l10n.t("Client"),
        },
        everywhere: vscode.l10n.t("Everywhere"),
        builtin: vscode.l10n.t("builtin"),
      },
    });
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; style-src ${w.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
<style>
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground);
         padding: 10px; font-size: var(--vscode-font-size); }
  .toolbar { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; align-items: center; }
  .grow { flex: 1; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground);
           border: none; padding: 4px 12px; cursor: pointer; border-radius: 2px; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { background: var(--vscode-button-secondaryBackground);
                     color: var(--vscode-button-secondaryForeground); }
  button:disabled { opacity: .5; cursor: default; }
  .layout { display: flex; gap: 12px; align-items: flex-start; }
  .list { flex: 1; min-width: 0; max-height: 70vh; overflow: auto;
          border: 1px solid var(--vscode-panel-border); }
  table { border-collapse: collapse; width: 100%; }
  th { text-align: left; font-weight: 600; padding: 4px 8px; position: sticky; top: 0;
       background: var(--vscode-editor-background); border-bottom: 1px solid var(--vscode-panel-border); }
  td { padding: 3px 8px; cursor: pointer; }
  tr.sel td { background: var(--vscode-list-activeSelectionBackground);
              color: var(--vscode-list-activeSelectionForeground); }
  tr.cat td { font-weight: 600; opacity: .75; cursor: default; padding-top: 8px; }
  .mark { opacity: .6; font-size: 90%; }
  .form { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
  label { font-size: 90%; opacity: .85; }
  input[type=text], textarea { width: 100%; box-sizing: border-box; font-family: inherit;
      background: var(--vscode-input-background); color: var(--vscode-input-foreground);
      border: 1px solid var(--vscode-input-border, transparent); padding: 4px; }
  textarea { font-family: var(--vscode-editor-font-family); min-height: 220px; white-space: pre; }
  .row { display: flex; gap: 12px; flex-wrap: wrap; }
  .err { color: var(--vscode-errorForeground); min-height: 1.2em; }
  .hint { opacity: .7; font-size: 90%; }
</style>
</head>
<body>
<div class="toolbar">
  <button id="add">${vscode.l10n.t("Add")}</button>
  <button id="del" class="secondary">${vscode.l10n.t("Delete")}</button>
  <span class="grow"></span>
  <button id="imp" class="secondary">${vscode.l10n.t("Import...")}</button>
  <button id="exp" class="secondary">${vscode.l10n.t("Export...")}</button>
  <button id="reset" class="secondary">${vscode.l10n.t("Restore defaults")}</button>
</div>
<div class="layout">
  <div class="list">
    <table>
      <thead><tr><th>${vscode.l10n.t("Name")}</th><th>${vscode.l10n.t("Call context")}</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </div>
  <div class="form">
    <label>${vscode.l10n.t("Name")} <span class="hint">${vscode.l10n.t("abbreviation[optional tail] - title")}</span></label>
    <input type="text" id="name" spellcheck="false">
    <label>${vscode.l10n.t("Description")} <span class="hint">${vscode.l10n.t("/Category/Subcategory/Title")}</span></label>
    <input type="text" id="desc" spellcheck="false">
    <div class="row">
      <div><label>${vscode.l10n.t("Call context")}</label><div id="ctxs"></div></div>
      <div><label>${vscode.l10n.t("Environment")}</label><div id="envs"></div></div>
    </div>
    <label>${vscode.l10n.t("Template")} <span class="hint">\${${vscode.l10n.t("Edit")}("...")}, \${${vscode.l10n.t("Choose")}("a", "b")}</span></label>
    <textarea id="pattern" spellcheck="false"></textarea>
    <div class="err" id="err"></div>
    <div class="toolbar">
      <button id="save">${vscode.l10n.t("Apply")}</button>
      <span class="hint" id="file"></span>
    </div>
  </div>
</div>
<script nonce="${nonce}">
const vsapi = acquireVsCodeApi();
const DATA = ${data};
let selected = null;      // name of the selected template
let original = null;      // name before the edit: the engine replaces the record by it

const $ = (id) => document.getElementById(id);

function contextText(row) {
  if (row.contexts.length === DATA.contexts.length) return DATA.text.everywhere;
  return row.contexts.map((c) => DATA.text.contexts[c] || c).join(", ");
}

function renderList() {
  const body = $("rows");
  body.textContent = "";
  for (const group of DATA.groups) {
    const head = body.insertRow();
    head.className = "cat";
    const cell = head.insertCell();
    cell.colSpan = 2;
    cell.textContent = group.category;
    for (const row of group.templates) {
      const tr = body.insertRow();
      tr.className = row.name === selected ? "sel" : "";
      const c1 = tr.insertCell();
      c1.textContent = row.trigger + " - " + row.title;
      if (row.builtin) {
        const mark = document.createElement("span");
        mark.className = "mark";
        mark.textContent = "  (" + DATA.text.builtin + ")";
        c1.appendChild(mark);
      }
      tr.insertCell().textContent = contextText(row);
      tr.onclick = () => select(row.name);
    }
  }
}

function checkboxes(host, values, chosen, textMap) {
  host.textContent = "";
  for (const value of values) {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = value;
    box.checked = chosen.includes(value);
    label.appendChild(box);
    label.appendChild(document.createTextNode(" " + (textMap[value] || value)));
    label.style.display = "block";
    host.appendChild(label);
  }
}

function chosen(host) {
  return [...host.querySelectorAll("input:checked")].map((b) => b.value);
}

function fill(row) {
  $("name").value = row ? row.name : "";
  $("desc").value = row ? row.description : "";
  $("pattern").value = row ? row.pattern : "";
  checkboxes($("ctxs"), DATA.contexts, row ? row.contexts : ["STATEMENT_CONTEXT"], DATA.text.contexts);
  checkboxes($("envs"), DATA.environments, row ? row.environments : [...DATA.environments], DATA.text.environments);
  $("err").textContent = "";
}

function select(name) {
  selected = name;
  original = name;
  fill(DATA.rows.find((r) => r.name === name) || null);
  renderList();
}

$("add").onclick = () => {
  selected = null;
  original = null;
  fill(null);
  renderList();
  $("name").focus();
};
$("del").onclick = () => selected && vsapi.postMessage({ type: "delete", name: selected });
$("imp").onclick = () => vsapi.postMessage({ type: "import" });
$("exp").onclick = () => vsapi.postMessage({ type: "export" });
$("reset").onclick = () => vsapi.postMessage({ type: "reset" });
$("save").onclick = () => {
  vsapi.postMessage({
    type: "save",
    original: original,
    draft: {
      name: $("name").value,
      description: $("desc").value,
      pattern: $("pattern").value,
      contexts: chosen($("ctxs")),
      environments: chosen($("envs")),
      isAutoinsertable: false,
    },
  });
};

window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "invalid") $("err").textContent = e.data.text;
});

$("file").textContent = DATA.file;
renderList();
fill(null);
</script>
</body>
</html>`;
  }

  private dispose(): void {
    TemplatesPanel.current = undefined;
    this.panel.dispose();
    while (this.disposables.length) {
      this.disposables.pop()?.dispose();
    }
  }
}

async function importTemplates(): Promise<void> {
  const picked = await vscode.window.showOpenDialog({
    canSelectMany: false,
    openLabel: vscode.l10n.t("Import"),
    filters: { JSON: ["json"], [vscode.l10n.t("All files")]: ["*"] },
  });
  if (!picked?.length) {
    return;
  }
  const res = await run(templatesArgs("import", engineConfig(), [picked[0].fsPath]));
  if (res.error) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to import the templates: {0}", res.error));
    return;
  }
  try {
    const out = parseTemplatesResult(res.stdout);
    await reloadEngine();
    void vscode.window.showInformationMessage(
      vscode.l10n.t("Templates imported: {0} (skipped: {1})", String(out.imported ?? 0), String(out.skipped ?? 0)),
    );
  } catch (e) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to import the templates: {0}", String(e)));
  }
}

async function exportTemplates(): Promise<void> {
  const target = await vscode.window.showSaveDialog({
    saveLabel: vscode.l10n.t("Export"),
    filters: { JSON: ["json"] },
    defaultUri: vscode.Uri.file("templates.json"),
  });
  if (!target) {
    return;
  }
  const res = await run(templatesArgs("export", engineConfig(), ["--output", target.fsPath]));
  if (res.error) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to export the templates: {0}", res.error));
    return;
  }
  try {
    const out = parseTemplatesResult(res.stdout);
    void vscode.window.showInformationMessage(
      vscode.l10n.t("Templates exported: {0}", String(out.exported ?? 0)),
    );
  } catch (e) {
    void vscode.window.showErrorMessage(vscode.l10n.t("Failed to export the templates: {0}", String(e)));
  }
}

export function registerTemplates(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    // Session restore: without a serializer VS Code drops the tab on restart. The panel holds no
    // per-session target - the template list is re-read - so restoring is just re-adoption.
    vscode.window.registerWebviewPanelSerializer(TEMPLATES_VIEW_TYPE, {
      async deserializeWebviewPanel(restored: vscode.WebviewPanel): Promise<void> {
        await TemplatesPanel.adopt(restored);
      },
    }),
    vscode.commands.registerCommand("xbsl.templates.manage", () => TemplatesPanel.show()),
    vscode.commands.registerCommand("xbsl.templates.import", async () => {
      await importTemplates();
      await TemplatesPanel.current?.refresh();
    }),
    vscode.commands.registerCommand("xbsl.templates.export", () => exportTemplates()),
  );
}
