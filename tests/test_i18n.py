"""Bilingual output: catalog integrity and language selection.

The catalog is assembled from the rule modules on import, so these checks cover every rule
that registered itself – including the ones an external package contributes.
"""

import re
import string

import pytest

from xbsl import i18n
from xbsl.engine import RULES

_FORMATTER = string.Formatter()

#: A word of Cyrillic letters, and the `{n[...]}` substitution that legitimately holds one.
_CYRILLIC = re.compile(r"[А-Яа-яЁё][А-Яа-яЁё0-9_]*")
_SUBSTITUTION = re.compile(r"\{n\[[^\]]*\]\}")


def _fields(template: str) -> list[str]:
    """Field names a CALLER must pass. A doubled brace is literal text and yields nothing.

    `{n[Ид]}` is not one of them: `n` is the metadata-name map that `t()` always supplies, and
    the name inside the brackets is deliberately Cyrillic - it is the key of the platform pair.
    """
    return sorted({
        name for _, name, _, _ in _FORMATTER.parse(template)
        if name and not name.startswith("n[")
    })


def _name_fields(template: str) -> list[str]:
    """The `{n[...]}` substitutions of a template - the names resolved through the dictionary."""
    return sorted({
        name[2:-1] for _, name, _, _ in _FORMATTER.parse(template)
        if name and name.startswith("n[") and name.endswith("]")
    })


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
    """Catches a stray brace: t() always formats, so a literal brace must be doubled.

    The dummy tries a string first - most fields carry prose - and only falls back to a
    number when the template itself demands one: a numeric format spec (say `{coverage:.1%}`)
    rejects a string outright with ValueError, and the real value such a field gets at
    runtime is a number anyway. A field that rejects both is a genuine template defect, not a
    type mismatch of the dummy.
    """
    for key in i18n.registered_keys():
        entry = i18n.translations(key)
        for lang in i18n.LANGS:
            template = entry[lang]
            fields = _fields(template)
            for dummy_value in ("X", 1):
                try:
                    template.format(**{"n": i18n._NAMES, **dict.fromkeys(fields, dummy_value)})
                    break
                except ValueError:
                    continue
                except (IndexError, KeyError) as exc:
                    pytest.fail(f"{key} [{lang}]: {type(exc).__name__}: {exc} || {template}")
            else:
                pytest.fail(f"{key} [{lang}]: fails to format with both a string and a number "
                             f"dummy || {template}")


def test_field_names_are_plain_ascii_identifiers():
    """Rules pass ASCII keywords. A Cyrillic 'field' is really a brace that was not doubled –
    e.g. '${выражение}' inside a message about string interpolation."""
    for key in i18n.registered_keys():
        for lang in i18n.LANGS:
            for name in _fields(i18n.translations(key)[lang]):
                assert name.isascii() and name.isidentifier(), f"{key} [{lang}]: odd field '{name}'"


def test_metadata_names_resolve_through_the_platform_dictionary():
    """Every `{n[...]}` names a pair the platform itself knows - otherwise the English message
    keeps the Russian word and the substitution is pointless noise."""
    from xbsl import dataset

    if not dataset.available_versions():
        pytest.skip("нет данных Элемента")
    i18n.set_lang("en")
    unresolved = []
    for key in i18n.registered_keys():
        for lang in i18n.LANGS:
            for value in _name_fields(i18n.translations(key)[lang]):
                if i18n.name(value) == value:
                    unresolved.append(f"{key} [{lang}]: {value}")
    assert not unresolved, "имена без пары в словаре платформы: " + ", ".join(unresolved)


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


def test_keywords_are_spelled_in_the_language_of_the_message():
    """A keyword is bilingual too, only its pairs live in the grammar tables.

    "Expected 'метод'" is useless to a project written `method`; the dictionary is tried first,
    so a name it knows never reaches the keyword table.
    """
    from xbsl import dataset

    if not dataset.available_versions():
        pytest.skip("нет данных Элемента")
    i18n.set_lang("en")
    assert i18n.name("метод") == "method"
    assert i18n.name("выбор") == "case"
    assert i18n.name("Тип") == "Type"  # the dictionary wins over the keyword table
    i18n.set_lang("ru")
    assert i18n.name("метод") == "метод"


