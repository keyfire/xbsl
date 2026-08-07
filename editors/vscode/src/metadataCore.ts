// Parsing of the internal structure of a 1C:Element object (attributes, dimensions, resources,
// tabular sections, enumeration values, client operation parameters, HTTP service URL templates)
// and generation of a targeted insertion of a new section item into yaml. The module is pure
// (no vscode) so it can be checked by plain node tests; the tree wiring is in metadataTree.ts,
// the properties-panel row mapping and writes are in propsModes.ts.
//
// Sections are arrays of same-shaped descriptions. The shape depends on the section:
// attribute/dimension/resource - { Ид, Имя, Тип }; enumeration value - { Ид, Имя }; client
// parameter - { Имя, Тип }; URL template - { Имя, Шаблон, Методы }. Standard attributes
// (Наименование, Код) come without Ид.

import { isMap, isScalar, isSeq, parseDocument } from "yaml";
import type { Node, YAMLMap } from "yaml";

// The kind spellings the platform's SERIALIZER writes into `ElementKind:` of an English
// project, read out of the distribution's own kind table (kept in sync with the engine's
// `xbsl/metamodel.py` constant). This is a different vocabulary from the stdlib TYPE names:
// the type of an enumeration is `Enum`, while `ElementKind:` says `Enumeration` - objects
// spelled that way used to fall out of the metadata tree into "Other"
// ([issue #1](https://github.com/keyfire/xbsl/issues/1)).
export const SERIALIZER_KIND_SPELLINGS: ReadonlyMap<string, string> = new Map([
  ["AccessKey", "КлючДоступа"],
  ["AccumulationRegister", "РегистрНакопления"],
  ["Catalog", "Справочник"],
  ["ClientWorkParameters", "ПараметрыРаботыКлиента"],
  ["CommandInterfaceFragment", "ФрагментКомандногоИнтерфейса"],
  ["CommandWithComponent", "КомандаСКомпонентом"],
  ["CommonModule", "ОбщийМодуль"],
  ["ConstantsSet", "НаборКонстант"],
  ["DataJournal", "ЖурналДанных"],
  ["Document", "Документ"],
  ["EntityContract", "КонтрактСущности"],
  ["Enumeration", "Перечисление"],
  ["EventLogEvent", "СобытиеЖурналаСобытий"],
  ["ExchangePlan", "ПланОбмена"],
  ["GlobalClientEvent", "ГлобальноеКлиентскоеСобытие"],
  ["HttpService", "HttpСервис"],
  ["InformationRegister", "РегистрСведений"],
  ["IntegrableApplication", "ИнтегрируемоеПриложение"],
  ["IntegrationProcess", "ПроцессИнтеграции"],
  ["InterfaceComponent", "КомпонентИнтерфейса"],
  ["LocalizedStrings", "ЛокализованныеСтроки"],
  ["NavigationCommand", "НавигационнаяКоманда"],
  ["PrivilegeOnAction", "ПравоНаДействие"],
  ["PrivilegeOnElement", "ПравоНаЭлемент"],
  ["Processing", "Обработка"],
  ["Project", "Проект"],
  ["Report", "Отчет"],
  ["ReportColorSchema", "ЦветоваяСхемаОтчета"],
  ["ReportPanel", "ПанельОтчетов"],
  ["ScheduledJob", "ЗапланированноеЗадание"],
  ["ServiceContract", "КонтрактСервиса"],
  ["SettingsStorage", "ХранилищеНастроек"],
  ["SoapService", "SoapСервис"],
  ["SoapServiceClient", "КлиентSoapСервиса"],
  ["StorableStructure", "ХранимаяСтруктура"],
  ["Structure", "Структура"],
  ["SwitchableCommand", "ПереключаемаяКоманда"],
  ["TypeContract", "КонтрактТипа"],
  ["UserSelfRegistrationParameter", "ПараметрСамостоятельнойРегистрацииПользователя"],
  ["UsualCommand", "ОбычнаяКоманда"],
  ["VirtualTable", "ВиртуальнаяТаблица"],
]);

export interface MetaField {
  name: string;
  type?: string; // Тип / Шаблон / Обработчик - shown as the field caption
  offset?: number; // offset of the field map in the text - for navigation and the properties panel
  children?: MetaField[]; // nested (tabular section attributes, URL template methods)
}

export interface MetaInternals {
  rootOffset: number;
  attributes: MetaField[]; // Реквизиты
  dimensions: MetaField[]; // Измерения
  resources: MetaField[]; // Ресурсы
  tabulars: MetaField[]; // ТабличныеЧасти (children = attributes)
  enumValues: MetaField[]; // Элементы (enumeration)
  clientParams: MetaField[]; // Параметры (ПараметрыРаботыКлиента)
  urlTemplates: MetaField[]; // ШаблоныUrl (children = methods)
  structFields: MetaField[]; // Поля (Структура)
}

