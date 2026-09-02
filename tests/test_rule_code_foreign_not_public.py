"""code/foreign-not-public: a module reaches a non-public element of another subsystem.

The code side of yaml/foreign-not-public. The compiler refuses such a reference at the
position of the name (`Тип "..." недоступен из-за модификатора видимости @ВПодсистеме`); the
live case was the project module - it belongs to no subsystem - calling a common module of a
subsystem that had been left at the default visibility, and the refusal arrived from the
server compilation. Before this rule nothing in the linter judged the code side: the yaml side
was covered by yaml/foreign-not-public, and code/missing-import deliberately leaves a
non-public target alone.

The mapper parses the module, so the tests that lint code carry `needs_data` (the lexer needs
language.json); the registration check runs in every checkout.
"""

import pytest

from xbsl import engine, i18n
from xbsl.diagnostics import Severity

RULE = "code/foreign-not-public"

SUB_A = "Использование:\n    - Б\n"
SUB_B = "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n"
# Subsystem Б: a common module at the explicit default and a catalog with the property absent.
DEADLINES_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: СрокиЗадач\nОбластьВидимости: ВПодсистеме\n"
DEADLINES_XBSL = "@ВПроекте\nметод БлижайшийСрок(): Дата?\n    возврат Неопределено\n;\n"
TASKS_YAML = "ВидЭлемента: Справочник\nИмя: Задачи\n"
# Subsystem А: a module that names the catalog in a type position and calls the module.
SUMMARY_YAML = "ВидЭлемента: ОбщийМодуль\nИмя: СводкаЗадач\nОбластьВидимости: ВПроекте\n"
SUMMARY_XBSL = (
    "импорт Б\n\n"
    "метод СрокСводки(Задача: Задачи.Ссылка): Дата?\n"
    "    возврат СрокиЗадач.БлижайшийСрок()\n;\n"
)
PROJECT_XBSL = "импорт Б\n\nметод ПересчетСроков()\n    СрокиЗадач.БлижайшийСрок()\n;\n"


