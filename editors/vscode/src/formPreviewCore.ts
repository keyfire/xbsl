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

// {"Dictionary.Key": text} of the project, filled from the engine (`xbsl/localizationStrings`)
// in the editor's language. Without it a localized value was drawn as the key's last segment and
// the page read as a row of identifiers instead of the words the user will see.
let _locStrings: Record<string, string> = {};

// Availability travels DOWN the tree: "the availability state applies to every component of
// the content until an override is met" (docs of the component properties). The wireframe keeps
// it in a flag rather than in a parameter - the render is synchronous and single-threaded, and
// threading a parameter through every renderer would touch a dozen call sites for one bit.
let _inaccessible = false;

export function setLocalizationStrings(strings: Record<string, string>): void {
  _locStrings = strings ?? {};
}

// -- wireframe placeholder strings -----------------------------------------------------------
//
// The texts the wireframe shows on its own (placeholders, the table toolbar, the search bar)
// in the platform's canonical Russian; the host overrides them with the editor's language
// (vscode.l10n), so an English VS Code shows an English wireframe. The core stays pure.
const PREVIEW_STRINGS_RU = {
  label: "Надпись",
  button: "Кнопка",
  checkbox: "Флажок",
  section: "Секция",
  mainCommand: "Основная команда",
  form: "форма",
  add: "Добавить",
  search: "Поиск...",
  option: "Вариант",
  dropText: "Перетащите файлы в окно или {0} вручную",
  dropLink: "добавьте",
  fileDropText: "{0} или перетащите файлы в эту область",
  fileDropLink: "Выберите",
};

export type PreviewStrings = typeof PREVIEW_STRINGS_RU;

let _strings: PreviewStrings = PREVIEW_STRINGS_RU;

export function setPreviewStrings(overrides: Partial<PreviewStrings>): void {
  _strings = { ...PREVIEW_STRINGS_RU, ...overrides };
}

function s(key: keyof PreviewStrings): string {
  return _strings[key];
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
  // Availability is drawn the way the platform draws it - a gray fill with no border - both when
  // it is switched off outright and when it is computed: the frame cannot know which way the
  // expression goes, and a field that may be closed reads better closed.
  const availability = prop(node, "Доступность");
  const inaccessible = _inaccessible || availability === "Ложь"
    || (availability !== undefined && availability.startsWith("="));
  const tip = [
    prop(node, "Тип"),
    prop(node, "Имя"),
    hidden ? "Видимость: Ложь" : conditional ? `Видимость: ${visibility}` : undefined,
    availability !== undefined ? `Доступность: ${availability}` : undefined,
  ].filter(Boolean).join(" · ");
  const titleAttr = tip ? ` title="${esc(tip)}"` : "";
  const mark = (hidden ? " off" : conditional ? " cond" : "") + (inaccessible ? " dis" : "");
  return `class="${cls}${mark}"${styleAttr}${offAttr}${titleAttr}`;
}

// The platform's designer cuts a long expression in the MIDDLE - the head names the data and the
// tail names the field, and both matter, while a CSS ellipsis keeps the head alone. CSS cannot cut
// a middle, so the string is cut here; the whole text stays in the tooltip. The threshold is taken
// from the corpora: half of the expressions are under 30 characters and 90% under 55, so 64 leaves
// the ordinary ones untouched and shortens the long tail (168 of 2518 on two projects).
export const EXPRESSION_MAX = 64;

