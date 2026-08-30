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

#: The member kinds a stdlib type declares. Events have a section of their own in the newer
#: documents; older ones listed them among the properties, so a dataset without the section is
#: not "an API without events" - see the extractor.
MEMBER_KINDS = ("properties", "methods", "events")

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
    "dataset.bad-json": {
        "ru": "Файл данных не разбирается как JSON: {path} ({error})",
        "en": "The data file does not parse as JSON: {path} ({error})",
    },
}
i18n.register(_MESSAGES)


class DatasetError(RuntimeError):
    pass


def read_json(path: Path) -> dict:
    """Read one of our JSON files: tolerate a BOM, name the file when it does not parse.

    PowerShell 5.1 (`Out-File -Encoding utf8`) writes a BOM, and a bare `JSONDecodeError`
    without a path once cost a run of its own to diagnose - every step reading the index
    failed with the same message and none of them said on which file. Writing stays
    BOM-free; only reading is tolerant.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        raise DatasetError(i18n.t("dataset.bad-json", path=path, error=error)) from error


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


def pinned_root() -> str | None:
    """The root set_data_root pinned for this process, or None when nothing is pinned.

    A worker process starts without the pin - the override is a module global - so a run
    that spawns workers has to hand it over explicitly (engine._worker_lint).
    """
    return str(_root_override) if _root_override is not None else None


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
    return read_json(idx)


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
    for section in ("type_members", "member_types", "member_signatures", "bases", "type_ctors",
                    "type_params", "member_type_params"):
        entries = data.get(section)
        if not entries:
            continue
        for ru, en in pairs.items():
            if ru in entries and en not in entries:
                entries[en] = entries[ru]
    return data


def _add_english_globals(data: dict, common: dict) -> dict:
    """Add the English spelling of every global NAME the catalog lists.

    `_add_english_keys` above pairs the type KEYS; `globals` is not keyed at all - it is the
    list of names the language offers by themselves, and the catalog carries it in one
    spelling, because the documentation it is extracted from is Russian. An English project
    calls the very same global `GoToLink`, the compiler accepts both, and a consumer that
    reads the list as "the global scope" (the undefined-name rule, the completion) must see
    both. `common` is the compiler dictionary (terms_full.json); a name it does not pair
    stays as it is, and a name already spelled in Latin is not touched.
    """
    if data.get("meta", {}).get("bilingual_keys") != "expand" or not common:
        return data
    names = data.get("globals")
    if not isinstance(names, list):
        return data
    known = set(names)
    for name in names:
        english = common.get(name)
        if english and english not in known:
            known.add(english)
    data["globals"] = sorted(known)
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
        by_kind = {kind: set(own.get(kind, ())) for kind in MEMBER_KINDS}
        for base in bases.get(name, ()):
            base_own = own_members.get(base, {})
            for kind in MEMBER_KINDS:
                by_kind[kind].update(base_own.get(kind, ()))
        full_members[name] = {
            kind: sorted(by_kind[kind]) for kind in MEMBER_KINDS if by_kind[kind]
        }
    own_returns = data.get("member_types") or {}
    full_returns: dict[str, dict[str, str]] = {}
    # Every type with ancestors, not just those with own result types: a collection declares no
    # result type of its own (`First`, `Get` belong to its bases), so walking own_returns alone
    # left `Array` without a single one - a chain over any of its methods ended there.
    for name in set(own_returns) | {n for n in own_members if bases.get(n)}:
        merged: dict[str, str] = {}
        for base in bases.get(name, ()):
            merged.update(own_returns.get(base, {}))
        merged.update(own_returns.get(name, {}))
        if merged:
            full_returns[name] = merged
    # Method signatures merge exactly like the result types - an inherited method keeps the
    # signature of the type that declares it, an overridden one its own.
    own_signatures = data.get("member_signatures") or {}
    full_signatures: dict[str, dict[str, list[str]]] = {}
    for name in set(own_signatures) | {n for n in own_members if bases.get(n)}:
        merged_sigs: dict[str, list[str]] = {}
        for base in bases.get(name, ()):
            merged_sigs.update(own_signatures.get(base, {}))
        merged_sigs.update(own_signatures.get(name, {}))
        if merged_sigs:
            full_signatures[name] = merged_sigs
    # The type parameters of a METHOD travel with the method: an heir that inherits
    # `Transform` inherits the parameter that names its result.
    own_method_params = data.get("member_type_params") or {}
    full_method_params: dict[str, dict[str, list[str]]] = {}
    for name in set(own_method_params) | {n for n in own_members if bases.get(n)}:
        merged_params: dict[str, list[str]] = {}
        for base in bases.get(name, ()):
            merged_params.update(own_method_params.get(base, {}))
        merged_params.update(own_method_params.get(name, {}))
        if merged_params:
            full_method_params[name] = merged_params
    if own_method_params:
        data["member_type_params"] = full_method_params
    data["type_members"] = full_members
    data["member_types"] = full_returns
    if own_signatures:
        data["member_signatures"] = full_signatures
    return data


def _stdlib_pairs(root: str, version: str) -> dict:
    """terms.json's Russian->English pairs (types + facets), or empty if the file is absent."""
    try:
        terms = _load_cached(root, version, "terms.json")
    except DatasetError:
        return {}
    return {**(terms.get("types") or {}), **(terms.get("facets") or {})}


