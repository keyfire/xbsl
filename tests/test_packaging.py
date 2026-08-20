"""Packaging: what a published wheel says about itself and what it carries.

Pitfall of 2026-07-17: the version was duplicated in pyproject.toml and in xbsl/__init__.py;
bumps only touched pyproject, and the 0.20/0.21 releases identified themselves as 0.19.0 -
seen by `xbsl --version`, the LSP and the extension status bar. The version is now dynamic
(attr = xbsl.__version__), and this test keeps that property.

The second guard is about the contents. [tool.setuptools] packages is written by hand, and a
subpackage left out of it is absent from the wheel while nobody working on the sources can see
it: a checkout and an editable install both expose the whole tree, so the tests, the CLI and the
IDE keep working right up to the release. That is how xbsl.translation was nearly published as
an import error - the list had not been extended when the package appeared.
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


def test_packages_list_matches_the_tree():
    # The tree is read with the tool that assembles the wheel, and with the same filter the list
    # is meant to describe: everything under the two distributed top-level names.
    setuptools = pytest.importorskip(
        "setuptools", reason="сверка списка пакетов с деревом требует setuptools"
    )
    declared = set(_project()["tool"]["setuptools"]["packages"])
    found = set(
        setuptools.find_packages(where=str(_PYPROJECT.parent), include=["xbsl*", "xbsllint*"])
    )
    missing = sorted(found - declared)
    stale = sorted(declared - found)
    assert not missing, (
        "в pyproject.toml, [tool.setuptools] packages, не перечислены подпакеты: "
        + ", ".join(missing)
        + " – в колесо они не попадут, импорт у пользователя упадёт"
    )
    assert not stale, (
        "в pyproject.toml, [tool.setuptools] packages, перечислены несуществующие пакеты: "
        + ", ".join(stale)
    )
