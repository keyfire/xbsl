// Дерево метаданных проекта 1С:Элемент (своя иконка на Activity Bar): корень – проект (правый
// клик открывает модуль приложения Проект.xbsl), под ним элементы сгруппированы по виду
// (ВидЭлемента) – справочники, общие модули, регистры и т.п. У объектов раскрываются поддеревья:
// Реквизиты / Измерения / Ресурсы / Табличные части / Формы; в реквизиты/измерения/ресурсы
// можно добавить поле. Клик: общий модуль -> xbsl, форма -> предпросмотр, объект -> описание.
// Формы объекта/списка вложены под владельца, формы без владельца – в раздел "Общие формы".
//
// Иконки – codicon (родные для VS Code). Целевой набор под замену на свой SVG (Material Symbols,
// Rounded, Apache-2.0) описан в README расширения. Разбор и вставка полей – чистый metadataCore.

import { randomUUID } from "crypto";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import {
  MetaField,
  MetaInternals,
  newObjectYaml,
  newSubsystemYaml,
  parseInternals,
  insertItemEdit,
  insertTabularAttrEdit,
  standardAttrNames,
} from "./metadataCore";

// Вид элемента -> группа в дереве + codicon. Несколько видов могут делить одну группу. Название
// группы – английский ключ: он и группирует, и служит ключом l10n (в англ. UI бандл не грузится и
// показывается сам ключ; ru-перевод – в bundle.l10n.ru.json). Метки нижних поддеревьев см. ADD_SPECS.
const KIND_ROWS: ReadonlyArray<readonly [kind: string, group: string, icon: string]> = [
  ["Справочник", "Catalogs", "book"],
  ["Документ", "Documents", "note"],
  ["Перечисление", "Enumerations", "symbol-enum"],
  ["Структура", "Structures", "symbol-structure"],
  ["ХранимаяСтруктура", "Stored structures", "symbol-structure"],
  ["НаборКонстант", "Constant sets", "symbol-constant"],
  ["РегистрСведений", "Information registers", "table"],
  ["РегистрНакопления", "Accumulation registers", "graph"],
  ["ВиртуальнаяТаблица", "Virtual tables", "table"],
  ["ОбщийМодуль", "Common modules", "file-code"],
  ["HttpСервис", "HTTP services", "globe"],
  ["SoapСервис", "SOAP services", "server"],
  ["КлиентSoapСервиса", "SOAP services", "server"],
  ["КонтрактСервиса", "Contracts", "symbol-interface"],
  ["КонтрактТипа", "Contracts", "symbol-interface"],
  ["КонтрактСущности", "Contracts", "symbol-interface"],
  ["ГлобальноеКлиентскоеСобытие", "Client events", "zap"],
  ["СобытиеЖурналаСобытий", "Event-log events", "history"],
  ["ЗапланированноеЗадание", "Scheduled jobs", "clock"],
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

const FORM_KIND = "КомпонентИнтерфейса";
// Английские ключи-метки (см. комментарий к KIND_ROWS): показываются через l10n.t.
const OTHER_GROUP = "Other";
const COMMON_FORMS_GROUP = "Common forms";
const COMMON_FORMS_ORDER = 8000;
const OTHER_ORDER = 9000;

// Пополняемая группа: yaml-секция (русский ключ, не переводится), подпись (английский ключ l10n),
// иконка, токен меню, форма нового элемента.
interface AddSpec {
  section: string;
  label: string; // английский ключ l10n метки поддерева (показ через l10n.t)
  icon: string;
  token: string;
  defaultName: string;
  noun: string; // ключ l10n (родительный падеж): "attribute" -> "реквизита"
  lines: (uuid: string, name: string) => string[];
}

const WITH_TYPE = (uuid: string, name: string): string[] => [`Ид: ${uuid}`, `Имя: ${name}`, `Тип: Строка`];

const ADD_SPECS: Record<string, AddSpec> = {
  attr: { section: "Реквизиты", label: "Attributes", icon: "symbol-field", token: "addattr", defaultName: "НовыйРеквизит", noun: "attribute", lines: WITH_TYPE },
  dim: { section: "Измерения", label: "Dimensions", icon: "key", token: "adddim", defaultName: "НовоеИзмерение", noun: "dimension", lines: WITH_TYPE },
  res: { section: "Ресурсы", label: "Resources", icon: "symbol-numeric", token: "addres", defaultName: "НовыйРесурс", noun: "resource", lines: WITH_TYPE },
  enum: { section: "Элементы", label: "Values", icon: "symbol-enum", token: "addval", defaultName: "НовоеЗначение", noun: "enum value", lines: (uuid, name) => [`Ид: ${uuid}`, `Имя: ${name}`] },
  param: { section: "Параметры", label: "Parameters", icon: "settings", token: "addparam", defaultName: "НовыйПараметр", noun: "parameter", lines: (_uuid, name) => [`Имя: ${name}`, `Тип: Строка`] },
  structfield: { section: "Поля", label: "Fields", icon: "symbol-field", token: "addstructfield", defaultName: "НовоеПоле", noun: "field", lines: (_uuid, name) => [`Имя: ${name}`, `Тип: Строка`] },
  tabular: {
    section: "ТабличныеЧасти",
    label: "Tabular sections",
    icon: "table",
    token: "addtabular",
    defaultName: "НоваяТабличнаяЧасть",
    noun: "tabular section",
    // Табличная часть с одним стартовым реквизитом (пустая обычно бесполезна).
    lines: (uuid, name) => [
      `Ид: ${uuid}`,
      `Имя: ${name}`,
      "Реквизиты:",
      "    -",
      `        Ид: ${randomUUID()}`,
      "        Имя: Реквизит1",
      "        Тип: Строка",
    ],
  },
};

// Вид -> пополняемые группы (порядок = порядок групп).
const KIND_ADD_GROUPS: Record<string, string[]> = {
  Справочник: ["attr", "tabular"],
  Документ: ["attr", "tabular"],
  РегистрСведений: ["dim", "res", "attr"],
  РегистрНакопления: ["dim", "res", "attr"],
  Перечисление: ["enum"],
  ПараметрыРаботыКлиента: ["param"],
  Структура: ["structfield"],
};

// Секция -> её поля из разобранной структуры.
const SECTION_FIELDS: Record<string, (it: MetaInternals) => MetaField[]> = {
  Реквизиты: (it) => it.attributes,
  Измерения: (it) => it.dimensions,
  Ресурсы: (it) => it.resources,
  Элементы: (it) => it.enumValues,
  Параметры: (it) => it.clientParams,
  Поля: (it) => it.structFields,
  ТабличныеЧасти: (it) => it.tabulars,
};

// Виды, у которых первичный артефакт – код: клик открывает xbsl, а не описание.
const CODE_KINDS = new Set(["ОбщийМодуль", "HttpСервис", "SoapСервис", "КлиентSoapСервиса"]);

// Кандидаты для поля Тип в панели свойств: примитивы + ссылки объектов + перечисления. Ссылку
// дают справочники и документы (<Имя>.Ссылка?), перечисление – <Имя>? (обычно требует nullable).
// Список открытый: панель показывает его подсказками datalist, но ввести можно любой тип.
const PRIMITIVE_TYPES = ["Строка", "Число", "Булево", "Дата", "ДатаВремя", "УникальныйИдентификатор"];
const REF_KINDS = new Set(["Справочник", "Документ"]);

// Создаваемые виды: категория показывается всегда (даже пустой), в её корне – "добавить объект".
// Шаблон минимальный и валидный; extra – доп. строки по виду, module – создать парный .xbsl.
interface NewObjectSpec {
  extra?: (name: string) => string[];
  module?: boolean;
}
const NEW_OBJECT: Record<string, NewObjectSpec> = {
  Справочник: {},
  Документ: {},
  Перечисление: {},
  Структура: { extra: () => ["Окружение: КлиентИСервер"] },
  РегистрСведений: {},
  РегистрНакопления: {},
  ПараметрыРаботыКлиента: {},
  ОбщийМодуль: { extra: () => ["Окружение: Сервер"], module: true },
  HttpСервис: { extra: (name) => [`КорневойUrl: /${name}`], module: true },
  ГлобальноеКлиентскоеСобытие: {},
  ФрагментКомандногоИнтерфейса: {},
  // Общая форма (без владельца): база + минимальная форма.
  КомпонентИнтерфейса: {
    extra: () => ["Наследует:", "    Тип: Форма", "    Содержимое:", "        Тип: Группа", "        Компоновка: Вертикальная"],
  },
};
// Категории по видам (форма – в псевдокатегории "Общие формы", а не своей категорией).
const CREATABLE_KINDS = Object.keys(NEW_OBJECT).filter((k) => k !== FORM_KIND);

// Латинский slug вида – для id по-видовой команды "Добавить <класс>" и токена меню.
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

// Осмысленное имя по умолчанию (иначе "Новый" + вид даёт неуклюжее "НовыйКомпонентИнтерфейса").
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

// Подсистема = папка с Подсистема.yaml (имя = имя папки; членство элементов – по папке).
interface Subsystem {
  name: string;
  dir: string;
}

// --- разбор исходников ------------------------------------------------------------------

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
    // Подсистема.yaml – папка-подсистема (имя не парсим, оно = имя папки).
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
    // Проект.yaml – без ВидЭлемента: отдельный корень дерева.
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

// --- узел дерева ------------------------------------------------------------------------

class XbslNode extends vscode.TreeItem {
  children?: XbslNode[];
  parent?: XbslNode; // родитель – для getParent (нужен TreeView.reveal)
  yamlPath?: string;
  modulePath?: string;
  objectModulePath?: string;
  appModulePath?: string;
  offset?: number; // смещение узла в yaml – для перехода
  addKind?: string; // группа: ключ ADD_SPECS для "добавить"
  newObjectKind?: string; // категория: вид создаваемого объекта
  ownerName?: string; // группа "Формы": объект-владелец (для добавления формы)
  codeKind?: boolean; // код-вид (модуль/HTTP-сервис): клик открывает модуль слева
  stdKind?: string; // стандартный реквизит: вид объекта (Справочник/Документ)
  stdName?: string; // стандартный реквизит: имя (Наименование/Код/Номер/Дата)
}

// Проставить ссылки на родителя по всему построенному дереву (для reveal).
function setParents(nodes: XbslNode[], parent?: XbslNode): void {
  for (const node of nodes) {
    node.parent = parent;
    if (node.children) {
      setParents(node.children, node);
    }
  }
}

// Первый узел дерева, удовлетворяющий предикату (обход в глубину, включая вложенные поля).
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
  node.resourceUri = vscode.Uri.file(node.yamlPath); // для git-статусов (цвет/бейдж), иконку держим свою
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

// Узел подсистемы в режиме "По подсистемам": сворачиваемый, несёт вложенные подсистемы и свои
// объекты (по классам). Открыть Подсистема.yaml – через контекстное меню (клик разворачивает).
function subsystemGroupNode(sub: Subsystem, children: XbslNode[]): XbslNode {
  const node = new XbslNode(
    sub.name,
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon("symbol-namespace");
  node.yamlPath = path.join(sub.dir, "Подсистема.yaml");
  node.resourceUri = vscode.Uri.file(node.yamlPath); // git-статусы
  node.contextValue = "subsystem yaml addsub";
  node.children = children;
  return node;
}

// Дети проекта в режиме "По подсистемам": дерево подсистем (по вложенности папок), под каждой – её
// объекты по классам; объекты вне подсистем – категориями в корне проекта. Членство – по папке:
// объект принадлежит САМОЙ ГЛУБОКОЙ подсистеме, чья папка является префиксом его пути.
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
      ...categoriesOf(elemsBySub.get(s.dir) ?? [], false),
    ]);
  return [...topSubs.sort(byName).map(buildSub), ...categoriesOf(rootElems, false)];
}

