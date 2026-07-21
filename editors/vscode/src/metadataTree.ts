// Metadata tree of a 1C:Element project (own icon on the Activity Bar): the root is the project
// (right click opens the application module Проект.xbsl), elements under it are grouped by kind
// (ВидЭлемента) - catalogs, common modules, registers and so on. Objects expand into subtrees:
// Реквизиты / Измерения / Ресурсы / Табличные части / Формы; a field can be added into
// attributes/dimensions/resources. Click: common module -> xbsl, form -> preview, object -> description.
// Object/list forms are nested under their owner, ownerless forms go to the "Common forms" section.
//
// Icons are codicons (native to VS Code). The target set for replacing them with our own SVG
// (Material Symbols, Rounded, Apache-2.0) is described in the extension README. Parsing and field
// insertion are pure metadataCore.

import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { applyScaffold, callMeta, ensureSavedForCli, ScaffoldResult } from "./engineMeta";
import { lspActive, lspRequest } from "./lspClient";
import { docsCommandUri } from "./hoverDocs";
import {
  MetaField,
  MetaInternals,
  parseInternals,
  standardAttrNames,
} from "./metadataCore";
import { updatePropsFromSelection } from "./formProps";

// Element kind -> tree group + codicon. Several kinds may share one group. The group name is an
// English key: it both groups and serves as the l10n key (in the English UI the bundle is not loaded
// and the key itself is shown; the ru translation lives in bundle.l10n.ru.json). Labels of the lower
// subtrees - see ADD_SPECS.
const KIND_ROWS: ReadonlyArray<readonly [kind: string, group: string, icon: string]> = [
  ["Справочник", "Catalogs", "book"],
  ["Документ", "Documents", "note"],
  ["Перечисление", "Enumerations", "symbol-enum"],
  ["Структура", "Structures", "symbol-structure"],
  ["ХранимаяСтруктура", "Stored structures", "database"],
  ["НаборКонстант", "Constant sets", "symbol-constant"],
  ["РегистрСведений", "Information registers", "table"],
  ["РегистрНакопления", "Accumulation registers", "graph"],
  ["ВиртуальнаяТаблица", "Virtual tables", "list-flat"],
  ["ОбщийМодуль", "Common modules", "file-code"],
  ["HttpСервис", "HTTP services", "globe"],
  ["SoapСервис", "SOAP services", "server"],
  ["КлиентSoapСервиса", "SOAP services", "server"],
  ["КонтрактСервиса", "Contracts", "symbol-interface"],
  ["КонтрактТипа", "Contracts", "symbol-interface"],
  ["КонтрактСущности", "Contracts", "symbol-interface"],
  ["ГлобальноеКлиентскоеСобытие", "Client events", "zap"],
  ["СобытиеЖурналаСобытий", "Event-log events", "history"],
  ["ЗапланированноеЗадание", "Scheduled jobs", "calendar"],
  ["Обработка", "Data processors", "tools"],
  ["Отчет", "Reports", "graph-line"],
  ["ПанельОтчетов", "Report panels", "dashboard"],
  ["ЦветоваяСхемаОтчета", "Color schemes", "symbol-color"],
  ["ФрагментКомандногоИнтерфейса", "Command-interface fragments", "menu"],
  ["ОбычнаяКоманда", "Commands", "symbol-event"],
  ["НавигационнаяКоманда", "Commands", "symbol-event"],
  ["ПереключаемаяКоманда", "Commands", "symbol-event"],
  ["КомандаСКомпонентом", "Commands", "symbol-event"],
  ["ПланОбмена", "Exchange plans", "sync"],
  ["КлючДоступа", "Access keys", "key"],
  ["ПравоНаДействие", "Rights", "shield"],
  ["ПравоНаЭлемент", "Rights", "shield"],
  ["ХранилищеНастроек", "Settings storages", "settings-gear"],
  ["ПараметрыРаботыКлиента", "Client-work parameters", "settings"],
  ["ПараметрСамостоятельнойРегистрацииПользователя", "Registration parameters", "person-add"],
  ["ЛокализованныеСтроки", "Localized strings", "symbol-string"],
  ["Проект", "Project", "project"],
  ["Подсистема", "Subsystems", "folder-library"],
];

interface KindMeta {
  group: string;
  icon: string;
  order: number;
}

const KIND_META = new Map<string, KindMeta>();
KIND_ROWS.forEach(([kind, group, icon], i) => KIND_META.set(kind, { group, icon, order: i }));

// The platform type that best documents each category (the first kind mapped to the group) -
// the metadata-tree category tooltip resolves its docs page by this name (xbsl/docsByName).
const GROUP_PRIMARY_KIND = new Map<string, string>();
KIND_ROWS.forEach(([kind, group]) => {
  if (!GROUP_PRIMARY_KIND.has(group)) {
    GROUP_PRIMARY_KIND.set(group, kind);
  }
});

// A tree icon in the neutral tree-foreground color. The symbol-* codicons (symbol-enum,
// symbol-interface, ...) otherwise render in their own semantic colors, so enumerations and
// contracts stand out from the rest; forcing icon.foreground keeps every category one color.
function neutralIcon(id: string): vscode.ThemeIcon {
  return new vscode.ThemeIcon(id, new vscode.ThemeColor("icon.foreground"));
}

// Every standard metadata category, shown even when empty (the 1C:Element convention: the tree
// structure is the same regardless of content). Distinct groups from KIND_ROWS with their icon and
// order; the structural groups (the project root and the subsystems branch) are not object
// categories and are excluded. Multiple kinds may map to one group - the first wins.
const ALL_CATEGORY_GROUPS: ReadonlyArray<{ group: string; icon: string; order: number }> = (() => {
  const seen = new Map<string, { group: string; icon: string; order: number }>();
  KIND_ROWS.forEach(([, group, icon], i) => {
    if (group === "Project" || group === "Subsystems") {
      return;
    }
    if (!seen.has(group)) {
      seen.set(group, { group, icon, order: i });
    }
  });
  return [...seen.values()];
})();

const FORM_KIND = "КомпонентИнтерфейса";
// English label keys (see the comment at KIND_ROWS): displayed via l10n.t.
const OTHER_GROUP = "Other";
const COMMON_FORMS_GROUP = "Common forms";
const COMMON_FORMS_ORDER = 8000;
const OTHER_ORDER = 9000;

// Appendable group: yaml section (Russian key, not translated), caption (English l10n key),
// icon, menu token. Line templates for a new element live in the engine (xbsl.scaffold);
// fieldKind is the element kind name in its vocabulary.
interface AddSpec {
  section: string;
  fieldKind: string;
  label: string; // English l10n key of the subtree label (shown via l10n.t)
  icon: string;
  token: string;
  defaultName: string;
  noun: string; // l10n key (genitive case): "attribute" -> "реквизита"
}

const ADD_SPECS: Record<string, AddSpec> = {
  attr: { section: "Реквизиты", fieldKind: "реквизит", label: "Attributes", icon: "symbol-field", token: "addattr", defaultName: "НовыйРеквизит", noun: "attribute" },
  dim: { section: "Измерения", fieldKind: "измерение", label: "Dimensions", icon: "key", token: "adddim", defaultName: "НовоеИзмерение", noun: "dimension" },
  res: { section: "Ресурсы", fieldKind: "ресурс", label: "Resources", icon: "symbol-numeric", token: "addres", defaultName: "НовыйРесурс", noun: "resource" },
  enum: { section: "Элементы", fieldKind: "значение", label: "Values", icon: "symbol-enum", token: "addval", defaultName: "НовоеЗначение", noun: "enum value" },
  param: { section: "Параметры", fieldKind: "параметр", label: "Parameters", icon: "settings", token: "addparam", defaultName: "НовыйПараметр", noun: "parameter" },
  structfield: { section: "Поля", fieldKind: "поле", label: "Fields", icon: "symbol-field", token: "addstructfield", defaultName: "НовоеПоле", noun: "field" },
  tabular: { section: "ТабличныеЧасти", fieldKind: "табличная-часть", label: "Tabular sections", icon: "table", token: "addtabular", defaultName: "НоваяТабличнаяЧасть", noun: "tabular section" },
};

