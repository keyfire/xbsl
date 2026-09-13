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
from xbsl.rules import _typesets as T
from xbsl.rules import _querytypes as Q

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


def test_the_signature_reader_counts_optional_and_variadic_parameters():
    fewest, most, result, generic = T._signature('Найти(Строка: Строка, От: Число = 0): Число?')
    assert (fewest, most, result, generic) == (1, 2, "Число?", False)
    assert T._signature("Шаблон(Шаблон: Строка, ...Аргументы: Объект?): Строка")[:2] == (1, 10_000)
    assert T._signature("Очистить()")[2] is None


def test_a_default_with_a_comma_inside_quotes_is_one_parameter():
    shape = T._signature('Соединить(Разделитель: Строка = ", ", Хвост: Булево = Ложь): Строка')
    assert shape[:2] == (0, 2)


def test_a_generic_method_is_marked_generic():
    shape = T._signature("ПервыйИлиУмолчание<ТипУмолчания>(Умолчание: ТипЭлемента|ТипУмолчания): "
                         "ТипЭлемента|ТипУмолчания")
    assert shape[3] is True


def test_the_display_of_a_set_writes_the_empty_value_the_source_way():
    assert T.TypeSet(frozenset({"Строка"}), True).display() == "Строка?"
    assert T.TypeSet(frozenset({"Строка", "Число"}), True).display() == "Строка|Число|?"
    assert T.TypeSet(frozenset({"Строка", "Число"})).key() == "Строка|Число"


# --- the written types ------------------------------------------------------------------------


@pytest.mark.needs_data
def test_written_types_read_as_sets_in_either_language():
    assert T.parse_type("Строка|Число|?") == T.TypeSet(frozenset({"Строка", "Число"}), True)
    assert T.parse_type("Строка|Число?") == T.TypeSet(frozenset({"Строка", "Число"}), True)
    assert T.parse_type("String?") == T.parse_type("Строка?")
    assert T.parse_type("Массив<Строка?>") == T.single("Массив<Строка|?>")


@pytest.mark.needs_data
def test_a_type_the_reader_cannot_compare_answers_nothing():
    assert T.parse_type("неизвестно") is None
    assert T.parse_type("()->ничто") is None
    assert T.parse_type("Основное::Задачи.Ссылка") is None


@pytest.mark.needs_data
def test_a_member_of_a_generic_type_is_typed_by_the_argument():
    assert T.member_result("СобытиеПриИзменении<Строка>", "НовоеЗначение", None) == T.single("Строка")
    got = T.member_result("СобытиеПриИзменении<Строка|?>", "НовоеЗначение", None)
    assert got == T.TypeSet(frozenset({"Строка"}), True)
    # A raw receiver binds nothing, and a member typed by the parameter is unknown.
    assert T.member_result("СобытиеПриИзменении", "НовоеЗначение", None) is None


@pytest.mark.needs_data
def test_overloads_that_disagree_about_the_result_give_no_type():
    """The zero-argument overload of the documentation yields the empty value, the others do not."""
    assert T.member_result("Массив<Строка>", "ПервыйИлиУмолчание", 0) == T.TypeSet(frozenset({"Строка"}), True)
    assert T.member_result("Массив<Строка>", "ПервыйИлиУмолчание", 1) is None


_VERSIONED_BLOCK = (
    '<h3 id="таблица">Таблица</h3> <p><code>Версия 8.0 и выше</code></p>'
    " <pre><code>Таблица: ОтражениеТаблицы?</code></pre> <hr>\n"
    '<h3 id="таблица-1"><del>Таблица</del></h3> <p><code>Версия 7.0 и ниже</code></p>'
    " <pre><code>Таблица: ОтражениеТаблицы</code></pre> <hr>"
)


def test_a_property_the_page_prints_nullable_in_its_current_form_is_not_trusted(monkeypatch):
    """The catalog folded both versions into the bare head; the current form admits the empty value."""
    from xbsl import docs

    T._documented_types.cache_clear()
    monkeypatch.setattr(docs, "available", lambda version=None: True)
    monkeypatch.setattr(docs, "member_doc", lambda name, version=None: {"block": _VERSIONED_BLOCK})
    try:
        assert T._documented_types("Отражение", "Таблица") == ("ОтражениеТаблицы?",)
        assert T._documented_alike("Отражение", "Таблица") is False
    finally:
        T._documented_types.cache_clear()


def test_a_property_documented_plain_in_every_form_is_trusted(monkeypatch):
    from xbsl import docs

    T._documented_types.cache_clear()
    block = '<h3 id="имя">Имя</h3> <pre><code>Имя: Строка</code></pre> <hr>'
    monkeypatch.setattr(docs, "available", lambda version=None: True)
    monkeypatch.setattr(docs, "member_doc", lambda name, version=None: {"block": block})
    try:
        assert T._documented_alike("Задачи", "Имя") is True
    finally:
        T._documented_types.cache_clear()


@pytest.mark.needs_data
def test_a_property_folded_from_two_versions_is_left_untyped():
    """The page prints the main table of a reflection nullable for the current platform and plain for
    an old one; the catalog kept the plain head, the documentation check keeps the member untyped."""
    from xbsl import docs

    if not docs.available():
        pytest.skip("the documentation database is not installed")
    assert T.member_result("ОтражениеЭлементаПроектаСТаблицами", "ОсновнаяТаблица", None) is None


@pytest.mark.needs_data
def test_a_disputed_property_is_left_untyped_while_the_data_still_calls_it_plain():
    """The entry is evidence from the editor; once the data admits the empty value it is redundant."""
    from xbsl import dataset

    for owner, member in T._DISPUTED_PROPERTIES:
        written = (dataset.load_json("stdlib.json")["member_types"].get(owner) or {}).get(member)
        got = T.parse_type(written)
        assert got is not None and not got.undefined, f"{owner}.{member} is no longer plain - drop it"
        assert T.member_result(owner, member, None) is None


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


def test_the_column_reader_answers_nothing_for_an_expression_it_does_not_know():
    """Plain data in, plain data out: the shapes travel from a worker to the reduce phase."""
    fields = {"товары": {"цена": "Число"}}
    assert Q.resolve([["lit", "Число"], ["lit", "Число"]], fields.get) is not None
    assert Q.resolve([["chain", "Нет", False, ["Цена"], None]], fields.get) is None
