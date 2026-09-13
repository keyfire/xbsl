"""Moving an object between packages and renaming a package: the scaffolding and its surfaces.

A package is a folder of a subsystem, and an element of a package lives in its own namespace
(`Подсистема::Пакет`): another subsystem reaches it only through `импорт Склад::Партии`, while
inside one subsystem the root and the packages see each other. So a move changes more than
paths. op_move_object runs the linter's import and visibility rules over the sources before
and after the move and repairs what the move brought - an import of the new place, a
qualified name that spells the old one, the usage of a subsystem - and op_rename_package
renames the folder and every name that spells it.

The fixture is one project, `Демо::Учет`: subsystem `Склад` keeps a catalog with its list form
and a common module at its root, a package `Партии` with a catalog and a common module, and a
nested package `Партии::Архив`; subsystem `Продажи` uses `Склад`.

The code rules parse the modules, and the parser needs the language data, so the tests that
assert on module imports carry `needs_data`; without the data the move still judges the yaml
and says in a note that the modules were not checked.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli, engine, scaffold
from xbsl.scaffold import ScaffoldError, apply_result

PROJECT_FILES = {
    "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
    "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
    "Склад/Номенклатура.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000101\n"
        "Имя: Номенклатура\nОбластьВидимости: ВПроекте\n"
    ),
    "Склад/НоменклатураФормаСписка.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000102\n"
        "Имя: НоменклатураФормаСписка\nОбластьВидимости: ВПроекте\nНаследует:\n"
        "    Тип: ФормаСписка<Демо::Учет::Склад::НоменклатураФормаСписка.ДанныеСтрокиСписка>\n"
    ),
    "Склад/Остатки.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000103\n"
        "Имя: Остатки\nОбластьВидимости: ВПроекте\n"
    ),
    "Склад/Остатки.xbsl": (
        "@ВПроекте\nметод Пересчитать(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n"
    ),
    "Склад/Партии/ПартииТоваров.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000104\n"
        "Имя: ПартииТоваров\nОбластьВидимости: ВПроекте\n"
    ),
    "Склад/Партии/РасчетПартий.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000105\n"
        "Имя: РасчетПартий\nОбластьВидимости: ВПроекте\n"
    ),
    "Склад/Партии/РасчетПартий.xbsl": (
        "@ВПроекте\nметод Партия(): ПартииТоваров.Ссылка?\n    возврат Неопределено\n;\n"
    ),
    "Склад/Партии/Архив/АрхивПартий.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000106\n"
        "Имя: АрхивПартий\nОбластьВидимости: ВПроекте\n"
    ),
    "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
    "Продажи/Заказы.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000107\nИмя: Заказы\n"
    ),
    "Продажи/Заказы.xbsl": (
        "импорт Склад\n\nметод Товар(): Номенклатура.Ссылка?\n    Остатки.Пересчитать()\n"
        "    возврат Неопределено\n;\n"
    ),
    "Продажи/ФормаЗаказа.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000108\n"
        "Имя: ФормаЗаказа\nИмпорт:\n    - Склад\nНаследует:\n    Тип: Группа\nСвойства:\n"
        "    -\n        Имя: Товар\n        Тип: Номенклатура.Ссылка?\n"
    ),
}


def _project(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    project_dir = tmp_path / "Демо" / "Учет"
    for rel, text in {**PROJECT_FILES, **(extra or {})}.items():
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return project_dir


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _content(result, path: Path) -> str:
    return next(c.content for c in result.changes if c.path == path)


# --- moving an object -------------------------------------------------------------------------


def test_moving_into_a_package_takes_the_family_and_imports_the_package_in_yaml(tmp_path):
    project = _project(tmp_path)
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")

    assert sorted((r.old_path.name, r.new_path) for r in result.renames) == [
        ("Номенклатура.yaml", stock / "Партии" / "Номенклатура.yaml"),
        ("НоменклатураФормаСписка.yaml", stock / "Партии" / "НоменклатураФормаСписка.yaml"),
    ]
    form = _content(result, project / "Продажи" / "ФормаЗаказа.yaml")
    assert "Импорт:\n    - Склад\n    - Склад::Партии\n" in form
    # The full type name of the moved list form spells the new place; the file is edited
    # at the path it moves to.
    moved_form = _content(result, stock / "Партии" / "НоменклатураФормаСписка.yaml")
    assert "Демо::Учет::Склад::Партии::НоменклатураФормаСписка.ДанныеСтрокиСписка" in moved_form
    assert any("Дописан импорт Склад::Партии" in n and "ФормаЗаказа.yaml" in n for n in result.notes)
    # Nothing is written: the operation computes.
    assert (stock / "Номенклатура.yaml").is_file()


@pytest.mark.needs_data  # the code rules parse the modules
def test_moving_into_a_package_imports_it_in_the_modules_of_other_subsystems(tmp_path):
    project = _project(tmp_path)
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")

    orders = _content(result, project / "Продажи" / "Заказы.xbsl")
    assert orders.startswith("импорт Склад\nимпорт Склад::Партии\n\nметод Товар()")
    # Inside the subsystem the root sees the package without an import.
    assert all(c.path.name != "Остатки.xbsl" for c in result.changes)


@pytest.mark.needs_data
def test_after_the_move_the_import_rules_find_nothing(tmp_path):
    project = _project(tmp_path)
    stock = project / "Склад"
    apply_result(scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии"))

    assert (stock / "Партии" / "Номенклатура.yaml").is_file()
    assert not (stock / "Номенклатура.yaml").exists()
    sources = engine.find_sources(tmp_path, "*.yaml") + engine.find_sources(tmp_path, "*.xbsl")
    found = engine.run(sources, select={"code/missing-import", "yaml/missing-import"})
    assert found == []


@pytest.mark.needs_data
def test_an_import_the_move_made_unnecessary_is_named_and_kept(tmp_path):
    """`импорт Склад` served only the catalog that moved away into the package."""
    project = _project(tmp_path, {
        "Продажи/Заказы.xbsl": (
            "импорт Склад\n\nметод Товар(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n"
        ),
    })
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    orders = _content(result, project / "Продажи" / "Заказы.xbsl")
    assert orders.startswith("импорт Склад\nимпорт Склад::Партии\n")
    assert any("code/unused-import" in n and "Заказы.xbsl:1 Склад" in n for n in result.notes)


@pytest.mark.needs_data  # the import rule reads the project module through the parser
def test_the_project_module_gets_the_import_of_the_package(tmp_path):
    project = _project(tmp_path, {
        "Проект.xbsl": "метод Т(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n",
    })
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    module = _content(result, project / "Проект.xbsl")
    assert module.startswith("импорт Склад::Партии\n\nметод Т()")


_BALANCES = {
    "ОстаткиТоваров.yaml": (
        "ВидЭлемента: ВиртуальнаяТаблица\nИд: 6f0b6a44-0000-4000-8000-000000000109\n"
        "Имя: ОстаткиТоваров\nОбластьВидимости: ВПроекте\n"
    ),
    "ОстаткиТоваров.xbql": "ВЫБРАТЬ\n    Н.Ссылка КАК Товар\nИЗ\n    Номенклатура КАК Н\n",
}


@pytest.mark.needs_data  # the import rule tokenizes the query
def test_a_query_naming_a_moved_table_imports_the_package_in_its_yaml(tmp_path):
    """The query of a virtual table resolves its tables against the imports of its yaml."""
    project = _project(tmp_path, {
        "Продажи/ОстаткиТоваров.yaml": _BALANCES["ОстаткиТоваров.yaml"] + "Импорт:\n    - Склад\n",
        "Продажи/ОстаткиТоваров.xbql": _BALANCES["ОстаткиТоваров.xbql"],
    })
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    table = _content(result, project / "Продажи" / "ОстаткиТоваров.yaml")
    assert "Импорт:\n    - Склад\n    - Склад::Партии\n" in table


@pytest.mark.needs_data
def test_a_query_of_the_same_subsystem_gets_no_import(tmp_path):
    """Within one subsystem a query reads the tables of its root and its packages without an
    import: modules of a compiled library and of a project split into packages read tables of
    another package of their subsystem that way, and yaml/missing-import holds the same."""
    project = _project(tmp_path, {f"Склад/{name}": text for name, text in _BALANCES.items()})
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    assert all(change.path != stock / "ОстаткиТоваров.yaml" for change in result.changes)


def test_a_qualified_reference_follows_the_moved_element(tmp_path):
    project = _project(tmp_path, {
        "Продажи/КарточкаЗаказа.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000110\n"
            "Имя: КарточкаЗаказа\nНаследует:\n    Тип: Группа\nСвойства:\n    -\n"
            "        Имя: Товар\n        Тип: Склад::Номенклатура.Ссылка?\n"
        ),
    })
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    card = _content(result, project / "Продажи" / "КарточкаЗаказа.yaml")
    assert "Тип: Склад::Партии::Номенклатура.Ссылка?" in card
    assert "Импорт" not in card  # a qualified name needs no import


@pytest.mark.needs_data
def test_a_move_to_another_subsystem_imports_both_ways_and_declares_the_usage(tmp_path):
    """The module leaves `Склад` for `Продажи`: it now looks back at a package of `Склад`, and
    the root of `Склад` reaches it across the boundary."""
    project = _project(tmp_path, {
        "Склад/Остатки.xbsl": (
            "@ВПроекте\nметод Пересчитать()\n    РасчетПартий.Партия()\n;\n"
        ),
    })
    stock = project / "Склад"
    sales = project / "Продажи"
    result = scaffold.op_move_object(tmp_path, stock / "Партии" / "РасчетПартий.yaml", sales)

    moved = _content(result, sales / "РасчетПартий.xbsl")
    assert moved.startswith("импорт Склад::Партии\n\n@ВПроекте")
    assert _content(result, stock / "Остатки.xbsl").startswith("импорт Продажи\n\n@ВПроекте")
    descriptor = _content(result, stock / "Подсистема.yaml")
    assert descriptor.startswith("Использование:\n    - Продажи\n")


def test_moving_a_hidden_element_out_of_its_subsystem_is_refused(tmp_path):
    project = _project(tmp_path, {
        "Склад/Закрытый.yaml": (
            "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000111\nИмя: Закрытый\n"
        ),
        "Склад/ФормаЗакрытого.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000112\n"
            "Имя: ФормаЗакрытого\nНаследует:\n    Тип: Группа\nСвойства:\n    -\n"
            "        Имя: Ссылка\n        Тип: Закрытый.Ссылка?\n"
        ),
    })
    with pytest.raises(ScaffoldError, match="ОбластьВидимости: ВПроекте"):
        scaffold.op_move_object(tmp_path, project / "Склад" / "Закрытый.yaml", project / "Продажи")


def test_a_taken_name_in_the_target_is_refused(tmp_path):
    project = _project(tmp_path, {
        "Склад/Партии/Номенклатура.yaml": (
            "ВидЭлемента: Перечисление\nИд: 6f0b6a44-0000-4000-8000-000000000113\n"
            "Имя: Номенклатура\n"
        ),
    })
    stock = project / "Склад"
    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")

    other = _project(tmp_path / "второй", {
        "Склад/Партии/Товары.yaml": (
            "ВидЭлемента: Перечисление\nИд: 6f0b6a44-0000-4000-8000-000000000114\n"
            "Имя: Номенклатура\n"
        ),
    })
    with pytest.raises(ScaffoldError, match="уже занято"):
        scaffold.op_move_object(
            tmp_path / "второй", other / "Склад" / "Номенклатура.yaml", other / "Склад" / "Партии",
        )


def test_a_namesake_elsewhere_in_the_subsystem_is_noted_as_ambiguous(tmp_path):
    project = _project(tmp_path, {
        "Склад/Партии/Архив/Номенклатура.yaml": (
            "ВидЭлемента: Перечисление\nИд: 6f0b6a44-0000-4000-8000-000000000115\n"
            "Имя: Номенклатура\n"
        ),
    })
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    assert any("неоднозначным" in n for n in result.notes)


def test_a_move_outside_the_packages_of_the_project_is_refused(tmp_path):
    project = _project(tmp_path)
    catalog = project / "Склад" / "Номенклатура.yaml"
    with pytest.raises(ScaffoldError, match="не каталог подсистемы"):
        scaffold.op_move_object(tmp_path, catalog, project)
    with pytest.raises(ScaffoldError, match="служебном каталоге"):
        scaffold.op_move_object(tmp_path, catalog, project / "Склад" / "Ресурсы")
    with pytest.raises(ScaffoldError, match="уже лежит"):
        scaffold.op_move_object(tmp_path, catalog, project / "Склад")
    with pytest.raises(ScaffoldError, match="Недопустимое имя пакета"):
        scaffold.op_move_object(tmp_path, catalog, project / "Склад" / "Новые партии")
    with pytest.raises(ScaffoldError, match="Подсистемы 'Доставка' нет"):
        scaffold.op_move_object(tmp_path, catalog, project / "Доставка")


def test_a_new_package_of_a_project_with_a_dictionary_is_reminded_of_the_pair(tmp_path):
    project = _project(tmp_path)
    (tmp_path / "xbsl-translation.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Склад: Warehouse\n", encoding="utf-8",
    )
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Сверки")
    assert any("словаре перевода" in n and "Сверки" in n for n in result.notes)
    known = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Склад")
    assert not any("словаре перевода" in n for n in known.notes)


def test_moving_out_of_a_package_leaves_no_empty_folder(tmp_path):
    project = _project(tmp_path)
    archive = project / "Склад" / "Партии" / "Архив"
    apply_result(scaffold.op_move_object(tmp_path, archive / "АрхивПартий.yaml", project / "Склад"))
    assert (project / "Склад" / "АрхивПартий.yaml").is_file()
    assert not archive.exists()


def test_vacated_dirs_are_the_parents_no_renamed_file_lands_in(tmp_path):
    rename = scaffold.FileRename
    moves = [
        rename(tmp_path / "А" / "Б" / "В" / "Х.yaml", tmp_path / "А" / "Г" / "В" / "Х.yaml"),
        rename(tmp_path / "А" / "Б" / "Ф.yaml", tmp_path / "А" / "Г" / "Ф.yaml"),
    ]
    assert scaffold.vacated_dirs(moves) == [tmp_path / "А" / "Б" / "В", tmp_path / "А" / "Б"]
    within = [rename(tmp_path / "А" / "Х.yaml", tmp_path / "А" / "Ц.yaml")]
    assert scaffold.vacated_dirs(within) == []


# --- the text edits the moves are made of -----------------------------------------------------


def test_a_module_import_joins_the_import_block_or_opens_the_module():
    joined = scaffold._with_module_imports("импорт Склад\r\n\r\nметод Т()\r\n;\r\n",
                                           ["Склад::Партии"], "ru")
    assert joined == "импорт Склад\r\nимпорт Склад::Партии\r\n\r\nметод Т()\r\n;\r\n"
    opened = scaffold._with_module_imports("метод Т()\n;\n", ["Склад::Партии"], "en")
    assert opened == "import Склад::Партии\n\nметод Т()\n;\n"
    full = "импорт Демо::Учет::Склад::Партии\n"
    assert scaffold._with_module_imports(full, ["Склад::Партии"], "ru", "Демо::Учет") == full


def test_a_yaml_import_keeps_the_shape_of_the_section():
    head = "ВидЭлемента: КомпонентИнтерфейса\nИд: 1\nИмя: Ф\n"
    block = head + "Импорт:\n  - Склад\nНаследует:\n    Тип: Группа\n"
    assert scaffold._with_yaml_imports(block, ["Склад::Партии"]) == (
        head + "Импорт:\n  - Склад\n  - Склад::Партии\nНаследует:\n    Тип: Группа\n"
    )
    flow = head + "Импорт: [Склад]\nНаследует:\n    Тип: Группа\n"
    assert "Импорт: [Склад, Склад::Партии]\n" in scaffold._with_yaml_imports(flow, ["Склад::Партии"])
    bare = head + "ОбластьВидимости: ВПроекте\nНаследует:\n    Тип: Группа\n"
    assert scaffold._with_yaml_imports(bare, ["Склад::Партии"]) == (
        head + "ОбластьВидимости: ВПроекте\nИмпорт:\n    - Склад::Партии\n"
        "Наследует:\n    Тип: Группа\n"
    )


def test_code_spans_leave_literals_but_not_interpolations():
    text = 'а = "x %{Склад::Задачи.Имя} y" + Склад::Задачи // "c"\nб = \'Склад::Задачи\'\n'
    code = "".join(text[s:e] for s, e, is_code in scaffold._code_spans(text) if is_code)
    assert "Склад::Задачи.Имя" in code and "// \"c\"" in code
    assert "'Склад::Задачи'" not in code and "x %{" not in code


# --- renaming a package -----------------------------------------------------------------------


RENAME_EXTRA = {
    "Проект.xbsl": "импорт Склад::Партии\n\nметод Т()\n    РасчетПартий.Партия()\n;\n",
    "Склад/Партии/Ресурсы/Схема.svg": "<svg/>",
    "Склад/Партии/ПартииТоваровФормаСписка.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000120\n"
        "Имя: ПартииТоваровФормаСписка\nНаследует:\n"
        "    Тип: ФормаСписка<Демо::Учет::Склад::Партии::ПартииТоваровФормаСписка.ДанныеСтрокиСписка>\n"
    ),
    "Продажи/Заказы.xbsl": (
        "импорт Склад::Партии\nимпорт Демо::Учет::Склад::Партии::Архив\n\n"
        "метод Т(): ПартииТоваров.Ссылка?\n    знч С = \"%{Склад::Партии::ПартииТоваров.Имя}\"\n"
        "    возврат Неопределено\n;\n"
    ),
    "Продажи/ФормаЗаказа.yaml": (
        "ВидЭлемента: КомпонентИнтерфейса\nИд: 6f0b6a44-0000-4000-8000-000000000121\n"
        "Имя: ФормаЗаказа\nИмпорт: [Склад::Партии]\nНаследует:\n    Тип: Группа\nСвойства:\n"
        "    -\n        Имя: Товар\n        Тип: Склад::ПартииТоваров.Ссылка?\n"
    ),
}


def test_renaming_a_package_moves_its_files_and_rewrites_its_names(tmp_path):
    project = _project(tmp_path, RENAME_EXTRA)
    stock = project / "Склад"
    result = scaffold.op_rename_package(tmp_path, stock / "Партии", "Лоты")

    assert {r.new_path for r in result.renames} >= {
        stock / "Лоты" / "Ресурсы" / "Схема.svg",
        stock / "Лоты" / "Архив" / "АрхивПартий.yaml",
    }
    orders = _content(result, project / "Продажи" / "Заказы.xbsl")
    assert orders.startswith("импорт Склад::Лоты\nимпорт Демо::Учет::Склад::Лоты::Архив\n")
    assert '"%{Склад::Лоты::ПартииТоваров.Имя}"' in orders
    form = _content(result, project / "Продажи" / "ФормаЗаказа.yaml")
    # The flow list is renamed; `Склад::ПартииТоваров` names another place and stays.
    assert "Импорт: [Склад::Лоты]" in form and "Тип: Склад::ПартииТоваров.Ссылка?" in form
    list_form = _content(result, stock / "Лоты" / "ПартииТоваровФормаСписка.yaml")
    assert "Демо::Учет::Склад::Лоты::ПартииТоваровФормаСписка.ДанныеСтрокиСписка" in list_form
    assert _content(result, project / "Проект.xbsl").startswith("импорт Склад::Лоты\n")

    apply_result(result)
    assert (stock / "Лоты" / "Архив" / "АрхивПартий.yaml").is_file()
    assert not (stock / "Партии").exists()


def test_another_project_under_the_root_keeps_its_own_short_name(tmp_path):
    _project(tmp_path, RENAME_EXTRA)
    other = tmp_path / "Второй" / "Проект"
    (other / "Основное").mkdir(parents=True)
    (other / "Проект.yaml").write_text(
        "Поставщик: Второй\nИмя: Проект\n", encoding="utf-8", newline="\n",
    )
    (other / "Основное" / "Модуль.xbsl").write_text(
        "импорт Склад::Партии\nимпорт Демо::Учет::Склад::Партии\n", encoding="utf-8", newline="\n",
    )
    result = scaffold.op_rename_package(tmp_path, tmp_path / "Демо" / "Учет" / "Склад" / "Партии", "Лоты")
    module = _content(result, other / "Основное" / "Модуль.xbsl")
    assert module == "импорт Склад::Партии\nимпорт Демо::Учет::Склад::Лоты\n"


def test_rename_package_refuses_what_is_not_a_package(tmp_path):
    project = _project(tmp_path)
    stock = project / "Склад"
    (stock / "Ресурсы").mkdir()
    (stock / "Лоты").mkdir()
    with pytest.raises(ScaffoldError, match="не пакет"):
        scaffold.op_rename_package(tmp_path, stock, "Хранение")
    with pytest.raises(ScaffoldError, match="служебный каталог"):
        scaffold.op_rename_package(tmp_path, stock / "Ресурсы", "Картинки")
    with pytest.raises(ScaffoldError, match="уже существует"):
        scaffold.op_rename_package(tmp_path, stock / "Партии", "Лоты")
    with pytest.raises(ScaffoldError, match="регистром"):
        scaffold.op_rename_package(tmp_path, stock / "Партии", "партии")
    with pytest.raises(ScaffoldError, match="Недопустимое имя пакета"):
        scaffold.op_rename_package(tmp_path, stock / "Партии", "Новые партии")


# --- subsystems and new packages ----------------------------------------------------------------


def test_a_subsystem_is_created_only_at_the_project_root(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ScaffoldError, match="пакет"):
        scaffold.op_add_subsystem(project / "Склад", "Отчеты")
    created = scaffold.op_add_subsystem(project, "Отчеты")
    assert created.changes[0].path == project / "Отчеты" / "Подсистема.yaml"


def test_an_object_in_a_new_folder_starts_a_package_with_a_checked_name(tmp_path):
    project = _project(tmp_path)
    (tmp_path / "xbsl-translation.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Склад: Warehouse\n", encoding="utf-8",
    )
    stock = project / "Склад"
    with pytest.raises(ScaffoldError, match="Недопустимое имя пакета"):
        scaffold.op_new_object(stock / "Сверки остатков", "Справочник", "Сверки")
    result = scaffold.op_new_object(stock / "Сверки", "Справочник", "СверкиОстатков")
    assert any("словаре перевода" in n and "Сверки" in n for n in result.notes)
    existing = scaffold.op_new_object(stock / "Партии", "Справочник", "Лоты")
    assert not any("словаре перевода" in n for n in existing.notes)


def test_the_import_findings_carry_their_namespaces(tmp_path):
    """The move reads the repair from the finding's data, never from its message."""
    _project(tmp_path, {
        "Склад/Партии/Номенклатура2.yaml": (
            "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000122\n"
            "Имя: Номенклатура2\nОбластьВидимости: ВПроекте\n"
        ),
        "Продажи/ФормаЗаказа.yaml": PROJECT_FILES["Продажи/ФормаЗаказа.yaml"].replace(
            "Номенклатура.Ссылка?", "Номенклатура2.Ссылка?"),
    })
    found = engine.run(engine.find_sources(tmp_path, "*.yaml"), select={"yaml/missing-import"})
    assert [d.data for d in found] == [{"namespaces": ["Склад::Партии"]}]


