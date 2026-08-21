// Unit tests for the pure form-designer core (src/formDesignerCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  componentNameOfPath,
  formPathOfModule,
  looksLikeFormText,
  modulePathOfForm,
  neighborColumn,
  revealStartColumn,
  shouldRevealInEditor,
  DataLabels,
  DataModel,
  DEFAULT_LAYOUT,
  dataMenu,
  expandAncestors,
  flattenData,
  flattenStructure,
  isRowExpanded,
  OBJECT_SECTION_ID,
  PROPS_SECTION_ID,
  propertyRowId,
  sanitizeLayout,
  structureMenu,
} from "../src/formDesignerCore";
import { FormNode, indexTree, NodeDiagBadge, ROOT_ID } from "../src/formStructureCore";

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

// --- fixtures (the shapes the engine's node_dict emits) -----------------------------------

function comp(
  id: string,
  type: string | null,
  name: string | null,
  span: [number, number],
  children: FormNode[] = [],
  properties: Array<{ key: string; kind: string; valuePreview: string }> = []
): FormNode {
  return {
    id,
    kind: "component",
    span: { start: span[0], end: span[1] },
    type,
    typeFull: type,
    name,
    slot: null,
    properties,
    children,
  };
}

function slot(id: string, name: string, span: [number, number], children: FormNode[]): FormNode {
  return { id, kind: "slot", span: { start: span[0], end: span[1] }, name, list: true, children };
}

// Наследует
//   Содержимое
//     [0] Группа Шапка
//         Содержимое
//           [0] Надпись Заголовок
//           [1] Кнопка (безымянная)
//     [1] ПолеВвода Поиск
const LABEL = comp(
  "Наследует/Содержимое[0]/Содержимое[0]",
  "Надпись",
  "Заголовок",
  [40, 100],
  [],
  [{ key: "Заголовок", kind: "scalar", valuePreview: "О сервисе" }]
);
const BUTTON = comp("Наследует/Содержимое[0]/Содержимое[1]", "Кнопка", null, [100, 190]);
const INNER_SLOT = slot("Наследует/Содержимое[0]/Содержимое", "Содержимое", [30, 190], [LABEL, BUTTON]);
const GROUP = comp("Наследует/Содержимое[0]", "Группа", "Шапка", [20, 200], [INNER_SLOT]);
const FIELD = comp("Наследует/Содержимое[1]", "ПолеВвода", "Поиск", [200, 300]);
const CONTENT_SLOT = slot("Наследует/Содержимое", "Содержимое", [10, 300], [GROUP, FIELD]);
const ROOT = comp(ROOT_ID, "Форма", null, [0, 500], [CONTENT_SLOT]);
const INDEX = indexTree(ROOT);

const EMPTY = new Set<string>();
const BASE = { expanded: EMPTY, collapsed: EMPTY };

// --- structure flattening -----------------------------------------------------------------

test("default expansion opens the root and the slots, keeps components closed", () => {
  // The rule the native tree followed; a webview has to be TOLD it, so it is worth pinning.
  assert.strictEqual(isRowExpanded(ROOT, true, BASE), true);
  assert.strictEqual(isRowExpanded(CONTENT_SLOT, false, BASE), true);
  assert.strictEqual(isRowExpanded(GROUP, false, BASE), false);
  // Hand-made state wins over the default, in both directions.
  assert.strictEqual(isRowExpanded(GROUP, false, { ...BASE, expanded: new Set([GROUP.id]) }), true);
  assert.strictEqual(isRowExpanded(CONTENT_SLOT, false, { ...BASE, collapsed: new Set([CONTENT_SLOT.id]) }), false);
});

