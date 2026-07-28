"""Checks of the yaml/unknown-component-property rule (a markup key vs the ui schema).

The schema is written into a temporary data root, so the tests need no generated Element
data and run in a public checkout as well.
"""

import json

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover
from xbsl.rules import component_props

_RULE = "yaml/unknown-component-property"
_VER = "9.9.9+0"
_SCHEMA = {
    "meta": {"source": "docs", "element_version": _VER, "tool": "extract_uischema", "count": 3},
    "components": {
        "ПолеАкме": {
            "package": "Стд::Интерфейс::ОбщиеКомпоненты",
            "props": {
                "Видимость": {"types": ["Авто", "Булево"]},
                "ЗамещающийТекст": {"types": ["Авто", "Строка"]},
                "Значение": {"types": ["Объект"]},
            },
        },
        "ФлажокАкме": {
            "package": "Стд::Интерфейс::ОбщиеКомпоненты",
            "props": {
                "Видимость": {"types": ["Авто", "Булево"]},
                "Заголовок": {"types": ["Авто", "Строка"]},
            },
            # documented beyond the typed set: the guide topic and the prose sections
            "yaml_props": ["ВключатьВАвтоИнтерфейс", "ЕстьНаведение"],
        },
        "КарточкаАкме": {
            "package": "Стд::Интерфейс::ОбщиеКомпоненты",
            "props": {"Содержимое": {"types": ["Компонент"], "slot": True}},
            "yaml_props": ["ПослеСоздания"],
        },
    },
    "enums": {},
}


def _root(tmp_path, schema: dict, name: str = "data"):
    root = tmp_path / name
    ver_dir = root / _VER
    ver_dir.mkdir(parents=True)
    (ver_dir / "uischema.json").write_text(
        json.dumps(schema, ensure_ascii=False), encoding="utf-8"
    )
    (root / "index.json").write_text(
        json.dumps({"available": [_VER], "default": _VER}), encoding="utf-8"
    )
    dataset.set_data_root(root)
    return root


@pytest.fixture
def ui_root(tmp_path):
    """A data root holding the schema above; the rule reads it as if it were real."""
    yield _root(tmp_path, _SCHEMA)
    dataset.set_data_root(None)
    component_props._tables.cache_clear()


@pytest.fixture
def no_data(tmp_path):
    """An empty data root: no ui schema - the public-checkout degradation."""
    root = tmp_path / "empty"
    root.mkdir()
    dataset.set_data_root(root)
    yield
    dataset.set_data_root(None)
    component_props._tables.cache_clear()


def _run(tmp_path, text: str, name: str = "Форма.yaml"):
    component_props._tables.cache_clear()
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    diags = engine.run(discover([str(path)]), select={_RULE})
    return [d for d in diags if d.rule_id == _RULE]


_MARKUP = """ВидЭлемента: КомпонентИнтерфейса
Ид: 11111111-2222-4333-8444-555555555555
Имя: Форма
Наследует:
    Тип: КарточкаАкме
    ПослеСоздания: Инициализация
    Содержимое:
        -
            Тип: ФлажокАкме
            Имя: Признак
            Заголовок: Признак
            ВключатьВАвтоИнтерфейс: Ложь
            {extra}
        -
            Тип: ПолеАкме
            Имя: Поле
            ЗамещающийТекст: Введите значение
"""


def test_property_of_another_component_is_reported(ui_root, tmp_path):
    diags = _run(tmp_path, _MARKUP.format(extra="ЗамещающийТекст: Подсказка"))
    assert len(diags) == 1
    assert diags[0].line == 13
    assert "ЗамещающийТекст" in diags[0].message and "ПолеАкме" in diags[0].message
    assert diags[0].severity.value == "error"


def test_own_properties_and_documented_keys_are_silent(ui_root, tmp_path):
    # the same file without the foreign key: the typed props, the guide-only keys of
    # yaml_props and the structural Type/Name all pass
    assert _run(tmp_path, _MARKUP.format(extra="Видимость: Истина")) == []


def test_key_no_component_declares_is_silent(ui_root, tmp_path):
    # the documentation does not list the yaml keys in full - an unknown name is not judged
    assert _run(tmp_path, _MARKUP.format(extra="ОтслеживатьИзменениеДанных: Истина")) == []


def test_generic_head_is_taken(ui_root, tmp_path):
    text = _MARKUP.format(extra="Видимость: Истина").replace(
        "Тип: ПолеАкме", "Тип: ПолеАкме<Строка>"
    ).replace("ЗамещающийТекст: Введите значение", "Заголовок: Чужое")
    diags = _run(tmp_path, text)
    assert len(diags) == 1 and "Заголовок" in diags[0].message


def test_project_component_is_not_judged(ui_root, tmp_path):
    text = _MARKUP.format(extra="Видимость: Истина").replace(
        "Тип: ФлажокАкме", "Тип: МойКомпонент"
    )
    assert _run(tmp_path, text) == []


def test_declarations_outside_the_markup_are_not_judged(ui_root, tmp_path):
    # an item of Properties declares a property whose TYPE is a component; its keys
    # (DefaultValue and the like) are not component properties at all
    text = """ВидЭлемента: КомпонентИнтерфейса
Ид: 11111111-2222-4333-8444-555555555555
Имя: Форма
Свойства:
    -
        Имя: Признак
        Тип: ПолеАкме
        Заголовок: Не свойство компонента
Наследует:
    Тип: КарточкаАкме
"""
    assert _run(tmp_path, text) == []


def test_latin_key_without_a_pair_is_skipped(ui_root, tmp_path):
    # no English spellings in the data - judging an ASCII key would report legal sources
    text = _MARKUP.format(extra="PlaceholderText: Подсказка")
    assert _run(tmp_path, text) == []


def test_schema_without_yaml_props_switches_the_rule_off(tmp_path):
    # data generated before yaml_props existed knows the constructor parameters alone
    stripped = json.loads(json.dumps(_SCHEMA))
    for record in stripped["components"].values():
        record.pop("yaml_props", None)
    _root(tmp_path, stripped, name="old")
    try:
        assert _run(tmp_path, _MARKUP.format(extra="ЗамещающийТекст: Подсказка")) == []
    finally:
        dataset.set_data_root(None)
        component_props._tables.cache_clear()


def test_no_schema_no_findings(no_data, tmp_path):
    assert _run(tmp_path, _MARKUP.format(extra="ЗамещающийТекст: Подсказка")) == []


def test_file_without_markup_is_skipped(ui_root, tmp_path):
    text = """ВидЭлемента: Справочник
Ид: 11111111-2222-4333-8444-555555555555
Имя: Товары
Реквизиты:
    -
        Имя: Наименование
        Тип: Строка
"""
    assert _run(tmp_path, text, name="Товары.yaml") == []
