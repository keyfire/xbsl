"""Checks of the yaml/item-id-required rule (a collection item without its Ид)."""

from xbsl import engine

_RULE = "yaml/item-id-required"

_HEAD = (
    "ВидЭлемента: Справочник\n"
    "Ид: 5e7f1a29-6b83-4c47-a0d2-8f3b9c5e1d66\n"
    "Имя: Проверки\n"
)


def _lint(text: str, name: str = "Проверки.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={_RULE})


def test_attribute_without_an_id_is_reported():
    d = _lint(_HEAD + "Реквизиты:\n    -\n        Имя: Сумма\n        Тип: Число\n")
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].line == 6
    assert "Сумма" in d[0].message


def test_attribute_with_an_id_is_silent():
    d = _lint(
        _HEAD + "Реквизиты:\n    -\n        Ид: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903\n"
        "        Имя: Сумма\n        Тип: Число\n"
    )
    assert d == []


def test_built_in_attribute_needs_no_id():
    # the dispatched class of Наименование declares no Ид - there the key is forbidden,
    # which the neighbouring rule reports
    d = _lint(_HEAD + "Реквизиты:\n    -\n        Имя: Наименование\n")
    assert d == []


def test_tabular_section_and_its_attribute_are_judged():
    d = _lint(
        _HEAD + "ТабличныеЧасти:\n    -\n        Имя: Строки\n        Реквизиты:\n"
        "            -\n                Имя: Поле\n                Тип: Строка\n"
    )
    assert [x.line for x in d] == [6, 9]


def test_enumeration_item_is_judged():
    d = _lint(
        "ВидЭлемента: Перечисление\nИд: 9b1c3d47-8e52-4a69-b7f3-0d6a2e8c4f77\n"
        "Имя: ВидПроверки\nЭлементы:\n    -\n        Имя: Первый\n",
        name="ВидПроверки.yaml",
    )
    assert len(d) == 1 and "Первый" in d[0].message


def test_english_spelling_is_judged():
    d = _lint(
        "ElementKind: Catalog\nId: 5e7f1a29-6b83-4c47-a0d2-8f3b9c5e1d66\nName: Checks\n"
        "Attributes:\n    -\n        Name: Amount\n        Type: Number\n"
        "    -\n        Id: 8f3a2c14-7b6d-4e05-9a1c-2d5f8b47e903\n        Name: Note\n",
        name="Checks.yaml",
    )
    assert len(d) == 1 and "Amount" in d[0].message
