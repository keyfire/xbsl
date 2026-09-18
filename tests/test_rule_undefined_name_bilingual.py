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

from xbsl import dataset, engine
from xbsl.rules import undefined_names

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


# --- the members the platform gives the object module --------------------------------------

def _with_generated(monkeypatch, entries: dict | None) -> None:
    """Read the shipped catalog with `generated_members` set to `entries` (None removes it).

    The shipped data carries the section only after the extractor is run again, so the wiring
    is exercised against a catalog put together here - and the same helper writes the state of
    an OLDER dataset, where the section is absent.
    """
    real = dataset.load_json

    def load(name, version=None):
        catalog = real(name, version) if version is not None else real(name)
        if name != "stdlib.json":
            return catalog
        catalog = dict(catalog)
        if entries is None:
            catalog.pop("generated_members", None)
        else:
            catalog["generated_members"] = entries
        return catalog

    monkeypatch.setattr(undefined_names.dataset, "load_json", load)


_GENERATED_CATALOG = {
    "Справочник.Объект": {
        "properties": ["МоментПометкиУдаления", "ПометкаУдаления", "Ссылка"],
        "methods": ["Записать", "СоздатьКопию", "Удалить", "ЭтоНовый"],
    },
}


def test_object_module_calls_a_method_the_platform_gives_it(monkeypatch):
    """`ЭтоНовый()` is documented on the object type of a catalog and compiles in a product
    that ships; the rule called it undeclared because the members of that type were nowhere
    in the data."""
    _with_generated(monkeypatch, _GENERATED_CATALOG)
    found = _lint({
        "Задачи.yaml": _CATALOG_RU,
        "Задачи.Объект.xbsl": (
            "@Обработчик\n"
            "метод ПередЗаписью(До: Задачи.Данные, "
            "ПараметрыЗаписи: Задачи.ПараметрыЗаписи)\n"
            "    если не ЭтоНовый()\n"
            "        СоздатьКопию()\n"
            "    ;\n"
            ";\n"
        ),
    })
    assert found == []


def test_object_module_still_reports_a_name_the_platform_does_not_give_it(monkeypatch):
    """The negative control: the scope grows by what the data says, not by everything."""
    _with_generated(monkeypatch, _GENERATED_CATALOG)
    found = _lint({
        "Задачи.yaml": _CATALOG_RU,
        "Задачи.Объект.xbsl": (
            "@Обработчик\n"
            "метод ПередЗаписью(До: Задачи.Данные, "
            "ПараметрыЗаписи: Задачи.ПараметрыЗаписи)\n"
            "    если не ЭтоСтарый()\n"
            "    ;\n"
            ";\n"
        ),
    })
    assert [d.line for d in found] == [3]
    assert "ЭтоСтарый" in found[0].message


def test_an_older_dataset_without_the_section_keeps_the_scope_it_had(monkeypatch):
    """A dataset extracted before this section exists must not lose the four names the
    compiler probe confirmed - they are the fallback, and `Write` is one of them."""
    _with_generated(monkeypatch, None)
    found = _lint({
        "Задачи.yaml": _CATALOG_RU,
        "Задачи.Объект.xbsl": (
            "@Обработчик\n"
            "метод ПередЗаписью(До: Задачи.Данные, "
            "ПараметрыЗаписи: Задачи.ПараметрыЗаписи)\n"
            "    Записать()\n"
            ";\n"
        ),
    })
    assert found == []


def test_english_object_module_calls_the_same_method_by_its_english_name(monkeypatch):
    """The section is keyed by the kind in its Russian spelling and carries Russian member
    names; an English project spells both sides differently and must reach the same scope."""
    _with_generated(monkeypatch, _GENERATED_CATALOG)
    found = _lint({
        "Tasks.yaml": _CATALOG_EN,
        "Tasks.Object.xbsl": (
            "@Handler\n"
            "method BeforeWrite(To: Tasks.Data, WriteParameters: Tasks.WriteParameters)\n"
            "    if not IsNew()\n"
            "    ;\n"
            ";\n"
        ),
    })
    assert found == []
