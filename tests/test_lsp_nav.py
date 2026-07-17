"""Tests of the pure LSP navigation core (a port of the extension's navCore tests).

The core itself needs no Element data - it works over the project index. The tests of the
syntactic helpers (types of locals, query aliases and columns) do run the lexer, so they carry
`needs_data` and are skipped in a checkout without the data bundle.
"""

import pytest

from xbsl import dataset, engine
from xbsl.lsp_nav import (
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
        # метод Загрузить (модуль Товар): объявление, свой-модульный вызов, вызов Товар.Загрузить(), шум
        {"name": "Загрузить", "qualifier": "", "module": "Товар", "path": "Каталог/Товар.xbsl", "line": 20, "col": 4},
        {"name": "Загрузить", "qualifier": "", "module": "Товар", "path": "Каталог/Товар.xbsl", "line": 25, "col": 8},
        {"name": "Загрузить", "qualifier": "Товар", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 6, "col": 10},
        {"name": "Загрузить", "qualifier": "Прочее", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 50, "col": 4},
        # метод Обновить (модуль ГлавнаяФорма): вызов в коде и yaml-обработчик
        {"name": "Обновить", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 12, "col": 4},
        {"name": "Обновить", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.yaml", "line": 33, "col": 20},
        # объект Товар как корень цепочки
        {"name": "Товар", "qualifier": "", "module": "ГлавнаяФорма", "path": "Каталог/ГлавнаяФорма.xbsl", "line": 6, "col": 0},
        # компонент Кнопка формы ГлавнаяФорма (использование в коде) и метод Нажать её модуля
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
    assert d("Обновить()", 2) == ("Каталог/ГлавнаяФорма.xbsl", 5)  # свой модуль по file_stem
    assert d("Компоненты.Кнопка.Видимость", 12) == ("Каталог/ГлавнаяФорма.yaml", 33)
    assert d("Компоненты.Кнопка.Нажать()", 20) == ("Каталог/Кнопка.xbsl", 7)


def test_definition_yaml_handler():
    assert d("    Обработчик: Обновить", 20, language_id="yaml",
             file_path="Каталог/ГлавнаяФорма.yaml") == ("Каталог/ГлавнаяФорма.xbsl", 5)
    # вне значения обработчика – молчание
    assert d("    Обработчик: Обновить", 3, language_id="yaml") is None


def test_definition_yaml_handler_with_comment():
    # хвостовой комментарий после имени обработчика не мешает переходу
    assert d("    Обработчик: Обновить # клик", 20, language_id="yaml",
             file_path="Каталог/ГлавнаяФорма.yaml") == ("Каталог/ГлавнаяФорма.xbsl", 5)


def test_definition_unknown_contexts():
    assert d("Неведомое.Что", 3) is None
    assert d("А.Б.В.Г", 6) is None  # глубокая цепочка без Компоненты – вне охвата


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
    # курсор на Товар.Загрузить(): использования метода Загрузить модуля Товар
    got = r("Товар.Загрузить()", 8)
    sites = _sites(got)
    assert ("Каталог/ГлавнаяФорма.xbsl", 6) in sites  # Товар.Загрузить() в форме
    assert ("Каталог/Товар.xbsl", 25) in sites  # голый вызов в своём модуле
    assert ("Каталог/Товар.xbsl", 20) not in sites  # объявление исключено
    assert ("Каталог/ГлавнаяФорма.xbsl", 50) not in sites  # чужой qualifier Прочее – не наш метод


def test_references_include_declaration():
    got = r("Товар.Загрузить()", 8, include_declaration=True)
    assert ("Каталог/Товар.xbsl", 20) in _sites(got)  # объявление добавлено


def test_references_method_from_yaml_handler():
    # обработчик в yaml -> использования метода Обновить (и сам сайт обработчика – тоже использование)
    got = r("    Обработчик: Обновить", 20, language_id="yaml", file_path="Каталог/ГлавнаяФорма.yaml")
    sites = _sites(got)
    assert ("Каталог/ГлавнаяФорма.xbsl", 12) in sites
    assert ("Каталог/ГлавнаяФорма.yaml", 33) in sites


def test_references_object():
    # объект Товар как корень цепочки
    got = r("знч Х = Товар.Ссылка", 11)
    assert _sites(got) == {("Каталог/ГлавнаяФорма.xbsl", 6)}


def test_references_component():
    # компонент Кнопка через Компоненты в форме ГлавнаяФорма (использование в коде, не строка yaml-узла)
    got = r("Компоненты.Кнопка.Видимость", 13)
    assert _sites(got) == {("Каталог/ГлавнаяФорма.xbsl", 8)}


def test_references_col_and_length():
    # позиция несёт col (0-based) и длину имени для выделения
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
    assert "Объект" not in labels  # член объекта/менеджера, не поле таблицы
    assert all(e["kind"] == "field" for e in entries)


def test_completion_query_table_alias():
    # к таблицам в проекте обращаются через алиас (`ИЗ Товар КАК Т`) – после `Т.` те же поля
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
    # Вне блока Запрос{...} после точки – прежнее поведение (члены объекта).
    labels = {e["label"] for e in c("знч Х = Товар.")}
    assert "Объект" in labels


def test_completion_stdlib_type_members():
    # не проект-объект, но stdlib-тип/глобаль – члены из type_members датасета: свойства и методы
    # раздельно (у метода свой вид и скобки при вставке)
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
    # старый датасет (плоский список имён, свойства и методы вперемешку) – совместимость
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
    # пер Список = новый Массив<Строка>() -> Список. даёт члены Массива (тип переменной считает
    # вызывающий, лексером)
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
    # переменная перекрывает одноимённый stdlib-тип: `пер Список = новый Массив<...>()` – это про
    # члены Массива, а не про компонент Список
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
    # тип переменной – структура проекта, а не stdlib: подсказывать нечем, уступаем словарному
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
    # неизвестный токен (не проект-объект и не stdlib) – None, уступаем словарному дополнению
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
    assert c("просто текст") is None


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
    # алиасы таблиц запроса – так к таблицам обращаются в реальном коде
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    inside = МОДУЛЬ_С_ЗАПРОСОМ.index("А.Заголовок")
    assert query_aliases(src, inside) == {"А": "Акция", "П": "Программа"}
    # вне блока запроса карты нет
    outside = МОДУЛЬ_С_ЗАПРОСОМ.index("возврат 0")
    assert query_aliases(src, outside) == {}


@pytest.mark.needs_data
def test_query_row_columns_for_loop():
    # `знч Результат = Запрос{...}` + `для С из Результат` -> у С колонки выборки: алиас КАК,
    # поле без алиаса (последний сегмент), вычисляемое выражение только с алиасом
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    got = query_row_columns(src, МОДУЛЬ_С_ЗАПРОСОМ.index("С.Заголовок"))
    assert got == {"С": ["Заголовок", "Слаг", "Вес"]}


@pytest.mark.needs_data
def test_query_row_columns_only_above_cursor():
    # цикл ниже курсора ещё не виден
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    assert query_row_columns(src, МОДУЛЬ_С_ЗАПРОСОМ.index("знч Результат")) == {}


def test_completion_query_row_member():
    # С. внутри `для С из Результат` -> колонки строки результата
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
    # тип берётся из инициализации (новый Массив<...>) и из аннотации; дженерик-параметр
    # отбрасывается – члены типа от него не зависят; параметры метода тоже дают тип
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
    # переменные соседнего метода в область видимости не затекают
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("возврат Индекс"))
    assert got == {"Индекс": "Соответствие"}


@pytest.mark.needs_data
def test_local_var_types_only_above_cursor():
    # объявления ниже курсора ещё не видны
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("пер Список"))
    assert got == {"Ключи": "Массив", "Лимит": "Число"}


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
    # `знч З = Запрос{...}` конструирует ТипизированныйЗапрос (topics/query-literal):
    # после `З.` должны подсказываться Выполнить и компания
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
    # у регистров поля живут в Измерениях и Ресурсах - подсказка полей таблицы в
    # Запрос{...} обязана их видеть (реквизитов у регистра может не быть вовсе)
    entries = _query_field_entries(
        "РегистрСведений", [], [],
        [{"name": "Настройка"}], [{"name": "Значение"}],
    )
    got = {e["label"]: e["detail"] for e in entries}
    assert got == {"Настройка": "измерение", "Значение": "ресурс"}


@pytest.mark.needs_data
def test_local_var_type_from_call_chain():
    # тип из возврата метода: статическая фабрика и цепочка на переменной
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
    # точка после вызова: `ЗапросКБД.Выполнить().` - тип цепочки слева от курсора
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
def test_local_var_type_through_property_and_use():
    # `исп` типизируется как обычная переменная; звено-свойство (Ответ.Тело) идёт
    # через member_types так же, как вызов
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
    # переменная проектного типа: члены структуры модуля - из индекса (struct_members)
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
    # переменная типа yaml-структуры: реквизиты объекта вида Структура/ХранимаяСтруктура
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