export function middleEllipsis(text: string, max = EXPRESSION_MAX): string {
  if (text.length <= max) {
    return text;
  }
  // The head keeps a little more than the tail: it carries the data source, which is what the
  // reader looks for first.
  const head = Math.ceil((max - 1) * 0.6);
  const tail = max - 1 - head;
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`;
}

// Property value: a binding (`=Данные.Х`) is shown as a monospaced chip, a localization
// reference (`$Словарь.Ключ`) - as the TEXT the user will see, with the key in the tooltip, and
// a literal - as text. When the engine has not answered with the strings (or the key is not
// among them - a stale reference, a translation still missing), the reference falls back to its
// last segment, which is what the frame used to show for every such value.
function valueHtml(v: string | undefined, placeholder = ""): string {
  if (v === undefined || v === "") {
    return `<span class="ph">${esc(placeholder)}</span>`;
  }
  if (v.startsWith("=")) {
    const shown = middleEllipsis(v);
    const tip = shown === v ? "" : ` title="${esc(v)}"`;
    return `<code class="chip"${tip}>${esc(shown)}</code>`;
  }
  if (v.startsWith("$")) {
    const key = v.slice(1);
    const text = _locStrings[key];
    if (text !== undefined && text !== "") {
      return `<span class="loc" title="${esc(v)}">${esc(text)}</span>`;
    }
    const last = v.slice(v.lastIndexOf(".") + 1) || key;
    return `<span class="loc" title="${esc(v)}">${esc(last)}</span>`;
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


// WidthInColumns. The platform states the scale by name (half a column ... four columns,
// unlimited) and never says what a column is, so the wireframe used to invent a fixed base and
// keep the ratios exact against it. MEASURED on a deployed form (a probe of all five sizes,
// read at six viewport widths), the platform turns out to do something else entirely - the
// column is not a constant but a share of the row:
//
//   gap between columns    24px, always;
//   number of columns      the largest n <= 4 whose column (row - (n-1)*24) / n is >= 250px;
//   a size of N columns    N * column + (N-1) * 24;
//   half a column          (column - 24) / 2, so two halves fill one column with a gap;
//   the unlimited size      the whole row.
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

// The component's background: a literal absolute color paints it; an expression is computed
// by the runtime and the wireframe leaves it alone.
function bgStyle(node: unknown): string {
  const rgb = prop(get(node, "Фон"), "Значение");
  const hex = rgb && /^RGB\(([0-9A-Fa-f]{6})\)$/.exec(rgb.trim());
  return hex ? `background-color:#${hex[1]}` : "";
}

function renderGroup(node: unknown, cls: string, extraStyle = ""): string {
  const layout = layoutClass(node);
  const style = [extraStyle, bgStyle(node), contentAlignStyle(node), spacingStyle(node), layout.style]
    .filter(Boolean).join(";");
  const inner = renderChildren(get(node, "Содержимое"), layout.horizontal, layout.byColumns);
  return `<div ${tagAttrs(node, `${cls} ${layout.cls}`, style)}>${nameTag(node)}${inner}</div>`;
}

// The platform draws tables without a grid: bare headers, hairline row separators and - when
// rows are created right in the table (OnRowCreate) - a toolbar strip above it.
function renderTable(node: unknown, layout = ""): string {
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
  const th = heads.map((h) => `<th>${h ? valueHtml(h) : "&nbsp;"}</th>`).join("");
  const placeholderRow = `<tr>${heads.map(() => "<td>···</td>").join("")}</tr>`;
  const editable = get(node, "ПриСозданииСтроки") !== undefined;
  const bar = editable
    ? `<div class="tbar"><span class="codicon codicon-add"></span>${esc(s("add"))}<span class="tsp"></span><span class="codicon codicon-search"></span></div>`
    : "";
  return (
    `<div ${tagAttrs(node, "tblbox", layout)}>${bar}` +
    `<table class="tbl"><thead><tr>${th}</tr></thead><tbody>${placeholderRow}${placeholderRow}</tbody></table></div>`
  );
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
    bar.push(`<button class="tabbtn${i === 0 ? " act" : ""}" data-tab="${i}"${off !== undefined ? ` data-off="${off}"` : ""}>${valueHtml(title)}</button>`);
    bodies.push(`<div class="tabpage${i === 0 ? " act" : ""}" data-tab="${i}">${renderChildren(get(page, "Содержимое"), false)}</div>`);
  });
  return `<div ${tagAttrs(node, "tabs", growStyle(node, horizontalParent))}><div class="tabbar">${bar.join("")}</div>${bodies.join("")}</div>`;
}

