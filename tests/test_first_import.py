"""Every module of the package imports first, in a process of its own.

Importing the engine loads the rule package, and rules take names from other modules of the
package at their own import. A module that imported the engine before it defined those names
failed as the first import of a process: `from xbsl import scaffold` stopped on
`latin_url_path`, and `import xbsl.resource_usage` on the analyzer a rule subclasses. Inside
the test suite nothing showed it - an earlier test had always imported the engine already -
so each module is imported here by a fresh interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: The exit code of a child whose module needs an optional extra the environment lacks (the
#: MCP server without `mcp`): the extra is the business of its own tests, not of the order.
_EXTRA_MISSING = 3

#: What the child runs: import one module and nothing before it.
_CHILD = f"""
import importlib, sys
try:
    importlib.import_module(sys.argv[1])
except SystemExit:
    sys.exit({_EXTRA_MISSING})
except ModuleNotFoundError as exc:
    if (exc.name or "").split(".")[0] in ("xbsl", "xbsllint"):
        raise
    sys.exit({_EXTRA_MISSING})
"""


def _import_first(statement_or_module: str, *, statement: bool = False) -> subprocess.CompletedProcess:
    """Run the import in a fresh interpreter from the checkout, without plugins.

    The working directory puts this checkout first on the path, so an editable install of
    another one is not what gets imported; a plugin may bring its own imports, and the
    published package has to import without any.
    """
    args = ["-c", statement_or_module] if statement else ["-c", _CHILD, statement_or_module]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "XBSL_NO_PLUGINS": "1"}
    return subprocess.run(
        [sys.executable, *args], cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=180, stdin=subprocess.DEVNULL,
    )


def test_scaffold_imports_first():
    """The case the defect was found by: the scaffolding imported before anything else."""
    done = _import_first("from xbsl import scaffold", statement=True)
    assert done.returncode == 0, done.stderr


def test_every_module_imports_first():
    names = sorted(
        f"xbsl.{path.stem}" for path in (ROOT / "xbsl").glob("*.py")
        if path.stem not in ("__init__", "__main__")
    )
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        results = dict(zip(names, pool.map(_import_first, names)))
    failed = {
        name: (done.stderr.strip().splitlines() or ["(no output)"])[-1]
        for name, done in results.items() if done.returncode not in (0, _EXTRA_MISSING)
    }
    assert not failed, "\n".join(f"{name}: {line}" for name, line in sorted(failed.items()))
