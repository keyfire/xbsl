"""Чистые функции сравнения версий данных (xbsl/datadiff.py) - на синтетических структурах.

Файлы данных не нужны: сравниватели принимают уже загруженные словари, рендеры - готовый
дифф. Версии в фикстурах вымышленные.
"""

from __future__ import annotations

from xbsl import datadiff


def test_previous_version_orders_numerically():
    available = ["1.10.0", "1.9.8+11", "1.2.0"]
    assert datadiff.previous_version("1.10.0", available) == "1.9.8+11"
    assert datadiff.previous_version("1.2.0", available) is None


def test_diff_language_keywords_forms_operators():
    old = {"keywords": {"AND": {"forms": ["and", "и"]}, "OLD": {"forms": ["old"]}},
           "operators": ["+", "-"]}
    new = {"keywords": {"AND": {"forms": ["and", "и", "And"]}, "NEW": {"forms": ["new"]}},
           "operators": ["+", "??"]}
    diff = datadiff.diff_language(old, new)
    assert diff["keywords"] == {"added": ["NEW"], "removed": ["OLD"]}
    assert diff["forms"] == {"AND": {"added": ["And"]}}
    assert diff["operators"] == {"added": ["??"], "removed": ["-"]}


def test_diff_stdlib_types_members_and_result_types():
    old = {
        "type_members": {"Массив": {"methods": ["Добавить"]}, "Старый": {"methods": ["М"]}},
        "member_types": {"Массив": {"Добавить": "Число"}},
        "globals": ["Мин"],
    }
    new = {
        "type_members": {"Массив": {"methods": ["Добавить", "Вставить"]}, "Новый": {"methods": ["М"]}},
        "member_types": {"Массив": {"Добавить": "Строка"}},
        "globals": ["Мин", "Макс"],
    }
    diff = datadiff.diff_stdlib(old, new)
    assert diff["types"] == {"added": ["Новый"], "removed": ["Старый"]}
    assert diff["members"]["Массив"]["methods"] == {"added": ["Вставить"]}
    assert diff["member_types"] == {"Массив.Добавить": ["Число", "Строка"]}
    assert diff["globals"] == {"added": ["Макс"]}


def test_diff_stdlib_members_compare_expanded_and_lift_to_the_root():
    # 1.2.3+4: the hierarchy went unresolved - the heir carries every member as its own.
    # 1.3.0: the same members split between the base and the heir. Expansion makes the
    # sets equal, so the split itself is NOT a change; the genuinely new base member is
    # reported once - at the base, not at every heir.
    old = {
        "type_members": {
            "Компонент": {"properties": ["Видимость"]},
            "Кнопка": {"properties": ["Видимость", "Заголовок"]},
        },
        "bases": {"Кнопка": []},
    }
    new = {
        "type_members": {
            "Компонент": {"properties": ["Видимость", "Подсказка"]},
            "Кнопка": {"properties": ["Заголовок"]},
        },
        "bases": {"Кнопка": ["Компонент"]},
    }
    diff = datadiff.diff_stdlib(old, new)
    assert diff["members"] == {"Компонент": {"properties": {"added": ["Подсказка"]}}}


def test_diff_stdlib_member_type_change_reported_at_the_root_only():
    old = {
        "type_members": {},
        "member_types": {"Коллекция": {"Объединить": "Коллекция<Т>"},
                         "Массив": {"Объединить": "Коллекция<Т>"}},
        "bases": {"Массив": ["Коллекция"]},
    }
    new = {
        "type_members": {},
        "member_types": {"Коллекция": {"Объединить": "Коллекция"},
                         "Массив": {"Объединить": "Коллекция"}},
        "bases": {"Массив": ["Коллекция"]},
    }
    diff = datadiff.diff_stdlib(old, new)
    assert diff["member_types"] == {"Коллекция.Объединить": ["Коллекция<Т>", "Коллекция"]}


def test_diff_metamodel_props_enums_vids():
    old = {
        "classes": {"Widget": {"props": {"Имя": {"type": "str"}, "Цвет": {"req": False}}}},
        "enums": {"Вид": ["А", "Б"]},
        "vid2class": {"Справочник": "CatalogModel"},
    }
    new = {
        "classes": {"Widget": {"props": {"Имя": {"type": "str"}, "Цвет": {"req": True},
                                         "Представление": {}}}},
        "enums": {"Вид": ["А", "В"]},
        "vid2class": {"Справочник": "CatalogDescriptor"},
    }
    diff = datadiff.diff_metamodel(old, new)
    assert diff["props"]["Widget"]["added"] == ["Представление"]
    assert diff["props"]["Widget"]["changed"] == {"Цвет": ["req"]}
    assert diff["enum_values"]["Вид"] == {"added": ["В"], "removed": ["Б"]}
    assert diff["vid2class"]["changed"] == {"Справочник": ["CatalogModel", "CatalogDescriptor"]}


