// Unit tests for the pure properties-panel core (src/formPropsCore.ts) and the shared
// webview helpers (src/webviewShared.ts). No test runner and no vscode: plain Node asserts,
// bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  FormNodeDto,
  ModuleHandlersPayload,
  NodePropertyDto,
  PanelModel,
  SpanDto,
  UiComponentDto,
  buildAddHandlerParams,
  buildCompositeYaml,
  buildPanelModel,
  chooseEditor,
  collectFormBindings,
  collectFormColors,
  createSerialQueue,
  colorYaml,
  defaultHandlerName,
  encodeFragmentScalar,
  extractScalarValue,
  findRow,
  handlerChoices,
  hexFromColorFields,
  isReadonlyScheme,
  normalizeHex,
  panelTarget,
  parseCompositeFields,
  parseEventSignature,
  planHandlerApply,
  prepareWrite,
  rowMatchesFilter,
} from "../src/formPropsCore";
import { cspMeta, escapeHtml, inlineJson, makeNonce } from "../src/webviewShared";

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

// -- fixture: a form slice with a Надпись node ------------------------------------------------

const FORM = `ВидЭлемента: КомпонентИнтерфейса
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Надпись
        Имя: Шапка
        Заголовок: "Привет <мир>"
        РастягиватьПоГоризонтали: Истина
        Цвет:
            Тип: АбсолютныйЦвет
            Значение: RGB(595964)
        ПриНажатии: ОбработатьНажатие
`;

// Whole-line span of a block: from the marker line through `lines` lines (newline included).
function lineSpan(text: string, marker: string, lines = 1): SpanDto {
  const start = text.indexOf(marker);
  assert.ok(start >= 0, `marker not found: ${marker}`);
  let end = start;
  for (let i = 0; i < lines; i++) {
    end = text.indexOf("\n", end) + 1;
  }
  return { start, end };
}

function propDto(
  text: string,
  key: string,
  kind: NodePropertyDto["kind"],
  preview: string,
  lines = 1
): NodePropertyDto {
  return {
    key,
    kind,
    valuePreview: preview,
    span: lineSpan(text, `        ${key}:`, lines),
    valueSpan: null,
  };
}

const NODE: FormNodeDto = {
  id: "Наследует/Содержимое[0]",
  kind: "component",
  span: lineSpan(FORM, "        Тип: Надпись", 8),
  type: "Надпись",
  typeFull: "Надпись",
  name: "Шапка",
  slot: "Содержимое",
  properties: [
    propDto(FORM, "Заголовок", "scalar", "Привет <мир>"),
    propDto(FORM, "РастягиватьПоГоризонтали", "scalar", "Истина"),
    propDto(FORM, "Цвет", "composite", "АбсолютныйЦвет", 3),
    propDto(FORM, "ПриНажатии", "handler", "ОбработатьНажатие"),
  ],
};

const SCHEMA: UiComponentDto = {
  name: "Надпись",
  package: "Стд::Интерфейс::ОбщиеКомпоненты",
  props: {
    Заголовок: { types: ["Авто", "Строка"], doc: "Заголовок надписи." },
    РастягиватьПоГоризонтали: { types: ["Авто", "Булево"], default: "Ложь" },
    Цвет: { types: ["Авто", "Цвет"] },
    ПриНажатии: { event: "(Надпись, СобытиеПриНажатии)->ничто", doc: "Вызывается при нажатии." },
    Видимость: { types: ["Авто", "Булево"] },
    ВидОтображения: { types: ["Авто", "ВидОтображения"], enum: ["Карточка", "Баннер"], default: "Карточка" },
    Ширина: { types: ["Авто", "Число"] },
    Изображение: { types: ["Url", "ДвоичныйОбъект.Ссылка"], nullable: true },
    // a union with an enumeration member: the values come from the enums map below
    Фон: { types: ["Авто", "ВидФона", "Цвет"] },
    Картинка: { types: ["Картинка"], slot: true },
    Индекс: { types: ["Число"], readonly: true },
  },
  enums: { ВидФона: ["Сплошной", "Градиент"] },
};

// -- webviewShared ----------------------------------------------------------------------------

test("inlineJson escapes < so </script> cannot break out, and stays valid JSON", () => {
  const payload = { hint: "</script><script>alert(1)</script>", sep: "a b" };
  const inlined = inlineJson(payload);
  assert.ok(!inlined.includes("</script>"), "the raw closing tag must not survive");
  assert.ok(!inlined.includes("<"), "no bare < at all");
  assert.deepStrictEqual(JSON.parse(inlined), payload);
});

test("escapeHtml and cspMeta basics", () => {
  assert.strictEqual(escapeHtml('<a b="c">&'), "&lt;a b=&quot;c&quot;&gt;&amp;");
  const nonce = makeNonce();
  assert.strictEqual(nonce.length, 24);
  const meta = cspMeta(nonce);
  assert.ok(meta.includes(`'nonce-${nonce}'`));
  assert.ok(meta.includes("default-src 'none'"));
});

// -- value extraction -------------------------------------------------------------------------

