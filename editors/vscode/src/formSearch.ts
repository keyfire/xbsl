// Structural search across the project's interface-component forms (docs/DESIGNER.md hook 10).
// The command asks for a query - a component type plus optional key=value property predicates -
// gathers the form texts (live buffers), sends them to the engine (xbsl/searchForms), and shows
// the matches in a quick pick that navigates to the component's line in its form yaml. A thin
// client: the matching is the engine's business (formsearch.py), this only drives the UI.

import * as vscode from "vscode";
import { lspActive, lspRequest } from "./lspClient";
import { revealContent } from "./reveal";

interface FormMatch {
  path: string;
  nodeId: string;
  name: string;
  type: string;
  line: number; // 0-based
}

interface SearchDeps {
  // The project's КомпонентИнтерфейса forms (name + yaml path) - the metadata tree provides them.
  interfaceComponents: () => Promise<Array<{ name: string; yamlPath: string }>>;
}

export function registerFormSearch(context: vscode.ExtensionContext, deps: SearchDeps): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.forms.search", () => runSearch(deps))
  );
}

async function runSearch(deps: SearchDeps): Promise<void> {
  if (!lspActive()) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("Structural search needs the LSP mode (xbsl.lsp.enabled) and the xbsl engine.")
    );
    return;
  }
  const query = await vscode.window.showInputBox({
    title: vscode.l10n.t("Search forms by structure"),
    prompt: vscode.l10n.t("A component type and optional key=value predicates"),
    placeHolder: "Кнопка Вид=Основная",
  });
  if (query === undefined || query.trim() === "") {
    return;
  }
  const forms = await deps.interfaceComponents();
  if (!forms.length) {
    void vscode.window.showInformationMessage(
      vscode.l10n.t("No interface-component forms in the project.")
    );
    return;
  }
  const paths: string[] = [];
  const texts: string[] = [];
  for (const form of forms) {
    try {
      const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(form.yamlPath));
      paths.push(form.yamlPath);
      texts.push(doc.getText());
    } catch {
      // an unreadable form is skipped, not fatal
    }
  }
  const res = await lspRequest<{ matches: FormMatch[] }>("xbsl/searchForms", { paths, texts, query });
  const matches = res?.matches ?? [];
  if (!matches.length) {
    void vscode.window.showInformationMessage(vscode.l10n.t('No components match "{0}".', query));
    return;
  }
  const nameByPath = new Map(forms.map((f) => [f.yamlPath, f.name]));
  const items = matches.map((m) => ({
    label: `$(symbol-field) ${m.type}${m.name ? " · " + m.name : ""}`,
    description: nameByPath.get(m.path) ?? "",
    detail: `${vscode.workspace.asRelativePath(m.path)}:${m.line + 1}`,
    match: m,
  }));
  const pick = await vscode.window.showQuickPick(items, {
    title: vscode.l10n.t("Matches: {0}", String(matches.length)),
    matchOnDescription: true,
    matchOnDetail: true,
    placeHolder: vscode.l10n.t("Open a component in its form yaml"),
  });
  if (!pick) {
    return;
  }
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(pick.match.path));
  const editor = await vscode.window.showTextDocument(doc);
  const line = Math.min(Math.max(pick.match.line, 0), Math.max(0, doc.lineCount - 1));
  const pos = new vscode.Position(line, 0);
  editor.selection = new vscode.Selection(pos, pos);
  revealContent(editor, pos);
}