test("flattenStructure walks pre-order and stops at a collapsed row", () => {
  const rows = flattenStructure(INDEX, BASE);
  assert.deepStrictEqual(
    rows.map((r) => r.id),
    [ROOT_ID, CONTENT_SLOT.id, GROUP.id, FIELD.id]
  );
  assert.deepStrictEqual(
    rows.map((r) => r.depth),
    [0, 1, 2, 2]
  );
  // The closed Группа still advertises children - otherwise there is no twisty to open it.
  const group = rows.find((r) => r.id === GROUP.id)!;
  assert.strictEqual(group.hasChildren, true);
  assert.strictEqual(group.expanded, false);
  // Opening it brings its slot and the two components in.
  const opened = flattenStructure(INDEX, { ...BASE, expanded: new Set([GROUP.id]) });
  assert.deepStrictEqual(
    opened.map((r) => r.id),
    [ROOT_ID, CONTENT_SLOT.id, GROUP.id, INNER_SLOT.id, LABEL.id, BUTTON.id, FIELD.id]
  );
});

test("row kinds, labels and draggability follow the node", () => {
  const rows = flattenStructure(INDEX, { ...BASE, expanded: new Set([GROUP.id]) });
  const byId = new Map(rows.map((r) => [r.id, r]));
  assert.strictEqual(byId.get(ROOT_ID)!.kind, "root");
  assert.strictEqual(byId.get(CONTENT_SLOT.id)!.kind, "slot");
  assert.strictEqual(byId.get(GROUP.id)!.kind, "component");
  assert.strictEqual(byId.get(GROUP.id)!.label, "Группа Шапка");
  assert.strictEqual(byId.get(LABEL.id)!.description, "О сервисе");
  assert.strictEqual(byId.get(CONTENT_SLOT.id)!.description, "2");
  // Only components are dragged; the root and the slots stay put.
  assert.strictEqual(byId.get(GROUP.id)!.draggable, true);
  assert.strictEqual(byId.get(CONTENT_SLOT.id)!.draggable, false);
  assert.strictEqual(byId.get(ROOT_ID)!.draggable, false);
  // A container is marked as such (Группа is in the offline container list).
  assert.strictEqual(byId.get(GROUP.id)!.container, true);
  assert.strictEqual(byId.get(FIELD.id)!.container, false);
});

test("the focused subtree becomes the root row at depth 0", () => {
  const rows = flattenStructure(INDEX, { ...BASE, rootId: GROUP.id });
  assert.deepStrictEqual(
    rows.map((r) => r.id),
    [GROUP.id, INNER_SLOT.id, LABEL.id, BUTTON.id]
  );
  assert.strictEqual(rows[0].depth, 0);
  // A focus id that no longer exists (the node was deleted) falls back to the form root.
  const stale = flattenStructure(INDEX, { ...BASE, rootId: "Наследует/Ушедший[7]" });
  assert.strictEqual(stale[0].id, ROOT_ID);
});

test("the named-only filter hides rows and their subtrees", () => {
  const visible = new Set([ROOT_ID, CONTENT_SLOT.id, GROUP.id, FIELD.id]);
  const rows = flattenStructure(INDEX, { ...BASE, visibleIds: visible, expanded: new Set([GROUP.id]) });
  // INNER_SLOT is not in the visible set: the unnamed Кнопка under it never shows either.
  assert.deepStrictEqual(
    rows.map((r) => r.id),
    [ROOT_ID, CONTENT_SLOT.id, GROUP.id, FIELD.id]
  );
});

test("a diagnostic badge is carried into the row and its description", () => {
  const badges = new Map<string, NodeDiagBadge>([
    [FIELD.id, { count: 2, severity: 0, firstMessage: "Неизвестное свойство" }],
  ]);
  const rows = flattenStructure(INDEX, { ...BASE, badges });
  const field = rows.find((r) => r.id === FIELD.id)!;
  assert.deepStrictEqual(field.badge, { count: 2, severity: 0 });
  assert.strictEqual(field.description, "(2)");
  assert.ok(field.tooltip.includes("Неизвестное свойство"));
  // A property preview and a badge live together, separated by the middle dot.
  const withPreview = flattenStructure(INDEX, {
    ...BASE,
    expanded: new Set([GROUP.id]),
    badges: new Map([[LABEL.id, { count: 1, severity: 1, firstMessage: "x" }]]),
  });
  assert.strictEqual(withPreview.find((r) => r.id === LABEL.id)!.description, "О сервисе · (1)");
});

