---
title: "Правила линтера XBSL"
description: "Полный перечень проверок линтера с уровнями важности и областью применения."
sidebar:
  label: Правила
  order: 5
---

<!-- severity icons -->
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"><symbol id="sev-error" viewBox="0 -960 960 960"><path fill="#e5484d" d="M508.5-291.5Q520-303 520-320t-11.5-28.5Q497-360 480-360t-28.5 11.5Q440-337 440-320t11.5 28.5Q463-280 480-280t28.5-11.5Zm0-160Q520-463 520-480v-160q0-17-11.5-28.5T480-680q-17 0-28.5 11.5T440-640v160q0 17 11.5 28.5T480-440q17 0 28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol><symbol id="sev-warning" viewBox="0 -960 960 960"><path fill="#d0a215" d="M109-120q-11 0-20-5.5T75-140q-5-9-5.5-19.5T75-180l370-640q6-10 15.5-15t19.5-5q10 0 19.5 5t15.5 15l370 640q6 10 5.5 20.5T885-140q-5 9-14 14.5t-20 5.5H109Zm69-80h604L480-720 178-200Zm330.5-51.5Q520-263 520-280t-11.5-28.5Q497-320 480-320t-28.5 11.5Q440-297 440-280t11.5 28.5Q463-240 480-240t28.5-11.5Zm0-120Q520-383 520-400v-120q0-17-11.5-28.5T480-560q-17 0-28.5 11.5T440-520v120q0 17 11.5 28.5T480-360q17 0 28.5-11.5ZM480-460Z"/></symbol><symbol id="sev-info" viewBox="0 -960 960 960"><path fill="#3b82f6" d="M508.5-291.5Q520-303 520-320v-160q0-17-11.5-28.5T480-520q-17 0-28.5 11.5T440-480v160q0 17 11.5 28.5T480-280q17 0 28.5-11.5Zm0-320Q520-623 520-640t-11.5-28.5Q497-680 480-680t-28.5 11.5Q440-657 440-640t11.5 28.5Q463-600 480-600t28.5-11.5ZM480-80q-83 0-158-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-158T197-763q54-54 127-85.5T480-880q83 0 158 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 158T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol></svg>


Полный перечень проверок линтера. Файл дополняется при добавлении правил, а действующий
список печатает `xbsl --list-rules` или инструмент MCP `list_rules`. Сейчас правил: 241.

