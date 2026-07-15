// Правила линтера, реализующие платформенные СТАНДАРТЫ, связаны со страницей стандарта в
// документации Элемента: id страницы (для локальной панели + дерева) и канонический URL (для
// кликабельной ссылки в самой диагностике). Прочие правила – собственные соглашения линтера,
// отдельной страницы стандарта у них нет, ссылки не добавляем.

import * as vscode from "vscode";

const DOCS_ORIGIN = "https://1cmycloud.com/docs/help/";

// Соответствие правило/группа -> страница документации (id как в docs.sqlite / дереве).
const RULE_DOCS: ReadonlyArray<{ match: (rule: string) => boolean; page: string }> = [
  { match: (r) => r.startsWith("naming/"), page: "topics/project-element-names-standard" },
  { match: (r) => r.startsWith("project/"), page: "topics/project-properties-standard" },
  { match: (r) => r === "query/in-subquery-composite", page: "topics/in-expression" },
];

export interface RuleDoc {
  page: string; // id страницы для xbsl.docs.open (панель + позиционирование дерева)
  url: string; // канонический адрес на сайте документации
}

export function ruleDoc(rule: string | undefined): RuleDoc | undefined {
  if (!rule) {
    return undefined;
  }
  const hit = RULE_DOCS.find((d) => d.match(rule));
  return hit ? { page: hit.page, url: DOCS_ORIGIN + hit.page + "/" } : undefined;
}

// Код диагностики: у правила со стандартом – ссылка (значок правила кликабелен в "Проблемах"),
// иначе просто идентификатор правила.
export function docCode(rule: string): string | { value: string; target: vscode.Uri } {
  const doc = ruleDoc(rule);
  return doc ? { value: rule, target: vscode.Uri.parse(doc.url) } : rule;
}

// Идентификатор правила из кода диагностики (строка или объект {value, target}).
export function ruleOfCode(code: vscode.Diagnostic["code"]): string | undefined {
  if (typeof code === "string") {
    return code;
  }
  if (code && typeof code === "object" && "value" in code) {
    return String(code.value);
  }
  return undefined;
}
