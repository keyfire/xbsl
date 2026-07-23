// Unit tests for the pure logic of the unified properties panel modes (src/propsModes.ts).
// No test runner and no vscode: plain Node asserts, bundled by esbuild. Run with `npm test`
// from editors/vscode.

import * as assert from "assert";
import { parseDocument } from "yaml";
import { parseInternals } from "../src/metadataCore";
import {
  buildMetaPanelModel,
  classifyEditor,
  describeMetaSelection,
  isRootNode,
  metaKindOf,
  metaNodeOffsetAt,
  metaSchemaPathAt,
  metaPropertyEdits,
  pairedYamlPath,
} from "../src/propsModes";

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

// Apply a batch of edits computed against ONE source text (descending starts keep the
// earlier offsets valid) - what the extension's WorkspaceEdit does.
function applyAll(text: string, edits: { start: number; end: number; newText: string }[]): string {
  const sorted = [...edits].sort((a, b) => b.start - a.start);
  let out = text;
  for (const e of sorted) {
    out = out.slice(0, e.start) + e.newText + out.slice(e.end);
  }
  return out;
}

function parses(text: string): boolean {
  return parseDocument(text, { uniqueKeys: false }).errors.length === 0;
}

function headOf(text: string): string {
  return text.split("\n").slice(0, 50).join("\n");
}

const CATALOG = `ВидЭлемента: Справочник
Ид: aaa
Имя: Товары
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: bbb
        Имя: Описание
        Тип: Строка
        Многострочная: Истина
    -
        Ид: ccc
        Имя: Цена
        Тип: Число
ТабличныеЧасти:
    -
        Ид: ddd
        Имя: Строки
        Реквизиты:
            -
                Ид: eee
                Имя: Количество
                Тип: Число
`;

const FORM = `ВидЭлемента: КомпонентИнтерфейса
Ид: fff
Имя: Карточка
Наследует:
    Тип: Форма
    Содержимое:
        -
            Тип: Надпись
`;

// --- classifyEditor -----------------------------------------------------------------------

test("classifyEditor: a component yaml drives the component mode", () => {
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\Карточка.yaml", headOf(FORM), FORM), "component");
});

test("classifyEditor: an element yaml without a form drives the metadata mode", () => {
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\Товары.yaml", headOf(CATALOG), CATALOG), "metadata");
});

test("classifyEditor: a yaml without ВидЭлемента drives nothing", () => {
  const plain = "Имя: Просто\nЗначение: 1\n";
  assert.strictEqual(classifyEditor("yaml", "C:\\p\\other.yaml", headOf(plain), plain), "none");
});

test("classifyEditor: an .xbsl module by language id or by extension", () => {
  assert.strictEqual(classifyEditor("xbsl", "C:\\p\\Товары.Объект.xbsl", "", ""), "module");
  assert.strictEqual(classifyEditor("plaintext", "C:\\p\\Товары.xbsl", "", ""), "module");
});

test("classifyEditor: non-yaml languages drive nothing", () => {
  assert.strictEqual(classifyEditor("markdown", "C:\\p\\readme.md", "", "ВидЭлемента: X"), "none");
});

// --- pairedYamlPath -----------------------------------------------------------------------

test("pairedYamlPath: same stem, the object module suffix is stripped", () => {
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.xbsl"), "C:\\p\\Задачи.yaml");
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.Объект.xbsl"), "C:\\p\\Задачи.yaml");
  assert.strictEqual(pairedYamlPath("/a/b/Карточка.xbsl"), "/a/b/Карточка.yaml");
});

test("pairedYamlPath: a non-module path has no pair", () => {
  assert.strictEqual(pairedYamlPath("C:\\p\\readme.md"), undefined);
  assert.strictEqual(pairedYamlPath("C:\\p\\Задачи.yaml"), undefined);
});

// --- metaNodeOffsetAt ---------------------------------------------------------------------

