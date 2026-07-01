"""Версионированный доступ к данным о языке и типах (самодостаточно, без дистрибутива).

Данные лежат в xbsllint/data/element/<версия>/{language.json, stdlib.json}, а
xbsllint/data/element/index.json хранит список доступных версий и версию по умолчанию.
Версия выбирается так: явный аргумент/set_version > env XBSLLINT_ELEMENT_VERSION > default из индекса.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

DATA_ROOT = Path(__file__).parent / "data" / "element"
_ENV_VERSION = "XBSLLINT_ELEMENT_VERSION"
_selected: str | None = None


class DatasetError(RuntimeError):
    pass


def _read_index() -> dict:
    idx = DATA_ROOT / "index.json"
    if not idx.exists():
        raise DatasetError(
            f"Нет индекса версий данных: {idx}. Сгенерируйте данные через tools/extract_*.py."
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
    load_json.cache_clear()


def resolve_version(override: str | None = None) -> str:
    version = override or _selected or os.environ.get(_ENV_VERSION) or default_version()
    avail = available_versions()
    if version not in avail:
        raise DatasetError(
            f"Версия данных '{version}' недоступна. Доступны: {', '.join(avail) or '—'}"
        )
    return version


@lru_cache(maxsize=None)
def load_json(name: str, version: str | None = None) -> dict:
    ver = resolve_version(version)
    path = DATA_ROOT / ver / name
    if not path.exists():
        raise DatasetError(f"Нет файла данных '{name}' для версии {ver}: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