function renderUnknown(node: unknown, type: string): string {
  // A PROJECT component (its yaml was handed over by the host): its own content is drawn
  // inline, so a site page assembled from cards and buttons looks like the page and not like a
  // fence of placeholders. The offsets of the nested yaml are stripped - they belong to another
  // file, and the whole block navigates to its USE site. Depth is capped and a name on the
  // rendering stack is skipped: components may nest and, in a broken project, recurse.
  const sub = _components[type];
  if (sub !== undefined && _subStack.length < 2 && !_subStack.includes(type)) {
    let contents = _componentCache.get(type);
    if (contents === undefined) {
      contents = parsedContents(sub) ?? null;
      _componentCache.set(type, contents);
    }
    const content = get(get(contents, "Наследует"), "Содержимое");
    if (content) {
      _subStack.push(type);
      const inner = renderComponent(content, false).replace(/ data-off="\d+"/g, "");
      _subStack.pop();
      return `<div ${tagAttrs(node, "subc")}>${inner}</div>`;
    }
  }
  const inner = renderChildren(get(node, "Содержимое"), false);
  const label = `${esc(type)}${prop(node, "Имя") ? " · " + esc(prop(node, "Имя")!) : ""}`;
  // A component the wireframe cannot draw: its caption goes IN FLOW, not as the absolute
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
  // An override switches the state for this node AND for everything under it; the flag is
  // restored on the way out, so a sibling of an inaccessible group stays as it was.
  const availability = prop(node, "Доступность");
  const outerInaccessible = _inaccessible;
  if (availability === "Ложь" || (availability !== undefined && availability.startsWith("="))) {
    _inaccessible = true;
  } else if (availability === "Истина") {
    _inaccessible = false;
  }
  try {
    return renderComponentBody(node, horizontalParent, byColumnsParent);
  } finally {
    _inaccessible = outerInaccessible;
  }
}

function renderComponentBody(node: unknown, horizontalParent: boolean, byColumnsParent = false): string {
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
      return `<span ${tagAttrs(node, "lbl", joinStyle(textStyle(node), layout))}>${valueHtml(text, s("label"))}</span>`;
    }
    case "ЗаголовокСекции":
      return `<div ${tagAttrs(node, "sechead", layout)}>${valueHtml(prop(node, "Заголовок"), s("section"))}</div>`;
    case "ПолеВвода":
    case "ПолеВыбора":
    case "ВыборЗначения": {
      const cap = prop(node, "Заголовок");
      // A required field gets the platform's red asterisk before the caption.
      const required = isTrue(node, "Обязательное");
      const capHtml = cap
        ? `<div class="fld-cap">${required ? `<span class="req">*</span>` : ""}${valueHtml(cap)}</div>`
        : "";
      // A switcher: a value choice with a radio-button group is drawn as circles, not as a box.
      if (prop(node, "ВидОтображенияПереключателя") !== undefined) {
        return (
          `<div ${tagAttrs(node, "rgrp col", layout)}>${capHtml}` +
          `<label class="radio"><span class="rdo"></span>${valueHtml(prop(node, "Значение"), s("option"))}</label></div>`
        );
      }
      // A date field carries a calendar at its right edge, a choice field - a chevron; gray,
      // inside the box. The type parameter is bilingual like the source: InputField<Date>.
      const rawType = prop(node, "Тип") ?? "";
      const icon =
        type === "ПолеВвода"
          ? /<\s*(Дата|Date)/.test(rawType)
            ? `<span class="fico codicon codicon-calendar"></span>`
            : ""
          : `<span class="fico codicon codicon-chevron-down"></span>`;
      return (
        `<div ${tagAttrs(node, "fld", layout)}>${capHtml}` +
        `<div class="inp">${valueHtml(prop(node, "Значение"), "…")}${icon}${fieldCommands(node)}</div></div>`
      );
    }
    case "Флажок":
      return `<label ${tagAttrs(node, "chk", layout)}><span class="cbox"></span>${valueHtml(prop(node, "Заголовок"), s("checkbox"))}</label>`;
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
        inner = valueHtml(title, s("button"));
      } else {
        inner = icon + valueHtml(title, s("button"));
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
        // The platform's placeholder - a gray image glyph with no border and no background.
        inner = `<span class="iph codicon codicon-file-media"></span>`;
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
      return renderTable(node, boxed);
    case "Страницы":
      return renderTabs(node, horizontalParent);
    case "РедакторHtml":
      // The text editor: an input-like box with the formatting toolbar on top.
      return (
        `<div ${tagAttrs(node, "editor", layout)}>` +
        `<div class="edbar"><b>B</b><i>I</i><u>U</u>` +
        `<span class="codicon codicon-list-unordered"></span><span class="codicon codicon-link"></span></div>` +
        `<div class="edbody">${valueHtml(prop(node, "Значение"), "")}</div></div>`
      );
    case "ВыборФайлов":
      return (
        `<div ${tagAttrs(node, "drop", layout)}>` +
        `${esc(s("dropText")).replace("{0}", `<span class="dlink">${esc(s("dropLink"))}</span>`)}</div>`
      );
    case "СписокФайлов":
      return (
        `<div ${tagAttrs(node, "filedrop", layout)}>` +
        `<span class="clip codicon codicon-cloud-upload"></span>` +
        `<div>${esc(s("fileDropText")).replace("{0}", `<span class="dlink">${esc(s("fileDropLink"))}</span>`)}</div></div>`
      );
    case "КонтейнерHtml":
      return `<div ${tagAttrs(node, "htmlbox", layout)}><span class="tag">HTML${prop(node, "Имя") ? " · " + esc(prop(node, "Имя")!) : ""}</span></div>`;
    default:
      return renderUnknown(node, type || "?");
  }
}

