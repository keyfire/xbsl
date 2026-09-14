"""The pairs the form designer of the editor gets from `xbsl/formKeys`.

The designer reads a form yaml on its own, so every name it compares - a key, the type of a node,
the value of an enumerated property - has to reach it in both spellings: an English form is legal
code the platform reads the same way. A tiny data root is written into a temporary directory, so
the module needs no distribution and no generated data and runs in a public checkout as well.
"""

import json

import pytest

from xbsl import dataset, uischema

_VER = "9.9.9+0"

_UI_SCHEMA = {
    "components": {
        "Группа": {"props": {"Компоновка": {"types": ["Авто", "КомпоновкаГруппы"]}}},
        "Кнопка": {"props": {"Вид": {"types": ["Авто", "ВидКнопки"]}, "Шрифт": {"types": ["Авто", "Шрифт"]}}},
        "Флажок": {"props": {"Вид": {"types": ["Авто", "ВидФлажка"]}}},
        "ПолеВвода": {"props": {"Вид": {"types": ["Авто", "ВидПоляВвода"]}}},
    },
    "enums": {
        "КомпоновкаГруппы": {"values": ["Вертикальная", "Горизонтальная"]},
        "ВидКнопки": {"values": ["Основная", "Обычная"]},
        "ВидФлажка": {"values": ["Флажок", "Переключатель"]},
        "ВидПоляВвода": {"values": ["Обычный"]},
    },
}

_UI_TERMS = {
    "enum_values": {
        "КомпоновкаГруппы": {"Вертикальная": "Vertical", "Горизонтальная": "Horizontal"},
        "ВидКнопки": {"Основная": "Main", "Обычная": "Usual"},
        "ВидФлажка": {"Флажок": "Checkbox", "Переключатель": "Switch"},
        # One English word for a value of another enumeration standing at the same property.
        "ВидПоляВвода": {"Обычный": "Usual"},
    },
    "types": {"Group": "Группа", "Button": "Кнопка", "Checkbox": "Флажок", "Edit": "ПолеВвода"},
    "properties": {"Layout": "Компоновка", "Kind": "Вид", "Font": "Шрифт"},
}

_TERMS = {
    "types": {
        "ОбычнаяКоманда": "UsualCommand",
        "ГруппаКомандногоИнтерфейса": "CommandInterfaceGroup",
        "АбсолютныйШрифт": "AbsoluteFont",
    },
}

_TERMS_FULL = {
    "common": {},
    "members": {"AbsoluteFont": {"Размер": "Size", "Полужирный": "Bold"}},
}

_STDLIB = {
    "type_members": {"АбсолютныйШрифт": {"properties": ["Размер", "Полужирный"]}},
    "bases": {},
}

_METAMODEL = {
    "meta": {"element_version": _VER, "props": "typed"},
    "classes": {
        "UsualCommand": {"props": {"Обработчик": {"kind": "string"}}, "ext": []},
        "CommandInterfaceGroup": {"props": {"Элементы": {"kind": "list"}}, "ext": []},
        # A class the term dictionary does not name in Russian stays out of the table.
        "AcmeInternalDescriptor": {"props": {}, "ext": []},
    },
    "enums": {},
    "vid2class": {},
    "common": [],
}


def _write_root(root, files: dict) -> None:
    ver_dir = root / _VER
    ver_dir.mkdir(parents=True)
    for name, data in files.items():
        (ver_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(json.dumps({"available": [_VER], "default": _VER}), encoding="utf-8")


@pytest.fixture
def form_root(tmp_path):
    root = tmp_path / "data"
    _write_root(root, {
        "uischema.json": _UI_SCHEMA,
        "uiterms.json": _UI_TERMS,
        "terms.json": _TERMS,
        "terms_full.json": _TERMS_FULL,
        "stdlib.json": _STDLIB,
        "metamodel.json": _METAMODEL,
    })
    dataset.set_data_root(root)
    yield root
    dataset.set_data_root(None)


@pytest.fixture
def empty_root(tmp_path):
    root = tmp_path / "empty"
    _write_root(root, {})
    dataset.set_data_root(root)
    yield root
    dataset.set_data_root(None)


def test_value_pairs_are_inverted_per_property(form_root):
    values = uischema.value_aliases()
    assert values["Компоновка"] == {"Vertical": "Вертикальная", "Horizontal": "Горизонтальная"}
    # the kinds of two components meet under one property: a button and a checkbox
    assert values["Вид"]["Main"] == "Основная"
    assert values["Вид"]["Switch"] == "Переключатель"


def test_an_english_value_two_values_of_a_property_share_is_dropped(form_root):
    # `Kind: Usual` answers to a value of the button kinds and to one of the input field kinds
    assert "Usual" not in uischema.value_aliases()["Вид"]


def test_the_value_table_is_a_copy(form_root):
    uischema.value_aliases()["Компоновка"]["Diagonal"] = "Диагональная"
    assert "Diagonal" not in uischema.value_aliases()["Компоновка"]


def test_type_pairs_add_the_metamodel_classes_to_the_palette(form_root):
    types = uischema.type_aliases()
    assert types["Group"] == "Группа" and types["Checkbox"] == "Флажок"
    assert types["UsualCommand"] == "ОбычнаяКоманда"
    assert types["CommandInterfaceGroup"] == "ГруппаКомандногоИнтерфейса"
    assert "AcmeInternalDescriptor" not in types
    # the palette table itself keeps its meaning
    assert "UsualCommand" not in uischema.component_aliases()


def test_member_pairs_of_an_inline_value_object(form_root):
    assert uischema.literal_member_aliases() == {"Size": "Размер", "Bold": "Полужирный"}


def test_without_data_the_tables_are_empty(empty_root):
    assert uischema.value_aliases() == {}
    assert uischema.type_aliases() == {}
    assert uischema.literal_member_aliases() == {}


def _server_features():
    pytest.importorskip("pygls", reason="LSP-методы проверяются при установленном extra [lsp]")
    from xbsl import lsp

    server = lsp._make_server()
    fm = getattr(server.lsp, "fm", None) or getattr(server.lsp, "_features", None)
    return getattr(fm, "features", fm)


def test_lsp_form_keys_answer_values_types_and_member_keys(form_root):
    answer = _server_features()["xbsl/formKeys"](None)
    assert answer["values"]["Компоновка"]["Horizontal"] == "Горизонтальная"
    assert answer["types"]["UsualCommand"] == "ОбычнаяКоманда"
    assert answer["aliases"]["Layout"] == "Компоновка"
    assert answer["aliases"]["Size"] == "Размер"
    assert answer["aliases"]["Bold"] == "Полужирный"


def test_lsp_form_keys_without_data(empty_root):
    answer = _server_features()["xbsl/formKeys"](None)
    assert answer["values"] == {} and answer["types"] == {}
