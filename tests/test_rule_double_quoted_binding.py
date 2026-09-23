"""Only double-quoted bindings of schema-proven nonstring UI properties are rejected."""

import json

import pytest
import yaml

from xbsl import dataset, engine
from xbsl.rules import binding_types

RULE = "yaml/double-quoted-binding"
VERSION = "9.9.9+0"
SCHEMA = {
    "meta": {"source": "docs", "element_version": VERSION, "tool": "extract_uischema"},
    "components": {
        "Группа": {
            "props": {
                "Ширина": {"types": ["Авто", "Число"]},
                "Видимость": {"types": ["Авто", "Булево"]},
                "ОтступПоГоризонтали": {"types": ["Авто", "РазмерОтступа"]},
                "Заголовок": {"types": ["Строка"]},
                "Значение": {"types": ["Объект"]},
                "Содержимое": {"types": ["Массив<Компонент>"], "slot": True},
            },
        },
    },
}


@pytest.fixture
def ui_root(tmp_path):
    root = tmp_path / "data"
    version = root / VERSION
    version.mkdir(parents=True)
    (version / "uischema.json").write_text(json.dumps(SCHEMA, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": [VERSION], "default": VERSION}), encoding="utf-8",
    )
    dataset.set_data_root(root)
    binding_types._double_quoted_props.cache_clear()
    yield root
    dataset.set_data_root(None)
    binding_types._double_quoted_props.cache_clear()


def _find(text):
    source = engine.load_text("Probe.yaml", text)
    return [d for d in engine.run_sources([source], select={RULE}) if d.rule_id == RULE]


def test_only_double_quoted_known_nonstring_bindings_are_reported(ui_root):
    text = """ВидЭлемента: КомпонентИнтерфейса
Наследует:
    Тип: Группа
    Ширина: "=200"
    Видимость: "=Истина"
    ОтступПоГоризонтали: "=РазмерОтступа.Одинарный"
    Заголовок: "=Текст()"
    Значение: "=Объект()"
    Содержимое: "=Компонент()"
    НеизвестноеСвойство: "=Неизвестно()"
"""
    findings = _find(text)
    assert len(findings) == 3
    assert all(d.severity.value == "error" and d.fix is not None for d in findings)
    fixed = text
    for finding in sorted(findings, key=lambda d: d.fix.start, reverse=True):
        assert text[finding.fix.start:finding.fix.end].startswith('"=')
        fixed = fixed[:finding.fix.start] + finding.fix.new + fixed[finding.fix.end:]
    assert yaml.safe_load(fixed) == yaml.safe_load(text)
    assert _find(fixed) == []


def test_single_quoted_and_bare_bindings_are_clean(ui_root):
    text = """ВидЭлемента: КомпонентИнтерфейса
Наследует:
    Тип: Группа
    Ширина: =200
    Видимость: '=Истина'
    ОтступПоГоризонтали: '=РазмерОтступа.Одинарный'
"""
    assert _find(text) == []


def test_fix_preserves_expression_with_inner_apostrophe(ui_root):
    text = """ВидЭлемента: КомпонентИнтерфейса
Наследует:
    Тип: Группа
    Ширина: "=Имя == \\"It's\\" ? 200 : 240"
"""
    findings = _find(text)
    assert len(findings) == 1 and findings[0].fix
    fix = findings[0].fix
    fixed = text[:fix.start] + fix.new + text[fix.end:]
    assert yaml.safe_load(fixed) == yaml.safe_load(text)
    assert "''" in fix.new
    assert _find(fixed) == []


def test_fix_preserves_crlf_and_a_trailing_comment(ui_root):
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\r\n"
        "Наследует:\r\n"
        "    Тип: Группа\r\n"
        "    Ширина: \"=200\"  # keep this note\r\n"
    )
    findings = _find(text)
    assert len(findings) == 1 and findings[0].fix
    edit = findings[0].fix
    fixed = text[:edit.start] + edit.new + text[edit.end:]
    assert fixed == text.replace('Ширина: "=200"', "Ширина: '=200'")
    assert fixed.count("\r\n") == text.count("\r\n")
    assert yaml.safe_load(fixed) == yaml.safe_load(text)


def test_escaped_equal_sign_is_still_a_binding(ui_root):
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        '    Ширина: "\\u003d200"\n'
    )
    findings = _find(text)
    assert len(findings) == 1 and findings[0].fix
    edit = findings[0].fix
    fixed = text[:edit.start] + edit.new + text[edit.end:]
    assert "Ширина: '=200'\n" in fixed
    assert yaml.safe_load(fixed) == yaml.safe_load(text)
    assert _find(fixed) == []


def test_without_ui_schema_is_silent(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    dataset.set_data_root(empty)
    binding_types._double_quoted_props.cache_clear()
    try:
        assert _find('ВидЭлемента: КомпонентИнтерфейса\nНаследует:\n    Тип: Группа\n    Ширина: "=200"\n') == []
    finally:
        dataset.set_data_root(None)
        binding_types._double_quoted_props.cache_clear()


@pytest.mark.needs_data
def test_english_aliases_find_and_fix_the_same_binding():
    text = 'ElementKind: InterfaceComponent\nInherits:\n    Type: Group\n    Width: "=200"\n'
    findings = _find(text)
    assert len(findings) == 1 and findings[0].fix
    fix = findings[0].fix
    fixed = text[:fix.start] + fix.new + text[fix.end:]
    assert yaml.safe_load(fixed) == yaml.safe_load(text)
    assert _find(fixed) == []
