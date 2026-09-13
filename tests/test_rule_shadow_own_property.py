"""style/shadow-own-property: a local variable that hides a property of the object of its method.

The rule reproduces a compiler warning the IDE shows, so both sides are pinned: the
declarations and owners the compiler asks about, and the ones it never does - parameters,
loop variables, `поймать`, static methods, the manager module of an element, a server method
outside the component context.

The module is mixed: reading the owner out of a yaml needs no Element data and runs in the
public CI; everything that parses a module (the lexer takes its keywords from the data) or
reads the type catalog is marked `needs_data`.
"""

import pytest

from xbsl import engine, i18n
from xbsl.rules.style_variables import _own_property_mapper

RULE = "style/shadow-own-property"

_PANEL_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Панель\n"
    "Наследует:\n"
    "    Тип: Группа\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: ОбычноеСвойство\n"
    "        Тип: Строка\n"
    "    -\n"
    "        Имя: КонтекстноеСвойство\n"
    "        Тип: Строка\n"
    "        Контекстное: Истина\n"
)


def _lines(*files):
    return sorted(d.line for d in engine.run_sources(
        [engine.load_text(name, content) for name, content in files], select={RULE},
    ))


def _panel(body: str):
    return _lines(("Панель.yaml", _PANEL_YAML), ("Панель.xbsl", body))


# --- the owner fact (no data needed) --------------------------------------------------------------

def test_owner_fact_carries_the_base_type_and_the_contextual_properties():
    fact = _own_property_mapper(engine.load_text("Панель.yaml", _PANEL_YAML))
    assert fact["k"] == "component"
    assert fact["base"] == "Группа"
    assert fact["own"] == ["ОбычноеСвойство", "КонтекстноеСвойство"]
    assert fact["contextual"] == ["КонтекстноеСвойство"]


def test_owner_fact_takes_the_head_of_a_generic_base_type():
    fact = _own_property_mapper(engine.load_text("Карточка.yaml", (
        "ВидЭлемента: КомпонентИнтерфейса\nИмя: Карточка\n"
        "Наследует:\n    Тип: ФормаОбъекта<Задачи.Объект>\n"
    )))
    assert fact["base"] == "ФормаОбъекта"
    assert fact["own"] == []


def test_owner_fact_of_a_catalog_lists_attributes_and_tabular_sections():
    """Deleted at once, the catalog keeps no deletion mark - the answer is the same without data."""
    fact = _own_property_mapper(engine.load_text("Задачи.yaml", (
        "ВидЭлемента: Справочник\nИмя: Задачи\nРежимУдаления: Немедленно\n"
        "Реквизиты:\n    -\n        Имя: Срок\n        Тип: Дата\n"
        "ТабличныеЧасти:\n    -\n        Имя: Шаги\n"
        "        Реквизиты:\n            -\n                Имя: Шаг\n                Тип: Строка\n"
    )))
    assert fact == {
        "k": "record", "stem": "Задачи", "name": "Задачи", "kind": "Справочник",
        "names": ["Срок", "Шаги"],
    }


def test_owner_fact_ignores_kinds_without_an_object_in_scope():
    fact = _own_property_mapper(engine.load_text("Склады.yaml", (
        "ВидЭлемента: ОбщийМодуль\nИмя: Склады\nОкружение: Сервер\n"
    )))
    assert fact is None


# --- a component: declared, inherited, added by the compiler ------------------------------------

@pytest.mark.needs_data
def test_inherited_property_of_the_base_type_is_reported():
    """The live case: `Inherits: Type: Group` brings `Title` into the component."""
    d = engine.run_sources([
        engine.load_text("Панель.yaml", _PANEL_YAML),
        engine.load_text("Панель.xbsl", "метод Показать()\n    знч Заголовок = 1\n;\n"),
    ], select={RULE})
    assert [(x.rule_id, x.line, x.col) for x in d] == [(RULE, 2, 9)]
    assert "Заголовок" in d[0].message and "Группа" in d[0].message


@pytest.mark.needs_data
def test_declared_and_compiler_added_properties_are_reported():
    assert _panel(
        "метод Показать()\n"
        "    пер ОбычноеСвойство = \"\"\n"
        "    знч Компоненты = 1\n"
        "    знч Итого = 2\n"
        ";\n"
    ) == [2, 3]


@pytest.mark.needs_data
def test_every_declaration_statement_is_judged_where_it_stands():
    """`знч`, `пер` and `исп`, in a nested block and inside a lambda body alike."""
    assert _panel(
        "метод Показать()\n"
        "    пер Ширина = 1\n"
        "    если Истина\n"
        "        знч Высота = 2\n"
        "    ;\n"
        "    знч Действие = метод() ->\n"
        "        знч Видимость = Ложь\n"
        "    ;\n"
        "    исп Содержимое = Ресурс()\n"
        ";\n"
    ) == [2, 4, 7, 9]


