"""code/redundant-undefined-guard and code/redundant-type-check: what the types already decide.

The platform's editor warns about a `??`, a `!` and a `?.` whose operand has no empty value in
its type, and about `Х это Тип` whose operand fits the check whatever it holds. The cases below are
the shapes a probe project put through the editor's own language server: each finding here is a
place the editor warns about, and each silent case is one it does not (or one the data cannot
type, where silence is the rule's promise).
"""

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.cli import discover
from xbsl.rules.redundant_checks import display
from xbsl.typeinfer import TypeSet

GUARD = "code/redundant-undefined-guard"
CHECK = "code/redundant-type-check"


def _run(tmp_path: Path, files: dict[str, str], rule: str) -> list:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={rule}) if d.rule_id == rule]


def _module(body: str, params: str = "") -> str:
    return f"метод Проверка({params})\n{body};\n"


# --- data-free pieces ---------------------------------------------------------------------------
# The inference itself (written types, the members of the catalog, the documentation check) is
# tested with the rest of the type sets in test_typeinfer_sets.py.


def test_the_display_of_a_set_writes_the_empty_value_the_source_way():
    assert display(TypeSet(frozenset({"Строка"}), True)) == "Строка?"
    assert display(TypeSet(frozenset({"Строка", "Число"}), True)) == "Строка|Число|?"
    assert TypeSet(frozenset({"Строка", "Число"})).text() == "Строка|Число"


def test_the_display_names_a_structure_of_the_module_the_way_the_module_writes_it():
    local = {"Модуль.Позиция": "Позиция"}
    assert display(TypeSet.of("Модуль.Позиция"), local) == "Позиция"
    assert display(TypeSet.of("Массив<Модуль.Позиция?>"), local) == "Массив<Позиция?>"
    assert display(TypeSet.of("Другой.Позиция"), local) == "Другой.Позиция"


# --- code/redundant-undefined-guard ------------------------------------------------------------


@pytest.mark.needs_data
def test_a_default_over_a_typed_local_is_found(tmp_path):
    found = _run(tmp_path, {"Модуль.xbsl": _module('    пер Имя: Строка = "а"\n    знч Итог = Имя ?? ""\n')}, GUARD)
    assert [(d.line, d.col) for d in found] == [(3, 16)]
    assert "Строка" in found[0].message


@pytest.mark.needs_data
def test_a_nullable_operand_is_left_alone(tmp_path):
    body = '    пер Имя: Строка? = Неопределено\n    знч Итог = Имя ?? ""\n    знч Длина = Имя!.Длина()\n'
    assert _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD) == []


@pytest.mark.needs_data
def test_a_union_without_the_empty_value_is_never_empty(tmp_path):
    body = "    знч Первый = Значение ?? 0\n    знч Второй = Пустое ?? 0\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Значение: Строка|Число, Пустое: Строка|Число|?")}, GUARD)
    assert [d.line for d in found] == [2]


@pytest.mark.needs_data
def test_the_insistent_operation_and_the_safe_access_are_judged_the_same_way(tmp_path):
    body = "    знч Первый = Текст!\n    знч Второй = Текст?.Длина()\n    знч Третий = Пустой?.Длина()\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Текст: Строка, Пустой: Строка?")}, GUARD)
    assert [d.line for d in found] == [2, 3]
    assert "'!'" in found[0].message and "'?.'" in found[1].message


@pytest.mark.needs_data
def test_a_safe_access_over_a_never_empty_value_is_itself_never_empty(tmp_path):
    """The editor warns twice on this line: at the `?.` and at the `??` after it."""
    body = "    знч Длина = Текст?.Длина() ?? 0\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Текст: Строка")}, GUARD)
    assert len(found) == 2 and {d.line for d in found} == {2}


@pytest.mark.needs_data
def test_the_new_value_of_an_event_is_typed_by_the_parameter_declaration(tmp_path):
    module = ("метод ПриИзменении(Источник: ПолеВвода<Строка>, Событие: СобытиеПриИзменении<Строка>)\n"
              "    Применить(Событие.НовоеЗначение ?? \"\")\n;\n\n"
              "метод ПриИзмененииПустого(Источник: ПолеВвода<Строка?>, Событие: СобытиеПриИзменении<Строка?>)\n"
              "    Применить(Событие.НовоеЗначение ?? \"\")\n;\n\n"
              "метод Применить(Текст: Строка)\n;\n")
    found = _run(tmp_path, {"Модуль.xbsl": module}, GUARD)
    assert [d.line for d in found] == [2]


