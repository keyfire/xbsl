---
title: "Правила линтера XBSL"
description: "Полный перечень проверок линтера с уровнями важности и областью применения."
sidebar:
  label: Правила
  order: 5
---

<!-- severity icons -->
<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"><symbol id="sev-error" viewBox="0 -960 960 960"><path fill="#e5484d" d="M508.5-291.5Q520-303 520-320t-11.5-28.5Q497-360 480-360t-28.5 11.5Q440-337 440-320t11.5 28.5Q463-280 480-280t28.5-11.5Zm0-160Q520-463 520-480v-160q0-17-11.5-28.5T480-680q-17 0-28.5 11.5T440-640v160q0 17 11.5 28.5T480-440q17 0 28.5-11.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol><symbol id="sev-warning" viewBox="0 -960 960 960"><path fill="#d0a215" d="M109-120q-11 0-20-5.5T75-140q-5-9-5.5-19.5T75-180l370-640q6-10 15.5-15t19.5-5q10 0 19.5 5t15.5 15l370 640q6 10 5.5 20.5T885-140q-5 9-14 14.5t-20 5.5H109Zm69-80h604L480-720 178-200Zm330.5-51.5Q520-263 520-280t-11.5-28.5Q497-320 480-320t-28.5 11.5Q440-297 440-280t11.5 28.5Q463-240 480-240t28.5-11.5Zm0-120Q520-383 520-400v-120q0-17-11.5-28.5T480-560q-17 0-28.5 11.5T440-520v120q0 17 11.5 28.5T480-360q17 0 28.5-11.5ZM480-460Z"/></symbol><symbol id="sev-info" viewBox="0 -960 960 960"><path fill="#3b82f6" d="M508.5-291.5Q520-303 520-320v-160q0-17-11.5-28.5T480-520q-17 0-28.5 11.5T440-480v160q0 17 11.5 28.5T480-280q17 0 28.5-11.5Zm0-320Q520-623 520-640t-11.5-28.5Q497-680 480-680t-28.5 11.5Q440-657 440-640t11.5 28.5Q463-600 480-600t28.5-11.5ZM480-80q-83 0-156-31.5T197-197q-54-54-85.5-127T80-480q0-83 31.5-156T197-763q54-54 127-85.5T480-880q83 0 156 31.5T763-763q54 54 85.5 127T880-480q0 83-31.5 156T763-197q-54 54-127 85.5T480-80Zm0-80q134 0 227-93t93-227q0-134-93-227t-227-93q-134 0-227 93t-93 227q0 134 93 227t227 93Zm0-320Z"/></symbol></svg>


Полный перечень проверок линтера. Файл дополняется при добавлении правил; актуальный
список в рантайме – `xbsl --list-rules` (или MCP `list_rules`). Сейчас правил: 155.

