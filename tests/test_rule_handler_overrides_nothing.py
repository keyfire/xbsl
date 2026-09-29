"""code/handler-overrides-nothing: the handler annotation on a method that overrides nothing.

The annotation marks an override of a handler the base type of the module declares; a method
the yaml does not bind and the base declares no handler of that name is refused by the
compiler at the line of the annotation ("A handler associated with method X is not found"). A
server probe gave that refusal for such a method in a form module; the form's own after-create
handler under the same annotation compiled.

The handlers of a component module come from the data (the `module_handlers` section of
stdlib.json, see xbsl/modulehandlers.py). The tests put a table of the same shape in place of
it - the rows the distribution ships for these components - so they do not wait for a data
release; the lexer and the parser still need the language data, hence `needs_data`.

A row may name the compatibility modes its handler is there in: the web chat handler of a
client application is gone from mode 8.0 on (`to: 8.0`, the compiler declares it while the
mode is below 8.0). Such a handler is judged in the mode of the project description.
"""

from functools import lru_cache

import pytest

from xbsl import engine, i18n, modulehandlers
from xbsl.diagnostics import Severity
from xbsl.fixer import fix_source

RULE = "code/handler-overrides-nothing"

#: The rows the distribution ships for the components the tests build on, under both
#: spellings of the type, the way the loader keys the section.
_TABLE = {
    "Компонент": ({"ru": "ПослеСоздания", "en": "AfterCreate"},),
    "Форма": ({"ru": "ПриОбновлении", "en": "OnRefresh"},
              {"ru": "ПослеЗакрытия", "en": "AfterClose"},
              {"ru": "ПередЗакрытием", "en": "BeforeClose"}),
    "ФормаОбъекта": ({"ru": "ПослеЧтения", "en": "AfterRead"},
                     {"ru": "ПередЗаписью", "en": "BeforeWrite"},
                     {"ru": "ПослеЗаписи", "en": "AfterWrite"},
                     {"ru": "ПередУдалением", "en": "BeforeDelete"},
                     {"ru": "ПослеУдаления", "en": "AfterDelete"}),
    "КлиентскоеПриложение": ({"ru": "ПриОткрытииПоСсылке", "en": "OnOpenByLink"},
                             {"ru": "ПолучитьДанныеПользователяВебЧата",
                              "en": "GetWebChatUserData", "to": "8.0"}),
}
_TABLE.update({"Component": _TABLE["Компонент"], "Form": _TABLE["Форма"],
               "ObjectForm": _TABLE["ФормаОбъекта"],
               "ClientApplication": _TABLE["КлиентскоеПриложение"]})


@pytest.fixture
def handlers(monkeypatch):
    """The lists in place of the data section; the catalog still answers the bases."""
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: _TABLE))
    modulehandlers._reset()
    yield
    monkeypatch.undo()
    modulehandlers._reset()


FORM_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 2b0d5a4e-6c1f-4f3a-9e8d-7a1b2c3d4e5f
Имя: ПанельСкладов
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    Содержимое:
        Тип: Группа
        Содержимое:
            -
                Тип: Кнопка
                Имя: КнопкаОбновить
                ПриНажатии: Обновить
"""

FORM_XBSL = """\
@Обработчик
метод ПослеСоздания()
    Компоненты.КнопкаОбновить.Заголовок = "Обновить"
;

@Обработчик
метод ПередЗакрытием(Событие: ПараметрыЗакрытияФормы)
;

метод Обновить(Источник: Кнопка, Событие: СобытиеПриНажатии)
;
"""

CARD_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 3c1e6b5f-7d2a-4a4b-8f9e-8b2c3d4e5f60
Имя: КарточкаСклада
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: ФормаОбъекта<Склады.Объект>
"""


def _lint(files):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={RULE})


def _form(module):
    return _lint({"Склады/ПанельСкладов.yaml": FORM_YAML, "Склады/ПанельСкладов.xbsl": module})


def test_rule_registered_as_a_project_error_on_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default
    assert info.severity is Severity.ERROR and info.mapper is not None


@pytest.mark.needs_data
def test_the_overrides_the_base_declares_are_silent(handlers):
    assert _form(FORM_XBSL) == []