function projectNode(project: Project, children: XbslNode[], filterNames: string[]): XbslNode {
  const node = new XbslNode(project.name, vscode.TreeItemCollapsibleState.Expanded);
  node.iconPath = new vscode.ThemeIcon("project");
  node.resourceUri = vscode.Uri.file(path.join(project.dir, "Проект.yaml")); // git-статусы
  // Серым рядом – Поставщик\Имя из Проект.yaml; при отборе добавляем его перечень.
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
  // group – английский ключ (он же ключ группировки); показываем перевод, ключ не меняем.
  const node = new XbslNode(
    vscode.l10n.t(group),
    children.length ? vscode.TreeItemCollapsibleState.Collapsed : vscode.TreeItemCollapsibleState.None
  );
  node.iconPath = new vscode.ThemeIcon(icon);
  node.description = String(children.length);
  node.newObjectKind = createKind;
  // Токен newobj-<slug> включает нужную по-видовую команду "Добавить <класс>".
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
  // Клик: описание слева (курсор на поле), панель свойств – справа.
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  return node;
}

// Узел табличной части: как поле, но с действием "+ добавить реквизит" (маркер addtcattr).
function tabularNode(tc: MetaField, yamlPath: string): XbslNode {
  const node = fieldNode(tc, yamlPath, "table");
  node.contextValue = "member field props addtcattr";
  return node;
}