export interface TextEdit {
  start: number;
  end: number;
  newText: string;
}

// -- access to yaml nodes -----------------------------------------------------------------

function get(map: unknown, key: string): unknown {
  if (!isMap(map)) {
    return undefined;
  }
  for (const item of (map as YAMLMap).items) {
    if (isScalar(item.key) && String(item.key.value) === key) {
      return item.value ?? undefined;
    }
  }
  return undefined;
}

// The platform spells every metadata key two ways (Имя/Name, ВидЭлемента/ElementKind), and a
// project written in English is legal code - a reader that knows one spelling shows "?" over half
// the world. Every lookup below asks by the Russian name and falls back to the English pair.
const EN_KEY: Record<string, string> = {
  "Имя": "Name",
  "Тип": "Type",
  "Ид": "Id",
  "ВидЭлемента": "ElementKind",
  "Представление": "Presentation",
  "Окружение": "Environment",
};

// Section keys (`Реквизиты`, `ТабличныеЧасти`, `ШаблоныUrl` ...) are NOT in the table above:
// listing them by hand would mean guessing the English spellings, and the platform declares them
// itself - every metamodel class carries the pair. The engine hands the whole map over once per
// session (`xbsl/metaKeys`), the editor stores it here, and lookups below consult it. Until it
// arrives - or when the engine has no data - the map stays empty and the reader behaves exactly
// as before: Russian keys only.
let EN_BY_RU: Record<string, string> = {};

// The names a HINT puts in front of the user - the rename prompt, the wrap prompt, the "no form
// content" note. A hint that names a key names the key the user is about to look for in the
// sources, so its spelling follows the language of the PROJECT and not the language of the
// editor: an English window over a Russian project must still say `Имя`, and a Russian window
// over an English project must say `Name`. Hence the hints are parametric and this table is
// their argument. The English spellings are the platform's own - the compiler dictionary
// (terms_full.json, the `common` pairs), never a translation.
const HINT_NAME_EN: Record<string, string> = {
  "Имя": "Name",
  "Содержимое": "Content",
  "Наследует": "Inherits",
  "Импорт": "Import",
};

/** The spelling of a platform name for a project that writes its names in English, or in Russian.
 *
 * A name the table does not carry comes back as it was given: the platform has far more names
 * than the hints use, and inventing an English spelling would be worse than showing the Russian
 * one - the user would look for a key that is not in the file.
 */
export function hintName(name: string, english: boolean): string {
  return english ? HINT_NAME_EN[name] ?? name : name;
}

/** Store the {Russian key: English spelling} pairs the engine reports (`xbsl/metaKeys`). */
export function setMetaKeyAliases(aliases: Record<string, string>): void {
  const pairs: Record<string, string> = {};
  for (const [english, russian] of Object.entries(aliases ?? {})) {
    if (russian && english) {
      pairs[russian] = english;
    }
  }
  EN_BY_RU = pairs;
}

/** A collection node by its Russian key, falling back to the English spelling of the platform. */
function section(map: unknown, key: string): unknown {
  const direct = get(map, key);
  if (direct !== undefined) {
    return direct;
  }
  const english = EN_BY_RU[key] ?? EN_KEY[key];
  return english ? get(map, english) : undefined;
}

function prop(map: unknown, key: string): string | undefined {
  for (const spelling of [key, EN_KEY[key]]) {
    if (!spelling) {
      continue;
    }
    const v = get(map, spelling);
    if (isScalar(v) && v.value !== null && v.value !== undefined) {
      return String(v.value);
    }
  }
  return undefined;
}

function offsetOf(node: unknown): number | undefined {
  const n = node as Node;
  return n && n.range ? n.range[0] : undefined;
}

interface FieldOpts {
  nameKey?: string;
  typeKey?: string;
  childKey?: string;
  childOpts?: FieldOpts;
}

function fieldsOf(seq: unknown, opts: FieldOpts = {}): MetaField[] {
  if (!isSeq(seq)) {
    return [];
  }
  const nameKey = opts.nameKey ?? "Имя";
  const typeKey = opts.typeKey ?? "Тип";
  const out: MetaField[] = [];
  for (const item of seq.items) {
    if (!isMap(item)) {
      continue;
    }
    out.push({
      name: prop(item, nameKey) ?? "?",
      type: prop(item, typeKey),
      offset: offsetOf(item),
      // Nested collections go through the same lookup: a tabular section spells its own
      // `Реквизиты`/`Attributes`, and the url template its `Методы`/`Methods`.
      children: opts.childKey ? fieldsOf(section(item, opts.childKey), opts.childOpts ?? {}) : undefined,
    });
  }
  return out;
}