test("extractScalarValue decodes quotes and escapes", () => {
  const prop = NODE.properties!.find((p) => p.key === "Заголовок")!;
  assert.strictEqual(extractScalarValue(FORM, prop), "Привет <мир>");
});

test("extractScalarValue returns the full value where the engine preview truncates", () => {
  const long = "Очень длинное значение заголовка, которое движок обрезал бы в превью до многоточия";
  const doc = `        Заголовок: "${long}"\n`;
  const prop: NodePropertyDto = {
    key: "Заголовок",
    kind: "scalar",
    valuePreview: long.slice(0, 57) + "...",
    span: { start: 0, end: doc.length },
    valueSpan: null,
  };
  assert.strictEqual(extractScalarValue(doc, prop), long);
});

test("parseCompositeFields reads scalar fields and flags nested blocks", () => {
  const color = NODE.properties!.find((p) => p.key === "Цвет")!;
  const parsed = parseCompositeFields(FORM, color);
  assert.strictEqual(parsed.allScalar, true);
  assert.deepStrictEqual(parsed.fields, [
    { key: "Тип", value: "АбсолютныйЦвет", scalar: true },
    { key: "Значение", value: "RGB(595964)", scalar: true },
  ]);

  const doc = "        Фон:\n            Тип: Заливка\n            Слои:\n                - А\n";
  const nested: NodePropertyDto = {
    key: "Фон",
    kind: "composite",
    valuePreview: "Заливка",
    span: { start: 0, end: doc.length },
    valueSpan: null,
  };
  const locked = parseCompositeFields(doc, nested);
  assert.strictEqual(locked.allScalar, false);
  assert.deepStrictEqual(
    locked.fields.map((f) => [f.key, f.scalar]),
    [["Тип", true], ["Слои", false]]
  );
});

// -- color spellings --------------------------------------------------------------------------

test("colorYaml accepts #RRGGBB, bare and short forms, rejects garbage", () => {
  assert.strictEqual(colorYaml("#595964"), "Тип: АбсолютныйЦвет\nЗначение: RGB(595964)");
  assert.strictEqual(colorYaml("595964"), "Тип: АбсолютныйЦвет\nЗначение: RGB(595964)");
  assert.strictEqual(colorYaml("#abc"), "Тип: АбсолютныйЦвет\nЗначение: RGB(aabbcc)");
  assert.strictEqual(colorYaml("красный"), undefined);
  assert.strictEqual(colorYaml("#12345"), undefined);
});

test("hexFromColorFields reads hex and decimal RGB, only for АбсолютныйЦвет", () => {
  assert.strictEqual(
    hexFromColorFields([
      { key: "Тип", value: "АбсолютныйЦвет", scalar: true },
      { key: "Значение", value: "RGB(595964)", scalar: true },
    ]),
    "#595964"
  );
  assert.strictEqual(
    hexFromColorFields([
      { key: "Тип", value: "АбсолютныйЦвет", scalar: true },
      { key: "Значение", value: "RGB(255, 0, 16)", scalar: true },
    ]),
    "#ff0010"
  );
  assert.strictEqual(
    hexFromColorFields([{ key: "Тип", value: "Ссылка", scalar: true }]),
    undefined
  );
});

test("isReadonlyScheme: only real editable sources are writable (hook 11)", () => {
  assert.strictEqual(isReadonlyScheme("file"), false);
  assert.strictEqual(isReadonlyScheme("untitled"), false);
  assert.strictEqual(isReadonlyScheme("vscode-userdata"), false);
  // git diffs, output, and any virtual scheme a library viewer might use are read-only.
  assert.strictEqual(isReadonlyScheme("git"), true);
  assert.strictEqual(isReadonlyScheme("output"), true);
  assert.strictEqual(isReadonlyScheme("xlib"), true);
});

test("normalizeHex canonicalizes to lowercase #rrggbb, rejects non-colors (hook 7)", () => {
  assert.strictEqual(normalizeHex("#AABBCC"), "#aabbcc");
  assert.strictEqual(normalizeHex("aabbcc"), "#aabbcc");
  assert.strictEqual(normalizeHex("#abc"), "#aabbcc"); // short form expands
  assert.strictEqual(normalizeHex("  #FfF  "), "#ffffff"); // trims, folds case
  assert.strictEqual(normalizeHex("красный"), undefined);
  assert.strictEqual(normalizeHex("#12345"), undefined);
});

test("collectFormColors gathers АбсолютныйЦвет shades, deduped in first-seen order (hook 7)", () => {
  const doc = [
    "ЦветФона: {Тип: АбсолютныйЦвет, Значение: RGB(595964)}",
    "ЦветТекста: {Тип: АбсолютныйЦвет, Значение: RGB(255, 0, 16)}",
    "ЦветРамки: {Тип: АбсолютныйЦвет, Значение: RGB(595964)}", // duplicate of the first
  ].join("\n");
  assert.deepStrictEqual(collectFormColors(doc), ["#595964", "#ff0010"]);
  // A decimal component over 255 is not a color and is skipped.
  assert.deepStrictEqual(collectFormColors("x: RGB(300, 0, 0)"), []);
  // The cap bounds the list.
  const many = Array.from({ length: 20 }, (_, i) => `RGB(0000${i.toString(16).padStart(2, "0")})`).join(" ");
  assert.strictEqual(collectFormColors(many, 5).length, 5);
});

