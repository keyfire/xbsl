"""yaml/localization-key-unique: a name a localization dictionary declares twice.

The reach is not a guess - the compiler answered it on a throwaway project of three
dictionaries in one run: a name repeated inside a section, the same name in `Strings` and
in `Templates`, and a repeat inside a translation file were all refused, each on its own
line ('Name "X" is not unique').

The rule needs no Element data for the Russian spellings, so the tests live outside
test_rules (that module is skipped whole in a data-less checkout) and run in the public
CI; the one test that exercises the English spellings is marked as needing the data.
"""

import pytest

from xbsl import engine

RULE = "yaml/localization-key-unique"

_HEAD = (
    "ВидЭлемента: ЛокализованныеСтроки\n"
    "Ид: 11111111-1111-1111-1111-111111111111\n"
    "Имя: Словарь\n"
)


def _lint(name, content):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _dictionary(body: str):
    return _lint("Словарь.yaml", _HEAD + body)


def test_key_repeated_inside_one_section():
    # The compiler on this shape: 'Name "Сохранить" is not unique'.
    d = _dictionary(
        "Строки:\n"
        "    Сохранить: Сохранить\n"
        "    Отменить: Отменить\n"
        "    Сохранить: Записать\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (7, 5)
    assert "'Сохранить'" in d[0].message and "строка 5" in d[0].message


def test_key_in_both_sections_is_one_namespace():
    # The two sections compile into one type, and the compiler refuses the repeat the
    # same way it refuses one inside a section.
    d = _dictionary(
        "Строки:\n"
        "    Общий: Общая строка\n"
        "Шаблоны:\n"
        "    Общий: \"Общая строка $0\"\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (7, 5)
    assert "Строки" in d[0].message and "Шаблоны" in d[0].message


def test_translation_file_without_a_head_is_judged():
    # A translation carries no element kind - it is recognised by shape, section names alone.
    d = _lint(
        "Локализация/En/Словарь.yaml",
        "Строки:\n"
        "    Заголовок: Title\n"
        "    Подпись: Caption\n"
        "    Заголовок: Heading\n",
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (4, 5)


def test_unique_keys_are_silent():
    d = _dictionary(
        "Строки:\n"
        "    Сохранить: Сохранить\n"
        "    Отменить: Отменить\n"
        "Шаблоны:\n"
        "    Осталось: \"Осталось $0\"\n"
    )
    assert d == [], [x.message for x in d]


def test_a_repeat_outside_a_dictionary_is_not_judged():
    # The narrowing: the rule speaks about the dictionary namespace, not about yaml at
    # large. A catalog repeating a key is a different defect with a different message.
    d = _lint(
        "Справочник.yaml",
        "ВидЭлемента: Справочник\n"
        "Ид: 22222222-2222-2222-2222-222222222222\n"
        "Имя: Справочник\n"
        "Представление: Наименование\n"
        "Представление: Наименование\n",
    )
    assert d == [], [x.message for x in d]


def test_three_repeats_report_each_one_past_the_first():
    d = _dictionary(
        "Строки:\n"
        "    Ключ: Раз\n"
        "    Ключ: Два\n"
        "    Ключ: Три\n"
    )
    assert len(d) == 2, [x.message for x in d]
    assert [x.line for x in d] == [6, 7]


@pytest.mark.needs_data
def test_english_spelling_of_the_sections():
    # The section names come from the metamodel record of the kind, so an English project
    # is judged by the same rule.
    d = _lint(
        "Dictionary.yaml",
        "ElementKind: LocalizedStrings\n"
        "Id: 33333333-3333-3333-3333-333333333333\n"
        "Name: Dictionary\n"
        "Strings:\n"
        "    Save: Save\n"
        "Templates:\n"
        "    Save: \"Save $0\"\n",
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (7, 5)
