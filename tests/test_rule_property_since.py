"""Checks of the yaml/property-since-compat rule (a property newer than the compatibility mode)."""

from xbsl import engine, uischema

_RULE = "yaml/property-since-compat"

#: The property the fixtures lean on, and the version the SCHEMA says it appeared in. Read
#: from the data rather than written out: the tests are about the comparison, not about which
#: build introduced what, and a hard-coded number would also age with every data update.
_NEWER_PROP = "ИспользоватьМножественнуюСортировку"
_NEWER_SINCE = str(
    (((uischema.component("Таблица") or {}).get("component") or {}).get("props") or {})
    .get(_NEWER_PROP, {}).get("since") or ""
)

_PROJECT = (
    "Ид: 2c8f4a17-9b31-4d6e-8a05-3f1e7c2b9d55\n"
    "Поставщик: acme\nИмя: П\nВерсия: 1.0.0\n"
    "РежимСовместимости: {mode}\n"
)

_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 1f9b6d38-5c27-4e91-8a43-2d7e0b5c9a11
Имя: Ф
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Таблица<ДинамическийСписок>
        Имя: Список
        {prop}: Истина
"""


def _lint(mode: str, prop: str = _NEWER_PROP, form: str | None = None):
    sources = [
        engine.load_text("acme/П/Проект.yaml", _PROJECT.format(mode=mode)),
        engine.load_text("acme/П/Основное/Ф.yaml", form or _FORM.format(prop=prop)),
    ]
    return engine.run_sources(sources, select={_RULE})


def test_a_newer_property_is_reported_under_an_older_mode():
    # the compiler answers `Неизвестное свойство` for exactly this pair
    d = _lint("9.0")
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].line == 9
    # The message names both sides: the version the property appeared in and the mode declared.
    assert _NEWER_SINCE in d[0].message and "9.0" in d[0].message


def test_the_same_property_is_silent_under_its_own_mode():
    assert _lint(_NEWER_SINCE) == []


def test_older_property_is_silent():
    # РастягиватьПоГоризонтали is not newer than the mode - nothing to report
    assert _lint("9.0", prop="РастягиватьПоГоризонтали") == []


def test_english_spelling_is_judged_too():
    form = (
        "ElementKind: InterfaceComponent\n"
        "Id: 1f9b6d38-5c27-4e91-8a43-2d7e0b5c9a11\n"
        "Name: F\n"
        "Inherits:\n"
        "    Type: Table<DynamicList>\n"
        "    Content:\n"
        "        Type: Table<DynamicList>\n"
        "        Name: List\n"
        "        UseMultipleSort: True\n"
    )
    d = _lint("9.0", form=form)
    assert len(d) == 1 and "UseMultipleSort" in d[0].message


def test_without_a_project_description_the_rule_is_silent():
    # the mode is unknown - a finding would be a guess
    d = engine.run_sources(
        [engine.load_text("acme/П/Основное/Ф.yaml",
                          _FORM.format(prop="ИспользоватьМножественнуюСортировку"))],
        select={_RULE},
    )
    assert d == []
