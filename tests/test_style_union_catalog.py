"""Optional generic metadata consumed by `style/redundant-union-member`.

These tests need no Element data: malformed optional sections must be ignored before the rule
tries to compare a source type. Keeping them outside the data-dependent rule module makes the
conservative fallback run in a public clone too.
"""

import pytest

from xbsl.rules import style_unions


@pytest.mark.parametrize("malformed", [None, 7, "out", []])
def test_non_mapping_optional_catalog_sections_are_ignored(monkeypatch, malformed):
    data = {
        "bases": {"Коробка": ["Объект"]},
        "type_params": {"Коробка": ["ТипЭлемента"]},
        "type_param_variance": malformed,
        "generic_bases": malformed,
    }
    monkeypatch.setattr(style_unions.dataset, "load_json", lambda _name: data)
    style_unions._catalog.cache_clear()
    try:
        _bases, _params, variance, generic_bases = style_unions._catalog()
    finally:
        style_unions._catalog.cache_clear()

    assert variance == {}
    assert generic_bases == {}


def test_malformed_optional_catalog_entries_are_ignored(monkeypatch):
    data = {
        "bases": {},
        "type_params": {},
        "type_param_variance": {
            "ЧитаемаяКоробка": ["out"],
            "Пустая": None,
            "Скаляр": 123,
            "Смешанная": ["out", 123],
            "Неизвестная": ["sideways"],
        },
        "generic_bases": {
            "Коробка": {"База": ["ТипЭлемента"]},
            "Пустая": None,
            "Скаляр": 123,
            "Смешанная": {"База": ["ТипЭлемента", 123]},
            "ПлохаяБаза": {"База": None},
        },
    }
    monkeypatch.setattr(style_unions.dataset, "load_json", lambda _name: data)
    style_unions._catalog.cache_clear()
    try:
        _bases, _params, variance, generic_bases = style_unions._catalog()
    finally:
        style_unions._catalog.cache_clear()

    assert variance == {"ЧитаемаяКоробка": ("out",)}
    assert generic_bases == {"Коробка": {"База": ("ТипЭлемента",)}}
