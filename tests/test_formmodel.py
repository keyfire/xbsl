"""Form model and designer operations (xbsl/formmodel.py + xbsl/formedits.py).

Every operation result is checked against the stage-0 acceptance guarantees of
docs/DESIGNER.md: edits touch nothing outside the reported ranges, applying and
reverting is byte-identical, and re-parsing the edited text yields the expected tree.
Fixtures are synthetic forms in the spirit of the scaffold generators.
"""

import pytest
import yaml as pyyaml

from xbsl import formedits, formmodel
from xbsl.formmodel import FormModelError, node_at, parse_form

# A form with list slots, pages, a table (Колонки/Команды), composite properties,
# handlers, bindings, a generic type and a node-attached comment.
FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000101
Имя: ПанельЗаказа
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: ФормаОбъекта<Заказы.Объект>
    Заголовок: Заказ
    ОсновнаяКоманда:
        Тип: ОбычнаяКоманда
        Обработчик: ЗаписатьИЗакрыть
        Представление: Записать и закрыть
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        ШиринаВКолонках: Двойная
        Содержимое:
            -
                Тип: Надпись
                Имя: Подсказка
                Значение: "Заполните поля заказа."
                Шрифт:
                    Тип: АбсолютныйШрифт
                    Размер: 28
            # Куда уходит заказ
            -
                Тип: ПолеВвода<Строка>
                Имя: Получатель
                Значение: =Объект.Получатель
                РастягиватьПоГоризонтали: Истина
            -
                Тип: Страницы
                Имя: Разделы
                Страницы:
                    -
                        Имя: СтраницаСостав
                        Заголовок: Состав
                        Содержимое:
                            Тип: Таблица<ИсточникДанныхМассив<Заказы.Состав>>
                            Имя: Состав
                            Источник:
                                Данные: =Объект.Состав
                            Колонки:
                                -
                                    Тип: СтандартнаяКолонкаТаблицы<Заказы.Состав>
                                    Заголовок: Товар
                                    ПолеЗначения: Товар
                            Команды:
                                Тип: ФрагментКомандногоИнтерфейса
                                Элементы:
                                    - =Компоненты.Состав.ДобавитьСтроку
                    -
                        Имя: СтраницаОплата
                        Заголовок: Оплата
                        Содержимое:
                            Тип: Группа
                            Имя: ГруппаОплаты
                            Компоновка: Вертикальная
                            Содержимое:
                                -
                                    Тип: Флажок
                                    Имя: Оплачен
                                    Значение: =Объект.Оплачен
                                -
                                    Тип: Кнопка
                                    Имя: КнопкаОплатить
                                    Заголовок: Оплатить
                                    ПриНажатии: Оплатить
"""

# A chain of single-mapping slots (the second live spelling of Содержимое).
CHAIN = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000102
Имя: Приветствие
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    Заголовок: Приветствие
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Компоновка: Вертикальная
            Содержимое:
                Тип: Надпись
                Имя: Текст
                Значение: Здравствуйте
"""

TPL = "Наследует/Содержимое[0]"
LIST_GRP = TPL + "/Содержимое"
LABEL = TPL + "/Содержимое[0]"
FIELD = TPL + "/Содержимое[1]"
PAGES = TPL + "/Содержимое[2]"
PAGE1 = PAGES + "/Страницы[0]"
PAGE2 = PAGES + "/Страницы[1]"
TABLE = PAGE1 + "/Содержимое[0]"
PAY_GRP = PAGE2 + "/Содержимое[0]"
CHECKBOX = PAY_GRP + "/Содержимое[0]"
BUTTON = PAY_GRP + "/Содержимое[1]"

CH_TPL = "Наследует/Содержимое[0]"
CH_GRP = CH_TPL + "/Содержимое[0]"
CH_LABEL = CH_GRP + "/Содержимое[0]"


def props(node):
    return {p.key: p for p in node.properties}


# --- parsing ------------------------------------------------------------------------------


def test_parse_root_and_ids():
    form = parse_form(FORM)
    assert form.root.id == "Наследует"
    assert form.root.type_full == "ФормаОбъекта<Заказы.Объект>"
    assert form.root.type == "ФормаОбъекта"
    assert form.step == 4 and form.nl == "\n"
    assert set(form.nodes) >= {TPL, LABEL, FIELD, PAGES, PAGE1, TABLE, BUTTON}


def test_parse_slot_styles():
    form = parse_form(FORM)
    single = form.nodes["Наследует/Содержимое"]
    assert single.kind == "slot" and single.list_style is False
    assert [c.id for c in single.children] == [TPL]
    listed = form.nodes[LIST_GRP]
    assert listed.list_style is True
    assert [c.type for c in listed.children] == ["Надпись", "ПолеВвода", "Страницы"]
    # pages have no Тип - components all the same
    page = form.nodes[PAGE1]
    assert page.kind == "component" and page.type is None and page.name == "СтраницаСостав"


def test_parse_properties_vs_children():
    form = parse_form(FORM)
    root_props = props(form.root)
    # a composite mapping with Тип is a property, not a child slot
    assert root_props["ОсновнаяКоманда"].kind == "composite"
    assert root_props["ОсновнаяКоманда"].value_preview == "ОбычнаяКоманда"
    assert [s.name for s in form.root.children] == ["Содержимое"]
    label = form.nodes[LABEL]
    assert props(label)["Шрифт"].kind == "composite"
    assert props(label)["Значение"].kind == "scalar"
    field = form.nodes[FIELD]
    assert props(field)["Значение"].kind == "binding"
    table = form.nodes[TABLE]
    assert props(table)["Источник"].kind == "composite"
    assert {s.name for s in table.children} == {"Колонки", "Команды"}
    # Элементы (a list of bindings) belongs to the command fragment as a property
    fragment = form.nodes[TABLE + "/Команды[0]"]
    assert fragment.type == "ФрагментКомандногоИнтерфейса"
    assert props(fragment)["Элементы"].kind == "composite"
    assert props(fragment)["Элементы"].value_preview == "[...]"
    # Тип and Имя are node fields, not properties
    assert "Тип" not in props(label) and "Имя" not in props(label)


