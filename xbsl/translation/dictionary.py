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
completed stub next to the existing ones; a key two files translate differently is refused,
and the refusal names every such key at once (see `collisions`). Discovery walks up from the
project root for a `xbsl-translation` directory or a `xbsl-translation.yaml` file - the
dictionary lives in the repository, outside the sources it describes, and never ships inside
an assembly.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from xbsl import i18n
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
        "ru": "ключей, переведённых по-разному в разных файлах: {count} (каждая строка ниже –"
              " секция, ключ и перевод в каждом файле; оставьте одно значение)",
        "en": "keys translated differently in different files: {count} (each line below is the"
              " section, the key and the translation in every file; keep one value)",
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
    #: The keys two files translate the SAME way - rows of `collisions`. Harmless to the
    #: lookups, so the load keeps them rather than refusing; listed because the second copy
    #: is what a person takes out (`xbsl translate --check-duplicates`).
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

#: The validated content of one dictionary file: section -> {key: translation}. Empty values
#: (stubs still being filled) are already dropped, so every pair here is a translation.
Sections = dict[str, dict[str, str]]


def load(path: Path) -> Dictionary:
    """Load a dictionary from a file or from every yaml file of a directory.

    Every file is read and checked before anything is merged, and the keys that two files
    translate differently are refused in ONE error naming all of them. Refusing at the first
    one made the fix a loop: take a duplicate out, load again, meet the next - once per key,
    on a merge that had brought ten of them in at a time. The other refusals (a file that
    does not parse, a broken token value) still stop at the first, as before: they are one
    file's fault, and the file is named.
    """
    if not _HAVE_YAML:
        raise DictionaryError(i18n.t("translate.dictionary.no-yaml"))
    files = _files_of(path)
    out = Dictionary(sources=tuple(files))
    language: str | None = None
    parsed: list[tuple[str, Sections]] = []
    for file in files:
        data = _parse(file, _text_of(file))
        file_language = str(data.get("language") or "en")
        if language is None:
            language = file_language
        elif file_language != language:
            raise DictionaryError(i18n.t(
                "translate.dictionary.language-mismatch",
                path=file, language=file_language, expected=language,
            ))
        parsed.append((str(file), _sections(file, data, out.notes)))
    conflicts, out.duplicates = collisions(parsed)
    if conflicts:
        raise DictionaryError(conflicts_message(conflicts))
    for _label, sections in parsed:
        for section, pairs in sections.items():
            getattr(out, section).update(pairs)
    out.language = language or "en"
    return out


def read_sections(path: Path) -> list[tuple[str, Sections]]:
    """(name, validated sections) of every dictionary file, in the order `load` reads them.

    The reading behind `load` without the merge - what a check of the files against each
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
    return _sections(label, _parse(label, text), [] if notes is None else notes)


def collisions(files: Sequence[tuple[str, Sections]]) -> tuple[list[dict], list[dict]]:
    """The keys more than one file translates: (conflicts, duplicates).

    A conflict is a key two files translate DIFFERENTLY - what the load refuses. A duplicate
    is a key two files translate the same way: the lookups do not care, and it is listed
    because the second copy is what a person takes out. A key with three readings, two of them
    alike, is a conflict. A row is `{"section", "key", "places": [{"file", "value"}, ...]}`,
    the places in file order; the rows come in section order, then by key.
    """
    places: dict[tuple[str, str], list[dict]] = {}
    for name, sections in files:
        for section, pairs in sections.items():
            for key, value in pairs.items():
                places.setdefault((section, key), []).append({"file": name, "value": value})
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
    """
    known = dict(working)
    out = list(working)
    for name, sections in other:
        mine = known.get(name) or {}
        extra: Sections = {}
        for section, pairs in sections.items():
            have = mine.get(section) or {}
            added = {key: value for key, value in pairs.items() if key not in have}
            if added:
                extra[section] = added
        if extra:
            out.append((f"{prefix}:{name}", extra))
    return out


def conflicts_message(conflicts: list[dict]) -> str:
    """The text of the refusal: the count, then one line per key with every file and value."""
    lines = [i18n.t("translate.dictionary.conflicts", count=len(conflicts))]
    lines.extend("  " + collision_line(row) for row in conflicts)
    return "\n".join(lines)


def collision_line(row: dict) -> str:
    """One conflict as a report line: the section, the key, then each file with its value."""
    places = "; ".join(f"{place['file']} = '{place['value']}'" for place in row["places"])
    return f"[{row['section']}] {row['key']}: {places}"


def duplicate_line(row: dict) -> str:
    """One duplicate as a report line: the value once, since every file agrees on it."""
    files = ", ".join(place["file"] for place in row["places"])
    return f"[{row['section']}] {row['key']} = '{row['places'][0]['value']}': {files}"


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


def _parse(label: str | Path, text: str) -> dict:
    """The mapping of one dictionary file, its version checked."""
    try:
        data = yaml.load(text, Loader=_LOADER) or {}
    except yaml.YAMLError as exc:
        raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=label, error=exc)) from exc
    if not isinstance(data, dict):
        raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=label, error="mapping expected"))
    version = data.get("version", 1)
    if version != 1:
        raise DictionaryError(i18n.t("translate.dictionary.bad-version", path=label, version=version))
    return data


def _sections(label: str | Path, data: dict, notes: list[str]) -> Sections:
    """The four sections of one parsed file, validated, the empty values dropped."""
    out: Sections = {}
    for section in SECTIONS:
        raw = data.get(section)
        if raw is None:
            continue
        if not isinstance(raw, dict):
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=label, section=section))
        pairs: dict[str, str] = {}
        for key, value in raw.items():
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
            pairs[key] = value
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
    # is a note for the report, not a refusal.
    keyword_targets = {en.lower() for en in platform_map.keyword_english().values()}
    if value.lower() in keyword_targets:
        notes.append(i18n.t(
            "translate.dictionary.keyword-value", path=file, key=key, value=value,
        ))


#: mtime-stamped cache for the editor path: the rule loads the dictionary on every file
#: check, and the same directory answers from memory until one of its files changes.
_CACHE: dict[Path, tuple[tuple, Dictionary]] = {}


def load_cached(path: Path) -> Dictionary:
    files = sorted(p for p in path.rglob("*.yaml")) if path.is_dir() else [path]
    stamp = tuple((str(p), p.stat().st_mtime_ns if p.exists() else 0) for p in files)
    known = _CACHE.get(path)
    if known is not None and known[0] == stamp:
        return known[1]
    loaded = load(path)
    _CACHE[path] = (stamp, loaded)
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