test("metaNodeOffsetAt: a cursor inside a field resolves to that field's map", () => {
  const internals = parseInternals(CATALOG)!;
  const cursor = CATALOG.indexOf("Цена");
  assert.strictEqual(metaNodeOffsetAt(CATALOG, cursor), internals.attributes[1].offset);
});

test("metaNodeOffsetAt: a nested tabular attribute wins as the deepest map", () => {
  const internals = parseInternals(CATALOG)!;
  const cursor = CATALOG.indexOf("Количество");
  assert.strictEqual(metaNodeOffsetAt(CATALOG, cursor), internals.tabulars[0].children![0].offset);
});

test("metaNodeOffsetAt: the top lines and section headers resolve to the object", () => {
  const internals = parseInternals(CATALOG)!;
  assert.strictEqual(metaNodeOffsetAt(CATALOG, 0), internals.rootOffset);
  assert.strictEqual(metaNodeOffsetAt(CATALOG, CATALOG.indexOf("Реквизиты")), internals.rootOffset);
});

test("metaNodeOffsetAt: offset 0 before leading comments falls back to the root map", () => {
  const commented = "# generated\n" + CATALOG;
  const internals = parseInternals(commented)!;
  assert.ok(internals.rootOffset > 0);
  assert.strictEqual(metaNodeOffsetAt(commented, 0), internals.rootOffset);
});

// --- metaSchemaPathAt ---------------------------------------------------------------------

test("metaSchemaPathAt: the object itself asks for the kind's own schema", () => {
  const internals = parseInternals(CATALOG)!;
  assert.deepStrictEqual(metaSchemaPathAt(CATALOG, internals.rootOffset), {
    sections: [],
    names: [],
  });
});

test("metaSchemaPathAt: an attribute carries its section and its name", () => {
  const internals = parseInternals(CATALOG)!;
  assert.deepStrictEqual(metaSchemaPathAt(CATALOG, internals.attributes[1].offset!), {
    sections: ["Реквизиты"],
    names: ["Цена"],
  });
});

test("metaSchemaPathAt: a nested tabular attribute carries both levels", () => {
  const internals = parseInternals(CATALOG)!;
  const offset = internals.tabulars[0].children![0].offset!;
  assert.deepStrictEqual(metaSchemaPathAt(CATALOG, offset), {
    sections: ["ТабличныеЧасти", "Реквизиты"],
    names: ["Строки", "Количество"],
  });
});

test("metaSchemaPathAt: an item without Имя still names its section", () => {
  const text = "ВидЭлемента: Перечисление\nИмя: Оценка\nЭлементы:\n    -\n        Ид: bbb\n";
  const offset = text.indexOf("Ид: bbb");
  assert.deepStrictEqual(metaSchemaPathAt(text, offset), {
    sections: ["Элементы"],
    names: [""],
  });
});

test("metaSchemaPathAt: a node that is not a collection item has no path", () => {
  // The map under `Наследует` is a block, not an item of a collection - the metamodel does
  // not address it this way, so the panel keeps showing the set rows alone.
  const offset = metaNodeOffsetAt(FORM, FORM.indexOf("Тип: Форма"))!;
  assert.strictEqual(metaSchemaPathAt(FORM, offset), undefined);
});

// --- describeMetaSelection ----------------------------------------------------------------

test("describeMetaSelection: a cursor describes the field under it", () => {
  const desc = describeMetaSelection(CATALOG, { cursor: CATALOG.indexOf("Число") })!;
  assert.strictEqual(desc.title, "Цена");
});

test("describeMetaSelection: an exact offset describes that node", () => {
  const internals = parseInternals(CATALOG)!;
  const desc = describeMetaSelection(CATALOG, { offset: internals.rootOffset })!;
  assert.strictEqual(desc.title, "Справочник");
});

test("describeMetaSelection: a synthetic standard attribute keeps offset -1", () => {
  const desc = describeMetaSelection(CATALOG, { std: { kind: "Справочник", name: "Код" } })!;
  assert.strictEqual(desc.offset, -1);
  assert.deepStrictEqual(desc.rows.map((r) => r.key), ["Тип", "Длина", "Уникальность"]);
});