_MARKUP = """ВидЭлемента: КомпонентИнтерфейса
Имя: Карточка
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: ПолеВвода<Число>
            Имя: ПолеКоличества
        -
            Тип: ПолеВвода<Число?>
            Имя: ПолеСкидки
        -
            Тип: Флажок
            Имя: ФлажокСрочно
Свойства:
    -
        Имя: Счетчик
        Тип: Число
    -
        Имя: Остаток
        Тип: Число?
"""


@pytest.mark.needs_data
def test_a_component_value_is_typed_by_the_markup(tmp_path):
    module = ("@НаКлиенте\nметод Собрать()\n"
              "    знч Количество = Компоненты.ПолеКоличества.Значение ?? 0\n"
              "    знч Скидка = Компоненты.ПолеСкидки.Значение ?? 0\n"
              "    знч Срочно = Компоненты.ФлажокСрочно.Значение ?? Ложь\n"
              "    знч Счет = Счетчик ?? 0\n"
              "    знч Ост = Остаток ?? 0\n"
              "    знч Свой = этот.Счетчик ?? 0\n;\n")
    found = _run(tmp_path, {"Карточка.yaml": _MARKUP, "Карточка.xbsl": module}, GUARD)
    assert [d.line for d in found] == [3, 6, 8]


@pytest.mark.needs_data
def test_a_component_typed_by_a_project_type_without_the_empty_value_stays_untyped(tmp_path):
    """The value type of an input field must have a default or hold the empty value; the editor
    refuses `ПолеВвода<Задачи.Ссылка>` and warns about nothing there, so the rule reads nothing."""
    markup = _MARKUP.replace("Тип: ПолеВвода<Число>", "Тип: ПолеВвода<Задачи.Ссылка>")
    module = "@НаКлиенте\nметод Собрать()\n    знч Выбранная = Компоненты.ПолеКоличества.Значение ?? Неопределено\n;\n"
    assert _run(tmp_path, {"Карточка.yaml": markup, "Карточка.xbsl": module}, GUARD) == []


@pytest.mark.needs_data
def test_without_a_markup_pair_the_component_root_means_nothing(tmp_path):
    module = "метод Собрать()\n    знч Количество = Компоненты.ПолеКоличества.Значение ?? 0\n;\n"
    assert _run(tmp_path, {"Модуль.xbsl": module}, GUARD) == []


@pytest.mark.needs_data
def test_a_local_named_like_a_property_hides_it(tmp_path):
    module = ("@НаКлиенте\nметод Собрать(Данные: Массив<Число?>)\n"
              "    для Счетчик из Данные\n        знч Итог = Счетчик ?? 0\n    ;\n;\n")
    assert _run(tmp_path, {"Карточка.yaml": _MARKUP, "Карточка.xbsl": module}, GUARD) == []


@pytest.mark.needs_data
def test_a_declaration_is_read_by_its_block(tmp_path):
    """One name in two loops of a method: the first is never empty, the second may be."""
    body = ("    для Элемент из Строки\n        знч Первый = Элемент ?? \"\"\n    ;\n"
            "    для Элемент из Пустые\n        знч Второй = Элемент ?? \"\"\n    ;\n")
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Строки: Массив<Строка>, Пустые: Массив<Строка?>")}, GUARD)
    assert [d.line for d in found] == [3]


@pytest.mark.needs_data
def test_a_name_declared_further_down_is_not_read_as_a_property(tmp_path):
    module = ("@НаКлиенте\nметод Собрать()\n"
              "    знч Итог = Счетчик ?? 0\n"
              "    знч Счетчик = Итог\n;\n")
    assert _run(tmp_path, {"Карточка.yaml": _MARKUP, "Карточка.xbsl": module}, GUARD) == []


@pytest.mark.needs_data
def test_a_parameter_of_a_project_type_is_judged_without_the_project(tmp_path):
    """The file does not see the element, and it needs not: only the empty value of the type is judged."""
    body = "    знч Первая = Задача ?? Неопределено\n    знч Вторая = Пустая ?? Неопределено\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Задача: Задачи.Ссылка, Пустая: Задачи.Ссылка?")}, GUARD)
    assert [d.line for d in found] == [2]


@pytest.mark.needs_data
def test_a_member_of_a_bare_type_name_is_left_to_the_project(tmp_path):
    """A name the module does not declare may be an object of the project as well as a type of the
    platform, and the file cannot tell which: the static member stays unjudged."""
    body = "    знч Ключ = Ууид.Случайный() ?? Ууид.Случайный()\n"
    assert _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD) == []


@pytest.mark.needs_data
def test_an_element_of_a_typed_array_is_never_empty(tmp_path):
    """The index of `Массив<Строка>` reads the argument of the array, the way the cast rules read it."""
    body = '    знч Первый = Строки[0] ?? ""\n    знч Второй = Пустые[0] ?? ""\n'
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Строки: Массив<Строка>, Пустые: Массив<Строка?>")}, GUARD)
    assert [d.line for d in found] == [2]


