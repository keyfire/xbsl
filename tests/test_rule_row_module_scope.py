"""code/undefined-name in the module of a tabular-section row type.

Every tabular section generates a structure type named after the element and the section, and
the help page on tabular sections says that type may have a module: `Заказы.Строки.xbsl` beside
`Заказы.yaml`. A probe compiled such a module with the attributes of the row resolved by bare
name. The rule used to skip the module whole, so a misspelled name there reached the compiler
unseen. Where the skip missed - sources held in memory, a section named like a type another
kind generates (`Parameters`) - the module was judged as an orphan instead, and every
attribute of the row was reported.

The scope is the row now: the attributes its section declares, the members of a structure type,
the methods of the module and the global names. The attributes of the owner and those of its
other sections are not there - the row is a type of its own. The owner is looked up among the
facts of the run, so a module read from memory is judged like one on the disk.

A method of the structure type answers only to a call: the probe compiled `Presentation()` and
`ToString()` in the module of a row and refused a bare `Presentation` ("Variable ... is not
defined"), the same answer it gave the standard fields of a section table.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules.undefined_names import _row_candidate, _row_type_scope

pytestmark = pytest.mark.needs_data

_RULE = "code/undefined-name"


def _owner(kind: str = "Справочник", name: str = "Заказы") -> str:
    return f"""\
ВидЭлемента: {kind}
Ид: 1d1f5c60-0000-4000-8000-00000000f001
Имя: {name}
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000f002
        Имя: Клиент
        Тип: Строка
ТабличныеЧасти:
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000f003
        Имя: Строки
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-00000000f004
                Имя: Количество
                Тип: Число
            -
                Ид: 1d1f5c60-0000-4000-8000-00000000f005
                Имя: Цена
                Тип: Число
    -
        Ид: 1d1f5c60-0000-4000-8000-00000000f006
        Имя: Этапы
        Реквизиты:
            -
                Ид: 1d1f5c60-0000-4000-8000-00000000f007
                Имя: Срок
                Тип: Дата
"""


_OWNER_EN = """\
ElementKind: Catalog
Id: 1d1f5c60-0000-4000-8000-00000000f011
Name: Orders
VisibilityScope: InProject
Attributes:
    -
        Id: 1d1f5c60-0000-4000-8000-00000000f012
        Name: Customer
        Type: String
TabularParts:
    -
        Id: 1d1f5c60-0000-4000-8000-00000000f013
        Name: Lines
        Attributes:
            -
                Id: 1d1f5c60-0000-4000-8000-00000000f014
                Name: Quantity
                Type: Number
            -
                Id: 1d1f5c60-0000-4000-8000-00000000f015
                Name: Price
                Type: Number
