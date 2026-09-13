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
import {
  applyScaffold,
  callMeta,
  engineProjectInfo,
  ensureSavedForCli,
  ensureSourcesSavedForCli,
  ScaffoldResult,
} from "./engineMeta";
import { lspActive, lspRequest } from "./lspClient";
import {
  allPackages,
  bucketItems,
  EnginePlacement,
  EngineProjectInfo,
  PackageGroup,
  pathKey,
  projectPlacementOf,
  readPlacement,
} from "./packagesCore";
import { docsCommandUri } from "./hoverDocs";
import {
  groupResources,
  MetaField,
  MetaInternals,
  parseInternals,
  ResourceFile,
  ResourceScope,
  SERIALIZER_KIND_SPELLINGS,
  standardAttrNames,
  translationRef,
} from "./metadataCore";
import { formPathOfModule } from "./formDesignerCore";
import { resourcePreviewHtml } from "./resourcePreviewCore";
import { updatePropsFromSelection } from "./formProps";
import { revealContent } from "./reveal";

// Element kind -> tree group + codicon. Several kinds may share one group. The group name is an
// English key: it both groups and serves as the l10n key (in the English UI the bundle is not loaded
// and the key itself is shown; the ru translation lives in bundle.l10n.ru.json). Labels of the lower
// subtrees - see ADD_SPECS.
const KIND_ROWS: ReadonlyArray<readonly [kind: string, group: string, icon: string, english?: string]> = [
  ["Справочник", "Catalogs", "book", "Catalog"],
  ["Документ", "Documents", "note", "Document"],
  ["Перечисление", "Enumerations", "symbol-enum", "Enum"],
  ["Структура", "Structures", "symbol-structure", "Structure"],
  ["ХранимаяСтруктура", "Stored structures", "database", "StorableStructure"],
  ["НаборКонстант", "Constant sets", "symbol-constant", "ConstantsSet"],
  ["РегистрСведений", "Information registers", "table", "InformationRegister"],
  ["РегистрНакопления", "Accumulation registers", "graph", "AccumulationRegister"],
  ["ВиртуальнаяТаблица", "Virtual tables", "list-flat", "VirtualTable"],
  ["ОбщийМодуль", "Common modules", "file-code", "CommonModule"],
  ["HttpСервис", "HTTP services", "globe"],
  ["SoapСервис", "SOAP services", "server"],
  ["КлиентSoapСервиса", "SOAP services", "server"],
  ["КонтрактСервиса", "Contracts", "symbol-interface", "ServiceContract"],
  ["КонтрактТипа", "Contracts", "symbol-interface", "TypeContract"],
  ["КонтрактСущности", "Contracts", "symbol-interface", "EntityContract"],
  ["ГлобальноеКлиентскоеСобытие", "Client events", "zap", "GlobalClientEvent"],
  ["СобытиеЖурналаСобытий", "Event-log events", "history", "EventLogEvent"],
  ["ЗапланированноеЗадание", "Scheduled jobs", "calendar", "ScheduledJob"],
  ["Обработка", "Data processors", "tools", "Processing"],
  ["Отчет", "Reports", "graph-line", "Report"],
  ["ПанельОтчетов", "Report panels", "dashboard", "ReportPanel"],
  ["ЦветоваяСхемаОтчета", "Color schemes", "symbol-color", "ReportColorSchema"],
  ["ФрагментКомандногоИнтерфейса", "Command-interface fragments", "menu", "CommandInterfaceFragment"],
  ["ОбычнаяКоманда", "Commands", "symbol-event", "UsualCommand"],
  ["НавигационнаяКоманда", "Commands", "symbol-event", "NavigationCommand"],
  ["ПереключаемаяКоманда", "Commands", "symbol-event", "SwitchableCommand"],
  ["КомандаСКомпонентом", "Commands", "symbol-event", "CommandWithComponent"],
  ["ПланОбмена", "Exchange plans", "sync", "ExchangePlan"],
  ["КлючДоступа", "Access keys", "key", "AccessKey"],
  ["ПравоНаДействие", "Rights", "shield", "PrivilegeOnAction"],
  ["ПравоНаЭлемент", "Rights", "shield", "PrivilegeOnElement"],
  ["ХранилищеНастроек", "Settings storages", "settings-gear", "SettingsStorage"],
  ["ПараметрыРаботыКлиента", "Client-work parameters", "settings", "ClientWorkParameters"],
  ["ПараметрСамостоятельнойРегистрацииПользователя", "Registration parameters", "person-add", "UserSelfRegistrationParameter"],
  ["ЛокализованныеСтроки", "Localized strings", "symbol-string", "LocalizedStrings"],
  ["Проект", "Project", "project", "Project"],
  ["Подсистема", "Subsystems", "folder-library", "Subsystem"],
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
const LOCALIZED_STRINGS_KIND = "ЛокализованныеСтроки";
// Localization languages by their folder code - English l10n keys (see KIND_ROWS): the pick
// shows them through l10n.t, in the language of the editor.
const LANGUAGE_NAMES: Record<string, string> = { Ru: "Russian", En: "English" };
// English label keys (see the comment at KIND_ROWS): displayed via l10n.t.
const OTHER_GROUP = "Other";
const COMMON_FORMS_GROUP = "Common forms";
// Resource FILES (svg, png, css under a Resources folder, either spelling) are not yaml
// elements, so no kind row lists them - the section is a pseudo-category like Common forms.
const RESOURCES_GROUP = "Resources";
const RESOURCES_ORDER = 7500;
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
  "ХранимаяСтруктура",
  "НаборКонстант",
  "РегистрСведений",
  "РегистрНакопления",
  "ВиртуальнаяТаблица",
  "ПараметрыРаботыКлиента",
  "ОбщийМодуль",
  "HttpСервис",
  "SoapСервис",
  "КонтрактСервиса",
  "КонтрактТипа",
  "КонтрактСущности",
  "ГлобальноеКлиентскоеСобытие",
  "СобытиеЖурналаСобытий",
  "ЗапланированноеЗадание",
  "Обработка",
  "ЦветоваяСхемаОтчета",
  "ФрагментКомандногоИнтерфейса",
  "ОбычнаяКоманда",
  "НавигационнаяКоманда",
  "ПереключаемаяКоманда",
  "КомандаСКомпонентом",
  "ПланОбмена",
  "КлючДоступа",
  "ПравоНаДействие",
  "ПравоНаЭлемент",
  "ХранилищеНастроек",
  "ПараметрСамостоятельнойРегистрацииПользователя",
  "ЛокализованныеСтроки",
  FORM_KIND, // common form (without an owner)
];
const CREATABLE_KINDS = NEW_OBJECT_KINDS.filter((k) => k !== FORM_KIND);

// Latin slug of a kind - for the id of the per-kind "Add <class>" command and the menu token.
const CREATABLE_SLUG: Record<string, string> = {
  Справочник: "catalog",
  Документ: "document",
  Перечисление: "enumeration",
  Структура: "structure",
  ХранимаяСтруктура: "storedstructure",
  НаборКонстант: "constantsset",
  РегистрСведений: "inforegister",
  РегистрНакопления: "accumregister",
  ВиртуальнаяТаблица: "virtualtable",
  ПараметрыРаботыКлиента: "clientparams",
  ОбщийМодуль: "commonmodule",
  HttpСервис: "httpservice",
  SoapСервис: "soapservice",
  КонтрактСервиса: "servicecontract",
  КонтрактТипа: "typecontract",
  КонтрактСущности: "entitycontract",
  ГлобальноеКлиентскоеСобытие: "clientevent",
  СобытиеЖурналаСобытий: "logevent",
  ЗапланированноеЗадание: "scheduledjob",
  Обработка: "processing",
  ЦветоваяСхемаОтчета: "colorscheme",
  ФрагментКомандногоИнтерфейса: "cmdfragment",
  ОбычнаяКоманда: "usualcommand",
  НавигационнаяКоманда: "navcommand",
  ПереключаемаяКоманда: "switchcommand",
  КомандаСКомпонентом: "componentcommand",
  ПланОбмена: "exchangeplan",
  КлючДоступа: "accesskey",
  ПравоНаДействие: "actionright",
  ПравоНаЭлемент: "elementright",
  ХранилищеНастроек: "settingsstorage",
  ПараметрСамостоятельнойРегистрацииПользователя: "regparam",
  ЛокализованныеСтроки: "locstrings",
  КомпонентИнтерфейса: "commonform",
};

// A meaningful default name (otherwise "Новый" + kind yields the clumsy "НовыйКомпонентИнтерфейса").
const NEW_OBJECT_DEFAULT: Record<string, string> = {
  КомпонентИнтерфейса: "НоваяФорма",
  Структура: "НоваяСтруктура",
  ХранимаяСтруктура: "НоваяХранимаяСтруктура",
  ГлобальноеКлиентскоеСобытие: "НовоеСобытие",
  СобытиеЖурналаСобытий: "НовоеСобытиеЖурнала",
  ФрагментКомандногоИнтерфейса: "НовыйФрагмент",
  ВиртуальнаяТаблица: "НоваяВиртуальнаяТаблица",
  Обработка: "НоваяОбработка",
  ЗапланированноеЗадание: "НовоеЗадание",
  ЦветоваяСхемаОтчета: "НоваяЦветоваяСхема",
  ОбычнаяКоманда: "НоваяКоманда",
  НавигационнаяКоманда: "НоваяНавигационнаяКоманда",
  ПереключаемаяКоманда: "НоваяПереключаемаяКоманда",
  КомандаСКомпонентом: "НоваяКомандаСКомпонентом",
  ПравоНаДействие: "НовоеПравоНаДействие",
  ПравоНаЭлемент: "НовоеПравоНаЭлемент",
  ХранилищеНастроек: "НовоеХранилищеНастроек",
  ПараметрСамостоятельнойРегистрацииПользователя: "НовыйПараметрРегистрации",
  ЛокализованныеСтроки: "НовыеСтроки",
};

