"""Tests of the pure LSP navigation core (a port of the extension's navCore tests)."""

from xbsllint import engine
from xbsllint.lsp_nav import IndexLookup, chain_at, resolve_completions, resolve_definition, resolve_hover
from xbsllint.rules._syntax import local_var_types, query_aliases, query_row_columns

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


def test_definition_unknown_contexts():
    assert d("Неведомое.Что", 3) is None
    assert d("А.Б.В.Г", 6) is None  # глубокая цепочка без Компоненты – вне охвата


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


def test_query_aliases_from_and_join():
    # алиасы таблиц запроса – так к таблицам обращаются в реальном коде
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    inside = МОДУЛЬ_С_ЗАПРОСОМ.index("А.Заголовок")
    assert query_aliases(src, inside) == {"А": "Акция", "П": "Программа"}
    # вне блока запроса карты нет
    outside = МОДУЛЬ_С_ЗАПРОСОМ.index("возврат 0")
    assert query_aliases(src, outside) == {}


def test_query_row_columns_for_loop():
    # `знч Результат = Запрос{...}` + `для С из Результат` -> у С колонки выборки: алиас КАК,
    # поле без алиаса (последний сегмент), вычисляемое выражение только с алиасом
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ_С_ЗАПРОСОМ)
    got = query_row_columns(src, МОДУЛЬ_С_ЗАПРОСОМ.index("С.Заголовок"))
    assert got == {"С": ["Заголовок", "Слаг", "Вес"]}


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


def test_local_var_types_scoped_to_method():
    # переменные соседнего метода в область видимости не затекают
    src = engine.load_text("Модуль.xbsl", МОДУЛЬ)
    got = local_var_types(src, МОДУЛЬ.index("возврат Индекс"))
    assert got == {"Индекс": "Соответствие"}


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
