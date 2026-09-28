// Unit tests for the pure metadata core (src/metadataCore.ts). No test runner and no vscode:
// plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import { parseDocument } from "yaml";
import {
  COMPONENT_MEMBER_SPECS,
  componentMemberNames,
  componentMemberRequest,
  componentMemberTypeChoices,
  describeMetaNode,
  describeStandardAttr,
  existingModule,
  existingRowModules,
  hintName,
  insertItemEdit,
  MODULE_TAIL_ENGLISH,
  MODULE_TAILS,
  moduleMenuTokens,
  ModuleTail,
  modulePathFor,
  moduleTailsOf,
  parseInternals,
  ROW_MODULE_KINDS,
  rowModuleMenuTokens,
  rowModulePathFor,
  SERIALIZER_KIND_SPELLINGS,
  setMetaKeyAliases,
  stringAttributeNames,
  translationRef,
} from "../src/metadataCore";

let failed = 0;
let passed = 0;

function test(name: string, fn: () => void): void {
  try {
    fn();
    passed++;
    console.log(`ok   ${name}`);
  } catch (e) {
    failed++;
    console.error(`FAIL ${name}`);
    console.error(e instanceof Error ? e.message : e);
  }
}

function apply(text: string, e: { start: number; end: number; newText: string }): string {
  return text.slice(0, e.start) + e.newText + text.slice(e.end);
}

function parses(text: string): boolean {
  return parseDocument(text, { uniqueKeys: false }).errors.length === 0;
}

const CATALOG = `ВидЭлемента: Справочник
Ид: aaa
Имя: Товар
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Имя: Наименование
        Длина: 250
    -
        Ид: bbb
        Имя: Цена
        Тип: Число
ТабличныеЧасти:
    -
        Ид: ccc
        Имя: Строки
        Реквизиты:
            -
                Ид: ddd
                Имя: Количество
                Тип: Число
`;

const REGISTER = `ВидЭлемента: РегистрСведений
Ид: rrr
Имя: Курсы
Измерения:
    -
        Ид: m1
        Имя: Валюта
        Тип: Строка
Ресурсы:
    -
        Ид: r1
        Имя: Курс
        Тип: Число
`;

const ENUM = `ВидЭлемента: Перечисление
Ид: eee
Имя: Цвет
Элементы:
    -
        Ид: e1
        Имя: Красный
    -
        Ид: e2
        Имя: Зеленый
`;

const HTTP = `ВидЭлемента: HttpСервис
Ид: hhh
Имя: Апи
КорневойUrl: /api
ШаблоныUrl:
    -
        Имя: Пинг
        Шаблон: /ping
        Методы:
            -
                Метод: GET
                Обработчик: Пинг
`;

const CLIENT_PARAMS = `ВидЭлемента: ПараметрыРаботыКлиента
Ид: ppp
Имя: Настройки
Параметры:
    -
        Имя: Адрес
        Тип: Строка
`;

const attr = (uuid: string, name: string): string[] => [`Ид: ${uuid}`, `Имя: ${name}`, `Тип: Строка`];

// --- parseInternals -----------------------------------------------------------------------

test("parseInternals: реквизиты справочника – имена, типы, смещения", () => {
  const it = parseInternals(CATALOG)!;
  assert.deepStrictEqual(it.attributes.map((a) => a.name), ["Наименование", "Цена"]);
  assert.strictEqual(it.attributes[1].type, "Число");
  assert.ok(typeof it.attributes[0].offset === "number");
});

test("parseInternals: табличная часть несёт свои реквизиты", () => {
  const it = parseInternals(CATALOG)!;
  assert.deepStrictEqual(it.tabulars[0].children!.map((c) => c.name), ["Количество"]);
});

test("parseInternals: измерения и ресурсы регистра", () => {
  const it = parseInternals(REGISTER)!;
  assert.deepStrictEqual(it.dimensions.map((d) => d.name), ["Валюта"]);
  assert.deepStrictEqual(it.resources.map((r) => r.name), ["Курс"]);
});