// --- buildMetaPanelModel ------------------------------------------------------------------

test("buildMetaPanelModel: the object header carries ВидЭлемента and Имя", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(describeMetaSelection(CATALOG, { offset: internals.rootOffset })!);
  assert.strictEqual(model.meta, true);
  assert.strictEqual(model.type, "Справочник");
  assert.strictEqual(model.name, "Товары");
  // The kind and the read-only keys never sit among the editable rows: the kind is already
  // in the header (no row repeats it), Ид lives in the "readonly" section.
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set", "readonly"]);
  const keys = model.sections.flatMap((s) => s.rows.map((r) => r.key));
  assert.ok(!keys.includes("ВидЭлемента"));
  assert.ok(model.sections[0].rows.every((r) => r.editor.control !== "readonly"));
  assert.deepStrictEqual(model.sections[1].rows.map((r) => r.key), ["Ид"]);
});

test("buildMetaPanelModel: row editors map onto the shared controls", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { offset: internals.attributes[0].offset })!,
    ["Строка", "Число"]
  );
  const byKey = Object.fromEntries(model.sections.flatMap((s) => s.rows).map((r) => [r.key, r]));
  assert.strictEqual(byKey["Ид"].editor.control, "readonly");
  assert.strictEqual(byKey["Имя"].editor.control, "text");
  assert.strictEqual(byKey["Многострочная"].editor.control, "tristate");
  assert.strictEqual(byKey["Тип"].editor.control, "combo");
  assert.deepStrictEqual((byKey["Тип"].editor as { options: string[] }).options, ["Строка", "Число"]);
  assert.ok(model.sections.every((s) => s.rows.every((r) => r.set)));
  assert.strictEqual(byKey["Имя"].hay, "имя описание");
  // The field header does not repeat the name: title IS the name.
  assert.strictEqual(model.type, "Описание");
  assert.strictEqual(model.name, "");
});

test("buildMetaPanelModel: the object select rows become enum editors", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(describeMetaSelection(CATALOG, { offset: internals.rootOffset })!);
  const scope = model.sections[0].rows.find((r) => r.key === "ОбластьВидимости")!;
  assert.strictEqual(scope.editor.control, "enum");
  assert.deepStrictEqual((scope.editor as { options: string[] }).options, ["ВПроекте", "ВПодсистеме"]);
});

test("buildMetaPanelModel: a synthetic standard attribute renders every row as not set", () => {
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { std: { kind: "Справочник", name: "Код" } })!
  );
  assert.strictEqual(model.type, "Код");
  assert.strictEqual(model.name, "");
  assert.ok(model.sections[0].rows.every((r) => !r.set));
});

// --- the metadata schema of a kind (xbsl/metadataSchema) -----------------------------------

// What the engine answers for Справочник, trimmed to what the panel needs.
const CATALOG_SCHEMA = {
  kind: "Справочник",
  props: {
    Представление: { kind: "string", type: "AttributeName", priority: 9900 },
    Иерархический: { kind: "boolean", type: "boolean", default: "false", since: "8.0" },
    РежимУдаления: { kind: "enum", enum: "DeletionMode", default: "ПометкаУдаления" },
    СозданиеНаОсновании: { kind: "type", item: "Type" },
    Реквизиты: { kind: "list", item: "ICatalogAttributeDescriptor" },
    КонтрольДоступа: { kind: "block", type: "CatalogAccessControl" },
    Разработчик: { kind: "string", deprecated: true },
    ОбластьВидимости: { kind: "enum", enum: "VisibilityScopeEnum" },
  },
  enums: {
    DeletionMode: ["Немедленно", "ПометкаУдаления"],
    VisibilityScopeEnum: ["ВПодсистеме", "ВПроекте", "Глобально"],
  },
};