@pytest.mark.needs_data
def test_a_method_nobody_binds_is_reported_at_the_annotation(handlers):
    module = FORM_XBSL + "\n@Обработчик\nметод Пересчитать()\n;\n"
    diags = _form(module)
    assert len(diags) == 1
    found = diags[0]
    annotation_line = module.splitlines().index("метод Пересчитать()")
    assert (found.path.replace("\\", "/"), found.line, found.col) == (
        "Склады/ПанельСкладов.xbsl", annotation_line, 1)
    assert found.severity is Severity.ERROR
    assert "'Пересчитать'" in found.message and "is not found" in found.message
    # The reader learns what the base does let a module override.
    assert "ПриОбновлении, ПослеЗакрытия, ПередЗакрытием, ПослеСоздания" in found.message


@pytest.mark.needs_data
def test_the_fix_takes_the_annotation_away(handlers):
    module = FORM_XBSL + "\n@Обработчик\nметод Пересчитать()\n;\n"
    source = engine.load_text("Склады/ПанельСкладов.xbsl", module)
    fixed = fix_source(source, _form(module)).text
    assert fixed == FORM_XBSL + "\nметод Пересчитать()\n;\n"


@pytest.mark.needs_data
def test_a_handler_of_another_component_is_reported(handlers):
    """A form is no object form: the write handler is not one it declares."""
    diags = _form(FORM_XBSL + "\n@Обработчик\nметод ПередЗаписью()\n;\n")
    assert [d.rule_id for d in diags] == [RULE]


@pytest.mark.needs_data
def test_an_object_form_overrides_its_own_handlers_and_those_of_its_bases(handlers):
    module = "@Обработчик\nметод ПередЗаписью()\n;\n\n@Обработчик\nметод ПослеСоздания()\n;\n"
    assert _lint({"Склады/КарточкаСклада.yaml": CARD_YAML,
                  "Склады/КарточкаСклада.xbsl": module}) == []


@pytest.mark.needs_data
def test_a_near_miss_of_a_handler_is_called_a_misspelling_and_left_unfixed(handlers):
    """Taking the annotation off would turn a broken override into a method nobody calls."""
    diags = _form(FORM_XBSL.replace("метод ПослеСоздания()", "метод ПослеСозданя()"))
    assert len(diags) == 1
    assert "ПослеСоздания" in diags[0].message and "опечатку" in diags[0].message
    assert diags[0].fix is None


@pytest.mark.needs_data
def test_a_bound_method_is_left_to_the_other_rule(handlers):
    module = FORM_XBSL.replace("метод Обновить(", "@Обработчик\nметод Обновить(")
    assert _form(module) == []


@pytest.mark.needs_data
def test_a_chain_of_project_components_is_walked_to_the_platform_type(handlers):
    derived = CARD_YAML.replace("Имя: КарточкаСклада", "Имя: КарточкаНовогоСклада").replace(
        "Тип: ФормаОбъекта<Склады.Объект>", "Тип: КарточкаСклада")
    module = "@Обработчик\nметод ПередЗаписью()\n;\n\n@Обработчик\nметод Пересчитать()\n;\n"
    diags = _lint({"Склады/КарточкаСклада.yaml": CARD_YAML,
                   "Склады/КарточкаНовогоСклада.yaml": derived,
                   "Склады/КарточкаНовогоСклада.xbsl": module})
    assert [(d.line, d.rule_id) for d in diags] == [(5, RULE)]
    assert "ФормаОбъекта" in diags[0].message


@pytest.mark.needs_data
def test_a_base_outside_the_project_and_the_catalog_is_not_judged(handlers):
    yaml_text = CARD_YAML.replace("ФормаОбъекта<Склады.Объект>", "ФормаИзБиблиотеки")
    assert _lint({"Склады/КарточкаСклада.yaml": yaml_text,
                  "Склады/КарточкаСклада.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}) == []


@pytest.mark.needs_data
def test_a_module_of_another_kind_is_not_judged(handlers, monkeypatch):
    """Not by the component lists: the modules of a catalog are judged by the lists of the
    compiler and the access settings of the catalog (see
    test_rule_handler_overrides_nothing_elements), and without those lists by nothing."""
    monkeypatch.setattr(modulehandlers, "_elements", lru_cache(maxsize=1)(lambda: {}))
    modulehandlers._reset()
    catalog = "ВидЭлемента: Справочник\nИд: 4d2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a71\nИмя: Склады\n"
    assert _lint({"Склады/Склады.yaml": catalog,
                  "Склады/Склады.Объект.xbsl": "@Обработчик\nметод ПередЗаписью()\n;\n",
                  "Склады/Склады.xbsl": "@Обработчик\nметод Пересчитать()\n;\n"}) == []


@pytest.mark.needs_data
def test_without_the_lists_nothing_is_judged(monkeypatch):
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: {}))
    modulehandlers._reset()
    try:
        assert _form(FORM_XBSL + "\n@Обработчик\nметод Пересчитать()\n;\n") == []
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


