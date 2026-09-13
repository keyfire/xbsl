"""code/unused-import reads what the compiler resolves, not what the module spells.

The editor reports an import whose namespace the binder never asked for a type of. The earlier
reading kept an import alive by any identifier that spelled an element of the namespace, and on a
real project with packages it matched none of the editor's findings: the word was the import line
itself, a member after a dot, a local, a property of the paired yaml. Each test below pins one
mechanism of the binder model (see the docstring of xbsl.rules.unused_imports) together with its
control - the same module without the construct, which the rule has to report.

The fixture is one project, `Демо::Учет`: subsystem `Снабжение` keeps a catalog of counterparties,
subsystem `Склад` keeps a catalog, a common module named like the subsystem itself, an
enumeration and a package `Партии` with a common module and a catalog, and subsystem `Продажи`
uses both. The mappers tokenize and parse the modules, so everything that runs the rule needs the
language data; the helpers that read type texts do not.
"""

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules.unused_imports import _qualified_name, _type_chains

RULE = "code/unused-import"
BASE = "Демо/Учет"

needs_data = pytest.mark.needs_data  # the lexer reads the operators and keywords from the data


def _catalog(name: str, extra: str = "") -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\nОбластьВидимости: ВПроекте\n{extra}"


def _common(name: str) -> str:
    return f"ВидЭлемента: ОбщийМодуль\nИмя: {name}\nОбластьВидимости: ВПроекте\n"


SUPPLIER = "Импорт:\n    - Снабжение\nРеквизиты:\n    -\n        Имя: Поставщик\n        Тип: Контрагенты.Ссылка?\n"


def _files(module: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Снабжение/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Снабжение/Контрагенты.yaml": _catalog("Контрагенты"),
        "Склад/Подсистема.yaml": "Использование:\n    - Снабжение\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура", SUPPLIER),
        "Склад/Склад.yaml": _common("Склад"),
        "Склад/Склад.xbsl": "@ВПроекте\nметод Остаток(): Число\n    возврат 0\n;\n",
        "Склад/ВидНоменклатуры.yaml": (
            "ВидЭлемента: Перечисление\nИмя: ВидНоменклатуры\nОбластьВидимости: ВПроекте\n"
            "Элементы:\n    -\n        Имя: Штучный\n    -\n        Имя: Весовой\n"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров", SUPPLIER),
        "Склад/Партии/РасчетПартий.yaml": _common("РасчетПартий"),
        "Склад/Партии/РасчетПартий.xbsl": (
            "импорт Снабжение\n\n"
            "@ВПроекте\nструктура ИтогПартии\n    пер Поставщик: Контрагенты.Ссылка? = Неопределено\n;\n\n"
            "@ВПроекте\nметод Итог(): ИтогПартии\n    возврат новый ИтогПартии()\n;\n\n"
            "@ВПроекте\nметод Пересчитать()\n;\n"),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n    - Снабжение\n",
        "Продажи/Заказы.yaml": _common("Заказы"),
        "Продажи/Заказы.xbsl": module,
    }
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _lint(module: str, extra: dict[str, str] | None = None) -> list[tuple[int, str]]:
    sources = [engine.load_text(name, text) for name, text in _files(module, extra).items()]
    return [(d.line, d.data["namespace"]) for d in engine.run_sources(sources, select={RULE})]


def _component(module: str, properties: str) -> dict[str, str]:
    yaml = ("ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\nОбластьВидимости: ВПроекте\n"
            "Импорт:\n    - Склад\n    - Снабжение\nНаследует:\n    Тип: Группа\n"
            f"Свойства:\n{properties}")
    return {"Продажи/КарточкаЗаказа.yaml": yaml, "Продажи/КарточкаЗаказа.xbsl": module}


def _lint_component(module: str, properties: str) -> list[tuple[int, str]]:
    sources = [engine.load_text(name, text)
               for name, text in _files("", _component(module, properties)).items()]
    return [(d.line, d.data["namespace"]) for d in engine.run_sources(sources, select={RULE})
            if "КарточкаЗаказа" in d.path]


# --- the words that are not uses ----------------------------------------------------------------


@needs_data
def test_the_import_line_and_the_qualifier_do_not_use_an_element_named_like_the_subsystem():
    """The live shape: the root of a subsystem holds an element named like the subsystem, the
    module imports the root and a package, and reaches only the package."""
    code = "импорт Склад\nимпорт Склад::Партии\n\nметод Т()\n    РасчетПартий.Пересчитать()\n;\n"
    assert _lint(code) == [(1, "Склад")]
    # The control: the element named like the subsystem is called.
    assert _lint(code.replace("Пересчитать()\n", "Пересчитать()\n    Склад.Остаток()\n")) == []


