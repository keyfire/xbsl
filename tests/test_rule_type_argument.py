"""Checks of the yaml/unexpected-type-argument rule (a generic argument vs the ui schema).

The schema, its type parameters and their defaults are written into a temporary data root, so
the tests need no generated Element data and run in a public checkout as well.
"""

import json

import pytest

from xbsl import dataset, engine
from xbsl.cli import discover
from xbsl.rules import component_values

_RULE = "yaml/unexpected-type-argument"
_VER = "9.9.9+0"
_SCHEMA = {
    "meta": {"source": "docs", "element_version": _VER, "tool": "extract_uischema", "count": 1},
    "components": {
        "ФормаАкме": {
            "package": "Стд::Интерфейс::Формы",
            "props": {
                # declared bare: the platform takes ФрагментАкме<КомандаАкме> and nothing else
                "ДополнительныеКоманды": {"types": ["ФрагментАкме"], "slot": True,
                                          "nullable": True},
                # declared parametrized: an argument here is what the platform asks for
                "КомандыСтроки": {"types": ["ФрагментАкме<КомандаСПараметромАкме>"],
                                  "slot": True},
                # a collection slot: the items are subtypes, and this rule does not judge them
                "Содержимое": {"types": ["Массив<КолонкаАкме>"], "slot": True},
                # a generic whose default the docs do not state - nothing to compare with
                "Ряд": {"types": ["РядАкме"], "slot": True},
            },
        },
    },
    "enums": {},
    "type_params": {
        "ФрагментАкме": {"params": ["ТипКоманды"], "defaults": {"ТипКоманды": "КомандаАкме"}},
        "РядАкме": {"params": ["ТипЗначения"]},
    },
}


def _pin(root):
    dataset.set_data_root(root)
    component_values._unparametrized_props.cache_clear()


@pytest.fixture
def ui_root(tmp_path):
    """A data root holding the schema above; the rule reads it as if it were real."""
    root = tmp_path / "data"
    ver_dir = root / _VER
    ver_dir.mkdir(parents=True)
    (ver_dir / "uischema.json").write_text(
        json.dumps(_SCHEMA, ensure_ascii=False), encoding="utf-8"
    )
    (root / "index.json").write_text(
        json.dumps({"available": [_VER], "default": _VER}), encoding="utf-8"
    )
    _pin(root)
    yield root
    _pin(None)


@pytest.fixture
def no_data(tmp_path):
    """An empty data root: no ui schema - the public-checkout degradation."""
    root = tmp_path / "empty"
    root.mkdir()
    _pin(root)
    yield
    _pin(None)


def _run(tmp_path, body, name="Ф.yaml"):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    text = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n    Тип: ФормаАкме\n" + body
    (src / name).write_text(text, encoding="utf-8")
    return engine.run(discover([str(src)]), select={_RULE})


def _has(diags):
    return any(d.rule_id == _RULE for d in diags)


def test_argument_other_than_the_default_flagged(tmp_path, ui_root):
    d = _run(tmp_path, "    ДополнительныеКоманды:\n        Тип: ФрагментАкме<ОбычнаяКомандаАкме>\n")
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].severity.name == "ERROR"
    assert "ФрагментАкме<ОбычнаяКомандаАкме>" in d[0].message
    assert "ФрагментАкме<КомандаАкме>" in d[0].message  # the message names the default spelling
    assert (d[0].line, d[0].col) == (6, 14)  # points at the value, where the fix goes


def test_argument_equal_to_the_default_not_flagged(tmp_path, ui_root):
    """ФрагментАкме<КомандаАкме> IS ФрагментАкме - the docs give ТипКоманды that default."""
    d = _run(tmp_path, "    ДополнительныеКоманды:\n        Тип: ФрагментАкме<КомандаАкме>\n")
    assert not _has(d)


def test_spacing_inside_the_argument_is_not_a_difference(tmp_path, ui_root):
    d = _run(tmp_path, "    ДополнительныеКоманды:\n        Тип: ФрагментАкме< КомандаАкме >\n")
    assert not _has(d)


def test_bare_type_not_flagged(tmp_path, ui_root):
    d = _run(tmp_path, "    ДополнительныеКоманды:\n        Тип: ФрагментАкме\n")
    assert not _has(d)


def test_property_declared_parametrized_not_flagged(tmp_path, ui_root):
    """КомандыСтроки asks for an argument, and the project type inside it cannot be checked."""
    d = _run(tmp_path, "    КомандыСтроки:\n        Тип: ФрагментАкме<КомандаСПараметромАкме<Заказ>>\n")
    assert not _has(d)


def test_head_the_property_does_not_declare_is_skipped(tmp_path, ui_root):
    """A subtype in a collection slot is legal - judging it belongs to another rule."""
    d = _run(tmp_path, "    Содержимое:\n        -\n            Тип: СтандартнаяКолонкаАкме<Заказ>\n")
    assert not _has(d)


def test_generic_without_a_documented_default_is_skipped(tmp_path, ui_root):
    d = _run(tmp_path, "    Ряд:\n        Тип: РядАкме<Строка>\n")
    assert not _has(d)


def test_unknown_component_is_skipped(tmp_path, ui_root):
    text = "ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\nНаследует:\n    Тип: ФормаПроекта\n"
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "П.yaml").write_text(
        text + "    ДополнительныеКоманды:\n        Тип: ФрагментАкме<ОбычнаяКомандаАкме>\n",
        encoding="utf-8",
    )
    assert not _has(engine.run(discover([str(src)]), select={_RULE}))


def test_without_the_schema_the_rule_is_silent(tmp_path, no_data):
    d = _run(tmp_path, "    ДополнительныеКоманды:\n        Тип: ФрагментАкме<ОбычнаяКомандаАкме>\n")
    assert not _has(d)
