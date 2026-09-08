"""A component property named after a common module (yaml/property-shadows-module).

The property name takes over the whole component, so the module it repeats stops being
addressable there and every `Module.Method()` access turns into a member of the property
value - which the server refuses only when the build is applied. The rule joins the property
names of a component with the common module names of the project and reports the clash at the
declaration, in both spellings of the sources.

The narrowings are checked as carefully as the finding: a namesake that is not a common
module is a live idiom, and a module of a subsystem the component does not import was never
reachable by the bare name in the first place.

The rule reads the yaml keys through the metamodel, so the whole module needs the data bundle
(listed in conftest._DATA_DEPENDENT).
"""

from xbsl import engine
from xbsl.cli import discover

RULE = "yaml/property-shadows-module"

_MODULE = """ВидЭлемента: ОбщийМодуль
Ид: 11111111-1111-1111-1111-111111111111
Имя: РаботаСЗадачами
Окружение: Клиент
"""

_CATALOG = """ВидЭлемента: Справочник
Ид: 22222222-2222-2222-2222-222222222222
Имя: РаботаСЗадачами
"""

_COMPONENT = """ВидЭлемента: КомпонентИнтерфейса
Ид: 33333333-3333-3333-3333-333333333333
Имя: КарточкаЗадачи
{imports}Свойства:
    -
        Имя: {prop}
        Тип: Массив<Строка>
"""

_COMPONENT_EN = """ElementKind: InterfaceComponent
Id: 44444444-4444-4444-4444-444444444444
Name: TaskCard
Properties:
    -
        Name: {prop}
        Type: Array<String>
"""

_MODULE_EN = """ElementKind: CommonModule
Id: 55555555-5555-5555-5555-555555555555
Name: TaskHandling
Environment: Client
"""


def _component(prop: str, imports: tuple[str, ...] = ()) -> str:
    block = ""
    if imports:
        block = "Импорт:\n" + "".join(f"    - {name}\n" for name in imports)
    return _COMPONENT.format(prop=prop, imports=block)


def _lint(tmp_path, files: dict[str, str]) -> list:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return [
        d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE
    ]


# --- the finding ------------------------------------------------------------------------


def test_property_named_after_a_module_of_the_same_subsystem_is_reported(tmp_path):
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Основное/КарточкаЗадачи.yaml": _component("РаботаСЗадачами"),
    })
    assert len(diags) == 1
    assert "РаботаСЗадачами" in diags[0].message
    # the declaration line of the property, not the head of the file
    assert diags[0].path.endswith("КарточкаЗадачи.yaml")
    assert (diags[0].line, diags[0].col) == (6, 14)


def test_a_project_without_subsystem_files_is_judged_all_the_same(tmp_path):
    """A flat tree puts every element in one nameless placement - the module is reachable."""
    diags = _lint(tmp_path, {
        "РаботаСЗадачами.yaml": _MODULE,
        "КарточкаЗадачи.yaml": _component("РаботаСЗадачами"),
    })
    assert len(diags) == 1


def test_the_english_spelling_is_judged_too(tmp_path):
    """The kinds and the keys are read through the metamodel, not by their Russian text."""
    diags = _lint(tmp_path, {
        "Main/Subsystem.yaml": "Interface:\n    IncludeInAutoInterface: True\n",
        "Main/TaskHandling.yaml": _MODULE_EN,
        "Main/TaskCard.yaml": _COMPONENT_EN.format(prop="TaskHandling"),
    })
    assert len(diags) == 1
    assert "TaskHandling" in diags[0].message


def test_a_module_of_an_imported_subsystem_is_reported(tmp_path):
    """An import makes the foreign module addressable by the bare name - so it is hidden too."""
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Смежное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Смежное/КарточкаЗадачи.yaml": _component("РаботаСЗадачами", imports=("Основное",)),
    })
    assert len(diags) == 1


# --- the narrowings ---------------------------------------------------------------------


def test_a_property_with_no_namesake_module_is_clean(tmp_path):
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Основное/КарточкаЗадачи.yaml": _component("ЖурналЗадач"),
    })
    assert diags == []


def test_a_namesake_that_is_not_a_common_module_is_left_alone(tmp_path):
    """A property repeating a catalog name is a live idiom - the element is used as a TYPE."""
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _CATALOG,
        "Основное/КарточкаЗадачи.yaml": _component("РаботаСЗадачами"),
    })
    assert diags == []


def test_a_module_of_a_foreign_subsystem_that_is_not_imported_is_left_alone(tmp_path):
    """Without an import the bare name never reached that module, so the name is free."""
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Смежное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Смежное/КарточкаЗадачи.yaml": _component("РаботаСЗадачами"),
    })
    assert diags == []


def test_a_component_without_own_properties_contributes_nothing(tmp_path):
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Основное/КарточкаЗадачи.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\n"
            "Ид: 33333333-3333-3333-3333-333333333333\n"
            "Имя: КарточкаЗадачи\n"
            "Наследует:\n    Тип: Форма\n"
        ),
    })
    assert diags == []


def test_a_nested_component_name_is_not_a_property(tmp_path):
    """Only the top-level properties block is read: an embedded component named after a module
    is addressed through the components collection and hides nothing."""
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Основное/КарточкаЗадачи.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\n"
            "Ид: 33333333-3333-3333-3333-333333333333\n"
            "Имя: КарточкаЗадачи\n"
            "Наследует:\n"
            "    Тип: Форма\n"
            "    Содержимое:\n"
            "        Тип: Группа\n"
            "        Имя: РаботаСЗадачами\n"
        ),
    })
    assert diags == []


def test_the_finding_carries_no_autofix(tmp_path):
    """The cure is a rename, which reaches other files - an edit here would leave a broken tree."""
    diags = _lint(tmp_path, {
        "Основное/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Истина\n",
        "Основное/РаботаСЗадачами.yaml": _MODULE,
        "Основное/КарточкаЗадачи.yaml": _component("РаботаСЗадачами"),
    })
    assert len(diags) == 1 and diags[0].fix is None