def test_diff_uischema_props_and_flags():
    old = {"components": {"Кнопка": {"package": "Стд::А", "props": {
        "Вид": {"types": ["Авто"], "doc": "старый текст"}}}}}
    new = {"components": {"Кнопка": {"package": "Стд::Б", "abstract": True, "props": {
        "Вид": {"types": ["Авто", "ВидКнопки"], "doc": "новый текст"},
        "Иконка": {"types": ["Строка"]}}}}}
    diff = datadiff.diff_uischema(old, new)
    assert diff["props"]["Кнопка"]["added"] == ["Иконка"]
    # doc не сравнивается - только структурные ключи
    assert diff["props"]["Кнопка"]["changed"] == {"Вид": ["types"]}
    assert diff["flags"]["Кнопка"]["package"] == ["Стд::А", "Стд::Б"]
    assert diff["flags"]["Кнопка"]["abstract"] == [None, True]


def test_diff_terms_reports_changed_pairs():
    old = {"types": {"Запрос": "Query", "Старый": "Old"}}
    new = {"types": {"Запрос": "DataQuery", "Новый": "New"}}
    diff = datadiff.diff_terms(old, new)
    assert diff["types"]["added"] == ["Новый"]
    assert diff["types"]["removed"] == ["Старый"]
    assert diff["types"]["changed"] == {"Запрос": ["Query", "DataQuery"]}


def test_diff_docs_pages_added_removed_retitled():
    old = {"a": ("Один", "type"), "b": ("Два", "type")}
    new = {"b": ("Два-новое", "type"), "c": ("Три", "member")}
    diff = datadiff.diff_docs(old, new)
    assert diff["pages"]["added"] == [["c", "Три", "member"]]
    assert diff["pages"]["removed"] == [["a", "Один", "type"]]
    assert diff["pages"]["retitled"] == {"b": ["Два", "Два-новое"]}
    assert diff["counts"] == {"old": 2, "new": 2}


def _sample_diff() -> dict:
    return {
        "meta": {"old": "1.2.3+4", "new": "1.3.0", "root": "r"},
        "language": {"operators": {"added": ["??"]}},
        "stdlib": {"members": {"Массив": {"methods": {"added": ["Вставить", "Найти", "Слить"]}}}},
        "metamodel": {},
        "uischema": {"props": {"Кнопка": {"changed": {"Вид": ["types"]}}}},
        "terms": {"types": {"changed": {"Запрос": ["Query", "DataQuery"]}}},
        "docs": {"pages": {"added": [["c", "Три", "member"]]}, "counts": {"old": 1, "new": 2}},
    }


def test_render_text_caps_lists_and_marks_sections():
    text = datadiff.render_text(_sample_diff(), limit=2)
    assert "1.2.3+4 -> 1.3.0" in text
    assert "+ ??" in text
    assert "и ещё 1" in text          # лимит 2 из 3 методов
    assert "изменений нет" in text    # пустая секция метамодели
    assert "Три" in text


def test_render_markdown_is_uncapped_and_structured():
    md = datadiff.render_markdown(_sample_diff())
    assert md.startswith("# ")
    assert "## " in md
    assert "Вставить, Найти, Слить" in md   # без лимита
    assert "Запрос: Query -> DataQuery" in md


def test_prune_drops_empty_branches():
    assert datadiff._prune({"a": {"b": []}, "c": {"d": {"e": None}}, "keep": ["x"]}) == {"keep": ["x"]}

def test_a_member_that_changed_kind_is_a_move_not_a_removal():
    """A newer documentation gave events a section of their own, and the diff of the datasets reported
    dozens of them as REMOVED - Кнопка without ПриНажатии, ПолеВвода without ПриИзменении -
    while the API had not changed at all. A member that left one kind and joined another is
    reported as a move, and neither half is counted as a change of the API."""
    old = {"type_members": {"Кнопка": {"properties": ["Заголовок", "ПриНажатии"]}}, "bases": {}}
    new = {"type_members": {"Кнопка": {"properties": ["Заголовок"], "events": ["ПриНажатии"]}},
           "bases": {}}

    report = datadiff.diff_stdlib(old, new)

    assert report["members"]["Кнопка"] == {"moved": {"ПриНажатии": ["properties", "events"]}}


def test_a_member_that_really_went_away_is_still_a_removal():
    """The control: without a place to move to, a disappearance stays a disappearance."""
    old = {"type_members": {"Кнопка": {"properties": ["Заголовок", "Устаревшее"]}}, "bases": {}}
    new = {"type_members": {"Кнопка": {"properties": ["Заголовок"]}}, "bases": {}}

    report = datadiff.diff_stdlib(old, new)

    assert report["members"]["Кнопка"] == {"properties": {"removed": ["Устаревшее"]}}
