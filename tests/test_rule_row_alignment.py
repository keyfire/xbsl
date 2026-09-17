"""Rows whose children stand on different baselines.

A horizontal group with no explicit vertical alignment lines its children up on the baseline.
A native `Button` keeps its baseline on the caption and a native `Picture` on its bottom edge,
so the two end up at different heights (19 px on a live row). Two rules judge that pair:

- `yaml/insert-row-needs-align` (file scope) - the pair standing in the row directly, next to
  the insert case the rule has judged from the start;
- `yaml/component-row-needs-align` (project scope) - a neighbour drawn by a project component,
  expanded only as far as the component can be read statically.

The literal Russian cases need no Element data. Everything that reads a binding or a module goes
through the parser, whose tables live in the data, so those tests are marked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl.cli import discover
from xbsl.engine import run

ROW_RULE = "yaml/insert-row-needs-align"
COMPONENT_RULE = "yaml/component-row-needs-align"


def _lint(tmp_path, files: dict[str, str], rule_id: str) -> list[tuple[str, int, int, str]]:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    found = run(discover([str(tmp_path)]), select={rule_id})
    return [(Path(d.path).name, d.line, d.col, d.message) for d in found]


_SHOWCASE = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 0f0f0f0f-9999-aaaa-bbbb-cccccccccccc\n"
    "Имя: ВитринаПроб\n"
    "ОбластьВидимости: ВПодсистеме\n"
    "Наследует:\n"
    "    Тип: ПроизвольныйКомпонент\n"
    "    Содержимое:\n"
    "        Тип: Группа\n"
    "        Имя: Шеренга\n"
    "        Компоновка: {layout}\n"
    "{align}"
    "        Содержимое:\n"
    "{children}"
)

#: The position of the row's layout key in `_SHOWCASE` - where both rules report.
_ROW_KEY = (10, 9)

#: A ternary layout binding. It is written without spaces around the colon: yaml reads ` : `
#: inside a plain scalar as the start of a nested mapping.
_BY_WIDTH = "=Теснота.Тесно()?КомпоновкаСодержимого.Вертикальная:КомпоновкаСодержимого.Горизонтальная"


def _showcase(children: str, layout: str = "Горизонтальная", align: str = "") -> str:
    aligned = f"        ВыравниваниеСодержимогоПоВертикали: {align}\n" if align else ""
    return _SHOWCASE.format(layout=layout, align=aligned, children=children)


def _child(kind: str, name: str, *extra: str) -> str:
    lines = ["            -\n", f"                Тип: {kind}\n", f"                Имя: {name}\n"]
    lines += [f"                {line}\n" for line in extra]
    return "".join(lines)


BUTTON = _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть")
PICTURE = _child("Картинка", "Эмблема")
LABEL = _child("Надпись", "Эскиз", "Значение: Текст")


# --- yaml/insert-row-needs-align: the native pair --------------------------------------------


def test_a_button_next_to_a_picture_is_flagged(tmp_path):
    found = _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(BUTTON + PICTURE)}, ROW_RULE)
    assert len(found) == 1, found
    _name, line, col, message = found[0]
    assert (line, col) == _ROW_KEY
    assert "Центр" in message
    assert "Толкнуть" in message and "Эмблема" in message


def test_the_order_of_the_pair_does_not_matter(tmp_path):
    found = _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(PICTURE + LABEL + BUTTON)}, ROW_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]


def test_an_explicit_alignment_silences_the_pair(tmp_path):
    text = _showcase(BUTTON + PICTURE, align="Центр")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE) == []


def test_a_vertical_group_is_not_a_row_for_the_pair(tmp_path):
    text = _showcase(BUTTON + PICTURE, layout="Вертикальная")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE) == []


def test_a_button_next_to_a_label_is_not_judged(tmp_path):
    """No measurement stands behind this pair, so the rule does not guess."""
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(BUTTON + LABEL)}, ROW_RULE) == []


def test_neighbours_of_one_kind_share_a_baseline(tmp_path):
    buttons = BUTTON + _child("Кнопка", "Толкач", "Заголовок: Ещё")
    pictures = PICTURE + _child("Картинка", "Эскиз")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(buttons)}, ROW_RULE) == []
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(pictures)}, ROW_RULE) == []


@pytest.mark.parametrize("button", [
    _child("Кнопка", "Толкнуть", "Изображение: Значок.svg"),
    _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", "ВидОтображенияЗаголовка: Иконка"),
    _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", "Вид: ИконкаДействия"),
], ids=["no-caption", "icon-display", "action-icon"])
def test_a_button_without_a_visible_caption_is_not_judged(tmp_path, button):
    """The measured button had a caption; an icon-only one has not been measured."""
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(button + PICTURE)}, ROW_RULE) == []


def test_a_neighbour_aligned_on_its_own_is_not_judged(tmp_path):
    picture = _child("Картинка", "Эмблема", "ВыравниваниеВГруппеПоВертикали: Центр")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(BUTTON + picture)}, ROW_RULE) == []


def test_a_hidden_neighbour_is_not_a_pair(tmp_path):
    picture = _child("Картинка", "Эмблема", "Видимость: Ложь")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(BUTTON + picture)}, ROW_RULE) == []


def test_a_button_inside_a_card_is_not_a_direct_neighbour(tmp_path):
    card = (
        "            -\n"
        "                Тип: Группа\n"
        "                Имя: Остов\n"
        "                Компоновка: Вертикальная\n"
        "                Содержимое:\n"
        "                    -\n"
        "                        Тип: Надпись\n"
        "                        Значение: Текст\n"
        "                    -\n"
        "                        Тип: Кнопка\n"
        "                        Заголовок: Толкнуть\n"
    )
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(card + PICTURE)}, ROW_RULE) == []


def test_a_row_with_an_insert_keeps_the_insert_message(tmp_path):
    insert = _child("КонтейнерHtml", "Вставка")
    found = _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(insert + BUTTON + PICTURE)}, ROW_RULE)
    assert len(found) == 1, found
    assert "КонтейнерHtml" in found[0][3]


@pytest.mark.needs_data
def test_a_row_horizontal_in_one_branch_of_a_binding_is_judged(tmp_path):
    text = _showcase(BUTTON + PICTURE, layout=_BY_WIDTH)
    found = _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]


@pytest.mark.needs_data
def test_a_binding_without_a_horizontal_branch_is_not_a_row(tmp_path):
    layout = _BY_WIDTH.replace("Горизонтальная", "ПоКолонкам")
    text = _showcase(BUTTON + PICTURE, layout=layout)
    assert _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE) == []


@pytest.mark.needs_data
def test_an_insert_under_a_binding_row_is_flagged(tmp_path):
    insert = _child("КонтейнерHtml", "Вставка") + LABEL
    found = _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(insert, layout=_BY_WIDTH)}, ROW_RULE)
    assert len(found) == 1, found
    assert "КонтейнерHtml" in found[0][3]


@pytest.mark.needs_data
@pytest.mark.parametrize("button_visible, picture_visible", [
    ("=Облик == ОбликПлитки.Клавишей", "=Облик == ОбликПлитки.Рисунком"),
    ("=Показ", "=не Показ"),
    ("=Список.Количество() > 0", "=Список.Количество() == 0"),
], ids=["enum-values", "negation", "related-comparisons"])
def test_neighbours_shown_in_separate_states_are_not_a_pair(
    tmp_path, button_visible, picture_visible,
):
    button = _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", f"Видимость: {button_visible}")
    picture = _child("Картинка", "Эмблема", f"Видимость: {picture_visible}")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(button + picture)}, ROW_RULE) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("picture_visible, button_visible", [
    ("=ЕстьЭмблема", "=НетЭмблемы"),
    ("=Эмблема != Неопределено", "=ЭмблемаНеЗагружена()"),
], ids=["two-flags", "comparison-and-call"])
def test_neighbours_with_different_conditions_of_their_own_are_left_alone(
    tmp_path, picture_visible, button_visible,
):
    """The program may keep two different conditions apart - a picture, or a button in its
    place - and nothing in the file says so: both conditional over different names gives no
    answer."""
    button = _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", f"Видимость: {button_visible}")
    picture = _child("Картинка", "Эмблема", f"Видимость: {picture_visible}")
    assert _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(button + picture)}, ROW_RULE) == []


@pytest.mark.needs_data
def test_a_neighbour_whose_condition_depends_on_the_row_condition_is_left_alone(tmp_path):
    """One side is unconditional, so the pair is read; the other side's condition shares a
    name with the row's own condition in a way the text does not resolve."""
    layout = (
        "=Список.Количество() > 0?КомпоновкаСодержимого.Горизонтальная:"
        "КомпоновкаСодержимого.Вертикальная"
    )
    button = _child(
        "Кнопка", "Толкнуть", "Заголовок: Толкнуть", "Видимость: =Список.Количество() == 0",
    )
    text = _showcase(button + PICTURE, layout=layout)
    assert _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE) == []


