"""Tier A: project properties per the 1C:Element standard "Заполнение свойств проекта".

Checked is the project description (it has no ВидЭлемента but does have Поставщик and Версия).
The standard is mandatory, so the rules are warnings:

- Поставщик and Имя are valid identifiers built from the presentations: every word capitalized,
  including one-letter prepositions (НовыеЭлементарныеТехнологии, ВсегдаВДвижении,
  КабинетСотрудника). Word boundaries in a fused name are invisible, so we check what can be
  checked: the identifier starts with a capital and contains no separators;
- Представление and ПредставлениеПоставщика are filled in: the official project name and the
  name of the developing company (Имя and Поставщик are built from them);
- Версия is three numbers A.B.C (semantic versioning): A breaks compatibility, B adds
  functionality, C is backward-compatible fixes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsl import i18n, metamodel
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind

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
    "project/path-matches-descriptor.title": {
        "ru": "Путь проекта не совпадает с дескриптором",
        "en": "The project path does not match the descriptor",
    },
    "project/path-matches-descriptor.mismatch": {
        "ru": "Каталог проекта обязан лежать по схеме {{репозиторий}}/{{поставщик}}/{{имя}}: "
              "дескриптор объявляет {expected}, а путь несёт {actual}. Сборка отвергнет проект "
              "ДО компиляции – переименуйте каталоги (регистр важен) либо дескриптор.",
        "en": "The project directory must follow the {{repo}}/{{vendor}}/{{name}} layout: the "
              "descriptor declares {expected} while the path carries {actual}. A build refuses "
              "such a project BEFORE compiling – rename the directories (case matters) or the "
              "descriptor.",
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

# A language identifier: a letter (capital - the standard requires that), then letters and digits.
_IDENTIFIER_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_KEY_RE = re.compile(r"(?m)^([^\s#:][^:\n]*):")

# Presentation properties and what each of them is per the standard.
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


def _pair(data: dict, name: str) -> tuple[object, str]:
    """(value, the key as the FILE spells it) of a project property, either spelling.

    A project descriptor may be written in English (`Vendor`, `Version`, `Name`) - such a
    project compiles as it is - so every rule here reads both. The
    pair comes from the metamodel, never from a guess; without the data the English key is
    simply unknown and the rules stay as Russian-only as before.
    """
    if name in data:
        return data[name], name
    english = metamodel.english_name(name)
    if english and english in data:
        return data[english], english
    return None, name


def _project(source: SourceFile) -> dict | None:
    """The parsed project description, or None.

    A project has no ВидЭлемента (it is the root itself); it is recognized by the Поставщик +
    Версия pair: this way the rule fires neither on an element description nor on an unrelated
    yaml of the repository.
    """
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict) or object_kind(data):
        return None
    if _pair(data, "Поставщик")[0] is None or _pair(data, "Версия")[0] is None:
        return None
    return data


def _key_pos(source: SourceFile, key: str) -> tuple[int, int]:
    """Line and column of a top-level key (or the start of the file if the key is absent)."""
    lm = linemap(source)
    for m in _KEY_RE.finditer(source.text):
        if m.group(1).strip() == key:
            return lm.linecol(m.start(1))
    return 1, 1


@rule("project/identifier", "project/identifier.title", "A", severity=Severity.WARNING)
def identifier(source: SourceFile) -> Iterable[Diagnostic]:
    """Имя and Поставщик are identifiers starting with a capital (КабинетСотрудника, not site)."""
    data = _project(source)
    if data is None:
        return
    for prop in ("Поставщик", "Имя"):
        value, key = _pair(data, prop)
        if not isinstance(value, str) or not value:
            continue  # an empty value is a different check, done by the platform
        if _IDENTIFIER_RE.match(value):
            continue
        line, col = _key_pos(source, key)
        yield Diagnostic(
            source.rel, line, col, "project/identifier", Severity.WARNING,
            i18n.t("project/identifier.bad", prop=i18n.name(prop), value=value),
        )


@rule("project/presentation", "project/presentation.title", "A", severity=Severity.WARNING)
def presentation(source: SourceFile) -> Iterable[Diagnostic]:
    """Представление and ПредставлениеПоставщика are filled in: Имя and Поставщик come from them."""
    data = _project(source)
    if data is None:
        return
    for prop, what in PRESENTATIONS.items():
        value, key = _pair(data, prop)
        if isinstance(value, str) and value.strip():
            continue
        anchor = key if key in data else _pair(data, "Имя")[1]
        line, col = _key_pos(source, anchor)
        yield Diagnostic(
            source.rel, line, col, "project/presentation", Severity.WARNING,
            i18n.t("project/presentation.missing", prop=i18n.name(prop), what=i18n.t(what)),
        )


@rule("project/version", "project/version.title", "A", severity=Severity.WARNING)
def version(source: SourceFile) -> Iterable[Diagnostic]:
    """Версия is three numbers A.B.C: 1.0 does not say what changed - compatibility or fixes."""
    data = _project(source)
    if data is None:
        return
    raw, key = _pair(data, "Версия")
    value = str(raw) if raw is not None else ""
    if _VERSION_RE.match(value):
        return
    parts = [p for p in re.split(r"[.\s]+", value) if p.isdigit()]
    suggestion = ".".join((parts + ["0", "0", "0"])[:3]) if parts else "1.0.0"
    line, col = _key_pos(source, key)
    yield Diagnostic(
        source.rel, line, col, "project/version", Severity.WARNING,
        i18n.t("project/version.bad", value=value, suggestion=suggestion),
    )


@rule(
    "project/path-matches-descriptor", "project/path-matches-descriptor.title", "A",
    severity=Severity.ERROR,
)
def path_matches_descriptor(source: SourceFile) -> Iterable[Diagnostic]:
    """The directories around Проект.yaml must spell the vendor and the name of the descriptor.

    A build packs the project files under `{vendor}/{name}/...` taken from the descriptor and
    demands the same layout on disk, so a mismatch is refused before the sources ever reach the
    compiler – and the symptom (a build error about a layout) looks like nothing else. Renaming
    a project therefore means renaming the directories too.

    Case matters: `acme/tasks` under a descriptor saying `Acme`/`Tasks` is refused just as a
    different name would be. A file whose path has no two parent directories (a single file
    linted out of its tree) is skipped - there is nothing to compare against.
    """
    data = _project(source)
    if data is None:
        return
    parent = source.path.parent
    if not parent.name or not parent.parent.name:
        return
    for prop, actual in (("Имя", parent.name), ("Поставщик", parent.parent.name)):
        value, key = _pair(data, prop)
        if not isinstance(value, str) or not value:
            continue  # an empty descriptor value is checked by the platform, not here
        if value == actual:
            continue
        line, col = _key_pos(source, key)
        yield Diagnostic(
            source.rel, line, col, "project/path-matches-descriptor", Severity.ERROR,
            i18n.t(
                "project/path-matches-descriptor.mismatch",
                expected=f".../{_pair(data, 'Поставщик')[0]}/{_pair(data, 'Имя')[0]}",
                actual=f".../{parent.parent.name}/{parent.name}",
            ),
        )
        return  # one finding per file: both halves are the same mismatch
