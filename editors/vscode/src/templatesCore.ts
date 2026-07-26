// Pure core of the templates panel: engine arguments, parsing its response, grouping and
// draft validation. No vscode imports - covered by unit tests (test/templatesCore.test.ts).
//
// All writing lives in the engine (xbsl templates save/import/export): the extension only draws.

export interface TemplateRow {
  name: string;
  trigger: string;
  prefix: string;
  title: string;
  description: string;
  category: string;
  contexts: string[];
  environments: string[];
  pattern: string;
  preview: string;
  isAutoinsertable: boolean;
  builtin: boolean;
}

export interface TemplatesList {
  templates: TemplateRow[];
  file: string;
}

export interface EngineConfig {
  command: string;
  usePython: boolean;
  templatesFile?: string;
}

export const CONTEXTS = ["STATEMENT_CONTEXT", "DECLARATION_CONTEXT", "QUERY_CONTEXT"] as const;
export const ENVIRONMENTS = ["SERVER_ENVIRONMENT", "CLIENT_ENVIRONMENT"] as const;

// Arguments of `xbsl templates <action>`. --file goes AFTER the action: the engine accepts
// it on every subcommand exactly for this.
export function templatesArgs(action: string, cfg: EngineConfig, extra: string[] = []): string[] {
  const args = cfg.usePython ? ["-m", "xbsl"] : [];
  args.push("templates", action, ...extra);
  if (cfg.templatesFile) {
    args.push("--file", cfg.templatesFile);
  }
  return args;
}

export function parseTemplatesList(stdout: string): TemplatesList {
  const data = JSON.parse(stdout);
  if (data && typeof data.error === "string") {
    throw new Error(data.error);
  }
  if (!data || !Array.isArray(data.templates)) {
    throw new Error("xbsl templates list: unexpected output");
  }
  return { templates: data.templates as TemplateRow[], file: String(data.file ?? "") };
}

// Response of writing actions (save/import/export) - either {error} or a summary.
export function parseTemplatesResult(stdout: string): Record<string, unknown> {
  const data = JSON.parse(stdout);
  if (data && typeof data.error === "string") {
    throw new Error(data.error);
  }
  return data as Record<string, unknown>;
}

export interface CategoryGroup {
  category: string;
  templates: TemplateRow[];
}

// List tree: categories in alphabetical order, inside - by abbreviation. The order is stable,
// otherwise the row would slide out from under the cursor on every edit.
export function groupByCategory(rows: TemplateRow[]): CategoryGroup[] {
  const byCategory = new Map<string, TemplateRow[]>();
  for (const row of rows) {
    const key = row.category || "/";
    const list = byCategory.get(key);
    if (list) {
      list.push(row);
    } else {
      byCategory.set(key, [row]);
    }
  }
  return [...byCategory.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], "ru"))
    .map(([category, templates]) => ({
      category,
      templates: [...templates].sort((a, b) => a.trigger.localeCompare(b.trigger, "ru")),
    }));
}

export interface TemplateDraft {
  name: string;
  description: string;
  pattern: string;
  contexts: string[];
  environments: string[];
  isAutoinsertable: boolean;
}

// Draft validation before sending to the engine: the engine checks again, but a message in the
// form is clearer than a process error and costs no disk write.
export function validateDraft(draft: TemplateDraft, existing: TemplateRow[], original?: string): string | undefined {
  const name = draft.name.trim();
  if (!name) {
    return "empty-name";
  }
  if (!draft.pattern.trim()) {
    return "empty-pattern";
  }
  if (name !== original && existing.some((t) => t.name === name)) {
    return "duplicate-name";
  }
  if (!draft.contexts.length) {
    return "no-context";
  }
  if (!draft.environments.length) {
    return "no-environment";
  }
  return undefined;
}

// `мет[од] - Метод` -> the abbreviation `метод`: what is visible in the list and what is typed
// in the editor. The parsing duplicates the engine on purpose - the form needs the hint before
// saving.
export function triggerOf(name: string): string {
  const head = name.split(" - ")[0] ?? "";
  return head.replace("[", "").replace("]", "").trim();
}

// The set that goes to `xbsl templates save`: an envelope of the same shape as the export.
export function toEnvelope(rows: Array<TemplateRow | TemplateDraft>): string {
  return JSON.stringify({
    templates: rows.map((r) => ({
      type: "xbsl.template",
      name: r.name,
      description: r.description,
      context: { moduleEnvironments: r.environments, moduleContexts: r.contexts },
      pattern: r.pattern,
      isAutoinsertable: r.isAutoinsertable,
    })),
  });
}

// Replace a template by name (edit) or append at the end (new).
export function upsert(
  rows: TemplateRow[],
  draft: TemplateDraft,
  original?: string,
): Array<TemplateRow | TemplateDraft> {
  const key = original ?? draft.name;
  const out: Array<TemplateRow | TemplateDraft> = [];
  let replaced = false;
  for (const row of rows) {
    if (row.name === key) {
      out.push(draft);
      replaced = true;
    } else {
      out.push(row);
    }
  }
  if (!replaced) {
    out.push(draft);
  }
  return out;
}
