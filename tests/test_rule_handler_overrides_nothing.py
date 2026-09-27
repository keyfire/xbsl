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
}
_TABLE.update({"Component": _TABLE["Компонент"], "Form": _TABLE["Форма"],
               "ObjectForm": _TABLE["ФормаОбъекта"]})


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
def test_a_module_of_another_kind_is_not_judged(handlers):
    """The handlers of an object module are declared by the compiler, not by a description."""
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