Таблица описывает инструментарий в поставке. Установленный плагин может добавить свои правила
и переопределить severity и включённость по умолчанию (см. [Расширение](/ru/servers#расширение-свои-правила-данные-и-уровни)),
поэтому список в рантайме способен отличаться от этого: `xbsl --list-rules` показывает, что
действительно работает в вашем окружении, а `XBSL_NO_PLUGINS=1` – набор ниже.

## Граница: линтер дополняет компилятор, но не заменяет его

Линтер работает по тексту, AST и модели проекта. Правила знают типы "на первом шаге":
объявленный номинальный тип переменной и его члены, объекты проекта и порождаемые ими типы,
значения перечислений, глобальные типы подключённых библиотек (из архива `.xlib`).

Вывод типа ВЫРАЖЕНИЯ у движка есть – модуль `xbsl.typeinfer` отвечает про получателя, член,
конструктор, приведение и настойчивую операцию, а вывод типов цепочек и локальных переменных
питает ховер и автодополнение в редакторе. Проверки на него не опираются: правила судят по
объявленным типам – см. ниже про то, чего линтер не делает.

Часть находок поймал бы и компилятор: неизвестный тип, число аргументов, не-исключение в
`поймать`, возврат не по сигнатуре. Здесь ценность линтера не в том, что он видит больше, а
в том, что он видит это **раньше** – за секунды на рабочей машине, до сборки и деплоя, и
показывает точное место. Остального же компилятор не проверяет вовсе: соглашения по
написанию кода, типографику, структуру проекта (дубли `Ид`, парность файлов),
неиспользуемые переменные, секреты в исходниках.

Чего линтер не делает – всё, что требует полного вывода типов выражений: избыточное
приведение, утечку ресурса в общем случае, соответствие ТИПА возвращаемого значения сигнатуре.
Два последних стоит различать. Структурное несоответствие возврата (значение в методе-ничто,
пустой `возврат` в типизированном) правило `code/return-mismatch` ловит, а `возврат` строки из
метода с `: Число` пропустит – для этого нужно вывести тип выражения. Ресурс же судится
единственной формой, где всё сказано самим объявлением: правило `code/unclosed-resource`
прослеживает закрываемое от объявления до перебора в том же методе, а ресурс, ушедший в вызовы
или коллекции, остаётся вне досягаемости.

Проверка корректности кода – серверная компиляция при деплое; линтер идёт перед ней и снимает
частые ошибки заранее.

## Как читать таблицу

- **Правило** – идентификатор `группа/имя`. Группа (часть до `/`) позволяет включать и
  выключать правила пачкой.
- **Уровень** – <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> `error` (сборка и CI должны падать), <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> `warning` (нарушено соглашение),
  <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> `info` (подсказка, обычно выключена).
- **Умолч.** – ✓ правило входит в набор по умолчанию, – включается явно.
- **Область** – `файл` (правило видит один файл) или `проект` (нужен индекс всего проекта:
  дубли Ид, неизвестные типы, кросс-модульные вызовы).
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
| `yaml/id-uuid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ид не является UUID |
| `yaml/id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | У объекта нет Ид |
| `yaml/name-matches-file` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя не совпадает с именем файла |
| `yaml/id-unique` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Дубли Ид в проекте |
| `yaml/standard-field-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Длина стандартного реквизита сверх лимита платформы (`Наименование` > 400, `Код` > 50) – применение отвергает реквизит, и он выпадает из объекта [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ссылочный тип в позиции `Тип` без `?` (`Товары.Ссылка`, `ПолеВвода<Товары.Ссылка>`) – у ссылки нет значения по умолчанию, компиляция падает `Default value initialization is not supported` [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Выражение `=...` внутри узла литерального типа (`Шрифт: {Тип: АбсолютныйШрифт, Размер: =...}`) – платформа принимает здесь только литерал, вычислять нужно весь объект [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `project/identifier` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя или поставщик проекта не идентификатор [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Представление проекта не заполнено [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Версия проекта не A.B.C [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Модуль .xbsl без парного .yaml |
| `project/path-matches-descriptor` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Путь `{{поставщик}}/{{имя}}` разошёлся с дескриптором – сборка отвергнет проект до компиляции [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ разметки, которого у компонента нет, а у ДРУГОГО компонента ui-схемы есть (`Флажок` + `ЗамещающийТекст` – свойство `ПолеВвода`): применение отвечает `Неизвестное свойство`; имя, которого нет ни у одного компонента, не трогается – документация перечисляет ключи yaml не полностью [доки](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |

### Тир B – текст и соглашения

Кодировка, переводы строк, пробелы, типографика (тире, кавычки, многоточие), длина строки,
секреты в исходниках.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `security/hardcoded-secret` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ или пароль литералом в коде |
| `typography/em-dash` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Длинное тире в комментарии |
| `typography/ellipsis` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Символ многоточия в комментарии |
| `typography/curly-quotes` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Кудрявые кавычки |
| `typography/guillemets-comment` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Ёлочки в комментарии |
| `whitespace/trailing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Хвостовые пробелы |
| `whitespace/mixed-newline` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Смешанные переводы строк |
| `encoding/utf8` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Файл не в UTF-8 |
| `style/tab-indent` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Табуляция в отступе [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Строка длиннее 120 символов [доки](https://1cmycloud.com/docs/help/topics/general-design/) |

### Тир C – структура кода, базовый синтаксис и соглашения по написанию

Баланс блоков и скобок, заголовки циклов и методов, локальные переменные и группа `style/` –
соглашения из раздела документации "Рекомендации по написанию кода". Часть правил `style/`
выключена по умолчанию (накопленный долг, `info`): включаются `--select style` для замера.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `code/parse-error` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Синтаксическая ошибка (полный разбор по грамматике платформы) [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Оператор-выражение без эффекта: значение отбрасывается (часто опечатка в ключевом слове вида `возрат 5`) |
| `code/return-mismatch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Возврат не по сигнатуре метода (значение в методе-ничто, пустой `возврат` в типизированном) – компилятор такой код отвергает [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/call-arity` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Число аргументов локального вызова вне диапазона [обязательные, все] сигнатуры [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Дисбаланс скобок () [] {} |
| `code/blocks` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Дисбаланс блоков и ';' [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Составное условие тернарного оператора без скобок [доки](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/param-type-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Параметр без типа и без значения по умолчанию [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/loop-header` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Неверный заголовок цикла 'для' [доки](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Недопустимая управляющая последовательность в строковом литерале (`\'`, регексные `\d`) – компилятор отвергает такой литерал; валидны `\н \в \т \\ \" \% \$ \ю<код>` и латинские написания [доки](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/unused-local` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Неиспользуемая локальная переменная |
| `code/unused-loop-var` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Неиспользуемая переменная цикла |
| `code/ref-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле-ссылка структуры без 'обз' [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Сравнение булева значения с Истина/Ложь [доки](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/undefined-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Проверка Неопределено оператором 'это' [доки](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| `style/negated-is` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Отрицание оператора 'это' снаружи [доки](https://1cmycloud.com/docs/help/topics/is-operator/) |
| `style/semicolon-line` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | ';' не на отдельной строке [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/wrap-operator` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Операция в конце перенесённой строки [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/wrap-comma` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Запятая в начале перенесённой строки [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/camel-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя не в UpperCamelCase [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/const-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Константа не БОЛЬШИМИ_БУКВАМИ [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/exception-prefix` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя исключения без префикса "Исключение" [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/abbreviation-case` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Аббревиатура заглавными буквами в имени [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/enum-name-vid` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя перечисления начинается с "Тип" [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/collection-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Ручное наполнение коллекции вместо литерала [доки](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| `style/redundant-tostring` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | '.ВСтроку()' в конкатенации [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Конкатенация вместо интерполяции [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пробелы вокруг двоеточия типа [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пробелы вокруг '\|' в составном типе [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Неопределено в типе без сокращения '?' [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Избыточная аннотация типа при инициализации [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/optional-params-last` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Необязательный параметр перед обязательным [доки](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `Ресурс{Ресурсы/Имя.svg}` – ключ ресурса задается ОТНОСИТЕЛЬНО каталога Ресурсы; сам каталог в ключе ломает поиск [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Именованный параметр `&Имя` внутри литерала запроса – значения в литерал передаются интерполяцией (`%Имя`) [доки](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключевое слово `этот` в теле статического метода – статический метод общий для всего типа и контекста объекта не имеет, проект компилятор отвергает [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Вызов обычного метода того же владельца по голому имени из статического метода – документация запрещает это прямо; вызывайте метод у значения либо сделайте его статическим [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `Закрыть()` внутри `ПередЗакрытием` – платформа игнорирует вызов, и форму не закрывает уже ничто |
| `query/no-isnull` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `ЕСТЬNULL(` внутри литерала запроса – такой функции в языке запросов нет |
| `style/abstract-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Абстрактное имя переменной (`Данные`, `Элемент`, `Объект`, `Строка`, `Значение`, `Документ` – точное или с числовым хвостом `Данные1`) не отражает суть; основа внутри длинного имени (`ДанныеКлиента`) и поля структур (контракт сериализации) не трогаются [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Однобуквенное имя переменной, параметра или переменной цикла – по стандарту имён односимвольными бывают только параметры коротких лямбда-выражений (`(А, Б) -> А + Б`) [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Булева переменная названа от отрицания (`НеПодключен`, `НетОшибок`) – имя образуют от истинного значения признака (`Подключен`, `ЕстьОшибки`); судится только доказанное Булево: аннотация типа или булев литерал в инициализации [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Имя переменной начинается с типа-контейнера (`МассивСтруктурИмен`, `СтруктураОтвета`) – тип виден по объявлению и подсказке редактора, в имя его не включают [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Числительное в имени константы (`ТАЙМАУТ_ОДНА_МИНУТА`) описывает её значение – константу называют абстрактно (`ТАЙМАУТ`), чтобы смена значения не ломала имя [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |

### Тир D – семантика над stdlib, формы и метамодель

Требует индекс проекта и данные платформы: неизвестные типы и объекты, значения перечислений,
модель выполнения (клиент/сервер), обработчики форм, свойства и запросы.

| Правило | | | Область | Что проверяет |
|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | ВыборЗначения без статичного СпискаВыбора [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `code/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип |
| `code/catch-non-exception` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Тип в `поймать` не исключение (stdlib-тип без сигнатуры исключения или локальная `структура`) – компилятор такой код отвергает [доки](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Обращение к отсутствующему члену переменной известного stdlib-типа – простого или дженерика, у которого аргументы типизируют члены, но не называют их (первый шаг цепочки, у опечаток подсказка) |
| `code/unknown-static-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение к отсутствующему члену по имени типа (`ДатаВремя.Минимальная()`); тип результата такого вызова переносится на следующий шаг цепочки. Голое имя читается как тип, только если проект не придаёт ему другого смысла; парный yaml модуля учитывается и при проверке одиночного файла |
| `yaml/foreign-not-public` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на элемент чужой подсистемы, у которого `ОбластьВидимости` не `ВПроекте`/`Глобально` – снаружи своей подсистемы он недоступен, и импорт не поможет [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Число аргументов вызова `Модуль.Метод(...)` вне диапазона сигнатуры модуля-адресата [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/undefined-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Неизвестное имя в выражении (опечатки вида `Адресар` вместо `Адреса`) и в короткой интерполяции строки (`"?$format=json"` – подстановка имени `format`, нужен `\$`) – компилятор такой код отвергает |
| `code/unknown-object-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип объекта проекта |
| `yaml/unknown-type` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестный тип в yaml |
| `yaml/dynlist-missing-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Нет поля динамического списка [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/dynlist-row-editing` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Обработчик `ПриРедактированииСтроки` у списка с ПЛОСКИМ динамическим источником: событие объявлено для узловых строк иерархии, у плоского списка платформа его не вызывает вовсе – по нажатию открывается автоформа объекта; дайте объекту свою форму объекта [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/Lists/List_ru/) |
| `yaml/ref-input-auto-commands` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Ссылочное `ПолеВвода` без своих `Команды`: платформа рисует рядом собственную кнопку открытия значения в отдельном окне (у ссылочного поля `Авто` разворачивается во фрагмент командного интерфейса). Чаще всего кнопка и нужна, поэтому правило информационное и выключено; глушится пустым фрагментом [доки](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/dynlist-column-sort-lost` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Колонка таблицы над динамическим списком, чьё значение – ВЫЗОВ: заголовок сортировать не будет, платформа сортирует по ПОЛЮ источника, а не по отображаемому тексту. Привязывайте колонку к полю либо добавьте поле-представление в сам список. Выключено по умолчанию: нужна ли этой колонке сортировка, из файла не видно [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Неизвестное значение перечисления [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Перечисление без nullable [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Значение свойства компонента вне списка перечисления ui-схемы (`ВыравниваниеСодержимогоПоВертикали: Конец` – по вертикали значения `Конец` нет) |
| `yaml/bare-object-value` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Голое слово в свойстве, принимающем `Объект` (`Значение: Титул`) – платформа ждёт литерал в кавычках, выражение с `=` либо `$`-ссылку локализованной строки [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Имени из `Ресурс{...}` нет ни в каталогах `Ресурсы` проекта, ни в библиотеке картинок платформы [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Обработчик формы не найден в модуле [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Серверный метод недоступен клиентскому обработчику [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-annotation-in-server-module` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Клиентская аннотация в серверном общем модуле [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Клиентский общий модуль в HTTP-сервисе [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Блок `Запрос{...}` в методе клиентского модуля (форма либо общий модуль с клиентским `Окружение`) без `@НаСервере` – на клиенте такого типа нет, сборку компилятор отвергает [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
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
| `code/reserved-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Зарезервированное имя |
| `yaml/builtin-property-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Совпадение со встроенным свойством |
| `yaml/size-needs-no-stretch` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Размер без отключения растягивания [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/matrix-group-max-width` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Числовая `МаксимальнаяШирина` у группы с матричной компоновкой: максимум – это и РАСПОЛАГАЕМАЯ ширина, автоматические колонки раскладываются по нему, а не по окну, и телефон рисует страницу десктопной шириной (контент уходит за правый край). Отдавайте `Авто`. Выключено по умолчанию: страница только для десктопа живёт с максимумом нормально [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/card-literal-stretch-weight` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Литеральный `ВесПриРастягивании` у карточки или у группы внутри неё: вес – это flex с НУЛЕВОЙ базой, а в вертикальной колонке (мобильная раскладка) база относится к высоте – Safari схлопывает карточку и обрезает её скруглением, Chrome не показывает ничего. Снимайте вес на телефоне биндингом. Выключено по умолчанию: карточка, живущая только в широком ряду, носит вес законно [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Метод нигде не используется |
| `yaml/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на публичный элемент чужой подсистемы, которой нет в секции `Импорт` [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/unused-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль импортирует подсистему, ни один элемент которой в его КОДЕ не упомянут – редактор платформы такие импорты показывает, а копятся они сами: код, которому импорт был нужен, переписан, строка осталась. Ссылка из ПАРНОГО yaml употреблением не считается: у yaml своя секция импорта [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/missing-import` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль называет тип публичного элемента чужой подсистемы, а строки импорта этой подсистемы у него нет – компиляция проекта падает на этой строке. Судятся и ЗАПИСАННЫЕ позиции типа (параметр, переменная, возврат, `новый`, `как`, `это`, аргументы обобщённого), и корень цепочки (`Модуль.Метод()`); у корня сначала вычитается всё, что объясняет имя само по себе: объявления метода и модуля, неявные имена платформы и секции ПАРНОГО yaml [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/missing-subsystem-usage` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Элементы и модули подсистемы импортируют другую подсистему, а в описании своей (`Подсистема.yaml`) её нет в блоке `Использование` – применение проекта падает, и узнаётся это только на деплое. Импорт даёт краткие имена, но саму подсистему разрешает `Использование`; замечание – на описании подсистемы, там же и правка [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/presentation-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле представления объекта [доки](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Параметр типа у свойства, которое ui-схема объявляет без параметра, – это другой тип, применение сборки его отвергнет (`ДополнительныеКоманды` формы принимают `ФрагментКомандногоИнтерфейса`, а не `ФрагментКомандногоИнтерфейса<ОбычнаяКоманда>`) [доки](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Свойство компонента новее, чем `РежимСовместимости` проекта (версию появления несёт ui-схема) – применение отвергает его как неизвестное [доки](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Условие с пометкой удаления в запросе к объекту с `РежимУдаления: Немедленно` – поля пометки у него нет, запрос падает применением [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/item-id-required` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Элемент коллекции метаданных (реквизит, табличная часть, элемент перечисления, параметр ключа доступа) без `Ид`, который объявляет его класс – применение отвечает `ID required` |
| `code/unknown-row-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Поле строки динамического списка (`СтрокаДинамическогоСписка<Форма.Тип>`), которого нет среди `Поля` списка [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Поле динамического списка, взятое через ссылку (`Абонент.Номер`), имеет тип `<тип>|Null` и не годится типизированному полю структуры – компилятор отвечает `Null cannot be assigned` [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ, которого класс самого реквизита не объявляет (`Длина` у обычного реквизита – её объявляет стандартный `Код`, а у числового есть `ДлинаЦелойЧасти`) – применение сборки отвергает объект |
| `yaml/empty-group-sized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Пустая `Группа` с `Высота`/`Ширина` – рендер выбрасывает узел, зазора не будет |
| `yaml/insert-row-needs-align` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Горизонтальная группа со вставкой `КонтейнерHtml` и без `ВыравниваниеСодержимогоПоВертикали`: дети равняются ПО БАЗОВОЙ ЛИНИИ, а у вставки она своя – элемент со вставкой съезжает вниз относительно соседей (на живом ряду 50 px). Отвечает ближайший горизонтальный предок, поэтому ряд с уже выровненной внутренней полосой молчит [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `yaml/hint-too-long` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `Подсказка` длиннее предела отрисовки – хвост не показывается вовсе |
| `yaml/date-input-needs-plain-date` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | `ПолеВвода<Дата?>` – поле ввода даты, допускающей пустое значение, рендер молча не рисует; тип делается непустым, "не задано" – пустая дата [доки](https://1cmycloud.com/docs/help/topics/edit-component/) |
| `yaml/binding-needs-auto` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Биндинг свойства без пустого значения зовёт метод с nullable-возвратом – клиент регистрирует "Неожиданное значение" на каждом пересчёте; "не задано" – это значение Авто |
| `code/client-available-needs-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | `@ДоступноСКлиента` у метода модуля компонента интерфейса, который не статический и без `@Контекстный` – тип компонента не синглтонный, применение отвергает модификатор [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение `Модуль.Член(...)` к общему модулю с `Окружение: Сервер` из метода, исполняемого на клиенте (компонент интерфейса, команда, клиентский общий модуль) – на клиенте типа нет [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/component-in-server-context` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение `Компонент.Член(...)` к компоненту интерфейса из кода, компилируемого для сервера – метод `@НаСервере` где угодно либо метод без аннотации в серверном или клиент-серверном модуле: тип компонента живёт на клиенте, и серверная компиляция отвечает "Переменная X не определена" [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | `ПриУдаленииОбъектаПоСсылке: УдалятьТекущий` у реквизита владельца, чей `РежимУдаления` только помечает (`ПометкаУдаления` – это ещё и умолчание) – применение отвечает `Action УдалятьТекущий cannot apply to object with a DeletionMark` [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/per-object-permissions-need-common` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Объект вычисляет разрешения для каждого объекта, но в его модуле нет обработчика `ВычислитьРазрешенияДоступа` – общий расчёт обязателен и при per-object, пусть и возвращает пустой массив [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | В `ВычислитьРазрешенияДоступаДляОбъектов` читается поле, которого нет среди `РасчетРазрешенийПо`, либо объявленное поле берётся через `Сущность` вместо `Запись` [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-handlers-need-recalc` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Модуль объявляет обработчик разрешений (`ВычислитьРазрешенияДоступа` и родня), а `ПересчитатьРазрешенияДоступа` этой сущности не вызван нигде в проекте – платформа обработчик сама не вызывает, и правка прав молча не действует; пересчёт с получателем не-сущностью (документированный цикл) глушит правило, виды без метода пересчёта (право-элементы) не судятся [доки](https://1cmycloud.com/docs/help/topics/recalculate-access-permissions-and-keys/) |
| `yaml/placeholder-key-in-strings` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Ключ с подстановкой `$0` в секции `Строки` словаря `ЛокализованныеСтроки`: секция компилируется в метод БЕЗ параметров, и вызов с аргументом падает на применении "Неизвестный метод" [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `yaml/localization-ref-to-template` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Ссылка `$Словарь.Ключ` указывает на ключ секции `Шаблоны`: ссылка ищет ключ только в `Строки`, и применение падает с "Не удалось найти локализованную строку" (стенд откатывается). Ключ шаблонов, на который никто не ссылается, не судится – из кода его зовут законно [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/compare-with-localized` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Локализованное значение (`Словарь.Ключ()`, `Представление()`) сравнивается с литералом или со вторым локализованным – на другом языке ветка молча не срабатывает [доки](https://1cmycloud.com/docs/help/topics/app-localization/) |
| `code/url-params-partial-encoding` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="info"><use href="#sev-info"/></svg> | – | файл | Вызов метода Url `СПараметрамиЗапроса`: значение параметра кодируется частично – "&" и "=" внутри значения остаются разделителями, и значение-адрес приходит обрезанным по первому "&"; строку собирать самим объектом параметров и клеить к базовому адресу. Выключено по умолчанию: видны ли "&" в значениях, статически не решается [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Http/Url_ru/) |
| `code/bound-property-assign` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Свойство, ВЫЧИСЛЯЕМОЕ выражением в парной разметке (`Высота: =Общее.ЭтоМобильный()?820:528`), присваивается из кода – платформа такое присваивание отвергает, а в попытка/поймать отказ не виден; связь с данными (голый путь) не трогается, она двунаправленная по устройству |
| `yaml/event-needs-importance` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | В описании `СобытиеЖурналаСобытий` не задана `Важность`: её умолчание – `ИзКонструктора`, и тогда платформа требует значение в КАЖДОМ конструкторе, а пропуск хотя бы в одном месте записи роняет применение на строке конструктора; явное `Важность: ИзКонструктора` объявляет выбор и снимает предупреждение [доки](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | файл | Поле структуры с обобщённым типом без конструктора без аргументов (`ЧитаемыйМассив<Строка>`) и без `обз`, `?` или инициализатора – применение отвечает "не может быть проинициализировано значением по умолчанию"; `Массив<Строка>` и подобные конструируются пустыми и не трогаются [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Переменная объявлена одним типом, у которого нет ни конструктора, ни значения по умолчанию (`пер Ответ: ОтветHttp`) – компиляция отвечает "не имеет конструктора и значения по умолчанию"; перечисление, аннотация, одиночка и имя, перекрытое типом проекта, пропускаются [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение к отсутствующему члену коллекции строк табличной части (`Объект.Секция.Член` в модуле формы объекта, голое имя секции или `этот.Секция` в модулях сущности) – коллекция это `Массив<Сущность.Секция>`, и привычное из другой платформы `Количество()` здесь зовётся `Размер()`; секцию затеняет одноимённый модуль, реквизиты не судятся |
| `code/global-unavailable` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Вызов глобального имени вне его окружения: `Сообщить` (только клиент) в серверном модуле – применение отвечает "Метод недоступен в текущем окружении", `Вычислить` (только сервер) в клиентском методе без `@НаСервере`; `@НаКлиенте`/`@НаСервере` переопределяют окружение модуля, доступность имён – из строк "Доступность" пакетов глобального контекста [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Переменная, параметр или метод с именем элемента проекта (`знч Склады` при справочнике `Склады`) – объявление закрывает обращение к элементу из этой области; платформенные имена параметров обработчиков с именами проекта не пересекаются [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `style/shadow-own-property` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Локальная ПЕРЕМЕННАЯ с именем свойства своего же элемента: внутри метода имя разрешается в переменную, и присваивание до свойства не доходит. Судятся только модули, где такое свойство в области видимости, – компонента интерфейса и объекта; параметр с тем же именем это обычный способ передать значение и не судится [доки](https://1cmycloud.com/docs/help/topics/name-scope/) |
| `code/unclosed-resource` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | файл | Закрываемый ресурс (`знч Выборка = Запрос{...}.Выполнить()`), брошенный досрочным выходом из перебора: полный проход платформа закрывает сама, а `возврат` или `прервать` в середине оставляет ресурс открытым, и платформа пишет в журнал событий незакрытый ресурс; объявление через `исп` закрывает его на любом пути выхода. Ресурс, пришедший параметром, закрытый вручную и возвращённый вызывающему, оставлены автору [доки](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `conventions/untranslated-visible-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | ✓ | проект | Видимый текст, оставшийся кириллическим литералом там, где то же свойство проект уже вынес ссылкой на словарь локализации – намерение считается в разрезе вида элемента, и свойство-тёзка другого вида не судится; молчит на проекте, у которого в дескрипторе меньше двух языков локализации |
| `conventions/untranslated-code-literal` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="warning"><use href="#sev-warning"/></svg> | – | проект | Видимый текст, оставшийся кириллическим литералом В МОДУЛЕ – судится по СТОКУ, куда он попадает (аргумент платформенного вызова сообщения, свойство события журнала или то же самое через метод, пробрасывающий свой параметр); разметка, чистая интерполяция и одиночные слова пропускаются, а на проекте с менее чем двумя языками локализации правило молчит |
| `code/unknown-structure-field` | <svg width="16" height="16" style="display:inline-block;vertical-align:-3px" aria-label="error"><use href="#sev-error"/></svg> | ✓ | проект | Обращение к полю структуры, объявленной В ПРОЕКТЕ, сверяется с её объявлением: переименовали поле – потребитель в другом модуле краснеет здесь, а не на серверной компиляции. Тип берётся из объявления переменной (`Модуль.Структура`, голое имя структуры своего модуля), из конструктора `новый` и из элемента коллекции в `для X из Список`; имя, объявленное в методе ещё чем-нибудь, тёзка stdlib-типа, второй шаг цепочки и латинские написания члена не судятся |

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
Это разбор морфологический, а не по окончаниям: `Номенклатура` единственного числа стандарту не
противоречит, а `Задачи` и `Партии` без падежа читаются как родительный падеж единственного.
Нужен extra `[morph]` (`pip install "xbsl[morph]"`); без него правило молчит.

Остальное: буква `ё` и подчёркивания в именах, аббревиатура одним словом (`Ндс`, а не `НДС`),
англоязычный термин оригиналом (`Xml`, а не `Хмл`), `Вид` вместо `Тип` у перечислений, вид
элемента внутри его имени (`ОтчетЗависшиеЗадачи`), слова-пустышки (`Управление`, `Менеджер`),
постфикс окружения у общего модуля (`ОбменДаннымиКлиентИСервер` – окружение задаётся свойством),
булев реквизит через отрицание (`НетОшибок` вместо `Успешно`), незаполненное `Представление` и
обязательные префиксы отдельных видов (`КлючДоступа`, `ПравоНа`, `Навигация`).

### Соглашения по написанию кода (правила `style/`)

Двадцать восемь правил по документации платформы ("Соглашения по написанию кода", "Идиомы
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

Правила, которым чистый код уже соответствует, включены по умолчанию (`warning`) – они защищают
от регресса. Правила, под которые обычно накоплен долг, идут как `info` и выключены – их включают,
чтобы замерить долг и убирать его:

```sh
xbsl путь/к/исходникам --select style     # все соглашения, включая выключенные
xbsl путь/к/исходникам --ignore style     # без них
```

Блоки `Запрос{ ... }` (отдельный DSL) и строковые литералы (HTML/CSS/SVG вставок) из этих проверок
исключены. Не проверяются и остаются на авторе с ревью: кратность отступа четырём, идиомы
коллекций, `Строки.Соединить()` при массовой конкатенации, идиомы `?.` / `??` и `выбор` вместо
цепочки `иначе если`.

### Семантика кода (правила `code/`)

Самая большая группа – пятьдесят три правила, тридцать из них ошибки. Это то, что компилятор
отвергнет или что платформа выполнит не так, как читается: неизвестное имя или член типа, число
аргументов вызова, окружение (клиентский код в серверном методе и наоборот), обращение к
экземпляру через тип, неперехваченное не-исключение, незакрытый ресурс, обход по коллекции при
её изменении, а также обходы платформенных ловушек, у которых нет иного признака, кроме формы
кода. Часть правил проектные (`--stdin` их не гоняет): им нужны парный yaml и имена объектов.

### Описания элементов (правила `yaml/`)

Тридцать девять правил по описаниям (`.yaml`): обязательные и уникальные `Ид`, известные ключи
и типы, ссылки на компоненты, обработчики и локализованные строки, требования платформы к типам
полей (ссылка и перечисление допускают пустое значение), настройки динамических списков и форм,
а также ловушки вёрстки, которые применяются без ошибки, но рисуются не так, как задумано.
Пять правил – `info` и выключены: они говорят "так работает платформа", а не "здесь ошибка".

### Мелкие группы

- `typography/` – типографские символы в прозе и комментариях: длинное тире, символ многоточия,
  кудрявые кавычки, ёлочки в комментариях;
- `whitespace/` – хвостовые пробелы и смешанные переводы строк;
- `encoding/` – файл не в UTF-8;
- `structure/` – парность `Имя.yaml` и `Имя.xbsl`;
- `security/` – секрет в исходниках (токен, пароль, ключ);
- `form/` – обработчик формы, которого нет в модуле (проектное правило);
- `query/` – запросы: неизвестная таблица, `ЕСТЬNULL`, именованный параметр, немедленная
  пометка удаления и стандарт про `В` с подзапросом (разобран выше).

## Включение и выключение

`--select` и `--ignore` принимают идентификатор правила, группу (часть до `/`, напр. `style`)
или букву тира `A`/`B`/`C`/`D`. Плагин может переопределить severity правила (группа
entry-points `xbsl.severity`); `XBSL_NO_PLUGINS=1` отключает плагины и возвращает встроенные
значения из этой таблицы.
