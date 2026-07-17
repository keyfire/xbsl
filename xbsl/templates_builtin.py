"""The templates shipped with the toolkit: the constructs of XBSL and the idioms of a project.

Kept as Python rather than a data file for one reason: a pattern is multi-line code, and it has
to stay readable and reviewable - in JSON it would be one line of `\\n` escapes.

Every pattern here is verified: the syntax comes from the platform documentation or from working
sources, and `tests/test_templates.py` parses each one (the same parser the linter runs), so a
template cannot ship code that does not compile. Three traps this set deliberately avoids, all
of them BSL habits that XBSL does not share and that a parser reports late or not at all:

  * a block ends with `;` - there is no `Тогда`/`КонецЕсли`, and those parse as bare names;
  * the default branch of `выбор` is `иначе` - `умолчание` marks an enumeration item instead;
  * a catch is `поймать Имя: Тип` - a bare `исключение` opens an exception type declaration.

Naming follows EDT: `<аббревиатура> - <заголовок>`, where the bracketed tail is optional to
type, so `мет` already reaches every flavour of a method. Triggers are deliberately shared by
a family of templates - the title tells them apart in the list.
"""

from __future__ import annotations

from xbsl.templates import (
    CLIENT_ENVIRONMENT,
    DECLARATION_CONTEXT,
    QUERY_CONTEXT,
    SERVER_ENVIRONMENT,
    STATEMENT_CONTEXT,
    Template,
)

_STATEMENT = (STATEMENT_CONTEXT,)
_DECLARATION = (DECLARATION_CONTEXT,)
_QUERY = (QUERY_CONTEXT,)
_SERVER = (SERVER_ENVIRONMENT,)
_CLIENT = (CLIENT_ENVIRONMENT,)


# ------------------------------------------------------------------------ control statements

_CONTROL = [
    Template(
        name="есл[и] - Если",
        description="/Стандартные/Управляющие/Если",
        contexts=_STATEMENT,
        pattern='''\
если ${Редактировать("Условие")}
    ${Редактировать("")}
;''',
    ),
    Template(
        name="есл[иИначе] - Если ... иначе",
        description="/Стандартные/Управляющие/Если ... иначе",
        contexts=_STATEMENT,
        pattern='''\
если ${Редактировать("Условие")}
    ${Редактировать("")}
иначе
    ${Редактировать("")}
;''',
    ),
    Template(
        name="есл[иИначеЕсли] - Если ... иначе если ... иначе",
        description="/Стандартные/Управляющие/Если ... иначе если",
        contexts=_STATEMENT,
        pattern='''\
если ${Редактировать("Условие")}
    ${Редактировать("")}
иначе если ${Редактировать("ДругоеУсловие")}
    ${Редактировать("")}
иначе
    ${Редактировать("")}
;''',
    ),
    Template(
        name="для[Из] - Для ... из (обход коллекции)",
        description="/Стандартные/Управляющие/Для ... из",
        contexts=_STATEMENT,
        pattern='''\
для ${Редактировать("Элемент")} из ${Редактировать("Коллекция")}
    ${Редактировать("")}
;''',
    ),
    Template(
        name="для[Счетчик] - Для ... по (счётчик)",
        description="/Стандартные/Управляющие/Для ... по",
        contexts=_STATEMENT,
        pattern='''\
для ${Редактировать("Индекс")} = 0 по ${Редактировать("Коллекция")}.Размер() - 1
    ${Редактировать("")}
;''',
    ),
    Template(
        name="пок[а] - Пока",
        description="/Стандартные/Управляющие/Пока",
        contexts=_STATEMENT,
        pattern='''\
пока ${Редактировать("Условие")}
    ${Редактировать("")}
;''',
    ),
    # `поймать` needs a variable and a type - a bare `исключение` is not a catch here: it
    # would open an exception TYPE declaration, and the error would surface far from the spot.
    Template(
        name="попыт[ка] - Попытка ... поймать",
        description="/Стандартные/Управляющие/Попытка",
        contexts=_STATEMENT,
        pattern='''\
попытка
    ${Редактировать("")}
поймать ${Редактировать("Ошибка")}: Исключение
    ${Редактировать("")}
;''',
    ),
    Template(
        name="попыт[каВконце] - Попытка ... поймать ... вконце",
        description="/Стандартные/Управляющие/Попытка ... вконце",
        contexts=_STATEMENT,
        pattern='''\
попытка
    ${Редактировать("")}
поймать ${Редактировать("Ошибка")}: Исключение
    ${Редактировать("")}
вконце
    ${Редактировать("")}
;''',
    ),
    # The default branch is `иначе`; `умолчание` is a postfix of an enumeration item instead.
    Template(
        name="выб[ор] - Выбор ... когда",
        description="/Стандартные/Управляющие/Выбор",
        contexts=_STATEMENT,
        pattern='''\
выбор ${Редактировать("Выражение")}
когда ${Редактировать("Значение")}
    ${Редактировать("")}
иначе
    ${Редактировать("")}
;''',
    ),
    Template(
        name="выб[орУсловие] - Выбор по условиям",
        description="/Стандартные/Управляющие/Выбор по условиям",
        contexts=_STATEMENT,
        pattern='''\
выбор
когда ${Редактировать("Условие")}
    ${Редактировать("")}
иначе
    ${Редактировать("")}
;''',
    ),
    Template(
        name="возв[рат] - Возврат",
        description="/Стандартные/Управляющие/Возврат",
        contexts=_STATEMENT,
        pattern='возврат ${Редактировать("")}',
    ),
    # What is thrown is an INSTANCE of an Исключение descendant, not a string; its first
    # parameter is Описание.
    Template(
        name="выбр[осить] - Выбросить исключение",
        description="/Стандартные/Управляющие/Выбросить",
        contexts=_STATEMENT,
        pattern='выбросить новый ${Редактировать("Исключение")}("${Редактировать("Описание")}")',
    ),
    Template(
        name="обл[асть] - Область видимости",
        description="/Стандартные/Управляющие/Область видимости",
        contexts=_STATEMENT,
        pattern='''\
область
    ${Редактировать("")}
;''',
    ),
]