// Узел стандартного реквизита (Наименование/Код/Номер/Дата): материализован (есть в Реквизиты) – со
// смещением записи, иначе синтетический (значения по умолчанию, серым "(по умолчанию)"). Клик открывает
// описание слева + панель свойств справа; правка синтетического материализует запись в yaml.
function standardAttrNode(kind: string, name: string, yamlPath: string, internals?: MetaInternals): XbslNode {
  const offset = internals?.attributes.find((a) => a.name === name)?.offset;
  const node = new XbslNode(name, vscode.TreeItemCollapsibleState.None);
  node.iconPath = new vscode.ThemeIcon("symbol-field");
  node.yamlPath = yamlPath;
  node.offset = offset; // undefined – синтетический
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
  // У табличных частей дети – ТЧ с добавлением реквизита; у прочих групп – обычные поля.
  node.children = fields.map((f) => (addKind === "tabular" ? tabularNode(f, yamlPath) : fieldNode(f, yamlPath, spec.icon)));
  return node;
}

// Группа только для просмотра (табличные части, шаблоны URL): без "добавить". label – английский
// ключ l10n.
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
  node.resourceUri = vscode.Uri.file(el.yamlPath); // git-статусы
  node.modulePath = el.modulePath;
  node.contextValue = ["member", "form", "yaml", el.modulePath ? "xbsl" : ""].filter(Boolean).join(" ");
  node.command = { command: "xbsl.metadata.previewForm", title: "", arguments: [node] };
  node.tooltip = FORM_KIND;
  return node;
}