test("parseInternals: значения перечисления (без типа)", () => {
  const it = parseInternals(ENUM)!;
  assert.deepStrictEqual(it.enumValues.map((v) => v.name), ["Красный", "Зеленый"]);
  assert.strictEqual(it.enumValues[0].type, undefined);
});

test("parseInternals: шаблоны URL с методами", () => {
  const it = parseInternals(HTTP)!;
  assert.strictEqual(it.urlTemplates.length, 1);
  assert.strictEqual(it.urlTemplates[0].name, "Пинг");
  assert.strictEqual(it.urlTemplates[0].type, "/ping");
  assert.deepStrictEqual(it.urlTemplates[0].children!.map((m) => `${m.name}->${m.type}`), ["GET->Пинг"]);
});

// An English project is legal code: the platform spells every section two ways, and the pairs
// come from the engine (`xbsl/metaKeys`), not from a table written here. Before they arrive the
// reader knows Russian keys only - that is the "empty branches" state this pair of tests pins.
const CATALOG_EN = `Ид: 019f0000-0000-0000-0000-000000000001
Name: Goods
ElementKind: Catalog
Attributes:
    -
        Name: Title
        Type: String
    -
        Name: Price
        Type: Number
TabularParts:
    -
        Name: Lines
        Attributes:
            -
                Name: Quantity
                Type: Number
`;

test("parseInternals: английский объект без пар - ветки пусты", () => {
  setMetaKeyAliases({});
  const it = parseInternals(CATALOG_EN)!;
  assert.strictEqual(it.attributes.length, 0);
  assert.strictEqual(it.tabulars.length, 0);
});

test("parseInternals: с парами движка английские секции читаются", () => {
  // Exactly the shape `xbsl/metaKeys` answers: {English spelling: the Russian key}.
  setMetaKeyAliases({ Attributes: "Реквизиты", TabularParts: "ТабличныеЧасти" });
  try {
    const it = parseInternals(CATALOG_EN)!;
    assert.deepStrictEqual(it.attributes.map((a) => a.name), ["Title", "Price"]);
    assert.strictEqual(it.attributes[1].type, "Number");
    // The nested collection uses the same lookup - a tabular section spells its own Attributes.
    assert.deepStrictEqual(it.tabulars.map((t) => t.name), ["Lines"]);
    assert.deepStrictEqual(it.tabulars[0].children!.map((c) => c.name), ["Quantity"]);
  } finally {
    setMetaKeyAliases({}); // the map is module state - do not leak it into the tests below
  }
});

test("parseInternals: пары не ломают русский объект", () => {
  setMetaKeyAliases({ Attributes: "Реквизиты", TabularParts: "ТабличныеЧасти" });
  try {
    const it = parseInternals(CATALOG)!;
    assert.deepStrictEqual(it.attributes.map((a) => a.name), ["Наименование", "Цена"]);
    assert.deepStrictEqual(it.tabulars[0].children!.map((c) => c.name), ["Количество"]);
  } finally {
    setMetaKeyAliases({});
  }
});

test("parseInternals: параметры работы клиента", () => {
  const it = parseInternals(CLIENT_PARAMS)!;
  assert.deepStrictEqual(it.clientParams.map((p) => `${p.name}:${p.type}`), ["Адрес:Строка"]);
});

test("parseInternals: поля структуры", () => {
  const struct = `ВидЭлемента: Структура
Ид: sss
Имя: Данные
Окружение: КлиентИСервер
Поля:
    -
        Имя: Категория
        Тип: Строка
    -
        Имя: Сумма
        Тип: Число
`;
  const it = parseInternals(struct)!;
  assert.deepStrictEqual(it.structFields.map((f) => `${f.name}:${f.type}`), ["Категория:Строка", "Сумма:Число"]);
});

// --- insertItemEdit -----------------------------------------------------------------------

