"""Общие настройки тестов.

Данные о языке/типах (xbsllint/data/element/...) извлекаются из дистрибутива 1С:Элемент и
могут не быть сгенерированы (напр. в публичной сборке без бандла данных). Тесты, которым
данные нужны, в этом случае пропускаются, а не падают.
"""

import pytest

from xbsllint import dataset

_DATA_DEPENDENT = {
    "test_lexer",
    "test_language",
    "test_rules",
    "test_mcp",
    "test_dataset",
    "test_corpus",
}


def _has_data() -> bool:
    try:
        return bool(dataset.available_versions())
    except Exception:  # noqa: BLE001
        return False


def pytest_collection_modifyitems(config, items):
    if _has_data():
        return
    skip = pytest.mark.skip(
        reason="нет данных Элемента – сгенерируйте tools/extract_grammar.py + extract_stdlib.py"
    )
    for item in items:
        module = getattr(item, "module", None)
        name = getattr(module, "__name__", "")
        if name in _DATA_DEPENDENT:
            item.add_marker(skip)
