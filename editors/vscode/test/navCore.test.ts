// Unit tests for the pure navigation core (src/navCore.ts) against the frozen index
// schema fixture. No test runner and no dependencies: plain Node asserts, bundled by
// esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import * as fs from "fs";
import * as path from "path";
import {
  chainAt,
  IndexLookup,
  isInQuery,
  parseIndex,
  queryFieldEntries,
  resolveCompletions,
  resolveDefinition,
  resolveReferences,
} from "../src/navCore";

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

// The bundle lives in dist/, the fixture next to the test source.
const fixturePath = path.resolve(__dirname, "..", "test", "fixtures", "index.json");
const lookup = new IndexLookup(parseIndex(fs.readFileSync(fixturePath, "utf8")));

// Cursor helper: 0-based column pointing into `word` inside `line`.
function on(line: string, word: string): number {
  const i = line.indexOf(word);
  assert.ok(i >= 0, `слово "${word}" не найдено в строке "${line}"`);
  return i + 1;
}

// --- parseIndex -------------------------------------------------------------

test("parseIndex: отчёт линтера не принимается за индекс", () => {
  assert.throws(() => parseIndex('{"diagnostics": [], "summary": {}}'));
});

test("parseIndex: мусор не принимается", () => {
  assert.throws(() => parseIndex("xbsllint: error: unrecognized arguments"));
});

test("parseIndex: минимальный индекс нормализуется", () => {
  const idx = parseIndex('{"meta": {"root": "/tmp/p"}, "objects": []}');
  assert.strictEqual(idx.meta.root, "/tmp/p");
  assert.deepStrictEqual(idx.methods, []);
  assert.deepStrictEqual(idx.components, []);
  assert.deepStrictEqual(idx.references, []); // an old linter without references - find-usages stays silent
});

// --- chainAt ----------------------------------------------------------------

test("chainAt: сегмент цепочки под курсором", () => {
  const line = "Результат = Товар.ПолучитьДанные(Отбор);";
  assert.deepStrictEqual(chainAt(line, on(line, "Товар")), {
    parts: ["Товар", "ПолучитьДанные"],
    at: 0,
  });
  assert.deepStrictEqual(chainAt(line, on(line, "ПолучитьДанные")), {
    parts: ["Товар", "ПолучитьДанные"],
    at: 1,
  });
  assert.strictEqual(chainAt(line, line.indexOf("=")), null);
});

// --- resolveDefinition: xbsl ------------------------------------------------

const inMain = { languageId: "xbsl", fileStem: "ФормаСписка", filePath: "Раздел/ФормаСписка.xbsl" };

test("переход: голое имя объекта / корень цепочки -> yaml объекта", () => {
  const line = "пер Ссылка: Товар.Ссылка;";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "Товар") }),
    { path: "Раздел/Товар/Товар.yaml", line: 1 }
  );
});

test("переход: Объект.ЛокальныйТип -> объявление типа", () => {
  const line = "пер Данные: Товар.ДанныеСтроки;";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "ДанныеСтроки") }),
    { path: "Раздел/Товар/Товар.xbsl", line: 12 }
  );
});

test("переход: Объект.ТабличнаяЧасть -> строка в yaml объекта", () => {
  const line = "Т = Товар.Позиции;";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "Позиции") }),
    { path: "Раздел/Товар/Товар.yaml", line: 58 }
  );
});

test("переход: Перечисление.Значение -> строка значения в yaml", () => {
  const line = "Если Категория = ВидТовара.Розница Тогда";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "Розница") }),
    { path: "Раздел/ВидТовара/ВидТовара.yaml", line: 12 }
  );
});

test("переход: Модуль.Метод -> объявление метода", () => {
  const line = "Адрес = Общий.АбсолютныйАдрес(Путь);";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "АбсолютныйАдрес") }),
    { path: "Раздел/Общий.xbsl", line: 5 }
  );
});

test("переход: метод менеджера объекта (модуль = имя объекта)", () => {
  const line = "Данные = Товар.ПолучитьДанные(Отбор);";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "ПолучитьДанные") }),
    { path: "Раздел/Товар/Товар.xbsl", line: 40 }
  );
});

test("переход: голое имя метода в своём модуле", () => {
  const line = "    ОбновитьСписок();";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "ОбновитьСписок") }),
    { path: "Раздел/ФормаСписка.xbsl", line: 27 }
  );
});

test("переход: Компоненты.X -> узел компонента в yaml формы", () => {
  const line = "Компоненты.КнопкаОткрыть.Видимость = Ложь;";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "КнопкаОткрыть") }),
    { path: "Раздел/ФормаСписка.yaml", line: 61 }
  );
});

test("переход: Компоненты.X.Метод -> метод модуля X", () => {
  const line = "Компоненты.КарточкаТовара.ПриНажатии();";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "ПриНажатии") }),
    { path: "Раздел/КарточкаТовара.xbsl", line: 15 }
  );
});

test("переход: неизвестное имя -> null (молчание)", () => {
  const line = "НеизвестноеИмя = Товар.НетТакогоЧлена;";
  assert.strictEqual(resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "НеизвестноеИмя") }), null);
  assert.strictEqual(resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "НетТакогоЧлена") }), null);
});

