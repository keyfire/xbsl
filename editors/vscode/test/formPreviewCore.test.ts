// Tests of the form wireframe rendering (yaml -> HTML) and of the targeted property edits
// that serve the metadata properties panel. Run with plain node (see npm test).

import { collectComponentTypes, collectDataOffsets, collectResourceImages, nearestOffset, propertyEdit, renderFormPreview, restoredTargetUri, selectionForCursor, setFormKeyAliases, setLocalizationStrings } from "../src/formPreviewCore";

let failures = 0;

function check(name: string, cond: boolean): void {
  if (cond) {
    console.log(`ok   ${name}`);
  } else {
    failures++;
    console.error(`FAIL ${name}`);
  }
}

const FORM = `
ВидЭлемента: КомпонентИнтерфейса
Ид: 00000000-0000-4000-8000-000000000001
Имя: ТестоваяФорма
Наследует:
    Тип: Форма<Строка?>
    Заголовок: Ввод значения
    ОсновнаяКоманда:
        Тип: ОбычнаяКоманда
        Обработчик: ВыполнитьЗаписать
        Представление: Записать
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Компоновка: Вертикальная
            Содержимое:
                -
                    Тип: Надпись
                    Значение: "Введите код:"
                    Цвет:
                        Тип: АбсолютныйЦвет
                        Значение: RGB(595964)
                -
                    Тип: ПолеВвода<Строка>
                    Имя: ПолеКод
                    Заголовок: Код
                    Значение: =Код
                -
                    Тип: Страницы
                    Страницы:
                        -
                            Имя: СтраницаОдин
                            Заголовок: Первая
                            Содержимое:
                                Тип: Флажок
                                Заголовок: Включено
                        -
                            Имя: СтраницаДва
                            Заголовок: Вторая
                            Содержимое:
                                Тип: Таблица<Неопределено>
                                Колонки:
                                    -
                                        Тип: СтандартнаяКолонкаТаблицы<Неопределено>
                                        Заголовок: Наименование
                -
                    Тип: Группа
                    Компоновка: Горизонтальная
                    ВыравниваниеВГруппеПоГоризонтали: Конец
                    Содержимое:
                        -
                            Тип: Кнопка
                            Вид: Основная
                            Заголовок: "Активировать"
`;

