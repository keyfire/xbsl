"""Checks of the yaml/dynlist-missing-field rule (completeness of a dynamic list's Источник.Поля).

The rule does not depend on the platform data - it works off the project yaml, so this file
is not in the data-dependent module list of conftest.py.
"""

from xbsl import engine

RULE = "yaml/dynlist-missing-field"

# A catalog with three attributes; Наименование is declared without Тип (a standard attribute).
_ТОВАРЫ = """ВидЭлемента: Справочник
Имя: Товары
Реквизиты:
    -
        Имя: Наименование
        Длина: 250
    -
        Имя: Цена
        Тип: Число
    -
        Имя: Опубликован
        Тип: Булево
"""


def _форма(поля: list[str], *, тип_строки="Товары.АвтоматическаяФормаСписка.ДанныеСтрокиСписка",
           таблица="Товары") -> str:
    generic = f"<ДинамическийСписок<{тип_строки}>>" if тип_строки else "<ДинамическийСписок>"
    text = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        f"        Тип: Таблица{generic}\n"
        "        Имя: Список\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        f"                Таблица: {таблица}\n"
        "            Поля:\n"
    )
    for f in поля:
        text += "                -\n                    Тип: ПолеДинамическогоСписка\n"
        text += f"                    Выражение: {f}\n"
    return text


def _lint(*files: tuple[str, str]):
    sources = [engine.load_text(name, content) for name, content in files]
    return engine.run_sources(sources, select={RULE})


def _lint_form(form_yaml: str, obj_yaml: str = _ТОВАРЫ):
    return _lint(("Товары.yaml", obj_yaml), ("Ф.yaml", form_yaml))


# --- The main criterion ----------------------------------------------------------------

def test_full_field_set_not_flagged():
    d = _lint_form(_форма(["Ссылка", "Наименование", "Цена", "Опубликован"]))
    assert d == []


def test_missing_attribute_flagged():
    # the Цена attribute is not selected - a list typed by the auto-form will crash at runtime
    d = _lint_form(_форма(["Ссылка", "Наименование", "Опубликован"]))
    assert len(d) == 1
    assert d[0].rule_id == RULE
    assert "'Цена'" in d[0].message and "'Товары'" in d[0].message
    assert d[0].line == 5  # the line with the value Тип: Таблица<ДинамическийСписок<...>>


def test_new_attribute_without_form_update_flagged():
    # the pitfall scenario: an attribute was added to the catalog, the list form was not updated
    расширенный = _ТОВАРЫ + "    -\n        Имя: Артикул\n        Тип: Строка\n"
    d = _lint_form(_форма(["Ссылка", "Наименование", "Цена", "Опубликован"]), расширенный)
    assert len(d) == 1 and "'Артикул'" in d[0].message


def test_missing_ssylka_not_required():
    # Ссылка is not an attribute - the rule only requires what is declared in Реквизиты
    d = _lint_form(_форма(["Наименование", "Цена", "Опубликован"]))
    assert d == []


# --- Lists that infer the row type from the declaration are not checked -----------------

def test_untyped_list_not_flagged():
    d = _lint_form(_форма(["Ссылка", "Наименование"], тип_строки=None))
    assert d == []


def test_form_own_row_type_not_flagged():
    # a two-segment row type of the form itself (ФормаX.ДанныеСтрокиСписка) - a field subset is legal
    d = _lint_form(_форма(["Наименование"], тип_строки="Ф.ДанныеСтрокиСписка"))
    assert d == []


# --- Zero-false-positive guards ---------------------------------------------------------

def test_collection_attribute_not_required():
    # a collection attribute is not selectable - excluded from the required set
    объект = _ТОВАРЫ + "    -\n        Имя: Файлы\n        Тип: Массив<ДвоичныйОбъект.Ссылка>\n"
    d = _lint_form(_форма(["Ссылка", "Наименование", "Цена", "Опубликован"]), объект)
    assert d == []


def test_foreign_main_table_skipped():
    # ОсновнаяТаблица does not match the generic's object - the semantics is unclear, the node is skipped
    d = _lint_form(_форма(["Ссылка"], таблица="Склады"))
    assert d == []


