"""code/image-binding-server-call (xbsl/rules/image_binding.py).

The fixtures repeat the live shape: an Image property bound to an expression whose call
reaches a server method - directly (a catalog member) or through a client wrapper of the
form module - draws the rows first and fetches the picture by its own server round-trip,
re-requested on every redraw. The negative controls pin the narrowings: a client method
without server calls, a bare data path without a call (the cure), a constructor head, an
unresolved name, and a project component's own property named like the platform's.

Every test needs the Element data: the node gate is the set of schema components that
declare the Image property, and the module scan needs the language data of the lexer.
"""

import pytest

from xbsl import engine, i18n

RULE = "code/image-binding-server-call"

CATALOG = (
    "ВидЭлемента: Справочник\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c36047203001\n"
    "Имя: Значки\n"
)
CATALOG_MODULE = (
    "@НаСервере @ДоступноСКлиента\n"
    "метод ИконкаПоКоду(Код: Строка): Строка\n"
    "    возврат Код\n"
    ";\n"
)
FORM_HEAD = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 019ef4c8-232f-7f33-9da6-c36047203002\n"
    "Имя: ФормаСписка\n"
    "Содержимое:\n"
)


def _form(image_value: str) -> str:
    return (
        FORM_HEAD
        + "    -\n"
        + "        Тип: Картинка\n"
        + "        Имя: Логотип\n"
        + f"        Изображение: {image_value}\n"
    )


def _lint(files: dict[str, str]):
    sources = [engine.load_text(name, content) for name, content in files.items()]
    return engine.run_sources(sources, select={RULE})


@pytest.mark.needs_data
def test_direct_server_element_call_flagged():
    """The corpus shape: a catalog member called right in the binding. The element module
    lives on the server whole, so the call is a hop whatever the method declares."""
    i18n.set_lang("ru")
    try:
        d = _lint({
            "Значки.yaml": CATALOG,
            "ФормаСписка.yaml": _form('=Значки.ИконкаПоКоду("а")'),
        })
        assert len(d) == 1
        assert d[0].rule_id == RULE and d[0].severity.value == "info"
        assert "Значки.ИконкаПоКоду" in d[0].message
        assert d[0].line == 8
    finally:
        i18n.set_lang(None)


@pytest.mark.needs_data
def test_wrapper_through_client_method_flagged():
    """The measured live case: the binding calls a client method of the form module and
    the server hop hides one step deeper - the transitive walk is what finds it."""
    i18n.set_lang("ru")
    try:
        d = _lint({
            "Значки.yaml": CATALOG,
            "Значки.xbsl": CATALOG_MODULE,
            "ФормаСписка.yaml": _form("=ИконкаСтроки(Данные)"),
            "ФормаСписка.xbsl": (
                "метод ИконкаСтроки(Код: Строка): Строка\n"
                "    возврат Значки.ИконкаПоКоду(Код)\n"
                ";\n"
            ),
        })
        assert len(d) == 1
        assert "ИконкаСтроки" in d[0].message
        assert "Значки.ИконкаПоКоду" in d[0].message
    finally:
        i18n.set_lang(None)


@pytest.mark.needs_data
def test_on_server_form_method_flagged():
    """A @НаСервере method of the form module itself is the server hop with no chain."""
    d = _lint({
        "ФормаСписка.yaml": _form("=СерверныйЗначок(Данные)"),
        "ФормаСписка.xbsl": (
            "@НаСервере @ДоступноСКлиента\n"
            "метод СерверныйЗначок(Код: Строка): Строка\n"
            "    возврат Код\n"
            ";\n"
        ),
    })
    assert len(d) == 1


@pytest.mark.needs_data
def test_server_common_module_flagged():
    """A common module with the Server environment: any member of it is a server hop."""
    d = _lint({
        "СерверныеДанные.yaml": (
            "ВидЭлемента: ОбщийМодуль\n"
            "Ид: 019ef4c8-232f-7f33-9da6-c36047203003\n"
            "Имя: СерверныеДанные\n"
            "Окружение: Сервер\n"
        ),
        "ФормаСписка.yaml": _form("=СерверныеДанные.Картинка(Данные)"),
    })
    assert len(d) == 1


