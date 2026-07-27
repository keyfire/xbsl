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

The second half of the file guards the strings the extension shows at RUNTIME - the message
argument of `vscode.l10n.t(...)`. The rule there is not "no Cyrillic on screen": a hint that
names a key must name the key the user will actually find in the sources, so over a Russian
project an English window is RIGHT to say `Имя`. What must not happen is a hint that hardcodes
one spelling - it then advises an English project of a key that is not in its files. The cure
is to make the hint parametric (`Rename ({0})`) and pass the spelling the project uses; the
guard therefore reads the MESSAGE only and never the arguments, which is exactly where a name
belongs. Cyrillic anywhere else in the sources - platform keys the parser matches, kind tables,
default values - is code and is not looked at.
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


# --- the runtime strings of the VS Code extension ----------------------------------------

EXTENSION_SOURCES = ROOT / "editors" / "vscode" / "src"

_L10N_CALL = re.compile(r"\bl10n\.t\(")
# A string literal of any of the three TypeScript flavours; the body is group 1, 2 or 3.
_TS_LITERAL = re.compile(
    r"\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'|`((?:[^`\\]|\\.)*)`", re.S
)


def _first_argument(source: str, start: int) -> str:
    """The text of the first argument of a call, `start` standing just past its `(`.

    Scanned rather than split on a comma: the message is often a concatenation broken over
    several lines, and commas inside nested calls, arrays and template holes are not argument
    separators.
    """
    depth = 0
    i = start
    while i < len(source):
        char = source[i]
        if char in "\"'`":
            quote, i = char, i + 1
            while i < len(source):
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    break
                i += 1
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return source[start:i]
            depth -= 1
        elif char == "," and depth == 0:
            return source[start:i]
        i += 1
    return source[start:]


def _hint_offenders(source: str) -> list[tuple[int, str]]:
    """Russian names hardcoded into the MESSAGE of an l10n.t call, with the line of the call."""
    found: list[tuple[int, str]] = []
    for call in _L10N_CALL.finditer(source):
        expression = _first_argument(source, call.end())
        message = " ".join(
            m.group(1) or m.group(2) or m.group(3) or "" for m in _TS_LITERAL.finditer(expression)
        )
        rest = _PLATFORM_FILENAME.sub(" ", message)
        words = [w for w in _CYRILLIC.findall(rest) if len(w) > 1]
        if words:
            found.append((source.count("\n", 0, call.start()) + 1, " ".join(sorted(set(words)))))
    return found


def test_extension_hints_have_no_hardcoded_russian_names():
    assert EXTENSION_SOURCES.is_dir(), "нет каталога исходников расширения – поправьте путь"
    problems: list[str] = []
    scanned = 0
    for path in sorted(EXTENSION_SOURCES.rglob("*.ts")):
        text = path.read_text(encoding="utf-8")
        scanned += len(_L10N_CALL.findall(text))
        for number, words in _hint_offenders(text):
            problems.append(f"  {path.relative_to(ROOT).as_posix()}:{number}: {words}")
    # Non-vacuity: a green run must mean the hints are clean and not that the walk found no
    # hints at all (a renamed folder, a switch to another localization helper).
    assert scanned > 100, f"подсказок найдено всего {scanned} – проверка ничего не смотрит"
    assert not problems, (
        "русские имена платформы зашиты в английские подсказки расширения – сделайте строку "
        "параметрической (`l10n.t(\"Rename ({0})\", nameKey)`) и передавайте написание, принятое "
        "в ПРОЕКТЕ (writesEnglishNames):\n" + "\n".join(problems)
    )


def test_hint_guard_notices_a_russian_name():
    """The twin of the check above: a defect of the shape it looks for is caught."""
    assert _hint_offenders('const a = vscode.l10n.t("Rename (Имя)");') == [(1, "Имя")]
    assert _hint_offenders('l10n.t(\n  "Container type (a Содержимое slot)"\n)') == [(1, "Содержимое")]


def test_hint_guard_allows_the_legitimate_cases():
    # The name is an ARGUMENT: the spelling follows the project, which is the whole point.
    assert _hint_offenders('vscode.l10n.t("Rename ({0})", hintName("Имя", english))') == []
    # A single Cyrillic letter is the subject of the sentence, not a name.
    assert _hint_offenders('vscode.l10n.t("An identifier, without the letter ё")') == []
    # A file name the platform fixes in Russian for a project of either language.
    assert _hint_offenders('vscode.l10n.t("Open application module (Проект.xbsl)")') == []
    # Cyrillic outside a hint is code - a platform key, a kind table, a default value.
    assert _hint_offenders('const KIND = "Справочник";') == []
