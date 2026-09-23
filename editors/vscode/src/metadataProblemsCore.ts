// Counts diagnostics over a source family and its visible metadata folders.
// This module stays independent of VS Code so ownership and cleanup can be tested under Node.

import { pathKey } from "./packagesCore";

export interface ProblemCounts {
  errors: number;
  warnings: number;
}

export interface ProblemFamily {
  id: string;
  files: string[];
  ancestors: string[];
}

const none = (): ProblemCounts => ({ errors: 0, warnings: 0 });

/** The element's own YAML and every paired code file in the same folder. */
export function filesForElement(yamlPath: string, codePaths: readonly string[]): string[] {
  const normalized = pathKey(yamlPath);
  if (!normalized.endsWith(".yaml")) {
    return [yamlPath];
  }
  const stem = normalized.slice(0, -".yaml".length);
  const paired = codePaths.filter((candidate) => {
    const file = pathKey(candidate);
    return file === `${stem}.xbsl` || file === `${stem}.xbql`
      || (file.startsWith(`${stem}.`) && file.endsWith(".xbsl"));
  });
  return [yamlPath, ...paired];
}

export class MetadataProblemCounts {
  private owners = new Map<string, { path: string; ids: string[] }>();
  private perFile = new Map<string, ProblemCounts>();
  private totals = new Map<string, ProblemCounts>();

  constructor(families: readonly ProblemFamily[]) {
    this.setFamilies(families);
  }

  setFamilies(families: readonly ProblemFamily[]): void {
    const previous = this.perFile;
    this.owners = new Map();
    this.perFile = new Map();
    this.totals = new Map();
    for (const family of families) {
      const ids = [...new Set([family.id, ...family.ancestors].map(pathKey))];
      for (const file of family.files) {
        const fileKey = pathKey(file);
        if (!this.owners.has(fileKey)) {
          this.owners.set(fileKey, { path: file, ids });
        }
      }
    }
    for (const [file, counts] of previous) {
      if (this.owners.has(file)) {
        this.set(file, counts);
      }
    }
  }

  paths(): string[] {
    return [...this.owners.values()].map((owner) => owner.path);
  }

  hasFile(path: string): boolean {
    return this.owners.has(pathKey(path));
  }

  update(path: string, severities: readonly number[]): string[] {
    const next = none();
    for (const severity of severities) {
      if (severity === 0) next.errors++;
      else if (severity === 1) next.warnings++;
    }
    return this.set(pathKey(path), next);
  }

  private set(file: string, next: ProblemCounts): string[] {
    const owner = this.owners.get(file);
    if (!owner) return [];
    const before = this.perFile.get(file) ?? none();
    if (before.errors === next.errors && before.warnings === next.warnings) return [];
    if (next.errors || next.warnings) this.perFile.set(file, next);
    else this.perFile.delete(file);
    for (const id of owner.ids) {
      const total = this.totals.get(id) ?? none();
      total.errors += next.errors - before.errors;
      total.warnings += next.warnings - before.warnings;
      if (total.errors || total.warnings) this.totals.set(id, total);
      else this.totals.delete(id);
    }
    return owner.ids;
  }

  get(id: string): ProblemCounts {
    return this.totals.get(pathKey(id)) ?? none();
  }

  dispose(): void {
    this.owners.clear();
    this.perFile.clear();
    this.totals.clear();
  }
}
