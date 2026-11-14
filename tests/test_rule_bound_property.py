"""A computed property must not be assigned from code (code/bound-property-assign).

The pair the rule judges lives on disk - a form's components are declared in the yaml next
to the module - so every case here is written as a real file pair in a temporary folder.

The line that matters most is the negative one: a DATA BINDING (`Значение: =Запись.Значение`)
is a plain path into the form's data, the documentation calls such a link two-way for an
editable component, and writing to it is how an editor gives the value back. Only a
COMPUTED expression - a call, a ternary, arithmetic - is not assignable.
"""

from pathlib import Path

import pytest

from xbsl import engine

FORM_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6e2a2f0f-4a1d-4d2e-9b0f-2b5c7f2a1111
Имя: Форма
Содержимое:
  - ВидЭлемента: Группа
    Имя: Группа
    Содержимое:
      - ВидЭлемента: ПолеВвода
        Имя: Значение
        {value}
      - ВидЭлемента: КонтейнерHtml
        Имя: Вставка
        {height}
"""


def _pair(tmp_path: Path, *, value: str, height: str, code: str) -> list:
    module = tmp_path / "Форма.xbsl"
    (tmp_path / "Форма.yaml").write_text(
        FORM_YAML.format(value=value, height=height), encoding="utf-8"
    )
    module.write_text(code, encoding="utf-8")
    return engine.run([module], select={"code/bound-property-assign"})


def test_computed_property_assignment_flagged(tmp_path):
    """Ровно живой случай: высота вычисляется выражением, а код её присваивает."""
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: =Устройство.ЭтоТелефон()?820:528",
        code="метод Ф()\n    Компоненты.Вставка.Высота = 640\n;\n",
    )
    assert len(diags) == 1
    assert "Высота" in diags[0].message and "Вставка" in diags[0].message
    # Строка разметки названа: читатель идёт в yaml, а не ищет свойство глазами.
    assert "строка 13" in diags[0].message


def test_data_binding_assignment_is_not_flagged(tmp_path):
    """Связь с данными двунаправленная - так редактор и отдаёт значение обратно."""
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: 320",
        code="метод Ф(Источник: Флажок)\n    Компоненты.Значение.Значение = Источник.Значение\n;\n",
    )
    assert diags == []


def test_bare_path_in_a_setting_is_flagged(tmp_path):
    """A bare path in a SETTING is not a binding: the platform refuses the assignment.

    The live case: `Visibility: =Flag` and `Components.Table.Visibility = Flag` in the
    module. By the shape of the expression it is the same bare path as the lawful
    `Value` binding - what tells them apart is the property type in the schema, not
    the kind of expression.
    """
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Доступность: =ФлагДоступности",
        code="метод Ф(Флаг: Булево)\n    Компоненты.Вставка.Доступность = Флаг\n;\n",
    )
    assert len(diags) == 1
    assert "Доступность" in diags[0].message


def test_setting_of_a_plain_group_is_flagged(tmp_path):
    """A group with no type arguments: the property comes from the schema by its kind."""
    (tmp_path / "Форма.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 6e2a2f0f-4a1d-4d2e-9b0f-2b5c7f2a1111\n"
        "Имя: Форма\n"
        "Содержимое:\n"
        "  - ВидЭлемента: Группа\n"
        "    Имя: ГруппаФормы\n"
        "    Видимость: =Флаг\n",
        encoding="utf-8",
    )
    module = tmp_path / "Форма.xbsl"
    module.write_text(
        "метод Ф(Флаг: Булево)\n    Компоненты.ГруппаФормы.Видимость = Флаг\n;\n",
        encoding="utf-8",
    )
    diags = engine.run([module], select={"code/bound-property-assign"})
    assert len(diags) == 1 and "Видимость" in diags[0].message


def test_literal_property_assignment_is_not_flagged(tmp_path):
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: Авто",
        code="метод Ф()\n    Компоненты.Вставка.Высота = 640\n;\n",
    )
    assert diags == []


def test_comparison_is_not_an_assignment(tmp_path):
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: =Устройство.ЭтоТелефон()?820:528",
        code="метод Ф()\n    если Компоненты.Вставка.Высота == 640\n        Метод1()\n    ;\n;\n",
    )
    assert diags == []


def test_assignment_through_an_event_source_is_left_alone(tmp_path):
    """Источник обработчика - это тот же компонент, но статически лишь параметр."""
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: =Устройство.ЭтоТелефон()?820:528",
        code="метод Ф(Источник: КонтейнерHtml)\n    Источник.Высота = 640\n;\n",
    )
    assert diags == []


def test_module_without_a_pair_is_silent(tmp_path):
    module = tmp_path / "Одинокий.xbsl"
    module.write_text("метод Ф()\n    Компоненты.Вставка.Высота = 640\n;\n", encoding="utf-8")
    assert engine.run([module], select={"code/bound-property-assign"}) == []


@pytest.mark.needs_data
def test_english_pair_is_judged(tmp_path):
    """A translated pair: the markup key and the module member are one property.

    The markup keys are stored under the metamodel's own name, so a module writing the
    property in English used to match nothing at all.
    """
    (tmp_path / "Form.yaml").write_text(
        "ElementKind: InterfaceComponent\nName: Form\nContent:\n"
        "  - ElementKind: HtmlContainer\n    Name: Insert\n"
        "    Height: =Device.IsPhone()?820:528\n",
        encoding="utf-8",
    )
    module = tmp_path / "Form.xbsl"
    module.write_text("method F()\n    Components.Insert.Height = 640\n;\n", encoding="utf-8")
    diags = engine.run([module], select={"code/bound-property-assign"})
    assert len(diags) == 1 and "Height" in diags[0].message


@pytest.mark.parametrize(
    "name, kind, prop, expression, code",
    [
        ("Форма", "Кнопка", "Активность", "=Флаг",
         "метод Ф()\n    Компоненты.Переключатель.Активность = Истина\n;\n"),
        ("Form", "Button", "Active", "=Flag",
         "method F()\n    Components.Переключатель.Active = True\n;\n"),
        ("Форма", "ПолеВвода", "Значение", "=Значения[0]",
         "метод Ф()\n    Компоненты.Переключатель.Значение = 42\n;\n"),
    ],
)
def test_writable_binding_is_accepted_by_both_rules(tmp_path, name, kind, prop, expression, code):
    markup = tmp_path / f"{name}.yaml"
    module = tmp_path / f"{name}.xbsl"
    markup.write_text(
        f"ВидЭлемента: КомпонентИнтерфейса\nИмя: {name}\nСодержимое:\n"
        f"  - Тип: {kind}\n    Имя: Переключатель\n    {prop}: {expression}\n",
        encoding="utf-8",
    )
    module.write_text(code, encoding="utf-8")
    assert engine.run([markup, module], select={
        "code/bound-property-assign", "yaml/binding-needs-two-way",
    }) == []


def test_assignment_to_computed_data_property_is_reported(tmp_path):
    diags = _pair(
        tmp_path,
        value="Значение: =Вычислить()\n        ТолькоЧтение: Истина",
        height="Высота: 320",
        code="метод Ф()\n    Компоненты.Значение.Значение = 42\n;\n",
    )
    assert len(diags) == 1 and diags[0].rule_id == "code/bound-property-assign"


def test_assignment_to_unknown_property_with_a_data_path_is_left_alone(tmp_path):
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="СвойствоПользователя: =Запись.Значение",
        code="метод Ф()\n    Компоненты.Вставка.СвойствоПользователя = 42\n;\n",
    )
    assert diags == []