def _lint(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


def _where(diags):
    """(path, line) of every finding, the path with forward slashes on any platform."""
    return [(d.path.replace("\\", "/"), d.line) for d in diags]


def _project(**extra):
    files = {
        "А/Подсистема.yaml": SUB_A,
        "Б/Подсистема.yaml": SUB_B,
        "Б/СрокиЗадач.yaml": DEADLINES_YAML,
        "Б/СрокиЗадач.xbsl": DEADLINES_XBSL,
        "Б/Задачи.yaml": TASKS_YAML,
        "А/СводкаЗадач.yaml": SUMMARY_YAML,
        "А/СводкаЗадач.xbsl": SUMMARY_XBSL,
    }
    files.update(extra)
    return files


def test_rule_registered_project_scope_error():
    info = next(r for r in engine.active_rules() if r.id == RULE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default
    assert info.severity is Severity.ERROR


@pytest.mark.needs_data  # the mapper parses the module: the lexer needs language.json
def test_a_type_position_and_a_call_across_the_boundary_are_reported():
    diags = _lint(_project())
    assert _where(diags) == [("А/СводкаЗадач.xbsl", 3), ("А/СводкаЗадач.xbsl", 4)]
    assert {d.rule_id for d in diags} == {RULE}
    by_type, by_call = diags
    assert "Задачи.Ссылка" in by_type.message and "'Б'" in by_type.message
    assert "'А'" in by_type.message and by_type.severity is Severity.ERROR
    # The property absent from the catalog yaml is the platform default, and is named as such.
    assert "ВПодсистеме" in by_type.message
    assert "СрокиЗадач.БлижайшийСрок" in by_call.message and by_call.col == 13


@pytest.mark.needs_data
def test_the_project_module_outside_any_subsystem_is_judged():
    """The live case: the project module belongs to no subsystem, so a non-public element of
    any subsystem is foreign to it - and code/missing-import stands down exactly there."""
    diags = _lint(_project(**{"Проект.yaml": "Имя: Tasks\n", "Проект.xbsl": PROJECT_XBSL}))
    root = [d for d in diags if d.path.endswith("Проект.xbsl")]
    assert [(d.line, d.col) for d in root] == [(4, 5)]
    assert "СрокиЗадач.БлижайшийСрок" in root[0].message and "вне подсистем" in root[0].message
    assert "ВПодсистеме" in root[0].message


@pytest.mark.needs_data
def test_a_public_target_is_left_to_the_import_rules():
    public_module = DEADLINES_YAML.replace("ВПодсистеме", "ВПроекте")
    public_catalog = TASKS_YAML + "ОбластьВидимости: Глобально\n"
    files = _project(**{"Б/СрокиЗадач.yaml": public_module, "Б/Задачи.yaml": public_catalog})
    assert _lint(files) == []
    # Without the import line the reference is still not this rule's case.
    files["А/СводкаЗадач.xbsl"] = SUMMARY_XBSL.replace("импорт Б\n\n", "")
    assert _lint(files) == []


@pytest.mark.needs_data
def test_the_method_annotation_does_not_open_the_module():
    """A method marked `@ВПроекте` inside a module whose element is `InSubsystem` stays
    unreachable - the visibility of the element is judged first, so the rule does not read
    the annotations at all."""
    diags = _lint(_project(**{
        "Б/СрокиЗадач.xbsl": "@Глобально\nметод БлижайшийСрок(): Дата?\n    возврат Неопределено\n;\n",
    }))
    assert len(diags) == 2


@pytest.mark.needs_data
def test_a_reference_inside_the_own_subsystem_is_silent():
    files = _project()
    files["Б/СводкаЗадач.yaml"] = files.pop("А/СводкаЗадач.yaml")
    files["Б/СводкаЗадач.xbsl"] = files.pop("А/СводкаЗадач.xbsl").replace("импорт Б\n\n", "")
    assert _lint(files) == []


@pytest.mark.needs_data
def test_a_namesake_in_the_own_subsystem_resolves_locally():
    files = _project(**{"А/Задачи.yaml": TASKS_YAML})
    assert [d.line for d in _lint(files)] == [4]  # only the call is left


@pytest.mark.needs_data
def test_a_public_owner_anywhere_silences_the_name():
    files = _project(**{
        "В/Подсистема.yaml": SUB_B,
        "В/Задачи.yaml": TASKS_YAML + "ОбластьВидимости: ВПроекте\n",
    })
    assert [d.line for d in _lint(files)] == [4]


@pytest.mark.needs_data
@pytest.mark.needs_data
def test_a_qualified_name_is_judged_by_the_subsystem_it_names():
    """`Б::Задачи.Ссылка` in a type position and `Б::СрокиЗадач.БлижайшийСрок()` as a call:
    the form needs no import, but a server build refuses both when the element is not
    public (probe of 02.09.2026, the same message at the position of the name)."""
    qualified = SUMMARY_XBSL.replace("Задачи.Ссылка", "Б::Задачи.Ссылка").replace(
        "СрокиЗадач.БлижайшийСрок", "Б::СрокиЗадач.БлижайшийСрок"
    )
    diags = _lint(_project(**{"А/СводкаЗадач.xbsl": qualified}))
    assert sorted(d.line for d in diags) == [3, 4]
    assert any("Б::Задачи" in d.message for d in diags)
    assert any("Б::СрокиЗадач" in d.message for d in diags)
    # Public targets: the qualified form is as clean as the plain one.
    public = _project(**{
        "А/СводкаЗадач.xbsl": qualified,
        "Б/СрокиЗадач.yaml": DEADLINES_YAML.replace("ВПодсистеме", "ВПроекте"),
        "Б/Задачи.yaml": TASKS_YAML + "ОбластьВидимости: ВПроекте\n",
    })
    assert _lint(public) == []


@pytest.mark.needs_data
def test_names_the_module_explains_are_not_references():
    # A parameter named like the foreign module, and a local structure named like the catalog.
    module = (
        "структура Задачи\n    пер Срок: Дата?\n;\n\n"
        "метод СрокСводки(СрокиЗадач: Задачи): Дата?\n"
        "    возврат СрокиЗадач.Срок\n;\n"
    )
    assert _lint(_project(**{"А/СводкаЗадач.xbsl": module})) == []


@pytest.mark.needs_data
def test_a_section_of_the_paired_yaml_is_not_a_reference():
    # A top-level section of the paired yaml is handed to the module by name (a scheduled job
    # reads its parameters that way); a foreign element named like the section must not turn
    # the read into a report.
    files = _project(**{
        "Б/Настройки.yaml": "ВидЭлемента: Справочник\nИмя: Настройки\n",
        "А/СводкаЗадач.yaml": SUMMARY_YAML + "Настройки:\n    -\n        Имя: ГлубинаСводки\n",
        "А/СводкаЗадач.xbsl": "метод Выполнить()\n    пер П = Настройки.ГлубинаСводки\n;\n",
    })
    assert _lint(files) == []


@pytest.mark.needs_data
def test_an_unplaced_namesake_shields_a_module_outside_the_subsystems():
    files = _project(**{
        "Проект.yaml": "Имя: Tasks\n",
        "Проект.xbsl": PROJECT_XBSL,
        "СрокиЗадач.yaml": DEADLINES_YAML,  # an element outside every subsystem
    })
    assert _where(_lint(files)) == [("А/СводкаЗадач.xbsl", 3), ("А/СводкаЗадач.xbsl", 4)]


@pytest.mark.needs_data
def test_two_references_to_one_target_are_one_diagnostic():
    module = SUMMARY_XBSL + "\nметод Другой(): Дата?\n    возврат СрокиЗадач.БлижайшийСрок()\n;\n"
    diags = _lint(_project(**{"А/СводкаЗадач.xbsl": module}))
    assert [d.line for d in diags] == [3, 4]


@pytest.mark.needs_data
def test_without_subsystem_files_the_rule_stands_down():
    files = {k: v for k, v in _project().items() if not k.endswith("Подсистема.yaml")}
    assert _lint(files) == []


@pytest.mark.needs_data
def test_the_english_spelling_of_the_scope_is_read():
    english = "ElementKind: CommonModule\nName: СрокиЗадач\nVisibilityScope: InProject\n"
    assert [d.line for d in _lint(_project(**{"Б/СрокиЗадач.yaml": english}))] == [3]
    english = english.replace("InProject", "InSubsystem")
    diags = _lint(_project(**{"Б/СрокиЗадач.yaml": english}))
    assert [d.line for d in diags] == [3, 4] and "InSubsystem" in diags[1].message


@pytest.mark.needs_data
def test_the_english_message_names_the_scope_in_english():
    i18n.set_lang("en")
    try:
        diags = _lint(_project())
    finally:
        i18n.set_lang("ru")
    assert "VisibilityScope: InSubsystem" in diags[0].message
    assert "VisibilityScope: InProject" in diags[0].message
