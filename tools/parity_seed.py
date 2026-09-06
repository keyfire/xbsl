"""Seeded bilingual parity: plant a case in a Russian tree and demand the same verdict in English.

1C:Element is bilingual down to the identifiers, and the tables the rules judge by are
extracted from Russian-only documentation. A rule that matches source text against such a
table is blind on a translated project unless it derives the English spelling - what the
compiler accepts comes back as a finding, or a real defect goes unreported.

The measurement used so far was a COUNTING DIFF: lint the translated tree of a real project,
lint the Russian one, compare file by file. It finds a rule whose count moved, and it is blind
to a rule whose count is zero on both sides - either because the project happens to carry no
such construct, or because the rule fires on neither spelling. `structure/xbsl-pair` lived in
exactly that shadow: every English module of a generated type except the object module was
reported, and the diff saw nothing, because the measured English tree carries object modules
alone.

So this tool does not measure a project. It SEEDS one. A seed is a small Russian tree plus the
verdict the rule owes it - a finding, or silence. The seed is run through the project's own
translator, the same path the real translated tree came from, so the English spelling under
test is the one the toolkit actually produces. Then the rule runs on both trees and the two
verdicts have to agree:

    ok           both trees answer as the seed says
    en-misses    the English tree stays silent where the seed plants a violation
    en-invents   the English tree reports where the seed plants legal code
    ru-misses    the same, on the Russian side
    ru-invents   the same, on the Russian side
    stale        NEITHER tree answers as the seed says - the seed no longer describes the
                 rule, and it is the catalog that needs the fix, not the engine

The verdict names the side that is wrong and what it did, because the two failures need
opposite fixes: a table that lacks the English spelling makes the rule miss, and one that
lacks the Russian reading of an English construct makes it invent.

A seed may also carry its English twin WRITTEN BY HAND (`english=`), spelled the way the
platform's own dictionaries spell the names (terms.json, uiterms.json, the ui schema). Then the
rule is judged on the spelling the platform documents, and the translator's output becomes a
THIRD tree, compared against both: a rule that misreads the hand-written tree is blind by
itself (`en-...`), one that misreads the translated tree alone points at the translator:

    translator-misses   the translated tree stays silent while the hand-written one answers
    translator-invents  the translated tree reports while the hand-written one passes

The files the translator wrote differently from the hand are listed next to the verdict, so a
translator gap is read off the line instead of being rediscovered by a diff.

A gap that cannot be closed today is still planted, with `known=` naming the reason: deleting
the seed would delete the evidence, and the next reader would rediscover the same thing from
scratch. Such a seed reports `known (...)` and does not fail the run - but the moment it
starts AGREEING it reports `fixed!` and fails, so a closed gap cannot keep a stale excuse.

Usage:

    python tools/parity_seed.py                  # every seed
    python tools/parity_seed.py --rule structure/xbsl-pair
    python tools/parity_seed.py --uncovered      # rules no seed speaks for
    python tools/parity_seed.py --json

Exit code 1 when any seed disagrees - the check is meant to be gateable.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from xbsl import engine  # noqa: E402
import xbsl.rules  # noqa: F401,E402  - registers every rule
from xbsl.translation.dictionary import Dictionary  # noqa: E402
from xbsl.translation.project import translate_project  # noqa: E402

FINDING = "finding"
CLEAN = "clean"


@dataclass
class Seed:
    """One planted case: a Russian tree and the verdict the rule owes it in BOTH spellings."""

    rule: str
    #: What the rule must answer. FINDING - the seed is a violation and has to be reported;
    #: CLEAN - the seed is legal code and has to pass. Both directions are needed: a
    #: Russian-only table makes a rule miss a violation on one project and invent one on the
    #: next, and a seed can only catch the direction it plants.
    expect: str
    #: Why the seed exists - printed next to a disagreement, so the reader learns what broke
    #: rather than which fixture failed.
    note: str
    files: dict[str, str]
    #: The project names the translator needs. Platform names come from the shipped
    #: dictionaries; only the names this seed invents belong here.
    tokens: dict[str, str] = field(default_factory=dict)
    #: The English twin written by hand, one file per Russian file, under the names the
    #: translator would give them - spelled from the platform's own dictionaries, never
    #: guessed. Empty: the translated tree is the English twin, as before.
    english: dict[str, str] = field(default_factory=dict)
    #: Why this disagreement is KNOWN and accepted for now. A gap that cannot be closed
    #: today is still worth planting: deleting the seed would delete the evidence, and the
    #: next reader would rediscover the same thing from scratch. A seed carrying a reason
    #: does not fail the run - but if it starts AGREEING, the run says so loudly, because
    #: that means the gap closed and this note is now a lie.
    known: str = ""


_REGISTER_RU = """\
ВидЭлемента: РегистрСведений
Ид: 1d1f5c60-0000-4000-8000-000000000f01
Имя: Цены
ОбластьВидимости: ВПроекте
"""
_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f02
Имя: Заявки
ОбластьВидимости: ВПроекте
"""


_CATALOG_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-000000000f02
Name: Applications
VisibilityScope: InProject
"""
_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f08
Имя: ФормаЗаявки
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ФормаОбъекта<Заявки.Объект>
"""
_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f08
Name: ApplicationForm
VisibilityScope: InProject
Inherits:
    Type: ObjectForm<Applications.Object>
"""
_ENUM_RU = """\
ВидЭлемента: Перечисление
Ид: 1d1f5c60-0000-4000-8000-000000000f09
Имя: Состояния
ОбластьВидимости: ВПроекте
Элементы:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0a
        Имя: Открыт
"""
_ENUM_EN = """\
ElementKind: Enumeration
Id: 1d1f5c60-0000-4000-8000-000000000f09
Name: States
VisibilityScope: InProject
Items:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0a
        Name: Open
"""
_ATTRIBUTE_RU = """\
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0b
        Имя: Срок
        Тип: {type}
"""
_ATTRIBUTE_EN = """\
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0b
        Name: Deadline
        Type: {type}
"""
_FORM_TOKENS = {"Заявки": "Applications", "ФормаЗаявки": "ApplicationForm"}
#: A button whose click names a handler of the paired module.
_BUTTON_RU = _FORM_RU + "    Содержимое:\n        Тип: Кнопка\n        Имя: Отправить\n        ПриНажатии: Нажатие\n"
_BUTTON_EN = _FORM_EN + "    Content:\n        Type: Button\n        Name: Send\n        OnClick: Click\n"
_BUTTON_TOKENS = {**_FORM_TOKENS, "Отправить": "Send", "Нажатие": "Click", "Источник": "Source",
                  "Событие": "Event", "Другое": "Other"}
#: An input whose change event names a handler of the paired module.
_INPUT_RU = _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Строка>\n        Имя: Поле\n        ПриИзменении: Изменение\n"
_INPUT_EN = _FORM_EN + "    Content:\n        Type: Edit<String>\n        Name: Field\n        OnChange: Change\n"
_INPUT_TOKENS = {**_FORM_TOKENS, "Поле": "Field", "Изменение": "Change", "Источник": "Source",
                 "Событие": "Event"}
#: A number attribute of the catalog – a regular attribute, judged by the keys of its own class.
_NUMBER_ATTRIBUTE_RU = """\
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0b
        Имя: Сумма
        Тип: Число
"""
_NUMBER_ATTRIBUTE_EN = """\
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0b
        Name: Amount
        Type: Number
"""
_NUMBER_ATTRIBUTE_TOKENS = {"Заявки": "Applications", "Сумма": "Amount"}
#: A reference attribute pointing back at the catalog, with the on-delete action that is legal
#: only on an owner deleted outright.
_DELETE_CURRENT_RU = """\
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0b
        Имя: Основание
        Тип: Справочник.Заявки.Ссылка?
        ПриУдаленииОбъектаПоСсылке: УдалятьТекущий
"""
_DELETE_CURRENT_EN = """\
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0b
        Name: Basis
        Type: Catalog.Applications.Reference?
        OnReferencedObjectDeletion: DeleteCurrent
"""
_DELETE_CURRENT_TOKENS = {"Заявки": "Applications", "Основание": "Basis"}
#: A common module of both environments – where a query block needs the server annotation.
_COMMON_MODULE_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-000000000f0c
Имя: Вычисления
ОбластьВидимости: ВПроекте
Окружение: КлиентИСервер
"""
_COMMON_MODULE_EN = """\
ElementKind: CommonModule
Id: 1d1f5c60-0000-4000-8000-000000000f0c
Name: Calculations
VisibilityScope: InProject
Environment: ClientAndServer
"""
_QUERY_RU = "    знч Итог = Запрос{\n        ВЫБРАТЬ ПЕРВЫЕ 1 Наименование ИЗ Справочник.Заявки\n    }\n"
_QUERY_EN = "    val Result = Query{\n        SELECT TOP 1 Name FROM Catalog.Applications\n    }\n"
_QUERY_TOKENS = {"Заявки": "Applications", "Вычисления": "Calculations", "Пересчитать": "Recount",
                 "Итог": "Result"}
#: An event log event without the importance line – the seeds append it, or not.
_EVENT_RU = """\
ВидЭлемента: СобытиеЖурналаСобытий
Ид: 1d1f5c60-0000-4000-8000-000000000f0d
Имя: ЗаявкаПринята
ОбластьВидимости: ВПроекте
ВидСобытия: Информация
"""
_EVENT_EN = """\
ElementKind: EventLogEvent
Id: 1d1f5c60-0000-4000-8000-000000000f0d
Name: ApplicationAccepted
VisibilityScope: InProject
EventKind: Information
"""
_EVENT_PROPERTY_RU = "Важность: Обычная\nСвойства:\n    -\n        Имя: {name}\n        Тип: {type}\n"
_EVENT_PROPERTY_EN = "Importance: Normal\nProperties:\n    -\n        Name: {name}\n        Type: {type}\n"
_EVENT_TOKENS = {"ЗаявкаПринята": "ApplicationAccepted", "Состояния": "States", "Открыт": "Open",
                 "Причина": "Reason", "Состояние": "State"}