# ------------------------------------------------------------------------------ declarations

_DECLARATIONS = [
    Template(
        name="мет[од] - Метод",
        description="/Стандартные/Объявления/Метод",
        contexts=_DECLARATION,
        pattern='''\
метод ${Редактировать("ИмяМетода")}()
    ${Редактировать("")}
;''',
    ),
    Template(
        name="мет[одПараметры] - Метод с параметрами и возвратом",
        description="/Стандартные/Объявления/Метод с параметрами",
        contexts=_DECLARATION,
        pattern='''\
метод ${Редактировать("ИмяМетода")}(${Редактировать("Параметр")}: ${Редактировать("Строка")}): ${Редактировать("Булево")}
    возврат ${Редактировать("")}
;''',
    ),
    # Annotations stack on one line - that is how the working sources are written.
    Template(
        name="мет[одСервера] - Метод сервера",
        description="/Стандартные/Объявления/Метод сервера",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@НаСервере @ВПроекте
метод ${Редактировать("ИмяМетода")}()
    ${Редактировать("")}
;''',
    ),
    # Without @ДоступноСКлиента a server method cannot be called from a client handler.
    Template(
        name="мет[одСервераСКлиента] - Метод сервера, доступный с клиента",
        description="/Стандартные/Объявления/Метод сервера, доступный с клиента",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@НаСервере @ВПроекте @ДоступноСКлиента
метод ${Редактировать("ИмяМетода")}()
    ${Редактировать("")}
;''',
    ),
    Template(
        name="мет[одКлиента] - Метод клиента",
        description="/Стандартные/Объявления/Метод клиента",
        contexts=_DECLARATION,
        environments=_CLIENT,
        pattern='''\
@НаКлиенте @Локально
метод ${Редактировать("ИмяМетода")}()
    ${Редактировать("")}
;''',
    ),
    Template(
        name="стат[ическийМетод] - Статический метод",
        description="/Стандартные/Объявления/Статический метод",
        contexts=_DECLARATION,
        pattern='''\
статический метод ${Редактировать("ИмяМетода")}(): ${Редактировать("Строка")}
    возврат ${Редактировать("")}
;''',
    ),
    # An abstract method has no body and no closing ';' - it only declares the signature.
    Template(
        name="абстр[актныйМетод] - Абстрактный метод (контракт)",
        description="/Стандартные/Объявления/Абстрактный метод",
        contexts=_DECLARATION,
        pattern='абстрактный метод ${Редактировать("ИмяМетода")}(): ${Редактировать("Строка")}',
    ),
    Template(
        name="реал[изация] - Реализация метода контракта",
        description="/Стандартные/Объявления/Реализация контракта",
        contexts=_DECLARATION,
        pattern='''\
@Реализация
метод ${Редактировать("ИмяМетода")}(): ${Редактировать("Строка")}
    возврат ${Редактировать("")}
;''',
    ),
    # `обз` makes the field mandatory in the constructor; a `знч` field is set by it alone.
    Template(
        name="стр[уктура] - Структура",
        description="/Стандартные/Объявления/Структура",
        contexts=_DECLARATION,
        pattern='''\
структура ${Редактировать("ИмяСтруктуры")}
    обз пер ${Редактировать("Поле")}: ${Редактировать("Строка")}
    @ИменованныеПараметры
    конструктор
;''',
    ),
    Template(
        name="переч[исление] - Перечисление",
        description="/Стандартные/Объявления/Перечисление",
        contexts=_DECLARATION,
        pattern='''\
перечисление ${Редактировать("ИмяПеречисления")}
    ${Редактировать("Первое")} умолчание,
    ${Редактировать("Второе")}
;''',
    ),
    Template(
        name="искл[ючениеТип] - Тип исключения",
        description="/Стандартные/Объявления/Тип исключения",
        contexts=_DECLARATION,
        pattern='''\
исключение Исключение${Редактировать("Имя")}
    обз пер ${Редактировать("Поле")}: ${Редактировать("Строка")}
;''',
    ),
    Template(
        name="имп[орт] - Импорт",
        description="/Стандартные/Объявления/Импорт",
        contexts=_DECLARATION,
        pattern='импорт ${Редактировать("Подсистема")}',
    ),
    Template(
        name="конст - Константа модуля",
        description="/Стандартные/Объявления/Константа",
        contexts=_DECLARATION,
        pattern='конст ${Редактировать("ИМЯ_КОНСТАНТЫ")} = ${Редактировать("Значение")}',
    ),
]