@pytest.mark.needs_data
def test_client_method_without_server_calls_silent():
    """A client method that stays on the client - a resource reference - is legal."""
    assert _lint({
        "ФормаСписка.yaml": _form("=КлиентскийЗначок()"),
        "ФормаСписка.xbsl": (
            "метод КлиентскийЗначок(): Строка\n"
            "    возврат \"ресурс\"\n"
            ";\n"
        ),
    }) == []


@pytest.mark.needs_data
def test_client_module_method_silent():
    """A member of a client common module resolves and stays on the client."""
    assert _lint({
        "Админка.yaml": (
            "ВидЭлемента: ОбщийМодуль\n"
            "Ид: 019ef4c8-232f-7f33-9da6-c36047203004\n"
            "Имя: Админка\n"
            "Окружение: Клиент\n"
        ),
        "Админка.xbsl": (
            "метод ЗначокУдаленной(Код: Строка): Строка\n"
            "    возврат \"ресурс\"\n"
            ";\n"
        ),
        "ФормаСписка.yaml": _form("=Оформление.ЗначокСкрытой(Данные)"),
    }) == []


@pytest.mark.needs_data
def test_bare_data_path_silent():
    """`=ДанныеСтроки.Данные.Поле` without a call is the cure, not a finding."""
    assert _lint({
        "Значки.yaml": CATALOG,
        "ФормаСписка.yaml": _form("=ДанныеСтроки.Данные.Логотип"),
    }) == []


@pytest.mark.needs_data
def test_constructor_is_not_a_call():
    """A constructor names a type: without the skip the qualified head of
    `новый Значки.Объект(...)` would read as a member call of the server catalog."""
    assert _lint({
        "Значки.yaml": CATALOG,
        "ФормаСписка.yaml": _form("=новый Значки.Объект(Код)"),
    }) == []


@pytest.mark.needs_data
def test_unresolved_name_silent():
    """A name the project does not declare (a built-in, a library) is not guessed."""
    assert _lint({
        "Значки.yaml": CATALOG,
        "ФормаСписка.yaml": _form("=НеведомаяФункция(Данные)"),
    }) == []


@pytest.mark.needs_data
def test_project_component_own_property_silent():
    """A project component's own property named like the platform's is not judged:
    the node gate takes only schema components that declare the Image property."""
    assert _lint({
        "Значки.yaml": CATALOG,
        "МойКомпонент.yaml": (
            "ВидЭлемента: КомпонентИнтерфейса\n"
            "Ид: 019ef4c8-232f-7f33-9da6-c36047203005\n"
            "Имя: МойКомпонент\n"
            "Свойства:\n"
            "    -\n"
            "        Имя: Изображение\n"
            "        Тип: Строка\n"
        ),
        "ФормаСписка.yaml": (
            FORM_HEAD
            + "    -\n"
            + "        Тип: МойКомпонент\n"
            + "        Имя: Свой\n"
            + '        Изображение: =Значки.ИконкаПоКоду("а")\n'
        ),
    }) == []


@pytest.mark.needs_data
def test_english_spellings_flagged():
    """An English project: ElementKind/Type/Image/@OnServer resolve through the same
    dictionaries as the Russian spellings."""
    d = _lint({
        "Badges.yaml": (
            "ElementKind: Catalog\n"
            "Id: 019ef4c8-232f-7f33-9da6-c36047203006\n"
            "Name: Badges\n"
        ),
        "ListForm.yaml": (
            "ElementKind: InterfaceComponent\n"
            "Id: 019ef4c8-232f-7f33-9da6-c36047203007\n"
            "Name: ListForm\n"
            "Content:\n"
            "    -\n"
            "        Type: Picture\n"
            "        Name: Logo\n"
            '        Image: =Badges.IconByCode("a")\n'
        ),
    })
    assert len(d) == 1
    assert "Badges.IconByCode" in d[0].message
