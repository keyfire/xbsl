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
    python tools/parity_seed.py --quiet          # only the seeds that disagree, and the summary
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
#: A dynamic list whose source joins a second table. `{main}` and `{joined}` are the argument
#: expressions of the main and of the joined table - only the second one is a runtime refusal.
_JOINED_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f19
Имя: РеестрЗаявок
ОбластьВидимости: ВПроекте
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Таблица<ДинамическийСписок>
        Имя: Список
        Источник:
            ОсновнаяТаблица:
                Таблица: Заявки
                Аргументы:
                    -
                        Тип: АргументТаблицыВыражение
                        Имя: Раздел
                        Выражение: '{main}'
            ПрисоединенныеТаблицы:
                -
                    Тип: ПрисоединеннаяТаблица
                    Таблица: Отметки
                    Псевдоним: Отметка
                    Аргументы:
                        -
                            Тип: АргументТаблицыВыражение
                            Имя: Раздел
                            Выражение: '{joined}'
"""
_JOINED_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f19
Name: ApplicationRegistry
VisibilityScope: InProject
Inherits:
    Type: Form
    Content:
        Type: Table<DynamicList>
        Name: List
        Source:
            MainTable:
                Table: Applications
                Arguments:
                    -
                        Type: TableArgumentExpression
                        Name: Section
                        Expression: '{main}'
            JoinedTables:
                -
                    Type: JoinedTable
                    Table: Marks
                    Alias: Mark
                    Arguments:
                        -
                            Type: TableArgumentExpression
                            Name: Section
                            Expression: '{joined}'
"""
_JOINED_TOKENS = {"Заявки": "Applications", "РеестрЗаявок": "ApplicationRegistry",
                  "Список": "List", "Отметки": "Marks", "Отметка": "Mark", "Раздел": "Section"}
#: A catalog of two attributes, the set the automatic list row type carries.
_MARKS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f1a
Имя: Отметки
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f1b
        Имя: Срок
        Тип: Строка
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f1c
        Имя: Сумма
        Тип: Число
"""
_MARKS_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-000000000f1a
Name: Marks
VisibilityScope: InProject
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f1b
        Name: Deadline
        Type: String
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f1c
        Name: Amount
        Type: Number
"""
#: A list over the object's automatic row type; `{extra}` is the second selected field or nothing.
#: The tail segment of the chain has no English pair anywhere in the platform's dictionaries,
#: so both spellings write it the same - that is what the rule's own table says.
_AUTO_LIST_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f1d
Имя: РеестрОтметок
ОбластьВидимости: ВПроекте
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Таблица<ДинамическийСписок<Отметки.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>
        Имя: Список
        Источник:
            ОсновнаяТаблица:
                Таблица: Отметки
            Поля:
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Срок
{extra}"""
_AUTO_LIST_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f1d
Name: MarkRegistry
VisibilityScope: InProject
Inherits:
    Type: Form
    Content:
        Type: Table<DynamicList<Marks.AutomaticListForm.ДанныеСтрокиСписка>>
        Name: List
        Source:
            MainTable:
                Table: Marks
            Fields:
                -
                    Type: DynamicListField
                    Expression: Deadline
{extra}"""
_AUTO_FIELD_RU = ("                -\n                    Тип: ПолеДинамическогоСписка\n"
                  "                    Выражение: Сумма\n")
_AUTO_FIELD_EN = ("                -\n                    Type: DynamicListField\n"
                  "                    Expression: Amount\n")
_AUTO_LIST_TOKENS = {"Отметки": "Marks", "РеестрОтметок": "MarkRegistry", "Список": "List",
                     "Срок": "Deadline", "Сумма": "Amount"}
#: The project description – the only place the compatibility mode is written.
_PROJECT_RU = """\
Ид: 1d1f5c60-0000-4000-8000-000000000f1e
Поставщик: acme
Имя: Проба
Версия: 1.0.0
РежимСовместимости: {mode}
"""
_PROJECT_EN = """\
Id: 1d1f5c60-0000-4000-8000-000000000f1e
Vendor: acme
Name: Probe
Version: 1.0.0
CompatibilityMode: {mode}
"""
#: A picture carrying a property the schema dates 9.0 – newer than an 8.0 project.
_PICTURE_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f1f
Имя: ЗначокЗаявки
ОбластьВидимости: ВПроекте
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Картинка
        Имя: Значок
        ОтображатьПодсказку: Всегда
"""
_PICTURE_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f1f
Name: ApplicationBadge
VisibilityScope: InProject
Inherits:
    Type: Form
    Content:
        Type: Picture
        Name: Badge
        DisplayTooltip: Always
"""
_PICTURE_TOKENS = {"Проба": "Probe", "ЗначокЗаявки": "ApplicationBadge", "Значок": "Badge"}
#: A label whose value is an object-typed property; `{value}` is a bare word or a binding.
_LABEL_VALUE_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f20
Имя: КарточкаИтога
ОбластьВидимости: ВПроекте
Свойства:
    -
        Имя: Подытог
        Тип: Строка
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Надпись
        Имя: Подпись
        Значение: {value}
"""
_LABEL_VALUE_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f20
Name: TotalCard
VisibilityScope: InProject
Properties:
    -
        Name: Subtotal
        Type: String
Inherits:
    Type: Form
    Content:
        Type: Label
        Name: Caption
        Value: {value}
"""
_LABEL_VALUE_TOKENS = {"КарточкаИтога": "TotalCard", "Подытог": "Subtotal", "Подпись": "Caption"}
#: A form declaring a dynamic list whose row type carries two fields: one taken straight and
#: one taken THROUGH A REFERENCE, which types it `<тип>|Null`; the guarded twin is next to it.
_ROW_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f21
Имя: ПанельОтметок
ОбластьВидимости: ВПроекте
Свойства:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f22
        Имя: Список
        Тип: ДинамическийСписок<ПанельОтметок.СтрокаСписка>
        ЗначениеПоУмолчанию:
            ИмяТипаДанныхСтроки: СтрокаСписка
            ОсновнаяТаблица:
                Таблица: Отметки
            Поля:
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Срок
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Раздел.Сумма
                    Псевдоним: СуммаРаздела
                -
                    Тип: ПолеДинамическогоСписка
                    Выражение: Раздел.Сумма.ЗаменитьNull(0)
                    Псевдоним: ЗащищеннаяСумма
"""
_ROW_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f21
Name: MarkPanel
VisibilityScope: InProject
Properties:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f22
        Name: List
        Type: DynamicList<MarkPanel.ListRow>
        DefaultValue:
            RowDataTypeName: ListRow
            MainTable:
                Table: Marks
            Fields:
                -
                    Type: DynamicListField
                    Expression: Deadline
                -
                    Type: DynamicListField
                    Expression: Section.Amount
                    Alias: SectionAmount
                -
                    Type: DynamicListField
                    Expression: Section.Amount.ReplaceNull(0)
                    Alias: GuardedAmount
"""
#: A handler reading one member off the row; `{field}` is the member.
_ROW_READ_RU = ("метод Показать(ДанныеСтроки: СтрокаДинамическогоСписка<ПанельОтметок.СтрокаСписка>)\n"
                "    знч Строчка = ДанныеСтроки.Данные\n"
                "    знч Итог = Строчка.{field}\n;\n")
_ROW_READ_EN = ("method Show(RowData: DynamicListRow<MarkPanel.ListRow>)\n"
                "    val Line = RowData.Data\n"
                "    val Result = Line.{field}\n;\n")
#: The same handler filling a typed structure field from the row; `{field}` is the row member.
_ROW_FILL_RU = ("структура Сводка\n    знч Сумма: Число = 0\n;\n"
                "метод Показать(ДанныеСтроки: СтрокаДинамическогоСписка<ПанельОтметок.СтрокаСписка>)\n"
                "    знч Строчка = ДанныеСтроки.Данные\n"
                "    знч Итог = новый Сводка(Сумма = Строчка.{field})\n;\n")
_ROW_FILL_EN = ("structure Summary\n    val Amount: Number = 0\n;\n"
                "method Show(RowData: DynamicListRow<MarkPanel.ListRow>)\n"
                "    val Line = RowData.Data\n"
                "    val Result = new Summary(Amount = Line.{field})\n;\n")
_ROW_TOKENS = {"ПанельОтметок": "MarkPanel", "Отметки": "Marks", "Список": "List",
               "Срок": "Deadline", "Сумма": "Amount", "СуммаРаздела": "SectionAmount",
               "ЗащищеннаяСумма": "GuardedAmount", "Строчка": "Line", "Сводка": "Summary",
               "Итог": "Result", "Показать": "Show"}
#: A structure declared in a common module, read from another module through a typed variable.
_STRUCT_DECL_RU = "структура Сводка\n    знч Сумма: Число = 0\n    знч Срок: Строка = \"\"\n;\n"
_STRUCT_DECL_EN = "structure Summary\n    val Amount: Number = 0\n    val Deadline: String = \"\"\n;\n"
_STRUCT_READ_RU = "метод Проба(Свод: Вычисления.Сводка)\n    знч Итог = Свод.{field}\n;\n"
_STRUCT_READ_EN = "method Probe(Digest: Calculations.Summary)\n    val Result = Digest.{field}\n;\n"
_STRUCT_TOKENS = {"Вычисления": "Calculations", "Сводка": "Summary", "Сумма": "Amount",
                  "Срок": "Deadline", "Свод": "Digest", "Проба": "Probe", "Итог": "Result",
                  "Заявки": "Applications", "Остаток": "Balance"}
#: A method open to the client; `{extra}` adds the context annotation, or nothing.
_CLIENT_AVAILABLE_RU = ("@НаСервере @ДоступноСКлиента{extra}\n"
                        "метод Прочитать(): Строка\n    возврат \"\"\n;\n")
_CLIENT_AVAILABLE_EN = ("@OnServer @AvailableFromClient{extra}\n"
                        "method Read(): String\n    return \"\"\n;\n")
#: The client side of the pair: a component method that names the server method, or does not.
#: The local name carries no token of its own, so its English half is the dictionary's.
_CLIENT_CALL_RU = "метод Отобразить()\n    знч Итог = Серверный.Прочитать()\n;\n"
_CLIENT_CALL_EN = "method Display()\n    val Total = ServerSide.Read()\n;\n"
_CLIENT_IDLE_RU = "метод Отобразить()\n    знч Итог = \"\"\n;\n"
_CLIENT_IDLE_EN = "method Display()\n    val Total = \"\"\n;\n"
#: An enumeration named after the kind word the standard picks, or after the one it rejects.
_ENUM_NAME_RU = """\
ВидЭлемента: Перечисление
Ид: 1d1f5c60-0000-4000-8000-000000000f23
Имя: {name}
ОбластьВидимости: ВПроекте
Элементы:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f24
        Имя: Основной
"""
_ENUM_NAME_EN = """\
ElementKind: Enumeration
Id: 1d1f5c60-0000-4000-8000-000000000f23
Name: {name}
VisibilityScope: InProject
Items:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f24
        Name: Main
"""
_ENUM_NAME_TOKENS = {"ВидЗаявки": "ApplicationKind", "ТипЗаявки": "ApplicationType",
                     "Основной": "Main"}
#: A common module named with the environment in its name, or without it.
_MODULE_NAME_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-000000000f25
Имя: {name}
ОбластьВидимости: ВПроекте
Окружение: КлиентИСервер
"""
_MODULE_NAME_EN = """\
ElementKind: CommonModule
Id: 1d1f5c60-0000-4000-8000-000000000f25
Name: {name}
VisibilityScope: InProject
Environment: ClientAndServer
"""
_MODULE_NAME_TOKENS = {"Обмен": "Exchange", "ОбменКлиентИСервер": "ExchangeClientAndServer"}
#: A standard card whose background is bound to a method of the paired module.
_CARD_BINDING_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f26
Имя: КарточкаОтметки
ОбластьВидимости: ВПроекте
Наследует:
    Тип: СтандартнаяКарточка
    Фон: =ФонКарточки()
"""
_CARD_BINDING_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f26
Name: MarkCard
VisibilityScope: InProject
Inherits:
    Type: StandardCard
    Background: =CardBackground()