def test_parse_handlers():
    form = parse_form(FORM)
    button = form.nodes[BUTTON]
    assert props(button)["ПриНажатии"].kind == "handler"
    # Представление does not start with Перед, Приоритет has a lowercase continuation
    assert formmodel._HANDLER_KEY_RE.match("ПриНажатии")
    assert formmodel._HANDLER_KEY_RE.match("ПослеСоздания")
    assert not formmodel._HANDLER_KEY_RE.match("Представление")
    assert not formmodel._HANDLER_KEY_RE.match("Приоритет")


def test_parse_generic_types():
    form = parse_form(FORM)
    assert form.nodes[FIELD].type_full == "ПолеВвода<Строка>"
    assert form.nodes[FIELD].type == "ПолеВвода"
    table = form.nodes[TABLE]
    assert table.type == "Таблица"
    assert table.type_full == "Таблица<ИсточникДанныхМассив<Заказы.Состав>>"


def test_parse_comment_attaches_to_node():
    form = parse_form(FORM)
    field = form.nodes[FIELD]
    payload = FORM[field.span.start : field.span.end]
    assert payload.startswith("            # Куда уходит заказ\n            -\n")
    # the neighbour above ends where the comment begins - spans do not overlap
    label = form.nodes[LABEL]
    assert label.span.end == field.span.start
    # content_span excludes the comment
    assert FORM[field.content_span.start : field.content_span.end].startswith("            -")


def test_parse_property_spans_cover_blocks():
    form = parse_form(FORM)
    label = form.nodes[LABEL]
    font = props(label)["Шрифт"]
    block = FORM[font.span.start : font.span.end]
    assert block.splitlines() == [
        "                Шрифт:",
        "                    Тип: АбсолютныйШрифт",
        "                    Размер: 28",
    ]
    value = props(label)["Значение"]
    assert FORM[value.value_span.start : value.value_span.end] == '"Заполните поля заказа."'


def test_parse_rejects_non_component():
    with pytest.raises(FormModelError, match="не является компонентом интерфейса"):
        parse_form("ВидЭлемента: Справочник\nИмя: Товары\n")
    with pytest.raises(FormModelError, match="нет блока Наследует"):
        parse_form("ВидЭлемента: КомпонентИнтерфейса\nИмя: Ф\n")
    with pytest.raises(FormModelError, match="Ошибка разбора yaml"):
        parse_form("ВидЭлемента: КомпонентИнтерфейса\nНаследует:\n  - a\n - b\n")


def test_node_at_resolution():
    form = parse_form(FORM)
    assert node_at(form, FORM.find("КнопкаОплатить")).id == BUTTON
    assert node_at(form, FORM.find("# Куда уходит заказ")).id == FIELD  # comments belong to the node
    # the slot key line resolves to the slot itself
    assert node_at(form, FORM.find("Страницы:")).id == PAGES + "/Страницы"
    assert node_at(form, 0) is None  # ВидЭлемента line is outside the tree


def test_node_dict_shapes():
    form = parse_form(FORM)
    compact = formmodel.node_dict(form.root, property_spans=False)
    assert compact["typeFull"] == "ФормаОбъекта<Заказы.Объект>"
    assert "span" not in compact["properties"][0]
    full = formmodel.node_dict(form.nodes[BUTTON], deep=False)
    assert "children" not in full
    assert full["properties"][1]["kind"] == "handler"
    assert full["properties"][1]["valueSpan"]


def test_node_dict_content_span():
    form = parse_form(FORM)
    # a node with an attached comment: contentSpan starts below the comment
    field = formmodel.node_dict(form.nodes[FIELD], deep=False)
    assert field["contentSpan"]["start"] > field["span"]["start"]
    assert field["contentSpan"]["end"] == field["span"]["end"]
    assert FORM[field["contentSpan"]["start"]:].startswith("            -\n")
    # without comments the two spans coincide, on slots included
    button = formmodel.node_dict(form.nodes[BUTTON], deep=False)
    assert button["contentSpan"] == button["span"]
    slot = formmodel.node_dict(form.nodes[LIST_GRP], deep=False)
    assert slot["contentSpan"] == slot["span"]


def test_parent_component_skips_slots():
    form = parse_form(FORM)
    # a slot resolves to its owner component
    slot = form.nodes[LIST_GRP]
    assert formmodel.parent_component(form, slot).id == TPL
    # a component resolves to the component above its slot (the slot is skipped)
    assert formmodel.parent_component(form, form.nodes[FIELD]).id == TPL
    assert formmodel.parent_component(form, form.nodes[BUTTON]).id == PAY_GRP
    # the root has no parent
    assert formmodel.parent_component(form, form.root) is None


# --- helpers for operation tests ----------------------------------------------------------


def unchanged_outside(original: str, result: formedits.EditResult) -> bool:
    """The acceptance guarantee: nothing outside the reported ranges changed."""
    rebuilt = []
    pos = 0
    for e in result.edits:
        rebuilt.append(original[pos : e.start])
        rebuilt.append(e.new_text)
        pos = e.end
    rebuilt.append(original[pos:])
    return "".join(rebuilt) == result.new_text


def slice_of(text: str, form, node_id: str) -> str:
    node = form.nodes[node_id]
    return text[node.span.start : node.span.end]


# --- insert -------------------------------------------------------------------------------


def test_insert_at_end_of_list():
    res = formedits.insert_component(FORM, TPL, "Содержимое", type_="Надпись", name="Итог")
    assert unchanged_outside(FORM, res)
    assert res.node_id == TPL + "/Содержимое[3]"
    form = parse_form(res.new_text)
    assert [c.type for c in form.nodes[LIST_GRP].children] == [
        "Надпись", "ПолеВвода", "Страницы", "Надпись",
    ]
    assert res.new_text[res.node_span.start : res.node_span.end] == (
        "            -\n"
        "                Тип: Надпись\n"
        "                Имя: Итог\n"
    )