test("переход: член семейства (Ссылка) не имеет определения -> null", () => {
  const line = "пер С: Товар.Ссылка;";
  assert.strictEqual(resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "Ссылка;") }), null);
});

test("переход: глубокая цепочка без вывода типов -> null", () => {
  const line = "Имя = Элемент.Товар.Наименование;";
  assert.strictEqual(resolveDefinition(lookup, { ...inMain, lineText: line, character: on(line, "Наименование") }), null);
});

// --- resolveDefinition: yaml ------------------------------------------------

const inMainYaml = { languageId: "yaml", fileStem: "ФормаСписка", filePath: "Раздел/ФормаСписка.yaml" };

test("переход yaml: Обработчик: Имя -> метод в парном .xbsl", () => {
  const line = "      Обработчик: ПослеСоздания";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMainYaml, lineText: line, character: on(line, "ПослеСоздания") }),
    { path: "Раздел/ФормаСписка.xbsl", line: 3 }
  );
});

test("переход yaml: Обработчик с неизвестным методом -> null, без фоллбека", () => {
  const line = "      Обработчик: Товар";
  assert.strictEqual(
    resolveDefinition(lookup, { ...inMainYaml, lineText: line, character: on(line, "Товар") }),
    null
  );
});

test("переход yaml: Тип: Объект.Ссылка -> yaml объекта (корень цепочки)", () => {
  const line = "    Тип: КешОстатков.НаборЗаписей";
  assert.deepStrictEqual(
    resolveDefinition(lookup, { ...inMainYaml, lineText: line, character: on(line, "КешОстатков") }),
    { path: "Раздел/КешОстатков/КешОстатков.yaml", line: 1 }
  );
});

test("переход yaml: голое имя метода не резолвится (только в xbsl)", () => {
  const line = "  Значение: ОбновитьСписок";
  assert.strictEqual(
    resolveDefinition(lookup, { ...inMainYaml, lineText: line, character: on(line, "ОбновитьСписок") }),
    null
  );
});

// --- resolveReferences ------------------------------------------------------

function refSites(refs: { path: string; line: number }[]): string[] {
  return refs.map((r) => `${r.path}:${r.line}`).sort();
}

test("использования: метод модуля (Товар.ПолучитьДанные), без объявления", () => {
  const line = "Данные = Товар.ПолучитьДанные(Отбор);";
  const refs = resolveReferences(lookup, { ...inMain, lineText: line, character: on(line, "ПолучитьДанные") });
  assert.deepStrictEqual(refSites(refs), ["Раздел/КарточкаТовара.xbsl:8", "Раздел/ФормаСписка.xbsl:30"]);
});

test("использования: includeDeclaration добавляет объявление", () => {
  const line = "Данные = Товар.ПолучитьДанные(Отбор);";
  const refs = resolveReferences(lookup, {
    ...inMain,
    lineText: line,
    character: on(line, "ПолучитьДанные"),
    includeDeclaration: true,
  });
  assert.ok(refSites(refs).includes("Раздел/Товар/Товар.xbsl:40"));
});

test("использования: голый метод своего модуля + yaml-обработчик, чужой qualifier отсеян", () => {
  const line = "    ОбновитьСписок();";
  const refs = resolveReferences(lookup, { ...inMain, lineText: line, character: on(line, "ОбновитьСписок") });
  assert.deepStrictEqual(refSites(refs), ["Раздел/ФормаСписка.xbsl:15", "Раздел/ФормаСписка.yaml:45"]);
});

test("использования: объект как корень цепочки", () => {
  const line = "пер Ссылка: Товар.Ссылка;";
  const refs = resolveReferences(lookup, { ...inMain, lineText: line, character: on(line, "Товар") });
  assert.deepStrictEqual(refSites(refs), ["Раздел/КарточкаТовара.xbsl:8", "Раздел/ФормаСписка.xbsl:30"]);
});

test("использования: компонент через Компоненты, с колонкой и длиной", () => {
  const line = "Компоненты.КнопкаОткрыть.Видимость = Ложь;";
  const refs = resolveReferences(lookup, { ...inMain, lineText: line, character: on(line, "КнопкаОткрыть") });
  assert.deepStrictEqual(refSites(refs), ["Раздел/ФормаСписка.xbsl:20"]);
  assert.strictEqual(refs[0].col, 10);
  assert.strictEqual(refs[0].length, "КнопкаОткрыть".length);
});

test("использования: неизвестный символ -> пусто", () => {
  const line = "НеизвестноеИмя = 1;";
  assert.deepStrictEqual(resolveReferences(lookup, { ...inMain, lineText: line, character: on(line, "НеизвестноеИмя") }), []);
});

// --- resolveCompletions -----------------------------------------------------

function labels(entries: { label: string }[] | null): string[] {
  assert.ok(entries, "ожидался список дополнений, получен null");
  return entries.map((e) => e.label).sort();
}