@pytest.mark.needs_data
def test_parameters_loops_and_catch_variables_are_left_alone():
    """The compiler asks about declaration statements only: these are other nodes."""
    assert _panel(
        "метод Показать(Заголовок: Строка)\n"
        "    для Ширина из [1, 2]\n"
        "    ;\n"
        "    для Высота = 1 по 2\n"
        "    ;\n"
        "    попытка\n"
        "        знч Проба = 1\n"
        "    поймать Видимость: Исключение\n"
        "    ;\n"
        "    знч Функция = (Доступность: Булево) -> Доступность\n"
        ";\n"
    ) == []


@pytest.mark.needs_data
def test_static_method_is_not_judged():
    assert _panel("статический метод Создать()\n    знч Заголовок = 1\n;\n") == []


@pytest.mark.needs_data
def test_server_method_sees_the_contextual_properties_alone():
    """On the server a method works on the component context, not on the component."""
    assert _panel(
        "@НаСервере @ДоступноСКлиента @Контекстный\n"
        "метод Сохранить()\n"
        "    знч Заголовок = 1\n"
        "    знч ОбычноеСвойство = 2\n"
        "    знч КонтекстноеСвойство = 3\n"
        ";\n"
    ) == [5]


@pytest.mark.needs_data
def test_method_marked_for_both_sides_is_judged_on_the_client():
    assert _panel("@НаКлиенте @НаСервере\nметод Общий()\n    знч Заголовок = 1\n;\n") == [3]


@pytest.mark.needs_data
def test_letter_case_must_match_exactly():
    assert _panel("метод Показать()\n    знч заголовок = 1\n;\n") == []


@pytest.mark.needs_data
def test_english_spelling_of_an_inherited_property_is_reported():
    """The compiler matches either spelling of a platform property."""
    assert _panel("метод Показать()\n    знч Title = 1\n;\n") == [2]


@pytest.mark.needs_data
def test_english_tree_is_judged_by_the_same_owner():
    d = engine.run_sources([
        engine.load_text("Panel.yaml", (
            "ElementKind: InterfaceComponent\nName: Panel\nInherits:\n    Type: Group\n"
        )),
        engine.load_text(
            "Panel.xbsl", "method Show()\n    val Width = 1\n    val Заголовок = 2\n;\n",
        ),
    ], select={RULE})
    assert sorted(x.line for x in d) == [2, 3]


@pytest.mark.needs_data
def test_generic_base_type_brings_its_properties():
    d = _lines(
        ("Карточка.yaml", (
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Карточка\n"
            "Наследует:\n    Тип: ФормаОбъекта<Задачи.Объект>\n"
        )),
        ("Карточка.xbsl", "метод Показать()\n    знч Объект = 1\n    знч КлючОбъекта = 2\n;\n"),
    )
    assert d == [2, 3]


@pytest.mark.needs_data
def test_base_type_the_catalog_does_not_know_is_silent():
    """A base type the catalog does not know gives no property set - silence, not a guess.

    The platform itself refuses a project component as a base; the rule only has to stay quiet.
    """
    d = _lines(
        ("Наследник.yaml", (
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Наследник\nНаследует:\n    Тип: Панель\n"
        )),
        ("Наследник.xbsl", "метод Показать()\n    знч Заголовок = 1\n;\n"),
    )
    assert d == []


@pytest.mark.needs_data
def test_module_that_does_not_parse_is_skipped():
    assert _panel("метод Показать(\n    знч Заголовок = 1\n;\n") == []


@pytest.mark.needs_data
def test_english_message_names_the_base_type_in_english():
    i18n.set_lang("en")
    d = engine.run_sources([
        engine.load_text("Панель.yaml", _PANEL_YAML),
        engine.load_text("Панель.xbsl", "метод Показать()\n    знч Заголовок = 1\n;\n"),
    ], select={RULE})
    assert len(d) == 1 and "Group" in d[0].message and "Группа" not in d[0].message


# --- the other owners: a record, a structure element, a local structure -------------------------

_CATALOG_YAML = (
    "ВидЭлемента: Справочник\nИмя: Задачи\n"
    "Реквизиты:\n    -\n        Имя: Срок\n        Тип: Дата\n"
    "ТабличныеЧасти:\n    -\n        Имя: Шаги\n"
    "        Реквизиты:\n            -\n                Имя: Шаг\n                Тип: Строка\n"
)


@pytest.mark.needs_data
def test_object_module_hides_attributes_and_tabular_sections():
    d = _lines(
        ("Задачи.yaml", _CATALOG_YAML),
        ("Задачи.Объект.xbsl", (
            "метод Проверить()\n"
            "    знч Срок = 1\n"
            "    знч Шаги = 2\n"
            "    знч Шаг = 3\n"
            ";\n"
        )),
    )
    assert d == [2, 3]


@pytest.mark.needs_data
def test_manager_module_of_a_catalog_carries_no_record():
    assert _lines(
        ("Задачи.yaml", _CATALOG_YAML),
        ("Задачи.xbsl", "метод Проверить()\n    знч Срок = 1\n;\n"),
    ) == []