test("insertItemEdit: реквизит в конец существующей секции, не залезая в ТЧ", () => {
  const out = apply(CATALOG, insertItemEdit(CATALOG, "Реквизиты", attr("new-uuid", "Скидка")));
  assert.ok(parses(out), "результат должен парситься");
  const it = parseInternals(out)!;
  assert.deepStrictEqual(it.attributes.map((a) => a.name), ["Наименование", "Цена", "Скидка"]);
  assert.strictEqual(it.attributes[2].type, "Строка");
  assert.strictEqual(it.tabulars[0].name, "Строки");
});

test("insertItemEdit: измерение регистра сохраняет отступ 4/8", () => {
  const edit = insertItemEdit(REGISTER, "Измерения", attr("dim-uuid", "Организация"));
  assert.ok(edit.newText.includes("\n    -\n        Ид: dim-uuid"), edit.newText);
  const it = parseInternals(apply(REGISTER, edit))!;
  assert.deepStrictEqual(it.dimensions.map((d) => d.name), ["Валюта", "Организация"]);
});

test("insertItemEdit: значение перечисления (Ид+Имя, без типа)", () => {
  const out = apply(ENUM, insertItemEdit(ENUM, "Элементы", [`Ид: v3`, `Имя: Синий`]));
  assert.ok(parses(out), "результат должен парситься");
  assert.deepStrictEqual(parseInternals(out)!.enumValues.map((v) => v.name), ["Красный", "Зеленый", "Синий"]);
});

test("insertItemEdit: параметр клиента (Имя+Тип, без Ид)", () => {
  const out = apply(CLIENT_PARAMS, insertItemEdit(CLIENT_PARAMS, "Параметры", [`Имя: Порт`, `Тип: Число`]));
  assert.ok(parses(out), "результат должен парситься");
  assert.deepStrictEqual(parseInternals(out)!.clientParams.map((p) => p.name), ["Адрес", "Порт"]);
});

test("insertItemEdit: табличная часть с вложенными реквизитами", () => {
  const lines = ["Ид: t1", "Имя: Комплект", "Реквизиты:", "    -", "        Ид: a1", "        Имя: Кол", "        Тип: Число"];
  const out = apply(CATALOG, insertItemEdit(CATALOG, "ТабличныеЧасти", lines));
  assert.ok(parses(out), "результат должен парситься");
  const it = parseInternals(out)!;
  assert.deepStrictEqual(it.tabulars.map((t) => t.name), ["Строки", "Комплект"]);
  const added = it.tabulars.find((t) => t.name === "Комплект")!;
  assert.deepStrictEqual(added.children!.map((c) => c.name), ["Кол"]);
});

test("insertItemEdit: отсутствующая секция дописывается в конец файла", () => {
  const out = apply(REGISTER, insertItemEdit(REGISTER, "Реквизиты", attr("attr-uuid", "Комментарий")));
  assert.ok(parses(out), "результат должен парситься");
  const it = parseInternals(out)!;
  assert.deepStrictEqual(it.attributes.map((a) => a.name), ["Комментарий"]);
  assert.deepStrictEqual(it.dimensions.map((d) => d.name), ["Валюта"]);
  assert.deepStrictEqual(it.resources.map((r) => r.name), ["Курс"]);
});

// Templates of new objects, subsystems and tabular section insertions moved to the engine
// (xbsl/scaffold.py) and are checked by its pytest tests (tests/test_scaffold.py).

test("describeMetaNode: объект – заголовок, Ид/Вид только чтение, ОбластьВидимости = select", () => {
  const it = parseInternals(CATALOG)!;
  const d = describeMetaNode(CATALOG, it.rootOffset)!;
  assert.strictEqual(d.title, "Справочник");
  const byKey = Object.fromEntries(d.rows.map((r) => [r.key, r]));
  assert.strictEqual(byKey["Имя"].value, "Товар");
  assert.ok(!byKey["Имя"].readonly);
  assert.ok(byKey["Ид"].readonly);
  assert.ok(byKey["ВидЭлемента"].readonly);
  assert.strictEqual(byKey["ОбластьВидимости"].control, "select");
  assert.ok(!byKey["Реквизиты"], "коллекции не попадают в строки");
});

