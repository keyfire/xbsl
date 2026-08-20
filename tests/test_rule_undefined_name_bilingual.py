"""code/undefined-name on ENGLISH sources: the scope has to accept both spellings.

1C:Element is bilingual - the compiler answers to a global by either spelling, Russian or
English - while the catalog the rule builds its global scope from is
extracted from the documentation, which is Russian only. Two defects met here:

- the `globals` section of the catalog listed the Russian spelling alone, so every call of a
  global by its English name was reported undefined (`GoToLink`, `Pause`, `Message`), and so
  were the context roots of the rule's own tables (`Entity`, the rights namespace of a
  permission handler);
- an object module is `<Name>.Object.xbsl` in an English project and `<Имя>.Объект.xbsl` in a
  Russian one. Only the Russian tail was recognised, so the pair lookup went to
  `<Name>.Object.yaml`, which no project has: the module was left without the attributes of
  its own object, and every one of them was reported undefined.

Both scopes are checked here from memory (engine.load_text), the Russian half of each next to
the English one, plus the negative controls - a bilingual scope must not turn the rule blind.
"""

import pytest

from xbsl import engine
from xbsl.rules import undefined_names  # noqa: F401 - registers the rule

pytestmark = pytest.mark.needs_data

_RULE = "code/undefined-name"

_CATALOG_RU = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-00000000e001
Имя: Задачи
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000e002
        Имя: Наименование
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000e003
        Имя: Исполнитель
        Тип: Строка
"""

_CATALOG_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-00000000e004
Name: Tasks
VisibilityScope: InProject
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-00000000e005
        Name: Name
    -
        Id: 1d1f5c60-0000-4000-8000-00000000e006
        Name: Assignee
        Type: String
"""

_COMMON_RU = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-00000000e007
Имя: Шаги
ОбластьВидимости: ВПроекте
"""

_COMMON_EN = """\
ElementKind: CommonModule
Id: 1d1f5c60-0000-4000-8000-00000000e008
Name: Steps
VisibilityScope: InProject
"""


def _lint(files: dict[str, str]) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == _RULE]


# --- a global called by its English name -------------------------------------------------

def test_russian_module_calls_a_global_by_its_russian_name():
    found = _lint({
        "Шаги.yaml": _COMMON_RU,
        "Шаги.xbsl": "метод Открыть(Адрес: Строка)\n    ПерейтиПоСсылке(Адрес)\n;\n",
    })
    assert found == []


def test_english_module_calls_the_same_global_by_its_english_name():
    # The regression: the catalog listed the Russian spelling alone, and this was an error.
    found = _lint({
        "Steps.yaml": _COMMON_EN,
        "Steps.xbsl": "method Open(Address: String)\n    GoToLink(Address)\n;\n",
    })
    assert found == []


def test_english_module_reports_a_global_that_does_not_exist():
    # The negative control: the English scope is wider, not blind.
    found = _lint({
        "Steps.yaml": _COMMON_EN,
        "Steps.xbsl": "method Open(Address: String)\n    GoToLinq(Address)\n;\n",
    })
    assert [d.line for d in found] == [2]
    assert "GoToLinq" in found[0].message


def test_english_module_reads_the_rights_namespace_by_its_english_name():
    # `Entity` is the root of the rights namespace in a permission handler.
    found = _lint({
        "Steps.yaml": _COMMON_EN,
        "Steps.xbsl": "method Allowed(): Boolean\n    return Entity.Permission.Read\n;\n",
    })
    assert found == []


# --- the attributes of an object module ---------------------------------------------------

def test_russian_object_module_sees_the_attributes_of_its_object():
    found = _lint({
        "Задачи.yaml": _CATALOG_RU,
        "Задачи.Объект.xbsl": (
            "@Обработчик\n"
            "метод ПередЗаписью(До: Задачи.Данные, "
            "ПараметрыЗаписи: Задачи.ПараметрыЗаписи)\n"
            "    Исполнитель = Наименование\n"
            ";\n"
        ),
    })
    assert found == []


def test_english_object_module_sees_them_too():
    # The regression: `Tasks.Object.xbsl` paired with nothing, so both attributes and the
    # standard `Link` of the entity protocol were reported undefined.
    found = _lint({
        "Tasks.yaml": _CATALOG_EN,
        "Tasks.Object.xbsl": (
            "@Handler\n"
            "method BeforeWrite(To: Tasks.Data, WriteParameters: Tasks.WriteParameters)\n"
            "    Assignee = Name\n"
            "    var Own = Link\n"
            ";\n"
        ),
    })
    assert found == []


def test_english_object_module_reports_an_attribute_that_is_not_declared():
    # The negative control of the pairing: the yaml is read, not waved through.
    found = _lint({
        "Tasks.yaml": _CATALOG_EN,
        "Tasks.Object.xbsl": (
            "@Handler\n"
            "method BeforeWrite(To: Tasks.Data, WriteParameters: Tasks.WriteParameters)\n"
            "    Assignee = Assignes\n"
            ";\n"
        ),
    })
    assert [d.line for d in found] == [3]
    assert "Assignes" in found[0].message


def test_english_manager_module_calls_a_manager_method_by_its_english_name():
    # `SetDeletionMark` of a catalog manager, called by its bare name.
    found = _lint({
        "Tasks.yaml": _CATALOG_EN,
        "Tasks.xbsl": (
            "method Drop(Reference: Tasks.Link)\n"
            "    SetDeletionMark(Reference, True)\n"
            ";\n"
        ),
    })
    assert found == []
