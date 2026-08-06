"""Правило conventions/untranslated-visible-literal."""

import pytest

from xbsl import engine, i18n

RULE = "conventions/untranslated-visible-literal"


@pytest.fixture(autouse=True)
def _ru_lang():
    # Тесты сверяют русский текст; язык окружения не должен на них влиять.
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _descriptor(languages="[Русский, Английский]"):
    return engine.load_text(
        "Проект.yaml",
        f"Ид: 019ef4c8-232f-7f33-9da6-c3604720b33c\nИмя: site\n"
        f"ЯзыкиЛокализации: {languages}\n",
    )


def _object(name, body):
    return engine.load_text(
        f"{name}.yaml",
        f"ВидЭлемента: КомпонентИнтерфейса\nИд: 019ef4c8-232f-7f33-9da6-c3604720b3{name[-2:]}\n"
        f"Имя: {name}\n{body}",
    )


def _lint(*sources, languages="[Русский, Английский]"):
    return engine.run_sources([_descriptor(languages), *sources], select={RULE})


#: Объект, который свою подпись локализует – он и задаёт "намерение проекта".
_ЛОКАЛИЗОВАННЫЙ = _object("Ф1", "Содержимое:\n    Заголовок: $Словарь.Привет\n")


def test_literal_flagged_when_key_is_localized_elsewhere():
    d = _lint(_ЛОКАЛИЗОВАННЫЙ, _object("Ф2", "Содержимое:\n    Заголовок: Привет\n"))
    assert len(d) == 1 and "Заголовок" in d[0].message and "Привет" in d[0].message


def test_single_language_project_silent():
    """Гейт: на одноязычном проекте локализовывать нечего."""
    d = _lint(_ЛОКАЛИЗОВАННЫЙ, _object("Ф2", "Содержимое:\n    Заголовок: Привет\n"),
              languages="[Русский]")
    assert not d


def test_key_never_localized_silent():
    """Правило самонастраиваемое: судятся только ключи, которые проект где-то вынес."""
    d = _lint(_object("Ф2", "Содержимое:\n    Заголовок: Привет\n"))
    assert not d


def test_same_key_on_other_element_kind_silent():
    """Намерение считается в разрезе вида элемента: свойства-тёзки у разных видов – разные.

    Живой случай: "Описание" карточки компонента локализовано словарём, а "Описание"
    события журнала – документация оператору, и судить его по чужому намерению нельзя.
    """
    d = _lint(
        _object("Ф1", "Содержимое:\n    Описание: $Словарь.Привет\n"),
        engine.load_text(
            "Событие.yaml",
            "ВидЭлемента: СобытиеЖурналаСобытий\nИмя: Событие\n"
            "Описание: Отказ обращения к сервису\n"
            "Свойства:\n    -\n        Имя: Метод\n        Тип: Строка\n"
            "        Описание: Путь группы и метода\n",
        ),
    )
    assert not d


def test_same_key_same_element_kind_flagged():
    """Контроль к разрезу по виду: внутри ОДНОГО вида элемента тёзка судится как прежде."""
    d = _lint(
        _object("Ф1", "Содержимое:\n    Описание: $Словарь.Привет\n"),
        _object("Ф2", "Содержимое:\n    Описание: Привет\n"),
    )
    assert len(d) == 1 and "Описание" in d[0].message


def test_expression_value_silent():
    """Значение с '=' – выражение, а не текст: оно может звать словарь само."""
    d = _lint(_ЛОКАЛИЗОВАННЫЙ,
              _object("Ф2", "Содержимое:\n    Заголовок: =СеоЗаголовок()\n"))
    assert not d


def test_top_level_presentation_silent():
    """Представление верхнего уровня объекта – ИМЯ ПОЛЯ, его держит yaml/presentation-field."""
    d = _lint(
        engine.load_text("Спр.yaml",
                         "ВидЭлемента: Справочник\nИмя: Спр\nПредставление: Наименование\n"),
        _object("Ф1", "Содержимое:\n    Представление: $Словарь.Привет\n"),
    )
    assert not d


def test_dictionary_file_silent():
    """В словаре ключ и есть текст – судить его нечем."""
    d = _lint(
        _ЛОКАЛИЗОВАННЫЙ,
        engine.load_text("Словарь.yaml",
                         "ВидЭлемента: ЛокализованныеСтроки\nИмя: Словарь\n"
                         "Строки:\n    Заголовок: Привет\n"),
    )
    assert not d


def test_technical_key_silent():
    d = _lint(_ЛОКАЛИЗОВАННЫЙ,
              engine.load_text("Ф2.yaml",
                               "ВидЭлемента: КомпонентИнтерфейса\nИмя: Кириллица\n"
                               "Содержимое:\n    Заголовок: $Словарь.Привет\n"))
    assert not d


def test_message_is_bilingual():
    i18n.set_lang("en")
    d = _lint(_ЛОКАЛИЗОВАННЫЙ, _object("Ф2", "Содержимое:\n    Заголовок: Привет\n"))
    assert d and "localization language" in d[0].message