"""


def _method(body: str, result: str = "Число") -> str:
    return f"@ВПроекте\nметод Итог(): {result}\n    {body}\n;\n"


def _lint(files: dict[str, str]) -> list:
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return [d for d in engine.run_sources(sources) if d.rule_id == _RULE]


def _names(files: dict[str, str]) -> list[str]:
    return sorted(d.message.split("'")[1] for d in _lint(files))


# --- what the row gives its module ---------------------------------------------------------

@pytest.mark.parametrize("kind", ["Справочник", "Документ"])
def test_a_row_module_sees_the_attributes_of_its_section(kind):
    # The regression the other way round: judged without the row, both were reported.
    assert _lint({
        "Заказы.yaml": _owner(kind),
        "Заказы.Строки.xbsl": _method("возврат Количество * Цена"),
    }) == []


def test_a_row_module_calls_its_own_methods_and_the_members_of_a_structure():
    # `ToString` is what every structure type has - the module of a structure element sees it
    # by the same bare name.
    assert _lint({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": (
            "@ВПроекте\nметод Сумма(): Число\n    возврат Количество * Цена\n;\n\n"
            + _method('возврат ВСтроку() + " " + Сумма().ВСтроку()', "Строка")
        ),
    }) == []


def test_a_row_module_reports_a_misspelled_attribute_and_names_the_right_one():
    # The regression: the module was skipped, and this went to the compiler.
    found = _lint({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method("возврат Количесво * Цена"),
    })
    assert [d.line for d in found] == [3]
    assert "'Количесво'" in found[0].message and "'Количество'" in found[0].message


def test_the_attributes_of_the_owner_are_not_fields_of_its_row():
    assert _names({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method("возврат Клиент", "Строка"),
    }) == ["Клиент"]


def test_another_section_of_the_owner_is_not_in_scope_either():
    assert _names({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method("возврат Срок", "Дата"),
    }) == ["Срок"]


def test_an_english_row_module_reads_the_english_keys_of_its_owner():
    # `TabularParts` and `Attributes`: the keys of an English yaml, the same row.
    files = {
        "Orders.yaml": _OWNER_EN,
        "Orders.Lines.xbsl": (
            "@InProject\nmethod Total(): String\n"
            "    return (Quantity * Price).ToString() + ToString()\n;\n"
        ),
    }
    assert _lint(files) == []
    files["Orders.Lines.xbsl"] = "@InProject\nmethod Total(): Number\n    return Customer\n;\n"
    assert _names(files) == ["Customer"]


# --- a method of the structure type answers only to a call ---------------------------------

@pytest.mark.parametrize("call", ["Представление()", "ВСтроку()", "ПолучитьТип().ВСтроку()"])
def test_a_method_of_the_structure_type_is_called(call):
    assert _lint({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method(f"возврат {call}", "Строка"),
    }) == []


def test_a_bare_method_of_the_structure_type_is_reported_with_the_call_to_write():
    # The regression: the members were taken as names, so the bare one passed. The control is
    # the test above - the same name with the parentheses.
    found = _lint({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method("возврат Представление", "Строка"),
    })
    assert [d.line for d in found] == [3]
    assert "'Представление()'" in found[0].message


def test_a_bare_method_is_reported_in_an_english_row_module_too():
    files = {
        "Orders.yaml": _OWNER_EN,
        "Orders.Lines.xbsl": "@InProject\nmethod Total(): String\n    return Presentation()\n;\n",
    }
    assert _lint(files) == []
    files["Orders.Lines.xbsl"] = "@InProject\nmethod Total(): String\n    return Presentation\n;\n"
    found = _lint(files)
    assert len(found) == 1 and "'Presentation()'" in found[0].message


def test_an_attribute_named_like_a_method_is_read_bare():
    # The section may call an attribute by the name of a method of the type: the attribute is a
    # value, so the bare name is its own.
    owner = _owner().replace("Имя: Цена", "Имя: Представление")
    assert _lint({
        "Заказы.yaml": owner,
        "Заказы.Строки.xbsl": _method("возврат Представление", "Строка"),
    }) == []


@pytest.mark.parametrize("name", ["НомерСтроки", "Индекс", "Владелец"])
def test_the_standard_fields_of_a_section_table_are_not_names_of_its_row(name):
    # The probe answered "Variable ... is not defined" for each of them in the module of a row.
    assert _names({
        "Заказы.yaml": _owner(),
        "Заказы.Строки.xbsl": _method(f"возврат {name}"),
    }) == [name]


_STRUCTURE = (
    "ВидЭлемента: Структура\nИд: 1d1f5c60-0000-4000-8000-00000000f021\nИмя: Точка\n"
    "ОбластьВидимости: ВПроекте\nПоля:\n    -\n        Имя: Икс\n        Тип: Число\n"
)


@pytest.mark.parametrize("name", ["Представление", "ВСтроку", "ПолучитьТип"])
def test_the_module_of_a_structure_element_calls_the_methods_of_its_type(name):
    # The module of a `Structure` element extends the same structure type, and the probe
    # answered there as in a row: each of the three bare got "Variable ... is not defined".
    found = _lint({"Точка.yaml": _STRUCTURE, "Точка.xbsl": _method(f"возврат {name}", "Строка")})
    assert [d.line for d in found] == [3]
    assert f"'{name}()'" in found[0].message


def test_the_module_of_a_structure_element_reads_its_fields_and_calls_the_methods():
    # The control of the test above: the calls compiled, and a field is a value.
    assert _lint({
        "Точка.yaml": _STRUCTURE,
        "Точка.xbsl": _method('возврат Представление() + ВСтроку() + Икс.ВСтроку()', "Строка"),
    }) == []
    named = _STRUCTURE.replace("Имя: Икс\n        Тип: Число",
                               "Имя: Представление\n        Тип: Строка")
    assert _lint({"Точка.yaml": named,
                  "Точка.xbsl": _method("возврат Представление", "Строка")}) == []


def test_data_that_does_not_split_the_members_keeps_every_member_a_name():
    # Data generated before the manager members were split cannot tell a method from a
    # property: narrowing blindly would report code that compiles.
    names, calls = _row_type_scope({}, {"Структура": ["ВСтроку", "Представление"]})
    assert {"ВСтроку", "Представление"} <= names and calls == set()
    names, calls = _row_type_scope(
        {}, {"Структура": {"properties": ["Индекс"], "methods": ["Представление"]}},
    )
    assert "Индекс" in names and "Представление" in calls
    assert "Представление" not in names


# --- the controls: a module that is no row module ------------------------------------------

def test_a_module_named_after_no_section_is_not_given_a_row():
    # `Прочее` is no section of the owner: the module is judged as before, without the row.
    assert _names({
        "Заказы.yaml": _owner(),
        "Заказы.Прочее.xbsl": _method("возврат Количество"),
    }) == ["Количество"]


def test_an_owner_that_does_not_read_leaves_the_row_module_unjudged():
    # Whether it declares the section is unknown: its own yaml/valid is the finding to read.
    assert _lint({
        "Заказы.yaml": "ВидЭлемента: Справочник\nИмя: Заказы\nТабличныеЧасти: [\n",
        "Заказы.Строки.xbsl": _method("возврат Количесво"),
    }) == []


def test_the_object_module_keeps_the_scope_of_its_element():
    # An object module is never taken for a row: the element's attributes, not the row's.
    files = {"Заказы.yaml": _owner(), "Заказы.Объект.xbsl": _method("возврат Клиент", "Строка")}
    assert _lint(files) == []
    files["Заказы.Объект.xbsl"] = _method("возврат Количество")
    assert _names(files) == ["Количество"]


def test_a_section_named_like_a_type_of_another_kind_keeps_its_row():
    # The section is named like the `Parameters` type of a report, which a catalog does not
    # generate: the declaration decides, not a list of the tails of every kind.
    owner = _owner().replace("Имя: Строки", "Имя: Параметры")
    assert _lint({
        "Заказы.yaml": owner,
        "Заказы.Параметры.xbsl": _method("возврат Количество * Цена"),
    }) == []


def test_a_module_name_is_split_at_the_last_dot():
    assert _row_candidate("Заказы.Строки.xbsl") == ["Заказы.yaml", "Строки"]
    assert _row_candidate("Orders.Lines.xbsl") == ["Orders.yaml", "Lines"]
    assert _row_candidate("Заказы.xbsl") is None


def test_on_the_disk_the_module_is_paired_and_judged_the_same_way(tmp_path):
    (tmp_path / "Заказы.yaml").write_text(_owner(), encoding="utf-8")
    (tmp_path / "Заказы.Строки.xbsl").write_text(
        _method("возврат Количество * Цена + Количесво"), encoding="utf-8",
    )
    found = engine.run(discover([str(tmp_path)]), select={_RULE, "structure/xbsl-pair"})
    assert [(d.rule_id, d.line) for d in found] == [(_RULE, 3)]
    assert "'Количесво'" in found[0].message
