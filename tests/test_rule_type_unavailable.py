"""A standard type used as a value in the wrong execution environment."""

import pytest

from xbsl import engine, terms
from xbsl.rules import environment


pytestmark = pytest.mark.needs_data
RULE = "code/type-unavailable"


@pytest.fixture(autouse=True)
def _type_catalog(monkeypatch):
    # The catalog is synthetic so this regression stays independent of private data releases.
    monkeypatch.setattr(environment, "_type_availability", lambda: {
        "Кодировки": "Сервер", "ВидПлатформыКлиента": "Клиент",
    }, raising=False)


def _lint(yaml_text, xbsl_text, name="Панель"):
    return engine.run_sources([
        engine.load_text(name + ".yaml", yaml_text),
        engine.load_text(name + ".xbsl", xbsl_text),
    ], select={RULE})


FORM = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Панель\n"
SERVER = "ВидЭлемента: ОбщийМодуль\nИмя: Панель\nОкружение: Сервер\n"
BOTH = "ВидЭлемента: ОбщийМодуль\nИмя: Панель\nОкружение: КлиентИСервер\n"


def test_server_only_type_property_rejected_in_client_form():
    found = _lint(FORM, "метод Показать()\n    знч Данные = Кодировки.Base64\n;\n")
    assert len(found) == 1
    assert found[0].rule_id == RULE and found[0].severity.value == "error"
    assert (found[0].line, found[0].col) == (2, 18)
    assert "Кодировки" in found[0].message


def test_english_type_name_is_read_from_the_type_terms(monkeypatch):
    monkeypatch.setattr(terms, "common_russian", lambda _name: None)
    found = _lint("ElementKind: InterfaceComponent\nName: Panel\n",
                  "method Show()\n    Encodings.Base64.Decode(\"x\")\n;\n", "Panel")
    assert len(found) == 1
    assert found[0].line == 2 and "Encodings" in found[0].message


def test_server_annotation_moves_the_form_method_to_server():
    found = _lint(FORM, "@НаСервере\nметод Показать()\n    Кодировки.Base64\n;\n")
    assert found == []


def test_client_annotation_overrides_a_server_module():
    found = _lint(SERVER, "@НаКлиенте\nметод Показать()\n    Кодировки.Base64\n;\n")
    assert len(found) == 1 and found[0].line == 3


def test_client_only_type_rejected_in_server_module():
    found = _lint(SERVER, "метод Показать()\n    ВидПлатформыКлиента.iOS\n;\n")
    assert len(found) == 1 and "ВидПлатформыКлиента" in found[0].message


def test_both_environment_module_checks_both_compilation_sides():
    found = _lint(BOTH, "метод Показать()\n    Кодировки.Base64\n;\n")
    assert len(found) == 1


def test_both_annotations_leave_call_environment_unknown():
    found = _lint(BOTH, "@НаСервере @НаКлиенте\nметод Показать()\n    Кодировки.Base64\n;\n")
    assert found == []


def test_type_annotation_is_not_a_value_access():
    found = _lint(FORM, "метод Показать(Ссылка: ДвоичныйОбъект.Ссылка): ДвоичныйОбъект.Ссылка\n"
                  "    возврат Ссылка\n;\n")
    assert found == []


def test_local_method_and_form_field_shadow_standard_type():
    source = ("метод Кодировки(): Строка\n    возврат \"ok\"\n;\n"
              "метод Показать()\n    знч Данные = Кодировки.Base64\n;\n")
    assert _lint(FORM, source) == []
    source = "метод Показать()\n    знч Данные = Кодировки.Base64\n;\n"
    yaml = FORM + "Реквизиты:\n  - Имя: Кодировки\n    Тип: Строка\n"
    assert _lint(yaml, source) == []


def test_local_variable_shadows_standard_type():
    source = ("метод Показать()\n    знч Кодировки = ПолучитьКодировки()\n"
              "    знч Данные = Кодировки.Base64\n;\n")
    assert _lint(FORM, source) == []


def test_untyped_parameter_shadows_standard_type_in_its_method():
    source = "метод Показать(Кодировки)\n    знч Данные = Кодировки.Base64\n;\n"
    assert _lint(FORM, source) == []


def test_shadow_in_one_method_does_not_hide_standard_type_in_another():
    source = ("метод СЛокальнойПеременной()\n"
              "    знч Кодировки = ПолучитьКодировки()\n"
              "    возврат Кодировки.Base64\n;\n"
              "метод Показать()\n    возврат Кодировки.Base64\n;\n")
    found = _lint(FORM, source)
    assert len(found) == 1 and found[0].line == 6


def test_old_catalog_without_type_availability_stays_silent(monkeypatch):
    monkeypatch.setattr(environment, "_type_availability", lambda: {})
    assert _lint(FORM, "метод Показать()\n    Кодировки.Base64\n;\n") == []


def test_unresolved_module_environment_stays_silent():
    yaml = "ВидЭлемента: ОбщийМодуль\nИмя: Панель\n"
    source = "@НаКлиенте\nметод Показать()\n    Кодировки.Base64\n;\n"
    assert _lint(yaml, source) == []


def test_project_type_name_shadows_standard_type():
    sources = [
        engine.load_text("Панель.yaml", FORM),
        engine.load_text("Панель.xbsl", "метод Показать()\n    Кодировки.Base64\n;\n"),
        engine.load_text("Кодировки.yaml", "ВидЭлемента: ОбщийМодуль\nИмя: Кодировки\n"
                         "Окружение: Клиент\n"),
    ]
    assert engine.run_sources(sources, select={RULE}) == []


def test_new_server_only_type_rejected_in_client_form(monkeypatch):
    monkeypatch.setattr(environment, "_type_availability", lambda: {
        "СерверныйБуфер": "Сервер",
    })
    found = _lint(FORM, "метод Показать()\n    знч Буфер = новый СерверныйБуфер()\n;\n")
    assert len(found) == 1 and found[0].line == 2
