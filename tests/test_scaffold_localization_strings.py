"""Adding a localized string: the value is quoted where yaml needs it, and the translations
get the key too.

Both were found by using the tool on a live project. A value with a colon and a space in it
was written bare, and the file the tool had just written did not parse - yaml read the tail as
a nested mapping. And a translation file carries no element kind of its own, so the ordinary
add refused it: the English half was typed by hand after every string.
"""

import io
from pathlib import Path

import pytest
import yaml as _yaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import scaffold

_PROJECT = (
    "ВидЭлемента: Проект\nИд: 11111111-1111-1111-1111-111111111111\nПоставщик: Acme\n"
    "Имя: Demo\nВерсия: 1.0.0\nРежимСовместимости: 9.0\n"
    "ЯзыкиЛокализации:\n    - Русский\n    - Английский\nЯзыкПоУмолчанию: Русский\n"
)


def _write(result) -> None:
    for change in result.changes:
        change.path.parent.mkdir(parents=True, exist_ok=True)
        io.open(change.path, "w", encoding="utf-8", newline="").write(change.content)


@pytest.fixture
def element(tmp_path: Path) -> Path:
    subsystem = tmp_path / "acme" / "demo" / "Основное"
    subsystem.mkdir(parents=True)
    io.open(subsystem.parent / "Проект.yaml", "w", encoding="utf-8", newline="").write(_PROJECT)
    io.open(subsystem / "Подсистема.yaml", "w", encoding="utf-8", newline="").write(
        "ВидЭлемента: Подсистема\nИд: 22222222-2222-2222-2222-222222222222\nИмя: Основное\n")
    _write(scaffold.op_new_object(subsystem, "ЛокализованныеСтроки", "Тексты"))
    return subsystem / "Тексты.yaml"


def _add(path: Path, kind: str, name: str, value: str):
    result = scaffold.op_add_field(path, kind, name, type_=value)
    _write(result)
    return result


def _loaded(path: Path) -> dict:
    return _yaml.safe_load(io.open(path, encoding="utf-8-sig").read())


# --- quoting ---------------------------------------------------------------------------


def test_a_value_with_a_colon_survives(element: Path):
    """The whole point of the item: the file must parse after the tool has written it."""
    text = "Рекламных переходов посетителей: $0."

    _add(element, "строка", "Переходы", text)

    assert _loaded(element)["Строки"]["Переходы"] == text


def test_a_value_that_starts_a_comment_survives(element: Path):
    _add(element, "строка", "Скидка", "Скидка #1")

    assert _loaded(element)["Строки"]["Скидка"] == "Скидка #1"


def test_a_plain_value_stays_unquoted(element: Path):
    """The control: files of a live project write their strings plain, and so does the tool."""
    _add(element, "строка", "Обычная", "Обычный текст")

    assert "Обычная: Обычный текст" in io.open(element, encoding="utf-8-sig").read()


def test_a_template_is_always_quoted(element: Path):
    _add(element, "шаблон", "Привет", "Привет, %0!")

    assert 'Привет: "Привет, %0!"' in io.open(element, encoding="utf-8-sig").read()


# --- the translations ------------------------------------------------------------------


def test_a_new_string_reaches_the_translation(element: Path):
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    result = _add(element, "строка", "Вторая", "Второй текст")

    translation = element.parent / "Локализация" / "En" / "Тексты.yaml"
    assert _loaded(translation)["Строки"]["Вторая"] == "Второй текст"
    assert any("Вторая" in note for note in result.notes)


def test_a_key_the_translation_already_has_is_left_alone(element: Path):
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))
    translation = element.parent / "Локализация" / "En" / "Тексты.yaml"
    io.open(translation, "w", encoding="utf-8", newline="").write(
        "Строки:\n    Первая: The first text\n    Вторая: The second text\n")

    _add(element, "строка", "Вторая", "Второй текст")

    assert _loaded(translation)["Строки"]["Вторая"] == "The second text"


def test_without_translations_nothing_extra_is_written(element: Path):
    result = _add(element, "строка", "Первая", "Первый текст")

    assert [c.path for c in result.changes] == [element]
    assert result.notes == []


def test_the_note_names_the_call_that_writes_the_translation(element: Path):
    """The row lands in the translation with the DEFAULT text, and the note used to leave the
    reader with "replace it" - as if by hand, while one call writes every language at once."""
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    result = _add(element, "строка", "Вторая", "Второй текст")

    assert any("set-localization" in note for note in result.notes), result.notes


def test_a_call_on_the_translation_file_names_the_element_and_the_call(element: Path):
    """A translation carries no kind of its own, so the kind check used to answer
    "У вида ? нет секции для 'строка'" - true, useless, and silent about where the text of a
    translation is actually written.
    """
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.op_add_field(_translation(element), "строка", "Вторая", type_="The second")

    said = str(refusal.value)
    assert "перевод" in said and "En" in said
    assert "Тексты.yaml" in said and "set-localization" in said