# Cyrillic that is LEGAL in an English message: a quote of the sources or of the platform.
_QUOTED_IN_ENGLISH = frozenset({
    # keywords and literals quoted as code
    "для", "не", "если", "поймать", "это", "обз", "знч", "пер", "из", "по", "возврат",
    "Истина", "Ложь", "Неопределено", "новый", "как", "и", "или", "Запрос", "метод",
    "импорт", "исп", "иначе", "попытка", "пока", "область", "выбор",
    # the literal text of a compiler / platform error
    "Неизвестное", "свойство", "Неизвестный", "ресурс", "Ресурс", "Поле", "найдено",
    "может", "быть", "присвоено", "Ожидалось", "указание", "типа", "ТипДанных",
    # names the platform generates or does not translate
    "ДанныеСтрокиСписка", "Заменить",
    # the naming standard quotes its own prefixes and examples
    "Вид", "Исключение", "Это", "Есть", "Содержит", "Успешно", "НетОшибок", "Устарело",
    "используется", "ФизическоеЛицо", "ФизическиеЛица",
    "КабинетСотрудника", "НовыеЭлементарныеТехнологии",
})


def test_english_messages_carry_no_untranslated_metadata_names():
    """An English message may quote the sources, but must not NAME metadata in Russian.

    The guard is a whitelist of what a quote may contain: anything else in an English text
    means a name that should have gone through `{n[...]}`. Without it the remainder creeps
    back one message at a time.
    """
    import re

    # Keys whose Cyrillic is a quote of the NAMING STANDARD itself - the standard forbids the
    # prefix `Тип` for an enumeration by that very word, so translating it would lose the rule.
    quoting_the_standard = {"naming/enum-vid.title", "style/enum-name-vid.title"}
    leftovers = []
    for key in i18n.registered_keys():
        if key.startswith("cli.help") or key in quoting_the_standard:
            continue  # the help of the scaffolding quotes kinds and sections wholesale
        text = i18n.translations(key).get("en", "")
        # what already goes through the name map is not a leftover
        text = re.sub(r"\{n\[[^\]]+\]\}", "", text)
        for word in re.findall(r"[А-Яа-яЁё][А-Яа-яЁё]+", text):
            if word not in _QUOTED_IN_ENGLISH:
                leftovers.append(f"{key}: {word}")
    assert not leftovers, "имена метаданных остались русскими: " + ", ".join(sorted(set(leftovers)))


#: The quotes an English message may legitimately keep in Cyrillic: the VERBATIM text of a
#: platform error. Translating those would send the reader looking for a message the platform
#: never prints. Everything else with an English spelling has to use it (or `{n[...]}`, which
#: follows the reader's language).
_VERBATIM_QUOTES = {
    "code/row-field-null.assign",          # '.ЗаменитьNull(...)' - the member has no English pair
    "query/deletion-mark-immediate.absent",  # 'Поле не найдено' - the compiler's own wording
    "yaml/bare-object-value.bare",           # 'Ожидалось Неопределено...' - the same
    "yaml/ref-needs-nullable.input",         # 'Parameter "ТипДанных" ... must' - the same
    "yaml/ref-needs-nullable.input-union",   # 'Parameter "ТипДанных" ... must' - the same
}


def test_english_messages_use_english_spellings():
    """An English message must not carry a Russian name the platform spells in English too.

    The rule of the repository: Cyrillic is legal in English text only for names the platform
    writes in Russian alone. The catalog had drifted - a sweep once counted 111 offending
    messages, though two thirds of that count was the `{n[...]}` substitution being mistaken
    for debt. What was left is fixed; this test keeps it from creeping back.
    """
    from xbsl import dataset, terms

    if not dataset.available_versions():
        pytest.skip("нет данных Элемента")
    offenders = []
    for key in i18n.registered_keys():
        if key in _VERBATIM_QUOTES:
            continue
        text = _SUBSTITUTION.sub(" ", i18n.translations(key)["en"])
        for word in dict.fromkeys(_CYRILLIC.findall(text)):
            english = (terms.common_english(word) or terms.english(word, "types")
                       or terms.english(word, "properties") or terms.english(word, "enums"))
            if english:
                offenders.append(f"{key}: {word} -> {english}")
    assert not offenders, (
        "кириллица в английских сообщениях там, где у имени есть английское написание: "
        + ", ".join(offenders)
    )