@pytest.mark.needs_data
def test_an_untyped_lambda_parameter_stays_unknown(tmp_path):
    body = "    знч Отобранные = Строки.Фильтровать(Э -> (Э ?? \"\") == \"а\")\n"
    assert _run(tmp_path, {"Модуль.xbsl": _module(body, "Строки: Массив<Строка>")}, GUARD) == []


@pytest.mark.needs_data
def test_a_module_that_does_not_parse_is_left_to_the_parser(tmp_path):
    body = '    пер Имя: Строка = "а"\n    знч Итог = Имя ?? ""\n    если (\n'
    assert _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD) == []


@pytest.mark.needs_data
def test_an_english_module_is_judged_like_a_russian_one(tmp_path):
    module = 'method Check(Text: String, Empty: String?)\n    val First = Text ?? ""\n    val Second = Empty ?? ""\n;\n'
    found = _run(tmp_path, {"Module.xbsl": module}, GUARD)
    assert [d.line for d in found] == [2]


# --- the fix -----------------------------------------------------------------------------------


def _fixed(tmp_path: Path, name: str, found: list) -> str:
    """The text of the file on disk with the fixes applied - offsets index the file, not a string."""
    text = (tmp_path / name).read_bytes().decode("utf-8")
    for edit in sorted((d.fix for d in found if d.fix is not None), key=lambda e: -e.start):
        text = text[: edit.start] + edit.new + text[edit.end:]
    return text


@pytest.mark.needs_data
def test_the_fix_removes_the_default(tmp_path):
    body = '    пер Имя: Строка = "а"\n    знч Итог = (Имя) ?? ("")\n'
    found = _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD)
    assert _fixed(tmp_path, "Модуль.xbsl", found).splitlines()[2] == "    знч Итог = (Имя)"


@pytest.mark.needs_data
def test_a_default_that_widens_the_type_keeps_no_fix(tmp_path):
    """`Строка ?? 0` is a string or a number; a variable declared by it would change its type."""
    body = '    пер Имя: Строка = "а"\n    пер Итог = Имя ?? 0\n'
    found = _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD)
    assert len(found) == 1 and found[0].fix is None


@pytest.mark.needs_data
def test_a_default_with_a_comment_inside_keeps_no_fix(tmp_path):
    body = '    пер Имя: Строка = "а"\n    знч Итог = Имя ?? // запасное\n        ""\n'
    found = _run(tmp_path, {"Модуль.xbsl": _module(body)}, GUARD)
    assert len(found) == 1 and found[0].fix is None


@pytest.mark.needs_data
def test_the_fix_removes_the_insistent_operation(tmp_path):
    body = "    знч Длина = Текст!.Длина()\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Текст: Строка")}, GUARD)
    assert _fixed(tmp_path, "Модуль.xbsl", found).splitlines()[1] == "    знч Длина = Текст.Длина()"


@pytest.mark.needs_data
def test_the_safe_access_keeps_no_fix(tmp_path):
    """`Х?.Длина()` may be empty and `Х.Длина()` may not: a declaration by it would change its type."""
    found = _run(tmp_path, {"Модуль.xbsl": _module("    пер Длина = Текст?.Длина()\n", "Текст: Строка")}, GUARD)
    assert len(found) == 1 and found[0].fix is None


# --- code/redundant-type-check -----------------------------------------------------------------


@pytest.mark.needs_data
def test_a_check_the_declared_type_decides_is_found(tmp_path):
    body = ("    знч Первый = Номер это Число\n"
            "    знч Второй = Номер это не Число\n"
            "    знч Третий = Пустой это Число\n"
            "    знч Четвертый = Пустой это Число?\n"
            "    знч Пятый = Номер это Объект\n")
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Номер: Число, Пустой: Число?")}, CHECK)
    assert [d.line for d in found] == [2, 3, 5, 6]
    assert "ничего не проверяет" in found[0].message and "не выполняется никогда" in found[1].message


@pytest.mark.needs_data
def test_a_union_is_decided_only_when_all_of_it_fits(tmp_path):
    body = "    знч Первый = Значение это Строка\n    знч Второй = Значение это Строка|Число\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Значение: Строка|Число")}, CHECK)
    assert [d.line for d in found] == [3]


@pytest.mark.needs_data
def test_a_generic_type_fits_its_base_with_the_same_argument(tmp_path):
    body = ("    знч Первый = Строки это ЧитаемыйМассив<Строка>\n"
            "    знч Второй = Строки это ЧитаемыйМассив<Число>\n")
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Строки: Массив<Строка>")}, CHECK)
    assert [d.line for d in found] == [2]