def test_setting_a_property_on_a_translation_file_is_refused_the_same_way(element: Path):
    """The same file meets the same kind check through the property editor."""
    _write(scaffold.op_add_localization(element, "En"))

    with pytest.raises(scaffold.ScaffoldError) as refusal:
        scaffold.op_set_field_property(
            _translation(element), "реквизит", "Первая", {"Представление": "First"})

    assert "set-localization" in str(refusal.value)


def test_an_ordinary_element_is_not_taken_for_a_translation(element: Path):
    """The control of the detection: it keys on the Localization/<Code>/ position alone."""
    assert scaffold.translation_element(element) is None
    _write(scaffold.op_add_localization(element, "En"))
    assert scaffold.translation_element(_translation(element)) == element


# --- one row, every language -----------------------------------------------------------


def _set(path: Path, name: str, values: dict, **kwargs):
    result = scaffold.op_set_localization(path, name, values, **kwargs)
    _write(result)
    return result


def _translation(element: Path) -> Path:
    return element.parent / "Локализация" / "En" / "Тексты.yaml"


def test_one_call_writes_both_languages(element: Path):
    """The item itself: a row used to be typed into the element and again into its twin."""
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    _set(element, "Заголовок", {"Русский": "Личный кабинет", "En": "Personal account"})

    assert _loaded(element)["Строки"]["Заголовок"] == "Личный кабинет"
    assert _loaded(_translation(element))["Строки"]["Заголовок"] == "Personal account"


def test_an_existing_row_is_corrected_in_place_in_both(element: Path):
    _add(element, "строка", "Заголовок", "Старый текст")
    _write(scaffold.op_add_localization(element, "En"))

    _set(element, "Заголовок", {"Ru": "Новый текст", "English": "The new text"})

    text = io.open(element, encoding="utf-8-sig").read()
    assert _loaded(element)["Строки"]["Заголовок"] == "Новый текст"
    assert text.count("Заголовок:") == 1, "the row is corrected, not doubled"
    assert _loaded(_translation(element))["Строки"]["Заголовок"] == "The new text"


def test_a_language_the_call_says_nothing_about_still_gets_the_row(element: Path):
    """A key missing from a translation is a gap the translator meets much later."""
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    result = _set(element, "Заголовок", {"Русский": "Личный кабинет"})

    assert _loaded(_translation(element))["Строки"]["Заголовок"] == "Личный кабинет"
    assert any("Заголовок" in note for note in result.notes)


def test_a_language_without_a_translation_file_is_refused(element: Path):
    with pytest.raises(scaffold.ScaffoldError) as exc:
        scaffold.op_set_localization(element, "Заголовок", {"En": "Personal account"})

    assert "add-localization" in str(exc.value)


def test_the_default_language_must_carry_the_text(element: Path):
    """The element holds the text itself; a translation is only a replacement of it."""
    _write(scaffold.op_add_localization(element, "En"))

    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization(element, "Заголовок", {"En": "Personal account"})


def test_quoting_is_the_writers_business_here_too(element: Path):
    _set(element, "Переходы", {"Русский": "Рекламных переходов посетителей: $0."})

    assert _loaded(element)["Строки"]["Переходы"] == "Рекламных переходов посетителей: $0."


def test_a_key_keeps_the_section_it_lives_in(element: Path):
    _add(element, "шаблон", "Привет", "Привет, %0!")

    _set(element, "Привет", {"Русский": "Здравствуйте, %0!"})

    loaded = _loaded(element)
    assert loaded["Шаблоны"]["Привет"] == "Здравствуйте, %0!"
    assert "Привет" not in (loaded.get("Строки") or {})


def test_the_section_can_be_named(element: Path):
    _set(element, "Привет", {"Русский": "Здравствуйте, %0!"}, section="Шаблоны")

    assert _loaded(element)["Шаблоны"]["Привет"] == "Здравствуйте, %0!"


@pytest.mark.needs_data
def test_the_section_is_taken_in_either_spelling(element: Path):
    """The platform is bilingual, and a project may be written either way."""
    _set(element, "Привет", {"Русский": "Здравствуйте, %0!"}, section="Templates")

    assert _loaded(element)["Шаблоны"]["Привет"] == "Здравствуйте, %0!"


def test_an_unknown_section_and_an_unknown_language_are_refused(element: Path):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization(element, "Привет", {"Русский": "Текст"}, section="Строчки")
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization(element, "Привет", {"Французский": "Bonjour"})


@pytest.mark.parametrize("name", ["Два слова", "Ключ:", "#Ключ", "", "  "])
def test_a_key_that_would_not_survive_being_written_bare_is_refused(element: Path, name: str):
    """The row is written unquoted, like the hand-written ones - so the key has to hold."""
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization(element, name, {"Русский": "Текст"})


