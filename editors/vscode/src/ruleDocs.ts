// Linter rules backed by a documented platform requirement are linked to an Element
// documentation page: the page id (for the local panel + tree) and the section anchor. The
// code of such a diagnostic in "Problems" becomes a link opening the relevant section
// INSIDE VS Code. Rules without a page (typography, whitespace, encoding, file pairing,
// unused variables, catalog-based existence checks, empirical apply restrictions) get no
// links: better no link than a link to the wrong place.

import * as vscode from "vscode";

const DOCS_ORIGIN = "https://1cmycloud.com/docs/help/";

// Standards (mandatory).
const NAMES = "topics/project-element-names-standard";
const PROPS = "topics/project-properties-standard";
// The "Рекомендации по написанию кода" section.
const DESIGN = "topics/general-design";
const NAMING = "topics/naming-convention";
const TYPES = "topics/type-description-and-initialization";
const WRAP = "topics/split-expressions";
const CONCAT = "topics/string-concatenation";
// Language and the execution model.
const METHODS = "topics/methods-in-built-in-script-language";
const EXEC = "topics/module-execution";
const MODULAR = "topics/modular-development";
const ENUM = "topics/enumeration-properties";

// Mapping rule/group -> documentation page + section anchor (heading id on the page).
// Specific rules go before group ones. Anchors are heading ids in docs.sqlite
// (see extract_docs); every pair is verified to exist.
const RULE_DOCS: ReadonlyArray<{ match: (rule: string) => boolean; page: string; anchor?: string }> = [
  // --- project element names (standard) ---
  { match: (r) => r === "naming/presentation", page: NAMES, anchor: "2-представления-элементов-проекта" },
  // Environment postfix, number in a name and per-kind prefix live in section 3, not in general 1.
  {
    match: (r) => r === "naming/module-suffix",
    page: NAMES,
    anchor: "приложение-и-структура-проекта",
  },
  {
    match: (r) => r === "naming/number" || r === "naming/prefix-by-kind",
    page: NAMES,
    anchor: "3-особенности-и-примеры-наименования-элементов-проекта",
  },
  { match: (r) => r.startsWith("naming/"), page: NAMES, anchor: "1-общие-правила-наименования" },

  // --- project properties (standard) ---
  { match: (r) => r === "project/presentation", page: PROPS, anchor: "представление" },
  { match: (r) => r === "project/version", page: PROPS, anchor: "версия" },
  { match: (r) => r.startsWith("project/"), page: PROPS, anchor: "поставщик" }, // Поставщик + Имя

  // --- code writing recommendations: general layout ---
  { match: (r) => r === "style/tab-indent", page: DESIGN, anchor: "синтаксический-отступ" },
  { match: (r) => r === "style/line-length", page: DESIGN, anchor: "длина-строки" },
  { match: (r) => r === "style/semicolon-line" || r === "code/blocks", page: DESIGN, anchor: "составные-инструкции" },

  // --- recommendations: names in code ---
  { match: (r) => r === "style/camel-case", page: NAMING, anchor: "общие-рекомендации" },
  { match: (r) => r === "style/abbreviation-case", page: NAMING, anchor: "аббревиатуры" },
  { match: (r) => r === "style/const-case", page: NAMING, anchor: "константы" },
  { match: (r) => r === "style/enum-name-vid", page: NAMING, anchor: "перечисления" },
  { match: (r) => r === "style/exception-prefix", page: NAMING, anchor: "исключения" },

  // --- recommendations: types and initialization ---
  { match: (r) => r === "style/type-colon-space", page: TYPES, anchor: "синтаксис" },
  { match: (r) => r === "style/union-spaces", page: TYPES, anchor: "составной-тип" },
  { match: (r) => r === "style/nullable-shorthand", page: TYPES, anchor: "тип-неопределено" },
  { match: (r) => r === "style/redundant-type", page: TYPES, anchor: "инициализация" },

  // --- recommendations: line wrapping, strings, collections ---
  { match: (r) => r === "style/wrap-comma", page: WRAP, anchor: "перенос-параметров" },
  { match: (r) => r === "style/wrap-operator", page: WRAP, anchor: "перенос-выражений" },
  { match: (r) => r === "style/interpolation", page: CONCAT, anchor: "интерполяция" },
  {
    match: (r) => r === "style/redundant-tostring",
    page: CONCAT,
    anchor: "неявное-преобразование-к-типу-строка",
  },
  { match: (r) => r === "style/collection-literal", page: "topics/collection-literals-usage" },

  // --- recommendations: operations and statements ---
  { match: (r) => r === "style/optional-params-last", page: "topics/method-declarations" },
  { match: (r) => r === "style/boolean-compare", page: "topics/check-logical-values" },
  { match: (r) => r === "style/undefined-is", page: "topics/check-if-undefined" },
  { match: (r) => r === "style/negated-is", page: "topics/is-operator" },

  // --- language: constructs ---
  { match: (r) => r === "code/parse-error", page: DESIGN },
  { match: (r) => r === "code/param-type-required", page: METHODS, anchor: "определение-метода" },
  { match: (r) => r === "code/loop-header", page: "topics/for-in-loop", anchor: "синтаксис" },
  { match: (r) => r === "code/ternary-and-or", page: "topics/question-mark-operation", anchor: "синтаксис" },
  { match: (r) => r === "code/ref-field-needs-req", page: "topics/structure", anchor: "синтаксис" },
  { match: (r) => r === "code/return-mismatch", page: METHODS, anchor: "определение-метода" },
  { match: (r) => r === "code/call-arity", page: METHODS, anchor: "определение-метода" },
  { match: (r) => r === "code/call-arity-cross", page: METHODS, anchor: "определение-метода" },
  { match: (r) => r === "code/catch-non-exception", page: "topics/exceptions" },
  { match: (r) => r === "code/unknown-enum-value", page: ENUM, anchor: "элементы" },

  // --- execution model and modularity ---
  {
    match: (r) => r === "code/client-annotation-in-server-module"
      || r === "code/client-module-in-http-service"
      || r === "code/server-call-from-handler",
    page: EXEC,
  },
  {
    match: (r) => r === "code/local-method-cross-component",
    page: MODULAR,
    anchor: "видимость-языковых-конструкций",
  },
  { match: (r) => r === "yaml/missing-import", page: MODULAR, anchor: "импорт-пространств-имен" },
  {
    match: (r) => r === "yaml/foreign-not-public",
    page: MODULAR,
    anchor: "область-видимости-элемента-проекта",
  },

  // --- queries, forms, yaml ---
  {
    match: (r) => r === "query/in-subquery-composite",
    page: "topics/in-expression",
    anchor: "использование-выражения-в-с-подзапросом-для-выражений-составного-типа",
  },
  { match: (r) => r === "query/unknown-table", page: "topics/select-from", anchor: "синтаксис" },
  { match: (r) => r === "form/unknown-handler", page: "topics/form-component", anchor: "события" },
  { match: (r) => r === "yaml/enum-needs-nullable", page: ENUM, anchor: "элементы" },
  { match: (r) => r === "yaml/dynlist-missing-field", page: "topics/dynamic-list" },
  {
    match: (r) => r === "yaml/choice-needs-static-list",
    page: "stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru",
    anchor: "списоквыбора",
  },
  {
    match: (r) => r === "yaml/size-needs-no-stretch",
    page: "topics/arrange-components-on-screen",
    anchor: "растягиватьповертикали-и-растягиватьпогоризонтали",
  },
];

