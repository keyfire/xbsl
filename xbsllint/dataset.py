"""Версионированный доступ к данным о языке и типах (самодостаточно, без дистрибутива).

Данные лежат в <корень>/<версия>/{language.json, stdlib.json, metamodel.json}, а
<корень>/index.json хранит список доступных версий и версию по умолчанию.

Корень данных выбирается так: set_data_root() (CLI --data-dir) > env XBSLLINT_DATA_DIR >
корень из точки расширения "xbsllint.data" > каталог внутри пакета (xbsllint/data/element).
Внешний корень нужен тем, кто не может публиковать данные вместе с пакетом: данные
извлекаются из своего дистрибутива и подключаются отдельным пакетом (см. xbsllint/plugins.py).

Версия выбирается так: явный аргумент/set_version > env XBSLLINT_ELEMENT_VERSION >
default из индекса.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from xbsllint import plugins

BUNDLED_DATA_ROOT = Path(__file__).parent / "data" / "element"
_ENV_VERSION = "XBSLLINT_ELEMENT_VERSION"
_ENV_DATA_DIR = "XBSLLINT_DATA_DIR"

_selected: str | None = None
_root_override: Path | None = None


class DatasetError(RuntimeError):
    pass


def set_data_root(path: str | os.PathLike[str] | None) -> None:
    """Зафиксировать корень данных для процесса (CLI --data-dir). Сбрасывает кэш."""
    global _root_override
    _root_override = Path(path) if path is not None else None
    _load_cached.cache_clear()


def data_root() -> Path:
    """Действующий корень данных по порядку приоритетов (см. описание модуля)."""
    if _root_override is not None:
        return _root_override
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        return Path(env)
    for root in plugins.data_roots():
        if (root / "index.json").exists():
            return root
    return BUNDLED_DATA_ROOT


def _read_index() -> dict:
    idx = data_root() / "index.json"
    if not idx.exists():
        raise DatasetError(
            f"Нет индекса версий данных: {idx}. Сгенерируйте данные через tools/extract_*.py "
            f"или укажите готовый корень: --data-dir / env {_ENV_DATA_DIR}."
        )
    return json.loads(idx.read_text(encoding="utf-8"))


def available_versions() -> list[str]:
    try:
        return list(_read_index().get("available", []))
    except DatasetError:
        return []


def default_version() -> str:
    version = _read_index().get("default")
    if not version:
        raise DatasetError("В индексе версий не задан default")
    return version


def set_version(version: str | None) -> None:
    """Зафиксировать версию данных для процесса (CLI --element-version). Сбрасывает кэш."""
    global _selected
    _selected = version
    _load_cached.cache_clear()


def resolve_version(override: str | None = None) -> str:
    version = override or _selected or os.environ.get(_ENV_VERSION) or default_version()
    avail = available_versions()
    if version not in avail:
        raise DatasetError(
            f"Версия данных '{version}' недоступна. Доступны: {', '.join(avail) or '—'}"
        )
    return version


# Корень входит в ключ кэша: иначе смена корня отдавала бы данные, прочитанные из прежнего.
@lru_cache(maxsize=None)
def _load_cached(root: str, version: str, name: str) -> dict:
    path = Path(root) / version / name
    if not path.exists():
        raise DatasetError(f"Нет файла данных '{name}' для версии {version}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_json(name: str, version: str | None = None) -> dict:
    return _load_cached(str(data_root()), resolve_version(version), name)
