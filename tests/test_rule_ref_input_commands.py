"""Checks of yaml/ref-input-auto-commands: a reference input that leaves its commands to the
platform, which then draws its own "open the value" button next to the field."""

import pytest

from xbsl import engine

RULE = "yaml/ref-input-auto-commands"

HEAD = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\nНаследует:\n    Тип: Форма\n    Содержимое:\n"


def _lint(body: str):
    text = HEAD + body
    return [d for d in engine.run_sources([engine.load_text("Форма.yaml", text)], select={RULE})
            if d.rule_id == RULE]


def test_a_reference_input_without_commands_is_reported():
    d = _lint("        -\n            Тип: ПолеВвода<Товары.Ссылка?>\n")
    assert len(d) == 1 and "Товары.Ссылка?" in d[0].message


def test_an_explicit_fragment_silences_the_rule():
    d = _lint(
        "        -\n            Тип: ПолеВвода<Товары.Ссылка?>\n"
        "            Команды:\n                Тип: ФрагментКомандногоИнтерфейса\n"
    )
    assert d == [], [x.message for x in d]


def test_a_value_input_is_not_judged():
    d = _lint("        -\n            Тип: ПолеВвода<Строка>\n")
    assert d == []


def test_a_union_carrying_a_reference_is_reported():
    d = _lint("        -\n            Тип: ПолеВвода<Товары.Ссылка|Услуги.Ссылка|?>\n")
    assert len(d) == 1


@pytest.mark.needs_data
def test_the_english_spelling_is_read_the_same_way():
    # The facet spelling comes from the platform dictionary: the serializer writes
    # `Reference`, and the hand-written `Ref` this test used to encode matched nothing.
    text = (
        "ElementKind: InterfaceComponent\nName: Форма\nInherits:\n    Type: Form\n    Content:\n"
        "        -\n            Type: Edit<Товары.Reference?>\n"
    )
    d = [x for x in engine.run_sources([engine.load_text("Форма.yaml", text)], select={RULE})
         if x.rule_id == RULE]
    assert len(d) == 1


def test_another_component_is_not_judged():
    d = _lint("        -\n            Тип: Надпись\n            Значение: Товары.Ссылка\n")
    assert d == []