const result = renderFormPreview(FORM);
check("форма разбирается", result.ok);
if (result.ok) {
  const html = result.html;
  check("заголовок формы", html.includes("Ввод значения"));
  check("команда формы в панели команд", html.includes("Записать"));
  check("надпись с литералом", html.includes("Введите код:"));
  check("цвет надписи из АбсолютныйЦвет", html.includes("color:#595964"));
  check("поле ввода: подпись", html.includes("Код") && html.includes('class="fld'));
  check("биндинг чипом", html.includes("=Код") && html.includes('class="chip"'));
  check("вкладки: две кнопки", (html.match(/class="tabbtn/g) ?? []).length === 2);
  check("вкладки: заголовки", html.includes("Первая") && html.includes("Вторая"));
  check("таблица: колонка", html.includes("<th>Наименование</th>"));
  check("кнопка Основная = primary", html.includes('btn primary'));
  check("горизонтальная группа row", html.includes('grp row'));
  // ВыравниваниеВГруппеПо* ставит компонент в РОДИТЕЛЕ (здесь горизонталь - поперечная ось
  // вертикального родителя, то есть align-self), а раскладку детей задаёт
  // ВыравниваниеСодержимогоПо* - это разные свойства, и платформа документирует их порознь.
  check("выравнивание себя в родителе", html.includes("align-self:flex-end"));
  check("узлы кликабельны (data-off)", html.includes("data-off="));
  check("нет сырых < из значений", !html.includes("Форма<Строка?>"));
  check("node tooltip carries type and name", html.includes('title="ПолеВвода&lt;Строка&gt; · ПолеКод"'));
  check("node tooltip without a name is the bare type", html.includes('title="Надпись"'));
}

// A localization reference (`$Словарь.Ключ`) shows its last segment with the full key in the
// tooltip: the real text lives in the localization files, the wireframe stays readable without them.
const LOC_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Заголовок: $ОсновноеЛокализация.ЗаголовокФормы",
  "    Содержимое:",
  "        Тип: ПолеВвода<Строка>",
  "        Заголовок: $ОсновноеЛокализация.Название",
  "        Обязательное: Истина",
  "",
].join("\n");
const loc = renderFormPreview(LOC_FORM);
check("локализация: последний сегмент ключа", loc.ok && loc.html.includes(">Название</span>") && !loc.html.includes(">$ОсновноеЛокализация.Название<"));
check("локализация: полный ключ в подсказке", loc.ok && loc.html.includes('title="$ОсновноеЛокализация.Название"'));
check("обязательное поле: звёздочка", loc.ok && loc.html.includes('class="req"'));

// With the strings from the engine the same value is drawn as the TEXT the user will see, and the
// key moves to the tooltip: the page used to read as a row of identifiers.
setLocalizationStrings({ "ОсновноеЛокализация.Название": "Наименование" });
const locText = renderFormPreview(LOC_FORM);
check("локализация: показан текст, а не ключ", locText.ok && locText.html.includes(">Наименование</span>"));
check("локализация: ключ остался в подсказке", locText.ok && locText.html.includes('title="$ОсновноеЛокализация.Название"'));
// A key the engine does not know (a stale reference, a translation still missing) keeps the old
// behaviour instead of showing an empty label.
const locPartial = renderFormPreview(LOC_FORM);
check("локализация: незнакомый ключ – последний сегмент", locPartial.ok && locPartial.html.includes(">ЗаголовокФормы<"));
setLocalizationStrings({});

// A project component whose yaml was handed over by the host is drawn with its own content; the
// offsets of the nested file are stripped - navigation goes to the USE site. No yaml - a placeholder.
const SUB_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        Тип: КарточкаОблако",
  "        Имя: Карточка1",
  "",
].join("\n");
const SUB_COMPONENT = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Имя: КарточкаОблако",
  "Наследует:",
  "    Тип: Форма",
  "    Содержимое:",
  "        Тип: Надпись",
  "        Значение: Текст карточки",
  "",
].join("\n");
const nested = renderFormPreview(SUB_FORM, {}, { КарточкаОблако: SUB_COMPONENT });
check("вложенный компонент: содержимое из его yaml", nested.ok && nested.html.includes("Текст карточки") && nested.html.includes('class="subc"'));
check(
  "вложенный компонент: одно смещение - место использования",
  nested.ok && collectDataOffsets(nested.html).length === 1 && collectDataOffsets(nested.html)[0] === SUB_FORM.indexOf("Тип: КарточкаОблако")
);
const bare = renderFormPreview(SUB_FORM);
check("без yaml компонента - заглушка", bare.ok && bare.html.includes('class="unknown'));
check(
  "collectComponentTypes отдаёт кандидатов без нарисованных типов",
  JSON.stringify(collectComponentTypes(SUB_FORM)) === JSON.stringify(["КарточкаОблако"]) &&
    collectComponentTypes(SUB_COMPONENT).length === 1 // Form is an inheritance type, not a drawn component
);

// A sectioned application: no content, a navigation panel instead - the wireframe draws the app chrome.
const APP_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Тип: СтандартноеКлиентскоеПриложениеСРазделами",
  "    ОриентацияПанелиНавигации: Вертикальная",
  "    КомандныйИнтерфейсПанелиНавигации:",
  "        Тип: ФрагментКомандногоИнтерфейса",
  "        Элементы:",
  "            -",
  "                Тип: НавигационнаяКоманда",
  "                Представление: Программы",
  "                ТипФормы: ПрограммыФормаСписка",
  "",
].join("\n");
const app = renderFormPreview(APP_FORM);
check("приложение с разделами: панель навигации", app.ok && app.html.includes('class="app vert"') && app.html.includes("Программы"));

const notForm = renderFormPreview("Ид: 1\nИмя: Просто\n");
check("не-форма распознана", !notForm.ok && notForm.reason === "not-form");

const broken = renderFormPreview("Имя: [незакрытый\n  список");
check("битый yaml: аккуратный отказ без исключения", !broken.ok);

// -- targeted property edits (the metadata properties panel drives these) ------------------

const apply = (text: string, edit: { start: number; end: number; newText: string } | undefined): string =>
  edit ? text.slice(0, edit.start) + edit.newText + text.slice(edit.end) : text;

const groupOff = FORM.indexOf("Тип: Группа");
const replaced = apply(FORM, propertyEdit(FORM, groupOff, "Компоновка", "Горизонтальная"));
check("правка: замена значения", replaced.includes("Компоновка: Горизонтальная") && !replaced.includes("Компоновка: Вертикальная"));
check("правка: результат парсится", renderFormPreview(replaced).ok);

