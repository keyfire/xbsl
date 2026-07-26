"""Tests of the pure LSP navigation core (a port of the extension's navCore tests).

The core itself needs no Element data - it works over the project index. The tests of the
syntactic helpers (types of locals, query aliases and columns) do run the lexer, so they carry
`needs_data` and are skipped in a checkout without the data bundle.
"""

import pytest

from xbsl import dataset, engine
from xbsl import templates as tpl
from xbsl.lsp_nav import (
    CHAIN_TAIL_RE,
    IndexLookup,
    _query_field_entries,
    chain_at,
    resolve_completions,
    resolve_definition,
    resolve_hover,
    resolve_references,
)
from xbsl.rules._syntax import (
    chain_type_at,
    local_var_names,
    local_var_types,
    query_aliases,
    query_row_columns,
)

INDEX = {
    "meta": {"root": "/project/src", "version": "test"},
    "objects": [
        {
            "name": "Товар",
            "kind": "Справочник",
            "path": "Каталог/Товар.yaml",
            "line": 3,
            "tabular": [{"name": "Цены", "line": 40}],
            "attributes": [{"name": "Цена", "line": 10}, {"name": "Артикул", "line": 11}],
            "local_types": [{"name": "ДанныеКарточки", "path": "Каталог/Товар.xbsl", "line": 12}],
            "family": ["Ссылка", "Объект"],
            "values": [],
        },
        {
            "name": "ВидТовара",
            "kind": "Перечисление",
            "path": "Каталог/ВидТовара.yaml",
            "line": 2,
            "tabular": [],
            "local_types": [],
            "family": [],
            "values": [{"name": "Весовой", "line": 9}],
        },
    ],
    "methods": [
        {"module": "Товар", "name": "Загрузить", "path": "Каталог/Товар.xbsl", "line": 20, "annotations": ["НаСервере"]},
        {"module": "ГлавнаяФорма", "name": "Обновить", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 5, "annotations": []},
        {"module": "Кнопка", "name": "Нажать", "path": "Каталог/Кнопка.xbsl", "line": 7, "annotations": ["Локально"]},
    ],
    "components": [
        {"form": "ГлавнаяФорма", "name": "Кнопка", "type": "Кнопка", "path": "Каталог/ГлавнаяФорма.yaml", "line": 33},
    ],
    "references": [
        # method Загрузить (module Товар): declaration, own-module call, a Товар.Загрузить() call, noise
        {"name": "Загрузить", "qualifier": "", "module": "Товар", "path": "Каталог/Товар.xbsl", "line": 20, "col": 4},
        {"name": "Загрузить", "qualifier": "", "module": "Товар", "path": "Каталог/Товар.xbsl", "line": 25, "col": 8},
        {"name": "Загрузить", "qualifier": "Товар", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 6, "col": 10},
        {"name": "Загрузить", "qualifier": "Прочее", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 50, "col": 4},
        # method Обновить (module ГлавнаяФорма): a call in code and a yaml handler
        {"name": "Обновить", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 12, "col": 4},
        {"name": "Обновить", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.yaml", "line": 33, "col": 20},
        # the object Товар as a chain root
        {"name": "Товар", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 6, "col": 0},
        # component Кнопка of form ГлавнаяФорма (a usage in code) and method Нажать of its module
        {"name": "Кнопка", "qualifier": "Компоненты", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 8, "col": 4},
        {"name": "Нажать", "qualifier": "Кнопка", "module": "ГлавнаяФорма", "path": "Каталог/Кнопка.xbsl", "line": 9, "col": 4},
    ],
}

LOOKUP = IndexLookup(INDEX)


def d(line_text, character, language_id="xbsl", file_stem="ГлавнаяФорма", file_path=None):
    return resolve_definition(
        LOOKUP,
        language_id=language_id,
        line_text=line_text,
        character=character,
        file_stem=file_stem,
        file_path=file_path,
    )


def test_chain_at_segments():
    parts, at = chain_at("знч Х = Товар.Цены", 10)
    assert parts == ["Товар", "Цены"] and at == 0
    parts, at = chain_at("знч Х = Товар.Цены", 16)
    assert parts == ["Товар", "Цены"] and at == 1
    assert chain_at("    ", 2) is None


def test_definition_object_and_members():
    assert d("пер Т: Товар.Ссылка", 8) == ("Каталог/Товар.yaml", 3)
    assert d("знч Ц = Товар.Цены", 15) == ("Каталог/Товар.yaml", 40)
    assert d("пер К: Товар.ДанныеКарточки", 15) == ("Каталог/Товар.xbsl", 12)
    assert d("знч В = ВидТовара.Весовой", 20) == ("Каталог/ВидТовара.yaml", 9)


def test_definition_methods_and_components():
    assert d("Товар.Загрузить()", 8) == ("Каталог/Товар.xbsl", 20)
    assert d("Обновить()", 2) == ("Каталог/ГлавнаяФорма.xbsl", 5)  # own module via file_stem
    assert d("Компоненты.Кнопка.Видимость", 12) == ("Каталог/ГлавнаяФорма.yaml", 33)
    assert d("Компоненты.Кнопка.Нажать()", 20) == ("Каталог/Кнопка.xbsl", 7)


def test_definition_yaml_handler():
    assert d("    Обработчик: Обновить", 20, language_id="yaml",
             file_path="Каталог/ГлавнаяФорма.yaml") == ("Каталог/ГлавнаяФорма.xbsl", 5)
    # outside the handler value - silence
    assert d("    Обработчик: Обновить", 3, language_id="yaml") is None


def test_definition_yaml_handler_with_comment():
    # a trailing comment after the handler name does not break the jump
    assert d("    Обработчик: Обновить # клик", 20, language_id="yaml",
             file_path="Каталог/ГлавнаяФорма.yaml") == ("Каталог/ГлавнаяФорма.xbsl", 5)


def test_definition_unknown_contexts():
    assert d("Неведомое.Что", 3) is None
    assert d("А.Б.В.Г", 6) is None  # a deep chain without Компоненты - out of scope


def r(line_text, character, include_declaration=False, language_id="xbsl", file_stem="ГлавнаяФорма", file_path=None):
    return resolve_references(
        LOOKUP,
        language_id=language_id,
        line_text=line_text,
        character=character,
        file_stem=file_stem,
        file_path=file_path,
        include_declaration=include_declaration,
    )


def _sites(refs):
    return {(path, line) for path, line, _col, _len in refs}


def test_references_method():
    # cursor on Товар.Загрузить(): usages of method Загрузить of module Товар
    got = r("Товар.Загрузить()", 8)
    sites = _sites(got)
    assert ("Каталог/ГлавнаяФорма.xbsl", 6) in sites  # Товар.Загрузить() in the form
    assert ("Каталог/Товар.xbsl", 25) in sites  # a bare call in its own module
    assert ("Каталог/Товар.xbsl", 20) not in sites  # the declaration is excluded
    assert ("Каталог/ГлавнаяФорма.xbsl", 50) not in sites  # a foreign qualifier Прочее - not our method


def test_references_include_declaration():
    got = r("Товар.Загрузить()", 8, include_declaration=True)
    assert ("Каталог/Товар.xbsl", 20) in _sites(got)  # the declaration is included


def test_references_method_from_yaml_handler():
    # a yaml handler -> usages of method Обновить (the handler site itself is a usage too)
    got = r("    Обработчик: Обновить", 20, language_id="yaml", file_path="Каталог/ГлавнаяФорма.yaml")
    sites = _sites(got)
    assert ("Каталог/ГлавнаяФорма.xbsl", 12) in sites
    assert ("Каталог/ГлавнаяФорма.yaml", 33) in sites


def test_references_object():
    # the object Товар as a chain root
    got = r("знч Х = Товар.Ссылка", 11)
    assert _sites(got) == {("Каталог/ГлавнаяФорма.xbsl", 6)}


def test_references_component():
    # component Кнопка via Компоненты in form ГлавнаяФорма (a usage in code, not the yaml node line)
    got = r("Компоненты.Кнопка.Видимость", 13)
    assert _sites(got) == {("Каталог/ГлавнаяФорма.xbsl", 8)}


def test_references_col_and_length():
    # a position carries col (0-based) and the name length for highlighting
    got = r("Компоненты.Кнопка.Видимость", 13)
    _path, _line, col, length = got[0]
    assert col == 4 and length == len("Кнопка")


def test_references_unknown_is_empty():
    assert r("Неведомое.Что", 3) == []


def c(prefix, language_id="xbsl", file_stem="ГлавнаяФорма"):
    return resolve_completions(LOOKUP, language_id=language_id, line_prefix=prefix, file_stem=file_stem)


def test_completion_object_members():
    labels = {e["label"] for e in c("знч Х = Товар.")}
    assert {"Ссылка", "Объект", "Цены", "ДанныеКарточки", "Загрузить"} <= labels


def test_completion_query_table_fields():
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="Товар.",
        file_stem="ГлавнаяФорма",
        in_query=True,
    )
    labels = {e["label"] for e in entries}
    assert {"Ссылка", "Код", "Наименование", "Цена", "Артикул", "Цены"} <= labels
    assert "Объект" not in labels  # an object/manager member, not a table field
    assert all(e["kind"] == "field" for e in entries)