test("the container predicate reaches the icon and the container flag", () => {
  // A type unknown offline (Аккордеон) counts as a container only through the ui schema.
  const accordion = comp("Наследует/Содержимое[2]", "Аккордеон", null, [300, 320]);
  const index = indexTree(comp(ROOT_ID, "Форма", null, [0, 500], [slot("Наследует/Содержимое", "Содержимое", [10, 400], [accordion])]));
  const plain = flattenStructure(index, BASE).find((r) => r.id === accordion.id)!;
  assert.strictEqual(plain.container, false);
  const schema = flattenStructure(index, { ...BASE, isContainerType: (t) => t === "Аккордеон" }).find(
    (r) => r.id === accordion.id
  )!;
  assert.strictEqual(schema.container, true);
});

test("expandAncestors opens the whole chain, so a reveal can land inside a collapsed group", () => {
  // The frame click / yaml cursor picks a node the pane does not currently show: BUTTON sits
  // under Группа, and Группа is closed by default - the row is not in the flat list at all.
  const expanded = new Set<string>();
  const collapsed = new Set<string>([GROUP.id, INNER_SLOT.id]);
  assert.ok(!flattenStructure(INDEX, { ...BASE, collapsed }).some((r) => r.id === BUTTON.id));
  assert.strictEqual(expandAncestors(INDEX, BUTTON.id, expanded, collapsed), true);
  // Both the group and its slot are open now; the node itself is NOT force-expanded.
  assert.deepStrictEqual([...collapsed], []);
  assert.ok(expanded.has(GROUP.id) && expanded.has(INNER_SLOT.id) && expanded.has(CONTENT_SLOT.id));
  assert.ok(!expanded.has(BUTTON.id));
  const rows = flattenStructure(INDEX, { expanded, collapsed });
  assert.ok(rows.some((r) => r.id === BUTTON.id));
  // Nothing to open twice, and an unknown id is a no-op rather than a crash.
  assert.strictEqual(expandAncestors(INDEX, BUTTON.id, expanded, collapsed), false);
  assert.strictEqual(expandAncestors(INDEX, "Наследует/Ушедший[9]", expanded, collapsed), false);
});

// --- data flattening ----------------------------------------------------------------------

const LABELS: DataLabels = {
  propsSection: "Свойства компонента",
  objectSection: "Реквизиты объекта",
  propertyTooltip: "Свойство компонента",
  attributeTooltip: "Реквизит объекта",
  tabularTooltip: "Табличная часть",
  insertHint: "Двойной клик вставляет поле",
};

const DATA: DataModel = {
  records: [
    { name: "Заголовок", type: "Строка", span: { start: 10, end: 20 } },
    { name: null, type: null, span: { start: 20, end: 30 } },
  ],
  owner: { name: "Товары", kind: "Справочник" },
  fields: [
    { name: "Наименование", type: "Строка" },
    { name: "Проведён", type: "Булево" },
  ],
  tabulars: [{ name: "Состав", fields: [{ name: "Количество", type: "Число" }] }],
};

test("flattenData shows both sections with their counts", () => {
  const rows = flattenData(DATA, EMPTY, EMPTY, LABELS);
  assert.deepStrictEqual(
    rows.map((r) => r.id),
    [PROPS_SECTION_ID, "prop:Заголовок", "prop#1", OBJECT_SECTION_ID, "attr:Наименование", "attr:Проведён", "tab:Состав"]
  );
  assert.strictEqual(rows[0].description, "2");
  assert.strictEqual(rows[3].description, "Товары · 3");
  // A tabular part is closed by default and opens on demand.
  assert.strictEqual(rows[6].expanded, false);
  const opened = flattenData(DATA, new Set(["tab:Состав"]), EMPTY, LABELS);
  assert.strictEqual(opened[opened.length - 1].id, "col:Состав:Количество");
  assert.strictEqual(opened[opened.length - 1].depth, 2);
});