test("buildMetaPanelModel: the schema adds the applicable properties below the set ones", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { offset: internals.rootOffset })!,
    ["Товары.Ссылка"],
    CATALOG_SCHEMA
  );
  assert.strictEqual(model.schemaAvailable, true);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set", "all", "readonly"]);
  const all = Object.fromEntries(model.sections[1].rows.map((r) => [r.key, r]));
  const ro = Object.fromEntries(model.sections[2].rows.map((r) => [r.key, r]));
  // Not written in the file - and now visible, which is the whole point.
  assert.strictEqual(all["Иерархический"].set, false);
  assert.strictEqual(all["Иерархический"].editor.control, "tristate");
  assert.strictEqual(all["Иерархический"].defaultValue, "false");
  assert.strictEqual(all["Иерархический"].since, "8.0");
  assert.strictEqual(all["Представление"].editor.control, "text");
  assert.strictEqual(all["РежимУдаления"].editor.control, "enum");
  assert.deepStrictEqual(
    (all["РежимУдаления"].editor as { options: string[] }).options,
    ["Немедленно", "ПометкаУдаления"]
  );
  // A data type takes the project's candidates, the same open combobox as Тип.
  assert.strictEqual(all["СозданиеНаОсновании"].editor.control, "combo");
  assert.deepStrictEqual(
    (all["СозданиеНаОсновании"].editor as { options: string[] }).options,
    ["Товары.Ссылка"]
  );
  // Structures are shown (so they are discoverable) but not edited here - the tree owns
  // them, and the panel keeps them apart from the editable rows, in the readonly section.
  assert.ok(!("Реквизиты" in all));
  assert.ok(!("КонтрольДоступа" in all));
  assert.strictEqual(ro["Реквизиты"].editor.control, "readonly");
  assert.strictEqual(ro["КонтрольДоступа"].editor.control, "readonly");
  // A property already written in the file is marked as set in this section too.
  assert.strictEqual(all["ОбластьВидимости"].set, true);
  assert.strictEqual(all["ОбластьВидимости"].value, "ВПроекте");
  // An old spelling kept for compatibility is not offered.
  assert.ok(!("Разработчик" in all));
  // The kind row never renders - the header names the kind already.
  assert.ok(!("ВидЭлемента" in all) && !("ВидЭлемента" in ro));
  // No key is shown twice across the sections that are visible together.
  const seen = model.sections.filter((s) => s.id !== "all").flatMap((s) => s.rows.map((r) => r.key));
  assert.strictEqual(new Set(seen).size, seen.length);
});

// What the engine answers for the Код standard attribute (a class of its own in the metamodel).
const CODE_ATTR_SCHEMA = {
  kind: "Справочник",
  props: {
    Тип: { kind: "enum", enum: "CodeType", default: "Строка" },
    Длина: { kind: "number", default: "9" },
    Уникальность: { kind: "boolean", default: "true" },
    Автонумерация: { kind: "boolean", default: "true" },
  },
  enums: { CodeType: ["Строка", "Число"] },
};

test("buildMetaPanelModel: a synthetic standard attribute with a schema shows the real set", () => {
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { std: { kind: "Справочник", name: "Код" } })!,
    undefined,
    CODE_ATTR_SCHEMA
  );
  assert.strictEqual(model.schemaAvailable, true);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set", "all"]);
  // The handwritten spec rows give way to the schema: nothing is set, and the properties the
  // spec never knew (Автонумерация) become discoverable - that closes the "no all-properties
  // section on Код/Наименование" gap.
  assert.strictEqual(model.sections[0].rows.length, 0);
  const all = Object.fromEntries(model.sections[1].rows.map((r) => [r.key, r]));
  assert.ok(model.sections[1].rows.every((r) => !r.set));
  assert.strictEqual(all["Автонумерация"].editor.control, "tristate");
  assert.strictEqual(all["Длина"].defaultValue, "9");
  assert.deepStrictEqual((all["Тип"].editor as { options: string[] }).options, ["Строка", "Число"]);
});

