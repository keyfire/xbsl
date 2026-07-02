"""Тир D: свойства верхнего уровня yaml-объекта по метамодели Элемента.

Метамодель конфигурации (xbsllint/data/.../metamodel.json, генерит tools/extract_metamodel.py)
описывает для каждого класса допустимые свойства (@PropertyInfo из .xcore) и наследование.
Правило проверяет ключи ВЕРХНЕГО уровня yaml-объекта: если ключ не входит в множество свойств
корневого класса (с учётом наследования) плюс универсальные ключи оболочки (common) – это
недопустимое свойство (опечатка/перенос из другого вида).

Только выверенные виды: если `ВидЭлемента` нет в vid2class метамодели, объект не проверяется –
это исключает ложные на непроверенных видах. Проверяется лишь верхний уровень (не вложенные
компоненты) – их валидация требует резолвинга типа узла по дискриминаторам (отдельный этап).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache

from xbsllint import dataset
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap
from xbsllint.rules.yaml_schema import _HAVE_YAML, _is_object, _parsed

# Ключ верхнего уровня yaml: имя в начале строки (без отступа) до двоеточия.
_TOPKEY_RE = re.compile(r"(?m)^([^\s#:][^:\n]*):")


@lru_cache(maxsize=1)
def _metamodel():
    try:
        return dataset.load_json("metamodel.json")
    except (dataset.DatasetError, KeyError, ValueError):
        return None


@lru_cache(maxsize=None)
def _allowed_for_class(name: str) -> frozenset[str]:
    """Свойства класса с учётом наследования (транзитивно по ext)."""
    mm = _metamodel()
    if not mm:
        return frozenset()
    classes = mm["classes"]
    out: set[str] = set()
    seen: set[str] = set()
    stack = [name]
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        node = classes.get(c)
        if not node:
            continue
        out.update(node["props"])
        stack.extend(node["ext"])
    return frozenset(out)


@rule("yaml/unknown-property", "Неизвестное свойство объекта", "D", severity=Severity.WARNING)
def unknown_property(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml" or not _HAVE_YAML:
        return []
    mm = _metamodel()
    if not mm:
        return []  # метамодель не сгенерирована – проверку не выполняем
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return []
    vid = data.get("ВидЭлемента")
    cls = mm["vid2class"].get(vid)
    if not cls:
        return []  # вид не выверен – не проверяем
    allowed = set(_allowed_for_class(cls)) | set(mm["common"])

    diags: list[Diagnostic] = []
    lm = linemap(source)
    for m in _TOPKEY_RE.finditer(source.text):
        key = m.group(1).strip()
        if key in data and key not in allowed:  # только реальные ключи верхнего уровня
            line, col = lm.linecol(m.start(1))
            diags.append(Diagnostic(
                source.rel, line, col, "yaml/unknown-property", Severity.WARNING,
                f"Свойство '{key}' недопустимо для вида '{vid}'.",
            ))
    return diags
