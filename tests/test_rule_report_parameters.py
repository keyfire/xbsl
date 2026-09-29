"""yaml/report-parameters-alias: the query parameters of a report under the `Parameters` key.

The metamodel lists `Parameters` as a second spelling of the `QueryParameters` property of a
report, and a live probe got the unknown property refusal for it on the server. The right key
compiles; the fix renames the wrong one unless the report already has the right key.

The rule needs no Element data for a Russian description, so the tests live outside test_rules
and run in the public CI; the English spelling needs the platform dictionary and is marked.
"""

import pytest

from xbsl import engine

_RULE = "yaml/report-parameters-alias"


def _report(key: str, tail: str = "") -> str:
    return ("ВидЭлемента: Отчет\nИд: 11111111-1111-1111-1111-111111111111\nИмя: СводкаПоставок\n"
            "ОбластьВидимости: ВПроекте\nВидИсточникаДанных: Запрос\n"
            f"{key}:\n    -\n        Имя: ПериодСводки\n        Тип: Дата\n" + tail)


def _lint(text: str, name: str = "СводкаПоставок.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={_RULE})


def test_the_alias_key_is_flagged_with_a_fix():
    text = _report("Параметры")
    d = _lint(text)
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (6, 1)
    assert "'ПараметрыЗапроса'" in d[0].message and "Неизвестное свойство" in d[0].message
    fixed = text[:d[0].fix.start] + d[0].fix.new + text[d[0].fix.end:]
    assert fixed == _report("ПараметрыЗапроса")
    assert _lint(fixed) == []


def test_negative_control_the_same_key_elsewhere_is_silent():
    # The right key of a report passes; the same `Parameters` key on another kind - a global
    # client event declares it - and inside a nested node is not this rule's business.
    assert _lint(_report("ПараметрыЗапроса")) == []
    event = _report("Параметры").replace(
        "ВидЭлемента: Отчет", "ВидЭлемента: ГлобальноеКлиентскоеСобытие")
    assert _lint(event) == []
    nested = _report("ПараметрыЗапроса", "Интерфейс:\n    Параметры:\n        - ПериодСводки\n")
    assert _lint(nested) == []


def test_a_report_with_both_keys_is_flagged_without_a_fix():
    # The renamed key would repeat the one already there - the two lists are merged by hand.
    text = _report("Параметры", "ПараметрыЗапроса:\n    -\n        Имя: ОтборПоставщика\n"
                                "        Тип: Строка\n")
    d = _lint(text)
    assert len(d) == 1 and d[0].fix is None


def test_a_quoted_key_is_flagged_without_a_fix():
    d = _lint(_report("\"Параметры\""))
    assert len(d) == 1 and d[0].fix is None


@pytest.mark.needs_data
def test_an_english_report_is_renamed_in_its_own_spelling():
    # The kind and both keys are read through the platform dictionary and the metamodel.
    text = ("ElementKind: Report\nId: 11111111-1111-1111-1111-111111111111\nName: SupplySummary\n"
            "VisibilityScope: InProject\nDataSourceKind: Query\n"
            "Parameters:\n    -\n        Name: SummaryPeriod\n        Type: Date\n")
    d = _lint(text, "SupplySummary.yaml")
    assert len(d) == 1 and "'QueryParameters'" in d[0].message
    fixed = text[:d[0].fix.start] + d[0].fix.new + text[d[0].fix.end:]
    assert "\nQueryParameters:\n" in fixed and _lint(fixed, "SupplySummary.yaml") == []
