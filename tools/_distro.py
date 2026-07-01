"""Общие помощники для экстракторов: поиск .car, определение версии, индекс версий данных.

Экстракторы (extract_grammar.py, extract_stdlib.py) сами определяют версию Элемента из
дистрибутива и кладут производные данные в xbsllint/data/element/<версия>/, обновляя индекс.
Сам линтер работает от этих закоммиченных данных и дистрибутив в рантайме не требует.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_VER_RE = re.compile(r"-(\d+\.\d+\.\d+(?:\+\d+)?)-")


def find_car(dist: Path) -> Path:
    cars = sorted(dist.glob("*element-server-with-ide-*.car"))
    if not cars:
        raise SystemExit(f"В дистрибутиве {dist} не найден .car сервера с IDE")
    return cars[0]


def detect_version(dist: Path, override: str | None = None) -> str:
    """Версия Элемента: из --element-version или из имени .car (напр. 9.2.8+11)."""
    if override:
        return override
    car = find_car(dist)
    m = _VER_RE.search(car.name)
    if not m:
        raise SystemExit(
            f"Не удалось определить версию из '{car.name}'; задайте --element-version явно"
        )
    return m.group(1)


def data_root() -> Path:
    return REPO / "xbsllint" / "data" / "element"


def version_dir(version: str) -> Path:
    d = data_root() / version
    d.mkdir(parents=True, exist_ok=True)
    return d


def update_index(version: str, make_default: bool = True) -> None:
    """Добавить версию в индекс (data/element/index.json) и при необходимости сделать default."""
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    idx = root / "index.json"
    data = {"available": [], "default": None}
    if idx.exists():
        data = json.loads(idx.read_text(encoding="utf-8"))
    if version not in data["available"]:
        data["available"].append(version)
        data["available"].sort()
    if make_default or not data.get("default"):
        data["default"] = version
    idx.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
