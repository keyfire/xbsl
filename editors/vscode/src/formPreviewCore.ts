// Wireframe preview of a 1C:Element form: the yaml description (КомпонентИнтерфейса) is turned
// into an HTML mockup - groups, fields, buttons, tables, tabs. This is a wireframe, not the
// platform's rendering: layout, captions, explicit sizes and colors are conveyed, the exact
// platform look is not. The module is pure (no vscode) so the rendering can be checked by
// plain node tests; the webview wiring is in formDesigner.ts.
//
// The tree is taken from Наследует.Содержимое; child nodes live only in known properties
// (Содержимое, Страницы, Колонки) - other nested objects (АбсолютныйЦвет, the Источник of a
// dynamic list, etc.) are property values, not components.

import { isMap, isScalar, isSeq, parseDocument } from "yaml";
import type { YAMLMap } from "yaml";

export type PreviewResult =
  | { ok: true; html: string; title: string }
  | { ok: false; reason: "parse" | "not-form"; detail?: string };

// -- access to yaml nodes -----------------------------------------------------------------

// {English spelling: the Russian key} of the form structure - filled from the engine
// (`xbsl/formKeys`). A form written in English is legal code the platform reads either way, and
// without the pairs the frame stayed empty: the tree is looked up by `Содержимое` while the file
// spells `Content`. The pairs always come from the platform dictionary, never from a guess here.
let _keyAliases: Record<string, string> = {};

let _typeAliases: Record<string, string> = {};

export function setFormKeyAliases(
  aliases: Record<string, string>,
  types: Record<string, string> = {},
): void {
  _keyAliases = aliases ?? {};
  _typeAliases = types ?? {};
}

function canonicalKey(key: string): string {
  return _keyAliases[key] ?? key;
}

/** The component type as the schema names it (`Group` -> `Группа`). */
function canonicalType(type: string): string {
  return _typeAliases[type] ?? type;
}

function get(map: unknown, key: string): unknown {
  if (!isMap(map)) {
    return undefined;
  }
  for (const item of map.items) {
    if (isScalar(item.key) && canonicalKey(String(item.key.value)) === key) {
      return item.value ?? undefined;
    }
  }
  return undefined;
}

function str(node: unknown): string | undefined {
  if (isScalar(node) && node.value !== null && node.value !== undefined) {
    return String(node.value);
  }
  return undefined;
}

function prop(map: unknown, key: string): string | undefined {
  return str(get(map, key));
}

// Component type without generic parameters: "ПолеВвода<Строка>" -> "ПолеВвода".
function baseType(map: unknown): string | undefined {
  const t = prop(map, "Тип");
  if (!t) {
    return undefined;
  }
  const angle = t.indexOf("<");
  return canonicalType((angle > 0 ? t.slice(0, angle) : t).trim());
}

// Node offset in the source text - for navigating from the preview to yaml.
function offsetOf(map: unknown): number | undefined {
  return isMap(map) && map.range ? map.range[0] : undefined;
}

// -- HTML utilities -------------------------------------------------------------------------

export function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function tagAttrs(node: unknown, cls: string, style?: string): string {
  const off = offsetOf(node);
  const offAttr = off !== undefined ? ` data-off="${off}"` : "";
  const styleAttr = style ? ` style="${esc(style)}"` : "";
  // Hover tooltip: the node type and name, both already at hand from the yaml map.
  // Visibility comes in three shapes and the wireframe shows all three differently: a node the
  // platform never draws (`Ложь`) is dimmed hard, a node whose visibility is COMPUTED
  // (`=выражение`) is dimmed lightly - it may or may not be on screen, and two such groups are
  // often mutually exclusive (a desktop footer and a mobile one) - and everything else is drawn
  // as is. The node stays in place either way, so the yaml and the wireframe keep one shape.
  const visibility = prop(node, "Видимость");
  const hidden = visibility === "Ложь";
  const conditional = visibility !== undefined && visibility.startsWith("=");
  const tip = [
    prop(node, "Тип"),
    prop(node, "Имя"),
    hidden ? "Видимость: Ложь" : conditional ? `Видимость: ${visibility}` : undefined,
  ].filter(Boolean).join(" · ");
  const titleAttr = tip ? ` title="${esc(tip)}"` : "";
  const mark = hidden ? " off" : conditional ? " cond" : "";
  return `class="${cls}${mark}"${styleAttr}${offAttr}${titleAttr}`;
}

// Property value: a binding (=Данные.Х) is shown as a monospaced chip, a literal - as text.
function valueHtml(v: string | undefined, placeholder = ""): string {
  if (v === undefined || v === "") {
    return `<span class="ph">${esc(placeholder)}</span>`;
  }
  if (v.startsWith("=")) {
    return `<code class="chip">${esc(v)}</code>`;
  }
  return esc(v);
}

