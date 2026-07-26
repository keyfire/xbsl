"""Compatibility: the package was renamed to `xbsl`, this name remains an alias.

Importing `xbsllint` (and any `xbsllint.X` submodule) returns THE SAME module object as
`xbsl` / `xbsl.X`: the finder below intercepts the `xbsllint*` names and hands out the
already imported modules of the new package. Shared objects are essential - a separate
module copy would run the rule registration again (@rule in xbsl.engine) and split the
registry in two. New code should import `xbsl`.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys

_PREFIX = "xbsllint"


class _AliasLoader(importlib.abc.Loader):
    """Returns the existing xbsl.* module instead of creating a new one."""

    def __init__(self, target: str) -> None:
        self._target = target

    def create_module(self, spec):  # noqa: ANN001 - the import protocol signature
        return importlib.import_module(self._target)

    def exec_module(self, module) -> None:  # noqa: ANN001 - the module is already executed
        pass


class _AliasFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001
        if fullname != _PREFIX and not fullname.startswith(_PREFIX + "."):
            return None
        if fullname.endswith(".__main__"):
            # runpy (python -m xbsllint) must get a regular spec with a source file: the
            # standard search finds xbsl/__main__.py via the aliased package's __path__.
            return None
        real = "xbsl" + fullname[len(_PREFIX):]
        return importlib.machinery.ModuleSpec(fullname, _AliasLoader(real))


if not any(isinstance(f, _AliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _AliasFinder())

# The alias package itself is also replaced with the real one: `import xbsllint;
# xbsllint.engine` works after `import xbsllint.engine`, and the attributes
# (__version__ etc.) come from xbsl.
_real = importlib.import_module("xbsl")
sys.modules[__name__] = _real