@pytest.mark.needs_data
def test_a_conditional_neighbour_still_meets_an_unconditional_one(tmp_path):
    button = _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", "Видимость: =Показ")
    found = _lint(tmp_path, {"ВитринаПроб.yaml": _showcase(button + PICTURE)}, ROW_RULE)
    assert len(found) == 1, found


@pytest.mark.needs_data
def test_a_neighbour_shown_only_while_the_row_is_vertical_is_not_a_pair(tmp_path):
    button = _child("Кнопка", "Толкнуть", "Заголовок: Толкнуть", "Видимость: =Теснота.Тесно()")
    text = _showcase(button + PICTURE, layout=_BY_WIDTH)
    assert _lint(tmp_path, {"ВитринаПроб.yaml": text}, ROW_RULE) == []


_SHOWCASE_EN = (
    "ElementKind: InterfaceComponent\n"
    "Id: 0f0f0f0f-9999-aaaa-bbbb-cccccccccccc\n"
    "Name: ProbeShowcase\n"
    "VisibilityScope: InSubsystem\n"
    "Inherits:\n"
    "    Type: CustomComponent\n"
    "    Content:\n"
    "        Type: Group\n"
    "        Name: Rank\n"
    "        Layout: {layout}\n"
    "{align}"
    "        Content:\n"
    "{children}"
)