const inserted = apply(FORM, propertyEdit(FORM, groupOff, "РастягиватьПоГоризонтали", "Истина"));
check("правка: вставка нового свойства", inserted.includes("РастягиватьПоГоризонтали: Истина"));
check("правка: после вставки парсится", renderFormPreview(inserted).ok);

const labelOff = FORM.indexOf("Тип: Надпись");
const removed = apply(FORM, propertyEdit(FORM, labelOff, "Значение", null));
check("правка: снятие свойства удаляет строку", !removed.includes("Введите код:"));
check("правка: после снятия парсится", renderFormPreview(removed).ok);

const quoted = apply(FORM, propertyEdit(FORM, labelOff, "Значение", "Текст: с двоеточием"));
check("правка: значение с двоеточием в кавычках", quoted.includes('Значение: "Текст: с двоеточием"'));
check("правка: после кавычек парсится", renderFormPreview(quoted).ok);

check("правка: смещение не на узле – undefined", propertyEdit(FORM, 3, "Имя", "Х") === undefined);

// -- selection sync: cursor -> node, restore after a re-render ------------------------------

function renderedOffsets(text: string): number[] {
  const r = renderFormPreview(text);
  return r.ok ? collectDataOffsets(r.html) : [];
}

const offsets = renderedOffsets(FORM);
const labelNodeOff = FORM.indexOf("Тип: Надпись");
const fieldNodeOff = FORM.indexOf("Тип: ПолеВвода<Строка>");

check("offsets are collected and ascending", offsets.length > 5 && offsets.every((o, i) => i === 0 || offsets[i - 1] < o));
check("component starts are among the offsets", offsets.includes(labelNodeOff) && offsets.includes(fieldNodeOff));

check("cursor in the file header - no node", selectionForCursor(offsets, 0) === undefined);
check("cursor at a node start - that node", selectionForCursor(offsets, labelNodeOff) === labelNodeOff);
// The cursor sits inside a property value object (Цвет) that is not a component itself:
// the match is the closest data-off below, i.e. the component that contains the offset.
check("cursor inside a node - the containing node", selectionForCursor(offsets, FORM.indexOf("RGB(595964)")) === labelNodeOff);
check("cursor on a node property - the node", selectionForCursor(offsets, FORM.indexOf("Заголовок: Код")) === fieldNodeOff);
check("empty offsets - no selection", selectionForCursor([], 10) === undefined);

check("restore: an exact survivor is kept", nearestOffset(offsets, fieldNodeOff) === fieldNodeOff);
check("restore: the nearest offset wins", nearestOffset([10, 52, 90], 50) === 52);
check("restore: a tie resolves to the earlier node", nearestOffset([40, 60], 50) === 40);
check("restore: empty offsets - undefined", nearestOffset([], 50) === undefined);

// An edit above the node shifts the text: the restore lands on the shifted node start.
const SHIFTED = FORM.replace('Значение: "Введите код:"', 'Значение: "Введите код и значение:"');
const shiftedOffsets = renderedOffsets(SHIFTED);
const shiftedFieldOff = SHIFTED.indexOf("Тип: ПолеВвода<Строка>");
check(
  "restore after an edit - the shifted node",
  shiftedOffsets.length > 0 && shiftedFieldOff !== fieldNodeOff && nearestOffset(shiftedOffsets, fieldNodeOff) === shiftedFieldOff
);

// --- resource images in the wireframe (Изображение: info.svg) ---
const IMG_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        Тип: Картинка",
  "        Изображение: info.svg",
  "",
].join("\n");
check(
  "resource image names: a plain filename is collected",
  JSON.stringify(collectResourceImages(IMG_FORM)) === JSON.stringify(["info.svg"])
);
check(
  "resource image names: a binding and a URL are skipped",
  collectResourceImages("Изображение: =Объект.Лого\nИзображение: https://x/y.png").length === 0
);
const withImg = renderFormPreview(IMG_FORM, { "info.svg": "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" });
check("Картинка renders an <img> when the resource is resolved", withImg.ok && withImg.html.includes("<img class=\"rimg\" src=\"data:image/svg+xml;base64,"));
const withoutImg = renderFormPreview(IMG_FORM);
check("Картинка keeps the placeholder when the resource is not resolved", withoutImg.ok && !withoutImg.html.includes("<img") && withoutImg.html.includes('class="iph'));