// Form commands, placed the way the platform places them: the main commands (ОсновнаяКоманда,
// КомандыЗаписи) sit at the BOTTOM right as the yellow primary and its gray neighbours, the
// auxiliary ones (ДополнительныеКоманды, Команды) are gray pills at the top right of the title,
// and the create commands of a list form are a blue text button next to it.
function commandButton(cmd: unknown, cls: string, fallback: string): string | undefined {
  if (!isMap(cmd)) {
    return undefined;
  }
  const title = prop(cmd, "Представление") ?? prop(cmd, "Заголовок") ?? fallback;
  return `<button ${tagAttrs(cmd, cls)}>${valueHtml(title)}</button>`;
}

function collectCommands(inherit: unknown, keys: string[], cls: string): string[] {
  const buttons: string[] = [];
  for (const key of keys) {
    const cmds = get(inherit, key);
    if (isMap(cmds)) {
      for (const item of (cmds as YAMLMap).items) {
        const btn = commandButton(item.value, cls, isScalar(item.key) ? String(item.key.value) : "");
        if (btn) {
          buttons.push(btn);
        }
      }
    } else if (isSeq(cmds)) {
      for (const item of cmds.items) {
        const btn = commandButton(item, cls, "");
        if (btn) {
          buttons.push(btn);
        }
      }
    }
  }
  return buttons;
}

function renderHeaderCommands(inherit: unknown): string {
  const create = collectCommands(inherit, ["КомандыСоздания"], "btn create");
  const pills = collectCommands(inherit, ["ДополнительныеКоманды", "Команды"], "btn pill");
  const parts = [...create, ...pills];
  return parts.length > 0 ? `<span class="hsp"></span><span class="cmdbar pills">${parts.join("")}</span>` : "";
}

