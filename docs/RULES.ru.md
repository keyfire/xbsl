---
title: "Правила линтера XBSL"
description: "Полный перечень проверок линтера с уровнями важности и областью применения."
sidebar:
  label: Правила
  order: 4
---

Полный перечень проверок линтера. Файл дополняется при добавлении правил; актуальный
список в рантайме – `xbsl --list-rules` (или MCP `list_rules`). Сейчас правил: 115.

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
приведение, незакрытый ресурс, соответствие ТИПА возвращаемого значения сигнатуре. Последнее
стоит различать: структурное несоответствие (значение в методе-ничто, пустой `возврат` в
типизированном) правило `code/return-mismatch` ловит, а `возврат` строки из метода с `: Число`
пропустит – для этого нужно вывести тип выражения.

Проверка корректности кода – серверная компиляция при деплое; линтер идёт перед ней и снимает
частые ошибки заранее.

## Как читать таблицу

- **Правило** – идентификатор `группа/имя`. Группа (часть до `/`) позволяет включать и
  выключать правила пачкой.
- **Severity** – `error` (сборка/CI должны падать), `warning` (нарушение соглашения),
  `info` (подсказка, обычно выключена).
- **Умолч.** – входит ли правило в набор по умолчанию (`вкл`) или включается явно (`выкл`).
- **Область** – `файл` (правило видит один файл) или `проект` (нужен индекс всего проекта:
  дубли Ид, неизвестные типы, кросс-модульные вызовы).
- **Документация** – ссылка на раздел документации платформы, стоящий за правилом. В VS Code
  код такого правила в панели "Проблемы" открывает этот раздел прямо в редакторе.

## Тиры

Правила разбиты на тиры A–D по тому, на что они опираются. Тир – это и есть быстрый фильтр
для `--select`/`--ignore` (наряду с группой и идентификатором): `--select A,B` гоняет только
структуру и текст, `--ignore D` убирает семантику над stdlib.

### Тир A – структура и YAML

Файл существует, парсится, у объекта есть уникальный UUID, имя совпадает с файлом.