@pytest.mark.needs_data
def test_the_english_spelling_is_read_and_reported_in_english(handlers):
    i18n.set_lang("en")
    yaml_text = """\
ElementKind: InterfaceComponent
Id: 2b0d5a4e-6c1f-4f3a-9e8d-7a1b2c3d4e5f
Name: StockPanel
VisibilityScope: InSubsystem
Inherits:
    Type: Form
"""
    module = "@Handler\nmethod AfterCreate()\n;\n\n@Handler\nmethod Recalculate()\n;\n"
    diags = _lint({"Stock/StockPanel.yaml": yaml_text, "Stock/StockPanel.xbsl": module})
    assert [(d.line, d.col) for d in diags] == [(5, 1)]
    assert "@Handler" in diags[0].message
    assert "OnRefresh, AfterClose, BeforeClose, AfterCreate" in diags[0].message


# --- the compatibility mode of the project -------------------------------------------------

APP_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 5e2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a72
Имя: ПриложениеСклада
ОбластьВидимости: ВПроекте
Наследует:
    Тип: ПроизвольноеКлиентскоеПриложение
"""

PROJECT_YAML = """\
Ид: 1d1f5c60-0000-4000-8000-000000000f1e
Поставщик: acme
Имя: Склад
Версия: 1.0.0
"""

WEB_CHAT = "@Обработчик\nметод ПолучитьДанныеПользователяВебЧата()\n;\n"


def _app(module, mode="9.0", described=True):
    """The client application of a project that declares `mode` ("" - none at all); without
    a description when `described` is off."""
    files = {"Склады/ПриложениеСклада.yaml": APP_YAML, "Склады/ПриложениеСклада.xbsl": module}
    if described:
        files["Проект.yaml"] = PROJECT_YAML + (f"РежимСовместимости: {mode}\n" if mode else "")
    return _lint(files)


def _with_rows(monkeypatch, rows):
    """The table with the own rows of a client application replaced."""
    table = {**_TABLE, "КлиентскоеПриложение": rows, "ClientApplication": rows}
    monkeypatch.setattr(modulehandlers, "_table", lru_cache(maxsize=1)(lambda: table))
    modulehandlers._reset()


@pytest.mark.needs_data
def test_a_handler_gone_from_a_mode_is_silent_below_that_mode(handlers):
    """The compiler declares the web chat handler while the mode is below 8.0."""
    assert _app(WEB_CHAT, mode="7.0") == []


@pytest.mark.needs_data
@pytest.mark.parametrize("mode", ["8.0", "9.0"])
def test_a_handler_gone_from_a_mode_is_reported_from_that_mode_on(handlers, mode):
    diags = _app(WEB_CHAT, mode=mode)
    assert [(d.line, d.col, d.rule_id) for d in diags] == [(1, 1, RULE)]
    message = diags[0].message
    assert "переопределяет ПолучитьДанныеПользователяВебЧата только в режимах ниже 8.0" in message
    assert f"режим совместимости проекта – {mode}." in message
    assert "is not found" in message
    # The platform does not call such a method in this mode: taking the annotation off would
    # leave a method nobody calls.
    assert diags[0].fix is None


@pytest.mark.needs_data
def test_the_other_handlers_of_the_base_stay_in_that_mode(handlers):
    module = ("@Обработчик\nметод ПриОткрытииПоСсылке()\n;\n\n"
              "@Обработчик\nметод ПослеСоздания()\n;\n")
    assert _app(module, mode="9.0") == []


@pytest.mark.needs_data
def test_the_handlers_a_message_lists_follow_the_mode(handlers):
    module = "@Обработчик\nметод Пересчитать()\n;\n"
    newer = _app(module, mode="9.0")
    assert "переопределяет только ПриОткрытииПоСсылке, ПослеСоздания, а " in newer[0].message
    older = _app(module, mode="7.0")
    assert ("переопределяет только ПриОткрытииПоСсылке, ПолучитьДанныеПользователяВебЧата, "
            "ПослеСоздания, а ") in older[0].message


@pytest.mark.needs_data
@pytest.mark.parametrize("declared", ["", "8.5", "5.0", "новейший"],
                         ids=["no-mode", "unsupported-mode", "below-the-oldest", "not-a-mode"])
def test_a_project_without_a_supported_mode_is_read_in_the_newest_one(handlers, declared):
    """The build refuses such a description, and the reader of the platform goes on in the
    newest mode - where the handler of the older modes is gone. A mode below the oldest
    supported one is no exception: the reader does not fall back to the oldest mode."""
    diags = _app(WEB_CHAT, mode=declared)
    assert [d.rule_id for d in diags] == [RULE]
    assert "(новейший: проект не указывает режим, который поддерживает платформа)" in (
        diags[0].message)


@pytest.mark.needs_data
def test_without_a_project_description_every_handler_of_the_base_counts(handlers):
    """No description in the run - no mode to judge by, and the rule keeps quiet."""
    assert _app(WEB_CHAT, described=False) == []


@pytest.mark.needs_data
def test_control_the_bound_of_the_row_is_what_reports_the_override(monkeypatch):
    """The same row with its mode bound taken away is a handler of every mode."""
    _with_rows(monkeypatch, tuple({key: value for key, value in row.items() if key != "to"}
                                  for row in _TABLE["КлиентскоеПриложение"]))
    try:
        assert _app(WEB_CHAT, mode="9.0") == []
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


@pytest.mark.needs_data
def test_each_project_of_a_run_is_judged_in_its_own_mode(handlers):
    files = {}
    for folder, mode in (("Архив", "7.0"), ("Учет", "9.0")):
        files[f"{folder}/Проект.yaml"] = PROJECT_YAML + f"РежимСовместимости: {mode}\n"
        files[f"{folder}/Склады/ПриложениеСклада.yaml"] = APP_YAML
        files[f"{folder}/Склады/ПриложениеСклада.xbsl"] = WEB_CHAT
    diags = _lint(files)
    assert [d.path.replace("\\", "/") for d in diags] == ["Учет/Склады/ПриложениеСклада.xbsl"]


_CHECK_HANDLER = {"ru": "ПриПроверкеСклада", "en": "OnStockCheck"}


@pytest.mark.needs_data
@pytest.mark.parametrize("bounds, mode, words", [
    ({"from": "9.0"}, "8.0", "только начиная с режима 9.0"),
    ({"from": "7.0", "to": "9.0"}, "9.0", "только в режимах от 7.0 и ниже 9.0"),
    ({"from": "7.0", "to": "9.0"}, "6.0", "только в режимах от 7.0 и ниже 9.0"),
], ids=["below-from", "range-above", "range-below"])
def test_the_message_words_the_modes_the_description_states(monkeypatch, bounds, mode, words):
    _with_rows(monkeypatch, ({**_CHECK_HANDLER, **bounds},))
    try:
        diags = _app("@Обработчик\nметод ПриПроверкеСклада()\n;\n", mode=mode)
        assert len(diags) == 1 and words in diags[0].message
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


@pytest.mark.needs_data
@pytest.mark.parametrize("bounds, mode", [
    ({"from": "9.0"}, "9.0"),  # the first mode of the range is in it
    ({"from": "7.0", "to": "9.0"}, "8.0"),
], ids=["at-from", "inside-range"])
def test_a_mode_inside_the_range_declares_the_handler(monkeypatch, bounds, mode):
    _with_rows(monkeypatch, ({**_CHECK_HANDLER, **bounds},))
    try:
        assert _app("@Обработчик\nметод ПриПроверкеСклада()\n;\n", mode=mode) == []
    finally:
        monkeypatch.undo()
        modulehandlers._reset()


APP_YAML_EN = """\
ElementKind: InterfaceComponent
Id: 5e2f7c60-8e3b-4b5c-9a0f-9c3d4e5f6a72
Name: StockApplication
VisibilityScope: InProject
Inherits:
    Type: CustomClientApplication
"""

PROJECT_YAML_EN = """\
Id: 1d1f5c60-0000-4000-8000-000000000f1e
Vendor: acme
Name: Stock
Version: 1.0.0
CompatibilityMode: {mode}
"""


@pytest.mark.needs_data
def test_the_english_project_is_judged_in_its_mode_too(handlers):
    i18n.set_lang("en")
    module = "@Handler\nmethod GetWebChatUserData()\n;\n"

    def lint(mode):
        return _lint({"Project.yaml": PROJECT_YAML_EN.format(mode=mode),
                      "Stock/StockApplication.yaml": APP_YAML_EN,
                      "Stock/StockApplication.xbsl": module})

    assert lint("7.0") == []
    diags = lint("9.0")
    assert [(d.line, d.col) for d in diags] == [(1, 1)]
    assert "overrides GetWebChatUserData only in modes below 8.0" in diags[0].message
    assert "the project compatibility mode is 9.0." in diags[0].message
