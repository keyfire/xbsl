"""Smoke tests independent of the generated Element data (always executed)."""

import xbsl
from xbsl import dataset
from xbsl.engine import RULES


def test_version_present():
    assert xbsl.__version__


def test_rules_registered():
    ids = {r.id for r in RULES}
    assert {"code/blocks", "yaml/id-uuid", "typography/curly-quotes"} <= ids
    assert len(RULES) >= 15


def test_available_versions_is_list():
    # Without the generated data the version list is empty, but the call must not crash.
    assert isinstance(dataset.available_versions(), list)