| # | Правило | Severity | Умолч. | Область | Что проверяет | Документация |
|---|---|---|---|---|---|---|
| 1 | `yaml/valid` | error | вкл | файл | YAML не парсится | – |
| 2 | `yaml/id-uuid` | error | вкл | файл | Ид не является UUID | – |
| 3 | `yaml/id-required` | warning | вкл | файл | У объекта нет Ид | – |
| 4 | `yaml/name-matches-file` | warning | вкл | файл | Имя не совпадает с именем файла | – |
| 5 | `yaml/id-unique` | error | вкл | проект | Дубли Ид в проекте | – |
| 6 | `yaml/standard-field-length` | error | вкл | файл | Длина стандартного реквизита сверх лимита платформы (`Наименование` > 400, `Код` > 50) – применение отвергает реквизит, и он выпадает из объекта | [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 7 | `yaml/ref-needs-nullable` | error | вкл | файл | Ссылочный тип в позиции `Тип` без `?` (`Товары.Ссылка`, `ПолеВвода<Товары.Ссылка>`) – у ссылки нет значения по умолчанию, компиляция падает `Default value initialization is not supported` | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 8 | `yaml/no-expression-in-literal` | error | вкл | файл | Выражение `=...` внутри узла литерального типа (`Шрифт: {Тип: АбсолютныйШрифт, Размер: =...}`) – платформа принимает здесь только литерал, вычислять нужно весь объект | [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| 9 | `project/identifier` | warning | вкл | файл | Имя или поставщик проекта не идентификатор | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 10 | `project/presentation` | warning | вкл | файл | Представление проекта не заполнено | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 11 | `project/version` | warning | вкл | файл | Версия проекта не A.B.C | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |
| 12 | `structure/xbsl-pair` | warning | вкл | файл | Модуль .xbsl без парного .yaml | – |
| 13 | `project/path-matches-descriptor` | error | вкл | файл | Путь `{{поставщик}}/{{имя}}` разошёлся с дескриптором – сборка отвергнет проект до компиляции | [доки](https://1cmycloud.com/docs/help/topics/project-properties-standard/) |

### Тир B – текст и соглашения

Кодировка, переводы строк, пробелы, типографика (тире, кавычки, многоточие), длина строки,
секреты в исходниках.

| # | Правило | Severity | Умолч. | Область | Что проверяет | Документация |
|---|---|---|---|---|---|---|
| 14 | `security/hardcoded-secret` | error | вкл | файл | Ключ или пароль литералом в коде | – |
| 15 | `typography/em-dash` | info | выкл | файл | Длинное тире в комментарии | – |
| 16 | `typography/ellipsis` | warning | вкл | файл | Символ многоточия в комментарии | – |
| 17 | `typography/curly-quotes` | warning | вкл | файл | Кудрявые кавычки | – |
| 18 | `typography/guillemets-comment` | info | выкл | файл | Ёлочки в комментарии | – |
| 19 | `whitespace/trailing` | warning | вкл | файл | Хвостовые пробелы | – |
| 20 | `whitespace/mixed-newline` | warning | вкл | файл | Смешанные переводы строк | – |
| 21 | `encoding/utf8` | error | вкл | файл | Файл не в UTF-8 | – |
| 22 | `style/tab-indent` | warning | вкл | файл | Табуляция в отступе | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| 23 | `style/line-length` | info | выкл | файл | Строка длиннее 120 символов | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |

### Тир C – структура кода, базовый синтаксис и соглашения по написанию

Баланс блоков и скобок, заголовки циклов и методов, локальные переменные и группа `style/` –
соглашения из раздела документации "Рекомендации по написанию кода". Часть правил `style/`
выключена по умолчанию (накопленный долг, `info`): включаются `--select style` для замера.

| # | Правило | Severity | Умолч. | Область | Что проверяет | Документация |
|---|---|---|---|---|---|---|
| 24 | `code/parse-error` | error | вкл | файл | Синтаксическая ошибка (полный разбор по грамматике платформы) | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| 25 | `code/statement-no-effect` | warning | вкл | файл | Оператор-выражение без эффекта: значение отбрасывается (часто опечатка в ключевом слове вида `возрат 5`) | – |
| 26 | `code/return-mismatch` | error | вкл | файл | Возврат не по сигнатуре метода (значение в методе-ничто, пустой `возврат` в типизированном) – компилятор такой код отвергает | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 27 | `code/call-arity` | error | вкл | файл | Число аргументов локального вызова вне диапазона [обязательные, все] сигнатуры | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 28 | `code/brackets` | error | вкл | файл | Дисбаланс скобок () [] {} | – |
| 29 | `code/blocks` | error | вкл | файл | Дисбаланс блоков и ';' | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| 30 | `code/ternary-and-or` | error | вкл | файл | Составное условие тернарного оператора без скобок | [доки](https://1cmycloud.com/docs/help/topics/question-mark-operation/) |
| 31 | `code/param-type-required` | error | вкл | файл | Параметр без типа и без значения по умолчанию | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 32 | `code/loop-header` | error | вкл | файл | Неверный заголовок цикла 'для' | [доки](https://1cmycloud.com/docs/help/topics/for-in-loop/) |
| 33 | `code/invalid-string-escape` | error | вкл | файл | Недопустимая управляющая последовательность в строковом литерале (`\'`, регексные `\d`) – компилятор отвергает такой литерал; валидны `\н \в \т \\ \" \% \$ \ю<код>` и латинские написания | [доки](https://1cmycloud.com/docs/help/topics/escape-sequence/) |
| 34 | `code/unused-local` | warning | вкл | файл | Неиспользуемая локальная переменная | – |
| 35 | `code/unused-loop-var` | warning | вкл | файл | Неиспользуемая переменная цикла | – |
| 36 | `code/ref-field-needs-req` | error | вкл | файл | Поле-ссылка структуры без 'обз' | [доки](https://1cmycloud.com/docs/help/topics/structure/) |
| 37 | `style/boolean-compare` | info | выкл | файл | Сравнение булева значения с Истина/Ложь | [доки](https://1cmycloud.com/docs/help/topics/check-logical-values/) |
| 38 | `style/undefined-is` | warning | вкл | файл | Проверка Неопределено оператором 'это' | [доки](https://1cmycloud.com/docs/help/topics/check-if-undefined/) |
| 39 | `style/negated-is` | warning | вкл | файл | Отрицание оператора 'это' снаружи | [доки](https://1cmycloud.com/docs/help/topics/is-operator/) |
| 40 | `style/semicolon-line` | warning | вкл | файл | ';' не на отдельной строке | [доки](https://1cmycloud.com/docs/help/topics/general-design/) |
| 41 | `style/wrap-operator` | warning | вкл | файл | Операция в конце перенесённой строки | [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 42 | `style/wrap-comma` | warning | вкл | файл | Запятая в начале перенесённой строки | [доки](https://1cmycloud.com/docs/help/topics/split-expressions/) |
| 43 | `style/camel-case` | info | выкл | файл | Имя не в UpperCamelCase | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 44 | `style/const-case` | warning | вкл | файл | Константа не БОЛЬШИМИ_БУКВАМИ | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 45 | `style/exception-prefix` | warning | вкл | файл | Имя исключения без префикса "Исключение" | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 46 | `style/abbreviation-case` | info | выкл | файл | Аббревиатура заглавными буквами в имени | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 47 | `style/enum-name-vid` | warning | вкл | файл | Имя перечисления начинается с "Тип" | [доки](https://1cmycloud.com/docs/help/topics/naming-convention/) |
| 48 | `style/collection-literal` | info | выкл | файл | Ручное наполнение коллекции вместо литерала | [доки](https://1cmycloud.com/docs/help/topics/collection-literals-usage/) |
| 49 | `style/redundant-tostring` | info | выкл | файл | '.ВСтроку()' в конкатенации | [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 50 | `style/interpolation` | info | выкл | файл | Конкатенация вместо интерполяции | [доки](https://1cmycloud.com/docs/help/topics/string-concatenation/) |
| 51 | `style/type-colon-space` | warning | вкл | файл | Пробелы вокруг двоеточия типа | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 52 | `style/union-spaces` | warning | вкл | файл | Пробелы вокруг '\|' в составном типе | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 53 | `style/nullable-shorthand` | warning | вкл | файл | Неопределено в типе без сокращения '?' | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 54 | `style/redundant-type` | warning | вкл | файл | Избыточная аннотация типа при инициализации | [доки](https://1cmycloud.com/docs/help/topics/type-description-and-initialization/) |
| 55 | `style/optional-params-last` | warning | вкл | файл | Необязательный параметр перед обязательным | [доки](https://1cmycloud.com/docs/help/topics/method-declarations/) |
| 56 | `code/resource-bare-name` | error | вкл | файл | `Ресурс{Ресурсы/Имя.svg}` – ключ ресурса задается ОТНОСИТЕЛЬНО каталога Ресурсы; сам каталог в ключе ломает поиск | [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| 57 | `query/named-parameter` | error | вкл | файл | Именованный параметр `&Имя` внутри литерала запроса – значения в литерал передаются интерполяцией (`%Имя`) | [доки](https://1cmycloud.com/docs/help/topics/query-literal/) |
| 58 | `code/this-in-static-method` | error | вкл | файл | Ключевое слово `этот` в теле статического метода – статический метод общий для всего типа и контекста объекта не имеет, проект компилятор отвергает | [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 59 | `code/instance-call-from-static` | error | вкл | файл | Вызов обычного метода того же владельца по голому имени из статического метода – документация запрещает это прямо; вызывайте метод у значения либо сделайте его статическим | [доки](https://1cmycloud.com/docs/help/topics/static-methods/) |
| 60 | `code/close-in-before-close` | warning | вкл | файл | `Закрыть()` внутри `ПередЗакрытием` – платформа игнорирует вызов, и форму не закрывает уже ничто | – |
| 61 | `query/no-isnull` | error | вкл | файл | `ЕСТЬNULL(` внутри литерала запроса – такой функции в языке запросов нет | – |

### Тир D – семантика над stdlib, формы и метамодель

Требует индекс проекта и данные платформы: неизвестные типы и объекты, значения перечислений,
модель выполнения (клиент/сервер), обработчики форм, свойства и запросы.

| # | Правило | Severity | Умолч. | Область | Что проверяет | Документация |
|---|---|---|---|---|---|---|
| 62 | `yaml/choice-needs-static-list` | warning | вкл | файл | ВыборЗначения без статичного СпискаВыбора | [доки](https://1cmycloud.com/docs/help/stdlib/element/xbsl/Std/Interface/CommonComponents/ValueChoice_ru/) |
| 63 | `code/unknown-type` | warning | вкл | проект | Неизвестный тип | – |
| 64 | `code/catch-non-exception` | error | вкл | файл | Тип в `поймать` не исключение (stdlib-тип без сигнатуры исключения или локальная `структура`) – компилятор такой код отвергает | [доки](https://1cmycloud.com/docs/help/topics/exceptions/) |
| 65 | `code/unknown-member` | error | вкл | файл | Обращение к отсутствующему члену переменной известного stdlib-типа – простого или дженерика, у которого аргументы типизируют члены, но не называют их (первый шаг цепочки, у опечаток подсказка) | – |
| 66 | `code/unknown-static-member` | error | вкл | проект | Обращение к отсутствующему члену по имени типа (`ДатаВремя.Минимальная()`); тип результата такого вызова переносится на следующий шаг цепочки. Голое имя читается как тип, только если проект не придаёт ему другого смысла; парный yaml модуля учитывается и при проверке одиночного файла | – |
| 67 | `yaml/foreign-not-public` | error | вкл | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на элемент чужой подсистемы, у которого `ОбластьВидимости` не `ВПроекте`/`Глобально` – снаружи своей подсистемы он недоступен, и импорт не поможет | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 68 | `code/call-arity-cross` | error | вкл | проект | Число аргументов вызова `Модуль.Метод(...)` вне диапазона сигнатуры модуля-адресата | [доки](https://1cmycloud.com/docs/help/topics/methods-in-built-in-script-language/) |
| 69 | `code/undefined-name` | error | вкл | проект | Неизвестное имя в выражении (опечатки вида `Адресар` вместо `Адреса`) и в короткой интерполяции строки (`"?$format=json"` – подстановка имени `format`, нужен `\$`) – компилятор такой код отвергает | – |
| 70 | `code/unknown-object-type` | warning | вкл | проект | Неизвестный тип объекта проекта | – |
| 71 | `yaml/unknown-type` | warning | вкл | проект | Неизвестный тип в yaml | – |
| 72 | `yaml/dynlist-missing-field` | warning | вкл | проект | Нет поля динамического списка | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 73 | `code/unknown-enum-value` | warning | вкл | проект | Неизвестное значение перечисления | [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 74 | `yaml/enum-needs-nullable` | warning | вкл | проект | Перечисление без nullable | [доки](https://1cmycloud.com/docs/help/topics/enumeration-properties/) |
| 75 | `yaml/unknown-enum-value` | error | вкл | файл | Значение свойства компонента вне списка перечисления ui-схемы (`ВыравниваниеСодержимогоПоВертикали: Конец` – по вертикали значения `Конец` нет) | – |
| 76 | `yaml/bare-object-value` | error | вкл | файл | Голое слово в свойстве, принимающем `Объект` (`Значение: Титул`) – платформа ждёт литерал в кавычках, выражение с `=` либо `$`-ссылку локализованной строки | [доки](https://1cmycloud.com/docs/help/topics/label-component/) |
| 77 | `code/unknown-resource` | error | вкл | проект | Имени из `Ресурс{...}` нет ни в каталогах `Ресурсы` проекта, ни в библиотеке картинок платформы | [доки](https://1cmycloud.com/docs/help/topics/image-library/) |
| 78 | `form/unknown-handler` | warning | вкл | проект | Обработчик формы не найден в модуле | [доки](https://1cmycloud.com/docs/help/topics/form-component/) |
| 79 | `code/server-call-from-handler` | warning | вкл | проект | Серверный метод недоступен клиентскому обработчику | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 80 | `code/client-annotation-in-server-module` | warning | вкл | проект | Клиентская аннотация в серверном общем модуле | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 81 | `code/client-module-in-http-service` | warning | вкл | проект | Клиентский общий модуль в HTTP-сервисе | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 82 | `code/query-needs-server` | error | вкл | проект | Блок `Запрос{...}` в методе клиентского модуля (форма либо общий модуль с клиентским `Окружение`) без `@НаСервере` – на клиенте такого типа нет, сборку компилятор отвергает | [доки](https://1cmycloud.com/docs/help/topics/module-execution/) |
| 83 | `code/local-method-cross-component` | warning | вкл | проект | Кросс-компонентный вызов локального метода | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 84 | `code/local-method-cross-module` | error | вкл | проект | Межмодульный вызов локального метода | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 85 | `naming/yo` | warning | вкл | файл | Буква "ё" в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 86 | `naming/underscore` | warning | вкл | файл | Подчёркивание в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 87 | `naming/abbreviation` | warning | вкл | файл | Аббревиатура заглавными буквами в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 88 | `naming/latin-term` | warning | вкл | файл | Англоязычный термин записан русскими буквами | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 89 | `naming/enum-vid` | warning | вкл | файл | Имя перечисления со словом "Тип" | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 90 | `naming/kind-in-name` | warning | вкл | файл | Вид элемента в его имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 91 | `naming/filler-word` | warning | вкл | файл | Слово-пустышка в имени | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 92 | `naming/module-suffix` | warning | вкл | файл | Постфикс окружения в имени общего модуля | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 93 | `naming/number` | warning | вкл | файл | Число имени не по виду элемента | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 94 | `naming/boolean-name` | warning | вкл | файл | Имя булева реквизита | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 95 | `naming/presentation` | warning | вкл | файл | Представление элемента | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 96 | `naming/prefix-by-kind` | warning | вкл | файл | Имя вида без обязательного префикса | [доки](https://1cmycloud.com/docs/help/topics/project-element-names-standard/) |
| 97 | `code/unknown-ns-object` | warning | вкл | проект | Неизвестный объект в пространстве имён вида | – |
| 98 | `query/unknown-table` | warning | вкл | проект | Неизвестная таблица в запросе | [доки](https://1cmycloud.com/docs/help/topics/select-from/) |
| 99 | `query/in-subquery-composite` | warning | вкл | проект | 'В' с подзапросом по составному типу | [доки](https://1cmycloud.com/docs/help/topics/in-expression/) |
| 100 | `yaml/unknown-property` | warning | вкл | файл | Неизвестное свойство объекта | – |
| 101 | `code/reserved-name` | warning | вкл | файл | Зарезервированное имя | – |
| 102 | `yaml/builtin-property-name` | warning | вкл | файл | Совпадение со встроенным свойством | – |
| 103 | `yaml/size-needs-no-stretch` | info | выкл | файл | Размер без отключения растягивания | [доки](https://1cmycloud.com/docs/help/topics/arrange-components-on-screen/) |
| 104 | `code/unused-method` | warning | выкл | проект | Метод нигде не используется | – |
| 105 | `yaml/missing-import` | warning | вкл | проект | Ссылка из yaml (позиция типа или цель навигации `ТипФормы`) на публичный элемент чужой подсистемы, которой нет в секции `Импорт` | [доки](https://1cmycloud.com/docs/help/topics/modular-development/) |
| 106 | `yaml/presentation-field` | error | вкл | файл | Поле представления объекта | [доки](https://1cmycloud.com/docs/help/topics/element-view/) |
| 107 | `yaml/unexpected-type-argument` | error | вкл | файл | Параметр типа у свойства, которое ui-схема объявляет без параметра, – это другой тип, применение сборки его отвергнет (`ДополнительныеКоманды` формы принимают `ФрагментКомандногоИнтерфейса`, а не `ФрагментКомандногоИнтерфейса<ОбычнаяКоманда>`) | [доки](https://1cmycloud.com/docs/help/topics/command-interface/) |
| 108 | `yaml/property-since-compat` | error | вкл | проект | Свойство компонента новее, чем `РежимСовместимости` проекта (версию появления несёт ui-схема) – применение отвергает его как неизвестное | [доки](https://1cmycloud.com/docs/help/topics/update-server/) |
| 109 | `query/deletion-mark-immediate` | error | вкл | проект | Условие с пометкой удаления в запросе к объекту с `РежимУдаления: Немедленно` – поля пометки у него нет, запрос падает применением | [доки](https://1cmycloud.com/docs/help/topics/catalog-properties/) |
| 110 | `yaml/item-id-required` | error | вкл | файл | Элемент коллекции метаданных (реквизит, табличная часть, элемент перечисления, параметр ключа доступа) без `Ид`, который объявляет его класс – применение отвечает `ID required` | – |
| 111 | `code/unknown-row-field` | error | вкл | проект | Поле строки динамического списка (`СтрокаДинамическогоСписка<Форма.Тип>`), которого нет среди `Поля` списка | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 112 | `code/row-field-null` | error | вкл | проект | Поле динамического списка, взятое через ссылку (`Абонент.Номер`), имеет тип `<тип>|Null` и не годится типизированному полю структуры – компилятор отвечает `Null cannot be assigned` | [доки](https://1cmycloud.com/docs/help/topics/dynamic-list/) |
| 113 | `yaml/unknown-attribute-property` | error | вкл | файл | Ключ, которого класс самого реквизита не объявляет (`Длина` у обычного реквизита – её объявляет стандартный `Код`, а у числового есть `ДлинаЦелойЧасти`) – применение сборки отвергает объект | – |
| 114 | `yaml/empty-group-sized` | warning | вкл | файл | Пустая `Группа` с `Высота`/`Ширина` – рендер выбрасывает узел, зазора не будет | – |
| 115 | `yaml/hint-too-long` | warning | вкл | файл | `Подсказка` длиннее предела отрисовки – хвост не показывается вовсе | – |

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
противоречит, а `Программы` и `Акции` без падежа читаются как родительный падеж единственного.
Нужен extra `[morph]` (`pip install "xbsl[morph]"`); без него правило молчит.

Остальное: буква `ё` и подчёркивания в именах, аббревиатура одним словом (`Ндс`, а не `НДС`),
англоязычный термин оригиналом (`Xml`, а не `Хмл`), `Вид` вместо `Тип` у перечислений, вид
элемента внутри его имени (`ОтчетЗависшиеЗадачи`), слова-пустышки (`Управление`, `Менеджер`),
постфикс окружения у общего модуля (`ОбменДаннымиКлиентИСервер` – окружение задаётся свойством),
булев реквизит через отрицание (`НетОшибок` вместо `Успешно`), незаполненное `Представление` и
обязательные префиксы отдельных видов (`КлючДоступа`, `ПравоНа`, `Навигация`).

### Соглашения по написанию кода (правила `style/`)

Двадцать одно правило по документации платформы ("Соглашения по написанию кода" и "Идиомы
языка"): оформление и переносы выражений, именование, описание типов и сигнатуры, литералы
коллекций, интерполяция строк, проверки булевых значений и `Неопределено`.

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