// Группа "Формы". Для справочника/документа можно добавить форму объекта (canAddForm) – тогда
// группа показывается всегда и несёт владельца.
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
    // Стандартные реквизиты показываем в своей группе – из обычных Реквизитов их убираем (без дублей).
    if (key === "attr" && stdNames.size) {
      fields = fields.filter((f) => !stdNames.has(f.name));
    }
    groups.push(addGroupNode(key, el.yamlPath, fields));
  }
  if (internals) {
    // Табличные части справочника/документа – через KIND_ADD_GROUPS (с добавлением); здесь только
    // группы без добавления.
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
  node.iconPath = new vscode.ThemeIcon(metaFor(el.kind).icon);
  node.yamlPath = el.yamlPath;
  node.resourceUri = vscode.Uri.file(el.yamlPath); // git-статусы (цвет/бейдж), иконку держим свою
  node.modulePath = el.modulePath;
  node.objectModulePath = el.objectModulePath;
  node.offset = internals?.rootOffset; // корень объекта – для панели свойств
  node.children = groups;
  node.contextValue = ["element", "yaml", "props", "deletable", el.modulePath ? "xbsl" : "", el.objectModulePath ? "objmod" : ""]
    .filter(Boolean)
    .join(" ");
  node.codeKind = CODE_KINDS.has(el.kind);
  // Клик: исходник слева (модуль код-видов или описание), панель свойств – справа.
  node.command = { command: "xbsl.metadata.openWithProps", title: "", arguments: [node] };
  node.tooltip = el.kind;
  return node;
}

// --- построение модели ------------------------------------------------------------------

