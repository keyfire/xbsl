"""The tables a list reads in yaml: the reference input settings and the visibility of a table.

Two edges of the rules that read the tables of a list, both settled by the IDE server on a probe
project.

The reference input settings of a field (`ReferencesInputSettings`, a setting per type) join tables
of their own to the list of choice. The server resolves such a joined table like a table of a
dynamic list: a table of a package of another subsystem without the import of the package is
refused as not imported, at the value of the table; with the import, and for a table of the own
subsystem, the setting compiles. yaml/missing-import used to read the tables of a dynamic list
alone.

A table of a list must be public like any other reference: a non-public table of another
subsystem is refused as not visible - the main table and a joined table of a dynamic list, a
qualified main table, a joined table of the reference input settings - and a non-public table of
the list's own subsystem compiles. yaml/foreign-not-public did not read the tables at all.

The fixture is the project `Демо::Учет`: subsystem `Склад` keeps a public catalog and a hidden one
at its root, a public and a hidden catalog in its package `Партии`; subsystem `Продажи` uses
`Склад`. The yaml side runs in every checkout; the English keys come from the language data.
"""

import pytest

from xbsl import engine, i18n

IMPORT = "yaml/missing-import"
VISIBILITY = "yaml/foreign-not-public"
BASE = "Демо/Учет"


def _catalog(name: str, scope: str | None = "ВПроекте", kind: str = "Справочник") -> str:
    return f"ВидЭлемента: {kind}\nИмя: {name}\n" + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _project(extra: dict[str, str]) -> dict[str, str]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/СкрытыйСклад.yaml": _catalog("СкрытыйСклад", scope=None),
        "Склад/ОстаткиСклада.yaml": _catalog("ОстаткиСклада", scope=None, kind="РегистрСведений"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/СкрытыеПартии.yaml": _catalog("СкрытыеПартии", scope=None),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        **extra,
    }
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _imports(namespaces) -> str:
    return "Импорт:\n" + "".join(f"    - {ns}\n" for ns in namespaces) if namespaces else ""


