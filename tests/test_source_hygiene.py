"""Repository hygiene: a module must not define the same top-level name twice.

The second `def` of a name silently replaces the first, and nothing in the pipeline says a
word: the linter's own unused-method rule reads XBSL sources, not the Python of the engine,
and a test helper that is never called fails no assertion. That is how `_rule_findings` came
to stand twice in tests/test_translate.py - two identical copies, the first of them dead from
the day it was written.

The guard walks the whole checkout (the engine, the tools, the scripts and the tests) and
holds every module to one definition per name. `@overload` declarations are the deliberate
exception - there the repeated name is the typing protocol itself; definitions nested in an
`if` or a `try` are not top-level statements and are never compared, so a platform-conditional
fallback stays legal.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The checkout the repository owns. `build/` holds a copy of the package made by a wheel build
# and `node_modules/` the documentation site's dependencies - neither is ours to judge.
AREAS = ("xbsl", "tools", "scripts", "tests")


def _sources() -> list[Path]:
    files: list[Path] = []
    for area in AREAS:
        for path in sorted((ROOT / area).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _shadowed(source: str, filename: str = "<module>") -> list[str]:
    """Top-level names the module defines more than once, in the order they appear."""
    tree = ast.parse(source, filename=filename)
    counts: Counter[str] = Counter()
    order: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if any("overload" in ast.unparse(dec) for dec in node.decorator_list):
            continue
        if counts[node.name] == 1:
            order.append(node.name)
        counts[node.name] += 1
    return order


def test_no_top_level_definition_is_shadowed():
    files = _sources()
    assert len(files) > 100, "обход не нашёл исходников - проверять было нечего"
    shadowed = []
    for path in files:
        # utf-8-sig: xbsl/__init__.py carries a BOM, and a plain utf-8 read of it is a SyntaxError.
        names = _shadowed(path.read_text(encoding="utf-8-sig"), str(path))
        shadowed += [f"{path.relative_to(ROOT).as_posix()}: {name}" for name in names]
    assert shadowed == [], "имя объявлено дважды, первое объявление мертво: " + ", ".join(shadowed)


def test_the_guard_sees_a_shadowed_name():
    """Control: without this the check would pass because it compares nothing."""
    assert _shadowed("def f():\n    pass\n\n\ndef f():\n    pass\n") == ["f"]
    assert _shadowed("def f():\n    pass\n\n\ndef g():\n    pass\n") == []


def test_an_overload_declaration_is_not_a_second_definition():
    source = (
        "from typing import overload\n\n\n"
        "@overload\n"
        "def f(x: int) -> int: ...\n\n\n"
        "@overload\n"
        "def f(x: str) -> str: ...\n\n\n"
        "def f(x):\n    return x\n"
    )
    assert _shadowed(source) == []


def test_a_definition_inside_a_branch_is_not_compared():
    """A fallback under `try`/`if` is not a top-level statement - it defines the name once."""
    source = (
        "try:\n    from fast import f\n"
        "except ImportError:\n    def f():\n        pass\n"
    )
    assert _shadowed(source) == []
