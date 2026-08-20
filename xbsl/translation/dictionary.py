"""The project translation dictionary: the project's OWN names and comments.

Platform tokens translate by the dataset (platform_map.py); everything the PROJECT named -
objects, methods, variables, localization keys, resource files - and every comment line is
translated by people, and this module is where their work lives. Two planes:

- `tokens`: one exact identifier to one exact identifier ("Задачи" -> Tasks). Whole names,
  not words: the word order of an English name is the reverse of the Russian one, and the parts
  of a Russian name are declined, so gluing per-word translations produces calques. A
  resource file is entered by its stem ("Значок" -> Icon for the svg of the same name).
- `phrases`: one comment line to its translation, the text after `//`/`#` trimmed. Per line
  rather than per block: an edit next to a line does not invalidate it, and one entry
  serves every repetition.

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


@dataclass
class Dictionary:
    """The merged content of every dictionary file, ready for lookups."""

    language: str = "en"
    tokens: dict[str, str] = field(default_factory=dict)
    phrases: dict[str, str] = field(default_factory=dict)
    sources: tuple[Path, ...] = ()
    #: Non-fatal remarks gathered while loading (an empty value skipped, etc.).
    notes: list[str] = field(default_factory=list)
    #: Where each key was first seen - for the duplicate report.
    _origins: dict[str, str] = field(default_factory=dict)

    def token(self, name: str, scope: str = "") -> str | None:
        """The translation of a name, the scoped entry first.

        A key of a localized-strings dictionary lives in its OWN namespace, where the
        project may need a spelling the same word cannot have elsewhere: "Войти" is the
        key `SignIn` there while the bare word stays `Login` in code. Such an entry is
        written qualified - `<Dictionary>.<Key>: SignIn` - and wins over the plain one.
        """
        if scope:
            scoped = self.tokens.get(f"{scope}.{name}")
            if scoped is not None:
                return scoped
        return self.tokens.get(name)

    def phrase(self, text: str) -> str | None:
        return self.phrases.get(text)

    @property
    def empty(self) -> bool:
        return not self.tokens and not self.phrases


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
            data = yaml.safe_load(file.read_text(encoding="utf-8-sig")) or {}
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
        _merge_section(out, file, data, "tokens", validate_token=True)
        _merge_section(out, file, data, "phrases", validate_token=False)
    out.language = language or "en"
    return out


def _merge_section(out: Dictionary, file: Path, data: dict, section: str, *, validate_token: bool) -> None:
    raw = data.get(section)
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
    target = out.tokens if section == "tokens" else out.phrases
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
        if value is None or value == "":
            continue  # a stub still being filled - the key simply stays untranslated
        if not isinstance(value, str):
            raise DictionaryError(i18n.t("translate.dictionary.bad-section", path=file, section=section))
        if validate_token:
            _validate_token(out, file, key, value)
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
) -> None:
    """Write the untranslated remainder as a dictionary file with empty values.

    The stub IS a dictionary file: fill the values and drop it into the dictionary
    directory. Entries are ordered by frequency, each annotated with its count and first
    location; a token that names a resource file or collides with a platform spelling is
    annotated too, so the filler sees what they are naming.
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
    path.write_text("\n".join(lines), encoding="utf-8")
