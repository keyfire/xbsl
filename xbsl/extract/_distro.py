"""Shared helpers for the extractors: .car lookup, version detection, index of data versions.

The extractors (extract_grammar.py, extract_stdlib.py) detect the Element version from the
distribution themselves and put the derived data under <root>/<version>/, updating the index.
The linter itself works off that data and does not need the distribution at runtime.

The default root is xbsl/data/element of this clone. Whoever keeps the data separately
(cannot publish it) points the output to a directory of their own: --data-dir or the env
XBSL_DATA_DIR - the same variable the linter later reads that data by.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_ENV_DATA_DIR = "XBSL_DATA_DIR"
_VER_RE = re.compile(r"-(\d+\.\d+\.\d+(?:\+\d+)?)-")
#: The build number of the server .car ('...-<timestamp>+<build>-...'); the version the
#: data is filed under does not carry it - see record_build.
_BUILD_RE = re.compile(r"\+(\d+)")
_root_override: Path | None = None


def find_car(dist: Path) -> Path:
    cars = sorted(dist.glob("*element-server-with-ide-*.car"))
    if not cars:
        raise SystemExit(f"В дистрибутиве {dist} не найден .car сервера с IDE")
    return cars[0]


def detect_version(dist: Path, override: str | None = None) -> str:
    """The Element version: from --element-version or from the .car name (e.g. 1.2.3+4)."""
    if override:
        return override
    car = find_car(dist)
    m = _VER_RE.search(car.name)
    if not m:
        raise SystemExit(
            f"Не удалось определить версию из '{car.name}'; задайте --element-version явно"
        )
    return m.group(1)


def native_version(dist: Path) -> str:
    """The version the distribution itself carries, or '' when its name does not say.

    detect_version answers what the data will be FILED under and honours the override;
    this one answers what the distribution is, and never raises: the caller asks it only
    to tell an override apart from the real thing.
    """
    try:
        car = find_car(dist)
    except SystemExit:
        return ""
    m = _VER_RE.search(car.name)
    return m.group(1) if m else ""


def detect_build(dist: Path) -> str:
    """The build number from the server .car name ('' when the name carries none).

    detect_version answers the PRODUCT version ('1.2.3'): in the .car name the build
    number sits after the timestamp ('...-1.2.3-20260731.125205+243-...'), so the
    version regex never captures it. A version override with a '+' already names a
    build - the .car is not consulted then.
    """
    m = _BUILD_RE.search(find_car(dist).name)
    return m.group(1) if m else ""


def prog_name(command: str) -> str | None:
    """The name for a usage line, or None to keep argparse's own answer.

    argparse names the program after `sys.argv[0]`, and for an installed console script that is
    the script path with the interpreter in front of it (`python.exe C:\\...\\Scripts\\xbsl`) -
    not a command anyone can retype. Name the documented command instead.

    Only when the process did NOT start from a file: a tools/extract_*.py shim and
    `python -m xbsl.extract.<step>` both leave the real command line in argv[0], and argparse
    prints those correctly - overriding them would replace what the user typed with a synonym.
    """
    return None if Path(sys.argv[0] or "").suffix.lower() == ".py" else command


def add_data_dir_arg(ap) -> None:
    """The extractors' shared option: where to put the data and the index."""
    ap.add_argument(
        "--data-dir",
        help=f"корень данных (по умолчанию xbsl/data/element клона; также env {_ENV_DATA_DIR})",
    )


def set_data_root(path: str | os.PathLike[str] | None) -> None:
    global _root_override
    _root_override = Path(path) if path else None


def data_root() -> Path:
    if _root_override is not None:
        return _root_override
    env = os.environ.get(_ENV_DATA_DIR)
    if env:
        return Path(env)
    # The package's own bundled root - the directory dataset.BUNDLED_DATA_ROOT names.
    # REPO above is the PACKAGE directory: the extractors once lived outside it, and an
    # extra "xbsl" segment survived the move - the default silently wrote to xbsl/xbsl/data
    # while every real run masked it with --data-dir or the environment variable.
    return REPO / "data" / "element"


def version_dir(version: str) -> Path:
    d = data_root() / version
    d.mkdir(parents=True, exist_ok=True)
    return d


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _read_index(idx: Path) -> dict:
    # utf-8-sig: индекс, переписанный PowerShell 5.1, несёт BOM; ошибка разбора обязана
    # называть файл - без имени она одинаково валила все шаги, читающие индекс.
    data = {"available": [], "default": None}
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8-sig"))
        except ValueError as error:
            raise SystemExit(f"Индекс версий не разбирается как JSON: {idx} ({error})") from error
    return data


def _write_index(idx: Path, data: dict) -> None:
    idx.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_index(version: str, make_default: bool = True) -> None:
    """Add the version to the index (data/element/index.json) and make it the default if needed.

    The default only moves forward: regenerating an OLD version (say, for a clean data diff)
    must not silently switch the linter back to it.
    """
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    idx = root / "index.json"
    data = _read_index(idx)
    if version not in data["available"]:
        data["available"].append(version)
        data["available"].sort()
    current = data.get("default")
    if not current or (make_default and _version_key(version) >= _version_key(current)):
        data["default"] = version
    _write_index(idx, data)


def record_build(version: str, build: str) -> None:
    """Remember which BUILD the version directory holds (the index 'builds' map).

    The directory is named by the product version, and the server names its .car
    '<product>-<timestamp>+<build>' - so two neighbouring builds of one release write
    into the SAME directory, and without this record nothing can tell them apart or
    name a snapshot of the previous one.
    """
    # A version whose NAME already carries the build needs no record of it: the entry
    # would say the directory of build 11 holds build 11, and a snapshot of it would be named
    # after itself.
    if not build or "+" in version:
        return
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    idx = root / "index.json"
    data = _read_index(idx)
    builds = data.setdefault("builds", {})
    builds[version] = build
    _write_index(idx, data)


def keep_previous(version: str, build: str) -> str:
    """Snapshot <root>/<version> as <version>+<previous build> before a regeneration.

    Returns a human line about what happened - the caller prints it. The snapshot is
    registered in the index 'available', so `xbsl data-diff <version>+<N> <version>`
    works right away; without a recorded build number there is nothing to name the
    snapshot by, and that is said instead of guessing.
    """
    root = data_root()
    current = root / version
    if not current.is_dir():
        return "прежних данных нет - снимок не нужен"
    idx = root / "index.json"
    data = _read_index(idx)
    previous = str((data.get("builds") or {}).get(version, ""))
    if not previous:
        return ("прежний каталог не несёт номера сборки - снимок не назван и не сделан; "
                "номер записывается начиная с этого прогона")
    if build and previous == build:
        return f"в каталоге уже сборка +{previous} - снимок не нужен"
    snapshot = f"{version}+{previous}"
    target = root / snapshot
    if target.exists():
        return f"снимок {snapshot} уже есть - не перезаписываю"
    shutil.copytree(current, target)
    if snapshot not in data["available"]:
        data["available"].append(snapshot)
        data["available"].sort()
    _write_index(idx, data)
    return f"прежняя сборка сохранена как {snapshot}"