@needs_data
def test_a_member_after_a_dot_is_not_a_use():
    code = "импорт Склад\n\nметод Т(Запрос: Строка): Число\n    возврат Запрос.Номенклатура.Длина()\n;\n"
    assert _lint(code) == [(1, "Склад")]
    assert _lint(code.replace("Запрос.Номенклатура.Длина()", "Номенклатура.Представление()")) == []


@needs_data
def test_a_local_named_like_an_element_is_not_a_use_even_as_a_chain_root():
    variable = ("импорт Склад\n\nметод Т(): Число\n    пер Номенклатура = новый Массив<Строка>()\n"
                "    возврат Номенклатура.Размер()\n;\n")
    parameter = ("импорт Склад\n\nметод Т(Номенклатура: Массив<Строка>): Число\n"
                 "    возврат Номенклатура.Размер()\n;\n")
    assert _lint(variable) == [(1, "Склад")]
    assert _lint(parameter) == [(1, "Склад")]


@needs_data
def test_a_property_of_the_paired_yaml_is_a_use_only_as_a_chain_root():
    """The compiler tries `Корень.член` as a static access before it binds the root as a
    property, so a property named like an element keeps the import there - and only there."""
    properties = "    -\n        Имя: Номенклатура\n        Тип: Массив<Строка>\n"
    chain = "импорт Склад\n\nметод Т(): Число\n    возврат Номенклатура.Размер()\n;\n"
    bare = "импорт Склад\n\nметод Т()\n    Номенклатура = новый Массив<Строка>()\n;\n"
    assert _lint_component(chain, properties) == []
    assert _lint_component(bare, properties) == [(1, "Склад")]


# --- the declared types -------------------------------------------------------------------------


@needs_data
def test_the_type_of_a_property_the_code_names_is_a_use():
    properties = "    -\n        Имя: Партии\n        Тип: Массив<Склад::Партии::ПартииТоваров.Ссылка>\n"
    named = ("импорт Склад::Партии\n\nметод Т(): Строка\n    для Партия из Партии\n"
             "        возврат Партия.Представление()\n    ;\n    возврат \"\"\n;\n")
    assert _lint_component(named, properties) == []
    silent = "импорт Склад::Партии\n\nметод Т(): Строка\n    возврат \"\"\n;\n"
    assert _lint_component(silent, properties) == [(1, "Склад::Партии")]


@needs_data
def test_a_property_of_a_base_component_of_the_project_is_read_like_an_own_one():
    base = ("ВидЭлемента: КомпонентИнтерфейса\nИмя: БазоваяКарточка\nОбластьВидимости: ВПроекте\n"
            "Импорт:\n    - Склад::Партии\nНаследует:\n    Тип: Группа\nСвойства:\n    -\n"
            "        Имя: Партии\n        Тип: Массив<ПартииТоваров.Ссылка>\n")
    card = ("ВидЭлемента: КомпонентИнтерфейса\nИмя: КарточкаЗаказа\nОбластьВидимости: ВПроекте\n"
            "Наследует:\n    Тип: Склад::БазоваяКарточка\n")
    named = ("импорт Склад::Партии\n\nметод Т(): Строка\n    для Партия из Партии\n"
             "        возврат Партия.Представление()\n    ;\n    возврат \"\"\n;\n")
    extra = {"Склад/БазоваяКарточка.yaml": base, "Продажи/КарточкаЗаказа.yaml": card,
             "Продажи/КарточкаЗаказа.xbsl": named}
    assert [d for d in _lint("", extra) if d[1] == "Склад::Партии"] == []
    silent = {**extra, "Продажи/КарточкаЗаказа.xbsl": "импорт Склад::Партии\n\nметод Т()\n;\n"}
    assert [d for d in _lint("", silent) if d[1] == "Склад::Партии"] == [(1, "Склад::Партии")]


@needs_data
def test_a_structure_returned_by_a_foreign_module_brings_the_types_of_the_fields_read():
    code = ("импорт Снабжение\n\nметод Т(): Строка\n"
            "    знч Итог = Склад::Партии::РасчетПартий.Итог()\n"
            "    возврат Итог.Поставщик?.Представление() ?? \"\"\n;\n")
    assert _lint(code) == []
    unread = code.replace("Итог.Поставщик?.Представление() ?? \"\"", "\"\"")
    assert _lint(unread) == [(1, "Снабжение")]


