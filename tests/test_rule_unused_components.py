"""Checks of the yaml/unused-component rule (a dead interface component, tier A, project).

The rule reads the element kind and the property names through the metamodel and the term
pairs, so without the Element data the whole module is skipped (conftest does not know this
file, so we guard ourselves).
"""

import re

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "yaml/unused-component"

COMPONENT = "ВидЭлемента: КомпонентИнтерфейса\nИмя: {name}\n"
#: The rule judges nothing until the run proves it covers a project, so every fixture carries
#: the descriptor; the case that checks the gate itself writes its files without one.
PROJECT = "Поставщик: acme\nИмя: demo\nВерсия: 1.0.0\n"


def _diags(tmp_path, files: dict[str, str]):
    for name, content in {"Проект.yaml": PROJECT, **files}.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)])) if d.rule_id == RULE]


def _flagged(tmp_path, files: dict[str, str]) -> set[str]:
    """The names the rule reports over a throwaway project.

    A set of names rather than the diagnostics themselves: a fixture usually carries a second
    component of its own - the one that PLACES the component under test - and that second one
    is dead in its turn, true but not what the case is about.
    """
    return {
        m.group(1)
        for d in _diags(tmp_path, files)
        for m in [re.search(r"'([^']+)'", d.message)]
        if m
    }


# --- The signal ---------------------------------------------------------------------------

def test_component_nobody_places_is_flagged(tmp_path):
    names = _flagged(tmp_path, {
        "Одинокий.yaml": COMPONENT.format(name="Одинокий"),
        "Страница.yaml": COMPONENT.format(name="Страница") + "Наследует:\n    Тип: Группа\n",
    })
    assert "Одинокий" in names


def test_position_points_at_the_name(tmp_path):
    diags = _diags(tmp_path, {"Одинокий.yaml": COMPONENT.format(name="Одинокий")})
    assert (diags[0].line, diags[0].col) == (2, 6)


def test_rule_is_on_without_select(tmp_path):
    """Unlike code/unused-method, the rule belongs to the default set."""
    (tmp_path / "Одинокий.yaml").write_text(COMPONENT.format(name="Одинокий"), encoding="utf-8")
    (tmp_path / "Проект.yaml").write_text(PROJECT, encoding="utf-8")
    assert [d for d in engine.run(discover([str(tmp_path)])) if d.rule_id == RULE]


def test_a_run_without_the_project_descriptor_is_silent(tmp_path):
    """A single file, a directory or an editor buffer is not a project: a component placed
    outside the linted set would be reported as dead."""
    (tmp_path / "Одинокий.yaml").write_text(COMPONENT.format(name="Одинокий"), encoding="utf-8")
    assert not [d for d in engine.run(discover([str(tmp_path)])) if d.rule_id == RULE]


# --- Uses that silence it -----------------------------------------------------------------

def test_placed_by_type_in_another_yaml(tmp_path):
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Страница.yaml": COMPONENT.format(name="Страница")
        + "Наследует:\n    Тип: Группа\n    Содержимое:\n        -\n            Тип: Карточка\n",
    })
    assert "Карточка" not in names


def test_placed_as_a_generic_argument(tmp_path):
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Список.yaml": COMPONENT.format(name="Список") + "Наследует:\n    Тип: Обёртка<Карточка>\n",
    })
    assert "Карточка" not in names


def test_created_by_code(tmp_path):
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Страница.yaml": COMPONENT.format(name="Страница"),
        "Страница.xbsl": "метод Построить()\n    пер Узел = новый Карточка()\n;\n",
    })
    assert "Карточка" not in names


def test_mentioned_in_a_module_comment(tmp_path):
    """Lax on purpose: a component may be created by name from a string of an HTML bridge."""
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Страница.yaml": COMPONENT.format(name="Страница"),
        "Страница.xbsl": "// разметку рисует Карточка\nметод Построить()\n;\n",
    })
    assert "Карточка" not in names


# --- Mentions that do NOT count -----------------------------------------------------------

def test_name_as_a_dictionary_key_is_not_a_use(tmp_path):
    """A localization or a translation dictionary writes every name as a KEY."""
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Словарь.yaml": "Карточка: Card\n",
    })
    assert "Карточка" in names


def test_name_in_a_yaml_comment_is_not_a_use(tmp_path):
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Страница.yaml": COMPONENT.format(name="Страница") + "# рядом с Карточка, но не размещена\n",
    })
    assert "Карточка" in names


def test_own_pair_does_not_count_as_a_use(tmp_path):
    names = _flagged(tmp_path, {
        "Карточка.yaml": COMPONENT.format(name="Карточка"),
        "Карточка.xbsl": "// Карточка строит себя сама\nметод Построить()\n;\n",
    })
    assert names == {"Карточка"}


# --- Guards --------------------------------------------------------------------------------

def test_client_application_is_an_entry_point(tmp_path):
    names = _flagged(tmp_path, {
        "Кабинет.yaml": COMPONENT.format(name="Кабинет")
        + "Наследует:\n    Тип: ПроизвольноеКлиентскоеПриложение\n    Путь: cabinet\n",
    })
    assert not names


def test_globally_visible_component_is_a_library_surface(tmp_path):
    names = _flagged(tmp_path, {
        "Кнопка.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: Кнопка\nОбластьВидимости: Глобально\n",
    })
    assert not names


def test_lower_case_name_is_left_alone(tmp_path):
    """The mention search keeps capitalized words only, so such a name is judged blindly."""
    names = _flagged(tmp_path, {
        "карточка.yaml": "ВидЭлемента: КомпонентИнтерфейса\nИмя: карточка\n",
    })
    assert not names


def test_an_object_is_not_a_component(tmp_path):
    names = _flagged(tmp_path, {"Программы.yaml": "ВидЭлемента: Справочник\nИмя: Программы\n"})
    assert not names


# --- The English spelling of the same sources ----------------------------------------------

def test_english_component_is_judged_too(tmp_path):
    names = _flagged(tmp_path, {"Card.yaml": "ElementKind: InterfaceComponent\nName: Card\n"})
    assert names == {"Card"}


def test_english_placement_silences_it(tmp_path):
    names = _flagged(tmp_path, {
        "Card.yaml": "ElementKind: InterfaceComponent\nName: Card\n",
        "Page.yaml": "ElementKind: InterfaceComponent\nName: Page\n"
        + "Inherits:\n    Type: Group\n    Content:\n        -\n            Type: Card\n",
    })
    assert "Card" not in names