# --- many keys, one pass ----------------------------------------------------------------


def test_op_set_localization_returns_a_plain_scaffold_result(element: Path):
    """The single-key call stays a ScaffoldResult - existing callers read .changes/.notes."""
    result = scaffold.op_set_localization(element, "Привет", {"Русский": "Привет!"})

    assert isinstance(result, scaffold.ScaffoldResult)
    assert not isinstance(result, scaffold.LocalizationOutcome)


def test_batch_writes_two_keys_with_one_file_change_each(element: Path):
    """Ten keys touching the same pair of files used to mean ten reads and ten writes of
    each - ten FileChanges silently overwriting one another when only the last stuck."""
    _write(scaffold.op_add_localization(element, "En"))

    outcome = scaffold.op_set_localization_batch(element, {
        "Заголовок": {"Русский": "Личный кабинет", "En": "Personal account"},
        "Кнопка": {"Русский": "Сохранить", "En": "Save"},
    })
    _write(outcome.result)

    assert [c.path for c in outcome.result.changes] == [element, _translation(element)]
    assert _loaded(element)["Строки"] == {"Заголовок": "Личный кабинет", "Кнопка": "Сохранить"}
    assert _loaded(_translation(element))["Строки"] == {
        "Заголовок": "Personal account", "Кнопка": "Save",
    }


def test_batch_entries_report_key_language_file_old_and_new(element: Path):
    _add(element, "строка", "Заголовок", "Старый текст")
    _write(scaffold.op_add_localization(element, "En"))

    outcome = scaffold.op_set_localization_batch(element, {
        "Заголовок": {"Русский": "Новый текст", "En": "The new text"},
        "Подвал": {"Русский": "Низ страницы"},
    })

    by_file_and_key = {(e.file, e.key): e for e in outcome.entries}
    changed = by_file_and_key[(element, "Заголовок")]
    assert (changed.language, changed.old, changed.new) == ("Русский", "Старый текст", "Новый текст")
    added = by_file_and_key[(element, "Подвал")]
    assert (added.language, added.old, added.new) == ("Русский", "", "Низ страницы")
    # add-localization seeded the translation with the default-language text at the time it
    # ran, so its "old" is that copy ("Старый текст"), not "" - the row already existed.
    translated = by_file_and_key[(_translation(element), "Заголовок")]
    assert (translated.language, translated.old, translated.new) == (
        "Английский", "Старый текст", "The new text",
    )


def test_batch_stops_at_the_first_bad_key_and_plans_nothing(element: Path):
    """A batch is one plan, not a loop of independent calls: the second key is invalid, and
    the first must not reach disk just because it was read before the failure."""
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization_batch(element, {
            "Заголовок": {"Русский": "Личный кабинет"},
            "Два слова": {"Русский": "Текст"},
        })

    assert "Заголовок" not in _loaded(element).get("Строки", {})


def test_batch_of_one_writes_nothing_on_disk_until_applied(element: Path):
    """op_set_localization_batch only plans - apply_result is what touches the filesystem."""
    before = element.read_text(encoding="utf-8-sig")

    scaffold.op_set_localization_batch(element, {"Заголовок": {"Русский": "Личный кабинет"}})

    assert element.read_text(encoding="utf-8-sig") == before


def test_batch_requires_at_least_one_entry(element: Path):
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization_batch(element, {})


def test_batch_refuses_a_value_that_is_not_a_text(element: Path):
    """A caption is a string. str() on whatever came in wrote the word "True" into the row,
    and an MCP client passing typed JSON reaches this function directly."""
    with pytest.raises(scaffold.ScaffoldError) as exc:
        scaffold.op_set_localization_batch(element, {"Заголовок": {"Русский": True}})

    assert "Заголовок" in str(exc.value)


def test_batch_refuses_a_key_that_is_not_a_text(element: Path):
    """A key loaded as a yaml boolean used to crash the write on `.strip()`."""
    with pytest.raises(scaffold.ScaffoldError):
        scaffold.op_set_localization_batch(element, {True: {"Русский": "Включено"}})


def test_batch_does_not_rewrite_a_translation_it_only_read(element: Path):
    """A translation the pass only consulted used to come back as a FileChange: the same
    bytes, a new mtime, and a row in the list of files the caller was told about."""
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))
    translation = _translation(element)
    before = translation.read_text(encoding="utf-8-sig")

    outcome = scaffold.op_set_localization_batch(element, {"Первая": {"Русский": "Иной текст"}})
    _write(outcome.result)

    assert [c.path for c in outcome.result.changes] == [element]
    assert translation.read_text(encoding="utf-8-sig") == before