test("collectFormBindings gathers =-expressions at value positions, deduped (hook 6)", () => {
  const doc = [
    "        Заголовок: =Объект.Наименование",
    "        Видимость: =не Объект.Скрыт",
    "        Данные: {Данные: =Объект.Шаги}", // flow, trailing brace must be dropped
    "        Ещё: =Объект.Наименование", // duplicate
    '        Текст: "цена = 10"', // an "=" in a quoted literal, not a binding value',
  ].join("\n");
  assert.deepStrictEqual(collectFormBindings(doc), [
    "=Объект.Наименование",
    "=не Объект.Скрыт",
    "=Объект.Шаги",
  ]);
  assert.deepStrictEqual(collectFormBindings("Метод: =Вычислить(Объект.Х, 2)"), ["=Вычислить(Объект.Х, 2)"]);
});

// -- fragment assembly ------------------------------------------------------------------------

test("encodeFragmentScalar mirrors the engine's bare/quoted split", () => {
  assert.strictEqual(encodeFragmentScalar("28"), "28");
  assert.strictEqual(encodeFragmentScalar("-1.5"), "-1.5");
  assert.strictEqual(encodeFragmentScalar("АбсолютныйШрифт"), "АбсолютныйШрифт");
  assert.strictEqual(encodeFragmentScalar("Оплатить заказ"), "Оплатить заказ");
  assert.strictEqual(encodeFragmentScalar("=Объект.Срок"), "=Объект.Срок");
  assert.strictEqual(encodeFragmentScalar("true"), '"true"');
  assert.strictEqual(encodeFragmentScalar(" с пробелом"), '" с пробелом"');
  assert.strictEqual(encodeFragmentScalar('с "кавычкой"'), '"с \\"кавычкой\\""');
});

test("buildCompositeYaml: block for many fields, flow for a single one", () => {
  assert.strictEqual(
    buildCompositeYaml([
      { key: "Тип", value: "АбсолютныйШрифт" },
      { key: "Размер", value: "28" },
    ]),
    "Тип: АбсолютныйШрифт\nРазмер: 28"
  );
  // The engine writes a one-line fragment inline after the key, so it must be a flow
  // collection to stay valid yaml there.
  assert.strictEqual(
    buildCompositeYaml([{ key: "Данные", value: "=Объект.Шаги" }]),
    "{Данные: =Объект.Шаги}"
  );
});

// -- editor choice ----------------------------------------------------------------------------

test("chooseEditor picks typed editors from the schema union", () => {
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Булево"] }, undefined, ""), {
    control: "tristate",
  });
  assert.deepStrictEqual(
    chooseEditor({ types: ["Авто", "Вид"], enum: ["Карточка", "Баннер"] }, undefined, ""),
    { control: "enum", options: ["Карточка", "Баннер"] }
  );
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Число"] }, undefined, ""), {
    control: "number",
  });
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Цвет"] }, undefined, ""), {
    control: "color",
  });
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Строка"] }, undefined, "привет"), {
    control: "text",
    multiline: false,
  });
  const long = "х".repeat(80);
  assert.deepStrictEqual(chooseEditor({ types: ["Строка"] }, undefined, long), {
    control: "text",
    multiline: true,
  });
});

test("chooseEditor: union pair editor with the current member from composite fields", () => {
  const editor = chooseEditor(
    { types: ["Url", "Ссылка", "Цвет"] },
    { key: "Фон", kind: "composite", valuePreview: "Ссылка", span: { start: 0, end: 0 }, valueSpan: null },
    "Ссылка",
    [
      { key: "Тип", value: "Ссылка", scalar: true },
      { key: "Адрес", value: "/home", scalar: true },
    ],
    true
  );
  assert.deepStrictEqual(editor, { control: "union", types: ["Url", "Ссылка", "Цвет"], current: "Ссылка" });
});

test("chooseEditor: union editor carries the enum values of its enumeration members", () => {
  const componentEnums = { ВидФона: ["Сплошной", "Градиент"], Чужое: ["А"] };
  const editor = chooseEditor(
    { types: ["Авто", "ВидФона", "Цвет"] },
    undefined,
    "",
    undefined,
    undefined,
    componentEnums
  );
  // only the members of THIS union get a key; the color member has no values
  assert.deepStrictEqual(editor, {
    control: "union",
    types: ["ВидФона", "Цвет"],
    current: undefined,
    enums: { ВидФона: ["Сплошной", "Градиент"] },
  });
  // without the per-component map (an older engine) the editor shape stays as before
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "ВидФона", "Цвет"] }, undefined, ""), {
    control: "union",
    types: ["ВидФона", "Цвет"],
    current: undefined,
  });
});

