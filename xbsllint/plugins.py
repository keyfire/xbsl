"""Точки расширения: внешние пакеты добавляют правила и данные через entry points.

Группа "xbsllint.rules" – значение указывает на модуль, импорт которого регистрирует
правила декоратором @rule (см. xbsllint/engine.py). Группа "xbsllint.data" – значение
указывает на корень данных: путь (Path/str) либо функция без аргументов, возвращающая путь.

Объявление в pyproject.toml стороннего пакета:

    [project.entry-points."xbsllint.rules"]
    имя-пакета = "мой_пакет.rules"

    [project.entry-points."xbsllint.data"]
    имя-пакета = "мой_пакет:data_root"

Обе группы отключает переменная окружения XBSLLINT_NO_PLUGINS=1 – прогон только со
встроенными правилами и данными.

Сбой загрузки точки расширения – ошибка, а не предупреждение: линтер, молча потерявший
правило, остаётся зелёным в CI и перестаёт что-либо гарантировать.
"""

from __future__ import annotations

import os
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

RULES_GROUP = "xbsllint.rules"
DATA_GROUP = "xbsllint.data"
ENV_DISABLE = "XBSLLINT_NO_PLUGINS"

_FALSY = {"", "0", "false", "no"}


class PluginError(RuntimeError):
    pass


def disabled() -> bool:
    return os.environ.get(ENV_DISABLE, "").strip().lower() not in _FALSY


def _points(group: str) -> list[EntryPoint]:
    if disabled():
        return []
    return sorted(entry_points(group=group), key=lambda ep: ep.name)


def _load(ep: EntryPoint):
    try:
        return ep.load()
    except Exception as exc:
        raise PluginError(
            f"Точка расширения '{ep.name}' группы {ep.group} не загрузилась "
            f"({ep.value}): {exc}"
        ) from exc


def load_rules() -> list[str]:
    """Импортировать модули правил внешних пакетов; вернуть имена загруженных точек."""
    loaded: list[str] = []
    for ep in _points(RULES_GROUP):
        _load(ep)
        loaded.append(ep.name)
    return loaded


def data_roots() -> list[Path]:
    """Корни данных, объявленные внешними пакетами (в порядке имён точек)."""
    roots: list[Path] = []
    for ep in _points(DATA_GROUP):
        target = _load(ep)
        if callable(target):
            target = target()
        roots.append(Path(target))
    return roots
