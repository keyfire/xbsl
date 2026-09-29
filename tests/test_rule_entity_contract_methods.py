"""code/contract-method-not-abstract: the object and row modules of an entity contract.

An entity contract generates an object type and a row type for each of its tabular sections, and
a probe compiled a module for both: an ordinary method got "Non-abstract method ... cannot be
defined" in each, and the row module compiled once the method was gone. The rule joins a module
to the yaml of its contract through the facts of the run, so the modules are judged the same way
read from memory and from the disk. The module of the contract type itself, a static method and
the modules of every other kind stay silent.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

pytestmark = pytest.mark.needs_data

_RULE = "code/contract-method-not-abstract"

_CONTRACT = """\
ВидЭлемента: КонтрактСущности
Ид: 1d1f5c60-0000-4000-8000-00000000d001
Имя: Экспонаты
ОбластьВидимости: ВПроекте
Свойства:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000d002
        Имя: Название
        Тип: Строка
        МаксимальнаяДлина: 100
ТабличныеЧасти:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000d003
        Имя: Метки
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-00000000d004
                Имя: Текст
                Тип: Строка
                МаксимальнаяДлина: 50
"""

_CONTRACT_EN = """\
ElementKind: EntityContract
Id: 1d1f5c60-0000-4000-8000-00000000d011
Name: Exhibits
VisibilityScope: InProject
Properties:
    -
        Id: 1d1f5c60-0000-4000-8000-00000000d012
        Name: Title
        Type: String
        MaxLength: 100
TabularParts:
    -
        Id: 1d1f5c60-0000-4000-8000-00000000d013
        Name: Labels
        Attributes:
            -
                Id: 1d1f5c60-0000-4000-8000-00000000d014
                Name: Text
                Type: String
                MaxLength: 50
"""

_ORDINARY = 'метод Описание(): Строка\n    возврат ""\n;\n'
_ABSTRACT = "абстрактный метод Описание(): Строка\n"


def _lint(files: dict[str, str]) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == _RULE]


def _where(files: dict[str, str]) -> list[tuple[str, int, int]]:
    return [(d.path, d.line, d.col) for d in _lint(files)]


# --- what the compiler refuses --------------------------------------------------------------

def test_an_ordinary_method_of_the_object_module_is_reported_at_its_name():
    found = _lint({
        "Экспонаты.yaml": _CONTRACT,
        "Экспонаты.Объект.xbsl": "@ВПроекте\n" + _ORDINARY,
    })
    assert [(d.path, d.line, d.col) for d in found] == [("Экспонаты.Объект.xbsl", 2, 7)]
    assert "'Описание'" in found[0].message and "'Экспонаты'" in found[0].message


def test_an_ordinary_method_of_a_row_module_is_reported_with_its_section():
    found = _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Метки.xbsl": _ORDINARY})
    assert [(d.path, d.line, d.col) for d in found] == [("Экспонаты.Метки.xbsl", 1, 7)]
    assert "'Метки'" in found[0].message


def test_each_ordinary_method_is_reported_and_the_abstract_ones_are_not():
    module = _ABSTRACT + "\n" + _ORDINARY + "\n" + _ORDINARY.replace("Описание", "Итог")
    assert _where({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Объект.xbsl": module}) == [
        ("Экспонаты.Объект.xbsl", 3, 7), ("Экспонаты.Объект.xbsl", 7, 7),
    ]


def test_english_spellings_are_judged_the_same_way():
    ordinary = 'method Description(): String\n    return ""\n;\n'
    for module in ("Exhibits.Object.xbsl", "Exhibits.Labels.xbsl"):
        assert len(_lint({"Exhibits.yaml": _CONTRACT_EN, module: ordinary})) == 1, module
        clean = {"Exhibits.yaml": _CONTRACT_EN, module: "abstract method Description(): String\n"}
        assert _lint(clean) == [], module


def test_on_the_disk_the_modules_are_joined_the_same_way(tmp_path):
    (tmp_path / "Экспонаты.yaml").write_text(_CONTRACT, encoding="utf-8")
    (tmp_path / "Экспонаты.Метки.xbsl").write_text(_ORDINARY, encoding="utf-8")
    found = engine.run(discover([str(tmp_path)]), select={_RULE, "structure/xbsl-pair"})
    assert [(d.rule_id, d.line) for d in found] == [(_RULE, 1)]


# --- what stays silent ----------------------------------------------------------------------

@pytest.mark.parametrize("module", ["Экспонаты.Объект.xbsl", "Экспонаты.Метки.xbsl"])
def test_abstract_methods_are_what_the_modules_take(module):
    assert _lint({"Экспонаты.yaml": _CONTRACT, module: _ABSTRACT}) == []


@pytest.mark.parametrize("kind", ["Справочник", "Документ", "ПланОбмена"])
def test_the_modules_of_another_kind_are_not_judged(kind):
    # The control of the whole rule: the same files, only the kind of the element differs.
    owner = _CONTRACT.replace("КонтрактСущности", kind).replace("Свойства:", "Реквизиты:")
    for module in ("Экспонаты.Объект.xbsl", "Экспонаты.Метки.xbsl"):
        assert _lint({"Экспонаты.yaml": owner, module: _ORDINARY}) == [], module


def test_the_module_of_the_contract_type_is_not_judged():
    # The help page puts the abstract methods of the contract into this module; an ordinary one
    # there has not been compiled by any probe.
    assert _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.xbsl": _ORDINARY}) == []


def test_a_module_named_after_no_section_is_not_judged():
    # Not a row module: structure/xbsl-pair reports it as a module without a description.
    assert _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Прочее.xbsl": _ORDINARY}) == []


def test_a_static_method_is_not_judged():
    # The probe compiled an instance method; a static one has not been tried.
    static = "статический " + _ORDINARY
    assert _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Объект.xbsl": static}) == []


def test_the_methods_of_a_structure_inside_the_module_are_its_own():
    module = (
        _ABSTRACT + "\nструктура Точка\n    пер Икс: Число\n\n"
        "    метод Длина(): Число\n        возврат Икс\n    ;\n;\n"
    )
    assert _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Объект.xbsl": module}) == []


def test_a_contract_that_does_not_read_leaves_its_modules_alone():
    broken = "ВидЭлемента: КонтрактСущности\nИмя: Экспонаты\nТабличныеЧасти: [\n"
    for module in ("Экспонаты.Объект.xbsl", "Экспонаты.Метки.xbsl"):
        assert _lint({"Экспонаты.yaml": broken, module: _ORDINARY}) == [], module


def test_a_module_that_does_not_parse_is_left_to_the_parser():
    module = "метод Описание(: Строка\n    возврат \"\"\n;\n"
    assert _lint({"Экспонаты.yaml": _CONTRACT, "Экспонаты.Объект.xbsl": module}) == []