test("chooseEditor: kind and flags outrank the type union", () => {
  const prop: NodePropertyDto = {
    key: "Значение",
    kind: "binding",
    valuePreview: "=Объект.Имя",
    span: { start: 0, end: 0 },
    valueSpan: null,
  };
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Строка"] }, prop, "=Объект.Имя"), {
    control: "binding",
  });
  assert.deepStrictEqual(chooseEditor({ types: ["Картинка"], slot: true }, undefined, ""), {
    control: "readonly",
  });
  assert.deepStrictEqual(chooseEditor({ types: ["Число"], readonly: true }, undefined, "3"), {
    control: "readonly",
  });
  assert.deepStrictEqual(chooseEditor({ event: "(К, С)->ничто" }, undefined, ""), {
    control: "handler",
  });
});

test("chooseEditor: composite editors, editable only when every field is scalar", () => {
  const prop: NodePropertyDto = {
    key: "Шрифт",
    kind: "composite",
    valuePreview: "АбсолютныйШрифт",
    span: { start: 0, end: 0 },
    valueSpan: null,
  };
  const fields = [
    { key: "Тип", value: "АбсолютныйШрифт", scalar: true },
    { key: "Размер", value: "28", scalar: true },
  ];
  assert.deepStrictEqual(chooseEditor({ types: ["Авто", "Шрифт"] }, prop, "АбсолютныйШрифт", fields, true), {
    control: "composite",
    fields,
    editable: true,
  });
  assert.deepStrictEqual(
    chooseEditor(undefined, prop, "АбсолютныйШрифт", fields, false),
    { control: "composite", fields, editable: false }
  );
});

test("chooseEditor: no schema - heuristics over the set value", () => {
  const scalar = (v: string): NodePropertyDto => ({
    key: "Х",
    kind: "scalar",
    valuePreview: v,
    span: { start: 0, end: 0 },
    valueSpan: null,
  });
  assert.deepStrictEqual(chooseEditor(undefined, scalar("Истина"), "Истина"), { control: "tristate" });
  assert.deepStrictEqual(chooseEditor(undefined, scalar("220"), "220"), { control: "number" });
  assert.deepStrictEqual(chooseEditor(undefined, scalar("текст"), "текст"), {
    control: "text",
    multiline: false,
  });
});

// -- panel model ------------------------------------------------------------------------------

test("buildPanelModel: set section is alphabetical, events go to their own section", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  assert.strictEqual(model.type, "Надпись");
  assert.strictEqual(model.name, "Шапка");
  assert.strictEqual(model.schemaAvailable, true);
  assert.deepStrictEqual(
    model.sections.map((s) => s.id),
    ["set", "events", "all"]
  );
  const set = model.sections[0];
  assert.deepStrictEqual(
    set.rows.map((r) => r.key),
    ["Заголовок", "РастягиватьПоГоризонтали", "Цвет"]
  );
  assert.ok(set.rows.every((r) => r.set));
  const title = set.rows.find((r) => r.key === "Заголовок")!;
  assert.strictEqual(title.value, "Привет <мир>");
  assert.strictEqual(title.doc, "Заголовок надписи.");
  assert.strictEqual(set.rows.find((r) => r.key === "РастягиватьПоГоризонтали")!.editor.control, "tristate");
  const color = set.rows.find((r) => r.key === "Цвет")!;
  assert.strictEqual(color.editor.control, "color");
  assert.strictEqual(color.colorHex, "#595964");
});

test("buildPanelModel: the set section is sorted, not in file order (stable position)", () => {
  // Properties written out of alphabetical order in the yaml still come back sorted, so a row
  // never jumps when the engine re-inserts a re-set property elsewhere in the block.
  const form = "Наследует\n    Содержимое\n        Тип: Надпись\n        Ширина: 10\n        Видимость: Истина\n";
  const node: FormNodeDto = {
    id: "n",
    kind: "component",
    span: lineSpan(form, "        Тип: Надпись", 3),
    type: "Надпись",
    typeFull: "Надпись",
    name: "X",
    slot: "Содержимое",
    properties: [
      propDto(form, "Ширина", "scalar", "10"),
      propDto(form, "Видимость", "scalar", "Истина"),
    ],
  };
  const set = buildPanelModel(node, SCHEMA, form).sections[0];
  assert.deepStrictEqual(set.rows.map((r) => r.key), ["Видимость", "Ширина"]);
});

test("buildPanelModel: the events section carries the set handler name", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  const events = model.sections[1];
  assert.deepStrictEqual(events.rows.map((r) => r.key), ["ПриНажатии"]);
  const row = events.rows[0];
  assert.strictEqual(row.set, true);
  assert.strictEqual(row.value, "ОбработатьНажатие");
  assert.strictEqual(row.editor.control, "handler");
  assert.strictEqual(row.event, "(Надпись, СобытиеПриНажатии)->ничто");
});

