// Unit tests for the pure properties-panel core (src/formPropsCore.ts) and the shared
// webview helpers (src/webviewShared.ts). No test runner and no vscode: plain Node asserts,
// bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  FormNodeDto,
  NodePropertyDto,
  PanelModel,
  SpanDto,
  UiComponentDto,
  buildCompositeYaml,
  buildPanelModel,
  chooseEditor,
  colorYaml,
  encodeFragmentScalar,
  extractScalarValue,
  findRow,
  hexFromColorFields,
  parseCompositeFields,
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
    Картинка: { types: ["Картинка"], slot: true },
    Индекс: { types: ["Число"], readonly: true },
  },
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

test("buildPanelModel: set section keeps the file order, events go to their own section", () => {
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
  assert.strictEqual(set.rows[0].value, "Привет <мир>");
  assert.strictEqual(set.rows[0].doc, "Заголовок надписи.");
  assert.strictEqual(set.rows[1].editor.control, "tristate");
  const color = set.rows[2];
  assert.strictEqual(color.editor.control, "color");
  assert.strictEqual(color.colorHex, "#595964");
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
  assert.strictEqual(keys.length, 8);
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

test("buildPanelModel: without a schema only the set section remains, kind-based editors", () => {
  const model = buildPanelModel(NODE, null, FORM);
  assert.strictEqual(model.schemaAvailable, false);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set"]);
  const rows = model.sections[0].rows;
  assert.deepStrictEqual(
    rows.map((r) => r.key),
    ["Заголовок", "РастягиватьПоГоризонтали", "Цвет", "ПриНажатии"]
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

console.log(`\n${passed} passed, ${failed} failed`);
if (failed) {
  process.exit(1);
}
