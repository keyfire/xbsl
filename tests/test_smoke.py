"""Смоук-тесты, не зависящие от сгенерированных данных Элемента (выполняются всегда)."""

import xbsllint
from xbsllint import dataset
from xbsllint.engine import RULES


def test_version_present():
    assert xbsllint.__version__


def test_rules_registered():
    ids = {r.id for r in RULES}
    assert {"code/blocks", "yaml/id-uuid", "typography/curly-quotes"} <= ids
    assert len(RULES) >= 15


def test_available_versions_is_list():
    # Без сгенерированных данных список версий пуст, но вызов не должен падать.
    assert isinstance(dataset.available_versions(), list)
