"""Tier D: a component property named after a common module hides that module in the component.

The yaml/property-shadows-module rule. An own property of an interface component
(the top-level `Свойства:` block) puts its name into the scope of the WHOLE component - the
markup expressions and the paired module alike. A common module is addressed by its bare name
(docs, topic `Обращение к модулю, его методам и типам`: the module is reached by its name,
because that name is the name of the type extending the module), so a property repeating a
module name takes the name over: `X.Метод()` is no longer a module call but a member of the
property VALUE. Nothing complains until the build is applied, and then the server refuses every
such access at once (`Неизвестный метод` on the property's own type), the apply is rolled back
and the stand returns to the previous build. The complaint is easy to misread: it points at the
component file and carries the real method names, so the module looks broken rather than hidden.

The finding is reported at the property declaration. That is where the cure belongs - rename the
property, leave the module alone - and it is the earliest moment: the clash is a defect before
any call is written, because the module stays unreachable from that component for good.

No autofix on purpose. The cure is a rename, and a rename is not mechanical: the name is also
written in the markup bindings, in the paired module and in whatever passes the property from
outside, so an edit that renamed the declaration alone would leave a project that no longer
builds - a worse state than the clash it repaired.

Narrowings that keep the rule at zero false positives:

- only a COMMON MODULE is judged. A property repeating the name of a catalog, an enumeration, a
  structure or another component is a live idiom - such an element is normally reached in a TYPE
  position (`Массив<Тезка.Ссылка>`), which a property name does not take over. A run over the
  corpora found eleven such properties, every one of them in working code, against zero module
  clashes;
- the module has to be reachable from the component by the bare name: it lives in the same
  subsystem, or in a subsystem the component's own yaml imports. A foreign module that is not
  imported was never addressable there without a qualifier, so its name is free;
- a namespace `импорт` written in the paired .xbsl is NOT read. It covers the module and not the
  yaml, so a clash that would bite inside the module alone is left silent rather than guessed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
# The `Свойства:` block reader of the sibling property rule: one description of where an own
# property is declared, rather than two that can drift apart.
from xbsl.rules.reserved_names import _key_alternation, _props_block_re
from xbsl.rules.yaml_imports import _SUBSYSTEM_FILES, _subsystem_of
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of

MESSAGES = {
    "yaml/property-shadows-module.title": {
        "ru": "Свойство перекрывает общий модуль",
        "en": "Property shadows a common module",
    },
    "yaml/property-shadows-module.clash": {
        "ru": "Свойство '{prop}' названо как общий модуль проекта: имя перекрывает модуль во "
              "всём компоненте, и обращения '{prop}.Метод()' читаются как обращение к члену "
              "значения свойства – применение сборки падает \"Неизвестный метод\" и стенд "
              "откатывается. Переименуйте свойство, модуль трогать не нужно.",
        "en": "Property '{prop}' repeats the name of a common module of the project: the name "
              "hides the module across the whole component, and '{prop}.Method()' accesses read "
              "as members of the property VALUE – the apply fails with an unknown-method error "
              "and the stand rolls back. Rename the property; the module stays as it is.",
    },
}
i18n.register(MESSAGES)

RULE_ID = "yaml/property-shadows-module"

#: The element kinds the rule joins: the one that owns properties and the one it can hide.
_COMPONENT_KIND = "КомпонентИнтерфейса"
_MODULE_KIND = "ОбщийМодуль"


@lru_cache(maxsize=1)
def _name_line_re() -> re.Pattern:
    """A `Имя: <identifier>` line, both spellings of the key, quoted or bare."""
    return re.compile(
        r"(?m)^[ \t]*(?:- +)?(?:" + _key_alternation("Имя")
        + r"):[ \t]*(['\"]?)([A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)\1[ \t]*(?:#[^\n]*)?\r?$"
    )


dataset.register_reset(_name_line_re.cache_clear)


def _property_positions(source: SourceFile) -> dict[str, list[tuple[int, int]]]:
    """(line, col) of every declared property name inside the top-level properties block.

    One pass over the block for all the names: which of them clash is decided in the reduce,
    where the source is long gone, so the positions cannot be collected per interesting name.
    """
    lm = linemap(source)
    found: dict[str, list[tuple[int, int]]] = {}
    for block in _props_block_re().finditer(source.text):
        for m in _name_line_re().finditer(block.group(1)):
            found.setdefault(m.group(2), []).append(lm.linecol(block.start(1) + m.start(2)))
    return found


def _shadow_mapper(source: SourceFile) -> dict | None:
    """The map phase: subsystem roots, common module names, component properties.

    The property names come from the PARSED document (the block reader only says where they
    are written), so a name the regex cannot place still reaches the reduce - anchored at the
    head of the file rather than dropped.
    """
    if not _HAVE_YAML or source.kind != "yaml":
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    if source.path.name in _SUBSYSTEM_FILES:
        name = value_of(data, "Имя")
        return {
            "k": "sub",
            "dir": str(source.path.parent),
            "name": name if isinstance(name, str) else source.path.parent.name,
        }
    kind = object_kind(data)
    if kind == _MODULE_KIND:
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str) or not name:
            return None
        return {"k": "mod", "path": str(source.path), "name": name}
    if kind != _COMPONENT_KIND:
        return None
    props = value_of(data, "Свойства", kind)
    if not isinstance(props, list):
        return None
    declared = [
        name for name in dict.fromkeys(
            value_of(item, "Имя") for item in props if isinstance(item, dict)
        )
        if isinstance(name, str) and name
    ]
    if not declared:
        return None
    positions = _property_positions(source)
    raw = value_of(data, "Импорт", kind)
    imports = sorted({e for e in raw if isinstance(e, str)}) if isinstance(raw, list) else []
    return {
        "k": "comp",
        "path": str(source.path),
        "imports": imports,
        "props": [
            [name, line, col]
            for name in declared
            for line, col in positions.get(name) or [(1, 1)]
        ],
    }


@rule(
    RULE_ID, f"{RULE_ID}.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_shadow_mapper,
)
def property_shadows_module(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    roots = {Path(f["dir"]): f["name"] for f in facts.values() if f["k"] == "sub"}
    modules: dict[str | None, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "mod":
            subsystem = _subsystem_of(Path(fact["path"]), roots)
            modules.setdefault(subsystem, set()).add(fact["name"])
    if not modules:
        return
    for rel, fact in facts.items():
        if fact["k"] != "comp":
            continue
        reachable = set(modules.get(_subsystem_of(Path(fact["path"]), roots), ()))
        for imported in fact["imports"]:
            reachable |= modules.get(imported, set())
        for name, line, col in fact["props"]:
            if name in reachable:
                yield Diagnostic(
                    rel, line, col, RULE_ID, Severity.ERROR,
                    i18n.t(f"{RULE_ID}.clash", prop=name),
                )