def _input_field(table: str, *, imports=()) -> str:
    """A component with a field whose reference input settings join a table."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: ВыборНоменклатуры\n" + _imports(imports)
        + "Наследует:\n    Тип: Группа\n    Содержимое:\n        -\n"
        "            Тип: ПолеВвода<Номенклатура.Ссылка?>\n"
        "            Имя: Поле\n"
        "            НастройкиВводаСсылок:\n"
        "                НастройкиПоТипу:\n"
        "                    -\n"
        "                        Ключ: Номенклатура.Ссылка\n"
        "                        Значение:\n"
        "                            ПсевдонимОсновнойТаблицы: Осн\n"
        "                            ПрисоединенныеТаблицы:\n"
        "                                -\n"
        f"                                    Таблица: {table}\n"
        "                                    Псевдоним: Прис\n"
    )


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
            text += f"            -\n                Таблица: {name}\n"
    return text


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id})


def _value_position(text: str, line_text: str) -> tuple[int, int]:
    """(line, column) of the value of the first `key: value` line of the fixture, 1-based."""
    for number, line in enumerate(text.split("\n"), start=1):
        if line.strip() == line_text:
            return number, line.index(line_text.split(": ", 1)[1]) + 1
    raise AssertionError(line_text)


# --- the joined tables of the reference input settings -----------------------------------------


def test_a_joined_table_of_the_input_settings_needs_the_package_import():
    field = _input_field("ПартииТоваров", imports=["Склад"])
    diags = _lint(IMPORT, _project({"Продажи/ВыборНоменклатуры.yaml": field}))
    assert [(d.rule_id, d.line, d.col) for d in diags] == [
        (IMPORT, *_value_position(field, "Таблица: ПартииТоваров"))
    ]
    assert "Присоединённая таблица 'ПартииТоваров' настроек ввода ссылки" in diags[0].message
    assert "'- Склад::Партии'" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_the_package_import_covers_the_joined_table_of_the_input_settings():
    field = _input_field("ПартииТоваров", imports=["Склад", "Склад::Партии"])
    assert _lint(IMPORT, _project({"Продажи/ВыборНоменклатуры.yaml": field})) == []


def test_a_joined_table_of_the_own_subsystem_asks_for_nothing():
    """A hidden table of another package of the own subsystem: neither an import nor a visibility
    finding (the IDE server compiled exactly that)."""
    for table in ("ПартииТоваров", "СкрытыеПартии"):
        files = _project({"Склад/ВыборНоменклатуры.yaml": _input_field(table)})
        assert _lint(IMPORT, files) == [] and _lint(VISIBILITY, files) == [], table


def test_the_english_message_names_the_input_settings():
    field = _input_field("ПартииТоваров", imports=["Склад"])
    i18n.set_lang("en")
    try:
        diags = _lint(IMPORT, _project({"Продажи/ВыборНоменклатуры.yaml": field}))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1 and "of the reference input settings" in diags[0].message
    assert "'- Склад::Партии'" in diags[0].message


@pytest.mark.needs_data  # the English spellings of the keys come from the compiler dictionary
def test_the_english_keys_of_the_input_settings_are_read():
    field = (
        "ElementKind: InterfaceComponent\nName: ВыборНоменклатуры\nImport:\n    - Склад\n"
        "Inherits:\n    Type: Group\n    Content:\n        -\n"
        "            Type: Edit<Номенклатура.Ссылка?>\n"
        "            ReferencesInputSettings:\n"
        "                SettingsByType:\n"
        "                    -\n"
        "                        Key: Номенклатура.Ссылка\n"
        "                        Value:\n"
        "                            MainTableAlias: Осн\n"
        "                            JoinedTables:\n"
        "                                -\n"
        "                                    Table: ПартииТоваров\n"
    )
    diags = _lint(IMPORT, _project({"Продажи/ВыборНоменклатуры.yaml": field}))
    assert [(d.line, d.col) for d in diags] == [_value_position(field, "Table: ПартииТоваров")]


# --- the visibility of a table of a list ----------------------------------------------------------


def test_a_hidden_main_table_of_another_subsystem_is_not_visible():
    form = _list_component("СкрытыйСклад", imports=["Склад"])
    diags = _lint(VISIBILITY, _project({"Продажи/ПодборТоваров.yaml": form}))
    assert [(d.rule_id, d.line, d.col) for d in diags] == [
        (VISIBILITY, *_value_position(form, "Таблица: СкрытыйСклад"))
    ]
    assert "'СкрытыйСклад'" in diags[0].message and "'Склад'" in diags[0].message
    assert diags[0].data == {"namespace": "Склад", "name": "СкрытыйСклад"}


def test_a_hidden_joined_table_of_a_package_is_not_visible():
    form = _list_component("Номенклатура", imports=["Склад", "Склад::Партии"],
                           joined=["СкрытыеПартии"])
    diags = _lint(VISIBILITY, _project({"Продажи/ПодборТоваров.yaml": form}))
    assert [(d.line, d.col) for d in diags] == [_value_position(form, "Таблица: СкрытыеПартии")]
    assert diags[0].data == {"namespace": "Склад::Партии", "name": "СкрытыеПартии"}


def test_a_qualified_hidden_table_is_judged_by_the_place_it_names():
    for table, namespace in (("Склад::СкрытыйСклад", "Склад"),
                             ("Демо::Учет::Склад::Партии::СкрытыеПартии", "Склад::Партии"),
                             ("Склад::ОстаткиСклада.СрезПоследних", "Склад")):
        form = _list_component(table)
        diags = _lint(VISIBILITY, _project({"Продажи/ПодборТоваров.yaml": form}))
        assert [(d.line, d.col) for d in diags] == [_value_position(form, f"Таблица: {table}")], table
        assert diags[0].data["namespace"] == namespace


def test_a_hidden_joined_table_of_the_input_settings_is_not_visible():
    field = _input_field("СкрытыйСклад", imports=["Склад"])
    diags = _lint(VISIBILITY, _project({"Продажи/ВыборНоменклатуры.yaml": field}))
    assert [(d.line, d.col) for d in diags] == [_value_position(field, "Таблица: СкрытыйСклад")]


def test_public_tables_and_the_own_subsystem_stay_visible():
    public = _list_component("Номенклатура", imports=["Склад", "Склад::Партии"],
                             joined=["ПартииТоваров", "Склад::Партии::ПартииТоваров"])
    own = _list_component("СкрытыйСклад", joined=["СкрытыеПартии"])
    files = _project({"Продажи/ПодборТоваров.yaml": public, "Склад/Партии/ПодборСклада.yaml": own})
    assert _lint(VISIBILITY, files) == []


def test_a_binding_in_the_table_position_is_not_a_table():
    form = _list_component("=ВыборТаблицы.ИмяТаблицы")
    assert _lint(VISIBILITY, _project({"Продажи/ПодборТоваров.yaml": form})) == []


def test_one_finding_per_hidden_table_even_when_it_is_also_a_type():
    form = _list_component("СкрытыйСклад", imports=["Склад"]).replace(
        "Наследует:", "Свойства:\n    -\n        Имя: Товар\n        Тип: СкрытыйСклад.Ссылка?\nНаследует:",
    )
    diags = _lint(VISIBILITY, _project({"Продажи/ПодборТоваров.yaml": form}))
    assert len(diags) == 1