// The same, for a project that writes its metadata in English: the name goes INTO the sources, so
// it follows the language of the project rather than the language of the editor.
const NEW_OBJECT_DEFAULT_EN: Record<string, string> = {
  КомпонентИнтерфейса: "NewForm",
  Структура: "NewStructure",
  ГлобальноеКлиентскоеСобытие: "NewEvent",
  СобытиеЖурналаСобытий: "NewLogEvent",
  ФрагментКомандногоИнтерфейса: "NewFragment",
  ЗапланированноеЗадание: "NewJob",
  ЦветоваяСхемаОтчета: "NewColorSchema",
  ОбычнаяКоманда: "NewCommand",
  ПараметрСамостоятельнойРегистрацииПользователя: "NewRegistrationParameter",
  ЛокализованныеСтроки: "NewStrings",
};

// The English name a kind is offered under in an English project - the serializer's spelling
// (what `ElementKind:` will actually say), with the KIND_ROWS column as the fallback.
const ENGLISH_BY_KIND = new Map<string, string>();
SERIALIZER_KIND_SPELLINGS.forEach((kind, english) => {
  if (!ENGLISH_BY_KIND.has(kind)) {
    ENGLISH_BY_KIND.set(kind, english);
  }
});

function englishKindName(kind: string): string | undefined {
  return ENGLISH_BY_KIND.get(kind) ?? KIND_ROWS.find((r) => r[0] === kind)?.[3];
}

function newObjectDefault(kind: string, english: boolean): string {
  if (english) {
    const name = englishKindName(kind);
    return NEW_OBJECT_DEFAULT_EN[kind] ?? (name ? "New" + name : "New" + kind);
  }
  return NEW_OBJECT_DEFAULT[kind] ?? "Новый" + kind;
}

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
  // The kind was written in English in this very file (`ElementKind: Catalog`).
  englishKind?: boolean;
  name: string;
  yamlPath: string;
  modulePath?: string;
  objectModulePath?: string;
  queryPath?: string; // VirtualTable: the paired `.xbql` query
  ownerType?: string;
  text: string;
  translations?: Translation[]; // LocalizedStrings: the files of the Localization section
}

// One language of the Localization section: the file with the strings translated into it.
interface Translation {
  lang: string;
  yamlPath: string;
}

interface Project {
  name: string;
  vendor?: string; // Поставщик
  dir: string;
  yamlPath: string; // Проект.yaml or Project.yaml - the platform accepts both spellings
  appModulePath?: string; // Проект.xbsl / Project.xbsl, spelled like the descriptor
}

// A subsystem folder as the tree found it: a folder with Подсистема.yaml (name = the folder
// name). With the engine's placement (EnginePlacement) the subsystems come from the engine
// instead - a first-level folder of the project, the descriptor optional - and the descriptor
// found here only lends its file to the node.
interface Subsystem {
  name: string;
  dir: string;
  yamlPath?: string; // Подсистема.yaml or Subsystem.yaml; none - a subsystem without a descriptor
  namespace?: string; // Vendor::Project::Subsystem, when the engine told
}

// --- source parsing ---------------------------------------------------------------------

// The platform reads a project in either language, so every key the tree looks for is matched in
// both spellings and the KIND is brought back to the one the tables above are keyed by. Without
// this an English-spelled project showed empty sections - the catalog was simply not seen.
const RE_KIND = /^(?:ВидЭлемента|ElementKind):\s*(\S+)/m;
const RE_NAME = /^(?:Имя|Name):\s*(\S+)/m;
const RE_VENDOR = /^(?:Поставщик|Provider):\s*(\S+)/m;
const RE_OWNER_TYPE = /(?:^|\n)\s*(?:Тип|Type):\s*(?:Форма|Form)\w*<([^>]+)>/;
const RE_DECLARED_FORM = /^\s*(?:Форма|Form):\s*(\S+)/gm;

// English spelling of a kind -> the spelling the tree works in. Two sources, never a
// translation: the stdlib TYPE spellings of the fourth KIND_ROWS column, and on top of them
// the SERIALIZER's own kind table - what an English project actually writes into
// `ElementKind:` (`Enumeration`, not the type name `Enum`). Every spelling stays accepted,
// the serializer's wins nothing away.
const KIND_BY_ENGLISH = new Map([
  ...KIND_ROWS.filter((r) => r[3]).map((r) => [r[3] as string, r[0]] as const),
  ...SERIALIZER_KIND_SPELLINGS,
]);

export function canonicalKind(kind: string): string {
  return KIND_BY_ENGLISH.get(kind) ?? kind;
}

async function collectFiles(root: string, ext: string): Promise<string[]> {
  const pattern = new vscode.RelativePattern(vscode.Uri.file(root), `**/*.${ext}`);
  const uris = await vscode.workspace.findFiles(pattern, "**/node_modules/**");
  return uris.map((u) => u.fsPath);
}

interface Model {
  elements: Element[];
  projects: Project[];
  subsystems: Subsystem[];
  resources: string[]; // resource FILE paths - grouped into the Resources section lazily
}

// Resource files: anything under a Resources folder (either spelling). They are not yaml
// elements, which is exactly why the tree used to miss them.
async function collectResourceFiles(root: string): Promise<string[]> {
  const pattern = new vscode.RelativePattern(
    vscode.Uri.file(root), "**/{Ресурсы,Resources}/**/*"
  );
  const uris = await vscode.workspace.findFiles(pattern, "**/node_modules/**");
  return uris.map((u) => u.fsPath);
}

async function parseModel(projectRootFor: (folder: vscode.WorkspaceFolder) => string): Promise<Model> {
  const yamlPaths: string[] = [];
  const xbslPaths: string[] = [];
  // A VirtualTable has no module: its paired file is a `.xbql` query, and the platform requires
  // that file to exist and to hold a query. Collected next to the modules so that the tree can
  // open it the same way.
  const xbqlPaths: string[] = [];
  const resourcePaths: string[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    const root = projectRootFor(folder);
    const [y, x, q, r] = await Promise.all([
      collectFiles(root, "yaml"), collectFiles(root, "xbsl"), collectFiles(root, "xbql"),
      collectResourceFiles(root),
    ]);
    yamlPaths.push(...y);
    xbslPaths.push(...x);
    xbqlPaths.push(...q);
    resourcePaths.push(...r);
  }
  const xbslSet = new Set(xbslPaths.map((p) => p.toLowerCase()));
  const xbqlSet = new Set(xbqlPaths.map((p) => p.toLowerCase()));
  const seen = new Set<string>();
  const elements: Element[] = [];
  const projects: Project[] = [];
  const subsystems: Subsystem[] = [];

  const addYaml = async (yamlPath: string): Promise<void> => {
    const key = yamlPath.toLowerCase();
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    // Подсистема.yaml / Subsystem.yaml - a subsystem folder (the name is not parsed,
    // it = the folder name); the platform accepts both spellings of the file name.
    if (["Подсистема.yaml", "Subsystem.yaml"].includes(path.basename(yamlPath))) {
      const dir = path.dirname(yamlPath);
      subsystems.push({ name: path.basename(dir), dir, yamlPath });
      return;
    }
    let text: string;
    try {
      const raw = await fs.promises.readFile(yamlPath, "utf8");
      text = raw.charCodeAt(0) === 0xfeff ? raw.slice(1) : raw;
    } catch {
      return;
    }
    // Проект.yaml / Project.yaml - has no ВидЭлемента: a separate tree root. The
    // application module follows the descriptor's spelling (Проект.xbsl / Project.xbsl).
    const descriptorBase = path.basename(yamlPath);
    if (["Проект.yaml", "Project.yaml"].includes(descriptorBase)) {
      const dir = path.dirname(yamlPath);
      const appModule = path.join(
        dir, descriptorBase === "Project.yaml" ? "Project.xbsl" : "Проект.xbsl"
      );
      projects.push({
        name: RE_NAME.exec(text)?.[1] ?? path.basename(dir),
        vendor: RE_VENDOR.exec(text)?.[1],
        dir,
        yamlPath,
        appModulePath: xbslSet.has(appModule.toLowerCase()) ? appModule : undefined,
      });
      return;
    }
    const declared = RE_KIND.exec(text)?.[1];
    if (!declared) {
      return;
    }
    const kind = canonicalKind(declared);
    // Which spelling the file itself used: a new object of this project should be named the same
    // way, and the prompt should call the kind by the name the author sees in the sources.
    const englishKind = kind !== declared;
    const name = RE_NAME.exec(text)?.[1] ?? path.basename(yamlPath, ".yaml");
    const base = yamlPath.slice(0, -".yaml".length);
    const modulePath = base + ".xbsl";
    const objectModulePath = base + ".Объект.xbsl";
    const queryPath = base + ".xbql";
    elements.push({
      kind,
      englishKind,
      name,
      yamlPath,
      modulePath: xbslSet.has(modulePath.toLowerCase()) ? modulePath : undefined,
      objectModulePath: xbslSet.has(objectModulePath.toLowerCase()) ? objectModulePath : undefined,
      queryPath: xbqlSet.has(queryPath.toLowerCase()) ? queryPath : undefined,
      ownerType: kind === FORM_KIND ? RE_OWNER_TYPE.exec(text)?.[1]?.split(".")[0] : undefined,
      text,
    });
  };

  // A file of the Localization section is held back: it belongs UNDER the element it translates,
  // not next to it. The guess is confirmed afterwards by the owner - a file whose owner is not a
  // LocalizedStrings element goes through the regular path (a folder may be named after the
  // section for its own reasons).
  const pending: Array<{ yamlPath: string; lang: string; ownerPath: string }> = [];
  for (const yamlPath of yamlPaths) {
    const ref = translationRef(yamlPath);
    if (ref) {
      pending.push({ yamlPath, lang: ref.lang, ownerPath: ref.ownerPath });
    } else {
      await addYaml(yamlPath);
    }
  }
  const localized = new Map<string, Element>();
  for (const el of elements) {
    if (el.kind === LOCALIZED_STRINGS_KIND) {
      localized.set(el.yamlPath.toLowerCase(), el);
    }
  }
  for (const { yamlPath, lang, ownerPath } of pending) {
    const owner = localized.get(ownerPath.toLowerCase());
    if (!owner) {
      await addYaml(yamlPath);
      continue;
    }
    owner.translations = [...(owner.translations ?? []), { lang, yamlPath }];
  }
  return { elements, projects, subsystems, resources: resourcePaths };
}

