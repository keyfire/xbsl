"""Two more places an element of a package is reached from: the project module and a query.

The project module (`Проект.xbsl`) belongs to no subsystem, and code/missing-import used to
leave it alone. A server build refused a project module that called a common module of a
package while it imported the subsystem alone, so an element of a package now asks for its
own import there too; an element at the root of a subsystem still asks for nothing.

A table after FROM/JOIN names an element the way a type position does. The query of a
virtual table (`.xbql`) resolves its tables against the Import section of the yaml of the
pair - a build refused such a query with "the table is in a namespace that is not imported"
until the yaml imported the package - and a query block of a module resolves them against
the imports of the module.

The fixtures are the project `Демо::Учет` of tests/test_subsystem_packages.py: subsystem
`Склад` with a catalog at its root and a package `Партии`, subsystem `Продажи` using it.
Everything here tokenizes a module or a query, so every test needs the language data.
"""

import pytest

from xbsl import engine, i18n
from xbsl.rules._syntax import query_tables, query_temporary_tables

MISSING_CODE = "code/missing-import"
MISSING_YAML = "yaml/missing-import"
UNUSED = "code/unused-import"
CODE_VISIBILITY = "code/foreign-not-public"

BASE = "Демо/Учет"
PROJECT = "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n"

pytestmark = pytest.mark.needs_data  # the lexer reads the operators and keywords from the data


def _catalog(name: str, scope: str | None = "ВПроекте") -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\n" + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _module_yaml(name: str, scope: str | None = "ВПроекте") -> str:
    return f"ВидЭлемента: ОбщийМодуль\nИмя: {name}\n" + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _project(extra: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "Проект.yaml": PROJECT,
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/РасчетПартий.yaml": _module_yaml("РасчетПартий"),
        "Склад/Партии/РасчетПартий.xbsl": "@ВПроекте\nметод Пересчитать()\n;\n",
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        "Продажи/Заказы.yaml": _module_yaml("Заказы", None),
    }
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id})


def _rel(diag) -> str:
    return diag.path.replace("\\", "/").removeprefix(f"{BASE}/")


# --- the project module ---------------------------------------------------------------------

CALL = "метод Т()\n    РасчетПартий.Пересчитать()\n;\n"


def test_the_project_module_needs_the_import_of_a_package():
    """The live shape: the subsystem is imported, the called module lies in its package."""
    diags = _lint(MISSING_CODE, _project({"Проект.xbsl": "импорт Склад\n\n" + CALL}))
    assert [(d.rule_id, _rel(d), d.line, d.col) for d in diags] == [
        (MISSING_CODE, "Проект.xbsl", 4, 5)
    ]
    assert "импорт Склад::Партии" in diags[0].message and "вне подсистем" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}  # what a move repairs by


def test_the_import_of_the_package_covers_the_project_module():
    for line in ("импорт Склад::Партии", "импорт Демо::Учет::Склад::Партии"):
        files = _project({"Проект.xbsl": f"{line}\n\n{CALL}"})
        assert _lint(MISSING_CODE, files) == [], line


def test_an_element_at_the_root_asks_the_project_module_for_nothing():
    code = "метод Т(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n"
    assert _lint(MISSING_CODE, _project({"Проект.xbsl": code})) == []


def test_a_root_namesake_keeps_the_project_module_silent():
    """A name the root of another subsystem owns as well is not judged against the package."""
    files = _project({
        "Проект.xbsl": CALL,
        "Продажи/РасчетПартий.yaml": _module_yaml("РасчетПартий"),
    })
    assert _lint(MISSING_CODE, files) == []


def test_a_module_in_a_folder_of_the_project_root_is_not_taken_for_the_project_module():
    """Only a module lying right in the project folder is outside the subsystems."""
    files = _project({"Проект.xbsl": CALL, "Ресурсы/Сценарий.xbsl": CALL})
    assert [_rel(d) for d in _lint(MISSING_CODE, files)] == ["Проект.xbsl"]


def test_unused_import_of_the_project_module_is_judged_by_its_packages():
    code = "импорт Склад\nимпорт Склад::Партии\n\n" + CALL
    diags = _lint(UNUSED, _project({"Проект.xbsl": code}))
    assert [(_rel(d), d.line) for d in diags] == [("Проект.xbsl", 1)]
    assert "Склад::Партии" in diags[0].message


def test_the_english_message_of_the_project_module():
    i18n.set_lang("en")
    try:
        diags = _lint(MISSING_CODE, _project({"Проект.xbsl": CALL}))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1 and "outside any subsystem" in diags[0].message
    assert "Склад::Партии" in diags[0].message


# --- the query of a virtual table -------------------------------------------------------------

TABLE_HEAD = "ВидЭлемента: ВиртуальнаяТаблица\nИмя: ОстаткиПартий\n"
TABLE_TAIL = "КлючевыеПоля:\n    - Ссылка\n"
QUERY = (
    "ВЫБРАТЬ\n"
    "    П.Ссылка КАК Ссылка\n"
    "ИЗ\n"
    "    ПартииТоваров КАК П\n"
)


