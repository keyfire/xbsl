"""code/unknown-form-component: a form module reaching a name its markup does not declare.

The compiler is the only thing that sees this today, and it answers
`Unknown property "<Form>.Компоненты.<Name>"` at the apply, after the deploy. Three forms were
compiled on a throwaway application to settle what the root reaches: a NESTED component name
and the name of the group itself both compile, an invented one is refused.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "code/unknown-form-component"

# The rule reads the term dictionary (both spellings of the name key), so without the platform
# data it cannot answer - in a public clone these must SKIP rather than fail.
pytestmark = pytest.mark.needs_data

_MARKUP = """ВидЭлемента: КомпонентИнтерфейса
Имя: Форма
Наследует:
    Тип: Форма
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Имя: ГруппаВерхняя
            Содержимое:
                -
                    Тип: Надпись
                    Имя: ПодписьВнутри
"""


def _has(diags):
    return [d for d in diags if d.rule_id == RULE]


def _form(tmp_path, module, markup=_MARKUP, name="Форма"):
    (tmp_path / f"{name}.yaml").write_text(markup, encoding="utf-8")
    (tmp_path / f"{name}.xbsl").write_text(module, encoding="utf-8")
    return engine.run(discover([str(tmp_path)]), select={RULE})


def test_a_name_the_markup_does_not_declare_is_found(tmp_path):
    d = _has(_form(tmp_path, "@НаКлиенте\nметод Ф()\n    Компоненты.НетТакого.Видимость = Ложь\n;\n"))
    assert len(d) == 1
    assert "НетТакого" in d[0].message and "Форма" in d[0].message


def test_a_nested_name_is_reachable(tmp_path):
    """The probe says so: a component inside a group answers to the root."""
    d = _has(_form(tmp_path, "@НаКлиенте\nметод Ф()\n    Компоненты.ПодписьВнутри.Видимость = Ложь\n;\n"))
    assert d == []


def test_the_name_of_the_group_itself_is_reachable(tmp_path):
    d = _has(_form(tmp_path, "@НаКлиенте\nметод Ф()\n    Компоненты.ГруппаВерхняя.Видимость = Ложь\n;\n"))
    assert d == []


def test_only_the_first_name_after_the_root_is_judged(tmp_path):
    """`Компоненты.Карточка.Компоненты.Поле`: the second name lives in another file."""
    module = ("@НаКлиенте\nметод Ф()\n"
              "    Компоненты.ПодписьВнутри.Компоненты.ЧужоеПоле.Видимость = Ложь\n;\n")
    assert _has(_form(tmp_path, module)) == []


def test_a_shadowed_root_silences_the_file(tmp_path):
    """A local named like the root means the accesses are not the form's own."""
    module = ("@НаКлиенте\nметод Ф()\n    знч Компоненты = Список()\n"
              "    Компоненты.НетТакого.Видимость = Ложь\n;\n")
    assert _has(_form(tmp_path, module)) == []


def test_a_module_without_a_markup_pair_is_silent(tmp_path):
    (tmp_path / "Модуль.xbsl").write_text(
        "@НаКлиенте\nметод Ф()\n    Компоненты.НетТакого.Видимость = Ложь\n;\n",
        encoding="utf-8")
    assert _has(engine.run(discover([str(tmp_path)]), select={RULE})) == []


def test_a_pair_that_is_not_an_interface_component_is_silent(tmp_path):
    markup = "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: Клиент\n"
    assert _has(_form(tmp_path, "@НаКлиенте\nметод Ф()\n    Компоненты.НетТакого.X = 1\n;\n",
                      markup=markup, name="Модуль")) == []


def test_a_broken_markup_is_left_to_the_checks_that_judge_syntax(tmp_path):
    markup = "ВидЭлемента: КомпонентИнтерфейса\nИмя: [оборванный\n"
    assert _has(_form(tmp_path, "@НаКлиенте\nметод Ф()\n    Компоненты.НетТакого.X = 1\n;\n",
                      markup=markup)) == []


def test_the_english_spelling_of_the_root_is_judged_too(tmp_path):
    markup = ("ElementKind: InterfaceComponent\nName: Form\nInherits:\n    Type: Form\n"
              "    Content:\n        Type: CustomFormTemplate\n        Content:\n"
              "            Type: Group\n            Name: TopGroup\n")
    d = _has(_form(tmp_path, "@OnClient\nmethod F()\n    Components.NoSuchOne.Visible = False\n;\n",
                   markup=markup, name="Form"))
    assert len(d) == 1


def test_every_unknown_access_is_reported(tmp_path):
    module = ("@НаКлиенте\nметод Ф()\n"
              "    Компоненты.ПервыйНет.Видимость = Ложь\n"
              "    Компоненты.ВторойНет.Видимость = Ложь\n"
              "    Компоненты.ПодписьВнутри.Видимость = Истина\n;\n")
    d = _has(_form(tmp_path, module))
    assert sorted(x.line for x in d) == [3, 4]