function isTrue(map: unknown, key: string): boolean {
  // `Истина` and `True` are the platform's own pair - a form written in English spells the
  // second one, and the frame must read it the same way.
  const value = prop(map, key);
  return value === "Истина" || value === "True";
}

// -- mapping properties to styles -----------------------------------------------------------

function growStyle(node: unknown, horizontalParent: boolean): string {
  const parts: string[] = [];
  const weight = prop(node, "ВесПриРастягивании");
  const growH = isTrue(node, "РастягиватьПоГоризонтали");
  const growV = isTrue(node, "РастягиватьПоВертикали");
  if (horizontalParent ? growH : growV) {
    parts.push(`flex-grow:${weight && /^\d+$/.test(weight) ? weight : 1}`);
  }
  if (horizontalParent ? growV : growH) {
    parts.push("align-self:stretch");
  } else if (prop(node, horizontalParent ? "РастягиватьПоВертикали" : "РастягиватьПоГоризонтали") === "Ложь") {
    // An explicit Ложь opts out of the container's cross-axis stretch (.form-body stretches
    // its children by default), so the component hugs its content like on the platform.
    parts.push("align-self:flex-start");
  }
  return parts.join(";");
}

function joinStyle(...parts: Array<string | undefined>): string {
  return parts.filter(Boolean).join(";");
}

// An integer property value, or undefined when absent or not a plain number.
function numOf(node: unknown, key: string): string | undefined {
  const v = prop(node, key);
  return v && /^\d+$/.test(v) ? v : undefined;
}

// Explicit sizes; the numbers are pixels on the platform. Stretch styles from growStyle
// coexist with them the same way the platform resolves the combination - via flexbox.
// A bounded box must CLIP: without this the children of a group with `Высота` simply paint over
// whatever follows it - a wizard whose pages live in a 420px area drew its footer and its error
// bubble on top of the fields. The platform scrolls where the group asks for it and clips
// otherwise, so the wireframe does the same.
function clipStyle(node: unknown): string {
  const parts: string[] = [];
  const axis = (scroll: string, size: string, max: string, css: string) => {
    if (prop(node, scroll) === "Истина") {
      parts.push(`${css}:auto`);
    } else if (numOf(node, size) || numOf(node, max)) {
      parts.push(`${css}:hidden`);
    }
  };
  axis("ПрокруткаПоВертикали", "Высота", "МаксимальнаяВысота", "overflow-y");
  axis("ПрокруткаПоГоризонтали", "Ширина", "МаксимальнаяШирина", "overflow-x");
  return parts.join(";");
}


// ШиринаВКолонках. The platform states the scale by name (half a column ... four columns,
// unlimited) and never says what a column is, so the wireframe used to invent a fixed base and
// keep the ratios exact against it. MEASURED on a deployed form (a probe of all five sizes,
// read at six viewport widths), the platform turns out to do something else entirely - the
// column is not a constant but a share of the row:
//
//   gap between columns    24px, always;
//   number of columns      the largest n <= 4 whose column (row - (n-1)*24) / n is >= 250px;
//   a size of N columns    N * column + (N-1) * 24;
//   half a column          (column - 24) / 2, so two halves fill one column with a gap;
//   Неограниченная         the whole row.
//
// Every reading fits: a row of 1572.4 gives four columns of 375.1, a row of 1052.4 three of
// 334.8 (four would be 245.1 - under the minimum), a row of 732.4 two of 354.2. The cap of four
// is real: a 1572-wide row has space for five 250px columns and still lays out four.
//
// CSS says all of that natively. `auto-fit` with a minimum of max(250px, a quarter of the row)
// yields the same count the platform picks - the quarter is what caps it at four - and a size
// of N columns is a span of N tracks.
const COLUMN_MIN_PX = 250;
const COLUMN_GAP_PX = 24;
const COLUMN_GRID =
  `gap:${COLUMN_GAP_PX}px;grid-template-columns:repeat(auto-fit,minmax(` +
  `max(${COLUMN_MIN_PX}px,calc((100% - ${COLUMN_GAP_PX * 3}px) / 4)),1fr))`;

const COLUMN_SPAN: Record<string, number> = {
  Одинарная: 1,
  Двойная: 2,
  Тройная: 3,
  Четверная: 4,
};

function columnWidthStyle(node: unknown, byColumns: boolean): string {
  // The platform uses this size ONLY where the layout is by columns: a horizontal group goes by
  // pixels, a vertical one by Ширина/Минимальная/Максимальная. Applying it everywhere squeezed
  // components the platform would have left alone.
  if (!byColumns) {
    return "";
  }
  const value = prop(node, "ШиринаВКолонках");
  if (value === undefined || value === "Авто") {
    return "";
  }
  if (value === "Неограниченная") {
    return "grid-column:1 / -1";
  }
  if (value === "Половинная") {
    // Half a column is not half a track: the platform puts two halves INTO one column, and the
    // gap between them comes out of it.
    return `width:calc(50% - ${COLUMN_GAP_PX / 2}px)`;
  }
  const span = COLUMN_SPAN[value];
  return span ? `grid-column:span ${span}` : "";
}


