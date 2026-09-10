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