export function parseInternals(text: string): MetaInternals | undefined {
  let root: unknown;
  try {
    root = parseDocument(text, { uniqueKeys: false }).contents ?? undefined;
  } catch {
    return undefined;
  }
  if (!isMap(root)) {
    return undefined;
  }
  return {
    rootOffset: offsetOf(root) ?? 0,
    attributes: fieldsOf(section(root, "Реквизиты")),
    dimensions: fieldsOf(section(root, "Измерения")),
    resources: fieldsOf(section(root, "Ресурсы")),
    tabulars: fieldsOf(section(root, "ТабличныеЧасти"), { childKey: "Реквизиты" }),
    enumValues: fieldsOf(section(root, "Элементы")),
    clientParams: fieldsOf(section(root, "Параметры")),
    urlTemplates: fieldsOf(section(root, "ШаблоныUrl"), {
      typeKey: "Шаблон",
      childKey: "Методы",
      childOpts: { nameKey: "Метод", typeKey: "Обработчик" },
    }),
    structFields: fieldsOf(section(root, "Поля")),
  };
}

// -- node description for the properties panel -----------------------------------------------
//
// Property rows of the selected yaml node (the whole object or one of its fields). Scalar
// properties are edited by the panel via propertyEdit (formPreviewCore) at this same offset;
// Ид and ВидЭлемента are read-only; complex values (Реквизиты, Интерфейс ...) are not shown.

export interface MetaPropRow {
  key: string;
  value: string;
  control: "text" | "select" | "tristate" | "combo";
  options?: string[];
  readonly?: boolean;
}

export interface MetaNodeDescription {
  title: string;
  offset: number;
  rows: MetaPropRow[];
  // Collection keys present in yaml (Реквизиты, Элементы ...) with their item count: the
  // rows edit scalars only, but the schema section must not call a non-empty collection
  // "(not set)" just because it has no scalar row.
  collections?: Record<string, number>;
}

function scalarStr(node: unknown): string | undefined {
  if (isScalar(node) && node.value !== null && node.value !== undefined) {
    return String(node.value);
  }
  return undefined;
}

function findMapAt(node: unknown, offset: number): YAMLMap | undefined {
  if (isMap(node)) {
    const m = node as YAMLMap;
    if (m.range && m.range[0] === offset) {
      return m;
    }
    for (const item of m.items) {
      const found = findMapAt(item.value, offset);
      if (found) {
        return found;
      }
    }
  } else if (isSeq(node)) {
    for (const item of node.items) {
      const found = findMapAt(item, offset);
      if (found) {
        return found;
      }
    }
  }
  return undefined;
}

// Value options of known enumerable metadata properties.
function metaOptionsFor(key: string): string[] | undefined {
  if (key === "ОбластьВидимости") {
    return ["ВПроекте", "ВПодсистеме"];
  }
  if (key === "Окружение") {
    return ["Сервер", "Клиент", "КлиентИСервер"];
  }
  return undefined;
}

const READONLY_KEYS = new Set(["Ид", "ВидЭлемента", "Id", "ElementKind"]);

// Keys whose value is a data type: shown as a combobox (input + datalist). The candidates
// (primitives + <Объект>.Ссылка? + <Перечисление>?) are known only to the tree provider, which
// feeds them into the panel; the list is open - the value can be typed in manually.
const TYPE_KEYS = new Set(["Тип", "Type"]);

// String-specific attribute properties: shown only when Тип is Строка. When the type changes
// to another one the panel removes them from yaml (see metaPropertyEdits in propsModes.ts).
const STRING_ONLY_KEYS = new Set(["Многострочная"]);

