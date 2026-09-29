"""yaml/soap-handler-name: the name of a SOAP service handler the build refuses.

The cases are the verdict of a probe build: a Cyrillic name, a name with a whitespace, one
starting with a digit and a Latin name with one Cyrillic letter were refused with "Handler
name ... contains invalid characters" at the value; `AddToCart` and `Add_Item` compiled, and so
did `Add-Item` and `Add.Item`.
"""

import pytest

from xbsl import engine, i18n

RULE = "yaml/soap-handler-name"

# The kind and the keys are read in both spellings from the metamodel and the term dictionary.
pytestmark = pytest.mark.needs_data

_SERVICE = """ВидЭлемента: SoapСервис
Ид: 7c1e5a90-0000-4000-8000-000000000001
Имя: СервисЗаказов
ОбластьВидимости: ВПодсистеме
ПространствоИменСервиса: https://example.com/orders
КорневойUrl: orders
Обработчики:
{handlers}"""


def _handlers(*names):
    return "".join(f"    -\n        Имя: {name}\n        Метод: Операция{index}\n"
                   for index, name in enumerate(names, start=1))


def _lint(text, name="СервисЗаказов.yaml"):
    return [d for d in engine.run_sources([engine.load_text(name, text)], select={RULE})
            if d.rule_id == RULE]


def test_the_names_the_build_refused_are_reported_at_the_value():
    text = _SERVICE.format(handlers=_handlers("ДобавитьЗаказ", '"Add Order"', "1AddOrder",
                                              "AddЁ"))
    diags = _lint(text)
    assert [(d.line, d.col) for d in diags] == [(9, 14), (12, 14), (15, 14), (18, 14)]
    assert "'ДобавитьЗаказ'" in diags[0].message and "не латиницей" in diags[0].message
    assert "пробельный" in diags[1].message
    assert "с цифры" in diags[2].message
    assert "('Ё')" in diags[3].message


def test_control_the_names_the_build_took_are_silent():
    text = _SERVICE.format(handlers=_handlers("AddOrder", "Add_Order", "Add-Order", "Add.Order"))
    assert _lint(text) == []


def test_the_method_of_the_module_may_stay_cyrillic():
    assert _lint(_SERVICE.format(handlers=_handlers("AddOrder"))) == []


def test_another_kind_is_not_judged():
    text = _SERVICE.replace("SoapСервис", "HttpСервис").format(
        handlers=_handlers("ДобавитьЗаказ"))
    assert _lint(text) == []


def test_the_english_spelling_is_read():
    i18n.set_lang("en")
    text = ("ElementKind: SoapService\nId: 7c1e5a90-0000-4000-8000-000000000002\n"
            "Name: OrderService\nVisibilityScope: InSubsystem\n"
            "ServiceNamespace: https://example.com/orders\nRootUrl: orders\n"
            "Handlers:\n    -\n        Name: ДобавитьЗаказ\n        Method: AddOrder\n")
    diags = _lint(text, "OrderService.yaml")
    assert [(d.line, d.col) for d in diags] == [(9, 15)]
    assert "outside Latin" in diags[0].message
