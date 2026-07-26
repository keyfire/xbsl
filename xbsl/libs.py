"""Types the libraries a project depends on make visible to it.

A project declares its dependencies in `Проект.yaml` by coordinates only - vendor, name and
version:

    Библиотеки:
        -
            Версия: 2.0.1
            Имя: CurrencyConverter
            Поставщик: acme

The types themselves live in the library archive, which the platform names
`{Поставщик}-{Имя}-{Версия}.xlib` and ships next to the sources. The archive is a zip of the
library's own sources: every element yaml carries ВидЭлемента and Имя, and only an element
with `ОбластьВидимости: Глобально` is visible to the depending project - the rest belongs to
the library's own subsystems. So without the archive a project's type checks cannot tell a
library type from a typo; with it, the global names simply join the known set.

The archive is read lazily and cached by (path, mtime, size): a project has few dependencies
and one project descriptor, so the whole cost is one zip read per process.
"""

from __future__ import annotations

import re
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from xbsl import terms

try:
    import yaml

    _HAVE_YAML = True
except ImportError:  # pragma: no cover - the parser is an install dependency
    _HAVE_YAML = False

_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader) if _HAVE_YAML else None

# The keys are bilingual, as everywhere in Element yaml: shipped sources carry English
# spellings too. A project descriptor is recognized by its dependency block, not by the file
# name, so a renamed or English-named descriptor is picked up just the same.
#: Spellings come from the platform's own term pairs (terms.py), not from guesses - a
#: hand-written "VisibilityArea" used to sit here and matched nothing.
_LIB_BLOCK_RE = re.compile(r"^(?:Библиотеки|Libraries)\s*:", re.M)
_PROJECT_KEY_RE = re.compile(r"^(?:Поставщик|Vendor)\s*:", re.M)
_VENDOR_KEYS = terms.key_forms("Поставщик", extra=("Vendor",))
_NAME_KEYS = terms.key_forms("Имя")
_VERSION_KEYS = terms.key_forms("Версия")
_KIND_KEYS = terms.key_forms("ВидЭлемента")
_SCOPE_KEYS = terms.key_forms("ОбластьВидимости")

# The scope written when an element is visible outside its library; anything else (the
# default is ВПодсистеме) stays internal to the library.
_GLOBAL_SCOPE = "Глобально"
# Descriptors rather than elements: a subsystem file may sit at an element's depth.
_NON_ELEMENT_FILES = frozenset({"Подсистема.yaml", "Subsystem.yaml"})
# How far above the descriptor to look for the archive. The sources sit a couple of levels
# deep inside the checkout (`<корень>/<поставщик>/<проект>/Проект.yaml`) while the archive
# lies next to them, at the checkout root.
_SEARCH_LEVELS = 4


def _first(values: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def declared_libraries(text: str) -> list[tuple[str, str, str]]:
    """(vendor, name, version) of every library the project descriptor declares."""
    if not _HAVE_YAML or not _LIB_BLOCK_RE.search(text):
        return []
    try:
        data = yaml.load(text, Loader=_LOADER)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict):
        return []
    block = data.get("Библиотеки") or data.get("Libraries")
    if not isinstance(block, list):
        return []
    out = []
    for item in block:
        if not isinstance(item, dict):
            continue
        vendor = _first(item, _VENDOR_KEYS)
        name = _first(item, _NAME_KEYS)
        version = _first(item, _VERSION_KEYS)
        if vendor and name and version:
            out.append((vendor, name, version))
    return out


def project_coordinates(text: str) -> Optional[tuple[str, str]]:
    """(vendor, name) of a project descriptor, or None when the yaml is not one.

    The descriptor is the yaml that names the project itself: it carries Поставщик and Имя and,
    unlike every element of the project, no ВидЭлемента. The pair is what a qualified name
    starts with (`{Поставщик}::{Имя}::Подсистема::Тип`), so it tells one's own types from a
    library's.
    """
    if not _HAVE_YAML or not _PROJECT_KEY_RE.search(text):
        return None
    try:
        data = yaml.load(text, Loader=_LOADER)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or _first(data, _KIND_KEYS):
        return None
    vendor, name = _first(data, _VENDOR_KEYS), _first(data, _NAME_KEYS)
    return (vendor, name) if vendor and name else None


def find_archive(start: Path, vendor: str, name: str, version: str) -> Optional[Path]:
    """The library archive next to the sources: the descriptor's own directory, then up."""
    filename = f"{vendor}-{name}-{version}.xlib"
    # A relative descriptor path would end the walk right away: Path(".").parent is ".".
    start = start.resolve()
    directory = start if start.is_dir() else start.parent
    for _ in range(_SEARCH_LEVELS + 1):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
        if directory.parent == directory:
            break
        directory = directory.parent
    return None


@lru_cache(maxsize=32)
def _global_types_cached(path: str, mtime: float, size: int) -> frozenset[str]:
    if not _HAVE_YAML:
        return frozenset()
    names: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for entry in archive.namelist():
                if not entry.endswith(".yaml") or entry.count("/") < 3:
                    continue  # the manifest and the descriptor are not elements
                if entry.rsplit("/", 1)[-1] in _NON_ELEMENT_FILES:
                    continue  # a subsystem describes a namespace, it is not a type
                try:
                    values = yaml.load(archive.read(entry).decode("utf-8-sig"), Loader=_LOADER)
                except (yaml.YAMLError, UnicodeDecodeError):
                    continue
                if not isinstance(values, dict) or not _first(values, _KIND_KEYS):
                    continue
                if _first(values, _SCOPE_KEYS) != _GLOBAL_SCOPE:
                    continue
                element = _first(values, _NAME_KEYS) or entry.rsplit("/", 1)[-1][: -len(".yaml")]
                names.add(element)
    except (zipfile.BadZipFile, OSError):
        return frozenset()
    return frozenset(names)


def archive_global_types(path: Path) -> frozenset[str]:
    """Names of the archive's elements visible to a depending project, or an empty set."""
    try:
        stat = path.stat()
    except OSError:
        return frozenset()
    return _global_types_cached(str(path), stat.st_mtime, stat.st_size)


def project_library_types(descriptor: Path, text: str) -> list[str]:
    """Global type names of every library the descriptor declares and whose archive is found.

    An archive that is not next to the sources yields nothing: the check then behaves exactly
    as it did before libraries were understood at all, rather than guessing at the names.
    """
    names: set[str] = set()
    for vendor, name, version in declared_libraries(text):
        archive = find_archive(descriptor, vendor, name, version)
        if archive is not None:
            names |= archive_global_types(archive)
    return sorted(names)