export function describeMetaNode(text: string, offset: number): MetaNodeDescription | undefined {
  let root: unknown;
  try {
    root = parseDocument(text, { uniqueKeys: false }).contents ?? undefined;
  } catch {
    return undefined;
  }
  const map = findMapAt(root, offset);
  if (!map) {
    return undefined;
  }
  const title = prop(map, "ВидЭлемента") ?? prop(map, "Имя") ?? "?";
  // String-specific properties are shown only for the Строка type (a standard attribute has no
  // Тип - it is a string by default).
  const fieldType = prop(map, "Тип");
  const isStringField = fieldType === undefined || fieldType === "Строка" || fieldType === "Строка?";
  const rows: MetaPropRow[] = [];
  const collections: Record<string, number> = {};
  for (const item of map.items) {
    const key = isScalar(item.key) ? String(item.key.value) : "";
    if (!key) {
      continue;
    }
    if (STRING_ONLY_KEYS.has(key) && !isStringField) {
      continue; // e.g. Многострочная is not shown for a non-string type
    }
    // Scalar properties only; collections (Реквизиты, Интерфейс ...) are edited via the tree -
    // but their presence and size are recorded, or the schema section reads them as unset.
    if (!(isScalar(item.value) || item.value === null || item.value === undefined)) {
      if (isSeq(item.value) || isMap(item.value)) {
        collections[key] = (item.value as { items: unknown[] }).items.length;
      }
      continue;
    }
    const value = scalarStr(item.value) ?? "";
    const readonly = READONLY_KEYS.has(key);
    const options = readonly ? undefined : metaOptionsFor(key);
    const control: MetaPropRow["control"] = readonly
      ? "text"
      : TYPE_KEYS.has(key)
        ? "combo"
        : value === "Истина" || value === "Ложь"
          ? "tristate"
          : options
            ? "select"
            : "text";
    rows.push({
      key,
      value,
      control,
      options: options && value && !options.includes(value) ? [value, ...options] : options,
      readonly: readonly || undefined,
    });
  }
  return {
    title,
    offset: map.range ? map.range[0] : offset,
    rows,
    collections: Object.keys(collections).length > 0 ? collections : undefined,
  };
}

// -- standard attributes --------------------------------------------------------------------
//
// Standard (platform-predefined) attributes per kind: always shown in the tree, even when absent
// from yaml. The set of editable scalar properties is confirmed against project data (Наименование:
// Длина/Многострочная; Код: Тип/Длина/Уникальность; nested Автонумерация - edited directly in yaml).
// An empty (synthetic) property materializes on edit: a record { Имя: <standard name>,
// <key>: <value> } is appended to Реквизиты (without Ид - like a standard attribute).

export interface StandardAttrSpec {
  name: string;
  rows: Array<{ key: string; control: MetaPropRow["control"]; options?: string[] }>;
}

const SEL_STR_NUM = ["Строка", "Число"];

export const STANDARD_ATTRS: Record<string, StandardAttrSpec[]> = {
  Справочник: [
    { name: "Наименование", rows: [{ key: "Длина", control: "text" }, { key: "Многострочная", control: "tristate" }] },
    {
      name: "Код",
      rows: [
        { key: "Тип", control: "select", options: SEL_STR_NUM },
        { key: "Длина", control: "text" },
        { key: "Уникальность", control: "tristate" },
      ],
    },
  ],
  Документ: [
    {
      name: "Номер",
      rows: [
        { key: "Тип", control: "select", options: SEL_STR_NUM },
        { key: "Длина", control: "text" },
        { key: "Уникальность", control: "tristate" },
      ],
    },
    { name: "Дата", rows: [{ key: "Тип", control: "select", options: ["Дата", "ДатаВремя", "Время"] }] },
  ],
};

// Standard attribute names of a kind (for the tree).
export function standardAttrNames(kind: string): string[] {
  return (STANDARD_ATTRS[kind] ?? []).map((s) => s.name);
}

// Offset of the attribute record by Имя in the Реквизиты section (a materialized standard
// attribute), otherwise undefined (default values, absent from yaml).
export function findAttrOffset(text: string, name: string): number | undefined {
  return parseInternals(text)?.attributes.find((a) => a.name === name)?.offset;
}

// Attribute names offered for an AttributeName-typed schema property (the Представление of a
// catalog or a document names its presentation FIELD - an existing string attribute). Offered:
// a declared Строка (nullable included) and a record without Тип - the standard Наименование
// has no Тип at all and Код defaults to a string; an explicitly non-string attribute is not.
// A hint, not validation - the yaml/presentation-field rule stays the judge.
export function stringAttributeNames(text: string): string[] {
  const attrs = parseInternals(text)?.attributes ?? [];
  return attrs.filter((a) => !a.type || /^Строка\s*\??$/.test(a.type)).map((a) => a.name);
}

// Standard attribute description for the panel: materialized (present in Реквизиты) - like a
// regular node; otherwise synthetic rows from the spec (empty values; editing materializes it).
export function describeStandardAttr(text: string, kind: string, name: string): MetaNodeDescription | undefined {
  const spec = (STANDARD_ATTRS[kind] ?? []).find((s) => s.name === name);
  if (!spec) {
    return undefined;
  }
  const offset = findAttrOffset(text, name);
  if (offset !== undefined) {
    return describeMetaNode(text, offset);
  }
  return {
    title: name,
    offset: -1, // synthetic - no node in yaml
    rows: spec.rows.map((r) => ({ key: r.key, value: "", control: r.control, options: r.options })),
  };
}

