"""yaml/size-needs-no-stretch by component kind: the measured stretch at the auto value.

The rule judges only the kinds a live page showed stretching at `Auto`, each along the axes it
stretched along, and a list kind additionally needs a scroll of its own for its height to hold.
"""

import pytest

from xbsl import dataset, engine
from xbsl.rules import size_stretch

RULE = "yaml/size-needs-no-stretch"


def _lint(content, name="Ф.yaml"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _form(node: str) -> str:
    """A minimal interface yaml object holding one component node (the node lines indented 12)."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 1e0e26f1-2222-4222-8222-222222222222\n"
        "Имя: Ф\n"
        "Наследует:\n"
        "    Тип: Группа\n"
        "    Компоновка: Вертикальная\n"
        "    Содержимое:\n"
        "        -\n"
        + node
    )


def _node(kind: str, *lines: str) -> str:
    return "".join(f"            {line}\n" for line in (f"Тип: {kind}", *lines))


TABLE = "Таблица<ИсточникДанныхМассив<Задачи.Строка>>"

#: The kinds measured as stretching along both axes at the auto value.
BOTH_AXES = [
    "КонтейнерHtml", TABLE, "СтандартныйСписок<ИсточникДанныхМассив<Задачи.Строка>>",
    "ПроизвольныйСписок<ДинамическийСписок>", "ФорматированныйДокумент", "ПросмотрPdf",
    "ДиаграммаСпидометр<Задачи.Строка>", "КруговаяДиаграмма<Задачи.Строка>", "РазделяющаяГруппа",
]
#: The kinds measured as stretching along the width only.
WIDTH_ONLY = ["Страницы", "ПанельТегов<Строка>", "ПанельЭтапов<Строка>", "СписокФайлов"]
#: The kinds measured as keeping a set size at the auto value along both axes.
KEEP_SIZE = [
    "Надпись", "Картинка", "ПолеВвода<Строка>", "Кнопка", "Флажок", "Группа", "СтековаяГруппа",
    "СворачиваемыйКомпонент", "СтандартнаяКарточка", "ПроизвольнаяКарточка", "КомпонентВыбора",
    "ВыборЗначения<Строка>", "РедакторHtml", "ВыборФайлов",
]


@pytest.mark.parametrize("kind", BOTH_AXES)
def test_kinds_stretching_both_ways_are_judged_on_both_axes(kind):
    d = _lint(_form(_node(kind, "Высота: 120", "Ширина: 90")))
    assert [x.line for x in d] == [10, 11], kind


@pytest.mark.parametrize("kind", WIDTH_ONLY)
def test_kinds_stretching_in_width_only_keep_their_height(kind):
    d = _lint(_form(_node(kind, "Высота: 120", "Ширина: 90")))
    # only the width is overridden; the height of these kinds holds without the key
    assert [x.line for x in d] == [11], kind
    assert "РастягиватьПоГоризонтали" in d[0].message


@pytest.mark.parametrize("kind", KEEP_SIZE)
def test_kinds_measured_as_keeping_their_size_are_left_alone(kind):
    assert _lint(_form(_node(kind, "Высота: 120", "Ширина: 90"))) == [], kind


def test_the_message_names_the_kind_without_its_type_arguments():
    d = _lint(_form(_node(TABLE, "Ширина: 90")))
    assert len(d) == 1
    assert "Таблица" in d[0].message and "ИсточникДанныхМассив" not in d[0].message


def test_a_table_height_without_the_key_names_both_keys():
    d = _lint(_form(_node(TABLE, "Высота: 200")))
    assert len(d) == 1
    assert "РастягиватьПоВертикали" in d[0].message
    assert "ПрокруткаПоВертикали" in d[0].message


def test_a_table_that_scrolls_already_needs_only_the_stretch_key():
    d = _lint(_form(_node(TABLE, "Высота: 200", "ПрокруткаПоВертикали: Истина")))
    assert len(d) == 1
    assert "РастягиватьПоВертикали" in d[0].message
    assert "ПрокруткаПоВертикали" not in d[0].message


def test_a_table_with_the_stretch_off_but_no_scroll_is_reported():
    # the stretch off alone: the list grows with its rows, the height is a lower bound
    d = _lint(_form(_node(TABLE, "Высота: 200", "РастягиватьПоВертикали: Ложь")))
    assert [(x.rule_id, x.line) for x in d] == [(RULE, 10)]
    assert "ПрокруткаПоВертикали" in d[0].message


def test_a_table_with_the_scroll_switched_off_explicitly_is_reported():
    d = _lint(_form(_node(
        TABLE, "Высота: 200", "РастягиватьПоВертикали: Ложь", "ПрокруткаПоВертикали: Ложь",
    )))
    assert len(d) == 1


def test_the_stretch_off_and_a_scroll_hold_the_height_of_a_table():
    content = _form(_node(
        TABLE, "Высота: 200", "РастягиватьПоВертикали: Ложь", "ПрокруткаПоВертикали: Истина",
    ))
    assert _lint(content) == []


@pytest.mark.parametrize("kind", [
    "СтандартныйСписок<ИсточникДанныхМассив<Задачи.Строка>>",
    "ПроизвольныйСписок<ДинамическийСписок>",
])
def test_the_other_lists_need_the_scroll_as_well(kind):
    assert len(_lint(_form(_node(kind, "Высота: 200", "РастягиватьПоВертикали: Ложь")))) == 1
    assert _lint(_form(_node(
        kind, "Высота: 200", "РастягиватьПоВертикали: Ложь", "ПрокруткаПоВертикали: Истина",
    ))) == []


def test_a_bound_scroll_is_the_authors_call():
    content = _form(_node(
        TABLE, "Высота: 200", "РастягиватьПоВертикали: Ложь", "ПрокруткаПоВертикали: =Длинный",
    ))
    assert _lint(content) == []


def test_a_stretching_table_with_a_height_is_a_deliberate_choice():
    # `True` with a height: the author wants the table to fill the space
    content = _form(_node(TABLE, "Высота: 420", "РастягиватьПоВертикали: Истина"))
    assert _lint(content) == []


def test_the_width_of_a_table_holds_with_the_stretch_off_alone():
    assert _lint(_form(_node(TABLE, "Ширина: 300", "РастягиватьПоГоризонтали: Ложь"))) == []


def test_a_scroll_alone_does_not_stop_the_stretch():
    # the scroll without the key: the table still stretches over the parent's leftover space
    d = _lint(_form(_node(TABLE, "Высота: 200", "ПрокруткаПоВертикали: Истина")))
    assert len(d) == 1


def test_a_multi_line_input_field_stretches_in_width_only():
    content = _form(_node(
        "ПолеВвода<Строка>", "Высота: 120", "Ширина: 300",
        "НастройкиВводаСтроки:", "    Многострочная: Истина",
    ))
    d = _lint(content)
    assert [x.line for x in d] == [11]
    assert "РастягиватьПоГоризонтали" in d[0].message


def test_a_single_line_input_field_keeps_its_width():
    content = _form(_node(
        "ПолеВвода<Строка>", "Ширина: 300", "НастройкиВводаСтроки:", "    Многострочная: Ложь",
    ))
    assert _lint(content) == []


def test_a_multi_line_input_field_with_the_stretch_off_is_left_alone():
    content = _form(_node(
        "ПолеВвода<Строка>", "Ширина: 300", "РастягиватьПоГоризонтали: Ложь",
        "НастройкиВводаСтроки:", "    Многострочная: Истина",
    ))
    assert _lint(content) == []


def test_every_measured_kind_is_a_component_with_both_stretch_properties():
    schema = dataset.load_ui_schema()
    if not schema:
        pytest.skip("no ui schema data")
    components = schema.get("components") or {}
    for kind in size_stretch._STRETCH_AT_AUTO:
        props = (components.get(kind) or {}).get("props") or {}
        assert "РастягиватьПоВертикали" in props and "РастягиватьПоГоризонтали" in props, kind
    assert size_stretch._SCROLLED_LISTS <= set(size_stretch._STRETCH_AT_AUTO)
    for kind in size_stretch._SCROLLED_LISTS:
        assert "ПрокруткаПоВертикали" in components[kind]["props"], kind


def _english_form(node: str) -> str:
    return (
        "ElementKind: InterfaceComponent\n"
        "Id: 1e0e26f1-2222-4222-8222-222222222223\n"
        "Name: Panel\n"
        "Inherits:\n"
        "    Type: Group\n"
        "    Content:\n"
        "        -\n"
        + node
    )


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_a_table_height_in_english_markup_names_both_keys_in_english():
    content = _english_form(
        "            Type: Table<ArrayDataSource<Tasks.Row>>\n"
        "            Name: Steps\n"
        "            Height: 200\n"
    )
    d = _lint(content, "Panel.yaml")
    assert [(x.rule_id, x.line) for x in d] == [(RULE, 10)]
    assert "VerticalStretch" in d[0].message and "VerticalScroll" in d[0].message


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_the_english_pair_holds_the_height_of_a_table():
    stretch_off = (
        "            Type: Table<ArrayDataSource<Tasks.Row>>\n"
        "            Height: 200\n"
        "            VerticalStretch: False\n"
    )
    d = _lint(_english_form(stretch_off), "Panel.yaml")
    assert len(d) == 1 and "VerticalScroll" in d[0].message
    both = stretch_off + "            VerticalScroll: True\n"
    assert _lint(_english_form(both), "Panel.yaml") == []


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_a_multi_line_input_field_in_english_markup():
    content = _english_form(
        "            Type: Edit<String>\n"
        "            Height: 120\n"
        "            Width: 300\n"
        "            StringInputSettings:\n"
        "                Multiline: True\n"
    )
    d = _lint(content, "Panel.yaml")
    assert [x.line for x in d] == [10]
    assert "HorizontalStretch" in d[0].message


@pytest.mark.needs_data  # the English spellings come from the platform dictionaries
def test_width_only_kinds_in_english_markup():
    content = _english_form(
        "            Type: Pages\n"
        "            Height: 120\n"
        "            Width: 90\n"
    )
    d = _lint(content, "Panel.yaml")
    assert [x.line for x in d] == [10]
    assert "HorizontalStretch" in d[0].message
