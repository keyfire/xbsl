"""Bindings that require a writable property path, as shown in the UI schema."""

from copy import deepcopy

import pytest

from xbsl import dataset, engine, uischema
from xbsl.rules.binding_types import _two_way_props


pytestmark = pytest.mark.needs_data
RULE = "yaml/binding-needs-two-way"


@pytest.fixture(autouse=True)
def schema_with_binding(monkeypatch):
    schema = deepcopy(dataset.load_ui_schema())
    schema["components"]["Кнопка"]["props"]["Активность"]["binding"] = "two-way"
    checkbox = uischema.canonical_component("Checkbox")
    schema["components"][checkbox]["props"]["Значение"]["binding"] = "two-way"
    monkeypatch.setattr(dataset, "load_ui_schema", lambda version=None: schema)
    _two_way_props.cache_clear()
    yield schema
    _two_way_props.cache_clear()


def _lint(value, component="Кнопка", prop="Активность", extra=""):
    text = f"""ВидЭлемента: КомпонентИнтерфейса
Имя: Проверка
Наследует:
    Тип: {component}
    {prop}: {value}
{extra}"""
    return engine.run_sources([engine.load_text("Проверка.yaml", text)], select={RULE})


def test_active_button_property_announces_two_way_binding():
    result = uischema.component_property("Кнопка", "Активность")
    assert result["property"]["binding"] == "two-way"
    assert "two-way" in uischema.component_brief("Кнопка")["component"]["props"]["Активность"]


@pytest.mark.parametrize("component, prop", [("Кнопка", "Активность"), ("Button", "Active")])
@pytest.mark.parametrize("value", ["=Проверить()", "=Истина"])
def test_computed_active_binding_is_reported(component, prop, value):
    findings = _lint(value, component, prop)
    assert len(findings) == 1
    assert findings[0].rule_id == RULE and findings[0].line == 5


@pytest.mark.parametrize("value", [
    "=Состояние", "=Запись.Состояние", "=(Запись.Состояние)", "=Записи[0].Состояние", "Истина",
])
def test_writable_path_or_literal_is_not_reported(value):
    assert _lint(value) == []


def test_same_expression_in_other_property_is_allowed():
    assert _lint("=Проверить()", prop="Видимость") == []


def test_old_schema_without_binding_metadata_is_supported(schema_with_binding):
    schema_with_binding["components"]["Кнопка"]["props"]["Активность"].pop("binding")
    assert _lint("=Проверить()") == []


@pytest.mark.parametrize("readonly", ["Истина", "true", "=ПрочитатьРежим()"])
def test_read_only_setting_can_make_a_computed_value_legal(readonly):
    assert _lint("=Проверить()", "Checkbox", "Value", f"    ReadOnly: {readonly}\n") == []


def test_explicit_editable_value_still_requires_a_binding():
    assert len(_lint("=Проверить()", "Checkbox", "Value", "    ReadOnly: false\n")) == 1


def test_a_buttons_command_can_supply_its_active_value():
    assert _lint("=Проверить()", extra="    Команда: =Действия.Переключить\n") == []


@pytest.mark.parametrize("expression", ["=GetItem().Flag", "=Item?.Flag", "=GetItems()[0]"])
def test_computed_receiver_is_not_a_writable_binding(expression):
    findings = _lint(expression, "Button", "Active")
    assert len(findings) == 1 and findings[0].rule_id == RULE