test("describeMetaNode: поле реквизита – Имя и Тип", () => {
  const it = parseInternals(CATALOG)!;
  const d = describeMetaNode(CATALOG, it.attributes[1].offset!)!;
  assert.strictEqual(d.title, "Цена");
  const keys = d.rows.map((r) => r.key);
  assert.ok(keys.includes("Имя") && keys.includes("Тип"));
});

test("describeMetaNode: Тип поля – комбобокс, Имя – текст", () => {
  const it = parseInternals(CATALOG)!;
  const d = describeMetaNode(CATALOG, it.attributes[1].offset!)!;
  const byKey = Object.fromEntries(d.rows.map((r) => [r.key, r]));
  assert.strictEqual(byKey["Тип"].control, "combo");
  assert.strictEqual(byKey["Тип"].value, "Число");
  assert.strictEqual(byKey["Имя"].control, "text");
});

test("describeMetaNode: Многострочная видна у Строки и скрыта у другого типа", () => {
  const doc = `ВидЭлемента: Справочник
Ид: a
Имя: Т
Реквизиты:
    -
        Ид: b
        Имя: Описание
        Тип: Строка
        Многострочная: Истина
    -
        Ид: c
        Имя: Сумма
        Тип: Число
        Многострочная: Истина
`;
  const it = parseInternals(doc)!;
  const strKeys = describeMetaNode(doc, it.attributes[0].offset!)!.rows.map((r) => r.key);
  assert.ok(strKeys.includes("Многострочная"), "у Строки Многострочная показывается");
  const numKeys = describeMetaNode(doc, it.attributes[1].offset!)!.rows.map((r) => r.key);
  assert.ok(!numKeys.includes("Многострочная"), "у Числа Многострочная скрыта");
});

test("describeStandardAttr: синтетический (нет в yaml) даёт строки спецификации", () => {
  const d = describeStandardAttr(CATALOG, "Справочник", "Код")!;
  assert.strictEqual(d.offset, -1);
  assert.deepStrictEqual(d.rows.map((r) => r.key), ["Тип", "Длина", "Уникальность"]);
  assert.ok(d.rows.every((r) => r.value === ""));
});

test("describeStandardAttr: материализованный берёт свойства из yaml", () => {
  const d = describeStandardAttr(CATALOG, "Справочник", "Наименование")!;
  assert.ok(d.offset >= 0, "материализован – реальное смещение узла");
  const byKey = Object.fromEntries(d.rows.map((r) => [r.key, r]));
  assert.strictEqual(byKey["Длина"].value, "250");
});

// -----------------------------------------------------------------------------

test("stringAttributeNames: no-Тип and Строка attributes offered, others not", () => {
  // Наименование carries no Тип (a string by construction), Цена is a Число - filtered out;
  // tabular-section attributes are not the object's own fields.
  assert.deepStrictEqual(stringAttributeNames(CATALOG), ["Наименование"]);
  const doc = `ВидЭлемента: Справочник
Ид: aaa
Имя: Товары
Реквизиты:
    -
        Ид: bbb
        Имя: Заголовок
        Тип: Строка
    -
        Ид: ccc
        Имя: Примечание
        Тип: Строка?
    -
        Ид: ddd
        Имя: Владелец
        Тип: Пользователи.Ссылка
`;
  assert.deepStrictEqual(stringAttributeNames(doc), ["Заголовок", "Примечание"]);
});

test("stringAttributeNames: no attributes - an empty list", () => {
  assert.deepStrictEqual(stringAttributeNames("ВидЭлемента: Справочник\nИмя: Пусто\n"), []);
});

