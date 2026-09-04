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
    "Имя: Demo\nВерсия: 1.0.0\nРежимСовместимости: 10.0\n"
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
