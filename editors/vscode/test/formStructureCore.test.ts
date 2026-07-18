// Unit tests for the pure form-structure core (src/formStructureCore.ts). No test runner and
// no vscode: plain Node asserts, bundled by esbuild. Run with `npm test` from editors/vscode.

import * as assert from "assert";
import {
  decodePaletteDrag,
  decodeStructureDrag,
  dropPlan,
  editsOverlap,
  encodePaletteDrag,
  encodeStructureDrag,
  FormNode,
  indexTree,
  insertPlanForSelection,
  isContainerNode,
  isDescendantOf,
  massEditKeys,
  nodeDescription,
  nodeIconId,
  nodeLabel,
  pasteFragmentArgs,
  planRemoval,
  unwrapSingleListItem,
  projectDiagnostics,
  remapIds,
  revealOffset,
  ROOT_ID,
  siblingInfo,
  validMoveTarget,
  visibleWithNamedFilter,
} from "../src/formStructureCore";

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

// --- fixture builders (the shapes the engine's node_dict emits) ---------------------------

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
//           [1] Кнопка (unnamed)
//     [1] ПолеВвода Поиск
//   Подвал
//     [0] Кнопка (unnamed)
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
const FOOTER_BUTTON = comp("Наследует/Подвал[0]", "Кнопка", null, [310, 400]);
const FOOTER_SLOT = slot("Наследует/Подвал", "Подвал", [300, 400], [FOOTER_BUTTON]);
const ROOT = comp(ROOT_ID, "Форма", null, [0, 500], [CONTENT_SLOT, FOOTER_SLOT]);
const INDEX = indexTree(ROOT);

// --- indexing -----------------------------------------------------------------------------

test("indexTree collects every node with its parent", () => {
  assert.strictEqual(INDEX.byId.size, 9);
  assert.strictEqual(INDEX.parentOf.get(LABEL.id), INNER_SLOT.id);
  assert.strictEqual(INDEX.parentOf.get(INNER_SLOT.id), GROUP.id);
  assert.strictEqual(INDEX.parentOf.get(ROOT_ID), undefined);
});

test("isDescendantOf walks the parent chain (self included)", () => {
  assert.ok(isDescendantOf(INDEX, LABEL.id, GROUP.id));
  assert.ok(isDescendantOf(INDEX, GROUP.id, GROUP.id));
  assert.ok(!isDescendantOf(INDEX, FIELD.id, GROUP.id));
});

// --- labels and icons ---------------------------------------------------------------------

test("labels combine the type and the name; slots show the key", () => {
  assert.strictEqual(nodeLabel(GROUP), "Группа Шапка");
  assert.strictEqual(nodeLabel(BUTTON), "Кнопка");
  assert.strictEqual(nodeLabel(INNER_SLOT), "Содержимое");
});

test("descriptions: property preview for components, child count for slots", () => {
  assert.strictEqual(nodeDescription(LABEL), "О сервисе");
  assert.strictEqual(nodeDescription(BUTTON), "");
  assert.strictEqual(nodeDescription(CONTENT_SLOT), "2");
});

test("icons: root and slots keep their own, components go through the shared type mapping", () => {
  assert.strictEqual(nodeIconId(ROOT), "window");
  assert.strictEqual(nodeIconId(INNER_SLOT), "layers");
  assert.strictEqual(nodeIconId(GROUP), "layout"); // the Группа family
  assert.strictEqual(nodeIconId(BUTTON), "inspect"); // the exact Кнопка entry
  assert.strictEqual(nodeIconId(LABEL), "symbol-string");
  assert.strictEqual(nodeIconId(FIELD), "symbol-field");
  // A schema-known container outside the mapping still reads as a container...
  const emptyCard = comp("x", "СпецКарточка", null, [0, 1]);
  assert.strictEqual(nodeIconId(emptyCard, (t) => t === "СпецКарточка"), "layout");
  // ...an unknown leaf type falls to the generic icon, refined by the package when the
  // catalog is cached (the same inputs the palette resolves - one type, one icon).
  assert.strictEqual(nodeIconId(emptyCard), "symbol-misc");
  const listy = comp("y", "Аккордеон", null, [0, 1]);
  assert.strictEqual(nodeIconId(listy, undefined, () => "Стд::Интерфейс::Списки"), "list-flat");
  // an untyped mapping (e.g. a page of Страницы) keeps the local container/leaf heuristic
  const page = comp("z", null, null, [0, 1], [slot("z/Содержимое", "Содержимое", [0, 1], [])]);
  assert.strictEqual(nodeIconId(page), "layout");
  assert.strictEqual(nodeIconId(comp("w", null, null, [0, 1])), "symbol-field");
});