def test_insert_before_and_after_sibling():
    res = formedits.insert_component(FORM, TPL, "Содержимое", type_="Гиперссылка", before=FIELD)
    form = parse_form(res.new_text)
    assert [c.type for c in form.nodes[LIST_GRP].children] == [
        "Надпись", "Гиперссылка", "ПолеВвода", "Страницы",
    ]
    assert res.node_id == TPL + "/Содержимое[1]"
    # inserting before a node with a comment lands above the comment, keeping it attached
    inserted_end = res.node_span.end
    assert res.new_text[inserted_end:].startswith("            # Куда уходит заказ\n")

    res = formedits.insert_component(FORM, TPL, "Содержимое", type_="Гиперссылка", after=LABEL)
    assert res.node_id == TPL + "/Содержимое[1]"
    form = parse_form(res.new_text)
    assert form.nodes[TPL + "/Содержимое[2]"].type == "ПолеВвода"


def test_insert_converts_single_mapping_slot_to_list():
    res = formedits.insert_component(CHAIN, CH_GRP, "Содержимое", type_="Надпись", name="Вторая")
    assert unchanged_outside(CHAIN, res)
    assert res.node_id == CH_GRP + "/Содержимое[1]"
    form = parse_form(res.new_text)
    slot = form.nodes[CH_GRP + "/Содержимое"]
    assert slot.list_style is True
    assert [c.name for c in slot.children] == ["Текст", "Вторая"]
    assert (
        "            Содержимое:\n"
        "                -\n"
        "                    Тип: Надпись\n"
        "                    Имя: Текст\n"
        "                    Значение: Здравствуйте\n"
        "                -\n"
        "                    Тип: Надпись\n"
        "                    Имя: Вторая\n"
    ) in res.new_text


def test_insert_before_converts_and_prepends():
    res = formedits.insert_component(
        CHAIN, CH_GRP, "Содержимое", type_="Надпись", name="Первая", before=CH_LABEL
    )
    form = parse_form(res.new_text)
    assert [c.name for c in form.nodes[CH_GRP + "/Содержимое"].children] == ["Первая", "Текст"]
    assert res.node_id == CH_GRP + "/Содержимое[0]"


def test_insert_into_missing_and_empty_slot():
    res = formedits.insert_component(CHAIN, CH_GRP, "Шапка", type_="Надпись", name="Верх")
    form = parse_form(res.new_text)
    assert [c.name for c in form.nodes[CH_GRP + "/Шапка"].children] == ["Верх"]
    assert form.nodes[CH_GRP + "/Шапка"].list_style is False  # the singleton spelling

    empty = CHAIN.replace("""    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            Тип: Группа
            Компоновка: Вертикальная
            Содержимое:
                Тип: Надпись
                Имя: Текст
                Значение: Здравствуйте
""", "    Содержимое:\n")
    res = formedits.insert_component(empty, "Наследует", "Содержимое", type_="Группа")
    assert "    Содержимое:\n        Тип: Группа\n" in res.new_text
    assert res.node_id == "Наследует/Содержимое[0]"


def test_insert_validation_errors():
    with pytest.raises(FormModelError, match="Слот не поддерживается"):
        formedits.insert_component(FORM, TPL, "Элементы", type_="Надпись")
    with pytest.raises(FormModelError, match="хотя бы тип или имя"):
        formedits.insert_component(FORM, TPL, "Содержимое")
    with pytest.raises(FormModelError, match="только один из параметров"):
        formedits.insert_component(FORM, TPL, "Содержимое", type_="Надпись",
                                   before=LABEL, after=LABEL)
    with pytest.raises(FormModelError, match="Узел не найден"):
        formedits.insert_component(FORM, "Наследует/Нет[9]", "Содержимое", type_="Надпись")
    with pytest.raises(FormModelError, match="не находится в слоте"):
        formedits.insert_component(FORM, TPL, "Содержимое", type_="Надпись", before=BUTTON)
    with pytest.raises(FormModelError, match="Недопустимый тип"):
        formedits.insert_component(FORM, TPL, "Содержимое", type_="А: Б")
    with pytest.raises(FormModelError, match="Недопустимое имя"):
        formedits.insert_component(FORM, TPL, "Содержимое", type_="Надпись", name="Плохое имя")


# --- remove -------------------------------------------------------------------------------


def test_remove_middle_item_keeps_neighbours():
    form = parse_form(FORM)
    before_label = slice_of(FORM, form, LABEL)
    before_pages = slice_of(FORM, form, PAGES)
    res = formedits.remove_node(FORM, FIELD)
    assert unchanged_outside(FORM, res)
    after = parse_form(res.new_text)
    assert [c.type for c in after.nodes[LIST_GRP].children] == ["Надпись", "Страницы"]
    # the comment attached to the removed node went with it
    assert "# Куда уходит заказ" not in res.new_text
    assert slice_of(res.new_text, after, LABEL) == before_label
    assert slice_of(res.new_text, after, TPL + "/Содержимое[1]") == before_pages


def test_remove_last_item_removes_slot():
    one = formedits.remove_node(FORM, CHECKBOX).new_text
    res = formedits.remove_node(one, PAY_GRP + "/Содержимое[0]")
    form = parse_form(res.new_text)
    group = form.nodes[PAY_GRP]
    assert group.children == [] and "Содержимое" not in group.pairs
    assert group.type == "Группа"  # the container itself survived


def test_remove_single_mapping_child_removes_slot():
    res = formedits.remove_node(CHAIN, CH_LABEL)
    form = parse_form(res.new_text)
    assert "Содержимое" not in form.nodes[CH_GRP].pairs
    assert form.nodes[CH_GRP].properties  # Компоновка stays


def test_remove_root_rejected():
    with pytest.raises(FormModelError, match="Корневой узел"):
        formedits.remove_node(FORM, "Наследует")


# --- move ---------------------------------------------------------------------------------


def test_move_reorder_within_slot_roundtrip():
    res = formedits.move_node(FORM, FIELD, TPL, "Содержимое", before=LABEL)
    form = parse_form(res.new_text)
    assert [c.name for c in form.nodes[LIST_GRP].children] == [
        "Получатель", "Подсказка", "Разделы",
    ]
    assert res.node_id == TPL + "/Содержимое[0]"
    # the comment travelled with the node
    assert res.new_text.index("# Куда уходит заказ") < res.new_text.index("Имя: Подсказка")
    # move back -> byte-identical source
    back = formedits.move_node(res.new_text, res.node_id, TPL, "Содержимое",
                               after=TPL + "/Содержимое[1]")
    assert back.new_text == FORM