// --- buttons: icon display kind, danger tint, explicit sizes -------------------------------

const BTN_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        -",
  "            Тип: Кнопка",
  "            Имя: КнопкаКопии",
  "            Вид: Дополнительная",
  "            ВидОтображенияЗаголовка: Иконка",
  "            Изображение: copy.svg",
  "            РастягиватьПоГоризонтали: Ложь",
  "            МинимальнаяШирина: 32",
  "        -",
  "            Тип: Кнопка",
  "            Имя: КнопкаДобавить",
  "            Заголовок: Добавить",
  "            Изображение: plus.svg",
  "        -",
  "            Тип: Кнопка",
  "            Заголовок: Удалить",
  "            ОпасностьДействия: Высокая",
  "        -",
  "            Тип: Кнопка",
  "            Заголовок: Сбросить",
  "            ОпасностьДействия: Средняя",
  "            ВидОтображенияЗаголовка: Текст",
  "            Изображение: reset.svg",
  "",
].join("\n");
const BTN_RES = {
  "copy.svg": "data:image/svg+xml;base64,Q09QWQ==",
  "plus.svg": "data:image/svg+xml;base64,UExVUw==",
  "reset.svg": "data:image/svg+xml;base64,UkVTRVQ=",
};
const btns = renderFormPreview(BTN_FORM, BTN_RES);
check("кнопки: форма разбирается", btns.ok);
if (btns.ok) {
  const html = btns.html;
  check("икон-кнопка: класс ico и картинка", html.includes('class="btn link ico"') && html.includes('class="bico" src="data:image/svg+xml;base64,Q09QWQ=="'));
  check("икон-кнопка: имя не попало в содержимое", !html.includes(">КнопкаКопии<"));
  check("икон-кнопка: минимальная ширина", html.includes("min-width:32px"));
  check("икон-кнопка: запрет растягивания прижимает", html.includes("align-self:flex-start"));
  check("кнопка с текстом и иконкой: обе части", html.includes('src="data:image/svg+xml;base64,UExVUw=="') && html.includes(">Добавить</button>"));
  check("опасность Высокая: класс dng-hi", html.includes('class="btn dng-hi"'));
  check("опасность Средняя: класс dng-mid", html.includes("dng-mid"));
  check("ВидОтображенияЗаголовка Текст: иконка не рисуется", !html.includes("UkVTRVQ="));
}
const btnNoRes = renderFormPreview(BTN_FORM);
check(
  "икон-кнопка без ресурса: глиф вместо полного имени",
  btnNoRes.ok && btnNoRes.html.includes('class="bico-ph"') && !btnNoRes.html.includes(">КнопкаКопии<")
);

// --- images: explicit sizes and the explicit color -----------------------------------------

const SIZED_IMG_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        -",
  "            Тип: Картинка",
  "            Изображение: logo.svg",
  "            Ширина: 30",
  "            Высота: 30",
  "            Цвет:",
  "                Тип: АбсолютныйЦвет",
  "                Значение: RGB(1F9D55)",
  "        -",
  "            Тип: Картинка",
  "            Изображение: logo.svg",
  "            Ширина: 40",
  "",
].join("\n");
const sizedImgs = renderFormPreview(SIZED_IMG_FORM, { "logo.svg": "data:image/svg+xml;base64,TE9HTw==" });
check("картинки: форма разбирается", sizedImgs.ok);
if (sizedImgs.ok) {
  const html = sizedImgs.html;
  check("картинка: явные размеры в стиле", html.includes("width:30px;height:30px"));
  check("картинка: явный цвет красит маску", html.includes('class="rmask"') && html.includes("background-color:#1F9D55") && html.includes("mask-image:url("));
  check("картинка: одна размерность освобождает вторую", html.includes("width:40px;height:auto"));
  check("картинка без цвета: обычный img", html.includes('class="rimg"'));
}

// --- a bounded group clips instead of painting over its neighbours -------------------------