function sizeStyle(node: unknown): string {
  const parts: string[] = [];
  const push = (key: string, css: string) => {
    const v = numOf(node, key);
    if (v) {
      parts.push(`${css}:${v}px`);
    }
  };
  push("Ширина", "width");
  push("Высота", "height");
  push("МинимальнаяШирина", "min-width");
  push("МинимальнаяВысота", "min-height");
  push("МаксимальнаяШирина", "max-width");
  push("МаксимальнаяВысота", "max-height");
  // A bounded box must CLIP: without this the children of a group with `Высота` simply paint
  // over whatever follows it - a wizard whose pages live in a 420px area drew its footer and
  // its error bubble on top of the fields. The platform scrolls where the group asks for it
  // and clips otherwise, so the wireframe does the same.
  return parts.join(";");
}

const ALIGN_CSS: Record<string, string> = {
  Начало: "flex-start",
  Центр: "center",
  Конец: "flex-end",
  Верх: "flex-start",
  Низ: "flex-end",
  ПоШирине: "stretch",
  ПоБазовойЛинии: "baseline",
};

// The two alignments are DIFFERENT properties and the platform documents them as such
// ("Размещение компонентов на экране"): `ВыравниваниеСодержимогоПо*` lays out the CHILDREN of a
// container in bulk, `ВыравниваниеВГруппеПо*` places the component ITSELF inside its parent and
// overrides the bulk setting. The wireframe used to read the second one and apply it as the
// first, so a group asking to sit at the end of its parent instead pushed its own content there.
function contentAlignStyle(node: unknown): string {
  const horizontal = prop(node, "Компоновка") === "Горизонтальная";
  const h = prop(node, "ВыравниваниеСодержимогоПоГоризонтали");
  const v = prop(node, "ВыравниваниеСодержимогоПоВертикали");
  const parts: string[] = [];
  const main = horizontal ? h : v;
  const cross = horizontal ? v : h;
  if (main && ALIGN_CSS[main]) {
    parts.push(`justify-content:${ALIGN_CSS[main]}`);
  }
  if (cross && ALIGN_CSS[cross]) {
    parts.push(`align-items:${ALIGN_CSS[cross]}`);
  }
  return parts.join(";");
}

// The component's own place in its parent. Only the cross axis has a per-item property in
// flexbox (align-self); along the MAIN axis the same effect is an auto margin, which is what the
// browser leaves for exactly this case.
function selfAlignStyle(node: unknown, horizontalParent: boolean): string {
  const h = prop(node, "ВыравниваниеВГруппеПоГоризонтали");
  const v = prop(node, "ВыравниваниеВГруппеПоВертикали");
  const main = horizontalParent ? h : v;
  const cross = horizontalParent ? v : h;
  // Stretching WINS over the alignment: the platform says so outright ("Истина - Элемент
  // растягивает компонент, несмотря на значения свойств Высота или Ширина"), and the alignment
  // only matters "если размер группы больше размера, требуемого всем ее компонентам". In CSS
  // align-self would silently shrink a stretched component to its content - which is exactly how
  // a full-width section of the main page collapsed into a narrow column.
  const stretchedAcross = isTrue(node, horizontalParent ? "РастягиватьПоВертикали" : "РастягиватьПоГоризонтали");
  const parts: string[] = [];
  if (cross && ALIGN_CSS[cross] && !stretchedAcross) {
    parts.push(`align-self:${ALIGN_CSS[cross]}`);
  }
  if (main === "Конец") {
    parts.push(horizontalParent ? "margin-left:auto" : "margin-top:auto");
  } else if (main === "Центр") {
    parts.push(horizontalParent ? "margin-left:auto;margin-right:auto" : "margin-top:auto;margin-bottom:auto");
  }
  return parts.join(";");
}

// Color {Тип: АбсолютныйЦвет, Значение: RGB(595964)} and font {Размер, Начертание/Насыщенность}.
function textStyle(node: unknown): string {
  const parts: string[] = [];
  const rgb = prop(get(node, "Цвет"), "Значение");
  const hex = rgb && /^RGB\(([0-9A-Fa-f]{6})\)$/.exec(rgb.trim());
  if (hex) {
    parts.push(`color:#${hex[1]}`);
  }
  const font = get(node, "Шрифт");
  const size = prop(font, "Размер");
  if (size && /^\d+$/.test(size)) {
    parts.push(`font-size:${size}px`);
  }
  const face = (prop(font, "Начертание") ?? "") + (prop(font, "Насыщенность") ?? "");
  if (face.includes("Жирн")) {
    parts.push("font-weight:600");
  }
  return parts.join(";");
}