@pytest.mark.needs_data
def test_the_predicate_form_of_a_case_reads_the_subject(tmp_path):
    body = "    выбор Номер\n        когда это Число\n            возврат\n    ;\n"
    found = _run(tmp_path, {"Модуль.xbsl": _module(body, "Номер: Число")}, CHECK)
    assert [d.line for d in found] == [3]


_GOODS = """ВидЭлемента: Справочник
Имя: Товары
Реквизиты:
    -
        Имя: Цена
        Тип: Число
    -
        Имя: Артикул
        Тип: Строка?
    -
        Имя: Аналог
        Тип: Товары.Ссылка?
ТабличныеЧасти:
    -
        Имя: Состав
        Реквизиты:
            -
                Имя: Товар
                Тип: Товары.Ссылка?
            -
                Имя: Количество
                Тип: Число
"""

_QUERY_MODULE = """метод Проверка()
    знч Выборка = Запрос{
        ВЫБРАТЬ
            Т.Цена КАК Цена,
            Т.Аналог.Цена КАК ЦенаАналога,
            Т.Аналог.Цена.ЗаменитьNull(0) КАК Замена,
            Т2.Цена КАК ЦенаСоседа,
            Т.Артикул КАК Артикул
        ИЗ Товары КАК Т
            ЛЕВОЕ СОЕДИНЕНИЕ Товары КАК Т2
                ПО Т2.Ссылка == Т.Аналог
        ОБЪЕДИНИТЬ ВСЕ
        ВЫБРАТЬ
            С.Количество,
            С.Товар.Цена,
            С.Товар.Цена.ЗаменитьNull(0),
            С.Количество,
            С.Товар.Артикул
        ИЗ Товары.Состав КАК С
    }.Выполнить()
    для Запись из Выборка
        знч Первый = Запись.Цена это Число
        знч Второй = Запись.ЦенаАналога это Число
        знч Третий = Запись.Замена это Число
        знч Четвертый = Запись.ЦенаСоседа это Число
        знч Пятый = Запись.Артикул это Строка
    ;
;
"""


@pytest.mark.needs_data
def test_a_query_column_is_typed_by_the_fields_of_the_project(tmp_path):
    """A field through a reference and a field of a left-joined table may be Null; a null
    replacement by a number is a number in both parts of the union."""
    found = _run(tmp_path, {"Товары.yaml": _GOODS, "Отчет.xbsl": _QUERY_MODULE}, CHECK)
    assert [d.line for d in found] == [22, 24]


_COMPUTED_COLUMNS = """метод Проверка()
    для Запись из Запрос{
        ВЫБРАТЬ
            ВЫБОР КОГДА Т.Цена > 0 ТОГДА 1 ИНАЧЕ 0 КОНЕЦ КАК Знак,
            Т.Цена + 1 КАК Следующая
        ИЗ Товары КАК Т
    }.Выполнить()
        знч Первый = Запись.Знак это Число
        знч Второй = Запись.Следующая это Число
    ;
    для Итог из Запрос{
        ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК Всего, МАКСИМУМ(Т.Цена) КАК Наибольшая
        ИЗ Товары КАК Т
    }.Выполнить()
        знч Третий = Итог.Всего это Число
        знч Четвертый = Итог.Наибольшая это Число
    ;
;
"""


@pytest.mark.needs_data
def test_a_computed_query_column_is_typed_like_the_cast_rules_type_it(tmp_path):
    """A choice over numbers, arithmetic and a count are numbers; the maximum over no rows is Null."""
    found = _run(tmp_path, {"Товары.yaml": _GOODS, "Отчет.xbsl": _COMPUTED_COLUMNS}, CHECK)
    assert [d.line for d in found] == [8, 9, 15]


@pytest.mark.needs_data
def test_a_query_over_an_object_the_project_names_twice_is_left_alone(tmp_path):
    files = {"Товары.yaml": _GOODS, "Второе/Товары.yaml": _GOODS, "Отчет.xbsl": _QUERY_MODULE}
    assert _run(tmp_path, files, CHECK) == []


@pytest.mark.needs_data
def test_a_query_without_the_object_yaml_is_left_alone(tmp_path):
    assert _run(tmp_path, {"Отчет.xbsl": _QUERY_MODULE}, CHECK) == []


@pytest.mark.needs_data
def test_a_batch_query_is_left_alone(tmp_path):
    module = _QUERY_MODULE.replace("        ОБЪЕДИНИТЬ ВСЕ\n", "        ;\n")
    found = _run(tmp_path, {"Товары.yaml": _GOODS, "Отчет.xbsl": module}, CHECK)
    assert found == []