test("buildMetaPanelModel: a collection present in yaml is set, its size is the value", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { offset: internals.rootOffset })!,
    undefined,
    CATALOG_SCHEMA
  );
  const ro = Object.fromEntries(model.sections[2].rows.map((r) => [r.key, r]));
  // The catalog writes two attributes: the row must not read "(not set)" only because
  // collections carry no scalar row. The size stands for the value; editing stays with the tree.
  assert.strictEqual(ro["Реквизиты"].set, true);
  assert.strictEqual(ro["Реквизиты"].value, "2");
  assert.strictEqual(ro["Реквизиты"].editor.control, "readonly");
  // A block absent from yaml stays honestly unset.
  assert.strictEqual(ro["КонтрольДоступа"].set, false);
});

test("buildMetaPanelModel: the schema types the editors of the set rows", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(
    describeMetaSelection(CATALOG, { offset: internals.rootOffset })!,
    undefined,
    CATALOG_SCHEMA
  );
  const set = Object.fromEntries(model.sections[0].rows.map((r) => [r.key, r]));
  // The metamodel knows the enumeration - the row offers its values, not a free-text field.
  assert.strictEqual(set["ОбластьВидимости"].editor.control, "enum");
  assert.deepStrictEqual(
    (set["ОбластьВидимости"].editor as { options: string[] }).options,
    ["ВПодсистеме", "ВПроекте", "Глобально"]
  );
  // Read-only keys stay read-only - and sit in their own section, not among the editable rows.
  assert.ok(!("Ид" in set));
  const ro = Object.fromEntries(model.sections.find((s) => s.id === "readonly")!.rows.map((r) => [r.key, r]));
  assert.strictEqual(ro["Ид"].editor.control, "readonly");
});

test("buildMetaPanelModel: without a schema the panel keeps the set rows, readonly apart", () => {
  const internals = parseInternals(CATALOG)!;
  const model = buildMetaPanelModel(describeMetaSelection(CATALOG, { offset: internals.rootOffset })!);
  assert.strictEqual(model.schemaAvailable, false);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set", "readonly"]);
});

test("buildMetaPanelModel: an enumeration with items - the count in readonly, no duplicates", () => {
  // The reported case: five values in yaml, and the panel called Элементы "(not set)" while
  // repeating the read-only rows in both sections and the kind in a row of its own.
  const enumYaml = [
    "ВидЭлемента: Перечисление",
    "ОбластьВидимости: ВПодсистеме",
    "Ид: 9633168e-730d-47ca-836b-b432a8d7b153",
    "Имя: ВариантПревью",
    "Элементы:",
    "    -",
    "        Ид: 0daefecc-5430-4d35-b146-648afe7f9e75",
    "        Имя: БезПриложений",
    "    -",
    "        Ид: 1a450a64-d8b5-49c5-bbe1-363e45d474a7",
    "        Имя: СПриложениями",
    "",
  ].join("\n");
  const schema = {
    kind: "Перечисление",
    props: {
      Имя: { kind: "string" },
      ОбластьВидимости: { kind: "enum", enum: "VisibilityScopeEnum" },
      Импорт: { kind: "list", item: "NamespaceHolder" },
      ВидЭлемента: { kind: "string" },
      Ид: { kind: "string" },
      Элементы: { kind: "list", item: "EnumerationItem" },
    },
    enums: { VisibilityScopeEnum: ["ВПодсистеме", "ВПроекте", "Глобально"] },
  };
  const model = buildMetaPanelModel(describeMetaSelection(enumYaml, { cursor: 0 })!, undefined, schema);
  assert.deepStrictEqual(model.sections.map((s) => s.id), ["set", "all", "readonly"]);
  const ro = Object.fromEntries(model.sections[2].rows.map((r) => [r.key, r]));
  assert.strictEqual(ro["Элементы"].set, true);
  assert.strictEqual(ro["Элементы"].value, "2"); // the size, not "(not set)"
  assert.strictEqual(ro["Импорт"].set, false); // truly absent stays honestly unset
  assert.deepStrictEqual(model.sections[2].rows.map((r) => r.key), ["Ид", "Импорт", "Элементы"]);
  const keys = model.sections.flatMap((s) => s.rows.map((r) => r.key));
  assert.ok(!keys.includes("ВидЭлемента"));
  assert.deepStrictEqual(model.sections[0].rows.map((r) => r.key), ["ОбластьВидимости", "Имя"]);
});

