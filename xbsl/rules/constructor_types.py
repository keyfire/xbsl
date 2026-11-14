"""Known argument types of constructors generated from project metadata."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsl import dataset, i18n, typeinfer
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule

RULE = "code/constructor-argument-type"
_PERMISSION_DATA = "ДанныеРасчетаРазрешений"

i18n.register({
    f"{RULE}.title": {
        "ru": "Тип аргумента не подходит конструктору",
        "en": "An argument type does not match the constructor",
    },
    f"{RULE}.argument": {
        "ru": "Конструктор '{constructor}' ожидает для '{parameter}' тип {expected}. "
              "Передан {actual}.",
        "en": "Constructor '{constructor}' expects {expected} for '{parameter}'. "
              "The argument has type {actual}.",
    },
})


@lru_cache(maxsize=1)
def _names() -> frozenset[str]:
    return frozenset({_PERMISSION_DATA, *(
        alias for alias, canonical in typeinfer._facet_suffixes().items()
        if canonical == _PERMISSION_DATA
    )})


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern:
    return re.compile(r"(?<!\w)(?:%s)(?!\w)" % "|".join(sorted(map(re.escape, _names()))))


dataset.register_reset(_names.cache_clear)
dataset.register_reset(_pattern.cache_clear)


def _needs_typing(source: SourceFile) -> bool:
    return _pattern().search(source.text) is not None


typeinfer.wants_text(_needs_typing)


def _parameters(fields: list[str], names: list[str | None]) -> list[str] | None:
    if len(fields) == 1 and names == [None]:
        return fields
    if None not in names and len(names) == len(fields) and set(names) == set(fields):
        return [name for name in names if name is not None]
    return None


@rule(RULE, f"{RULE}.title", "D", scope="project", severity=Severity.ERROR, mapper=typeinfer.project_fact)
def constructor_argument_type(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """Check known field overloads of a catalog's generated permission-data constructor."""
    for rel, typing in typeinfer.project_typings(facts).items():
        catalog = typing.catalog
        for node, types in typing.typer.constructor_arguments(typing.tree, _names(), _pattern()):
            written = node.type.text
            owner, dot, _facet = written.rpartition(".")
            owner = owner.strip()
            if not dot or owner not in catalog.elements:
                continue
            element = catalog.elements[owner]
            fields = element.get("permissions_by") or []
            if element.get("kind") != "Справочник" or not fields:
                continue
            names = [argument.name for argument in node.args]
            parameters = _parameters(fields, names)
            if parameters is None:
                continue
            for argument, name, actual in zip(node.args, parameters, types):
                if actual is None or actual.size != 1 or not actual.names:
                    continue
                source = next(iter(actual.names))
                if argument.name is None and source in {f"{owner}.Объект", f"{owner}.Данные"}:
                    continue  # The copy overload takes the catalog object.
                expected_name = catalog.field_written(owner, name)
                expected = catalog.written(expected_name, None) if isinstance(expected_name, str) else None
                if expected is None or not expected.names:
                    continue
                if any(catalog.assignable(source, target) or catalog.assignable(target, source)
                       for target in expected.names):
                    continue
                offset = argument.value.start
                yield Diagnostic(
                    rel, typing.text.count("\n", 0, offset) + 1,
                    offset - typing.text.rfind("\n", 0, offset), RULE, Severity.ERROR,
                    i18n.t(f"{RULE}.argument", constructor=written, parameter=name,
                           expected=" | ".join(sorted(expected.names)), actual=source),
                )
