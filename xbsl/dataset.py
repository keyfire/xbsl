"""Versioned access to the language and type data (self-contained, no distribution needed).

The data lives in <root>/<version>/{language.json, stdlib.json, metamodel.json}, and
<root>/index.json holds the list of available versions and the default one.

The data root is chosen by: set_data_root() (CLI --data-dir) > env XBSL_DATA_DIR >
a root from the "xbsl.data" entry point > a directory inside the package (xbsl/data/element).
An external root is for those who cannot publish the data with the package: the data is
extracted from their own distribution and supplied by a separate package (see xbsl/plugins.py).

The version is chosen by: an explicit argument/set_version > env XBSL_ELEMENT_VERSION >
the index default.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from xbsl import i18n, plugins

BUNDLED_DATA_ROOT = Path(__file__).parent / "data" / "element"
_ENV_VERSION = "XBSL_ELEMENT_VERSION"
_ENV_DATA_DIR = "XBSL_DATA_DIR"
# The pre-rename variable names keep working (checked after the new ones).
_ENV_VERSION_LEGACY = "XBSLLINT_ELEMENT_VERSION"
_ENV_DATA_DIR_LEGACY = "XBSLLINT_DATA_DIR"


def _env(name: str, legacy: str) -> str | None:
    return os.environ.get(name) or os.environ.get(legacy)

_selected: str | None = None
_root_override: Path | None = None

_MESSAGES = {
    "dataset.no-index": {
        "ru": "Нет индекса версий данных: {idx}. Сгенерируйте данные через tools/extract_*.py "
              "или укажите готовый корень: --data-dir / env {env}.",
        "en": "No data version index: {idx}. Generate the data via tools/extract_*.py "
              "or point at a ready root: --data-dir / env {env}.",
    },
    "dataset.no-default": {
        "ru": "В индексе версий не задан default",
        "en": "The version index has no default",
    },
    "dataset.version-unavailable": {
        "ru": "Версия данных '{version}' недоступна. Доступны: {available}",
        "en": "Data version '{version}' is unavailable. Available: {available}",
    },
    "dataset.no-file": {
        "ru": "Нет файла данных '{name}' для версии {version}: {path}",
        "en": "No data file '{name}' for version {version}: {path}",
    },
}
i18n.register(_MESSAGES)


class DatasetError(RuntimeError):
    pass


#: Caches derived from the dataset, dropped whenever the root or the version changes. A module
#: that precomputes tables over the data (the metamodel does) registers its own reset here -
#: otherwise pinning another root would still answer from the previous one.
_RESET_HOOKS: list = []


def register_reset(hook) -> None:
    """Register a callable to run when the pinned data root or version changes."""
    _RESET_HOOKS.append(hook)


#: Modification stamps of the files behind the caches: (root, version, name) -> st_mtime_ns.
#: A file regenerated IN PLACE (tools/extract.py over the same root) must not keep answering
#: from the process cache: the LSP and MCP servers live long, and a stale catalog used to be
#: discovered only by answers diverging from freshly generated data - the cure was a restart.
#: Every load compares the stamps of the files already read for that root; one changed stamp
#: drops every cache, the derived tables registered via register_reset included (they are
#: built over this data and must not outlive it).
_FILE_STAMPS: dict[tuple[str, str, str], int | None] = {}


def _stamp(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _drop_if_stale(root: str) -> None:
    """Clear every cache when any file read for this root changed on disk since."""
    for (r, version, name), stamp in list(_FILE_STAMPS.items()):
        if r != root:
            continue
        if _stamp(Path(r) / version / name if version else Path(r) / name) != stamp:
            _clear_caches()
            return


def _clear_caches() -> None:
    _load_cached.cache_clear()
    _discovered_root.cache_clear()
    _index_cached.cache_clear()
    _FILE_STAMPS.clear()
    for hook in _RESET_HOOKS:
        hook()


def set_data_root(path: str | os.PathLike[str] | None) -> None:
    """Pin the data root for the process (CLI --data-dir). Clears the cache."""
    global _root_override
    _root_override = Path(path) if path is not None else None
    _clear_caches()


def data_root() -> Path:
    """The effective data root, by priority order (see the module description).

    Every dataset access resolves the root, so the plugin walk below is cached; the
    override and the env checks stay outside the cache - they are cheap and a test
    (or the CLI) changes them mid-process.
    """
    if _root_override is not None:
        return _root_override
    env = _env(_ENV_DATA_DIR, _ENV_DATA_DIR_LEGACY)
    if env:
        return Path(env)
    return _discovered_root()


@lru_cache(maxsize=None)
def _discovered_root() -> Path:
    for root in plugins.data_roots():
        if (root / "index.json").exists():
            return root
    return BUNDLED_DATA_ROOT


def data_root_source() -> str:
    """Where the data root came from (for the --where diagnostic): CLI / env / plugin / bundle."""
    if _root_override is not None:
        return "--data-dir"
    if _env(_ENV_DATA_DIR, _ENV_DATA_DIR_LEGACY):
        return f"env {_ENV_DATA_DIR}"
    for root in plugins.data_roots():
        if (root / "index.json").exists():
            return "плагин (точка расширения xbsl.data)"
    return "встроенные данные пакета"


def _read_index() -> dict:
    root = str(data_root())
    _drop_if_stale(root)
    return _index_cached(root)


# The root is the cache key: version resolution reads the index on every dataset access,
# and re-reading the file each time costs a run dearly (a whole-project pass resolves
# the version hundreds of times). set_data_root/set_version clear the cache.
@lru_cache(maxsize=None)
def _index_cached(root: str) -> dict:
    idx = Path(root) / "index.json"
    if not idx.exists():
        raise DatasetError(i18n.t("dataset.no-index", idx=idx, env=_ENV_DATA_DIR))
    _FILE_STAMPS[(root, "", "index.json")] = _stamp(idx)
    return json.loads(idx.read_text(encoding="utf-8"))


def available_versions() -> list[str]:
    try:
        return list(_read_index().get("available", []))
    except DatasetError:
        return []


def default_version() -> str:
    version = _read_index().get("default")
    if not version:
        raise DatasetError(i18n.t("dataset.no-default"))
    return version


def set_version(version: str | None) -> None:
    """Pin the data version for the process (CLI --element-version). Clears the cache."""
    global _selected
    _selected = version
    _clear_caches()


def resolve_version(override: str | None = None) -> str:
    version = override or _selected or _env(_ENV_VERSION, _ENV_VERSION_LEGACY) or default_version()
    avail = available_versions()
    if version not in avail:
        raise DatasetError(
            i18n.t("dataset.version-unavailable", version=version, available=", ".join(avail) or "–")
        )
    return version


# The root is part of the cache key: otherwise switching roots would return data read from the old one.
def _add_english_keys(data: dict, pairs: dict) -> dict:
    """Add the English key of every type/facet, copying the Russian entry.

    The catalog stores members, bases and facets once - under the Russian name (or the Latin
    one for a type that has no Russian). `pairs` is terms.json's Russian->English map (types +
    facets); the English key gets the same value, so a type is not written twice. Runs before
    the inheritance expansion, so the English types then inherit exactly like the Russian ones.
    """
    if data.get("meta", {}).get("bilingual_keys") != "expand" or not pairs:
        return data
    for section in ("type_members", "member_types", "bases"):
        entries = data.get(section)
        if not entries:
            continue
        for ru, en in pairs.items():
            if ru in entries and en not in entries:
                entries[en] = entries[ru]
    return data


def _expand_inherited(data: dict) -> dict:
    """Re-expand the own-members form of stdlib.json into full member sets.

    The extractor stores only each type's OWN members (meta.members == "own") to avoid
    repeating an inherited member once per heir. Here a type's full set is rebuilt by adding
    every ancestor's own set - `bases` is the transitively closed ancestor list, so one pass
    over it suffices. member_types (result types) merges the same way, the type's own last so
    an overridden member keeps its own result type. Datasets without the marker (older, full)
    are returned untouched. The consumers keep reading type_members/member_types as before.
    """
    if data.get("meta", {}).get("members") != "own":
        return data
    bases = data.get("bases") or {}
    own_members = data.get("type_members") or {}
    full_members: dict[str, dict[str, list[str]]] = {}
    for name, own in own_members.items():
        props, methods = set(own.get("properties", ())), set(own.get("methods", ()))
        for base in bases.get(name, ()):
            base_own = own_members.get(base, {})
            props.update(base_own.get("properties", ()))
            methods.update(base_own.get("methods", ()))
        entry: dict[str, list[str]] = {}
        if props:
            entry["properties"] = sorted(props)
        if methods:
            entry["methods"] = sorted(methods)
        full_members[name] = entry
    own_returns = data.get("member_types") or {}
    full_returns: dict[str, dict[str, str]] = {}
    for name, own in own_returns.items():
        merged: dict[str, str] = {}
        for base in bases.get(name, ()):
            merged.update(own_returns.get(base, {}))
        merged.update(own)
        full_returns[name] = merged
    data["type_members"] = full_members
    data["member_types"] = full_returns
    return data


def _stdlib_pairs(root: str, version: str) -> dict:
    """terms.json's Russian->English pairs (types + facets), or empty if the file is absent."""
    try:
        terms = _load_cached(root, version, "terms.json")
    except DatasetError:
        return {}
    return {**(terms.get("types") or {}), **(terms.get("facets") or {})}


