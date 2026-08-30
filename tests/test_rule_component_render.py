"""Checks of the render-combination rules: yaml/badge-column-image, yaml/value-choice-title."""

import pytest

from xbsl import engine

BADGE_RULE = "yaml/badge-column-image"
TITLE_RULE = "yaml/value-choice-title"


def _lint(name, content, rule):
    return engine.run_sources([engine.load_text(name, content)], select={rule})


def _table_form(columns: str) -> str:
    """A minimal interface yaml with a table and the given column list (lines from 10)."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 1e0e26f1-2222-4111-8111-111111111111\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n"
        "        Тип: Таблица<СтрокаСписка>\n"
        "        Данные: =Список\n"
        "        Колонки:\n"
        + columns
    )


def _choice_form(items: str) -> str:
    """A minimal interface yaml with a vertical group and the given items (lines from 10)."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 1e0e26f1-3333-4111-8111-111111111111\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Форма\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Компоновка: Вертикальная\n"
        "        Содержимое:\n"
        + items
    )


# --- yaml/badge-column-image ------------------------------------------------------------


@pytest.mark.needs_data  # the spellings and the enum values come from the ui schema
def test_a_badge_column_with_an_image_is_reported():
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Вид: Значок\n"
        "                Изображение: =ДанныеСтроки.Иконка\n"
    )
    d = _lint("Ф.yaml", content, BADGE_RULE)
    assert [(x.rule_id, x.line, x.col) for x in d] == [(BADGE_RULE, 13, 17)]
    assert d[0].severity.value == "warning"
    assert "Картинка" in d[0].message


@pytest.mark.needs_data  # the spellings and the enum values come from the ui schema
def test_a_qualified_badge_spelling_is_reported():
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Вид: ВидКолонкиТаблицы.Значок\n"
        "                Изображение: =ДанныеСтроки.Иконка\n"
    )
    d = _lint("Ф.yaml", content, BADGE_RULE)
    assert [(x.rule_id, x.line) for x in d] == [(BADGE_RULE, 13)]


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_english_badge_spellings_are_reported():
    content = _table_form(
        "            -\n"
        "                Type: StandardTableColumn<СтрокаСписка>\n"
        "                Kind: Badge\n"
        "                Image: =ДанныеСтроки.Icon\n"
    )
    d = _lint("Ф.yaml", content, BADGE_RULE)
    assert [(x.rule_id, x.line) for x in d] == [(BADGE_RULE, 13)]
    # The advice spells the picture kind the way the file spells the badge.
    assert "Kind: Picture" in d[0].message


def test_a_picture_column_keeps_its_image():
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Вид: Картинка\n"
        "                Изображение: =ДанныеСтроки.Фото\n"
    )
    assert _lint("Ф.yaml", content, BADGE_RULE) == []


def test_a_badge_column_without_an_image_is_silent():
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Вид: Значок\n"
        "                ПолеЗначения: Статус\n"
    )
    assert _lint("Ф.yaml", content, BADGE_RULE) == []


def test_an_image_without_a_kind_is_the_mixed_mode():
    # The working replacement: at the automatic kind the picture stands next to the text.
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Изображение: =ДанныеСтроки.Картинка\n"
        "                ПолеЗначения: Название\n"
    )
    assert _lint("Ф.yaml", content, BADGE_RULE) == []


def test_a_binding_column_kind_is_not_judged():
    content = _table_form(
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаСписка>\n"
        "                Вид: =ВидКолонки()\n"
        "                Изображение: =ДанныеСтроки.Иконка\n"
    )
    assert _lint("Ф.yaml", content, BADGE_RULE) == []


# --- yaml/value-choice-title ------------------------------------------------------------


@pytest.mark.needs_data  # the spellings and the enum values come from the ui schema
def test_a_titled_switcher_is_reported():
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                Заголовок: Режим показа\n"
        "                ВидОтображенияПереключателя: Переключатель\n"
    )
    d = _lint("Ф.yaml", content, TITLE_RULE)
    assert [(x.rule_id, x.line, x.col) for x in d] == [(TITLE_RULE, 12, 17)]
    assert d[0].severity.value == "warning"
    assert "Надписью" in d[0].message


@pytest.mark.needs_data  # the spellings and the enum values come from the ui schema
def test_a_qualified_switcher_spelling_is_reported():
    # The title as a localized reference is flagged alike: it is not drawn either.
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                Заголовок: $Локализация.Источник\n"
        "                ВидОтображенияПереключателя: ВидОтображенияПереключателя.Переключатель\n"
    )
    d = _lint("Ф.yaml", content, TITLE_RULE)
    assert [(x.rule_id, x.line) for x in d] == [(TITLE_RULE, 12)]


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_english_switcher_spellings_are_reported():
    content = _choice_form(
        "            -\n"
        "                Type: ValueChoice<Строка?>\n"
        "                Title: Display mode\n"
        "                SwitcherDisplayKind: Switcher\n"
    )
    d = _lint("Ф.yaml", content, TITLE_RULE)
    assert [(x.rule_id, x.line) for x in d] == [(TITLE_RULE, 12)]


def test_a_radio_group_keeps_its_title():
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                Заголовок: Вариант\n"
        "                ВидОтображенияПереключателя: ГруппаРадиоКнопок\n"
    )
    assert _lint("Ф.yaml", content, TITLE_RULE) == []


def test_a_switcher_without_a_title_is_silent():
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                ВидОтображенияПереключателя: Переключатель\n"
    )
    assert _lint("Ф.yaml", content, TITLE_RULE) == []


def test_no_explicit_switcher_kind_is_not_judged():
    # What the automatic display kind resolves to is not documented.
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                Заголовок: Тема\n"
    )
    assert _lint("Ф.yaml", content, TITLE_RULE) == []


def test_an_array_argument_is_a_checkbox_group():
    # The switcher display kind does not apply to a multi-value choice.
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Массив<Строка>>\n"
        "                Заголовок: Набор\n"
        "                ВидОтображенияПереключателя: Переключатель\n"
    )
    assert _lint("Ф.yaml", content, TITLE_RULE) == []


def test_a_binding_switcher_kind_is_not_judged():
    content = _choice_form(
        "            -\n"
        "                Тип: ВыборЗначения<Строка?>\n"
        "                Заголовок: Прочее\n"
        "                ВидОтображенияПереключателя: =ВидПереключателя()\n"
    )
    assert _lint("Ф.yaml", content, TITLE_RULE) == []


def test_render_combo_rules_skip_non_yaml_sources():
    assert _lint("М.xbsl", "метод Ф()\n;\n", BADGE_RULE) == []
    assert _lint("М.xbsl", "метод Ф()\n;\n", TITLE_RULE) == []
