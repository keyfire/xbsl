"""yaml/missing-import reads the tables of a dynamic list.

A dynamic list names its tables in yaml - the table of its main table and of each joined table -
and the compiler resolves them against the imports of the yaml like any other reference: a
server build refused a list whose main table, and another whose joined table, lay in a package
of another subsystem (`Namespace ... is not imported`, at the value of the table), while the
import of the package, a qualified table and a table of another package of the same subsystem
compiled clean. The rule used to read only the type positions, the navigation targets and the
bindings, so a list whose table was its only reference to the package passed.

The fixture is one project, `Демо::Учет`: subsystem `Склад` keeps a catalog at its root and a
package `Партии` with a catalog, a register and a non-public catalog; subsystem `Продажи` uses
`Склад`. The yaml side runs in every checkout; the English keys and the stdlib names come from
the language data.
"""

from pathlib import Path

import pytest

from xbsl import engine, i18n, scaffold

RULE = "yaml/missing-import"
BASE = "Демо/Учет"


def _catalog(name: str, scope: str | None = "ВПроекте", kind: str = "Справочник") -> str:
    return f"ВидЭлемента: {kind}\nИмя: {name}\n" + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _project(extra: dict[str, str]) -> dict[str, str]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/ОстаткиПартий.yaml": _catalog("ОстаткиПартий", kind="РегистрСведений"),
        "Склад/Партии/Закрытый.yaml": _catalog("Закрытый", scope=None),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        **extra,
    }
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _imports(namespaces) -> str:
    return "Импорт:\n" + "".join(f"    - {ns}\n" for ns in namespaces) if namespaces else ""


def _list_component(table: str, *, imports=(), joined=()) -> str:
    """A table component whose source is a dynamic list."""
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПодборТоваров\n" + _imports(imports)
        + "Наследует:\n    Тип: Таблица<ДинамическийСписок>\n    Источник:\n"
        "        ОсновнаяТаблица:\n"
        f"            Таблица: {table}\n"
        "            Псевдоним: Основная\n"
    )
    if joined:
        text += "        ПрисоединенныеТаблицы:\n"
        for name in joined:
            text += (
                "            -\n                Тип: ПрисоединеннаяТаблица\n"
                f"                Таблица: {name}\n"
            )
    return text + (
        "        Поля:\n            -\n                Тип: ПолеДинамическогоСписка\n"
        "                Выражение: Основная.Ссылка\n"
    )


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


def _value_position(text: str, line_text: str) -> tuple[int, int]:
    """(line, column) of the value of the first `key: value` line of the fixture, 1-based."""
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip() == line_text:
            return number, line.index(line_text.split(": ", 1)[1]) + 1
    raise AssertionError(line_text)


def _findings(diags):
    return [(d.rule_id, d.path.replace("\\", "/").removeprefix(f"{BASE}/"), d.line, d.col)
            for d in diags]


# --- the tables of a list ---------------------------------------------------------------------


def test_a_main_table_of_a_foreign_package_needs_the_package_import():
    form = _list_component("ПартииТоваров", imports=["Склад"])
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert _findings(diags) == [
        (RULE, "Продажи/ПодборТоваров.yaml", *_value_position(form, "Таблица: ПартииТоваров"))
    ]
    assert "- Склад::Партии" in diags[0].message and "'ПартииТоваров'" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_a_joined_table_of_a_foreign_package_needs_the_package_import():
    form = _list_component("Номенклатура", imports=["Склад"], joined=["ПартииТоваров"])
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert [(d.line, d.col) for d in diags] == [_value_position(form, "Таблица: ПартииТоваров")]
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_the_imports_of_the_root_and_the_package_cover_both_tables():
    form = _list_component("Номенклатура", imports=["Склад", "Склад::Партии"],
                           joined=["ПартииТоваров"])
    assert _lint(_project({"Продажи/ПодборТоваров.yaml": form})) == []


def test_a_list_without_imports_asks_for_the_subsystem_of_a_root_table():
    form = _list_component("Номенклатура")
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert len(diags) == 1 and diags[0].data == {"namespaces": ["Склад"]}


def test_a_table_of_the_own_subsystem_needs_no_import():
    """The root and the packages of one subsystem see each other (a server build compiled a
    list of one package reading a table of another package of its subsystem)."""
    form = _list_component("ПартииТоваров", joined=["Номенклатура"])
    for place in ("Склад", "Склад/Партии", "Склад/Приемка"):
        assert _lint(_project({f"{place}/ПодборТоваров.yaml": form})) == [], place


def test_a_qualified_table_needs_no_import():
    form = _list_component("Склад::Партии::ПартииТоваров", joined=["Демо::Учет::Склад::Номенклатура"])
    assert _lint(_project({"Продажи/ПодборТоваров.yaml": form})) == []