// -- component rendering --------------------------------------------------------------------

function renderChildren(node: unknown, horizontal: boolean, byColumns = false): string {
  if (isSeq(node)) {
    return node.items.map((item) => renderComponent(item, horizontal, byColumns)).join("");
  }
  return renderComponent(node, horizontal, byColumns);
}

function nameTag(node: unknown, fallback?: string): string {
  const name = prop(node, "Имя") ?? fallback;
  return name ? `<span class="tag">${esc(name)}</span>` : "";
}

// РазмерОтступа in pixels. The platform documents the scale by name only ("Авто равно
// Одинарный"), so the numbers are measured on a deployed application: every gap the page sets
// falls on 0/8/16/24/32, and 16 - the default - dominates. One step is 16 pixels.
const INDENT_PX: Record<string, number> = {
  Отсутствует: 0,
  Половинный: 8,
  Одинарный: 16,
  Полуторный: 24,
  Двойной: 32,
};

function indentOf(node: unknown, key: string): number | undefined {
  const value = prop(node, key);
  return value !== undefined && value in INDENT_PX ? INDENT_PX[value] : undefined;
}

// The spacing a group asks for: the gap between its children and its own inner padding. Without
// these every group looked equally spaced whatever the yaml said - the wireframe carried one
// hardcoded padding and no gap at all.
function spacingStyle(node: unknown): string {
  const parts: string[] = [];
  const rowGap = indentOf(node, "ИнтервалМеждуЭлементамиПоВертикали");
  const colGap = indentOf(node, "ИнтервалМеждуЭлементамиПоГоризонтали");
  if (rowGap !== undefined || colGap !== undefined) {
    // A single axis is set far more often than both; the other keeps the platform default.
    parts.push(`gap:${rowGap ?? INDENT_PX.Одинарный}px ${colGap ?? INDENT_PX.Одинарный}px`);
  }
  const padV = indentOf(node, "ОтступПоВертикали");
  const padH = indentOf(node, "ОтступПоГоризонтали");
  if (padV !== undefined) {
    parts.push(`padding-top:${padV}px`, `padding-bottom:${padV}px`);
  }
  if (padH !== undefined) {
    parts.push(`padding-left:${padH}px`, `padding-right:${padH}px`);
  }
  return parts.join(";");
}


// Компоновка, as the platform lays it out (the docs topic on the Группа component):
//   Вертикальная - one column;  Горизонтальная - one row, no wrapping;
//   ПоКолонкам   - a row that wraps by the form columns (sizes come from ШиринаВКолонках);
//   Матричная    - a grid of columns and rows, auto-filled per НастройкиМатричнойКомпоновки;
//   Карусель     - one row the user scrolls through;  Бенто - a packing grid of blocks.
// Everything but the first two used to render as a plain column, which is why a row of four
// advantages showed up as four stacked cards.
function layoutClass(node: unknown): { cls: string; horizontal: boolean; style: string; byColumns: boolean } {
  const layout = prop(node, "Компоновка");
  switch (layout) {
    case "Горизонтальная":
      return { cls: "row", horizontal: true, style: "flex-wrap:nowrap", byColumns: false };
    case "ПоКолонкам":
      // A real grid, because that is what the platform builds: see COLUMN_GRID below.
      return { cls: "grid", horizontal: true, style: COLUMN_GRID, byColumns: true };
    case "Карусель":
      return { cls: "row", horizontal: true, style: "flex-wrap:nowrap;overflow-x:auto", byColumns: false };
    case "Матричная":
    case "Бенто":
      return { cls: "grid", horizontal: true, style: gridStyle(node, layout), byColumns: false };
    default:
      // Авто is "ПоКолонкам when the content can be distributed by columns, otherwise
      // Вертикальная"; whether it can is not decidable from the yaml, so the wireframe keeps the
      // vertical reading - the one it has always shown.
      return { cls: "col", horizontal: false, style: "", byColumns: false };
  }
}

function gridStyle(node: unknown, layout: string): string {
  if (layout === "Бенто") {
    // The bento algorithm packs blocks by their column and row sizes; the wireframe shows the
    // grid it packs into, not the packing itself.
    return "grid-template-columns:repeat(auto-fill,minmax(160px,1fr))";
  }
  const settings = get(node, "НастройкиМатричнойКомпоновки");
  const columns = get(settings, "Колонки");
  if (isSeq(columns) && columns.items.length > 0) {
    return `grid-template-columns:repeat(${columns.items.length},1fr)`;
  }
  const auto = get(settings, "ОписаниеАвтоматическихКолонок");
  const min = numOf(auto, "МинимальнаяШирина");
  return `grid-template-columns:repeat(auto-fill,minmax(${min ?? 200}px,1fr))`;
}

