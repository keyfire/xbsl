// Tests of the form wireframe rendering (yaml -> HTML) and of the targeted property edits
// that serve the metadata properties panel. Run with plain node (see npm test).

import { collectDataOffsets, nearestOffset, propertyEdit, renderFormPreview, selectionForCursor } from "../src/formPreviewCore";

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

if (failures > 0) {
  console.error(`итого: ${failures} FAIL`);
  process.exit(1);
}
console.log("итого: все проверки ok");
