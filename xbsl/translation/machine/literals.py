"""Literals are names written a second time - a resource path, a field key, a component name.

They are not translated: their value is already decided in the tokens plan, so it is substituted
when the literal matches exactly. A literal that is not known leaves the result empty - a guess
here would diverge from the rename silently, which is the whole class of defect this plan exists
to avoid.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from xbsl.translation.entries import Gap


def fill(gaps: Sequence[Gap], tokens: Mapping[str, str]) -> dict[str, str]:
    """Fill literal gaps only when they match exactly in tokens.

    Only a literal that matches exactly (case-sensitive) as a whole key in tokens gets
    substituted. Partial matches and case variations are left alone to prevent accidental
    mismatches with unrelated entities.
    """
    filled: dict[str, str] = {}
    for gap in gaps:
        if gap.kind != "literal":
            continue
        text = gap.key
        # Exact match only: the text as written in the source must be a key in tokens.
        if text in tokens:
            filled[text] = tokens[text]
    return filled