// Kind -> its appendable groups (order = group order).
const KIND_ADD_GROUPS: Record<string, string[]> = {
  Справочник: ["attr", "tabular"],
  Документ: ["attr", "tabular"],
  РегистрСведений: ["dim", "res", "attr"],
  РегистрНакопления: ["dim", "res", "attr"],
  Перечисление: ["enum"],
  ПараметрыРаботыКлиента: ["param"],
  Структура: ["structfield"],
};

// Section -> its fields from the parsed structure.
const SECTION_FIELDS: Record<string, (it: MetaInternals) => MetaField[]> = {
  Реквизиты: (it) => it.attributes,
  Измерения: (it) => it.dimensions,
  Ресурсы: (it) => it.resources,
  Элементы: (it) => it.enumValues,
  Параметры: (it) => it.clientParams,
  Поля: (it) => it.structFields,
  ТабличныеЧасти: (it) => it.tabulars,
};

// Kinds whose primary artifact is code: click opens the xbsl, not the description.
const CODE_KINDS = new Set(["ОбщийМодуль", "HttpСервис", "SoapСервис", "КлиентSoapСервиса"]);

// Candidates for the Тип field in the properties panel: primitives + object references +
// enumerations. A reference comes from catalogs and documents (<Имя>.Ссылка?), an enumeration -
// <Имя>? (usually requires nullable). The list is open: the panel shows it as datalist hints,
// but any type can be entered.
const PRIMITIVE_TYPES = ["Строка", "Число", "Булево", "Дата", "ДатаВремя", "УникальныйИдентификатор"];
const REF_KINDS = new Set(["Справочник", "Документ"]);

// Kinds creatable from the tree: the category is always shown (even empty), with "add object"
// at its root. Templates (extra lines, the paired module) are known to the engine (xbsl.scaffold);
// here is only the list for the menu. A form goes to the "Common forms" pseudo-category, not its own.
const NEW_OBJECT_KINDS = [
  "Справочник",
  "Документ",
  "Перечисление",
  "Структура",
  "РегистрСведений",
  "РегистрНакопления",
  "ПараметрыРаботыКлиента",
  "ОбщийМодуль",
  "HttpСервис",
  "ГлобальноеКлиентскоеСобытие",
  "ФрагментКомандногоИнтерфейса",
  FORM_KIND, // common form (without an owner)
];
const CREATABLE_KINDS = NEW_OBJECT_KINDS.filter((k) => k !== FORM_KIND);

// Latin slug of a kind - for the id of the per-kind "Add <class>" command and the menu token.
const CREATABLE_SLUG: Record<string, string> = {
  Справочник: "catalog",
  Документ: "document",
  Перечисление: "enumeration",
  Структура: "structure",
  РегистрСведений: "inforegister",
  РегистрНакопления: "accumregister",
  ПараметрыРаботыКлиента: "clientparams",
  ОбщийМодуль: "commonmodule",
  HttpСервис: "httpservice",
  ГлобальноеКлиентскоеСобытие: "clientevent",
  ФрагментКомандногоИнтерфейса: "cmdfragment",
  КомпонентИнтерфейса: "commonform",
};

// A meaningful default name (otherwise "Новый" + kind yields the clumsy "НовыйКомпонентИнтерфейса").
const NEW_OBJECT_DEFAULT: Record<string, string> = {
  КомпонентИнтерфейса: "НоваяФорма",
  Структура: "НоваяСтруктура",
  ГлобальноеКлиентскоеСобытие: "НовоеСобытие",
  ФрагментКомандногоИнтерфейса: "НовыйФрагмент",
};

function metaFor(kind: string): KindMeta {
  return KIND_META.get(kind) ?? { group: OTHER_GROUP, icon: "symbol-misc", order: OTHER_ORDER };
}

function formIcon(name: string): string {
  if (name.endsWith("ФормаСписка")) {
    return "list-flat";
  }
  if (name.endsWith("ФормаОтчета")) {
    return "graph-line";
  }
  return "window";
}

interface Element {
  kind: string;
  name: string;
  yamlPath: string;
  modulePath?: string;
  objectModulePath?: string;
  ownerType?: string;
  text: string;
}

interface Project {
  name: string;
  vendor?: string; // Поставщик
  dir: string;
  appModulePath?: string; // Проект.xbsl
}

// Subsystem = a folder with Подсистема.yaml (name = the folder name; element membership is by folder).
interface Subsystem {
  name: string;
  dir: string;
}

// --- source parsing ---------------------------------------------------------------------

const RE_KIND = /^ВидЭлемента:\s*(\S+)/m;
const RE_NAME = /^Имя:\s*(\S+)/m;
const RE_VENDOR = /^Поставщик:\s*(\S+)/m;
const RE_OWNER_TYPE = /(?:^|\n)\s*Тип:\s*Форма\w*<([^>]+)>/;
const RE_DECLARED_FORM = /^\s*Форма:\s*(\S+)/gm;

async function collectFiles(root: string, ext: string): Promise<string[]> {
  const pattern = new vscode.RelativePattern(vscode.Uri.file(root), `**/*.${ext}`);
  const uris = await vscode.workspace.findFiles(pattern, "**/node_modules/**");
  return uris.map((u) => u.fsPath);
}

interface Model {
  elements: Element[];
  projects: Project[];
  subsystems: Subsystem[];
}

async function parseModel(projectRootFor: (folder: vscode.WorkspaceFolder) => string): Promise<Model> {
  const yamlPaths: string[] = [];
  const xbslPaths: string[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const root = projectRootFor(folder);
    const [y, x] = await Promise.all([collectFiles(root, "yaml"), collectFiles(root, "xbsl")]);
    yamlPaths.push(...y);
    xbslPaths.push(...x);
  }
  const xbslSet = new Set(xbslPaths.map((p) => p.toLowerCase()));
  const seen = new Set<string>();
  const elements: Element[] = [];
  const projects: Project[] = [];
  const subsystems: Subsystem[] = [];
  for (const yamlPath of yamlPaths) {
    const key = yamlPath.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    // Подсистема.yaml - a subsystem folder (the name is not parsed, it = the folder name).
    if (path.basename(yamlPath) === "Подсистема.yaml") {
      const dir = path.dirname(yamlPath);
      subsystems.push({ name: path.basename(dir), dir });
      continue;
    }
    let text: string;
    try {
      const raw = await fs.promises.readFile(yamlPath, "utf8");
      text = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
    } catch {
      continue;
    }
    // Проект.yaml - has no ВидЭлемента: a separate tree root.
    if (path.basename(yamlPath) === "Проект.yaml") {
      const dir = path.dirname(yamlPath);
      const appModule = path.join(dir, "Проект.xbsl");
      projects.push({
        name: RE_NAME.exec(text)?.[1] ?? path.basename(dir),
        vendor: RE_VENDOR.exec(text)?.[1],
        dir,
        appModulePath: xbslSet.has(appModule.toLowerCase()) ? appModule : undefined,
      });
      continue;
    }
    const kind = RE_KIND.exec(text)?.[1];
    if (!kind) {
      continue;
    }
    const name = RE_NAME.exec(text)?.[1] ?? path.basename(yamlPath, ".yaml");
    const base = yamlPath.slice(0, -".yaml".length);
    const modulePath = base + ".xbsl";
    const objectModulePath = base + ".Объект.xbsl";
    elements.push({
      kind,
      name,
      yamlPath,
      modulePath: xbslSet.has(modulePath.toLowerCase()) ? modulePath : undefined,
      objectModulePath: xbslSet.has(objectModulePath.toLowerCase()) ? objectModulePath : undefined,
      ownerType: kind === FORM_KIND ? RE_OWNER_TYPE.exec(text)?.[1]?.split(".")[0] : undefined,
      text,
    });
  }
  return { elements, projects, subsystems };
}

// --- tree node --------------------------------------------------------------------------

class XbslNode extends vscode.TreeItem {
  children?: XbslNode[];
  parent?: XbslNode; // parent - for getParent (required by TreeView.reveal)
  yamlPath?: string;
  modulePath?: string;
  objectModulePath?: string;
  appModulePath?: string;
  offset?: number; // node offset in the yaml - for navigation
  addKind?: string; // group: the ADD_SPECS key for "add"
  newObjectKind?: string; // category: the kind of the object being created
  ownerName?: string; // "Forms" group: the owner object (for adding a form)
  codeKind?: boolean; // code kind (module/HTTP service): click opens the module on the left
  stdKind?: string; // standard attribute: the object kind (Справочник/Документ)
  stdName?: string; // standard attribute: the name (Наименование/Код/Номер/Дата)
  docsKind?: string; // category: the platform type whose docs page describes it (tooltip)
}

