"""The tables of a query in the rules of the package model, settled by the IDE server.

Four claims were put to a probe project, and each answer changed a rule or confirmed it:

- a comma after a join condition opens the next item of the FROM list: the server named a missing
  table there as not found and asked for the import of a package for the table of another
  subsystem, and so it did after a subquery and after a collection source. The reading of the
  tables stopped at such a comma, and the import rules missed the table;
- a table must be public: a non-public table of another subsystem was refused as not visible -
  in a query block of a module with the namespace imported, by a qualified name without an import,
  in the query of a virtual table and in the project module once it imported the subsystem - while
  a non-public table of the query's own subsystem compiled. code/foreign-not-public did not read
  the tables;
- the project module belongs to no subsystem, and it needs the import of the root of a subsystem
  as well as of a package: a type, a call of a common module and a query table of the root were
  refused as not imported, a qualified table compiled. code/missing-import judged the packages
  alone there;
- the query of a virtual table in a package reads a table of another package of its subsystem
  without an import: the server resolved the table (it named a missing field of it) and asked for
  no import. That was a conclusion by analogy with the modules; now it is a checked fact.

The fixture is the project `Демо::Учет`: subsystem `Склад` keeps public and hidden catalogs at its
root and in its packages `Партии` and `Архив`, a common module at its root; subsystem `Продажи`
uses `Склад`. Everything here tokenizes a module or a query, so every test needs the language data.
"""

import pytest

from xbsl import engine, i18n
from xbsl.rules._syntax import query_block_tokens, query_from_items, query_ranges, query_tables

MISSING_CODE = "code/missing-import"
MISSING_YAML = "yaml/missing-import"
UNUSED = "code/unused-import"
VISIBILITY = "code/foreign-not-public"
BASE = "Демо/Учет"

pytestmark = pytest.mark.needs_data  # the lexer reads the operators and keywords from the data


def _catalog(name: str, scope: str | None = "ВПроекте") -> str:
    return f"ВидЭлемента: Справочник\nИмя: {name}\n" + (f"ОбластьВидимости: {scope}\n" if scope else "")


def _project(extra: dict[str, str] | None = None) -> dict[str, str]:
    files = {
        "Проект.yaml": "Поставщик: Демо\nИмя: Учет\nВерсия: 1.0.0\n",
        "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
        "Склад/Номенклатура.yaml": _catalog("Номенклатура"),
        "Склад/СкрытыйСклад.yaml": _catalog("СкрытыйСклад", None),
        "Склад/РасчетСклада.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: РасчетСклада\nОбластьВидимости: ВПроекте\n",
        "Склад/РасчетСклада.xbsl": "@ВПроекте\nметод Пересчитать()\n;\n",
        "Склад/Партии/ПартииТоваров.yaml": _catalog("ПартииТоваров"),
        "Склад/Партии/СкрытыеПартии.yaml": _catalog("СкрытыеПартии", None),
        "Склад/Архив/АрхивПартий.yaml": _catalog("АрхивПартий"),
        "Продажи/Подсистема.yaml": "Использование:\n    - Склад\n",
        "Продажи/Заказы.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: Заказы\n",
    }
    files.update(extra or {})
    return {f"{BASE}/{name}": text for name, text in files.items()}


def _lint(rule_id: str, files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={rule_id})


def _rel(diag) -> str:
    return diag.path.replace("\\", "/").removeprefix(f"{BASE}/")


def _query(body: str, imports: str = "импорт Склад\n") -> dict[str, str]:
    """A module of `Продажи` with one query block."""
    code = f"{imports}\nметод Прочитать()\n    знч Выборка = Запрос{{\n{body}    }}\n    Выборка.Выполнить()\n;\n"
    return _project({"Продажи/Заказы.xbsl": code})


def _read(text: str) -> list[tuple[str, str | None]]:
    source = engine.load_text("Склад/Отчет.xbql", text)
    items = []
    for span in query_ranges(source):
        for (qualifiers, segments), alias in query_from_items(query_block_tokens(source, span)):
            name = "::".join(t.value for t in (*qualifiers, *segments[:1]))
            items.append((".".join([name, *(t.value for t in segments[1:])]), alias.value if alias else None))
    return items


# --- the FROM list ----------------------------------------------------------------------------------