// --- tree node --------------------------------------------------------------------------

class XbslNode extends vscode.TreeItem {
  children?: XbslNode[];
  parent?: XbslNode; // parent - for getParent (required by TreeView.reveal)
  yamlPath?: string;
  modulePath?: string;
  objectModulePath?: string;
  queryPath?: string;
  appModulePath?: string;
  offset?: number; // node offset in the yaml - for navigation
  addKind?: string; // group: the ADD_SPECS key for "add"
  routeTemplate?: string; // URL template node: its Template - how the engine addresses a route
  newObjectKinds?: string[]; // category: the kinds an object can be created as
  ownerName?: string; // "Forms" group: the owner object (for adding a form)
  ownerKind?: string; // "Forms" group: the owner's element kind (decides the form choices)
  codeKind?: boolean; // code kind (module/HTTP service): click opens the module on the left
  stdKind?: string; // standard attribute: the object kind (Справочник/Документ)
  stdName?: string; // standard attribute: the name (Наименование/Код/Номер/Дата)
  docsKind?: string; // category: the platform type whose docs page describes it (tooltip)
  folderDir?: string; // subsystem or package: the folder a new package and a dropped object go into
  projectDir?: string; // project root: the folder a new subsystem goes into
  packageKey?: string; // package: its path under the subsystem (`Партии::Архив`)
  movable?: boolean; // an object "move to a package" and drag and drop can carry
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
  node.yamlPath = sub.yamlPath;
  node.folderDir = sub.dir;
  // git statuses (color/badge), keeping our own icon: the descriptor, or the folder without one
  node.resourceUri = vscode.Uri.file(sub.yamlPath ?? sub.dir);
  node.contextValue = ["subsystem", sub.yamlPath ? "yaml" : "", "addpkg"].filter(Boolean).join(" ");
  if (sub.yamlPath) {
    node.command = { command: "xbsl.metadata.openYaml", title: "", arguments: [node] };
  }
  node.tooltip = sub.namespace;
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

// Subsystem node in the "By subsystems" mode: collapsible, carries its packages and its own
// objects (by classes). The descriptor is opened via the context menu (a click expands the
// node); a subsystem without one - the descriptor is optional - offers no such item.
// A subsystem does not nest: its finer division is a package, so the node offers "Create
// package" where it used to offer a nested subsystem.
function subsystemGroupNode(sub: Subsystem, children: XbslNode[]): XbslNode {
  const node = new XbslNode(
    sub.name,
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("symbol-namespace");
  node.yamlPath = sub.yamlPath;
  node.folderDir = sub.dir;
  node.resourceUri = vscode.Uri.file(sub.yamlPath ?? sub.dir); // git statuses
  node.contextValue = ["subsystem", sub.yamlPath ? "yaml" : "", "addpkg"].filter(Boolean).join(" ");
  node.tooltip = sub.namespace;
  node.children = children;
  return node;
}

// A package of a subsystem: a folder without a descriptor, labeled by its last segment (the
// nesting shows the rest), the full namespace in the tooltip, the number of its objects -
// nested packages included - in the description.
function packageNode(group: PackageGroup, children: XbslNode[], objects: number): XbslNode {
  const node = new XbslNode(
    group.name,
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = neutralIcon("package");
  node.folderDir = group.dir;
  node.packageKey = group.key;
  node.resourceUri = vscode.Uri.file(group.dir); // git statuses of the folder
  node.description = String(objects);
  node.contextValue = "package addpkg renamepkg";
  node.tooltip = group.namespace;
  node.children = children;
  return node;
}

// The objects a category shows at its top level - what its description counts.
function countedObjects(categories: XbslNode[]): number {
  return categories
    .filter((c) => !/\bxbslResources\b/.test(c.contextValue ?? ""))
    .reduce((sum, c) => sum + (c.children?.length ?? 0), 0);
}

// Project children in the "By subsystems" mode.
//
// With the engine's placement: the subsystems of the project (a descriptor is optional), under
// each - its packages with their nesting and the objects of its root by classes; under a package
// - its nested packages and its objects. Which subsystem and package an object belongs to is the
// engine's answer, never guessed here (packagesCore.bucketItems).
//
// Without it (an engine that cannot answer): the old picture - the subsystem tree by folder
// nesting, an object belongs to the DEEPEST subsystem folder that is a prefix of its path, and
// packages are not shown.
function subsystemModeChildren(
  subsystems: Subsystem[],
  elements: Element[],
  resources: string[] = [],
  placement?: EnginePlacement,
  projectDir?: string
): XbslNode[] {
  // The engine's view of exactly this project: an answer that does not know it yet (a project
  // created after it was given) draws it the old way until the next one.
  const project = placement?.projects.find((p) => pathKey(p.dir) === pathKey(projectDir ?? ""));
  if (placement && project) {
    return packagedChildren(subsystems, elements, resources, placement, project.dir);
  }
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
  // Resource files join their subsystem the same way the objects do - by folder.
  const resBySub = new Map<string, string[]>();
  const rootRes: string[] = [];
  for (const filePath of resources) {
    const s = deepest(filePath, subsystems);
    if (!s) {
      rootRes.push(filePath);
      continue;
    }
    const list = resBySub.get(s.dir);
    if (list) {
      list.push(filePath);
    } else {
      resBySub.set(s.dir, [filePath]);
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
      ...categoriesOf(elemsBySub.get(s.dir) ?? [], false, false, resBySub.get(s.dir) ?? []),
    ]);
  return [
    ...topSubs.sort(byName).map(buildSub),
    ...categoriesOf(rootElems, false, false, rootRes),
  ];
}

// The engine-backed half of subsystemModeChildren (see there).
function packagedChildren(
  descriptors: Subsystem[],
  elements: Element[],
  resources: string[],
  placement: EnginePlacement,
  projectDir: string
): XbslNode[] {
  const project = placement.projects.find((p) => p.dir === projectDir);
  if (!project) {
    return categoriesOf(elements, false, false, resources);
  }
  const namespaceOf = (el: Element): string | undefined => placement.objects.get(pathKey(el.yamlPath))?.namespace;
  const byElement = bucketItems(elements, (el) => el.yamlPath, project, placement);
  const byResource = bucketItems(resources, (p) => p, project, placement);
  const nodes: XbslNode[] = [];
  for (const group of project.subsystems) {
    const elementSlot = byElement.subsystems.get(group);
    const resourceSlot = byResource.subsystems.get(group);
    const buildPackage = (pkg: PackageGroup): { node: XbslNode; objects: number } => {
      const nested = [...pkg.children].sort(byName).map(buildPackage);
      const categories = categoriesOf(
        elementSlot?.packages.get(pkg.key) ?? [], false, false,
        resourceSlot?.packages.get(pkg.key) ?? [], namespaceOf
      );
      const objects = countedObjects(categories) + nested.reduce((sum, n) => sum + n.objects, 0);
      return { node: packageNode(pkg, [...nested.map((n) => n.node), ...categories], objects), objects };
    };
    const descriptor = descriptors.find((d) => pathKey(d.dir) === pathKey(group.dir));
    const view: Subsystem = { name: group.name, dir: group.dir, yamlPath: descriptor?.yamlPath, namespace: group.namespace };
    nodes.push(
      subsystemGroupNode(view, [
        ...[...group.packages].sort(byName).map((pkg) => buildPackage(pkg).node),
        ...categoriesOf(elementSlot?.root ?? [], false, false, resourceSlot?.root ?? [], namespaceOf),
      ])
    );
  }
  nodes.sort((a, b) => String(a.label).localeCompare(String(b.label), "ru"));
  return [...nodes, ...categoriesOf(byElement.outside, false, false, byResource.outside, namespaceOf)];
}

// The subsystems to list: the engine's, when it answered for this project (a subsystem without a
// descriptor included, a nested descriptor - a package - left out), else the descriptors found.
function subsystemViews(descriptors: Subsystem[], placement: EnginePlacement | undefined, projectDir: string | undefined): Subsystem[] {
  const project = placement && projectDir !== undefined
    ? placement.projects.find((p) => pathKey(p.dir) === pathKey(projectDir))
    : undefined;
  if (!project) {
    return descriptors;
  }
  return project.subsystems.map((group) => ({
    name: group.name,
    dir: group.dir,
    yamlPath: descriptors.find((d) => pathKey(d.dir) === pathKey(group.dir))?.yamlPath,
    namespace: group.namespace,
  }));
}

function projectNode(project: Project, children: XbslNode[], filterNames: string[]): XbslNode {
  const node = new XbslNode(project.name, vscode.TreeItemCollapsibleState.Expanded);
  node.iconPath = new vscode.ThemeIcon("project");
  node.resourceUri = vscode.Uri.file(project.yamlPath); // git statuses
  // Grayed out next to the name - Поставщик\Имя from Проект.yaml; a filter appends its list.
  const base = project.vendor ? `${project.vendor}\\${project.name}` : "";
  node.description = filterNames.length
    ? `${base} • ${vscode.l10n.t("filter")}: ${filterNames.join(", ")}`.trim()
    : base || undefined;
  node.contextValue = ["project", project.appModulePath ? "appmod" : "", filterNames.length ? "filtered" : ""]
    .filter(Boolean)
    .join(" ");
  node.appModulePath = project.appModulePath;
  node.projectDir = project.dir;
  node.children = children;
  node.tooltip = vscode.l10n.t("Project");
  return node;
}

function categoryNode(group: string, icon: string, children: XbslNode[], createKinds?: string[]): XbslNode {
  // group is an English key (also the grouping key); we display the translation, the key stays.
  const node = new XbslNode(
    vscode.l10n.t(group),
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = neutralIcon(icon);
  node.description = String(children.length);
  node.newObjectKinds = createKinds;
  node.docsKind = GROUP_PRIMARY_KIND.get(group); // the tooltip resolves its docs page lazily

  // The newobj-<slug> tokens enable the per-kind "Add <class>" commands in the context menu.
  // A category of several kinds (Contracts, Rights, Commands) additionally gets the newobjpick
  // token: its single inline "+" asks which kind, the per-kind inline buttons are not declared.
  node.contextValue = [
    "xbslCategory",
    ...(createKinds ?? []).map((k) => `newobj-${CREATABLE_SLUG[k]}`),
    (createKinds?.length ?? 0) > 1 ? "newobjpick" : "",
  ]
    .filter(Boolean)
    .join(" ");
  node.children = children;
  return node;
}

// A resource file is shown by its KEY - the exact spelling a `Ресурс{...}` reference takes,
// so the section teaches the correct addressing rather than just lists files.
function resourceFileNode(file: ResourceFile): XbslNode {
  const node = new XbslNode(file.key, vscode.TreeItemCollapsibleState.None);
  node.iconPath = neutralIcon("file-media");
  node.resourceUri = vscode.Uri.file(file.filePath); // git statuses; the icon stays ours
  node.tooltip = `Ресурс{${file.key}}`;
  node.contextValue = "xbslResource";
  // An svg goes to our own preview: the project's icons are fill="currentColor", and a
  // standalone viewer paints them black - invisible on a dark canvas. Other images open
  // with the editor's own viewers.
  node.command = file.key.toLowerCase().endsWith(".svg")
    ? { command: "xbsl.metadata.previewResource", title: "", arguments: [file.filePath, file.key] }
    : { command: "vscode.open", title: "", arguments: [vscode.Uri.file(file.filePath)] };
  return node;
}

// The folder that owns a Resources dir - a subsystem or the project root.
function resourceScopeNode(scope: ResourceScope): XbslNode {
  const node = new XbslNode(scope.scope, vscode.TreeItemCollapsibleState.Collapsed);
  node.iconPath = neutralIcon("symbol-namespace");
  node.description = String(scope.files.length);
  node.contextValue = "xbslResourceScope";
  node.children = scope.files.map(resourceFileNode);
  return node;
}

function resourcesCategoryNode(paths: string[]): XbslNode {
  const scopes = groupResources(paths);
  const total = scopes.reduce((sum, scope) => sum + scope.files.length, 0);
  const node = new XbslNode(
    vscode.l10n.t(RESOURCES_GROUP),
    total ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = neutralIcon("file-media");
  node.description = String(total);
  node.contextValue = "xbslCategory xbslResources";
  // A single scope loses the extra level: a small project has one Resources folder, and the
  // scope node would repeat what the project root already says.
  node.children =
    scopes.length === 1 ? scopes[0].files.map(resourceFileNode) : scopes.map(resourceScopeNode);
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

// The URL templates of an HTTP service. Unlike the tabular sections next door these ARE
// addable: the engine writes a route with its handler stub in one operation (xbsl/metaAddRoute),
// so the group offers "add a URL template" and every template offers "add an HTTP method".
// The template carries its own path - the engine addresses a route by the path, not by the name.
function routeGroupNode(yamlPath: string, templates: MetaField[]): XbslNode {
  const node = new XbslNode(vscode.l10n.t("URL templates"), vscode.TreeItemCollapsibleState.Collapsed);
  node.iconPath = new vscode.ThemeIcon("globe");
  node.description = String(templates.length);
  node.yamlPath = yamlPath;
  node.contextValue = "group addroute";
  node.children = templates.map((t) => routeTemplateNode(t, yamlPath));
  return node;
}

function routeTemplateNode(template: MetaField, yamlPath: string): XbslNode {
  const node = fieldNode(template, yamlPath, "globe");
  node.routeTemplate = template.type ?? "";
  node.contextValue = "member field props addroutemethod";
  return node;
}

// One language of the Localization section: the label is the language folder as the platform wrote
// it (En), a click opens that file - the strings of the element translated into this language.
// The node sits right under the element: a "Localization" group above it would be a level with
// nothing to choose in it - one language, one child, one extra click.
// The icon is the one of localized strings (abc) rather than a globe: a translation is text, and
// the globe belongs where URLs are (HTTP services and their templates), otherwise the two read as
// the same thing in the tree.
function translationNode(tr: Translation): XbslNode {
  const node = new XbslNode(tr.lang, vscode.TreeItemCollapsibleState.None);
  node.iconPath = new vscode.ThemeIcon("symbol-string");
  node.description = vscode.l10n.t("Localization");
  node.yamlPath = tr.yamlPath;
  node.resourceUri = vscode.Uri.file(tr.yamlPath); // git statuses (color/badge), keeping our own icon
  node.contextValue = "member translation yaml";
  node.command = { command: "xbsl.metadata.openYaml", title: "", arguments: [node] };
  node.tooltip = vscode.l10n.t("Localization");
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

// Owners the engine can generate forms for (op_add_form): object+list owners, list-only
// owners (registers and a constant set have no object form), plus the single-form kinds -
// Report (report) and Processing (processing). The engine is the source of the abilities;
// these sets only word the menu.
const OBJECT_FORM_OWNER_KINDS = new Set(["Справочник", "Документ", "ПланОбмена", "ХранилищеНастроек"]);
const LIST_ONLY_FORM_OWNER_KINDS = new Set(["РегистрСведений", "РегистрНакопления", "НаборКонстант"]);
const FORM_OWNER_KINDS = new Set([
  ...OBJECT_FORM_OWNER_KINDS,
  ...LIST_ONLY_FORM_OWNER_KINDS,
  "Отчет",
  "Обработка",
]);

// The "Forms" group. For a form-capable owner (FORM_OWNER_KINDS) a form can be added - then
// the group is always shown and carries the owner.
function formsGroupNode(forms: Element[], owner?: { name: string; yamlPath: string; kind: string }): XbslNode {
  const node = new XbslNode(
    vscode.l10n.t("Forms"),
    forms.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("window");
  node.description = String(forms.length);
  node.children = [...forms].sort(byName).map(formNode);
  if (owner) {
    node.ownerName = owner.name;
    node.ownerKind = owner.kind;
    node.yamlPath = owner.yamlPath;
    node.contextValue = "group addform";
  } else {
    node.contextValue = "group";
  }
  return node;
}

function elementNode(el: Element, boundForms: Element[], namespace?: string): XbslNode {
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
    if (el.kind === "HttpСервис") {
      // The group is shown even when empty: a service without routes is exactly where the
      // "add a URL template" action is needed.
      groups.push(routeGroupNode(el.yamlPath, internals.urlTemplates));
    }
  }
  const canAddForm = FORM_OWNER_KINDS.has(el.kind);
  if (boundForms.length || canAddForm) {
    groups.push(
      formsGroupNode(
        boundForms,
        canAddForm ? { name: el.name, yamlPath: el.yamlPath, kind: el.kind } : undefined
      )
    );
  }
  if (el.translations?.length) {
    groups.push(
      ...[...el.translations].sort((a, b) => a.lang.localeCompare(b.lang)).map(translationNode)
    );
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
  node.queryPath = el.queryPath;
  node.offset = internals?.rootOffset; // the object root - for the properties panel
  node.children = groups;
  node.contextValue = [
    "element", "yaml", "props", "deletable",
    el.modulePath ? "xbsl" : "",
    el.objectModulePath ? "objmod" : "",
    el.queryPath ? "xbql" : "",
    // Localized strings get translations right on the element - the "+" mirrors the cloud IDE.
    el.kind === LOCALIZED_STRINGS_KIND ? "addloc" : "",
    "movable",
  ]
    .filter(Boolean)
    .join(" ");
  node.movable = true;
  node.codeKind = CODE_KINDS.has(el.kind);
  // Click: the source on the left (module for code kinds, or the description), properties - right.
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  // The namespace the object lives in, as the engine placed it (Vendor::Project::Subsystem
  // [::Package]) - what a full type name of it spells; the kind below it.
  node.tooltip = namespace ? `${namespace}\n${el.kind}` : el.kind;
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
    const conventions = [
      "ФормаОбъекта", "ФормаСписка", "ФормаОтчета", "ФормаОбработки",
      "ObjectForm", "ListForm", "ReportForm", "ProcessingForm",
    ];
    for (const suffix of conventions) {
      if (form.name.endsWith(suffix)) {
        const owner = form.name.slice(0, -suffix.length);
        if (elementNames.has(owner)) {
          return owner;
        }
      }
    }
    // The card-list row component (ListRow<Object> from the list-cards generator): its
    // generic references the list form's row type rather than the object, so only the name
    // convention ties it to the owner.
    for (const prefix of ["СтрокаСписка", "ListRow"]) {
      if (form.name.startsWith(prefix)) {
        const owner = form.name.slice(prefix.length);
        if (owner && elementNames.has(owner)) {
          return owner;
        }
      }
    }
    return undefined;
  };
}

// Categories (by kind) for a set of elements, including the "Common forms" section. Empty creatable
// categories are shown only without a filter (showEmptyCreatable) - under a filter they are noise.
function categoriesOf(
  elements: Element[], showEmptyCreatable: boolean, hideEmpty: boolean, resources: string[] = [],
  namespaceOf?: (el: Element) => string | undefined
): XbslNode[] {
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
    createKinds?: string[];
  }
  const cats = new Map<string, Cat>();
  for (const obj of [...objects].sort(byName)) {
    const meta = metaFor(obj.kind);
    const node = elementNode(obj, formsByOwner.get(obj.name) ?? [], namespaceOf?.(obj));
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
  // are shown). A category may collect several kinds (Contracts, Rights, Commands).
  for (const kind of CREATABLE_KINDS) {
    const meta = metaFor(kind);
    const existing = cats.get(meta.group);
    if (!existing && !showEmpties) {
      continue;
    }
    const cat = existing ?? { icon: meta.icon, order: meta.order, elements: [] };
    cat.createKinds = [...(cat.createKinds ?? []), kind];
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
      cat.createKinds = [...(cat.createKinds ?? []), kind];
      cats.set(meta.group, cat);
    }
  }

  const roots = [...cats.entries()].map(([group, cat]) => ({
    order: cat.order,
    node: categoryNode(group, cat.icon, cat.elements, cat.createKinds),
  }));

  // Common forms are a pseudo-category; "add" creates a form without an owner. Shown when it has
  // forms, or (empty) when empties are shown.
  const commonFormNodes = [...commonForms].sort(byName).map(formNode);
  if (commonFormNodes.length || showEmpties) {
    roots.push({
      order: COMMON_FORMS_ORDER,
      node: categoryNode(COMMON_FORMS_GROUP, "window", commonFormNodes, [FORM_KIND]),
    });
  }

  // Resource files follow the Common forms pattern: shown when there are files, or empty
  // when empty categories are shown at all.
  if (resources.length || showEmpties) {
    roots.push({ order: RESOURCES_ORDER, node: resourcesCategoryNode(resources) });
  }

  roots.sort((a, b) => a.order - b.order || String(a.node.label).localeCompare(String(b.node.label), "ru"));
  return roots.map((r) => r.node);
}

type GroupMode = "kind" | "subsystem";

function buildRoots(
  model: Model, filterDirs: Set<string>, mode: GroupMode, hideEmpty: boolean, placement?: EnginePlacement
): XbslNode[] {
  const filterActive = filterDirs.size > 0;
  const underFilter = (p: string): boolean =>
    [...filterDirs].some((d) => p.toLowerCase().startsWith(d.toLowerCase() + path.sep));
  const elements = filterActive ? model.elements.filter((el) => underFilter(el.yamlPath)) : model.elements;
  const resources = filterActive ? model.resources.filter(underFilter) : model.resources;
  const showEmpty = !filterActive;

  // The namespace of an object, when the engine placed it - the tooltip of its node.
  const namespaceOf = placement
    ? (el: Element): string | undefined => placement.objects.get(pathKey(el.yamlPath))?.namespace
    : undefined;

  // Project children: "By object classes" - the Subsystems branch + categories by kind;
  // "By subsystems" - the subsystem tree with the packages and the objects under it.
  const childrenOf = (elems: Element[], subs: Subsystem[], res: string[], projectDir?: string): XbslNode[] =>
    mode === "subsystem"
      ? subsystemModeChildren(subs, elems, res, placement, projectDir)
      : [
          subsystemsBranchNode(subsystemViews(subs, placement, projectDir)),
          ...categoriesOf(elems, showEmpty, hideEmpty, res, namespaceOf),
        ];

  if (model.projects.length === 0) {
    // No Проект.yaml found - go without a project root.
    return mode === "subsystem"
      ? subsystemModeChildren(model.subsystems, elements, resources, placement, "")
      : categoriesOf(elements, showEmpty, hideEmpty, resources, namespaceOf);
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
  const resourcesByProject = new Map<Project, string[]>();
  for (const filePath of resources) {
    const p = projectOf(filePath);
    const list = resourcesByProject.get(p) ?? [];
    list.push(filePath);
    resourcesByProject.set(p, list);
  }
  const filterNamesOf = (p: Project): string[] =>
    model.subsystems.filter((s) => filterDirs.has(s.dir) && projectOf(s.dir) === p).map((s) => s.name);

  return projects.map((p) =>
    projectNode(
      p,
      childrenOf(
        elementsByProject.get(p) ?? [],
        subsystemsByProject.get(p) ?? [],
        resourcesByProject.get(p) ?? [],
        p.dir
      ),
      filterNamesOf(p)
    )
  );
}

// --- provider ---------------------------------------------------------------------------

// The one provider of the session (registerMetadataTree fills it in). Panels that carry no tree
// of their own - the form structure, the data panel, the designer, the project wizard - ask the
// language of the project through it.
let sessionProvider: XbslMetadataProvider | undefined;

// The column of the form-designer panel open for a yaml, when there is one (formDesigner.ts's
// DesignerAccess.panelColumnFor). Wired in by registerMetadataTree through a lazy closure - the
// designer registers after the tree, so the value exists only by the time a click happens.
let panelColumnFn: ((uri: vscode.Uri) => vscode.ViewColumn | undefined) | undefined;

/** Does the project of this workspace write its metadata names in English?
 *
 * The answer decides the spelling of every name a hint shows: the name goes to the user (and
 * from a default value, into the sources), so it follows the project rather than the editor.
 * Without a provider - the extension has not activated the tree yet - the answer is Russian,
 * the language `xbsl new-project` writes.
 */
export async function projectWritesEnglishNames(): Promise<boolean> {
  return (await sessionProvider?.ensureWritesEnglishNames()) ?? false;
}

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
  private modelStale = false; // files changed since the model was parsed

  // The engine's placement of the objects - subsystem, package, namespace (xbsl/metaProjectInfo).
  // Asked once per change of the file SET and never waited for: the tree is drawn at once with
  // what is known - the last answer, or none (then without packages) - and drawn again when the
  // answer arrives. A change of a file's content keeps the answer: no folder moved.
  private placement?: EnginePlacement;
  private generation = 0; // bumped when files appear, disappear or move
  private placementGeneration = -1; // the generation the placement was last asked for
  private placementRequest?: Promise<void>;
  // The engine answered, and its answer had no placement (an engine older than packages): it is
  // not asked again this session - an answer that cannot change is not worth a process per save.
  private placementUnsupported = false;

  constructor(private readonly projectRootFor: (folder: vscode.WorkspaceFolder) => string) {}

  // The root the engine walks for an operation on this path - the project root the lint uses.
  rootFor(fsPath: string): string | undefined {
    const folder = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(fsPath));
    return folder ? this.projectRootFor(folder) : undefined;
  }

  // The tree view is created separately (access to reveal is needed); attached after creation.
  attachView(view: vscode.TreeView<XbslNode>): void {
    this.treeView = view;
  }

  // Does this workspace write its metadata names in English? Read off the sources themselves: a
  // new object should be named the way the project around it is named, whatever language the
  // editor speaks.
  writesEnglishNames(): boolean {
    return (this.model?.elements ?? []).some((e) => e.englishKind);
  }

  // The async twin of the predicate above, for callers outside the tree. The model is built
  // lazily by getChildren, so a panel that asks before the view was ever opened would be told
  // "Russian" about an English project.
  async ensureWritesEnglishNames(): Promise<boolean> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    return this.writesEnglishNames();
  }

  // The files changed: the model is parsed anew on the next draw. `structural` - files appeared,
  // disappeared or moved, so the placement is asked for again too; a content change keeps it.
  refresh(structural = true): void {
    if (structural) {
      this.generation++;
    }
    this.modelStale = true;
    this.redraw();
  }

  // Another picture of the same files: a filter, the grouping, a toggle, the placement arriving.
  private redraw(): void {
    this.roots = undefined;
    this.emitter.fire(undefined);
  }

  // Ask the engine for the placement unless the current file set was asked for already. The
  // answer triggers a redraw; failing to answer keeps the last placement (a restarting server is
  // no reason to fold the packages away) or, never having had one, the tree without packages.
  private askPlacement(): Promise<void> {
    if (this.placementRequest) {
      return this.placementRequest;
    }
    if (this.placementGeneration === this.generation || this.placementUnsupported) {
      return Promise.resolve();
    }
    const generation = this.generation;
    this.placementGeneration = generation;
    this.placementRequest = this.fetchPlacement()
      .then((placement) => {
        if (placement) {
          this.placement = placement;
        }
      })
      .catch(() => undefined)
      .finally(() => {
        this.placementRequest = undefined;
        this.redraw(); // a newer file set asks again from the draw
      });
    return this.placementRequest;
  }

  private async fetchPlacement(): Promise<EnginePlacement | undefined> {
    const merged: Required<Omit<EngineProjectInfo, "error">> = { projects: [], packages: [], objects: [] };
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      const info = await engineProjectInfo(this.projectRootFor(folder));
      if (!info) {
        return undefined;
      }
      merged.projects.push(...(info.projects ?? []));
      merged.packages.push(...(info.packages ?? []));
      merged.objects.push(...(info.objects ?? []));
    }
    const placement = readPlacement(merged, (this.model?.subsystems ?? []).map((s) => s.dir));
    this.placementUnsupported = placement === undefined && merged.objects.length > 0;
    return placement;
  }

  // The placement for a command that needs it now (the move targets): the current answer, asked
  // for and awaited when the file set changed since.
  async currentPlacement(): Promise<EnginePlacement | undefined> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    await this.askPlacement();
    return this.placement;
  }

  get filterDirs(): Set<string> {
    return this.filter;
  }

  setFilter(dirs: string[]): void {
    this.filter = new Set(dirs);
    this.redraw();
  }

  get mode(): GroupMode {
    return this.groupMode;
  }

  setGroupMode(mode: GroupMode): void {
    if (this.groupMode === mode) {
      return;
    }
    this.groupMode = mode;
    this.redraw();
  }

  get emptyHidden(): boolean {
    return this.hideEmpty;
  }

  setHideEmpty(hide: boolean): void {
    if (this.hideEmpty === hide) {
      return;
    }
    this.hideEmpty = hide;
    this.redraw();
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
      if (!this.model || this.modelStale) {
        this.modelStale = false;
        this.model = await parseModel(this.projectRootFor);
      }
      void this.askPlacement();
      this.roots = buildRoots(this.model, this.filter, this.groupMode, this.hideEmpty, this.placement);
      setParents(this.roots, undefined);
    }
    return this.roots;
  }

  // Expand the root nodes one level down - the metadata kinds live right under them.
  async expandRoots(): Promise<void> {
    if (!this.treeView) {
      return;
    }
    const roots = this.roots ?? (await this.getChildren());
    for (const root of roots) {
      await this.treeView.reveal(root, { expand: 1, select: false, focus: false });
    }
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
  async placements(): Promise<{
    subsystems: Subsystem[];
    packages: Array<{ label: string; description: string; dir: string }>;
    projectDir?: string;
    projectDirs: string[];
  }> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    // The packages the engine told of last: a new object may go into one of them.
    const packages = (this.placement?.projects ?? []).flatMap((project) =>
      project.subsystems.flatMap((s) =>
        allPackages(s.packages).map((g) => ({ label: `${s.name}::${g.key}`, description: g.namespace, dir: g.dir }))
      )
    );
    return {
      subsystems: this.model.subsystems,
      packages,
      projectDir: this.model.projects[0]?.dir,
      projectDirs: this.model.projects.map((p) => p.dir),
    };
  }

  // Where an object may move within its project: the root of every subsystem and every package,
  // as the engine placed them. undefined - the engine has not told (an older one, none at all).
  async moveTargets(fsPath: string): Promise<Array<vscode.QuickPickItem & { dir: string }> | undefined> {
    const placement = await this.currentPlacement();
    const project = placement ? projectPlacementOf(placement, fsPath) : undefined;
    if (!project) {
      return undefined;
    }
    return project.subsystems.flatMap((s) => [
      { label: s.name, description: vscode.l10n.t("subsystem root"), dir: s.dir },
      ...allPackages(s.packages).map((g) => ({ label: `${s.name}::${g.key}`, description: g.namespace, dir: g.dir })),
    ]);
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
        /\b(element|form|subsystem|translation)\b/.test(n.contextValue ?? "") &&
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

// The group a form-designer panel holds this file's form in, when one is open: its own panel for
// a form yaml, the panel of the paired form for a module. Nothing to avoid without a panel.
function designerColumnOf(uri?: vscode.Uri): vscode.ViewColumn | undefined {
  if (!uri || !panelColumnFn) {
    return undefined;
  }
  const own = panelColumnFn(uri);
  if (own !== undefined) {
    return own;
  }
  const formPath = formPathOfModule(uri.path);
  return formPath === undefined ? undefined : panelColumnFn(uri.with({ path: formPath }));
}

// Editor column for sources (yaml/xbsl): where this file is already open, otherwise where any
// source is open, otherwise - the left one. This keeps descriptions/modules on the left while the
// preview/properties panels go right (Beside), and repeated clicks do not multiply columns.
//
// A form-designer panel makes its own group unusable for the form's sources: opening one there
// puts it behind the very form it belongs to, and the pairing then brings the panel forward over
// it on every click (docs/DESIGNER.md - a source opens BESIDE the panel, never in its column).
// A tab that already exists is left where it is: bringing it forward beats a duplicate of the
// same document in a second group.
function sourceColumn(uri?: vscode.Uri): vscode.ViewColumn {
  const editors = vscode.window.visibleTextEditors;
  if (uri) {
    const same = editors.find((e) => e.document.uri.toString() === uri.toString());
    if (same?.viewColumn) {
      return same.viewColumn;
    }
  }
  const panel = designerColumnOf(uri);
  const source = editors
    .filter((e) => {
      if (e.document.uri.scheme !== "file") {
        return false;
      }
      const p = e.document.uri.fsPath.toLowerCase();
      return p.endsWith(".yaml") || p.endsWith(".xbsl");
    })
    .sort((a, b) => (a.viewColumn ?? 1) - (b.viewColumn ?? 1))
    .find((e) => e.viewColumn !== panel);
  if (source?.viewColumn) {
    return source.viewColumn;
  }
  return panel === vscode.ViewColumn.One ? vscode.ViewColumn.Beside : vscode.ViewColumn.One;
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

// One preview panel for all resources: a click swaps its content, closing drops the handle.
let resourcePanel: vscode.WebviewPanel | undefined;

async function openResourcePreview(filePath?: string, key?: string): Promise<void> {
  if (!filePath || !key) {
    return;
  }
  if (!fs.existsSync(filePath)) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the file is not found: {0}", filePath));
    return;
  }
  let svgText: string;
  try {
    svgText = await fs.promises.readFile(filePath, "utf8");
  } catch {
    return;
  }
  if (!resourcePanel) {
    resourcePanel = vscode.window.createWebviewPanel(
      "xbslResourcePreview", key, vscode.ViewColumn.Active,
      { enableScripts: false }
    );
    resourcePanel.onDidDispose(() => {
      resourcePanel = undefined;
    });
  } else {
    resourcePanel.title = key;
    resourcePanel.reveal(vscode.ViewColumn.Active, true);
  }
  resourcePanel.webview.html = resourcePreviewHtml(
    svgText, key, vscode.l10n.t("currentColor follows the editor theme")
  );
}

async function reveal(node?: XbslNode): Promise<void> {
  const editor = await openFile(node?.yamlPath);
  if (editor && node?.offset !== undefined) {
    const pos = editor.document.positionAt(node.offset);
    editor.selection = new vscode.Selection(pos, pos);
    revealContent(editor, pos);
  }
}

async function previewForm(node?: XbslNode): Promise<void> {
  if (!node?.yamlPath) {
    return;
  }
  // Only the panel: the sources open on demand - the panel's bottom "Module" tab, a click on
  // a node (the cursor sync shows the yaml), or the tree's own context menu items.
  await vscode.commands.executeCommand("xbsl.previewForm", vscode.Uri.file(node.yamlPath));
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
  } else if (node.queryPath) {
    // A VirtualTable keeps its substance in the paired `.xbql`: the yaml holds the parameters,
    // the query is the element itself, so a click opens the query.
    await openFile(node.queryPath);
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
  revealPred?: (n: XbslNode) => boolean,
  openEdited = true
): Promise<void> {
  const paths = await applyScaffold(result);
  if (!paths.length) {
    return;
  }
  if (revealPred) {
    provider.requestReveal(revealPred);
  }
  // A move or a package rename edits files all over the project: none of them is the point of
  // interest, the node in the tree is.
  if (!openEdited) {
    return;
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
    revealContent(editor, pos);
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

// The verbs come from the ENGINE (xbsl/httpMethods): it owns the list a route may declare, and
// a copy here would drift from it. Asked once per session; an engine that does not answer (an
// older one, the CLI mode) leaves the pick empty and the caller falls back to free text -
// the value is validated where it is written, not here.
let httpMethodsCache: string[] | undefined;

async function httpMethods(): Promise<string[]> {
  if (httpMethodsCache) {
    return httpMethodsCache;
  }
  const answer = lspActive()
    ? await lspRequest<{ methods?: string[] }>("xbsl/httpMethods", {})
    : undefined;
  httpMethodsCache = answer?.methods?.length ? answer.methods : undefined;
  return httpMethodsCache ?? [];
}

async function pickHttpMethods(template: string): Promise<string[]> {
  const known = await httpMethods();
  if (!known.length) {
    const typed = await vscode.window.showInputBox({
      prompt: vscode.l10n.t("HTTP methods of {0} (comma separated)", template),
      placeHolder: "GET, POST",
    });
    return typed?.trim() ? typed.split(",").map((m) => m.trim()).filter(Boolean) : [];
  }
  const picked = await vscode.window.showQuickPick(known, {
    canPickMany: true,
    title: vscode.l10n.t("HTTP methods of {0}", template),
    placeHolder: vscode.l10n.t("One or several - the engine writes a handler stub for each"),
  });
  return picked ?? [];
}

// One route addition. The template and the verbs go to the engine AS THEY ARE: it composes the
// routes string itself (scaffold.routes_for), writes the yaml and the handler stubs, and skips
// what a template already has - an existing one is extended with the missing verbs only.
async function runAddRoute(
  provider: XbslMetadataProvider, yamlPath: string, template: string, methods: string[], reveal: string
): Promise<void> {
  if (!(await ensureSavedForCli([yamlPath]))) {
    return;
  }
  const result = await callMeta(
    "xbsl/metaAddRoute",
    { path: yamlPath, template, methods },
    "add-route",
    [yamlPath, methods.map((m) => `${m} ${template}`).join(", ")]
  );
  if (!result) {
    return;
  }
  await applyAndReveal(
    provider, result, (n) => n.yamlPath === yamlPath && String(n.label) === reveal
  );
}

// "Add a URL template" on the group: the path is the developer's decision, the methods come
// from the pick, the handler names are the engine's business.
async function addRoute(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  if (!node?.yamlPath) {
    return;
  }
  const template = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("URL template of the new route"),
    value: "/",
    placeHolder: "/orders/{id}",
    validateInput: (v) =>
      v.trim().startsWith("/") ? undefined : vscode.l10n.t("A URL template starts with \"/\"."),
  });
  const path = template?.trim();
  if (!path) {
    return;
  }
  const methods = await pickHttpMethods(path);
  if (!methods.length) {
    return;
  }
  await runAddRoute(provider, node.yamlPath, path, methods, path);
}

// "Add an HTTP method" on a URL template: the template is known, so only the verbs are asked.
async function addRouteMethod(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const template = node?.routeTemplate?.trim();
  if (!node?.yamlPath || !template) {
    return;
  }
  const methods = await pickHttpMethods(template);
  if (!methods.length) {
    return;
  }
  await runAddRoute(provider, node.yamlPath, template, methods, methods[0]);
}

interface Placement extends vscode.QuickPickItem {
  dir: string;
}

// The nearest node - the node itself included - that stands for a folder of a subsystem or of a
// package: where a new package, a new object of its category and a dropped object go.
function folderNodeOf(node?: XbslNode): XbslNode | undefined {
  for (let n = node; n; n = n.parent) {
    if (n.folderDir) {
      return n;
    }
  }
  return undefined;
}

// `targetDir` - the folder is already known (a category under a subsystem or a package node, a
// new package): the new object goes there without asking.
async function addObject(provider: XbslMetadataProvider, kind?: string, targetDir?: string): Promise<void> {
  if (!kind) {
    return;
  }
  const english = provider.writesEnglishNames();
  const name = await askIdentifier(
    vscode.l10n.t("Name of the new object ({0})", (english && englishKindName(kind)) || kind),
    newObjectDefault(kind, english)
  );
  if (!name) {
    return;
  }

  // Where to put it: a subsystem (folder), a package of one or the project root.
  const { subsystems, packages, projectDir } = await provider.placements();
  const items: Placement[] = [
    ...subsystems.map((s) => ({ label: s.name, dir: s.dir })),
    ...packages,
    ...(projectDir ? [{ label: vscode.l10n.t("(project root)"), description: projectDir, dir: projectDir }] : []),
  ];
  let dir: string | undefined = targetDir;
  if (dir) {
    // the folder came with the command
  } else if (items.length <= 1) {
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

// "Add localization" on a LocalizedStrings element: the language candidates come from the
// ENGINE (xbsl/localizationInfo) - the declared localization languages minus the default one
// and minus the translations already present. Without the LSP the pick falls back to the
// supported folder codes minus the translations the tree itself shows; the engine validates
// on write either way.
async function addLocalization(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const yamlPath = node?.yamlPath;
  if (!yamlPath) {
    return;
  }
  interface LocInfo {
    candidates?: string[];
    names?: Record<string, string>;
    error?: string;
  }
  const info = lspActive()
    ? await lspRequest<LocInfo>("xbsl/localizationInfo", { path: yamlPath })
    : undefined;
  if (info?.error) {
    void vscode.window.showWarningMessage(info.error);
    return;
  }
  let candidates = info?.candidates;
  if (!candidates) {
    const existing = new Set(
      (node.children ?? [])
        .filter((c) => /\btranslation\b/.test(c.contextValue ?? ""))
        .map((c) => String(c.label))
    );
    candidates = ["Ru", "En"].filter((c) => !existing.has(c));
  }
  if (!candidates.length) {
    void vscode.window.showInformationMessage(
      vscode.l10n.t("Every declared localization language already has its translation.")
    );
    return;
  }
  const pick = await vscode.window.showQuickPick(
    candidates.map((code) => ({
      // The language name is UI text: shown in the language of the EDITOR, not of the
      // project (unlike a name that goes into the sources). The engine's own name is the
      // fallback for a code the editor knows nothing about.
      label: LANGUAGE_NAMES[code] ? vscode.l10n.t(LANGUAGE_NAMES[code]) : info?.names?.[code] ?? code,
      description: code,
      code,
    })),
    { placeHolder: vscode.l10n.t("Language of the translation") }
  );
  if (!pick) {
    return;
  }
  const result = await callMeta(
    "xbsl/metaAddLocalization",
    { path: yamlPath, language: pick.code },
    "add-localization",
    [yamlPath, pick.code]
  );
  if (!result) {
    return;
  }
  const fileName = path.basename(yamlPath);
  await applyAndReveal(
    provider,
    result,
    (n) =>
      /\btranslation\b/.test(n.contextValue ?? "") &&
      String(n.label) === pick.code &&
      !!n.yamlPath &&
      path.basename(n.yamlPath) === fileName
  );
}

// The inline "+" of a category with several creatable kinds (Contracts, Rights, Commands):
// asks which kind, then goes the usual way. The name shown follows the language the project
// writes its names in, like the "Name of the new object" prompt does.
async function addObjectPick(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const kinds = node?.newObjectKinds ?? [];
  const targetDir = folderNodeOf(node)?.folderDir;
  if (kinds.length < 2) {
    return addObject(provider, kinds[0], targetDir);
  }
  const english = provider.writesEnglishNames();
  const pick = await vscode.window.showQuickPick(
    kinds.map((k) => ({ label: (english && englishKindName(k)) || k, objectKind: k })),
    { placeHolder: vscode.l10n.t("Kind of the new object") }
  );
  if (pick) {
    await addObject(provider, pick.objectKind, targetDir);
  }
}

// "Create package" on a subsystem or a package. A package has no descriptor and a folder without
// objects is not a package, so the command asks the name and goes straight on to the first object
// of the package - the engine's own "new object" with the new folder as its directory; the engine
// checks the name as a namespace segment and reminds of the dictionary pair it needs.
async function addPackage(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const parent = folderNodeOf(node);
  if (!parent?.folderDir) {
    return;
  }
  const english = provider.writesEnglishNames();
  const name = await askIdentifier(vscode.l10n.t("Name of the new package"), english ? "NewPackage" : "НовыйПакет");
  if (!name) {
    return;
  }
  const dir = path.join(parent.folderDir, name);
  if (fs.existsSync(dir)) {
    void vscode.window.showWarningMessage(vscode.l10n.t("XBSL: the folder {0} already exists.", dir));
    return;
  }
  const kinds = NEW_OBJECT_KINDS.map((k) => ({ label: (english && englishKindName(k)) || k, objectKind: k }));
  const pick = await vscode.window.showQuickPick(kinds, {
    placeHolder: vscode.l10n.t("Kind of the first object of the package {0}", name),
  });
  if (pick) {
    await addObject(provider, pick.objectKind, dir);
  }
}

// One object moved by the engine (xbsl/metaMoveObject): the files, the imports a reference needs
// at the new place, the full names spelling the old one. The engine reads every source of the
// project, which takes a while on a large one - hence the progress.
async function runMove(provider: XbslMetadataProvider, nodes: XbslNode[], targetDir: string): Promise<void> {
  if (!(await ensureSourcesSavedForCli())) {
    return;
  }
  for (const node of nodes) {
    const yamlPath = node.yamlPath;
    const root = yamlPath ? provider.rootFor(yamlPath) : undefined;
    if (!yamlPath || !root) {
      continue;
    }
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: vscode.l10n.t("XBSL: moving {0}...", String(node.label)) },
      () => callMeta("xbsl/metaMoveObject", { root, path: yamlPath, targetDir }, "move-object", [root, yamlPath, targetDir])
    );
    if (!result) {
      return;
    }
    const moved = pathKey(path.join(targetDir, path.basename(yamlPath)));
    await applyAndReveal(
      provider,
      result,
      (n) => !!n.yamlPath && pathKey(n.yamlPath) === moved && /\belement\b/.test(n.contextValue ?? ""),
      false
    );
    if (result.error) {
      return;
    }
  }
}

interface MoveTarget extends vscode.QuickPickItem {
  dir?: string;
  newPackage?: boolean;
}

// "Move to package" on an object: the targets are the roots and packages of its subsystems as
// the engine placed them, plus a new package under any of them.
async function moveToPackage(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  if (!node?.yamlPath) {
    return;
  }
  const targets = await provider.moveTargets(node.yamlPath);
  if (!targets) {
    void vscode.window.showWarningMessage(
      vscode.l10n.t("XBSL: the engine did not tell where the packages are - moving needs the xbsl engine with packages support.")
    );
    return;
  }
  const current = pathKey(path.dirname(node.yamlPath));
  const items: MoveTarget[] = [
    ...targets.filter((t) => pathKey(t.dir) !== current),
    { label: `$(add) ${vscode.l10n.t("New package...")}`, newPackage: true },
  ];
  const pick = await vscode.window.showQuickPick(items, {
    placeHolder: vscode.l10n.t("Where to move {0}", String(node.label)),
  });
  if (!pick) {
    return;
  }
  let dir = pick.dir;
  if (pick.newPackage) {
    const parent = await vscode.window.showQuickPick(targets, {
      placeHolder: vscode.l10n.t("Where the new package goes"),
    });
    if (!parent) {
      return;
    }
    const name = await askIdentifier(
      vscode.l10n.t("Name of the new package"),
      provider.writesEnglishNames() ? "NewPackage" : "НовыйПакет"
    );
    if (!name) {
      return;
    }
    dir = path.join(parent.dir, name);
  }
  if (dir) {
    await runMove(provider, [node], dir);
  }
}

// "Rename package": the folder and every import and full name that spells the package - the
// engine's operation (xbsl/metaRenamePackage), the tree applies what it computed.
async function renamePackage(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const packageDir = node?.folderDir;
  if (!packageDir || !node?.packageKey) {
    return;
  }
  const current = path.basename(packageDir);
  const name = await askIdentifier(vscode.l10n.t("New name of the package {0}", node.packageKey), current);
  if (!name || name === current) {
    return;
  }
  const root = provider.rootFor(packageDir);
  if (!root || !(await ensureSourcesSavedForCli())) {
    return;
  }
  const packageKey = node.packageKey;
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: vscode.l10n.t("XBSL: renaming the package {0}...", packageKey) },
    () => callMeta(
      "xbsl/metaRenamePackage", { root, packageDir, newName: name }, "rename-package", [root, packageDir, name]
    )
  );
  if (!result) {
    return;
  }
  const renamed = pathKey(path.join(path.dirname(packageDir), name));
  await applyAndReveal(
    provider,
    result,
    (n) => !!n.folderDir && pathKey(n.folderDir) === renamed && /\bpackage\b/.test(n.contextValue ?? ""),
    false
  );
}

const TREE_MIME = "application/vnd.code.tree.xbslmetadata";

// Drag an object onto a subsystem or a package (or anything under one) - the same move as the
// "Move to package" command, confirmed first: a drop is easy to make by accident, and a move
// edits files across the project.
class MetadataDragAndDrop implements vscode.TreeDragAndDropController<XbslNode> {
  readonly dragMimeTypes = [TREE_MIME];
  readonly dropMimeTypes = [TREE_MIME];