// Set parent links across the whole built tree (for reveal), and give every node a STABLE, unique
// TreeItem.id. Without an id VS Code identifies a node by its label, which is recreated on each
// rebuild, so the expanded/collapsed state is lost on every refresh and window reload; a stable id
// (the path of parent ids plus the node's own key) lets VS Code preserve the tree's open state.
function setParents(nodes: XbslNode[], parent?: XbslNode): void {
  const seen = new Map<string, number>();
  for (const node of nodes) {
    node.parent = parent;
    const label = typeof node.label === "string" ? node.label : node.label?.label ?? "";
    let key = node.yamlPath ?? node.modulePath ?? label ?? "";
    const nth = (seen.get(key) ?? 0) + 1;
    seen.set(key, nth);
    if (nth > 1) {
      key += "#" + nth; // disambiguate the rare same-key siblings
    }
    node.id = (parent?.id ? parent.id + "/" : "") + key;
    if (node.children) {
      setParents(node.children, node);
    }
  }
}

// The first tree node satisfying the predicate (depth-first traversal, including nested fields).
function findNode(nodes: XbslNode[], pred: (n: XbslNode) => boolean): XbslNode | undefined {
  for (const node of nodes) {
    if (pred(node)) {
      return node;
    }
    if (node.children) {
      const found = findNode(node.children, pred);
      if (found) {
        return found;
      }
    }
  }
  return undefined;
}

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, "ru");

function subsystemNode(sub: Subsystem): XbslNode {
  const node = new XbslNode(sub.name, vscode.TreeItemCollapsibleState.None);
  node.iconPath = new vscode.ThemeIcon("symbol-namespace");
  node.yamlPath = path.join(sub.dir, "Подсистема.yaml");
  node.resourceUri = vscode.Uri.file(node.yamlPath); // for git statuses (color/badge), keeping our own icon
  node.contextValue = "subsystem yaml";
  node.command = { command: "xbsl.metadata.openYaml", title: "", arguments: [node] };
  return node;
}