def test_move_across_slots_reindents():
    # the deep Кнопка moves into the top-level template list (much shallower)
    res = formedits.move_node(FORM, BUTTON, TPL, "Содержимое", after=PAGES)
    assert unchanged_outside(FORM, res)
    form = parse_form(res.new_text)
    moved = form.nodes[TPL + "/Содержимое[3]"]
    assert moved.type == "Кнопка" and moved.name == "КнопкаОплатить"
    assert res.new_text[moved.span.start : moved.span.end] == (
        "            -\n"
        "                Тип: Кнопка\n"
        "                Имя: КнопкаОплатить\n"
        "                Заголовок: Оплатить\n"
        "                ПриНажатии: Оплатить\n"
    )
    # the source group kept its second child only
    assert [c.name for c in form.nodes[PAY_GRP + "/Содержимое"].children] == ["Оплачен"]


def test_move_last_child_collapses_source_slot():
    one = formedits.remove_node(FORM, CHECKBOX).new_text
    res = formedits.move_node(one, PAY_GRP + "/Содержимое[0]", TPL, "Содержимое", after=PAGES)
    form = parse_form(res.new_text)
    assert "Содержимое" not in form.nodes[PAY_GRP].pairs
    assert form.nodes[TPL + "/Содержимое[3]"].type == "Кнопка"


def test_move_out_of_converting_single_slot():
    # the destination slot holds a single mapping that CONTAINS the moved node:
    # the conversion and the removal must land as one composed edit
    res = formedits.move_node(CHAIN, CH_LABEL, CH_TPL, "Содержимое", after=CH_GRP)
    assert len(res.edits) == 1
    assert unchanged_outside(CHAIN, res)
    form = parse_form(res.new_text)
    slot = form.nodes[CH_TPL + "/Содержимое"]
    assert [c.type for c in slot.children] == ["Группа", "Надпись"]
    assert "Содержимое" not in form.nodes[CH_TPL + "/Содержимое[0]"].pairs
    assert res.node_id == CH_TPL + "/Содержимое[1]"

    first = formedits.move_node(CHAIN, CH_LABEL, CH_TPL, "Содержимое", before=CH_GRP)
    assert [c.type for c in parse_form(first.new_text).nodes[CH_TPL + "/Содержимое"].children] == [
        "Надпись", "Группа",
    ]


def test_move_into_missing_slot_creates_singleton():
    res = formedits.move_node(FORM, BUTTON, PAY_GRP, "Подвал")
    form = parse_form(res.new_text)
    slot = form.nodes[PAY_GRP + "/Подвал"]
    assert slot.list_style is False
    assert [c.name for c in slot.children] == ["КнопкаОплатить"]


def test_move_guards():
    with pytest.raises(FormModelError, match="собственного поддерева"):
        formedits.move_node(FORM, PAGES, PAGE1, "Содержимое")
    with pytest.raises(FormModelError, match="относительно самого себя"):
        formedits.move_node(FORM, FIELD, TPL, "Содержимое", before=FIELD)
    with pytest.raises(FormModelError, match="единственный в слоте"):
        formedits.move_node(CHAIN, CH_LABEL, CH_GRP, "Содержимое")
    with pytest.raises(FormModelError, match="Корневой узел"):
        formedits.move_node(FORM, "Наследует", TPL, "Содержимое")


# --- wrap / unwrap ------------------------------------------------------------------------


def test_wrap_list_item_and_unwrap_roundtrip():
    res = formedits.wrap_node(FORM, FIELD, "Группа", name="Обертка")
    assert unchanged_outside(FORM, res)
    form = parse_form(res.new_text)
    wrapper = form.nodes[FIELD]  # the wrapper takes the node's place
    assert wrapper.type == "Группа" and wrapper.name == "Обертка"
    inner = form.nodes[FIELD + "/Содержимое[0]"]
    assert inner.type == "ПолеВвода"
    # the node's attached comment stays above the wrapper and now belongs to it
    assert res.new_text[wrapper.span.start : wrapper.content_span.start] == (
        "            # Куда уходит заказ\n"
    )
    back = formedits.unwrap_node(res.new_text, res.node_id)
    assert back.new_text == FORM


def test_wrap_single_mapping_child_and_unwrap_roundtrip():
    res = formedits.wrap_node(CHAIN, CH_LABEL, "Группа")
    form = parse_form(res.new_text)
    wrapper = form.nodes[CH_LABEL]
    assert wrapper.type == "Группа"
    assert form.nodes[CH_LABEL + "/Содержимое[0]"].type == "Надпись"
    back = formedits.unwrap_node(res.new_text, CH_LABEL)
    assert back.new_text == CHAIN


def test_unwrap_multiple_children_into_list():
    res = formedits.unwrap_node(FORM, PAY_GRP)
    form = parse_form(res.new_text)
    slot = form.nodes[PAGE2 + "/Содержимое"]
    assert slot.list_style is True
    assert [c.name for c in slot.children] == ["Оплачен", "КнопкаОплатить"]


def test_unwrap_guards():
    with pytest.raises(FormModelError, match="несколько слотов"):
        formedits.unwrap_node(FORM, TABLE)  # Колонки and Команды are both filled
    with pytest.raises(FormModelError, match="нет вложенных компонентов"):
        formedits.unwrap_node(FORM, BUTTON)
    with pytest.raises(FormModelError, match="Корневой узел"):
        formedits.unwrap_node(FORM, "Наследует")


# --- duplicate ----------------------------------------------------------------------------


def test_duplicate_uniquifies_names_including_nested():
    res = formedits.duplicate_node(FORM, PAY_GRP)
    assert unchanged_outside(FORM, res)
    form = parse_form(res.new_text)
    copy = form.nodes[res.node_id]
    assert res.node_id == PAGE2 + "/Содержимое[1]"
    assert copy.name is not None and copy.name != form.nodes[PAY_GRP].name
    nested = [c.name for c in form.nodes[res.node_id + "/Содержимое"].children]
    assert nested == ["Оплачен2", "КнопкаОплатить2"]
    # names across the whole file stay unique
    names = [n.name for n in form.nodes.values() if n.kind == "component" and n.name]
    assert len(names) == len(set(names))