"""
_CARD_BINDING_RETURN_RU = "метод ФонКарточки(): {type}\n    возврат {value}\n;\n"
_CARD_BINDING_RETURN_EN = "method CardBackground(): {type}\n    return {value}\n;\n"
_CARD_BINDING_TOKENS = {"КарточкаОтметки": "MarkCard", "ФонКарточки": "CardBackground"}
#: A form template whose content slot is typed as a list; `{dash}` opens a list item or nothing.
_SLOT_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f27
Имя: ШаблонОтметки
ОбластьВидимости: ВПроекте
Наследует:
    Тип: Форма
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Имя: Блок
            Содержимое:
{item}"""
_SLOT_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f27
Name: MarkTemplate
VisibilityScope: InProject
Inherits:
    Type: Form
    Content:
        Type: CustomFormTemplate
        Content:
            Type: Group
            Name: Block
            Content:
{item}"""
_SLOT_ITEM_RU = "                Тип: Надпись\n                Имя: Подпись\n"
_SLOT_ITEM_EN = "                Type: Label\n                Name: Caption\n"
_SLOT_LIST_RU = "                -\n                    Тип: Надпись\n                    Имя: Подпись\n"
_SLOT_LIST_EN = "                -\n                    Type: Label\n                    Name: Caption\n"
_SLOT_TOKENS = {"ШаблонОтметки": "MarkTemplate", "Блок": "Block", "Подпись": "Caption"}
#: A label carrying a hint; `{hint}` is the hint text, the length is what the rule judges.
_HINT_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f28
Имя: ПодписьОтметки
ОбластьВидимости: ВПроекте
Содержимое:
    -
        Тип: Надпись
        Заголовок: Отметка
        Подсказка: {hint}
"""
_HINT_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f28
Name: MarkCaption
VisibilityScope: InProject
Content:
    -
        Type: Label
        Title: Отметка
        Tooltip: {hint}
"""
_HINT_TOKENS = {"ПодписьОтметки": "MarkCaption", "Отметка": "Mark"}
#: A component derived from the popup window, and a form that places it or only declares it.
_POPUP_DERIVED_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f29
Имя: СобственнаяПодсказка
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ВсплывающийКомпонент
    ЗакрыватьПриНажатииСнаружи: Истина
"""
_POPUP_DERIVED_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f29
Name: OwnTooltip
VisibilityScope: InProject
Inherits:
    Type: PopupComponent
    CloseOnClickOutside: True
"""
_POPUP_HOST_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f2a
Имя: СтраницаОтметки
ОбластьВидимости: ВПроекте
{declaration}Наследует:
    Тип: Форма
    Содержимое:
        Тип: {placed}
        Имя: Блок
"""
_POPUP_HOST_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f2a
Name: MarkPage
VisibilityScope: InProject
{declaration}Inherits:
    Type: Form
    Content:
        Type: {placed}
        Name: Block
"""
_POPUP_DECLARATION_RU = "Свойства:\n    -\n        Имя: Окно\n        Тип: СобственнаяПодсказка?\n"
_POPUP_DECLARATION_EN = "Properties:\n    -\n        Name: Window\n        Type: OwnTooltip?\n"
_POPUP_TOKENS = {"СобственнаяПодсказка": "OwnTooltip", "СтраницаОтметки": "MarkPage",
                 "Блок": "Block", "Окно": "Window"}
#: An insert whose height is bound; `{height}` is a computed expression or a bare path.
_BOUND_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f2b
Имя: ФормаОтметки
ОбластьВидимости: ВПроекте
Содержимое:
    -
        Тип: КонтейнерHtml
        Имя: Блок
        Высота: {height}
"""
_BOUND_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f2b
Name: MarkForm
VisibilityScope: InProject
Content:
    -
        Type: HtmlContainer
        Name: Block
        Height: {height}
"""
_BOUND_ASSIGN_RU = "метод Показать()\n    Компоненты.Блок.Высота = 640\n;\n"
_BOUND_ASSIGN_EN = "method Show()\n    Components.Block.Height = 640\n;\n"
_BOUND_TOKENS = {"ФормаОтметки": "MarkForm", "Блок": "Block", "ВысотаБлока": "BlockHeight",
                 "Показать": "Show", "Отступ": "Indent"}
#: A component declaring a property its own module assigns, and the instances that bind it.
_PICKER_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f2c
Имя: ПолеОттенка
ОбластьВидимости: ВПроекте
Свойства:
    -
        Имя: Оттенок
        Тип: Строка
"""
_PICKER_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f2c
Name: ShadeField
VisibilityScope: InProject
Properties:
    -
        Name: Shade
        Type: String
"""
_PICKER_MODULE_RU = "метод Выбрать()\n    Оттенок = \"FFFFFF\"\n;\n"
_PICKER_MODULE_EN = "method Choose()\n    Shade = \"FFFFFF\"\n;\n"
_PICKER_HOST_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f2d
Имя: ПанельОттенков
ОбластьВидимости: ВПроекте
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: ПолеОттенка
            Оттенок: {value}
"""
_PICKER_HOST_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f2d
Name: ShadePanel
VisibilityScope: InProject
Inherits:
    Type: Group
    Content:
        -
            Type: ShadeField
            Shade: {value}
"""
_PICKER_TOKENS = {"ПолеОттенка": "ShadeField", "Оттенок": "Shade", "Выбрать": "Choose",
                  "ПанельОттенков": "ShadePanel", "ВычислитьОттенок": "ComputeShade",
                  "ПоказанныйОттенок": "ShownShade"}
#: A dynamic list with one filter item; `{use}` is the declared state of that item.
_FILTER_LIST_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f2e
Имя: СписокОтметок
ОбластьВидимости: ВПроекте
Свойства:
    -
        Имя: Данные
        Тип: ДинамическийСписок
        ЗначениеПоУмолчанию:
            ОсновнаяТаблица:
                Таблица: Отметки
            Фильтр:
                Тип: ГруппаЭлементовФильтра
                Элементы:
                    -
                        Тип: ЭлементФильтра
                        Поле: Раздел
                        Использовать: {use}
"""
_FILTER_LIST_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f2e
Name: MarkList
VisibilityScope: InProject
Properties:
    -
        Name: Data
        Type: DynamicList
        DefaultValue:
            MainTable:
                Table: Marks
            Filter:
                Type: FilterItemGroup
                Items:
                    -
                        Type: FilterItem
                        Field: Section
                        Use: {use}
"""
#: The paired module switching that filter item on - the second half of the race.
_FILTER_CODE_RU = ("@Обработчик\nметод ПослеСоздания()\n"
                   "    для Элемент из Данные.Фильтр.Элементы\n"
                   "        (Элемент как ЭлементФильтра).Использовать = Истина\n    ;\n;\n")
_FILTER_CODE_EN = ("@Handler\nmethod AfterCreate()\n"
                   "    for Item in Data.Filter.Items\n"
                   "        (Item as FilterItem).Use = True\n    ;\n;\n")
#: The property and the handler are names the PROJECT declares, so the dictionary carries
#: them as tokens - a platform pair does not apply to a name of the project's own.
_FILTER_TOKENS = {"СписокОтметок": "MarkList", "Отметки": "Marks", "Раздел": "Section",
                  "Данные": "Data", "ПослеСоздания": "AfterCreate"}
#: A query literal over the catalog; `{value}` is how the condition takes its value.
_PARAM_QUERY_RU = ("метод Собрать()\n    знч Итог = Запрос{{\n"
                   "        ВЫБРАТЬ Наименование ИЗ Справочник.Отметки ГДЕ Раздел = {value}\n"
                   "    }}\n;\n")
_PARAM_QUERY_EN = ("method Collect()\n    val Total = Query{{\n"
                   "        SELECT Name FROM Catalog.Marks WHERE Section = {value}\n"
                   "    }}\n;\n")
_PARAM_TOKENS = {"Отметки": "Marks", "Собрать": "Collect", "Раздел": "Section",
                 "Срок": "Deadline", "Сумма": "Amount"}
#: An element whose name repeats its own kind, or does not; `{kind}` and `{name}` vary.
_KIND_NAME_RU = """\
ВидЭлемента: {kind}
Ид: 1d1f5c60-0000-4000-8000-000000000f2f
Имя: {name}
ОбластьВидимости: ВПроекте
Представление: Просроченные отметки
"""
_KIND_NAME_EN = """\
ElementKind: {kind}
Id: 1d1f5c60-0000-4000-8000-000000000f2f
Name: {name}
VisibilityScope: InProject
Presentation: Просроченные отметки
"""
_KIND_NAME_TOKENS = {"ПросроченныеОтметки": "OverdueMarks",
                     "ОтчетПросроченныеОтметки": "OverdueMarksReport"}
#: A list over an entity that declares no hierarchy, wired to the row-editing event.
_ROW_EDIT_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f30
Имя: ТаблицаОтметок
ОбластьВидимости: ВПроекте
Содержимое:
    -
        Тип: Таблица<ДинамическийСписок<{entity}>>
        Имя: Список
        ПриРедактированииСтроки: СтрокаПриРедактировании
"""
_ROW_EDIT_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f30
Name: MarkTable
VisibilityScope: InProject
Content:
    -
        Type: Table<DynamicList<{entity}>>
        Name: List
        OnRowEdit: RowOnEdit
"""
_HIER_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f31
Имя: Разделы
ОбластьВидимости: ВПроекте
Иерархический: Истина
"""
_HIER_CATALOG_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-000000000f31
Name: Sections
VisibilityScope: InProject
Hierarchical: True
"""
_ROW_EDIT_TOKENS = {"Отметки": "Marks", "Разделы": "Sections", "ТаблицаОтметок": "MarkTable",
                    "Список": "List", "СтрокаПриРедактировании": "RowOnEdit",
                    "Срок": "Deadline", "Сумма": "Amount"}
#: A picture whose image is bound; `{value}` either calls a server member or reads a field.
_IMAGE_FORM_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f32
Имя: ПлиткаОтметки
ОбластьВидимости: ВПроекте
Содержимое:
    -
        Тип: Картинка
        Имя: Значок
        Изображение: {value}
"""
_IMAGE_FORM_EN = """\
ElementKind: InterfaceComponent
Id: 1d1f5c60-0000-4000-8000-000000000f32
Name: MarkTile
VisibilityScope: InProject
Content:
    -
        Type: Picture
        Name: Badge
        Image: {value}
"""
_IMAGE_TOKENS = {"Отметки": "Marks", "ПлиткаОтметки": "MarkTile", "Значок": "Badge",
                 "ЗначокПоКоду": "BadgeByCode", "Код": "Code", "ДанныеСтроки": "RowData"}
#: A catalog whose boolean attribute is named the way the standard wants, or negated.
_BOOLEAN_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f33
Имя: Отметки
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f34
        Имя: {name}
        Тип: Булево
"""
_BOOLEAN_CATALOG_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-000000000f33
Name: Marks
VisibilityScope: InProject
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-000000000f34
        Name: {name}
        Type: Boolean
"""
_BOOLEAN_TOKENS = {"Отметки": "Marks", "Успешно": "Successful", "НетОшибок": "NoErrors"}

