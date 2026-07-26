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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_ENV_DATA_DIR = "XBSL_DATA_DIR"
_VER_RE = re.compile(r"-(\d+\.\d+\.\d+(?:\+\d+)?)-")
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
    return REPO / "xbsl" / "data" / "element"


def version_dir(version: str) -> Path:
    d = data_root() / version
    d.mkdir(parents=True, exist_ok=True)
    return d


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def update_index(version: str, make_default: bool = True) -> None:
    """Add the version to the index (data/element/index.json) and make it the default if needed.

    The default only moves forward: regenerating an OLD version (say, for a clean data diff)
    must not silently switch the linter back to it.
    """
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    idx = root / "index.json"
    data = {"available": [], "default": None}
    if idx.exists():
        data = json.loads(idx.read_text(encoding="utf-8"))
    if version not in data["available"]:
        data["available"].append(version)
        data["available"].sort()
    current = data.get("default")
    if not current or (make_default and _version_key(version) >= _version_key(current)):
        data["default"] = version
    idx.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