def test_duplicate_with_comment_and_remove_roundtrip():
    res = formedits.duplicate_node(FORM, FIELD)
    assert res.new_text.count("# Куда уходит заказ") == 2  # the comment is part of the node
    back = formedits.remove_node(res.new_text, res.node_id)
    assert back.new_text == FORM


def test_duplicate_single_mapping_child_converts():
    res = formedits.duplicate_node(CHAIN, CH_LABEL)
    form = parse_form(res.new_text)
    slot = form.nodes[CH_GRP + "/Содержимое"]
    assert slot.list_style is True
    assert [c.name for c in slot.children] == ["Текст", "Текст2"]


# --- rename -------------------------------------------------------------------------------


def test_rename_set_change_drop():
    res = formedits.rename_node(FORM, LABEL, "Шапка2")
    form = parse_form(res.new_text)
    assert form.nodes[LABEL].name == "Шапка2"

    # a node without Имя gets one right after Тип
    res = formedits.rename_node(FORM, TABLE + "/Колонки[0]", "КолонкаТовар")
    form = parse_form(res.new_text)
    node = form.nodes[TABLE + "/Колонки[0]"]
    assert node.name == "КолонкаТовар"
    lines = res.new_text[node.content_span.start : node.content_span.end].splitlines()
    assert lines[2].strip() == "Имя: КолонкаТовар"  # after the dash and Тип lines

    dropped = formedits.rename_node(res.new_text, TABLE + "/Колонки[0]", None)
    assert dropped.new_text == FORM


def test_rename_guards():
    with pytest.raises(FormModelError, match="Недопустимое имя"):
        formedits.rename_node(FORM, LABEL, "1Плохое")
    with pytest.raises(FormModelError, match="корневого узла"):
        formedits.rename_node(FORM, "Наследует", "Имя")
    with pytest.raises(FormModelError, match="не задано"):
        formedits.rename_node(FORM, TABLE + "/Колонки[0]", None)


# --- set_property / reset_property --------------------------------------------------------


def test_set_property_new_scalar_lands_after_type():
    res = formedits.set_property(FORM, BUTTON, "Ширина", value="220")
    assert unchanged_outside(FORM, res)
    form = parse_form(res.new_text)
    node = form.nodes[BUTTON]
    lines = res.new_text[node.span.start : node.span.end].splitlines()
    assert lines[1].strip() == "Тип: Кнопка"
    assert lines[2].strip() == "Ширина: 220"  # bare number, right after Тип
    back = formedits.reset_property(res.new_text, BUTTON, "Ширина")
    assert back.new_text == FORM


def test_set_property_replace_scalar_and_binding():
    res = formedits.set_property(FORM, BUTTON, "Заголовок", value="Оплатить заказ")
    assert "Заголовок: Оплатить заказ" in res.new_text  # inner spaces are fine bare
    res2 = formedits.set_property(FORM, FIELD, "Значение", value="=Объект.Плательщик")
    assert "Значение: =Объект.Плательщик" in res2.new_text


def test_set_property_scalar_spellings():
    quoted = formedits.set_property(FORM, BUTTON, "Пометка", value="true")
    assert 'Пометка: "true"' in quoted.new_text  # yaml would read a bare true as a boolean
    generic = formedits.set_property(FORM, BUTTON, "ТипЗначения", value="Массив<Строка>")
    assert "ТипЗначения: Массив<Строка>" in generic.new_text
    negative = formedits.set_property(FORM, BUTTON, "НачальныйУровеньРазворачивания", value="-1")
    assert "НачальныйУровеньРазворачивания: -1" in negative.new_text


def test_set_property_composite_new_and_replace():
    res = formedits.set_property(
        FORM, BUTTON, "Шрифт", value_yaml="Тип: АбсолютныйШрифт\nРазмер: 28"
    )
    form = parse_form(res.new_text)
    node = form.nodes[BUTTON]
    assert props(node)["Шрифт"].kind == "composite"
    block = res.new_text[props(node)["Шрифт"].span.start : props(node)["Шрифт"].span.end]
    assert block.splitlines()[0].strip() == "Шрифт:"
    assert block.splitlines()[1].strip() == "Тип: АбсолютныйШрифт"
    # composite -> scalar replaces the whole block (the label keeps its own Шрифт)
    res2 = formedits.set_property(res.new_text, BUTTON, "Шрифт", value="=Стили.Основной")
    assert res2.new_text.count("АбсолютныйШрифт") == FORM.count("АбсолютныйШрифт")
    assert "Шрифт: =Стили.Основной" in res2.new_text
    # scalar -> composite the other way round
    res3 = formedits.set_property(
        FORM, LABEL, "Значение", value_yaml="Тип: Ссылка\nАдрес: /home"
    )
    assert '"Заполните поля заказа."' not in res3.new_text


def test_set_property_inline_flow_fragment():
    res = formedits.set_property(FORM, TABLE, "РасчетРазрешенийПо", value_yaml="[Товар]")
    assert "РасчетРазрешенийПо: [Товар]" in res.new_text


def test_set_property_replace_keeps_trailing_comment():
    with_comment = FORM.replace(
        "                                    Заголовок: Оплатить\n",
        "                                    Заголовок: Оплатить  # подпись\n",
    )
    assert with_comment != FORM
    res = formedits.set_property(with_comment, BUTTON, "Заголовок", value="Провести")
    assert "Заголовок: Провести  # подпись" in res.new_text


def test_set_property_guards():
    with pytest.raises(FormModelError, match="слот дочерних компонентов"):
        formedits.set_property(FORM, PAY_GRP, "Содержимое", value="х")
    with pytest.raises(FormModelError, match="ровно один"):
        formedits.set_property(FORM, BUTTON, "Ширина")
    with pytest.raises(FormModelError, match="ровно один"):
        formedits.set_property(FORM, BUTTON, "Ширина", value="1", value_yaml="А: 1")
    with pytest.raises(FormModelError, match="не является корректным yaml"):
        formedits.set_property(FORM, BUTTON, "Шрифт", value_yaml="Тип: [оборвано")
    with pytest.raises(FormModelError, match="скаляр"):
        formedits.set_property(FORM, BUTTON, "Шрифт", value_yaml="просто строка")