def test_unknown_object_skipped():
    # the object is not in the project (e.g. from an external library) - do not guess
    d = _lint(("Ф.yaml", _форма(["Ссылка"], тип_строки="Чужой.АвтоматическаяФормаСписка.ДанныеСтрокиСписка",
                                таблица="Чужой")))
    assert d == []


def test_field_without_expression_skips_node():
    form = _форма(["Наименование"])
    form += "                -\n                    Тип: ПолеДинамическогоСписка\n"
    d = _lint_form(form)  # a field without Выражение - the set cannot be trusted
    assert d == []


def test_empty_fields_skipped():
    form = (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        "        Тип: Таблица<ДинамическийСписок<Товары.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>\n"
        "        Источник:\n"
        "            ОсновнаяТаблица:\n"
        "                Таблица: Товары\n"
        "            Поля: []\n"
    )
    d = _lint_form(form)
    assert d == []


def test_qualified_expression_and_alias_count_as_present():
    form = _форма(["Ссылка", "Наименование", "Т.Цена"])
    form += "                -\n                    Тип: ПолеДинамическогоСписка\n"
    form += "                    Выражение: ВЫБОР КОГДА Цена > 0 ТОГДА Истина ИНАЧЕ Ложь КОНЕЦ\n"
    form += "                    Псевдоним: Опубликован\n"
    d = _lint_form(form)
    assert d == []


# --- yaml/dynlist-row-editing ----------------------------------------------------------

EDIT_RULE = "yaml/dynlist-row-editing"

_FLAT_CATALOG = "ВидЭлемента: Справочник\nИмя: Заявки\n"
_HIER_CATALOG = "ВидЭлемента: Справочник\nИмя: Категории\nИерархический: Истина\n"


def _event_form(type_text: str, event_key: str = "ПриРедактированииСтроки") -> str:
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        f"        Тип: {type_text}\n"
        "        Имя: Список\n"
        f"        {event_key}: СтрокаПриРедактировании\n"
    )


def _lint_edit(*files: tuple[str, str]):
    sources = [engine.load_text(name, content) for name, content in files]
    return engine.run_sources(sources, select={EDIT_RULE})


def test_row_edit_on_a_flat_dynlist_flagged():
    """The registry case: the handler looks like working code, the platform never calls it."""
    d = _lint_edit(
        ("Заявки.yaml", _FLAT_CATALOG),
        ("Ф.yaml", _event_form("Таблица<ДинамическийСписок<Заявки>>")),
    )
    assert [x.rule_id for x in d] == [EDIT_RULE]
    assert "Заявки" in d[0].message and "не вызывает" in d[0].message
    assert (d[0].line, d[0].col) == (7, 34)  # the handler name, not the top of the file


def test_a_hierarchical_source_is_left_alone():
    """Node rows of a hierarchy are what the event is documented for."""
    d = _lint_edit(
        ("Категории.yaml", _HIER_CATALOG),
        ("Ф.yaml", _event_form("Таблица<ДинамическийСписок<Категории>>")),
    )
    assert d == []


def test_an_untyped_dynlist_is_not_guessed():
    """The untyped list of a list form implies its entity - resolving that would guess."""
    d = _lint_edit(
        ("Заявки.yaml", _FLAT_CATALOG),
        ("Ф.yaml", _event_form("Таблица<ДинамическийСписок>")),
    )
    assert d == []


def test_an_entity_outside_the_project_is_left_alone():
    d = _lint_edit(("Ф.yaml", _event_form("Таблица<ДинамическийСписок<Чужая>>")))
    assert d == []


def test_the_row_form_chain_resolves_the_entity():
    chain = "Таблица<ДинамическийСписок<Заявки.АвтоматическаяФормаСписка.ДанныеСтрокиСписка>>"
    d = _lint_edit(("Заявки.yaml", _FLAT_CATALOG), ("Ф.yaml", _event_form(chain)))
    assert [x.rule_id for x in d] == [EDIT_RULE]