  constructor(private readonly provider: XbslMetadataProvider) {}

  handleDrag(source: readonly XbslNode[], data: vscode.DataTransfer): void {
    const movable = source.filter((n) => n.movable && n.yamlPath);
    if (movable.length) {
      data.set(TREE_MIME, new vscode.DataTransferItem(movable));
    }
  }

  async handleDrop(target: XbslNode | undefined, data: vscode.DataTransfer): Promise<void> {
    const destination = folderNodeOf(target);
    const nodes = data.get(TREE_MIME)?.value as XbslNode[] | undefined;
    const dir = destination?.folderDir;
    if (!destination || !dir || !nodes?.length) {
      return;
    }
    // The editor puts every dragged node under the tree's own type as well: a field or a form
    // carries the yaml of its object, and only an object itself moves.
    const moving = nodes.filter(
      (n) => n.movable && n.yamlPath && pathKey(path.dirname(n.yamlPath)) !== pathKey(dir)
    );
    if (!moving.length) {
      return;
    }
    const where = typeof destination.tooltip === "string" && destination.tooltip
      ? destination.tooltip
      : String(destination.label);
    const move = vscode.l10n.t("Move");
    const pick = await vscode.window.showWarningMessage(
      vscode.l10n.t(
        "XBSL: move {0} to {1}? The imports and full names that need it are updated across the project.",
        moving.map((n) => String(n.label)).join(", "),
        where
      ),
      { modal: true },
      move
    );
    if (pick === move) {
      await runMove(this.provider, moving, dir);
    }
  }
}

// The file suffix of a generated form, both project languages (the engine spells the file by
// the project language - the reveal must find it either way).
const FORM_FILE_SUFFIXES: Record<string, [string, string]> = {
  object: ["ФормаОбъекта", "ObjectForm"],
  list: ["ФормаСписка", "ListForm"],
  report: ["ФормаОтчета", "ReportForm"],
  processing: ["ФормаОбработки", "ProcessingForm"],
};

// Add forms to a form-capable owner: the engine generates a form populated from the
// attributes and registers it in the owner's Interface by itself. The choices follow the
// owner's kind: object/object+list for data objects, list alone for registers and a constant
// set, the report form for Report, the processing form for Processing.
async function addObjectForm(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const owner = node?.ownerName;
  const ownerYaml = node?.yamlPath;
  if (!owner || !ownerYaml) {
    return;
  }
  const kind = node?.ownerKind ?? "";
  let forms: string[];
  if (kind === "Отчет") {
    forms = ["report"];
  } else if (kind === "Обработка") {
    forms = ["processing"];
  } else if (LIST_ONLY_FORM_OWNER_KINDS.has(kind)) {
    forms = ["list"];
  } else {
    const objectForm = vscode.l10n.t("Object form (record editing)");
    const bothForms = vscode.l10n.t("Object form + list form");
    const pick = await vscode.window.showQuickPick([objectForm, bothForms], {
      placeHolder: vscode.l10n.t("Which forms to create for {0}", owner),
    });
    if (!pick) {
      return;
    }
    forms = pick === bothForms ? ["object", "list"] : ["object"];
  }
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
  const targets = new Set(
    (FORM_FILE_SUFFIXES[forms[0]] ?? []).map((s) => path.join(path.dirname(ownerYaml), `${owner}${s}.yaml`))
  );
  await applyAndReveal(
    provider,
    result,
    (n) => !!n.yamlPath && targets.has(n.yamlPath) && /\bform\b/.test(n.contextValue ?? "")
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

// A subsystem is a first-level folder of its project (a folder inside a subsystem is a package),
// so the only parent to choose is the project: the one the command was called on, the only one,
// or one of several.
async function addSubsystem(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const { projectDir, projectDirs } = await provider.placements();
  const parents: Placement[] = projectDirs.map((dir) => ({
    label: vscode.l10n.t("(project root)"), description: dir, dir,
  }));
  let parent: string | undefined = node?.projectDir;
  if (parent) {
    // called on a project node
  } else if (parents.length <= 1) {
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
  // The engine names the file by the project's spelling (Подсистема.yaml or
  // Subsystem.yaml) - match the created node by its directory instead.
  const createdDir = path.join(parent, name);
  await applyAndReveal(
    provider,
    result,
    (n) => !!n.yamlPath && path.dirname(n.yamlPath) === createdDir
      && /\bsubsystem\b/.test(n.contextValue ?? "")
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
  projectRootFor: (folder: vscode.WorkspaceFolder) => string,
  panelColumnFor?: (uri: vscode.Uri) => vscode.ViewColumn | undefined
): {
  typeCandidates: () => Promise<string[]>;
  interfaceComponents: () => Promise<Array<{ name: string; yamlPath: string }>>;
  formOwnerByPath: (yamlPath: string) => Promise<{ name: string; kind: string; yamlPath: string } | undefined>;
  projectEnums: () => Promise<Record<string, string[]>>;
} {
  const provider = new XbslMetadataProvider(projectRootFor);
  sessionProvider = provider; // the panels ask the project language through it
  panelColumnFn = panelColumnFor; // where a form's own designer panel sits, when one is open
  const view = vscode.window.createTreeView("xbslMetadata", {
    treeDataProvider: provider,
    // A button of our own instead of the built-in one: that collapses the project root too,
    // leaving a single line in the tree and two clicks back to the metadata kinds.
    showCollapseAll: false,
    // An object dragged onto a subsystem or a package moves there (the engine's move).
    dragAndDropController: new MetadataDragAndDrop(provider),
  });
  provider.attachView(view); // reveal requires access to the tree view
  // Collapse everything but keep the root open: the list of metadata kinds is what the tree is
  // opened for, and hiding it buys nothing.
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.metadata.collapse", async () => {
      await vscode.commands.executeCommand("list.collapseAll");
      await provider.expandRoots();
    })
  );
  const savedMode = context.globalState.get<GroupMode>(GROUP_MODE_KEY);
  if (savedMode === "kind" || savedMode === "subsystem") {
    provider.setGroupMode(savedMode);
  }
  const savedHide = context.globalState.get<boolean>(HIDE_EMPTY_KEY) ?? false;
  provider.setHideEmpty(savedHide);
  void vscode.commands.executeCommand("setContext", HIDE_EMPTY_CONTEXT, savedHide);

  const watcher = vscode.workspace.createFileSystemWatcher("**/*.{yaml,xbsl}");
  // Resource files carry arbitrary extensions - watched by their folder, not by type.
  const resourceWatcher = vscode.workspace.createFileSystemWatcher("**/{Ресурсы,Resources}/**");
  let timer: NodeJS.Timeout | undefined;
  let structural = false;
  // `reshapes` - files appeared or disappeared (or a descriptor changed, which renames a
  // subsystem or a project): the engine is asked for the placement again. A change of content
  // re-reads the model but keeps the placement - no folder moved.
  const bump = (reshapes: boolean) => {
    structural = structural || reshapes;
    if (timer) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = undefined;
      const changedSet = structural;
      structural = false;
      provider.refresh(changedSet);
    }, 300);
  };
  const DESCRIPTORS = new Set(["Проект.yaml", "Project.yaml", "Подсистема.yaml", "Subsystem.yaml"]);
  watcher.onDidCreate(() => bump(true));
  watcher.onDidDelete(() => bump(true));
  watcher.onDidChange((uri) => bump(DESCRIPTORS.has(path.basename(uri.fsPath))));
  // A changed file keeps its node; only appearing and disappearing files reshape the tree.
  resourceWatcher.onDidCreate(() => bump(true));
  resourceWatcher.onDidDelete(() => bump(true));