test("hintName: the spelling follows the project, not the editor", () => {
  // A hint names the key the user will look for in the sources: over a Russian project the
  // key is Russian whatever language the window speaks, and over an English one it is English.
  assert.strictEqual(hintName("Имя", false), "Имя");
  assert.strictEqual(hintName("Имя", true), "Name");
  assert.strictEqual(hintName("Содержимое", true), "Content");
  assert.strictEqual(hintName("Наследует", true), "Inherits");
  assert.strictEqual(hintName("Импорт", true), "Import");
  // A name the table does not carry comes back unchanged - an invented English spelling would
  // send the user looking for a key that is not in the file.
  assert.strictEqual(hintName("Реквизиты", true), "Реквизиты");
});

test("translationRef: the section file points at the element it translates", () => {
  assert.deepStrictEqual(translationRef("D:\\proj\\Основное\\Локализация\\En\\ЛокализованныеСтроки.yaml"), {
    ownerPath: "D:\\proj\\Основное\\ЛокализованныеСтроки.yaml",
    lang: "En",
  });
  // The separator of the incoming path is kept - the caller compares the result with paths of its own.
  assert.deepStrictEqual(translationRef("/proj/Мероприятия/Локализация/En/ЛокализованныеСтроки.yaml"), {
    ownerPath: "/proj/Мероприятия/ЛокализованныеСтроки.yaml",
    lang: "En",
  });
});

test("translationRef: the section spelled in English, and the package nesting kept", () => {
  assert.deepStrictEqual(translationRef("/p/Main/Localization/En/Strings.yaml"), {
    ownerPath: "/p/Main/Strings.yaml",
    lang: "En",
  });
  // The tail after the language folder repeats where the element lies inside the subsystem.
  assert.deepStrictEqual(translationRef("/p/Основное/Локализация/En/Пакет/Строки.yaml"), {
    ownerPath: "/p/Основное/Пакет/Строки.yaml",
    lang: "En",
  });
});

test("translationRef: a path without the section is not a translation", () => {
  assert.strictEqual(translationRef("/p/Основное/ОбменЛокализация.yaml"), undefined);
  // A folder named Локализация with the file right in it: no language folder - no translation.
  assert.strictEqual(translationRef("/p/Локализация/Строки.yaml"), undefined);
});

test("serializer kind spellings: the kinds of issue #1 resolve to the tree's spelling", () => {
  // The serializer writes `Enumeration` while the stdlib TYPE is `Enum` - exactly the class of
  // objects that used to fall into "Other". The five names come from the issue report.
  assert.strictEqual(SERIALIZER_KIND_SPELLINGS.get("Enumeration"), "Перечисление");
  assert.strictEqual(SERIALIZER_KIND_SPELLINGS.get("HttpService"), "HttpСервис");
  assert.strictEqual(SERIALIZER_KIND_SPELLINGS.get("SoapService"), "SoapСервис");
  assert.strictEqual(SERIALIZER_KIND_SPELLINGS.get("SoapServiceClient"), "КлиентSoapСервиса");
  assert.strictEqual(SERIALIZER_KIND_SPELLINGS.get("InterfaceComponent"), "КомпонентИнтерфейса");
});

test("serializer kind spellings: one Russian kind per English name and back", () => {
  // The table must be invertible: englishKindName() builds the reverse map from it, and a
  // duplicate Russian kind would silently pick whichever pair came first.
  const russians = [...SERIALIZER_KIND_SPELLINGS.values()];
  assert.strictEqual(new Set(russians).size, russians.length);
});

// --- the modules of an element ------------------------------------------------------------

test("module tails: an object kind has its own module and the object module", () => {
  assert.deepStrictEqual([...moduleTailsOf("Справочник")], ["", "Объект"]);
  assert.deepStrictEqual([...moduleTailsOf("Обработка")], ["", "Объект"]);
  assert.deepStrictEqual([...moduleTailsOf("ПравоНаДействие")], ["", "Объект"]);
});

test("module tails: an entity contract has the object module, a client event its own one", () => {
  // Both compiled on a live server: the contract's object module takes abstract methods, the
  // event's module compiles in the client environment.
  assert.deepStrictEqual([...moduleTailsOf("КонтрактСущности")], ["", "Объект"]);
  assert.deepStrictEqual([...moduleTailsOf("ГлобальноеКлиентскоеСобытие")], [""]);
  assert.deepStrictEqual(moduleMenuTokens("КонтрактСущности", { "": "/p/К.xbsl" }), ["xbsl", "newobjmod"]);
});