# ------------------------------------------------------------------- variables and collections

_VARIABLES = [
    # In a value position an edit point carries a prompt rather than nothing: an empty one
    # would leave an unfinished statement (`пер Имя = `) that the compiler rejects.
    Template(
        name="пер - Переменная",
        description="/Стандартные/Переменные/Переменная",
        contexts=_STATEMENT,
        pattern='пер ${Редактировать("Имя")} = ${Редактировать("Значение")}',
    ),
    Template(
        name="знч - Значение (только чтение)",
        description="/Стандартные/Переменные/Значение",
        contexts=_STATEMENT,
        pattern='знч ${Редактировать("Имя")} = ${Редактировать("Значение")}',
    ),
    # `исп` closes the resource itself when the scope ends - for descendants of Закрываемое.
    Template(
        name="исп - Закрываемый ресурс",
        description="/Стандартные/Переменные/Закрываемый ресурс",
        contexts=_STATEMENT,
        pattern='исп ${Редактировать("Имя")} = ${Редактировать("Ресурс")}',
    ),
    Template(
        name="мас[сив] - Массив",
        description="/Стандартные/Коллекции/Массив",
        contexts=_STATEMENT,
        pattern='знч ${Редактировать("Имя")} = [${Редактировать("Элемент")}]',
    ),
    # An empty literal gives nothing to infer the type from - it has to be spelled out.
    Template(
        name="мас[сивПустой] - Пустой массив",
        description="/Стандартные/Коллекции/Пустой массив",
        contexts=_STATEMENT,
        pattern='пер ${Редактировать("Имя")}: Массив<${Редактировать("Строка")}> = []',
    ),
    Template(
        name="соотв[етствие] - Соответствие",
        description="/Стандартные/Коллекции/Соответствие",
        contexts=_STATEMENT,
        pattern='знч ${Редактировать("Имя")} = {${Редактировать("\\"Ключ\\"")}: ${Редактировать("Значение")}}',
    ),
    Template(
        name="соотв[етствиеПустое] - Пустое соответствие",
        description="/Стандартные/Коллекции/Пустое соответствие",
        contexts=_STATEMENT,
        pattern='знч ${Редактировать("Имя")} = <${Редактировать("Строка")}, ${Редактировать("Число")}>{:}',
    ),
    Template(
        name="множ[ество] - Множество",
        description="/Стандартные/Коллекции/Множество",
        contexts=_STATEMENT,
        pattern='знч ${Редактировать("Имя")} = {${Редактировать("Элемент")}}',
    ),
]