  context.subscriptions.push(
    view,
    watcher,
    resourceWatcher,
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
    vscode.commands.registerCommand(
      "xbsl.metadata.previewResource",
      (filePath?: string, key?: string) => openResourcePreview(filePath, key)
    ),
    vscode.commands.registerCommand("xbsl.metadata.openYaml", (n?: XbslNode) => openFile(n?.yamlPath)),
    vscode.commands.registerCommand("xbsl.metadata.openModule", (n?: XbslNode) => openFile(n?.modulePath)),
    vscode.commands.registerCommand("xbsl.metadata.openQuery", (n?: XbslNode) => openFile(n?.queryPath)),
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
    vscode.commands.registerCommand("xbsl.metadata.addRoute", (n?: XbslNode) => addRoute(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addRouteMethod", (n?: XbslNode) => addRouteMethod(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addObjectForm", (n?: XbslNode) => addObjectForm(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.deleteObject", (n?: XbslNode) => deleteObject(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addSubsystem", (n?: XbslNode) => addSubsystem(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.addPackage", (n?: XbslNode) => addPackage(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.renamePackage", (n?: XbslNode) => renamePackage(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.moveToPackage", (n?: XbslNode) => moveToPackage(provider, n)),
    vscode.commands.registerCommand("xbsl.metadata.filterBySubsystem", () => filterBySubsystem(provider)),
    vscode.commands.registerCommand("xbsl.metadata.clearFilter", () => provider.setFilter([])),
    vscode.commands.registerCommand("xbsl.metadata.groupMode", () => pickGroupMode(provider, context)),
    vscode.commands.registerCommand("xbsl.metadata.hideEmptyCategories", () => setEmptyHidden(provider, context, true)),
    vscode.commands.registerCommand("xbsl.metadata.showEmptyCategories", () => setEmptyHidden(provider, context, false))
  );

  // Per-kind "Add <class>" commands (label = the kind; the command carries its kind, so one
  // category may offer several). Including the common form (its category is "Common forms",
  // not via CREATABLE_KINDS). The pick command serves the inline "+" of multi-kind categories.
  for (const kind of NEW_OBJECT_KINDS) {
    context.subscriptions.push(
      // Called on a category under a subsystem or a package, the object goes into that folder.
      vscode.commands.registerCommand(`xbsl.metadata.addObject.${CREATABLE_SLUG[kind]}`, (n?: XbslNode) =>
        addObject(provider, kind, folderNodeOf(n)?.folderDir)
      )
    );
  }
  context.subscriptions.push(
    vscode.commands.registerCommand("xbsl.metadata.addObjectPick", (n?: XbslNode) =>
      addObjectPick(provider, n)
    ),
    vscode.commands.registerCommand("xbsl.metadata.addLocalization", (n?: XbslNode) =>
      addLocalization(provider, n)
    )
  );

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