function renderGroup(node: unknown, cls: string, extraStyle = ""): string {
  const layout = layoutClass(node);
  const style = [extraStyle, contentAlignStyle(node), spacingStyle(node), layout.style]
    .filter(Boolean).join(";");
  const inner = renderChildren(get(node, "Содержимое"), layout.horizontal, layout.byColumns);
  return `<div ${tagAttrs(node, `${cls} ${layout.cls}`, style)}>${nameTag(node)}${inner}</div>`;
}

function renderTable(node: unknown): string {
  const cols = get(node, "Колонки");
  const heads: string[] = [];
  if (isSeq(cols)) {
    for (const col of cols.items) {
      heads.push(prop(col, "Заголовок") ?? prop(col, "ПолеЗначения") ?? "");
    }
  }
  if (heads.length === 0) {
    heads.push("", "", "");
  }
  const th = heads.map((h) => `<th>${esc(h) || "&nbsp;"}</th>`).join("");
  const placeholderRow = `<tr>${heads.map(() => "<td>···</td>").join("")}</tr>`;
  return `<table ${tagAttrs(node, "tbl")}><thead><tr>${th}</tr></thead><tbody>${placeholderRow}${placeholderRow}</tbody></table>`;
}

function renderTabs(node: unknown, horizontalParent: boolean): string {
  const pages = get(node, "Страницы");
  if (!isSeq(pages)) {
    return renderUnknown(node, "Страницы");
  }
  const bar: string[] = [];
  const bodies: string[] = [];
  pages.items.forEach((page, i) => {
    const title = prop(page, "Заголовок") ?? prop(page, "Имя") ?? `${i + 1}`;
    const off = offsetOf(page);
    bar.push(`<button class="tabbtn${i === 0 ? " act" : ""}" data-tab="${i}"${off !== undefined ? ` data-off="${off}"` : ""}>${esc(title)}</button>`);
    bodies.push(`<div class="tabpage${i === 0 ? " act" : ""}" data-tab="${i}">${renderChildren(get(page, "Содержимое"), false)}</div>`);
  });
  return `<div ${tagAttrs(node, "tabs", growStyle(node, horizontalParent))}><div class="tabbar">${bar.join("")}</div>${bodies.join("")}</div>`;
}

function renderUnknown(node: unknown, type: string): string {
  const inner = renderChildren(get(node, "Содержимое"), false);
  const label = `${esc(type)}${prop(node, "Имя") ? " · " + esc(prop(node, "Имя")!) : ""}`;
  // A project component the wireframe cannot draw: its caption goes IN FLOW, not as the absolute
  // tag the containers use. An empty placeholder is 20 pixels wide while its name is a hundred
  // and a half, so an absolute caption hung far outside the box and painted over the neighbours.
  return `<div ${tagAttrs(node, "unknown col")}><span class="uname">${label}</span>${inner}</div>`;
}

// Field commands (Команды: a single command or a command-interface fragment/group) show as
// compact icons at the input's edge - the platform places them next to the field.
function fieldCommands(node: unknown): string {
  const block = get(node, "Команды");
  if (!isMap(block)) {
    return "";
  }
  const elements = get(block, "Элементы");
  const commands = isSeq(elements) ? elements.items : [block];
  const chips: string[] = [];
  for (const cmd of commands) {
    if (!isMap(cmd)) {
      continue;
    }
    const image = prop(cmd, "Изображение");
    const src = image ? _resources[image] : undefined;
    const icon = src ? `<img class="cico" src="${esc(src)}" alt="">` : `<span class="cph">⚙</span>`;
    const tip = prop(cmd, "Представление") ?? prop(cmd, "Тип") ?? "";
    const off = offsetOf(cmd);
    chips.push(`<span class="fcmd"${off !== undefined ? ` data-off="${off}"` : ""}${tip ? ` title="${esc(tip)}"` : ""}>${icon}</span>`);
  }
  return chips.length > 0 ? `<span class="fcmds">${chips.join("")}</span>` : "";
}

