"""Project resource namespaces and the platform's priority-based link resolution."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from xbsl import dataset, terms
from xbsl.layout import Layout, PROJECT_FILES, Place, service_dirs
from xbsl.restext import RESOURCE_DIRS


@lru_cache(maxsize=1)
def _visibility_keys() -> tuple[str, ...]:
    """Both platform spellings of the resources descriptor's visibility key."""
    return terms.key_forms("ОбластьВидимости")


@lru_cache(maxsize=1)
def _public_scopes() -> frozenset[str]:
    """Visibility values that publish resources outside their subsystem."""
    return frozenset(terms.key_forms("ВПроекте", "Глобально"))


@lru_cache(maxsize=1)
def _private_scopes() -> frozenset[str]:
    """Visibility values that keep resources inside their subsystem."""
    return frozenset(terms.key_forms("ВПодсистеме"))


dataset.register_reset(_visibility_keys.cache_clear)
dataset.register_reset(_public_scopes.cache_clear)
dataset.register_reset(_private_scopes.cache_clear)


def _find(root: Path, name: str) -> list[Path]:
    """Paths named `name` below root, excluding hidden service trees."""
    return sorted(
        path for path in root.rglob(name)
        if not any(part.startswith(".") for part in path.relative_to(root).parts)
    )


def _version(value: object) -> tuple[int, ...] | None:
    if not isinstance(value, (str, int, float)):
        return None
    parts = str(value).split(".")
    return tuple(int(part) for part in parts) if parts and all(part.isdigit() for part in parts) else None


def project_compatibility(project_dir: Path | None) -> tuple[int, ...] | None:
    """Compatibility mode declared by a project, or None when it is not known."""
    if project_dir is None:
        return None
    for name in PROJECT_FILES:
        descriptor = project_dir / name
        if not descriptor.is_file():
            continue
        try:
            data = yaml.safe_load(descriptor.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return None
        if not isinstance(data, dict):
            return None
        for key in terms.key_forms("РежимСовместимости"):
            version = _version(data.get(key))
            if version is not None:
                return version
        return None
    return None


def resource_folder_visibility(
        directory: Path, compatibility: tuple[int, ...] | None,
) -> bool | None:
    """Public, private or unknown visibility of one resources namespace."""
    for name in RESOURCE_DIRS:
        descriptor = directory / f"{name}.yaml"
        if not descriptor.is_file():
            continue
        try:
            data = yaml.safe_load(descriptor.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, yaml.YAMLError):
            return None
        if not isinstance(data, dict):
            return None
        scope = next((data.get(key) for key in _visibility_keys()
                      if isinstance(data.get(key), str)), None)
        if scope in _public_scopes():
            return True
        if scope in _private_scopes():
            return False
        return None
    if compatibility is None:
        return None
    return compatibility < (8, 0)


def resource_keys(directory: Path) -> frozenset[str]:
    """Resource keys below one folder, excluding the folder descriptor itself."""
    return frozenset(
        path.relative_to(directory).as_posix()
        for path in _find(directory, "*")
        if path.is_file()
        and not (path.parent == directory and path.suffix == ".yaml"
                 and path.stem in RESOURCE_DIRS)
    )


@dataclass(frozen=True)
class ResourceScope:
    """One resources folder and the namespace facts needed to resolve its keys."""

    directory: Path
    place: Place
    keys: frozenset[str]
    public: bool | None


def resource_scopes(root: Path, layout: Layout) -> tuple[ResourceScope, ...]:
    """Every top-level resources folder under root with its owner, keys and visibility."""
    found: list[ResourceScope] = []
    for name in RESOURCE_DIRS:
        for directory in _find(root, name):
            if not directory.is_dir():
                continue
            place = layout.place(directory / "_")
            if place is None:
                continue
            try:
                parts = directory.relative_to(place.subsystem_dir).parts
            except ValueError:
                continue
            first = next((index for index, part in enumerate(parts)
                          if part in service_dirs()), None)
            if first != len(parts) - 1:
                continue
            compatibility = project_compatibility(place.project_dir)
            found.append(ResourceScope(
                directory, place, resource_keys(directory),
                resource_folder_visibility(directory, compatibility),
            ))
    return tuple(sorted(found, key=lambda scope: str(scope.directory)))


@dataclass(frozen=True)
class ResourceCandidate:
    """A namespace holding one requested key; token identifies it to the caller."""

    namespace: str
    local: bool
    public: bool | None
    token: str


@dataclass(frozen=True)
class ResourceResolution:
    """A resource link verdict and the candidates at the winning namespace priority."""

    kind: str
    candidates: tuple[ResourceCandidate, ...] = ()


def resolve_resource(
        candidates: Iterable[ResourceCandidate], imported: Iterable[str],
        qualifier: str | None = None,
) -> ResourceResolution:
    """Resolve candidates by the runtime order: local subsystem, then imported namespaces.

    All packages of the current subsystem have the same priority. A qualified link already
    selects its namespace. Ambiguity is decided by namespace before visibility, matching the
    runtime resolver.
    """
    candidates = tuple(candidates)
    imports = frozenset(imported)
    if qualifier is not None:
        selected = tuple(candidate for candidate in candidates
                         if candidate.namespace == qualifier)
    else:
        local = tuple(candidate for candidate in candidates if candidate.local)
        selected = local or tuple(candidate for candidate in candidates
                                  if candidate.namespace in imports)
    if not selected:
        return ResourceResolution("unknown")
    namespaces = {candidate.namespace for candidate in selected}
    if len(namespaces) > 1:
        return ResourceResolution("ambiguous", selected)
    namespace = next(iter(namespaces))
    if not selected[0].local:
        values = {candidate.public for candidate in selected}
        public = True if True in values else False if values == {False} else None
        if public is False:
            return ResourceResolution("hidden", selected)
        if public is None:
            return ResourceResolution("unproven", selected)
    return ResourceResolution("resolved", selected)