// -- insertion of a new section item --------------------------------------------------------
//
// Templates of new objects/subsystems and tree insertions live in the engine (xbsl.scaffold) -
// the tree calls it via LSP/CLI (engineMeta.ts). Only the targeted insertion for the properties
// panel is left here: materialization of a standard attribute is applied to the open buffer
// locally.

function lineEndOf(text: string, offset: number): number {
  const nl = text.indexOf("\n", offset);
  return nl === -1 ? text.length : nl;
}

// Section item indentation from the first existing "-" in the body; otherwise from the header indent.
function detectIndent(bodySlice: string, headerIndentLen: number): { item: string; field: string } {
  const m = /^([ \t]*)-[ \t]*\r?\n([ \t]*)\S/m.exec(bodySlice);
  if (m) {
    return { item: m[1], field: m[2] };
  }
  return { item: " ".repeat(headerIndentLen + 4), field: " ".repeat(headerIndentLen + 8) };
}

// -- localization section -----------------------------------------------------------------

// Translations of a LocalizedStrings element live in a separate project section rather than
// inside the element: <where the element lies>/Localization/<language>/<Name>.yaml, one file per
// language of LocalizationLanguages. Such a file carries the string sections alone, without
// ElementKind - so the tree, which collects elements by that key, never saw the translations and
// there was no way to open a translated text from the tree at all.
export interface TranslationRef {
  ownerPath: string; // the yaml of the element being translated
  lang: string; // the language folder as the platform wrote it (En)
}

// Both spellings of the section folder - a project written in English is legal code.
const LOCALIZATION_DIRS = new Set(["локализация", "localization"]);

// The element a translation file belongs to, or undefined when the path is not a translation.
// The tail after the language folder is kept as is: the section repeats the package nesting of
// the element it translates. The caller confirms the guess - a translation counts as one only
// when the owner it points at exists and is a LocalizedStrings element.
export function translationRef(yamlPath: string): TranslationRef | undefined {
  const parts = yamlPath.split(/[\\/]/);
  // The language folder plus at least the file itself must follow the section folder; of several
  // such folders the innermost one wins - it is the section the file actually lies in.
  let section = -1;
  for (let i = parts.length - 3; i >= 0; i--) {
    if (LOCALIZATION_DIRS.has(parts[i].toLowerCase())) {
      section = i;
      break;
    }
  }
  if (section < 0) {
    return undefined;
  }
  const sep = yamlPath.includes("\\") ? "\\" : "/";
  return {
    ownerPath: [...parts.slice(0, section), ...parts.slice(section + 2)].join(sep),
    lang: parts[section + 1],
  };
}

const LINE_INDENT = /^([ \t]*)/;

// Targeted insertion of a new item (a set of field lines itemLines, e.g. ["Ид: ...","Имя: ...",
// "Тип: Строка"]) at the end of a section. Parsing is purely textual (more reliable than yaml
// ranges for block lists): the section header and indentation locate the end of its body. No
// section - append at the end of the file. Applied on top undo-safely.
export function insertItemEdit(text: string, section: string, itemLines: string[]): TextEdit {
  const body = (item: string, field: string): string =>
    `${item}-\n` + itemLines.map((l) => `${field}${l}`).join("\n");

  const header = new RegExp(`^([ \\t]*)${section}:[ \\t]*\\r?$`, "m").exec(text);
  if (!header) {
    const nl = text.length === 0 || text.endsWith("\n") ? "" : "\n";
    return { start: text.length, end: text.length, newText: `${nl}${section}:\n${body("    ", "        ")}\n` };
  }

  const headerIndentLen = header[1].length;
  const headerLineEnd = lineEndOf(text, header.index);
  let insertAt = headerLineEnd;
  let bodyEnd = headerLineEnd;
  let pos = headerLineEnd;
  while (pos < text.length) {
    const lineStart = pos + 1;
    const lineEnd = lineEndOf(text, lineStart);
    const line = text.slice(lineStart, lineEnd);
    const indentLen = LINE_INDENT.exec(line)![1].length;
    const blank = line.trim() === "";
    if (!blank && indentLen <= headerIndentLen) {
      break;
    }
    if (!blank) {
      insertAt = lineEnd;
      bodyEnd = lineEnd;
    }
    pos = lineEnd;
  }
  const { item, field } = detectIndent(text.slice(headerLineEnd, bodyEnd), headerIndentLen);
  return { start: insertAt, end: insertAt, newText: `\n${body(item, field)}` };
}
