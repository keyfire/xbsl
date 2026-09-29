"""yaml/root-url-cyrillic: a service `RootUrl` with Cyrillic letters, which no request reaches.

The cases follow probes on a server: an HTTP service and a SOAP one with a Cyrillic root address
built and ran next to Latin ones, and a request to the percent-encoded address got "Handler of
HTTP request ... not found" while the Latin ones answered. The service name and the namespace
of a SOAP service worked in Cyrillic and are not judged.
"""

import pytest

from xbsl import engine, i18n
from xbsl.fixer import fix_source

RULE = "yaml/root-url-cyrillic"

# The kinds and the key are read in both spellings from the metamodel.
pytestmark = pytest.mark.needs_data

_HTTP = """ВидЭлемента: HttpСервис
Ид: 7c1e5a90-0000-4000-8000-000000000011
Имя: СервисЗадач
ОбластьВидимости: ВПодсистеме
КорневойUrl: {root}
"""

_SOAP = """ВидЭлемента: SoapСервис
Ид: 7c1e5a90-0000-4000-8000-000000000012
Имя: СервисЗадач
ОбластьВидимости: ВПодсистеме
ПространствоИменСервиса: https://example.com/{namespace}
ИмяСервиса: {service}
КорневойUrl: {root}
Обработчики:
    -
        Имя: AddTask
        Метод: ДобавитьЗадачу
"""


def _lint(text, name="СервисЗадач.yaml"):
    return [d for d in engine.run_sources([engine.load_text(name, text)], select={RULE})
            if d.rule_id == RULE]


def test_a_cyrillic_root_url_of_an_http_service_is_reported_at_the_value():
    diags = _lint(_HTTP.format(root="/ЗадачиПроекта"))
    assert [(d.line, d.col) for d in diags] == [(5, 14)]
    assert "'/ЗадачиПроекта'" in diags[0].message
    assert "'/zadachi-proekta'" in diags[0].message


def test_a_cyrillic_root_url_of_a_soap_service_is_reported():
    diags = _lint(_SOAP.format(namespace="tasks", service="TaskService", root="/задачи/v1"))
    assert [(d.line, d.col) for d in diags] == [(7, 14)]
    assert "'/zadachi/v1'" in diags[0].message


def test_control_a_latin_address_and_the_cyrillic_names_that_work_are_silent():
    assert _lint(_HTTP.format(root="/tasks")) == []
    # The service name and the namespace answered in Cyrillic on the server.
    assert _lint(_SOAP.format(namespace="задачи", service="СервисЗадач", root="/tasks")) == []


def test_another_kind_is_not_judged():
    text = _HTTP.format(root="/Задачи").replace("HttpСервис", "ОбщийМодуль")
    assert _lint(text) == []


def test_the_fix_writes_the_address_in_latin_letters():
    text = _HTTP.format(root="/ЗадачиПроекта")
    source = engine.load_text("СервисЗадач.yaml", text)
    diags = [d for d in engine.run_sources([source], select={RULE}) if d.rule_id == RULE]
    assert fix_source(source, diags).text == _HTTP.format(root="/zadachi-proekta")


def test_a_quoted_address_is_reported_without_a_fix():
    diags = _lint(_HTTP.format(root='"/Задачи"'))
    assert len(diags) == 1 and diags[0].fix is None


def test_the_english_spelling_is_read():
    i18n.set_lang("en")
    text = ("ElementKind: HttpService\nId: 7c1e5a90-0000-4000-8000-000000000013\n"
            "Name: TaskService\nVisibilityScope: InSubsystem\nRootUrl: /Задачи\n")
    diags = _lint(text, "TaskService.yaml")
    assert [(d.line, d.col) for d in diags] == [(5, 10)]
    assert "RootUrl '/Задачи' holds Cyrillic letters" in diags[0].message