def _child_en(kind: str, name: str, *extra: str) -> str:
    lines = ["            -\n", f"                Type: {kind}\n", f"                Name: {name}\n"]
    lines += [f"                {line}\n" for line in extra]
    return "".join(lines)


@pytest.mark.needs_data
def test_the_pair_in_english_spelling_is_judged(tmp_path):
    children = _child_en("Button", "Nudge", "Title: Nudge") + _child_en("Picture", "Emblem")
    text = _SHOWCASE_EN.format(layout="Horizontal", align="", children=children)
    found = _lint(tmp_path / "flagged", {"ProbeShowcase.yaml": text}, ROW_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]
    aligned = _SHOWCASE_EN.format(
        layout="Horizontal", align="        ContentVerticalAlign: Center\n", children=children,
    )
    assert _lint(tmp_path / "aligned", {"ProbeShowcase.yaml": aligned}, ROW_RULE) == []


# --- yaml/component-row-needs-align ----------------------------------------------------------

_TILE = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 0f0f0f0f-5555-6666-7777-888888888888\n"
    "Имя: ПлиткаВыбора\n"
    "ОбластьВидимости: ВПодсистеме\n"
    "Наследует:\n"
    "    Тип: ПроизвольныйКомпонент\n"
    "    Содержимое:\n"
    "        Тип: Группа\n"
    "        Имя: Остов\n"
    "        Компоновка: Вертикальная\n"
    "        Содержимое:\n"
    "            -\n"
    "                Тип: Картинка\n"
    "                Имя: Эскиз\n"
    "                Видимость: {picture_visible}\n"
    "            -\n"
    "                Тип: Кнопка\n"
    "                Имя: Толкач\n"
    "                Видимость: {button_visible}\n"
    "                Заголовок: =ТекстПлитки\n"
    "            -\n"
    "                Тип: СтандартнаяКарточка\n"
    "                Имя: Пустышка\n"
    "                Видимость: {card_visible}\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: ТекстПлитки\n"
    "        Тип: Строка\n"
    "    -\n"
    "        Имя: Облик\n"
    "        Тип: ОбликПлитки?\n"
    "{extra_properties}"
)