def _stdlib_common_pairs(root: str, version: str) -> dict:
    """terms_full.json's Russian->English pairs of every compiler name, or empty when absent.

    The compact terms.json covers types, facets, yaml properties and enumeration values; the
    globals of the language (`Message`, `GoToLink`) are only in the full dictionary.
    Read here rather than through xbsl.terms: that module reads its data from this one.
    """
    try:
        terms = _load_cached(root, version, "terms_full.json")
    except DatasetError:
        return {}
    return dict(terms.get("common") or {})


@lru_cache(maxsize=None)
def _load_cached(root: str, version: str, name: str) -> dict:
    path = Path(root) / version / name
    if not path.exists():
        raise DatasetError(i18n.t("dataset.no-file", name=name, version=version, path=path))
    data = read_json(path)
    _FILE_STAMPS[(root, version, name)] = _stamp(path)
    if name == "stdlib.json":
        # English keys first (so the English types then inherit like the Russian ones),
        # then the inheritance expansion.
        data = _add_english_keys(data, _stdlib_pairs(root, version))
        data = _add_english_globals(data, _stdlib_common_pairs(root, version))
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


def generic_args(written: str) -> list[str]:
    """The generic arguments of a written type: `Соответствие<Строка, Массив<Ссылка>>` ->
    ['Строка', 'Массив<Ссылка>'].

    Nesting is respected - a comma inside an inner argument does not split the outer list -
    and a type with no arguments answers with an empty list.
    """
    start = written.find("<")
    if start < 0 or not written.rstrip().endswith(">"):
        return []
    inner = written[start + 1: written.rstrip().rindex(">")]
    args, depth, current = [], 0, ""
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(current.strip())
            current = ""
            continue
        current += ch
    if current.strip():
        args.append(current.strip())
    return [a for a in args if a]


def method_type_params(owner: str, member: str) -> list[str]:
    """The type parameters a METHOD of `owner` declares itself, or an empty list."""
    by_type = load_json("stdlib.json").get("member_type_params") or {}
    return list((by_type.get(owner) or {}).get(member) or ())


def substitute_params(result: str, owner_head: str, owner_written: str | None) -> str:
    """A member result spelled with the owner's TYPE PARAMETERS, resolved by its arguments.

    A generic type names the result of its members by the parameter (`Array.First():
    ItemType`), so the answer means nothing until the arguments the code wrote are put in:
    a value of `Array<Catalog.Card>` answers `Catalog.Card`. Without the arguments,
    or without a parameter list for the owner, the result is returned as it stands.
    """
    if not owner_written or not result:
        return result
    params = (load_json("stdlib.json").get("type_params") or {}).get(owner_head) or []
    args = generic_args(owner_written)
    if not params or not args:
        return result
    replacements = dict(zip(params, args))
    head = member_type_head(result)
    if head in replacements:
        # `ТипЭлемента?` keeps the nullable marker of the member, and the argument replaces
        # only the name itself.
        return result.replace(head, replacements[head], 1)
    return result


#: Where a result type spelled for a TEMPLATE leaves the object's own name: the docs write
#: `Получить(): {ИмяНабораКонстант}.Запись`, the data stores `{}.Запись`, and a consumer puts
#: the name of the concrete object in. Replaced textually, not through `str.format` - the
#: spelling comes from a page and may carry braces of its own.
PLACEHOLDER = "{}"


def manager_member_names(entry) -> list[str]:
    """Every member name of one manager_members entry, whichever shape the data has.

    The section keeps a kind's properties and methods apart ({"properties": [...],
    "methods": [...]}), like type_members; data generated before the split is a plain list of
    names. A caller that only needs "is this name a member of the kind" reads through here.
    """
    if isinstance(entry, dict):
        return [str(name) for kind in MEMBER_KINDS for name in entry.get(kind) or ()]
    return [str(name) for name in entry or ()]


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
