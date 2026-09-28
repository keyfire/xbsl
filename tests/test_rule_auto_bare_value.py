"""yaml/auto-bare-value: a bare Auto in a property whose type is the union of Auto and a string.

A live apply refused four such properties with "Не указан тип значения": the caption of a
button (a component property of the ui schema), and three members of a dynamic list - the
presentation of a filter group, of a filter item and the ascending sort presentation of a
field's automatic filter. The rule types the markup through the ui schema and the type
catalog, so every test needs the data.
"""

import pytest

from xbsl import engine

pytestmark = pytest.mark.needs_data

RULE = "yaml/auto-bare-value"
HIERARCHY = "yaml/hierarchy-bare-value"


def _form(content: str, name: str = "ФормаПробы") -> str:
    """A form whose template holds `content` (indented as the template's own content)."""
    body = "".join("            " + line + "\n" for line in content.splitlines())
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 0d0d0d0d-1111-2222-3333-444444444444\n"
        f"Имя: {name}\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n"
        "        Тип: ПроизвольныйШаблонФормы\n"
        "        Содержимое:\n" + body
    )


def _lint(text: str, rules=(RULE,), name: str = "ФормаПробы.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select=set(rules))


_BUTTON = "Тип: Кнопка\nИмя: КнопкаПробы\nЗаголовок: {value}\n"
_LIST = (
    "Тип: Таблица<ДинамическийСписок>\n"
    "Имя: ТаблицаПробы\n"
    "Источник:\n"
    "    ОсновнаяТаблица:\n"
    "        Таблица: Товары\n"
)


def test_button_caption():
    diags = _lint(_form(_BUTTON.format(value="Авто")))
    assert [d.rule_id for d in diags] == [RULE]
    assert "Заголовок (Кнопка)" in diags[0].message
    assert "Не указан тип значения" in diags[0].message


@pytest.mark.parametrize("value", ['"Авто"', "Сохранить", "=ЗаголовокКнопки()"])
def test_button_caption_as_text_or_binding_is_silent(value):
    # The negative control: a quoted word and any other word are text, a binding is a binding.
    assert _lint(_form(_BUTTON.format(value=value))) == []


def test_auto_in_a_union_without_a_string_is_silent():
    # `Видимость` takes Auto or a boolean - the bare word is the Auto the union names.
    assert _lint(_form("Тип: Кнопка\nИмя: КнопкаПробы\nВидимость: Авто\n")) == []


@pytest.mark.parametrize("tail, line_of", [
    ("    Фильтр:\n        Представление: Авто\n", "        Представление: Авто"),
    ("    Фильтр:\n        Элементы:\n            -\n"
     "                Тип: ЭлементФильтраВыражение\n"
     "                Выражение: Товары.Наименование != \"\"\n"
     "                Представление: Авто\n", "                Представление: Авто"),
    ("    Поля:\n        -\n            Тип: ПолеДинамическогоСписка\n"
     "            Выражение: Товары.Наименование\n"
     "            НастройкиАвтоматическогоФильтра:\n"
     "                ПредставлениеСортировкиПоВозрастанию: Авто\n",
     "                ПредставлениеСортировкиПоВозрастанию: Авто"),
])
def test_dynamic_list_members(tail, line_of):
    text = _form(_LIST + tail)
    diags = _lint(text)
    assert [d.rule_id for d in diags] == [RULE]
    lines = text.splitlines()
    assert lines[diags[0].line - 1].endswith(line_of.strip())


def test_the_list_field_presentation_is_a_plain_string():
    # `ПолеДинамическогоСписка.Представление` is a string alone: a bare word is its text.
    tail = ("    Поля:\n        -\n            Тип: ПолеДинамическогоСписка\n"
            "            Выражение: Товары.Наименование\n            Представление: Авто\n")
    assert _lint(_form(_LIST + tail)) == []


def test_a_list_declared_in_a_property_default_is_walked():
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 0d0d0d0d-1111-2222-3333-444444444445\n"
        "Имя: ФормаСписка\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Список\n"
        "        Тип: ДинамическийСписок<ФормаСписка.СтрокаСписка>\n"
        "        ЗначениеПоУмолчанию:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Товары\n"
        "            Фильтр:\n"
        "                Представление: Авто\n"
    )
    assert [d.rule_id for d in _lint(text, name="ФормаСписка.yaml")] == [RULE]


def test_the_hierarchy_stays_with_its_own_rule():
    text = _form(_LIST + "    ИспользуемаяИерархия: Авто\n")
    assert [d.rule_id for d in _lint(text, rules=(RULE, HIERARCHY))] == [HIERARCHY]


def test_a_project_component_is_not_judged():
    # A component of the project: its own properties are nothing the schema can type.
    text = _form("Тип: КарточкаТовара\nЗаголовок: Авто\n")
    assert _lint(text) == []


def test_english_file():
    text = (
        "ElementKind: InterfaceComponent\n"
        "Id: 0d0d0d0d-1111-2222-3333-444444444446\n"
        "Name: TrialForm\n"
        "Inherits:\n"
        "    Type: Form\n"
        "    Content:\n"
        "        Type: CustomFormTemplate\n"
        "        Content:\n"
        "            Type: Button\n"
        "            Name: TrialButton\n"
        "            Title: Auto\n"
    )
    assert [d.rule_id for d in _lint(text, name="TrialForm.yaml")] == [RULE]