test("module tails: a register has the modules of its record types, a constants set two of them", () => {
  assert.deepStrictEqual([...moduleTailsOf("РегистрСведений")], ["", "Запись", "НаборЗаписей", "КлючЗаписи"]);
  assert.deepStrictEqual([...moduleTailsOf("НаборКонстант")], ["", "Запись", "КлючЗаписи"]);
});

test("module tails: a kind without modules offers none", () => {
  for (const kind of ["ВиртуальнаяТаблица", "СобытиеЖурналаСобытий", "ЛокализованныеСтроки",
    "НавигационнаяКоманда", "ПравоНаЭлемент", "Отчет", "НеизвестныйВид"]) {
    assert.deepStrictEqual([...moduleTailsOf(kind)], [], kind);
  }
  assert.deepStrictEqual([...moduleTailsOf("Перечисление")], [""]);
});

test("module path: beside the description, spelled the way the description is", () => {
  const yaml = "/p/Каталог/Товары.yaml";
  assert.strictEqual(modulePathFor(yaml, "", false), "/p/Каталог/Товары.xbsl");
  assert.strictEqual(modulePathFor(yaml, "Объект", false), "/p/Каталог/Товары.Объект.xbsl");
  assert.strictEqual(modulePathFor("/p/Prices.yaml", "НаборЗаписей", true), "/p/Prices.RecordSet.xbsl");
  assert.strictEqual(modulePathFor("/p/Prices.yaml", "", true), "/p/Prices.xbsl");
});

test("module tails: every tail a kind offers has an English spelling", () => {
  for (const tails of Object.values(MODULE_TAILS)) {
    for (const tail of tails.filter((t: ModuleTail) => t !== "")) {
      assert.ok(MODULE_TAIL_ENGLISH[tail], tail);
    }
  }
});

test("module menu: a catalog without modules offers to create both of them", () => {
  assert.deepStrictEqual(moduleMenuTokens("Справочник", {}), ["newmod", "newobjmod"]);
  assert.deepStrictEqual(moduleMenuTokens("Справочник", { "": "/p/Т.xbsl" }), ["xbsl", "newobjmod"]);
  assert.deepStrictEqual(
    moduleMenuTokens("Справочник", { "": "/p/Т.xbsl", Объект: "/p/Т.Объект.xbsl" }), ["xbsl", "objmod"]
  );
});

test("module menu: a register opens the record modules it has and creates the rest", () => {
  assert.deepStrictEqual(
    moduleMenuTokens("РегистрСведений", { НаборЗаписей: "/p/Ц.НаборЗаписей.xbsl" }),
    ["recsetmod", "newmod", "newrecmod", "newreckeymod"],
  );
});

test("module menu: a kind without modules offers nothing, a module that is there still opens", () => {
  assert.deepStrictEqual(moduleMenuTokens("ВиртуальнаяТаблица", {}), []);
  assert.deepStrictEqual(moduleMenuTokens("НеизвестныйВид", { "": "/p/Н.xbsl" }), ["xbsl"]);
});

test("existing module: either spelling of the tail, the Russian one first", () => {
  const files = new Set(["/p/Prices.Object.xbsl", "/p/Цены.НаборЗаписей.xbsl", "/p/Цены.RecordSet.xbsl"]);
  const exists = (candidate: string): boolean => files.has(candidate);
  assert.strictEqual(existingModule("/p/Prices.yaml", "Объект", exists), "/p/Prices.Object.xbsl");
  assert.strictEqual(existingModule("/p/Цены.yaml", "НаборЗаписей", exists), "/p/Цены.НаборЗаписей.xbsl");
  assert.strictEqual(existingModule("/p/Цены.yaml", "Запись", exists), undefined);
  assert.strictEqual(existingModule("/p/Цены.yaml", "", exists), undefined);
});