def test_reset_property_composite_and_guards():
    res = formedits.reset_property(FORM, LABEL, "Шрифт")
    assert "АбсолютныйШрифт" not in res.new_text
    form = parse_form(res.new_text)
    assert "Шрифт" not in props(form.nodes[LABEL])
    with pytest.raises(FormModelError, match="не задано"):
        formedits.reset_property(FORM, LABEL, "Ширина")
    with pytest.raises(FormModelError, match="слот дочерних"):
        formedits.reset_property(FORM, PAY_GRP, "Содержимое")


def test_set_property_on_root():
    res = formedits.set_property(FORM, "Наследует", "Заголовок", value="Новый заказ")
    assert "    Заголовок: Новый заказ" in res.new_text
    assert res.node_id == "Наследует"


# --- the dispatcher -----------------------------------------------------------------------


def test_apply_operation_dispatch_and_camel_case():
    res = formedits.apply_operation(FORM, "insert", {
        "parent": TPL, "slot": "Содержимое", "type": "Надпись", "name": "Итог",
    })
    assert res.node_id == TPL + "/Содержимое[3]"
    # camelCase argument spellings are accepted (the TS client side)
    res = formedits.apply_operation(FORM, "move", {
        "node": FIELD, "newParent": TPL, "slot": "Содержимое", "before": LABEL,
    })
    assert res.node_id == TPL + "/Содержимое[0]"
    res = formedits.apply_operation(FORM, "set-property", {
        "node": BUTTON, "key": "Ширина", "value": 220,
    })
    assert "Ширина: 220" in res.new_text
    with pytest.raises(FormModelError, match="Неизвестная операция"):
        formedits.apply_operation(FORM, "explode", {})
    with pytest.raises(FormModelError, match="не задан параметр"):
        formedits.apply_operation(FORM, "insert", {"slot": "Содержимое"})


# --- crlf and file-level wrapper ----------------------------------------------------------


def test_operations_preserve_crlf():
    crlf = FORM.replace("\n", "\r\n")
    res = formedits.insert_component(crlf, TPL, "Содержимое", type_="Надпись", name="Итог")
    inserted = res.new_text[res.node_span.start : res.node_span.end]
    assert "\r\n" in inserted and "\n" not in inserted.replace("\r\n", "")
    back = formedits.remove_node(res.new_text, res.node_id)
    assert back.new_text == crlf


def test_op_component_edit_writes_scaffold_result(tmp_path):
    path = tmp_path / "ПанельЗаказа.yaml"
    path.write_text(FORM, encoding="utf-8")
    outcome = formedits.op_component_edit(path, "insert", {
        "parent": TPL, "slot": "Содержимое", "type": "Надпись", "name": "Итог",
    })
    change = outcome.result.changes[0]
    assert change.path == path and change.created is False
    assert outcome.node["id"] == TPL + "/Содержимое[3]"
    assert outcome.edits and outcome.result.changes[0].cursor is not None
    with pytest.raises(FormModelError, match="Файл не найден"):
        formedits.op_component_edit(tmp_path / "Нет.yaml", "remove", {"node": TPL})


# --- every edited text stays valid yaml ---------------------------------------------------


@pytest.mark.parametrize("op,args", [
    ("insert", {"parent": TPL, "slot": "Содержимое", "type": "Надпись"}),
    ("move", {"node": BUTTON, "new_parent": TPL, "slot": "Содержимое"}),
    ("remove", {"node": FIELD}),
    ("wrap", {"node": CHECKBOX, "container": "Группа"}),
    ("unwrap", {"node": PAY_GRP}),
    ("duplicate", {"node": LABEL}),
    ("rename", {"node": LABEL, "new_name": "Шапка2"}),
    ("set_property", {"node": LABEL, "key": "Ширина", "value": "220"}),
    ("reset_property", {"node": LABEL, "key": "Шрифт"}),
])
def test_result_parses_as_yaml(op, args):
    res = formedits.apply_operation(FORM, op, args)
    assert pyyaml.safe_load(res.new_text)
    assert unchanged_outside(FORM, res)


# --- the Свойства section: model and operations --------------------------------------------

# A form with the top-level Свойства section: comments at both levels (a section-level
# run attached to the first record, a record-level run attached to its own record) and
# two bindings that use the Титул property.
PROPS = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000103
Имя: Карточка
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Группа
    Компоновка: Вертикальная
    Видимость: =не Скрыта
    Содержимое:
        -
            Тип: Надпись
            Имя: Заголовок
            Значение: =Титул
        -
            Тип: Надпись
            Имя: Повтор
            Значение: =Титул
Свойства:
    # Свойства карточки
    -
        Имя: Титул
        Тип: Строка
    -
        # Скрыть карточку целиком
        Имя: Скрыта
        Тип: Булево
