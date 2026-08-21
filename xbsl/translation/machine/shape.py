"""Prose from the service becomes a name here - deterministically, never by the service.

The service answers in sentences ("Site address"); the tokens plan needs an identifier. Terms
are applied again at this point even when the provider was given a glossary: a service returns a
term in whatever case it likes and buried inside a phrase, and only here can the spelling be
pinned exactly - word by word, against the English the service answered.
"""

from __future__ import annotations

import re
from typing import Mapping

STOP_WORDS = frozenset({"a", "an", "the", "of", "for", "to", "in", "on", "by", "with"})

# British spelling the localization texts do not use.
AMERICAN_SPELLING = {"colour": "color", "catalogue": "catalog", "centre": "center",
                     "analyse": "analyze", "licence": "license", "behaviour": "behavior"}


def identifier(prose: str, terms: Mapping[str, str], taken: set[str]) -> tuple[str, str]:
    words = [w for w in re.split(r"[^0-9A-Za-z]+", prose) if w]
    words = [w for w in words if w.casefold() not in STOP_WORDS]
    if not words:
        return "", f"nothing to build a name from: {prose!r}"

    parts: list[str] = []
    for word in words:
        key = word.casefold()
        key = AMERICAN_SPELLING.get(key, key)
        term = terms.get(key)
        parts.append(term if term else key[:1].upper() + key[1:])

    name = "".join(parts)
    if not re.fullmatch(r"[A-Za-z][0-9A-Za-z]*", name):
        return "", f"not an identifier: {name!r}"

    # Check if name is already taken (case-insensitive comparison)
    normalized_name = name.casefold()
    taken_name = None
    for candidate in taken:
        if candidate.casefold() == normalized_name:
            taken_name = candidate
            break

    if taken_name is not None:
        return "", f"the name {taken_name!r} is already taken by another key"

    return name, ""