def _table(imports: list[str] | None, query: str = QUERY, where: str = "Продажи") -> dict[str, str]:
    section = "Импорт:\n" + "".join(f"    - {name}\n" for name in imports) if imports else ""
    return _project({
        f"{where}/ОстаткиПартий.yaml": TABLE_HEAD + section + TABLE_TAIL,
        f"{where}/ОстаткиПартий.xbql": query,
    })


def test_a_query_table_of_a_package_needs_the_package_import_in_the_yaml():
    diags = _lint(MISSING_YAML, _table(["Склад"]))
    assert [(d.rule_id, _rel(d), d.line, d.col) for d in diags] == [
        (MISSING_YAML, "Продажи/ОстаткиПартий.yaml", 3, 1)
    ]
    message = diags[0].message
    assert "ПартииТоваров" in message and "ОстаткиПартий.xbql" in message
    assert "строка 4" in message and "- Склад::Партии" in message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_the_package_import_in_the_yaml_covers_the_query():
    assert _lint(MISSING_YAML, _table(["Склад", "Склад::Партии"])) == []
    assert _lint(MISSING_YAML, _table(["Демо::Учет::Склад::Партии"])) == []


def test_a_yaml_without_an_import_section_is_reported_at_its_head():
    query = QUERY.replace("ПартииТоваров КАК П", "Номенклатура КАК П")
    diags = _lint(MISSING_YAML, _table(None, query))
    assert [(d.line, d.col) for d in diags] == [(1, 1)]
    assert "- Склад'" in diags[0].message or "'- Склад'" in diags[0].message


def test_a_table_of_the_own_subsystem_needs_no_import():
    assert _lint(MISSING_YAML, _table(None, where="Склад")) == []


def test_qualified_and_platform_tables_need_no_import():
    query = ("ВЫБРАТЬ П.Ссылка КАК Ссылка ИЗ Склад::Партии::ПартииТоваров КАК П\n"
             "    ЛЕВОЕ СОЕДИНЕНИЕ Пользователи КАК Пол ПО Истина\n")
    assert _lint(MISSING_YAML, _table(None, query)) == []


def test_joined_tables_a_comma_list_and_a_subquery_are_read():
    query = (
        "ВЫБРАТЬ Н.Ссылка КАК Ссылка\n"
        "ИЗ Номенклатура КАК Н, ПартииТоваров П\n"
    )
    diags = _lint(MISSING_YAML, _table(["Склад"], query))
    assert len(diags) == 1 and "'ПартииТоваров'" in diags[0].message
    nested = (
        "ВЫБРАТЬ В.Ссылка КАК Ссылка\n"
        "ИЗ (ВЫБРАТЬ П.Ссылка КАК Ссылка ИЗ ПартииТоваров КАК П) КАК В\n"
        "    ВНУТРЕННЕЕ СОЕДИНЕНИЕ Номенклатура КАК Н ПО Истина\n"
    )
    diags = _lint(MISSING_YAML, _table(["Склад"], nested))
    assert len(diags) == 1 and "строка 2" in diags[0].message


def test_the_english_keywords_of_a_query_are_read():
    query = "SELECT П.Ссылка AS Ссылка\nFROM Номенклатура AS Н\n    LEFT JOIN ПартииТоваров AS П ON True\n"
    diags = _lint(MISSING_YAML, _table(["Склад"], query))
    assert len(diags) == 1 and "Склад::Партии" in diags[0].message


def test_the_query_line_goes_to_the_english_message():
    i18n.set_lang("en")
    try:
        diags = _lint(MISSING_YAML, _table(["Склад"]))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1 and "(line 4)" in diags[0].message


# --- the query blocks of a module -------------------------------------------------------------


def _query_module(body: str, imports: str = "импорт Склад\n") -> dict[str, str]:
    return _project({"Продажи/Заказы.xbsl": f"{imports}\nметод Т()\n{body};\n"})


def test_a_query_block_of_a_module_needs_the_package_import():
    body = ("    знч Выборка = Запрос{ВЫБРАТЬ П.Ссылка КАК Ссылка ИЗ ПартииТоваров КАК П}\n"
            "    Выборка.Выполнить()\n")
    diags = _lint(MISSING_CODE, _query_module(body))
    assert [(d.rule_id, d.line) for d in diags] == [(MISSING_CODE, 4)]
    assert "Таблица запроса 'ПартииТоваров'" in diags[0].message
    covered = _query_module(body, "импорт Склад\nимпорт Склад::Партии\n")
    assert _lint(MISSING_CODE, covered) == []


def test_a_temporary_table_of_the_module_is_not_a_reference():
    """The platform reads a temporary table by its short name in every query of the module."""
    body = (
        "    знч Заполнение = Запрос{ВЫБРАТЬ Н.Ссылка КАК Ссылка ПОМЕСТИТЬ ПартииТоваров "
        "ИЗ Номенклатура КАК Н}\n"
        "    Заполнение.Выполнить()\n"
        "    знч Чтение = Запрос{ВЫБРАТЬ В.Ссылка КАК Ссылка ИЗ ПартииТоваров КАК В}\n"
        "    Чтение.Выполнить()\n"
    )
    assert _lint(MISSING_CODE, _query_module(body)) == []


