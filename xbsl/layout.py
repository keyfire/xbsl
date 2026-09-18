"""The placement model of a project: subsystems, packages and namespaces read off the layout.

The platform ("Модульная разработка", "Устройство проекта") splits a project into subsystems
and packages, and every element takes its namespace from where it lies:
`Поставщик::Проект::Подсистема[::Пакет[::Вложенный]]`. The names are read off the folders:

- the project root is the folder holding `Проект.yaml` (`Project.yaml`);
- a subsystem is a first-level folder of the project root. Its descriptor `Подсистема.yaml`
  is OPTIONAL (a shipped library keeps a subsystem with no descriptor at all); the name is
  the descriptor's `Name` when there is one, otherwise the folder name;
- a package is every folder between the subsystem folder and the element file, nested ones
  included; a package has no descriptor of its own, so its name is the folder name. The
  service folders - resources and localization, in either spelling - are not packages, and
  they end the chain;
- a file lying directly in the project root belongs to no subsystem (the project module).

Without a project descriptor in the run (the fixtures of the tests, a fragment of a project)
the model falls back to the descriptors alone: the nearest ancestor holding a
`Подсистема.yaml` is the subsystem root, and the folders below it are packages.

The distinction the model exists for: within one subsystem the root and the packages see
each other without an import (proven on a server build, 13.09.2026), but ACROSS subsystems an
element of a package is imported by the package's own namespace - `импорт Б::П` - and an
import of the subsystem alone (`импорт Б`) does not bring it: the compiler refuses the
reference with `Пространство имен "...::Б::П" не импортировано`. So the placement of an
element is keyed by `Subsystem` or `Subsystem::Package`, never by the subsystem alone.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, terms
from xbsl.restext import RESOURCE_DIRS

#: Both spellings: the platform accepts the English service file names too.
PROJECT_FILES = ("Проект.yaml", "Project.yaml")
SUBSYSTEM_FILES = ("Подсистема.yaml", "Subsystem.yaml")

#: The Russian names of the service folders that are not packages.
_SERVICE_DIRS_RU = ("Ресурсы", "Локализация")


@lru_cache(maxsize=1)
def service_dirs() -> frozenset[str]:
    """The folders that are not packages: resources and localization, both spellings.

    The English spellings come from the compiler dictionary of the distribution. Without the
    data the resources pair the engine already carries (probed on a server) still stands, so
    a clean public clone keeps an English project's resources out of the package chain; the
    localization folder holds translation files with no element kind, so an unpaired
    spelling there places nothing.
    """
    names = {*_SERVICE_DIRS_RU, *RESOURCE_DIRS}
    for russian in _SERVICE_DIRS_RU:
        english = terms.common_english(russian)
        if english:
            names.add(english)
    return frozenset(names)


dataset.register_reset(service_dirs.cache_clear)


@lru_cache(maxsize=1)
def vendor_keys() -> tuple[str, ...]:
    """Both spellings of the vendor key of a project descriptor, Russian first.

    `Vendor` is added the way the library manifest reader adds it (`libs._VENDOR_KEYS`): no
    metamodel record pairs it, and without it an English project would lose its vendor.
    """
    return terms.key_forms("Поставщик", extra=("Vendor",))


@lru_cache(maxsize=1)
def name_keys() -> tuple[str, ...]:
    """Both spellings of the name key of a descriptor, Russian first."""
    return terms.key_forms("Имя")


dataset.register_reset(vendor_keys.cache_clear)
dataset.register_reset(name_keys.cache_clear)


def first_text(data: Mapping[str, object], keys: Iterable[str]) -> str | None:
    """The first non-empty string value under any of the keys of a parsed descriptor."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def package_of(folders: Sequence[str]) -> str | None:
    """The package path (`П` or `П1::П2`) the folders under a subsystem spell, or None.

    A service folder ends the chain: a file under `П/Ресурсы/...` still belongs to package `П`.
    """
    parts: list[str] = []
    for folder in folders:
        if folder in service_dirs():
            break
        parts.append(folder)
    return "::".join(parts) or None


