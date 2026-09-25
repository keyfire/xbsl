"""The project translation dictionary: the project's OWN names and comments.

Platform tokens translate by the dataset (platform_map.py); everything the PROJECT named -
objects, methods, variables, localization keys, resource files - and every comment line is
translated by people, and this module is where their work lives. Three planes:

- `tokens`: one exact identifier to one exact identifier ("Задачи" -> Tasks). Whole names,
  not words: the word order of an English name is the reverse of the Russian one, and the parts
  of a Russian name are declined, so gluing per-word translations produces calques. A
  resource file is entered by its stem ("Значок" -> Icon for the svg of the same name).
- `phrases`: one comment line to its translation, the text after `//`/`#` trimmed. Per line
  rather than per block: an edit next to a line does not invalidate it, and one entry
  serves every repetition.
- `literals`: one STRING LITERAL to its translation. The KEY and the VALUE are both the text
  between the quotes exactly as the source writes it, escaping included: an inner quote is
  `\"`, a backslash is `\\`. One escaping, the one the author sees in the code, and never a
  second on top of it - and the price of that convention is a check, so the value is refused
  on load unless it really is a literal body (see `literal_body_error`). A literal is data,
  and the translator never guesses at data - but part of that data is NAMES written as
  strings (a settings key, a field of a contract) and part is a sentence a person reads. This
  plane is where the project says, one literal at a time, which is which; what it does not
  name stays as written and is reported. An interpolation belongs to the key and to the value
  as the source spells it - the code inside it is translated by the ordinary pass, so the
  author of an entry does not have to know the English spelling of a name.

A fourth section, `terms`, sits next to the three planes but is not one of them: a short
"Russian term -> English" list that names how the project's own vocabulary is spelled. A term
is a hint for the external translation service and a spelling rule for the name it builds from
the service's prose - never a translation record on its own, so it feeds no plan and is never
counted toward coverage.

The dictionary is a directory of yaml files (or one file), so filling it is dropping a
completed stub next to the existing ones; a key translated differently in two places - two
files, or twice in one file - is refused, and the refusal names every such key at once with
the file and the line of each place (see `collisions`). Discovery walks up from the project
root for a `xbsl-translation` directory or a `xbsl-translation.yaml` file - the dictionary
lives in the repository, outside the sources it describes, and never ships inside an assembly.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from xbsl import dataset, i18n
from xbsl.translation import platform_map

try:
    import yaml

    _HAVE_YAML = True
except ImportError:  # pragma: no cover
    _HAVE_YAML = False

# libyaml (CSafeLoader) reads the same YAML an order of magnitude faster, and the dictionary of
# a real project is megabytes of it - the editor panel used to spend more than a second per run
# on the pure-Python loader alone, once per process and three processes per refresh. The pure
# loader stays as the fallback for builds without libyaml.
_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader) if _HAVE_YAML else None

MESSAGES = {
    "translate.dictionary.three-way": {
        "ru": "трехстороннее слияние словаря неоднозначно для {name}; согласуйте изменения обеих веток",
        "en": "the dictionary three-way merge is ambiguous for {name}",
    },
    "translate.dictionary.no-yaml": {
        "ru": "для чтения словаря нужен пакет pyyaml",
        "en": "reading a dictionary requires the pyyaml package",
    },
    "translate.dictionary.not-found": {
        "ru": "словарь не найден: {path}",
        "en": "dictionary not found: {path}",
    },
    "translate.dictionary.not-discovered": {
        "ru": "словарь не найден рядом с {root}: ожидается каталог {dir} или файл {file} в этом"
              " каталоге либо в одном из родительских – укажите каталог проекта (с дескриптором"
              " проекта), рядом с которым лежит словарь",
        "en": "no dictionary found next to {root}: an {dir} directory or an {file} file is"
              " expected there or in one of its parent directories - pass the project directory"
              " (the one with the project descriptor) the dictionary sits next to",
    },
    "translate.dictionary.found-below": {
        "ru": "; ниже {root} словарь есть – {found}: каталог проекта лежит рядом с ним",
        "en": "; a dictionary sits below {root} - {found}: the project directory is next to it",
    },
    "translate.dictionary.bad-file": {
        "ru": "{path}: файл словаря не читается: {error}",
        "en": "{path}: the dictionary file does not parse: {error}",
    },
    "translate.dictionary.bad-version": {
        "ru": "{path}: неподдерживаемая версия словаря {version} (движок знает 1)",
        "en": "{path}: unsupported dictionary version {version} (the engine knows 1)",
    },
    "translate.dictionary.language-mismatch": {
        "ru": "{path}: язык словаря '{language}' не совпадает с '{expected}' из соседнего файла",
        "en": "{path}: the dictionary language '{language}' differs from '{expected}' of a sibling file",
    },
    "translate.dictionary.conflicts": {
        "ru": "ключей, переведённых по-разному в нескольких местах: {count} (каждая строка ниже –"
              " секция, ключ и перевод в каждом месте, файл:строка; оставьте одно значение)",
        "en": "keys translated differently in several places: {count} (each line below is the"
              " section, the key and the translation at every place, file:line; keep one value)",
    },
    "translate.dictionary.bad-token-value": {
        "ru": "{path}: перевод токена '{key}' не является латинским идентификатором: '{value}'",
        "en": "{path}: the translation of token '{key}' is not a Latin identifier: '{value}'",
    },
    "translate.dictionary.keyword-value": {
        "ru": "{path}: перевод токена '{key}' совпадает с ключевым словом языка: '{value}'",
        "en": "{path}: the translation of token '{key}' collides with a language keyword: '{value}'",
    },
    "translate.dictionary.bad-section": {
        "ru": "{path}: секция '{section}' должна быть соответствием строк",
        "en": "{path}: the '{section}' section must be a string-to-string mapping",
    },
    "translate.dictionary.batch-not-mapping": {
        "ru": "под секцией {section} должны стоять пары \"ключ: значение\"",
        "en": "the {section} section needs \"key: value\" pairs under it",
    },
    "translate.dictionary.batch-not-text": {
        "ru": "секция {section}, строка {line}: ключ и значение – тексты, а здесь список или "
              "соответствие",
        "en": "section {section}, line {line}: a key and a value are texts, and here stands a "
              "list or a mapping",
    },
    "translate.dictionary.stub-literals-note": {
        "ru": "Ключ и перевод – текст между кавычками ровно так, как он написан в исходнике:"
              "\nкавычка внутри – \\\", обратный слеш – \\\\, перенос строки – \\н."
              "\nПеревод проверяется как тело строкового литерала и негодный отвергается.",
        "en": "The key and the translation are the text between the quotes exactly as the"
              "\nsource writes it: an inner quote is \\\", a backslash is \\\\, a line break is \\n."
              "\nThe translation is checked as a string-literal body and a bad one is refused.",
    },
    "translate.dictionary.bad-literal-value": {
        "ru": "{path}: перевод литерала '{key}' не годится телом строкового литерала XBSL: {reason}",
        "en": "{path}: the translation of literal '{key}' is not a valid XBSL string-literal body: {reason}",
    },
    "translate.dictionary.bad-literal-key": {
        "ru": "{path}: ключ литерала '{key}' не годится телом строкового литерала XBSL: {reason}."
              " Ключ пишут ровно так, как текст стоит в исходнике между кавычками",
        "en": "{path}: the literal key '{key}' is not a valid XBSL string-literal body: {reason}."
              " A key is written exactly as the text stands between the quotes in the source",
    },
    "translate.dictionary.literal.quote": {
        "ru": "кавычка закрывает литерал раньше времени – внутри её пишут как \\\"",
        "en": "a quote ends the literal early - inside one it is written as \\\"",
    },
    "translate.dictionary.literal.dangling": {
        "ru": "обратный слеш в конце: он съест закрывающую кавычку – сам слеш пишут как \\\\",
        "en": "a trailing backslash: it eats the closing quote - a backslash itself is written as \\\\",
    },
    "translate.dictionary.literal.escape": {
        "ru": "неизвестная управляющая последовательность '\\{char}'; литерал знает"
              " \\\\ \\\" \\% \\$, перевод строки \\н (\\n), возврат каретки \\в (\\r),"
              " табуляцию \\т (\\t) и код Unicode \\юЧИСЛО (\\uЧИСЛО)",
        "en": "unknown escape sequence '\\{char}'; a literal knows"
              " \\\\ \\\" \\% \\$, the line break \\n (\\н), the carriage return \\r (\\в),"
              " the tab \\t (\\т) and the Unicode code point \\uNUMBER (\\юNUMBER)",
    },
    "translate.dictionary.literal.unicode": {
        "ru": "за '\\{char}' должен идти код символа десятичным числом",
        "en": "'\\{char}' must be followed by a code point written in decimal",
    },
    "translate.dictionary.literal.newline": {
        "ru": "перевод строки: значение занимает ровно одну строку исходника, перенос пишут как \\н",
        "en": "a line break: the value stands on exactly one source line, a break is written as \\n",
    },
    "translate.dictionary.literal.shape": {
        "ru": "лексер читает этот текст не как одно строковое тело – проверьте"
              " интерполяции %{{...}} и ${{...}}",
        "en": "the lexer does not read this text as one string body - check the"
              " %{{...}} and ${{...}} interpolations",
    },
}
i18n.register(MESSAGES)


class DictionaryError(Exception):
    """A dictionary that cannot be loaded (broken yaml, conflicting entries)."""


#: The conventional dictionary location, discovered upward from the project root.
DICTIONARY_DIR = "xbsl-translation"
DICTIONARY_FILE = "xbsl-translation.yaml"

#: The target of a token entry: a Latin identifier; a dash is tolerated for resource file
#: stems (their names are file names, not code), it never appears in a code identifier.
_TOKEN_VALUE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

#: What a backslash may open inside a string literal ("Управляющие последовательности" of the
#: platform documentation): the backslash itself, the quote, the two interpolation openers and
#: the three control characters. The language spells its words in two alphabets and the sources
#: carry both letters for one meaning - `\н` and `\n` are the same line break - so both alphabets
#: answer here. Only in LOWER case, though: an English sentence that carries a path (`C:\New`)
#: is exactly what this gate exists to catch, and reading `\N` as an escape would wave it through.
_LITERAL_ESCAPES = frozenset('\\"%$' + "нвтnrt")

#: The escape that spells a code point: `\ю` (`\u`) and a DECIMAL number after it.
_LITERAL_UNICODE_ESCAPES = frozenset("юu")


def literal_body_error(text: str) -> str:
    """Why `text` cannot stand between the quotes of a string literal; "" when it can.

    An entry of the literals plane writes its key and its value the way the SOURCE writes
    them - with the escaping the code carries - so that the author escapes once, where they
    see it, and never a second time on top of that. The price of the convention is this
    check: the pass pastes the value between two quotes, so the value has to BE a literal
    body, or the paste ends the literal early and the module stops compiling. Three ways to
    end it early, all of them ordinary in a real dictionary:

    - a quote of its own (`Не заполнено поле "Наименование"` is the shape of half the messages
      a project writes, and the source spells it `\\"`);
    - a backslash with nothing to escape - the last one eats the closing quote;
    - a line break - the pass rewrites ONE span of ONE line, and a value arriving on two is a
      different string anyway (a multi-line literal keeps the indentation of its lines).

    The character scan names the reason; the lexer then reads `"<text>"` back as the final
    word, which is what catches an unbalanced `%{...}` - a fourth way to swallow the quote
    that no per-character rule sees.
    """
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            return i18n.t("translate.dictionary.literal.quote")
        if char in "\r\n":
            return i18n.t("translate.dictionary.literal.newline")
        if char != "\\":
            index += 1
            continue
        if index + 1 >= len(text):
            return i18n.t("translate.dictionary.literal.dangling")
        letter = text[index + 1]
        if letter in _LITERAL_UNICODE_ESCAPES:
            digits = index + 2
            while digits < len(text) and text[digits] in "0123456789":
                digits += 1
            if digits == index + 2:
                return i18n.t("translate.dictionary.literal.unicode", char=letter)
            index = digits
            continue
        if letter not in _LITERAL_ESCAPES:
            return i18n.t("translate.dictionary.literal.escape", char=letter)
        index += 2
    if not _reads_back_as_one_literal(text):
        return i18n.t("translate.dictionary.literal.shape")
    return ""


def _reads_back_as_one_literal(text: str) -> bool:
    """Does the lexer read `"<text>"` as one closed string and nothing else?

    The lexer is the authority on where a literal ends - the same code that reads the sources
    the pass rewrites - so the last word about a value belongs to it rather than to a rule
    written twice.
    """
    from xbsl import lexer

    toks = [tok for tok in lexer.tokenize(f'"{text}"') if tok.kind != "EOF"]
    if len(toks) != 1:
        return False
    only = toks[0]
    return (
        only.kind == "STRING"
        and not only.flags.get("unterminated")
        and only.start == 0
        and only.end == len(text) + 2
    )


@dataclass
class Dictionary:
    """The merged content of every dictionary file, ready for lookups."""

    language: str = "en"
    tokens: dict[str, str] = field(default_factory=dict)
    phrases: dict[str, str] = field(default_factory=dict)
    literals: dict[str, str] = field(default_factory=dict)
    #: A short list of project terms ("Russian term" -> "English"): a hint for the
    #: translation service and a spelling rule for the name builder, never a translation
    #: record of its own - it feeds no plan and counts toward no coverage.
    terms: dict[str, str] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()
    #: Non-fatal remarks gathered while loading (an empty value skipped, etc.).
    notes: list[str] = field(default_factory=list)
    #: The keys translated the SAME way in more than one place - two files, or twice in one -
    #: rows of `collisions`. Harmless to the lookups, so the load keeps them rather than
    #: refusing; listed because the second copy is what a person takes out
    #: (`xbsl translate --check-duplicates`).
    duplicates: list[dict] = field(default_factory=list)

    def token(self, name: str, *scopes: str) -> str | None:
        """The translation of a name, the scoped entry first.

        A key of a localized-strings dictionary lives in its OWN namespace, where the
        project may need a spelling the same word cannot have elsewhere: "Войти" is the
        key `SignIn` there while the bare word stays `Login` in code. Such an entry is
        written qualified - `<Dictionary>.<Key>: SignIn` - and wins over the plain one.

        More than one scope may fit one place, and then they are tried IN ORDER: after a dot
        the receiver as the source writes it comes first - `Event.Ссылка: Link` speaks about
        that variable - and the type its declaration names second: `JsonRoot.Услуги: Offerings`
        speaks about every field of that structure, whatever the variable holding it is called.
        """
        scoped = self.scoped_token(name, *scopes)
        if scoped is not None:
            return scoped
        return self.tokens.get(name)

    def scoped_token(self, name: str, *scopes: str) -> str | None:
        """The translation of a name from a QUALIFIED entry alone, the scopes tried in order.

        What `token` reads first, on its own: a caller that has a better answer than the plain
        entry for one receiver (the reference member of a project facet, spelled by the
        platform's facet table) still lets an entry written about THAT receiver win.
        """
        for scope in scopes:
            if scope:
                scoped = self.tokens.get(f"{scope}.{name}")
                if scoped is not None:
                    return scoped
        return None

    def phrase(self, text: str) -> str | None:
        return self.phrases.get(text)

    def literal(self, text: str) -> str | None:
        """The translation of a string literal, keyed by its text without the quotes."""
        return self.literals.get(text)

    @property
    def empty(self) -> bool:
        return not self.tokens and not self.phrases and not self.literals


def discover(start: Path) -> Path | None:
    """The dictionary next to (or above) the project: a directory or a single file.

    Walks up from `start` so the dictionary can live at the repository root while the
    project sits in a subdirectory - the same shape as a lint baseline.
    """
    current = start if start.is_dir() else start.parent
    for folder in (current, *current.parents):
        as_dir = folder / DICTIONARY_DIR
        if as_dir.is_dir():
            return as_dir
        as_file = folder / DICTIONARY_FILE
        if as_file.is_file():
            return as_file
    return None


#: How many levels below a start directory found_below() looks: `<repository>/<vendor>/` +
#: DICTIONARY_DIR is two levels under the repository root, and that root is the first one a
#: caller reaches for; a bound keeps a wrong root high up in the tree from becoming a disk walk.
HINT_DEPTH = 3


def found_below(start: Path, depth: int = HINT_DEPTH) -> list[Path]:
    """Dictionaries UNDER `start` - what discover() never sees, since it only walks up.

    The hint for a root passed one level too high. Hidden directories are skipped, symlinked
    ones are not followed, and the search stops at `depth` levels.
    """
    out: list[Path] = []
    level = [start]
    for _ in range(depth):
        deeper: list[Path] = []
        for folder in level:
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda entry: entry.name)
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.name == DICTIONARY_DIR and entry.is_dir(follow_symlinks=False):
                    out.append(Path(entry.path))
                elif entry.name == DICTIONARY_FILE and entry.is_file(follow_symlinks=False):
                    out.append(Path(entry.path))
                elif entry.is_dir(follow_symlinks=False):
                    deeper.append(Path(entry.path))
        level = deeper
    return out


def missing_message(start: Path) -> str:
    """Why discover(start) came back empty, spelled from the constants the search itself uses.

    Names the root, the two spellings looked for there and above, and - when one sits BELOW
    the root - where it is. The case this exists for is the repository root passed instead of
    the project directory: the walk-up never looks down, and an empty dictionary read as
    "every name is a gap" - a report that looked like work.
    """
    root = start if start.is_dir() else start.parent
    text = i18n.t(
        "translate.dictionary.not-discovered",
        root=root, dir=DICTIONARY_DIR, file=DICTIONARY_FILE,
    )
    below = found_below(root)
    if below:
        text += i18n.t(
            "translate.dictionary.found-below",
            root=root, found=", ".join(str(path) for path in below),
        )
    return text


#: The sections of a dictionary file, in the order the reports list them - the three planes
#: and the terms. Each is an attribute of `Dictionary` under the same name.
SECTIONS = ("tokens", "phrases", "literals", "terms")


class Pair(NamedTuple):
    """One pair as a file declares it: the key, the translation, the 1-based line of the key."""

    key: str
    value: str
    line: int


#: The validated content of one dictionary file: section -> the pairs in the order the file
#: declares them. A key the file declares twice stands here twice, each time with its line:
#: yaml keeps the last reading alone and says nothing about the first, so a mapping of the
#: file could never show the repeat. Empty values (stubs still being filled) are already
#: dropped, so every pair here is a translation.
Sections = dict[str, list[Pair]]


def load(path: Path) -> Dictionary:
    """Load a dictionary from a file or from every yaml file of a directory.

    Every file is read and checked before anything is merged, and the keys translated
    differently in two places are refused in ONE error naming all of them. Refusing at the
    first one made the fix a loop: take a duplicate out, load again, meet the next - once per
    key, on a merge that had brought ten of them in at a time. A place is a file and a line, so
    a key one file declares twice with two translations is refused the same way: yaml keeps
    the second reading without a word, and which one the author meant is not the load's call.
    The other refusals (a file that does not parse, a broken token value) still stop at the
    first, as before: they are one file's fault, and the file is named.
    """
    if not _HAVE_YAML:
        raise DictionaryError(i18n.t("translate.dictionary.no-yaml"))
    files = _files_of(path)
    out = Dictionary(sources=tuple(files))
    language: str | None = None
    parsed: list[tuple[str, Sections]] = []
    for file in files:
        data, declared = _parse(file, _text_of(file))
        file_language = str(data.get("language") or "en")
        if language is None:
            language = file_language
        elif file_language != language:
            raise DictionaryError(i18n.t(
                "translate.dictionary.language-mismatch",
                path=file, language=file_language, expected=language,
            ))
        parsed.append((str(file), _sections(file, data, declared, out.notes)))
    conflicts, out.duplicates = collisions(parsed)
    if conflicts:
        raise DictionaryError(conflicts_message(conflicts))
    for _label, sections in parsed:
        for section, pairs in sections.items():
            getattr(out, section).update((key, value) for key, value, _line in pairs)
    out.language = language or "en"
    return out


def read_sections(path: Path) -> list[tuple[str, Sections]]:
    """(name, validated sections) of every dictionary file, in the order `load` reads them.

    The reading behind `load` without the merge - what a check of the places against each
    other starts from. The name is the file's path relative to the dictionary (POSIX slashes),
    which is how the same file read from a git ref is matched to it (see `overlay`); the
    single-file dictionary is named by its file name. A file that does not load stops the
    reading with the same error `load` would raise for it.
    """
    if not _HAVE_YAML:
        raise DictionaryError(i18n.t("translate.dictionary.no-yaml"))
    base = path if path.is_dir() else path.parent
    return [
        (file.relative_to(base).as_posix(), sections_of(file, _text_of(file)))
        for file in _files_of(path)
    ]


def sections_of(label: str | Path, text: str, notes: list[str] | None = None) -> Sections:
    """The validated sections of one dictionary file given as TEXT.

    `label` names the file in the refusals - a path, or `ref:name` for a copy read out of git.
    The keyword notes of the tokens plane land in `notes` when a list is given.
    """
    data, declared = _parse(label, text)
    return _sections(label, data, declared, [] if notes is None else notes)


def collisions(files: Sequence[tuple[str, Sections]]) -> tuple[list[dict], list[dict]]:
    """The keys declared in more than one place: (conflicts, duplicates).

    A place is a file and a line, so a key one file declares twice counts the way a key two
    files declare does. A conflict is a key translated DIFFERENTLY in two places - what the
    load refuses. A duplicate is a key translated the same way: the lookups do not care, and
    it is listed because the second copy is what a person takes out. A key with three readings,
    two of them alike, is a conflict. The same key in two sections is two keys: the planes
    answer different questions. A row is
    `{"section", "key", "places": [{"file", "line", "value"}, ...]}`, the places in file order
    and within a file in line order; the rows come in section order, then by key.
    """
    places: dict[tuple[str, str], list[dict]] = {}
    for name, sections in files:
        for section, pairs in sections.items():
            for key, value, line in pairs:
                places.setdefault((section, key), []).append(
                    {"file": name, "line": line, "value": value})
    conflicts: list[dict] = []
    duplicates: list[dict] = []
    ordered = sorted(places.items(), key=lambda kv: (SECTIONS.index(kv[0][0]), kv[0][1]))
    for (section, key), seen in ordered:
        if len(seen) < 2:
            continue
        row = {"section": section, "key": key, "places": seen}
        (conflicts if len({place["value"] for place in seen}) > 1 else duplicates).append(row)
    return conflicts, duplicates


def overlay(
    working: Sequence[tuple[str, Sections]], other: Sequence[tuple[str, Sections]], prefix: str,
) -> list[tuple[str, Sections]]:
    """The working tree's files plus what `other` - the same dictionary at a git ref - adds.

    A file present on both sides is ONE file: a key the working tree spells differently is
    that file's own edit, not a collision, and only the keys the working tree's copy does not
    carry come in - under `prefix:name`, so a report says where the second reading lives. A
    file `other` has and the working tree does not comes in whole, the same way. This is what
    lets a branch see the collision it would bring to the target branch BEFORE the merge: the
    keys the target added since the fork, in files of its own or in the shared ones.

    A key comes in with every place the ref's copy declares it at, so a key that copy declares
    twice is judged too. A key the working tree's copy carries stays out however often the
    ref's copy repeats it - the rule above, read the same way for one declaration or for two.
    """
    known = dict(working)
    out = list(working)
    for name, sections in other:
        mine = known.get(name) or {}
        extra: Sections = {}
        for section, pairs in sections.items():
            have = {key for key, _value, _line in mine.get(section) or ()}
            added = [pair for pair in pairs if pair[0] not in have]
            if added:
                extra[section] = added
        if extra:
            out.append((f"{prefix}:{name}", extra))
    return out


def three_way(working: Sequence[tuple[str, Sections]], base: Sequence[tuple[str, Sections]],
              other: Sequence[tuple[str, Sections]], prefix: str, *,
              working_renames: dict[str, str] | None = None,
              other_renames: dict[str, str] | None = None) -> list[tuple[str, Sections]]:
    """Project translated keys, preserving both sides of a real value conflict.

    Line numbers are locations, not edits. Every selected pair keeps its original location;
    target records are labelled with the ref instead of pretending to exist on disk.
    File deletion versus modification cannot be expressed as a duplicate, so it is refused.
    """
    wr, tr = working_renames or {}, other_renames or {}
    w, b, t = dict(working), dict(base), dict(other)
    for identity in set(wr) & set(tr):
        if wr[identity] != tr[identity]:
            raise DictionaryError(i18n.t("translate.dictionary.three-way", name=identity))
    for renames, side, opposite, opposite_renames in ((wr, w, t, tr), (tr, t, w, wr)):
        for old, new in renames.items():
            if (old not in b or new not in side or new in b
                    or (new in opposite and opposite_renames.get(old) != new)):
                raise DictionaryError(i18n.t("translate.dictionary.three-way", name=new))

    def records(sections):
        grouped = {}
        for section, pairs in (sections or {}).items():
            for pair in pairs:
                grouped.setdefault((section, pair[0]), []).append(pair)
        return grouped

    def values(pairs):
        return [pair[1] for pair in pairs]

    def semantic(grouped):
        return {key: values(pairs) for key, pairs in grouped.items()}

    ours: dict[str, Sections] = {}
    theirs: dict[str, Sections] = {}

    def keep(destination, name, section, pairs):
        if pairs:
            destination.setdefault(name, {}).setdefault(section, []).extend(pairs)

    identities = set(b) | (set(w) - set(wr.values())) | (set(t) - set(tr.values()))
    for identity in sorted(identities):
        wn, tn = wr.get(identity, identity), tr.get(identity, identity)
        ws, bs, ts = w.get(wn), b.get(identity), t.get(tn)
        wg, bg, tg = records(ws), records(bs), records(ts)
        if bs is not None and ((ws is None and ts is not None and semantic(tg) != semantic(bg))
                               or (ts is None and ws is not None and semantic(wg) != semantic(bg))):
            raise DictionaryError(i18n.t("translate.dictionary.three-way", name=identity))
        for key in sorted(set(wg) | set(bg) | set(tg)):
            section, name = key
            wp, bp, tp = wg.get(key, []), bg.get(key, []), tg.get(key, [])
            if values(wp) == values(tp):
                keep(ours, wn, section, wp)
            elif values(tp) == values(bp):
                keep(ours, wn, section, wp)
            elif values(wp) == values(bp):
                keep(theirs, tn, section, tp)
            elif not wp or not tp:
                raise DictionaryError(i18n.t("translate.dictionary.three-way", name=f"{identity}:{name}"))
            else:
                keep(ours, wn, section, wp)
                keep(theirs, tn, section, tp)
    return ([(name, ours[name]) for name in w if name in ours]
            + [(f"{prefix}:{name}", theirs[name]) for name in t if name in theirs])


def conflicts_message(conflicts: list[dict]) -> str:
    """The text of the refusal: the count, then one line per key with every place and value."""
    lines = [i18n.t("translate.dictionary.conflicts", count=len(conflicts))]
    lines.extend("  " + collision_line(row) for row in conflicts)
    return "\n".join(lines)


def collision_line(row: dict) -> str:
    """One conflict as a report line: the section, the key, then each place with its value."""
    places = "; ".join(f"{_place(place)} = '{place['value']}'" for place in row["places"])
    return f"[{row['section']}] {row['key']}: {places}"


def duplicate_line(row: dict) -> str:
    """One duplicate as a report line: the value once, since every place agrees on it."""
    places = ", ".join(_place(place) for place in row["places"])
    return f"[{row['section']}] {row['key']} = '{row['places'][0]['value']}': {places}"


def _place(place: dict) -> str:
    """`file:line` - the spelling an editor and a terminal open at the line."""
    return f"{place['file']}:{place['line']}"


def _files_of(path: Path) -> list[Path]:
    """The files a dictionary path stands for: every yaml under a directory, or the file."""
    if path.is_dir():
        return sorted(p for p in path.rglob("*.yaml") if p.is_file())
    if path.is_file():
        return [path]
    raise DictionaryError(i18n.t("translate.dictionary.not-found", path=path))


def _text_of(file: Path) -> str:
    try:
        return file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=file, error=exc)) from exc


#: The pairs of each section as the file declares them, before any check: (key, value, line),
#: the key and the value as the loader constructs them, in file order.
_Declared = dict[str, list[tuple[object, object, int]]]

#: The tag of a plain mapping. A section tagged otherwise (`!!set`) is not read pair by pair:
#: the loader constructs it whole, and `_sections` refuses what comes out.
_MAP_TAG = "tag:yaml.org,2002:map"


def _parse(label: str | Path, text: str) -> tuple[dict, _Declared]:
    """(the top-level values, the declared pairs of each section) of one file, version checked.

    One composition serves both, and the loader constructs every value exactly as `yaml.load`
    would - quoting, escapes and the explicit `? key` form are the parser's business. What
    differs is where the pairs of a section come from: the nodes, not the constructed mapping.
    A mapping holds a key once, so a key the file declared twice arrived with its last value
    alone, and the first place was gone before any check could look: yaml reports no repeat,
    and neither the load nor `--check-duplicates` saw a pair translated twice in one file. The
    nodes keep every pair and the line its key stands on. Reading the text again line by line
    would give the same, at the price of a second pass over the dictionary.

    A section head written twice in one file reads as one section holding the pairs of both
    blocks: the entries table reads such a file that way, and its writer adds to the first
    block, which yaml would drop. Every other top-level key lands among the top-level values as
    the loader constructs it, a section whose value is not a mapping included.
    """
    loader = _LOADER(text)
    data: object = None
    declared: _Declared = {}
    try:
        root = loader.get_single_node()
        if isinstance(root, yaml.MappingNode):
            data = {}
            loader.flatten_mapping(root)
            for key_node, value_node in root.value:
                name = loader.construct_object(key_node, deep=True)
                if isinstance(name, str) and name in SECTIONS \
                        and isinstance(value_node, yaml.MappingNode) and value_node.tag == _MAP_TAG:
                    loader.flatten_mapping(value_node)
                    pairs = declared.setdefault(name, [])
                    # Shallow, as the mapping constructor itself builds a mapping: a translation
                    # is a scalar, and `_sections` refuses a nested value whatever it holds.
                    constructed = loader.construct_pairs(value_node)
                    for (key, value), (pair_key, _pair_value) in zip(constructed, value_node.value):
                        pairs.append((key, value, pair_key.start_mark.line + 1))
                    continue
                if not isinstance(name, Hashable):
                    # The words and the error class `yaml.load` refuses such a key with.
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", root.start_mark,
                        "found unhashable key", key_node.start_mark)
                data[name] = loader.construct_object(value_node, deep=True)
        elif root is not None:
            data = loader.construct_document(root)
    except yaml.YAMLError as exc:
        raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=label, error=exc)) from exc
    finally:
        loader.dispose()
    data = data or {}
    if not isinstance(data, dict):
        raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=label, error="mapping expected"))
    version = data.get("version", 1)
    if version != 1:
        raise DictionaryError(i18n.t("translate.dictionary.bad-version", path=label, version=version))
    return data, declared


def batch_pairs(text: str, sections: Sequence[str]) -> tuple[dict[str, list[tuple[str, str]]], list[str]]:
    """The pairs of the given sections of a batch of edits, and every top-level key it holds.

    The loader and the node-by-node reading of `_parse`: the quoting, the escapes and the
    explicit `? key` form are the parser's business, a section head written in quotes is the
    same head, and a key the batch names twice keeps both of its pairs. Unlike a dictionary
    file, a batch keeps its empty values - an empty value removes an entry - and takes a scalar
    the loader would make a number or a truth value as the text it is written with: `Да: Yes`
    names a word. The version is not checked: a batch is not a dictionary file.

    Raises yaml.YAMLError when the text is not yaml and ValueError when a section holds
    anything but pairs of texts - the message names the section and the key.
    """
    loader = _LOADER(text)
    pairs: dict[str, list[tuple[str, str]]] = {}
    keys: list[str] = []
    try:
        root = loader.get_single_node()
        if not isinstance(root, yaml.MappingNode):
            return pairs, keys
        loader.flatten_mapping(root)
        for key_node, value_node in root.value:
            name = _batch_text(loader, key_node, "") if isinstance(key_node, yaml.ScalarNode) else "?"
            keys.append(name)
            if name not in sections:
                continue
            listed = pairs.setdefault(name, [])
            if isinstance(value_node, yaml.ScalarNode) and _batch_text(loader, value_node, name) == "":
                continue  # a head with nothing under it
            if not isinstance(value_node, yaml.MappingNode):
                raise ValueError(i18n.t("translate.dictionary.batch-not-mapping", section=name))
            loader.flatten_mapping(value_node)
            for pair_key, pair_value in value_node.value:
                listed.append((_batch_text(loader, pair_key, name),
                               _batch_text(loader, pair_value, name)))
    finally:
        loader.dispose()
    return pairs, keys


def _batch_text(loader, node, section: str) -> str:
    """One scalar of a batch as text: null is empty, anything else is the text as written."""
    if not isinstance(node, yaml.ScalarNode):
        raise ValueError(i18n.t("translate.dictionary.batch-not-text", section=section,
                                line=node.start_mark.line + 1))
    value = loader.construct_object(node)
    if value is None:
        return ""
    return value if isinstance(value, str) else node.value


def _sections(label: str | Path, data: dict, declared: _Declared, notes: list[str]) -> Sections:
    """The four sections of one parsed file, validated, the empty values dropped.

    Every declaration is checked, a repeated one included: the second line of a key is as much
    the file as the first. An empty value is a stub wherever it stands, so one written after a
    translation of the same key does not take the translation away.
    """
    out: Sections = {}
    for section in SECTIONS:
        if data.get(section) is not None:
            # The head is there and its value is not a mapping (an empty head reads as None).
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=label, section=section))
        raw = declared.get(section)
        if raw is None:
            continue
        pairs: list[Pair] = []
        for key, value, line in raw:
            if not isinstance(key, str) or not key:
                raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=label, section=section))
            if value is None or value == "":
                continue  # a stub still being filled - the key simply stays untranslated
            if not isinstance(value, str):
                raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=label, section=section))
            if section == "tokens":
                _validate_token(notes, label, key, value)
            elif section == "literals":
                _validate_literal(label, key, value)
            pairs.append(Pair(key, value, line))
        out[section] = pairs
    return out


def _validate_literal(file: str | Path, key: str, value: str) -> None:
    """Refuse an entry whose key or value would not survive being pasted between quotes.

    Both sides are checked, because both obey one convention: the key is the text the source
    already carries (a key that could not be a literal body names nothing and would sit in the
    dictionary as a silent dud), and the value is the text the pass writes back.
    """
    reason = literal_body_error(key)
    if reason:
        raise DictionaryError(i18n.t(
            "translate.dictionary.bad-literal-key", path=file, key=key, reason=reason,
        ))
    reason = literal_body_error(value)
    if reason:
        raise DictionaryError(i18n.t(
            "translate.dictionary.bad-literal-value", path=file, key=key, reason=reason,
        ))


def _validate_token(notes: list[str], file: str | Path, key: str, value: str) -> None:
    if not _TOKEN_VALUE_RE.match(value):
        raise DictionaryError(i18n.t(
            "translate.dictionary.bad-token-value", path=file, key=key, value=value,
        ))
    # A keyword-shaped name is legal in the metadata (the English demo project compiles an
    # attribute named `Step`), but a keyword-named VARIABLE is asking for trouble - so this
    # is a note for the report, not a refusal. A pair one file repeats word for word says it
    # once.
    if value.lower() in _keyword_targets():
        note = i18n.t("translate.dictionary.keyword-value", path=file, key=key, value=value)
        if note not in notes:
            notes.append(note)


@lru_cache(maxsize=1)
def _keyword_targets() -> frozenset[str]:
    """The English keywords, lowercased: the names a token value is noted for.

    Built once per data root. Built per pair, the set was built ten thousand times over the
    tokens of a live dictionary, and that came to about a sixth of the whole load.
    """
    return frozenset(en.lower() for en in platform_map.keyword_english().values())


dataset.register_reset(_keyword_targets.cache_clear)


#: Cache for the editor path: the rule loads the dictionary on every file check, and the same
#: directory answers from memory until one of its files changes. What "changes" means is a
#: digest of the bytes (see _digest).
_CACHE: dict[Path, tuple[tuple, Dictionary]] = {}


def _digest(path: Path) -> bytes:
    """A digest of the file's bytes - the stamp the project index is kept by.

    A modification time cannot answer the question the cache asks. The filesystem stamps whole
    ticks, so two writes in a row share one: out of two hundred pairs of consecutive writes
    into one file, measured on Windows, 151 came out with the same `st_mtime_ns`. In a
    long-lived MCP server an edit through `translate_set` and the lint that follows it then
    read the dictionary from before the edit. The bytes cannot be fooled, and the price is one
    read of files that are about to be read anyway when the digest says they moved.
    """
    try:
        return hashlib.blake2b(path.read_bytes(), digest_size=16).digest()
    except OSError:  # vanished between the walk and the read, and the next walk will say so
        return b""


#: Guards every read and write of `_CACHE`: the look that finds a dictionary stale and the
#: read that follows it have to run as one step, or two callers racing for the same directory
#: both find it stale and both parse it - megabytes of yaml on a real project. Re-entrant on
#: purpose, for the reason the index lock is (see translation/code.py): the read goes through
#: the platform data, data that changed under it drops every cache derived from it, and
#: `forget_cached` then asks for this very lock on the thread that already holds it.
_LOCK = threading.RLock()


#: Directories whose freshness has already been established during the current pass of the
#: engine. The stamp `_digest` takes reads the bytes of every dictionary file, and the rule
#: that asks for the dictionary asks once per checked file: on a project of 1267 sources with
#: a dictionary of 185 files that came to 234 395 reads and 83 of the 188 seconds of the run.
#: A pass takes the stamp at its start (`dataset.begin_pass`) and trusts it until the next one.
_FRESH: set[Path] = set()


def forget_cached() -> None:
    """Drop the kept dictionaries - the next `load_cached` reads the files again."""
    with _LOCK:
        _CACHE.clear()
        _FRESH.clear()


def _forget_freshness() -> None:
    """A new pass begins: the state of every dictionary is taken again (dataset hook)."""
    with _LOCK:
        _FRESH.clear()


dataset.register_pass(_forget_freshness)


# The load reads the platform data - a token value is checked against the English keywords
# (_keyword_targets), a literal is read by the lexer - so a dictionary must not outlive the
# pinned data root any more than the tables the rules build over the same data do.
dataset.register_reset(forget_cached)


def load_cached(path: Path) -> Dictionary:
    files = sorted(p for p in path.rglob("*.yaml")) if path.is_dir() else [path]
    with _LOCK:
        stamp = tuple((str(p), _digest(p)) for p in files)
        known = _CACHE.get(path)
        if known is not None and known[0] == stamp:
            return known[1]
        loaded = load(path)
        _CACHE[path] = (stamp, loaded)
        return loaded


def load_for_pass(path: Path) -> Dictionary:
    """The same dictionary, with its state taken once per pass of the engine.

    For a caller that asks per FILE while the answer can only change between passes: the rule
    `conventions/missing-translation` loads the dictionary for every source it checks, and the
    stamp `load_cached` takes reads the bytes of every dictionary file. An edit lands between
    passes - `translate_set` writes and the lint that follows it reads - so the pass that has
    already looked is allowed to trust what it saw.

    The lock is taken around both steps and `load_cached` takes it again from inside: that is
    what the re-entrant lock is for, and a plain one would deadlock here.
    """
    with _LOCK:
        known = _CACHE.get(path)
        if known is not None and path in _FRESH:
            return known[1]
        loaded = load_cached(path)
        _FRESH.add(path)
        return loaded


def _scalar(text: str) -> str:
    """One yaml scalar, quoted the safe way for a generated stub."""
    dumped = yaml.safe_dump(text, allow_unicode=True, default_flow_style=True, width=10**6)
    return dumped.strip().removesuffix("\n...").strip()


def write_stub(
    path: Path,
    missing_tokens: dict[str, dict],
    missing_phrases: dict[str, dict],
    language: str = "en",
    missing_literals: dict[str, dict] | None = None,
) -> None:
    """Write the untranslated remainder as a dictionary file with empty values.

    The stub IS a dictionary file: fill the values and drop it into the dictionary
    directory. Entries are ordered by frequency, each annotated with its count and first
    location; a token that names a resource file or collides with a platform spelling is
    annotated too, so the filler sees what they are naming. The literals section carries the
    Cyrillic string literals the code kept - a name written as a string next to a sentence
    meant for a person, which only the project can tell apart.
    """
    lines: list[str] = ["version: 1", f"language: {language}", ""]
    if missing_tokens:
        lines.append("tokens:")
        ordered = sorted(missing_tokens.items(), key=lambda kv: (-kv[1].get("count", 0), kv[0]))
        for name, info in ordered:
            notes = [f"{info.get('count', 0)}x", str(info.get("sample", ""))]
            if info.get("resource"):
                notes.append("resource file")
            lines.append(f"    # {', '.join(n for n in notes if n)}")
            lines.append(f"    {_scalar(name)}: \"\"")
        lines.append("")
    if missing_phrases:
        lines.append("phrases:")
        ordered = sorted(missing_phrases.items(), key=lambda kv: (-kv[1].get("count", 0), kv[0]))
        for text, info in ordered:
            notes = [f"{info.get('count', 0)}x", str(info.get("sample", ""))]
            lines.append(f"    # {', '.join(n for n in notes if n)}")
            lines.append(f"    {_scalar(text)}: \"\"")
        lines.append("")
    if missing_literals:
        for note in i18n.t("translate.dictionary.stub-literals-note").splitlines():
            lines.append(f"# {note}")
        lines.append("literals:")
        ordered = sorted(missing_literals.items(), key=lambda kv: (-kv[1].get("count", 0), kv[0]))
        for text, info in ordered:
            notes = [f"{info.get('count', 0)}x", str(info.get("sample", ""))]
            lines.append(f"    # {', '.join(n for n in notes if n)}")
            lines.append(f'    {_scalar(text)}: ""')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