#: --- Cross-subsystem references: a consumer subsystem and a supplier subsystem -----------
#: The consumer declares the supplier as used; the supplier is private to the auto-interface.
_SUB_USE_RU = "Использование:\n    - Склад\n"
_SUB_PRIVATE_RU = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
_SUB_TOKENS = {"Учет": "Accounting", "Склад": "Warehouse"}
_GOODS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f31
Имя: Товары
ОбластьВидимости: {vis}
"""
_CARD_HEAD_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f32
Имя: Карточка
"""
_CARD_BODY_RU = """\
Наследует:
    Тип: Группа
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f33
        Имя: Товар
        Тип: Товары.Ссылка?
"""
_CROSS_TOKENS = {**_SUB_TOKENS, "Товары": "Goods", "Карточка": "Card", "Товар": "Product"}
_CALC_YAML_RU = "ВидЭлемента: ОбщийМодуль\nИд: 1d1f5c60-0000-4000-8000-000000000f3a\nИмя: Расчеты\n"
_CALC_TOKENS = {**_SUB_TOKENS, "Товары": "Goods", "Расчеты": "Calculations", "Первый": "First"}
_DEADLINES_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-000000000f39
Имя: СрокиТоваров
ОбластьВидимости: {vis}
"""
_DEADLINES_XBSL_RU = "@ВПроекте\nметод БлижайшийСрок(): Дата?\n    возврат Неопределено\n;\n"
_SUMMARY_RU = "ВидЭлемента: ОбщийМодуль\nИд: 1d1f5c60-0000-4000-8000-000000000f3b\nИмя: Сводка\nОбластьВидимости: ВПроекте\n"
_SUMMARY_XBSL_RU = "импорт Склад\n\nметод СрокСводки(): Дата?\n    возврат СрокиТоваров.БлижайшийСрок()\n;\n"
_VISIBILITY_TOKENS = {**_SUB_TOKENS, "СрокиТоваров": "GoodsDeadlines", "БлижайшийСрок": "NearestDeadline",
                      "Сводка": "Summary", "СрокСводки": "SummaryDeadline"}

#: --- Computed access control -----------------------------------------------------------
_RECORDS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f34
Имя: Записи
КонтрольДоступа:
    РасчетРазрешенийПо:
        - Владелец
    Разрешения:
        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f35
        Имя: Владелец
        Тип: Строка
"""
_COMMON_HANDLER_RU = (
    "@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n"
    "    возврат новый Массив<РазрешениеДоступа>()\n;\n\n"
)


def _per_object_ru(body: str) -> str:
    """The per-object handler of the records catalog, reading the record through the
    loop variable the platform's contract names (`Record`)."""
    return (
        "@Обработчик\n"
        "метод ВычислитьРазрешенияДоступаДляОбъектов(Данные: ЧитаемыйМассив<Записи.Объект>)\n"
        "    для Запись из Данные\n"
        f"        {body}\n"
        "    ;\n"
        ";\n"
    )


_RECORDS_TOKENS = {"Записи": "Records", "Владелец": "Owner", "Данные": "Data"}
_NOTES_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f36
Имя: Заметки
КонтрольДоступа:
    Разрешения:
        Чтение: {read}
"""
_NOTES_XBSL_RU = (
    "метод ПрочитатьЗаметки()\n"
    "    исп КонтекстДоступа.Дополнить(Тип<Заметки.Объект>, [Сущность.Право.Чтение])\n;\n"
)
_NOTES_TOKENS = {"Заметки": "Notes", "Работа": "Work", "ПрочитатьЗаметки": "ReadNotes"}
_TRANSFERS_RU = """\
ВидЭлемента: РегистрСведений
Ид: 1d1f5c60-0000-4000-8000-000000000f37
Имя: Переводы
КонтрольДоступа:
    Разрешения:
        Чтение: РазрешеноВсем
        ПоУмолчанию: РазрешенияВычисляются
Измерения:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f38
        Имя: Ключ
        Тип: Строка
"""
_GRANT_RU = (
    "@Обработчик\nметод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n"
    "    возврат [новый РазрешениеДоступа([новый КлючДоступаЗаписей.Объект()],\n"
    "        [{rights}])]\n;\n"
)
_TRANSFERS_TOKENS = {"Переводы": "Transfers", "Ключ": "Key"}

#: --- Localized strings -------------------------------------------------------------------
_STRINGS_RU = """\
ВидЭлемента: ЛокализованныеСтроки
Ид: 1d1f5c60-0000-4000-8000-000000000f3c
Имя: Словарь
ОбластьВидимости: ВПроекте
Строки:
{strings}Шаблоны:
{templates}"""
_STRINGS_DEFAULT_RU = _STRINGS_RU.format(
    strings="    Приветствие: Привет\n", templates='    Расширена: "Расширена (до $0)"\n',
)
_LABEL_RU = _CARD_HEAD_RU + "Содержимое:\n    -\n        Тип: Надпись\n        Значение: {value}\n"
_STRINGS_TOKENS = {"Словарь": "Dictionary", "Приветствие": "Greeting", "Расширена": "Extended",
                   "Готово": "Done", "Карточка": "Card"}

#: --- Resources, components, modules ----------------------------------------------------
_PICTURES_XBSL_RU = "метод Картинка(): ДвоичныйОбъект.Ссылка\n    возврат Ресурс{{{key}}}.Ссылка\n;\n"
_PICTURES_TOKENS = {"Проба": "Probe", "Основное": "Main", "Своя": "Own", "Картинки": "Pictures",
                    "Картинка": "Picture", "Пробная9": "Probe9"}
_COMBINE_RU = "метод Сложить(А: Число, Б: Число = 0): Число\n    возврат А + Б\n;\n"
_ARITY_TOKENS = {"Расчеты": "Calculations", "Сложить": "Combine", "А": "A", "Б": "B",
                 "Проба": "Probe", "Служебный": "Internal", "Вызывающий": "Caller"}
_TAB_YAML_RU = "ВидЭлемента: КомпонентИнтерфейса\nИд: 1d1f5c60-0000-4000-8000-000000000f3d\nИмя: Вкладка\n"
_ROUTER_YAML_RU = (
    "ВидЭлемента: КомпонентИнтерфейса\nИд: 1d1f5c60-0000-4000-8000-000000000f3e\nИмя: Маршрутизатор\n"
    "Содержимое:\n    -\n        Тип: Вкладка\n        Имя: Вкладка\n"
)
_ROUTER_XBSL_RU = "метод Открыть()\n    Компоненты.Вкладка.Загрузить()\n;\n"
_TAB_TOKENS = {"Вкладка": "Tab", "Маршрутизатор": "Router", "Загрузить": "Load", "Открыть": "Open"}
_PANEL_RU = "ВидЭлемента: КомпонентИнтерфейса\nИд: 1d1f5c60-0000-4000-8000-000000000f3f\nИмя: Панель\n"
_CABINET_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f40
Имя: Кабинет
Наследует:
    Тип: ПроизвольноеКлиентскоеПриложение
    Путь: cabinet
    Содержимое:
        -
            Тип: Панель
"""
_HANDLING_RU = "ВидЭлемента: ОбщийМодуль\nИд: 1d1f5c60-0000-4000-8000-000000000f41\nИмя: РаботаСЗадачами\nОкружение: Клиент\n"
_TASK_CARD_RU = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1d1f5c60-0000-4000-8000-000000000f42
Имя: КарточкаЗадачи
Свойства:
    -
        Имя: {prop}
        Тип: Массив<Строка>
"""
_GOODS_FIELDS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f43
Имя: Товары
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f44
        Имя: Метка
        Тип: Строка
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f45
        Имя: Бейдж
        Тип: Строка|Число|?
"""
_FILTERS_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000f46
Имя: Фильтры
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000f47
        Имя: Бейдж
        Тип: Строка|Число|?