const BOUNDED_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        -",
  "            Тип: Группа",
  "            Имя: ОбластьСтраниц",
  "            Высота: 420",
  "            ПрокруткаПоВертикали: Истина",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Страница",
  "        -",
  "            Тип: Группа",
  "            Имя: Ограниченная",
  "            МаксимальнаяВысота: 200",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Хвост",
  "        -",
  "            Тип: Группа",
  "            Имя: Свободная",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Без размера",
  "",
].join("\n");
const bounded = renderFormPreview(BOUNDED_FORM, {});
check("ограниченная группа: форма разбирается", bounded.ok);
if (bounded.ok) {
  const html = bounded.html;
  // The wizard case: a fixed height that asks for a scrollbar - the pages must not paint over
  // the footer that follows them.
  check("группа с прокруткой: overflow-y auto", html.includes("height:420px;overflow-y:auto"));
  // A max height without a scroll property still bounds the box, so it clips.
  check("группа с максимальной высотой: клиппинг", html.includes("max-height:200px;overflow-y:hidden"));
  // A group with no size at all keeps growing - no overflow is imposed on it, so the whole
  // form carries exactly the two rules above.
  check("группа без размера: overflow не навязан", html.split("overflow").length - 1 === 2);
}

// --- content alignment, column width -------------------------------------------------------

const ALIGN_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        -",
  "            Тип: Группа",
  "            Компоновка: Горизонтальная",
  "            ВыравниваниеСодержимогоПоГоризонтали: Конец",
  "            ВыравниваниеСодержимогоПоВертикали: Центр",
  "            Содержимое:",
  "                -",
  "                    Тип: Кнопка",
  "                    Заголовок: Готово",
  "        -",
  "            Тип: Группа",
  "            Имя: ПоКолонкам",
  "            Компоновка: ПоКолонкам",
  "            Содержимое:",
  "                -",
  "                    Тип: ПолеВвода<Строка>",
  "                    Заголовок: Код",
  "                    ШиринаВКолонках: Двойная",
  "                -",
  "                    Тип: ПолеВвода<Строка>",
  "                    Заголовок: Половина",
  "                    ШиринаВКолонках: Половинная",
  "                -",
  "                    Тип: Группа",
  "                    Имя: Полоса",
  "                    ШиринаВКолонках: Неограниченная",
  "                    Содержимое:",
  "                        -",
  "                            Тип: Надпись",
  "                            Значение: Во всю строку",
  "",
].join("\n");
const aligned = renderFormPreview(ALIGN_FORM, {});
check("выравнивание содержимого: форма разбирается", aligned.ok);
if (aligned.ok) {
  const html = aligned.html;
  check("содержимое по главной оси", html.includes("justify-content:flex-end"));
  check("содержимое по поперечной оси", html.includes("align-items:center"));
  // WidthInColumns applies ONLY under the ByColumns layout - that is how the platform uses it.
  // The grid itself is MEASURED on a deployed form: the gap is 24, there are at most four
  // columns and a column is never narrower than 250 - so a size of N columns is a span of N
  // tracks rather than a made-up number of pixels.
  check("column grid: gap", html.includes("gap:24px"));
  check("column grid: column minimum and the cap of four", html.includes("max(250px,calc((100% - 72px) / 4))"));
  check("width in columns: two", html.includes("grid-column:span 2"));
  // Half a column is not half a track: two halves share ONE column, the gap coming out of it.
  check("width in columns: half", html.includes("width:calc(50% - 12px)"));
  check("width in columns: unlimited", html.includes("grid-column:1 / -1"));
}

// --- layouts: the platform has six, the wireframe used to know two ------------------------

const LAYOUT_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        -",
  "            Тип: Группа",
  "            Имя: Ряд",
  "            Компоновка: Горизонтальная",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: В одну строку",
  "        -",
  "            Тип: Группа",
  "            Имя: Матрица",
  "            Компоновка: Матричная",
  "            НастройкиМатричнойКомпоновки:",
  "                ОписаниеАвтоматическихКолонок:",
  "                    МинимальнаяШирина: 260",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Ячейка",
  "        -",
  "            Тип: Группа",
  "            Имя: Лента",
  "            Компоновка: Карусель",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Слайд",
  "        -",
  "            Тип: Группа",
  "            Имя: Десктоп",
  "            Видимость: =не Общее.ЭтоМобильный()",
  "            Содержимое:",
  "                -",
  "                    Тип: Надпись",
  "                    Значение: Только на десктопе",
  "",
].join("\n");
const layouts = renderFormPreview(LAYOUT_FORM, {});
check("компоновки: форма разбирается", layouts.ok);
if (layouts.ok) {
  const html = layouts.html;
  // Горизонтальная - ОДНА строка: "если места недостаточно, содержимое сжимается или
  // прокручивается", а не переносится. Именно перенос ломал подвал сайта.
  check("горизонтальная группа не переносится", html.includes("flex-wrap:nowrap"));
  check("матричная группа - сетка", html.includes("grid-template-columns:repeat(auto-fill,minmax(260px,1fr))"));
  check("карусель прокручивается", html.includes("flex-wrap:nowrap;overflow-x:auto"));
  // Видимость выражением: показан ли узел, решает рантайм - пометка слабее, чем у Ложь.
  check("вычисляемая видимость помечена", html.includes("cond"));
}

