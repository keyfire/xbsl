"""Checks of the dynamic-list declaration rules (xbsl/rules/dynlist_decl.py).

The Russian-spelling halves of the yaml rules work without the platform data, so those
tests run in a public checkout; the English spellings come from the term dictionary and
the code half of the filter rule tokenizes the module, so such tests are marked
`needs_data` one by one.
"""

import pytest

from xbsl import engine

JOINED = "yaml/dynlist-joined-table-param"
LISTFORM = "yaml/list-form-needs-dynlist"
RACE = "yaml/dynlist-filter-disabled"


def _lint(select: str, *files: tuple[str, str]):
    sources = [engine.load_text(name, content) for name, content in files]
    return engine.run_sources(sources, select={select})


# --- yaml/dynlist-joined-table-param ----------------------------------------------------

def _joined_form(argument_lines: str = "", filter_expr: str = "") -> str:
    """A dynamic list with one joined table; the caller seeds its arguments and filter."""
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Таблица<ДинамическийСписок>\n"
        "        Имя: Список\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Лента\n"
        "                Аргументы:\n"
        "                    -\n"
        "                        Тип: АргументТаблицыВыражение\n"
        "                        Имя: ЯзыкСодержимого\n"
        "                        Выражение: '&ЯзыкСодержимого'\n"
        "            ПрисоединенныеТаблицы:\n"
        "                -\n"
        "                    Тип: ПрисоединеннаяТаблица\n"
        "                    Таблица: Переводы\n"
        "                    Псевдоним: Перевод\n"
    )
    if argument_lines:
        text += "                    Аргументы:\n" + argument_lines
    if filter_expr:
        text += (
            "                    Фильтр:\n"
            "                        Элементы:\n"
            "                            -\n"
            "                                Тип: ЭлементФильтраВыражение\n"
            f"                                Выражение: {filter_expr}\n"
        )
    return text


def _argument(value_line: str) -> str:
    return (
        "                        -\n"
        "                            Тип: АргументТаблицы\n"
        "                            Имя: КодЯзыка\n"
        f"                            {value_line}\n"
    )


def _nested_argument(value: str) -> str:
    return (
        "                        -\n"
        "                            Тип: АргументТаблицы\n"
        "                            Имя: КодЯзыка\n"
        "                            Значение:\n"
        "                                Тип: Строка\n"
        f"                                Значение: \"{value}\"\n"
    )


def test_joined_nested_value_parameter_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_nested_argument("&КодЯзыка"))))
    assert [x.rule_id for x in d] == [JOINED]
    assert "'&КодЯзыка'" in d[0].message
    assert d[0].line == 26  # the nested value scalar, not the argument mapping


def test_joined_scalar_value_parameter_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_argument("Значение: \"&КодЯзыка\""))))
    assert len(d) == 1 and "'&КодЯзыка'" in d[0].message


def test_joined_argument_binding_expression_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_argument("Выражение: '=Общее.КодЯзыкаСеанса()'"))))
    assert len(d) == 1 and "'=Общее.КодЯзыкаСеанса()'" in d[0].message


def test_joined_argument_parameter_expression_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_argument("Выражение: '&Категория'"))))
    assert len(d) == 1


def test_joined_value_binding_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_argument("Значение: '=КодЯзыка'"))))
    assert len(d) == 1 and "'=КодЯзыка'" in d[0].message


def test_joined_filter_parameter_flagged():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(
        filter_expr="Перевод.Объект == Лента.Ссылка и Перевод.КодЯзыка == &КодЯзыка",
    )))
    assert [x.rule_id for x in d] == [JOINED]
    assert "'&КодЯзыка'" in d[0].message


def test_main_table_arguments_are_legal():
    # the builder always passes a list parameter to the MAIN table - that alone is silent
    assert _lint(JOINED, ("Ф.yaml", _joined_form())) == []


def test_joined_literal_argument_is_legal():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_nested_argument("ru"))))
    assert d == []


def test_ampersand_inside_string_literal_is_legal():
    d = _lint(JOINED, ("Ф.yaml", _joined_form(
        filter_expr="Перевод.Код != \"&нет\" и не Перевод.ПометкаУдаления",
    )))
    assert d == []


def test_ampersand_data_value_is_legal():
    # "&nbsp;" starts with '&' but is not a parameter: the whole value must match `&Имя`
    d = _lint(JOINED, ("Ф.yaml", _joined_form(_nested_argument("&nbsp;"))))
    assert d == []


