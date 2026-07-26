// Pure "component type -> codicon id" mapping shared by the component palette and the
// form structure view (no vscode import - unit-tested under plain Node,
// test/componentIconsCore.test.ts; the ThemeIcon wrapper lives in componentIcons.ts).
// One type MUST render with one icon in both panels, so neither panel hardcodes icon
// choices - both call iconIdFor with the same inputs: the type name, the ui-schema
// package (when known) and the schema-backed container flag.
//
// Resolution order, all data-driven:
//   1. exact type names (КруговаяДиаграмма beats the *Диаграмма* family);
//   2. name families in table order, camel-boundary aware ("Форма*" matches ФормаВыбора
//      but not Форматирование);
//   3. the last segment of the ui-schema package (Диаграммы, Списки, Файлы, ...);
//   4. containers flagged by the ui schema fall back to the layout icon;
//   5. everything else - the generic symbol-misc.
// Every icon id below is a real codicon name (see the known-names test) - an unknown id
// would silently render as nothing in a TreeItem.

import { packageSegment } from "./formPaletteCore";

export const GENERIC_COMPONENT_ICON = "symbol-misc";

//: The icon of a container type that has no mapping of its own (step 4).
export const CONTAINER_FALLBACK_ICON = "layout";

// Exact type names. Kept ahead of the families: the specific diagram kinds, the group
// flavors and the file components would otherwise be swallowed by their families.
const EXACT_ICONS: Readonly<Record<string, string>> = {
  // groups and layout containers
  СтековаяГруппа: "layers",
  РазделяющаяГруппа: "split-horizontal",
  СтандартнаяКарточка: "layout",
  Страницы: "browser",
  ПроизвольныйШаблонФормы: "editor-layout",
  // diagrams: every catalog kind gets a glyph of its own shape (no gantt codicon
  // exists - "project" draws the closest thing, offset horizontal bars)
  КруговаяДиаграмма: "pie-chart",
  ДиаграммаГанта: "project",
  ВоронкообразнаяДиаграмма: "filter",
  ДиаграммаСпидометр: "dashboard",
  ЛепестковаяДиаграмма: "target",
  XYДиаграмма: "graph-scatter",
  // actions
  Кнопка: "inspect",
  Гиперссылка: "link",
  // text and input
  Надпись: "symbol-string",
  ПолеВвода: "symbol-field",
  ВыборЗначения: "symbol-field",
  ВыборДатыВремени: "calendar",
  Флажок: "check",
  Переключатель: "circle-filled",
  // media
  Картинка: "file-media",
  Видео: "device-camera-video",
  // data views
  Дерево: "list-tree",
  ГрафическаяСхема: "type-hierarchy",
  // embedded html
  КонтейнерHtml: "code",
  Вставка: "code",
  // commands
  ПанельКоманд: "tools",
  Команды: "tools",
  // files
  СписокФайлов: "files",
  ВыборФайлов: "files",
};

interface FamilyRule {
  match: "prefix" | "suffix" | "includes";
  needle: string;
  icon: string;
}

// Name families, first match wins. The needles are capitalized words, so inside a camel
// case identifier an occurrence always STARTS a word; only the right boundary is checked.
const FAMILY_ICONS: readonly FamilyRule[] = [
  { match: "includes", needle: "Диаграмма", icon: "graph" },
  { match: "includes", needle: "Группа", icon: "layout" },
  { match: "prefix", needle: "Форма", icon: "window" },
  { match: "prefix", needle: "Таблица", icon: "table" },
  { match: "includes", needle: "Список", icon: "list-flat" },
  { match: "suffix", needle: "Меню", icon: "menu" },
];

// The last package segment decides for types without a name match (Аккордеон in
// Стд::Интерфейс::Списки renders as a list).
const PACKAGE_ICONS: Readonly<Record<string, string>> = {
  Диаграммы: "graph",
  Списки: "list-flat",
  Файлы: "file",
  Формы: "window",
  Команды: "tools",
};

// Whether the character after a matched needle closes a camel word: end of string or
// anything but a lowercase letter (Форма|Выбора yes, Форма|тирование no).
function closesWord(type: string, end: number): boolean {
  const after = type.charAt(end);
  return after === "" || !/[a-zа-яё]/.test(after);
}

function familyMatches(type: string, rule: FamilyRule): boolean {
  if (rule.match === "prefix") {
    return type.startsWith(rule.needle) && closesWord(type, rule.needle.length);
  }
  if (rule.match === "suffix") {
    return type.endsWith(rule.needle);
  }
  let at = type.indexOf(rule.needle);
  while (at >= 0) {
    if (closesWord(type, at + rule.needle.length)) {
      return true;
    }
    at = type.indexOf(rule.needle, at + 1);
  }
  return false;
}

// The codicon id of a component type. packageName - the ui-schema package when known
// (the palette has it in the catalog, the structure view resolves it through the cached
// catalog); container - the schema-backed container flag, used only as the last fallback
// before the generic icon so unmapped containers still read as layout.
export function iconIdFor(type: string, packageName?: string, container?: boolean): string {
  const exact = EXACT_ICONS[type];
  if (exact) {
    return exact;
  }
  for (const rule of FAMILY_ICONS) {
    if (familyMatches(type, rule)) {
      return rule.icon;
    }
  }
  const byPackage = PACKAGE_ICONS[packageSegment(packageName)];
  if (byPackage) {
    return byPackage;
  }
  return container ? CONTAINER_FALLBACK_ICON : GENERIC_COMPONENT_ICON;
}

// Every codicon id this mapping can produce - the known-names test guards each of them
// against the real codicon list (a typo would silently render an empty icon).
export function usedIconIds(): string[] {
  const ids = new Set<string>([GENERIC_COMPONENT_ICON, CONTAINER_FALLBACK_ICON]);
  for (const icon of Object.values(EXACT_ICONS)) {
    ids.add(icon);
  }
  for (const rule of FAMILY_ICONS) {
    ids.add(rule.icon);
  }
  for (const icon of Object.values(PACKAGE_ICONS)) {
    ids.add(icon);
  }
  return [...ids].sort();
}
