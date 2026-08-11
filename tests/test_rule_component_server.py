"""Checks of code/component-in-server-context (xbsl/rules/environment.py).

The fixtures repeat the live failure: a client-and-server common module called a static
method of an interface component, the linter said nothing, and the apply refused with
`<Сервер> Переменная ЛичныйКабинет не определена` - the component's type lives on the
client and its name is not declared in the server environment.
"""

from xbsl import engine, i18n

RULE = "code/component-in-server-context"

_COMPONENT = engine.load_text(
    "ЛичныйКабинет.yaml",
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3aa\n"
    "Имя: ЛичныйКабинет\n",
)

_BOTH_MODULE = engine.load_text(
    "ПосетительСайта.yaml",
    "ВидЭлемента: ОбщийМодуль\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ab\n"
    "Имя: ПосетительСайта\n"
    "Окружение: КлиентИСервер\n",
)

_SERVER_MODULE = engine.load_text(
    "СерверныеДанные.yaml",
    "ВидЭлемента: ОбщийМодуль\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ac\n"
    "Имя: СерверныеДанные\n"
    "Окружение: Сервер\n",
)

_CLIENT_MODULE = engine.load_text(
    "КлиентскиеДанные.yaml",
    "ВидЭлемента: ОбщийМодуль\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ad\n"
    "Имя: КлиентскиеДанные\n"
    "Окружение: Клиент\n",
)

_CALL = "    возврат ЛичныйКабинет.ИмяВошедшегоПользователя()\n"


def _lint(*sources):
    return engine.run_sources(list(sources), select={RULE})


def test_component_call_in_both_environments_module_flagged():
    """The live failure: an unannotated method of a КлиентИСервер module is compiled for
    the server too, and there the component's name does not exist."""
    i18n.set_lang("ru")
    try:
        d = _lint(_COMPONENT, _BOTH_MODULE, engine.load_text(
            "ПосетительСайта.xbsl",
            "метод Сведения(): Строка\n" + _CALL + ";\n"))
        assert len(d) == 1
        assert d[0].rule_id == RULE and d[0].severity.value == "error"
        assert "ЛичныйКабинет.ИмяВошедшегоПользователя" in d[0].message
        assert "не определена" in d[0].message
        assert d[0].line == 2
    finally:
        i18n.set_lang(None)


def test_component_call_in_server_module_flagged():
    d = _lint(_COMPONENT, _SERVER_MODULE, engine.load_text(
        "СерверныеДанные.xbsl",
        "метод Прочитать(): Строка\n" + _CALL + ";\n"))
    assert len(d) == 1


def test_component_call_in_on_server_method_of_a_component_flagged():
    """The side benefit named in the backlog: a @НаСервере method of a component module
    reaching for a component (its own or another) runs on the server all the same."""
    other = engine.load_text(
        "Карточка.yaml",
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ae\n"
        "Имя: Карточка\n",
    )
    d = _lint(_COMPONENT, other, engine.load_text(
        "Карточка.xbsl",
        "@НаСервере\nметод Прочитать(): Строка\n" + _CALL + ";\n"))
    assert len(d) == 1


def test_component_call_in_client_module_silent():
    assert _lint(_COMPONENT, _CLIENT_MODULE, engine.load_text(
        "КлиентскиеДанные.xbsl",
        "метод Показать(): Строка\n" + _CALL + ";\n")) == []


def test_component_call_in_unannotated_component_method_silent():
    """A component module lives on the client - its plain methods reach components freely."""
    other = engine.load_text(
        "Карточка.yaml",
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3ae\n"
        "Имя: Карточка\n",
    )
    assert _lint(_COMPONENT, other, engine.load_text(
        "Карточка.xbsl",
        "метод Показать(): Строка\n" + _CALL + ";\n")) == []


def test_on_client_method_in_both_module_silent():
    """@НаКлиенте pins the client side - the exact fix the message suggests."""
    assert _lint(_COMPONENT, _BOTH_MODULE, engine.load_text(
        "ПосетительСайта.xbsl",
        "@НаКлиенте\nметод Сведения(): Строка\n" + _CALL + ";\n")) == []


def test_namesake_of_another_kind_is_left_alone():
    """A name that also belongs to a non-component element (a namesake across subsystems)
    is not judged - the reference may mean the other element."""
    namesake = engine.load_text(
        "Тёзка.yaml",
        "ВидЭлемента: Перечисление\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3af\n"
        "Имя: ЛичныйКабинет\n",
    )
    assert _lint(_COMPONENT, namesake, _SERVER_MODULE, engine.load_text(
        "СерверныеДанные.xbsl",
        "метод Прочитать(): Строка\n" + _CALL + ";\n")) == []


def test_shadowed_name_is_left_alone():
    """A local of the same name gives the identifier its own meaning."""
    assert _lint(_COMPONENT, _SERVER_MODULE, engine.load_text(
        "СерверныеДанные.xbsl",
        "метод Прочитать(ЛичныйКабинет: Строка): Строка\n"
        "    возврат ЛичныйКабинет.ВРег()\n;\n")) == []


def test_module_without_environment_is_not_guessed():
    """A common module whose yaml names no environment is skipped: the default is not
    documented, and a guess would trade a false negative for a false positive."""
    bare = engine.load_text(
        "БезОкружения.yaml",
        "ВидЭлемента: ОбщийМодуль\n"
        "Ид: 019ef4c8-232f-7f33-9da6-c3604720b3b0\n"
        "Имя: БезОкружения\n",
    )
    assert _lint(_COMPONENT, bare, engine.load_text(
        "БезОкружения.xbsl",
        "метод Сведения(): Строка\n" + _CALL + ";\n")) == []
