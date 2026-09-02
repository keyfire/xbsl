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