test("metaKindOf/isRootNode: the schema applies to the object, not to a field", () => {
  const internals = parseInternals(CATALOG)!;
  assert.strictEqual(metaKindOf(CATALOG), "Справочник");
  assert.strictEqual(metaKindOf("Имя: Товары\n"), undefined);
  assert.ok(isRootNode(CATALOG, internals.rootOffset));
  assert.ok(!isRootNode(CATALOG, internals.attributes[0].offset!));
});

test("metaPropertyEdits: writing an unset schema property inserts the key", () => {
  const internals = parseInternals(CATALOG)!;
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: internals.rootOffset }, "Иерархический", "Истина")
  );
  assert.ok(parses(out));
  assert.ok(/^Иерархический: Истина$/m.test(out));
});

// --- metaPropertyEdits --------------------------------------------------------------------

test("metaPropertyEdits: a scalar write replaces the value in place", () => {
  const internals = parseInternals(CATALOG)!;
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: internals.attributes[1].offset! }, "Имя", "Стоимость")
  );
  assert.ok(parses(out));
  assert.deepStrictEqual(parseInternals(out)!.attributes.map((a) => a.name), ["Описание", "Стоимость"]);
});

test("metaPropertyEdits: value null removes the key line", () => {
  const internals = parseInternals(CATALOG)!;
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: internals.rootOffset }, "ОбластьВидимости", null)
  );
  assert.ok(parses(out));
  assert.ok(!out.includes("ОбластьВидимости"));
});

test("metaPropertyEdits: Тип changed off Строка also drops Многострочная", () => {
  const internals = parseInternals(CATALOG)!;
  const edits = metaPropertyEdits(CATALOG, { offset: internals.attributes[0].offset! }, "Тип", "Число");
  assert.strictEqual(edits.length, 2);
  const out = applyAll(CATALOG, edits);
  assert.ok(parses(out));
  const attr = parseInternals(out)!.attributes[0];
  assert.strictEqual(attr.type, "Число");
  assert.ok(!out.includes("Многострочная"));
});

test("metaPropertyEdits: Тип kept a string does not touch Многострочная", () => {
  const internals = parseInternals(CATALOG)!;
  const edits = metaPropertyEdits(CATALOG, { offset: internals.attributes[0].offset! }, "Тип", "Строка?");
  assert.strictEqual(edits.length, 1);
  const out = applyAll(CATALOG, edits);
  assert.ok(parses(out));
  assert.ok(out.includes("Многострочная"));
});

test("metaPropertyEdits: a synthetic standard attribute materializes into Реквизиты", () => {
  const out = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", "250")
  );
  assert.ok(parses(out));
  const added = parseInternals(out)!.attributes.find((a) => a.name === "Наименование");
  assert.ok(added, "the record must appear in Реквизиты");
  assert.ok(out.includes("Длина: 250"));
});

test("metaPropertyEdits: removing from a non-materialized standard attribute is a no-op", () => {
  assert.deepStrictEqual(
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", null),
    []
  );
});

test("metaPropertyEdits: a materialized standard attribute edits its record by name", () => {
  const materialized = applyAll(
    CATALOG,
    metaPropertyEdits(CATALOG, { offset: -1, std: { name: "Наименование" } }, "Длина", "250")
  );
  const out = applyAll(
    materialized,
    metaPropertyEdits(materialized, { offset: -1, std: { name: "Наименование" } }, "Длина", "500")
  );
  assert.ok(parses(out));
  assert.ok(out.includes("Длина: 500"));
  assert.ok(!out.includes("Длина: 250"));
});

// -----------------------------------------------------------------------------

console.log(`\ntotal: ${passed} ok, ${failed} fail`);
if (failed > 0) {
  process.exit(1);
}
