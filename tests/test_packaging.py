"""Packaging: the package version comes from exactly one place.

Pitfall of 2026-07-17: the version was duplicated in pyproject.toml and in xbsl/__init__.py;
bumps only touched pyproject, and the 0.20/0.21 releases identified themselves as 0.19.0 -
seen by `xbsl --version`, the LSP and the extension status bar. The version is now dynamic
(attr = xbsl.__version__), and this test keeps that property.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import xbsl

# tomllib exists since Python 3.11, while the package supports 3.10 (requires-python) - there
# the test is skipped rather than failing the run. No point pulling tomli into dependencies
# just for this: the property is checked on the other versions of the matrix.
tomllib = pytest.importorskip("tomllib", reason="tomllib появился в Python 3.11")

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _project() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_version_has_single_source():
    data = _project()
    assert "version" not in data["project"], (
        "версия не должна дублироваться в pyproject.toml – она динамическая"
    )
    assert "version" in (data["project"].get("dynamic") or [])
    attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "xbsl.__version__"


def test_version_is_sane():
    parts = xbsl.__version__.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts), xbsl.__version__
