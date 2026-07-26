"""Tier D: a component property newer than the project's compatibility mode.

The ui schema records the version a property appeared in (`since`), and the project declares
`РежимСовместимости`. Using a newer property is rejected when the build is applied, with a
message that names the property but not the reason - a project with `РежимСовместимости: 9.0`
answers `СписокЗадач.yaml [16:21]: Неизвестное свойство "ИспользоватьМножественнуюСортировку"`
(the property is newer than the mode the project declares). That costs a deploy cycle, hence
the error severity.

Guards, in the spirit of the neighbouring rules:

- only a node whose `Тип` names a component the schema knows is judged (the generic head is
  taken: `Таблица<ДинамическийСписок>` -> `Таблица`), so a project component is never mistaken
  for a platform one;
- both spellings of the component and of the property are accepted (the platform reads a form
  written in English the same way);
- a mode the rule cannot parse into numbers, or a source outside any project, is silence.

A project declaring an older mode than the properties it uses is a finding about the project,
not a false positive: an outdated mode the server refuses outright
(`Неподдерживаемый режим совместимости "5.0"`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, terms, uischema
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.rules.yaml_schema import (
    _HAVE_YAML,
    _composed,
    _is_object,
    _mapping_nodes,
    _parsed,
    _scalar_entries,
    yaml,
)

MESSAGES = {
    "yaml/property-since-compat.title": {
        "ru": "Свойство новее режима совместимости",
        "en": "Property newer than the compatibility mode",
    },
    "yaml/property-since-compat.newer": {
        "ru": "Свойство '{prop}' компонента '{component}' появилось в {since}, а режим "
              "совместимости проекта – {compat}: применение сборки отвергнет его "
              "('Неизвестное свойство'). Поднимите РежимСовместимости либо уберите свойство.",
        "en": "Property '{prop}' of component '{component}' appeared in {since} while the "
              "project compatibility mode ({n[РежимСовместимости]}) is {compat}: applying the build rejects it "
              "('Неизвестное свойство'). Raise {n[РежимСовместимости]} or drop the property.",
    },
}
i18n.register(MESSAGES)


def _version(value) -> tuple[int, ...] | None:
    """A dotted version as a tuple of numbers, or None when it is not one."""
    if not isinstance(value, (str, int, float)):
        return None
    parts = str(value).strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


@lru_cache(maxsize=1)
def _since_table() -> tuple[dict[str, dict[str, tuple[int, ...]]], "re.Pattern | None"]:
    """({component: {property: the version it appeared in}}, a key regex), empty without a schema.

    Built once - resolving the dataset walks the installed data plugins, and the table is the
    same for every file. The regex is the fast path: composing the node graph is a second parse
    of the file, so it happens only when the text carries a key the rule could judge.
    """
    schema = dataset.load_ui_schema()
    if not schema:
        return {}, None
    table: dict[str, dict[str, tuple[int, ...]]] = {}
    names: set[str] = set()
    for component, record in (schema.get("components") or {}).items():
        judged: dict[str, tuple[int, ...]] = {}
        for prop, info in (record.get("props") or {}).items():
            since = _version(info.get("since")) if isinstance(info, dict) else None
            if since is None:
                continue
            judged[prop] = since
            names.add(prop)
            # Both spellings, taken FORWARD from the names the schema carries: the reverse
            # dictionaries are many-to-one and would answer with whichever pair came last.
            english_prop = terms.common_english(prop)
            if english_prop:
                judged[english_prop] = since
                names.add(english_prop)
        if not judged:
            continue
        table[component] = judged
        english_component = terms.common_english(component)
        if english_component:
            table[english_component] = judged
    if not names:
        return {}, None
    keys_re = re.compile(
        r"(?m)^[ \t]*(?:-[ \t]+)?(?:%s)[ \t]*:" % "|".join(sorted(map(re.escape, names)))
    )
    return table, keys_re


dataset.register_reset(_since_table.cache_clear)


def _directory(rel: str) -> str:
    """The directory of a source, with forward slashes and no trailing one."""
    path = rel.replace("\\", "/")
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _since_mapper(source: SourceFile) -> dict | None:
    """The map phase: a project file contributes its compatibility mode, an element yaml its
    properties that carry a `since`. Which mode governs which file is the reduce's call."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    table, keys_re = _since_table()
    if keys_re is None:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    if not _is_object(data):
        # a project description carries no element kind; either spelling of the key
        mode = _version(data.get("РежимСовместимости") or data.get("CompatibilityMode"))
        if mode is None:
            return None
        return {"k": "p", "dir": _directory(source.rel), "compat": mode}
    if not keys_re.search(source.text):
        return None
    root = _composed(source)
    if root is None:  # pragma: no cover - _parsed has already vetted the syntax
        return None
    cands: list[tuple[int, int, str, str, tuple[int, ...]]] = []
    for mapping in _mapping_nodes(root):
        entries = _scalar_entries(mapping)
        type_entry = entries.get("Тип") or entries.get("Type")
        if type_entry is None or not isinstance(type_entry[1], yaml.ScalarNode):
            continue
        component = type_entry[1].value.split("<", 1)[0].strip()
        props = table.get(component)
        if props is None:
            continue  # not a platform component (a project one, a data type)
        for key, (key_node, _value) in entries.items():
            since = props.get(key) or props.get(key_node.value)
            if since is None:
                continue
            cands.append((
                key_node.start_mark.line + 1, key_node.start_mark.column + 1,
                component, key_node.value, since,
            ))
    if not cands:
        return None
    return {"k": "x", "dir": _directory(source.rel), "cands": cands}


@rule(
    "yaml/property-since-compat", "yaml/property-since-compat.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_since_mapper,
)
def property_since_compat(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A property newer than the project's compatibility mode - apply rejects it."""
    modes = {fact["dir"]: fact["compat"] for fact in facts.values() if fact["k"] == "p"}
    if not modes:
        return  # no project description in the run - the mode is unknown, stay silent
    for rel, fact in facts.items():
        if fact["k"] != "x":
            continue
        # The project of a source is the nearest description UP the tree.
        directory = fact["dir"]
        compat = None
        while True:
            if directory in modes:
                compat = modes[directory]
                break
            if not directory:
                break
            directory = directory.rsplit("/", 1)[0] if "/" in directory else ""
        if compat is None:
            continue
        for line, col, component, prop, since in fact["cands"]:
            if since <= compat:
                continue
            yield Diagnostic(
                rel, line, col, "yaml/property-since-compat", Severity.ERROR,
                i18n.t(
                    "yaml/property-since-compat.newer",
                    prop=prop, component=component,
                    since=".".join(str(part) for part in since),
                    compat=".".join(str(part) for part in compat),
                ),
            )