test("container detection: slot children, the known list, the schema callback", () => {
  assert.ok(isContainerNode(GROUP));
  assert.ok(isContainerNode(comp("x", "Группа", null, [0, 1]))); // known type, no slots yet
  assert.ok(!isContainerNode(BUTTON));
  assert.ok(!isContainerNode(INNER_SLOT)); // a slot is not a component
});

test("revealOffset prefers the content span over the comment-inclusive span", () => {
  // a node with a comment attached above: the click lands on the first content line
  const commented: FormNode = { ...LABEL, contentSpan: { start: 62, end: 100 } };
  assert.strictEqual(revealOffset(commented), 62);
  // no comments: contentSpan equals span; older engines send no contentSpan at all
  const same: FormNode = { ...LABEL, contentSpan: { start: 40, end: 100 } };
  assert.strictEqual(revealOffset(same), 40);
  assert.strictEqual(revealOffset(LABEL), LABEL.span.start);
});

// --- drop and insert planning -------------------------------------------------------------

test("drop on a container goes inside, to the slot end", () => {
  const plan = dropPlan(GROUP, INDEX);
  assert.deepStrictEqual(plan, { parentId: GROUP.id, slot: "Содержимое" });
});

test("drop on a leaf lands right after it", () => {
  const plan = dropPlan(LABEL, INDEX);
  assert.deepStrictEqual(plan, { parentId: GROUP.id, slot: "Содержимое", after: LABEL.id });
});

test("drop on a slot goes into that slot", () => {
  const plan = dropPlan(FOOTER_SLOT, INDEX);
  assert.deepStrictEqual(plan, { parentId: ROOT_ID, slot: "Подвал" });
});

test("drop on the root goes into the root content slot", () => {
  const plan = dropPlan(ROOT, INDEX);
  assert.deepStrictEqual(plan, { parentId: ROOT_ID, slot: "Содержимое" });
});

test("palette insertion targets the selection (empty selection - the root)", () => {
  assert.deepStrictEqual(insertPlanForSelection(undefined, INDEX), { parentId: ROOT_ID, slot: "Содержимое" });
  assert.deepStrictEqual(insertPlanForSelection(FIELD, INDEX), {
    parentId: ROOT_ID,
    slot: "Содержимое",
    after: FIELD.id,
  });
  assert.deepStrictEqual(insertPlanForSelection(GROUP, INDEX), { parentId: GROUP.id, slot: "Содержимое" });
});

test("pasteFragmentArgs: the palette target rules, the fragment travels verbatim", () => {
  // a copied node with an attached comment and quotes - byte-for-byte in the arguments
  // (the engine re-attaches the comments and re-indents; the client must not touch them)
  const fragment = '# Кнопка из другой формы\nТип: Кнопка\nЗаголовок: "Оплатить"\nСодержимое:\n    Тип: Надпись\n';
  assert.deepStrictEqual(pasteFragmentArgs(GROUP, INDEX, fragment), {
    parent: GROUP.id,
    slot: "Содержимое",
    fragment,
    before: undefined,
    after: undefined,
  });
  assert.deepStrictEqual(pasteFragmentArgs(LABEL, INDEX, fragment), {
    parent: GROUP.id,
    slot: "Содержимое",
    fragment,
    before: undefined,
    after: LABEL.id,
  });
  assert.deepStrictEqual(pasteFragmentArgs(FOOTER_SLOT, INDEX, fragment), {
    parent: ROOT_ID,
    slot: "Подвал",
    fragment,
    before: undefined,
    after: undefined,
  });
  // empty selection - the root content slot; the fragment is not validated client-side
  const empty = pasteFragmentArgs(undefined, INDEX, "мусор, не yaml");
  assert.deepStrictEqual(empty, {
    parent: ROOT_ID,
    slot: "Содержимое",
    fragment: "мусор, не yaml",
    before: undefined,
    after: undefined,
  });
});