#: A catalog with a tabular section and the object form over it – the rows' collection the
#: tabular member rule resolves from the project's own yaml.
_TASKS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f0e
Имя: Задачи
ОбластьВидимости: ВПроекте
ТабличныеЧасти:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0f
        Имя: Шаги
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-000000000f10
                Имя: Шаг
                Тип: Строка
"""
_TASKS_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-000000000f0e
Name: Tasks
VisibilityScope: InProject
TabularParts:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0f
        Name: Steps
        Attributes:
            -
                Id: 1d1f5c60-0000-4000-8000-000000000f10
                Name: Step
                Type: String
"""
_TASK_CARD_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f11
Имя: КарточкаЗадачи
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ФормаОбъекта<Задачи.Объект>
"""
_TASK_CARD_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f11
Name: TaskCard
VisibilityScope: InProject
Inherits:
    Type: ObjectForm<Tasks.Object>
"""
_TASK_TOKENS = {"Задачи": "Tasks", "Шаги": "Steps", "Шаг": "Step", "КарточкаЗадачи": "TaskCard",
                "Проверить": "Check", "Всего": "Total"}
#: The built-in name attribute – dispatched to a class of its own by the name alone.
_NAME_ATTRIBUTE_RU = "Реквизиты:\n    -\n        Имя: Наименование\n"
_NAME_ATTRIBUTE_EN = "Attributes:\n    -\n        Name: Name\n"
#: A reference attribute pointing back at the catalog; `{mark}` is the nullable marker or nothing.
_REFERENCE_ATTRIBUTE_RU = """\
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f0b
        Имя: Основание
        Тип: Заявки.Ссылка{mark}
"""
_REFERENCE_ATTRIBUTE_EN = """\
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f0b
        Name: Basis
        Type: Applications.Reference{mark}
"""
#: An insert of a fixed height under the form's content.
_INSET_RU = "    Содержимое:\n        Тип: КонтейнерHtml\n        Имя: Вставка\n        Высота: 480\n"
_INSET_EN = "    Content:\n        Type: HtmlContainer\n        Name: Inset\n        Height: 480\n"
#: A horizontal row holding an insert next to a label (a single child has nothing to slide
#: against); `{align}` is the alignment line or nothing.
_ROW_RU = ("    Содержимое:\n        Тип: Группа\n        Имя: Ряд\n        Компоновка: Горизонтальная\n"
           "{align}        Содержимое:\n            -\n                Тип: КонтейнерHtml\n"
           "                Имя: Вставка\n            -\n                Тип: Надпись\n"
           "                Заголовок: Есть\n")
_ROW_EN = ("    Content:\n        Type: Group\n        Name: Row\n        Layout: Horizontal\n"
           "{align}        Content:\n            -\n                Type: HtmlContainer\n"
           "                Name: Inset\n            -\n                Type: Label\n"
           "                Title: Есть\n")
_ROW_TOKENS = {**_FORM_TOKENS, "Ряд": "Row", "Вставка": "Inset"}
#: A table over a dynamic list with one column of a fixed width.
_COLUMN_RU = ("    Содержимое:\n        Тип: Таблица<ДинамическийСписок>\n        Имя: Список\n"
              "        Колонки:\n            -\n                Тип: СтандартнаяКолонкаТаблицы\n"
              "                Ширина: 40\n")
_COLUMN_EN = ("    Content:\n        Type: Table<DynamicList>\n        Name: List\n"
              "        Columns:\n            -\n                Type: StandardTableColumn\n"
              "                Width: 40\n")
_COLUMN_TOKENS = {**_FORM_TOKENS, "Список": "List"}
#: Common modules of one environment each – the pair the environment family judges.
_CLIENT_MODULE_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-000000000f12
Имя: Клиентский
ОбластьВидимости: ВПроекте
Окружение: Клиент
"""
_CLIENT_MODULE_EN = """\
ElementKind: CommonModule
Id: 1d1f5c60-0000-4000-8000-000000000f12
Name: ClientSide
VisibilityScope: InProject
Environment: Client
"""
_SERVER_MODULE_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-000000000f13
Имя: Серверный
ОбластьВидимости: ВПроекте
Окружение: Сервер
"""
_SERVER_MODULE_EN = """\
ElementKind: CommonModule
Id: 1d1f5c60-0000-4000-8000-000000000f13
Name: ServerSide
VisibilityScope: InProject
Environment: Server
"""
_SERVER_READ_RU = "@НаСервере @ВПроекте\nметод Прочитать(): Строка\n    возврат \"\"\n;\n"
_SERVER_READ_EN = "@OnServer @InProject\nmethod Read(): String\n    return \"\"\n;\n"
_ENVIRONMENT_TOKENS = {**_FORM_TOKENS, **_TASK_TOKENS, "Клиентский": "ClientSide",
                       "Серверный": "ServerSide", "Вычисления": "Calculations", "Проба": "Probe",
                       "Прочитать": "Read", "Загрузить": "Load", "Отобразить": "Display",
                       "Вызвать": "Invoke"}
#: Query blocks over the catalog: a deletion-mark condition, the habit function and the
#: platform's own null check.
_MARK_QUERY_RU = ("    знч Итог = Запрос{\n        ВЫБРАТЬ Заявка.Наименование ИЗ Заявки КАК Заявка\n"
                  "        ГДЕ НЕ Заявка.ПометкаУдаления\n    }\n")
_MARK_QUERY_EN = ("    val Result = Query{\n        SELECT Application.Name FROM Applications AS Application\n"
                  "        WHERE NOT Application.DeletionMark\n    }\n")
_ISNULL_QUERY_RU = ("    знч Итог = Запрос{\n        ВЫБРАТЬ ЕСТЬNULL(Заявка.Наименование, \"\")\n"
                    "        ИЗ Заявки КАК Заявка\n    }\n")
_ISNULL_QUERY_EN = ("    val Result = Query{\n        SELECT ISNULL(Application.Name, \"\")\n"
                    "        FROM Applications AS Application\n    }\n")
_CASE_QUERY_RU = ("    знч Итог = Запрос{\n        ВЫБРАТЬ ВЫБОР КОГДА Заявка.Наименование ЕСТЬ NULL ТОГДА \"\"\n"
                  "            ИНАЧЕ Заявка.Наименование КОНЕЦ\n        ИЗ Заявки КАК Заявка\n    }\n")
_CASE_QUERY_EN = ("    val Result = Query{\n        SELECT CASE WHEN Application.Name IS NULL THEN \"\"\n"
                  "            ELSE Application.Name END\n        FROM Applications AS Application\n    }\n")
_CATALOG_QUERY_TOKENS = {**_QUERY_TOKENS, "Заявка": "Application"}
#: The form module's handlers: the click handler of the button markup and the closing one.
_HANDLER_TOKENS = {**_BUTTON_TOKENS, "Ерунда": "Nonsense", "Сохранить": "Save",
                   "ПередЗакрытием": "BeforeClose"}
_CLICK_RU = "метод Нажатие(Источник: Кнопка, Событие: СобытиеПриНажатии)\n"
_CLICK_EN = "method Click(Source: Button, Event: OnClickEvent)\n"
_LOAD_TOKENS = {"Заявки": "Applications", "Проба": "Probe", "Строчка": "Line", "Основание": "Basis",
                "Итог": "Result", "СсылкаЗаявки": "ApplicationReference"}
#: A table column over a list row; `{kind}` is the column kind.
_BADGE_COLUMN_RU = ("    Содержимое:\n        Тип: Таблица<СтрокаСписка>\n        Колонки:\n            -\n"
                    "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n                Вид: {kind}\n"
                    "                Изображение: =ДанныеСтроки.Иконка\n")
_BADGE_COLUMN_EN = ("    Content:\n        Type: Table<ListRow>\n        Columns:\n            -\n"
                    "                Type: StandardTableColumn<ListRow>\n                Kind: {kind}\n"
                    "                Image: =RowData.Icon\n")
_BADGE_TOKENS = {**_FORM_TOKENS, "СтрокаСписка": "ListRow", "Иконка": "Icon"}
#: A titled value choice; `{kind}` is the switcher kind line or nothing.
_SWITCHER_RU = ("    Содержимое:\n        Тип: ВыборЗначения<Строка?>\n        Имя: Режим\n"
                "        Заголовок: Режим показа\n{kind}")
_SWITCHER_EN = ("    Content:\n        Type: ValueChoice<String?>\n        Name: Mode\n"
                "        Title: Режим показа\n{kind}")
_SWITCHER_TOKENS = {**_FORM_TOKENS, "Режим": "Mode"}
#: The additional commands of the form; `{items}` is the item list.
_COMMANDS_RU = ("    ДополнительныеКоманды:\n        Тип: ФрагментКомандногоИнтерфейса\n"
                "        Элементы:\n{items}")
_COMMANDS_EN = "    AdditionalCommands:\n        Type: CommandInterfaceFragment\n        Items:\n{items}"
_TOGGLE_RU = ("            -\n                Тип: ОбычнаяКоманда\n                Видимость: =не ПоказыватьВсе\n"
              "                Обработчик: Показать\n            -\n                Тип: ОбычнаяКоманда\n"
              "                Видимость: {second}\n                Обработчик: Скрыть\n")
_TOGGLE_EN = ("            -\n                Type: UsualCommand\n                Visible: =not ShowAll\n"
              "                Handler: Show\n            -\n                Type: UsualCommand\n"
              "                Visible: {second}\n                Handler: Hide\n")
_TOGGLE_TOKENS = {**_FORM_TOKENS, "ПоказыватьВсе": "ShowAll", "Показать": "Show", "Скрыть": "Hide",
                  "ЕстьПраво": "HasRight"}
#: A list form and the table shapes the dynamic-list rules judge.
_LIST_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f17
Имя: СписокЗаявок
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ФормаСписка<Неопределено>
"""
_LIST_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f17
Name: ApplicationList
VisibilityScope: InProject
Inherits:
    Type: ListForm<Undefined>
"""
_LIST_FORM_TOKENS = {"Заявки": "Applications", "СписокЗаявок": "ApplicationList", "Список": "List",
                     "Подпись": "Caption"}