// Категории (по виду) для набора элементов, включая раздел "Общие формы". Пустые создаваемые
// категории показываем только без отбора (showEmptyCreatable) – при отборе они лишний шум.
function categoriesOf(elements: Element[], showEmptyCreatable: boolean): XbslNode[] {
  const forms = elements.filter((e) => e.kind === FORM_KIND);
  const objects = elements.filter((e) => e.kind !== FORM_KIND);
  const elementNames = new Set(objects.map((e) => e.name));

  const declaredOwner = new Map<string, string>();
  for (const obj of objects) {
    let m: RegExpExecArray | null;
    RE_DECLARED_FORM.lastIndex = 0;
    while ((m = RE_DECLARED_FORM.exec(obj.text))) {
      declaredOwner.set(m[1], obj.name);
    }
  }

  const ownerOf = (form: Element): string | undefined => {
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
  // Создаваемые виды: помечаем "добавить объект"; пустые показываем только без отбора.
  for (const kind of CREATABLE_KINDS) {
    const meta = metaFor(kind);
    const existing = cats.get(meta.group);
    if (!existing && !showEmptyCreatable) {
      continue;
    }
    const cat = existing ?? { icon: meta.icon, order: meta.order, elements: [] };
    cat.createKind = kind;
    cats.set(meta.group, cat);
  }

  const roots = [...cats.entries()].map(([group, cat]) => ({
    order: cat.order,
    node: categoryNode(group, cat.icon, cat.elements, cat.createKind),
  }));

  // Общие формы – псевдокатегория; "добавить" создаёт форму без владельца. Показываем всегда
  // (как создаваемые), кроме активного отбора без общих форм.
  const commonFormNodes = [...commonForms].sort(byName).map(formNode);
  if (commonFormNodes.length || showEmptyCreatable) {
    roots.push({
      order: COMMON_FORMS_ORDER,
      node: categoryNode(COMMON_FORMS_GROUP, "window", commonFormNodes, FORM_KIND),
    });
  }

  roots.sort((a, b) => a.order - b.order || String(a.node.label).localeCompare(String(b.node.label), "ru"));
  return roots.map((r) => r.node);
}

type GroupMode = "kind" | "subsystem";

function buildRoots(model: Model, filterDirs: Set<string>, mode: GroupMode): XbslNode[] {
  const filterActive = filterDirs.size > 0;
  const underFilter = (p: string): boolean =>
    [...filterDirs].some((d) => p.toLowerCase().startsWith(d.toLowerCase() + path.sep));
  const elements = filterActive ? model.elements.filter((el) => underFilter(el.yamlPath)) : model.elements;
  const showEmpty = !filterActive;

  // Дети проекта: "По классам" – ветка Подсистемы + категории по видам; "По подсистемам" – дерево
  // подсистем с объектами под ними.
  const childrenOf = (elems: Element[], subs: Subsystem[]): XbslNode[] =>
    mode === "subsystem"
      ? subsystemModeChildren(subs, elems)
      : [subsystemsBranchNode(subs), ...categoriesOf(elems, showEmpty)];

  if (model.projects.length === 0) {
    // Не нашли Проект.yaml – без корня проекта.
    return mode === "subsystem" ? subsystemModeChildren(model.subsystems, elements) : categoriesOf(elements, showEmpty);
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

// --- провайдер --------------------------------------------------------------------------

class XbslMetadataProvider implements vscode.TreeDataProvider<XbslNode> {
  private readonly emitter = new vscode.EventEmitter<XbslNode | undefined | void>();
  readonly onDidChangeTreeData = this.emitter.event;
  private roots?: XbslNode[];
  private model?: Model;
  private filter = new Set<string>(); // каталоги подсистем активного отбора
  private groupMode: GroupMode = "kind"; // иерархия дерева: по классам или по подсистемам
  private treeView?: vscode.TreeView<XbslNode>; // для reveal (getParent обязателен)
  private pendingReveal?: (n: XbslNode) => boolean; // показать этот узел после перестроения

  constructor(private readonly projectRootFor: (folder: vscode.WorkspaceFolder) => string) {}

  // Дерево создаётся отдельно (нужен доступ к reveal); связываем после создания.
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

  getTreeItem(node: XbslNode): vscode.TreeItem {
    return node;
  }

  getParent(node: XbslNode): XbslNode | undefined {
    return node.parent;
  }

  private async buildRootsIfNeeded(): Promise<XbslNode[]> {
    if (!this.roots) {
      this.model = await parseModel(this.projectRootFor);
      this.roots = buildRoots(this.model, this.filter, this.groupMode);
      setParents(this.roots, undefined);
    }
    return this.roots;
  }

  async getChildren(node?: XbslNode): Promise<XbslNode[]> {
    if (node) {
      return node.children ?? [];
    }
    const roots = await this.buildRootsIfNeeded();
    // Отложенный показ (после добавления объекта/поля) – когда свежее дерево построено.
    if (this.pendingReveal) {
      setTimeout(() => void this.flushReveal(), 0);
    }
    return roots;
  }

  // Куда класть новый объект: подсистемы (папки) и корень проекта.
  async placements(): Promise<{ subsystems: Subsystem[]; projectDir?: string }> {
    if (!this.model) {
      this.model = await parseModel(this.projectRootFor);
    }
    return { subsystems: this.model.subsystems, projectDir: this.model.projects[0]?.dir };
  }

  // Кандидаты типа для панели свойств (комбобокс Тип): примитивы, затем ссылки объектов
  // (<Имя>.Ссылка?) и перечисления (<Имя>?), каждая группа по алфавиту. Список открытый.
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

  // Показать (выделить) узел в дереве после перестроения – для добавления объекта/поля: новый
  // узел появится только в свежих roots, поэтому reveal откладываем до их построения.
  requestReveal(pred: (n: XbslNode) => boolean): void {
    this.pendingReveal = pred;
    // Держим отбор reveal короткое окно: показ должен пережить повторное перестроение от файлового
    // наблюдателя (сохранение файла → refresh ~300 мс). По истечении окна снимаем.
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
      return; // узел не отображается (напр. под отбором) – молча выходим
    }
    // pendingReveal НЕ снимаем здесь – пусть показ переживёт перестроение наблюдателя (снимет таймер).
    try {
      await this.treeView.reveal(node, { select: true, focus: false });
    } catch {
      // reveal может отказать (дерево ещё не готово) – не критично
    }
  }

  // Показать в дереве элемент активного редактора – без перестроения дерева. Синхронизируем,
  // только когда дерево на виду, чтобы не выдёргивать его на каждый переход по редакторам.
  async revealForUri(uri: vscode.Uri): Promise<void> {
    if (this.pendingReveal) {
      return; // идёт показ только что добавленного узла (поля/объекта) – не перебиваем его
    }
    if (!this.treeView?.visible) {
      return;
    }
    const fsPath = uri.fsPath;
    // Уже выбран узел этого же файла (или его поле) – не перебиваем выбор пользователя: иначе клик по
    // полю (открывает yaml объекта) перебросил бы выделение на родителя-объект.
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

// --- команды и регистрация --------------------------------------------------------------

// Колонка редактора для исходников (yaml/xbsl): где уже открыт этот файл, иначе где открыт любой
// исходник, иначе – левая. Так описания/модули держатся слева, а панели предпросмотра/свойств
// уходят вправо (Beside), и повторные клики не плодят колонки.
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
  // yaml – в колонке исходников (слева, в фокусе), предпросмотр открываем панелью справа (Beside).
  await openFile(node.yamlPath);
  await vscode.commands.executeCommand("xbsl.previewForm", vscode.Uri.file(node.yamlPath));
}

// Клик по объекту/полю/модулю: исходник слева (описание с курсором на узле, или модуль код-видов),
// панель свойств – справа. У модуля исходник – его .xbsl, но свойства (описание) всё равно показываем.
async function openWithProps(node?: XbslNode): Promise<void> {
  if (!node) {
    return;
  }
  if (node.codeKind && node.modulePath) {
    await openFile(node.modulePath); // модуль слева
  } else if (node.yamlPath) {
    await reveal(node); // описание слева + курсор на узле (offset)
  }
  if (node.yamlPath && (node.offset !== undefined || node.stdName)) {
    await vscode.commands.executeCommand("xbsl.metadata.props", node); // свойства справа
  }
}

const IDENTIFIER = /^[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё0-9_]*$/;

async function addItem(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const spec = node?.addKind ? ADD_SPECS[node.addKind] : undefined;
  if (!node?.yamlPath || !spec) {
    return;
  }
  const name = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Name of the new element ({0})", vscode.l10n.t(spec.noun)),
    value: spec.defaultName,
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (!name) {
    return;
  }
  const uri = vscode.Uri.file(node.yamlPath);
  const doc = await vscode.workspace.openTextDocument(uri);
  const edit = insertItemEdit(doc.getText(), spec.section, spec.lines(randomUUID(), name.trim()));
  const we = new vscode.WorkspaceEdit();
  we.insert(uri, doc.positionAt(edit.start), edit.newText);
  await vscode.workspace.applyEdit(we);
  await doc.save();
  // Показать вставленное поле: и в дереве (reveal после перестроения), и в редакторе (курсор на строке).
  const yamlPath = node.yamlPath;
  const newName = name.trim();
  provider.requestReveal(
    (n) => n.yamlPath === yamlPath && String(n.label) === newName && /\bfield\b/.test(n.contextValue ?? "")
  );
  const editor = await vscode.window.showTextDocument(doc, { viewColumn: sourceColumn(uri), preview: false });
  const pos = doc.positionAt(edit.start + edit.newText.length);
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

// Добавить реквизит в табличную часть: вставка во вложенную секцию Реквизиты этой ТЧ (по смещению).
async function addTabularAttr(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  if (!node?.yamlPath || node.offset === undefined) {
    return;
  }
  const name = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Name of the new element ({0})", vscode.l10n.t("attribute")),
    value: "НовыйРеквизит",
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (!name) {
    return;
  }
  const uri = vscode.Uri.file(node.yamlPath);
  const doc = await vscode.workspace.openTextDocument(uri);
  const edit = insertTabularAttrEdit(doc.getText(), node.offset, [
    `Ид: ${randomUUID()}`,
    `Имя: ${name.trim()}`,
    `Тип: Строка`,
  ]);
  const we = new vscode.WorkspaceEdit();
  we.insert(uri, doc.positionAt(edit.start), edit.newText);
  await vscode.workspace.applyEdit(we);
  await doc.save();
  const yamlPath = node.yamlPath;
  const newName = name.trim();
  provider.requestReveal(
    (n) => n.yamlPath === yamlPath && String(n.label) === newName && /\bfield\b/.test(n.contextValue ?? "")
  );
  const editor = await vscode.window.showTextDocument(doc, { viewColumn: sourceColumn(uri), preview: false });
  const pos = doc.positionAt(edit.start + edit.newText.length);
  editor.selection = new vscode.Selection(pos, pos);
  editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

interface Placement extends vscode.QuickPickItem {
  dir: string;
}

async function addObject(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const kind = node?.newObjectKind;
  if (!kind) {
    return;
  }
  const spec = NEW_OBJECT[kind] ?? {};
  const name = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Name of the new object ({0})", kind),
    value: NEW_OBJECT_DEFAULT[kind] ?? "Новый" + kind,
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (!name) {
    return;
  }
  const objectName = name.trim();

  // Куда положить: подсистема (папка) или корень проекта.
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

  const yamlPath = path.join(dir, objectName + ".yaml");
  if (fs.existsSync(yamlPath)) {
    void vscode.window.showWarningMessage(vscode.l10n.t('XBSL: "{0}" already exists.', yamlPath));
    return;
  }
  const we = new vscode.WorkspaceEdit();
  const extra = spec.extra ? spec.extra(objectName) : [];
  we.createFile(vscode.Uri.file(yamlPath), {
    contents: Buffer.from(newObjectYaml(kind, randomUUID(), objectName, extra), "utf8"),
    ignoreIfExists: false,
  });
  if (spec.module) {
    we.createFile(vscode.Uri.file(path.join(dir, objectName + ".xbsl")), {
      contents: Buffer.from(`// ${objectName}\n`, "utf8"),
      ignoreIfExists: false,
    });
  }
  await vscode.workspace.applyEdit(we);
  provider.requestReveal((n) => n.yamlPath === yamlPath && /\belement\b/.test(n.contextValue ?? ""));
  await openFile(yamlPath);
}

// Добавить форму объекта справочнику/документу: файл ФормаОбъекта<Владелец.Объект> + регистрация
// в Интерфейс.Объект.Форма (только если секции Интерфейс ещё нет – иначе просим сделать вручную).
async function addObjectForm(provider: XbslMetadataProvider, node?: XbslNode): Promise<void> {
  const owner = node?.ownerName;
  const ownerYaml = node?.yamlPath;
  if (!owner || !ownerYaml) {
    return;
  }
  const name = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Name of the new form"),
    value: owner + "ФормаОбъекта",
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (!name) {
    return;
  }
  const formName = name.trim();
  const formPath = path.join(path.dirname(ownerYaml), formName + ".yaml");
  if (fs.existsSync(formPath)) {
    void vscode.window.showWarningMessage(vscode.l10n.t('XBSL: "{0}" already exists.', formPath));
    return;
  }
  const we = new vscode.WorkspaceEdit();
  const formYaml = newObjectYaml("КомпонентИнтерфейса", randomUUID(), formName, [
    "Наследует:",
    `    Тип: ФормаОбъекта<${owner}.Объект>`,
    "    Содержимое:",
    "        Тип: Группа",
    "        Компоновка: Вертикальная",
  ]);
  we.createFile(vscode.Uri.file(formPath), { contents: Buffer.from(formYaml, "utf8"), ignoreIfExists: false });
  const ownerDoc = await vscode.workspace.openTextDocument(vscode.Uri.file(ownerYaml));
  const ownerText = ownerDoc.getText();
  if (!/^Интерфейс:/m.test(ownerText)) {
    const nl = ownerText.endsWith("\n") ? "" : "\n";
    we.insert(
      vscode.Uri.file(ownerYaml),
      ownerDoc.positionAt(ownerText.length),
      `${nl}Интерфейс:\n    Объект:\n        Форма: ${formName}\n`
    );
  } else {
    void vscode.window.showInformationMessage(
      vscode.l10n.t("XBSL: {0} already has an Интерфейс section – register the form there manually.", owner)
    );
  }
  await vscode.workspace.applyEdit(we);
  provider.requestReveal((n) => n.yamlPath === formPath && /\bform\b/.test(n.contextValue ?? ""));
  await openFile(formPath);
}

// Удалить объект: его файлы (yaml + модуль + модуль объекта). Ссылки не обновляются –
// оборванные ловит линтер/деплой. С подтверждением; удаление обратимо (VS Code undo).
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
  const name = await vscode.window.showInputBox({
    prompt: vscode.l10n.t("Name of the new subsystem"),
    value: "НоваяПодсистема",
    validateInput: (v) =>
      IDENTIFIER.test(v.trim()) ? undefined : vscode.l10n.t("A valid identifier is required (letters, digits, _)."),
  });
  if (!name) {
    return;
  }
  const yamlPath = path.join(parent, name.trim(), "Подсистема.yaml");
  if (fs.existsSync(yamlPath)) {
    void vscode.window.showWarningMessage(vscode.l10n.t('XBSL: "{0}" already exists.', yamlPath));
    return;
  }
  const we = new vscode.WorkspaceEdit();
  we.createFile(vscode.Uri.file(yamlPath), {
    contents: Buffer.from(newSubsystemYaml(name.trim()), "utf8"),
    ignoreIfExists: false,
  });
  await vscode.workspace.applyEdit(we);
  provider.requestReveal((n) => n.yamlPath === yamlPath && /\bsubsystem\b/.test(n.contextValue ?? ""));
  await openFile(yamlPath);
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
    return; // отмена – отбор не трогаем
  }
  provider.setFilter(picks.map((p) => p.dir));
}

const GROUP_MODE_KEY = "xbsl.metadata.groupMode";

// Выбор иерархии дерева: по классам объектов или по подсистемам; выбор запоминается.
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
): { typeCandidates: () => Promise<string[]> } {
  const provider = new XbslMetadataProvider(projectRootFor);
  const view = vscode.window.createTreeView("xbslMetadata", {
    treeDataProvider: provider,
    showCollapseAll: true,
  });
  provider.attachView(view); // reveal требует доступ к дереву
  const savedMode = context.globalState.get<GroupMode>(GROUP_MODE_KEY);
  if (savedMode === "kind" || savedMode === "subsystem") {
    provider.setGroupMode(savedMode);
  }

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
    // Обратная навигация: активный редактор описания/модуля/формы – показать его элемент в дереве.
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
    vscode.commands.registerCommand("xbsl.metadata.groupMode", () => pickGroupMode(provider, context))
  );

  // По-видовые команды "Добавить <класс>" (метка = вид; создаёт addObject по newObjectKind узла).
  // Включая общую форму (её категория – "Общие формы", не через CREATABLE_KINDS).
  for (const kind of Object.keys(NEW_OBJECT)) {
    context.subscriptions.push(
      vscode.commands.registerCommand(`xbsl.metadata.addObject.${CREATABLE_SLUG[kind]}`, (n?: XbslNode) =>
        addObject(provider, n)
      )
    );
  }

  // Панель свойств берёт отсюда кандидатов для комбобокса Тип (состав проекта знает провайдер).
  return { typeCandidates: () => provider.typeCandidates() };
}
