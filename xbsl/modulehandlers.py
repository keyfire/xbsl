"""The handlers a module of an interface component overrides by name.

A component module may declare a method the platform itself calls: `AfterCreate` of every
component, `BeforeClose` of a form, `BeforeWrite` of an object form. Such a method is an
override - it carries the `@Handler` annotation, and its name is the platform's word, not the
project's: the compiler finds it by that name, in either spelling. A method under the same
annotation that overrides nothing is refused ("A handler associated with method X is not
found"), and a translated project has to spell the override the way the platform does.

The list comes from the distribution: each component description it ships names the
handlers of a module built on that component (`moduleHandlers`), both spellings included, and
the stdlib extractor keeps them in the `module_handlers` section of stdlib.json - each type
with its OWN handlers. A component inherits the handlers of its bases, so the lookup walks
`bases`, the way the member sets are expanded. A handler may be there in some compatibility
modes only - the description says which (see `declared_in`).

Only interface components are covered: the handlers of the other modules (an object module,
the module of a register, of a scheduled job) are declared by the compiler in code, not in a
description, and nothing here speaks for them. Without the section - a public checkout, or data
extracted before it existed - every answer is empty, and a caller judges nothing.
"""

from __future__ import annotations

from functools import lru_cache

from xbsl import dataset

#: The section of stdlib.json this module reads.
SECTION = "module_handlers"


def _catalog() -> dict:
    return dataset.load_optional("stdlib.json") or {}


@lru_cache(maxsize=1)
def _table() -> dict[str, tuple[dict, ...]]:
    """{type: its own handler rows} - both spellings of the type as keys, see dataset."""
    section = _catalog().get(SECTION)
    if not isinstance(section, dict):
        return {}
    return {
        str(owner): tuple(row for row in rows if isinstance(row, dict)
                          and isinstance(row.get("ru"), str) and isinstance(row.get("en"), str))
        for owner, rows in section.items() if isinstance(rows, list)
    }


def available() -> bool:
    """Whether the data carries the handler lists at all."""
    return bool(_table())


@lru_cache(maxsize=None)
def rows_of(type_name: str) -> tuple[dict, ...]:
    """The handler rows of a module built on `type_name`: its own and its bases', nearest first.

    Empty when the type is unknown to the catalog or the data carries no lists. A row is
    {"ru", "en"} plus the compatibility modes (`from`, `to`) where the description states them;
    which modes those admit is `declared_in`'s call.
    """
    table = _table()
    if not table:
        return ()
    bases = _catalog().get("bases") or {}
    if type_name not in table and type_name not in bases:
        return ()
    ancestors = bases.get(type_name) or ()
    owners = [type_name, *reversed(dataset.nearest_last(ancestors, bases))]
    rows: list[dict] = []
    seen: set[str] = set()
    for owner in owners:
        for row in table.get(owner, ()):
            if row["ru"] not in seen:
                seen.add(row["ru"])
                rows.append(row)
    return tuple(rows)


def declared_in(row: dict, mode: tuple[int, ...] | None) -> bool:
    """Whether a module declares the handler of `row` in compatibility mode `mode`.

    A description limits a handler to some modes by `from` and `to`, and the range is half-open:
    `from` is the first mode the handler is there in, `to` the first mode it is gone from. The
    compiler says so itself. The web chat handler of a client application, `to: 8.0` in the
    description, is declared by the handler provider of the compiler only while the mode is
    below 8.0 (`G5CompatibilityMode.lt(CMODE_8_0)`), under a term named for that range
    (`_00_80`); the web chat property of the newer modes is declared from 8.0 on, the mode
    itself included (`ge(CMODE_8_0)`, a term named `_80_00`). The descriptions of the components
    read the same way against the help: `to: 8.0` of the groups the help marks
    `Версия 7.0 и ниже`, and the `from` of a component is the mode its page marks "and above".

    An unknown mode (None) declares every row: which of them the project has cannot be told,
    and a row taken away on a guess would report an override the compiler accepts.
    """
    if mode is None:
        return True
    # The reader of a dotted version the rules share; imported here, since the rules import
    # this module.
    from xbsl.rules.component_since import _version

    first, last = _version(row.get("from")), _version(row.get("to"))
    return (first is None or first <= mode) and (last is None or mode < last)


@lru_cache(maxsize=1)
def all_names() -> frozenset[str]:
    """Both spellings of every handler a module of any component may override."""
    return frozenset(
        name for rows in _table().values() for row in rows for name in (row["ru"], row["en"])
    )


def base_head(written: str) -> str:
    """The name a base is looked up by: `ObjectForm<Tasks.Object>` -> `ObjectForm`.

    The generic arguments and the package (`Std::Interface::Forms::Form`) are dropped - the
    catalog keys a type by its head, and so does a project its components.
    """
    return written.split("<", 1)[0].strip().rpartition("::")[2].strip()


def platform_base(head: str, project_base, limit: int = 32) -> str:
    """The platform type a component module finally builds on, or "" when that cannot be told.

    `head` is the base the component's yaml names (`Наследует.Тип`, generic arguments and
    package already dropped). `project_base(name)` answers the base head of a component the
    PROJECT declares under that name, "" for a name the project has as something else, and
    None when the project has no element of that name: a component may build on another
    component of the project, and only the end of that chain is the platform's. A chain that
    loops, runs too deep or ends in a name neither side knows gives "".
    """
    seen: set[str] = set()
    while head and head not in seen and len(seen) < limit:
        seen.add(head)
        found = project_base(head)
        if found is None:
            return head if rows_of(head) else ""
        head = found
    return ""


def _reset() -> None:
    _table.cache_clear()
    rows_of.cache_clear()
    all_names.cache_clear()


dataset.register_reset(_reset)
# Answers read while the data was missing are empty; the recheck drops them with the rest.
dataset.register_recheck(_reset)
