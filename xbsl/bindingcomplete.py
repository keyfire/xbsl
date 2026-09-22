"""Completion of component-reference binding expressions for the form designer.

In a form yaml a component property value may be a BINDING written as ``=<expr>`` -
for example ``=Компоненты.Кнопка.Значение``. The VS Code binding editor already
completes the bindings already used in the form, the owner-object attributes
(``=Объект.<attr>``) and project enum values; this module supplies the missing piece,
component references and their members:

    =Компоненты.<part>          -> the form's components (``=Компоненты.<name>``)
    =Компоненты.<comp>.<part>   -> members of that component's TYPE, taken from the
                                   stdlib members map (properties first, then methods)

The module is PURE: the caller passes in the components (an ``IndexLookup`` or a plain
list of component dicts) and the stdlib members map, so there is no server or file IO
here and it is covered by unit tests directly. Every result is a FULL binding string,
the leading ``=`` included; the list is deduplicated, kept in a stable order and capped.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# The identifier alphabet of the platform - Latin and Cyrillic, as elsewhere in the LSP core.
_IDENT = r"[A-Za-zА-Яа-яЁё_][A-Za-z0-9А-Яа-яЁё_]*"
_ROOT = "Компоненты"

# The chain after an optional leading ``=`` and surrounding whitespace. The component-member
# chain (two dots) is distinct from the shorter component chain (one dot), so the two patterns
# never both match; the member pattern is tried first for clarity.
_MEMBER_RE = re.compile(rf"^{_ROOT}\.({_IDENT})\.({_IDENT})?$")
_COMPONENT_RE = re.compile(rf"^{_ROOT}\.({_IDENT})?$")

#: A permissive cap - the editor filters the list further, but an unbounded list is never useful.
DEFAULT_LIMIT = 200


def _component_dicts(components: Optional[object], form_stem: str) -> list[dict]:
    """The form's components as a list of dicts, from either an IndexLookup or a plain list."""
    if components is None:
        return []
    by_form = getattr(components, "components_by_form", None)
    if callable(by_form):
        return list(by_form(form_stem) or [])
    return [c for c in components if isinstance(c, dict)]  # type: ignore[union-attr]


def _type_root(type_name: Optional[str]) -> Optional[str]:
    """The bare type of a component for the members lookup.

    The generic argument and the nullable mark are dropped (``Таблица<...>`` -> ``Таблица``,
    ``Строка?`` -> ``Строка``); a facet type (``ДвоичныйОбъект.Ссылка``) is kept whole, since
    it is a key of the members map in its own right.
    """
    if not type_name:
        return None
    return re.split(r"[<?]", str(type_name), maxsplit=1)[0].strip() or None


def _member_names(members: Optional[dict], type_name: Optional[str]) -> list[str]:
    """Member names (properties then methods) of a component type from the stdlib members map.

    Both dataset shapes are understood: the current ``{"properties": [...], "methods": [...]}``
    and the older flat list of names mixed together.
    """
    root = _type_root(type_name)
    if not root or not members:
        return []
    entry = members.get(root)
    if entry is None:
        return []
    if isinstance(entry, dict):
        names = list(entry.get("properties") or []) + list(entry.get("methods") or [])
    else:
        names = list(entry)
    return [str(n) for n in names if n]


def _matches(segment: str, candidate: str) -> bool:
    """A case-insensitive substring match of the typed segment against a candidate name.

    An empty segment (the bare ``Компоненты.`` or ``<comp>.`` context) matches everything.
    """
    return segment.casefold() in candidate.casefold()


def _bindings(head: str, names: Iterable[str], segment: str, limit: int) -> list[str]:
    """Full binding strings ``head + name`` for the names matching the typed segment,
    deduplicated, source order preserved, capped at ``limit``."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in names:
        name = str(raw)
        if not name or not _matches(segment, name):
            continue
        binding = head + name
        if binding in seen:
            continue
        seen.add(binding)
        out.append(binding)
        if len(out) >= limit:
            break
    return out


def complete_binding(
    prefix: str,
    *,
    form_stem: str = "",
    components: Optional[object] = None,
    members: Optional[dict] = None,
    limit: int = DEFAULT_LIMIT,
) -> list[str]:
    """Component-reference binding completions for the typed prefix.

    ``prefix`` is the binding text up to the cursor (with or without the leading ``=``);
    ``components`` is an ``IndexLookup`` or a plain list of the form's component dicts;
    ``members`` is the stdlib members map (``type_members`` merged with ``facet_members``).
    Returns FULL binding strings, deduplicated, in a stable order, capped at ``limit``.
    Any prefix the module does not recognize yields an empty list.
    """
    if not prefix:
        return []
    chain = prefix.strip()
    if chain.startswith("="):
        chain = chain[1:].lstrip()

    member = _MEMBER_RE.match(chain)
    if member:
        comp_name, part = member.group(1), member.group(2) or ""
        comp = next(
            (c for c in _component_dicts(components, form_stem) if c.get("name") == comp_name),
            None,
        )
        if comp is None:
            return []
        names = _member_names(members, comp.get("type"))
        return _bindings(f"={_ROOT}.{comp_name}.", names, part, limit)

    component = _COMPONENT_RE.match(chain)
    if component:
        part = component.group(1) or ""
        names = [c.get("name", "") for c in _component_dicts(components, form_stem)]
        return _bindings(f"={_ROOT}.", names, part, limit)

    return []
