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
completed stub next to the existing ones; duplicate keys with different values are refused.
Discovery walks up from the project root for a `xbsl-translation` directory or a
`xbsl-translation.yaml` file - the dictionary lives in the repository, outside the sources
it describes, and never ships inside an assembly.
"""

from __future__ import annotations

import re
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
    "translate.dictionary.duplicate": {
        "ru": "{path}: ключ '{key}' уже переведён иначе в {other} ('{value}' против '{known}')",
        "en": "{path}: the key '{key}' is already translated differently in {other} ('{value}' vs '{known}')",
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
    #: Where each key was first seen - for the duplicate report.
    _origins: dict[str, str] = field(default_factory=dict)

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
        for scope in scopes:
            if scope:
                scoped = self.tokens.get(f"{scope}.{name}")
                if scoped is not None:
                    return scoped
        return self.tokens.get(name)

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


def load(path: Path) -> Dictionary:
    """Load a dictionary from a file or from every yaml file of a directory."""
    if not _HAVE_YAML:
        raise DictionaryError(i18n.t("translate.dictionary.no-yaml"))
    if path.is_dir():
        files = sorted(p for p in path.rglob("*.yaml") if p.is_file())
    elif path.is_file():
        files = [path]
    else:
        raise DictionaryError(i18n.t("translate.dictionary.not-found", path=path))
    out = Dictionary(sources=tuple(files))
    language: str | None = None
    for file in files:
        try:
            data = yaml.load(file.read_text(encoding="utf-8-sig"), Loader=_LOADER) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=file, error=exc)) from exc
        if not isinstance(data, dict):
            raise DictionaryError(i18n.t("translate.dictionary.bad-file", path=file, error="mapping expected"))
        version = data.get("version", 1)
        if version != 1:
            raise DictionaryError(i18n.t("translate.dictionary.bad-version", path=file, version=version))
        file_language = str(data.get("language") or "en")
        if language is None:
            language = file_language
        elif file_language != language:
            raise DictionaryError(i18n.t(
                "translate.dictionary.language-mismatch",
                path=file, language=file_language, expected=language,
            ))
        _merge_section(out, file, data, "tokens")
        _merge_section(out, file, data, "phrases")
        _merge_section(out, file, data, "literals")
        _merge_section(out, file, data, "terms")
    out.language = language or "en"
    return out


def _merge_section(out: Dictionary, file: Path, data: dict, section: str) -> None:
    raw = data.get(section)
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
    target = {
        "tokens": out.tokens, "phrases": out.phrases, "literals": out.literals, "terms": out.terms,
    }[section]
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
        if value is None or value == "":
            continue  # a stub still being filled - the key simply stays untranslated
        if not isinstance(value, str):
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
        if section == "tokens":
            _validate_token(out, file, key, value)
        elif section == "literals":
            _validate_literal(file, key, value)
        origin_key = f"{section}:{key}"
        known = target.get(key)
        if known is not None and known != value:
            raise DictionaryError(i18n.t(
                "translate.dictionary.duplicate",
                path=file, key=key, value=value,
                known=known, other=out._origins.get(origin_key, "?"),
            ))
        target[key] = value
        out._origins.setdefault(origin_key, str(file))


def _validate_literal(file: Path, key: str, value: str) -> None:
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


def _validate_token(out: Dictionary, file: Path, key: str, value: str) -> None:
    if not _TOKEN_VALUE_RE.match(value):
        raise DictionaryError(i18n.t(
            "translate.dictionary.bad-token-value", path=file, key=key, value=value,
        ))
    # A keyword-shaped name is legal in the metadata (the English demo project compiles an
    # attribute named `Step`), but a keyword-named VARIABLE is asking for trouble - so this
    # is a note for the report, not a refusal.
    keyword_targets = {en.lower() for en in platform_map.keyword_english().values()}
    if value.lower() in keyword_targets:
        out.notes.append(i18n.t(
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
    path.write_text("\n".join(lines), encoding="utf-8")
