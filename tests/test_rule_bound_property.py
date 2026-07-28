"""A computed property must not be assigned from code (code/bound-property-assign).

The pair the rule judges lives on disk - a form's components are declared in the yaml next
to the module - so every case here is written as a real file pair in a temporary folder.

The line that matters most is the negative one: a DATA BINDING (`Значение: =Запись.Значение`)
is a plain path into the form's data, the documentation calls such a link two-way for an
editable component, and writing to it is how an editor gives the value back. Only a
COMPUTED expression - a call, a ternary, arithmetic - is not assignable.
"""

from pathlib import Path

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
        height="Высота: =Общее.ЭтоМобильный()?820:528",
        code="метод Ф()\n    Компоненты.Вставка.Высота = 640\n;\n",
    )
    assert len(diags) == 1
    assert "Высота" in diags[0].message and "Вставка" in diags[0].message
    # Строка разметки названа: читатель идёт в yaml, а не ищет свойство глазами.
    assert "строка 13" in diags[0].message


def test_data_binding_assignment_is_not_flagged(tmp_path):
    """Связь с данными двунаправленная – так редактор и отдаёт значение обратно."""
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: 320",
        code="метод Ф(Источник: Флажок)\n    Компоненты.Значение.Значение = Источник.Значение\n;\n",
    )
    assert diags == []


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
        height="Высота: =Общее.ЭтоМобильный()?820:528",
        code="метод Ф()\n    если Компоненты.Вставка.Высота == 640\n        Метод1()\n    ;\n;\n",
    )
    assert diags == []


def test_assignment_through_an_event_source_is_left_alone(tmp_path):
    """Источник обработчика – это тот же компонент, но статически лишь параметр."""
    diags = _pair(
        tmp_path,
        value="Значение: =Запись.Значение",
        height="Высота: =Общее.ЭтоМобильный()?820:528",
        code="метод Ф(Источник: КонтейнерHtml)\n    Источник.Высота = 640\n;\n",
    )
    assert diags == []


def test_module_without_a_pair_is_silent(tmp_path):
    module = tmp_path / "Одинокий.xbsl"
    module.write_text("метод Ф()\n    Компоненты.Вставка.Высота = 640\n;\n", encoding="utf-8")
    assert engine.run([module], select={"code/bound-property-assign"}) == []