_DYNLIST_COLUMN_RU = ("    Содержимое:\n        Тип: Таблица<ДинамическийСписок<Заявки>>\n        Имя: Список\n"
                      "        Колонки:\n            -\n"
                      "                Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<Заявки>>\n"
                      "                Значение: {value}\n")
_DYNLIST_COLUMN_EN = ("    Content:\n        Type: Table<DynamicList<Applications>>\n        Name: List\n"
                      "        Columns:\n            -\n"
                      "                Type: StandardTableColumn<DynamicListRow<Applications>>\n"
                      "                Value: {value}\n")
#: A constants set with one constant over the project enumeration; `{value}` is its default.
_CONSTANTS_RU = """\
ВидЭлемента: НаборКонстант
Ид: 1d1f5c60-0000-4000-8000-000000000f14
Имя: Настройки
ОбластьВидимости: ВПроекте
Константы:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f15
        Имя: Состояние
        Тип: Состояния?
        ЗначениеПоУмолчанию: {value}
"""
_CONSTANTS_EN = """\
ElementKind: ConstantsSet
Id: 1d1f5c60-0000-4000-8000-000000000f14
Name: Settings
VisibilityScope: InProject
Constants:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f15
        Name: State
        Type: States?
        DefaultValue: {value}
"""
_CONSTANTS_TOKENS = {"Состояния": "States", "Открыт": "Open", "Настройки": "Settings",
                     "Состояние": "State"}
#: A component extending the standard card and declaring one property of its own; `{name}`
#: is the property name.
_CARD_PROPERTY_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f18
Имя: КарточкаЗаявки
ОбластьВидимости: ВПроекте
Наследует:
    Тип: СтандартнаяКарточка
Свойства:
    -
        Имя: {name}
        Тип: Строка
"""
_CARD_PROPERTY_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f18
Name: ApplicationCard
VisibilityScope: InProject
Inherits:
    Type: StandardCard
Properties:
    -
        Name: {name}
        Type: String
"""
_CARD_PROPERTY_TOKENS = {"КарточкаЗаявки": "ApplicationCard", "КрупныйЗаголовок": "LargeTitle",
                         "Заголовок": "Title"}

