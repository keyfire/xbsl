"""Guard: the English-facing documents must spell platform names in English.

The platform is bilingual - a metadata name carries an English spelling of its own
(`Environment`, `OnServer`, `Group`, `Tooltip`), and the English documents are expected to use
it, the way the rule table already does for `Query{...}`, `Environment` and `@OnServer`. The
Russian spellings belong in the `.ru` twins.

Kept by hand, this drifts with every wave of new rules: two waves in a row shipped table rows
reading `Группа`/`Высота`/`Ширина`, `Подсказка`, `Закрыть()`/`ПередЗакрытием` and
`СтрокаДинамическогоСписка<Форма.Тип>` into the English table, and `Ид`/`Обработчик`/`Имя`
into the settings strings the VS Code UI shows. Reviewing for it costs attention on every
release and fails silently when the attention goes elsewhere; a test does not.

Three things are legitimately Cyrillic in an English text and are allowed here:

  * a file name the platform fixes in Russian for projects of EITHER language - `Проект.yaml`,
    `Проект.xbsl`, `Подсистема.yaml`, `<Object>.Объект.xbsl` (see `demo-en/`, an
    English-language project whose descriptor is still `Проект.yaml`); there is no English form
    to use instead;
  * a single Cyrillic letter, which is the subject itself rather than a name: the escape
    letters of a string literal and the letter `ё` that `naming/yo` is about;
  * a link to the Russian twin of the document.

The changelogs are deliberately out of scope: their entries explain what the platform calls a
thing in each language ("`Type` is the English of both `Тип` and `ТипЭлементаПроекта`"), so
both spellings have to appear on the same line, and a rule that told those apart from a defect
would need the term dictionary - which a public checkout does not have.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

ENGLISH_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "docs/RULES.md",
    "docs/GUIDE.md",
    "docs/index.md",
    "editors/vscode/README.md",
    "editors/vscode/package.nls.json",
]

_CYRILLIC = re.compile("[Ѐ-ӿԀ-ԯ]+")
# A link or a label pointing at the Russian twin of the document.
_RUSSIAN_TWIN = re.compile(r"\.ru\.(md|json)|Русский")
# A name the platform fixes in Russian whatever the project's language.
_PLATFORM_FILENAME = re.compile(r"[Ѐ-ӿ]+\.(yaml|xbsl|xbql)\b")


def _offenders(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if _RUSSIAN_TWIN.search(line):
            continue
        rest = _PLATFORM_FILENAME.sub(" ", line)
        words = [w for w in _CYRILLIC.findall(rest) if len(w) > 1]
        if words:
            found.append((number, " ".join(sorted(set(words)))))
    return found


@pytest.mark.parametrize("name", ENGLISH_FILES)
def test_english_document_has_no_russian_names(name: str):
    path = ROOT / name
    assert path.exists(), f"{name}: файла нет – поправьте список ENGLISH_FILES"
    problems = _offenders(path.read_text(encoding="utf-8"))
    assert not problems, (
        f"{name}: русские написания имён платформы в английском документе – возьмите "
        f"английские из terms (`terms.common_english`):\n"
        + "\n".join(f"  строка {n}: {w}" for n, w in problems)
    )


def test_guard_notices_a_russian_name():
    """The twin of the checks above: a defect of the shape they look for is caught, so their
    silence means the documents are clean and not that the pattern matches nothing."""
    assert _offenders("| `Группа` with `Высота` |") == [(1, "Высота Группа")]


def test_guard_allows_the_legitimate_cases():
    assert _offenders("Open application module (Проект.xbsl)") == []
    assert _offenders("valid are `\\н \\в \\т` and the Latin spellings") == []
    assert _offenders("[Русский](CHANGELOG.ru.md) - the Russian twin") == []