def test_completion_query_table_alias():
    # project tables are addressed via an alias (`ИЗ Товар КАК Т`) - after `Т.` the same fields
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="            Т.",
        file_stem="ГлавнаяФорма",
        in_query=True,
        query_tables={"Т": "Товар"},
    )
    labels = {e["label"] for e in entries}
    assert {"Ссылка", "Код", "Наименование", "Цена", "Артикул", "Цены"} <= labels


def test_completion_query_only_inside_query():
    # Outside a Запрос{...} block, after a dot - the previous behavior (object members).
    labels = {e["label"] for e in c("знч Х = Товар.")}
    assert "Объект" in labels


def test_completion_stdlib_type_members():
    # not a project object but a stdlib type/global - members come from the type_members dataset:
    # properties and methods separately (a method gets its own kind and parens on insertion)
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="КонтекстДоступа.",
        file_stem="ГлавнаяФорма",
        stdlib_members={
            "КонтекстДоступа": {"properties": ["ТекущийПользователь"], "methods": ["Привилегированный"]}
        },
    )
    by_label = {e["label"]: e for e in entries}
    assert set(by_label) == {"Привилегированный", "ТекущийПользователь"}
    assert by_label["ТекущийПользователь"]["kind"] == "field"
    assert by_label["Привилегированный"]["kind"] == "method"
    assert by_label["Привилегированный"]["snippet"] == "Привилегированный($0)"