function renderFooterCommands(inherit: unknown): string {
  const buttons: string[] = [];
  const main = commandButton(get(inherit, "ОсновнаяКоманда"), "btn primary", s("mainCommand"));
  if (main) {
    buttons.push(main);
  }
  buttons.push(...collectCommands(inherit, ["КомандыЗаписи"], "btn"));
  return buttons.length > 0 ? `<div class="cmdbar footer">${buttons.join("")}</div>` : "";
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
// project's Ресурсы directories), and the yaml texts of the PROJECT components used by the
// form (component type name -> its yaml) - with them a page assembled from project cards is
// drawn with their content instead of placeholders. Module-scoped render context so it does
// not have to thread through every render function; set at the start of each (synchronous)
// renderFormPreview call.
let _resources: Record<string, string> = {};
let _components: Record<string, string> = {};
const _componentCache = new Map<string, unknown>();
const _subStack: string[] = [];

// The navigation panel of a sectioned application (СтандартноеКлиентскоеПриложениеСРазделами):
// the items live in КомандныйИнтерфейсПанелиНавигации, not in Содержимое.
function renderNavPanel(inherit: unknown): string {
  const nav = get(inherit, "КомандныйИнтерфейсПанелиНавигации");
  const elements = get(nav, "Элементы");
  if (!isSeq(elements)) {
    return "";
  }
  const items: string[] = [];
  const pushItem = (cmd: unknown, group: boolean) => {
    const title = prop(cmd, "Представление") ?? prop(cmd, "Имя") ?? "";
    const image = prop(cmd, "Изображение");
    const src = image ? _resources[image] : undefined;
    const icon = src ? `<img class="navico" src="${esc(src)}" alt="">` : "";
    const chevron = group ? `<span class="codicon codicon-chevron-down"></span>` : "";
    items.push(`<span ${tagAttrs(cmd, "navitem")}>${icon}${valueHtml(title)}${chevron}</span>`);
  };
  for (const item of elements.items) {
    const type = baseType(item) ?? "";
    pushItem(item, type === "ГруппаКомандногоИнтерфейса");
  }
  const theme = get(inherit, "ТемаОформления");
  const logoName = prop(theme, "Логотип");
  const logoSrc = logoName ? _resources[logoName] : undefined;
  const logo = logoSrc ? `<img class="applogo" src="${esc(logoSrc)}" alt="">` : "";
  const vertical = prop(inherit, "ОриентацияПанелиНавигации") === "Вертикальная";
  const bar = `<div class="navbar${vertical ? " vert" : ""}">${logo}${items.join("")}</div>`;
  const body = `<div class="appbody"></div>`;
  return `<div class="app${vertical ? " vert" : ""}">${bar}${body}</div>`;
}

export function renderFormPreview(
  text: string,
  resources: Record<string, string> = {},
  components: Record<string, string> = {},
): PreviewResult {
  _resources = resources;
  _components = components;
  _componentCache.clear();
  _subStack.length = 0;
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
  const navPanel = content ? "" : renderNavPanel(inherit);
  if (!content && !navPanel) {
    return { ok: false, reason: "not-form" };
  }
  const rawTitle = prop(inherit, "Заголовок");
  const name = prop(root, "Имя") ?? "";
  const baseTypeName = prop(inherit, "Тип") ?? "";
  const titleHtml =
    `<div class="form-head"><span class="form-title">${valueHtml(rawTitle, name)}</span>` +
    `<span class="form-type">${esc(baseTypeName)}</span>${renderHeaderCommands(inherit)}</div>`;
  // A list form gets its chrome from the platform, not from the yaml: the search bar above
  // the list is drawn so the wireframe reads like the page the user will see.
  const searchBar = baseTypeName.startsWith("ФормаСписка")
    ? `<div class="searchbar"><span class="codicon codicon-search"></span>${esc(s("search"))}</div>`
    : "";
  const body =
    titleHtml + searchBar +
    `<div class="form-body col">${content ? renderComponent(content, false) : navPanel}</div>` +
    renderFooterCommands(inherit);
  return { ok: true, html: body, title: name || rawTitle || s("form") };
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

// Component type names the wireframe draws itself - there is no point looking for their yaml.
const DRAWN_TYPES = new Set([
  "ПроизвольныйШаблонФормы", "Группа", "СтандартнаяКарточка", "Надпись", "ЗаголовокСекции",
  "ПолеВвода", "ПолеВыбора", "ВыборЗначения", "Флажок", "Кнопка", "КнопкаФормы",
  "ОбычнаяКоманда", "НавигационнаяКоманда", "Картинка", "Таблица", "ПроизвольныйСписок",
  "Страницы", "РедакторHtml", "ВыборФайлов", "СписокФайлов", "КонтейнерHtml",
]);

// The bare type names used by the form (`Тип: КарточкаОблако`) that MAY be project components:
// the host looks their yaml up in the workspace (`<Имя>.yaml`) and hands the texts to
// renderFormPreview - platform types simply have no such file and drop out on their own.
export function collectComponentTypes(text: string): string[] {
  const seen = new Set<string>();
  const re = /(?:^|\n)[ \t-]*(?:Тип|Type):[ \t]*([A-Za-zА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*)[ \t]*(?:<[^\n]*)?(?=\n|$)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const name = canonicalType(m[1]);
    if (!DRAWN_TYPES.has(name)) {
      seen.add(name);
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
