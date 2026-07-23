// Tests of the form wireframe rendering (yaml -> HTML) and of the targeted property edits
// that serve the metadata properties panel. Run with plain node (see npm test).

import { collectDataOffsets, collectResourceImages, nearestOffset, propertyEdit, renderFormPreview, restoredTargetUri, selectionForCursor } from "../src/formPreviewCore";

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
  check("выравнивание Конец", html.includes("justify-content:flex-end"));
  check("узлы кликабельны (data-off)", html.includes("data-off="));
  check("нет сырых < из значений", !html.includes("Форма<Строка?>"));
  check("node tooltip carries type and name", html.includes('title="ПолеВвода&lt;Строка&gt; · ПолеКод"'));
  check("node tooltip without a name is the bare type", html.includes('title="Надпись"'));
}

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
check("Картинка keeps the placeholder when the resource is not resolved", withoutImg.ok && !withoutImg.html.includes("<img") && withoutImg.html.includes("🖼"));

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

if (failures > 0) {
  console.error(`итого: ${failures} FAIL`);
  process.exit(1);
}
console.log("итого: все проверки ok");