test("buildPanelModel: the all section is alphabetical, slots and events excluded", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  const all = model.sections[2];
  const keys = all.rows.map((r) => r.key);
  assert.ok(!keys.includes("ПриНажатии"), "events are not repeated in all");
  assert.ok(!keys.includes("Картинка"), "slot properties are the structure view's business");
  assert.strictEqual(keys.length, 9);
  for (let i = 1; i < keys.length; i++) {
    assert.ok(keys[i - 1].localeCompare(keys[i], "ru") <= 0, `not sorted: ${keys[i - 1]} > ${keys[i]}`);
  }
  const vidRow = all.rows.find((r) => r.key === "ВидОтображения")!;
  assert.strictEqual(vidRow.set, false);
  assert.deepStrictEqual(vidRow.editor, { control: "enum", options: ["Карточка", "Баннер"] });
  assert.strictEqual(vidRow.defaultValue, "Карточка");
  const indexRow = all.rows.find((r) => r.key === "Индекс")!;
  assert.strictEqual(indexRow.editor.control, "readonly");
  const setRow = all.rows.find((r) => r.key === "Заголовок")!;
  assert.strictEqual(setRow.set, true);
  assert.strictEqual(setRow.value, "Привет <мир>");
});

test("buildPanelModel: a set slot property is flagged even when bound (slot indicator)", () => {
  const form = "Наследует\n    Содержимое\n        Тип: Надпись\n        Картинка: =Объект.Пиктограмма\n";
  const node: FormNodeDto = {
    id: "n",
    kind: "component",
    span: lineSpan(form, "        Тип: Надпись", 2),
    type: "Надпись",
    typeFull: "Надпись",
    name: "X",
    slot: "Содержимое",
    properties: [propDto(form, "Картинка", "binding", "=Объект.Пиктограмма")],
  };
  const model = buildPanelModel(node, SCHEMA, form);
  const row = model.sections[0].rows.find((r) => r.key === "Картинка")!;
  // A binding value drives a binding editor, but the schema slot flag still rides on the row.
  assert.strictEqual(row.editor.control, "binding");
  assert.strictEqual(row.slot, true);
  // A plain (non-slot) property is not flagged.
  const label = buildPanelModel(NODE, SCHEMA, FORM).sections[0].rows.find((r) => r.key === "Заголовок")!;
  assert.ok(!label.slot);
});

test("buildPanelModel: a universal child-slot key is flagged even without a schema flag", () => {
  // "Содержимое" is not in the component schema below, but it is one of the engine's CHILD_SLOTS,
  // so the panel still marks it a slot (the engine refuses to clear it as a plain value).
  const form = "Наследует\n    Содержимое\n        Тип: КонтейнерHtml\n        Содержимое: =РазметкаHtml()\n";
  const node: FormNodeDto = {
    id: "n",
    kind: "component",
    span: lineSpan(form, "        Тип: КонтейнерHtml", 2),
    type: "КонтейнерHtml",
    typeFull: "КонтейнерHtml",
    name: "X",
    slot: "Содержимое",
    properties: [propDto(form, "Содержимое", "binding", "=РазметкаHtml()")],
  };
  const row = buildPanelModel(node, SCHEMA, form).sections[0].rows.find((r) => r.key === "Содержимое")!;
  assert.strictEqual(row.slot, true);
});

test("buildPanelModel: a union row picks its member enum values from schema.enums", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  const bg = model.sections[2].rows.find((r) => r.key === "Фон")!;
  assert.deepStrictEqual(bg.editor, {
    control: "union",
    types: ["ВидФона", "Цвет"],
    current: undefined,
    enums: { ВидФона: ["Сплошной", "Градиент"] },
  });
});

test("panelTarget: a component shows itself, a slot shows its parent component", () => {
  const slotNode: FormNodeDto = {
    id: "Наследует/Содержимое",
    kind: "slot",
    span: { start: 40, end: 200 },
    name: "Содержимое",
  };
  assert.deepStrictEqual(panelTarget({ node: NODE }), { node: NODE });
  // a slot with the parent along (newer engines): the parent's properties are shown
  assert.deepStrictEqual(panelTarget({ node: slotNode, parent: NODE }), {
    node: NODE,
    viaSlot: "Содержимое",
  });
  // a slot from an older engine (no parent) keeps the hint path
  assert.strictEqual(panelTarget({ node: slotNode }), undefined);
  assert.strictEqual(panelTarget({ node: slotNode, parent: null }), undefined);
  assert.strictEqual(panelTarget({ node: null }), undefined);
  assert.strictEqual(panelTarget({}), undefined);
});

test("buildPanelModel: without a schema only the set section remains, kind-based editors", () => {
  const model = buildPanelModel(NODE, null, FORM);
  assert.strictEqual(model.schemaAvailable, false);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set"]);
  const rows = model.sections[0].rows;
  // Alphabetical (no schema -> no events section, so the handler stays among the set rows).
  assert.deepStrictEqual(
    rows.map((r) => r.key),
    ["Заголовок", "ПриНажатии", "РастягиватьПоГоризонтали", "Цвет"]
  );
  assert.strictEqual(rows.find((r) => r.key === "ПриНажатии")!.editor.control, "handler");
  assert.strictEqual(rows.find((r) => r.key === "Цвет")!.editor.control, "composite");
  assert.strictEqual(rows.find((r) => r.key === "РастягиватьПоГоризонтали")!.editor.control, "tristate");
});

