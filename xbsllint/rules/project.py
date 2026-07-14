"""Тир A: свойства проекта по стандарту 1С:Элемент "Заполнение свойств проекта".

Проверяется описание проекта (у него нет ВидЭлемента, зато есть Поставщик и Версия). Стандарт
обязателен, поэтому правила - предупреждения:

- Поставщик и Имя - валидные идентификаторы, образованные от представлений: каждое слово с
  прописной буквы, в том числе однобуквенные предлоги (НовыеЭлементарныеТехнологии,
  ВсегдаВДвижении, КабинетСотрудника). Границы слов в слитном имени не видны, поэтому проверяем
  то, что проверить можно: идентификатор начинается с прописной и не содержит разделителей;
- Представление и ПредставлениеПоставщика заполнены: официальное название проекта и название
  компании-разработчика (по ним же образуются Имя и Поставщик);
- Версия - три числа A.B.C (семантическое версионирование): A ломает совместимость, B добавляет
  функциональность, C - обратно совместимые исправления.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsllint import i18n
from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap
from xbsllint.rules.yaml_schema import _HAVE_YAML, _parsed

MESSAGES = {
    "project/identifier.title": {
        "ru": "Имя или поставщик проекта не идентификатор",
        "en": "Project name or vendor is not an identifier",
    },
    "project/identifier.bad": {
        "ru": "'{prop}' проекта – '{value}': это идентификатор, образованный от представления, "
              "каждое слово с прописной буквы (КабинетСотрудника, НовыеЭлементарныеТехнологии).",
        "en": "Project '{prop}' – '{value}': it is an identifier built from the presentation, every "
              "word capitalized (КабинетСотрудника, НовыеЭлементарныеТехнологии).",
    },
    "project/presentation.title": {
        "ru": "Представление проекта не заполнено",
        "en": "Project presentation is empty",
    },
    "project/presentation.missing": {
        "ru": "'{prop}' проекта не заполнено – это {what}, от него образуется идентификатор.",
        "en": "Project '{prop}' is empty – it is {what}, and the identifier is built from it.",
    },
    "project/version.title": {"ru": "Версия проекта не A.B.C", "en": "Project version is not A.B.C"},
    "project/version.bad": {
        "ru": "Версия проекта '{value}' – версия задаётся тремя числами A.B.C (семантическое "
              "версионирование): '{suggestion}'.",
        "en": "Project version '{value}' – the version is three numbers A.B.C (semantic versioning): "
              "'{suggestion}'.",
    },
}
i18n.register(MESSAGES)

# Идентификатор языка: буква (прописная - того требует стандарт), дальше буквы и цифры.
_IDENTIFIER_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_KEY_RE = re.compile(r"(?m)^([^\s#:][^:\n]*):")

# Свойства-представления и то, чем они являются по стандарту.
PRESENTATIONS = {
    "Представление": "presentation.project",
    "ПредставлениеПоставщика": "presentation.vendor",
}
i18n.register({
    "presentation.project": {
        "ru": "официальное название проекта",
        "en": "the official name of the project",
    },
    "presentation.vendor": {
        "ru": "название компании-разработчика",
        "en": "the name of the company that developed it",
    },
})


def _project(source: SourceFile) -> dict | None:
    """Разобранное описание проекта или None.

    У проекта нет ВидЭлемента (он сам - корень), опознаём по паре Поставщик + Версия: так правило
    не сработает ни на описании элемента, ни на постороннем yaml репозитория.
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict) or data.get("ВидЭлемента"):
        return None
    if "Поставщик" not in data or "Версия" not in data:
        return None
    return data


def _key_pos(source: SourceFile, key: str) -> tuple[int, int]:
    """Строка и колонка ключа верхнего уровня (или начало файла, если ключа нет)."""
    lm = linemap(source)
    for m in _KEY_RE.finditer(source.text):
        if m.group(1).strip() == key:
            return lm.linecol(m.start(1))
    return 1, 1


@rule("project/identifier", "project/identifier.title", "A", severity=Severity.WARNING)
def identifier(source: SourceFile) -> Iterable[Diagnostic]:
    """Имя и Поставщик - идентификаторы с прописной буквы (КабинетСотрудника, а не site)."""
    data = _project(source)
    if data is None:
        return
    for prop in ("Поставщик", "Имя"):
        value = data.get(prop)
        if not isinstance(value, str) or not value:
            continue  # пустое значение - это уже другая проверка платформы
        if _IDENTIFIER_RE.match(value):
            continue
        line, col = _key_pos(source, prop)
        yield Diagnostic(
            source.rel, line, col, "project/identifier", Severity.WARNING,
            i18n.t("project/identifier.bad", prop=prop, value=value),
        )


@rule("project/presentation", "project/presentation.title", "A", severity=Severity.WARNING)
def presentation(source: SourceFile) -> Iterable[Diagnostic]:
    """Представление и ПредставлениеПоставщика заполнены: от них образуются Имя и Поставщик."""
    data = _project(source)
    if data is None:
        return
    for prop, what in PRESENTATIONS.items():
        value = data.get(prop)
        if isinstance(value, str) and value.strip():
            continue
        line, col = _key_pos(source, prop if prop in data else "Имя")
        yield Diagnostic(
            source.rel, line, col, "project/presentation", Severity.WARNING,
            i18n.t("project/presentation.missing", prop=prop, what=i18n.t(what)),
        )


@rule("project/version", "project/version.title", "A", severity=Severity.WARNING)
def version(source: SourceFile) -> Iterable[Diagnostic]:
    """Версия - три числа A.B.C: 1.0 не говорит, что менялось - совместимость или исправления."""
    data = _project(source)
    if data is None:
        return
    raw = data.get("Версия")
    value = str(raw) if raw is not None else ""
    if _VERSION_RE.match(value):
        return
    parts = [p for p in re.split(r"[.\s]+", value) if p.isdigit()]
    suggestion = ".".join((parts + ["0", "0", "0"])[:3]) if parts else "1.0.0"
    line, col = _key_pos(source, "Версия")
    yield Diagnostic(
        source.rel, line, col, "project/version", Severity.WARNING,
        i18n.t("project/version.bad", value=value, suggestion=suggestion),
    )
