"""Language of the linter output: message catalogs and lookup.

A rule module registers its own messages next to the rules that emit them, so that a rule
and its wording cannot drift apart:

    MESSAGES = {
        "code/brackets.unclosed": {
            "ru": "Не закрыта скобка '{ch}'.",
            "en": "Unclosed bracket '{ch}'.",
        },
    }
    i18n.register(MESSAGES)

Keys are `<rule id>.title` for a rule title and `<rule id>.<variant>` for its messages;
non-rule text uses a `<module>.<name>` key. Placeholders are `str.format` fields and must be
the same in every language – `tests/test_i18n.py` enforces that. A brace that is part of the
text – `() [] {{}}` – has to be doubled, because every template is formatted.

The language is chosen by: set_lang() (CLI --lang) > env XBSLLINT_LANG > system locale > ru.
An unknown key is returned as is, so a plugin written against 0.3 – which passed literal
strings rather than keys – keeps working.
"""

from __future__ import annotations

import locale as _locale
import os

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"
ENV_LANG = "XBSLLINT_LANG"

_catalog: dict[str, dict[str, str]] = {}
_selected: str | None = None

# Text of the adapters themselves (CLI summary, tool descriptions) – not tied to any one rule.
_CORE_MESSAGES = {
    "cli.summary": {
        "ru": "\nПроверено файлов: {files} ({xbsl} .xbsl, {yaml} .yaml); "
              "замечаний: {diags} (ошибок: {errors})",
        "en": "\nFiles checked: {files} ({xbsl} .xbsl, {yaml} .yaml); "
              "diagnostics: {diags} (errors: {errors})",
    },
    "cli.no-rules": {
        "ru": "(правила ещё не зарегистрированы)",
        "en": "(no rules registered yet)",
    },
    "cli.data-error": {
        "ru": "Ошибка данных Элемента: {error}",
        "en": "Element data error: {error}",
    },
    "cli.stdin-needs-filename": {
        "ru": "Режиму --stdin нужен --filename (напр. Форма.xbsl): по расширению определяется вид файла.",
        "en": "--stdin needs --filename (e.g. Form.xbsl): the extension sets the file kind.",
    },
    "cli.index-single-path": {
        "ru": "Режиму --index нужен ровно один путь – корень индексируемого проекта.",
        "en": "--index takes exactly one path – the root of the project to index.",
    },
    "cli.index-missing-path": {
        "ru": "Путь '{path}' не существует.",
        "en": "Path '{path}' does not exist.",
    },
}


class MessageError(RuntimeError):
    pass


def _register_core() -> None:
    """Register the adapters' own messages. Called on import; safe to call again."""
    register(_CORE_MESSAGES)


def register(messages: dict[str, dict[str, str]]) -> None:
    """Add messages to the catalog. Every key must carry every language of LANGS."""
    for key, per_lang in messages.items():
        missing = [lang for lang in LANGS if lang not in per_lang]
        if missing:
            raise MessageError(f"Message '{key}' has no translation for: {', '.join(missing)}")
        known = _catalog.get(key)
        if known is not None and known != per_lang:
            raise MessageError(f"Message '{key}' is already registered with a different wording")
        _catalog[key] = dict(per_lang)


def registered_keys() -> list[str]:
    return sorted(_catalog)


def translations(key: str) -> dict[str, str] | None:
    entry = _catalog.get(key)
    return dict(entry) if entry else None


def set_lang(lang: str | None) -> None:
    """Pin the output language for the process (CLI --lang). None restores the lookup order."""
    global _selected
    if lang is not None and lang not in LANGS:
        raise MessageError(f"Unknown language '{lang}'. Available: {', '.join(LANGS)}")
    _selected = lang


def _system_lang() -> str | None:
    code = ""
    try:
        code = _locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        pass
    code = (code or os.environ.get("LC_ALL") or os.environ.get("LANG") or "").lower()
    # "ru_RU.UTF-8" and Windows' "Russian_Russia" both start with the language code.
    for lang in LANGS:
        if code.startswith(lang):
            return lang
    return None


def current_lang() -> str:
    if _selected is not None:
        return _selected
    env = os.environ.get(ENV_LANG, "").strip().lower()
    if env in LANGS:
        return env
    return _system_lang() or DEFAULT_LANG


def t(key: str, /, **fields) -> str:
    """Translate a key and substitute the fields. An unknown key is returned unchanged.

    A template is always run through str.format, so a literal brace must be doubled: `{{}}`.
    Formatting conditionally – only when fields are passed – would turn a literal brace into a
    field the day someone adds one, and the failure would surface as a crash in a rule.
    """
    entry = _catalog.get(key)
    if entry is None:
        return key
    template = entry.get(current_lang()) or entry[DEFAULT_LANG]
    return template.format(**fields)


_register_core()
