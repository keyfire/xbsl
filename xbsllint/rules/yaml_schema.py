"""Тир A: проверки YAML-описаний элементов.

- yaml/valid            – YAML корректно парсится;
- yaml/id-uuid          – каждый Ид (в т.ч. вложенных реквизитов) – валидный UUID;
- yaml/id-unique        – Ид уникальны в пределах проекта (кросс-файловое правило);
- yaml/id-required      – у объекта (есть ВидЭлемента) задан Ид верхнего уровня;
- yaml/name-matches-file – Имя объекта совпадает с именем файла.

Структурные файлы (Проект/Подсистема/Ресурсы) распознаются по отсутствию ВидЭлемента и от
правил про Имя/обязательный Ид освобождены; проверки Ид (формат/уникальность) применяются
ко всем Ид во всех файлах.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap

try:
    import yaml

    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ID_LINE_RE = re.compile(r"(?m)^[ \t]*Ид:[ \t]*(\S+)")
_NAME_LINE_RE = re.compile(r"(?m)^[ \t]*Имя:[ \t]*(\S.*)$")


def _parsed(source: SourceFile):
    """Разобранный YAML (или None) и ошибка разбора (или None), с кэшированием."""
    if "yaml" not in source.cache:
        data = None
        err = None
        try:
            data = yaml.safe_load(source.text)
        except yaml.YAMLError as exc:  # noqa: BLE001
            err = exc
        source.cache["yaml"] = data
        source.cache["yaml_error"] = err
    return source.cache["yaml"], source.cache["yaml_error"]


def _id_lines(source: SourceFile) -> list[tuple[str, int, int]]:
    """Список (значение Ид, строка, колонка) по всем строкам 'Ид:' файла."""
    key = "id_lines"
    if key not in source.cache:
        lm = linemap(source)
        out: list[tuple[str, int, int]] = []
        for m in _ID_LINE_RE.finditer(source.text):
            line, col = lm.linecol(m.start(1))
            out.append((m.group(1).strip(), line, col))
        source.cache[key] = out
    return source.cache[key]


def _is_object(data) -> bool:
    """Является ли файл описанием объекта метаданных (есть ВидЭлемента)."""
    return isinstance(data, dict) and data.get("ВидЭлемента") is not None


@rule("yaml/valid", "YAML не парсится", "A", severity=Severity.ERROR)
def yaml_valid(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    _data, err = _parsed(source)
    if err is not None:
        mark = getattr(err, "problem_mark", None)
        line = mark.line + 1 if mark else 1
        col = mark.column + 1 if mark else 1
        problem = getattr(err, "problem", None) or "ошибка синтаксиса YAML"
        yield Diagnostic(source.rel, line, col, "yaml/valid", Severity.ERROR, f"YAML: {problem}.")


@rule("yaml/id-uuid", "Ид не является UUID", "A", severity=Severity.ERROR)
def yaml_id_uuid(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "yaml":
        return
    for value, line, col in _id_lines(source):
        if not _UUID_RE.match(value):
            yield Diagnostic(
                source.rel, line, col, "yaml/id-uuid", Severity.ERROR,
                f"Ид '{value}' не является UUID (формат 8-4-4-4-12).",
            )


@rule("yaml/id-required", "У объекта нет Ид", "A", severity=Severity.WARNING)
def yaml_id_required(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    if "Ид" not in data:
        yield Diagnostic(
            source.rel, 1, 1, "yaml/id-required", Severity.WARNING,
            "У объекта не задан Ид верхнего уровня.",
        )


@rule("yaml/name-matches-file", "Имя не совпадает с именем файла", "A", severity=Severity.WARNING)
def yaml_name_matches_file(source: SourceFile) -> Iterable[Diagnostic]:
    if not _HAVE_YAML or source.kind != "yaml":
        return
    data, err = _parsed(source)
    if err is not None or not _is_object(data):
        return
    name = data.get("Имя")
    stem = source.path.stem
    if isinstance(name, str) and name != stem:
        m = _NAME_LINE_RE.search(source.text)
        line, col = (1, 1)
        if m:
            line, col = linemap(source).linecol(m.start(1))
        yield Diagnostic(
            source.rel, line, col, "yaml/name-matches-file", Severity.WARNING,
            f"Имя '{name}' не совпадает с именем файла '{stem}'.",
        )


@rule("yaml/id-unique", "Дубли Ид в проекте", "A", scope="project", severity=Severity.ERROR)
def yaml_id_unique(sources: list[SourceFile]) -> Iterable[Diagnostic]:
    occ: dict[str, list[tuple[SourceFile, int, int]]] = defaultdict(list)
    for s in sources:
        if s.kind != "yaml":
            continue
        for value, line, col in _id_lines(s):
            occ[value].append((s, line, col))
    for value, places in occ.items():
        if len(places) < 2:
            continue
        for i, (s, line, col) in enumerate(places):
            others = [f"{o.rel}:{ol}" for j, (o, ol, _oc) in enumerate(places) if j != i]
            yield Diagnostic(
                s.rel, line, col, "yaml/id-unique", Severity.ERROR,
                f"Дублирующийся Ид '{value}' (также: {', '.join(others[:3])}).",
            )