@needs_data
def test_a_derived_type_and_a_platform_member_bring_the_attributes_read():
    written = ("импорт Снабжение\n\nметод Т(Объект: Склад::Номенклатура.Объект): Строка\n"
               "    возврат Объект.Поставщик?.Представление() ?? \"\"\n;\n")
    found = ("импорт Снабжение\n\nметод Т(): Строка\n"
             "    знч Ссылка = Склад::Номенклатура.НайтиПоНаименованию(\"а\")\n"
             "    возврат Ссылка?.Загрузить().Поставщик?.Представление() ?? \"\"\n;\n")
    assert _lint(written) == []
    assert _lint(found) == []
    assert _lint(written.replace("Объект.Поставщик?.Представление() ?? \"\"", "\"\"")) == [
        (1, "Снабжение")]


@needs_data
def test_a_query_table_and_a_column_passed_on_as_it_is_are_uses():
    table = ("импорт Склад::Партии\n\nметод Т()\n    знч Р = Запрос{\n        ВЫБРАТЬ П.Ссылка\n"
             "        ИЗ ПартииТоваров КАК П\n    }.Выполнить()\n;\n")
    assert _lint(table) == []
    column = ("импорт Снабжение\n\nметод Т(): Строка\n    исп Р = Запрос{\n"
              "        ВЫБРАТЬ П.Поставщик КАК Кто\n        ИЗ Склад::Партии::ПартииТоваров КАК П\n"
              "    }.Выполнить()\n    для Запись из Р\n"
              "        возврат Запись.Кто?.Представление() ?? \"\"\n    ;\n    возврат \"\"\n;\n")
    assert _lint(column) == []
    # A computed column is a value of its own: the members read inside the query mark nothing.
    computed = column.replace("П.Поставщик КАК Кто", "П.Поставщик.Наименование КАК Кто")
    assert _lint(computed) == [(1, "Снабжение")]


# --- the other lookups --------------------------------------------------------------------------


@needs_data
def test_an_enumeration_value_in_a_when_branch_is_a_use():
    code = ("импорт Склад\n\nметод Т(): Число\n    выбор Заказы.Вид()\n    когда Штучный\n"
            "        возврат 1\n    ;\n    возврат 0\n;\n\nметод Вид(): Склад::ВидНоменклатуры\n"
            "    возврат Склад::ВидНоменклатуры.Весовой\n;\n")
    assert _lint(code) == []
    # The control drops the qualified result type too: that one alone is a use as well.
    control = code.replace("    когда Штучный\n        возврат 1\n", "    когда 1\n        возврат 1\n")
    control = control.replace("Склад::ВидНоменклатуры\n", "Число\n").replace(
        "Склад::ВидНоменклатуры.Весовой", "1")
    assert _lint(control) == [(1, "Склад")]


@needs_data
def test_a_qualified_name_uses_the_namespace_it_names():
    code = "импорт Склад::Партии\n\nметод Т(): Склад::Партии::ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n"
    assert _lint(code) == []
    assert _lint(code.replace("Склад::Партии::ПартииТоваров.Ссылка?", "Число?")) == [
        (1, "Склад::Партии")]


@needs_data
def test_an_import_of_the_own_namespace_is_judged():
    """A module that asks nothing of its own type has no use for importing its own subsystem, a
    component module as well; a local or a name that is not one makes the binder ask for it."""
    own = "импорт Продажи\n\nметод Т(): Число\n    возврат 1\n;\n"
    with_local = own.replace("    возврат 1\n", "    пер Х = 1\n    возврат Х\n")
    properties = "    -\n        Имя: Число1\n        Тип: Число\n"
    assert _lint(own) == [(1, "Продажи")]
    assert _lint(with_local) == []
    assert _lint_component(own, properties) == [(1, "Продажи")]
    assert _lint_component(own.replace("возврат 1", "возврат Число1"), properties) == []


@needs_data
def test_a_module_that_does_not_parse_is_not_judged():
    assert _lint("импорт Склад\n\nметод Т(\n;\n") == []


@needs_data
def test_an_english_module_is_read_the_same_way():
    code = "import Склад\nimport Склад::Партии\n\nmethod Т()\n    РасчетПартий.Пересчитать()\n;\n"
    assert _lint(code) == [(1, "Склад")]
    properties = "    -\n        Имя: Номенклатура\n        Тип: Array<String>\n"
    chain = "import Склад\n\nmethod Т(): Number\n    return Номенклатура.Size()\n;\n"
    assert _lint_component(chain, properties) == []
    bare = "import Склад\n\nmethod Т()\n    Номенклатура = new Array<String>()\n;\n"
    assert _lint_component(bare, properties) == [(1, "Склад")]


