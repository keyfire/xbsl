// F12 in an XBSL file: the definition when there is one, the documentation page when there
// is not. The decision itself lives in definitionDocsCore.ts; here is the VS Code glue -
// ask the definition providers, ask the server for a page (xbsl/hoverDoc answers the same
// {pageId, symbol} the hover link uses), then act.

import * as vscode from "vscode";
import { lspRequest } from "./lspClient";
import { chooseAction } from "./definitionDocsCore";

interface HoverDoc {
  pageId: string | null;
  symbol: string | null;
}

async function definitionCount(document: vscode.TextDocument, position: vscode.Position): Promise<number> {
  try {
    const targets = await vscode.commands.executeCommand<unknown[]>(
      "vscode.executeDefinitionProvider",
      document.uri,
      position
    );
    return Array.isArray(targets) ? targets.length : 0;
  } catch {
    // A provider that failed is not a reason to hide the documentation - treat it as a miss.
    return 0;
  }
}

export function registerDefinitionDocs(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.goToDefinition", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) {
        return;
      }
      const document = editor.document;
      const position = editor.selection.active;
      const found = await definitionCount(document, position);
      let pageId: string | null = null;
      if (found === 0 && document.languageId === "xbsl") {
        const res = await lspRequest<HoverDoc>("xbsl/hoverDoc", {
          uri: document.uri.toString(),
          position: { line: position.line, character: position.character },
        });
        pageId = res?.pageId ?? null;
      }
      if (chooseAction(found, pageId) === "docs" && pageId) {
        await vscode.commands.executeCommand("xbsl.docs.open", pageId);
        return;
      }
      // Both "reveal" and "passThrough" end here: the built-in command jumps when there is
      // somewhere to jump, and reports the miss itself when there is not.
      await vscode.commands.executeCommand("editor.action.revealDefinition");
    })
  );
}