def test_completion_stdlib_flat_members_still_work():
    # the old dataset (a flat list of names, properties and methods mixed) - compatibility
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="КонтекстДоступа.",
        file_stem="ГлавнаяФорма",
        stdlib_members={"КонтекстДоступа": ["Привилегированный", "ТекущийПользователь"]},
    )
    assert {e["label"] for e in entries} == {"Привилегированный", "ТекущийПользователь"}
    assert all(e["kind"] == "field" for e in entries)


def test_completion_local_var_members():
    # пер Список = новый Массив<Строка>() -> Список. offers the members of Массив (the variable
    # type is computed by the caller, with the lexer)
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="    Список.",
        file_stem="ГлавнаяФорма",
        stdlib_members={"Массив": {"methods": ["Добавить", "Размер"]}},
        local_vars={"Список": "Массив"},
    )
    assert {e["label"] for e in entries} == {"Добавить", "Размер"}
    assert all(e["kind"] == "method" for e in entries)


def test_completion_local_var_shadows_stdlib_type():
    # a variable shadows the namesake stdlib type: `пер Список = новый Массив<...>()` is about
    # the members of Массив, not about the component Список
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="если Лимит > 0 и Список.",
        file_stem="ГлавнаяФорма",
        stdlib_members={
            "Список": {"properties": ["ВыделеннаяСтрока"], "methods": ["ДобавитьСтроку"]},
            "Массив": {"methods": ["Добавить", "Размер"]},
        },
        local_vars={"Список": "Массив"},
    )
    assert {e["label"] for e in entries} == {"Добавить", "Размер"}


def test_completion_local_var_project_type_none():
    # the variable type is a project structure, not stdlib: nothing to offer, yield to word completion
    got = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="Строки.",
        file_stem="ГлавнаяФорма",
        stdlib_members={"Массив": {"methods": ["Добавить"]}},
        local_vars={"Строки": "КэшДанныхСервиса.СтрокаПодписки"},
    )
    assert got is None


def test_completion_unknown_dot_none():
    # an unknown token (not a project object and not stdlib) - None, yield to word completion
    got = resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix="Неведомо.", file_stem="Ф", stdlib_members={}
    )
    assert got is None


def test_completion_enum_values():
    entries = c("пер В = ВидТовара.")
    assert [e["label"] for e in entries] == ["Весовой"]
    assert entries[0]["kind"] == "enumMember"


def test_completion_components_and_methods():
    assert [e["label"] for e in c("Компоненты.")] == ["Кнопка"]
    assert [e["label"] for e in c("Компоненты.Кнопка.")] == ["Нажать"]


def test_completion_yaml_type():
    labels = [e["label"] for e in c("    Тип: ", language_id="yaml")]
    assert labels == ["Товар", "ВидТовара"]
    # in yaml outside a Тип value the context is unknown (the bare-name branch is xbsl-only)
    assert c("просто текст", language_id="yaml") is None


def _yaml_type(prefix):
    return resolve_completions(
        LOOKUP, language_id="yaml", line_prefix=prefix, file_stem="ГлавнаяФорма",
        stdlib_names=["СтандартнаяКолонкаТаблицы", "Таблица", "АвтоматическаяГруппа",
                      "ДвоичныйОбъект.Ссылка", "~~Стд::Геопозиционирование~~"],
    )