function subsystemsBranchNode(subsystems: Subsystem[]): XbslNode {
  const node = new XbslNode(
    vscode.l10n.t("Subsystems"),
    subsystems.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("folder-library");
  node.description = String(subsystems.length);
  node.contextValue = "subsystems";
  node.children = [...subsystems].sort(byName).map(subsystemNode);
  return node;
}

// Subsystem node in the "By subsystems" mode: collapsible, carries nested subsystems and its own
// objects (by classes). Подсистема.yaml is opened via the context menu (a click expands the node).
function subsystemGroupNode(sub: Subsystem, children: XbslNode[]): XbslNode {
  const node = new XbslNode(
    sub.name,
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("symbol-namespace");
  node.yamlPath = path.join(sub.dir, "Подсистема.yaml");
  node.resourceUri = vscode.Uri.file(node.yamlPath); // git statuses
  node.contextValue = "subsystem yaml addsub";
  node.children = children;
  return node;
}

// Project children in the "By subsystems" mode: the subsystem tree (by folder nesting), under each -
// its objects by classes; objects outside subsystems - as categories at the project root. Membership
// is by folder: an object belongs to the DEEPEST subsystem whose folder is a prefix of its path.
function subsystemModeChildren(subsystems: Subsystem[], elements: Element[]): XbslNode[] {
  const under = (child: string, dir: string): boolean => child.toLowerCase().startsWith(dir.toLowerCase() + path.sep);
  const deepest = (p: string, among: Subsystem[]): Subsystem | undefined => {
    let best: Subsystem | undefined;
    let bestLen = -1;
    for (const s of among) {
      if (under(p, s.dir) && s.dir.length > bestLen) {
        best = s;
        bestLen = s.dir.length;
      }
    }
    return best;
  };
  const elemsBySub = new Map<string, Element[]>();
  const rootElems: Element[] = [];
  for (const el of elements) {
    const s = deepest(el.yamlPath, subsystems);
    if (!s) {
      rootElems.push(el);
      continue;
    }
    const list = elemsBySub.get(s.dir);
    if (list) {
      list.push(el);
    } else {
      elemsBySub.set(s.dir, [el]);
    }
  }
  const childSubs = new Map<string, Subsystem[]>();
  const topSubs: Subsystem[] = [];
  for (const s of subsystems) {
    const parent = deepest(
      s.dir,
      subsystems.filter((o) => o.dir !== s.dir)
    );
    if (!parent) {
      topSubs.push(s);
      continue;
    }
    const list = childSubs.get(parent.dir);
    if (list) {
      list.push(s);
    } else {
      childSubs.set(parent.dir, [s]);
    }
  }
  const buildSub = (s: Subsystem): XbslNode =>
    subsystemGroupNode(s, [
      ...(childSubs.get(s.dir) ?? []).sort(byName).map(buildSub),
      ...categoriesOf(elemsBySub.get(s.dir) ?? [], false, false),
    ]);
  return [...topSubs.sort(byName).map(buildSub), ...categoriesOf(rootElems, false, false)];
}

function projectNode(project: Project, children: XbslNode[], filterNames: string[]): XbslNode {
  const node = new XbslNode(project.name, vscode.TreeItemCollapsibleState.Expanded);
  node.iconPath = new vscode.ThemeIcon("project");
  node.resourceUri = vscode.Uri.file(path.join(project.dir, "Проект.yaml")); // git statuses
  // Grayed out next to the name - Поставщик\Имя from Проект.yaml; a filter appends its list.
  const base = project.vendor ? `${project.vendor}\\${project.name}` : "";
  node.description = filterNames.length
    ? `${base} • ${vscode.l10n.t("filter")}: ${filterNames.join(", ")}`.trim()
    : base || undefined;
  node.contextValue = ["project", project.appModulePath ? "appmod" : "", filterNames.length ? "filtered" : ""]
    .filter(Boolean)
    .join(" ");
  node.appModulePath = project.appModulePath;
  node.children = children;
  node.tooltip = vscode.l10n.t("Project");
  return node;
}

function categoryNode(group: string, icon: string, children: XbslNode[], createKind?: string): XbslNode {
  // group is an English key (also the grouping key); we display the translation, the key stays.
  const node = new XbslNode(
    vscode.l10n.t(group),
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = neutralIcon(icon);
  node.description = String(children.length);
  node.newObjectKind = createKind;
  node.docsKind = GROUP_PRIMARY_KIND.get(group); // the tooltip resolves its docs page lazily

  // The newobj-<slug> token enables the right per-kind "Add <class>" command.
  node.contextValue = ["xbslCategory", createKind ? `newobj-${CREATABLE_SLUG[createKind]}` : ""]
    .filter(Boolean)
    .join(" ");
  node.children = children;
  return node;
}

function fieldNode(field: MetaField, yamlPath: string, icon: string): XbslNode {
  const kids = field.children?.map((c) => fieldNode(c, yamlPath, "symbol-field"));
  const node = new XbslNode(
    field.name,
    kids && kids.length
      ? vscode.TreeItemCollapsibleState.Collapsed
      : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon(icon);
  node.description = field.type;
  node.yamlPath = yamlPath;
  node.offset = field.offset;
  node.children = kids;
  node.contextValue = "member field props";
  // Click: the description on the left (cursor on the field), the properties panel - on the right.
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  return node;
}

// Tabular section node: like a field, but with the "+ add attribute" action (the addtcattr marker).
function tabularNode(tc: MetaField, yamlPath: string): XbslNode {
  const node = fieldNode(tc, yamlPath, "table");
  node.contextValue = "member field props addtcattr";
  return node;
}

// Standard attribute node (Наименование/Код/Номер/Дата): materialized (present in Реквизиты) - with
// the record offset, otherwise synthetic (default values, grayed "(default)"). Click opens the
// description on the left + the properties panel on the right; editing a synthetic one materializes
// the record in the yaml.
function standardAttrNode(kind: string, name: string, yamlPath: string, internals?: MetaInternals): XbslNode {
  const offset = internals?.attributes.find((a) => a.name === name)?.offset;
  const node = new XbslNode(name, vscode.TreeItemCollapsibleState.None);
  node.iconPath = new vscode.ThemeIcon("symbol-field");
  node.yamlPath = yamlPath;
  node.offset = offset; // undefined - synthetic
  node.stdKind = kind;
  node.stdName = name;
  node.description = offset === undefined ? vscode.l10n.t("(default)") : undefined;
  node.contextValue = ["member", "stdattr", "props", offset !== undefined ? "yaml" : ""].filter(Boolean).join(" ");
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  return node;
}

function standardAttrsGroupNode(kind: string, yamlPath: string, internals?: MetaInternals): XbslNode {
  const names = standardAttrNames(kind);
  const node = new XbslNode(vscode.l10n.t("Standard attributes"), vscode.TreeItemCollapsibleState.Collapsed);
  node.iconPath = new vscode.ThemeIcon("symbol-field");
  node.description = String(names.length);
  node.contextValue = "group";
  node.children = names.map((n) => standardAttrNode(kind, n, yamlPath, internals));
  return node;
}

function addGroupNode(addKind: string, yamlPath: string, fields: MetaField[]): XbslNode {
  const spec = ADD_SPECS[addKind];
  const node = new XbslNode(vscode.l10n.t(spec.label), vscode.TreeItemCollapsibleState.Collapsed);
  node.iconPath = new vscode.ThemeIcon(spec.icon);
  node.description = String(fields.length);
  node.yamlPath = yamlPath;
  node.addKind = addKind;
  node.contextValue = `group ${spec.token}`;
  // In the tabular group the children are sections with attribute adding; other groups - plain fields.
  node.children = fields.map((f) => (addKind === "tabular" ? tabularNode(f, yamlPath) : fieldNode(f, yamlPath, spec.icon)));
  return node;
}

// Display-only group (tabular sections, URL templates): without "add". label is an English
// l10n key.
function displayGroupNode(label: string, icon: string, yamlPath: string, fields: MetaField[]): XbslNode {
  const node = new XbslNode(vscode.l10n.t(label), vscode.TreeItemCollapsibleState.Collapsed);
  node.iconPath = new vscode.ThemeIcon(icon);
  node.description = String(fields.length);
  node.contextValue = "group";
  node.children = fields.map((f) => fieldNode(f, yamlPath, icon));
  return node;
}

function formNode(el: Element): XbslNode {
  const node = new XbslNode(el.name, vscode.TreeItemCollapsibleState.None);
  node.iconPath = new vscode.ThemeIcon(formIcon(el.name));
  node.yamlPath = el.yamlPath;
  node.resourceUri = vscode.Uri.file(el.yamlPath); // git statuses
  node.modulePath = el.modulePath;
  node.contextValue = ["member", "form", "yaml", el.modulePath ? "xbsl" : ""].filter(Boolean).join(" ");
  node.command = { command: "xbsl.metadata.previewForm", title: "", arguments: [node] };
  node.tooltip = FORM_KIND;
  return node;
}

// The "Forms" group. For a catalog/document an object form can be added (canAddForm) - then the
// group is always shown and carries the owner.
function formsGroupNode(forms: Element[], owner?: { name: string; yamlPath: string }): XbslNode {
  const node = new XbslNode(
    vscode.l10n.t("Forms"),
    forms.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("window");
  node.description = String(forms.length);
  node.children = [...forms].sort(byName).map(formNode);
  if (owner) {
    node.ownerName = owner.name;
    node.yamlPath = owner.yamlPath;
    node.contextValue = "group addform";
  } else {
    node.contextValue = "group";
  }
  return node;
}

function elementNode(el: Element, boundForms: Element[]): XbslNode {
  const groups: XbslNode[] = [];
  const internals = parseInternals(el.text);
  const stdNames = new Set(standardAttrNames(el.kind));
  if (stdNames.size) {
    groups.push(standardAttrsGroupNode(el.kind, el.yamlPath, internals));
  }
  for (const key of KIND_ADD_GROUPS[el.kind] ?? []) {
    let fields = internals ? SECTION_FIELDS[ADD_SPECS[key].section]?.(internals) ?? [] : [];
    // Standard attributes are shown in their own group - drop them from the regular Реквизиты (no duplicates).
    if (key === "attr" && stdNames.size) {
      fields = fields.filter((f) => !stdNames.has(f.name));
    }
    groups.push(addGroupNode(key, el.yamlPath, fields));
  }
  if (internals) {
    // Tabular sections of a catalog/document go through KIND_ADD_GROUPS (with adding); here are only
    // groups without adding.
    if (el.kind === "HttpСервис" && internals.urlTemplates.length) {
      groups.push(displayGroupNode("URL templates", "globe", el.yamlPath, internals.urlTemplates));
    }
  }
  const canAddForm = el.kind === "Справочник" || el.kind === "Документ";
  if (boundForms.length || canAddForm) {
    groups.push(formsGroupNode(boundForms, canAddForm ? { name: el.name, yamlPath: el.yamlPath } : undefined));
  }

  const node = new XbslNode(
    el.name,
    groups.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = neutralIcon(metaFor(el.kind).icon);
  node.yamlPath = el.yamlPath;
  node.resourceUri = vscode.Uri.file(el.yamlPath); // git statuses (color/badge), keeping our own icon
  node.modulePath = el.modulePath;
  node.objectModulePath = el.objectModulePath;
  node.offset = internals?.rootOffset; // the object root - for the properties panel
  node.children = groups;
  node.contextValue = ["element", "yaml", "props", "deletable", el.modulePath ? "xbsl" : "", el.objectModulePath ? "objmod" : ""]
    .filter(Boolean)
    .join(" ");
  node.codeKind = CODE_KINDS.has(el.kind);
  // Click: the source on the left (module for code kinds, or the description), properties - right.
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  node.tooltip = el.kind;
  return node;
}

// --- model building ---------------------------------------------------------------------

// Form-owner resolution shared by the tree grouping and the formOwnerByPath accessor (the
// "Data" panel of the form designer): the form's own Тип: Форма*<Owner...> generic, then
// the declared "Форма: <имя>" registration inside an object's Интерфейс section, then the
// name-suffix convention (<Owner>ФормаОбъекта / ФормаСписка / ФормаОтчета).
function formOwnerResolver(objects: Element[]): (form: Element) => string | undefined {
  const elementNames = new Set(objects.map((e) => e.name));

  const declaredOwner = new Map<string, string>();
  for (const obj of objects) {
    let m: RegExpExecArray | null;
    RE_DECLARED_FORM.lastIndex = 0;
    while ((m = RE_DECLARED_FORM.exec(obj.text))) {
      declaredOwner.set(m[1], obj.name);
    }
  }

  return (form: Element): string | undefined => {
    if (form.ownerType && elementNames.has(form.ownerType)) {
      return form.ownerType;
    }
    const declared = declaredOwner.get(form.name);
    if (declared) {
      return declared;
    }
    for (const suffix of ["ФормаОбъекта", "ФормаСписка", "ФормаОтчета"]) {
      if (form.name.endsWith(suffix)) {
        const owner = form.name.slice(0, -suffix.length);
        if (elementNames.has(owner)) {
          return owner;
        }
      }
    }
    return undefined;
  };
}

// Categories (by kind) for a set of elements, including the "Common forms" section. Empty creatable
// categories are shown only without a filter (showEmptyCreatable) - under a filter they are noise.
function categoriesOf(elements: Element[], showEmptyCreatable: boolean, hideEmpty: boolean): XbslNode[] {
  const forms = elements.filter((e) => e.kind === FORM_KIND);
  const objects = elements.filter((e) => e.kind !== FORM_KIND);

  const ownerOf = formOwnerResolver(objects);

  const formsByOwner = new Map<string, Element[]>();
  const commonForms: Element[] = [];
  for (const form of forms) {
    const owner = ownerOf(form);
    if (owner) {
      const list = formsByOwner.get(owner) ?? [];
      list.push(form);
      formsByOwner.set(owner, list);
    } else {
      commonForms.push(form);
    }
  }

  interface Cat {
    icon: string;
    order: number;
    elements: XbslNode[];
    createKind?: string;
  }
  const cats = new Map<string, Cat>();
  for (const obj of [...objects].sort(byName)) {
    const meta = metaFor(obj.kind);
    const node = elementNode(obj, formsByOwner.get(obj.name) ?? []);
    const cat = cats.get(meta.group) ?? { icon: meta.icon, order: meta.order, elements: [] };
    cat.elements.push(node);
    cats.set(meta.group, cat);
  }
  // Empty categories: without a filter, show every standard category even when empty (the 1C
  // convention - the tree structure stays the same regardless of content), UNLESS the user hid
  // empty categories (the toolbar toggle). Under a filter, only categories with matching objects.
  const showEmpties = showEmptyCreatable && !hideEmpty;
  if (showEmpties) {
    for (const g of ALL_CATEGORY_GROUPS) {
      if (!cats.has(g.group)) {
        cats.set(g.group, { icon: g.icon, order: g.order, elements: [] });
      }
    }
  }
  // Creatable kinds carry the "add object" action on their category (empty ones only when empties
  // are shown).
  for (const kind of CREATABLE_KINDS) {
    const meta = metaFor(kind);
    const existing = cats.get(meta.group);
    if (!existing && !showEmpties) {
      continue;
    }
    const cat = existing ?? { icon: meta.icon, order: meta.order, elements: [] };
    cat.createKind = kind;
    cats.set(meta.group, cat);
  }
  // Nothing to show at all (a fresh empty project with empties hidden): show the whole tree so the
  // panel is not blank.
  if (!cats.size && !commonForms.length && showEmptyCreatable) {
    for (const g of ALL_CATEGORY_GROUPS) {
      cats.set(g.group, { icon: g.icon, order: g.order, elements: [] });
    }
    for (const kind of CREATABLE_KINDS) {
      const meta = metaFor(kind);
      const cat = cats.get(meta.group) ?? { icon: meta.icon, order: meta.order, elements: [] };
      cat.createKind = kind;
      cats.set(meta.group, cat);
    }
  }

  const roots = [...cats.entries()].map(([group, cat]) => ({
    order: cat.order,
    node: categoryNode(group, cat.icon, cat.elements, cat.createKind),
  }));

  // Common forms are a pseudo-category; "add" creates a form without an owner. Shown when it has
  // forms, or (empty) when empties are shown.
  const commonFormNodes = [...commonForms].sort(byName).map(formNode);
  if (commonFormNodes.length || showEmpties) {
    roots.push({
      order: COMMON_FORMS_ORDER,
      node: categoryNode(COMMON_FORMS_GROUP, "window", commonFormNodes, FORM_KIND),
    });
  }

  roots.sort((a, b) => a.order - b.order || String(a.node.label).localeCompare(String(b.node.label), "ru"));
  return roots.map((r) => r.node);
}

type GroupMode = "kind" | "subsystem";

function buildRoots(model: Model, filterDirs: Set<string>, mode: GroupMode, hideEmpty: boolean): XbslNode[] {
  const filterActive = filterDirs.size > 0;
  const underFilter = (p: string): boolean =>
    [...filterDirs].some((d) => p.toLowerCase().startsWith(d.toLowerCase() + path.sep));
  const elements = filterActive ? model.elements.filter((el) => underFilter(el.yamlPath)) : model.elements;
  const showEmpty = !filterActive;

  // Project children: "By object classes" - the Subsystems branch + categories by kind;
  // "By subsystems" - the subsystem tree with the objects under it.
  const childrenOf = (elems: Element[], subs: Subsystem[]): XbslNode[] =>
    mode === "subsystem"
      ? subsystemModeChildren(subs, elems)
      : [subsystemsBranchNode(subs), ...categoriesOf(elems, showEmpty, hideEmpty)];

  if (model.projects.length === 0) {
    // No Проект.yaml found - go without a project root.
    return mode === "subsystem" ? subsystemModeChildren(model.subsystems, elements) : categoriesOf(elements, showEmpty, hideEmpty);
  }
  const projects = [...model.projects].sort(byName);
  const projectOf = (targetPath: string): Project => {
    let best = projects[0];
    let bestLen = -1;
    for (const p of projects) {
      const prefix = (p.dir + path.sep).toLowerCase();
      if (targetPath.toLowerCase().startsWith(prefix) && p.dir.length > bestLen) {
        best = p;
        bestLen = p.dir.length;
      }
    }
    return best;
  };
  const elementsByProject = new Map<Project, Element[]>();
  for (const el of elements) {
    const p = projectOf(el.yamlPath);
    const list = elementsByProject.get(p) ?? [];
    list.push(el);
    elementsByProject.set(p, list);
  }
  const subsystemsByProject = new Map<Project, Subsystem[]>();
  for (const s of model.subsystems) {
    const p = projectOf(s.dir);
    const list = subsystemsByProject.get(p) ?? [];
    list.push(s);
    subsystemsByProject.set(p, list);
  }
  const filterNamesOf = (p: Project): string[] =>
    model.subsystems.filter((s) => filterDirs.has(s.dir) && projectOf(s.dir) === p).map((s) => s.name);

  return projects.map((p) =>
    projectNode(p, childrenOf(elementsByProject.get(p) ?? [], subsystemsByProject.get(p) ?? []), filterNamesOf(p))
  );
}

// --- provider ---------------------------------------------------------------------------

class XbslMetadataProvider implements vscode.TreeDataProvider<XbslNode> {
  private readonly emitter = new vscode.EventEmitter<XbslNode | undefined | void>();
  readonly onDidChangeTreeData = this.emitter.event;
  private roots?: XbslNode[];
  private model?: Model;
  private filter = new Set<string>(); // subsystem directories of the active filter
  private groupMode: GroupMode = "kind"; // tree hierarchy: by classes or by subsystems
  private hideEmpty = false; // hide empty class categories (the toolbar toggle)
  private treeView?: vscode.TreeView<XbslNode>; // for reveal (getParent is mandatory)
  private pendingReveal?: (n: XbslNode) => boolean; // reveal this node after a rebuild

  constructor(private readonly projectRootFor: (folder: vscode.WorkspaceFolder) => string) {}

  // The tree view is created separately (access to reveal is needed); attached after creation.
  attachView(view: vscode.TreeView<XbslNode>): void {
    this.treeView = view;
  }

  refresh(): void {
    this.roots = undefined;
    this.emitter.fire(undefined);
  }

  get filterDirs(): Set<string> {
    return this.filter;
  }

  setFilter(dirs: string[]): void {
    this.filter = new Set(dirs);
    this.refresh();
  }

  get mode(): GroupMode {
    return this.groupMode;
  }

  setGroupMode(mode: GroupMode): void {
    if (this.groupMode === mode) {
      return;
    }
    this.groupMode = mode;
    this.refresh();
  }

  get emptyHidden(): boolean {
    return this.hideEmpty;
  }

  setHideEmpty(hide: boolean): void {
    if (this.hideEmpty === hide) {
      return;
    }
    this.hideEmpty = hide;
    this.refresh();
  }

  getTreeItem(node: XbslNode): vscode.TreeItem {
    return node;
  }

  // Category tooltips (a brief description + a docs-panel link) are resolved lazily on hover -
  // one xbsl/docsByName per category, cached for the session (null = no docs page for this kind).
  private readonly docsTipCache = new Map<string, vscode.MarkdownString | null>();

  async resolveTreeItem(item: vscode.TreeItem, node: XbslNode): Promise<vscode.TreeItem> {
    if (!node.docsKind) {
      return item;
    }
    const label = typeof node.label === "string" ? node.label : node.label?.label ?? node.docsKind;
    let md = this.docsTipCache.get(node.docsKind);
    if (md === undefined) {
      md = await this.buildCategoryTooltip(node.docsKind, label);
      this.docsTipCache.set(node.docsKind, md);
    }
    if (md) {
      item.tooltip = md;
    }
    return item;
  }

  private async buildCategoryTooltip(kind: string, label: string): Promise<vscode.MarkdownString | null> {
    if (!lspActive()) {
      return null;
    }
    const res = await lspRequest<{ id?: string; title?: string; summary?: string }>(
      "xbsl/docsByName",
      { name: kind }
    );
    if (!res || (!res.summary && !res.id)) {
      return null;
    }
    const md = new vscode.MarkdownString("", true); // supportThemeIcons for the $(book) glyph
    md.isTrusted = { enabledCommands: ["xbsl.docs.open"] };
    md.appendMarkdown(`**${label}**`);
    if (res.summary) {
      md.appendMarkdown(`\n\n${res.summary}`);
    }
    if (res.id) {
      md.appendMarkdown(
        `\n\n[$(book) ${vscode.l10n.t("Documentation")}](${docsCommandUri(res.id).toString()})`
      );
    }
    return md;
  }

  getParent(node: XbslNode): XbslNode | undefined {
    return node.parent;
  }

  private async buildRootsIfNeeded(): Promise<XbslNode[]> {
    if (!this.roots) {
      this.model = await parseModel(this.projectRootFor);
      this.roots = buildRoots(this.model, this.filter, this.groupMode, this.hideEmpty);
      setParents(this.roots, undefined);
    }
    return this.roots;
  }

  async getChildren(node?: XbslNode): Promise<XbslNode[]> {
    if (node) {
      return node.children ?? [];
    }
    const roots = await this.buildRootsIfNeeded();
    // Deferred reveal (after adding an object/field) - once the fresh tree is built.
    if (this.pendingReveal) {
      setTimeout(() => void this.flushReveal(), 0);
    }
    return roots;
  }

  // Where to put a new object: subsystems (folders) and the project root.
  async placements(): Promise<{ subsystems: Subsystem[]; projectDir?: string }> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    return { subsystems: this.model.subsystems, projectDir: this.model.projects[0]?.dir };
  }

  // Interface components (forms) of the workspace - the "Project" section of the component
  // palette is a thin consumer of the same parsed model.
  async interfaceComponents(): Promise<Array<{ name: string; yamlPath: string }>> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    return this.model.elements
      .filter((el) => el.kind === FORM_KIND)
      .map((el) => ({ name: el.name, yamlPath: el.yamlPath }));
  }

  // The owner OBJECT of a form by the form's yaml path - the form designer's "Data" panel
  // resolves the source of the object attributes through this. undefined for common forms
  // (no owner), for non-form paths and for paths outside the parsed model.
  async formOwnerByPath(
    yamlPath: string
  ): Promise<{ name: string; kind: string; yamlPath: string } | undefined> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    const key = yamlPath.toLowerCase();
    const form = this.model.elements.find(
      (el) => el.kind === FORM_KIND && el.yamlPath.toLowerCase() === key
    );
    if (!form) {
      return undefined;
    }
    const objects = this.model.elements.filter((el) => el.kind !== FORM_KIND);
    const ownerName = formOwnerResolver(objects)(form);
    const owner = ownerName ? objects.find((el) => el.name === ownerName) : undefined;
    return owner ? { name: owner.name, kind: owner.kind, yamlPath: owner.yamlPath } : undefined;
  }

  // Type candidates for the properties panel (the Тип combo box): primitives, then object references
  // (<Имя>.Ссылка?) and enumerations (<Имя>?), each group alphabetized. The list is open.
  async typeCandidates(): Promise<string[]> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    const refs: string[] = [];
    const enums: string[] = [];
    for (const el of this.model.elements) {
      if (REF_KINDS.has(el.kind)) {
        refs.push(`${el.name}.Ссылка?`);
      } else if (el.kind === "Перечисление") {
        enums.push(`${el.name}?`);
      }
    }
    refs.sort((a, b) => a.localeCompare(b, "ru"));
    enums.sort((a, b) => a.localeCompare(b, "ru"));
    return [...PRIMITIVE_TYPES, ...refs, ...enums];
  }

  // The project's enumerations as name -> values - the binding editor completes =Имя.Значение
  // after a dot (hook 6). The values come from each Перечисление element's Элементы section.
  async projectEnums(): Promise<Record<string, string[]>> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    const out: Record<string, string[]> = {};
    for (const el of this.model.elements) {
      if (el.kind !== "Перечисление") {
        continue;
      }
      const values = (parseInternals(el.text)?.enumValues ?? [])
        .map((v) => v.name)
        .filter((n): n is string => !!n);
      if (values.length) {
        out[el.name] = values;
      }
    }
    return out;
  }

  // Reveal (select) a node in the tree after a rebuild - for adding an object/field: the new node
  // only appears in the fresh roots, so the reveal is deferred until they are built.
  requestReveal(pred: (n: XbslNode) => boolean): void {
    this.pendingReveal = pred;
    // Keep the reveal predicate for a short window: the reveal must survive the repeated rebuild
    // from the file watcher (file save -> refresh ~300 ms). Once the window expires, clear it.
    setTimeout(() => {
      if (this.pendingReveal === pred) {
        this.pendingReveal = undefined;
      }
    }, 1200);
    this.refresh();
  }

  private async flushReveal(): Promise<void> {
    if (!this.pendingReveal || !this.treeView || !this.roots) {
      return;
    }
    const node = findNode(this.roots, this.pendingReveal);
    if (!node) {
      return; // the node is not displayed (e.g. filtered out) - exit silently
    }
    // pendingReveal is NOT cleared here - let the reveal survive the watcher rebuild (the timer clears it).
    try {
      await this.treeView.reveal(node, { select: true, focus: false });
    } catch {
      // reveal may refuse (the tree is not ready yet) - not critical
    }
  }

  // Reveal the active editor's element in the tree - without rebuilding the tree. Synchronize only
  // while the tree is visible, so as not to yank it on every editor switch.
  async revealForUri(uri: vscode.Uri): Promise<void> {
    if (this.pendingReveal) {
      return; // a just-added node (field/object) is being revealed - do not interrupt it
    }
    if (!this.treeView?.visible) {
      return;
    }
    const fsPath = uri.fsPath;
    // A node of this very file (or its field) is already selected - do not override the user's
    // choice: otherwise a click on a field (which opens the object's yaml) would move the selection
    // to the parent object.
    if (
      this.treeView.selection.some(
        (n) => n.yamlPath === fsPath || n.modulePath === fsPath || n.objectModulePath === fsPath
      )
    ) {
      return;
    }
    const roots = await this.buildRootsIfNeeded();
    const node = findNode(
      roots,
      (n) =>
        /\b(element|form|subsystem)\b/.test(n.contextValue ?? "") &&
        (n.yamlPath === fsPath || n.modulePath === fsPath || n.objectModulePath === fsPath)
    );
    if (node) {
      try {
        await this.treeView.reveal(node, { select: true, focus: false });
      } catch {
        // ignore
      }
    }
  }
}

// --- commands and registration ----------------------------------------------------------

// Editor column for sources (yaml/xbsl): where this file is already open, otherwise where any
// source is open, otherwise - the left one. This keeps descriptions/modules on the left while the
// preview/properties panels go right (Beside), and repeated clicks do not multiply columns.
function sourceColumn(uri?: vscode.Uri): vscode.ViewColumn {
  const editors = vscode.window.visibleTextEditors;
  if (uri) {
    const same = editors.find((e) => e.document.uri.toString() === uri.toString());
    if (same?.viewColumn) {
      return same.viewColumn;
    }
  }
  const source = editors
    .filter((e) => {
      if (e.document.uri.scheme !== "file") {
        return false;
      }
      const p = e.document.uri.fsPath.toLowerCase();
      return p.endsWith(".yaml") || p.endsWith(".xbsl");
    })
    .sort((a, b) => (a.viewColumn ?? 1) - (b.viewColumn ?? 1))[0];
  return source?.viewColumn ?? vscode.ViewColumn.One;
}

async function openFile(fsPath?: string, preserveFocus = false): Promise<vscode.TextEditor | undefined> {
  if (!fsPath) {
    return undefined;
  }
  if (!fs.existsSync(fsPath)) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the file is not found: {0}", fsPath));
    return undefined;
  }
  const uri = vscode.Uri.file(fsPath);
  const doc = await vscode.workspace.openTextDocument(uri);
  return vscode.window.showTextDocument(doc, { viewColumn: sourceColumn(uri), preview: false, preserveFocus });
}

