"""A popup component placed in the yaml markup draws its content inline (yaml/popup-in-markup).

The platform draws a placed popup instance as a regular element: the window content shows
up right in the form flow before the window ever opens, there is no property restricting
the drawing to the window, and hiding the instance breaks the window itself. The rule flags
every placement - the raw type and a project component transitively inheriting it - while
the legitimate shapes stay silent: the definition of a derived popup (the root `Inherits`
mapping) and a property declaration referencing the component.

The rule is project-scoped (the inheritance closure needs every yaml), so the tests run the
engine over a temporary project directory. The Russian spelling needs no data bundle; the
English one folds through the ui schema and is marked accordingly.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/popup-in-markup"


def _lint(tmp_path, files: dict[str, str]):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return [
        d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE
    ]


_DERIVED = """ВидЭлемента: КомпонентИнтерфейса
Ид: 11111111-1111-1111-1111-111111111111
Имя: МояПодсказка
Наследует:
    Тип: ВсплывающийКомпонент
    ЗакрыватьПриНажатииСнаружи: Истина
    Содержимое:
        Тип: Надпись
        Заголовок: Текст подсказки
"""

_FORM = """ВидЭлемента: КомпонентИнтерфейса
Ид: 22222222-2222-2222-2222-222222222222
Имя: ФормаПробы
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Группа
        Содержимое:
            -
                Тип: {placed}
                Имя: Размещённый
"""


def test_a_raw_popup_placed_in_markup_is_reported(tmp_path):
    diags = _lint(tmp_path, {
        "ФормаПробы.yaml": _FORM.format(placed="ВсплывающийКомпонент"),
    })

    assert len(diags) == 1
    assert diags[0].line == 10
    assert "ОткрытьВоВсплывающемОкне" in diags[0].message


def test_a_component_deriving_the_popup_is_reported_transitively(tmp_path):
    """The placement of a project component inheriting the popup is the same trap."""
    diags = _lint(tmp_path, {
        "МояПодсказка.yaml": _DERIVED,
        "ФормаПробы.yaml": _FORM.format(placed="МояПодсказка"),
    })

    assert len(diags) == 1
    assert diags[0].path.endswith("ФормаПробы.yaml")
    assert "МояПодсказка" in diags[0].message


def test_a_second_level_derivation_is_still_reported(tmp_path):
    """The closure is transitive: a component inheriting a derived popup counts too."""
    second = """ВидЭлемента: КомпонентИнтерфейса
Ид: 33333333-3333-3333-3333-333333333333
Имя: ПодсказкаПоШире
Наследует:
    Тип: МояПодсказка
"""
    diags = _lint(tmp_path, {
        "МояПодсказка.yaml": _DERIVED,
        "ПодсказкаПоШире.yaml": second,
        "ФормаПробы.yaml": _FORM.format(placed="ПодсказкаПоШире"),
    })

    assert len(diags) == 1 and diags[0].path.endswith("ФормаПробы.yaml")


def test_the_definition_of_a_derived_popup_stays_silent(tmp_path):
    """The root `Наследует: Тип: ВсплывающийКомпонент` is the cure's own shape, not a placement."""
    diags = _lint(tmp_path, {"МояПодсказка.yaml": _DERIVED})

    assert diags == []


def test_a_property_declaration_is_a_reference_not_a_placement(tmp_path):
    """The live sources keep such a reference to close the popup on mouse-out - legal."""
    holder = """ВидЭлемента: КомпонентИнтерфейса
Ид: 44444444-4444-4444-4444-444444444444
Имя: ЗначокСоСсылкой
Наследует:
    Тип: Группа
Свойства:
    -
        Имя: ОткрытаяПодсказка
        Тип: МояПодсказка?
"""
    diags = _lint(tmp_path, {
        "МояПодсказка.yaml": _DERIVED,
        "ЗначокСоСсылкой.yaml": holder,
    })

    assert diags == []


def test_the_popup_menu_is_a_different_component(tmp_path):
    diags = _lint(tmp_path, {
        "ФормаПробы.yaml": _FORM.format(placed="ВсплывающееМеню"),
    })

    assert diags == []


def test_a_popup_inside_the_window_content_of_a_popup_is_reported(tmp_path):
    """Inside the WINDOW content of a derived popup's definition a placement renders inline
    just the same - only the definition's own root `Type` is exempt."""
    nested = """ВидЭлемента: КомпонентИнтерфейса
Ид: 55555555-5555-5555-5555-555555555555
Имя: ПодсказкаСВложением
Наследует:
    Тип: ВсплывающийКомпонент
    Содержимое:
        -
            Тип: ВсплывающийКомпонент
            Имя: Вложенный
"""
    diags = _lint(tmp_path, {"ПодсказкаСВложением.yaml": nested})

    assert len(diags) == 1 and diags[0].line == 8


@pytest.mark.needs_data
def test_the_english_spelling_is_the_same_component(tmp_path):
    """Sources may be written in English: the spelling folds through the ui schema."""
    derived = """ElementKind: InterfaceComponent
Id: 66666666-6666-6666-6666-666666666666
Name: BadgeHint
Inherits:
    Type: PopupComponent
"""
    form = """ElementKind: InterfaceComponent
Id: 77777777-7777-7777-7777-777777777777
Name: ProbeForm
Inherits:
    Type: Form
    Content:
        Type: Group
        Content:
            -
                Type: PopupComponent
                Name: InlinePopup
            -
                Type: BadgeHint
                Name: InlineHint
"""
    diags = _lint(tmp_path, {"BadgeHint.yaml": derived, "ProbeForm.yaml": form})

    assert len(diags) == 2
    assert all(d.path.endswith("ProbeForm.yaml") for d in diags)