@pytest.mark.needs_data
def test_structure_element_module_hides_its_fields():
    d = _lines(
        ("Остаток.yaml", (
            "ВидЭлемента: Структура\nИмя: Остаток\nОкружение: КлиентИСервер\n"
            "Поля:\n    -\n        Имя: Количество\n        Тип: Число\n"
        )),
        ("Остаток.xbsl", (
            "метод Уменьшить()\n    знч Количество = 1\n;\n"
            "статический метод Создать()\n    знч Количество = 2\n;\n"
        )),
    )
    assert d == [2]


@pytest.mark.needs_data
def test_local_structure_method_hides_the_fields_of_that_structure():
    """The owner of such a method is the structure: a component property is not its business."""
    assert _panel(
        "структура Запись\n"
        "    пер Номер: Число = 0\n"
        "\n"
        "    метод Увеличить()\n"
        "        знч Номер = 1\n"
        "        знч Заголовок = 2\n"
        "    ;\n"
        "\n"
        "    статический метод Создать(): Запись\n"
        "        знч Номер = 3\n"
        "        возврат новый Запись(Номер)\n"
        "    ;\n"
        ";\n"
    ) == [5]


@pytest.mark.needs_data
def test_event_of_the_base_type_is_a_property_too():
    """A handler is bound by assignment, and the compiler keeps events among the properties."""
    assert _panel(
        "метод Показать()\n"
        "    знч ПриНаведении = 1\n"
        "    знч OnHover = 2\n"
        "    знч Активировать = 3\n"
        ";\n"
    ) == [2, 3]


@pytest.mark.needs_data
def test_object_module_hides_the_properties_of_the_object_facet():
    """The reference and the version stamp are the object's in either spelling of the facet class."""
    d = _lines(
        ("Задачи.yaml", "ВидЭлемента: Справочник\nИмя: Задачи\n"),
        ("Задачи.Объект.xbsl", (
            "метод Проверить()\n"
            "    знч Ссылка = 1\n"
            "    знч Reference = 2\n"
            "    знч МеткаВерсии = 3\n"
            "    знч Link = 4\n"
            "    знч ЭтоНовый = 5\n"
            ";\n"
        )),
    )
    assert d == [2, 3, 4]


@pytest.mark.needs_data
def test_record_set_module_hides_the_filter_and_not_the_dimensions():
    d = _lines(
        ("Остатки.yaml", (
            "ВидЭлемента: РегистрСведений\nИмя: Остатки\n"
            "Измерения:\n    -\n        Имя: Склад\n        Тип: Число\n"
        )),
        ("Остатки.НаборЗаписей.xbsl", (
            "метод Проверить()\n    знч Фильтр = 1\n    знч Склад = 2\n;\n"
        )),
        ("Остатки.xbsl", "метод Проверить()\n    знч Фильтр = 1\n;\n"),
    )
    assert d == [2]


@pytest.mark.needs_data
def test_declared_event_is_a_property_on_the_client_only():
    d = _lines(
        ("Карточка.yaml", (
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Карточка\nНаследует:\n    Тип: Группа\n"
            "События:\n    -\n        Имя: ПриВыборе\n        Тип: СобытиеСДанными<Строка>\n"
        )),
        ("Карточка.xbsl", (
            "метод Показать()\n    знч ПриВыборе = 1\n;\n"
            "@НаСервере @ДоступноСКлиента @Контекстный\nметод Сохранить()\n    знч ПриВыборе = 2\n;\n"
        )),
    )
    assert d == [2]


@pytest.mark.needs_data
def test_deletion_mark_is_a_property_while_the_element_deletes_by_mark():
    """The default deletion mode keeps the mark on the object; immediate deletion keeps none."""
    module = "метод Проверить()\n    знч ПометкаУдаления = 1\n    знч DeletionMark = 2\n;\n"
    by_mark = _lines(
        ("Заказы.yaml", "ВидЭлемента: Документ\nИмя: Заказы\n"),
        ("Заказы.Объект.xbsl", module),
    )
    at_once = _lines(
        ("Заказы.yaml", "ВидЭлемента: Документ\nИмя: Заказы\nРежимУдаления: Немедленно\n"),
        ("Заказы.Объект.xbsl", module),
    )
    assert (by_mark, at_once) == ([2, 3], [])


@pytest.mark.needs_data
def test_job_module_hides_the_job_properties_and_its_parameters():
    """The parameters are the job's even when the yaml declares none; a parameter name is not."""
    d = _lines(
        ("Очистка.yaml", (
            "ВидЭлемента: ЗапланированноеЗадание\nИмя: Очистка\n"
            "Параметры:\n    -\n        Имя: Глубина\n        Тип: Число\n"
        )),
        ("Очистка.xbsl", (
            "@Обработчик\n"
            "метод Обработчик()\n"
            "    знч Параметры = 1\n"
            "    знч Ключ = 2\n"
            "    знч Состояние = 3\n"
            "    знч Глубина = 4\n"
            ";\n"
        )),
    )
    assert d == [3, 4, 5]