async function reveal(node?: XbslNode): Promise<void> {
  const editor = await openFile(node?.yamlPath);
  if (editor && node?.offset !== undefined) {
    const pos = editor.document.positionAt(node.offset);
    editor.selection = new vscode.Selection(pos, pos);
    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }
}

async function previewForm(node?: XbslNode): Promise<void> {
  if (!node?.yamlPath) {
    return;
  }
  // The form panel on the LEFT (column One), the yaml on the RIGHT (column Two, focused): the
  // panel keeps its own tab group, so revealing a node in the yaml does not hide the designer.
  const uri = vscode.Uri.file(node.yamlPath);
  await vscode.commands.executeCommand("xbsl.previewForm", uri);
  const doc = await vscode.workspace.openTextDocument(uri);
  await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Two, preview: false });
}

// Click on an object/field/module: the source on the left (the description with the cursor on the
// node, or the module for code kinds), the properties panel - on the right. For a module the source
// is its .xbsl, but the properties (description) are shown anyway.
async function openWithProps(node?: XbslNode): Promise<void> {
  if (!node) {
    return;
  }
  if (node.codeKind && node.modulePath) {
    await openFile(node.modulePath); // the module on the left
  } else if (node.yamlPath) {
    await reveal(node); // the description on the left + cursor on the node (offset)
  }
  if (node.yamlPath && (node.offset !== undefined || node.stdName)) {
    await vscode.commands.executeCommand("xbsl.metadata.props", node); // properties on the right
  }
}

