// "Find All References" on a resource: the answer of the engine arranged for the References view -
// the places by file, the preview of a line with the place marked, the walk of F4 and the place
// nearest to a cursor.

import * as assert from "assert";
import {
  EngineResourceReference,
  groupByFile,
  linePreview,
  nearestPlace,
  rangeFragment,
  stepPlace,
} from "../src/resourceReferencesCore";

function place(path: string, line: number, character: number, length: number, text = ""): EngineResourceReference {
  return {
    path,
    kind: "reference",
    range: { start: { line, character }, end: { line, character: character + length } },
    text,
  };
}

const MODULE = "D:\\app\\Задачи\\Отчеты.xbsl";
const FORM = "D:\\app\\Задачи\\ФормаЗадачи.yaml";

// The files keep the engine's order, the places of a file are put in order of position.
{
  const files = groupByFile([
    place(MODULE, 7, 4, 9),
    place(FORM, 2, 17, 9),
    place(MODULE, 3, 20, 9),
    place(MODULE, 3, 2, 9),
  ]);
  assert.deepStrictEqual(files.map((file) => file.path), [MODULE, FORM]);
  assert.deepStrictEqual(
    files[0].references.map((r) => [r.range.start.line, r.range.start.character]),
    [[3, 2], [3, 20], [7, 4]]
  );
  assert.deepStrictEqual(groupByFile([]), []);
}

// The preview drops the indentation and marks the place in the label.
{
  const text = "    знч Логотип = Ресурс{Значки/Флаг.svg}.Ссылка";
  const start = text.indexOf("Значки");
  const preview = linePreview(text, start, start + "Значки/Флаг.svg".length);
  assert.strictEqual(preview.label, "знч Логотип = Ресурс{Значки/Флаг.svg}.Ссылка");
  assert.strictEqual(preview.label.slice(...preview.highlight), "Значки/Флаг.svg");
}

// A long head is cut down to a few characters ahead of the place, a long tail is cut off, and the
// place itself stays whole.
{
  const head = "x".repeat(60);
  const text = `${head}Получить("Стили/main.css")${"y".repeat(200)}`;
  const start = text.indexOf("Стили");
  const preview = linePreview(text, start, start + "Стили/main.css".length, 10, 40);
  assert.ok(preview.label.startsWith('...Получить("Стили'), preview.label);
  assert.ok(preview.label.endsWith("..."), preview.label);
  assert.strictEqual(preview.label.slice(...preview.highlight), "Стили/main.css");
  assert.strictEqual(preview.label.length, 3 + 40 + 3);

  const long = "Ресурс{" + "Папка/".repeat(40) + "a.svg}";
  const key = long.slice(7, -1);
  const whole = linePreview(long, 7, 7 + key.length, 24, 30);
  assert.strictEqual(whole.label.slice(...whole.highlight), key);
}

// The cut head starts at a word, not in the middle of one.
{
  const text = "// Разметка берёт стили из Ресурс{Стили/a.css}";
  const start = text.indexOf("Стили/");
  const preview = linePreview(text, start, start + "Стили/a.css".length);
  assert.strictEqual(preview.label, "...берёт стили из Ресурс{Стили/a.css}");
  assert.strictEqual(preview.label.slice(...preview.highlight), "Стили/a.css");
}

// A place outside its line (a line changed since the engine read it) does not break the preview.
{
  const preview = linePreview("abc", 10, 20);
  assert.strictEqual(preview.label, "abc");
  assert.deepStrictEqual(preview.highlight, [3, 3]);
}

// F4 walks the places across the files and wraps around, Shift+F4 walks back.
{
  const files = groupByFile([place(MODULE, 1, 0, 3), place(MODULE, 5, 0, 3), place(FORM, 2, 0, 3)]);
  assert.deepStrictEqual(stepPlace(files, [0, 0], true), [0, 1]);
  assert.deepStrictEqual(stepPlace(files, [0, 1], true), [1, 0]);
  assert.deepStrictEqual(stepPlace(files, [1, 0], true), [0, 0]);
  assert.deepStrictEqual(stepPlace(files, [0, 0], false), [1, 0]);
  assert.deepStrictEqual(stepPlace(files, [1, 0], false), [0, 1]);
  const single = groupByFile([place(FORM, 2, 0, 3)]);
  assert.deepStrictEqual(stepPlace(single, [0, 0], true), [0, 0]);
  assert.deepStrictEqual(stepPlace(single, [0, 0], false), [0, 0]);
}

// The place nearest to a cursor: the one under it, else the next one, else the last of the file.
{
  const files = groupByFile([place(MODULE, 1, 4, 6), place(MODULE, 5, 0, 3), place(FORM, 2, 0, 3)]);
  const isModule = (path: string) => path === MODULE;
  assert.deepStrictEqual(nearestPlace(files, isModule, { line: 1, character: 6 }), [0, 0]);
  assert.deepStrictEqual(nearestPlace(files, isModule, { line: 3, character: 0 }), [0, 1]);
  assert.deepStrictEqual(nearestPlace(files, isModule, { line: 9, character: 0 }), [0, 1]);
  assert.deepStrictEqual(nearestPlace(files, (path) => path === FORM, { line: 0, character: 0 }), [1, 0]);
  assert.strictEqual(nearestPlace(files, () => false, { line: 0, character: 0 }), undefined);
}

// A dragged place opens at its range: the fragment is one-based.
assert.strictEqual(rangeFragment(place(FORM, 2, 17, 9).range), "L3,18-3,27");

console.log("resourceReferencesCore: ok");