def test_an_array_source_is_not_judged():
    d = _lint_edit(
        ("Заявки.yaml", _FLAT_CATALOG),
        ("Ф.yaml", _event_form("Таблица<ИсточникДанныхМассив<Строка>>")),
    )
    assert d == []


def test_other_row_events_are_legal_on_a_flat_list():
    d = _lint_edit(
        ("Заявки.yaml", _FLAT_CATALOG),
        ("Ф.yaml", _event_form(
            "Таблица<ДинамическийСписок<Заявки>>", event_key="ПриНажатииСтроки"
        )),
    )
    assert d == []


# --- yaml/dynlist-column-sort-lost -----------------------------------------------------

SORT_RULE = "yaml/dynlist-column-sort-lost"


def _column_form(value: str, *, table="Таблица<ДинамическийСписок<Заявки>>") -> str:
    return (
        "ВидЭлемента: КомпонентИнтерфейса\n"
        "Имя: Ф\n"
        "Содержимое:\n"
        "    -\n"
        f"        Тип: {table}\n"
        "        Имя: Список\n"
        "        Колонки:\n"
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<Заявки>>\n"
        f"                Значение: {value}\n"
    )


def _lint_sort(form: str):
    return engine.run_sources([engine.load_text("Ф.yaml", form)], select={SORT_RULE})


def test_a_computed_column_is_reported():
    """The live case: a status badge built by a form method never sorts by its header."""
    d = _lint_sort(_column_form("=ПодписьСостояния(ДанныеСтроки.Данные.Состояние)"))
    assert [(x.rule_id, x.line) for x in d] == [(SORT_RULE, 10)]
    assert "ПодписьСостояния" in d[0].message


def test_a_qualified_call_is_reported_too():
    d = _lint_sort(_column_form("=СостояниеЗадачи.Текст(ДанныеСтроки.Данные.Статус)"))
    assert len(d) == 1 and "СостояниеЗадачи.Текст" in d[0].message


def test_a_bare_field_binding_is_the_sortable_form():
    """A second, computed column stands next to it on purpose: without a call anywhere in
    the file the cheap text gate would carry the test, and a broken pattern would pass."""
    form = _column_form("=ДанныеСтроки.Данные.Начало")
    form += (
        "            -\n"
        "                Тип: СтандартнаяКолонкаТаблицы<СтрокаДинамическогоСписка<Заявки>>\n"
        "                Значение: =ПодписьСостояния(ДанныеСтроки.Данные.Состояние)\n"
    )
    d = _lint_sort(form)
    assert [x.line for x in d] == [13], [x.message for x in d]  # only the computed one


def test_an_array_backed_list_has_no_header_sorting_to_lose():
    d = _lint_sort(_column_form(
        "=ПодписьСостояния(ДанныеСтроки.Данные.Состояние)",
        table="Таблица<ИсточникДанныхМассив<Строка>>",
    ))
    assert d == []


def _with_flag(flag: str) -> str:
    """The same computed column, with one more property declared above the value."""
    form = _column_form("=ОтметкаСрочности(ДанныеСтроки)")
    return form.replace(
        "                Значение:", f"                {flag}\n                Значение:")


def test_a_column_that_switches_sorting_off_is_left_alone():
    """The live case: a badge column carrying `ОтключитьСортировку: Истина` loses nothing."""
    assert _lint_sort(_with_flag("ОтключитьСортировку: Истина")) == []


def test_the_english_spelling_of_the_flag_counts_too():
    assert _lint_sort(_with_flag("DisableSorting: True")) == []


def test_the_flag_switched_off_leaves_the_finding_in_place():
    """Negative control: the skip must hang on the value, not on the key alone."""
    d = _lint_sort(_with_flag("ОтключитьСортировку: Ложь"))
    assert [x.rule_id for x in d] == [SORT_RULE]


# The default-off state is NOT asserted here: in a process with the plugin installed the
# project profile turns these rules on, and such a test would judge the machine rather than
# the engine. The default is guarded by tests/test_metadata_sync.py, which reads the
# registry in a subprocess with XBSL_NO_PLUGINS=1.
