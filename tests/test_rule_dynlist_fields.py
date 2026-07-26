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