@pytest.mark.needs_data
def test_english_joined_keys_flagged():
    form = (
        "ElementKind: InterfaceComponent\n"
        "Name: F\n"
        "Content:\n"
        "    -\n"
        "        Type: Table<DynamicList>\n"
        "        Source:\n"
        "            MainTable:\n"
        "                Table: Feed\n"
        "            JoinedTables:\n"
        "                -\n"
        "                    Type: JoinedTable\n"
        "                    Table: Translations\n"
        "                    Alias: Translation\n"
        "                    Arguments:\n"
        "                        -\n"
        "                            Type: TableArgument\n"
        "                            Name: LanguageCode\n"
        "                            Value:\n"
        "                                Type: String\n"
        "                                Value: \"&LanguageCode\"\n"
        "                    Filter:\n"
        "                        Items:\n"
        "                            -\n"
        "                                Type: FilterItemExpression\n"
        "                                Expression: Translation.Code == &LanguageCode\n"
    )
    d = _lint(JOINED, ("F.yaml", form))
    assert sorted(x.line for x in d) == [20, 25]


# --- yaml/list-form-needs-dynlist -------------------------------------------------------

def _list_form(*types: str, base: str = "ФормаСписка<Неопределено>") -> str:
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Наследует:\n"
        f"    Тип: {base}\n"
        "    Содержимое:\n"
        "        Тип: Группа\n"
        "        Содержимое:\n"
    )
    for typ in types:
        text += f"            -\n                Тип: {typ}\n                Имя: Список\n"
    return text


def test_array_table_in_list_form_flagged():
    d = _lint(LISTFORM, ("Ф.yaml", _list_form("Таблица<ИсточникДанныхМассив<Общее.Строка>>")))
    assert [x.rule_id for x in d] == [LISTFORM]
    assert "Таблица<ИсточникДанныхМассив<Общее.Строка>>" in d[0].message
    assert (d[0].line, d[0].col) == (4, 10)  # the inherited type, where the cure applies


def test_custom_list_over_array_flagged():
    d = _lint(LISTFORM, ("Ф.yaml", _list_form("ПроизвольныйСписок<ИсточникДанныхМассив<Общее.Строка>>")))
    assert len(d) == 1


def test_bare_list_form_head_counts_too():
    d = _lint(LISTFORM, ("Ф.yaml", _list_form(
        "Таблица<ИсточникДанныхМассив<Общее.Строка>>", base="ФормаСписка",
    )))
    assert len(d) == 1


def test_dynamic_list_table_is_legal():
    assert _lint(LISTFORM, ("Ф.yaml", _list_form("Таблица<ДинамическийСписок>"))) == []


def test_card_list_over_dynamic_list_is_legal():
    # the scaffold's own card list: the dynamic list sits deeper than the head
    d = _lint(LISTFORM, ("Ф.yaml", _list_form("ПроизвольныйСписок<ДинамическийСписок<Товары>>")))
    assert d == []


def test_array_table_next_to_dynamic_list_is_legal():
    d = _lint(LISTFORM, ("Ф.yaml", _list_form(
        "Таблица<ИсточникДанныхМассив<Общее.Строка>>", "Таблица<ДинамическийСписок>",
    )))
    assert d == []


def test_list_form_without_any_list_is_not_judged():
    # the dynamic list may live inside a nested project component - absence proves nothing
    assert _lint(LISTFORM, ("Ф.yaml", _list_form("Надпись"))) == []


def test_plain_form_with_array_table_is_legal():
    d = _lint(LISTFORM, ("Ф.yaml", _list_form(
        "Таблица<ИсточникДанныхМассив<Общее.Строка>>", base="Форма",
    )))
    assert d == []


@pytest.mark.needs_data
def test_english_list_form_flagged():
    form = (
        "ElementKind: InterfaceComponent\n"
        "Name: F\n"
        "Inherits:\n"
        "    Type: ListForm<Undefined>\n"
        "    Content:\n"
        "        Type: Group\n"
        "        Content:\n"
        "            -\n"
        "                Type: Table<ArrayDataSource<Common.Row>>\n"
    )
    d = _lint(LISTFORM, ("F.yaml", form))
    assert [x.rule_id for x in d] == [LISTFORM]
    assert (d[0].line, d[0].col) == (4, 11)


# --- yaml/dynlist-filter-disabled -------------------------------------------------------

