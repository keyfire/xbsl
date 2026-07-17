// Чистое ядро панели шаблонов: аргументы движка, разбор его ответа, группировка и проверка
// черновика. Без импортов vscode - покрыто юнит-тестами (test/templatesCore.test.ts).
//
// Вся запись живёт в движке (xbsl templates save/import/export): расширение только рисует.

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

// Аргументы `xbsl templates <действие>`. --file идёт ПОСЛЕ действия: движок принимает его
// у каждой подкоманды именно для этого.
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

// Ответ пишущих действий (save/import/export) - либо {error}, либо сводка.
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

// Дерево списка: категории в алфавитном порядке, внутри - по аббревиатуре. Порядок устойчив,
// иначе строка уезжала бы из-под курсора при каждой правке.
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

// Проверка черновика перед отправкой в движок: движок проверит ещё раз, но сообщение в форме
// понятнее, чем ошибка процесса, и не стоит записи на диск.
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

// `мет[од] - Метод` -> аббревиатура `метод`: то, что видно в списке и что набирают в редакторе.
// Разбор дублирует движок намеренно - в форме подсказка нужна до сохранения.
export function triggerOf(name: string): string {
  const head = name.split(" - ")[0] ?? "";
  return head.replace("[", "").replace("]", "").trim();
}

// Набор, который уйдёт в `xbsl templates save`: конверт того же вида, что и выгрузка.
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

// Замена шаблона по имени (правка) либо добавление в конец (новый).
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