function renderComponent(node: unknown, horizontalParent: boolean, byColumnsParent = false): string {
  if (isSeq(node)) {
    return renderChildren(node, horizontalParent, byColumnsParent);
  }
  if (!isMap(node)) {
    return "";
  }
  const type = baseType(node) ?? "";
  const layout = joinStyle(
    growStyle(node, horizontalParent),
    sizeStyle(node),
    columnWidthStyle(node, byColumnsParent),
    selfAlignStyle(node, horizontalParent),
  );
  // Clipping belongs to CONTAINERS only: on an image or a field `overflow` means nothing.
  const boxed = joinStyle(layout, clipStyle(node));
  switch (type) {
    case "ПроизвольныйШаблонФормы":
      return renderChildren(get(node, "Содержимое"), false);
    case "Группа":
      return renderGroup(node, "grp", boxed);
    case "СтандартнаяКарточка": {
      const banner = prop(node, "ВидОтображения") === "Баннер";
      return renderGroup(node, banner ? "card banner" : "card", boxed);
    }
    case "Надпись": {
      const text = prop(node, "Значение") ?? prop(node, "Заголовок");
      return `<span ${tagAttrs(node, "lbl", joinStyle(textStyle(node), layout))}>${valueHtml(text, "Надпись")}</span>`;
    }
    case "ЗаголовокСекции":
      return `<div ${tagAttrs(node, "sechead", layout)}>${valueHtml(prop(node, "Заголовок"), "Секция")}</div>`;
    case "ПолеВвода":
    case "ПолеВыбора":
    case "ВыборЗначения": {
      const cap = prop(node, "Заголовок");
      const suffix = type === "ПолеВвода" ? "" : `<span class="dd">▾</span>`;
      return (
        `<div ${tagAttrs(node, "fld", layout)}>` +
        (cap ? `<div class="fld-cap">${esc(cap)}</div>` : "") +
        `<div class="inp">${valueHtml(prop(node, "Значение"), "…")}${suffix}${fieldCommands(node)}</div></div>`
      );
    }
    case "Флажок":
      return `<label ${tagAttrs(node, "chk", layout)}>☐ ${valueHtml(prop(node, "Заголовок"), "Флажок")}</label>`;
    case "Кнопка":
    case "КнопкаФормы":
    case "ОбычнаяКоманда":
    case "НавигационнаяКоманда": {
      const kind = prop(node, "Вид");
      let cls = kind === "Основная" ? "btn primary" : kind === "Дополнительная" ? "btn link" : "btn";
      // The platform tints dangerous actions; the wireframe follows with red and amber.
      const danger = prop(node, "ОпасностьДействия");
      if (danger === "Высокая") {
        cls += " dng-hi";
      } else if (danger === "Средняя") {
        cls += " dng-mid";
      }
      const title = prop(node, "Заголовок") ?? prop(node, "Представление") ?? prop(node, "Имя");
      // ВидОтображенияЗаголовка picks icon, text or both; Авто shows the icon when given.
      // An icon that did not resolve keeps a compact glyph, not the full caption.
      const image = prop(node, "Изображение");
      const src = image ? _resources[image] : undefined;
      const icon = image ? (src ? `<img class="bico" src="${esc(src)}" alt="">` : `<span class="bico-ph">🖼</span>`) : undefined;
      const head = prop(node, "ВидОтображенияЗаголовка");
      let inner: string;
      if (head === "Иконка" && icon) {
        cls += " ico";
        inner = icon;
      } else if (head === "Текст" || !icon) {
        inner = valueHtml(title, "Кнопка");
      } else {
        inner = icon + valueHtml(title, "Кнопка");
      }
      return `<button ${tagAttrs(node, cls, layout)}>${inner}</button>`;
    }
    case "Картинка": {
      // A resource image (Изображение: info.svg) shows for real when the host resolved it; a
      // binding, a URL or an unresolved name keeps the placeholder glyph. An explicit Цвет
      // repaints the image the way the platform's monochrome adaptation does: the image
      // becomes a mask filled with that color.
      const image = prop(node, "Изображение");
      const src = image ? _resources[image] : undefined;
      const rgb = prop(get(node, "Цвет"), "Значение");
      const hex = rgb && /^RGB\(([0-9A-Fa-f]{6})\)$/.exec(rgb.trim());
      let inner: string;
      if (src && hex) {
        const mask = `-webkit-mask-image:url("${src}");mask-image:url("${src}")`;
        inner = `<span class="rmask" style="${esc(`background-color:#${hex[1]};${mask}`)}"></span>`;
      } else if (src) {
        inner = `<img class="rimg" src="${esc(src)}" alt="">`;
      } else {
        inner = "🖼";
      }
      // Explicit sizes defeat the fixed placeholder tile; when only one dimension is given
      // the other follows the image's aspect ratio instead of the tile's.
      const w = numOf(node, "Ширина");
      const h = numOf(node, "Высота");
      const free = w && !h ? "height:auto" : h && !w ? "width:auto" : "";
      return `<div ${tagAttrs(node, "img", joinStyle(layout, free))}>${inner}</div>`;
    }
    case "Таблица":
    case "ПроизвольныйСписок":
      return renderTable(node);
    case "Страницы":
      return renderTabs(node, horizontalParent);
    case "КонтейнерHtml":
    case "РедакторHtml":
      return `<div ${tagAttrs(node, "htmlbox", layout)}><span class="tag">HTML${prop(node, "Имя") ? " · " + esc(prop(node, "Имя")!) : ""}</span></div>`;
    default:
      return renderUnknown(node, type || "?");
  }
}