test("rowMatchesFilter matches the name AND the current value, case-insensitively", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  const title = findRow(model, "Заголовок")!;
  assert.ok(rowMatchesFilter(title, "загол"));
  assert.ok(rowMatchesFilter(title, "ПРИВЕТ"));
  assert.ok(!rowMatchesFilter(title, "нету"));
  assert.ok(rowMatchesFilter(title, ""));
  const color = findRow(model, "Цвет")!;
  assert.ok(rowMatchesFilter(color, "#5959"), "the derived hex is searchable");
  assert.ok(rowMatchesFilter(color, "абсолютныйцвет"), "composite field values are searchable");
});

test("findRow prefers the set-section instance", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM);
  const row = findRow(model, "Заголовок")!;
  assert.strictEqual(row.set, true);
  assert.strictEqual(findRow(model, "Несуществующее"), undefined);
});

// -- write preparation ------------------------------------------------------------------------

test("prepareWrite scalar: no-ops, the empty-value guard and type checks", () => {
  const text = { control: "text", multiline: false } as const;
  assert.deepStrictEqual(
    prepareWrite({ form: "scalar", value: "как было", editor: text, wasSet: true, oldValue: "как было" }),
    { kind: "noop" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "scalar", value: "", editor: text, wasSet: true, oldValue: "х" }),
    { kind: "error", code: "empty" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "scalar", value: "", editor: text, wasSet: false, oldValue: "" }),
    { kind: "noop" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "scalar", value: "abc", editor: { control: "number" }, wasSet: false, oldValue: "" }),
    { kind: "error", code: "number" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "scalar", value: "220", editor: { control: "number" }, wasSet: false, oldValue: "" }),
    { kind: "value", value: "220" }
  );
  assert.deepStrictEqual(
    prepareWrite({
      form: "scalar",
      value: "Чужое",
      editor: { control: "enum", options: ["Карточка", "Баннер"] },
      wasSet: false,
      oldValue: "",
    }),
    { kind: "error", code: "enum" }
  );
});

test("prepareWrite color and composite", () => {
  assert.deepStrictEqual(prepareWrite({ form: "color", hex: "#595964" }), {
    kind: "valueYaml",
    valueYaml: "Тип: АбсолютныйЦвет\nЗначение: RGB(595964)",
  });
  assert.deepStrictEqual(prepareWrite({ form: "color", hex: "зелёный" }), {
    kind: "error",
    code: "color",
  });
  assert.deepStrictEqual(
    prepareWrite({
      form: "composite",
      fields: [
        { key: "Тип", value: "АбсолютныйШрифт" },
        { key: "Размер", value: "28" },
      ],
    }),
    { kind: "valueYaml", valueYaml: "Тип: АбсолютныйШрифт\nРазмер: 28" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "composite", fields: [{ key: "Размер", value: " " }] }),
    { kind: "error", code: "empty" }
  );
});

test("prepareWrite scalar: a binding bypasses the literal type checks (hook 6)", () => {
  // A number property flipped to a binding must write verbatim, not fail the number check.
  assert.deepStrictEqual(
    prepareWrite({
      form: "scalar",
      value: "=Объект.Ширина",
      editor: { control: "number" },
      wasSet: false,
      oldValue: "",
    }),
    { kind: "value", value: "=Объект.Ширина" }
  );
  // An enum property flipped to a binding writes too, without the enum-membership check.
  assert.deepStrictEqual(
    prepareWrite({
      form: "scalar",
      value: "=Объект.Вид",
      editor: { control: "enum", options: ["Карточка", "Баннер"] },
      wasSet: true,
      oldValue: "Карточка",
    }),
    { kind: "value", value: "=Объект.Вид" }
  );
  // A non-binding literal is still validated.
  assert.deepStrictEqual(
    prepareWrite({
      form: "scalar",
      value: "abc",
      editor: { control: "number" },
      wasSet: false,
      oldValue: "",
    }),
    { kind: "error", code: "number" }
  );
});

test("prepareWrite union: the member type drives the value form", () => {
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "Цвет", value: "#ff0010" }), {
    kind: "valueYaml",
    valueYaml: "Тип: АбсолютныйЦвет\nЗначение: RGB(ff0010)",
  });
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "Url", value: "/img/logo.svg" }), {
    kind: "value",
    value: "/img/logo.svg",
  });
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "Число", value: "х" }), {
    kind: "error",
    code: "number",
  });
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "Булево", value: "Да" }), {
    kind: "error",
    code: "enum",
  });
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "", value: " " }), {
    kind: "error",
    code: "empty",
  });
});

test("prepareWrite union: an enumeration member accepts only its listed values", () => {
  const options = ["Сплошной", "Градиент"];
  assert.deepStrictEqual(
    prepareWrite({ form: "union", memberType: "ВидФона", value: "Градиент", options }),
    { kind: "value", value: "Градиент" }
  );
  assert.deepStrictEqual(
    prepareWrite({ form: "union", memberType: "ВидФона", value: "Чужое", options }),
    { kind: "error", code: "enum" }
  );
  // without options (older engines / a non-enum member) the value passes as before
  assert.deepStrictEqual(prepareWrite({ form: "union", memberType: "ВидФона", value: "Чужое" }), {
    kind: "value",
    value: "Чужое",
  });
});