const IDENTIFIER = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;

// Apply the engine result and show what was inserted: reveal in the tree + cursor in the editor
// (the point of interest is sent by the engine in the cursor field of the edited file).
async function applyAndReveal(
  provider: XbslMetadataProvider,
  result: ScaffoldResult,
  revealPred?: (n: XbslNode) => boolean
): Promise<void> {
  const paths = await applyScaffold(result);
  if (!paths.length) {
    return;
  }
  if (revealPred) {
    provider.requestReveal(revealPred);
  }
  const edited = (result.files ?? []).find((f) => !f.created && f.cursor);
  const target = edited ?? (result.files ?? [])[0];
  if (!target) {
    return;
  }
  const uri = vscode.Uri.file(target.path);
  const doc = await vscode.workspace.openTextDocument(uri);
  const editor = await vscode.window.showTextDocument(doc, { viewColumn: sourceColumn(uri), preview: false });
  if (target.cursor) {
    const pos = new vscode.Position(target.cursor.line, target.cursor.character);
    editor.selection = new vscode.Selection(pos, pos);
    editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  }
}

async function askIdentifier(prompt: string, value: string): Promise<string | undefined> {
  const name = await vscode.window.showInputBox({
    prompt,
    value,
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  return name?.trim() || undefined;
}

async function addItem(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const spec = node?.addKind ? ADD_SPECS[node.addKind] : undefined;
  if (!node?.yamlPath || !spec) {
    return;
  }
  const name = await askIdentifier(
    vscode.l10n.t("Name of the new element ({0})", vscode.l10n.t(spec.noun)),
    spec.defaultName
  );
  if (!name || !(await ensureSavedForCli([node.yamlPath]))) {
    return;
  }
  const yamlPath = node.yamlPath;
  const result = await callMeta(
    "xbsl/metaAddField",
    { path: yamlPath, fieldKind: spec.fieldKind, name },
    "add-field",
    [yamlPath, spec.fieldKind, name]
  );
  if (!result) {
    return;
  }
  await applyAndReveal(
    provider,
    result,
    (n) => n.yamlPath === yamlPath && String(n.label) === name && /\bfield\b/.test(n.contextValue ?? "")
  );
}

// Add an attribute into a tabular section: the engine receives the section name (tree node = that section).
async function addTabularAttr(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const tabular = node ? String(node.label) : "";
  if (!node?.yamlPath || !tabular) {
    return;
  }
  const name = await askIdentifier(
    vscode.l10n.t("Name of the new element ({0})", vscode.l10n.t("attribute")),
    "НовыйРеквизит"
  );
  if (!name || !(await ensureSavedForCli([node.yamlPath]))) {
    return;
  }
  const yamlPath = node.yamlPath;
  const result = await callMeta(
    "xbsl/metaAddField",
    { path: yamlPath, fieldKind: "реквизит", name, tabular },
    "add-field",
    [yamlPath, "реквизит", name, "--tabular", tabular]
  );
  if (!result) {
    return;
  }
  await applyAndReveal(
    provider,
    result,
    (n) => n.yamlPath === yamlPath && String(n.label) === name && /\bfield\b/.test(n.contextValue ?? "")
  );
}

interface Placement extends vscode.QuickPickItem {
  dir: string;
}

async function addObject(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const kind = node?.newObjectKind;
  if (!kind) {
    return;
  }
  const name = await askIdentifier(
    vscode.l10n.t("Name of the new object ({0})", kind),
    NEW_OBJECT_DEFAULT[kind] ?? "Новый" + kind
  );
  if (!name) {
    return;
  }

  // Where to put it: a subsystem (folder) or the project root.
  const { subsystems, projectDir } = await provider.placements();
  const items: Placement[] = [
    ...subsystems.map((s) => ({ label: s.name, dir: s.dir })),
    ...(projectDir ? [{ label: vscode.l10n.t("(project root)"), description: projectDir, dir: projectDir }] : []),
  ];
  let dir: string | undefined;
  if (items.length <= 1) {
    dir = items[0]?.dir ?? projectDir;
  } else {
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: vscode.l10n.t("Subsystem (folder) for the new object"),
    });
    if (!pick) {
      return;
    }
    dir = pick.dir;
  }
  if (!dir) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: no folder to create the object in."));
    return;
  }

  const result = await callMeta(
    "xbsl/metaNewObject",
    { directory: dir, kind, name },
    "new-object",
    [dir, kind, name]
  );
  if (!result) {
    return;
  }
  const yamlPath = path.join(dir, name + ".yaml");
  await applyAndReveal(
    provider,
    result,
    (n) => n.yamlPath === yamlPath && /\belement\b/.test(n.contextValue ?? "")
  );
}

