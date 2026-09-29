"""yaml/document-date-required: a document must declare its standard date attribute.

The help calls the date the required standard attribute of a document, and a probe build
refused a document without it with `Attribute "Дата" is required` at the dash of its first
attribute, while the same document with the date compiled.
"""

import pytest

from xbsl import engine, i18n

RULE = "yaml/document-date-required"

# The date is the item the metamodel dispatches the attributes of a document to by its name:
# without the metamodel the rule is silent.
pytestmark = pytest.mark.needs_data

_HEAD = ("ВидЭлемента: Документ\nИд: 5b3d7e21-0000-4000-8000-000000000001\nИмя: Поступления\n"
         "ОбластьВидимости: ВПодсистеме\n")
_AMOUNT = ("    -\n        Ид: 5b3d7e21-0000-4000-8000-000000000002\n        Имя: Сумма\n"
           "        Тип: Число\n")
_DATE = "    -\n        Имя: Дата\n        Тип: ДатаВремя\n"


def _lint(text, name="Поступления.yaml"):
    return [d for d in engine.run_sources([engine.load_text(name, text)], select={RULE})
            if d.rule_id == RULE]


def test_a_document_without_the_date_is_reported_at_its_attributes():
    diags = _lint(_HEAD + "Реквизиты:\n" + _AMOUNT)
    assert [(d.line, d.col) for d in diags] == [(6, 5)]
    assert "\"Attribute \"Дата\" is required\"" in diags[0].message


def test_a_document_without_attributes_at_all_is_reported_at_its_start():
    assert [(d.line, d.col) for d in _lint(_HEAD)] == [(1, 1)]


def test_control_the_date_in_any_place_of_the_list_is_enough():
    assert _lint(_HEAD + "Реквизиты:\n" + _AMOUNT + _DATE) == []
    assert _lint(_HEAD + "Реквизиты:\n" + _DATE + _AMOUNT) == []


def test_another_kind_is_not_judged():
    catalog = _HEAD.replace("Документ", "Справочник") + "Реквизиты:\n" + _AMOUNT
    assert _lint(catalog) == []


def test_the_english_spelling_is_read():
    i18n.set_lang("en")
    head = ("ElementKind: Document\nId: 5b3d7e21-0000-4000-8000-000000000003\nName: Receipts\n"
            "VisibilityScope: InSubsystem\nAttributes:\n")
    amount = ("    -\n        Id: 5b3d7e21-0000-4000-8000-000000000004\n        Name: Amount\n"
              "        Type: Number\n")
    diags = _lint(head + amount, "Receipts.yaml")
    assert [(d.line, d.col) for d in diags] == [(6, 5)]
    assert "\"Attribute \"Date\" is required\"" in diags[0].message
    assert _lint(head + amount + "    -\n        Name: Date\n        Type: DateTime\n",
                 "Receipts.yaml") == []