// -- event handlers (hook 1) --------------------------------------------------------------

test("parseEventSignature: plain, nullable-wrapped, generic and broken forms", () => {
  assert.deepStrictEqual(parseEventSignature("(Кнопка, СобытиеПриНажатии)->ничто"), {
    args: ["Кнопка", "СобытиеПриНажатии"],
    ret: "ничто",
  });
  // the nullable wrapping of callback-typed events unwraps to the inner signature
  assert.deepStrictEqual(parseEventSignature("((ОписаниеЗадания)->Булево)?"), {
    args: ["ОписаниеЗадания"],
    ret: "Булево",
  });
  // generic arguments keep their commas inside the brackets
  assert.deepStrictEqual(
    parseEventSignature("(ПолеВвода<ТипДанных>, Соответствие<Строка, Число>)->ничто"),
    { args: ["ПолеВвода<ТипДанных>", "Соответствие<Строка, Число>"], ret: "ничто" }
  );
  assert.deepStrictEqual(parseEventSignature("()->ничто"), { args: [], ret: "ничто" });
  assert.strictEqual(parseEventSignature("Строка"), undefined);
  assert.strictEqual(parseEventSignature(""), undefined);
  assert.strictEqual(parseEventSignature(undefined), undefined);
});

const HANDLERS: ModuleHandlersPayload = {
  available: true,
  module: "file:///форма.xbsl",
  parseErrors: 0,
  methods: [
    { name: "ПриОткрытии", params: [] },
    { name: "КнопкаПриНажатии", params: [{ name: "Источник" }, { name: "Событие" }] },
    { name: "Пересчитать", params: [{ name: "Источник" }] },
    { name: "Сложный", params: [{ name: "А" }, { name: "Б" }, { name: "В" }] },
    { name: "Абстрактный", abstract: true, params: [] },
  ],
};

test("handlerChoices: parameter count splits suitable from the rest, module order kept", () => {
  const choices = handlerChoices("(Кнопка, СобытиеПриНажатии)->ничто", undefined, HANDLERS);
  // <= 2 parameters fit a two-argument event; the abstract method is not callable
  assert.deepStrictEqual(choices.compatible, ["ПриОткрытии", "КнопкаПриНажатии", "Пересчитать"]);
  assert.deepStrictEqual(choices.rest, ["Сложный"]);
  assert.strictEqual(choices.currentMissing, false);
});

test("handlerChoices: unknown signature - no split, everything stays reachable", () => {
  const choices = handlerChoices(undefined, undefined, HANDLERS);
  assert.deepStrictEqual(choices.compatible, []);
  assert.deepStrictEqual(choices.rest, [
    "ПриОткрытии", "КнопкаПриНажатии", "Пересчитать", "Сложный",
  ]);
});

test("handlerChoices: the missing-method flag needs a KNOWN module state", () => {
  assert.strictEqual(
    handlerChoices(undefined, "КнопкаПриНажатии", HANDLERS).currentMissing,
    false
  );
  assert.strictEqual(handlerChoices(undefined, "Нету", HANDLERS).currentMissing, true);
  // the module file does not exist - the bound method cannot exist either
  const noModule: ModuleHandlersPayload = { available: false, module: null, methods: [] };
  assert.strictEqual(handlerChoices(undefined, "Нету", noModule).currentMissing, true);
  // an older engine (no payload at all) must not cry wolf
  assert.strictEqual(handlerChoices(undefined, "Нету", undefined).currentMissing, false);
  assert.strictEqual(handlerChoices(undefined, undefined, HANDLERS).currentMissing, false);
});

test("buildPanelModel: event rows carry the dropdown choices when handlers are known", () => {
  const model = buildPanelModel(NODE, SCHEMA, FORM, HANDLERS);
  const row = model.sections[1].rows[0];
  assert.strictEqual(row.key, "ПриНажатии");
  assert.strictEqual(row.editor.control, "handler");
  const editor = row.editor as { control: "handler"; choices?: unknown };
  assert.deepStrictEqual(editor.choices, {
    compatible: ["ПриОткрытии", "КнопкаПриНажатии", "Пересчитать"],
    rest: ["Сложный"],
    currentMissing: true, // ОбработатьНажатие is bound in the yaml but absent in the module
  });
  // without the payload the editor still renders, just without the method list
  const bare = buildPanelModel(NODE, SCHEMA, FORM);
  const bareEditor = bare.sections[1].rows[0].editor as { control: string; choices?: { compatible: string[]; rest: string[]; currentMissing: boolean } };
  assert.deepStrictEqual(bareEditor.choices, { compatible: [], rest: [], currentMissing: false });
});