"""


def prop_names(text):
    return [p.name for p in parse_form(text).component_properties]


def test_parse_component_properties():
    form = parse_form(PROPS)
    assert [(p.name, p.type_full) for p in form.component_properties] == [
        ("Титул", "Строка"), ("Скрыта", "Булево"),
    ]
    first, second = form.component_properties
    # the section-level comment run attaches to the first record
    assert PROPS[first.span.start : first.span.end].startswith("    # Свойства карточки\n    -\n")
    assert PROPS[first.content_span.start :].startswith("    -\n        Имя: Титул\n")
    # a comment written inside the record (above Имя) is part of its block
    assert "# Скрыть карточку целиком" in PROPS[second.span.start : second.span.end]
    assert second.span == second.content_span  # nothing attached above the dash
    # exact scalar spans of the values
    assert PROPS[first.name_span.start : first.name_span.end] == "Титул"
    assert PROPS[first.type_span.start : first.type_span.end] == "Строка"
    section = form.properties_section
    assert section.supported and section.dash_col == 4
    assert PROPS[section.content_span.start :].startswith("Свойства:\n")
    assert section.content_span.end == len(PROPS)
    # a form without the section
    assert parse_form(FORM).properties_section is None
    assert parse_form(FORM).component_properties == []


def test_component_properties_dicts_shape():
    d = formmodel.component_properties_dicts(parse_form(PROPS))
    assert d[0]["name"] == "Титул" and d[0]["type"] == "Строка"
    assert set(d[0]) == {"name", "type", "span", "nameSpan", "typeSpan"}
    assert d[0]["nameSpan"]["end"] - d[0]["nameSpan"]["start"] == len("Титул")


def test_parse_properties_section_spellings():
    bare = FORM + "Свойства:\n"
    form = parse_form(bare)
    assert form.properties_section is not None
    assert form.properties_section.supported and form.properties_section.entries == []

    flow = FORM + "Свойства: []\n"
    assert parse_form(flow).properties_section.supported is False
    with pytest.raises(FormModelError, match="не блочным списком"):
        formedits.property_add(flow, "Титул", "Строка")


def test_property_add_appends_to_section():
    res = formedits.property_add(PROPS, "Итог", "Число")
    assert unchanged_outside(PROPS, res)
    assert res.node_id == "Свойства/Итог"
    assert prop_names(res.new_text) == ["Титул", "Скрыта", "Итог"]
    assert res.new_text[res.node_span.start : res.node_span.end] == (
        "    -\n"
        "        Имя: Итог\n"
        "        Тип: Число\n"
    )
    back = formedits.property_remove(res.new_text, "Итог")
    assert back.new_text == PROPS


def test_property_add_creates_section_after_inherit():
    res = formedits.property_add(CHAIN, "Титул", "Строка")
    assert unchanged_outside(CHAIN, res)
    form = parse_form(res.new_text)
    assert [p.name for p in form.component_properties] == ["Титул"]
    # the corpus placement: the section opens right after the Наследует block
    assert res.new_text.endswith(
        "            Значение: Здравствуйте\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Титул\n"
        "        Тип: Строка\n"
    )
    back = formedits.property_remove(res.new_text, "Титул")
    assert back.new_text == CHAIN


def test_property_add_into_empty_section_and_eof():
    bare = FORM + "Свойства:"  # no trailing newline
    res = formedits.property_add(bare, "Титул", "Строка")
    assert prop_names(res.new_text) == ["Титул"]
    assert res.new_text.endswith("Свойства:\n    -\n        Имя: Титул\n        Тип: Строка\n")

    no_nl = CHAIN.rstrip("\n")
    res = formedits.property_add(no_nl, "Титул", "Строка")
    assert prop_names(res.new_text) == ["Титул"]
    assert "Здравствуйте\nСвойства:\n" in res.new_text


def test_property_add_validation():
    with pytest.raises(FormModelError, match="уже есть"):
        formedits.property_add(PROPS, "Титул", "Строка")
    with pytest.raises(FormModelError, match="Недопустимое имя"):
        formedits.property_add(PROPS, "Плохое имя", "Строка")
    with pytest.raises(FormModelError, match="Недопустимый тип"):
        formedits.property_add(PROPS, "Итог", "А: Б")
    # union and nullable types are legal property types
    res = formedits.property_add(PROPS, "Ссылка", "Накладная.Ссылка|?")
    assert "Тип: Накладная.Ссылка|?" in res.new_text


def test_property_retype():
    res = formedits.property_retype(PROPS, "Скрыта", "Булево?")
    assert unchanged_outside(PROPS, res)
    assert res.node_id == "Свойства/Скрыта"
    assert "Тип: Булево?" in res.new_text
    back = formedits.property_retype(res.new_text, "Скрыта", "Булево")
    assert back.new_text == PROPS

    # a record without Тип gets the key right after Имя
    no_type = PROPS.replace("        Имя: Скрыта\n        Тип: Булево\n",
                            "        Имя: Скрыта\n")
    res = formedits.property_retype(no_type, "Скрыта", "Булево")
    assert res.new_text == PROPS

    with pytest.raises(FormModelError, match="не найдено"):
        formedits.property_retype(PROPS, "Нет", "Строка")
    with pytest.raises(FormModelError, match="не найдено"):
        formedits.property_retype(FORM, "Титул", "Строка")  # no section at all


def test_property_remove_middle_and_last():
    res = formedits.property_remove(PROPS, "Титул")
    assert unchanged_outside(PROPS, res)
    assert res.node_id is None
    assert prop_names(res.new_text) == ["Скрыта"]
    # the section comment went with the first record it was attached to
    assert "# Свойства карточки" not in res.new_text

    only = formedits.property_remove(res.new_text, "Скрыта")
    assert "Свойства" not in only.new_text
    assert parse_form(only.new_text).properties_section is None

    with pytest.raises(FormModelError, match="не найдено"):
        formedits.property_remove(PROPS, "Нет")


def test_property_rename_reports_binding_usages():
    res = formedits.property_rename(PROPS, "Титул", "Заглавие")
    assert unchanged_outside(PROPS, res)
    assert res.node_id == "Свойства/Заглавие"
    # the record is renamed, the =Титул bindings are NOT rewritten - the note says so
    assert "Имя: Заглавие" in res.new_text
    assert res.new_text.count("=Титул") == 2
    assert res.notes and "2" in res.notes[0] and "Титул" in res.notes[0]

    back = formedits.property_rename(res.new_text, "Заглавие", "Титул")
    assert back.new_text == PROPS
    assert back.notes == []  # nothing references Заглавие

    # =не Скрыта counts as one usage too
    res = formedits.property_rename(PROPS, "Скрыта", "Спрятана")
    assert res.notes and "1" in res.notes[0]

    with pytest.raises(FormModelError, match="уже есть"):
        formedits.property_rename(PROPS, "Титул", "Скрыта")
    with pytest.raises(FormModelError, match="не найдено"):
        formedits.property_rename(PROPS, "Нет", "Имя2")


# --- insert_fragment ------------------------------------------------------------------------


FRAGMENT = """\
# Итоговая подпись
Тип: Надпись
Имя: Подпись
Шрифт:
    Тип: АбсолютныйШрифт
    Размер: 28