export interface RuleDoc {
  page: string; // page id for xbsl.docs.open (panel + tree positioning)
  anchor?: string; // section heading id on the page (scroll to the right place)
  url: string; // canonical address on the documentation site
}

export function ruleDoc(rule: string | undefined): RuleDoc | undefined {
  if (!rule) {
    return undefined;
  }
  const hit = RULE_DOCS.find((d) => d.match(rule));
  return hit ? { page: hit.page, anchor: hit.anchor, url: DOCS_ORIGIN + hit.page + "/" } : undefined;
}

// Diagnostic code: for a rule backed by a standard the rule badge in "Problems" becomes a link
// opening the relevant SECTION INSIDE VS Code (the Documentation panel + tree + scroll to the
// anchor) via the xbsl.docs.open command, not an external site. Other rules get a plain id.
export function docCode(rule: string): string | { value: string; target: vscode.Uri } {
  const doc = ruleDoc(rule);
  if (!doc) {
    return rule;
  }
  const args = encodeURIComponent(JSON.stringify(doc.anchor ? [doc.page, doc.anchor] : [doc.page]));
  return { value: rule, target: vscode.Uri.parse(`command:xbsl.docs.open?${args}`) };
}

// Rule id from a diagnostic code (a string or a {value, target} object).
export function ruleOfCode(code: vscode.Diagnostic["code"]): string | undefined {
  if (typeof code === "string") {
    return code;
  }
  if (code && typeof code === "object" && "value" in code) {
    return String(code.value);
  }
  return undefined;
}
