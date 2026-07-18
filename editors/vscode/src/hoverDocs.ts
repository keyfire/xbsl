// A hover addition for the code editor: for a symbol whose type is known (a stdlib type or
// member under the cursor, or a local variable's inferred type) it offers a clickable link to
// the INTERNAL documentation panel. The LSP server resolves the doc page (xbsl/hoverDoc); this
// provider renders the link. A command link needs a TRUSTED MarkdownString - a link inside the
// server's own MarkupContent hover would be sanitized and not clickable, which is why the link
// lives in a separate, client-side hover provider (VS Code stacks it under the LSP hover).

import * as vscode from "vscode";
import { lspRequest } from "./lspClient";

interface HoverDoc {
  pageId: string | null;
  symbol: string | null;
}

// The command link target: xbsl.docs.open(id) opens the page in the docs panel. Arguments ride
// as a JSON array in the query, url-encoded.
export function docsCommandUri(pageId: string): vscode.Uri {
  return vscode.Uri.parse(`command:xbsl.docs.open?${encodeURIComponent(JSON.stringify([pageId]))}`);
}

export function registerHoverDocs(context: vscode.ExtensionContext): void {
  const provider: vscode.HoverProvider = {
    async provideHover(document, position) {
      const res = await lspRequest<HoverDoc>("xbsl/hoverDoc", {
        uri: document.uri.toString(),
        position: { line: position.line, character: position.character },
      });
      if (!res || !res.pageId) {
        return undefined;
      }
      const md = new vscode.MarkdownString(
        `[$(book) ${vscode.l10n.t("Documentation")}](${docsCommandUri(res.pageId).toString()})`,
        true // supportThemeIcons
      );
      md.isTrusted = { enabledCommands: ["xbsl.docs.open"] };
      return new vscode.Hover(md);
    },
  };
  context.subscriptions.push(vscode.languages.registerHoverProvider({ language: "xbsl" }, provider));
}