// Form command bar: ОсновнаяКоманда + maps of named commands (КомандыЗаписи etc.).
function renderCommandBar(inherit: unknown): string {
  const buttons: string[] = [];
  const push = (cmd: unknown, fallback: string) => {
    if (!isMap(cmd)) {
      return;
    }
    const title = prop(cmd, "Представление") ?? prop(cmd, "Заголовок") ?? fallback;
    buttons.push(`<button ${tagAttrs(cmd, buttons.length === 0 ? "btn primary" : "btn")}>${esc(title)}</button>`);
  };
  push(get(inherit, "ОсновнаяКоманда"), "Основная команда");
  for (const key of ["КомандыЗаписи", "ДополнительныеКоманды", "Команды"]) {
    const cmds = get(inherit, key);
    if (isMap(cmds)) {
      for (const item of (cmds as YAMLMap).items) {
        push(item.value, isScalar(item.key) ? String(item.key.value) : "");
      }
    } else if (isSeq(cmds)) {
      for (const item of cmds.items) {
        push(item, "");
      }
    }
  }
  return buttons.length > 0 ? `<div class="cmdbar">${buttons.join("")}</div>` : "";
}

// -- entry point ----------------------------------------------------------------------------

// -- targeted yaml property edits -------------------------------------------------------------
//
// A property value edit is turned into a targeted text replacement by yaml node ranges - the
// document is not reformatted, undo works. Used by the metadata mode of the properties panel
// (propsModes.metaPropertyEdits); the form designer edits go through the engine (xbsl/formEdit)
// instead.

export interface TextEdit {
  start: number;
  end: number;
  newText: string;
}

function findMapAt(node: unknown, offset: number): YAMLMap | undefined {
  if (isMap(node)) {
    if (node.range && node.range[0] === offset) {
      return node;
    }
    for (const item of node.items) {
      const found = findMapAt(item.value, offset);
      if (found) {
        return found;
      }
    }
  } else if (isSeq(node)) {
    for (const item of node.items) {
      const found = findMapAt(item, offset);
      if (found) {
        return found;
      }
    }
  }
  return undefined;
}

function parsedContents(text: string): unknown {
  try {
    const doc = parseDocument(text, { uniqueKeys: false });
    return doc.contents ?? undefined;
  } catch {
    return undefined;
  }
}

// Scalar to yaml text: simple values without quotes, the rest - double quotes (JSON escaping
// is valid for YAML). Bindings (=Данные.Х) stay unquoted.
function encodeScalar(value: string): string {
  if (/^[=A-Za-zА-Яа-яЁё0-9_][A-Za-zА-Яа-яЁё0-9_.,() =\/-]*$/.test(value) && !/\s$/.test(value)) {
    return value;
  }
  return JSON.stringify(value);
}

function lineStartOf(text: string, offset: number): number {
  return text.lastIndexOf("\n", offset - 1) + 1;
}

function lineEndOf(text: string, offset: number): number {
  const nl = text.indexOf("\n", offset);
  return nl === -1 ? text.length : nl;
}

// Component property edit: value = null removes the property (the line is deleted), an
// existing scalar is replaced within its range, a new property is written as a line after
// "Тип" with the same indent as the node's other keys.
export function propertyEdit(text: string, nodeOffset: number, key: string, value: string | null): TextEdit | undefined {
  const node = findMapAt(parsedContents(text), nodeOffset);
  if (!node) {
    return undefined;
  }
  const pair = node.items.find((item) => isScalar(item.key) && String(item.key.value) === key);
  if (value === null) {
    if (!pair || !isScalar(pair.key) || !pair.key.range) {
      return undefined;
    }
    const valueEnd = isScalar(pair.value) && pair.value.range ? pair.value.range[1] : pair.key.range[1];
    const start = lineStartOf(text, pair.key.range[0]);
    const end = Math.min(lineEndOf(text, valueEnd) + 1, text.length);
    return { start, end, newText: "" };
  }
  if (pair) {
    if (isScalar(pair.value) && pair.value.range) {
      return { start: pair.value.range[0], end: pair.value.range[1], newText: encodeScalar(value) };
    }
    if ((pair.value === null || pair.value === undefined) && isScalar(pair.key) && pair.key.range) {
      // "Ключ:" without a value - append the value after the colon.
      const end = lineEndOf(text, pair.key.range[1]);
      return { start: end, end, newText: " " + encodeScalar(value) };
    }
    return undefined; // an object value is not edited by the panel
  }
  // The property is absent - insert after the "Тип" line (or the node's first line).
  const anchor = node.items.find((item) => isScalar(item.key) && String(item.key.value) === "Тип") ?? node.items[0];
  if (!anchor || !isScalar(anchor.key) || !anchor.key.range) {
    return undefined;
  }
  const anchorKeyStart = anchor.key.range[0];
  const indent = anchorKeyStart - lineStartOf(text, anchorKeyStart);
  const anchorValueEnd = isScalar(anchor.value) && anchor.value.range ? anchor.value.range[1] : anchor.key.range[1];
  const insertAt = lineEndOf(text, anchorValueEnd);
  return { start: insertAt, end: insertAt, newText: `\n${" ".repeat(indent)}${key}: ${encodeScalar(value)}` };
}