# --- surfaces ---------------------------------------------------------------------------------


def _run_cli(capsys, *argv) -> tuple[int, dict]:
    code = cli.main([str(a) for a in argv])
    return code, json.loads(capsys.readouterr().out.strip())


def test_cli_move_object_dry_run_writes_nothing(tmp_path, capsys):
    project = _project(tmp_path)
    stock = project / "Склад"
    code, plan = _run_cli(capsys, "move-object", tmp_path, stock / "Номенклатура.yaml",
                          stock / "Партии", "--dry-run")
    assert code == 0
    assert {Path(r["to"]).name for r in plan["renames"]} == {
        "Номенклатура.yaml", "НоменклатураФормаСписка.yaml"}
    assert any(f["path"].endswith("ФормаЗаказа.yaml") and "Склад::Партии" in f["content"]
               for f in plan["files"])
    assert (stock / "Номенклатура.yaml").is_file() and not (stock / "Партии" / "Номенклатура.yaml").exists()

    code, err = _run_cli(capsys, "move-object", tmp_path, stock / "Нет.yaml", stock / "Партии")
    assert code == 2 and "не найден" in err["error"]


@pytest.mark.needs_data  # the written module is linted
def test_cli_move_object_applies_and_lints(tmp_path, capsys):
    project = _project(tmp_path)
    stock = project / "Склад"
    code, out = _run_cli(capsys, "move-object", tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    assert code == 0 and out["renames"] and "lint" in out
    assert (stock / "Партии" / "Номенклатура.yaml").is_file()


def test_cli_rename_package_dry_run_writes_nothing(tmp_path, capsys):
    project = _project(tmp_path, RENAME_EXTRA)
    stock = project / "Склад"
    code, plan = _run_cli(capsys, "rename-package", tmp_path, stock / "Партии", "Лоты", "--dry-run")
    assert code == 0 and plan["renames"]
    assert (stock / "Партии").is_dir() and not (stock / "Лоты").exists()
    code, err = _run_cli(capsys, "rename-package", tmp_path, stock, "Лоты")
    assert code == 2 and "не пакет" in err["error"]


@pytest.mark.needs_data  # the written modules are linted
def test_mcp_meta_move_object_and_rename_package(mcp_module, tmp_path):
    project = _project(tmp_path, RENAME_EXTRA)
    stock = project / "Склад"

    plan = mcp_module.meta_move_object(str(tmp_path), "Демо/Учет/Склад/Номенклатура.yaml",
                                       "Демо/Учет/Склад/Партии", dry_run=True)
    assert plan["root"] == str(tmp_path)
    assert all("content" not in f for f in plan["files"])
    assert (stock / "Номенклатура.yaml").is_file()

    moved = mcp_module.meta_move_object(str(tmp_path), "Демо/Учет/Склад/Номенклатура.yaml",
                                        "Демо/Учет/Склад/Партии")
    assert moved["renames"] and "lint" in moved
    assert (stock / "Партии" / "Номенклатура.yaml").is_file()

    renamed = mcp_module.meta_rename_package(str(tmp_path), "Демо/Учет/Склад/Партии", "Лоты")
    assert renamed["renames"] and (stock / "Лоты" / "Номенклатура.yaml").is_file()
    assert "Склад::Лоты" in _read(project / "Продажи" / "Заказы.xbsl")

    err = mcp_module.meta_rename_package(str(tmp_path), "Демо/Учет/Склад", "Хранение")
    assert "не пакет" in err["error"] and err["root"] == str(tmp_path)


def test_mcp_tools_are_registered_with_root(mcp_module):
    for name in ("meta_move_object", "meta_rename_package"):
        assert name in mcp_module.mcp.tools


pygls = pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")


def _features():
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    return getattr(fm, "features", fm)


def test_lsp_meta_project_info_move_and_rename_compute_only(tmp_path):
    project = _project(tmp_path, RENAME_EXTRA)
    stock = project / "Склад"
    features = _features()

    info = features["xbsl/metaProjectInfo"]({"root": str(tmp_path)})
    placed = {o["name"]: o["package"] for o in info["objects"]}
    assert placed["ПартииТоваров"] == "Партии" and placed["Номенклатура"] is None
    assert [p["package"] for p in info["packages"]] == ["Партии", "Партии::Архив"]

    moved = features["xbsl/metaMoveObject"](
        {"root": str(tmp_path), "path": str(stock / "Номенклатура.yaml"),
         "targetDir": str(stock / "Партии")}
    )
    assert moved["renames"] and moved["files"][0]["content"]
    assert (stock / "Номенклатура.yaml").is_file()

    renamed = features["xbsl/metaRenamePackage"](
        {"root": str(tmp_path), "packageDir": str(stock / "Партии"), "newName": "Лоты"}
    )
    assert renamed["renames"] and (stock / "Партии").is_dir()
    refused = features["xbsl/metaRenamePackage"](
        {"root": str(tmp_path), "packageDir": str(stock), "newName": "Лоты"}
    )
    assert "не пакет" in refused["error"]
