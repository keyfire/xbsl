"""Checks of code/global-unavailable (xbsl/rules/environment.py).

The fixtures repeat the live failure: `Сообщить(...)` in a catalog module passed the
linter and failed the apply with `Метод "Сообщить" недоступен в текущем окружении` - the
global exists on the client only, while a catalog module runs on the server.
"""

from xbsl import engine, i18n

RULE = "code/global-unavailable"

_CATALOG = engine.load_text(
    "Задачи.yaml",
    "ВидЭлемента: Справочник\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3aa\n"
    "Имя: Задачи\n",
)

_FORM = engine.load_text(
    "Панель.yaml",
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ad\n"
    "Имя: Панель\n",
)


def _lint(*sources):
    return engine.run_sources(list(sources), select={RULE})


def test_client_global_in_catalog_module_flagged():
    i18n.set_lang("ru")
    try:
        d = _lint(_CATALOG, engine.load_text(
            "Задачи.xbsl",
            "метод Предупредить()\n    Сообщить(\"нельзя\")\n;\n"))
        assert len(d) == 1
        assert d[0].rule_id == RULE and d[0].severity.value == "error"
        assert "Сообщить" in d[0].message and "на сервере" in d[0].message
        assert d[0].line == 2 and d[0].col == 5
    finally:
        i18n.set_lang(None)


def test_object_module_judged_via_entity_yaml():
    """X.Объект.xbsl adds one dotted suffix to the entity's stem and is server code too."""
    d = _lint(_CATALOG, engine.load_text(
        "Задачи.Объект.xbsl",
        "метод ПередЗаписью()\n    Сообщить(\"нельзя\")\n;\n"))
    assert len(d) == 1


def test_client_global_in_form_module_silent():
    assert _lint(_FORM, engine.load_text(
        "Панель.xbsl",
        "@Обработчик\nметод Показать()\n    Сообщить(\"можно\")\n;\n")) == []


def test_on_client_method_makes_it_client_code():
    """Living reference code keeps @НаКлиенте methods inside catalog modules - the annotation
    pins the client side, and a client-only global is at home there."""
    assert _lint(_CATALOG, engine.load_text(
        "Задачи.xbsl",
        "@НаКлиенте\nметод Показать()\n    Сообщить(\"можно\")\n;\n")) == []


def test_server_global_in_client_method_flagged():
    i18n.set_lang("ru")
    try:
        d = _lint(_FORM, engine.load_text(
            "Панель.xbsl",
            "@Обработчик\nметод Посчитать()\n    знч Итог = Вычислить(\"2 + 2\")\n;\n"))
        assert len(d) == 1
        assert "Вычислить" in d[0].message and "@НаСервере" in d[0].message
    finally:
        i18n.set_lang(None)


def test_on_server_method_makes_it_server_code():
    assert _lint(_FORM, engine.load_text(
        "Панель.xbsl",
        "@НаСервере\nметод Посчитать()\n    знч Итог = Вычислить(\"2 + 2\")\n;\n")) == []


def test_on_server_method_loses_client_globals():
    """The same annotation cuts the other way: a @НаСервере method of a form module is
    server code, and Сообщить does not exist there."""
    d = _lint(_FORM, engine.load_text(
        "Панель.xbsl",
        "@НаСервере\nметод Записать()\n    Сообщить(\"нельзя\")\n;\n"))
    assert len(d) == 1


def test_both_annotations_skip_the_method():
    """@НаСервере @НаКлиенте runs where it is called from - skipped, not guessed."""
    assert _lint(_FORM, engine.load_text(
        "Панель.xbsl",
        "@НаСервере @НаКлиенте\nметод Показать()\n    Сообщить(\"как позовут\")\n;\n")) == []


def test_common_module_by_environment():
    сервер = engine.load_text(
        "Фоновое.yaml",
        "ВидЭлемента: ОбщийМодуль\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ba\n"
        "Имя: Фоновое\nОкружение: Сервер\n")
    d = _lint(сервер, engine.load_text(
        "Фоновое.xbsl", "метод Прогнать()\n    Сообщить(\"нельзя\")\n;\n"))
    assert len(d) == 1


def test_own_method_shadows_the_global():
    """A module method called Сообщить is the project's own name - nothing is judged."""
    assert _lint(_CATALOG, engine.load_text(
        "Задачи.xbsl",
        "метод Сообщить(Текст: Строка)\n    ЖурналСобытий.Записать(Текст)\n;\n"
        "метод Предупредить()\n    Сообщить(\"своё\")\n;\n")) == []


def test_everywhere_global_silent():
    """Округлить and the other КлиентИСервер names are at home on both sides."""
    assert _lint(_CATALOG, engine.load_text(
        "Задачи.xbsl",
        "метод Посчитать()\n    знч С = Округлить(1.5)\n;\n")) == []


def test_message_is_bilingual():
    i18n.set_lang("en")
    try:
        d = _lint(_CATALOG, engine.load_text(
            "Задачи.xbsl",
            "метод Предупредить()\n    Сообщить(\"нельзя\")\n;\n"))
        assert d and "on the client only" in d[0].message
    finally:
        i18n.set_lang(None)
