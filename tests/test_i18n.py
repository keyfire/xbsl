"""Bilingual output: catalog integrity and language selection.

The catalog is assembled from the rule modules on import, so these checks cover every rule
that registered itself – including the ones an external package contributes.
"""

import string

import pytest

from xbsl import i18n
from xbsl.engine import RULES

_FORMATTER = string.Formatter()


def _fields(template: str) -> list[str]:
    """Field names of a template. A doubled brace is literal text and yields nothing."""
    return sorted({name for _, name, _, _ in _FORMATTER.parse(template) if name})


@pytest.fixture(autouse=True)
def _restore_lang():
    """These tests move the language around; the rest of the suite expects Russian."""
    yield
    i18n.set_lang("ru")


def _builtin_rules():
    return [r for r in RULES if r.func.__module__.startswith("xbsl.rules")]


# --- Catalog integrity ---------------------------------------------------------------

def test_every_key_carries_every_language():
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            assert entry.get(lang, "").strip(), f"{key}: no '{lang}' text"


def test_placeholders_are_the_same_in_every_language():
    """A field present in one language and missing in another is a KeyError at runtime."""
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        fields = {lang: _fields(entry[lang]) for lang in i18n.LANGS}
        distinct = {tuple(v) for v in fields.values()}
        assert len(distinct) == 1, f"{key}: placeholders differ between languages: {fields}"


def test_every_template_can_be_formatted():
    """Catches a stray brace: t() always formats, so a literal brace must be doubled."""
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            template = entry[lang]
            dummy = dict.fromkeys(_fields(template), "X")
            try:
                template.format(**dummy)
            except (IndexError, KeyError, ValueError) as exc:
                pytest.fail(f"{key} [{lang}]: {type(exc).__name__}: {exc} || {template}")


def test_field_names_are_plain_ascii_identifiers():
    """Rules pass ASCII keywords. A Cyrillic 'field' is really a brace that was not doubled –
    e.g. '${выражение}' inside a message about string interpolation."""
    for key in i18n.registered_keys():
        for lang in i18n.LANGS:
            for name in _fields(i18n.translations(key)[lang]):
                assert name.isascii() and name.isidentifier(), f"{key} [{lang}]: odd field '{name}'"


def test_every_builtin_rule_has_a_translated_title():
    for r in _builtin_rules():
        assert i18n.translations(r.title_key) is not None, f"{r.id}: title key not in catalog"


def test_builtin_titles_are_translated_not_echoed():
    for lang in i18n.LANGS:
        i18n.set_lang(lang)
        for r in _builtin_rules():
            assert r.title != r.title_key, f"{r.id}: title falls back to the key in '{lang}'"


def test_titles_actually_differ_between_languages():
    """Guards against an 'en' entry copied from 'ru' – at least most titles must differ."""
    same = 0
    for r in _builtin_rules():
        entry = i18n.translations(r.title_key)
        if entry["ru"] == entry["en"]:
            same += 1
    assert same == 0, f"{same} rule titles are identical in both languages"


# --- Lookup --------------------------------------------------------------------------

def test_unknown_key_is_returned_as_is():
    # A plugin written against 0.3 passes a literal title rather than a key.
    assert i18n.t("Номер задачи в коде") == "Номер задачи в коде"


def test_fields_are_substituted():
    i18n.set_lang("en")
    assert "U+00AB" in i18n.t("typography/guillemets-comment.found", code="00AB")


def test_register_rejects_a_missing_language():
    with pytest.raises(i18n.MessageError, match="no translation"):
        i18n.register({"тест.ключ": {"ru": "текст"}})


def test_register_rejects_a_conflicting_redefinition():
    i18n.register({"тест.повтор": {"ru": "текст", "en": "text"}})
    i18n.register({"тест.повтор": {"ru": "текст", "en": "text"}})  # identical is fine
    with pytest.raises(i18n.MessageError, match="already registered"):
        i18n.register({"тест.повтор": {"ru": "другое", "en": "other"}})


# --- Language selection --------------------------------------------------------------

def test_set_lang_rejects_an_unknown_language():
    with pytest.raises(i18n.MessageError, match="Unknown language"):
        i18n.set_lang("de")


def test_env_is_used_when_nothing_is_pinned(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.setenv("XBSL_LANG", "en")
    assert i18n.current_lang() == "en"


def test_pinned_language_wins_over_env(monkeypatch):
    monkeypatch.setenv("XBSL_LANG", "en")
    i18n.set_lang("ru")
    assert i18n.current_lang() == "ru"


def test_falls_back_to_russian(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.delenv("XBSL_LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.setattr(i18n._locale, "getlocale", lambda *a: (None, None))
    assert i18n.current_lang() == i18n.DEFAULT_LANG == "ru"


def test_system_locale_is_recognised(monkeypatch):
    i18n.set_lang(None)
    monkeypatch.delenv("XBSL_LANG", raising=False)
    monkeypatch.setattr(i18n._locale, "getlocale", lambda *a: ("English_United States", "1252"))
    assert i18n.current_lang() == "en"


# --- Prescan of --lang in argv (help is assembled before parsing) --------------------

def test_lang_from_argv_reads_separate_value():
    assert i18n.lang_from_argv(["--lang", "en", "Форма.xbsl"]) == "en"


def test_lang_from_argv_reads_equals_form():
    assert i18n.lang_from_argv(["--lang=ru", "lint"]) == "ru"


def test_lang_from_argv_is_none_without_flag():
    assert i18n.lang_from_argv(["Форма.xbsl"]) is None


def test_lang_from_argv_rejects_unknown_value():
    # An unknown language is not pinned - argparse rejects it later with its own message.
    assert i18n.lang_from_argv(["--lang", "de"]) is None


def test_lang_from_argv_ignores_dangling_flag():
    assert i18n.lang_from_argv(["lint", "--lang"]) is None


def test_check_mode_help_follows_lang_flag(capsys):
    """--lang translates the check-mode --help text, not only the runtime output: the language
    is resolved before the parser is built. Both directions are checked with an explicit flag,
    which does not depend on the machine locale or on the Element data. _restore_lang puts ru back.
    """
    from xbsl import cli

    with pytest.raises(SystemExit) as info:
        cli.main(["--lang", "en", "--help"])
    assert info.value.code == 0
    assert "Linter for 1C:Element sources" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        cli.main(["--lang", "ru", "--help"])
    assert "Линтер исходников" in capsys.readouterr().out


def test_scaffold_help_follows_env_language(monkeypatch, capsys):
    """Scaffolding and templates take no --lang; their help language comes from XBSL_LANG (or the
    locale) via current_lang(). Set the env to en and check a subcommand's help is English. No
    Element data needed - --help exits before any scaffold work. _restore_lang puts ru back."""
    from xbsl import cli

    monkeypatch.setenv("XBSL_LANG", "en")
    i18n.set_lang(None)  # unpin, so current_lang() reads the env

    with pytest.raises(SystemExit) as info:
        cli.main(["add-field", "--help"])
    assert info.value.code == 0
    assert "tabular section name" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        cli.main(["templates", "--help"])
    assert "code templates" in capsys.readouterr().out
