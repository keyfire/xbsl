"""Упаковка: версия пакета берётся ровно из одного места.

Грабля 17.07.2026: версия дублировалась в pyproject.toml и в xbsl/__init__.py; бампы
правили только pyproject, и релизы 0.20/0.21 внутри представлялись как 0.19.0 – это
видели `xbsl --version`, LSP и статус-бар расширения. Теперь версия динамическая
(attr = xbsl.__version__), а тест держит это свойство.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import xbsl

# tomllib есть с Python 3.11, а пакет поддерживает 3.10 (requires-python) – на ней тест
# пропускается, а не роняет прогон. Тянуть ради него tomli в зависимости незачем: свойство
# проверяется на остальных версиях матрицы.
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