def subsystem_of_key(key: str) -> str:
    """The subsystem part of a placement key (`Б::П` -> `Б`)."""
    return key.split("::", 1)[0]


@dataclass(frozen=True)
class Place:
    """Where an element lies: its subsystem, its package (None at the subsystem root), the
    project root the placement was read from (None when the model fell back to descriptors)
    and the folder of the subsystem - a package folder is that folder plus the package path."""

    subsystem: str
    package: str | None
    project_dir: Path | None
    subsystem_dir: Path

    @property
    def key(self) -> str:
        """The placement key - the namespace the element is imported by, project prefix off."""
        return self.subsystem if self.package is None else f"{self.subsystem}::{self.package}"


class Layout:
    """The placement model of one run: the project roots with their identity (vendor, name)
    and the subsystem folders that carry a descriptor with the name it declares."""

    def __init__(
        self,
        projects: Mapping[Path, tuple[str, str]] | None = None,
        subsystem_names: Mapping[Path, str] | None = None,
    ) -> None:
        self.projects: dict[Path, tuple[str, str]] = dict(projects or {})
        self.subsystem_names: dict[Path, str] = dict(subsystem_names or {})

    @property
    def known(self) -> bool:
        """Whether the run holds any descriptor at all - without one the layout is unknown."""
        return bool(self.projects or self.subsystem_names)

    def project_dir_of(self, path: Path) -> Path | None:
        """The nearest project root above the path, or None."""
        for parent in path.parents:
            if parent in self.projects:
                return parent
        return None

    def identity(self, project_dir: Path | None) -> tuple[str, str] | None:
        """(vendor, name) of a project root, or None for a placement without one."""
        return self.projects.get(project_dir) if project_dir is not None else None

    def place(self, path: Path) -> Place | None:
        """The placement of a source path, or None for a file outside every subsystem."""
        project_dir = self.project_dir_of(path)
        if project_dir is not None:
            rel = path.parts[len(project_dir.parts):]
            if len(rel) < 2 or rel[0] in service_dirs():
                return None
            folder = project_dir / rel[0]
            name = self.subsystem_names.get(folder, rel[0])
            return Place(name, package_of(rel[1:-1]), project_dir, folder)
        for parent in path.parents:
            if parent in self.subsystem_names:
                rel = path.parts[len(parent.parts):]
                return Place(self.subsystem_names[parent], package_of(rel[:-1]), None, parent)
        return None

    def local_name(self, namespace: str, project_dir: Path | None) -> str:
        """A namespace as written in an import, the project's own `Поставщик::Проект::` off.

        `импорт Поставщик::Проект::Б::П` and `импорт Б::П` name one package of this project;
        a prefix of another project or a library is left as it is - it names nothing here.
        """
        identity = self.identity(project_dir)
        if identity is not None:
            prefix = f"{identity[0]}::{identity[1]}::"
            if namespace.startswith(prefix):
                return namespace[len(prefix):]
        return namespace

    def resolve(
        self, qualifiers: Sequence[str], project_dir: Path | None, keys: Iterable[str],
    ) -> str | None:
        """The placement key among `keys` that the qualifiers of a qualified name designate.

        With the project known the qualifiers are taken as written, the own prefix off: a
        chain of another project or of a library names nothing here. Without a project the
        longest suffix that is a key stands - `Поставщик::Проект::Б::П` and `Б::П` are one
        package, and the descriptors alone cannot tell the prefix.
        """
        keys = set(keys)
        if self.identity(project_dir) is not None:
            key = self.local_name("::".join(qualifiers), project_dir)
            return key if key in keys else None
        for start in range(len(qualifiers)):
            key = "::".join(qualifiers[start:])
            if key in keys:
                return key
        return None
