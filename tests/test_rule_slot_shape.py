"""yaml/slot-needs-list: a slot typed as a list, holding a single component.

The shape is settled by the ui schema, not by the property name: `Content` is a list on a
group and a single component on a form template, and both spellings of a key reach the same
record through the property dictionary.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/slot-needs-list"

# The rule reads the ui schema, so without the platform data it cannot answer - in a public
# clone these must SKIP rather than fail.
pytestmark = pytest.mark.needs_data

_HEAD = """ВидЭлемента: КомпонентИнтерфейса
Имя: Форма
Наследует:
    Тип: Форма
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
"""


def _run(tmp_path, markup, name="Форма"):
    (tmp_path / f"{name}.yaml").write_text(markup, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def test_one_component_under_a_list_slot_is_found(tmp_path):
    markup = _HEAD + """            Тип: Группа
            Имя: ГруппаВерхняя
            Содержимое:
                Тип: Надпись
                Имя: Подпись
"""
    found = _run(tmp_path, markup)
    assert len(found) == 1
    assert "Содержимое" in found[0].message and "Группа" in found[0].message


def test_a_list_is_silence(tmp_path):
    markup = _HEAD + """            Тип: Группа
            Имя: ГруппаВерхняя
            Содержимое:
                -
                    Тип: Надпись
                    Имя: Подпись
"""
    assert _run(tmp_path, markup) == []


def test_a_single_valued_slot_takes_one_component(tmp_path):
    """The template's own `Content` is typed with one component - the head above uses it."""
    markup = _HEAD + """            Тип: Группа
            Имя: ГруппаВерхняя
            Содержимое: []
"""
    assert _run(tmp_path, markup) == []


def test_the_english_spelling_is_judged_too(tmp_path):
    markup = """ElementKind: InterfaceComponent
Name: Form
Inherits:
    Type: Form
    Content:
        Type: CustomFormTemplate
        Content:
            Type: Group
            Name: TopGroup
            Content:
                Type: Label
                Name: Caption
"""
    assert len(_run(tmp_path, markup, name="Form")) == 1


def test_a_project_component_is_left_alone(tmp_path):
    """Its slots are its own business - the palette schema cannot know them."""
    markup = _HEAD + """            Тип: КарточкаЗадачи
            Имя: Карточка
            Содержимое:
                Тип: Надпись
                Имя: Подпись
"""
    assert _run(tmp_path, markup) == []


def test_a_scalar_is_left_alone(tmp_path):
    markup = _HEAD + """            Тип: Группа
            Имя: ГруппаВерхняя
            Содержимое: ГруппаИзДругогоФайла
"""
    assert _run(tmp_path, markup) == []


def test_markup_outside_inherits_is_not_judged(tmp_path):
    """A `Type` outside the markup names a type, and its neighbours are not properties."""
    markup = """ВидЭлемента: Справочник
Имя: Задачи
Реквизиты:
    -
        Имя: Группа
        Тип: Группа
        Содержимое:
            Тип: Надпись
"""
    assert _run(tmp_path, markup, name="Задачи") == []


def test_a_broken_yaml_is_left_to_the_checks_that_judge_syntax(tmp_path):
    assert _run(tmp_path, "ВидЭлемента: КомпонентИнтерфейса\nИмя: [оборванный\n") == []


def test_a_list_slot_other_than_content_is_judged(tmp_path):
    """The rule follows the schema, so a slot of another name is judged the same way."""
    markup = _HEAD + """            Тип: Страницы
            Имя: Разделы
            Страницы:
                Тип: Страница
                Имя: Первая
"""
    found = _run(tmp_path, markup)
    assert len(found) == 1
    assert "Страницы" in found[0].message