test("only named records and attributes are insertable", () => {
  const rows = flattenData(DATA, EMPTY, EMPTY, LABELS);
  const byId = new Map(rows.map((r) => [r.id, r]));
  assert.strictEqual(byId.get("prop:Заголовок")!.insertable, true);
  // A record without Имя is shown but cannot become a field - it has nothing to bind to.
  assert.strictEqual(byId.get("prop#1")!.insertable, false);
  assert.strictEqual(byId.get("prop#1")!.label, "?");
  assert.strictEqual(byId.get("attr:Наименование")!.insertable, true);
  assert.strictEqual(byId.get("tab:Состав")!.insertable, false);
  // The insert hint rides only on the rows that can actually be inserted.
  assert.ok(byId.get("attr:Наименование")!.tooltip.includes(LABELS.insertHint));
  assert.ok(!byId.get("prop#1")!.tooltip.includes(LABELS.insertHint));
});

test("a form with no owner object shows only the properties section", () => {
  const rows = flattenData({ ...DATA, owner: undefined }, EMPTY, EMPTY, LABELS);
  assert.ok(!rows.some((r) => r.id === OBJECT_SECTION_ID));
  // A collapsed section keeps its records out of the row list.
  const collapsed = flattenData(DATA, EMPTY, new Set([PROPS_SECTION_ID]), LABELS);
  assert.ok(!collapsed.some((r) => r.kind === "property"));
  assert.strictEqual(collapsed[0].expanded, false);
});

test("propertyRowId keys by name and falls back to the position", () => {
  assert.strictEqual(propertyRowId({ name: "Х", type: null, span: { start: 0, end: 1 } }, 3), "prop:Х");
  assert.strictEqual(propertyRowId({ name: null, type: null, span: { start: 0, end: 1 } }, 3), "prop#3");
});

// --- menus --------------------------------------------------------------------------------

test("the structure menu offers moves only on components", () => {
  const rows = flattenStructure(INDEX, BASE);
  const group = rows.find((r) => r.id === GROUP.id)!;
  const commands = structureMenu(group).map((i) => i.command);
  for (const expected of ["moveUp", "moveDown", "rename", "delete", "duplicate", "copyYaml", "focusSubtree"]) {
    assert.ok(commands.includes(expected), `меню компонента без ${expected}`);
  }
  // Unwrap only makes sense for a container.
  assert.ok(commands.includes("unwrap"));
  assert.ok(!structureMenu(rows.find((r) => r.id === FIELD.id)!).map((i) => i.command).includes("unwrap"));
  // A slot and the root are insertion targets, not movable nodes.
  const slotCommands = structureMenu(rows.find((r) => r.id === CONTENT_SLOT.id)!).map((i) => i.command);
  assert.deepStrictEqual(slotCommands, ["openInEditor", "pasteYaml", "insertPreset"]);
  assert.deepStrictEqual(structureMenu(rows[0]).map((i) => i.command), slotCommands);
  // The mass edit shows up only with several rows selected.
  assert.ok(!commands.includes("editSelected"));
  assert.ok(structureMenu(group, 3).map((i) => i.command).includes("editSelected"));
});

test("the data menu edits own properties and only inserts foreign ones", () => {
  const rows = flattenData(DATA, EMPTY, EMPTY, LABELS);
  const byId = new Map(rows.map((r) => [r.id, r]));
  assert.deepStrictEqual(
    dataMenu(byId.get("prop:Заголовок")!).map((i) => i.command),
    ["insert", "renameProperty", "retypeProperty", "removeProperty", "addProperty"]
  );
  // A broken record cannot be inserted, but is still renameable-free: the name-keyed
  // operations need a name, so only the section-level add remains meaningful.
  assert.ok(!dataMenu(byId.get("prop#1")!).map((i) => i.command).includes("insert"));
  assert.deepStrictEqual(dataMenu(byId.get("attr:Наименование")!).map((i) => i.command), ["insert"]);
  assert.deepStrictEqual(dataMenu(byId.get("tab:Состав")!), []);
  assert.deepStrictEqual(dataMenu(byId.get(PROPS_SECTION_ID)!).map((i) => i.command), ["addProperty"]);
});

// --- layout -------------------------------------------------------------------------------