_TILE_MODULE = "метод ЭтоКнопка(): Булево\n    возврат Облик == ОбликПлитки.Клавишей\n;\n"


def _tile_files(
    children: str,
    *,
    layout: str = _BY_WIDTH,
    align: str = "",
    picture_visible: str = "=не Теснота.Тесно() и не ЭтоКнопка()",
    button_visible: str = "=не Теснота.Тесно() и ЭтоКнопка()",
    card_visible: str = "=Теснота.Тесно()",
    extra_properties: str = "",
    module: str = _TILE_MODULE,
) -> dict[str, str]:
    tile = _TILE.format(
        picture_visible=picture_visible, button_visible=button_visible,
        card_visible=card_visible, extra_properties=extra_properties,
    )
    return {
        "ПлиткаВыбора.yaml": tile,
        "ПлиткаВыбора.xbsl": module,
        "ВитринаПроб.yaml": _showcase(children, layout=layout, align=align),
    }


def _tile(name: str, *extra: str) -> str:
    return _child("ПлиткаВыбора", name, "ТекстПлитки: Проба", *extra)


ALPHA = _tile("Альфа")
BETA_KEY = _tile("Бета", "Облик: =ОбликПлитки.Клавишей")


@pytest.mark.needs_data
def test_wrappers_drawing_a_picture_and_a_button_are_flagged(tmp_path):
    """The live shape: a wrapper component draws a picture or a native button by a property."""
    found = _lint(tmp_path, _tile_files(ALPHA + BETA_KEY), COMPONENT_RULE)
    assert len(found) == 1, found
    name, line, col, message = found[0]
    assert name == "ВитринаПроб.yaml"
    assert (line, col) == _ROW_KEY
    assert "Центр" in message
    assert "Бета" in message and "Альфа" in message


@pytest.mark.needs_data
def test_the_file_rule_does_not_judge_a_component_row(tmp_path):
    assert _lint(tmp_path, _tile_files(ALPHA + BETA_KEY), ROW_RULE) == []