def test_completion_yaml_type_offers_platform_catalog():
    # the component type lives only in the platform catalog - it is not among the project objects
    labels = {e["label"] for e in _yaml_type("        Тип: С")}
    assert {"СтандартнаяКолонкаТаблицы", "АвтоматическаяГруппа", "Товар"} <= labels
    # a facet is a member of its aggregate, not a bare name; catalog non-names are dropped
    assert "ДвоичныйОбъект.Ссылка" not in labels
    assert not [x for x in labels if x.startswith("~~")]


def test_completion_yaml_type_inside_generics():
    # a Тип value is an expression: the cursor may sit inside the brackets, not only at the root
    labels = {e["label"] for e in _yaml_type("    Тип: СтандартнаяКолонкаТаблицы<Табл")}
    assert "Таблица" in labels


МОДУЛЬ = """@НаСервере
метод Загрузить(Ключи: Массив<Строка>, Лимит: Число): Число
    пер Список = новый Массив<СводкаАкция>()
    пер Текст: Строка = ""
    пер Строки = новый Массив<КэшДанныхСервиса.СтрокаПодписки>()
    возврат 0
;

метод Другой()
    пер Индекс = новый Соответствие<Строка, Число>()
    возврат Индекс
;
"""


МОДУЛЬ_С_ЗАПРОСОМ = """@НаСервере
метод Сводки(): Число
    знч Результат = Запрос{
        ВЫБРАТЬ
            А.Заголовок КАК Заголовок,
            А.Слаг,
            СУММА(А.Порядок) КАК Вес
        ИЗ
            Акция КАК А
        ЛЕВОЕ СОЕДИНЕНИЕ
            Программа КАК П
        ПО
            П.Ссылка == А.Программа
    }.Выполнить()
    для С из Результат
        знч Х = С.Заголовок
    ;
    возврат 0
;
"""


@pytest.mark.needs_data
def test_query_aliases_from_and_join():
    # query table aliases - that is how real code addresses the tables
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    inside = МОДУЛЬ_С_ЗАПРОСОМ.index("А.Заголовок")
    assert query_aliases(src, inside) == {"А": "Акция", "П": "Программа"}
    # no map outside the query block
    outside = МОДУЛЬ_С_ЗАПРОСОМ.index("возврат 0")
    assert query_aliases(src, outside) == {}


@pytest.mark.needs_data
def test_query_row_columns_for_loop():
    # `знч Результат = Запрос{...}` + `для С из Результат` -> С carries the selection columns:
    # a КАК alias, an alias-free field (its last segment), a computed expression only with an alias
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    got = query_row_columns(src, МОДУЛЬ_С_ЗАПРОСОМ.index("С.Заголовок"))
    assert got == {"С": ["Заголовок", "Слаг", "Вес"]}


@pytest.mark.needs_data
def test_query_row_columns_only_above_cursor():
    # a loop below the cursor is not visible yet
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    assert query_row_columns(src, МОДУЛЬ_С_ЗАПРОСОМ.index("знч Результат")) == {}


def test_completion_query_row_member():
    # С. inside `для С из Результат` -> the result row columns
    entries = resolve_completions(
        LOOKUP,
        language_id="xbsl",
        line_prefix="        знч Х = С.",
        file_stem="ГлавнаяФорма",
        query_rows={"С": ["Заголовок", "Слаг"]},
    )
    assert [e["label"] for e in entries] == ["Заголовок", "Слаг"]
    assert all(e["kind"] == "field" for e in entries)


@pytest.mark.needs_data
def test_local_var_types_declarations_and_params():
    # the type comes from the initializer (новый Массив<...>) and from the annotation; the generic
    # argument is dropped - type members do not depend on it; method parameters yield a type too
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("возврат 0"))
    assert got == {
        "Ключи": "Массив",
        "Лимит": "Число",
        "Список": "Массив",
        "Текст": "Строка",
        "Строки": "Массив",
    }


@pytest.mark.needs_data
def test_local_var_types_scoped_to_method():
    # variables of the neighboring method do not leak into the scope
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("возврат Индекс"))
    assert got == {"Индекс": "Соответствие"}


@pytest.mark.needs_data
def test_local_var_types_only_above_cursor():
    # declarations below the cursor are not visible yet
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("пер Список"))
    assert got == {"Ключи": "Массив", "Лимит": "Число"}


