"""The translator on two kinds of yaml values that name something: handlers and fields.

A value the metamodel types `BslHandler` names a method of the element's module - the method of
a SOAP operation, the one serving any verb of a route - and the module renames that method; a
value typed `AttributeName` names a field of the element, a standard one among them. Both used
to stay Russian in a translated tree: the handler as data, the reference field as a word no
table spells on its own.
"""

from __future__ import annotations

from xbsl import engine
from xbsl.translation.code import Resolver
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml


def _yaml(text: str, tokens: dict[str, str], name: str = "Элемент.yaml") -> tuple[str, FileReport]:
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    return translate_yaml(source, Resolver(Dictionary(tokens=dict(tokens))), report), report


_SOAP = """\
ВидЭлемента: SoapСервис
Ид: 1d1f5c60-0000-4000-8000-000000000e01
Имя: СервисЗаявок
ОбластьВидимости: ВПроекте
Обработчики:
    -
        Имя: AcceptApplication
        Метод: ПринятьЗаявку
"""
_SOAP_TOKENS = {"СервисЗаявок": "ApplicationService", "ПринятьЗаявку": "AcceptApplication"}


def test_soap_handler_method_follows_the_module():
    out, _report = _yaml(_SOAP, _SOAP_TOKENS)
    assert "        Method: AcceptApplication\n" in out
    # The name of the operation is the WSDL's, Latin already, and stays as it is.
    assert "        Name: AcceptApplication\n" in out


def test_handler_without_an_entry_is_a_gap_not_a_text():
    # The method name has no entry: the gap is reported the way the module reports it, instead
    # of being kept as a text nobody translates.
    out, report = _yaml(_SOAP, {"СервисЗаявок": "ApplicationService"})
    assert "        Method: ПринятьЗаявку\n" in out
    assert "ПринятьЗаявку" in report.missing_tokens
    assert all("ПринятьЗаявку" not in str(kept) for kept in report.texts_kept)


def test_route_handler_of_any_verb_follows_the_module():
    text = (
        "ВидЭлемента: HttpСервис\nИд: 1d1f5c60-0000-4000-8000-000000000e02\nИмя: СервисДанных\n"
        "ОбластьВидимости: ВПроекте\nКорневойUrl: /data\nШаблоныUrl:\n    -\n        Имя: Корень\n"
        "        Шаблон: /\n        ЛюбойМетод: ОбработатьЛюбой\n"
    )
    tokens = {"СервисДанных": "DataService", "Корень": "Root", "ОбработатьЛюбой": "HandleAny"}
    out, _report = _yaml(text, tokens)
    assert "        AnyMethod: HandleAny\n" in out


_STOCK = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-000000000e03
Имя: Склады
ОбластьВидимости: ВПроекте
КонтрольДоступа:
    РасчетРазрешенийПо: [Ответственный, Ссылка, Владелец]
    Разрешения:
        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта
Индексы:
    -
        Имя: ПоОтветственному
        Поля:
            - Ответственный
            - Ссылка
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000e04
        Имя: Ответственный
        Тип: Строка
"""
_STOCK_TOKENS = {"Склады": "Stock", "Ответственный": "Keeper", "ПоОтветственному": "ByKeeper"}


def test_reference_field_is_spelled_as_a_member_of_the_entity():
    """The reference of an object is `Reference` - the member of the entity object - while the
    flat tables call the word `Link` after a dot and nothing on its own."""
    out, report = _yaml(_STOCK, _STOCK_TOKENS)
    assert "    ComputePermissionsBy: [Keeper, Reference, Owner]\n" in out
    assert "            - Keeper\n            - Reference\n" in out
    assert "Ссылка" not in out
    assert not report.missing_tokens


def test_dictionary_entry_answers_before_the_entity_member():
    # An entry for the word is the project's decision, and it is asked first - as in the code.
    out, _report = _yaml(_STOCK, {**_STOCK_TOKENS, "Ссылка": "Ref"})
    assert "    ComputePermissionsBy: [Keeper, Ref, Owner]\n" in out


_LISTED = """\
ВидЭлемента: {kind}
Ид: 1d1f5c60-0000-4000-8000-000000000e05
Имя: Узлы
ОбластьВидимости: ВПроекте
КонтрольДоступа:
    РасчетРазрешенийПо: [{listed}]
    Разрешения:
        Чтение: РазрешенияВычисляютсяДляКаждогоОбъекта
"""


def test_the_fields_of_an_exchange_plan_node_are_spelled_as_its_standard_attributes():
    """The metamodel gives each standard attribute of an exchange plan both spellings. The flat
    tables may keep none for a word the platform spells two ways, and the list kept the number of
    the sent message and this node in Russian."""
    out, report = _yaml(_LISTED.format(kind="ПланОбмена",
                                       listed="Код, НомерОтправленного, НомерПринятого, ЭтотУзел"),
                        {"Узлы": "Nodes"})
    assert "    ComputePermissionsBy: [Code, SentNumber, ReceivedNumber, ThisNode]\n" in out
    assert not report.missing_tokens


def test_the_system_attributes_of_a_settings_storage_are_spelled_in_the_list():
    out, report = _yaml(_LISTED.format(
        kind="ХранилищеНастроек",
        listed="Пользователь, КлючОбъекта, КлючНастройки, Вариант, Общая, Значение, Наименование"),
        {"Узлы": "Nodes"})
    assert ("    ComputePermissionsBy: [User, ObjectKey, SettingKey, Variant, Shared, Value, "
            "Name]\n") in out
    assert not report.missing_tokens


def test_the_connection_settings_of_an_integrable_application_are_spelled_in_the_list():
    out, report = _yaml(_LISTED.format(kind="ИнтегрируемоеПриложение",
                                       listed="НастройкиПрямогоПодключения, Код, Наименование"),
                        {"Узлы": "Nodes"})
    assert "    ComputePermissionsBy: [DirectConnectionSettings, Code, Name]\n" in out
    assert not report.missing_tokens


_NODES_WITH_ROWS = """\
ВидЭлемента: ПланОбмена
Ид: 1d1f5c60-0000-4000-8000-000000000e06
Имя: Узлы
ОбластьВидимости: ВПроекте
ТабличныеЧасти:
    -
        Ид: 1d1f5c60-0000-4000-8000-000000000e07
        Имя: Пакеты
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-000000000e08
                Имя: НомерОтправленного
                Тип: Число
        Индексы:
            -
                Имя: ПоНомеру
                Поля:
                    - НомерОтправленного
"""


def test_an_index_of_a_tabular_section_names_the_fields_of_the_section():
    """A tabular section owns the fields its index names, so the word is the section's own
    attribute there, not the standard attribute of the node: the index and the declaration it
    points at are spelled alike, whatever the flat tables say about the word."""
    out, _report = _yaml(_NODES_WITH_ROWS, {"Узлы": "Nodes", "Пакеты": "Packages",
                                            "ПоНомеру": "ByNumber"})
    declared = next(line for line in out.splitlines() if line.startswith("                Name: "))
    indexed = next(line for line in out.splitlines() if line.startswith("                    - "))
    assert declared.split(": ", 1)[1] == indexed.split("- ", 1)[1]
