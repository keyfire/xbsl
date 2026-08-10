---
title: "Правила линтера XBSL"
description: "Полный перечень проверок линтера с уровнями важности и областью применения."
sidebar:
  label: Правила
  order: 5
---

Полный перечень проверок линтера. Файл дополняется при добавлении правил; актуальный
список в рантайме – `xbsl --list-rules` (или MCP `list_rules`). Сейчас правил: 139.

Таблица описывает инструментарий в поставке. Установленный плагин может добавить свои правила
и переопределить severity и включённость по умолчанию (см. [Расширение](/ru/servers#расширение-свои-правила-данные-и-уровни)),
поэтому список в рантайме способен отличаться от этого: `xbsl --list-rules` показывает, что
действительно работает в вашем окружении, а `XBSL_NO_PLUGINS=1` – набор ниже.

## Граница: линтер дополняет компилятор, но не заменяет его

Линтер работает по тексту, AST и модели проекта. Правила знают типы "на первом шаге":
объявленный номинальный тип переменной и его члены, объекты проекта и порождаемые ими типы,
значения перечислений, глобальные типы подключённых библиотек (из архива `.xlib`) – но тип
выражения не выводят. Вывод типов цепочек у движка есть, но питает он ховер и автодополнение
в редакторе, а не проверки.

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
- **Уровень** – <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> `error` (сборка и CI должны падать), <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> `warning` (нарушено соглашение),
  <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> `info` (подсказка, обычно выключена).
- **Умолч.** – ✓ правило входит в набор по умолчанию, – включается явно.
- **Область** – `файл` (правило видит один файл) или `проект` (нужен индекс всего проекта:
  дубли Ид, неизвестные типы, кросс-модульные вызовы).
- **Документация** – ссылка на раздел документации платформы, стоящий за правилом. В VS Code
  код такого правила в панели "Проблемы" открывает этот раздел прямо в редакторе.

## Тиры

Правила разбиты на тиры A–D по тому, на что они опираются. Тир – это и есть быстрый фильтр
для `--select`/`--ignore` (наряду с группой и идентификатором): `--select A,B` гоняет только
структуру и текст, `--ignore D` убирает семантику над stdlib.

**Как читать колонки:** <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> error · <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> warning · <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> info; ✓ – входит в набор по умолчанию, – включается явно; область – один файл или весь проект.

### Тир A – структура и YAML

Файл существует, парсится, у объекта есть уникальный UUID, имя совпадает с файлом.

| Правило | | | Область | Что проверяет | Док. |
|---|---|---|---|---|---|
| `yaml/valid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | YAML не парсится | – |
| `yaml/id-uuid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ид не является UUID | – |
| `yaml/id-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | У объекта нет Ид | – |
| `yaml/name-matches-file` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя не совпадает с именем файла | – |
| `yaml/id-unique` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Дубли Ид в проекте | – |
| `yaml/standard-field-length` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Длина стандартного реквизита сверх лимита платформы (`Наименование` > 400, `Код` > 50) – применение отвергает реквизит, и он выпадает из объекта | [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/ref-needs-nullable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ссылочный тип в позиции `Тип` без `?` (`Товары.Ссылка`, `ПолеВвода<Товары.Ссылка>`) – у ссылки нет значения по умолчанию, компиляция падает `Default value initialization is not supported` | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `yaml/no-expression-in-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Выражение `=...` внутри узла литерального типа (`Шрифт: {Тип: АбсолютныйШрифт, Размер: =...}`) – платформа принимает здесь только литерал, вычислять нужно весь объект | [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `project/identifier` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя или поставщик проекта не идентификатор | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/presentation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Представление проекта не заполнено | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `project/version` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Версия проекта не A.B.C | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `structure/xbsl-pair` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Модуль .xbsl без парного .yaml | – |
| `project/path-matches-descriptor` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Путь `{{поставщик}}/{{имя}}` разошёлся с дескриптором – сборка отвергнет проект до компиляции | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| `yaml/unknown-component-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ключ разметки, которого у компонента нет, а у ДРУГОГО компонента ui-схемы есть (`Флажок` + `ЗамещающийТекст` – свойство `ПолеВвода`): применение отвечает `Неизвестное свойство`; имя, которого нет ни у одного компонента, не трогается – документация перечисляет ключи yaml не полностью | [доки](https://1cmycloud.com/docs/help/topics/system-and-interface-components/) |

### Тир B – текст и соглашения

Кодировка, переводы строк, пробелы, типографика (тире, кавычки, многоточие), длина строки,
секреты в исходниках.

| Правило | | | Область | Что проверяет | Док. |
|---|---|---|---|---|---|
| `security/hardcoded-secret` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ключ или пароль литералом в коде | – |
| `typography/em-dash` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | файл | Длинное тире в комментарии | – |
| `typography/ellipsis` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Символ многоточия в комментарии | – |
| `typography/curly-quotes` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Кудрявые кавычки | – |
| `typography/guillemets-comment` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | файл | Ёлочки в комментарии | – |
| `whitespace/trailing` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Хвостовые пробелы | – |
| `whitespace/mixed-newline` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Смешанные переводы строк | – |
| `encoding/utf8` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Файл не в UTF-8 | – |
| `style/tab-indent` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Табуляция в отступе | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/line-length` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Строка длиннее 120 символов | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |

### Тир C – структура кода, базовый синтаксис и соглашения по написанию

Баланс блоков и скобок, заголовки циклов и методов, локальные переменные и группа `style/` –
соглашения из раздела документации "Рекомендации по написанию кода". Часть правил `style/`
выключена по умолчанию (накопленный долг, `info`): включаются `--select style` для замера.

| Правило | | | Область | Что проверяет | Док. |
|---|---|---|---|---|---|
| `code/parse-error` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Синтаксическая ошибка (полный разбор по грамматике платформы) | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/statement-no-effect` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Оператор-выражение без эффекта: значение отбрасывается (часто опечатка в ключевом слове вида `возрат 5`) | – |
| `code/return-mismatch` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Возврат не по сигнатуре метода (значение в методе-ничто, пустой `возврат` в типизированном) – компилятор такой код отвергает | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/call-arity` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Число аргументов локального вызова вне диапазона [обязательные, все] сигнатуры | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/brackets` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Дисбаланс скобок () [] {} | – |
| `code/blocks` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Дисбаланс блоков и ';' | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `code/ternary-and-or` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Составное условие тернарного оператора без скобок | [доки](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| `code/param-type-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Параметр без типа и без значения по умолчанию | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/loop-header` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Неверный заголовок цикла 'для' | [доки](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| `code/invalid-string-escape` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Недопустимая управляющая последовательность в строковом литерале (`\'`, регексные `\d`) – компилятор отвергает такой литерал; валидны `\н \в \т \\ \" \% \$ \ю<код>` и латинские написания | [доки](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| `code/unused-local` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Неиспользуемая локальная переменная | – |
| `code/unused-loop-var` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Неиспользуемая переменная цикла | – |
| `code/ref-field-needs-req` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Поле-ссылка структуры без 'обз' | [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `style/boolean-compare` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Сравнение булева значения с Истина/Ложь | [доки](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| `style/undefined-is` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Проверка Неопределено оператором 'это' | [доки](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| `style/negated-is` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Отрицание оператора 'это' снаружи | [доки](https://1cmycloud.com/docs/help/topics/is-operator/) |
| `style/semicolon-line` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | ';' не на отдельной строке | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| `style/wrap-operator` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Операция в конце перенесённой строки | [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/wrap-comma` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Запятая в начале перенесённой строки | [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| `style/camel-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя не в UpperCamelCase | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/const-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Константа не БОЛЬШИМИ_БУКВАМИ | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/exception-prefix` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя исключения без префикса "Исключение" | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/abbreviation-case` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Аббревиатура заглавными буквами в имени | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/enum-name-vid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя перечисления начинается с "Тип" | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/collection-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Ручное наполнение коллекции вместо литерала | [доки](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| `style/redundant-tostring` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | '.ВСтроку()' в конкатенации | [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/interpolation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Конкатенация вместо интерполяции | [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| `style/type-colon-space` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Пробелы вокруг двоеточия типа | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/union-spaces` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Пробелы вокруг '\|' в составном типе | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/nullable-shorthand` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Неопределено в типе без сокращения '?' | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/redundant-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Избыточная аннотация типа при инициализации | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| `style/optional-params-last` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Необязательный параметр перед обязательным | [доки](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| `code/resource-bare-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | `Ресурс{Ресурсы/Имя.svg}` – ключ ресурса задается ОТНОСИТЕЛЬНО каталога Ресурсы; сам каталог в ключе ломает поиск | [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `query/named-parameter` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Именованный параметр `&Имя` внутри литерала запроса – значения в литерал передаются интерполяцией (`%Имя`) | [доки](https://1cmycloud.com/docs/help/topics/query-literal/) |
| `code/this-in-static-method` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ключевое слово `этот` в теле статического метода – статический метод общий для всего типа и контекста объекта не имеет, проект компилятор отвергает | [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/instance-call-from-static` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Вызов обычного метода того же владельца по голому имени из статического метода – документация запрещает это прямо; вызывайте метод у значения либо сделайте его статическим | [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| `code/close-in-before-close` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | `Закрыть()` внутри `ПередЗакрытием` – платформа игнорирует вызов, и форму не закрывает уже ничто | – |
| `query/no-isnull` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | `ЕСТЬNULL(` внутри литерала запроса – такой функции в языке запросов нет | – |
| `style/abstract-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Абстрактное имя переменной (`Данные`, `Элемент`, `Объект`, `Строка`, `Значение`, `Документ` – точное или с числовым хвостом `Данные1`) не отражает суть; основа внутри длинного имени (`ДанныеКлиента`) и поля структур (контракт сериализации) не трогаются | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/single-letter-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Однобуквенное имя переменной, параметра или переменной цикла – по стандарту имён односимвольными бывают только параметры коротких лямбда-выражений (`(А, Б) -> А + Б`) | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/negated-boolean-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Булева переменная названа от отрицания (`НеПодключен`, `НетОшибок`) – имя образуют от истинного значения признака (`Подключен`, `ЕстьОшибки`); судится только доказанное Булево: аннотация типа или булев литерал в инициализации | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/type-in-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя переменной начинается с типа-контейнера (`МассивСтруктурИмен`, `СтруктураОтвета`) – тип виден по объявлению и подсказке редактора, в имя его не включают | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `style/numeral-in-const-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Числительное в имени константы (`ТАЙМАУТ_ОДНА_МИНУТА`) описывает её значение – константу называют абстрактно (`ТАЙМАУТ`), чтобы смена значения не ломала имя | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |

### Тир D – семантика над stdlib, формы и метамодель

Требует индекс проекта и данные платформы: неизвестные типы и объекты, значения перечислений,
модель выполнения (клиент/сервер), обработчики форм, свойства и запросы.

| Правило | | | Область | Что проверяет | Док. |
|---|---|---|---|---|---|
| `yaml/choice-needs-static-list` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | ВыборЗначения без статичного СпискаВыбора | [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| `code/unknown-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестный тип | – |
| `code/catch-non-exception` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Тип в `поймать` не исключение (stdlib-тип без сигнатуры исключения или локальная `структура`) – компилятор такой код отвергает | [доки](https://1cmycloud.com/docs/help/topics/exceptions/) |
| `code/unknown-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Обращение к отсутствующему члену переменной известного stdlib-типа – простого или дженерика, у которого аргументы типизируют члены, но не называют их (первый шаг цепочки, у опечаток подсказка) | – |
| `code/unknown-static-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Обращение к отсутствующему члену по имени типа (`ДатаВремя.Минимальная()`); тип результата такого вызова переносится на следующий шаг цепочки. Голое имя читается как тип, только если проект не придаёт ему другого смысла; парный yaml модуля учитывается и при проверке одиночного файла | – |
| `yaml/foreign-not-public` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на элемент чужой подсистемы, у которого `ОбластьВидимости` не `ВПроекте`/`Глобально` – снаружи своей подсистемы он недоступен, и импорт не поможет | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/call-arity-cross` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Число аргументов вызова `Модуль.Метод(...)` вне диапазона сигнатуры модуля-адресата | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| `code/undefined-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Неизвестное имя в выражении (опечатки вида `Адресар` вместо `Адреса`) и в короткой интерполяции строки (`"?$format=json"` – подстановка имени `format`, нужен `\$`) – компилятор такой код отвергает | – |
| `code/unknown-object-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестный тип объекта проекта | – |
| `yaml/unknown-type` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестный тип в yaml | – |
| `yaml/dynlist-missing-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Нет поля динамического списка | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/unknown-enum-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестное значение перечисления | [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/enum-needs-nullable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Перечисление без nullable | [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| `yaml/unknown-enum-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Значение свойства компонента вне списка перечисления ui-схемы (`ВыравниваниеСодержимогоПоВертикали: Конец` – по вертикали значения `Конец` нет) | – |
| `yaml/bare-object-value` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Голое слово в свойстве, принимающем `Объект` (`Значение: Титул`) – платформа ждёт литерал в кавычках, выражение с `=` либо `$`-ссылку локализованной строки | [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| `code/unknown-resource` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Имени из `Ресурс{...}` нет ни в каталогах `Ресурсы` проекта, ни в библиотеке картинок платформы | [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| `form/unknown-handler` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Обработчик формы не найден в модуле | [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| `code/server-call-from-handler` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Серверный метод недоступен клиентскому обработчику | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-annotation-in-server-module` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Клиентская аннотация в серверном общем модуле | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/client-module-in-http-service` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Клиентский общий модуль в HTTP-сервисе | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/query-needs-server` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Блок `Запрос{...}` в методе клиентского модуля (форма либо общий модуль с клиентским `Окружение`) без `@НаСервере` – на клиенте такого типа нет, сборку компилятор отвергает | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/local-method-cross-component` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Кросс-компонентный вызов локального метода | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `code/local-method-cross-module` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Межмодульный вызов локального метода | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `naming/yo` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Буква "ё" в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/underscore` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Подчёркивание в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/abbreviation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Аббревиатура заглавными буквами в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/latin-term` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Англоязычный термин записан русскими буквами | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/enum-vid` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя перечисления со словом "Тип" | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/kind-in-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Вид элемента в его имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/filler-word` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Слово-пустышка в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/module-suffix` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Постфикс окружения в имени общего модуля | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/number` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Число имени не по виду элемента | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/boolean-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя булева реквизита | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/presentation` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Представление элемента | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `naming/prefix-by-kind` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Имя вида без обязательного префикса | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| `code/unknown-ns-object` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестный объект в пространстве имён вида | – |
| `query/unknown-table` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Неизвестная таблица в запросе | [доки](https://1cmycloud.com/docs/help/topics/select-from/) |
| `query/in-subquery-composite` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | 'В' с подзапросом по составному типу | [доки](https://1cmycloud.com/docs/help/topics/in-expression/) |
| `yaml/unknown-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Неизвестное свойство объекта | – |
| `code/reserved-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Зарезервированное имя | – |
| `yaml/builtin-property-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Совпадение со встроенным свойством | – |
| `yaml/size-needs-no-stretch` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-info.svg" width="16" alt="info"> | – | файл | Размер без отключения растягивания | [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| `code/unused-method` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | – | проект | Метод нигде не используется | – |
| `yaml/missing-import` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на публичный элемент чужой подсистемы, которой нет в секции `Импорт` | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| `yaml/presentation-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Поле представления объекта | [доки](https://1cmycloud.com/docs/help/topics/element-view/) |
| `yaml/unexpected-type-argument` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Параметр типа у свойства, которое ui-схема объявляет без параметра, – это другой тип, применение сборки его отвергнет (`ДополнительныеКоманды` формы принимают `ФрагментКомандногоИнтерфейса`, а не `ФрагментКомандногоИнтерфейса<ОбычнаяКоманда>`) | [доки](https://1cmycloud.com/docs/help/topics/command-interface/) |
| `yaml/property-since-compat` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Свойство компонента новее, чем `РежимСовместимости` проекта (версию появления несёт ui-схема) – применение отвергает его как неизвестное | [доки](https://1cmycloud.com/docs/help/topics/update-server/) |
| `query/deletion-mark-immediate` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Условие с пометкой удаления в запросе к объекту с `РежимУдаления: Немедленно` – поля пометки у него нет, запрос падает применением | [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `yaml/item-id-required` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Элемент коллекции метаданных (реквизит, табличная часть, элемент перечисления, параметр ключа доступа) без `Ид`, который объявляет его класс – применение отвечает `ID required` | – |
| `code/unknown-row-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Поле строки динамического списка (`СтрокаДинамическогоСписка<Форма.Тип>`), которого нет среди `Поля` списка | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `code/row-field-null` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Поле динамического списка, взятое через ссылку (`Абонент.Номер`), имеет тип `<тип>|Null` и не годится типизированному полю структуры – компилятор отвечает `Null cannot be assigned` | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| `yaml/unknown-attribute-property` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ключ, которого класс самого реквизита не объявляет (`Длина` у обычного реквизита – её объявляет стандартный `Код`, а у числового есть `ДлинаЦелойЧасти`) – применение сборки отвергает объект | – |
| `yaml/empty-group-sized` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Пустая `Группа` с `Высота`/`Ширина` – рендер выбрасывает узел, зазора не будет | – |
| `yaml/hint-too-long` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | `Подсказка` длиннее предела отрисовки – хвост не показывается вовсе | – |
| `code/client-available-needs-context` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | `@ДоступноСКлиента` у метода модуля компонента интерфейса, который не статический и без `@Контекстный` – тип компонента не синглтонный, применение отвергает модификатор | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `code/server-module-in-client-context` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Обращение `Модуль.Член(...)` к общему модулю с `Окружение: Сервер` из метода, исполняемого на клиенте (компонент интерфейса, команда, клиентский общий модуль) – на клиенте типа нет | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `yaml/delete-current-needs-immediate` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | `ПриУдаленииОбъектаПоСсылке: УдалятьТекущий` у реквизита владельца, чей `РежимУдаления` только помечает (`ПометкаУдаления` – это ещё и умолчание) – применение отвечает `Action УдалятьТекущий cannot apply to object with a DeletionMark` | [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| `code/per-object-permissions-need-common` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Объект вычисляет разрешения для каждого объекта, но в его модуле нет обработчика `ВычислитьРазрешенияДоступа` – общий расчёт обязателен и при per-object, пусть и возвращает пустой массив | [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `code/permission-field-not-declared` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | В `ВычислитьРазрешенияДоступаДляОбъектов` читается поле, которого нет среди `РасчетРазрешенийПо`, либо объявленное поле берётся через `Сущность` вместо `Запись` | [доки](https://1cmycloud.com/docs/help/topics/project-element-permissions/) |
| `yaml/placeholder-key-in-strings` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Ключ с подстановкой `$0` в секции `Строки` словаря `ЛокализованныеСтроки`: секция компилируется в метод БЕЗ параметров, и вызов с аргументом падает на применении "Неизвестный метод" | [доки](https://1cmycloud.com/docs/help/topics/localization/) |
| `code/compare-with-localized` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Локализованное значение (`Словарь.Ключ()`, `Представление()`) сравнивается с литералом или со вторым локализованным – на другом языке ветка молча не срабатывает | [доки](https://1cmycloud.com/docs/help/topics/localization/) |
| `code/bound-property-assign` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Свойство, ВЫЧИСЛЯЕМОЕ выражением в парной разметке (`Высота: =Общее.ЭтоМобильный()?820:528`), присваивается из кода – платформа такое присваивание отвергает, а в попытка/поймать отказ не виден; связь с данными (голый путь) не трогается, она двунаправленная по устройству | – |
| `yaml/event-needs-importance` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | В описании `СобытиеЖурналаСобытий` не задана `Важность`: её умолчание – `ИзКонструктора`, и тогда платформа требует значение в КАЖДОМ конструкторе, а пропуск хотя бы в одном месте записи роняет применение на строке конструктора; явное `Важность: ИзКонструктора` объявляет выбор и снимает предупреждение | [доки](https://1cmycloud.com/docs/help/topics/event-properties/) |
| `code/collection-field-needs-req` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | файл | Поле структуры с обобщённым типом без конструктора без аргументов (`ЧитаемыйМассив<Строка>`) и без `обз`, `?` или инициализатора – применение отвечает "не может быть проинициализировано значением по умолчанию"; `Массив<Строка>` и подобные конструируются пустыми и не трогаются | [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| `code/var-needs-init` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Переменная объявлена одним типом, у которого нет ни конструктора, ни значения по умолчанию (`пер Ответ: ОтветHttp`) – компиляция отвечает "не имеет конструктора и значения по умолчанию"; перечисление, аннотация, одиночка и имя, перекрытое типом проекта, пропускаются | [доки](https://1cmycloud.com/docs/help/topics/variable-declaration-statement/) |
| `code/unknown-tabular-member` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Обращение к отсутствующему члену коллекции строк табличной части (`Объект.Секция.Член` в модуле формы объекта, голое имя секции или `этот.Секция` в модулях сущности) – коллекция это `Массив<Сущность.Секция>`, и привычное из другой платформы `Количество()` здесь зовётся `Размер()`; секцию затеняет одноимённый модуль, реквизиты не судятся | – |
| `code/global-unavailable` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Вызов глобального имени вне его окружения: `Сообщить` (только клиент) в серверном модуле – применение отвечает "Метод недоступен в текущем окружении", `Вычислить` (только сервер) в клиентском методе без `@НаСервере`; `@НаКлиенте`/`@НаСервере` переопределяют окружение модуля, доступность имён – из строк "Доступность" пакетов глобального контекста | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| `style/shadow-project-name` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Переменная, параметр или метод с именем элемента проекта (`знч Склады` при справочнике `Склады`) – объявление закрывает обращение к элементу из этой области; платформенные имена параметров обработчиков с именами проекта не пересекаются | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| `code/unclosed-resource` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | файл | Закрываемый ресурс (`знч Выборка = Запрос{...}.Выполнить()`), брошенный досрочным выходом из перебора: полный проход платформа закрывает сама, а `возврат` или `прервать` в середине оставляет ресурс открытым, и платформа пишет в журнал событий незакрытый ресурс; объявление через `исп` закрывает его на любом пути выхода. Ресурс, пришедший параметром, закрытый вручную и возвращённый вызывающему, оставлены автору | [доки](https://1cmycloud.com/docs/help/topics/closeable-type/) |
| `conventions/untranslated-visible-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | ✓ | проект | Видимый текст, оставшийся кириллическим литералом там, где то же свойство проект уже вынес ссылкой на словарь локализации – намерение считается в разрезе вида элемента, и свойство-тёзка другого вида не судится; молчит на проекте, у которого в дескрипторе меньше двух языков локализации | – |
| `conventions/untranslated-code-literal` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-warning.svg" width="16" alt="warning"> | – | проект | Видимый текст, оставшийся кириллическим литералом В МОДУЛЕ – судится по СТОКУ, куда он попадает (аргумент платформенного вызова сообщения, свойство события журнала или то же самое через метод, пробрасывающий свой параметр); разметка, чистая интерполяция и одиночные слова пропускаются, а на проекте с менее чем двумя языками локализации правило молчит | – |
| `code/unknown-structure-field` | <img src="https://raw.githubusercontent.com/keyfire/xbsl/main/docs/icons/severity-error.svg" width="16" alt="error"> | ✓ | проект | Обращение к полю структуры, объявленной В ПРОЕКТЕ, сверяется с её объявлением: переименовали поле – потребитель в другом модуле краснеет здесь, а не на серверной компиляции. Тип берётся из объявления переменной (`Модуль.Структура`, голое имя структуры своего модуля), из конструктора `новый` и из элемента коллекции в `для X из Список`; имя, объявленное в методе ещё чем-нибудь, тёзка stdlib-типа, второй шаг цепочки и латинские написания члена не судятся | – |

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

Три правила по стандарту "Заполнение свойств проекта": `Поставщик` и `Имя` – идентификаторы,
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

Двадцать семь правил по документации платформы ("Соглашения по написанию кода", "Идиомы
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

## Включение и выключение

`--select` и `--ignore` принимают идентификатор правила, группу (часть до `/`, напр. `style`)
или букву тира `A`/`B`/`C`/`D`. Плагин может переопределить severity правила (группа
entry-points `xbsl.severity`); `XBSL_NO_PLUGINS=1` отключает плагины и возвращает встроенные
значения из этой таблицы.