def test_the_item_after_a_join_condition_is_a_table():
    assert _read(
        "ВЫБРАТЬ Н.Ссылка КАК Ссылка\n"
        "ИЗ Номенклатура КАК Н\n"
        "    ЛЕВОЕ СОЕДИНЕНИЕ АрхивПартий КАК А ПО А.Ссылка == Н.Ссылка И ЕСТЬNULL(А.Код, 0) В (1, 2),\n"
        "    ПартииТоваров КАК П\n"
        "ГДЕ Н.Ссылка В (ВЫБРАТЬ Ссылка ИЗ Склад::Номенклатура)\n"
        "СГРУППИРОВАТЬ ПО Н.Ссылка, П.Код\n"
        "УПОРЯДОЧИТЬ ПО Н.Ссылка, Код\n"
    ) == [("Номенклатура", "Н"), ("АрхивПартий", "А"), ("ПартииТоваров", "П"),
          ("Склад::Номенклатура", None)]


def test_the_items_after_a_subquery_and_a_collection_source_are_tables():
    assert _read(
        "ВЫБРАТЬ В.Код КАК Код\n"
        "ИЗ (ВЫБРАТЬ Х.Код КАК Код ИЗ АрхивПартий КАК Х, Номенклатура) КАК В,\n"
        "    %Строки КАК С, %{Выборка(1, 2)} Д, ПартииТоваров П\n"
        "    ВНУТРЕННЕЕ СОЕДИНЕНИЕ (ВЫБРАТЬ 1 КАК Код) КАК Е ПО Истина, СкрытыйСклад\n"
    ) == [("АрхивПартий", "Х"), ("Номенклатура", None), ("ПартииТоваров", "П"), ("СкрытыйСклад", None)]


def test_a_named_parameter_in_the_list_ends_the_reading():
    """The IDE server refuses a named parameter in a query literal and says nothing after it."""
    assert _read("ВЫБРАТЬ С.Код КАК Код\nИЗ &Строки КАК С, ПартииТоваров КАК П\n") == []


def test_a_field_named_like_a_query_word_does_not_end_the_condition():
    assert _read(
        "ВЫБРАТЬ Н.Ссылка КАК Ссылка\n"
        "ИЗ Номенклатура КАК Н\n"
        "    ЛЕВОЕ СОЕДИНЕНИЕ АрхивПартий КАК А ПО А.Количество == Н.Количество, ПартииТоваров КАК П\n"
    ) == [("Номенклатура", "Н"), ("АрхивПартий", "А"), ("ПартииТоваров", "П")]


def test_a_join_condition_ends_at_a_clause_and_at_the_next_join():
    assert _read(
        "SELECT Н.Ссылка AS Ссылка\n"
        "FROM Номенклатура AS Н\n"
        "    LEFT JOIN АрхивПартий AS А ON А.Ссылка == Н.Ссылка\n"
        "    INNER JOIN ПартииТоваров AS П ON П.Ссылка == Н.Ссылка, СкрытыйСклад AS Скр\n"
        "WHERE Н.Код IN (1, 2)\n"
        "GROUP BY Н.Ссылка, Н.Код\n"
    ) == [("Номенклатура", "Н"), ("АрхивПартий", "А"), ("ПартииТоваров", "П"), ("СкрытыйСклад", "Скр")]


def test_the_tables_of_a_module_keep_the_order_of_the_text():
    source = engine.load_text("Склад/Отчет.xbsl", (
        "метод Т()\n    знч А = Запрос{ВЫБРАТЬ 1 КАК Поле ИЗ (ВЫБРАТЬ 1 КАК Поле ИЗ АрхивПартий) КАК В, "
        "ПартииТоваров}\n;\n"
    ))
    assert [s[0].value for _q, s in query_tables(source)] == ["АрхивПартий", "ПартииТоваров"]


# --- the import rules read the item after a join condition ------------------------------------------


