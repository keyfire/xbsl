"""Extension points: external packages add rules, data and severity overrides via entry points.

The "xbsllint.rules" group – the value points to a module whose import registers rules with
the @rule decorator (see xbsllint/engine.py). The "xbsllint.data" group – the value points to
a data root: a path (Path/str) or a zero-argument callable returning a path. The
"xbsllint.severity" group – the value points to a dict {rule id: "error"|"warning"|"info"|"off"}
or a zero-argument callable returning one; the levels replace the rules' defaults for this
installation ("off" removes a rule from the default set; an explicit --select/--enable still
turns it on, with its base severity when a level is not given).

Declaration in a third-party package's pyproject.toml:

    [project.entry-points."xbsllint.rules"]
    package-name = "my_package.rules"

    [project.entry-points."xbsllint.data"]
    package-name = "my_package:data_root"

    [project.entry-points."xbsllint.severity"]
    package-name = "my_package:severity_overrides"

The XBSLLINT_NO_PLUGINS=1 environment variable disables all groups – a run with the built-in
rules, data and severities only.

A failing entry point is an error, not a warning: a linter that silently drops a rule stays
green in CI and stops guaranteeing anything. The same goes for overrides: an unknown rule id
or level in an override dict raises, because a silently ignored override is a typo that
nobody notices.
"""

from __future__ import annotations

import os
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path

RULES_GROUP = "xbsllint.rules"
DATA_GROUP = "xbsllint.data"
SEVERITY_GROUP = "xbsllint.severity"
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
    """Import external packages' rule modules; return the names of the loaded entry points."""
    loaded: list[str] = []
    for ep in _points(RULES_GROUP):
        _load(ep)
        loaded.append(ep.name)
    return loaded


def data_roots() -> list[Path]:
    """Data roots declared by external packages (ordered by entry-point name)."""
    roots: list[Path] = []
    for ep in _points(DATA_GROUP):
        target = _load(ep)
        if callable(target):
            target = target()
        roots.append(Path(target))
    return roots


def severity_overrides() -> dict[str, str]:
    """Severity overrides declared by external packages, merged by entry-point name.

    Each entry point supplies a dict {rule id: level}, where the level is one of
    "error"/"warning"/"info"/"off". On a repeated rule id the entry point later in the
    name order wins (same ordering as rules and data roots). Validation against the
    rule registry happens in the engine, after plugin rules are registered.
    """
    merged: dict[str, str] = {}
    for ep in _points(SEVERITY_GROUP):
        target = _load(ep)
        if callable(target):
            target = target()
        if not isinstance(target, dict):
            raise PluginError(
                f"Точка расширения '{ep.name}' группы {ep.group} должна давать словарь "
                f"{{id правила: уровень}}, получено: {type(target).__name__}"
            )
        for rule_id, level in target.items():
            merged[str(rule_id)] = str(level)
    return merged
