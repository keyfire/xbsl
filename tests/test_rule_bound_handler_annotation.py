"""code/bound-handler-annotation: the handler annotation on a method the paired yaml binds.

The annotation marks an override of a handler the base type of the module declares; a method
the yaml binds to an event, a command or a route overrides nothing, and the compiler refuses
the annotation at its line ("A handler associated with method X is not found"). A server probe
gave that refusal for all three bindings and compiled the form's own after-create handler under
the same annotation. A method nobody binds is refused as well, but it cannot be told from an
override without a complete list of the overridable handlers, which the data does not carry -
so the rule leaves it alone.

The mapper parses the module and reads the event names from the interface schema, so the tests
that lint carry `needs_data`; the registration check runs in every checkout.
"""

import pytest

from xbsl import engine, i18n
from xbsl.diagnostics import Severity
from xbsl.fixer import fix_source

RULE = "code/bound-handler-annotation"

FORM_YAML = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 2b0d5a4e-6c1f-4f3a-9e8d-7a1b2c3d4e5f
Имя: КарточкаСклада
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    ОсновнаяКоманда:
        Тип: ОбычнаяКоманда
        Обработчик: Сохранить
    Содержимое:
        Тип: Группа
        Содержимое:
            -
                Тип: Кнопка
                Имя: КнопкаОбновить
                ПриНажатии: Обновить
"""

FORM_XBSL = """\
метод Сохранить(Команда: ОбычнаяКоманда)
;

метод Обновить(Источник: Кнопка, Событие: СобытиеПриНажатии)
;

@Обработчик
метод ПослеСоздания()
;
"""

SERVICE_YAML = """\
ВидЭлемента: HttpСервис
Ид: 5e0c3f7a-9b1d-4c2e-8f3a-2d4b6c8e0a11
Имя: СервисСкладов
ОбластьВидимости: ВПодсистеме
КорневойUrl: /stock-api
ШаблоныUrl:
    -
        Имя: Остатки
        Шаблон: /stock
        Методы:
            -
                Метод: GET
                Обработчик: Остатки
"""


def _lint(files):
    sources = [engine.load_text(name, text) for name, text in files.items()]
    return engine.run_sources(sources, select={RULE})


def _annotated(text, method):
    return text.replace(f"метод {method}(", f"@Обработчик\nметод {method}(", 1)


def test_rule_registered_as_a_project_error_on_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)
    assert info.tier == "D" and info.scope == "project" and info.enabled_by_default
    assert info.severity is Severity.ERROR and info.mapper is not None


@pytest.mark.needs_data
def test_the_clean_form_is_silent():
    """The after-create override keeps its annotation: that is where it belongs."""
    assert _lint({"Склады/КарточкаСклада.yaml": FORM_YAML,
                  "Склады/КарточкаСклада.xbsl": FORM_XBSL}) == []


@pytest.mark.needs_data
@pytest.mark.parametrize(("method", "key", "line"), [
    ("Сохранить", "Обработчик", 9),
    ("Обновить", "ПриНажатии", 16),
])
def test_a_bound_command_or_event_handler_is_reported(method, key, line):
    module = _annotated(FORM_XBSL, method)
    diags = _lint({"Склады/КарточкаСклада.yaml": FORM_YAML, "Склады/КарточкаСклада.xbsl": module})
    assert len(diags) == 1
    found = diags[0]
    annotation_line = module.splitlines().index("@Обработчик") + 1
    assert (found.path.replace("\\", "/"), found.line, found.col) == (
        "Склады/КарточкаСклада.xbsl", annotation_line, 1)
    assert found.severity is Severity.ERROR
    assert f"'{method}'" in found.message and f"'{key}'" in found.message
    assert f"(строка {line})" in found.message and "is not found" in found.message


@pytest.mark.needs_data
def test_a_route_handler_of_an_http_service_is_reported():
    module = "@Обработчик\nметод Остатки(Запрос: HttpСервисЗапрос)\n;\n"
    diags = _lint({"Склады/СервисСкладов.yaml": SERVICE_YAML,
                   "Склады/СервисСкладов.xbsl": module})
    assert [(d.line, d.col) for d in diags] == [(1, 1)]


@pytest.mark.needs_data
def test_an_unbound_method_is_not_judged():
    """The compiler refuses it too, but only a complete list of overrides could tell."""
    module = FORM_XBSL + "\n@Обработчик\nметод Пересчитать()\n;\n"
    assert _lint({"Склады/КарточкаСклада.yaml": FORM_YAML,
                  "Склады/КарточкаСклада.xbsl": module}) == []


@pytest.mark.needs_data
def test_a_bound_name_of_a_known_override_is_not_judged():
    yaml_text = FORM_YAML.replace("ПриНажатии: Обновить", "ПриНажатии: ПослеСоздания")
    assert _lint({"Склады/КарточкаСклада.yaml": yaml_text,
                  "Склады/КарточкаСклада.xbsl": FORM_XBSL}) == []


@pytest.mark.needs_data
def test_a_module_of_another_element_is_not_paired():
    """The object module of an element sits next to its yaml under another stem."""
    module = _annotated(FORM_XBSL, "Сохранить")
    assert _lint({"Склады/КарточкаСклада.yaml": FORM_YAML,
                  "Склады/КарточкаСклада.Объект.xbsl": module}) == []


@pytest.mark.needs_data
def test_the_fix_takes_out_the_annotation_line():
    module = _annotated(FORM_XBSL, "Сохранить")
    source = engine.load_text("Склады/КарточкаСклада.xbsl", module)
    diags = _lint({"Склады/КарточкаСклада.yaml": FORM_YAML, "Склады/КарточкаСклада.xbsl": module})
    assert fix_source(source, diags).text == FORM_XBSL


@pytest.mark.needs_data
def test_the_fix_keeps_the_other_annotations_of_the_line():
    module = FORM_XBSL.replace("метод Сохранить(", "@НаКлиенте @Обработчик\nметод Сохранить(")
    source = engine.load_text("Склады/КарточкаСклада.xbsl", module)
    diags = _lint({"Склады/КарточкаСклада.yaml": FORM_YAML, "Склады/КарточкаСклада.xbsl": module})
    assert [(d.line, d.col) for d in diags] == [(1, 12)]
    fixed = fix_source(source, diags).text
    assert fixed.startswith("@НаКлиенте\nметод Сохранить(")


@pytest.mark.needs_data
def test_the_english_spelling_is_reported_in_english():
    i18n.set_lang("en")
    yaml_text = """\
ElementKind: InterfaceComponent
Id: 2b0d5a4e-6c1f-4f3a-9e8d-7a1b2c3d4e5f
Name: StockCard
VisibilityScope: InSubsystem
Inherits:
    Type: Form
    Content:
        Type: Group
        Content:
            -
                Type: Button
                Name: RefreshButton
                OnClick: Refresh
"""
    module = "@Handler\nmethod Refresh(Source: Button, Event: ClickEvent)\n;\n"
    diags = _lint({"Stock/StockCard.yaml": yaml_text, "Stock/StockCard.xbsl": module})
    assert [(d.line, d.col) for d in diags] == [(1, 1)]
    assert "@Handler" in diags[0].message and "AfterCreate" in diags[0].message