def test_a_table_after_a_join_condition_needs_the_package_import():
    body = (
        "        ВЫБРАТЬ Н.Ссылка КАК Ссылка\n"
        "        ИЗ Номенклатура КАК Н\n"
        "            ЛЕВОЕ СОЕДИНЕНИЕ Номенклатура КАК Н2 ПО Н.Ссылка == Н2.Ссылка,\n"
        "            ПартииТоваров КАК П\n"
    )
    diags = _lint(MISSING_CODE, _query(body))
    assert [(d.rule_id, d.line, d.col) for d in diags] == [(MISSING_CODE, 8, 13)]
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}
    assert _lint(MISSING_CODE, _query(body, "импорт Склад\nимпорт Склад::Партии\n")) == []


def test_an_import_serving_a_table_after_a_join_condition_is_used():
    body = (
        "        ВЫБРАТЬ Н.Ссылка КАК Ссылка\n"
        "        ИЗ Номенклатура КАК Н\n"
        "            ЛЕВОЕ СОЕДИНЕНИЕ Номенклатура КАК Н2 ПО Истина, ПартииТоваров КАК П\n"
    )
    assert _lint(UNUSED, _query(body, "импорт Склад\nимпорт Склад::Партии\n")) == []


def _virtual_table(query: str, imports=(), where: str = "Продажи") -> dict[str, str]:
    section = "Импорт:\n" + "".join(f"    - {name}\n" for name in imports) if imports else ""
    return _project({
        f"{where}/ОстаткиПартий.yaml": "ВидЭлемента: ВиртуальнаяТаблица\nИмя: ОстаткиПартий\n"
                                       + section + "КлючевыеПоля:\n    - Ссылка\n",
        f"{where}/ОстаткиПартий.xbql": query,
    })


def test_a_virtual_table_reads_the_table_after_a_join_condition():
    query = (
        "ВЫБРАТЬ\n    Н.Ссылка КАК Ссылка\nИЗ\n    Номенклатура КАК Н\n"
        "        ЛЕВОЕ СОЕДИНЕНИЕ Номенклатура КАК Н2\n        ПО Н.Ссылка == Н2.Ссылка,\n"
        "    ПартииТоваров КАК П\n"
    )
    diags = _lint(MISSING_YAML, _virtual_table(query, ["Склад"]))
    assert len(diags) == 1 and "строка 7" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад::Партии"]}


def test_a_virtual_table_of_a_package_reads_another_package_without_an_import():
    """Checked by the IDE server: the query of a package reading a table of another package of its
    subsystem asks for no import."""
    query = "ВЫБРАТЬ\n    А.Ссылка КАК Ссылка\nИЗ\n    АрхивПартий КАК А\n"
    assert _lint(MISSING_YAML, _virtual_table(query, where="Склад/Партии")) == []


# --- the visibility of a table ----------------------------------------------------------------------


def test_a_hidden_table_of_another_subsystem_is_not_visible_in_a_module():
    for table, imports, namespace in (("СкрытыйСклад", "импорт Склад\n", "Склад"),
                                      ("Склад::СкрытыйСклад", "", "Склад"),
                                      ("СкрытыеПартии", "импорт Склад::Партии\n", "Склад::Партии")):
        body = f"        ВЫБРАТЬ З.Ссылка КАК Ссылка\n        ИЗ {table} КАК З\n"
        diags = _lint(VISIBILITY, _query(body, imports))
        column = 12
        line = 5 + (1 if imports else 0)
        assert [(d.rule_id, d.line, d.col) for d in diags] == [(VISIBILITY, line, column)], table
        assert f"Таблица запроса '{table}'" in diags[0].message
        assert "подсистемы 'Продажи'" in diags[0].message
        assert diags[0].data == {"namespace": namespace, "name": table.rpartition("::")[2]}


def test_a_hidden_table_is_not_visible_in_the_query_of_a_virtual_table():
    for table in ("СкрытыйСклад", "Склад::СкрытыйСклад"):
        query = f"ВЫБРАТЬ\n    З.Ссылка КАК Ссылка\nИЗ\n    {table} КАК З\n"
        diags = _lint(VISIBILITY, _virtual_table(query, ["Склад"]))
        assert [(_rel(d), d.line, d.col) for d in diags] == [("Продажи/ОстаткиПартий.xbql", 4, 5)], table