"""
_IN_SUBQUERY_RU = (
    "метод Проба(): Число\n"
    "    знч Р = Запрос{{\n"
    "        ВЫБРАТЬ 1\n"
    "        ИЗ Товары КАК Т\n"
    "        ГДЕ Т.{field} В (ВЫБРАТЬ Ф.Бейдж ИЗ Фильтры КАК Ф)\n"
    "    }}.Выполнить()\n"
    "    возврат 1\n"
    ";\n"
)
_QUERY_TOKENS = {"Товары": "Goods", "Фильтры": "Filters", "Бейдж": "Badge", "Метка": "Tag",
                 "Р": "R", "Т": "T", "Ф": "F", "Проба": "Probe", "Отборы": "Selections"}
_CHECKS_TOKENS = {"Проверки": "Checks", "Проба": "Probe", "Флаг": "Flag"}
_PRICES_RU = "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f48\nИмя: Цены\n"
_PRICES_TOKENS = {"Цены": "Prices", "Заявки": "Applications", "Задачи": "Tasks", "Сумма": "Amount",
                  "Товар_Цена": "Product_Price"}
_DUPLICATE_BODY_RU = (
    "{annotation}метод Собрать(): Число\n"
    "    пер А = 1\n    пер Б = 2\n    пер В = 3\n    пер Г = 4\n"
    "    возврат А + Б + В + Г\n;\n"
)
_DUPLICATE_TOKENS = {"Первый": "First", "Второй": "Second", "Собрать": "Assemble",
                     "А": "A", "Б": "B", "В": "C", "Г": "D"}
_DESCRIPTOR_RU = (
    "Ид: 1d1f5c60-0000-4000-8000-000000000f49\n"
    "Поставщик: Acme\nИмя: Проба\nВерсия: {version}\n{presentation}"
    "РежимСовместимости: 9.0\n"
)
_DESCRIPTOR_PRESENTATION_RU = 'Представление: "Проба"\nПредставлениеПоставщика: "Акме"\n'
_STRINGS_PARTNER_EN = (
    "Строки:\n    Приветствие: Hello\n"
    "Шаблоны:\n    Расширена: \"Extended (until $0)\"\n"
)


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
    Seed(
        rule="yaml/dynlist-joined-table-param",
        expect=CLEAN,
        note="a list parameter in the MAIN table's argument – the legal half, next to a joined "
             "table whose own argument is a literal",
        files={"РеестрЗаявок.yaml": _JOINED_RU.format(main="&Раздел", joined="1")},
        english={"ApplicationRegistry.yaml": _JOINED_EN.format(main="&Section", joined="1")},
        tokens=_JOINED_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-joined-table-param",
        expect=FINDING,
        note="the same parameter inside the JOINED table's argument is reported – the joined "
             "key, the arguments key and the expression key are all metamodel names",
        files={"РеестрЗаявок.yaml": _JOINED_RU.format(main="1", joined="&Раздел")},
        english={"ApplicationRegistry.yaml": _JOINED_EN.format(main="1", joined="&Section")},
        tokens=_JOINED_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-missing-field",
        expect=CLEAN,
        note="a list over the automatic row type selecting every attribute of its object",
        files={
            "Отметки.yaml": _MARKS_RU,
            "РеестрОтметок.yaml": _AUTO_LIST_RU.format(extra=_AUTO_FIELD_RU),
        },
        english={
            "Marks.yaml": _MARKS_EN,
            "MarkRegistry.yaml": _AUTO_LIST_EN.format(extra=_AUTO_FIELD_EN),
        },
        tokens=_AUTO_LIST_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-missing-field",
        expect=FINDING,
        note="the same list missing one attribute is reported – the row-type chain and the "
             "fields key are read from the platform's own names",
        files={
            "Отметки.yaml": _MARKS_RU,
            "РеестрОтметок.yaml": _AUTO_LIST_RU.format(extra=""),
        },
        english={
            "Marks.yaml": _MARKS_EN,
            "MarkRegistry.yaml": _AUTO_LIST_EN.format(extra=""),
        },
        tokens=_AUTO_LIST_TOKENS,
    ),
    Seed(
        rule="yaml/property-since-compat",
        expect=CLEAN,
        note="a property of the mode the project declares – the mode key lives in the project "
             "description, which carries no element kind",
        files={"Проект.yaml": _PROJECT_RU.format(mode="9.0"), "ЗначокЗаявки.yaml": _PICTURE_RU},
        english={"Project.yaml": _PROJECT_EN.format(mode="9.0"),
                 "ApplicationBadge.yaml": _PICTURE_EN},
        tokens=_PICTURE_TOKENS,
    ),
    Seed(
        rule="yaml/property-since-compat",
        expect=FINDING,
        note="the same property under an older mode is reported – the component and the "
             "property are spelled by the ui schema in both scripts",
        files={"Проект.yaml": _PROJECT_RU.format(mode="8.0"), "ЗначокЗаявки.yaml": _PICTURE_RU},
        english={"Project.yaml": _PROJECT_EN.format(mode="8.0"),
                 "ApplicationBadge.yaml": _PICTURE_EN},
        tokens=_PICTURE_TOKENS,
    ),
    Seed(
        rule="yaml/bare-object-value",
        expect=CLEAN,
        note="an object-typed value written as a binding – the shape the platform accepts",
        files={"КарточкаИтога.yaml": _LABEL_VALUE_RU.format(value="=Подытог")},
        english={"TotalCard.yaml": _LABEL_VALUE_EN.format(value="=Subtotal")},
        tokens=_LABEL_VALUE_TOKENS,
    ),
    Seed(
        rule="yaml/bare-object-value",
        expect=FINDING,
        note="the same value as a bare word is rejected outright – the component whose "
             "property is object-typed is named by the ui schema",
        files={"КарточкаИтога.yaml": _LABEL_VALUE_RU.format(value="Подытог")},
        english={"TotalCard.yaml": _LABEL_VALUE_EN.format(value="Subtotal")},
        tokens=_LABEL_VALUE_TOKENS,
    ),
    Seed(
        rule="code/unknown-row-field",
        expect=CLEAN,
        note="a field the list selects, reached through the row's data member",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_READ_RU.format(field="Срок"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_READ_EN.format(field="Deadline"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/unknown-row-field",
        expect=FINDING,
        note="the reference itself instead of the alias the list gives it is reported – the row "
             "type annotation and the data member are read in both spellings",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_READ_RU.format(field="Раздел"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_READ_EN.format(field="Section"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/unknown-row-field",
        expect=CLEAN,
        note="the object protocol on a row – a member every instance carries, no list declares it",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_READ_RU.format(field="ВСтроку()"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_READ_EN.format(field="ToString()"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/unknown-row-field",
        expect=CLEAN,
        note="the row type's own key member – the documented way to the reference behind a row",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_READ_RU.format(field="Ключ"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_READ_EN.format(field="Key"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/row-field-null",
        expect=CLEAN,
        note="a field the list already guards with the null replacement fills a typed field",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_FILL_RU.format(field="ЗащищеннаяСумма"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_FILL_EN.format(field="GuardedAmount"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/row-field-null",
        expect=FINDING,
        note="the unguarded twin of the same field is reported – the guard is recognised by "
             "the member name, which the platform spells both ways",
        files={
            "ПанельОтметок.yaml": _ROW_FORM_RU,
            "ПанельОтметок.xbsl": _ROW_FILL_RU.format(field="СуммаРаздела"),
        },
        english={
            "MarkPanel.yaml": _ROW_FORM_EN,
            "MarkPanel.xbsl": _ROW_FILL_EN.format(field="SectionAmount"),
        },
        tokens=_ROW_TOKENS,
    ),
    Seed(
        rule="code/unknown-structure-field",
        expect=CLEAN,
        note="a field the structure declares, read through a parameter of that structure's type",
        files={
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": _STRUCT_DECL_RU,
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": _STRUCT_READ_RU.format(field="Сумма"),
        },
        english={
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": _STRUCT_DECL_EN,
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": _STRUCT_READ_EN.format(field="Amount"),
        },
        tokens=_STRUCT_TOKENS,
    ),
    Seed(
        rule="code/unknown-structure-field",
        expect=FINDING,
        note="a field the structure does not declare is reported – the member set comes from "
             "the project's own declaration, so both scripts have one to compare against",
        files={
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": _STRUCT_DECL_RU,
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": _STRUCT_READ_RU.format(field="Остаток"),
        },
        english={
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": _STRUCT_DECL_EN,
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": _STRUCT_READ_EN.format(field="Balance"),
        },
        tokens=_STRUCT_TOKENS,
    ),
    Seed(
        rule="code/unknown-structure-field",
        expect=CLEAN,
        note="the object protocol on a structure – a member no declaration lists and every "
             "instance carries",
        files={
            "Вычисления.yaml": _COMMON_MODULE_RU,
            "Вычисления.xbsl": _STRUCT_DECL_RU,
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": _STRUCT_READ_RU.format(field="ВСтроку()"),
        },
        english={
            "Calculations.yaml": _COMMON_MODULE_EN,
            "Calculations.xbsl": _STRUCT_DECL_EN,
            "Applications.yaml": _CATALOG_EN,
            "Applications.xbsl": _STRUCT_READ_EN.format(field="ToString()"),
        },
        tokens=_STRUCT_TOKENS,
    ),
    Seed(
        rule="code/client-available-needs-context",
        expect=CLEAN,
        note="a component method open to the client that keeps the instance context",
        files={
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": _CLIENT_AVAILABLE_RU.format(extra=" @Контекстный"),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": _CLIENT_AVAILABLE_EN.format(extra=" @Contextual"),
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-available-needs-context",
        expect=FINDING,
        note="the same method without the context annotation is reported – both annotations "
             "are read through the key forms of the term dictionary",
        files={
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": _CLIENT_AVAILABLE_RU.format(extra=""),
        },
        english={
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": _CLIENT_AVAILABLE_EN.format(extra=""),
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-available-unused",
        expect=CLEAN,
        note="a method open to the client that a component module calls",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": _CLIENT_AVAILABLE_RU.format(extra=""),
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": _CLIENT_CALL_RU,
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": _CLIENT_AVAILABLE_EN.format(extra=""),
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": _CLIENT_CALL_EN,
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="code/client-available-unused",
        expect=FINDING,
        note="the same method that no client place names is reported – which kinds count as "
             "client comes from the metamodel, the annotation from the term dictionary",
        files={
            "Серверный.yaml": _SERVER_MODULE_RU,
            "Серверный.xbsl": _CLIENT_AVAILABLE_RU.format(extra=""),
            "ФормаЗаявки.yaml": _FORM_RU,
            "ФормаЗаявки.xbsl": _CLIENT_IDLE_RU,
        },
        english={
            "ServerSide.yaml": _SERVER_MODULE_EN,
            "ServerSide.xbsl": _CLIENT_AVAILABLE_EN.format(extra=""),
            "ApplicationForm.yaml": _FORM_EN,
            "ApplicationForm.xbsl": _CLIENT_IDLE_EN,
        },
        tokens=_ENVIRONMENT_TOKENS,
    ),
    Seed(
        rule="naming/enum-vid",
        expect=CLEAN,
        note="an enumeration named with the kind word the standard picks",
        files={"ВидЗаявки.yaml": _ENUM_NAME_RU.format(name="ВидЗаявки")},
        english={"ApplicationKind.yaml": _ENUM_NAME_EN.format(name="ApplicationKind")},
        tokens=_ENUM_NAME_TOKENS,
    ),
    Seed(
        rule="naming/enum-vid",
        expect=FINDING,
        note="the same enumeration named with the word the standard rejects is reported – the "
             "kind word leads in Russian and trails in English",
        files={"ТипЗаявки.yaml": _ENUM_NAME_RU.format(name="ТипЗаявки")},
        english={"ApplicationType.yaml": _ENUM_NAME_EN.format(name="ApplicationType")},
        tokens=_ENUM_NAME_TOKENS,
    ),
    Seed(
        rule="naming/module-suffix",
        expect=CLEAN,
        note="a common module whose name says nothing about its environment",
        files={"Обмен.yaml": _MODULE_NAME_RU.format(name="Обмен")},
        english={"Exchange.yaml": _MODULE_NAME_EN.format(name="Exchange")},
        tokens=_MODULE_NAME_TOKENS,
    ),
    Seed(
        rule="naming/module-suffix",
        expect=FINDING,
        note="the same module carrying the environment in its name is reported – the "
             "environment values are an enumeration of the term dictionary",
        files={"ОбменКлиентИСервер.yaml": _MODULE_NAME_RU.format(name="ОбменКлиентИСервер")},
        english={
            "ExchangeClientAndServer.yaml":
                _MODULE_NAME_EN.format(name="ExchangeClientAndServer"),
        },
        tokens=_MODULE_NAME_TOKENS,
    ),
    Seed(
        rule="yaml/binding-needs-auto",
        expect=CLEAN,
        note="a binding whose method returns the union the property declares",
        files={
            "КарточкаОтметки.yaml": _CARD_BINDING_RU,
            "КарточкаОтметки.xbsl": _CARD_BINDING_RETURN_RU.format(type="Авто|Цвет", value="Авто"),
        },
        english={
            "MarkCard.yaml": _CARD_BINDING_EN,
            "MarkCard.xbsl": _CARD_BINDING_RETURN_EN.format(type="Auto|Color", value="Auto"),
        },
        tokens=_CARD_BINDING_TOKENS,
    ),
    Seed(
        rule="yaml/binding-needs-auto",
        expect=FINDING,
        note="the same binding returning the empty value is reported – the property union and "
             "its nullable flag come from the ui schema",
        files={
            "КарточкаОтметки.yaml": _CARD_BINDING_RU,
            "КарточкаОтметки.xbsl":
                _CARD_BINDING_RETURN_RU.format(type="Цвет?", value="Неопределено"),
        },
        english={
            "MarkCard.yaml": _CARD_BINDING_EN,
            "MarkCard.xbsl": _CARD_BINDING_RETURN_EN.format(type="Color?", value="Undefined"),
        },
        tokens=_CARD_BINDING_TOKENS,
    ),
    Seed(
        rule="yaml/slot-needs-list",
        expect=CLEAN,
        note="a list in a slot the schema types as a list",
        files={"ШаблонОтметки.yaml": _SLOT_RU.format(item=_SLOT_LIST_RU)},
        english={"MarkTemplate.yaml": _SLOT_EN.format(item=_SLOT_LIST_EN)},
        tokens=_SLOT_TOKENS,
    ),
    Seed(
        rule="yaml/slot-needs-list",
        expect=FINDING,
        note="one component where the same slot wants a list is reported – whether a slot is a "
             "list is the schema's word, not the property name's",
        files={"ШаблонОтметки.yaml": _SLOT_RU.format(item=_SLOT_ITEM_RU)},
        english={"MarkTemplate.yaml": _SLOT_EN.format(item=_SLOT_ITEM_EN)},
        tokens=_SLOT_TOKENS,
    ),
    Seed(
        rule="yaml/hint-too-long",
        expect=CLEAN,
        note="a hint the renderer shows in full",
        files={"ПодписьОтметки.yaml": _HINT_RU.format(hint="а" * 200)},
        english={"MarkCaption.yaml": _HINT_EN.format(hint="а" * 200)},
        tokens=_HINT_TOKENS,
    ),
    Seed(
        rule="yaml/hint-too-long",
        expect=FINDING,
        note="a hint the renderer cuts off is reported – the hint key is a schema property, "
             "spelled both ways",
        files={"ПодписьОтметки.yaml": _HINT_RU.format(hint="а" * 400)},
        english={"MarkCaption.yaml": _HINT_EN.format(hint="а" * 400)},
        tokens=_HINT_TOKENS,
    ),
    Seed(
        rule="yaml/popup-in-markup",
        expect=CLEAN,
        note="the derived popup only DECLARED as a property – the shape the cure produces",
        files={
            "СобственнаяПодсказка.yaml": _POPUP_DERIVED_RU,
            "СтраницаОтметки.yaml":
                _POPUP_HOST_RU.format(declaration=_POPUP_DECLARATION_RU, placed="Надпись"),
        },
        english={
            "OwnTooltip.yaml": _POPUP_DERIVED_EN,
            "MarkPage.yaml":
                _POPUP_HOST_EN.format(declaration=_POPUP_DECLARATION_EN, placed="Label"),
        },
        tokens=_POPUP_TOKENS,
    ),
    Seed(
        rule="yaml/popup-in-markup",
        expect=FINDING,
        note="the same component PLACED in the markup is reported – the popup type and the "
             "inheritance closure are read in both spellings",
        files={
            "СобственнаяПодсказка.yaml": _POPUP_DERIVED_RU,
            "СтраницаОтметки.yaml":
                _POPUP_HOST_RU.format(declaration="", placed="СобственнаяПодсказка"),
        },
        english={
            "OwnTooltip.yaml": _POPUP_DERIVED_EN,
            "MarkPage.yaml": _POPUP_HOST_EN.format(declaration="", placed="OwnTooltip"),
        },
        tokens=_POPUP_TOKENS,
    ),
    Seed(
        rule="code/bound-property-assign",
        expect=CLEAN,
        note="a data binding assigned from code – a bare path is a two-way link",
        files={
            "ФормаОтметки.yaml": _BOUND_FORM_RU.format(height="=Отступ"),
            "ФормаОтметки.xbsl": _BOUND_ASSIGN_RU,
        },
        english={
            "MarkForm.yaml": _BOUND_FORM_EN.format(height="=Indent"),
            "MarkForm.xbsl": _BOUND_ASSIGN_EN,
        },
        tokens=_BOUND_TOKENS,
    ),
    Seed(
        rule="code/bound-property-assign",
        expect=FINDING,
        note="a COMPUTED property assigned from code is reported – the components root and the "
             "property are matched in both spellings",
        files={
            "ФормаОтметки.yaml": _BOUND_FORM_RU.format(height="=ВысотаБлока()"),
            "ФормаОтметки.xbsl": _BOUND_ASSIGN_RU,
        },
        english={
            "MarkForm.yaml": _BOUND_FORM_EN.format(height="=BlockHeight()"),
            "MarkForm.xbsl": _BOUND_ASSIGN_EN,
        },
        tokens=_BOUND_TOKENS,
    ),
    Seed(
        rule="yaml/computed-binding-assigned",
        expect=CLEAN,
        note="the instance binds the assigned property with a bare path – the legal shape",
        files={
            "ПолеОттенка.yaml": _PICKER_RU,
            "ПолеОттенка.xbsl": _PICKER_MODULE_RU,
            "ПанельОттенков.yaml": _PICKER_HOST_RU.format(value="=ПоказанныйОттенок"),
        },
        english={
            "ShadeField.yaml": _PICKER_EN,
            "ShadeField.xbsl": _PICKER_MODULE_EN,
            "ShadePanel.yaml": _PICKER_HOST_EN.format(value="=ShownShade"),
        },
        tokens=_PICKER_TOKENS,
    ),
    Seed(
        rule="yaml/computed-binding-assigned",
        expect=FINDING,
        note="the only instance computes the property its component assigns – reported; the "
             "component kind is a metamodel name and the markup keys are schema names",
        files={
            "ПолеОттенка.yaml": _PICKER_RU,
            "ПолеОттенка.xbsl": _PICKER_MODULE_RU,
            "ПанельОттенков.yaml": _PICKER_HOST_RU.format(value="=ВычислитьОттенок(\"accent\")"),
        },
        english={
            "ShadeField.yaml": _PICKER_EN,
            "ShadeField.xbsl": _PICKER_MODULE_EN,
            "ShadePanel.yaml": _PICKER_HOST_EN.format(value="=ComputeShade(\"accent\")"),
        },
        tokens=_PICKER_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-filter-disabled",
        expect=CLEAN,
        note="a filter declared ENABLED next to the same assignment – the cure itself",
        files={
            "СписокОтметок.yaml": _FILTER_LIST_RU.format(use="Истина"),
            "СписокОтметок.xbsl": _FILTER_CODE_RU,
        },
        english={
            "MarkList.yaml": _FILTER_LIST_EN.format(use="True"),
            "MarkList.xbsl": _FILTER_CODE_EN,
        },
        tokens=_FILTER_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-filter-disabled",
        expect=FINDING,
        note="the same filter declared disabled while the module switches it on is reported – "
             "the use key and the member after the dot are one name in both spellings",
        files={
            "СписокОтметок.yaml": _FILTER_LIST_RU.format(use="Ложь"),
            "СписокОтметок.xbsl": _FILTER_CODE_RU,
        },
        english={
            "MarkList.yaml": _FILTER_LIST_EN.format(use="False"),
            "MarkList.xbsl": _FILTER_CODE_EN,
        },
        tokens=_FILTER_TOKENS,
    ),
    Seed(
        rule="query/named-parameter",
        expect=CLEAN,
        note="a query literal taking its value by interpolation – the shape the literal accepts",
        files={"Отметки.yaml": _MARKS_RU, "Отметки.xbsl": _PARAM_QUERY_RU.format(value="%Раздел")},
        english={"Marks.yaml": _MARKS_EN, "Marks.xbsl": _PARAM_QUERY_EN.format(value="%Section")},
        tokens=_PARAM_TOKENS,
    ),
    Seed(
        rule="query/named-parameter",
        expect=FINDING,
        note="the named parameter of the query language inside a literal is reported – the "
             "literal is recognised by the query keyword, spelled both ways",
        files={"Отметки.yaml": _MARKS_RU, "Отметки.xbsl": _PARAM_QUERY_RU.format(value="&Раздел")},
        english={"Marks.yaml": _MARKS_EN, "Marks.xbsl": _PARAM_QUERY_EN.format(value="&Section")},
        tokens=_PARAM_TOKENS,
    ),
    Seed(
        rule="naming/kind-in-name",
        expect=CLEAN,
        note="a report named without its kind word",
        files={"ПросроченныеОтметки.yaml":
               _KIND_NAME_RU.format(kind="Отчет", name="ПросроченныеОтметки")},
        english={"OverdueMarks.yaml":
                 _KIND_NAME_EN.format(kind="Report", name="OverdueMarks")},
        tokens=_KIND_NAME_TOKENS,
    ),
    Seed(
        rule="naming/kind-in-name",
        expect=FINDING,
        note="the same report carrying its kind in the name is reported – the kind word leads "
             "in Russian and trails in English",
        files={"ОтчетПросроченныеОтметки.yaml":
               _KIND_NAME_RU.format(kind="Отчет", name="ОтчетПросроченныеОтметки")},
        english={"OverdueMarksReport.yaml":
                 _KIND_NAME_EN.format(kind="Report", name="OverdueMarksReport")},
        tokens=_KIND_NAME_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-row-editing",
        expect=CLEAN,
        note="the event on a list over a HIERARCHICAL entity – node rows are what it is "
             "documented for",
        files={
            "Разделы.yaml": _HIER_CATALOG_RU,
            "ТаблицаОтметок.yaml": _ROW_EDIT_RU.format(entity="Разделы"),
        },
        english={
            "Sections.yaml": _HIER_CATALOG_EN,
            "MarkTable.yaml": _ROW_EDIT_EN.format(entity="Sections"),
        },
        tokens=_ROW_EDIT_TOKENS,
    ),
    Seed(
        rule="yaml/dynlist-row-editing",
        expect=FINDING,
        note="the same event over a flat entity is reported – the event key and the hierarchy "
             "key are both metamodel names",
        files={
            "Отметки.yaml": _MARKS_RU,
            "ТаблицаОтметок.yaml": _ROW_EDIT_RU.format(entity="Отметки"),
        },
        english={
            "Marks.yaml": _MARKS_EN,
            "MarkTable.yaml": _ROW_EDIT_EN.format(entity="Marks"),
        },
        tokens=_ROW_EDIT_TOKENS,
    ),
    Seed(
        rule="code/image-binding-server-call",
        expect=CLEAN,
        note="the image handed over WITH the row – a field, not a call: the cure itself",
        files={
            "Отметки.yaml": _MARKS_RU,
            "ПлиткаОтметки.yaml": _IMAGE_FORM_RU.format(value="=ДанныеСтроки.Данные.Срок"),
        },
        english={
            "Marks.yaml": _MARKS_EN,
            "MarkTile.yaml": _IMAGE_FORM_EN.format(value="=RowData.Data.Deadline"),
        },
        tokens={**_IMAGE_TOKENS, "Срок": "Deadline", "Сумма": "Amount"},
    ),
    Seed(
        rule="code/image-binding-server-call",
        expect=FINDING,
        note="the same image fetched by a call into an element module is reported – which "
             "components declare the image property is the ui schema's word",
        files={
            "Отметки.yaml": _MARKS_RU,
            "ПлиткаОтметки.yaml": _IMAGE_FORM_RU.format(value="=Отметки.ЗначокПоКоду(\"a\")"),
        },
        english={
            "Marks.yaml": _MARKS_EN,
            "MarkTile.yaml": _IMAGE_FORM_EN.format(value="=Marks.BadgeByCode(\"a\")"),
        },
        tokens={**_IMAGE_TOKENS, "Срок": "Deadline", "Сумма": "Amount"},
    ),
    Seed(
        rule="naming/boolean-name",
        expect=CLEAN,
        note="a boolean attribute named after the true value of the flag",
        files={"Отметки.yaml": _BOOLEAN_CATALOG_RU.format(name="Успешно")},
        english={"Marks.yaml": _BOOLEAN_CATALOG_EN.format(name="Successful")},
        tokens=_BOOLEAN_TOKENS,
    ),
    Seed(
        rule="naming/boolean-name",
        expect=FINDING,
        note="the negated twin of the same attribute is reported",
        files={"Отметки.yaml": _BOOLEAN_CATALOG_RU.format(name="НетОшибок")},
        english={"Marks.yaml": _BOOLEAN_CATALOG_EN.format(name="NoErrors")},
        tokens=_BOOLEAN_TOKENS,
        known="the check is blind on an English tree twice over, and only the first half can be "
              "closed from the data: the sections and the type are read by their Russian keys "
              "alone (pairable), while the naming words the verdict rests on are Russian "
              "GRAMMAR, not platform names - the negation particles and the assertion prefixes "
              "have no English spelling in any dictionary of the distribution, and the noun "
              "test is Russian morphology. Stating the English words is a decision "
              "about the standard, not a lookup, so the gap is planted rather than guessed.",
    ),
    Seed(
        rule="code/resource-bare-name",
        expect=FINDING,
        note="the Ресурсы root spelled out as the first segment of the key",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n"
                           "    знч Значок = Ресурс{Ресурсы/Проба.svg}\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значок": "Icon"},
    ),
    Seed(
        rule="code/resource-bare-name",
        expect=CLEAN,
        note="a key relative to the Ресурсы folder is the correct spelling",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n"
                           "    знч Значок = Ресурс{Проба.svg}\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe", "Значок": "Icon"},
    ),
    Seed(
        rule="code/unclosed-resource",
        expect=FINDING,
        note="a query result walked with an early break - the closeable stays open",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n"
                           "    знч Выборка = Запрос{\n"
                           "        ВЫБРАТЬ Заявка.Наименование ИЗ Заявки КАК Заявка\n"
                           "    }.Выполнить()\n"
                           "    для Запись из Выборка цикл\n"
                           "        прервать\n"
                           "    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Заявка": "Application", "Проба": "Probe",
                "Выборка": "Selection", "Запись": "Record"},
    ),
    Seed(
        rule="code/unclosed-resource",
        expect=CLEAN,
        note="the same loop over a resource held by `исп` closes on every exit path",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n"
                           "    исп Выборка = Запрос{\n"
                           "        ВЫБРАТЬ Заявка.Наименование ИЗ Заявки КАК Заявка\n"
                           "    }.Выполнить()\n"
                           "    для Запись из Выборка цикл\n"
                           "        прервать\n"
                           "    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Заявка": "Application", "Проба": "Probe",
                "Выборка": "Selection", "Запись": "Record"},
    ),
    Seed(
        rule="code/use-needs-closeable",
        expect=CLEAN,
        note="`исп` over a query result - a closeable by the catalog chain",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба()\n"
                           "    исп Выборка = Запрос{\n"
                           "        ВЫБРАТЬ Заявка.Наименование ИЗ Заявки КАК Заявка\n"
                           "    }.Выполнить()\n;\n",
        },
        tokens={"Заявки": "Applications", "Заявка": "Application", "Проба": "Probe",
                "Выборка": "Selection"},
    ),
    Seed(
        rule="code/compare-with-localized",
        expect=FINDING,
        note="a branch on the TEXT of a presentation - silent on another language",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Заявка: Заявки.Ссылка)\n"
                           "    если Заявка.Представление() == \"Новая\" тогда\n"
                           "        возврат\n"
                           "    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Заявка": "Application", "Проба": "Probe",
                "Новая": "New"},
    ),
    Seed(
        rule="code/compare-with-localized",
        expect=CLEAN,
        note="a branch on the value itself - the reference, not its text",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "Заявки.xbsl": "метод Проба(Заявка: Заявки.Ссылка, Образец: Заявки.Ссылка)\n"
                           "    если Заявка == Образец тогда\n"
                           "        возврат\n"
                           "    ;\n;\n",
        },
        tokens={"Заявки": "Applications", "Заявка": "Application", "Проба": "Probe",
                "Образец": "Sample"},
    ),
    Seed(
        rule="yaml/list-scroll-without-loading",
        expect=FINDING,
        note="a scrolled list whose navigation never asks for the next portion",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "СписокЗаявок.yaml": _LIST_FORM_RU
                                 + "    Содержимое:\n"
                                   "        Тип: Таблица<ДинамическийСписок<Заявки>>\n"
                                   "        Имя: Список\n"
                                   "        Навигация: Отсутствует\n"
                                   "        ПрокруткаПоВертикали: Истина\n",
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/list-scroll-without-loading",
        expect=CLEAN,
        note="the same list loading the next portion as it scrolls",
        files={
            "Заявки.yaml": _CATALOG_RU,
            "СписокЗаявок.yaml": _LIST_FORM_RU
                                 + "    Содержимое:\n"
                                   "        Тип: Таблица<ДинамическийСписок<Заявки>>\n"
                                   "        Имя: Список\n"
                                   "        Навигация: ПодгрузкаПриПрокрутке\n"
                                   "        ПрокруткаПоВертикали: Истина\n",
        },
        tokens=_LIST_FORM_TOKENS,
    ),
    Seed(
        rule="yaml/choice-needs-static-list",
        expect=FINDING,
        note="a value chooser with no static choice list - the form fails at initialisation",
        files={
            "КарточкаЗаявки.yaml": "ВидЭлемента: КомпонентИнтерфейса\n"
                                 "Ид: 1d1f5c60-0000-4000-8000-000000000f18\n"
                                 "Имя: КарточкаЗаявки\n"
                                 "ОбластьВидимости: ВПроекте\n"
                                 "Наследует:\n"
                                 "    Тип: ПроизвольнаяФорма\n"
                                 "    Содержимое:\n"
                                 "        Тип: ВыборЗначения<Строка>\n"
                                 "        Имя: Выбор\n",
        },
        tokens={"КарточкаЗаявки": "ApplicationCard", "Выбор": "Choice"},
    ),
    Seed(
        rule="yaml/choice-needs-static-list",
        expect=CLEAN,
        note="the same chooser carrying the list right on the node",
        files={
            "КарточкаЗаявки.yaml": "ВидЭлемента: КомпонентИнтерфейса\n"
                                 "Ид: 1d1f5c60-0000-4000-8000-000000000f18\n"
                                 "Имя: КарточкаЗаявки\n"
                                 "ОбластьВидимости: ВПроекте\n"
                                 "Наследует:\n"
                                 "    Тип: ПроизвольнаяФорма\n"
                                 "    Содержимое:\n"
                                 "        Тип: ВыборЗначения<Строка>\n"
                                 "        Имя: Выбор\n"
                                 "        СписокВыбора:\n"
                                 "            - Первый\n"
                                 "            - Второй\n",
        },
        tokens={"КарточкаЗаявки": "ApplicationCard", "Выбор": "Choice",
                "Первый": "First", "Второй": "Second"},
    ),
    Seed(
        rule="code/per-object-permissions-need-common",
        expect=FINDING,
        note="per-object permissions without the common handler in the module",
        files={
            "Заявки.yaml": _CATALOG_RU + "КонтрольДоступа:\n"
                            "    Разрешения:\n"
                            "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n",
            "Заявки.xbsl": "метод Проба()\n;\n",
        },
        tokens={"Заявки": "Applications", "Проба": "Probe"},
    ),
    Seed(
        rule="code/per-object-permissions-need-common",
        expect=CLEAN,
        note="the same object whose module declares the common calculation",
        files={
            "Заявки.yaml": _CATALOG_RU + "КонтрольДоступа:\n"
                            "    Разрешения:\n"
                            "        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта\n",
            "Заявки.xbsl": "@Обработчик\n"
                           "метод ВычислитьРазрешенияДоступа(): Массив<РазрешениеДоступа>\n"
                           "    возврат []\n;\n",
        },
        tokens={"Заявки": "Applications"},
    ),
    Seed(
        rule="code/local-method-cross-module",
        expect=FINDING,
        note="a method visible only in its own module called from another one",
        files={
            "Расчёты.yaml": "ВидЭлемента: ОбщийМодуль\n"
                           "Ид: 1d1f5c60-0000-4000-8000-000000000f21\n"
                           "Имя: Расчёты\n"
                           "ОбластьВидимости: ВПроекте\n"
                           "Окружение: КлиентИСервер\n",
            "Расчёты.xbsl": "@Локальный\nметод Служебный()\n;\n",
            "Отчёты.yaml": "ВидЭлемента: ОбщийМодуль\n"
                           "Ид: 1d1f5c60-0000-4000-8000-000000000f22\n"
                           "Имя: Отчёты\n"
                           "ОбластьВидимости: ВПроекте\n"
                           "Окружение: КлиентИСервер\n",
            "Отчёты.xbsl": "метод Проба()\n    Расчёты.Служебный()\n;\n",
        },
        tokens={"Расчёты": "Calculations", "Отчёты": "Reports", "Служебный": "Internal", "Проба": "Probe"},
    ),
    Seed(
        rule="code/local-method-cross-module",
        expect=CLEAN,
        note="the same call once the method is opened to the subsystem",
        files={
            "Расчёты.yaml": "ВидЭлемента: ОбщийМодуль\n"
                           "Ид: 1d1f5c60-0000-4000-8000-000000000f21\n"
                           "Имя: Расчёты\n"
                           "ОбластьВидимости: ВПроекте\n"
                           "Окружение: КлиентИСервер\n",
            "Расчёты.xbsl": "@ВПодсистеме\nметод Служебный()\n;\n",
            "Отчёты.yaml": "ВидЭлемента: ОбщийМодуль\n"
                           "Ид: 1d1f5c60-0000-4000-8000-000000000f22\n"
                           "Имя: Отчёты\n"
                           "ОбластьВидимости: ВПроекте\n"
                           "Окружение: КлиентИСервер\n",
            "Отчёты.xbsl": "метод Проба()\n    Расчёты.Служебный()\n;\n",
        },
        tokens={"Расчёты": "Calculations", "Отчёты": "Reports", "Служебный": "Internal", "Проба": "Probe"},
    ),
    # --- computed access control -------------------------------------------------------
    Seed(
        rule="code/permission-field-not-declared",
        expect=FINDING,
        note="the per-object handler reads a field the yaml does not list as computed by",
        files={"Записи.yaml": _RECORDS_RU,
               "Записи.xbsl": _COMMON_HANDLER_RU + _per_object_ru("возврат Запись.Пользователь")},
        tokens={**_RECORDS_TOKENS, "Пользователь": "User"},
    ),
    Seed(
        rule="code/permission-field-not-declared",
        expect=CLEAN,
        note="the same handler reading the declared field",
        files={"Записи.yaml": _RECORDS_RU,
               "Записи.xbsl": _COMMON_HANDLER_RU + _per_object_ru("возврат Запись.Владелец")},
        tokens=_RECORDS_TOKENS,
    ),
    Seed(
        rule="code/access-context-read-noop",
        expect=FINDING,
        note="the context is extended with the read right of an object everyone may read",
        files={"Заметки.yaml": _NOTES_RU.format(read="РазрешеноВсем"), "Работа.xbsl": _NOTES_XBSL_RU},
        tokens=_NOTES_TOKENS,
    ),
    Seed(
        rule="code/access-context-read-noop",
        expect=CLEAN,
        note="the same extension for an object whose reading is computed",
        files={"Заметки.yaml": _NOTES_RU.format(read="РазрешенияВычисляются"), "Работа.xbsl": _NOTES_XBSL_RU},
        tokens=_NOTES_TOKENS,
    ),
    Seed(
        rule="code/permission-handlers-need-recalc",
        expect=FINDING,
        note="a permission handler declared while nothing recomputes the permissions",
        files={"Записи.yaml": _RECORDS_RU, "Записи.xbsl": _COMMON_HANDLER_RU},
        tokens=_RECORDS_TOKENS,
    ),
    Seed(
        rule="code/permission-handlers-need-recalc",
        expect=CLEAN,
        note="the same handler with a recompute call elsewhere in the project",
        files={"Записи.yaml": _RECORDS_RU, "Записи.xbsl": _COMMON_HANDLER_RU,
               "Обновление.xbsl": "@ВПроекте\nметод Обновить()\n    Записи.ПересчитатьРазрешенияДоступа()\n;\n"},
        tokens={**_RECORDS_TOKENS, "Обновление": "Update", "Обновить": "Refresh"},
    ),
    Seed(
        rule="code/permission-right-not-computable",
        expect=FINDING,
        note="the handler hands out the read right the yaml settles statically",
        files={"Переводы.yaml": _TRANSFERS_RU, "Переводы.xbsl": _GRANT_RU.format(rights="Сущность.Право.Чтение")},
        tokens=_TRANSFERS_TOKENS,
    ),
    Seed(
        rule="code/permission-right-not-computable",
        expect=CLEAN,
        note="the same handler handing out a computed right",
        files={"Переводы.yaml": _TRANSFERS_RU, "Переводы.xbsl": _GRANT_RU.format(rights="Сущность.Право.Изменение")},
        tokens=_TRANSFERS_TOKENS,
    ),
    # --- references across a subsystem boundary ----------------------------------------
    Seed(
        rule="yaml/foreign-not-public",
        expect=FINDING,
        note="a yaml type position reaching a private element of another subsystem",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПодсистеме"),
               "Учет/Карточка.yaml": _CARD_HEAD_RU + "Импорт:\n    - Склад\n" + _CARD_BODY_RU},
        tokens=_CROSS_TOKENS,
    ),
    Seed(
        rule="yaml/foreign-not-public",
        expect=CLEAN,
        note="the same reference once the element is public",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Карточка.yaml": _CARD_HEAD_RU + "Импорт:\n    - Склад\n" + _CARD_BODY_RU},
        tokens=_CROSS_TOKENS,
    ),
    Seed(
        rule="code/foreign-not-public",
        expect=FINDING,
        note="a module calling a private common module of another subsystem",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/СрокиТоваров.yaml": _DEADLINES_RU.format(vis="ВПодсистеме"),
               "Склад/СрокиТоваров.xbsl": _DEADLINES_XBSL_RU,
               "Учет/Сводка.yaml": _SUMMARY_RU, "Учет/Сводка.xbsl": _SUMMARY_XBSL_RU},
        tokens=_VISIBILITY_TOKENS,
    ),
    Seed(
        rule="code/foreign-not-public",
        expect=CLEAN,
        note="the same call once the module is public",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/СрокиТоваров.yaml": _DEADLINES_RU.format(vis="ВПроекте"),
               "Склад/СрокиТоваров.xbsl": _DEADLINES_XBSL_RU,
               "Учет/Сводка.yaml": _SUMMARY_RU, "Учет/Сводка.xbsl": _SUMMARY_XBSL_RU},
        tokens=_VISIBILITY_TOKENS,
    ),
    Seed(
        rule="yaml/missing-import",
        expect=FINDING,
        note="a yaml reaching a public foreign element without importing its subsystem",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Карточка.yaml": _CARD_HEAD_RU + _CARD_BODY_RU},
        tokens=_CROSS_TOKENS,
    ),
    Seed(
        rule="yaml/missing-import",
        expect=CLEAN,
        note="the same reference with the subsystem imported",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Карточка.yaml": _CARD_HEAD_RU + "Импорт:\n    - Склад\n" + _CARD_BODY_RU},
        tokens=_CROSS_TOKENS,
    ),
    Seed(
        rule="code/missing-import",
        expect=FINDING,
        note="a module naming a public foreign type without importing its subsystem",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "метод Первый(): Товары.Ссылка?\n    возврат Неопределено\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="code/missing-import",
        expect=CLEAN,
        note="the same module with the import line",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "импорт Склад\n\nметод Первый(): Товары.Ссылка?\n    возврат Неопределено\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="code/unused-import",
        expect=FINDING,
        note="a module importing a subsystem its code never mentions",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "импорт Склад\n\nметод Первый()\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="code/unused-import",
        expect=CLEAN,
        note="the same import with an element of the subsystem in a type position",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "импорт Склад\n\nметод Первый(): Товары.Ссылка?\n    возврат Неопределено\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="yaml/missing-subsystem-usage",
        expect=FINDING,
        note="a module imports a subsystem its own subsystem does not declare as used",
        files={"Учет/Подсистема.yaml": _SUB_PRIVATE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "импорт Склад\n\nметод Первый(): Товары.Ссылка?\n    возврат Неопределено\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="yaml/missing-subsystem-usage",
        expect=CLEAN,
        note="the same import once the descriptor declares the usage",
        files={"Учет/Подсистема.yaml": _SUB_USE_RU, "Склад/Подсистема.yaml": _SUB_PRIVATE_RU,
               "Склад/Товары.yaml": _GOODS_RU.format(vis="ВПроекте"),
               "Учет/Расчеты.yaml": _CALC_YAML_RU,
               "Учет/Расчеты.xbsl": "импорт Склад\n\nметод Первый(): Товары.Ссылка?\n    возврат Неопределено\n;\n"},
        tokens=_CALC_TOKENS,
    ),
    Seed(
        rule="yaml/localization-missing-import",
        expect=FINDING,
        note="an unqualified dictionary reference across a subsystem boundary without the import",
        files={"Учет/Подсистема.yaml": "Имя: Учет\n", "Склад/Подсистема.yaml": "Имя: Склад\n",
               "Учет/Словарь.yaml": _STRINGS_DEFAULT_RU,
               "Учет/Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN,
               "Склад/Карточка.yaml": _CARD_HEAD_RU + "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Приветствие\n"},
        tokens={**_SUB_TOKENS, **_STRINGS_TOKENS},
    ),
    Seed(
        rule="yaml/localization-missing-import",
        expect=CLEAN,
        note="the same reference with the subsystem imported by the yaml itself",
        files={"Учет/Подсистема.yaml": "Имя: Учет\n", "Склад/Подсистема.yaml": "Имя: Склад\n",
               "Учет/Словарь.yaml": _STRINGS_DEFAULT_RU,
               "Учет/Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN,
               "Склад/Карточка.yaml": _CARD_HEAD_RU + "Импорт:\n    - Учет\n"
                                       "Наследует:\n    Тип: Страница\n    Заголовок: $Словарь.Приветствие\n"},
        tokens={**_SUB_TOKENS, **_STRINGS_TOKENS},
    ),
    # --- localized strings ---------------------------------------------------------------
    Seed(
        rule="yaml/localization-ref-to-template",
        expect=FINDING,
        note="a yaml reference to a key of the templates section",
        files={"Словарь.yaml": _STRINGS_DEFAULT_RU, "Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN,
               "Карточка.yaml": _LABEL_RU.format(value="$Словарь.Расширена")},
        tokens=_STRINGS_TOKENS,
    ),
    Seed(
        rule="yaml/localization-ref-to-template",
        expect=CLEAN,
        note="the same reference to a key of the strings section",
        files={"Словарь.yaml": _STRINGS_DEFAULT_RU, "Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN,
               "Карточка.yaml": _LABEL_RU.format(value="$Словарь.Приветствие")},
        tokens=_STRINGS_TOKENS,
    ),
    Seed(
        rule="yaml/placeholder-key-in-strings",
        expect=FINDING,
        note="a substitution left in the strings section",
        files={"Словарь.yaml": _STRINGS_RU.format(strings='    Готово: "Расширена (до $0)"\n',
                                                   templates="    Приветствие: Привет\n"),
               "Локализация/En/Словарь.yaml": 'Строки:\n    Готово: "Extended (until $0)"\nШаблоны:\n    Приветствие: Hello\n'},
        tokens=_STRINGS_TOKENS,
    ),
    Seed(
        rule="yaml/placeholder-key-in-strings",
        expect=CLEAN,
        note="the same substitution in the templates section",
        files={"Словарь.yaml": _STRINGS_DEFAULT_RU, "Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN},
        tokens=_STRINGS_TOKENS,
    ),
    Seed(
        rule="yaml/localization-key-unique",
        expect=FINDING,
        note="one key declared in both sections of a dictionary",
        files={"Словарь.yaml": _STRINGS_RU.format(strings="    Приветствие: Привет\n",
                                                   templates='    Приветствие: "Привет, $0"\n'),
               "Локализация/En/Словарь.yaml": 'Строки:\n    Приветствие: Hello\nШаблоны:\n    Приветствие: "Hello, $0"\n'},
        tokens=_STRINGS_TOKENS,
    ),
    Seed(
        rule="yaml/localization-key-unique",
        expect=CLEAN,
        note="the two sections with distinct keys",
        files={"Словарь.yaml": _STRINGS_DEFAULT_RU, "Локализация/En/Словарь.yaml": _STRINGS_PARTNER_EN},
        tokens=_STRINGS_TOKENS,
    ),
    # --- resources, declarations, calls --------------------------------------------------
    Seed(
        rule="code/unknown-resource",
        expect=FINDING,
        note="a resource key that resolves to nothing - neither the project nor the platform library",
        files={"Проект.yaml": _PROJECT_RU.format(mode="9.0"), "Основное/Ресурсы/Своя.svg": "<svg/>",
               "Основное/Картинки.xbsl": _PICTURES_XBSL_RU.format(key="Пробная9.svg")},
        tokens=_PICTURES_TOKENS,
    ),
    Seed(
        rule="code/unknown-resource",
        expect=CLEAN,
        note="a key naming a file of the project's resources folder",
        files={"Проект.yaml": _PROJECT_RU.format(mode="9.0"), "Основное/Ресурсы/Своя.svg": "<svg/>",
               "Основное/Картинки.xbsl": _PICTURES_XBSL_RU.format(key="Своя.svg")},
        tokens=_PICTURES_TOKENS,
    ),
    Seed(
        rule="code/collection-field-needs-req",
        expect=FINDING,
        note="a structure field of a collection type with no argument-less constructor",
        files={"Тело.xbsl": "структура Тело\n    пер Тексты: ЧитаемыйМассив<Строка>\n;\n"},
        tokens={"Тело": "Body", "Тексты": "Texts"},
    ),
    Seed(
        rule="code/collection-field-needs-req",
        expect=CLEAN,
        note="the same field made a constructor argument",
        files={"Тело.xbsl": "структура Тело\n    обз пер Тексты: ЧитаемыйМассив<Строка>\n;\n"},
        tokens={"Тело": "Body", "Тексты": "Texts"},
    ),
    Seed(
        rule="code/var-needs-init",
        expect=FINDING,
        note="a variable declared by a type that has no constructor and no default",
        files={"Работа.xbsl": "метод Проба()\n    пер Ответ: ОтветHttp\n    Сообщить(Ответ.КодСтатуса)\n;\n"},
        tokens={"Работа": "Work", "Проба": "Probe"},
    ),
    Seed(
        rule="code/var-needs-init",
        expect=CLEAN,
        note="the same variable declared nullable",
        files={"Работа.xbsl": "метод Проба()\n    пер Ответ: ОтветHttp?\n    Сообщить(1)\n;\n"},
        tokens={"Работа": "Work", "Проба": "Probe"},
    ),
    Seed(
        rule="code/call-arity",
        expect=FINDING,
        note="a local call passing more arguments than the signature takes",
        files={"Расчеты.xbsl": _COMBINE_RU + "\nметод Проба(): Число\n    возврат Сложить(1, 2, 3)\n;\n"},
        tokens=_ARITY_TOKENS,
    ),
    Seed(
        rule="code/call-arity",
        expect=CLEAN,
        note="the same call within the signature",
        files={"Расчеты.xbsl": _COMBINE_RU + "\nметод Проба(): Число\n    возврат Сложить(1)\n;\n"},
        tokens=_ARITY_TOKENS,
    ),
    Seed(
        rule="code/call-arity-cross",
        expect=FINDING,
        note="a cross-module call passing more arguments than the target signature takes",
        files={"Служебный.xbsl": _COMBINE_RU,
               "Вызывающий.xbsl": "метод Проба(): Число\n    возврат Служебный.Сложить(1, 2, 3)\n;\n"},
        tokens=_ARITY_TOKENS,
    ),
    Seed(
        rule="code/call-arity-cross",
        expect=CLEAN,
        note="the same call within the signature",
        files={"Служебный.xbsl": _COMBINE_RU,
               "Вызывающий.xbsl": "метод Проба(): Число\n    возврат Служебный.Сложить(1, 2)\n;\n"},
        tokens=_ARITY_TOKENS,
    ),
    Seed(
        rule="code/url-params-partial-encoding",
        expect=FINDING,
        note="the partially encoding query-parameter method on a builder chain",
        files={"Адреса.xbsl": 'метод Проба(): Строка\n    возврат Url.СБазовымUrl("http://x").СПараметрамиЗапроса("a=b").ВСтроку()\n;\n'},
        tokens={"Адреса": "Addresses", "Проба": "Probe"},
    ),
    Seed(
        rule="code/url-params-partial-encoding",
        expect=CLEAN,
        note="the same chain without that method",
        files={"Адреса.xbsl": 'метод Проба(): Строка\n    возврат Url.СБазовымUrl("http://x").ВСтроку()\n;\n'},
        tokens={"Адреса": "Addresses", "Проба": "Probe"},
    ),
    Seed(
        rule="code/local-method-cross-component",
        expect=FINDING,
        note="a component method at the default visibility called through an instance from another component",
        files={"Вкладка.yaml": _TAB_YAML_RU, "Вкладка.xbsl": "метод Загрузить()\n    возврат\n;\n",
               "Маршрутизатор.yaml": _ROUTER_YAML_RU, "Маршрутизатор.xbsl": _ROUTER_XBSL_RU},
        tokens=_TAB_TOKENS,
    ),
    Seed(
        rule="code/local-method-cross-component",
        expect=CLEAN,
        note="the same call once the method is opened to the subsystem",
        files={"Вкладка.yaml": _TAB_YAML_RU, "Вкладка.xbsl": "@ВПодсистеме\nметод Загрузить()\n    возврат\n;\n",
               "Маршрутизатор.yaml": _ROUTER_YAML_RU, "Маршрутизатор.xbsl": _ROUTER_XBSL_RU},
        tokens=_TAB_TOKENS,
    ),
    # --- components, modules, queries ----------------------------------------------------
    Seed(
        rule="yaml/unused-component",
        expect=FINDING,
        note="an interface component nothing places and nothing creates",
        files={"Проект.yaml": _PROJECT_RU.format(mode="9.0"), "Панель.yaml": _PANEL_RU},
        tokens={"Проба": "Probe", "Панель": "Panel", "Кабинет": "Cabinet"},
    ),
    Seed(
        rule="yaml/unused-component",
        expect=CLEAN,
        note="the same component placed by the entry point of the application",
        files={"Проект.yaml": _PROJECT_RU.format(mode="9.0"), "Панель.yaml": _PANEL_RU, "Кабинет.yaml": _CABINET_RU},
        tokens={"Проба": "Probe", "Панель": "Panel", "Кабинет": "Cabinet"},
    ),
    Seed(
        rule="yaml/property-shadows-module",
        expect=FINDING,
        note="an own property of a component named after a common module",
        files={"РаботаСЗадачами.yaml": _HANDLING_RU, "КарточкаЗадачи.yaml": _TASK_CARD_RU.format(prop="РаботаСЗадачами")},
        tokens={"РаботаСЗадачами": "TaskHandling", "КарточкаЗадачи": "TaskCard", "Задачи": "Tasks"},
    ),
    Seed(
        rule="yaml/property-shadows-module",
        expect=CLEAN,
        note="the same property under a name of its own",
        files={"РаботаСЗадачами.yaml": _HANDLING_RU, "КарточкаЗадачи.yaml": _TASK_CARD_RU.format(prop="Задачи")},
        tokens={"РаботаСЗадачами": "TaskHandling", "КарточкаЗадачи": "TaskCard", "Задачи": "Tasks"},
    ),
    Seed(
        rule="query/in-subquery-composite",
        expect=FINDING,
        note="a composite-type field checked with IN over a subquery",
        files={"Товары.yaml": _GOODS_FIELDS_RU, "Фильтры.yaml": _FILTERS_RU,
               "Отборы.xbsl": _IN_SUBQUERY_RU.format(field="Бейдж")},
        tokens=_QUERY_TOKENS,
    ),
    Seed(
        rule="query/in-subquery-composite",
        expect=CLEAN,
        note="the same condition over a field of one type",
        files={"Товары.yaml": _GOODS_FIELDS_RU, "Фильтры.yaml": _FILTERS_RU,
               "Отборы.xbsl": _IN_SUBQUERY_RU.format(field="Метка")},
        tokens=_QUERY_TOKENS,
    ),
    Seed(
        rule="code/unused-method",
        expect=FINDING,
        note="a method nothing in the project mentions",
        files={"Работа.xbsl": "метод Лишний()\n;\n"},
        tokens={"Работа": "Work", "Лишний": "Spare"},
    ),
    Seed(
        rule="code/unused-method",
        expect=CLEAN,
        note="the same method as a handler the platform calls itself",
        files={"Работа.xbsl": "@Обработчик\nметод Лишний()\n;\n"},
        tokens={"Работа": "Work", "Лишний": "Spare"},
    ),
    Seed(
        rule="code/duplicate-method-body",
        expect=FINDING,
        note="one method body written in two files",
        files={"Первый.xbsl": _DUPLICATE_BODY_RU.format(annotation=""),
               "Второй.xbsl": _DUPLICATE_BODY_RU.format(annotation="")},
        tokens=_DUPLICATE_TOKENS,
    ),
    Seed(
        rule="code/duplicate-method-body",
        expect=CLEAN,
        note="the same body in two platform hooks - the normal shape of that contract",
        files={"Первый.xbsl": _DUPLICATE_BODY_RU.format(annotation="@Обработчик\n"),
               "Второй.xbsl": _DUPLICATE_BODY_RU.format(annotation="@Обработчик\n")},
        tokens=_DUPLICATE_TOKENS,
    ),
    # --- conditions ------------------------------------------------------------------------
    Seed(
        rule="style/boolean-compare",
        expect=FINDING,
        note="a boolean parameter compared with the true keyword",
        files={"Проверки.xbsl": "метод Проба(Флаг: Булево)\n    если Флаг == Истина\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    Seed(
        rule="style/boolean-compare",
        expect=CLEAN,
        note="the same parameter checked without a comparison",
        files={"Проверки.xbsl": "метод Проба(Флаг: Булево)\n    если Флаг\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    Seed(
        rule="style/undefined-is",
        expect=FINDING,
        note="the undefined value checked with the type-test operator",
        files={"Проверки.xbsl": "метод Проба(Значение: Строка?)\n    если Значение это Неопределено\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    Seed(
        rule="style/undefined-is",
        expect=CLEAN,
        note="the same check written as a comparison",
        files={"Проверки.xbsl": "метод Проба(Значение: Строка?)\n    если Значение == Неопределено\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    Seed(
        rule="style/negated-is",
        expect=FINDING,
        note="the type-test operator negated on the outside",
        files={"Проверки.xbsl": "метод Проба(Значение: Объект)\n    если не (Значение это Строка)\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    Seed(
        rule="style/negated-is",
        expect=CLEAN,
        note="the same test negated on the inside",
        files={"Проверки.xbsl": "метод Проба(Значение: Объект)\n    если Значение это не Строка\n        возврат\n    ;\n;\n"},
        tokens=_CHECKS_TOKENS,
    ),
    # --- names, identifiers, the descriptor -------------------------------------------------
    Seed(
        rule="naming/underscore",
        expect=FINDING,
        note="an underscore used as a separator in an element name",
        files={"Товар_Цена.yaml": "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f4a\nИмя: Товар_Цена\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="naming/underscore",
        expect=CLEAN,
        note="a name without a separator",
        files={"Цены.yaml": _PRICES_RU},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="naming/presentation",
        expect=FINDING,
        note="a top-level element without its presentation",
        files={"Цены.yaml": _PRICES_RU},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="naming/presentation",
        expect=CLEAN,
        note="the same element with the presentation filled in",
        files={"Цены.yaml": _PRICES_RU + "Представление: Цены\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-required",
        expect=FINDING,
        note="an element declared without its identifier",
        files={"Цены.yaml": "ВидЭлемента: Справочник\nИмя: Цены\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-required",
        expect=CLEAN,
        note="the same element with its identifier",
        files={"Цены.yaml": _PRICES_RU},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-unique",
        expect=FINDING,
        note="two elements sharing one identifier",
        files={"Цены.yaml": _PRICES_RU,
               "Заявки.yaml": "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f48\nИмя: Заявки\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-unique",
        expect=CLEAN,
        note="the same two elements with identifiers of their own",
        files={"Цены.yaml": _PRICES_RU,
               "Заявки.yaml": "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f4c\nИмя: Заявки\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-uuid",
        expect=FINDING,
        note="an identifier that is not a uuid",
        files={"Цены.yaml": "ВидЭлемента: Справочник\nИд: nope\nИмя: Цены\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/id-uuid",
        expect=CLEAN,
        note="a well-formed identifier",
        files={"Цены.yaml": _PRICES_RU},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/name-matches-file",
        expect=FINDING,
        note="an element whose name differs from its file name",
        files={"Заявки.yaml": "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f4c\nИмя: Задачи\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="yaml/name-matches-file",
        expect=CLEAN,
        note="the name and the file agree",
        files={"Заявки.yaml": "ВидЭлемента: Справочник\nИд: 1d1f5c60-0000-4000-8000-000000000f4c\nИмя: Заявки\n"},
        tokens=_PRICES_TOKENS,
    ),
    Seed(
        rule="project/version",
        expect=FINDING,
        note="a project version of two numbers",
        files={"Проект.yaml": _DESCRIPTOR_RU.format(version="1.0", presentation=_DESCRIPTOR_PRESENTATION_RU)},
        tokens={"Проба": "Probe"},
    ),
    Seed(
        rule="project/version",
        expect=CLEAN,
        note="a semantic version of three numbers",
        files={"Проект.yaml": _DESCRIPTOR_RU.format(version="1.0.0", presentation=_DESCRIPTOR_PRESENTATION_RU)},
        tokens={"Проба": "Probe"},
    ),
    Seed(
        rule="project/presentation",
        expect=FINDING,
        note="a descriptor without the presentations",
        files={"Проект.yaml": _DESCRIPTOR_RU.format(version="1.0.0", presentation="")},
        tokens={"Проба": "Probe"},
    ),
    Seed(
        rule="project/presentation",
        expect=CLEAN,
        note="the same descriptor with both presentations",
        files={"Проект.yaml": _DESCRIPTOR_RU.format(version="1.0.0", presentation=_DESCRIPTOR_PRESENTATION_RU)},
        tokens={"Проба": "Probe"},
    ),
    # --- visible text, literal-typed properties, the descriptor's identifiers --------------
    Seed(
        rule="typography/yo-in-text",
        expect=FINDING,
        note="the letter yo in a caption a user reads",
        files={"Карточка.yaml": _CARD_HEAD_RU + "Содержимое:\n    -\n        Тип: Кнопка\n        Заголовок: Ещё\n"},
        tokens={"Карточка": "Card"},
    ),
    Seed(
        rule="typography/yo-in-text",
        expect=CLEAN,
        note="the same caption spelled without it",
        files={"Карточка.yaml": _CARD_HEAD_RU + "Содержимое:\n    -\n        Тип: Кнопка\n        Заголовок: Еще\n"},
        tokens={"Карточка": "Card"},
    ),
    Seed(
        rule="yaml/no-expression-in-literal",
        expect=FINDING,
        note="an expression written into a property that takes a literal alone",
        files={"Карточка.yaml": _CARD_HEAD_RU + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Текст\n"
                                                 "        Шрифт:\n            Тип: АбсолютныйШрифт\n"
                                                 "            Размер: =Мобильный?28:40\n"},
        tokens={"Карточка": "Card", "Текст": "Text", "Мобильный": "Mobile"},
    ),
    Seed(
        rule="yaml/no-expression-in-literal",
        expect=CLEAN,
        note="the same property with a literal",
        files={"Карточка.yaml": _CARD_HEAD_RU + "Содержимое:\n    -\n        Тип: Надпись\n        Имя: Текст\n"
                                                 "        Шрифт:\n            Тип: АбсолютныйШрифт\n"
                                                 "            Размер: 13\n"},
        tokens={"Карточка": "Card", "Текст": "Text"},
    ),
    Seed(
        rule="project/identifier",
        expect=FINDING,
        note="a vendor identifier starting in lower case",
        files={"Проект.yaml": "Ид: 1d1f5c60-0000-4000-8000-000000000f49\nПоставщик: acme\nИмя: Проба\n"
                              "Версия: 1.0.0\n" + _DESCRIPTOR_PRESENTATION_RU + "РежимСовместимости: 9.0\n"},
        tokens={"Проба": "Probe"},
    ),
    Seed(
        rule="project/identifier",
        expect=CLEAN,
        note="the identifiers as the standard wants them",
        files={"Проект.yaml": _DESCRIPTOR_RU.format(version="1.0.0", presentation=_DESCRIPTOR_PRESENTATION_RU)},
        tokens={"Проба": "Probe"},
    ),
    Seed(
        rule="style/enum-name-vid",
        expect=FINDING,
        note="an enumeration named with the word for type instead of kind",
        files={"Кнопки.xbsl": "перечисление ТипКнопки\n    Да\n;\n"},
        tokens={"Кнопки": "Buttons", "ТипКнопки": "ButtonType", "Да": "Yes"},
        known="the English standard puts the kind word LAST (ButtonType), and the rule matches the "
              "prefix alone in either spelling - the shape naming/kind-in-name had before its fix. "
              "Closing it is a change of the rule judged against the standard, not a lookup.",
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
        path.write_text(text, encoding="utf-8", newline="")
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
    parser.add_argument(
        "--quiet", action="store_true",
        help="print only the seeds that disagree (known gaps included) and the summary line",
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

    # A full run is one line per seed, and there are hundreds of them: read for the single
    # number "disagreements: 0" it floods the log. `--quiet` keeps the lines that carry
    # news - a disagreement, a known gap, a gap that closed - and the summary.
    shown = [r for r in results if not args.quiet or r["status"] != "ok"]
    width = max((len(r["status"]) for r in shown), default=0)
    for result in shown:
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