test("sanitizeLayout clamps the splitters and survives junk", () => {
  assert.deepStrictEqual(sanitizeLayout(undefined), DEFAULT_LAYOUT);
  assert.deepStrictEqual(sanitizeLayout({ left: 30, top: 60 }), { left: 30, top: 60 });
  // A splitter dragged to the edge would make a pane unreachable.
  assert.deepStrictEqual(sanitizeLayout({ left: 0, top: 100 }), { left: 15, top: 85 });
  // Junk from an older panel version, or a hand-edited state file.
  assert.deepStrictEqual(sanitizeLayout({ left: "нет", top: NaN }), DEFAULT_LAYOUT);
  assert.deepStrictEqual(sanitizeLayout("сломано"), DEFAULT_LAYOUT);
  assert.deepStrictEqual(sanitizeLayout({ left: 41.6, top: 33.2 }), { left: 42, top: 33 });
});

// --- горизонтальная прокрутка при переходе к узлу ---------------------------------------
// Узел формы лежит на восьмом уровне вложенности: если прокрутить ровно к тексту, отступ
// исчезает и вложенность становится нечитаемой. Оставляем ОДИН уровень перед текстом.
test("переход к узлу оставляет один уровень отступа", () => {
  assert.strictEqual(revealStartColumn(32, 4), 28);
  assert.strictEqual(revealStartColumn(0, 4), 0);
  assert.strictEqual(revealStartColumn(4, 4), 0);
  assert.strictEqual(revealStartColumn(12, NaN), 8);
});

// --- shouldRevealInEditor -------------------------------------------------------------------
// A field click in the form frame is an IMPLICIT follow: it must never open a closed yaml, and
// must not pull an already-open one out from behind the panel's own column - doing so covers
// the panel the click was aimed at. An EXPLICIT request ("Show in yaml", Ctrl+click) is a
// direct ask and always opens, exactly as before this guard existed.

test("shouldRevealInEditor: explicit call, yaml tab closed - opens", () => {
  assert.strictEqual(shouldRevealInEditor(true, undefined, 1), true);
});

test("shouldRevealInEditor: implicit follow, yaml tab closed - does not open", () => {
  assert.strictEqual(shouldRevealInEditor(false, undefined, 1), false);
});

test("shouldRevealInEditor: implicit follow, yaml open in another column - opens", () => {
  assert.strictEqual(shouldRevealInEditor(false, 2, 1), true);
});

test("shouldRevealInEditor: implicit follow, yaml open in the panel's own column - does not open", () => {
  assert.strictEqual(shouldRevealInEditor(false, 1, 1), false);
});

// The explicit path is a direct ask, not a follow: it always opens, whatever column the yaml
// tab is already in (or none) - unchanged from the behaviour before this guard existed. The
// case where that tab happens to sit in the panel's own column is unusual (the panel would be
// showing on top of it already) but the request still stands: an explicit "Show in yaml" must
// bring the yaml forward, even if that means it now covers the panel that issued the request.
test("shouldRevealInEditor: explicit call, yaml open in the panel's own column - still opens", () => {
  assert.strictEqual(shouldRevealInEditor(true, 1, 1), true);
});

// --- neighborColumn -------------------------------------------------------------------------
// Where a freshly created module opens: the panel's own column is excluded at every tier
// (reusing the module's own tab, joining a source group) - landing there would put the new
// code behind the very panel that just created it. undefined means "no existing candidate,
// split a new group beside the active one" - the caller maps that to vscode.ViewColumn.Beside.

test("neighborColumn: the module's own tab, open elsewhere - reused", () => {
  assert.strictEqual(neighborColumn(2, 3, 1), 2);
});

test("neighborColumn: no module tab, a source group open elsewhere - joins it", () => {
  assert.strictEqual(neighborColumn(undefined, 3, 1), 3);
});

test("neighborColumn: the module's own tab sits in the panel's column - skipped for the source group", () => {
  assert.strictEqual(neighborColumn(1, 3, 1), 3);
});

test("neighborColumn: only the panel's own column has anything open - splits beside", () => {
  assert.strictEqual(neighborColumn(1, 1, 1), undefined);
});

