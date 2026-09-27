"""Extension points: external packages add rules, data and severity overrides via entry points.

The "xbsl.rules" group - the value points to a module whose import registers rules with
the @rule decorator (see xbsl/engine.py). The "xbsl.data" group - the value points to
a data root: a path (Path/str) or a zero-argument callable returning a path. The
"xbsl.severity" group - the value points to a dict {rule id: "error"|"warning"|"info"|"off"}
or a zero-argument callable returning one; the levels replace the rules' defaults for this
installation ("off" removes a rule from the default set; an explicit --select/--enable still
turns it on, with its base severity when a level is not given).

Declaration in a third-party package's pyproject.toml:

    [project.entry-points."xbsl.rules"]
    package-name = "my_package.rules"

    [project.entry-points."xbsl.data"]
    package-name = "my_package:data_root"

    [project.entry-points."xbsl.severity"]
    package-name = "my_package:severity_overrides"

The XBSL_NO_PLUGINS=1 environment variable disables all groups - a run with the built-in
rules, data and severities only (the pre-rename name XBSLLINT_NO_PLUGINS still works).

Plugins published against the old package name keep working: the legacy groups
"xbsllint.rules"/"xbsllint.data"/"xbsllint.severity" are scanned after the new ones.

A failing entry point is an error, not a warning: a linter that silently drops a rule stays
green in CI and stops guaranteeing anything. The same goes for overrides: an unknown rule id
or level in an override dict raises, because a silently ignored override is a typo that
nobody notices.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Callable, NamedTuple

RULES_GROUP = "xbsl.rules"
DATA_GROUP = "xbsl.data"
SEVERITY_GROUP = "xbsl.severity"
# The groups under the pre-rename package name; scanned after the new ones.
_LEGACY_GROUPS = {
    RULES_GROUP: "xbsllint.rules",
    DATA_GROUP: "xbsllint.data",
    SEVERITY_GROUP: "xbsllint.severity",
}
ENV_DISABLE = "XBSL_NO_PLUGINS"
_ENV_DISABLE_LEGACY = "XBSLLINT_NO_PLUGINS"

_FALSY = {"", "0", "false", "no"}


class PluginError(RuntimeError):
    pass


def disabled() -> bool:
    raw = os.environ.get(ENV_DISABLE, os.environ.get(_ENV_DISABLE_LEGACY, ""))
    return raw.strip().lower() not in _FALSY


#: The groups a plugin may declare, in the order its distribution is named by.
_GROUPS = (RULES_GROUP, DATA_GROUP, SEVERITY_GROUP)


class Found(NamedTuple):
    """The distribution behind an entry point, as one reading of its metadata saw it."""

    name: str
    version: str
    #: The folder the distribution is installed into (its site-packages); None for a stub.
    folder: str | None


#: The distribution of every entry point the cached walk found, read by that walk:
#: {entry point: Found}. The walk is where a plugin is found and its modules imported, so this is
#: the version the process runs. The metadata on disk may say otherwise later - an upgrade under
#: a running server replaces it and leaves the loaded modules as they were.
_as_loaded: dict = {}


def _points(group: str) -> list[EntryPoint]:
    if disabled():
        return []
    return list(_scan(group, entry_points))


def _walk(group: str, scan: Callable) -> tuple[EntryPoint, ...]:
    """The entry points of a group and of its legacy twin, each once, ordered by name."""
    found = list(scan(group=group))
    legacy = _LEGACY_GROUPS.get(group)
    if legacy:
        # A package published for the transition period may declare both groups -
        # count each (name, target) once, the new group wins.
        seen = {(ep.name, ep.value) for ep in found}
        found.extend(ep for ep in scan(group=legacy) if (ep.name, ep.value) not in seen)
    return tuple(sorted(found, key=lambda ep: ep.name))


@lru_cache(maxsize=None)
def _scan(group: str, scan: Callable) -> tuple[EntryPoint, ...]:
    """One entry-point walk per group and process.

    A walk reads every installed distribution's metadata, and the callers (the dataset
    root resolution, the severity overrides) come back many times per run - uncached
    it was the single largest share of a whole-project pass. The scanning callable is
    part of the cache key on purpose: a test that monkeypatches `entry_points` gets a
    fresh walk through its stub, with no cache reset to remember. The distribution of each
    entry point is read here too (`_as_loaded`): this is the walk the plugins are loaded by.
    """
    found = _walk(group, scan)
    for ep in found:
        if ep not in _as_loaded:
            _as_loaded[ep] = _distribution(ep)
    return found


def _distribution(ep) -> Found | None:
    """The distribution behind an entry point, read now; None for a stub or unreadable metadata."""
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None
    try:
        name, version = dist.metadata["Name"], dist.version
    except Exception:
        return None
    if not name:
        return None
    try:
        folder = str(dist.locate_file(""))
    except Exception:
        folder = None
    return Found(str(name), str(version or ""), folder)


def _named(found: Iterable[Found | None]) -> list[dict]:
    """[{"name", "version"}] ordered by name, each distribution once (the first reading wins)."""
    versions: dict[str, str] = {}
    for one in found:
        if one is not None:
            versions.setdefault(one.name, one.version)
    return [{"name": name, "version": versions[name]} for name in sorted(versions)]


def _load(ep: EntryPoint):
    try:
        return ep.load()
    except Exception as exc:
        raise PluginError(
            f"Точка расширения '{ep.name}' группы {ep.group} не загрузилась "
            f"({ep.value}): {exc}"
        ) from exc


def module_files() -> list[str]:
    """The files of the top-level modules the plugin entry points name, for those imported.

    A plugin package is loaded code as much as the engine is: a pull in the checkout of an
    editable plugin changes the rules a running server holds while the version stays the
    same, so the fingerprint of xbsl/freshness.py walks these as well.
    """
    files: list[str] = []
    for group in _GROUPS:
        for ep in _points(group):
            top = str(getattr(ep, "value", "")).split(":", 1)[0].split(".", 1)[0].strip()
            module = sys.modules.get(top) if top else None
            file = getattr(module, "__file__", None)
            if file and file not in files:
                files.append(file)
    return files


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


def installed() -> list[dict]:
    """The plugged-in distributions, each once: [{"name", "version"}], ordered by name.

    For the --version line, the LSP start log and the MCP diagnostic. Two environments
    carrying different plugin versions answer differently on the same file, and nothing
    used to say so - the diagnosis went through site-packages of both. Nothing is loaded
    here: the names come from the entry-point metadata alone, so the answer is safe even
    when a plugin is broken. An entry point without a distribution (a test stub) is
    skipped.

    The versions are the ones the walk read when it loaded the plugins, not the ones on disk
    now: a long-lived server keeps the modules it imported, and after an upgrade under it the
    metadata on disk describes code it does not run. `on_disk` reads the disk.
    """
    return _named(_as_loaded.get(ep) or _distribution(ep)
                  for group in _GROUPS for ep in _points(group))


def installed_folders() -> list[str]:
    """The folders the loaded plugin distributions are installed into, each once."""
    folders: list[str] = []
    for group in _GROUPS:
        for ep in _points(group):
            found = _as_loaded.get(ep)
            if found is not None and found.folder and found.folder not in folders:
                folders.append(found.folder)
    return folders


def on_disk() -> list[dict]:
    """The plugin distributions installed now, as `installed` names them: a walk past the cache.

    What a long-lived process compares its plugins with (xbsl/freshness.py). One walk reads the
    entry points of every installed distribution: tens of milliseconds in a small environment,
    hundreds in one with a hundred packages - so the caller walks only when a folder the
    distributions live in has changed. A walk that fails raises; the caller decides what that
    is worth.
    """
    if disabled():
        return []
    everything = entry_points()

    def select(group: str):
        return everything.select(group=group)

    return _named(_distribution(ep) for group in _GROUPS for ep in _walk(group, select))


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