@lru_cache(maxsize=None)
def _load_cached(root: str, version: str, name: str) -> dict:
    path = Path(root) / version / name
    if not path.exists():
        raise DatasetError(i18n.t("dataset.no-file", name=name, version=version, path=path))
    data = json.loads(path.read_text(encoding="utf-8"))
    _FILE_STAMPS[(root, version, name)] = _stamp(path)
    if name == "stdlib.json":
        # English keys first (so the English types then inherit like the Russian ones),
        # then the inheritance expansion.
        data = _add_english_keys(data, _stdlib_pairs(root, version))
        data = _expand_inherited(data)
    return data


def load_json(name: str, version: str | None = None) -> dict:
    root = str(data_root())
    _drop_if_stale(root)
    return _load_cached(root, resolve_version(version), name)


def member_type_head(type_name: str) -> str:
    """The nominal root of a member_types value: 'ЧитаемоеМножество<Настройки>?' -> 'ЧитаемоеМножество'.

    The catalog keeps the full docs spelling of a member's result type (the generic
    parameter included), while the type tables are keyed by the bare head - every lookup
    cuts through here. Data of any vintage passes: a root stored bare comes back unchanged,
    and a dotted facet name (Пользователи.Объект) keeps its dot.
    """
    return type_name.split("<", 1)[0].split("|", 1)[0].strip().rstrip("?")


#: The interface component ui schema, generated by tools/extract_uischema.py from the
#: documentation dataset and written next to stdlib.json (see that tool's docstring for
#: the data shape).
UI_SCHEMA_FILE = "uischema.json"


def load_ui_schema(version: str | None = None) -> dict | None:
    """The interface component ui schema for the version, or None when not generated.

    Cached per (root, version) like the other data files (load_json). Returns None
    instead of raising: the ui schema is optional data - the designer surfaces (the
    palette, the typed properties panel) degrade gracefully without it, the same way
    the documentation does.
    """
    try:
        return load_json(UI_SCHEMA_FILE, version)
    except DatasetError:
        return None


def data_file(name: str, version: str | None = None) -> Path:
    """Path to a data file of the version (for non-JSON files: docs.sqlite etc.). Raises when the file is missing."""
    ver = resolve_version(version)
    path = data_root() / ver / name
    if not path.exists():
        raise DatasetError(i18n.t("dataset.no-file", name=name, version=ver, path=path))
    return path


def has_data_file(name: str, version: str | None = None) -> bool:
    """Whether the data file exists (no exception) - for optional data such as the documentation."""
    try:
        return data_file(name, version).exists()
    except DatasetError:
        return False