def _filter_form(use_line: str = "Использовать: Ложь", item: str = "ЭлементФильтра",
                 field_line: str = "Поле: Исполнитель") -> str:
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Список\n"
        "Свойства:\n"
        "    -\n"
        "        Имя: Данные\n"
        "        Тип: ДинамическийСписок\n"
        "        ЗначениеПоУмолчанию:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Заказы\n"
        "            Фильтр:\n"
        "                Тип: ГруппаЭлементовФильтра\n"
        "                Элементы:\n"
        "                    -\n"
        f"                        Тип: {item}\n"
    )
    if field_line:
        text += f"                        {field_line}\n"
    if use_line:
        text += f"                        {use_line}\n"
    return text


_ENABLING_CODE = (
    "// Turns the subscriber filter on after the service data arrives.\n"
    "@Обработчик\n"
    "метод ПослеСоздания()\n"
    "    для Элемент из Данные.Фильтр.Элементы\n"
    "        (Элемент как ЭлементФильтра).Использовать = Истина\n"
    "    ;\n"
    ";\n"
)

_COMPARING_CODE = (
    "// Only reads the flag - never assigns it.\n"
    "@Обработчик\n"
    "метод ПослеСоздания()\n"
    "    для Элемент из Данные.Фильтр.Элементы\n"
    "        если (Элемент как ЭлементФильтра).Использовать == Ложь\n"
    "            Сообщить(\"выключен\")\n"
    "        ;\n"
    "    ;\n"
    ";\n"
)


@pytest.mark.needs_data
def test_disabled_filter_enabled_from_code_flagged():
    d = _lint(RACE, ("Список.yaml", _filter_form()), ("Список.xbsl", _ENABLING_CODE))
    assert [x.rule_id for x in d] == [RACE]
    assert "'Исполнитель'" in d[0].message
    assert d[0].line == 16  # the declared value, where the cure applies


@pytest.mark.needs_data
def test_enabled_declaration_next_to_assignment_is_the_cure():
    d = _lint(RACE, ("Список.yaml", _filter_form(use_line="Использовать: Истина")),
              ("Список.xbsl", _ENABLING_CODE))
    assert d == []


@pytest.mark.needs_data
def test_missing_use_key_defaults_to_enabled():
    d = _lint(RACE, ("Список.yaml", _filter_form(use_line="")),
              ("Список.xbsl", _ENABLING_CODE))
    assert d == []


def test_disabled_filter_without_code_is_not_judged():
    # no paired module at all: the filter may be switched on by the user via the panel
    assert _lint(RACE, ("Список.yaml", _filter_form())) == []


@pytest.mark.needs_data
def test_comparison_is_not_an_assignment():
    d = _lint(RACE, ("Список.yaml", _filter_form()), ("Список.xbsl", _COMPARING_CODE))
    assert d == []


@pytest.mark.needs_data
def test_module_of_another_stem_does_not_pair():
    d = _lint(RACE, ("Список.yaml", _filter_form()), ("Другой.xbsl", _ENABLING_CODE))
    assert d == []


@pytest.mark.needs_data
def test_group_item_reported_without_a_field_name():
    d = _lint(RACE, ("Список.yaml", _filter_form(item="ГруппаЭлементовФильтра", field_line="")),
              ("Список.xbsl", _ENABLING_CODE))
    assert [x.rule_id for x in d] == [RACE]
    assert "''" not in d[0].message  # the unnamed wording, not an empty quoted field


@pytest.mark.needs_data
def test_english_use_false_flagged():
    form = (
        "ElementKind: InterfaceComponent\n"
        "Name: TheList\n"
        "Properties:\n"
        "    -\n"
        "        Name: Data\n"
        "        Type: DynamicList\n"
        "        DefaultValue:\n"
        "            MainTable:\n"
        "                Table: Orders\n"
        "            Filter:\n"
        "                Type: FilterItemGroup\n"
        "                Items:\n"
        "                    -\n"
        "                        Type: FilterItem\n"
        "                        Field: Subscriber\n"
        "                        Use: False\n"
    )
    code = (
        "// The English half of the same pair.\n"
        "@Handler\n"
        "method AfterCreation()\n"
        "    for Item from Data.Filter.Items\n"
        "        (Item as FilterItem).Use = True\n"
        "    ;\n"
        ";\n"
    )
    d = _lint(RACE, ("TheList.yaml", form), ("TheList.xbsl", code))
    assert [x.rule_id for x in d] == [RACE]
    assert "'Subscriber'" in d[0].message