@pytest.mark.needs_data
def test_variable_named_query_keyword_is_a_variable():
    # `Запрос` is the QUERY keyword only before `{`; as a variable name the declaration and
    # the chain typing must read it like any identifier - otherwise `Запрос.Выполнить()`
    # falls into the query-literal path and the neighbor variable gets the wrong type
    code = (
        "метод Т(Url: Строка): Строка\n"
        "    пер Запрос = КлиентHttp.ЗапросPost(Url)\n"
        '        .УстановитьЗаголовок("Accept", "application/json")\n'
        "    пер Ответ = Запрос.Выполнить()\n"
        "    возврат Ответ.Тело.ПрочитатьКакСтроку()\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    catalog = dataset.load_json("stdlib.json")
    members = {**(catalog.get("type_members") or {}), **(catalog.get("facet_members") or {})}
    got = local_var_types(
        src, code.index("возврат"),
        returns=catalog.get("member_types") or {}, static_roots=members.keys(),
    )
    assert got.get("Запрос") == "ЗапросHttp"
    assert got.get("Ответ") == "ОтветHttp"


@pytest.mark.needs_data
def test_local_var_names_cover_untyped_declarations():
    # the name shadow: parameters, untyped declarations and loop variables are variables
    # even when no type can be inferred - the docs hover must not read them as type names
    code = (
        "метод Т(Данные: Строка): Число\n"
        "    пер Запрос = ЧейТоМетод()\n"
        "    для Индекс = 1 по 5\n"
        "        для Элемент из Список\n"
        "            Сообщить(Элемент)\n"
        "        ;\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    got = local_var_names(src, code.index("возврат"))
    assert {"Данные", "Запрос", "Индекс", "Элемент"} <= got


def test_pair_yaml_names_read_from_disk(tmp_path):
    # the hover shadow: names of the paired yaml are variables of the form, not stdlib types
    (tmp_path / "Форма.yaml").write_text(
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Форма\nДанные:\n  - Имя: Email\n"
        "  - Имя: Телефон # контакт\n",
        encoding="utf-8",
    )
    from xbsl.rules._syntax import pair_yaml_names

    names = pair_yaml_names(tmp_path / "Форма.xbsl")
    assert {"Email", "Телефон", "Форма"} <= names
    assert pair_yaml_names(tmp_path / "Другой.xbsl") == set()


@pytest.mark.needs_data
def test_query_literal_keeps_its_keyword_and_type():
    # the real literal (`Запрос{...}`) is untouched by the retag and still types the variable
    code = (
        "метод Т()\n"
        "    пер З = Запрос{ ВЫБРАТЬ Код ИЗ Товары }\n"
        "    Сообщить(З)\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    got = local_var_types(src, code.index("Сообщить"))
    assert got.get("З") == "ТипизированныйЗапрос"


def test_hover_object_method_component():
    h = resolve_hover(LOOKUP, language_id="xbsl", line_text="пер Т: Товар", character=9,
                      file_stem="ГлавнаяФорма")
    assert "Справочник Товар" in h and "Цены" in h
    h = resolve_hover(LOOKUP, language_id="xbsl", line_text="Товар.Загрузить()", character=8,
                      file_stem="ГлавнаяФорма")
    assert "метод Товар.Загрузить" in h and "@НаСервере" in h
    h = resolve_hover(LOOKUP, language_id="xbsl", line_text="Компоненты.Кнопка", character=13,
                      file_stem="ГлавнаяФорма")
    assert "Компонент Кнопка" in h
    assert resolve_hover(LOOKUP, language_id="xbsl", line_text="Неведомое", character=2,
                         file_stem="ГлавнаяФорма") is None


@pytest.mark.needs_data
def test_local_var_type_from_query_literal():
    # `знч З = Запрос{...}` constructs a ТипизированныйЗапрос (topics/query-literal):
    # after `З.` the completion must offer Выполнить and friends
    code = (
        "метод А()\n"
        "    знч ЗапросКБД = Запрос{\n"
        "        ВЫБРАТЬ Значение ИЗ НастройкиПриложения\n"
        "    }\n"
        "    знч Р = ЗапросКБД.\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    got = local_var_types(src, code.index("ЗапросКБД.\n") + len("ЗапросКБД."))
    assert got.get("ЗапросКБД") == "ТипизированныйЗапрос"


def test_query_fields_include_register_sections():
    # register fields live in Измерения and Ресурсы - the table field completion inside
    # Запрос{...} must see them (a register may have no attributes at all)
    entries = _query_field_entries(
        "РегистрСведений", [], [],
        [{"name": "Настройка"}], [{"name": "Значение"}],
    )
    got = {e["label"]: e["detail"] for e in entries}
    assert got == {"Настройка": "измерение", "Значение": "ресурс"}


@pytest.mark.needs_data
def test_local_var_type_from_call_chain():
    # a type from a method return: a static factory and a chain on a variable
    code = (
        "метод А(Путь: Строка)\n"
        "    знч Клиент = КлиентHttp.СБазовымUrl(\"http://адрес\")\n"
        "    знч Ответ = Клиент.ЗапросGet(Путь).Выполнить()\n"
        "    знч Хвост = Ответ.\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    catalog = dataset.load_json("stdlib.json")
    members = {**catalog["type_members"], **catalog["facet_members"]}
    returns = catalog["member_types"]
    lv = local_var_types(
        src, code.index("Ответ.\n") + len("Ответ."),
        returns=returns, static_roots=members.keys(),
    )
    assert lv.get("Клиент") == "КлиентHttp"
    assert lv.get("Ответ") == "ОтветHttp"


@pytest.mark.needs_data
def test_chain_type_at_dot_after_call():
    # a dot after a call: `ЗапросКБД.Выполнить().` - the type of the chain left of the cursor
    code = (
        "метод А()\n"
        "    знч ЗапросКБД = Запрос{ ВЫБРАТЬ Значение ИЗ Настройки }\n"
        "    знч Строка1 = ЗапросКБД.Выполнить().\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    catalog = dataset.load_json("stdlib.json")
    members = {**catalog["type_members"], **catalog["facet_members"]}
    returns = catalog["member_types"]
    offset = code.index("Выполнить().\n") + len("Выполнить().")
    lv = local_var_types(src, offset, returns=returns, static_roots=members.keys())
    t = chain_type_at(src, offset, var_types=lv, returns=returns, static_roots=members.keys())
    assert t == "РезультатЗапроса"
    entries = resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix="    знч Строка1 = ЗапросКБД.Выполнить().",
        file_stem="Модуль", stdlib_members=members, expr_type=t,
    )
    assert any(e["label"] == "ПервыйИлиНеопределено" for e in entries)


@pytest.mark.needs_data
def test_chain_type_at_dot_after_property():
    # a dot after a PROPERTY link: `Список.НастройкиСервисовУчетныхЗаписей.` - the chain
    # walks property types the same way it walks returns, and the completion trigger
    # (CHAIN_TAIL_RE) must fire without a bracket before the dot. This is the owner's
    # reported dead completion: the first links worked, the property link answered nothing.
    code = (
        "метод А()\n"
        "    знч Список = СпискиПользователей.ПолучитьСписокПоУмолчанию()\n"
        "    знч Х = Список.НастройкиСервисовУчетныхЗаписей.\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    catalog = dataset.load_json("stdlib.json")
    members = {**catalog["type_members"], **catalog["facet_members"]}
    returns = catalog["member_types"]
    line_prefix = "    знч Х = Список.НастройкиСервисовУчетныхЗаписей."
    assert CHAIN_TAIL_RE.search(line_prefix)
    assert not CHAIN_TAIL_RE.search("    знч Х = Список.")  # one link stays on the old paths
    offset = code.index("НастройкиСервисовУчетныхЗаписей.\n") + len("НастройкиСервисовУчетныхЗаписей.")
    lv = local_var_types(src, offset, returns=returns, static_roots=members.keys())
    t = chain_type_at(src, offset, var_types=lv, returns=returns, static_roots=members.keys())
    assert t == "ЧитаемоеМножество"
    entries = resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix=line_prefix,
        file_stem="Модуль", stdlib_members=members, expr_type=t,
    )
    assert any(e["label"] == "Фильтровать" for e in entries)


def test_member_type_head_cuts_the_stored_spelling():
    # The catalog may keep the full docs spelling of a member's result type - every lookup
    # into the type tables goes through the head cut, and bare roots pass unchanged.
    assert dataset.member_type_head("ЧитаемоеМножество<НастройкиСервиса>") == "ЧитаемоеМножество"
    assert dataset.member_type_head("Строка?") == "Строка"
    assert dataset.member_type_head("Массив<Строка>?") == "Массив"
    assert dataset.member_type_head("Пользователи.Объект") == "Пользователи.Объект"
    assert dataset.member_type_head("ЧитаемоеМножество") == "ЧитаемоеМножество"


@pytest.mark.needs_data
def test_chain_type_walks_through_a_full_type_spelling():
    # A catalog that keeps the generic parameter must not break the chain: the full value
    # resolves the next link by its nominal head, and the inferred type is the head too.
    code = (
        "метод А()\n"
        "    знч Х = Клиент.Сервисы().Первый().\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    returns = {
        "КлиентНастроек": {"Сервисы": "ЧитаемоеМножество<НастройкиСервиса>"},
        "ЧитаемоеМножество": {"Первый": "НастройкиСервиса?"},
    }
    offset = code.index("Первый().\n") + len("Первый().")
    t = chain_type_at(
        src, offset, var_types={"Клиент": "КлиентНастроек"},
        returns=returns, static_roots=returns.keys(),
    )
    assert t == "НастройкиСервиса"


@pytest.mark.needs_data
def test_local_var_type_through_property_and_use():
    # `исп` is typed like a regular variable; a property link (Ответ.Тело) goes through
    # member_types the same way a call does
    code = (
        "метод А()\n"
        "    исп Ответ = КлиентHttp.ЗапросGet(\"адрес\").Выполнить()\n"
        "    пер Данные = Ответ.Тело.ПрочитатьКакБайты()\n"
        "    знч Хвост = Данные\n"
        ";\n"
    )
    src = engine.load_text("Модуль.xbsl", code)
    catalog = dataset.load_json("stdlib.json")
    members = {**catalog["type_members"], **catalog["facet_members"]}
    lv = local_var_types(
        src, code.index("знч Хвост"),
        returns=catalog["member_types"], static_roots=members.keys(),
    )
    assert lv.get("Ответ") == "ОтветHttp"
    assert lv.get("Данные") == "Байты"


def test_completion_project_struct_members():
    # a variable of a project type: module structure members come from the index (struct_members)
    idx = dict(INDEX)
    idx["struct_members"] = {
        "ДанныеРасширения": {
            "properties": ["Идентификатор", "ИдентификаторСеанса"],
            "methods": ["ВСтроку2"],
        },
    }
    lookup = IndexLookup(idx)
    entries = resolve_completions(
        lookup, language_id="xbsl", line_prefix="    знч Ид = Данные.",
        file_stem="Модуль", local_vars={"Данные": "ДанныеРасширения"},
    )
    got = {e["label"]: e["kind"] for e in entries}
    assert got == {
        "Идентификатор": "field",
        "ИдентификаторСеанса": "field",
        "ВСтроку2": "method",
    }


def test_completion_yaml_struct_attributes():
    # a yaml-structure-typed variable: attributes of a Структура/ХранимаяСтруктура object
    idx = dict(INDEX)
    idx["objects"] = list(INDEX["objects"]) + [{
        "name": "ДанныеРасширения", "kind": "ХранимаяСтруктура",
        "path": "Плюс/ДанныеРасширения.yaml", "line": 1,
        "tabular": [], "local_types": [], "family": [],
        "attributes": [{"name": "Идентификатор", "line": 5}],
    }]
    lookup = IndexLookup(idx)
    entries = resolve_completions(
        lookup, language_id="xbsl", line_prefix="    знч Ид = Данные.",
        file_stem="Модуль", local_vars={"Данные": "ДанныеРасширения"},
    )
    assert [e["label"] for e in entries] == ["Идентификатор"]


def test_completion_bare_name_top_level():
    # a bare name (no dot): variables, own-module methods, project objects,
    # module types, the global context and stdlib types
    idx = dict(INDEX)
    idx["struct_members"] = {"ДанныеРасширения": {"properties": ["Идентификатор"]}}
    lookup = IndexLookup(idx)
    entries = resolve_completions(
        lookup, language_id="xbsl", line_prefix="    знч ТелоЗапроса = Сериа",
        file_stem="ГлавнаяФорма",
        stdlib_members={"СериализацияJson": {"methods": ["ЗаписатьОбъект"]}, "Массив": {}},
        stdlib_globals=["Сообщить"],
        local_vars={"Данные": "ДанныеРасширения"},
    )
    got = {e["label"]: e["kind"] for e in entries}
    assert got["СериализацияJson"] == "object"      # stdlib type
    assert got["Сообщить"] == "method"              # global context
    assert got["Данные"] == "field"                 # a visible variable
    assert got["Обновить"] == "method"              # own-module method
    assert got["Товар"] == "object"                 # project object
    assert got["ВидТовара"] == "enum"
    assert got["ДанныеРасширения"] == "localType"   # module type


def test_completion_bare_name_not_after_dot():
    # after a dot the bare-name branch does not fire - those positions have contexts of their own
    entries = resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix="    знч Х = Неведомое.Что",
        file_stem="ГлавнаяФорма", stdlib_members={"Массив": {}}, stdlib_globals=["Сообщить"],
    )
    assert entries is None


# ------------------------------------------------------------------------- code templates

def _tmpl(name, pattern, contexts=(tpl.STATEMENT_CONTEXT,)):
    return tpl.Template(name=name, pattern=pattern, contexts=contexts)


def ct(prefix, templates, in_query=False):
    return resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix=prefix, file_stem="ГлавнаяФорма",
        in_query=in_query, templates=templates,
    ) or []


def test_completion_offers_templates_on_a_bare_name():
    entries = ct("    ", [_tmpl("если - Если", 'если ${Редактировать("Условие")}')])
    first = entries[0]
    assert (first["label"], first["kind"], first["detail"]) == ("если", "snippet", "Если")
    assert first["snippet"] == "если ${1:Условие}"


def test_templates_come_before_the_other_completions():
    # Ctrl+Space shows templates before names - the server sets the order, sortText seals the rank.
    entries = ct("    ", [_tmpl("тов[ар] - Товар шаблоном", "товар")])
    kinds = [e["kind"] for e in entries]
    assert kinds[0] == "snippet"
    assert "snippet" not in kinds[1:]


def test_template_object_variable_is_filled_from_the_project_index():
    entries = ct("    ", [_tmpl("обх - Обход", "для Э из Справочник.${ИмяОбъектаМетаданного(Справочник)}")])
    assert entries[0]["snippet"] == "для Э из Справочник.${1|Товар|}"


def test_template_full_object_variable_inserts_kind_and_name():
    entries = ct("    ", [_tmpl("пер - Перечисление", '${ПолноеИмяОбъектаМетаданного("Перечисление")}')])
    assert entries[0]["snippet"] == "${1|Перечисление.ВидТовара|}"


def test_template_object_variable_of_an_absent_kind_prompts_instead():
    entries = ct("    ", [_tmpl("док - Документ", "${ИмяОбъектаМетаданного(Документ)}")])
    assert entries[0]["snippet"] == "${1:Документ}"


def test_query_templates_are_offered_only_inside_a_query():
    items = [
        _tmpl("если - Если", "если", contexts=(tpl.STATEMENT_CONTEXT,)),
        _tmpl("выбрать - ВЫБРАТЬ", "ВЫБРАТЬ", contexts=(tpl.QUERY_CONTEXT,)),
    ]
    assert [e["label"] for e in ct("    ", items) if e["kind"] == "snippet"] == ["если"]
    assert [e["label"] for e in ct("    ", items, in_query=True) if e["kind"] == "snippet"] == ["выбрать"]


def test_templates_do_not_leak_after_a_dot():
    entries = resolve_completions(
        LOOKUP, language_id="xbsl", line_prefix="знч Х = Товар.", file_stem="ГлавнаяФорма",
        templates=[_tmpl("если - Если", "если")],
    )
    assert "snippet" not in {e["kind"] for e in entries}


def test_completion_without_templates_is_unchanged():
    assert [e["kind"] for e in ct("    ", None) if e["kind"] == "snippet"] == []


def test_hover_component_carries_type_for_docs_link():
    # The component-member hover shows the component's TYPE; the hoverDoc doc link reuses this exact
    # resolution (chain_at + lookup.component) to point at the type's documentation page.
    got = resolve_hover(
        LOOKUP,
        language_id="xbsl",
        line_text="Компоненты.Кнопка.Активировать()",
        character=13,
        file_stem="ГлавнаяФорма",
        file_path="Каталог/ГлавнаяФорма.xbsl",
    )
    assert got is not None and "Кнопка: Кнопка" in got


def test_hover_doc_request_registered():
    # xbsl/hoverDoc (the doc link in the code-editor hover) is wired on the server.
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    assert "xbsl/hoverDoc" in features
    # no document open in the bare workspace -> a clean empty result, never an exception
    res = features["xbsl/hoverDoc"]({"uri": "file:///нет.xbsl", "position": {"line": 0, "character": 0}})
    assert res == {"pageId": None, "symbol": None}


def test_docs_by_name_request_registered():
    # xbsl/docsByName (the metadata-tree category tooltip) is wired and never raises. Without the
    # docs bundle for_symbol returns nothing -> an empty dict, not an exception.
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    assert "xbsl/docsByName" in features
    assert features["xbsl/docsByName"]({"name": "нетТакогоТипа"}) == {}
    assert features["xbsl/docsByName"]({}) == {}


def test_search_forms_request_registered():
    # xbsl/searchForms (the structural search across forms, hook 10) is wired and zips its two
    # parallel arrays; an empty request yields an empty match list, never an exception.
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    assert "xbsl/searchForms" in features
    assert features["xbsl/searchForms"]({}) == {"matches": []}
    form = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n    Содержимое:\n        Тип: Кнопка\n        Имя: К\n"
    res = features["xbsl/searchForms"]({"paths": ["a.yaml"], "texts": [form], "query": "Кнопка"})
    assert [m["name"] for m in res["matches"]] == ["К"]


def test_binding_complete_request_registered():
    # xbsl/bindingComplete (the form binding editor's component-reference completions) is wired
    # and never raises. Without a built index (a bare workspace) it yields an empty list, and a
    # garbage request yields one too – an empty result, never an exception.
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp as lsp_module

    server = lsp_module._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    features = getattr(fm, "features", fm)
    assert "xbsl/bindingComplete" in features
    assert features["xbsl/bindingComplete"]({}) == {"completions": []}
    assert features["xbsl/bindingComplete"](
        {"uri": "file:///нет.yaml", "prefix": "=Компоненты."}
    ) == {"completions": []}