def test_batch_does_not_rewrite_a_translation_given_the_text_it_already_has(element: Path):
    """The same row written again is not a change either - the file is left alone."""
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))
    _write(scaffold.op_set_localization_batch(
        element, {"Первая": {"Русский": "Первый текст", "En": "The first text"}},
    ).result)

    outcome = scaffold.op_set_localization_batch(
        element, {"Первая": {"Русский": "Иной текст", "En": "The first text"}},
    )

    assert [c.path for c in outcome.result.changes] == [element]


# --- a key that spells a yaml 1.1 special word ------------------------------------------

# The tool's own reader (_section_entries) scans the file line by line and takes a key at
# face value; a THIRD-PARTY typed reader does not - it resolves a key that spells a bool or
# null word to True/False/None instead of to the string. The words are the `regexp` field of
# the bool and null type pages of the YAML 1.1 core schema - https://yaml.org/type/bool.html
# and https://yaml.org/type/null.html - not PyYAML's own resolver, which (checked in
# yaml/resolver.py) omits the single-letter y/Y/n/N the specification itself lists.
_YAML11_BOOL_WORDS = (
    "y", "Y", "yes", "Yes", "YES", "n", "N", "no", "No", "NO",
    "true", "True", "TRUE", "false", "False", "FALSE",
    "on", "On", "ON", "off", "Off", "OFF",
)
_YAML11_NULL_WORDS = ("null", "Null", "NULL")  # "~" is not an identifier; op_add_field
                                                # refuses it before the mapping writer is
                                                # even reached, so it is covered only through
                                                # op_set_localization below.


@pytest.mark.parametrize("word", _YAML11_BOOL_WORDS + _YAML11_NULL_WORDS)
def test_add_field_quotes_a_special_word_key(element: Path, word: str):
    """add-field's mapping writer is the other place a key is written bare."""
    _add(element, "строка", word, "Текст")

    assert _loaded(element)["Строки"][word] == "Текст"


@pytest.mark.parametrize("word", _YAML11_BOOL_WORDS + _YAML11_NULL_WORDS + ("~",))
def test_set_localization_quotes_a_special_word_key(element: Path, word: str):
    """set-localization's writer is the one the backlog item names."""
    _set(element, word, {"Русский": "Включено"})

    assert _loaded(element)["Строки"][word] == "Включено"


def test_an_ordinary_key_is_still_written_bare(element: Path):
    """Quoting is narrow: a key that is not a special word gets no extra noise."""
    _add(element, "строка", "Заголовок", "Текст")

    text = io.open(element, encoding="utf-8-sig").read()
    assert "Заголовок: Текст" in text
    assert '"Заголовок"' not in text


def test_the_tools_own_reader_still_sees_a_quoted_key(element: Path):
    """_section_entries already strips a value's surrounding quotes; it has to do the same
    for a key now that the writer may quote one."""
    _add(element, "строка", "On", "Включено")

    text = io.open(element, encoding="utf-8-sig").read()
    assert scaffold._section_entries(text) == {"On": "Включено"}


def test_a_bare_special_word_key_written_before_this_fix_still_reads():
    """A file written before this change has the key bare - the reader must not regress."""
    text = "ВидЭлемента: ЛокализованныеСтроки\nИмя: Тексты\nСтроки:\n    On: Включено\n"

    assert scaffold._section_entries(text) == {"On": "Включено"}


def test_setting_a_special_word_key_again_updates_in_place_not_duplicated(element: Path):
    _set(element, "On", {"Русский": "Включено"})

    _set(element, "On", {"Русский": "Выключено"})

    text = io.open(element, encoding="utf-8-sig").read()
    assert text.count('"On":') == 1
    assert _loaded(element)["Строки"]["On"] == "Выключено"


def test_add_field_refuses_a_special_word_key_already_present(element: Path):
    """The duplicate check has to recognize the key even though it is now written quoted."""
    _add(element, "строка", "On", "Включено")

    with pytest.raises(scaffold.ScaffoldError):
        _add(element, "строка", "On", "Опять")


def test_a_special_word_key_reaches_the_translation_quoted_too(element: Path):
    _add(element, "строка", "Первая", "Первый текст")
    _write(scaffold.op_add_localization(element, "En"))

    _add(element, "строка", "On", "Включено")

    translation = _translation(element)
    assert _loaded(translation)["Строки"]["On"] == "Включено"
    assert '"On":' in io.open(translation, encoding="utf-8-sig").read()


def test_a_special_word_key_keeps_its_section_when_quoted(element: Path):
    _add(element, "шаблон", "On", "Вкл, %0!")

    _set(element, "On", {"Русский": "Выкл, %0!"})

    loaded = _loaded(element)
    assert loaded["Шаблоны"]["On"] == "Выкл, %0!"
    assert "On" not in (loaded.get("Строки") or {})