// Add forms to a catalog/document: the engine generates a form populated from the attributes
// and registers it in the owner's Интерфейс by itself.
async function addObjectForm(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const owner = node?.ownerName;
  const ownerYaml = node?.yamlPath;
  if (!owner || !ownerYaml) {
    return;
  }
  const objectForm = vscode.l10n.t("Object form (record editing)");
  const bothForms = vscode.l10n.t("Object form + list form");
  const pick = await vscode.window.showQuickPick([objectForm, bothForms], {
    placeHolder: vscode.l10n.t("Which forms to create for {0}", owner),
  });
  if (!pick) {
    return;
  }
  const forms = pick === bothForms ? ["object", "list"] : ["object"];
  if (!(await ensureSavedForCli([ownerYaml]))) {
    return;
  }
  const root = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(ownerYaml))?.uri.fsPath;
  const result = await callMeta(
    "xbsl/metaAddForm",
    { path: ownerYaml, forms, root },
    "add-form",
    [root ?? path.dirname(ownerYaml), "--path", ownerYaml, "--forms", forms.join(",")]
  );
  if (!result) {
    return;
  }
  const formPath = path.join(path.dirname(ownerYaml), `${owner}ФормаОбъекта.yaml`);
  await applyAndReveal(
    provider,
    result,
    (n) => n.yamlPath === formPath && /\bform\b/.test(n.contextValue ?? "")
  );
}

// Delete an object: its files (yaml + module + object module). References are not updated -
// dangling ones are caught by the linter/deploy. With confirmation; the deletion is reversible
// (VS Code undo).
async function deleteObject(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  if (!node?.yamlPath) {
    return;
  }
  const name = path.basename(node.yamlPath, ".yaml");
  const files = [node.yamlPath, node.modulePath, node.objectModulePath].filter((f): f is string => !!f);
  const del = vscode.l10n.t("Delete");
  const pick = await vscode.window.showWarningMessage(
    vscode.l10n.t('XBSL: delete object "{0}"? Files: {1}. References are not updated.', name, files.map((f) => path.basename(f)).join(", ")),
    { modal: true },
    del
  );
  if (pick !== del) {
    return;
  }
  const we = new vscode.WorkspaceEdit();
  for (const f of files) {
    we.deleteFile(vscode.Uri.file(f), { ignoreIfNotExists: true });
  }
  await vscode.workspace.applyEdit(we);
  provider.refresh();
}