# ----------------------------------------------------------------------------------- queries

_QUERIES = [
    # A literal's parameter is %ИмяПеременной, evaluated when the literal is initialized.
    # УстановитьПараметр does NOT go with a literal - that is the ПроизвольныйЗапрос mechanism.
    Template(
        name="зпр[ос] - Запрос с обходом результата",
        description="/Стандартные/Запросы/Запрос",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='''\
знч Результат = Запрос{
    ВЫБРАТЬ
        Т.${Редактировать("Наименование")} КАК ${Редактировать("Наименование")}
    ИЗ
        ${ИмяОбъектаМетаданного(Справочник)} КАК Т
}.Выполнить()
для Строка из Результат
    ${Редактировать("")}
;''',
    ),
    Template(
        name="зпр[осПараметр] - Запрос с параметром",
        description="/Стандартные/Запросы/Запрос с параметром",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='''\
знч ${Редактировать("Отбор")} = ${Редактировать("Значение")}
знч Результат = Запрос{
    ВЫБРАТЬ
        Т.${Редактировать("Наименование")} КАК ${Редактировать("Наименование")}
    ИЗ
        ${ИмяОбъектаМетаданного(Справочник)} КАК Т
    ГДЕ
        Т.${Редактировать("Реквизит")} == %${Редактировать("Отбор")}
}.Выполнить()
для Строка из Результат
    ${Редактировать("")}
;''',
    ),
    # A custom query names its parameters with &, and its result is closeable - hence `исп`.
    Template(
        name="зпр[осПроизвольный] - Произвольный запрос",
        description="/Стандартные/Запросы/Произвольный запрос",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='''\
знч Запрос = новый ПроизвольныйЗапрос("ВЫБРАТЬ ${Редактировать("")} ГДЕ ${Редактировать("Реквизит")} == &${Редактировать("Параметр")}")
Запрос.УстановитьПараметр("${Редактировать("Параметр")}", ${Редактировать("")})
исп Результат = Запрос.Выполнить()
для Строка из Результат
    ${Редактировать("")}
;''',
    ),
    Template(
        name="выбрать - ВЫБРАТЬ ... ИЗ ... ГДЕ",
        description="/Стандартные/Запросы/ВЫБРАТЬ",
        contexts=_QUERY,
        environments=_SERVER,
        pattern='''\
ВЫБРАТЬ
    Т.${Редактировать("Наименование")} КАК ${Редактировать("Наименование")}
ИЗ
    ${ИмяОбъектаМетаданного(Справочник)} КАК Т
ГДЕ
    Т.${Редактировать("Реквизит")} == %${Редактировать("Параметр")}''',
    ),
    Template(
        name="соед[инение] - ВНУТРЕННЕЕ СОЕДИНЕНИЕ",
        description="/Стандартные/Запросы/Соединение",
        contexts=_QUERY,
        environments=_SERVER,
        pattern='''\
ВНУТРЕННЕЕ СОЕДИНЕНИЕ
    ${ИмяОбъектаМетаданного(Справочник)} КАК ${Редактировать("Д")}
ПО
    Т.${Редактировать("Реквизит")} == ${Редактировать("Д")}.Ссылка''',
    ),
]


