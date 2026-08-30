"""Checks of the yaml/col-width-needs-no-stretch rule (a column width that turns into a share)."""

import pytest

from xbsl import engine

RULE = "yaml/col-width-needs-no-stretch"
SIBLING = "yaml/size-needs-no-stretch"


def _lint(name, content, **kw):
    return engine.run_sources([engine.load_text(name, content)], **kw)


def _form(columns: str) -> str:
    """A minimal interface yaml object with a dynamic-list table and the given columns."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 2b1c37a2-2222-4222-8222-222222222222\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Содержимое:\n"
        "        -\n"
        "            Тип: Таблица<ДинамическийСписок>\n"
        "            Колонки:\n"
        + columns
    )


def test_col_width_without_stretch_key_flagged():
    content = _form(
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: 40\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert len(d) == 1
    assert d[0].severity.value == "info"
    assert "РастягиватьПоГоризонтали" in d[0].message
    assert "МинимальнаяШирина" in d[0].message
    assert (d[0].line, d[0].col) == (12, 21)  # the line of the 'Ширина' key


def test_col_explicit_stretch_of_any_kind_is_deliberate():
    # An explicitly written value of ANY kind is the author's choice, no hint given
    for value in ("Ложь", "Истина", "Авто", "=Общее.ЭтоУзкийЭкран()"):
        content = _form(
            "                -\n"
            "                    Тип: СтандартнаяКолонкаТаблицы\n"
            "                    Ширина: 40\n"
            f"                    РастягиватьПоГоризонтали: {value}\n"
        )
        assert _lint("Ф.yaml", content, select={RULE}) == [], value


def test_col_all_three_column_kinds_checked():
    content = _form(
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: 40\n"
        "                -\n"
        "                    Тип: КолонкаТаблицы\n"
        "                    Ширина: 120\n"
        "                -\n"
        "                    Тип: ПроизвольнаяКолонкаТаблицы\n"
        "                    Ширина: 200\n"
    )
    d = _lint("Ф.yaml", content, select={RULE})
    assert sorted(x.line for x in d) == [12, 15, 18]


def test_col_auto_binding_and_zero_widths_skipped():
    content = _form(
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: Авто\n"
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: =Общее.ШиринаКолонки()\n"
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: 0\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_col_parameterized_type_head_is_stripped():
    # A generic argument does not hide the column kind from the rule
    content = _form(
        "                -\n"
        "                    Тип: ПроизвольнаяКолонкаТаблицы<Строка>\n"
        "                    Ширина: 88\n"
    )
    assert len(_lint("Ф.yaml", content, select={RULE})) == 1


def test_col_height_axis_not_judged():
    # Only the Width axis is surveyed; a column height stays out of the rule
    content = _form(
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Высота: 40\n"
    )
    assert _lint("Ф.yaml", content, select={RULE}) == []


def test_col_rule_and_sibling_enable_separately():
    # The point of a separate rule: the column check is silent about HtmlContainer,
    # and yaml/size-needs-no-stretch stays silent about columns
    column = _form(
        "                -\n"
        "                    Тип: СтандартнаяКолонкаТаблицы\n"
        "                    Ширина: 40\n"
    )
    container = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 2b1c37a2-2222-4222-8222-222222222223\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Содержимое:\n"
        "        -\n"
        "            Тип: КонтейнерHtml\n"
        "            Ширина: 320\n"
    )
    assert _lint("Ф.yaml", column, select={SIBLING}) == []
    assert _lint("Ф.yaml", container, select={RULE}) == []


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_col_english_markup_flagged_with_english_advice():
    content = (
        "ElementKind: InterfaceComponent\n"
        "Id: 2b1c37a2-2222-4222-8222-222222222224\n"
        "Name: F\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: Table<DynamicList>\n"
        "            Columns:\n"
        "                -\n"
        "                    Type: StandardTableColumn\n"
        "                    Width: 40\n"
    )
    d = _lint("F.yaml", content, select={RULE})
    assert len(d) == 1
    assert "HorizontalStretch" in d[0].message
    assert "MinWidth" in d[0].message


@pytest.mark.needs_data  # the key spelling pair comes from the platform dictionaries
def test_col_english_stretch_key_silences_the_rule():
    content = (
        "ElementKind: InterfaceComponent\n"
        "Id: 2b1c37a2-2222-4222-8222-222222222225\n"
        "Name: F\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        "            Type: Table<DynamicList>\n"
        "            Columns:\n"
        "                -\n"
        "                    Type: StandardTableColumn\n"
        "                    Width: 40\n"
        "                    HorizontalStretch: False\n"
    )
    assert _lint("F.yaml", content, select={RULE}) == []


def test_col_non_object_yaml_skipped():
    # A file without an element kind (structural) is not checked
    content = (
        "Имя: Фрагмент\n"
        "Колонки:\n"
        "    -\n"
        "        Тип: СтандартнаяКолонкаТаблицы\n"
        "        Ширина: 40\n"
    )
    assert _lint("Фрагмент.yaml", content, select={RULE}) == []


def test_col_xbsl_file_skipped():
    assert _lint("М.xbsl", "метод Ф()\n;\n", select={RULE}) == []


# The default-off state is NOT asserted here: in a process with the plugin installed the
# project profile turns the rule on, and such a test would judge the machine rather than
# the engine. The default is guarded by tests/test_metadata_sync.py, which reads the
# registry in a subprocess with XBSL_NO_PLUGINS=1.