// --- field commands (Команды) ---------------------------------------------------------------

const CMD_FORM = [
  "ВидЭлемента: КомпонентИнтерфейса",
  "Наследует:",
  "    Содержимое:",
  "        Тип: ПолеВвода<Строка>",
  "        Заголовок: Код",
  "        Команды:",
  "            Тип: ФрагментКомандногоИнтерфейса",
  "            Элементы:",
  "                -",
  "                    Тип: ОбычнаяКоманда",
  "                    Обработчик: КопироватьОбработчик",
  "                    Изображение: copy.svg",
  "                    Представление: Скопировать код",
  "",
].join("\n");
const cmds = renderFormPreview(CMD_FORM, { "copy.svg": "data:image/svg+xml;base64,Q09QWQ==" });
check("команды поля: форма разбирается", cmds.ok);
if (cmds.ok) {
  const html = cmds.html;
  const cmdOff = CMD_FORM.indexOf("Тип: ОбычнаяКоманда");
  check("команды поля: иконка у поля", html.includes('class="fcmd"') && html.includes('class="cico" src="data:image/svg+xml;base64,Q09QWQ=="'));
  check("команды поля: подсказка из Представление", html.includes('title="Скопировать код"'));
  check("команды поля: узел команды кликабелен", html.includes(`data-off="${cmdOff}"`));
}
const SINGLE_CMD_FORM = CMD_FORM.replace(
  /Команды:[\s\S]*$/,
  ["Команды:", "            Тип: ОбычнаяКоманда", "            Представление: Очистить", ""].join("\n")
);
const singleCmd = renderFormPreview(SINGLE_CMD_FORM);
check(
  "команды поля: одиночная команда без иконки - глиф",
  singleCmd.ok && singleCmd.html.includes('class="fcmd"') && singleCmd.html.includes('class="cph"') && singleCmd.html.includes('title="Очистить"')
);

// --- session restore ---------------------------------------------------------------------

check(
  "restoredTargetUri prefers the state the webview saved",
  restoredTargetUri({ uri: "file:///p/Карточка.yaml" }, "file:///p/Старая.yaml") === "file:///p/Карточка.yaml"
);
check(
  "restoredTargetUri falls back to the remembered target",
  restoredTargetUri(undefined, "file:///p/Карточка.yaml") === "file:///p/Карточка.yaml"
);
check(
  "restoredTargetUri ignores a blank or non-string value",
  restoredTargetUri({ uri: "   " }, 42) === undefined && restoredTargetUri(null, null) === undefined
);

// --- an English form is drawn like the Russian one --------------------------------------
// The platform reads a project written with the English spellings the same way, and the
// designer parses the yaml itself: without the key pairs from the engine the frame came up
// empty on a legal form (found by the owner on demo-en).
const EN_FORM = `
ElementKind: InterfaceComponent
Id: 00000000-0000-4000-8000-000000000009
Name: Card
Inherits:
    Type: Form
    Content:
        Type: Group
        Layout: Vertical
        Content:
            -
                Type: Label
                Name: Hint
                Value: "Fill in the order."
`;

setFormKeyAliases({});
check(
  "английская форма без пар ключей - каркас пуст (прежнее поведение)",
  renderFormPreview(EN_FORM).ok === false
);
setFormKeyAliases(
  { Content: "Содержимое", Type: "Тип", Name: "Имя", Inherits: "Наследует", Value: "Значение" },
  { Group: "Группа", Label: "Надпись", Form: "Форма" },
);
const enResult = renderFormPreview(EN_FORM);
check("английская форма с парами ключей рисуется", enResult.ok === true);
check(
  "содержимое английской формы попадает в каркас",
  enResult.ok === true && enResult.html.includes("Fill in the order.")
);
setFormKeyAliases({});

if (failures > 0) {
  console.error(`итого: ${failures} FAIL`);
  process.exit(1);
}
console.log("итого: все проверки ok");