Таблица описывает инструментарий в поставке. Установленный плагин может добавить свои правила
и переопределить severity и включённость по умолчанию (см. [Расширение](/ru/servers#расширение-свои-правила-данные-и-уровни)),
поэтому действующий список способен отличаться от этого. `xbsl --list-rules` показывает, что
действительно работает в вашем окружении, а `XBSL_NO_PLUGINS=1` – набор ниже.

## Граница: линтер дополняет компилятор, но не заменяет его

Линтер работает по тексту, AST и модели проекта. Правила знают типы "на первом шаге":
объявленный номинальный тип переменной и его члены, объекты проекта и порождаемые ими типы,
значения перечислений, глобальные типы подключённых библиотек (из архива `.xlib`).

Вывод типа выражения у движка есть. Модуль `xbsl.typeinfer` отвечает про получателя, член,
конструктор, приведение и настойчивую операцию, а вывод типов цепочек и локальных переменных
питает подсказку при наведении и автодополнение в редакторе. По всему проекту он отвечает
множеством типов, в котором остаются объединение, `Неопределено` и `Null` колонки запроса, и знает
имена самого проекта: строки `Запрос{...}` типизируются по списку выборки, реквизиты – по yaml,
структуры и методы – по модулям. Пять правил судят выведенный тип и повторяют предупреждения
IDE платформы: `code/redundant-cast`, `code/cast-to-non-null`, `code/redundant-undefined-guard` и
`code/redundant-type-check`, а также `code/deprecated-api` при выборе перегрузки. О выражении, тип которого вывод не называет, они молчат. Остальные
правила судят по объявленным типам.

Часть находок поймал бы и компилятор: неизвестный тип, число аргументов, не-исключение в
`поймать`, возврат не по сигнатуре. Ценность линтера здесь во времени. Он показывает это
**раньше** – за секунды на рабочей машине, до сборки и деплоя, – и называет точное место.
Остального компилятор не проверяет вовсе: соглашения по написанию кода, типографику, структуру
проекта (дубли `Ид`, парность файлов), секреты в исходниках. О неиспользуемых переменных и
импортах IDE платформы только предупреждает, и сборка с ними проходит.

Чего линтер не делает – всё, что требует полного вывода типов выражений: утечку ресурса в общем
случае, соответствие типа возвращаемого значения сигнатуре. Их стоит различать. Структурное
несоответствие возврата (значение в методе-ничто, пустой `возврат` в типизированном) правило
`code/return-mismatch` ловит, а `возврат` строки из метода с `: Число` пропустит – для этого нужно
вывести тип выражения. Ресурс же судится единственной формой, где всё сказано самим объявлением:
правило `code/unclosed-resource` прослеживает закрываемое от объявления до перебора в том же
методе, а ресурс, ушедший в вызовы или коллекции, остаётся вне досягаемости.

Корректность кода проверяет серверная компиляция при деплое. Линтер идёт перед ней и снимает
частые ошибки заранее.

## Как читать таблицу

- **Правило** – идентификатор `группа/имя`. Группа (часть до `/`) позволяет включать и
  выключать правила пачкой.
- **Уровень** – <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> `error` (сборка и CI должны падать), <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> `warning` (нарушено соглашение),
  <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> `info` (подсказка, обычно выключена).
- **Умолч.** – ✓ правило входит в набор по умолчанию, – включается явно.
- **Область** – `файл` (правило видит один файл) или `проект` (нужен индекс всего проекта:
  дубли Ид, неизвестные типы, кросс-модульные вызовы).
- **Что проверяет** – одно-два предложения о находке. Ссылка "подробнее" ведёт под таблицу
  тира: там у правила лежат оговорки, примеры и ответ платформы.
- **Ссылка в конце описания** – раздел документации платформы, стоящий за правилом. В VS Code
  код такого правила в панели "Проблемы" открывает этот раздел прямо в редакторе.

## Тиры

Правила разбиты на тиры A–D по тому, на что они опираются. Тир – это и есть быстрый фильтр
для `--select`/`--ignore` (наряду с группой и идентификатором): `--select A,B` гоняет только
структуру и текст, `--ignore D` убирает семантику над stdlib.

**Как читать колонки:** <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> error · <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> warning · <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> info; ✓ – входит в набор по умолчанию, – включается явно; область – один файл или весь проект.

### Тир A – структура и YAML

Файл существует, парсится, у объекта есть уникальный UUID, имя совпадает с файлом.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `yaml/valid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | YAML не парсится |
| `yaml/duplicate-key` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Скалярный ключ задан в одном узле YAML дважды: загрузчик молча оставляет последнее значение, а компилятор отклоняет файл при деплое [подробнее](#a-yaml-duplicate-key) |
| `yaml/duplicate-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Пространство имён повторяется в секции `Импорт` элемента: вторая строка ничего не добавляет [подробнее](#a-yaml-duplicate-import) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/id-uuid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ид не является UUID |
| `yaml/id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | У объекта нет Ид |
| `yaml/name-matches-file` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя не совпадает с именем файла |
| `yaml/id-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Дубли Ид в проекте |
| `yaml/standard-field-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Длина стандартного реквизита сверх лимита платформы (`Наименование` > 400, `Код` > 50) – применение отвергает реквизит, и он выпадает из объекта [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ссылочный тип в позиции `Тип` без `?`: у ссылки нет значения по умолчанию, и компиляция падает [подробнее](#a-yaml-ref-needs-nullable) [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Выражение `=...` внутри узла литерального типа (`Шрифт: {Тип: АбсолютныйШрифт, Размер: =...}`) – платформа принимает здесь только литерал, вычислять нужно весь объект [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `yaml/localization-key-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ объявлен в словаре `ЛокализованныеСтроки` дважды: применение отвергает проект целиком [подробнее](#a-yaml-localization-key-unique) [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/unused-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Компонент интерфейса нигде не размещён и не создан: ни значением `Тип` в разметке, ни `новый` в коде. Мёртвая разметка едет в сборку и в перевод [подробнее](#a-yaml-unused-component) |
| `yaml/duplicate-subtree` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Поддерево разметки повторяет устройство поддерева в другом файле: новую форму завели копированием соседней, и правку теперь вносить в оба [подробнее](#a-yaml-duplicate-subtree) |
| `project/identifier` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя или поставщик проекта не идентификатор [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Представление проекта не заполнено [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Версия проекта не A.B.C [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Модуль .xbsl без парного .yaml |
| `project/path-matches-descriptor` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Путь `{{поставщик}}/{{имя}}` разошёлся с дескриптором – сборка отвергнет проект до компиляции [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ разметки, которого у компонента нет, а у другого компонента ui-схемы есть: применение отвечает `Неизвестное свойство` [подробнее](#a-yaml-unknown-component-property) [доки](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |
| `yaml/inline-command-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `Имя` у команды, объявленной прямо в разметке: применение отвергает узел и откатывает проект [подробнее](#a-yaml-inline-command-name) [доки](https://1cmycloud.com/docs/help/topics/command-interface-fragment/) |
| `yaml/list-scroll-without-loading` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Список с прокруткой по вертикали, у которого `Навигация: Отсутствует`: строки берутся одной порцией, и хвост данных прокруткой недостижим [подробнее](#a-yaml-list-scroll-without-loading) [доки](https://1cmycloud.com/docs/help/topics/custom-list-component/) |
| `yaml/plain-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Комментарий `#` в описании элемента: визуальный редактор пишет файл заново из модели и сохраняет только документирующий комментарий `##` в первых строках узла, у которого он есть (элемент, компонент, объявленное свойство, табличная часть и подобные). Автоисправление меняет маркер у блока, который уже стоит на таком месте, и переносит внутрь узла блок, стоящий перед `-` элемента списка (кроме экземпляра компонента проекта в списке: на нём комментарий ломает сборку); остальное называется вместе с ближайшим узлом, у которого комментарий есть |
| `yaml/doc-comment-misplaced` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Блок `##` стоит там, где среда разработки его не читает: перед `-` элемента списка, над отдельным свойством, у узла без документирующего комментария (стандартный реквизит вроде `Код` и `Наименование`, команда, поле динамического списка). Он пропадёт так же, как комментарий `#`. Отдельный случай – экземпляр компонента проекта или библиотеки в списке: с блоком `##` на таком узле сервер не применяет проект, и правило называет эту причину |

#### Подробнее о правилах тира A

<a id="a-yaml-duplicate-key"></a>**`yaml/duplicate-key`.** Проверки схемы читают уже слитый
документ, поэтому потерянное значение больше нигде не всплывает. Помечается второе вхождение и
каждое следующее, со строкой первого. Ключ слияния `<<` и нескалярные ключи правило не судит, а
ключи различает так же, как загрузчик: по тегу и по тексту.

<a id="a-yaml-duplicate-import"></a>**`yaml/duplicate-import`.** Короткое и полное имя своего
проекта – это одно пространство имён, поэтому пара из них тоже считается повтором. IDE платформы
секцию `Импорт` не проверяет. Исправление снимает лишнюю строку.

<a id="a-yaml-ref-needs-nullable"></a>**`yaml/ref-needs-nullable`.** Так пишут и отдельный
реквизит, и параметр типа компонента: `Товары.Ссылка`, `ПолеВвода<Товары.Ссылка>`. Компиляция
отвечает `Default value initialization is not supported`.

<a id="a-yaml-localization-key-unique"></a>**`yaml/localization-key-unique`.** У секций `Строки` и
`Шаблоны` одно пространство имён, и файл перевода судится наравне со словарём. Применение отвечает
"Имя не уникально" и откатывает проект.

<a id="a-yaml-unused-component"></a>**`yaml/unused-component`.** `code/unused-method` такой
компонент не видит: его методы зовёт его же yaml. Употреблением считается значение в yaml или
любое слово модуля, а имя, стоящее ключом словаря локализации, не в счёт. Yaml, который не
разобрался, засчитывается всеми своими словами, словарь перевода не засчитывается вовсе. Точку
входа и `ОбластьВидимости: Глобально` правило не судит: это публичная поверхность библиотеки. Без
файла-дескриптора проекта среди проверяемых правило молчит, иначе компонент, размещённый снаружи
проверяемого подмножества, выглядел бы мёртвым.

<a id="a-yaml-duplicate-subtree"></a>**`yaml/duplicate-subtree`.** В слепок поддерева не входят
имена, идентификаторы и тексты. Порог в 40 узлов выведен замером: ниже правило ловит раскладку, а
не копии. Повтор внутри одного файла, источник данных списка и словарь локализованных строк
правило не судит, а называет только максимальные группы. По умолчанию выключено: меру одинаковости
выбирает проект.

<a id="a-yaml-unknown-component-property"></a>**`yaml/unknown-component-property`.** Пример:
`ЗамещающийТекст` у `Флажка`, это свойство `ПолеВвода`. Имя, которого нет ни у одного компонента,
правило не трогает: документация перечисляет ключи yaml не полностью.

<a id="a-yaml-inline-command-name"></a>**`yaml/inline-command-name`.** Так выглядит и инлайновый
фрагмент командного интерфейса, и команда-свойство. Применение отвечает: "Имя команды разрешено
задавать только в элементах проекта типа фрагмент командного интерфейса". К команде обращаются
через параметр обработчика, а имя ей даёт только фрагмент, вынесенный отдельным элементом проекта.

<a id="a-yaml-list-scroll-without-loading"></a>**`yaml/list-scroll-without-loading`.** Порцию
задаёт `РазмерСтраницы`, и прокрутка крутит только её: запись находится поиском списка, но не
прокруткой. Лечит `Навигация: ПодгрузкаПриПрокрутке`. Список, который прокрутку не обещает, и
выражение в `Навигации` правило не судит.

### Тир B – текст и соглашения

Кодировка, переводы строк, пробелы, типографика (тире, кавычки, многоточие, знаки не с клавиатуры),
слог комментариев, английский текст словаря перевода, длина строки, секреты в исходниках.

Типографика читает и файлы ресурсов проекта – `.css`, `.js`, `.svg` и `.html` из каталога
`Ресурсы`. Подсистема отдаёт их браузеру как есть, поэтому проза оттуда доходит до читателя
так же, как проза модуля. Судятся комментарии всех четырёх форматов и текст, который
пользователь видит на экране: `<title>`, `<desc>` и `<text>` в SVG, текстовые узлы
HTML-страницы. Код не трогаем – селекторы, идентификаторы, имена тегов и атрибутов, значения
атрибутов, строковые литералы скрипта и стилей. Комментарии этих файлов читает и группа `comment/`.
Остальные правила тира смотрят только модуль и описание элемента; файлы словаря перевода читают
`translation/english-shape`, `comment/first-person` и `comment/emphasis-caps`.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `security/hardcoded-secret` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ или пароль литералом в коде |
| `typography/em-dash` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Длинное тире в комментарии – модуля или файла ресурсов – и в тексте страницы; пишется среднее тире |
| `typography/ellipsis` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Символ многоточия там, где нужны три точки: комментарий, текст SVG или HTML-страницы |
| `typography/curly-quotes` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Кудрявые кавычки везде, где попадутся: комментарий, строковый литерал модуля, текст страницы |
| `typography/guillemets-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Ёлочки в комментарии, в файле ресурсов тоже; в тексте на экране они уместны и не судятся |
| `typography/yo-in-text` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Буква "ё" в тексте, который читает пользователь: подпись, запись словаря локализованных строк, текст SVG или HTML-страницы |
| `typography/non-keyboard` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Знак не с клавиатуры в комментарии: стрелка, знак сравнения или умножения; исправление пишет `->`, `>=`, `<>`, `x` и подобное, валютный знак – данные и не судится |
| `typography/en-dash-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Среднее тире в комментарии – для проекта, который пишет в комментариях кода дефис; исправление ставит дефис |
| `comment/doc-marker` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Блок `//` прямо над объявлением (метод, структура, поле, элемент перечисления, константа модуля): среда разработки узнаёт документирующий комментарий только по маркеру `///` и только такой текст показывает в подсказке при наведении, в подсказке сигнатуры и в автодополнении. Автоисправление меняет маркер; о блоке `/* ... */` на этом месте правило сообщает без исправления |
| `comment/subjunctive` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Частица "бы" в комментарии; замечание просит слово условия, потому что без частицы предположение читается утверждением. Уступительные обороты не судятся |
| `comment/first-person` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Первое лицо в комментарии: местоимение "мы", "наш" или глагол вроде "проверяем", а в английской строке комментария из словаря перевода – "we", "our", "I"; комментарий безличен |
| `comment/emphasis-caps` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Слово прописными ради ударения в комментарии: "НЕ", "ТОЛЬКО", приставка "НЕзаполненным". Ударение набирают словами, а не регистром [подробнее](#b-comment-emphasis-caps) |
| `comment/dash-condition` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | файл | Условие в комментарии написано через тире ("склад не задан - берется основной") вместо слова "если" [подробнее](#b-comment-dash-condition) |
| `translation/english-shape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | След механической замены в английском значении словаря перевода: окончание, приклеенное к слову, которое его не принимает (`onlies`) [подробнее](#b-translation-english-shape) |
| `whitespace/trailing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Хвостовые пробелы |
| `whitespace/mixed-newline` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Смешанные переводы строк |
| `encoding/utf8` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Файл не в UTF-8 |
| `style/tab-indent` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Табуляция в отступе [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Строка длиннее 120 символов [доки](https://1cmycloud.com/docs/help/topics/general-design/) |

#### Подробнее о правилах тира B

<a id="b-comment-emphasis-caps"></a>**`comment/emphasis-caps`.** Правило судит служебное слово,
любое другое слово, которое тот же файл пишет и строчными, однобуквенное слово посреди фразы ("В
котором"), приклеенную приставку и прописные английской строки комментария в словаре перевода.
Аббревиатуры, маски дат и цитату запроса правило не судит. Исправление возвращает регистр.

<a id="b-comment-dash-condition"></a>**`comment/dash-condition`.** Замечание предлагает
формулировку со словом условия. Пояснение к значению правило не судит: там перед состоянием ничего
не названо либо после тире нет глагола.

<a id="b-translation-english-shape"></a>**`translation/english-shape`.** Правило ловит ещё
страдательный залог с именной группой сразу за ним ("is shadowed the parameter") и прописные,
которых нет в русском ключе. Судятся только файлы `xbsl-translation`.

### Тир C – структура кода, базовый синтаксис и соглашения по написанию

Баланс блоков и скобок, заголовки циклов и методов, локальные переменные и группа `style/` –
соглашения из раздела документации "Рекомендации по написанию кода". Все правила `style/`
включены по умолчанию и идут как `warning`.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `code/parse-error` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Синтаксическая ошибка (полный разбор по грамматике платформы) [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Оператор-выражение, который не является вызовом метода или выбросом исключения: ошибка сборки, даже если внутри есть вызов |
| `code/return-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Возврат не по сигнатуре метода (значение в методе-ничто, пустой `возврат` в типизированном) – компилятор такой код отвергает [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/self-assignment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Значение присваивается туда же, откуда читается: `Х = Х`, `этот.Поле = этот.Поле`, `Х -= Х`. Компилятор это отвергает, и сборка откатывается [подробнее](#c-code-self-assignment) |
| `code/assign-target` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Левая часть присваивания не может принять значение – вызов метода, приведение, сам `этот` или цепочка через безопасный доступ `?.`; компилятор такое присваивание отвергает [доки](https://1cmycloud.com/docs/help/topics/assignment-statement/) |
| `code/assign-readonly` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Присваивание имени, доступному только для чтения: переменной `знч` или `исп`, переменной цикла или `поймать`, константе модуля. Компилятор его отвергает [подробнее](#c-code-assign-readonly) [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unreachable-statement` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Код, до которого выполнение не доходит: после `возврат`, `выбросить`, `прервать` или `продолжить`. Компилятор его отвергает [подробнее](#c-code-unreachable-statement) |
| `code/misplaced-jump` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `прервать` или `продолжить` вне цикла, а также `возврат`, `прервать`, `продолжить` в секции `вконце`; компилятор такой переход отвергает [доки](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/call-arity` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Локальный вызов не соответствует установленной сигнатуре: число аргументов, неизвестное или повторное имя, позиционный аргумент после именованного либо пропущенный обязательный параметр [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Дисбаланс скобок () [] {} |
| `code/blocks` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Дисбаланс блоков и ';' [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Тернарный оператор сразу после `это Тип` справа от `и` или `или`: он принадлежит проверке типа, и строка компилируется не так, как читается [подробнее](#c-code-ternary-and-or) [доки](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/query-in-loop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Запрос внутри цикла |
| `code/param-type-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Параметр без типа и без значения по умолчанию [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/duplicate-annotation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Повторная аннотация у объявления, точный повтор имени без аргументов: компилятор такой модуль отвергает [подробнее](#c-code-duplicate-annotation) [доки](https://1cmycloud.com/docs/help/topics/annotations/) |
| `code/duplicate-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль ещё раз импортирует пространство имён: вторая строка ничего не добавляет [подробнее](#c-code-duplicate-import) [доки](https://1cmycloud.com/docs/help/topics/import-statement/) |
| `code/module-var-not-const` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Объявление `пер` / `знч` / `исп` на уровне модуля – там живёт только константа, выражение вне тела метода компилятор отвергает, и применение откатывает проект [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/param-redeclared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Объявление `знч`, `пер` или `исп` в теле метода с именем его же параметра: метод вместе с параметрами это одна область видимости, и применение откатывает проект [подробнее](#c-code-param-redeclared) [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `code/lambda-changes-outer-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Тело лямбды присваивает захваченной локальной переменной или параметру метода: компилятор отвергает проект целиком [подробнее](#c-code-lambda-changes-outer-local) [доки](https://1cmycloud.com/docs/help/topics/lambda-expression/) |
| `code/loop-header` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Неверный заголовок цикла 'для' [доки](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Недопустимая управляющая последовательность в строковом литерале (`\'`, регексные `\d`) – компилятор отвергает такой литерал; валидны `\н \в \т \\ \" \% \$ \ю<код>` и латинские написания [доки](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/dead-interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Удвоенный знак интерполяции перед скобкой: платформа читает пару как экранированный знак, и выражение не вычисляется [подробнее](#c-code-dead-interpolation) [доки](https://1cmycloud.com/docs/help/topics/string-interpolation/) |
| `code/unused-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Переменная `знч`, `пер` или `исп`, которую метод не читает или которой только присваивает: имя занимает место и сбивает при чтении [подробнее](#c-code-unused-local) |
| `code/unused-loop-var` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Переменная цикла `для Х из`, которую тело цикла не читает; счётчик `для Х = А по Б` не проверяется, как и в IDE платформы |
| `code/ref-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле-ссылка структуры без 'обз' [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Сравнение булева значения с Истина/Ложь [доки](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/boolean-ternary` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Тернарный оператор с ветвями `Истина` и `Ложь`: он равен своему условию или его отрицанию, и IDE платформы об этом предупреждает [подробнее](#c-style-boolean-ternary) [доки](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `style/undefined-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Проверка Неопределено оператором 'это' [доки](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| `style/negated-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Отрицание оператора 'это' снаружи [доки](https://1cmycloud.com/docs/help/topics/is-operator/) |
| `style/semicolon-line` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | ';' не на отдельной строке [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/wrap-operator` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Операция в конце перенесённой строки [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/wrap-comma` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Запятая в начале перенесённой строки [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/camel-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя не в UpperCamelCase [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/const-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Константа не БОЛЬШИМИ_БУКВАМИ [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/exception-prefix` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя исключения без пометки: у русского имени это префикс "Исключение", у латинского – суффикс Exception [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/abbreviation-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Аббревиатура заглавными буквами в имени [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/enum-name-vid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя перечисления начинается с "Тип" [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/collection-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Ручное наполнение коллекции вместо литерала [доки](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| `style/constructor-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Конструктор типа, у которого есть литерал, вызван с одними постоянными аргументами: IDE платформы об этом предупреждает [подробнее](#c-style-constructor-literal) [доки](https://1cmycloud.com/docs/help/topics/literals/) |
| `style/redundant-tostring` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | '.ВСтроку()' в конкатенации [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Конкатенация вместо интерполяции [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пробелы вокруг двоеточия типа [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пробелы вокруг '\|' в составном типе [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Неопределено в типе без сокращения '?' [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Избыточная аннотация типа при инициализации [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-scope` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `область` – единственная инструкция своего блока: она кончается там же, где блок, и ничего не ограничивает [подробнее](#c-style-redundant-scope) [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/optional-params-last` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Необязательный параметр перед обязательным [доки](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `Ресурс{Ресурсы/Имя.svg}` – ключ ресурса задается относительно каталога Ресурсы; сам каталог в ключе ломает поиск [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Именованный параметр `&Имя` внутри литерала запроса – значения в литерал передаются интерполяцией (`%Имя`) [доки](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключевое слово `этот` в теле статического метода – статический метод общий для всего типа и контекста объекта не имеет, проект компилятор отвергает [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Вызов обычного метода того же владельца по голому имени из статического метода – документация запрещает это прямо; вызывайте метод у значения либо сделайте его статическим [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `Закрыть()` внутри `ПередЗакрытием` – платформа игнорирует вызов, и форму не закрывает уже ничто |
| `query/no-isnull` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `ЕСТЬNULL(` внутри литерала запроса – такой функции в языке запросов нет |
| `style/abstract-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Абстрактное имя переменной (`Данные`, `Элемент`, `Значение`) не говорит о ней ничего [подробнее](#c-style-abstract-name) [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Однобуквенное имя переменной, параметра или переменной цикла – по стандарту имён односимвольными бывают только параметры коротких лямбда-выражений (`(А, Б) -> А + Б`) [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Булева переменная названа от отрицания (`НеПодключен`, `НетОшибок`): имя образуют от истинного значения признака [подробнее](#c-style-negated-boolean-name) [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя переменной начинается с типа-контейнера (`МассивСтруктурИмен`, `СтруктураОтвета`) – тип виден по объявлению и подсказке редактора, в имя его не включают [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Числительное в имени константы (`ТАЙМАУТ_ОДНА_МИНУТА`) описывает её значение – константу называют абстрактно (`ТАЙМАУТ`), чтобы смена значения не ломала имя [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `code/required-field-default` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле структуры или исключения с `обз` имеет значение по умолчанию, которое компилятор отвергает. Исправление удаляет инициализатор, только если остаётся явно указанный тип. |
| `code/declaration-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Локальная переменная или необязательное поле составного типа без пустого варианта не имеет инициализатора; константа модуля (`конст`) или переменная `исп` объявлена без значения. |
| `code/return-use-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Оператор `возврат` передаёт ресурс `исп`, который закрывается при выходе из области видимости, в том числе через приведение типа, выбор непустого значения и условное выражение. |
| `code/duplicate-when` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ветвь `когда` оператора `выбор` повторяет литерал, элемент перечисления своего файла или явно указанный тип, обработанный выше. |
| `code/duplicate-catch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Один тип исключения повторяется в секциях `поймать` одного оператора `попытка`. |
| `code/duplicate-declaration` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Имя объявлено повторно там, где регистр не учитывается, либо у перечисления несколько элементов `умолчание`; перегрузки с одинаковым написанием и локальные имена соседних областей допустимы. |
| `code/captured-local-write` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Изменяемая локальная переменная или параметр именованного метода получает присваивание после захвата лямбдой: лямбда увидит уже не то значение [подробнее](#c-code-captured-local-write) [доки](https://1cmycloud.com/docs/help/topics/lambda-expression/) |

#### Подробнее о правилах тира C

<a id="c-code-self-assignment"></a>**`code/self-assignment`.** Составная форма судится, только
когда файл называет тип операнда: строка, сложенная сама с собой, компилируется законно. Простую
форму снимает исправление.

<a id="c-code-assign-readonly"></a>**`code/assign-readonly`.** Правило судит и `знч`-поле
структуры, в том числе через параметр или локальную переменную, тип которой объявлен в том же
файле структурой или исключением. У локальной переменной исправление меняет `знч` на `пер`.

<a id="c-code-unreachable-statement"></a>**`code/unreachable-statement`.** Выходом считается ещё
вызов метода `никогда` своего файла и ветвление, у которого выходят все ветви. `выбор` по всем
элементам перечисления этого файла тоже считается.

<a id="c-code-ternary-and-or"></a>**`code/ternary-and-or`.** `А и Х это Строка ? 1 : 0` читается
как `А и (Х это Строка ? 1 : 0)` и не компилируется, пока обе ветви не булевы. Обычное `А и Б ? 1
: 0` берёт условие целиком, и его правило не судит. Исправление берёт условие в скобки.

<a id="c-code-duplicate-annotation"></a>**`code/duplicate-annotation`.** Аннотации копятся до
ближайшего объявления, и комментарий между ними их не разделяет.

<a id="c-code-duplicate-import"></a>**`code/duplicate-import`.** Короткое и полное имя своего
проекта – это одно пространство имён, а регистр букв имена различает. IDE платформы предупреждает
о каждом повторе после первого. Исправление снимает повторную строку.

<a id="c-code-param-redeclared"></a>**`code/param-redeclared`.** В ту же область входят и
вложенные блоки: цикл, ветка, `попытка`. Компилятор отвечает "Переменная с именем X уже
определена". Переменные цикла и `поймать`, параметры лямбд и тела полных лямбд правило не судит.

<a id="c-code-lambda-changes-outer-local"></a>**`code/lambda-changes-outer-local`.** Судится `пер`
или параметр метода либо внешней лямбды, операторы `=`, `+=`, `-=`, `*=` и `/=`, краткая и полная
лямбда на любой глубине. Член и элемент захваченного значения менять можно. `знч`, `исп`,
переменные цикла и `поймать` доступны только для чтения, и компилятор отвечает на них другой
ошибкой.

<a id="c-code-dead-interpolation"></a>**`code/dead-interpolation`.** Так выглядят `%%{...}` и
`$${...}`, и в значение уходит текст выражения. Экранируйте первый знак (`\%%{...}`) или соберите
строку конкатенацией.

<a id="c-code-unused-local"></a>**`code/unused-local`.** Имена разрешаются по блочным областям,
как в IDE платформы. Исправление снимает имя неиспользуемой переменной `исп`, и ресурс всё равно
закрывается в конце области видимости.

<a id="c-style-boolean-ternary"></a>**`style/boolean-ternary`.** Правило судит модуль,
интерполяцию строки и привязку yaml. Исправление записывает условие или отрицание так, как
платформа связывает `не`.

<a id="c-style-constructor-literal"></a>**`style/constructor-literal`.** Пример: `новый
Дата("9999-12-31")`. Так же судится `НайтиТип` с постоянным именем. Исправление ставит литерал
там, где он хранит то же значение.

<a id="c-style-redundant-scope"></a>**`style/redundant-scope`.** IDE платформы об этом
предупреждает. Исправление снимает область и сдвигает её тело на отступ влево.

<a id="c-style-abstract-name"></a>**`style/abstract-name`.** Судится точное имя и имя с числовым
хвостом (`Данные1`). Перечень: `Данные`, `Элемент`, `Объект`, `Строка`, `Значение`, `Документ`.
Основу внутри длинного имени (`ДанныеКлиента`) и поля структур правило не трогает: поле структуры
это контракт сериализации.

<a id="c-style-negated-boolean-name"></a>**`style/negated-boolean-name`.** Так было бы `Подключен`
и `ЕстьОшибки`. Судится только доказанное Булево: аннотация типа или булев литерал в
инициализации.


<a id="c-code-captured-local-write"></a>**`code/captured-local-write`.** Правило судит и запись
перед захватом в цикле, который повторно использует ту же переменную. Запись до захвата, новая
локальная переменная каждой итерации и изменение членов или элементов значения остаются
допустимыми. Автоматической правки нет.
### Тир D – семантика над stdlib, формы и метамодель

Требует индекс проекта и данные платформы: неизвестные типы и объекты, значения перечислений,
модель выполнения (клиент/сервер), обработчики форм, свойства и запросы.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | ВыборЗначения без статичного СпискаВыбора [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `yaml/slot-needs-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Слот, описанный в ui-схеме типом `Массив<...>`, получил один компонент вместо списка: применение сборки отвергает такую разметку, а линт до сих пор молчал [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Groups/Group_ru/) |
| `yaml/value-choice-title` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | У `ВыборЗначения` с явным `ВидОтображенияПереключателя: Переключатель` задан `Заголовок`: платформа его не рисует, и поле остаётся без подписи [подробнее](#d-yaml-value-choice-title) |
| `code/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип |
| `code/catch-non-exception` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Тип в `поймать` не исключение (stdlib-тип без сигнатуры исключения или локальная `структура`) – компилятор такой код отвергает [доки](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Обращение к отсутствующему члену переменной известного stdlib-типа – простого или дженерика, у которого аргументы типизируют члены, но не называют их (первый шаг цепочки, у опечаток подсказка) |
| `code/member-kind-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Метод стандартной библиотеки прочитан как свойство (или наоборот) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/unknown-static-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение по имени типа к члену, которого у типа нет (`ДатаВремя.Минимальная()`): такой вызов не скомпилируется [подробнее](#d-code-unknown-static-member) |
| `yaml/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Ссылка из yaml на элемент чужой подсистемы, у которого `ОбластьВидимости` не `ВПроекте` и не `Глобально`: снаружи своей подсистемы он недоступен, и импорт не поможет [подробнее](#d-yaml-foreign-not-public) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Модуль или запрос называет элемент чужой подсистемы, у которого `ОбластьВидимости` не `ВПроекте` и не `Глобально`: компилятор отвергает обращение на этой строке [подробнее](#d-code-foreign-not-public) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Вызов модуля не соответствует установленной сигнатуре по числу или связыванию именованных аргументов; неоднозначные перегрузки и затененные имена модулей не проверяются [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/missing-return` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Метод с результатом имеет установленный путь до конца без `возврат`: по этому пути метод не вернёт ничего [подробнее](#d-code-missing-return) [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/unused-return-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Отдельный оператор отбрасывает результат платформенного метода с аннотацией `@ПроверятьИспользованиеЗначения`: работа метода пропадает впустую [подробнее](#d-code-unused-return-value) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Annotations/Checks/CheckValueUsage_ru/) |
| `code/ambiguous-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Короткое имя типа в коде относится сразу к нескольким видимым пространствам имён проекта [подробнее](#d-code-ambiguous-type) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/ambiguous-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Короткое имя типа в YAML относится к нескольким видимым пространствам имён проекта. Имена корня и пакетов имеют равный приоритет; укажите пространство имён типа явно [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/undefined-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Неизвестное имя в выражении (опечатки вида `Адресар` вместо `Адреса`) и в короткой интерполяции строки (`"?$format=json"` – подстановка имени `format`, нужен `\$`) – компилятор такой код отвергает |
| `code/unknown-object-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип объекта проекта |
| `yaml/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип в yaml |
| `yaml/dynlist-missing-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Нет поля динамического списка [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-row-editing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Обработчик `ПриРедактированииСтроки` у списка с плоским динамическим источником: платформа его не вызывает вовсе [подробнее](#d-yaml-dynlist-row-editing) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Lists/List_ru/) |
| `yaml/dynlist-joined-table-param` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Параметр (`&Имя`) или биндинг (`=...`) в аргументах либо фильтре присоединённой таблицы динамического списка: он не вычисляется, и список отказывает уже при работе [подробнее](#d-yaml-dynlist-joined-table-param) [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-filter-disabled` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Отбор динамического списка объявлен с `Использовать: Ложь`, а парный модуль включает его присваиванием: первый кадр покажет всю таблицу [подробнее](#d-yaml-dynlist-filter-disabled) [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/list-form-needs-dynlist` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Форма наследует `ФормаСписка`, а таблица в её содержимом взята по `ИсточникДанныхМассив`: пункт навигации молча исчезает [подробнее](#d-yaml-list-form-needs-dynlist) [доки](https://1cmycloud.com/docs/help/topics/list-form-component/) |
| `yaml/ref-input-auto-commands` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Ссылочное `ПолеВвода` без своего узла `Команды`: платформа рисует рядом собственную кнопку, которая открывает значение в отдельном окне [подробнее](#d-yaml-ref-input-auto-commands) [доки](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/toggle-command-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Две соседние `ОбычныеКоманды` с зеркальной `Видимость` (`=X` и `=не X`) изображают одну команду с двумя состояниями, которая у платформы уже есть [подробнее](#d-yaml-toggle-command-pair) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Commands/SwitchableCommand_ru/) |
| `yaml/dynlist-column-sort-lost` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Колонка таблицы над динамическим списком, чьё значение это вызов: платформа сортирует по полю источника, и заголовок такой колонки сортировать не будет [подробнее](#d-yaml-dynlist-column-sort-lost) [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/badge-column-image` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | У `СтандартнаяКолонкаТаблицы` с `Вид: Значок` задано `Изображение`: платформа картинку не показывает [подробнее](#d-yaml-badge-column-image) [доки](https://1cmycloud.com/docs/help/topics/standard-table-column-component/) |
| `code/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестное значение перечисления [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Перечисление в позиции `Тип` без `?`: значения по умолчанию у него нет, и серверная компиляция падает [подробнее](#d-yaml-enum-needs-nullable) [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-default-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | `ЗначениеПоУмолчанию` поля-перечисления пишется голым именем объявленного значения: запись с именем типа (`ВидимостьМетки.Невидимая`) или несуществующее имя сборка отвергает [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Значение свойства компонента вне списка перечисления ui-схемы (`ВыравниваниеСодержимогоПоВертикали: Конец` – по вертикали значения `Конец` нет) |
| `yaml/bare-object-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Голое слово в свойстве, принимающем `Объект` (`Значение: Титул`) – платформа ждёт литерал в кавычках, выражение с `=` либо `$`-ссылку локализованной строки [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Имени из `Ресурс{...}` нет ни в каталогах `Ресурсы` проекта, ни в библиотеке картинок платформы [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Обработчик формы не найден в модуле [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| `form/handler-signature` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Сигнатура обработчика не совпадает с событием [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/unknown-form-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Обращение к компоненту, которого нет в разметке формы [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Серверный метод недоступен клиентскому обработчику [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/image-binding-server-call` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | ✓ | проект | Свойство `Изображение` компонента платформы обращается к серверу напрямую или через клиентские методы [подробнее](#d-code-image-binding-server-call) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/computed-property-server-call` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | проект | Вычисляемые свойства обращаются к доступному с клиента серверному методу без штатного кеша результата [подробнее](/ru/linting#серверные-вызовы-из-вычисляемых-свойств) [доки](https://1cmycloud.com/docs/help/topics/calculated-property-values-for-ui-components/) |
| `code/resource-read-without-cache` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | ✓ | проект | Доступный с клиента метод исполняется на сервере и только возвращает текст ресурса, прочитанный без штатного кеша результата [подробнее](/ru/linting#чтение-ресурса-без-кеша-результата) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Annotations/Environments/AvailableFromClient_ru/) |
| `code/client-annotation-in-server-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Клиентская аннотация в серверном общем модуле [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Клиентский общий модуль в серверном окружении [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-annotation-in-client-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Серверная аннотация в клиентском общем модуле [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Блок `Запрос{...}` в методе клиентского модуля без `@НаСервере`: на клиенте такого типа нет, и компилятор отвергает сборку [подробнее](#d-code-query-needs-server) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/local-method-cross-component` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Кросс-компонентный вызов локального метода [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/local-method-cross-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Межмодульный вызов локального метода [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `naming/yo` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Буква "ё" в имени [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/underscore` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Подчёркивание в имени [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/abbreviation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Аббревиатура заглавными буквами в имени [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/latin-term` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Англоязычный термин записан русскими буквами [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/enum-vid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя перечисления со словом "Тип" [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/kind-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Вид элемента в его имени [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/filler-word` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Слово-пустышка в имени [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/module-suffix` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Постфикс окружения в имени общего модуля [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/number` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Число имени не по виду элемента [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя булева реквизита [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Представление элемента [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/prefix-by-kind` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя вида без обязательного префикса [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `code/unknown-ns-object` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный объект в пространстве имён вида |
| `query/unknown-table` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестная таблица в запросе [доки](https://1cmycloud.com/docs/help/topics/select-from/) |
| `query/in-subquery-composite` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | 'В' с подзапросом по составному типу [доки](https://1cmycloud.com/docs/help/topics/in-expression/) |
| `yaml/unknown-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Неизвестное свойство объекта |
| `code/reserved-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Зарезервированное имя: `Тип`, `type` или `Type` полем структуры или параметром. Применение на сервере отвергает все три [подробнее](#d-code-reserved-name) |
| `yaml/builtin-property-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Совпадение со встроенным свойством |
| `yaml/property-shadows-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Свойство компонента названо как общий модуль: имя перекрывает модуль во всём компоненте, `Модуль.Метод()` читается как член значения свойства, и применение падает [подробнее](#d-yaml-property-shadows-module) [доки](https://1cmycloud.com/docs/help/topics/addressing-module/) |
| `yaml/size-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Размер без отключения растягивания [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/col-width-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Числовая `Ширина` колонки таблицы без `РастягиватьПоГоризонтали`: при растягивании число работает как доля свободного места, а не как пиксели [подробнее](#d-yaml-col-width-needs-no-stretch) [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/matrix-group-max-width` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Числовая `МаксимальнаяШирина` у группы с матричной компоновкой: телефон рисует страницу десктопной шириной, и контент уходит за правый край [подробнее](#d-yaml-matrix-group-max-width) [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/card-literal-stretch-weight` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Литеральный `ВесПриРастягивании` у карточки или у группы внутри неё: в мобильной раскладке Safari схлопывает карточку, а Chrome не показывает ничего [подробнее](#d-yaml-card-literal-stretch-weight) [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Метод объявлен в проекте и больше нигде не используется: ни вызовом в коде, ни привязкой в yaml, ни именем в строке. Комментарий использованием не считается [подробнее](#d-code-unused-method) |
| `code/unused-constant` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Константа модуля нигде больше в проекте не упоминается: объявление осталось без дела [подробнее](#d-code-unused-constant) |
| `code/duplicate-method-body` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Тело метода от пяти строк дословно повторяется в другом файле: сравнивается нормализованное тело, и правку придётся вносить в обе копии [подробнее](#d-code-duplicate-method-body) |
| `yaml/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Ссылка из yaml на публичный элемент чужой подсистемы, пространства имён которого нет в секции `Импорт`: по короткому имени элемент не находится [подробнее](#d-yaml-missing-import) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/unused-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль импортирует подсистему или её пакет, а компилятор ни разу не ищет тип в этом пространстве имён [подробнее](#d-code-unused-import) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль называет публичный элемент чужой подсистемы, а строки импорта его пространства имён нет: компиляция проекта падает на этой строке [подробнее](#d-code-missing-import) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/wrong-namespace` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Квалифицированное имя своего проекта в значении yaml ведёт в пространство имён, где элемента с таким именем нет: компилятор отвечает "Неизвестный тип" [подробнее](#d-yaml-wrong-namespace) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/wrong-namespace` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | То же в модуле и запросе: имя своего проекта ведёт в пространство имён, где его элемента нет, и компилятор отвечает "Неизвестный тип" [подробнее](#d-code-wrong-namespace) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/package-resources-missing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | `ПакетРесурсов.Текущий()` в модуле пакета или корня подсистемы, у которых нет своего каталога `Ресурсы`: ни один файл не находится, и ломается это только при выполнении [подробнее](#d-code-package-resources-missing) [доки](https://1cmycloud.com/docs/help/topics/resource-in-project/) |
| `yaml/missing-subsystem-usage` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Элементы и модули подсистемы импортируют другую подсистему, а в описании своей её нет в блоке `Использование`: применение проекта падает [подробнее](#d-yaml-missing-subsystem-usage) [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/computed-binding-assigned` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Каждый экземпляр компонента связывает свойство вычисляемым выражением, а компонент присваивает это свойство в своём модуле: на присваивании платформа падает [подробнее](#d-yaml-computed-binding-assigned) |
| `yaml/localization-missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Неквалифицированная ссылка `$Словарь.Ключ`, чей словарь лежит в пространстве имён, которого нет в секции `Импорт` этого yaml: применение отвергает узел [подробнее](#d-yaml-localization-missing-import) [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/presentation-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле представления объекта [доки](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Параметр типа у свойства, которое ui-схема объявляет без параметра: это уже другой тип, и применение сборки его отвергнет [подробнее](#d-yaml-unexpected-type-argument) [доки](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Свойство компонента новее, чем `РежимСовместимости` проекта (версию появления несёт ui-схема) – применение отвергает его как неизвестное [доки](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Условие с пометкой удаления в запросе к объекту с `РежимУдаления: Немедленно` – поля пометки у него нет, запрос падает применением [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/load-object-unwrap` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Форс-разворот результата `ЗагрузитьОбъект()` у ссылки из поля записи или строки табличной части: запись могли удалить физически, и разворот роняет весь обход [подробнее](#d-code-load-object-unwrap) [доки](https://1cmycloud.com/docs/help/topics/data-deletion/) |
| `yaml/item-id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Элемент коллекции метаданных (реквизит, табличная часть, элемент перечисления, параметр ключа доступа) без `Ид`, который объявляет его класс – применение отвечает `ID required` |
| `code/unknown-row-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Поле строки динамического списка (`СтрокаДинамическогоСписка<Форма.Тип>`), которого нет среди `Поля` списка [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Поле динамического списка, взятое через ссылку (`Исполнитель.Номер`), имеет тип `<тип>|Null` и не годится типизированному полю структуры – компилятор отвечает `Null cannot be assigned` [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ, которого класс самого реквизита не объявляет (`Длина` у обычного реквизита – её объявляет стандартный `Код`, а у числового есть `ДлинаЦелойЧасти`) – применение сборки отвергает объект |
| `yaml/empty-group-sized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пустая `Группа` с `Высота`/`Ширина` (числом – всегда; биндингом `=...` – только без `Имя`) – рендер выбрасывает узел, зазора не будет |
| `yaml/insert-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Горизонтальная группа без `ВыравниваниеСодержимогоПоВертикали` равняет детей по базовой линии, а вставка `КонтейнерHtml`, кнопка и картинка эту линию ломают [подробнее](#d-yaml-insert-row-needs-align) [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/component-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Та же пара кнопки и картинки, когда соседа рисует компонент проекта: они встают на разную высоту [подробнее](#d-yaml-component-row-needs-align) [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/hint-too-long` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `Подсказка` длиннее предела отрисовки – хвост не показывается вовсе |
| `yaml/popup-in-markup` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | `ВсплывающийКомпонент` размещён в yaml-разметке: содержимое рисуется прямо в строке формы ещё до открытия окна [подробнее](#d-yaml-popup-in-markup) [доки](https://1cmycloud.com/docs/help/topics/popup-component/) |
| `yaml/date-input-needs-plain-date` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `ПолеВвода<Дата?>` – поле ввода даты, допускающей пустое значение, рендер молча не рисует; тип делается непустым, "не задано" – пустая дата [доки](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/binding-needs-auto` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Биндинг свойства без пустого значения зовёт метод с nullable-возвратом – клиент регистрирует "Неожиданное значение" на каждом пересчёте; "не задано" – это значение Авто |
| `code/client-available-needs-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | `@ДоступноСКлиента` у метода модуля компонента интерфейса, который не статический и без `@Контекстный` – тип компонента не синглтонный, применение отвергает модификатор [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-available-unused` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Метод объявлен `@ДоступноСКлиента`, но клиентского места, которое его называет, в проекте нет: аннотация открывает клиенту поверхность, которой никто не пользуется [подробнее](#d-code-client-available-unused) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение `Модуль.Член(...)` к общему модулю с `Окружение: Сервер` из метода, исполняемого на клиенте: на клиенте такого типа нет [подробнее](#d-code-server-module-in-client-context) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/component-in-server-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение `Компонент.Член(...)` к компоненту интерфейса из кода, компилируемого для сервера: тип компонента живёт на клиенте [подробнее](#d-code-component-in-server-context) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `ПриУдаленииОбъектаПоСсылке: УдалятьТекущий` у реквизита, чей владелец удаление только помечает: применение отвергает такую пару [подробнее](#d-yaml-delete-current-needs-immediate) [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/access-context-read-noop` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Расширение контекста доступа правом Чтения для типа с `Чтение: РазрешеноВсем`: выдавать нечего, а вызов создаёт впечатление защищённости [подробнее](#d-code-access-context-read-noop) [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/per-object-permissions-need-common` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Объект вычисляет разрешения для каждого объекта, но в его модуле нет обработчика `ВычислитьРазрешенияДоступа` – общий расчёт обязателен и при per-object, пусть и возвращает пустой массив [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | В `ВычислитьРазрешенияДоступаДляОбъектов` читается поле, которого нет среди `РасчетРазрешенийПо`, либо объявленное поле берётся через `Сущность` вместо `Запись` [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-handlers-need-recalc` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль объявляет обработчик разрешений, а `ПересчитатьРазрешенияДоступа` этой сущности нигде не вызван: платформа обработчик сама не вызывает, и правка прав молча не действует [подробнее](#d-code-permission-handlers-need-recalc) [доки](https://1cmycloud.com/docs/help/topics/recalculate-access-permissions-and-keys/) |
| `code/permission-right-not-computable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обработчик `ВычислитьРазрешенияДоступа` выдаёт право, не объявленное вычислимым в yaml сущности: сборка применяется, а пересчёт разрешений падает уже при работе [подробнее](#d-code-permission-right-not-computable) [доки](https://1cmycloud.com/docs/help/topics/manage-access-control/) |
| `yaml/placeholder-key-in-strings` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ с подстановкой `$0` в секции `Строки` словаря `ЛокализованныеСтроки`: секция компилируется в метод без параметров [подробнее](#d-yaml-placeholder-key-in-strings) [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/localization-ref-to-template` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Ссылка `$Словарь.Ключ` указывает на ключ секции `Шаблоны`: ссылка ищет ключ только в `Строки`, и применение падает [подробнее](#d-yaml-localization-ref-to-template) [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/compare-with-localized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Локализованное значение (`Словарь.Ключ()`, `Представление()`) сравнивается с литералом или со вторым локализованным – на другом языке ветка молча не срабатывает [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/url-params-partial-encoding` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Вызов метода Url `СПараметрамиЗапроса`: значение параметра кодируется частично, и значение-адрес приходит обрезанным по первому "&" [подробнее](#d-code-url-params-partial-encoding) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Http/Url_ru/) |
| `code/bound-property-assign` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Свойство, вычисляемое выражением в парной разметке, присваивается из кода: платформа такое присваивание отвергает [подробнее](#d-code-bound-property-assign) |
| `yaml/event-needs-importance` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | В описании `СобытиеЖурналаСобытий` не задана `Важность`: её умолчание требует значение в каждом конструкторе, и пропуск роняет применение [подробнее](#d-yaml-event-needs-importance) [доки](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `yaml/event-property-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Тип свойства `СобытиеЖурналаСобытий` вне закрытого списка платформы: отказ приходит только серверной компиляцией и стоит деплоя [подробнее](#d-yaml-event-property-type) [доки](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле структуры имеет известный платформенный тип без значения по умолчанию и не имеет ни `обз`, ни допуска `Неопределено`, ни инициализатора [подробнее](#d-code-collection-field-needs-req) [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Переменная объявлена одним типом, у которого нет ни конструктора, ни значения по умолчанию (`пер Ответ: ОтветHttp`) [подробнее](#d-code-var-needs-init) [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение к члену, которого у коллекции строк табличной части нет: коллекция это `Массив<Сущность.Секция>` [подробнее](#d-code-unknown-tabular-member) |
| `code/global-unavailable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Вызов глобального имени вне его окружения: `Сообщить` в серверном модуле, вычисление выражения в клиентском методе без `@НаСервере` [подробнее](#d-code-global-unavailable) [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Переменная, параметр или метод с именем элемента проекта: объявление закрывает обращение к элементу из этой области [подробнее](#d-style-shadow-project-name) [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/shadow-own-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Переменная `знч`, `пер` или `исп` с именем свойства объекта, с которым работает метод: имя разрешается в переменную, и ни чтение, ни присваивание до свойства не доходят [подробнее](#d-style-shadow-own-property) [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/redundant-union-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Член составного типа, который уже покрыт другим: повтор, второе пустое значение или член под более широким соседом [подробнее](#d-style-redundant-union-member) [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `code/unclosed-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Закрываемый ресурс, брошенный досрочным выходом из перебора: `возврат` или `прервать` в середине оставляет его открытым [подробнее](#d-code-unclosed-resource) [доки](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `code/use-needs-closeable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Модификатор `исп` у типа, который описан каталогом и не наследует `Закрываемое` – модификатор существует ради автоматического `Закрыть()`, и компилятор отвергает объявление [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `conventions/untranslated-visible-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Видимый текст остался кириллическим литералом там, где то же свойство проект уже вынес ссылкой на словарь локализации [подробнее](#d-conventions-untranslated-visible-literal) |
| `conventions/untranslated-code-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Видимый текст остался кириллическим литералом в модуле: судится по стоку, куда он попадает [подробнее](#d-conventions-untranslated-code-literal) |
| `conventions/missing-translation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | проект | Токен проекта или кириллическая строка комментария, которых ещё нет в словаре перевода проекта [подробнее](#d-conventions-missing-translation) |
| `code/unknown-structure-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение к полю структуры, объявленной в проекте, сверяется с её объявлением: переименованное поле краснеет у потребителя, а не на серверной компиляции [подробнее](#d-code-unknown-structure-field) |
| `code/redundant-skip-undefined` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Исключение `Неопределено` из коллекции, у которой тип элемента его и так не допускает [подробнее](#d-code-redundant-skip-undefined) [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Iterable_ru/) |
| `code/redundant-cast` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Приведение к типу, который у операнда уже есть: IDE платформы о таком приведении предупреждает [подробнее](#d-code-redundant-cast) [доки](https://1cmycloud.com/docs/help/topics/as/) |
| `code/cast-to-non-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Приведение, которое только отбрасывает `Неопределено`: у операнда тип `Т?`, а приведение называет `Т`, и IDE платформы советует здесь настойчивую операцию [подробнее](#d-code-cast-to-non-null) [доки](https://1cmycloud.com/docs/help/topics/exclamation-mark-operation/) |
| `code/redundant-undefined-guard` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `??`, `!` или `?.` над значением, в типе которого нет `Неопределено`: защита ничего не проверяет, а значение по умолчанию не используется [подробнее](#d-code-redundant-undefined-guard) [доки](https://1cmycloud.com/docs/help/topics/undefined-type/) |
| `code/redundant-type-check` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Проверка `Х это Тип`, результат которой решает тип `Х`: проверка проходит всегда, а `это не` никогда [подробнее](#d-code-redundant-type-check) [доки](https://1cmycloud.com/docs/help/topics/is/) |
| `comment/unknown-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Имя в комментарии, которого нет ни в проекте, ни у платформы: метод переименован, объект заменён, опечатка [подробнее](#d-comment-unknown-name) |
| `code/deprecated-api` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Вызов, который привязывается только к устаревшей форме метода платформы: IDE платформы о нём предупреждает [подробнее](#d-code-deprecated-api) [доки](https://1cmycloud.com/docs/help/topics/update-app-data/) |

#### Подробнее о правилах тира D

<a id="d-yaml-value-choice-title"></a>**`yaml/value-choice-title`.** Подпись кладут отдельной
`Надписью` рядом с переключателем. Узел без явного вида и узел с тип-аргументом `Массив<...>`, то
есть группу флажков, правило не судит.

<a id="d-code-unknown-static-member"></a>**`code/unknown-static-member`.** Тип результата такого
вызова переносится на следующий шаг цепочки. Голое имя читается как тип, только если проект не
придаёт ему другого смысла. Парный yaml модуля учитывается и при проверке одиночного файла.

<a id="d-yaml-foreign-not-public"></a>**`yaml/foreign-not-public`.** Ссылкой считается позиция
типа, цель навигации `ТипФормы`, корень цепочки биндинга `=Модуль.Метод()`, таблица списка
(динамического списка или настроек ввода ссылки поля) и квалифицированное имя
`Подсистема[::Пакет]::Элемент`. Квалифицированная запись судится по названной подсистеме или
пакету.

<a id="d-code-foreign-not-public"></a>**`code/foreign-not-public`.** Судится записанная позиция
типа, корень цепочки `Модуль.Метод()` и таблица запроса: блока `Запрос{...}` или `.xbql`
виртуальной таблицы. Квалифицированная запись `Подсистема[::Пакет]::Элемент` входит сюда же. Ни
импорт, ни аннотация `@ВПроекте` на методе не помогают. Модуль проекта не принадлежит ни одной
подсистеме, поэтому всякий непубличный элемент для него чужой.

<a id="d-code-missing-return"></a>**`code/missing-return`.** Полный `выбор` по перечислению и
вызов метода с результатом `никогда` учитываются, а цикл возврата не гарантирует. Проверка проекта
читает перечисления и сигнатуры, а неустановленные случаи правило не угадывает.

<a id="d-code-unused-return-value"></a>**`code/unused-return-value`.** Тип приёмника отличает
неизменяемую операцию от изменяющего метода с тем же именем, а короткая лямбда оператором не
считается. Нужны свежие данные экстрактора. Автоматической правки нет.

<a id="d-code-ambiguous-type"></a>**`code/ambiguous-type`.** Корень подсистемы не имеет приоритета
над пакетами, поэтому пространство указывают явно. Квалификаторы и объявления типов внутри файла
учитываются.

<a id="d-yaml-dynlist-row-editing"></a>**`yaml/dynlist-row-editing`.** Событие объявлено для
узловых строк иерархии. У плоского списка по нажатию открывается автоформа объекта, поэтому
объекту дают свою форму объекта.

<a id="d-yaml-dynlist-joined-table-param"></a>**`yaml/dynlist-joined-table-param`.** У основной
таблицы такая запись законна, у присоединённой компилятор о ней молчит. В yaml оставляют литерал,
а живое значение присваивают из кода: `Источник.ПрисоединенныеТаблицы[i].Аргументы`.

<a id="d-yaml-dynlist-filter-disabled"></a>**`yaml/dynlist-filter-disabled`.** Это гонка первого
показа: платформа рисует список, не дожидаясь кода. Отбор объявляют включённым, с пустым
значением.

<a id="d-yaml-list-form-needs-dynlist"></a>**`yaml/list-form-needs-dynlist`.** Каркас формы списка
заточен под таблицу динамического списка, а в содержимом нет ни одного типа с
`ДинамическийСписок`. Таблице дают динамический список либо наследуют обычную форму (`Тип:
Форма`).

<a id="d-yaml-ref-input-auto-commands"></a>**`yaml/ref-input-auto-commands`.** У ссылочного поля
`Авто` разворачивается во фрагмент командного интерфейса. Чаще всего кнопка и нужна, поэтому
правило информационное и выключено, а глушат его пустым фрагментом.

<a id="d-yaml-toggle-command-pair"></a>**`yaml/toggle-command-pair`.** `ПереключаемаяКоманда`
несёт представления и изображения обоих состояний, начальное `Активна` задают литералом, а
состоянием владеет платформа. Общий обработчик пары усиливает картину, но не требуется.

<a id="d-yaml-dynlist-column-sort-lost"></a>**`yaml/dynlist-column-sort-lost`.** Колонку
привязывают к полю либо добавляют поле-представление в сам список. Колонку с `ОтключитьСортировку:
Истина` правило не судит: сортировки у неё нет по объявлению. По умолчанию выключено, потому что
из файла не видно, нужна ли этой колонке сортировка.

<a id="d-yaml-badge-column-image"></a>**`yaml/badge-column-image`.** Значение рисуется
тегами-пилюлями, а картинка задокументирована только для `Вид: Картинка`. Снимите `Вид`, и
картинка встанет рядом с текстом значения, либо задайте `Вид: Картинка`.

<a id="d-yaml-enum-needs-nullable"></a>**`yaml/enum-needs-nullable`.** Судятся оба написания: поле
ввода узнаётся как `Edit<...>`, это английское написание платформы. `InputField` написанием не
является, его ловит `yaml/unknown-type`.

<a id="d-code-image-binding-server-call"></a>**`code/image-binding-server-call`.** Методы с
включённым или неизвестным кешем и клиентские варианты исключаются. Изображение передают вместе с
данными либо берут из уже загруженных клиентских данных.

<a id="d-code-query-needs-server"></a>**`code/query-needs-server`.** Клиентским считается модуль
формы и общий модуль, у которого `Окружение` захватывает клиент.

<a id="d-code-reserved-name"></a>**`code/reserved-name`.** Правило судит поле структуры и параметр
метода. Написание с заглавной буквы подтверждено живым применением на сервере.

<a id="d-yaml-property-shadows-module"></a>**`yaml/property-shadows-module`.** Применение отвечает
"Неизвестный метод", и стенд откатывается. Лечение одно: переименовать свойство. Автоисправления
нет, за именем тянутся разметка, парный модуль и обращения снаружи. Судится только общий модуль,
достижимый по короткому имени: своя подсистема, её корень и пакеты, либо пространство имён,
импортированное в yaml компонента. `Подсистема` даёт модули корня этой подсистемы,
`Подсистема::Пакет` – модули пакета. Тёзка-справочник или тёзка-компонент это живая идиома.

<a id="d-yaml-col-width-needs-no-stretch"></a>**`yaml/col-width-needs-no-stretch`.** Судятся все
три вида колонок. Колонка выходит шире заданного, и содержимое уезжает от соседней. Пиксельной
ширине нужна `РастягиватьПоГоризонтали: Ложь`, доле с гарантированным минимумом –
`МинимальнаяШирина`. По умолчанию выключено: ширина-как-доля это законная техника, и статически
она от ловушки не отличается.

<a id="d-yaml-matrix-group-max-width"></a>**`yaml/matrix-group-max-width`.** Максимум служит и
располагаемой шириной, поэтому автоматические колонки раскладываются по нему, а не по окну.
Правильный ответ `Авто`. По умолчанию выключено: страница только для десктопа живёт с максимумом
нормально.

<a id="d-yaml-card-literal-stretch-weight"></a>**`yaml/card-literal-stretch-weight`.** Вес это
flex с нулевой базой, а в вертикальной колонке, то есть в мобильной раскладке, база относится к
высоте. Safari обрезает карточку скруглением. На телефоне вес снимают биндингом. По умолчанию
выключено: карточка, живущая только в широком ряду, носит вес законно.

<a id="d-code-unused-method"></a>**`code/unused-method`.** Имя в строковом литерале считается
употреблением: вставка HTML зовёт метод по имени, и такого вызова статически не видно. Комментарий не
считается нигде – ни в модуле, который объявляет метод, ни в парном yaml, ни в чужом элементе; когда имя
нашлось только в комментарии, находка так и говорит. Не судятся события платформы, модуль объекта, модуль
в паре с `HttpСервис` и метод, аннотация которого называет вызывающего вне кода проекта (`@Обработчик`,
`@Подписка`, `@Реализация` и прочие) – такая аннотация и есть ответ для метода, который зовёт сама
платформа или контракт. Если вызов всё равно не виден – имя собирается во время работы, клиентская точка
входа оставлена намеренно, – заморозьте находку в списке принятых вместе с причиной (`--write-baseline`,
затем `--baseline`). Выключено по умолчанию: на части файлов метод, который зовут снаружи, выглядел бы
мёртвым.

<a id="d-code-unused-constant"></a>**`code/unused-constant`.** Употреблением считаются слова кода,
yaml, строк и комментариев, а словарь перевода не считается. Глобальные константы и константы с
неизвестными аннотациями пропускаются. Правило включают при проверке всего проекта.

<a id="d-code-duplicate-method-body"></a>**`code/duplicate-method-body`.** Нормализация снимает
комментарии, пустые строки и отступы. Платформенный обработчик отделяется по аннотации
`@Обработчик`, а не по списку имён: одинаковое тело обработчика в каждом объекте нормально. Копии
внутри одного файла правило не судит. По умолчанию выключено: сводить ли две копии в один метод,
решает проектировщик.

<a id="d-yaml-missing-import"></a>**`yaml/missing-import`.** Ссылкой считается позиция типа, цель
навигации `ТипФормы` и корень цепочки биндинга `=ЧужойМодуль.Метод()`. Нужен `Подсистема` для
элемента в корне подсистемы и `Подсистема::Пакет` для элемента пакета: импорт подсистемы её
пакетов не даёт. Импорт в парном модуле разметку не покрывает. Корень биндинга судится после
вычета всего, что объясняет имя само по себе: объявлений этого yaml, парного модуля и неявных имён
платформы. Таблицы парного запроса виртуальной таблицы разрешаются через ту же секцию, и находка
ставится на неё: это `.xbql` и все элементы списков `ИЗ`, в том числе после условия соединения.
Квалифицированные и временные таблицы правило не судит. Так же разрешаются таблицы динамического
списка, то есть `Таблица` его `ОсновнаяТаблица` и каждой из `ПрисоединенныеТаблицы`, и
`ПрисоединенныеТаблицы` настроек ввода ссылки поля; находка ставится на значение таблицы, а
квалифицированная таблица импорта не требует.

<a id="d-code-unused-import"></a>**`code/unused-import`.** IDE платформы такие импорты показывает.
Считается то, что разрешает компилятор: записанный тип; имя, которое не локальное и не объявлено
модулем или парным yaml; корень цепочки `Корень.член`, даже если корень это свойство парного yaml;
квалифицированное имя; таблица запроса; значение перечисления в ветке `когда`; ключ `Ресурс{...}`
без пространства имён, если файл лежит только в этом пространстве. Считаются и типы, которые
приносят значения: свойства парного yaml, названные в коде, результаты методов и поля других
элементов по цепочке, поля этих структур и колонка запроса, передающая поле как есть. Сама строка
импорта, член после точки и локальная переменная с именем элемента употреблением не считаются,
поэтому `импорт Подсистема` рядом с `импорт Подсистема::Пакет` показывается, когда модуль
обращается только к пакету. Ссылка из парного yaml тоже не употребление: у yaml своя секция
импорта. Импорт собственного пространства модуля судится так же. Исправление снимает строку.

<a id="d-code-missing-import"></a>**`code/missing-import`.** Нужен `импорт Подсистема` для
элемента в корне подсистемы и `импорт Подсистема::Пакет` для элемента пакета: импорт подсистемы её
пакетов не даёт. Судятся записанные позиции типа (параметр, переменная, возврат, `новый`, `как`,
`это`, литерал `Тип<...>`, аргументы обобщённого), корень цепочки `Модуль.Метод()` и таблицы
блоков `Запрос{...}`, все элементы списка `ИЗ`. У корня сначала вычитается всё, что объясняет имя
само по себе: объявления метода и модуля, неявные имена платформы и секции парного yaml. Модуль
проекта не входит ни в одну подсистему, и импорт ему нужен для любого элемента, который он
называет, и в корне подсистемы, и в пакете.

<a id="d-yaml-wrong-namespace"></a>**`yaml/wrong-namespace`.** Судится и полное имя
`Поставщик::Проект::Подсистема[::Пакет]::Имя`, и частичное `Подсистема[::Пакет]::Имя`, причём
проект объявляет этот элемент в другом месте. Обычная причина это перенос элемента между корнем
подсистемы и пакетом: сгенерированная форма списка хранит тип строки со старым местом. Читаются
все строковые значения элемента и описаний, кроме списков пространств имён (`Импорт`,
`Использование`) и ссылок на ресурсы. Имя другого проекта, тип, объявленный в модуле, и цепочка,
которая целиком называет пространство имён, не судятся. Частичное имя судится, когда первый
сегмент это подсистема проекта, которую не называет ни одна объявленная библиотека. Если элемент
лежит в одном месте, у находки есть автоисправление: пространство имён заменяется местом элемента.
Элемент в нескольких местах сообщается со списком мест и без исправления.

<a id="d-code-wrong-namespace"></a>**`code/wrong-namespace`.** Имя бывает полным и частичным, а
стоять оно может в позиции типа, в вызове или таблицей запроса. О таблице компилятор отвечает, что
она не найдена. Строка импорта и ключ литерала `Ресурс{...}` не читаются. Автоисправление заменяет
пространство имён, если элемент лежит в одном месте.

<a id="d-code-package-resources-missing"></a>**`code/package-resources-missing`.** Метод отдаёт
ресурсы только своего пространства имён, поэтому у пакета не находятся даже файлы его подсистемы,
а у корня файлы её пакетов. Ответ один: `ИсключениеРесурсНеНайден`, в том числе у `ПолучитьВсе()`.
В пакете литерал `Ресурс{...}` файлы подсистемы находит. Каталог ищется на диске, а модуль проекта
правило не судит.

<a id="d-yaml-missing-subsystem-usage"></a>**`yaml/missing-subsystem-usage`.** `Подсистема::Пакет`
считается импортом этой подсистемы, а узнаётся всё только на деплое. Импорт даёт краткие имена, но
саму подсистему вместе с её пакетами разрешает `Использование`. Подсистема без описания не
судится: объявить использование ей негде. Замечание стоит на описании подсистемы, там же и правка.

<a id="d-yaml-computed-binding-assigned"></a>**`yaml/computed-binding-assigned`.** Платформа
отвечает IllegalStateException. Именованный аргумент присваиванием не считается, а экземпляр из
кода, связь голым путём, литерал или экземпляр без связи делают присваивание законным: правило
срабатывает, только когда вычисляемым связан каждый экземпляр.

<a id="d-yaml-localization-missing-import"></a>**`yaml/localization-missing-import`.** Нужен
`Подсистема` для словаря в корне подсистемы и `Подсистема::Пакет` для словаря пакета: импорт
подсистемы её пакетов не даёт. Применение отвергает узел как неимпортированное пространство имён.
Словарь своей подсистемы, в корне или в пакете, импорта не требует, импорт в парном модуле
разметку не покрывает, а квалифицированная форма `$Подсистема::Словарь.Ключ` работает без импорта.

<a id="d-yaml-unexpected-type-argument"></a>**`yaml/unexpected-type-argument`.** Пример:
`ДополнительныеКоманды` формы принимают `ФрагментКомандногоИнтерфейса`, а не
`ФрагментКомандногоИнтерфейса<ОбычнаяКоманда>`. Английское дерево судится так же: ключ, компонент,
свойство и голова типа канонизируются, а аргумент сравнивается с умолчанием имя за именем в любом
написании.

<a id="d-code-load-object-unwrap"></a>**`code/load-object-unwrap`.** Пример записи:
`Строка.Сервис!.ЗагрузитьОбъект()!`. Физическое удаление даёт `РежимУдаления: Немедленно` и форма
удаления помеченных. Результат проверяют на Неопределено. Собственную `.Ссылка` строки запроса
правило не судит.

<a id="d-yaml-insert-row-needs-align"></a>**`yaml/insert-row-needs-align`.** У вставки
`КонтейнерHtml` базовая линия своя, поэтому элемент со вставкой съезжает вниз: на живом ряду это
50 px. Отвечает ближайший горизонтальный предок, а ряд с уже выровненной внутренней полосой
молчит. У `Кнопка` базовая линия проходит по надписи, у `Картинка` по нижнему краю, поэтому кнопка
с надписью рядом с картинкой опускается на 19 px. Лечит `ВыравниваниеСодержимогоПоВертикали:
Центр`. Биндинг `Компоновка` учитывается в статически горизонтальных ветках. Пара судится, когда
один из двух виден безусловно или оба видны при одних и тех же условиях. Соседей с разными
собственными условиями видимости и ребёнка со своим вертикальным выравниванием правило не судит.

<a id="d-yaml-component-row-needs-align"></a>**`yaml/component-row-needs-align`.** Компонент
показывает нативную `Кнопка` или `Картинка` безусловно либо выбирает между ними по своему
свойству: экземпляр задаёт свойство литералом, а условие сравнивает его прямо или через метод,
который только возвращает это сравнение. На живом ряду кнопка опустилась на 19 px. Ряду задают
`ВыравниваниеСодержимогоПоВертикали: Центр`. Видимость читается как в
`yaml/insert-row-needs-align`. Компонент, который статически не прочитать, в паре не участвует, а
ряд, который файловое правило судит само, остаётся за `yaml/insert-row-needs-align`.

<a id="d-yaml-popup-in-markup"></a>**`yaml/popup-in-markup`.** Так же судится проектный компонент,
транзитивно наследующий `ВсплывающийКомпонент`. Свойства, ограничивающего отрисовку окном, у
платформы нет, а скрытие через `Видимость` ломает само окно. Окно собирают кодом на каждое
открытие: новый `ВсплывающийКомпонент(...)`, затем `ОткрытьВоВсплывающемОкне()`.

<a id="d-code-client-available-unused"></a>**`code/client-available-unused`.** Клиентским местом
считается модуль клиентского окружения, клиентский метод серверного модуля, yaml и строковый
литерал. По умолчанию выключено, как `code/unused-method`: клиентский вызов бывает не виден
статически.

<a id="d-code-server-module-in-client-context"></a>**`code/server-module-in-client-context`.**
Клиентским местом здесь считается компонент интерфейса, команда и клиентский общий модуль.

<a id="d-code-component-in-server-context"></a>**`code/component-in-server-context`.** Серверным
считается метод `@НаСервере` где угодно и метод без аннотации в серверном или клиент-серверном
модуле. Серверная компиляция отвечает "Переменная X не определена".

<a id="d-yaml-delete-current-needs-immediate"></a>**`yaml/delete-current-needs-immediate`.**
Пометка это `РежимУдаления: ПометкаУдаления`, и она же умолчание. Применение отвечает `Action
УдалятьТекущий cannot apply to object with a DeletionMark`.

<a id="d-code-access-context-read-noop"></a>**`code/access-context-read-noop`.** Читать такой тип
и так разрешено всем. Если право в списке одно, снимается вся строка, а если есть другие, то
только Чтение.

<a id="d-code-permission-handlers-need-recalc"></a>**`code/permission-handlers-need-recalc`.**
Обработчики это `ВычислитьРазрешенияДоступа` и родня. Пересчёт с получателем не-сущностью,
документированный цикл, глушит правило. Виды без метода пересчёта, то есть право-элементы, не
судятся.

<a id="d-code-permission-right-not-computable"></a>**`code/permission-right-not-computable`.**
Судится и `...ДляОбъектов`. Вычислимость объявляют `РазрешенияВычисляются` и
`РазрешенияВычисляютсяДляКаждогоОбъекта`, явно или через `ПоУмолчанию`. Пересчёт отвечает, что
право не указано как вычислимое. Права собираются только из конструкторов `новый
РазрешениеДоступа(...)` в обоих пространствах, `Сущность.Право.*` и `HttpСервисПраво.*`,
транзитивно по вызовам проекта: делегирование в общий модуль прав видно, а находка привязывается к
сущности. `КонтекстДоступа.Дополнить` не считается, недовыдача законна, виды без контроля доступа
не судятся.

<a id="d-yaml-placeholder-key-in-strings"></a>**`yaml/placeholder-key-in-strings`.** Вызов с
аргументом падает на применении с ответом "Неизвестный метод".

<a id="d-yaml-localization-ref-to-template"></a>**`yaml/localization-ref-to-template`.**
Применение отвечает "Не удалось найти локализованную строку", и стенд откатывается. Ключ шаблонов,
на который никто не ссылается, правило не судит: из кода его зовут законно.

<a id="d-code-url-params-partial-encoding"></a>**`code/url-params-partial-encoding`.** Знаки "&" и
"=" внутри значения остаются разделителями. Строку собирают самим объектом параметров и клеят к
базовому адресу. По умолчанию выключено: видны ли "&" в значениях, статически не решается.

<a id="d-code-bound-property-assign"></a>**`code/bound-property-assign`.** Выглядит это так:
`Высота: =Общее.ЭтоУзкийЭкран()?820:528`. В попытка/поймать отказ не виден. Связь с данными, то
есть голый путь, правило не трогает: она двунаправленная по устройству.

<a id="d-yaml-event-needs-importance"></a>**`yaml/event-needs-importance`.** Умолчание это
`ИзКонструктора`. Пропуск хотя бы в одном месте записи роняет применение на строке конструктора.
Явное `Важность: ИзКонструктора` объявляет выбор и снимает предупреждение.

<a id="d-yaml-event-property-type"></a>**`yaml/event-property-type`.** Перечисление проекта туда
положить нельзя. Список берётся из метамодели (`EventLogEventProperty.Тип`), а `?` и квалификация
`Стд::` терпятся. Вариантные значения пишут строковыми кодами, а перечень допустимых кодов кладут
в `Описание` свойства.

<a id="d-code-collection-field-needs-req"></a>**`code/collection-field-needs-req`.** Так выглядят
`ПозицияВТексте` и `ЧитаемыйМассив<Строка>`. Скалярные значения по умолчанию, неизвестные типы и
локальные тёзки платформенных типов замечаний не вызывают.

<a id="d-code-var-needs-init"></a>**`code/var-needs-init`.** Компиляция отвечает "не имеет
конструктора и значения по умолчанию". Перечисление, аннотация, одиночка и имя, перекрытое типом
проекта, пропускаются.

<a id="d-code-unknown-tabular-member"></a>**`code/unknown-tabular-member`.** Судится
`Объект.Секция.Член` в модуле формы объекта, голое имя секции и `этот.Секция` в модулях сущности.
Привычное из другой платформы `Количество()` здесь зовётся `Размер()`. Секцию затеняет одноимённый
модуль, а реквизиты правило не судит.

<a id="d-code-global-unavailable"></a>**`code/global-unavailable`.** Применение отвечает "Метод
недоступен в текущем окружении". `Сообщить` живёт только на клиенте, вычисление выражения только
на сервере. `@НаКлиенте` и `@НаСервере` переопределяют окружение модуля, а доступность имён
берётся из строк "Доступность" пакетов глобального контекста.

<a id="d-style-shadow-project-name"></a>**`style/shadow-project-name`.** Пример: `знч Склады` при
справочнике `Склады`. Платформенные имена параметров обработчиков с именами проекта не
пересекаются.

<a id="d-style-shadow-own-property"></a>**`style/shadow-own-property`.** IDE платформы о такой
переменной предупреждает. Свойства берутся у владельца метода. У компонента это объявленные
свойства и события, свойства типа платформы, от которого он наследует, и `Компоненты`. В модуле
объекта справочника, документа и обработки это реквизиты, табличные части, ссылка, метка версии и
пометка удаления. У набора записей это фильтр, у запланированного задания параметры и свойства
задания, у структуры поля. Статические методы, параметры, переменные цикла и `поймать` не судятся,
а серверный метод компонента видит только свойства с признаком `Контекстное`.

<a id="d-style-redundant-union-member"></a>**`style/redundant-union-member`.** Так выглядят
`Строка|Строка`, `Строка|Неопределено|?` и `Массив<Строка>|ЧитаемыйМассив<Строка>`, то есть член
под `Объект` или под базовым типом каталога с теми же аргументами. IDE платформы об этом
предупреждает, а функциональный тип не судится. Исправление записывает объединение без таких
членов.

<a id="d-code-unclosed-resource"></a>**`code/unclosed-resource`.** Выглядит это как `знч Выборка =
Запрос{...}.Выполнить()`. Полный проход платформа закрывает сама, а незакрытый ресурс пишет в
журнал событий. Объявление через `исп` закрывает ресурс на любом пути выхода. Ресурс, пришедший
параметром, закрытый вручную и возвращённый вызывающему, оставлены автору.

<a id="d-conventions-untranslated-visible-literal"></a>**`conventions/untranslated-visible-literal`.**
Намерение считается в разрезе вида элемента, поэтому свойство-тёзка другого вида не судится. На
проекте, у которого в дескрипторе меньше двух языков локализации, правило молчит.

<a id="d-conventions-untranslated-code-literal"></a>**`conventions/untranslated-code-literal`.**
Стоком считается аргумент платформенного вызова сообщения, свойство события журнала или то же
самое через метод, пробрасывающий свой параметр. Разметка, чистая интерполяция и одиночные слова
пропускаются. На проекте с менее чем двумя языками локализации правило молчит.

<a id="d-conventions-missing-translation"></a>**`conventions/missing-translation`.** Находка одна,
на первое вхождение в файле. Правило молчит, пока рядом с проектом или выше не лежит словарь
`xbsl-translation` (см. `xbsl translate`).

<a id="d-code-unknown-structure-field"></a>**`code/unknown-structure-field`.** Тип берётся из
объявления переменной (`Модуль.Структура`, голое имя структуры своего модуля), из конструктора
`новый` и из элемента коллекции в `для X из Список`. Имя, объявленное в методе ещё чем-нибудь,
тёзка stdlib-типа, второй шаг цепочки и латинские написания члена не судятся.

<a id="d-code-redundant-skip-undefined"></a>**`code/redundant-skip-undefined`.** У перебираемой
коллекции исправление заменяет метод на `ВМассив()`, сохраняя создание массива. Последовательности
достаётся только предупреждение.

<a id="d-code-redundant-cast"></a>**`code/redundant-cast`.** Так выглядит `Найдена!.Ссылка как
Товары.Ссылка` над запросом, читающим ссылку того же справочника, и объединение ссылок,
приведённое к контракту сущности, который реализуют оба. Если типы совпадают, исправление убирает
приведение вместе со скобками вокруг одиночного операнда. Приведение к более широкому типу
называется без исправления: этот тип может быть нужен объявлению или перегрузке.

<a id="d-code-cast-to-non-null"></a>**`code/cast-to-non-null`.** Обычно это реквизит с `?`,
прочитанный запросом, результат `Соответствие.ПолучитьИлиНеопределено(...)` или метода с
результатом `Т?`. Исправление ставит `!` вместо приведения. Тип операнда берётся по объявлениям, у
колонки запроса по списку выборки и yaml таблицы. Условие, проверенное перед приведением, тип не
сужает, а операнд, который вывод не называет, не судится.

<a id="d-code-redundant-undefined-guard"></a>**`code/redundant-undefined-guard`.** IDE платформы о
ней предупреждает. Тип берётся из объявления, из компонента парной разметки вроде
`ПолеВвода<Число>` или из аргумента обобщённого типа, как у
`СобытиеПриИзменении<Строка>.НовоеЗначение`. Исправление убирает `!`, а `?? ...` убирает, если
умолчание не расширяет тип.

<a id="d-code-redundant-type-check"></a>**`code/redundant-type-check`.** Каждый тип выражения
совпадает с одним из проверяемых или относится к нему: это база из каталога (`Массив<Строка>`
подходит под `ЧитаемыйМассив<Строка>`) и контракт сущности, который реализует элемент проекта. IDE
платформы о такой проверке предупреждает. Колонка строки запроса типизируется по списку ВЫБРАТЬ
так же, как у правил приведений: поле, выбор, арифметика, количество. Поле через ссылку и поле
левого соединения могут быть `Null`, а `.ЗаменитьNull(...)` этот `Null` убирает.

<a id="d-comment-unknown-name"></a>**`comment/unknown-name`.** Падежная форма известного имени,
закомментированный код и цепочка другой системы не судятся.

<a id="d-code-deprecated-api"></a>**`code/deprecated-api`.** Так выглядят
`ОбъектноеХранилище.ЗагрузитьИзБайт(...)` и `ОбъектноеХранилище.Загрузить(Поток, Размер)` рядом с
текущей `Загрузить("файл", Байты)`. Перегрузки выбираются по режиму совместимости проекта, по
аргументам и по их известным типам. Сообщение называет замену, если её называет документация.

## Подробнее о группах

### Запросы: `В` с подзапросом по составному типу (правило `query/in-subquery-composite`)

Стандарт платформы "Использование выражения `В` с подзапросом для выражений составного типа":
на большинстве СУБД такой вариант реализован неэффективно, и условие пишется через `СУЩЕСТВУЕТ`.
Правило – предупреждение, стандарт обязателен:

```
ГДЕ Т.Значение В (ВЫБРАТЬ Ф.Значение ИЗ Фильтры КАК Ф)          // предупреждение
ГДЕ СУЩЕСТВУЕТ (ВЫБРАТЬ 1 ИЗ Фильтры КАК Ф ГДЕ Ф.Значение = Т.Значение)   // так
```

Составным считается тип поля с двумя и более альтернативами в yaml (`Строка|Число|?`): `?` – не
тип, а допустимость `Неопределено`, и `Массив<Строка|Число>` тоже не составной. Под сомнение
ставится только поле, тип которого известен наверняка: `Алиас.Поле` или `Таблица.Поле`, где алиас
однозначен в пределах блока, а поле нашлось в yaml таблицы; список значений (`В (1, 2, &Коды)`)
стандарта не касается. Правило понимает и английские формы (`IN`, `NOT`, `SELECT`).

### Свойства проекта (правила `project/`)

Четыре правила по стандарту "Заполнение свойств проекта": `Поставщик` и `Имя` – идентификаторы,
образованные от представлений (каждое слово с прописной буквы: `КабинетСотрудника`,
`НовыеЭлементарныеТехнологии`); `Представление` и `ПредставлениеПоставщика` заполнены – это
официальное название проекта и название компании-разработчика; `Версия` – три числа `A.B.C`
(семантическое версионирование), а не `1.0`.

### Имена элементов проекта (правила `naming/`)

Двенадцать правил по стандарту платформы "Имена элементов проекта" – он обязателен в новом коде,
поэтому все они предупреждения. Проверяются описания (`.yaml`): имя самого элемента и имена его
реквизитов, измерений, ресурсов, табличных частей и значений перечисления.

Число имени сверяется с видом элемента: справочники, документы, регистры и табличные части
именуются во множественном числе, перечисления и структуры – в единственном (`naming/number`).
Для русского имени это разбор морфологический, а не по окончаниям: `Номенклатура` единственного
числа стандарту не противоречит, а `Задачи` и `Партии` без падежа читаются как родительный падеж
единственного. Нужен набор `[morph]` (`pip install "xbsl[morph]"`), без него русские имена молчат.
Английское имя в переведённом дереве судится по последнему слову, суффиксной эвристикой с
перечнем неправильных множественных, и отдельный набор ему не нужен. Несчисляемые слова и
неоднозначные хвосты остаются нерешёнными.

Остальное: буква `ё` и подчёркивания в именах, аббревиатура одним словом (`Ндс`, а не `НДС`),
англоязычный термин оригиналом (`Xml`, а не `Хмл`), `Вид` вместо `Тип` у перечислений, вид
элемента внутри его имени (`ОтчетЗависшиеЗадачи`), слова-пустышки (`Управление`, `Менеджер`),
постфикс окружения у общего модуля (`ОбменДаннымиКлиентИСервер` – окружение задаётся свойством),
булев реквизит через отрицание (`НетОшибок` вместо `Успешно`), незаполненное `Представление` и
обязательные префиксы отдельных видов (`КлючДоступа`, `ПравоНа`, `Навигация`).

### Соглашения по написанию кода (правила `style/`)

Тридцать два правила по документации платформы ("Соглашения по написанию кода", "Идиомы
языка") и стандарту разработки "Имена переменных и констант": оформление и переносы
выражений, именование, описание типов и сигнатуры, литералы коллекций, интерполяция строк,
проверки булевых значений и `Неопределено`.

Из стандарта имён переменных и констант проверяется доказуемая по токенам часть: абстрактные
имена, однобуквенные имена вне лямбд, кириллические и латинские аббревиатуры не одним словом,
булевы имена от отрицания, тип-контейнер в имени, числительные в именах констант и тень имён
элементов проекта. Остаются на авторе и ревью: избыточные слова в имени, сокращения за
пределами регистра аббревиатур, числа вместо уточнения при осмысленной основе (`Этап1` против
`Данные1` различаются только смыслом) и абстрактность имени константы за пределами
числительных (роль `НАЧАЛЬНЫЙ_ЭТАП` против значения `ЭТАП_ПРИЕМА_АНКЕТА` токенам не видна).

Пять правил группы выходят за пределы токенов: они читают разобранный модуль и повторяют
предупреждения IDE платформы. `style/constructor-literal` находит конструктор, который заменяется
литералом типа, `style/boolean-ternary` – тернарный оператор с ветвями `Истина` и `Ложь`,
`style/redundant-scope` – область, которая единственная инструкция своего блока, а
`style/redundant-union-member` – член составного типа, который покрывает другой. `style/shadow-own-property` читает ещё парный yaml и каталог типов платформы,
поэтому переменная с именем свойства, которое компонент наследует, например `Заголовок` у `Группа`,
находится так же, как переменная с именем объявленного свойства.

Все тридцать два правила включены по умолчанию (`warning`): чистый код им уже соответствует, и
они защищают от регресса. Флаги выбора правил принимают группу целиком:

```sh
xbsl путь/к/исходникам --select style     # только эти правила
xbsl путь/к/исходникам --ignore style     # всё, кроме них
```

Блоки `Запрос{ ... }` (отдельный DSL) и строковые литералы (HTML/CSS/SVG вставок) из этих проверок
исключены. Не проверяются и остаются на авторе с ревью: кратность отступа четырём, идиомы
коллекций, `Строки.Соединить()` при массовой конкатенации, идиомы `?.` / `??` и `выбор` вместо
цепочки `иначе если`.

### Семантика кода (правила `code/`)

Самая большая группа – девяносто восемь правил, шестьдесят из них ошибки. Это то, что компилятор
отвергнет или что платформа выполнит не так, как читается: неизвестное имя или член типа, число
аргументов вызова, окружение (клиентский код в серверном методе и наоборот), обращение к
экземпляру через тип, неперехваченное не-исключение, незакрытый ресурс, обход по коллекции при
её изменении, а также обходы платформенных ловушек, у которых нет иного признака, кроме формы
кода. Сюда же входят предупреждения IDE платформы: неиспользуемая переменная или импорт, лишнее
приведение, защита от `Неопределено` или проверка `это`, исход которых уже решили типы. Часть
правил проектные (`--stdin` их не гоняет): им нужны парный yaml и имена объектов.

### Описания элементов (правила `yaml/`)

Шестьдесят четыре правила по описаниям (`.yaml`): обязательные и уникальные `Ид`, известные ключи
и типы, ссылки на компоненты, обработчики и локализованные строки, требования платформы к типам
полей (ссылка и перечисление допускают пустое значение), настройки динамических списков и форм,
а также ловушки вёрстки, которые применяются без ошибки, но рисуются не так, как задумано.
Шесть правил – `info` и выключены: они говорят "так работает платформа", а не "здесь ошибка".

### Соглашения проекта (правила `conventions/`)

Правила о том, о чём договорился проект, а не о том, чего требует платформа. В базовом наборе
живёт семья двуязычного проекта: `conventions/untranslated-visible-literal` (включено по
умолчанию) сообщает про видимый текст, оставшийся кириллическим литералом там, где то же
свойство проект уже ведёт через словарь локализации, а `conventions/untranslated-code-literal`
и `conventions/missing-translation` (оба выключены) расширяют это на литералы модулей и словарь
перевода – обязана ли каждая читаемая человеком строка приходить из словаря, каждый проект
решает сам, и базовый набор этого не навязывает.

Группа заодно и точка расширения: надстройка проекта регистрирует под `conventions/` свои
правила-соглашения (запрет номеров задач в комментариях, внутренних отсылок и подобное) и сама
решает их severity и включённость – см. [Расширение](/ru/servers#расширение-свои-правила-данные-и-уровни).
Что работает на самом деле, показывает `xbsl --list-rules`; таблица выше описывает только базовый
набор.

### Мелкие группы

- `typography/` – типографские символы в прозе и комментариях: длинное тире, символ многоточия,
  кудрявые кавычки, ёлочки в комментариях, знак не с клавиатуры (стрелка, знак сравнения) и – для
  проекта, который пишет в комментариях кода дефис, – среднее тире в комментарии; а также буква "ё"
  в тексте, который читает пользователь. Группа читает и файлы ресурсов проекта (`.css`, `.js`,
  `.svg`, `.html`);
- `comment/` – слог комментария: частица "бы", первое лицо, служебное слово прописными ради ударения
  и условие через тире; `comment/unknown-name` сверяет с проектом имена, которые называет
  комментарий. Группа читает комментарии модулей, описаний элементов и файлов ресурсов (правило
  имён – модулей и описаний элементов), а первое лицо и капс ударения – и в английских строках
  словаря перевода; по умолчанию группа выключена; проект, у которого комментарии
  безличны, включает её ключом `--enable comment`;
- `translation/` – английский текст словаря перевода: `translation/english-shape` читает значения
  файлов `xbsl-translation`, текст которых `xbsl translate --strict` не судит;
- `whitespace/` – хвостовые пробелы и смешанные переводы строк;
- `encoding/` – файл не в UTF-8;
- `structure/` – парность `Имя.yaml` и `Имя.xbsl`;
- `security/` – секрет в исходниках (токен, пароль, ключ);
- `form/` – обработчик формы, которого нет в модуле, и обработчик, сигнатура которого
  противоречит событию компонента (проектные правила);
- `query/` – запросы: неизвестная таблица, `ЕСТЬNULL`, именованный параметр, немедленная
  пометка удаления и стандарт про `В` с подзапросом (разобран выше).

## Включение и выключение

`--select` и `--ignore` принимают идентификатор правила, группу (часть до `/`, напр. `style`)
или букву тира `A`/`B`/`C`/`D`. Плагин может переопределить severity правила (группа
entry-points `xbsl.severity`); `XBSL_NO_PLUGINS=1` отключает плагины и возвращает встроенные
значения из этой таблицы.
