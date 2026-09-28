"""yaml/dynlist-filter-computed-alias: a filter item of a dynamic list named after the alias of
a list field the filter cannot see - a computed field, a renamed column, a path through a
reference.

A filter looks its field up among the columns of the tables the list selects from, so such a
filter either goes by a column of the same name or fails the apply. The Russian spellings need
no Element data - the yaml is composed, the names are compared as they are written - so those
tests run in a public checkout; the English spellings come from the term dictionary and are
marked `needs_data`.
"""

import pytest

from xbsl import engine

RULE = "yaml/dynlist-filter-computed-alias"

_FILTER_ITEM = (
    "                    -\n"
    "                        Тип: ЭлементФильтра\n"
    "                        Поле: {field}\n"
    "                        ВидСравнения: Больше\n"
    "                        Значение: 0\n"
)


def _form(filter_items: str, joined_filter_items: str = "") -> str:
    """A table over a dynamic list of batches joined with their stock; the caller seeds the
    items of the list's own filter and, optionally, of the joined table's filter."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: СписокПартий\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Таблица<ДинамическийСписок>\n"
        "        Имя: Список\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Партии\n"
        "                Псевдоним: Партии\n"
        "            ПрисоединенныеТаблицы:\n"
        "                -\n"
        "                    Тип: ПрисоединеннаяТаблица\n"
        "                    Таблица: ОстаткиПартий\n"
        "                    Псевдоним: Остатки\n"
        "                    Фильтр:\n"
        "                        Элементы:\n"
        "                            -\n"
        "                                Тип: ЭлементФильтраВыражение\n"
        "                                Выражение: Остатки.Партия == Партии.Ссылка\n"
        + joined_filter_items
        + "            Поля:\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Ссылка\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Остатки.Количество.ЗаменитьNull(0)\n"
        "                    Псевдоним: Количество\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: ВЫБОР КОГДА Остатки.Количество > 0 ТОГДА \"есть\" "
        "ИНАЧЕ \"нет\" КОНЕЦ\n"
        "                    Псевдоним: Наличие\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Склад\n"
        "                    Псевдоним: СкладПартии\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Склад.Владелец\n"
        "                    Псевдоним: ВладелецСклада\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Цена\n"
        "                    Псевдоним: Цена\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Срок\n"
        "                    Псевдоним: Срок\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партия\n"
        "                    Псевдоним: НомерПартии\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Склад.Владелец\n"
        "                    Псевдоним: Владелец\n"
        "            Фильтр:\n"
        "                Тип: ГруппаЭлементовФильтра\n"
        "                Элементы:\n"
        + filter_items
        + "            Сортировка:\n"
        "                -\n"
        "                    Поле: Количество\n"
        "                    НаправлениеСортировки: ПоУбыванию\n"
    )


def _lint(text: str, name: str = "СписокПартий.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={RULE})


def _item(field: str) -> str:
    return _FILTER_ITEM.format(field=field)


def test_rule_is_a_file_warning_on_by_default():
    info = next(r for r in engine.RULES if r.id == RULE)

    assert info.severity.value == "warning"
    assert info.enabled_by_default is True
    assert info.tier == "D" and info.scope == "file"


def test_a_filter_by_the_alias_names_the_column_it_goes_by():
    """The expression reads a column of a joined table named like the alias: that column is
    what the filter reads, and the message says which one."""
    text = _form(_item("Количество"))

    diags = _lint(text)

    assert len(diags) == 1
    line = text.splitlines().index("                        Поле: Количество") + 1
    assert (diags[0].line, diags[0].col) == (line, 31)
    assert "'Количество'" in diags[0].message
    assert "Остатки.Количество" in diags[0].message
    assert "ЭлементФильтраВыражение" in diags[0].message


def test_a_filter_by_an_alias_no_column_is_named_after():
    """No column of that name in the expression: the message tells both outcomes - a column of
    another table read silently, or the apply refused."""
    diags = _lint(_form(_item("Наличие")))

    assert len(diags) == 1
    assert "'Наличие'" in diags[0].message
    assert "Неизвестное, или неоднозначное поле" in diags[0].message


def test_an_item_of_a_nested_group_is_judged():
    nested = (
        "                    -\n"
        "                        Тип: ГруппаЭлементовФильтра\n"
        "                        ВидГруппы: ГруппаИли\n"
        "                        Элементы:\n"
        "    " + _item("Наличие").replace("\n", "\n    ").rstrip(" ")
    )

    assert len(_lint(_form(nested))) == 1


@pytest.mark.parametrize(("field", "path"), (
    ("СкладПартии", "Партии.Склад"),
    ("НомерПартии", "Партия"),
    ("ВладелецСклада", "Партии.Склад.Владелец"),
    ("Владелец", "Партии.Склад.Владелец"),
))
def test_a_filter_by_the_alias_of_a_renamed_column_or_a_path(field, path):
    """A renamed column, qualified or bare, and a path through a reference - under another name
    or under the name of its last part: a live apply refused the first three shapes and found
    the table's own column for the fourth, so the message says both outcomes and names the path
    as the cure."""
    text = _form(_item(field))

    diags = _lint(text)

    assert len(diags) == 1
    line = text.splitlines().index(f"                        Поле: {field}") + 1
    assert (diags[0].line, diags[0].col) == (line, 31)
    assert f"'{field}'" in diags[0].message
    assert f"Поле: {path}." in diags[0].message
    assert "Неизвестное, или неоднозначное поле" in diags[0].message
    assert "ЭлементФильтраВыражение" not in diags[0].message


@pytest.mark.parametrize("item", (
    _item("Остатки.Количество"),
    _item("Партии.Склад.Владелец"),
    _item("=ПолеОтбора"),
    _item("Цена"),
    _item("Срок"),
    _item("Склад"),
    (
        "                    -\n"
        "                        Тип: ЭлементФильтраВыражение\n"
        "                        Выражение: Остатки.Количество.ЗаменитьNull(0) > 0\n"
        "                        Использовать: =ТолькоВНаличии\n"
    ),
))
def test_what_the_filter_resolves_itself_is_left_alone(item):
    """A qualified column and a path, a binding, the alias of a column under its own name
    (qualified or bare), a bare column and an expression item; the sorting by the computed alias
    in the fixture is legal as well."""
    assert _lint(_form(item)) == []


def _implicit_table_form(expression: str, alias: str) -> str:
    """A list whose main table goes by its written name (no alias), filtered by `alias`."""
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: СписокПартий\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Таблица<ДинамическийСписок>\n"
        "        Имя: Список\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Учет::Склады::Партии\n"
        "            Поля:\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        f"                    Выражение: {expression}\n"
        f"                    Псевдоним: {alias}\n"
        "            Фильтр:\n"
        "                Элементы:\n"
        + _item(alias)
    )


@pytest.mark.parametrize(("expression", "alias", "found"), (
    ("Партии.Склад", "Склад", 0),
    ("Партии.Склад.Владелец", "Владелец", 1),
    ("Партии.Склад", "СкладПартии", 1),
))
def test_a_table_going_by_its_written_name(expression, alias, found):
    """The file does not show every spelling such a table is read by, so `Партии.Склад`
    aliased `Склад` may be its column under its own name; a longer path and a renamed column
    are judged all the same."""
    assert len(_lint(_implicit_table_form(expression, alias))) == found


def test_the_filter_of_a_joined_table_is_not_judged():
    joined = (
        "                            -\n"
        "                                Тип: ЭлементФильтра\n"
        "                                Поле: Количество\n"
        "                                ВидСравнения: Больше\n"
        "                                Значение: 0\n"
    )

    assert _lint(_form(_item("Склад"), joined_filter_items=joined)) == []


def test_a_list_declared_as_the_default_value_of_a_form_property():
    text = (
        "ВидЭлемента: ФормаСписка\n"
        "Имя: ПартииФормаСписка\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Список\n"
        "        Тип: ДинамическийСписок\n"
        "        ЗначениеПоУмолчанию:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Партии\n"
        "                Псевдоним: Партии\n"
        "            Поля:\n"
        "                -\n"
        "                    Тип: ПолеДинамическогоСписка\n"
        "                    Выражение: Партии.Количество * Партии.Цена\n"
        "                    Псевдоним: Сумма\n"
        "            Фильтр:\n"
        "                Элементы:\n"
        "                    -\n"
        "                        Тип: ЭлементФильтра\n"
        "                        Поле: Сумма\n"
        "                        ВидСравнения: Больше\n"
        "                        Значение: 0\n"
    )

    diags = _lint(text, "ПартииФормаСписка.yaml")

    assert [d.rule_id for d in diags] == [RULE]


@pytest.mark.needs_data
def test_english_spellings_are_judged_too():
    text = (
        "ElementKind: ListForm\n"
        "Name: BatchesListForm\n"
        "Properties:\n"
        "    -\n"
        "        Name: List\n"
        "        Type: DynamicList\n"
        "        DefaultValue:\n"
        "            MainTable:\n"
        "                Table: Batches\n"
        "                Alias: Batches\n"
        "            JoinedTables:\n"
        "                -\n"
        "                    Type: JoinedTable\n"
        "                    Table: BatchStock\n"
        "                    Alias: Stock\n"
        "            Fields:\n"
        "                -\n"
        "                    Type: DynamicListField\n"
        "                    Expression: Stock.Quantity.ReplaceNull(0)\n"
        "                    Alias: Quantity\n"
        "            Filter:\n"
        "                Items:\n"
        "                    -\n"
        "                        Type: FilterItem\n"
        "                        Field: Quantity\n"
        "                        ComparisonType: Greater\n"
        "                        Value: 0\n"
    )

    diags = _lint(text, "BatchesListForm.yaml")

    assert len(diags) == 1
    assert "Stock.Quantity" in diags[0].message


@pytest.mark.needs_data
def test_english_renamed_column_is_judged_too():
    text = (
        "ElementKind: ListForm\n"
        "Name: BatchesListForm\n"
        "Properties:\n"
        "    -\n"
        "        Name: List\n"
        "        Type: DynamicList\n"
        "        DefaultValue:\n"
        "            MainTable:\n"
        "                Table: Batches\n"
        "                Alias: Batches\n"
        "            Fields:\n"
        "                -\n"
        "                    Type: DynamicListField\n"
        "                    Expression: Batches.Warehouse\n"
        "                    Alias: BatchWarehouse\n"
        "            Filter:\n"
        "                Items:\n"
        "                    -\n"
        "                        Type: FilterItem\n"
        "                        Field: BatchWarehouse\n"
        "                        ComparisonType: Equal\n"
        "                        Value: 0\n"
    )

    diags = _lint(text, "BatchesListForm.yaml")

    assert len(diags) == 1
    assert "Batches.Warehouse" in diags[0].message