test("neighborColumn: nothing open anywhere - splits beside", () => {
  assert.strictEqual(neighborColumn(undefined, undefined, undefined), undefined);
});

// The component name behind a yaml path: the designer drops the cached text of a nested component
// when its own file is edited, so the frame stops showing the previous version.
test("componentNameOfPath: имя элемента из пути", () => {
  assert.strictEqual(componentNameOfPath("/d/proj/e1c/Основное/КарточкаЗадачи.yaml"), "КарточкаЗадачи");
});

test("componentNameOfPath: путь Windows", () => {
  assert.strictEqual(componentNameOfPath(String.raw`C:\проект\Сайт\Форма.yaml`), "Форма");
});

test("componentNameOfPath: не yaml - ничего", () => {
  assert.strictEqual(componentNameOfPath("/d/proj/Модуль.xbsl"), undefined);
});

test("componentNameOfPath: голое расширение - ничего", () => {
  assert.strictEqual(componentNameOfPath("/d/proj/.yaml"), undefined);
});

// The designer's bottom tabs pair a form with the module file of the same base name; the
// mapping is mechanical (swap the extension), existence is the caller's business.
test("modulePathOfForm: модуль рядом с yaml", () => {
  assert.strictEqual(
    modulePathOfForm("/d/proj/e1c/Основное/КарточкаЗадачи.yaml"),
    "/d/proj/e1c/Основное/КарточкаЗадачи.xbsl"
  );
});

test("modulePathOfForm: путь Windows и регистр расширения", () => {
  assert.strictEqual(modulePathOfForm(String.raw`C:\проект\Сайт\Форма.YAML`), String.raw`C:\проект\Сайт\Форма.xbsl`);
});

test("modulePathOfForm: не yaml - ничего", () => {
  assert.strictEqual(modulePathOfForm("/d/proj/Модуль.xbsl"), undefined);
});

test("modulePathOfForm: голое расширение - ничего", () => {
  assert.strictEqual(modulePathOfForm("/d/proj/.yaml"), undefined);
});

// The way back from a module editor to its form.
test("formPathOfModule: yaml рядом с модулем", () => {
  assert.strictEqual(formPathOfModule("/d/proj/Дело.xbsl"), "/d/proj/Дело.yaml");
});

test("formPathOfModule: модуль объекта отображается механически", () => {
  assert.strictEqual(formPathOfModule("/d/proj/Дело.Объект.xbsl"), "/d/proj/Дело.Объект.yaml");
});

test("formPathOfModule: не xbsl - ничего", () => {
  assert.strictEqual(formPathOfModule("/d/proj/Дело.yaml"), undefined);
});

// Whether a yaml text is a form: the kind marker within the head lines plus inheritance
// anywhere. Shared by the designer and the module editor's title button.
test("looksLikeFormText: форма распознаётся", () => {
  assert.strictEqual(looksLikeFormText("КомпонентИнтерфейса:\n  Наследует: Форма\n  Содержимое:\n"), true);
});

test("looksLikeFormText: английское написание распознаётся", () => {
  assert.strictEqual(looksLikeFormText("InterfaceComponent:\n  Inherits: Form\n"), true);
});

test("looksLikeFormText: не компонент интерфейса - нет", () => {
  assert.strictEqual(looksLikeFormText("Справочник:\n  Наследует: Ссылочный\n"), false);
});

test("looksLikeFormText: без наследования - нет", () => {
  assert.strictEqual(looksLikeFormText("КомпонентИнтерфейса:\n  Имя: Черновик\n"), false);
});

test("looksLikeFormText: вид глубже шапки - нет", () => {
  const lines = Array(60).fill("# комментарий");
  lines.push("КомпонентИнтерфейса:", "  Наследует: Форма");
  assert.strictEqual(looksLikeFormText(lines.join("\n")), false);
});

test("looksLikeFormText: наследование может быть глубоко", () => {
  const lines = ["КомпонентИнтерфейса:"].concat(Array(60).fill("  # комментарий"));
  lines.push("  Наследует: Форма");
  assert.strictEqual(looksLikeFormText(lines.join("\n")), true);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