// Resource images for the current render, filename -> data URI (resolved by the host from the
// project's Ресурсы directories). Module-scoped render context so it does not have to thread
// through every render function; set at the start of each (synchronous) renderFormPreview call.
let _resources: Record<string, string> = {};

export function renderFormPreview(text: string, resources: Record<string, string> = {}): PreviewResult {
  _resources = resources;
  let doc;
  try {
    doc = parseDocument(text, { uniqueKeys: false });
  } catch (e) {
    return { ok: false, reason: "parse", detail: e instanceof Error ? e.message : String(e) };
  }
  if (doc.errors.length > 0 && !doc.contents) {
    return { ok: false, reason: "parse", detail: doc.errors[0].message };
  }
  const root = doc.contents;
  const inherit = get(root, "Наследует");
  const content = get(inherit, "Содержимое");
  if (!content) {
    return { ok: false, reason: "not-form" };
  }
  const rawTitle = prop(inherit, "Заголовок");
  const name = prop(root, "Имя") ?? "";
  const baseTypeName = prop(inherit, "Тип") ?? "";
  const titleHtml =
    `<div class="form-head"><span class="form-title">${valueHtml(rawTitle, name)}</span>` +
    `<span class="form-type">${esc(baseTypeName)}</span></div>`;
  const body = titleHtml + renderCommandBar(inherit) + `<div class="form-body col">${renderComponent(content, false)}</div>`;
  return { ok: true, html: body, title: name || rawTitle || "форма" };
}

// -- selection sync (the preview panel drives these) ------------------------------------------
//
// The wireframe highlights the node selected in the yaml editor and survives re-renders.
// The pure parts live here: the offsets a rendered wireframe exposes, the cursor-to-node
// match and the nearest-offset restore after the text (and the offsets) shifted.

// Resource image filenames referenced by Изображение: <file> in the form - a plain filename with
// an image extension, not a binding (=...) and not a URL. The host resolves these against the
// project's Ресурсы directories and passes them to renderFormPreview as data URIs (so the
// wireframe shows the real image instead of the placeholder glyph).
const RESOURCE_IMAGE_RE = /Изображение:\s*([^\s="][^\s"]*\.(?:svg|png|jpe?g|gif|webp))\b/gi;

export function collectResourceImages(text: string): string[] {
  const seen = new Set<string>();
  for (const m of text.matchAll(RESOURCE_IMAGE_RE)) {
    if (!m[1].includes("://")) {
      seen.add(m[1]);
    }
  }
  return [...seen];
}

// All node offsets present in a rendered wireframe (the data-off attributes), ascending.
export function collectDataOffsets(html: string): number[] {
  const offsets = new Set<number>();
  const re = /data-off="(\d+)"/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(html)) !== null) {
    offsets.add(Number(m[1]));
  }
  return [...offsets].sort((a, b) => a - b);
}

// The wireframe block for a yaml cursor position: the closest data-off at or below the cursor.
// Node maps nest, so among the nodes starting at or before the cursor the innermost (the one
// that contains the offset) starts last. undefined when the cursor is above every node - the
// file header carries no component.
export function selectionForCursor(offsets: number[], cursor: number): number | undefined {
  let best: number | undefined;
  for (const off of offsets) {
    if (off <= cursor && (best === undefined || off > best)) {
      best = off;
    }
  }
  return best;
}

// Restore a selection after a re-render: the same offset when it survived the edit, otherwise
// the nearest one (the node moved with the text above it). Ties resolve to the earlier node;
// undefined only when nothing is rendered.
export function nearestOffset(offsets: number[], previous: number): number | undefined {
  let best: number | undefined;
  for (const off of offsets) {
    if (best === undefined || Math.abs(off - previous) < Math.abs(best - previous)) {
      best = off;
    }
  }
  return best;
}

// -- session restore ---------------------------------------------------------------------------

// Which form a restored preview panel should show. VS Code hands the serializer the state the
// webview saved for itself; that is the authority, and the value remembered by the extension is
// the fallback for a panel that never got to save one (an older session, a crash). A blank or
// non-string value on either side is ignored, so the panel comes back empty rather than pointed
// at nonsense.
export function restoredTargetUri(webviewState: unknown, remembered: unknown): string | undefined {
  const pick = (value: unknown): string | undefined => {
    const text = typeof value === "string" ? value.trim() : "";
    return text || undefined;
  };
  const state = webviewState as { uri?: unknown } | undefined;
  return pick(state?.uri) ?? pick(remembered);
}