test("unwrapSingleListItem: a copied list item becomes the mapping form the engine takes", () => {
  // the shape copyYaml produces for a node in a "-" slot: attached comments at the dash
  // column, the inline dash, the body aligned with the first key
  const copied =
    "        # Кнопка с комментарием\n" +
    "        - Тип: Кнопка\n" +
    "          Имя: Оплатить\n" +
    "          Содержимое:\n" +
    "              Тип: Надпись\n";
  assert.strictEqual(
    unwrapSingleListItem(copied),
    "        # Кнопка с комментарием\n" +
      "        Тип: Кнопка\n" +
      "        Имя: Оплатить\n" +
      "        Содержимое:\n" +
      "            Тип: Надпись\n"
  );
  // the engine's own insert style: the dash alone on its line, the body one step deeper
  const dashAlone = "    -\n        Тип: Кнопка\n        Имя: Купить\n";
  assert.strictEqual(unwrapSingleListItem(dashAlone), "    Тип: Кнопка\n    Имя: Купить\n");
  // nested list dashes inside the item body are not top-level items
  const nested = "- Тип: Группа\n  Поля:\n      - Имя: А\n      - Имя: Б\n";
  assert.strictEqual(
    unwrapSingleListItem(nested),
    "Тип: Группа\nПоля:\n    - Имя: А\n    - Имя: Б\n"
  );
  // untouched: the mapping form, several items (the engine's diagnostic educates), garbage
  const mapping = "# к\nТип: Кнопка\nИмя: Х\n";
  assert.strictEqual(unwrapSingleListItem(mapping), mapping);
  const two = "- Тип: А\n- Тип: Б\n";
  assert.strictEqual(unwrapSingleListItem(two), two);
  assert.strictEqual(unwrapSingleListItem("мусор"), "мусор");
  assert.strictEqual(unwrapSingleListItem(""), "");
  // crlf clipboards keep their line endings
  const crlf = "- Тип: Кнопка\r\n  Имя: Х\r\n";
  assert.strictEqual(unwrapSingleListItem(crlf), "Тип: Кнопка\r\nИмя: Х\r\n");
});

test("a move into a dragged subtree is rejected", () => {
  assert.ok(!validMoveTarget(INDEX, [GROUP.id], LABEL.id)); // target inside the dragged node
  assert.ok(!validMoveTarget(INDEX, [GROUP.id], GROUP.id));
  assert.ok(validMoveTarget(INDEX, [GROUP.id], FIELD.id));
  assert.ok(!validMoveTarget(INDEX, [GROUP.id], "нет-такого"));
});

test("siblingInfo reports the slot, the parent component and the neighbours", () => {
  const info = siblingInfo(LABEL, INDEX);
  assert.strictEqual(info?.parentId, GROUP.id);
  assert.strictEqual(info?.slot, "Содержимое");
  assert.strictEqual(info?.prev, undefined);
  assert.strictEqual(info?.next?.id, BUTTON.id);
  const info2 = siblingInfo(FIELD, INDEX);
  assert.strictEqual(info2?.prev?.id, GROUP.id);
  assert.strictEqual(info2?.next, undefined);
});

// --- removal planning ---------------------------------------------------------------------

test("removal drops descendants of selected nodes and orders bottom-up", () => {
  const plan = planRemoval([LABEL.id, GROUP.id, FIELD.id], INDEX);
  assert.deepStrictEqual(plan.ids, [FIELD.id, GROUP.id]); // LABEL is inside GROUP; FIELD is later in text
});

test("removal covering a whole multi-child slot goes sequential", () => {
  const partial = planRemoval([LABEL.id], INDEX);
  assert.strictEqual(partial.sequential, false);
  const whole = planRemoval([LABEL.id, BUTTON.id], INDEX);
  assert.strictEqual(whole.sequential, true);
  // A single-child slot: the engine removes the slot key together with the child in one call.
  const single = planRemoval([FOOTER_BUTTON.id], INDEX);
  assert.deepStrictEqual(single, { ids: [FOOTER_BUTTON.id], sequential: false });
});

test("slots and the root are not removable", () => {
  const plan = planRemoval([INNER_SLOT.id, ROOT_ID], INDEX);
  assert.deepStrictEqual(plan.ids, []);
});

test("editsOverlap detects intersecting spans", () => {
  assert.ok(!editsOverlap([
    { start: 0, end: 10, newText: "" },
    { start: 10, end: 20, newText: "" },
  ]));
  assert.ok(editsOverlap([
    { start: 0, end: 11, newText: "" },
    { start: 10, end: 20, newText: "" },
  ]));
});

// --- diagnostics projection ---------------------------------------------------------------

test("diagnostics land on the deepest containing node", () => {
  const badges = projectDiagnostics(INDEX, [
    { start: 50, severity: 1, message: "первая" },
    { start: 60, severity: 0, message: "вторая" },
    { start: 250, severity: 2, message: "поле" },
    { start: 5, severity: 3, message: "корень" }, // inside the root, outside every slot
    { start: 600, severity: 0, message: "вне дерева" },
  ]);
  const label = badges.get(LABEL.id);
  assert.strictEqual(label?.count, 2);
  assert.strictEqual(label?.severity, 0); // the strongest of warning + error
  assert.strictEqual(label?.firstMessage, "первая");
  assert.strictEqual(badges.get(FIELD.id)?.count, 1);
  assert.strictEqual(badges.get(ROOT_ID)?.count, 1);
  assert.strictEqual(badges.size, 3);
});

