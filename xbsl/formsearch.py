"""Structural search over interface-component forms (docs/DESIGNER.md hook 10).

Given a query - a component type plus optional key=value property predicates - it walks each
form's node tree (formmodel.parse_form) and returns the matching components with their location.

The query is deliberately small and whitespace-separated: the first token that has no "=" is the
component type ("*" or absent matches any type), and every "key=value" token requires a property
whose value contains value (case-insensitive substring; an empty value only requires the key to be
present). A form that fails to parse is skipped, not fatal - one broken file never sinks a search.
"""
from __future__ import annotations

from dataclasses import dataclass

import yaml

from xbsl.formmodel import FormModelError, parse_form


@dataclass
class Predicate:
    key: str
    value: str


def parse_query(query: str) -> tuple[str | None, list[Predicate]]:
    """(type filter, predicates) of a raw query string. Empty/invalid tokens are dropped."""
    type_filter: str | None = None
    predicates: list[Predicate] = []
    for token in (query or "").split():
        if "=" in token:
            key, _, value = token.partition("=")
            key = key.strip()
            if key:
                predicates.append(Predicate(key, value.strip()))
        elif type_filter is None and token != "*":
            type_filter = token
    return type_filter, predicates


def _type_matches(node_type: str | None, type_filter: str) -> bool:
    return bool(node_type) and type_filter.lower() in node_type.lower()


def _node_matches(node, predicates: list[Predicate]) -> bool:
    if not predicates:
        return True
    by_key = {p.key: p.value_preview for p in node.properties}
    for pred in predicates:
        value = by_key.get(pred.key)
        if value is None or (pred.value and pred.value.lower() not in value.lower()):
            return False
    return True


def search_form(text: str, type_filter: str | None, predicates: list[Predicate]) -> list[dict]:
    """Matching components of ONE form: {nodeId, name, type, line} (line is 0-based)."""
    try:
        form = parse_form(text)
    except (FormModelError, yaml.YAMLError, ValueError):
        return []  # a broken form is skipped, not fatal
    out: list[dict] = []
    for node in form.nodes.values():
        if node.kind != "component":
            continue
        if type_filter and not _type_matches(node.type, type_filter):
            continue
        if not _node_matches(node, predicates):
            continue
        out.append(
            {
                "nodeId": node.id,
                "name": node.name or "",
                "type": node.type or "",
                "line": node.anchor_line,
            }
        )
    return out


def search_forms(forms: list[dict], query: str) -> list[dict]:
    """Matching components across many forms; each match carries the form path it came from.

    forms - a list of {"path", "text"}. Results keep the input order (form order, then node order).
    """
    type_filter, predicates = parse_query(query)
    results: list[dict] = []
    for form in forms:
        path = form.get("path", "")
        for match in search_form(form.get("text", ""), type_filter, predicates):
            results.append({**match, "path": path})
    return results