// -- the module of the row of a tabular section ------------------------------------------------

test("row module: named after the element and the section, beside the description", () => {
  assert.strictEqual(rowModulePathFor("/p/Каталог/Товары.yaml", "Позиции"), "/p/Каталог/Товары.Позиции.xbsl");
  // The section keeps its own name in an English project: there is no tail to translate.
  assert.strictEqual(rowModulePathFor("/p/Goods.yaml", "Items"), "/p/Goods.Items.xbsl");
});

test("row module: a catalog and a document offer to create it, the other kinds only open one", () => {
  assert.deepStrictEqual(rowModuleMenuTokens("Справочник", false), ["newtcmod"]);
  assert.deepStrictEqual(rowModuleMenuTokens("Документ", false), ["newtcmod"]);
  assert.deepStrictEqual(rowModuleMenuTokens("Документ", true), ["tcmod"]);
  // Tabular sections without a confirmed row module: nothing to create, an existing file still opens.
  for (const kind of ["ПланОбмена", "ИнтегрируемоеПриложение", "ХранилищеНастроек", "КонтрактСущности"]) {
    assert.deepStrictEqual(rowModuleMenuTokens(kind, false), [], kind);
    assert.deepStrictEqual(rowModuleMenuTokens(kind, true), ["tcmod"], kind);
  }
  assert.deepStrictEqual([...ROW_MODULE_KINDS].sort(), ["Документ", "Справочник"]);
});

test("row module: the modules that are there are found by the name of their section", () => {
  const files = new Set(["/p/Товары.Позиции.xbsl", "/p/Товары.Объект.xbsl", "/p/Цены.Позиции.xbsl"]);
  const exists = (candidate: string): boolean => files.has(candidate);
  assert.deepStrictEqual(existingRowModules("/p/Товары.yaml", ["Позиции", "Скидки"], exists), {
    Позиции: "/p/Товары.Позиции.xbsl",
  });
  assert.deepStrictEqual(existingRowModules("/p/Товары.yaml", [], exists), {});
});

test("row module: the tree menu opens and creates it by tokens of its own and hides both from the palette", () => {
  const pkg = JSON.parse(fs.readFileSync(path.resolve("package.json"), "utf8"));
  const menus = pkg.contributes.menus;
  const node = (present: boolean): string =>
    ["member field props addtcattr", ...rowModuleMenuTokens("Справочник", present)].join(" ");
  for (const [command, token, present] of [
    ["xbsl.metadata.openRowModule", "tcmod", true],
    ["xbsl.metadata.createRowModule", "newtcmod", false],
  ] as const) {
    assert.ok(pkg.contributes.commands.some((c: { command: string }) => c.command === command), command);
    const item = menus["view/item/context"].find((m: { command: string }) => m.command === command);
    assert.ok(item && item.when.includes(`/\\b${token}\\b/`), `${command}: the menu is keyed by ${token}`);
    // The item shows on the node that carries its token and not on the other one: `tcmod` is the
    // tail of `newtcmod`, and only the word boundary keeps "open" off a node with no module.
    const keyed = new RegExp(/=~ \/(.+)\/$/.exec(item.when)![1]);
    assert.ok(keyed.test(node(present)), `${command}: shown on its node`);
    assert.ok(!keyed.test(node(!present)), `${command}: hidden on the other node`);
    assert.ok(
      menus.commandPalette.some((m: { command: string; when: string }) => m.command === command && m.when === "false"),
      `${command}: hidden from the palette`
    );
  }
});

// -- own members of an interface component ---------------------------------------------------

const COMPONENT = `ВидЭлемента: КомпонентИнтерфейса
Имя: КарточкаСклада
Наследует:
    Тип: Группа
Свойства:
    -
        ## Название склада.
        Имя: Название
        Тип: Строка
    -
        Имя: Вместимость
        Тип: Число
        ЗначениеПоУмолчанию: 0
События:
    -
        Имя: ПриВыбореСклада
        Тип: СобытиеКомпонента
`;