"""


def test_insert_fragment_at_end_of_list():
    res = formedits.insert_fragment(FORM, TPL, "Содержимое", FRAGMENT)
    assert unchanged_outside(FORM, res)
    assert res.node_id == TPL + "/Содержимое[3]"
    assert res.new_text[res.node_span.start : res.node_span.end] == (
        "            # Итоговая подпись\n"
        "            -\n"
        "                Тип: Надпись\n"
        "                Имя: Подпись\n"
        "                Шрифт:\n"
        "                    Тип: АбсолютныйШрифт\n"
        "                    Размер: 28\n"
    )
    form = parse_form(res.new_text)
    node = form.nodes[res.node_id]
    assert node.type == "Надпись" and props(node)["Шрифт"].kind == "composite"
    back = formedits.remove_node(res.new_text, res.node_id)
    assert back.new_text == FORM


def test_insert_fragment_reindents_and_positions():
    deep = "\n".join("      " + line for line in FRAGMENT.splitlines()) + "\n"
    res = formedits.insert_fragment(FORM, TPL, "Содержимое", deep, before=LABEL)
    assert res.node_id == TPL + "/Содержимое[0]"
    form = parse_form(res.new_text)
    assert [c.type for c in form.nodes[LIST_GRP].children] == [
        "Надпись", "Надпись", "ПолеВвода", "Страницы",
    ]
    assert "            # Итоговая подпись\n            -\n" in res.new_text

    res = formedits.insert_fragment(FORM, TPL, "Содержимое", "Тип: Гиперссылка", after=LABEL)
    assert res.node_id == TPL + "/Содержимое[1]"


def test_insert_fragment_into_missing_and_singleton_slot():
    res = formedits.insert_fragment(CHAIN, CH_GRP, "Шапка", "Тип: Надпись\nИмя: Верх\n")
    form = parse_form(res.new_text)
    slot = form.nodes[CH_GRP + "/Шапка"]
    assert slot.list_style is False and [c.name for c in slot.children] == ["Верх"]
    # removing the only child takes the created slot with it - byte-identical rollback
    back = formedits.remove_node(res.new_text, res.node_id)
    assert back.new_text == CHAIN

    res = formedits.insert_fragment(CHAIN, CH_GRP, "Содержимое", FRAGMENT)
    assert unchanged_outside(CHAIN, res)
    form = parse_form(res.new_text)
    slot = form.nodes[CH_GRP + "/Содержимое"]
    assert slot.list_style is True  # the singleton slot converted to the list form
    assert [c.name for c in slot.children] == ["Текст", "Подпись"]


def test_insert_fragment_normalizes_leading_blank_lines():
    # a blank line between the comments and the body would detach the comments - dropped
    frag = "# заметка\n\n\nТип: Надпись\n"
    res = formedits.insert_fragment(FORM, TPL, "Содержимое", frag)
    assert res.new_text[res.node_span.start : res.node_span.end] == (
        "            # заметка\n"
        "            -\n"
        "                Тип: Надпись\n"
    )


def test_insert_fragment_preserves_crlf():
    crlf = FORM.replace("\n", "\r\n")
    res = formedits.insert_fragment(crlf, TPL, "Содержимое", FRAGMENT)
    inserted = res.new_text[res.node_span.start : res.node_span.end]
    assert "\r\n" in inserted and inserted.replace("\r\n", "").find("\n") == -1
    back = formedits.remove_node(res.new_text, res.node_id)
    assert back.new_text == crlf


def test_insert_fragment_validation():
    with pytest.raises(FormModelError, match="Пустой yaml-фрагмент"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "   \n")
    with pytest.raises(FormModelError, match="не является корректным yaml"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "Тип: [обрыв")
    with pytest.raises(FormModelError, match="список элементов"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "- Тип: А\n- Тип: Б\n")
    with pytest.raises(FormModelError, match="ожидается маппинг"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "просто строка")
    with pytest.raises(FormModelError, match="нет верхнеуровневого ключа Тип"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "Имя: БезТипа\n")
    with pytest.raises(FormModelError, match="несколько компонентов"):
        formedits.insert_fragment(FORM, TPL, "Содержимое", "Тип: А\nИмя: X\nТип: Б\n")
    with pytest.raises(FormModelError, match="Слот не поддерживается"):
        formedits.insert_fragment(FORM, TPL, "Реквизиты", FRAGMENT)
    with pytest.raises(FormModelError, match="Узел не найден"):
        formedits.insert_fragment(FORM, "Нет", "Содержимое", FRAGMENT)


@pytest.mark.parametrize("op,args", [
    ("insert_fragment", {"parent": TPL, "slot": "Содержимое", "fragment": FRAGMENT}),
    ("property_add", {"name": "Итог", "type": "Число"}),
    ("property_retype", {"name": "Скрыта", "new_type": "Булево?"}),
    ("property_remove", {"name": "Титул"}),
    ("property_rename", {"name": "Титул", "new_name": "Заглавие"}),
])
def test_new_op_results_parse_as_yaml(op, args):
    res = formedits.apply_operation(PROPS, op, args)
    assert pyyaml.safe_load(res.new_text)
    assert unchanged_outside(PROPS, res)


def test_apply_operation_new_ops_and_camel_op():
    res = formedits.apply_operation(PROPS, "insertFragment", {
        "parent": "Наследует", "slot": "Содержимое", "fragment": "Тип: Надпись",
    })
    assert res.node_id is not None
    res = formedits.apply_operation(PROPS, "property-retype", {
        "name": "Скрыта", "newType": "Булево?",
    })
    assert "Тип: Булево?" in res.new_text
    res = formedits.apply_operation(PROPS, "property_rename", {
        "name": "Титул", "new_name": "Заглавие",
    })
    assert res.notes  # the binding-usage warning rides on the dispatcher result too
    with pytest.raises(FormModelError, match="не задан параметр"):
        formedits.apply_operation(PROPS, "property_add", {"name": "Итог"})
    with pytest.raises(FormModelError, match="не задан параметр"):
        formedits.apply_operation(PROPS, "insert_fragment", {"parent": TPL, "slot": "Содержимое"})


# --- smoke over the demo project ----------------------------------------------------------


def test_demo_components_parse(request):
    demo = request.config.rootpath / "demo"
    components = []
    for path in sorted(demo.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8-sig")
        if "ВидЭлемента: КомпонентИнтерфейса" not in text:
            continue
        components.append(path)
        form = parse_form(text)
        assert form.root.type_full
        ids = list(form.nodes)
        assert len(ids) == len(set(ids))
        for node in form.nodes.values():
            assert 0 <= node.span.start < node.span.end <= len(text)
            assert node.span.start <= node.content_span.start
            hit = node_at(form, node.content_span.start)
            assert hit is not None and hit.id == node.id
    assert components, "в demo/ не нашлось ни одного компонента интерфейса"