async function addSubsystem(provider: XbslMetadataProvider): Promise<void> {
  const { subsystems, projectDir } = await provider.placements();
  const parents: Placement[] = [
    ...(projectDir ? [{ label: vscode.l10n.t("(project root)"), description: projectDir, dir: projectDir }] : []),
    ...subsystems.map((s) => ({ label: s.name, dir: s.dir })),
  ];
  let parent: string | undefined;
  if (parents.length <= 1) {
    parent = parents[0]?.dir ?? projectDir;
  } else {
    const pick = await vscode.window.showQuickPick(parents, {
      placeHolder: vscode.l10n.t("Parent folder for the new subsystem"),
    });
    if (!pick) {
      return;
    }
    parent = pick.dir;
  }
  if (!parent) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: no folder to create the subsystem in."));
    return;
  }
  const name = await askIdentifier(vscode.l10n.t("Name of the new subsystem"), "НоваяПодсистема");
  if (!name) {
    return;
  }
  const result = await callMeta(
    "xbsl/metaAddSubsystem",
    { parentDir: parent, name, representation: name },
    "add-subsystem",
    [parent, name, "--representation", name]
  );
  if (!result) {
    return;
  }
  const yamlPath = path.join(parent, name, "Подсистема.yaml");
  await applyAndReveal(
    provider,
    result,
    (n) => n.yamlPath === yamlPath && /\bsubsystem\b/.test(n.contextValue ?? "")
  );
}

async function filterBySubsystem(provider: XbslMetadataProvider): Promise<void> {
  const { subsystems } = await provider.placements();
  if (!subsystems.length) {
    void vscode.window.showInformationMessage(vscode.l10n.t("XBSL: the project has no subsystems."));
    return;
  }
  const current = provider.filterDirs;
  const items = subsystems.map((s) => ({ label: s.name, dir: s.dir, picked: current.has(s.dir) }));
  const picks = await vscode.window.showQuickPick(items, {
    canPickMany: true,
    placeHolder: vscode.l10n.t("Show only these subsystems (nothing selected – no filter)"),
  });
  if (!picks) {
    return; // canceled - leave the filter as is
  }
  provider.setFilter(picks.map((p) => p.dir));
}

const GROUP_MODE_KEY = "xbsl.metadata.groupMode";
// Persisted "hide empty categories" toggle; the context key drives which title button is shown.
const HIDE_EMPTY_KEY = "xbsl.metadata.hideEmpty";
const HIDE_EMPTY_CONTEXT = "xbsl.metadata.emptyHidden";

async function setEmptyHidden(
  provider: XbslMetadataProvider,
  context: vscode.ExtensionContext,
  hide: boolean
): Promise<void> {
  provider.setHideEmpty(hide);
  await context.globalState.update(HIDE_EMPTY_KEY, hide);
  await vscode.commands.executeCommand("setContext", HIDE_EMPTY_CONTEXT, hide);
}

// Tree hierarchy choice: by object classes or by subsystems; the choice is remembered.
async function pickGroupMode(provider: XbslMetadataProvider, context: vscode.ExtensionContext): Promise<void> {
  const current = provider.mode;
  const items: Array<vscode.QuickPickItem & { mode: GroupMode }> = [
    { label: (current === "kind" ? "$(check) " : "") + vscode.l10n.t("By object classes"), mode: "kind" },
    { label: (current === "subsystem" ? "$(check) " : "") + vscode.l10n.t("By subsystems"), mode: "subsystem" },
  ];
  const pick = await vscode.window.showQuickPick(items, { placeHolder: vscode.l10n.t("Tree grouping") });
  if (pick && pick.mode !== current) {
    provider.setGroupMode(pick.mode);
    await context.globalState.update(GROUP_MODE_KEY, pick.mode);
  }
}

export function registerMetadataTree(
  context: vscode.ExtensionContext,
  projectRootFor: (folder: vscode.WorkspaceFolder) => string
): {
  typeCandidates: () => Promise<string[]>;
  interfaceComponents: () => Promise<Array<{ name: string; yamlPath: string }>>;
  formOwnerByPath: (yamlPath: string) => Promise<{ name: string; kind: string; yamlPath: string } | undefined>;
  projectEnums: () => Promise<Record<string, string[]>>;
} {
  const provider = new XbslMetadataProvider(projectRootFor);
  const view = vscode.window.createTreeView("xbslMetadata", {
    treeDataProvider: provider,
    showCollapseAll: true,
  });
  provider.attachView(view); // reveal requires access to the tree view
  const savedMode = context.globalState.get<GroupMode>(GROUP_MODE_KEY);
  if (savedMode === "kind" || savedMode === "subsystem") {
    provider.setGroupMode(savedMode);
  }
  const savedHide = context.globalState.get<boolean>(HIDE_EMPTY_KEY) ?? false;
  provider.setHideEmpty(savedHide);
  void vscode.commands.executeCommand("setContext", HIDE_EMPTY_CONTEXT, savedHide);

  const watcher = vscode.workspace.createFileSystemWatcher("**/*.{yaml,xbsl}");
  let timer: NodeJS.Timeout | undefined;
  const bump = () => {
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = undefined;
      provider.refresh();
    }, 300);
  };
  watcher.onDidCreate(bump);
  watcher.onDidDelete(bump);
  watcher.onDidChange(bump);

  context.subscriptions.push(
    view,
    watcher,
    // The properties panel follows the tree selection (mouse, arrows, programmatic reveal)
    // if it is already open; it is still opened by a click or the "Properties" menu item.
    view.onDidChangeSelection((e) => updatePropsFromSelection(e.selection[0])),
    // Reverse navigation: the active editor of a description/module/form - reveal its element in the tree.
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (editor && editor.document.uri.scheme === "file") {
        void provider.revealForUri(editor.document.uri);
      }
    }),
    vscode.commands.registerCommand("xbsl.metadata.refresh", () => provider.refresh()),
    vscode.commands.registerCommand("xbsl.metadata.openYaml", (n?: XbslNode) => openFile(n?.yamlPath)),
    vscode.commands.registerCommand("xbsl.metadata.openModule", (n?: XbslNode) => openFile(n?.modulePath)),
    vscode.commands.registerCommand("xbsl.metadata.openObjectModule", (n?: XbslNode) => openFile(n?.objectModulePath)),
    vscode.commands.registerCommand("xbsl.metadata.openAppModule", (n?: XbslNode) => openFile(n?.appModulePath)),
    vscode.commands.registerCommand("xbsl.metadata.reveal", (n?: XbslNode) => reveal(n)),
    vscode.commands.registerCommand("xbsl.metadata.previewForm", (n?: XbslNode) => previewForm(n)),
    vscode.commands.registerCommand("xbsl.metadata.openWithProps", (n?: XbslNode) => openWithProps(n)),
    vscode.commands.registerCommand("xbsl.metadata.addAttribute", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addDimension", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addResource", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addEnumValue", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addClientParam", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addStructField", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addTabular", (n?: XbslNode) => addItem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addTabularAttr", (n?: XbslNode) => addTabularAttr(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addObjectForm", (n?: XbslNode) => addObjectForm(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.deleteObject", (n?: XbslNode) => deleteObject(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addSubsystem", () => addSubsystem(provider)),
    vscode.commands.registerCommand("xbsl.metadata.filterBySubsystem", () => filterBySubsystem(provider)),
    vscode.commands.registerCommand("xbsl.metadata.clearFilter", () => provider.setFilter([])),
    vscode.commands.registerCommand("xbsl.metadata.groupMode", () => pickGroupMode(provider, context)),
    vscode.commands.registerCommand("xbsl.metadata.hideEmptyCategories", () => setEmptyHidden(provider, context, true)),
    vscode.commands.registerCommand("xbsl.metadata.showEmptyCategories", () => setEmptyHidden(provider, context, false))
  );

  // Per-kind "Add <class>" commands (label = the kind; creates via addObject by the node's
  // newObjectKind). Including the common form (its category is "Common forms", not via CREATABLE_KINDS).
  for (const kind of NEW_OBJECT_KINDS) {
    context.subscriptions.push(
      vscode.commands.registerCommand(`xbsl.metadata.addObject.${CREATABLE_SLUG[kind]}`, (n?: XbslNode) =>
        addObject(provider, n)
      )
    );
  }

  // The properties panel takes the Тип combo box candidates from here; the component palette
  // takes the project's interface components; the form designer's data panel resolves a
  // form's owner object (the provider knows the project).
  return {
    typeCandidates: () => provider.typeCandidates(),
    interfaceComponents: () => provider.interfaceComponents(),
    projectEnums: () => provider.projectEnums(),
    formOwnerByPath: (yamlPath: string) => provider.formOwnerByPath(yamlPath),
  };
}
