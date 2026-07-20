"""Russian<->English term pairs of the platform (terms.json).

1C:Element is bilingual: `Запрос` is `Query`, the yaml key `ОбластьВидимости` is
`VisibilityScope`, the value `ВПроекте` is `InProject`. Sources may be written either way,
so anything that matches a platform name by text has to accept both spellings.

The pairs are extracted from the distribution (tools/extract_terms.py) and split by ROLE -
`Ссылка` is the property `Link` and the facet part `Reference`, and only the role tells
which is right. Without the data file every helper degrades to the Russian spelling alone:
a missed English spelling is a false negative, inventing one would be a false positive.
"""

from __future__ import annotations

from xbsl import dataset

SECTIONS = ("types", "facets", "properties", "enums")

_cache: dict[str, dict[str, str]] | None = None


def _terms() -> dict[str, dict[str, str]]:
    global _cache
    if _cache is None:
        try:
            data = dataset.load_json("terms.json")
        except Exception:  # noqa: BLE001 - no data, Russian spelling only
            data = {}
        _cache = {section: dict(data.get(section) or {}) for section in SECTIONS}
    return _cache


def english(name: str, section: str) -> str | None:
    """The English spelling of a name in the given role, when the platform declares one."""
    return _terms().get(section, {}).get(name)


def forms(name: str, section: str) -> tuple[str, ...]:
    """Both spellings of a name, or just the given one when the platform has no English."""
    other = english(name, section)
    return (name, other) if other else (name,)


def key_forms(*names: str, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Both spellings of yaml keys, Russian first.

    A key is looked up as a property and then as a type name - a yaml key may repeat the
    name of a type (`Версия`). `extra` adds spellings seen in real artifacts that the
    metamodel does not declare: the library manifest writes `Vendor`, but no
    `@PropertyInfo` pairs it with `Поставщик`.
    """
    out: list[str] = []
    for name in (*names, *extra):
        candidates = (name,) if name in out else forms(name, "properties")
        if len(candidates) == 1 and name not in extra:
            candidates = forms(name, "types")
        for form in candidates:
            if form not in out:
                out.append(form)
    return tuple(out)