SEEDS: list[Seed] = [
    Seed(
        rule="structure/xbsl-pair",
        expect=CLEAN,
        note="a module extending a generated type is described by the element's own yaml",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.НаборЗаписей.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Цены": "Prices", "Проба": "Probe"},
    ),
    Seed(
        rule="structure/xbsl-pair",
        expect=FINDING,
        note="a module whose tail is no generated type has no descriptor and is reported",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.Ерунда.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Цены": "Prices", "Ерунда": "Nonsense", "Проба": "Probe"},
    ),
    Seed(
        rule="code/unknown-object-type",
        expect=CLEAN,
        note="a derived type of the kind that generates it",
        files={
            "Цены.yaml": _REGISTER_RU,
            "Цены.xbsl": "метод Проба(Ключ: Цены.КлючЗаписи)\n;\n",
        },
        tokens={"Цены": "Prices", "Проба": "Probe", "Ключ": "Key"},
    ),
    Seed(
        rule="code/unknown-object-type",
        expect=FINDING,
        note="a derived type of ANOTHER kind is reported - the family is per-kind",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Схема: Заявки.СхемаДанных)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Схема": "Schema"},
    ),
    Seed(
        rule="code/undefined-name",
        expect=CLEAN,
        note="the entity protocol is in scope in an object module without being declared",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.Объект.xbsl": "метод Проба()\n    Записать()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe"},
    ),
    Seed(
        rule="style/exception-prefix",
        expect=FINDING,
        note="an exception without the kind word in its name - a prefix in Russian, a suffix "
             "in English",
        files={"Модуль.xbsl": "исключение Авторизация\n;\n"},
        tokens={"Модуль": "Module", "Авторизация": "Authentication"},
    ),
    Seed(
        rule="query/unknown-table",
        expect=FINDING,
        note="a query over a table of neither the platform nor the project",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Итог = Запрос{\n"
                           "        ВЫБРАТЬ Ссылка ИЗ Пользователз\n    }\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Итог": "Result"},
    ),
    Seed(
        rule="naming/prefix-by-kind",
        expect=CLEAN,
        note="an element named after its kind - the kind word leads in Russian and trails in "
             "English",
        files={
            "ФормаЗаявок.yaml": "ВидЭлемента: Форма\n"
                                "Ид: 1d1f5c60-0000-4000-8000-000000000f03\n"
                                "Имя: ФормаЗаявок\n"
                                "ОбластьВидимости: ВПроекте\n",
        },
        tokens={"ФормаЗаявок": "ApplicationsForm"},
    ),
    Seed(
        rule="yaml/unknown-property",
        expect=CLEAN,
        note="the properties a kind declares - the metamodel spells them Russian",
        files={"Заявки.yaml": _CATALOG_RU},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/unknown-property",
        expect=FINDING,
        note="a property the kind does not declare is reported",
        files={
            "Заявки.yaml": _CATALOG_RU + "ЛишнееСвойство: Истина\n",
        },
        tokens={"Заявки": "Applications", "ЛишнееСвойство": "SpareProperty"},
    ),
    Seed(
        rule="code/unknown-member",
        expect=CLEAN,
        note="a member of a stdlib type - the catalog stores the members Russian",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Список = новый Массив<Строка>()\n"
                           "    Список.Добавить(\"a\")\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Список": "List"},
    ),
    Seed(
        rule="code/unknown-member",
        expect=FINDING,
        note="a member no stdlib type has is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Список = новый Массив<Строка>()\n"
                           "    Список.НетТакогоМетода()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Список": "List",
                "НетТакогоМетода": "NoSuchMethod"},
        known="the rule skips Latin member spellings on purpose, and the type catalog stores "
              "members in Russian alone: translating the member set would report every "
              "correct English member whose Russian name the dictionaries do not pair - 287 "
              "of them, mostly enumeration values, which live in the ui terms rather than in "
              "the compiler dictionary. Closing this needs the member vocabulary completed, "
              "not a change to the rule.",
    ),
    Seed(
        rule="code/unknown-type",
        expect=CLEAN,
        note="a stdlib type in a signature - the type catalog is keyed Russian",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: Строка)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value"},
    ),
    Seed(
        rule="code/unknown-type",
        expect=FINDING,
        note="a type of neither the platform nor the project is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Значение: НесуществующийТип)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значение": "Value",
                "НесуществующийТип": "NonexistentType"},
    ),
    # --- Vocabulary seeds: rules that match source text against the platform's own tables.
    # The English twin of each is written by hand from terms.json / uiterms.json / the ui
    # schema, so the rule is judged on the platform's spelling and the translator apart.
    Seed(
        rule="yaml/unknown-component-property",
        expect=CLEAN,
        note="a property the component declares - the schema spells it Russian, the file may not",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Строка>\n"
                                "        Имя: Поле\n        ЗамещающийТекст: \"Введите текст\"\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<String>\n"
                                    "        Name: Field\n        PlaceholderText: \"Введите текст\"\n",
        },
        tokens={**_FORM_TOKENS, "Поле": "Field"},
    ),
    Seed(
        rule="yaml/unknown-component-property",
        expect=FINDING,
        note="a property of ANOTHER component (an input's placeholder on a checkbox) is reported",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Флажок\n"
                                "        Имя: Согласие\n        ЗамещающийТекст: \"Введите текст\"\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Checkbox\n"
                                    "        Name: Consent\n        PlaceholderText: \"Введите текст\"\n",
        },
        tokens={**_FORM_TOKENS, "Согласие": "Consent"},
    ),
    Seed(
        rule="yaml/unknown-enum-value",
        expect=CLEAN,
        note="a value of the property's own enumeration - the ui vocabulary spells it English",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Компоновка: Вертикальная\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Layout: Vertical\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/unknown-enum-value",
        expect=FINDING,
        note="a value copied from the neighbouring axis (End belongs to the horizontal one) is "
             "reported",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        ВыравниваниеСодержимогоПоВертикали: Конец\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        ContentVerticalAlign: End\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/unknown-type",
        expect=CLEAN,
        note="a stdlib type as an attribute type - the catalog is keyed Russian, the English key "
             "is derived on load",
        files={"Заявки.yaml": _CATALOG_RU + _ATTRIBUTE_RU.format(type="Дата")},
        english={"Applications.yaml": _CATALOG_EN + _ATTRIBUTE_EN.format(type="Date")},
        tokens={"Заявки": "Applications", "Срок": "Deadline"},
    ),
    Seed(
        rule="yaml/unknown-type",
        expect=FINDING,
        note="a type of neither the platform nor the project is reported",
        files={"Заявки.yaml": _CATALOG_RU + _ATTRIBUTE_RU.format(type="НесуществующийТип")},
        english={"Applications.yaml": _CATALOG_EN + _ATTRIBUTE_EN.format(type="NonexistentType")},
        tokens={"Заявки": "Applications", "Срок": "Deadline",
                "НесуществующийТип": "NonexistentType"},
    ),
    Seed(
        rule="yaml/unexpected-type-argument",
        expect=CLEAN,
        note="the argument spelled out equals the default of the bare head - the same type",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Команды:\n"
                                "            Тип: ФрагментКомандногоИнтерфейса<Команда>\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Commands:\n"
                                    "            Type: CommandInterfaceFragment<Command>\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/unexpected-type-argument",
        expect=FINDING,
        note="an argument on a property the schema declares bare, differing from the default, is "
             "reported",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Команды:\n"
                                "            Тип: ФрагментКомандногоИнтерфейса<ОбычнаяКоманда>\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Commands:\n"
                                    "            Type: CommandInterfaceFragment<UsualCommand>\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="form/unknown-handler",
        expect=CLEAN,
        note="the handler an event key names exists in the paired module - the key is spelled by "
             "the ui schema",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": "метод Нажатие(Источник: Кнопка, Событие: СобытиеПриНажатии)\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": "method Click(Source: Button, Event: OnClickEvent)\n;\n",
        },
        tokens=_BUTTON_TOKENS,
    ),
    Seed(
        rule="form/unknown-handler",
        expect=FINDING,
        note="a handler the paired module does not declare is reported",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": "метод Другое()\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": "method Other()\n;\n",
        },
        tokens=_BUTTON_TOKENS,
    ),
    Seed(
        rule="form/handler-signature",
        expect=CLEAN,
        note="the handler declares the event type with the component's own argument - the types "
             "are compared folded into one spelling",
        files={
            "ФормаЗаявки.yaml": _INPUT_RU,
            "ФормаЗаявки.xbsl": "метод Изменение(Источник: ПолеВвода<Строка>, "
                                "Событие: СобытиеПриИзменении<Строка>)\n;\n",
        },
        english={
            "ApplicationForm.yaml": _INPUT_EN,
            "ApplicationForm.xbsl": "method Change(Source: Edit<String>, "
                                    "Event: OnChangeEvent<String>)\n;\n",
        },
        tokens=_INPUT_TOKENS,
    ),
    Seed(
        rule="form/handler-signature",
        expect=FINDING,
        note="the same event type declared with another argument is reported",
        files={
            "ФормаЗаявки.yaml": _INPUT_RU,
            "ФормаЗаявки.xbsl": "метод Изменение(Источник: ПолеВвода<Строка>, "
                                "Событие: СобытиеПриИзменении<Число>)\n;\n",
        },
        english={
            "ApplicationForm.yaml": _INPUT_EN,
            "ApplicationForm.xbsl": "method Change(Source: Edit<String>, "
                                    "Event: OnChangeEvent<Number>)\n;\n",
        },
        tokens=_INPUT_TOKENS,
    ),
    Seed(
        rule="code/catch-non-exception",
        expect=CLEAN,
        note="a stdlib exception in a catch - recognized through the type hierarchy of the catalog",
        files={
            "Заявки.xbsl": "метод Проба()\n    попытка\n        знч Итог = 1\n"
                           "    поймать Ошибка: ИсключениеАрифметики\n    ;\n;\n",
        },
        english={
            "Applications.xbsl": "method Probe()\n    try\n        val Result = 1\n"
                                 "    catch Error: ArithmeticException\n    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Итог": "Result", "Ошибка": "Error"},
    ),
    Seed(
        rule="code/catch-non-exception",
        expect=FINDING,
        note="a stdlib type outside the exception hierarchy in a catch is reported",
        files={
            "Заявки.xbsl": "метод Проба()\n    попытка\n        знч Итог = 1\n"
                           "    поймать Ошибка: Строка\n    ;\n;\n",
        },
        english={
            "Applications.xbsl": "method Probe()\n    try\n        val Result = 1\n"
                                 "    catch Error: String\n    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Итог": "Result", "Ошибка": "Error"},
    ),
    Seed(
        rule="code/use-needs-closeable",
        expect=CLEAN,
        note="a closeable under `исп` - the ancestor chain of the catalog says so",
        files={"Заявки.xbsl": "метод Проба()\n    исп Доступ = новый КонтекстДоступа()\n;\n"},
        english={"Applications.xbsl": "method Probe()\n    use Access = new AccessContext()\n;\n"},
        tokens={"Заявки": "Applications", "Проба": "Probe", "Доступ": "Access"},
    ),
    Seed(
        rule="code/use-needs-closeable",
        expect=FINDING,
        note="a described type whose chain has no Closeable under `исп` is reported",
        files={"Заявки.xbsl": "метод Проба()\n    исп Чтение = новый ЧтениеXml()\n;\n"},
        english={"Applications.xbsl": "method Probe()\n    use Reading = new XmlReader()\n;\n"},
        tokens={"Заявки": "Applications", "Проба": "Probe", "Чтение": "Reading"},
    ),
    Seed(
        rule="code/unknown-static-member",
        expect=CLEAN,
        note="a static member reached through the type name - the catalog stores the members "
             "Russian, the type under both names",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Когда = ДатаВремя.Сейчас()\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe()\n    val When = DateTime.Now()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Когда": "When"},
    ),
    Seed(
        rule="code/unknown-static-member",
        expect=FINDING,
        note="a member the type does not have, reached through the type name, is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Когда = ДатаВремя.НетТакого()\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe()\n    val When = DateTime.NoSuchThing()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Когда": "When",
                "НетТакого": "NoSuchThing"},
    ),
    Seed(
        rule="code/unknown-ns-object",
        expect=CLEAN,
        note="a project object under its kind namespace with the reference facet - the kind and "
             "the facet are both platform words",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Заявка: Справочник.Заявки.Ссылка)\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe(Application: Catalog.Applications.Reference)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Заявка": "Application"},
    ),
    Seed(
        rule="code/unknown-ns-object",
        expect=FINDING,
        note="an object the project does not declare under a kind namespace is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Заявка: Справочник.Ерунда.Ссылка)\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe(Application: Catalog.Nonsense.Reference)\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Заявка": "Application",
                "Ерунда": "Nonsense"},
    ),
    Seed(
        rule="code/unknown-enum-value",
        expect=CLEAN,
        note="a built-in member of the enumeration type (ПоИмени) is not a value - the member set "
             "comes from the catalog in both spellings",
        files={
            "Состояния.yaml": _ENUM_RU,
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Найдено = Состояния.ПоИмени(\"Открыт\")\n;\n",
        },
        english={
            "States.yaml": _ENUM_EN,
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe()\n    val Found = States.ByName(\"Открыт\")\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Состояния": "States",
                "Открыт": "Open", "Найдено": "Found"},
    ),
    Seed(
        rule="code/unknown-enum-value",
        expect=FINDING,
        note="a value the enumeration does not declare is reported",
        files={
            "Состояния.yaml": _ENUM_RU,
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    знч Текущее = Состояния.Закрыт\n;\n",
        },
        english={
            "States.yaml": _ENUM_EN,
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe()\n    val Current = States.Closed\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Состояния": "States",
                "Открыт": "Open", "Закрыт": "Closed", "Текущее": "Current"},
    ),
    Seed(
        rule="yaml/enum-needs-nullable",
        expect=CLEAN,
        note="an input over a project enumeration with the nullable marker - the shape the rule "
             "asks for",
        files={
            "Состояния.yaml": _ENUM_RU,
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Состояния?>\n"
                                "        Имя: Состояние\n",
        },
        english={
            "States.yaml": _ENUM_EN,
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<States?>\n"
                                    "        Name: State\n",
        },
        tokens={**_FORM_TOKENS, "Состояния": "States", "Открыт": "Open", "Состояние": "State"},
    ),
    Seed(
        rule="yaml/enum-needs-nullable",
        expect=FINDING,
        note="an input over an enumeration without a default and without '?' is reported",
        files={
            "Состояния.yaml": _ENUM_RU,
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Состояния>\n"
                                "        Имя: Состояние\n",
        },
        english={
            "States.yaml": _ENUM_EN,
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<States>\n"
                                    "        Name: State\n",
        },
        tokens={**_FORM_TOKENS, "Состояния": "States", "Открыт": "Open", "Состояние": "State"},
    ),
    Seed(
        rule="code/reserved-name",
        expect=FINDING,
        note="a structure field named after the type keyword - the server apply rejects it",
        files={"Заявки.xbsl": "структура Данные\n    пер Тип: Строка\n;\n"},
        english={"Applications.xbsl": "structure Data\n    var Type: String\n;\n"},
        tokens={"Заявки": "Applications", "Данные": "Data"},
    ),
    Seed(
        rule="code/global-unavailable",
        expect=CLEAN,
        note="a client-only global in a method the annotation pins to the client - the annotation "
             "is read in both spellings",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "@НаКлиенте\nметод Проба()\n    Сообщить(\"Привет\")\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "@OnClient\nmethod Probe()\n    Message(\"Привет\")\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe"},
    ),
    Seed(
        rule="code/global-unavailable",
        expect=FINDING,
        note="a client-only global in a catalog module, which runs on the server - the "
             "availability table is keyed by the Russian names the docs print",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n    Сообщить(\"Привет\")\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe()\n    Message(\"Привет\")\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe"},
    ),
    # --- Rules keyed by platform names the file may spell either way: the class of an
    # attribute, a deletion mode, the contract of an event, the environment of a module, the
    # rows of a tabular section.
    Seed(
        rule="yaml/unknown-attribute-property",
        expect=CLEAN,
        note="a key the attribute's own class declares – the metamodel spells it Russian and "
             "records the English next to it",
        files={"Заявки.yaml": _CATALOG_RU + _NUMBER_ATTRIBUTE_RU + "        ДлинаЦелойЧасти: 12\n"},
        english={
            "Applications.yaml": _CATALOG_EN + _NUMBER_ATTRIBUTE_EN + "        IntegerPartLength: 12\n",
        },
        tokens=_NUMBER_ATTRIBUTE_TOKENS,
    ),
    Seed(
        rule="yaml/unknown-attribute-property",
        expect=FINDING,
        note="a key of ANOTHER attribute class (the built-in name's length on a number) is "
             "reported",
        files={"Заявки.yaml": _CATALOG_RU + _NUMBER_ATTRIBUTE_RU + "        Длина: 12\n"},
        english={"Applications.yaml": _CATALOG_EN + _NUMBER_ATTRIBUTE_EN + "        Length: 12\n"},
        tokens=_NUMBER_ATTRIBUTE_TOKENS,
    ),
    Seed(
        rule="code/query-needs-server",
        expect=CLEAN,
        note="a query block under the server annotation in a module of both environments – the "
             "annotation and the environment value are read in both spellings",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Пересчитать()\n" + _QUERY_RU + ";\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Recount()\n" + _QUERY_EN + ";\n",
        },
        tokens=_QUERY_TOKENS,
    ),
    Seed(
        rule="code/query-needs-server",
        expect=FINDING,
        note="the same query block in a method without the annotation is reported",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "метод Пересчитать()\n" + _QUERY_RU + ";\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "method Recount()\n" + _QUERY_EN + ";\n",
        },
        tokens=_QUERY_TOKENS,
    ),
    Seed(
        rule="yaml/delete-current-needs-immediate",
        expect=CLEAN,
        note="the on-delete action on an owner deleted outright – the mode and the action are "
             "enumeration values of the metamodel",
        files={"Заявки.yaml": _CATALOG_RU + "РежимУдаления: Немедленно\n" + _DELETE_CURRENT_RU},
        english={
            "Applications.yaml": _CATALOG_EN + "DeletionMode: Immediately\n" + _DELETE_CURRENT_EN,
        },
        tokens=_DELETE_CURRENT_TOKENS,
    ),
    Seed(
        rule="yaml/delete-current-needs-immediate",
        expect=FINDING,
        note="the same action on an owner that never names its mode – the default only marks – "
             "is reported",
        files={"Заявки.yaml": _CATALOG_RU + _DELETE_CURRENT_RU},
        english={"Applications.yaml": _CATALOG_EN + _DELETE_CURRENT_EN},
        tokens=_DELETE_CURRENT_TOKENS,
    ),
    Seed(
        rule="yaml/event-needs-importance",
        expect=CLEAN,
        note="an event that declares its importance – the key and the value are metamodel names",
        files={"ЗаявкаПринята.yaml": _EVENT_RU + "Важность: Обычная\n"},
        english={"ApplicationAccepted.yaml": _EVENT_EN + "Importance: Normal\n"},
        tokens=_EVENT_TOKENS,
    ),
    Seed(
        rule="yaml/event-needs-importance",
        expect=FINDING,
        note="an event silent about its importance leaves it to every constructor – reported on "
             "the line declaring the kind",
        files={"ЗаявкаПринята.yaml": _EVENT_RU},
        english={"ApplicationAccepted.yaml": _EVENT_EN},
        tokens=_EVENT_TOKENS,
    ),
    Seed(
        rule="yaml/event-property-type",
        expect=CLEAN,
        note="a property typed by a member of the closed list – the list is resolved into both "
             "spellings through the term dictionary",
        files={
            "ЗаявкаПринята.yaml": _EVENT_RU + _EVENT_PROPERTY_RU.format(name="Причина", type="Строка"),
        },
        english={
            "ApplicationAccepted.yaml":
                _EVENT_EN + _EVENT_PROPERTY_EN.format(name="Reason", type="String"),
        },
        tokens=_EVENT_TOKENS,
    ),
    Seed(
        rule="yaml/event-property-type",
        expect=FINDING,
        note="a property typed by a project enumeration – outside the closed list – is reported",
        files={
            "Состояния.yaml": _ENUM_RU,
            "ЗаявкаПринята.yaml":
                _EVENT_RU + _EVENT_PROPERTY_RU.format(name="Состояние", type="Состояния"),
        },
        english={
            "States.yaml": _ENUM_EN,
            "ApplicationAccepted.yaml":
                _EVENT_EN + _EVENT_PROPERTY_EN.format(name="State", type="States"),
        },
        tokens=_EVENT_TOKENS,
    ),
    Seed(
        rule="code/unknown-tabular-member",
        expect=CLEAN,
        note="an array member on the rows of a tabular section, reached through the form's data "
             "object – the section is resolved from the project's own yaml",
        files={
            "Задачи.yaml": _TASKS_RU,
            "КарточкаЗадачи.yaml": _TASK_CARD_RU,
            "КарточкаЗадачи.xbsl": "метод Проверить()\n    знч Всего = Объект.Шаги.Размер()\n;\n",
        },
        english={
            "Tasks.yaml": _TASKS_EN,
            "TaskCard.yaml": _TASK_CARD_EN,
            "TaskCard.xbsl": "method Check()\n    val Total = Object.Steps.Size()\n;\n",
        },
        tokens=_TASK_TOKENS,
    ),
    Seed(
        rule="code/unknown-tabular-member",
        expect=FINDING,
        note="a member the array does not have (the other platform's Count) is reported",
        files={
            "Задачи.yaml": _TASKS_RU,
            "КарточкаЗадачи.yaml": _TASK_CARD_RU,
            "КарточкаЗадачи.xbsl": "метод Проверить()\n    знч Всего = Объект.Шаги.Количество()\n;\n",
        },
        english={
            "Tasks.yaml": _TASKS_EN,
            "TaskCard.yaml": _TASK_CARD_EN,
            "TaskCard.xbsl": "method Check()\n    val Total = Object.Steps.Count()\n;\n",
        },
        tokens=_TASK_TOKENS,
        known="the rule inherits the Latin silencer of code/unknown-member: a member spelled in "
              "Latin is not judged at all, and the array members of the catalog are Russian "
              "alone. Closing this needs the member vocabulary completed – the same gap as the "
              "unknown-member seed above, not a change to the rule.",
    ),
    # --- The built-in attributes, the reference facet and the field types: names the yaml
    # spells either way and the rules resolve through the term dictionary.
    Seed(
        rule="yaml/standard-field-length",
        expect=CLEAN,
        note="the built-in name at the platform limit – the built-in is told by its dictionary "
             "spelling",
        files={"Заявки.yaml": _CATALOG_RU + _NAME_ATTRIBUTE_RU + "        Длина: 400\n"},
        english={"Applications.yaml": _CATALOG_EN + _NAME_ATTRIBUTE_EN + "        Length: 400\n"},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/standard-field-length",
        expect=FINDING,
        note="the built-in name over the limit is reported",
        files={"Заявки.yaml": _CATALOG_RU + _NAME_ATTRIBUTE_RU + "        Длина: 401\n"},
        english={"Applications.yaml": _CATALOG_EN + _NAME_ATTRIBUTE_EN + "        Length: 401\n"},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/presentation-field",
        expect=CLEAN,
        note="the presentation names the built-in name attribute – a string by its dispatched "
             "class",
        files={"Заявки.yaml": _CATALOG_RU + "Представление: Наименование\n" + _NAME_ATTRIBUTE_RU},
        english={"Applications.yaml": _CATALOG_EN + "Presentation: Name\n" + _NAME_ATTRIBUTE_EN},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/presentation-field",
        expect=FINDING,
        note="a presentation naming no attribute of the object is reported",
        files={"Заявки.yaml": _CATALOG_RU + "Представление: Ерунда\n" + _NAME_ATTRIBUTE_RU},
        english={"Applications.yaml": _CATALOG_EN + "Presentation: Nonsense\n" + _NAME_ATTRIBUTE_EN},
        tokens={"Заявки": "Applications", "Ерунда": "Nonsense"},
    ),
    Seed(
        rule="yaml/item-id-required",
        expect=CLEAN,
        note="the built-in name attribute carries no identifier – its dispatched class declares "
             "none",
        files={"Заявки.yaml": _CATALOG_RU + _NAME_ATTRIBUTE_RU},
        english={"Applications.yaml": _CATALOG_EN + _NAME_ATTRIBUTE_EN},
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="yaml/item-id-required",
        expect=FINDING,
        note="a regular attribute without its identifier is reported",
        files={"Заявки.yaml": _CATALOG_RU + "Реквизиты:\n    -\n        Имя: Сумма\n        Тип: Число\n"},
        english={
            "Applications.yaml": _CATALOG_EN + "Attributes:\n    -\n        Name: Amount\n        Type: Number\n",
        },
        tokens=_NUMBER_ATTRIBUTE_TOKENS,
    ),
    Seed(
        rule="yaml/ref-needs-nullable",
        expect=CLEAN,
        note="a reference attribute with the nullable marker – the facet is read in both spellings",
        files={"Заявки.yaml": _CATALOG_RU + _REFERENCE_ATTRIBUTE_RU.format(mark="?")},
        english={"Applications.yaml": _CATALOG_EN + _REFERENCE_ATTRIBUTE_EN.format(mark="?")},
        tokens=_DELETE_CURRENT_TOKENS,
    ),
    Seed(
        rule="yaml/ref-needs-nullable",
        expect=FINDING,
        note="a reference attribute without the marker has no default value – reported",
        files={"Заявки.yaml": _CATALOG_RU + _REFERENCE_ATTRIBUTE_RU.format(mark="")},
        english={"Applications.yaml": _CATALOG_EN + _REFERENCE_ATTRIBUTE_EN.format(mark="")},
        tokens=_DELETE_CURRENT_TOKENS,
    ),
    Seed(
        rule="code/ref-field-needs-req",
        expect=CLEAN,
        note="a required structure field of a reference type – the facet after the dot is the "
             "platform's word",
        files={"Заявки.xbsl": "структура Данные\n    обз пер Основание: Заявки.Ссылка\n;\n"},
        english={"Applications.xbsl": "structure Data\n    req var Basis: Applications.Reference\n;\n"},
        tokens={"Заявки": "Applications", "Данные": "Data", "Основание": "Basis"},
    ),
    Seed(
        rule="code/ref-field-needs-req",
        expect=FINDING,
        note="the same field without `обз`, `?` or an initializer is reported",
        files={"Заявки.xbsl": "структура Данные\n    пер Основание: Заявки.Ссылка\n;\n"},
        english={"Applications.xbsl": "structure Data\n    var Basis: Applications.Reference\n;\n"},
        tokens={"Заявки": "Applications", "Данные": "Data", "Основание": "Basis"},
    ),
    Seed(
        rule="yaml/date-input-needs-plain-date",
        expect=CLEAN,
        note="a date input over the plain type – the component and the type are catalog names",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Дата>\n"
                                "        Имя: Срок\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<Date>\n"
                                    "        Name: Deadline\n",
        },
        tokens={**_FORM_TOKENS, "Срок": "Deadline"},
    ),
    Seed(
        rule="yaml/date-input-needs-plain-date",
        expect=FINDING,
        note="the nullable date argument the renderer drops is reported",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Дата?>\n"
                                "        Имя: Срок\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<Date?>\n"
                                    "        Name: Deadline\n",
        },
        tokens={**_FORM_TOKENS, "Срок": "Deadline"},
    ),
    # --- Rendering and layout: the component types, the layout values and the size keys are
    # all names of the ui schema.
    Seed(
        rule="yaml/empty-group-sized",
        expect=CLEAN,
        note="a sized group with content – the content key is read by its schema spelling",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n        Высота: 20\n"
                                "        Содержимое:\n            Тип: Надпись\n"
                                "            Заголовок: Есть\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n        Height: 20\n"
                                    "        Content:\n            Type: Label\n"
                                    "            Title: Есть\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/empty-group-sized",
        expect=FINDING,
        note="a sized group without content is dropped by the renderer – reported",
        files={"ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n        Высота: 20\n"},
        english={"ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n        Height: 20\n"},
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/insert-row-needs-align",
        expect=CLEAN,
        note="a horizontal row holding an insert, aligned explicitly – the layout value and the "
             "alignment key are schema names",
        files={
            "ФормаЗаявки.yaml":
                _FORM_RU + _ROW_RU.format(align="        ВыравниваниеСодержимогоПоВертикали: Верх\n"),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _ROW_EN.format(align="        ContentVerticalAlign: Top\n"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="yaml/insert-row-needs-align",
        expect=FINDING,
        note="the same row left to the baseline alignment is reported",
        files={"ФормаЗаявки.yaml": _FORM_RU + _ROW_RU.format(align="")},
        english={"ApplicationForm.yaml": _FORM_EN + _ROW_EN.format(align="")},
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="yaml/size-needs-no-stretch",
        expect=CLEAN,
        note="a fixed height with the stretch switched off – the stretch key is spelled by the "
             "schema",
        files={"ФормаЗаявки.yaml": _FORM_RU + _INSET_RU + "        РастягиватьПоВертикали: Ложь\n"},
        english={"ApplicationForm.yaml": _FORM_EN + _INSET_EN + "        VerticalStretch: False\n"},
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="yaml/size-needs-no-stretch",
        expect=FINDING,
        note="a fixed height with the stretch left to the platform is reported",
        files={"ФормаЗаявки.yaml": _FORM_RU + _INSET_RU},
        english={"ApplicationForm.yaml": _FORM_EN + _INSET_EN},
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="yaml/col-width-needs-no-stretch",
        expect=CLEAN,
        note="a fixed column width with the stretch switched off – the column type and the key "
             "are schema names",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + _COLUMN_RU + "                РастягиватьПоГоризонтали: Ложь\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _COLUMN_EN + "                HorizontalStretch: False\n",
        },
        tokens=_COLUMN_TOKENS,
    ),
    Seed(
        rule="yaml/col-width-needs-no-stretch",
        expect=FINDING,
        note="a fixed column width that acts as a share is reported",
        files={"ФормаЗаявки.yaml": _FORM_RU + _COLUMN_RU},
        english={"ApplicationForm.yaml": _FORM_EN + _COLUMN_EN},
        tokens=_COLUMN_TOKENS,
    ),
    Seed(
        rule="yaml/card-literal-stretch-weight",
        expect=CLEAN,
        note="a literal weight on a plain group – only a card collapses, and the card list comes "
             "from the ui schema",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Компоновка: Вертикальная\n        ВесПриРастягивании: 1\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Layout: Vertical\n        WeightOnStretch: 1\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/card-literal-stretch-weight",
        expect=FINDING,
        note="a literal weight on a card is reported – the component type is a schema name",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: СтандартнаяКарточка\n"
                                "        ВесПриРастягивании: 1\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: StandardCard\n"
                                    "        WeightOnStretch: 1\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/matrix-group-max-width",
        expect=CLEAN,
        note="the maximum left automatic on a matrix group – the value the platform spells Auto",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Компоновка: Матричная\n        МаксимальнаяШирина: Авто\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Layout: Matrix\n        MaxWidth: Auto\n",
        },
        tokens=_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/matrix-group-max-width",
        expect=FINDING,
        note="a numeric maximum on a matrix group is reported – the layout value is an "
             "enumeration of the schema",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: Группа\n"
                                "        Компоновка: Матричная\n        МаксимальнаяШирина: 2000\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Group\n"
                                    "        Layout: Matrix\n        MaxWidth: 2000\n",
        },
        tokens=_FORM_TOKENS,
    ),
    # --- The environment family: the module environment is a metamodel enumeration, the
    # annotations are read in both spellings.
    Seed(
        rule="code/server-annotation-in-client-module",
        expect=CLEAN,
        note="a client module with the client annotation – how such a module is written",
        files={
            "Клиентский.yaml": _CLIENT_MODULE_RU,
            "Клиентский.xbsl": "@НаКлиенте\nметод Проба()\n    возврат\n;\n",
        },
        english={
            "ClientSide.yaml": _CLIENT_MODULE_EN,
            "ClientSide.xbsl": "@OnClient\nmethod Probe()\n    return\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/server-annotation-in-client-module",
        expect=FINDING,
        note="the server annotation in a client module is reported – the apply refuses it",
        files={
            "Клиентский.yaml": _CLIENT_MODULE_RU,
            "Клиентский.xbsl": "@НаСервере\nметод Проба()\n    возврат\n;\n",
        },
        english={
            "ClientSide.yaml": _CLIENT_MODULE_EN,
            "ClientSide.xbsl": "@OnServer\nmethod Probe()\n    return\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-annotation-in-server-module",
        expect=CLEAN,
        note="a server module with the server annotation",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаСервере\nметод Проба()\n    возврат\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnServer\nmethod Probe()\n    return\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-annotation-in-server-module",
        expect=FINDING,
        note="the client annotation in a server module is reported",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаКлиенте\nметод Проба()\n    возврат\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnClient\nmethod Probe()\n    return\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/server-module-in-client-context",
        expect=CLEAN,
        note="a server module reached from a form method the annotation pins to the server",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": _SERVER_READ_RU,
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": "@НаСервере\nметод Загрузить()\n    Серверный.Прочитать()\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": _SERVER_READ_EN,
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": "@OnServer\nmethod Load()\n    ServerSide.Read()\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/server-module-in-client-context",
        expect=FINDING,
        note="the same call from a plain form method, which runs on the client, is reported",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": _SERVER_READ_RU,
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": "метод Загрузить()\n    Серверный.Прочитать()\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": _SERVER_READ_EN,
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": "method Load()\n    ServerSide.Read()\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-module-in-http-service",
        expect=CLEAN,
        note="a server module reaching a module of both environments – its members exist on the "
             "server",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаСервере\nметод Вызвать(): Строка\n    возврат Вычисления.Отобразить()\n;\n",
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Отобразить(): Строка\n    возврат \"\"\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnServer\nmethod Invoke(): String\n    return Calculations.Display()\n;\n",
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Display(): String\n    return \"\"\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-module-in-http-service",
        expect=FINDING,
        note="a server module reaching a client module is reported – the environment value is a "
             "metamodel enumeration",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаСервере\nметод Вызвать(): Строка\n    возврат Клиентский.Отобразить()\n;\n",
            "Клиентский.yaml": _CLIENT_MODULE_RU,
            "Клиентский.xbsl": "@НаКлиенте\nметод Отобразить(): Строка\n    возврат \"\"\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnServer\nmethod Invoke(): String\n    return ClientSide.Display()\n;\n",
            "ClientSide.yaml": _CLIENT_MODULE_EN,
            "ClientSide.xbsl": "@OnClient\nmethod Display(): String\n    return \"\"\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/component-in-server-context",
        expect=CLEAN,
        note="an interface component reached from a method pinned to the client",
        files={
            "КарточкаЗадачи.yaml": _TASK_CARD_RU,
            "КарточкаЗадачи.xbsl": "@НаКлиенте\nметод Проверить(): Строка\n    возврат \"\"\n;\n",
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаКлиенте\nметод Отобразить(): Строка\n"
                               "    возврат КарточкаЗадачи.Проверить()\n;\n",
        },
        english={
            "TaskCard.yaml": _TASK_CARD_EN,
            "TaskCard.xbsl": "@OnClient\nmethod Check(): String\n    return \"\"\n;\n",
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnClient\nmethod Display(): String\n"
                                 "    return TaskCard.Check()\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/component-in-server-context",
        expect=FINDING,
        note="the same access from an unannotated method of a module of both environments, "
             "compiled for the server too, is reported",
        files={
            "КарточкаЗадачи.yaml": _TASK_CARD_RU,
            "КарточкаЗадачи.xbsl": "@НаКлиенте\nметод Проверить(): Строка\n    возврат \"\"\n;\n",
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "метод Отобразить(): Строка\n    возврат КарточкаЗадачи.Проверить()\n;\n",
        },
        english={
            "TaskCard.yaml": _TASK_CARD_EN,
            "TaskCard.xbsl": "@OnClient\nmethod Check(): String\n    return \"\"\n;\n",
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "method Display(): String\n    return TaskCard.Check()\n;\n",
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    # --- The query language: the deletion mode of the object, the mark field and the habit
    # function are names the block may spell either way.
    Seed(
        rule="query/deletion-mark-immediate",
        expect=CLEAN,
        note="a deletion-mark condition on an object the platform only marks – the default mode",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Пересчитать()\n" + _MARK_QUERY_RU + ";\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Recount()\n" + _MARK_QUERY_EN + ";\n",
        },
        tokens=_CATALOG_QUERY_TOKENS,
    ),
    Seed(
        rule="query/deletion-mark-immediate",
        expect=FINDING,
        note="the same condition on an object deleted outright, which has no mark field, is "
             "reported",
        files={
            "Заявки.yaml": _CATALOG_RU + "РежимУдаления: Немедленно\n",
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Пересчитать()\n" + _MARK_QUERY_RU + ";\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN + "DeletionMode: Immediately\n",
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Recount()\n" + _MARK_QUERY_EN + ";\n",
        },
        tokens=_CATALOG_QUERY_TOKENS,
    ),
    Seed(
        rule="query/no-isnull",
        expect=CLEAN,
        note="the null check spelled the platform's way – the query words come from the term "
             "dictionary",
        files={
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Пересчитать()\n" + _CASE_QUERY_RU + ";\n",
        },
        english={
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Recount()\n" + _CASE_QUERY_EN + ";\n",
        },
        tokens=_CATALOG_QUERY_TOKENS,
    ),
    Seed(
        rule="query/no-isnull",
        expect=FINDING,
        note="the habit function of the other platform, in either spelling, is reported",
        files={
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": "@НаСервере\nметод Пересчитать()\n" + _ISNULL_QUERY_RU + ";\n",
        },
        english={
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": "@OnServer\nmethod Recount()\n" + _ISNULL_QUERY_EN + ";\n",
        },
        tokens=_CATALOG_QUERY_TOKENS,
    ),
    # --- Form modules: the components root, the handler names and the stdlib members the
    # module may spell either way.
    Seed(
        rule="code/unknown-form-component",
        expect=CLEAN,
        note="a component the paired markup declares, reached through the components root – "
             "the root and the name key are dictionary words",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": "@НаКлиенте\n" + _CLICK_RU + "    Компоненты.Отправить.Видимость = Ложь\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": "@OnClient\n" + _CLICK_EN + "    Components.Send.Visible = False\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/unknown-form-component",
        expect=FINDING,
        note="a name the markup does not declare is reported",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": "@НаКлиенте\n" + _CLICK_RU + "    Компоненты.Ерунда.Видимость = Ложь\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": "@OnClient\n" + _CLICK_EN + "    Components.Nonsense.Visible = False\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/server-call-from-handler",
        expect=CLEAN,
        note="a client handler calling a server method opened to the client – the annotations "
             "are read in both spellings",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": _CLICK_RU + "    Сохранить()\n;\n\n"
                                "@НаСервере @ДоступноСКлиента\nметод Сохранить()\n    возврат\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": _CLICK_EN + "    Save()\n;\n\n"
                                    "@OnServer @AvailableFromClient\nmethod Save()\n    return\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/server-call-from-handler",
        expect=FINDING,
        note="the same call to a server method not opened to the client is reported – the handler "
             "is told by the event key of the markup",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": _CLICK_RU + "    Сохранить()\n;\n\n"
                                "@НаСервере\nметод Сохранить()\n    возврат\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": _CLICK_EN + "    Save()\n;\n\n"
                                    "@OnServer\nmethod Save()\n    return\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/close-in-before-close",
        expect=CLEAN,
        note="the close call in another handler – only the closing handler is judged, by its "
             "platform name",
        files={
            "ФормаЗаявки.yaml": _BUTTON_RU,
            "ФормаЗаявки.xbsl": "@Обработчик\n" + _CLICK_RU + "    Закрыть(Истина)\n;\n",
        },
        english={
            "ApplicationForm.yaml": _BUTTON_EN,
            "ApplicationForm.xbsl": "@Handler\n" + _CLICK_EN + "    Close(True)\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/close-in-before-close",
        expect=FINDING,
        note="the close call in the closing handler's own flow is reported – the handler name and "
             "the call are platform words",
        files={
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": "@Обработчик\nметод ПередЗакрытием(Событие: ПараметрыЗакрытияФормы)\n"
                                "    Закрыть(Истина)\n;\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": "@Handler\nmethod BeforeClose(Event: FormCloseParams)\n"
                                    "    Close(True)\n;\n",
        },
        tokens=_HANDLER_TOKENS,
    ),
    Seed(
        rule="code/load-object-unwrap",
        expect=CLEAN,
        note="a load through a bare variable – a reference held in a variable is alive by "
             "construction",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(СсылкаЗаявки: Заявки.Ссылка)\n"
                           "    знч Объект = СсылкаЗаявки.ЗагрузитьОбъект()!\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe(ApplicationReference: Applications.Reference)\n"
                                 "    val Object = ApplicationReference.LoadObject()!\n;\n",
        },
        tokens=_LOAD_TOKENS,
    ),
    Seed(
        rule="code/load-object-unwrap",
        expect=FINDING,
        note="a force-unwrapped load of a reference stored in a field of a row is reported – the "
             "load member is a dictionary word",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Строчка: Заявки.Ссылка)\n"
                           "    знч Итог = Строчка.Основание!.ЗагрузитьОбъект()!.Наименование\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe(Line: Applications.Reference)\n"
                                 "    val Result = Line.Basis!.LoadObject()!.Name\n;\n",
        },
        tokens=_LOAD_TOKENS,
    ),
    Seed(
        rule="code/load-object-unwrap",
        expect=CLEAN,
        note="a load through the row's own reference member – the member is the reference facet "
             "in both spellings",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Строчка: Заявки.Ссылка)\n"
                           "    знч Объект = Строчка.Ссылка.ЗагрузитьОбъект()!\n;\n",
        },
        english={
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": "method Probe(Line: Applications.Reference)\n"
                                 "    val Object = Line.Reference.LoadObject()!\n;\n",
        },
        tokens=_LOAD_TOKENS,
    ),
    Seed(
        rule="code/member-kind-mismatch",
        expect=CLEAN,
        note="a stdlib method called the way it is declared",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаСервере\nметод Проба()\n    знч Пояс = ЧасовойПояс.Текущий()\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnServer\nmethod Probe()\n    val Zone = TimeZone.Current()\n;\n",
        },
        tokens={**_ENVIRONMENT_TOKENS, "Пояс": "Zone"},
    ),
    Seed(
        rule="code/member-kind-mismatch",
        expect=FINDING,
        note="a stdlib method read as a constant is reported – the member kinds come from the "
             "catalog",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": "@НаСервере\nметод Проба()\n    знч Пояс = ЧасовойПояс.Текущий\n;\n",
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": "@OnServer\nmethod Probe()\n    val Zone = TimeZone.Current\n;\n",
        },
        tokens={**_ENVIRONMENT_TOKENS, "Пояс": "Zone"},
    ),
    # --- Markup vocabulary: column kinds, switcher kinds, command kinds and list shapes are
    # names of the ui schema; the enumeration default is a metamodel contract.
    Seed(
        rule="yaml/badge-column-image",
        expect=CLEAN,
        note="an image on a picture column – the column kind is an enumeration of the schema",
        files={"ФормаЗаявки.yaml": _FORM_RU + _BADGE_COLUMN_RU.format(kind="Картинка")},
        english={"ApplicationForm.yaml": _FORM_EN + _BADGE_COLUMN_EN.format(kind="Picture")},
        tokens=_BADGE_TOKENS,
    ),
    Seed(
        rule="yaml/badge-column-image",
        expect=FINDING,
        note="an image on a badge column is dropped by the renderer – reported",
        files={"ФормаЗаявки.yaml": _FORM_RU + _BADGE_COLUMN_RU.format(kind="Значок")},
        english={"ApplicationForm.yaml": _FORM_EN + _BADGE_COLUMN_EN.format(kind="Badge")},
        tokens=_BADGE_TOKENS,
    ),
    Seed(
        rule="yaml/value-choice-title",
        expect=CLEAN,
        note="a title on a value choice drawn the default way – only the explicit switcher loses it",
        files={"ФормаЗаявки.yaml": _FORM_RU + _SWITCHER_RU.format(kind="")},
        english={"ApplicationForm.yaml": _FORM_EN + _SWITCHER_EN.format(kind="")},
        tokens=_SWITCHER_TOKENS,
    ),
    Seed(
        rule="yaml/value-choice-title",
        expect=FINDING,
        note="a title on an explicit switcher is reported – the kind key and its value are schema "
             "names",
        files={
            "ФормаЗаявки.yaml":
                _FORM_RU + _SWITCHER_RU.format(kind="        ВидОтображенияПереключателя: Переключатель\n"),
        },
        english={
            "ApplicationForm.yaml":
                _FORM_EN + _SWITCHER_EN.format(kind="        SwitcherDisplayKind: Switcher\n"),
        },
        tokens=_SWITCHER_TOKENS,
    ),
    Seed(
        rule="yaml/inline-command-name",
        expect=CLEAN,
        note="an inline command without a name – the shape the apply accepts",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + _COMMANDS_RU.format(
                items="            -\n                Тип: ОбычнаяКоманда\n                Обработчик: Нажатие\n"),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _COMMANDS_EN.format(
                items="            -\n                Type: UsualCommand\n                Handler: Click\n"),
        },
        tokens=_BUTTON_TOKENS,
    ),
    Seed(
        rule="yaml/inline-command-name",
        expect=FINDING,
        note="an inline command carrying a name is reported – the command kinds come from the "
             "term dictionary",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + _COMMANDS_RU.format(
                items="            -\n                Тип: ОбычнаяКоманда\n                Имя: Отправка\n"
                      "                Обработчик: Нажатие\n"),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _COMMANDS_EN.format(
                items="            -\n                Type: UsualCommand\n                Name: Sending\n"
                      "                Handler: Click\n"),
        },
        tokens={**_BUTTON_TOKENS, "Отправка": "Sending"},
    ),
    Seed(
        rule="yaml/toggle-command-pair",
        expect=CLEAN,
        note="two commands with unrelated visibilities – no toggle",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + _COMMANDS_RU.format(items=_TOGGLE_RU.format(second="=ЕстьПраво")),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _COMMANDS_EN.format(items=_TOGGLE_EN.format(second="=HasRight")),
        },
        tokens=_TOGGLE_TOKENS,
    ),
    Seed(
        rule="yaml/toggle-command-pair",
        expect=FINDING,
        note="two usual commands whose visibilities negate each other are reported – the command "
             "kind and the visibility key are dictionary words",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + _COMMANDS_RU.format(items=_TOGGLE_RU.format(second="=ПоказыватьВсе")),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + _COMMANDS_EN.format(items=_TOGGLE_EN.format(second="=ShowAll")),
        },
        tokens=_TOGGLE_TOKENS,
    ),
    Seed(
        rule="yaml/ref-input-auto-commands",
        expect=CLEAN,
        note="a reference input with an explicit, empty command fragment – no platform button",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Заявки.Ссылка?>\n"
                                "        Имя: Основание\n        Команды:\n"
                                "            Тип: ФрагментКомандногоИнтерфейса\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<Applications.Reference?>\n"
                                    "        Name: Basis\n        Commands:\n"
                                    "            Type: CommandInterfaceFragment\n",
        },
        tokens={**_FORM_TOKENS, "Основание": "Basis"},
    ),
    Seed(
        rule="yaml/ref-input-auto-commands",
        expect=FINDING,
        note="a reference input leaving its commands to the platform is reported – the facet is "
             "read in both spellings",
        files={
            "ФормаЗаявки.yaml": _FORM_RU + "    Содержимое:\n        Тип: ПолеВвода<Заявки.Ссылка?>\n"
                                "        Имя: Основание\n",
        },
        english={
            "ApplicationForm.yaml": _FORM_EN + "    Content:\n        Type: Edit<Applications.Reference?>\n"
                                    "        Name: Basis\n",
        },
        tokens={**_FORM_TOKENS, "Основание": "Basis"},
    ),
    Seed(
        rule="yaml/list-form-needs-dynlist",
        expect=CLEAN,
        note="a list form over a dynamic list – the form and the list types are catalog names",
        files={
            "СписокЗаявок.yaml": _LIST_FORM_RU + "    Содержимое:\n        Тип: Таблица<ДинамическийСписок>\n"
                                 "        Имя: Список\n",
        },
        english={
            "ApplicationList.yaml": _LIST_FORM_EN + "    Content:\n        Type: Table<DynamicList>\n"
                                    "        Name: List\n",
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/list-form-needs-dynlist",
        expect=FINDING,
        note="a list form over an array table alone is reported – its navigation item vanishes",
        files={
            "СписокЗаявок.yaml": _LIST_FORM_RU + "    Содержимое:\n"
                                 "        Тип: Таблица<ИсточникДанныхМассив<Строка>>\n        Имя: Список\n",
        },
        english={
            "ApplicationList.yaml": _LIST_FORM_EN + "    Content:\n"
                                    "        Type: Table<ArrayDataSource<String>>\n        Name: List\n",
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-column-sort-lost",
        expect=CLEAN,
        note="a column bound to a field of the row – the sortable form",
        files={
            "СписокЗаявок.yaml":
                _LIST_FORM_RU + _DYNLIST_COLUMN_RU.format(value="=ДанныеСтроки.Данные.Наименование"),
        },
        english={
            "ApplicationList.yaml": _LIST_FORM_EN + _DYNLIST_COLUMN_EN.format(value="=RowData.Data.Name"),
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-column-sort-lost",
        expect=FINDING,
        note="a computed column of a table over a dynamic list is reported – the list and row "
             "types are catalog names",
        files={
            "СписокЗаявок.yaml":
                _LIST_FORM_RU + _DYNLIST_COLUMN_RU.format(value="=Подпись(ДанныеСтроки.Данные.Наименование)"),
        },
        english={
            "ApplicationList.yaml":
                _LIST_FORM_EN + _DYNLIST_COLUMN_EN.format(value="=Caption(RowData.Data.Name)"),
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/enum-default-value",
        expect=CLEAN,
        note="a bare enumeration value as the default – the shape the platform declares",
        files={"Состояния.yaml": _ENUM_RU, "Настройки.yaml": _CONSTANTS_RU.format(value="Открыт")},
        english={"States.yaml": _ENUM_EN, "Settings.yaml": _CONSTANTS_EN.format(value="Open")},
        tokens=_CONSTANTS_TOKENS,
    ),
    Seed(
        rule="yaml/enum-default-value",
        expect=FINDING,
        note="a default qualified by the enumeration name is reported – the default key is a "
             "metamodel name",
        files={
            "Состояния.yaml": _ENUM_RU,
            "Настройки.yaml": _CONSTANTS_RU.format(value="Состояния.Открыт"),
        },
        english={"States.yaml": _ENUM_EN, "Settings.yaml": _CONSTANTS_EN.format(value="States.Open")},
        tokens=_CONSTANTS_TOKENS,
    ),
    Seed(
        rule="yaml/builtin-property-name",
        expect=CLEAN,
        note="a property of the component's own, named apart from the base component's members",
        files={"КарточкаЗаявки.yaml": _CARD_PROPERTY_RU.format(name="КрупныйЗаголовок")},
        english={"ApplicationCard.yaml": _CARD_PROPERTY_EN.format(name="LargeTitle")},
        tokens=_CARD_PROPERTY_TOKENS,
    ),
    Seed(
        rule="yaml/builtin-property-name",
        expect=FINDING,
        note="a property named after a built-in member of the base component is reported – the "
             "members of the card come from the ui schema in both spellings",
        files={"КарточкаЗаявки.yaml": _CARD_PROPERTY_RU.format(name="Заголовок")},
        english={"ApplicationCard.yaml": _CARD_PROPERTY_EN.format(name="Title")},
        tokens=_CARD_PROPERTY_TOKENS,
    ),
]


def _lint(root: Path, rule: str) -> list:
    paths = engine.find_sources(root, "*.xbsl") + engine.find_sources(root, "*.yaml")
    return [d for d in engine.run(paths, select={rule}) if d.rule_id == rule]


def _verdict(fired: bool, expect: str) -> bool:
    """Did a tree answer the way the seed says it must?"""
    return fired if expect == FINDING else not fired


def _plant(root: Path, files: dict[str, str]) -> Path:
    """Write a tree of files under `root` and return it."""
    root.mkdir()
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _translator_differences(hand: dict[str, str], translated: Path) -> list[str]:
    """Names of the hand-written English files the translator did not reproduce verbatim.

    A file the translator did not write at all counts too - a name it could not rename ends
    up under the Russian one, which is the same kind of gap.
    """
    differing: list[str] = []
    for name, text in sorted(hand.items()):
        path = translated / name
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            differing.append(name)
    return differing


def run_seed(seed: Seed) -> dict:
    """Plant the seed, translate it, run the rule on every tree, judge them together."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        russian = _plant(base / "ru", seed.files)

        translated = base / "translated"
        report = translate_project(russian, Dictionary(tokens=dict(seed.tokens)), out=translated)
        # The hand-written twin, when the seed carries one, is the English tree the rule is
        # judged on; the translator's output is then a third tree of its own.
        english = _plant(base / "en", seed.english) if seed.english else translated
        differences = _translator_differences(seed.english, translated) if seed.english else []

        ru_found = _lint(russian, seed.rule)
        en_found = _lint(english, seed.rule)
        tr_found = en_found if english is translated else _lint(translated, seed.rule)
        ru_ok = _verdict(bool(ru_found), seed.expect)
        en_ok = _verdict(bool(en_found), seed.expect)
        tr_ok = _verdict(bool(tr_found), seed.expect)

        # The flavour follows the seed: on a planted violation a wrong tree MISSES it, on
        # legal code a wrong tree INVENTS one. Naming the side and the direction is what makes
        # the line actionable - the two call for opposite fixes. The Russian side is judged
        # first (a seed that fails there is not planted), then the hand-written English (the
        # rule itself), and only then the translated tree (the translator).
        flavour = "misses" if seed.expect == FINDING else "invents"
        if ru_ok and en_ok and tr_ok:
            status = "ok"
        elif not ru_ok and not en_ok and not tr_ok:
            status = "stale"
        elif not ru_ok:
            status = f"ru-{flavour}"
        elif not en_ok:
            status = f"en-{flavour}"
        else:
            status = f"translator-{flavour}"

        if seed.known:
            # A documented gap: not a failure, but its CLOSING is news worth shouting.
            status = "fixed!" if status == "ok" else f"known ({status})"

        return {
            "rule": seed.rule,
            "expect": seed.expect,
            "note": seed.note,
            "known": seed.known,
            "status": status,
            "russian": len(ru_found),
            "english": len(en_found),
            # The translated tree's own count, when the English twin is written by hand.
            "translated": None if english is translated else len(tr_found),
            "translator_differs": differences,
            # A name the dictionary does not carry stays Russian in the translated tree, and a
            # seed that leans on such a name would be testing the dictionary, not the rule.
            "translation_problems": list(report.problems),
        }


def _uncovered() -> list[str]:
    """Registered rules no seed speaks for - the honest size of what this check does not say."""
    seeded = {seed.rule for seed in SEEDS}
    return sorted(info.id for info in engine.RULES if info.id not in seeded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rule", help="run only the seeds of this rule")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--uncovered", action="store_true", help="list the rules no seed speaks for and exit",
    )
    args = parser.parse_args(argv)

    if args.uncovered:
        names = _uncovered()
        if args.json:
            print(json.dumps({"uncovered": names}, ensure_ascii=False, indent=2))
        else:
            for name in names:
                print(name)
            print(f"\nno seed: {len(names)}")
        return 0

    seeds = [s for s in SEEDS if not args.rule or s.rule == args.rule]
    if not seeds:
        print(f"no seed for {args.rule!r}", file=sys.stderr)
        return 2

    results = [run_seed(seed) for seed in seeds]
    # A documented gap does not fail the run; a gap that CLOSED does, so the note gets removed.
    bad = [r for r in results
           if r["status"] != "ok" and not r["status"].startswith("known")]
    known = [r for r in results if r["status"].startswith("known")]

    if args.json:
        print(json.dumps(
            {"results": results, "uncovered": len(_uncovered())},
            ensure_ascii=False, indent=2,
        ))
        return 1 if bad else 0

    width = max(len(r["status"]) for r in results)
    for result in results:
        mark = result["status"].ljust(width)
        counts = f"ru={result['russian']} en={result['english']}"
        if result["translated"] is not None:
            counts += f" translated={result['translated']}"
        print(f"[{mark}] {result['rule']} ({result['expect']}): {counts} - {result['note']}")
        if result["known"]:
            print(f"          known: {result['known']}")
        if result["translator_differs"]:
            print(f"          translator differs: {', '.join(result['translator_differs'])}")
        if result["translation_problems"]:
            print(f"          translation: {result['translation_problems']}")

    covered = len({s.rule for s in SEEDS})
    print(f"\nseeds: {len(results)}, disagreements: {len(bad)}, known gaps: {len(known)}; "
          f"rules with a seed: {covered}, without: {len(_uncovered())}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