def test_a_parameter_in_the_table_position_is_not_a_table():
    body = ("    знч Выборка = Запрос{ВЫБРАТЬ К.Код КАК Код ИЗ %Коллекция КАК К}\n"
            "    Выборка.Выполнить()\n")
    assert _lint(MISSING_CODE, _query_module(body, "")) == []


def test_the_visibility_rule_does_not_read_the_tables():
    """A non-public table stays the visibility rules' business, and they do not read queries."""
    body = ("    знч Выборка = Запрос{ВЫБРАТЬ З.Ссылка КАК Ссылка ИЗ Закрытый КАК З}\n"
            "    Выборка.Выполнить()\n")
    files = {**_query_module(body), f"{BASE}/Склад/Партии/Закрытый.yaml": _catalog("Закрытый", None)}
    assert _lint(MISSING_CODE, files) == [] and _lint(CODE_VISIBILITY, files) == []


def test_a_type_literal_is_a_written_type():
    """`Тип<Форма>` keeps no name in the parsed tree; a control over a project with packages
    found a module whose only use of a package was two such literals."""
    code = "метод Т(): Тип\n    возврат Тип<ПартииТоваров>\n;\n"
    diags = _lint(MISSING_CODE, _project({"Продажи/Заказы.xbsl": "импорт Склад\n\n" + code}))
    assert [(d.line, d.col) for d in diags] == [(4, 13)]
    assert "импорт Склад::Партии" in diags[0].message
    covered = _project({"Продажи/Заказы.xbsl": "импорт Склад::Партии\n\n" + code})
    assert _lint(MISSING_CODE, covered) == []


# --- an import of a subsystem whose root keeps nothing ------------------------------------------


def _root_emptied(code: str) -> dict[str, str]:
    """The project with every element of `Склад` in its package: the root keeps none."""
    files = _project({"Продажи/Заказы.xbsl": code})
    del files[f"{BASE}/Склад/Номенклатура.yaml"]
    return files


def test_an_import_of_a_subsystem_with_nothing_at_its_root_is_unused():
    diags = _lint(UNUSED, _root_emptied("импорт Склад\nимпорт Склад::Партии\n\n" + CALL))
    assert [(d.line, d.data) for d in diags] == [(1, {"namespace": "Склад"})]
    assert "Склад::Партии" in diags[0].message


def test_a_bare_resource_key_keeps_the_import_of_such_a_subsystem():
    """The import of a subsystem may still bring its resources to a key without a namespace."""
    code = ("импорт Склад\nимпорт Склад::Партии\n\nметод Т()\n    РасчетПартий.Пересчитать()\n"
            "    знч Схема = Ресурс{Схема.svg}\n;\n")
    assert _lint(UNUSED, _root_emptied(code)) == []
    qualified = code.replace("Ресурс{Схема.svg}", "Ресурс{Склад::Схема.svg}")
    assert len(_lint(UNUSED, _root_emptied(qualified))) == 1


def test_an_unknown_namespace_stays_out_of_the_judgement():
    assert _lint(UNUSED, _root_emptied("импорт Внешний\n\n" + CALL)) == []


# --- the reading of the tables itself ---------------------------------------------------------


def test_query_tables_reads_sections_virtual_tables_and_qualifiers():
    source = engine.load_text("Склад/ОстаткиПартий.xbql", (
        "ВЫБРАТЬ Т.Ссылка КАК Ссылка\n"
        "ИЗ ПартииТоваров.Состав КАК Т, Склад::Партии::АрхивПартий А, Номенклатура\n"
        "    ЛЕВОЕ СОЕДИНЕНИЕ ЦеныПартий.СрезПоследних(&Период, Истина) КАК К ПО Истина\n"
        "ГДЕ Т.Ссылка В (ВЫБРАТЬ Ссылка ИЗ Номенклатура)\n"
    ))
    read = [("::".join(t.value for t in q), ".".join(t.value for t in s))
            for q, s in query_tables(source)]
    assert read == [
        ("", "ПартииТоваров.Состав"),
        ("Склад::Партии", "АрхивПартий"),
        ("", "Номенклатура"),
        ("", "ЦеныПартий.СрезПоследних"),
        ("", "Номенклатура"),
    ]


def test_query_temporary_tables_reads_every_way_to_name_one():
    source = engine.load_text("Склад/Отчет.xbsl", (
        "метод Т()\n"
        "    знч А = Запрос{ВЫБРАТЬ 1 КАК Поле ПОМЕСТИТЬ ПервыеПартии ИЗ ПартииТоваров}\n"
        "    знч Б = Запрос{СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ ВторыеПартии (Поле Число)}\n"
        "    знч В = Запрос{УНИЧТОЖИТЬ ТретьиПартии}\n"
        ";\n"
    ))
    assert query_temporary_tables(source) == {"ПервыеПартии", "ВторыеПартии", "ТретьиПартии"}