// --- named-only filter --------------------------------------------------------------------

test("the named filter keeps named components with their ancestor chain", () => {
  const visible = visibleWithNamedFilter(INDEX);
  assert.ok(visible.has(LABEL.id)); // named
  assert.ok(visible.has(INNER_SLOT.id)); // ancestor of a named node
  assert.ok(visible.has(GROUP.id));
  assert.ok(visible.has(FIELD.id));
  assert.ok(visible.has(ROOT_ID));
  assert.ok(!visible.has(BUTTON.id)); // unnamed leaf
  assert.ok(!visible.has(FOOTER_SLOT.id)); // no named descendants
  assert.ok(!visible.has(FOOTER_BUTTON.id));
});

// --- expansion remapping ------------------------------------------------------------------

test("expansion survives positional id shifts via unique names", () => {
  // The same form after inserting a new first child: every index under Содержимое shifted.
  const label2 = comp(
    "Наследует/Содержимое[1]/Содержимое[0]",
    "Надпись",
    "Заголовок",
    [140, 200],
    [],
    []
  );
  const innerSlot2 = slot("Наследует/Содержимое[1]/Содержимое", "Содержимое", [130, 290], [label2]);
  const group2 = comp("Наследует/Содержимое[1]", "Группа", "Шапка", [120, 300], [innerSlot2]);
  const inserted = comp("Наследует/Содержимое[0]", "Надпись", null, [20, 120]);
  const field2 = comp("Наследует/Содержимое[2]", "ПолеВвода", "Поиск", [300, 400]);
  const content2 = slot("Наследует/Содержимое", "Содержимое", [10, 400], [inserted, group2, field2]);
  const root2 = comp(ROOT_ID, "Форма", null, [0, 500], [content2]);
  const newIndex = indexTree(root2);

  const remapped = remapIds([ROOT_ID, GROUP.id, INNER_SLOT.id, FIELD.id, BUTTON.id], INDEX, newIndex);
  assert.ok(remapped.has(ROOT_ID)); // untouched id
  assert.ok(remapped.has(group2.id)); // followed the unique name Шапка
  assert.ok(remapped.has(innerSlot2.id)); // slot re-attached to the remapped parent
  assert.ok(remapped.has(field2.id)); // followed Поиск
  assert.strictEqual(remapped.size, 4); // the unnamed Кнопка is not traceable
});

// --- drag payloads ------------------------------------------------------------------------

test("drag payloads round-trip and reject foreign data", () => {
  const structure = encodeStructureDrag({ uri: "file:///a.yaml", ids: [GROUP.id] });
  assert.deepStrictEqual(decodeStructureDrag(structure), { uri: "file:///a.yaml", ids: [GROUP.id] });
  assert.strictEqual(decodeStructureDrag("мусор"), undefined);
  assert.strictEqual(decodeStructureDrag('{"uri": 5, "ids": []}'), undefined);

  const palette = encodePaletteDrag({ componentType: "Надпись" });
  assert.deepStrictEqual(decodePaletteDrag(palette), { componentType: "Надпись" });
  assert.strictEqual(decodePaletteDrag("{}"), undefined);
  assert.strictEqual(decodePaletteDrag("мусор"), undefined);
});

test("massEditKeys: the union of scalar/binding keys, sorted, structure keys excluded (hook 9)", () => {
  const a = comp("a", "Надпись", "A", [0, 10], [], [
    { key: "Заголовок", kind: "scalar", valuePreview: "x" },
    { key: "Видимость", kind: "binding", valuePreview: "=Объект.Виден" },
    { key: "Шрифт", kind: "composite", valuePreview: "АбсолютныйШрифт" }, // composite excluded
    { key: "ПриНажатии", kind: "handler", valuePreview: "Обработать" }, // handler excluded
  ]);
  const b = comp("b", "Кнопка", "B", [10, 20], [], [
    { key: "Заголовок", kind: "scalar", valuePreview: "y" }, // shared - not duplicated
    { key: "Доступность", kind: "scalar", valuePreview: "Истина" },
  ]);
  assert.deepStrictEqual(massEditKeys([a, b]), ["Видимость", "Доступность", "Заголовок"]);
  // Slots contribute nothing.
  assert.deepStrictEqual(massEditKeys([slot("s", "Содержимое", [0, 5], [])]), []);
  assert.deepStrictEqual(massEditKeys([]), []);
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
