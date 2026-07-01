"""Тир D: семантические проверки по каталогу stdlib.

Первое правило – существование типа в выражении `новый <Тип>`: база типа должна быть либо
символом stdlib (xbsllint/data/stdlib.json, генерит tools/extract_stdlib.py), либо объектом
проекта (Имя из yaml с ВидЭлемента), либо локально объявленным типом (структура/перечисление/
исключение). Правило проектное (кросс-файловое): корректно только зная весь проект, поэтому
в режиме одиночного файла (lint_source) не выполняется – это исключает ложные срабатывания.

Выверено на корпусе сайта: из 142 разных типов в `новый` 125 – проектные/локальные, 17 –
stdlib, все покрыты каталогом; 0 ложных.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache

from xbsllint import dataset
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import tokens
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

_LOCAL_TYPE_KW = ("STRUCTURE", "ENUMERATION", "EXCEPTION")


@lru_cache(maxsize=1)
def _stdlib_names() -> frozenset[str]:
    try:
        return frozenset(dataset.load_json("stdlib.json")["names"])
    except (dataset.DatasetError, KeyError, ValueError):
        return frozenset()


def _project_object_names(sources: list[SourceFile]) -> set[str]:
    names: set[str] = set()
    if not _HAVE_YAML:
        return names
    for s in sources:
        if s.kind != "yaml":
            continue
        data, err = _parsed(s)
        if err is None and isinstance(data, dict) and data.get("ВидЭлемента"):
            nm = data.get("Имя")
            if isinstance(nm, str):
                names.add(nm)
    return names


def _local_type_names(sources: list[SourceFile]) -> set[str]:
    names: set[str] = set()
    for s in sources:
        if s.kind != "xbsl":
            continue
        toks = tokens(s)
        for i, t in enumerate(toks):
            if t.kind == "KEYWORD" and t.value[:1].islower() and t.canonical in _LOCAL_TYPE_KW:
                for j in range(i + 1, min(i + 3, len(toks))):
                    if toks[j].kind == "IDENT":
                        names.add(toks[j].value)
                        break
    return names


@rule(
    "code/unknown-type", "Неизвестный тип в 'новый'", "D",
    scope="project", severity=Severity.WARNING,
)
def unknown_new_type(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    stdlib = _stdlib_names()
    if not stdlib:
        return []  # каталог не сгенерирован – проверку не выполняем
    known = set(stdlib) | _project_object_names(sources) | _local_type_names(sources)

    diags: list[Diagnostic] = []
    for s in sources:
        if s.kind != "xbsl":
            continue
        toks = tokens(s)
        for i, t in enumerate(toks):
            if t.kind == "KEYWORD" and t.canonical == "NEW" and t.value[:1].islower():
                j = i + 1
                while j < len(toks) and toks[j].kind == "COMMENT":
                    j += 1
                if j < len(toks) and toks[j].kind == "IDENT":
                    base = toks[j].value
                    if base not in known:
                        diags.append(Diagnostic(
                            s.rel, toks[j].line, toks[j].col, "code/unknown-type",
                            Severity.WARNING,
                            f"Неизвестный тип '{base}' в 'новый' – нет ни в stdlib, "
                            "ни среди объектов проекта или локальных типов.",
                        ))
    return diags