test("defaultHandlerName mirrors the engine: name, else type, plus the event key", () => {
  assert.strictEqual(defaultHandlerName({ name: "КнопкаОплатить", type: "Кнопка" }, "ПриНажатии"), "КнопкаОплатитьПриНажатии");
  assert.strictEqual(defaultHandlerName({ name: null, type: "Кнопка" }, "ПриНажатии"), "КнопкаПриНажатии");
  assert.strictEqual(defaultHandlerName({ name: "", type: "" }, "ПриНажатии"), "ПриНажатии");
});

test("buildAddHandlerParams: flat params, empty optionals omitted", () => {
  assert.deepStrictEqual(
    buildAddHandlerParams("file:///ф.yaml", "Наследует/Содержимое[0]", "ПриНажатии"),
    { uri: "file:///ф.yaml", node: "Наследует/Содержимое[0]", key: "ПриНажатии" }
  );
  assert.deepStrictEqual(
    buildAddHandlerParams("u", "n", "k", "  МойМетод  ", "(К, С)->ничто"),
    { uri: "u", node: "n", key: "k", method: "МойМетод", signature: "(К, С)->ничто" }
  );
  assert.deepStrictEqual(buildAddHandlerParams("u", "n", "k", "   "), { uri: "u", node: "n", key: "k" });
});

test("planHandlerApply: a new module file comes as full content, an existing one as edits", () => {
  const created = planHandlerApply({
    method: "КнопкаПриНажатии",
    created: true,
    methodAdded: true,
    yamlEdits: [{ start: 10, end: 10, newText: "ПриНажатии: КнопкаПриНажатии\n" }],
    moduleUri: "file:///форма.xbsl",
    moduleEdits: [],
    moduleText: "метод КнопкаПриНажатии()\n;\n",
    cursor: { uri: "file:///форма.xbsl", offset: 6 },
    notes: ["заметка"],
  });
  assert.ok("plan" in created);
  if ("plan" in created) {
    assert.strictEqual(created.plan.createFile, true);
    assert.strictEqual(created.plan.moduleText, "метод КнопкаПриНажатии()\n;\n");
    assert.deepStrictEqual(created.plan.moduleEdits, []);
    assert.strictEqual(created.plan.cursorOffset, 6);
    assert.deepStrictEqual(created.plan.notes, ["заметка"]);
  }

  const appended = planHandlerApply({
    method: "М",
    created: false,
    methodAdded: true,
    yamlEdits: [],
    moduleUri: "file:///форма.xbsl",
    moduleEdits: [{ start: 100, end: 100, newText: "\nметод М()\n;\n" }],
    cursor: { uri: "file:///форма.xbsl", offset: 108 },
  });
  assert.ok("plan" in appended);
  if ("plan" in appended) {
    assert.strictEqual(appended.plan.createFile, false);
    assert.deepStrictEqual(appended.plan.moduleEdits, [{ start: 100, end: 100, newText: "\nметод М()\n;\n" }]);
    assert.deepStrictEqual(appended.plan.yamlEdits, []);
    assert.deepStrictEqual(appended.plan.notes, []);
  }

  assert.deepStrictEqual(planHandlerApply({ error: "Узел не найден" }), { error: "Узел не найден" });
  // a defensive check against a malformed answer
  assert.ok("error" in planHandlerApply({ method: "М" }));
  assert.ok("error" in planHandlerApply({ method: "М", moduleUri: "file:///м.xbsl", created: true }));
});

async function runAsyncTests(): Promise<void> {
  // createSerialQueue: three jobs enqueued rapidly (like three quick tri-state clicks) run
  // strictly one at a time, in order - never overlapping.
  const q = createSerialQueue();
  const events: string[] = [];
  let active = 0;
  let maxActive = 0;
  const job = (id: number) => async (): Promise<void> => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    events.push(`start${id}`);
    await new Promise((r) => setTimeout(r, id === 0 ? 15 : 1)); // the first is the slowest
    events.push(`end${id}`);
    active -= 1;
  };
  await Promise.all([q(job(0)), q(job(1)), q(job(2))]);
  try {
    assert.strictEqual(maxActive, 1);
    assert.deepStrictEqual(events, ["start0", "end0", "start1", "end1", "start2", "end2"]);
    passed += 1;
    console.log("ok   createSerialQueue runs rapid jobs one at a time, in order");
  } catch (e) {
    failed += 1;
    console.error("FAIL createSerialQueue runs rapid jobs one at a time, in order");
    console.error(e instanceof Error ? e.message : e);
  }

  // A failing job must not break the chain for the next one.
  const q2 = createSerialQueue();
  const seen: number[] = [];
  const pa = q2(async () => {
    throw new Error("boom");
  }).catch(() => undefined);
  const pb = q2(async () => {
    seen.push(2);
  });
  await Promise.all([pa, pb]);
  try {
    assert.deepStrictEqual(seen, [2]);
    passed += 1;
    console.log("ok   createSerialQueue survives a failing job");
  } catch (e) {
    failed += 1;
    console.error("FAIL createSerialQueue survives a failing job");
    console.error(e instanceof Error ? e.message : e);
  }
}

void runAsyncTests().then(() => {
  console.log(`\n${passed} passed, ${failed} failed`);
  if (failed) {
    process.exit(1);
  }
});
