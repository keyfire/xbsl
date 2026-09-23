// Bridge VS Code diagnostics to the metadata tree's file-family counts.

import * as vscode from "vscode";

import { MetadataProblemCounts, ProblemCounts, ProblemFamily } from "./metadataProblemsCore";
import { pathKey } from "./packagesCore";

export class MetadataProblems implements vscode.Disposable {
  private readonly counts = new MetadataProblemCounts([]);
  private readonly listener: vscode.Disposable;
  private readonly pending = new Map<string, vscode.Uri>();
  private timer?: NodeJS.Timeout;

  constructor(private readonly changed: () => void) {
    this.listener = vscode.languages.onDidChangeDiagnostics((event) => {
      for (const uri of event.uris) {
        if (uri.scheme === "file" && this.counts.hasFile(uri.fsPath)) {
          this.pending.set(pathKey(uri.fsPath), uri);
        }
      }
      if (this.pending.size && !this.timer) {
        this.timer = setTimeout(() => this.flush(), 180);
      }
    });
  }

  setFamilies(families: readonly ProblemFamily[]): void {
    this.counts.setFamilies(families);
    const snapshot = new Map(
      vscode.languages.getDiagnostics()
        .filter(([uri]) => uri.scheme === "file")
        .map(([uri, diagnostics]) => [pathKey(uri.fsPath), diagnostics] as const),
    );
    for (const file of this.counts.paths()) {
      const diagnostics = snapshot.get(pathKey(file)) ?? [];
      this.counts.update(file, diagnostics.map((diagnostic) => diagnostic.severity));
    }
    this.pending.clear();
  }

  get(id: string): ProblemCounts {
    return this.counts.get(id);
  }

  private flush(): void {
    this.timer = undefined;
    let hasChanges = false;
    for (const uri of this.pending.values()) {
      const severities = vscode.languages.getDiagnostics(uri).map((diagnostic) => diagnostic.severity);
      if (this.counts.update(uri.fsPath, severities).length) {
        hasChanges = true;
      }
    }
    this.pending.clear();
    if (hasChanges) this.changed();
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.pending.clear();
    this.listener.dispose();
    this.counts.dispose();
  }
}