# --------------------------------------------------------------------------- applied idioms

_APPLIED = [
    Template(
        name="обх[одСправочника] - Обход справочника запросом",
        description="/Стандартные/Прикладные/Обход справочника",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@НаСервере @ВПроекте
метод ${Редактировать("ИмяМетода")}(): Массив<Строка>
    исп КонтекстДоступа.Дополнить(Тип<${ИмяОбъектаМетаданного(Справочник)}.Объект>, [Сущность.Право.Чтение])
    знч Результат = Запрос{
        ВЫБРАТЬ
            Т.Наименование КАК Наименование
        ИЗ
            ${ИмяОбъектаМетаданного(Справочник)} КАК Т
    }.Выполнить()
    пер Список: Массив<Строка> = []
    для Строка из Результат
        Список.Добавить(Строка.Наименование)
    ;
    возврат Список
;''',
    ),
    # An object is created by the constructor `новый <Справочник>.Объект(...)`.
    Template(
        name="нов[ыйОбъект] - Создать и записать объект",
        description="/Стандартные/Прикладные/Создать объект",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='''\
знч Объект = новый ${ИмяОбъектаМетаданного(Справочник)}.Объект(Наименование = ${Редактировать("Наименование")})
Объект.Записать()
возврат Объект.Ссылка''',
    ),
    Template(
        name="изм[енитьОбъект] - Изменить объект по ссылке",
        description="/Стандартные/Прикладные/Изменить объект",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='''\
знч Объект = ${Редактировать("Ссылка")}.ЗагрузитьОбъект()
Объект.${Редактировать("Наименование")} = ${Редактировать("Значение")}
Объект.Записать()''',
    ),
    Template(
        name="найт[иПоКоду] - Найти по коду",
        description="/Стандартные/Прикладные/Найти по коду",
        contexts=_STATEMENT,
        environments=_SERVER,
        pattern='пер ${Редактировать("Найденный")} = ${ИмяОбъектаМетаданного(Справочник)}.НайтиПоКоду(${Редактировать("Код")})',
    ),
    # The filter is set BEFORE Записать(): the set is written by that filter.
    Template(
        name="движ[ения] - Движения регистра накопления",
        description="/Стандартные/Прикладные/Движения регистра",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
метод ВыполнитьПроведение()
    знч НаборЗаписей = новый ${ИмяОбъектаМетаданного(РегистрНакопления)}.НаборЗаписей()
    НаборЗаписей.Фильтр.Установить(Регистратор = Ссылка)
    для Строка из ${Редактировать("СписокНоменклатуры")}
        НаборЗаписей.ДобавитьЗапись(
            Период = Дата,
            ВидЗаписи = ВидЗаписиРегистраНакопления.Приход,
            ${Редактировать("Ресурс")} = Строка.${Редактировать("Ресурс")})
    ;
    НаборЗаписей.Записать()
;''',
    ),
    # The status code and the headers go strictly BEFORE УстановитьТело: once the body is
    # being written, changing them throws, and the error handler can no longer set a 500.
    Template(
        name="http[Обработчик] - Обработчик HttpСервиса",
        description="/Стандартные/Прикладные/Обработчик HttpСервиса",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
метод ${Редактировать("ИмяОбработчика")}(Запрос: HttpСервисЗапрос)
    попытка
        ${Редактировать("")}
        Запрос.Ответ.УстановитьКодСтатуса(200)
        Запрос.Ответ.Заголовки.Установить("Content-Type", "application/json")
        Запрос.Ответ.УстановитьТело(${Редактировать("Тело")})
    поймать Ошибка: Исключение
        Запрос.Ответ.УстановитьКодСтатуса(500)
        Запрос.Ответ.УстановитьТело(Ошибка.Описание)
    ;
;''',
    ),
    # The general ВычислитьРазрешенияДоступа is mandatory even when the object has no
    # whole-object rights at all.
    Template(
        name="раз[решенияДоступа] - Разрешения доступа по объектам",
        description="/Стандартные/Прикладные/Разрешения доступа",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@Обработчик
метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>
    возврат новый Массив<РазрешениеДоступа>()
;

@Обработчик
метод ВычислитьРазрешенияДоступаДляОбъектов(
        Данные: ЧитаемыйМассив<${Редактировать("Объект")}.ДанныеРасчетаРазрешений>
    ): Соответствие<${Редактировать("Объект")}.ДанныеРасчетаРазрешений, Массив<РазрешениеДоступа>>
    знч Разрешения = <${Редактировать("Объект")}.ДанныеРасчетаРазрешений, Массив<РазрешениеДоступа>>{:}
    для Запись из Данные
        если Запись.${Редактировать("Пользователь")} != Неопределено
            Разрешения.Вставить(Запись, [
                новый РазрешениеДоступа(
                    [новый КлючДоступаПользователя.Объект(Запись.${Редактировать("Пользователь")})],
                    [Сущность.Право.Чтение, Сущность.Право.Изменение])
            ])
        ;
    ;
    возврат Разрешения
;''',
    ),
    # The РежимЗагрузкиДанных guard comes first: on data load the handler must not compute.
    Template(
        name="перед[Записью] - Обработчик ПередЗаписью",
        description="/Стандартные/Прикладные/ПередЗаписью",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@Обработчик
метод ПередЗаписью(До: ${Редактировать("Объект")}.Данные, ПараметрыЗаписи: ${Редактировать("Объект")}.ПараметрыЗаписи)
    если ПараметрыЗаписи.РежимЗагрузкиДанных
        возврат
    ;
    ${Редактировать("")}
;''',
    ),
    Template(
        name="посл[еЗаписи] - Обработчик ПослеЗаписи",
        description="/Стандартные/Прикладные/ПослеЗаписи",
        contexts=_DECLARATION,
        environments=_SERVER,
        pattern='''\
@Обработчик
метод ПослеЗаписи(До: ${Редактировать("Объект")}.Данные, ПараметрыЗаписи: ${Редактировать("Объект")}.ПараметрыЗаписи)
    если ПараметрыЗаписи.РежимЗагрузкиДанных
        возврат
    ;
    ${Редактировать("")}
;''',
    ),
    Template(
        name="посл[еСоздания] - Обработчик формы ПослеСоздания",
        description="/Стандартные/Прикладные/ПослеСоздания",
        contexts=_DECLARATION,
        environments=_CLIENT,
        pattern='''\
@Обработчик
метод ПослеСоздания()
    ${Редактировать("")}
;''',
    ),
    # Command and event handlers are bound by name from the yaml - they carry no annotation.
    Template(
        name="ком[андаФормы] - Обработчик команды формы",
        description="/Стандартные/Прикладные/Команда формы",
        contexts=_DECLARATION,
        environments=_CLIENT,
        pattern='''\
метод ${Редактировать("ИмяКоманды")}(Команда: ОбычнаяКоманда)
    ${Редактировать("")}
;''',
    ),
    Template(
        name="кноп[каНажатие] - Обработчик нажатия кнопки",
        description="/Стандартные/Прикладные/Нажатие кнопки",
        contexts=_DECLARATION,
        environments=_CLIENT,
        pattern='''\
метод ${Редактировать("Кнопка")}ПриНажатии(Источник: Кнопка, Событие: СобытиеПриНажатии)
    ${Редактировать("")}
;''',
    ),
]


BUILTIN: tuple[Template, ...] = tuple(_CONTROL + _DECLARATIONS + _VARIABLES + _QUERIES + _APPLIED)