test("component members: the names of the properties and of the events, each from its section", () => {
  assert.deepStrictEqual(componentMemberNames(COMPONENT, "property"), ["Название", "Вместимость"]);
  assert.deepStrictEqual(componentMemberNames(COMPONENT, "event"), ["ПриВыбореСклада"]);
});

test("component members: a missing section, a broken file and a nameless item give nothing", () => {
  const noEvents = COMPONENT.slice(0, COMPONENT.indexOf("События:"));
  assert.deepStrictEqual(componentMemberNames(noEvents, "event"), []);
  assert.deepStrictEqual(componentMemberNames("Свойства: [\n", "property"), []);
  assert.deepStrictEqual(componentMemberNames("Свойства:\n    -\n        Тип: Строка\n", "property"), []);
});

test("component members: an English component is read through the engine's key pairs", () => {
  const english = "ElementKind: InterfaceComponent\nName: Card\nProperties:\n    -\n        Name: Title\n" +
    "        Type: String\nEvents:\n    -\n        Name: OnChosen\n";
  setMetaKeyAliases({ Properties: "Свойства", Events: "События" });
  try {
    assert.deepStrictEqual(componentMemberNames(english, "property"), ["Title"]);
    assert.deepStrictEqual(componentMemberNames(english, "event"), ["OnChosen"]);
  } finally {
    setMetaKeyAliases({});
  }
});

test("component members: an event offers the plain event first, a property the primitives, then the project", () => {
  const events = componentMemberTypeChoices("event", ["Склады.Ссылка?"]);
  assert.strictEqual(events[0], "СобытиеКомпонента"); // the platform's own default for an event
  assert.ok(events.every((type) => type.startsWith("Событие")), "an event is not offered a property type");
  const properties = componentMemberTypeChoices("property", ["Строка", "Склады.Ссылка?", "ВидСклада?"]);
  assert.deepStrictEqual(properties.slice(0, 3), ["Строка", "Число", "Булево"]);
  assert.deepStrictEqual(properties.slice(-2), ["Склады.Ссылка?", "ВидСклада?"]);
  assert.strictEqual(properties.filter((type) => type === "Строка").length, 1); // no repeats
});

test("component members: the engine request and the CLI arguments name the same operation", () => {
  const request = componentMemberRequest("/p/Карточка.yaml", "event", "ПриВыборе", "СобытиеСДанными<Строка>");
  assert.deepStrictEqual(request.params, {
    path: "/p/Карточка.yaml", fieldKind: "событие", name: "ПриВыборе", type: "СобытиеСДанными<Строка>",
  });
  assert.deepStrictEqual(request.cli, ["/p/Карточка.yaml", "событие", "ПриВыборе", "--type", "СобытиеСДанными<Строка>"]);
  assert.strictEqual(componentMemberRequest("/p/К.yaml", "property", "Название", "Строка").params.fieldKind, "свойство");
  assert.deepStrictEqual(
    [COMPONENT_MEMBER_SPECS.property.section, COMPONENT_MEMBER_SPECS.event.section], ["Свойства", "События"]
  );
});

test("component members: the tree menu offers both items on a form node and hides them from the palette", () => {
  const pkg = JSON.parse(fs.readFileSync(path.resolve("package.json"), "utf8"));
  const menus = pkg.contributes.menus;
  for (const [command, token] of [
    ["xbsl.metadata.addComponentProperty", "addprop"],
    ["xbsl.metadata.addComponentEvent", "addevent"],
  ]) {
    assert.ok(pkg.contributes.commands.some((c: { command: string }) => c.command === command), command);
    const item = menus["view/item/context"].find((m: { command: string }) => m.command === command);
    assert.ok(item && item.when.includes(`/\\b${token}\\b/`), `${command}: the menu is keyed by ${token}`);
    assert.ok(
      menus.commandPalette.some((m: { command: string; when: string }) => m.command === command && m.when === "false"),
      `${command}: hidden from the palette`
    );
  }
});

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