@needs_data
def test_a_star_and_a_column_without_an_alias_carry_the_fields_of_the_table():
    head = "импорт Снабжение\n\nметод Т(): Строка\n    исп Р = Запрос{\n"
    tail = ("    }.Выполнить()\n    для Запись из Р\n"
            "        возврат Запись.Поставщик?.Представление() ?? \"\"\n    ;\n    возврат \"\"\n;\n")
    no_alias = head + "        ВЫБРАТЬ П.Поставщик\n        ИЗ Склад::Партии::ПартииТоваров КАК П\n" + tail
    star = head + "        ВЫБРАТЬ *\n        ИЗ Склад::Партии::ПартииТоваров\n" + tail
    assert _lint(no_alias) == []
    assert _lint(star) == []
    unread = no_alias.replace("Запись.Поставщик?.Представление() ?? \"\"", "\"\"")
    assert _lint(unread) == [(1, "Снабжение")]


# --- resources, on disk -------------------------------------------------------------------------


def _write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@needs_data
def test_a_bare_resource_key_uses_the_namespace_that_alone_holds_the_file(tmp_path):
    svg = '<svg xmlns="http://www.w3.org/2000/svg"/>\n'
    _write(tmp_path, _files("", {
        "Склад/Ресурсы/Ресурсы.yaml": "ОбластьВидимости: ВПроекте\n",
        "Склад/Ресурсы/Общий.svg": svg,
        "Склад/Ресурсы/Складской.svg": svg,
        "Продажи/Ресурсы/Общий.svg": svg,
    }))
    module = tmp_path / BASE / "Продажи" / "Заказы.xbsl"

    def run(key: str) -> list[int]:
        module.write_text(f"импорт Склад\n\nметод Т(): ДвоичныйОбъект.Ссылка\n"
                          f"    возврат Ресурс{{{key}}}.Ссылка\n;\n", encoding="utf-8")
        return [d.line for d in engine.run(discover([str(tmp_path)]), select={RULE})]

    assert run("Складской.svg") == []
    assert run("Общий.svg") == [1]  # the own subsystem holds the file: it resolves there
    assert run("Склад::Складской.svg") == [1]  # a qualified key marks nothing


# --- the fix ------------------------------------------------------------------------------------


@needs_data
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_fix_removes_the_whole_line_of_the_import(tmp_path, newline):
    code = ("импорт Склад\nимпорт Склад::Партии  \n\nметод Т()\n    РасчетПартий.Пересчитать()\n;\n"
            ).replace("\n", newline)
    _write(tmp_path, _files(""))
    module = tmp_path / BASE / "Продажи" / "Заказы.xbsl"
    module.write_bytes(code.encode("utf-8"))
    diags = engine.run(discover([str(tmp_path)]), select={RULE})
    assert len(diags) == 1 and diags[0].fix is not None
    text = module.read_bytes().decode("utf-8")
    fix = diags[0].fix
    assert text[fix.start:fix.end] == "импорт Склад" + newline
    fixed = text[:fix.start] + fix.new + text[fix.end:]
    assert fixed.startswith("импорт Склад::Партии  " + newline)


@needs_data
def test_a_line_that_holds_more_than_the_import_gets_no_fix():
    sources = [engine.load_text(name, text) for name, text in _files(
        "импорт Склад // оставлено до переноса\n\nметод Т()\n;\n").items()]
    diags = engine.run_sources(sources, select={RULE})
    assert [(d.line, d.fix) for d in diags] == [(1, None)]


# --- the reading of type texts (no language data needed) ----------------------------------------


def test_type_chains_split_the_plain_chains_from_the_qualified_ones():
    plain, qualified = _type_chains("Массив<Номенклатура.Ссылка>|Склад::Партии::ПартииТоваров.Ссылка?")
    assert plain == {"Массив", "Номенклатура.Ссылка"}
    assert qualified == {"Склад::Партии::ПартииТоваров.Ссылка"}
    assert _type_chains("") == (set(), set())


def test_qualified_name_parts():
    assert _qualified_name("Склад::Партии::ПартииТоваров.Ссылка") == (
        "Склад::Партии", "ПартииТоваров", "Ссылка")
    assert _qualified_name("Склад::Номенклатура") == ("Склад", "Номенклатура", "")
