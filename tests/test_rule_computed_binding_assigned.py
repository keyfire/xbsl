"""yaml/computed-binding-assigned: every instance binds a property computed while the
component assigns it in its own module - the cross-file half of code/bound-property-assign.

The shape comes from a live defect: every instance of one component bound a property
with computed expressions while the component assigned it, and the platform threw
IllegalStateException on each run of that code. The narrowings encode what reconnaissance found on the
live corpus: a bare spelling inside a constructor call is a named argument, a code-built
instance (or one bound with a bare path / a literal / not at all) is a legal assignment
target, and a runtime-guarded component ships exactly that way.

The mapper tokenizes the module, so the whole module needs the language data and sits in
conftest's data-dependent list - the same reason as the sibling rule's tests.
"""

import pytest

from xbsl import engine
from xbsl.diagnostics import Severity

RULE = "yaml/computed-binding-assigned"

COMPONENT = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 11111111-1111-1111-1111-111111111111\n"
    "Имя: Пикер\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: Цвет\n"
    "        Тип: Строка\n"
)
MODULE = (
    "метод ПриВыборе()\n"
    "    Цвет = \"FFFFFF\"\n"
    ";\n"
)
FORM_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 11111111-1111-1111-1111-111111111112\n"
    "Имя: Форма\n"
)


def _lint(files):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


def _project(instances: str, module: str = MODULE, **extra):
    files = {
        "Пикер.yaml": COMPONENT,
        "Пикер.xbsl": module,
        "Форма.yaml": FORM_HEAD + "Наследует:\n    Тип: Группа\n    Содержимое:\n" + instances,
    }
    files.update(extra)
    return files


_TWO_COMPUTED = (
    "        -\n"
    "            Тип: Пикер\n"
    "            Цвет: =ВычислитьЦвет(\"accent\")\n"
    "        -\n"
    "            Тип: Пикер\n"
    "            Цвет: =ВычислитьЦвет(\"text\")\n"
)


def test_rule_registered_project_scope():
    info = next(r for r in engine.active_rules() if r.id == RULE)
    assert info.tier == "D" and info.scope == "project"
    assert info.severity is Severity.WARNING and info.enabled_by_default


def test_every_instance_computed_is_flagged_once():
    d = _lint(_project(_TWO_COMPUTED))
    assert len(d) == 1, [x.message for x in d]
    found = d[0]
    assert found.rule_id == RULE and found.path == "Форма.yaml"
    assert found.line == 9  # the first computed binding - the line the live fix edited
    assert "'Цвет'" in found.message and "'Пикер'" in found.message
    assert "Пикер.xbsl:2" in found.message  # the assignment the reader goes to
    assert "ещё 1" in found.message


def test_bare_path_instance_makes_assignment_legal():
    # The live fix itself: a bare path is a two-way binding, assigning is the point.
    instances = _TWO_COMPUTED + (
        "        -\n"
        "            Тип: Пикер\n"
        "            Цвет: =ПоказанныйЦвет\n"
    )
    assert _lint(_project(instances)) == []


def test_instance_without_the_property_makes_assignment_legal():
    instances = _TWO_COMPUTED + (
        "        -\n"
        "            Тип: Пикер\n"
        "            Заголовок: Роль\n"
    )
    assert _lint(_project(instances)) == []


def test_code_construction_silences_the_pair():
    # The guarded pattern: the code builds ordinary instances and guards the bound one.
    files = _project(_TWO_COMPUTED)
    files["Страница.xbsl"] = (
        "метод Построить()\n"
        "    пер Ряд = новый Пикер()\n"
        ";\n"
    )
    assert _lint(files) == []


def test_named_argument_is_not_an_assignment():
    # `новый Меню(Цвет = Цвет)` spells the same and assigns nothing.
    module = (
        "метод Открыть()\n"
        "    пер Меню = новый ВсплывающееМеню(Цвет = Цвет)\n"
        ";\n"
    )
    assert _lint(_project(_TWO_COMPUTED, module=module)) == []


def test_local_declaration_shadows_the_property():
    module = (
        "метод Пересчитать()\n"
        "    пер Цвет = \"FFFFFF\"\n"
        "    Цвет = \"000000\"\n"
        ";\n"
    )
    assert _lint(_project(_TWO_COMPUTED, module=module)) == []


def test_parameter_shadows_the_property():
    module = (
        "метод Показать(Цвет: Строка)\n"
        "    Цвет = \"000000\"\n"
        ";\n"
    )
    assert _lint(_project(_TWO_COMPUTED, module=module)) == []


def test_member_assignment_is_the_sibling_rules_case():
    module = (
        "метод Настроить()\n"
        "    Компоненты.Пикер.Цвет = \"000000\"\n"
        ";\n"
    )
    assert _lint(_project(_TWO_COMPUTED, module=module)) == []


def test_component_without_module_is_silent():
    files = _project(_TWO_COMPUTED)
    del files["Пикер.xbsl"]
    assert _lint(files) == []


@pytest.mark.needs_data
def test_english_spellings_flagged():
    files = {
        "Picker.yaml": (
            "ElementKind: InterfaceComponent\n"
            "Ид: 11111111-1111-1111-1111-111111111113\n"
            "Name: Picker\n"
            "Properties:\n"
            "    -\n"
            "        Name: Color\n"
            "        Тип: Строка\n"
        ),
        "Picker.xbsl": "метод ПриВыборе()\n    Color = \"FFFFFF\"\n;\n",
        "Form.yaml": (
            "ElementKind: КомпонентИнтерфейса\n"
            "Ид: 11111111-1111-1111-1111-111111111114\n"
            "Name: Form\n"
            "Inherits:\n"
            "    Type: Группа\n"
            "    Содержимое:\n"
            "        -\n"
            "            Type: Picker\n"
            "            Color: =ComputeColor(\"accent\")\n"
        ),
    }
    d = _lint(files)
    assert len(d) == 1, [x.message for x in d]
    assert "'Color'" in d[0].message and "Picker.xbsl:2" in d[0].message
