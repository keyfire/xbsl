"""The guard over the tables that claim platform names exist without data to back them.

Such a table is an assertion with nothing behind it: the data is silent about it by
construction, and a test written for it repeats the very same assertion. That is how two
names the platform does not have lived in the whitelist of `code/undefined-name`.

Only the compiler can confirm them - `tools/verify_claims.py` does that (it needs a stand,
hence not a test). What CAN be checked offline, on every run, is here:

- every claimed name has a recipe, so a table cannot grow silently;
- a name the shipped data already carries is redundant in a table: an exception that outlives
  its reason is silence on the rule's part for no reason at all.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from xbsl import dataset
from xbsl.rules.undefined_names import _ENTITY_COMMON, _IMPLICIT, _UNDOCUMENTED
from xbsl.rules.unknown_members import _COMMON_MEMBERS

ROOT = Path(__file__).resolve().parent.parent


def _tool():
    """The verification tool is a script rather than part of the package - loaded by path.

    It is registered in sys.modules before execution: it declares a dataclass, and a
    dataclass looks its own module up by name while resolving annotations.
    """
    spec = importlib.util.spec_from_file_location(
        "verify_claims", ROOT / "tools" / "verify_claims.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_TOOL = _tool()
RECIPES = _TOOL.RECIPES
TABLES = _TOOL.TABLES


def test_every_claimed_name_has_a_recipe():
    """A name with no recipe cannot be proven - so it must not be added."""
    missing = sorted(
        f"{table}.{name}"
        for table, names in TABLES.items()
        for name in names
        if (table, name) not in RECIPES
    )
    assert missing == [], (
        "no recipe for: " + ", ".join(missing)
        + " - describe one in tools/verify_claims.py::RECIPES"
    )


def test_the_registry_covers_the_tables_of_the_rules():
    """The registry looks at THE tables of the rules, not at a copy of its own."""
    assert TABLES["_IMPLICIT"] is _IMPLICIT
    assert TABLES["_UNDOCUMENTED"] is _UNDOCUMENTED
    assert TABLES["_ENTITY_COMMON"] is _ENTITY_COMMON
    assert TABLES["_COMMON_MEMBERS"] is _COMMON_MEMBERS


def test_no_recipe_is_left_for_a_name_that_left_the_tables():
    """A recipe without a claim is the trace of a deleted one; such litter piles up unseen."""
    known = {(table, name) for table, names in TABLES.items() for name in names}
    stale = sorted(f"{table}.{name}" for table, name in RECIPES if (table, name) not in known)
    assert stale == [], "a recipe left without its claim: " + ", ".join(stale)


@pytest.mark.needs_data
def test_a_claimed_name_is_not_already_in_the_data():
    """A claim for a name the data already carries is a redundant exception.

    Only the global names (`_UNDOCUMENTED`) are judged: the names of module contexts
    (`_IMPLICIT`, `_ENTITY_COMMON`) are not in the type catalogue and never should be, and
    the members of the object protocol (`_COMMON_MEMBERS`) are declared per type.
    """
    catalog = dataset.load_json("stdlib.json")
    globals_ = set(catalog.get("globals") or ())
    types = set(catalog.get("type_members") or ())
    redundant = sorted(name for name in _UNDOCUMENTED if name in globals_ or name in types)
    assert redundant == [], (
        "the name is already in the data, the exception is redundant: " + ", ".join(redundant)
    )