@pytest.mark.needs_data
def test_wrappers_in_the_same_look_are_silent(tmp_path):
    pictures = ALPHA + _tile("Бета")
    buttons = _tile("Альфа", "Облик: =ОбликПлитки.Клавишей") + BETA_KEY
    assert _lint(tmp_path / "pictures", _tile_files(pictures), COMPONENT_RULE) == []
    assert _lint(tmp_path / "buttons", _tile_files(buttons), COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_an_explicit_alignment_silences_the_component_row(tmp_path):
    files = _tile_files(ALPHA + BETA_KEY, align="Центр")
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_literal_row_is_judged_in_the_state_the_wrappers_draw_the_pair(tmp_path):
    files = _tile_files(ALPHA + BETA_KEY, layout="Горизонтальная")
    found = _lint(tmp_path, files, COMPONENT_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]


@pytest.mark.needs_data
def test_no_state_draws_the_pair_while_the_row_is_horizontal(tmp_path):
    """The row is horizontal only in the narrow state, and there the wrappers draw a card."""
    layout = "=Теснота.Тесно()?КомпоновкаСодержимого.Горизонтальная:КомпоновкаСодержимого.Вертикальная"
    assert _lint(tmp_path, _tile_files(ALPHA + BETA_KEY, layout=layout), COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_look_computed_by_a_binding_is_unresolvable(tmp_path):
    beta = _tile("Бета", "Облик: =ВычислитьОблик()")
    assert _lint(tmp_path, _tile_files(ALPHA + beta), COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_method_doing_more_than_returning_a_comparison_is_unresolvable(tmp_path):
    module = (
        "метод ЭтоКнопка(): Булево\n"
        "    знч Ответ = Облик == ОбликПлитки.Клавишей\n"
        "    возврат Ответ\n"
        ";\n"
    )
    files = _tile_files(ALPHA + BETA_KEY, module=module)
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_variants_that_differ_beyond_the_property_are_silent(tmp_path):
    """The picture has no width condition while the button has one - the choice between them
    is not made by the property alone."""
    files = _tile_files(ALPHA + BETA_KEY, picture_visible="=не ЭтоКнопка()")
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_sibling_that_shows_with_a_variant_is_silent(tmp_path):
    files = _tile_files(ALPHA + BETA_KEY, card_visible="Истина")
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_instances_with_different_conditions_of_their_own_are_left_alone(tmp_path):
    alpha = _tile("Альфа", "Видимость: =ЕстьЭмблема")
    beta = _tile("Бета", "Облик: =ОбликПлитки.Клавишей", "Видимость: =НетЭмблемы")
    assert _lint(tmp_path, _tile_files(alpha + beta), COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_an_instance_aligned_on_its_own_is_silent(tmp_path):
    beta = _tile("Бета", "Облик: =ОбликПлитки.Клавишей", "ВыравниваниеВГруппеПоВертикали: Центр")
    assert _lint(tmp_path, _tile_files(ALPHA + beta), COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_component_name_defined_twice_is_unresolvable(tmp_path):
    files = _tile_files(ALPHA + BETA_KEY)
    files["Другая/ПлиткаВыбора.yaml"] = files["ПлиткаВыбора.yaml"].replace(
        "0f0f0f0f-5555-6666-7777-888888888888", "0f0f0f0f-5555-6666-7777-999999999999",
    )
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_boolean_property_with_a_default_picks_the_variant(tmp_path):
    extra = (
        "    -\n"
        "        Имя: КакКнопка\n"
        "        Тип: Булево\n"
        "        ЗначениеПоУмолчанию: Ложь\n"
    )
    files = _tile_files(
        ALPHA + _tile("Бета", "КакКнопка: Истина"),
        layout="Горизонтальная",
        picture_visible="=не КакКнопка", button_visible="=КакКнопка", card_visible="Ложь",
        extra_properties=extra,
    )
    found = _lint(tmp_path, files, COMPONENT_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]


_SEND_TILE = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: 0f0f0f0f-5555-6666-7777-aaaaaaaaaaaa\n"
    "Имя: ПлиткаОтправки\n"
    "ОбластьВидимости: ВПодсистеме\n"
    "Наследует:\n"
    "    Тип: ПроизвольныйКомпонент\n"
    "{root_extra}"
    "    Содержимое:\n"
    "        Тип: Кнопка\n"
    "        Имя: Толкач\n"
    "        Заголовок: Отправка\n"
    "{button_extra}"
)


@pytest.mark.needs_data
def test_a_component_drawing_a_button_unconditionally_meets_a_native_picture(tmp_path):
    files = {
        "ПлиткаОтправки.yaml": _SEND_TILE.format(root_extra="", button_extra=""),
        "ВитринаПроб.yaml": _showcase(_child("ПлиткаОтправки", "Альфа") + PICTURE),
    }
    found = _lint(tmp_path, files, COMPONENT_RULE)
    assert len(found) == 1, found
    assert "Альфа" in found[0][3] and "Эмблема" in found[0][3]
    assert _lint(tmp_path, {}, ROW_RULE) == []


@pytest.mark.needs_data
def test_a_component_inheriting_a_button_meets_a_native_picture(tmp_path):
    component = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Ид: 0f0f0f0f-5555-6666-7777-bbbbbbbbbbbb\n"
        "Имя: ПлиткаОтправки\n"
        "ОбластьВидимости: ВПодсистеме\n"
        "Наследует:\n"
        "    Тип: Кнопка\n"
        "    Заголовок: Отправка\n"
    )
    files = {
        "ПлиткаОтправки.yaml": component,
        "ВитринаПроб.yaml": _showcase(_child("ПлиткаОтправки", "Альфа") + PICTURE),
    }
    assert len(_lint(tmp_path, files, COMPONENT_RULE)) == 1


@pytest.mark.needs_data
def test_a_conditional_single_button_is_silent(tmp_path):
    files = {
        "ПлиткаОтправки.yaml": _SEND_TILE.format(
            root_extra="", button_extra="        Видимость: =Теснота.Тесно()\n"),
        "ВитринаПроб.yaml": _showcase(_child("ПлиткаОтправки", "Альфа") + PICTURE),
    }
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
@pytest.mark.parametrize("root_extra", [
    "    ВыравниваниеВГруппеПоВертикали: Центр\n",
    "    Видимость: Ложь\n",
], ids=["root-aligned", "root-hidden"])
def test_the_root_of_a_custom_component_is_read_before_its_content(tmp_path, root_extra):
    files = {
        "ПлиткаОтправки.yaml": _SEND_TILE.format(root_extra=root_extra, button_extra=""),
        "ВитринаПроб.yaml": _showcase(_child("ПлиткаОтправки", "Альфа") + PICTURE),
    }
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_an_undefined_component_type_is_silent(tmp_path):
    files = {"ВитринаПроб.yaml": _showcase(_child("НеОписанная", "Альфа") + PICTURE)}
    assert _lint(tmp_path, files, COMPONENT_RULE) == []


@pytest.mark.needs_data
def test_a_native_pair_is_left_to_the_file_rule(tmp_path):
    files = _tile_files(BUTTON + PICTURE + ALPHA, layout="Горизонтальная")
    assert _lint(tmp_path / "component", files, COMPONENT_RULE) == []
    found = _lint(tmp_path / "file", files, ROW_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]


_TILE_EN = (
    "ElementKind: InterfaceComponent\n"
    "Id: 0f0f0f0f-5555-6666-7777-888888888888\n"
    "Name: TileChoice\n"
    "VisibilityScope: InSubsystem\n"
    "Inherits:\n"
    "    Type: CustomComponent\n"
    "    Content:\n"
    "        Type: Group\n"
    "        Name: Framework\n"
    "        Layout: Vertical\n"
    "        Content:\n"
    "            -\n"
    "                Type: Picture\n"
    "                Name: Sketch\n"
    "                Visible: =not Crampedness.Cramped() and not IsButton()\n"
    "            -\n"
    "                Type: Button\n"
    "                Name: Pusher\n"
    "                Visible: =not Crampedness.Cramped() and IsButton()\n"
    "                Title: =TileText\n"
    "            -\n"
    "                Type: StandardCard\n"
    "                Name: Dummy\n"
    "                Visible: =Crampedness.Cramped()\n"
    "Properties:\n"
    "    -\n"
    "        Name: TileText\n"
    "        Type: String\n"
    "    -\n"
    "        Name: Look\n"
    "        Type: TileLook?\n"
)


@pytest.mark.needs_data
def test_the_component_row_in_english_spelling_is_judged(tmp_path):
    children = (
        _child_en("TileChoice", "Alpha", "TileText: Probe")
        + _child_en("TileChoice", "Beta", "TileText: Probe", "Look: =TileLook.AsKey")
    )
    layout = "=Crampedness.Cramped()?ContentLayout.Vertical:ContentLayout.Horizontal"
    files = {
        "TileChoice.yaml": _TILE_EN,
        "TileChoice.xbsl": "method IsButton(): Boolean\n    return Look == TileLook.AsKey\n;\n",
        "ProbeShowcase.yaml": _SHOWCASE_EN.format(layout=layout, align="", children=children),
    }
    found = _lint(tmp_path, files, COMPONENT_RULE)
    assert [(line, col) for _n, line, col, _m in found] == [_ROW_KEY]