def test_a_virtual_table_of_a_register_resolves_by_its_root():
    form = _list_component("ОстаткиПартий.СрезПоследних", imports=["Склад"])
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert len(diags) == 1
    assert "'ОстаткиПартий.СрезПоследних'" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_the_list_in_the_default_value_of_a_property_is_read():
    """The shape of a generated list form: the list is the default value of a property."""
    form = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПартииФормаПодбора\nИмпорт:\n    - Склад\n"
        "Наследует:\n    Тип: ФормаСписка\nСвойства:\n    -\n        Имя: Список\n"
        "        Тип: ДинамическийСписок<ПартииФормаПодбора.ДанныеСтрокиСписка>\n"
        "        ЗначениеПоУмолчанию:\n            ИмяТипаДанныхСтроки: ДанныеСтрокиСписка\n"
        "            ОсновнаяТаблица:\n                Таблица: ПартииТоваров\n"
    )
    diags = _lint(_project({"Продажи/ПартииФормаПодбора.yaml": form}))
    assert [(d.line, d.col) for d in diags] == [_value_position(form, "Таблица: ПартииТоваров")]


def test_a_table_outside_a_dynamic_list_is_not_read():
    """A mapping with no main table is not a list: here the joined tables of the reference
    input settings of a field, which the compiler was not probed on."""
    form = (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ПодборТоваров\nИмпорт:\n    - Склад\n"
        "Наследует:\n    Тип: Группа\n    Содержимое:\n        -\n"
        "            Тип: ПолеВвода<Номенклатура.Ссылка?>\n"
        "            НастройкиВводаСсылки:\n                ПрисоединенныеТаблицы:\n"
        "                    -\n                        Таблица: ПартииТоваров\n"
        "            Таблица: ПартииТоваров\n"
    )
    assert _lint(_project({"Продажи/ПодборТоваров.yaml": form})) == []


def test_a_binding_and_a_hidden_table_are_not_import_findings():
    """A binding is an expression, not a name; a table nobody may reach from another subsystem
    is a visibility matter, not an import one."""
    for table in ("=ИмяТаблицы", "Закрытый"):
        form = _list_component(table, imports=["Склад"])
        assert _lint(_project({"Продажи/ПодборТоваров.yaml": form})) == [], table


def test_a_type_and_a_table_of_one_package_make_one_finding():
    form = _list_component("ПартииТоваров", imports=["Склад"]).replace(
        "Наследует:",
        "Свойства:\n    -\n        Имя: Партия\n        Тип: ПартииТоваров.Ссылка?\nНаследует:",
    )
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert len(diags) == 1 and diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_the_english_message_names_the_list():
    form = _list_component("ПартииТоваров", imports=["Склад"])
    i18n.set_lang("en")
    try:
        diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1 and "of a dynamic list" in diags[0].message
    assert "'- Склад::Партии'" in diags[0].message


@pytest.mark.needs_data  # the English spellings of the keys come from the compiler dictionary
def test_the_english_keys_of_a_list_are_read():
    form = (
        "ElementKind: InterfaceComponent\nName: ПодборТоваров\nImport:\n    - Склад\n"
        "Inherits:\n    Type: Table<DynamicList>\n    Source:\n        MainTable:\n"
        "            Table: Номенклатура\n        JoinedTables:\n            -\n"
        "                Table: ПартииТоваров\n"
    )
    diags = _lint(_project({"Продажи/ПодборТоваров.yaml": form}))
    assert [(d.line, d.col) for d in diags] == [_value_position(form, "Table: ПартииТоваров")]


@pytest.mark.needs_data  # the stdlib names come from the data
def test_a_platform_table_is_left_to_the_standard_namespace():
    """Without an import a name the platform owns resolves to the standard namespace."""
    files = _project({
        "Склад/Партии/Пользователи.yaml": _catalog("Пользователи"),
        "Продажи/ПодборТоваров.yaml": _list_component("Пользователи", imports=["Склад"]),
    })
    assert _lint(files) == []


# --- the move of an object reads the finding --------------------------------------------------


def test_a_moved_table_is_imported_in_a_foreign_list_that_reads_it(tmp_path):
    """The list is the only reference of the form to the moved catalog: the move writes the
    import of the new package through the finding of the rule."""
    files = _project({"Продажи/ПодборТоваров.yaml": _list_component("Номенклатура", imports=["Склад"])})
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    project = tmp_path / "Демо" / "Учет"
    stock = project / "Склад"
    result = scaffold.op_move_object(tmp_path, stock / "Номенклатура.yaml", stock / "Партии")
    form = next(c.content for c in result.changes
                if Path(c.path) == project / "Продажи" / "ПодборТоваров.yaml")
    assert "Импорт:\n    - Склад\n    - Склад::Партии\n" in form
    assert any("Дописан импорт Склад::Партии" in n and "ПодборТоваров.yaml" in n
               for n in result.notes)