test("isInQuery: внутри Запрос{...} истина, вне/после закрытия – ложь", () => {
  assert.strictEqual(isInQuery("исп Р = Запрос{ ВЫБРАТЬ Товар."), true);
  assert.strictEqual(isInQuery("var R = Query{ SELECT Item."), true); // the English form of the keyword
  assert.strictEqual(isInQuery("Запрос{ ВЫБРАТЬ Х ИЗ Т }.Выполнить(); Товар."), false);
  assert.strictEqual(isInQuery("Данные = Товар."), false);
});

test("queryFieldEntries: стандартные + реквизиты + ТЧ, без дублей, вид field", () => {
  const e = queryFieldEntries("Справочник", ["Цена", "Наименование"], ["Позиции"]);
  const l = e.map((x) => x.label);
  assert.ok(l.includes("Ссылка") && l.includes("Код") && l.includes("Наименование"));
  assert.ok(l.includes("Цена") && l.includes("Позиции"));
  assert.strictEqual(l.filter((x) => x === "Наименование").length, 1, "Наименование без дубля");
  assert.ok(e.every((x) => x.kind === "field"));
});

test("дополнение: в запросе после Таблица. -> поля таблицы, а не члены объекта", () => {
  const entries = resolveCompletions(lookup, {
    ...inMain,
    linePrefix: "Товар.",
    textBefore: "исп Р = Запрос{ ВЫБРАТЬ Товар.",
    attributesOf: (n) => (n === "Товар" ? ["Цена", "Артикул"] : undefined),
  });
  const l = labels(entries);
  assert.ok(l.includes("Наименование") && l.includes("Код") && l.includes("Цена"), "поля таблицы");
  assert.ok(!l.includes("Объект"), "члена Объект в запросе быть не должно");
  assert.ok(entries!.every((e) => e.kind === "field"));
});

test("дополнение: после Объект. -> семейство + ТЧ + локальные типы + методы менеджера", () => {
  const entries = resolveCompletions(lookup, { ...inMain, linePrefix: "Данные = Товар." });
  assert.deepStrictEqual(labels(entries), [
    "Выборка",
    "ДанныеСтроки",
    "Объект",
    "Позиции",
    "ПолучитьДанные",
    "Ссылка",
    "Цены",
  ]);
  const kinds = new Map(entries!.map((e) => [e.label, e.kind]));
  assert.strictEqual(kinds.get("Ссылка"), "family");
  assert.strictEqual(kinds.get("Позиции"), "tabular");
  assert.strictEqual(kinds.get("ДанныеСтроки"), "localType");
  assert.strictEqual(kinds.get("ПолучитьДанные"), "method");
});

test("дополнение: частично набранный член после точки не меняет список", () => {
  const entries = resolveCompletions(lookup, { ...inMain, linePrefix: "Данные = Товар.Пол" });
  assert.ok(labels(entries).includes("ПолучитьДанные"));
});

test("дополнение: после Перечисление. -> значения", () => {
  const entries = resolveCompletions(lookup, { ...inMain, linePrefix: "Категория = ВидТовара." });
  assert.deepStrictEqual(labels(entries), ["Опт", "Прочее", "Розница"]);
  assert.ok(entries!.every((e) => e.kind === "enumMember"));
});

test("дополнение: после Компоненты. -> компоненты текущей формы", () => {
  const entries = resolveCompletions(lookup, { ...inMain, linePrefix: "Компоненты." });
  assert.deepStrictEqual(labels(entries), ["КнопкаОткрыть", "Таблица"]);
  assert.strictEqual(entries![0].kind, "component");
});

test("дополнение: после Компоненты.X. -> методы модуля X", () => {
  const entries = resolveCompletions(lookup, { ...inMain, linePrefix: "Компоненты.КарточкаТовара." });
  assert.deepStrictEqual(labels(entries), ["ПриНажатии"]);
  assert.strictEqual(entries![0].kind, "method");
});

test("дополнение yaml: после Тип: -> имена объектов проекта с видом", () => {
  const entries = resolveCompletions(lookup, { ...inMainYaml, linePrefix: "    Тип: " });
  assert.deepStrictEqual(labels(entries), ["ВидТовара", "КешОстатков", "Склад", "Товар"]);
  const byLabel = new Map(entries!.map((e) => [e.label, e]));
  assert.strictEqual(byLabel.get("ВидТовара")!.kind, "enum");
  assert.strictEqual(byLabel.get("Товар")!.detail, "Справочник");
});

test("дополнение: Тип: в xbsl не срабатывает", () => {
  assert.strictEqual(resolveCompletions(lookup, { ...inMain, linePrefix: "    Тип: " }), null);
});

test("дополнение: неизвестный контекст -> null (не мешаем словарному)", () => {
  assert.strictEqual(resolveCompletions(lookup, { ...inMain, linePrefix: "Результат = " }), null);
  assert.strictEqual(resolveCompletions(lookup, { ...inMain, linePrefix: "Значение = Переменная." }), null);
  assert.strictEqual(resolveCompletions(lookup, { ...inMain, linePrefix: "А.Б." }), null);
});

// -----------------------------------------------------------------------------

console.log(`\nитого: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