def test_public_tables_and_the_own_subsystem_stay_visible():
    body = ("        ВЫБРАТЬ Н.Ссылка КАК Ссылка\n        ИЗ Номенклатура КАК Н, ПартииТоваров КАК П\n")
    assert _lint(VISIBILITY, _query(body, "импорт Склад\nимпорт Склад::Партии\n")) == []
    query = "ВЫБРАТЬ\n    З.Ссылка КАК Ссылка\nИЗ\n    СкрытыйСклад КАК З, СкрытыеПартии КАК П\n"
    assert _lint(VISIBILITY, _virtual_table(query, where="Склад/Архив")) == []


def test_a_temporary_table_is_not_judged_for_visibility():
    body = (
        "        ВЫБРАТЬ Н.Ссылка КАК Ссылка ПОМЕСТИТЬ СкрытыйСклад ИЗ Номенклатура КАК Н;\n"
        "        ВЫБРАТЬ В.Ссылка КАК Ссылка ИЗ СкрытыйСклад КАК В\n"
    )
    assert _lint(VISIBILITY, _query(body)) == []


def test_the_english_message_of_a_hidden_table():
    body = "        ВЫБРАТЬ З.Ссылка КАК Ссылка\n        ИЗ СкрытыйСклад КАК З\n"
    i18n.set_lang("en")
    try:
        diags = _lint(VISIBILITY, _query(body))
    finally:
        i18n.set_lang("ru")
    assert len(diags) == 1
    assert "Query table 'СкрытыйСклад'" in diags[0].message and "subsystem 'Продажи'" in diags[0].message


# --- the project module -----------------------------------------------------------------------------


def test_the_project_module_needs_the_import_of_the_root_of_a_subsystem():
    code = (
        "метод Номер(): Номенклатура.Ссылка?\n    возврат Неопределено\n;\n\n"
        "метод Пересчет()\n    РасчетСклада.Пересчитать()\n;\n"
    )
    diags = _lint(MISSING_CODE, _project({"Проект.xbsl": code}))
    assert [(_rel(d), d.line, d.col) for d in diags] == [("Проект.xbsl", 1, 16)]
    assert "'импорт Склад'" in diags[0].message and "вне подсистем" in diags[0].message
    assert diags[0].data == {"namespaces": ["Склад"]}
    assert _lint(MISSING_CODE, _project({"Проект.xbsl": "импорт Склад\n\n" + code})) == []


def test_a_query_table_of_the_root_needs_the_import_in_the_project_module():
    code = ("метод Прочитать()\n    знч Выборка = Запрос{ВЫБРАТЬ Н.Ссылка КАК Ссылка ИЗ Номенклатура КАК Н}\n"
            "    Выборка.Выполнить()\n;\n")
    diags = _lint(MISSING_CODE, _project({"Проект.xbsl": code}))
    assert [(d.line, d.col) for d in diags] == [(2, 57)]
    qualified = code.replace("ИЗ Номенклатура", "ИЗ Склад::Номенклатура")
    assert _lint(MISSING_CODE, _project({"Проект.xbsl": qualified})) == []


def test_a_name_of_the_root_and_of_a_package_asks_for_either_import():
    code = "метод Пересчет()\n    РасчетСклада.Пересчитать()\n;\n"
    files = _project({
        "Проект.xbsl": code,
        "Склад/Партии/РасчетСклада.yaml": "ВидЭлемента: ОбщийМодуль\nИмя: РасчетСклада\nОбластьВидимости: ВПроекте\n",
    })
    diags = _lint(MISSING_CODE, files)
    assert len(diags) == 1 and diags[0].data == {"namespaces": ["Склад", "Склад::Партии"]}
    files[f"{BASE}/Проект.xbsl"] = "импорт Склад\n\n" + code
    assert _lint(MISSING_CODE, files) == []


def test_a_hidden_table_is_not_visible_in_the_project_module():
    code = ("импорт Склад\n\nметод Прочитать()\n"
            "    знч Выборка = Запрос{ВЫБРАТЬ З.Ссылка КАК Ссылка ИЗ СкрытыйСклад КАК З}\n"
            "    Выборка.Выполнить()\n;\n")
    diags = _lint(VISIBILITY, _project({"Проект.xbsl": code}))
    assert [(d.line, d.col) for d in diags] == [(4, 57)]
    assert "модуля вне подсистем" in diags[0].message
    assert _lint(MISSING_CODE, _project({"Проект.xbsl": code})) == []
