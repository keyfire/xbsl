"""code/row-field-null over a query literal: a column that may hold Null sent where Null is refused.

Every shape here was put to the compiler of the platform on a probe project, and the verdicts are
the compiler's: a column read through a reference or from the joined side of an outer join,
passed to a structure field, a parameter, a variable or a result declared without Null, is
refused with `Incompatible types: type "Null" cannot be assigned`, a type that admits the empty
value included. The controls are the shapes it accepted: the null replacement in the query, a
direct field of the main table, a parameter of the root type, and `CASE` guarded by `IS NULL`.
"""

import pytest

from xbsl import engine, querytypes, typeinfer

pytestmark = pytest.mark.needs_data  # the module is parsed, the query row typed by the catalog

RULE = "code/row-field-null"

ASSIGNEES = """\
ВидЭлемента: Справочник
Ид: 5c7e2a10-0000-4000-8000-000000000001
Имя: Исполнители
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 5c7e2a10-0000-4000-8000-000000000002
        Имя: Разряд
        Тип: Число
    -
        Ид: 5c7e2a10-0000-4000-8000-000000000003
        Имя: Аватар
        Тип: ДвоичныйОбъект.Ссылка?
"""

TASKS = """\
ВидЭлемента: Справочник
Ид: 5c7e2a10-0000-4000-8000-000000000004
Имя: Задачи
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 5c7e2a10-0000-4000-8000-000000000005
        Имя: Исполнитель
        Тип: Исполнители.Ссылка?
"""

MODULE_YAML = """\
ВидЭлемента: ОбщийМодуль
Ид: 5c7e2a10-0000-4000-8000-000000000006
Имя: Сводки
ОбластьВидимости: ВПроекте
Окружение: Сервер
"""

OTHER_YAML = """\
ВидЭлемента: ОбщийМодуль
Ид: 5c7e2a10-0000-4000-8000-000000000007
Имя: Приемка
ОбластьВидимости: ВПроекте
Окружение: Сервер
"""

OTHER = "метод Принять(Разряд: Число)\n;\n"

HEAD = """\
структура Карточка
    пер Разряд: Число = 0
    пер Аватар: ДвоичныйОбъект.Ссылка? = Неопределено
;

метод Принять(Разряд: Число)
;

метод ПринятьЧтоУгодно(Значение: Объект?)
;

"""

QUERY = ("Запрос{ВЫБРАТЬ З.Исполнитель.Разряд КАК Разряд, З.Исполнитель.Аватар КАК Аватар "
         "ИЗ Задачи КАК З}")


def _lint(body: str) -> tuple[str, list]:
    module = HEAD + body
    files = {
        "Основное/Исполнители.yaml": ASSIGNEES,
        "Основное/Задачи.yaml": TASKS,
        "Основное/Сводки.yaml": MODULE_YAML,
        "Основное/Сводки.xbsl": module,
        "Основное/Приемка.yaml": OTHER_YAML,
        "Основное/Приемка.xbsl": OTHER,
    }
    sources = [engine.load_text(name, text) for name, text in files.items()]
    found = [d for d in engine.run_sources(sources, select={RULE}) if d.rule_id == RULE]
    return module, found


def _line(text: str, marker: str) -> int:
    return text[: text.index(marker)].count("\n") + 1


def test_a_column_through_a_reference_into_a_structure_field_is_reported():
    module, found = _lint(
        "метод Собрать()\n"
        f"    для Запись из {QUERY}.Выполнить()\n"
        "        знч К = новый Карточка(Разряд = Запись.Разряд)\n"
        "    ;\n"
        ";\n"
    )
    assert [d.line for d in found] == [_line(module, "новый Карточка")]
    message = found[0].message
    assert "З.Исполнитель.Разряд" in message and "Карточка" in message
    assert "ЗаменитьNull" in message


def test_a_type_that_admits_the_empty_value_refuses_null_too():
    # the compiler: type "Null" cannot be assigned to "ДвоичныйОбъект.Ссылка?"
    module, found = _lint(
        "метод Собрать()\n"
        f"    для Запись из {QUERY}.Выполнить()\n"
        "        знч К = новый Карточка(Аватар = Запись.Аватар)\n"
        "    ;\n"
        ";\n"
    )
    assert [d.line for d in found] == [_line(module, "новый Карточка")]


def test_the_null_replacement_in_the_query_silences_the_column():
    _module, found = _lint(
        "метод Собрать()\n"
        "    для Запись из Запрос{ВЫБРАТЬ З.Исполнитель.Разряд.ЗаменитьNull(0) КАК Разряд, "
        "З.Исполнитель.Аватар.ЗаменитьNull() КАК Аватар ИЗ Задачи КАК З}.Выполнить()\n"
        "        знч К = новый Карточка(Разряд = Запись.Разряд, Аватар = Запись.Аватар)\n"
        "    ;\n"
        ";\n"
    )
    assert found == []


def test_a_row_in_a_lambda_of_transform_is_typed_by_the_platform_signature():
    module, found = _lint(
        "метод Собрать(): Массив<Карточка>\n"
        f"    возврат {QUERY}.Выполнить()\n"
        "        .Преобразовать(Строка -> новый Карточка(Разряд = Строка.Разряд))\n"
        ";\n"
    )
    assert [d.line for d in found] == [_line(module, ".Преобразовать")]


def test_an_argument_a_result_and_typed_variables_are_judged():
    body = (
        "метод Собрать(): Число\n"
        "    пер Счет: Число = 0\n"
        "    пер К = новый Карточка()\n"
        f"    для Запись из {QUERY}.Выполнить()\n"
        "        Принять(Запись.Разряд)\n"
        "        Приемка.Принять(Разряд = Запись.Разряд)\n"
        "        Счет = Запись.Разряд\n"
        "        знч Последний: Число = Запись.Разряд\n"
        "        К.Разряд = Запись.Разряд\n"
        "        возврат Запись.Разряд\n"
        "    ;\n"
        "    возврат Счет\n"
        ";\n"
    )
    module, found = _lint(body)
    expected = [_line(module, marker) for marker in (
        "        Принять(Запись", "Приемка.Принять", "Счет = Запись", "знч Последний",
        "К.Разряд = ", "возврат Запись")]
    found.sort(key=lambda d: d.line)
    assert [d.line for d in found] == expected
    assert "параметр 'Разряд' метода 'Принять'" in found[0].message
    assert "результат метода 'Собрать'" in found[-1].message


def test_a_field_of_the_joined_side_of_an_outer_join_is_reported():
    module, found = _lint(
        "метод Собрать()\n"
        "    для Запись из Запрос{ВЫБРАТЬ И.Разряд КАК Разряд ИЗ Задачи КАК З "
        "ЛЕВОЕ СОЕДИНЕНИЕ Исполнители КАК И ПО И.Ссылка == З.Исполнитель}.Выполнить()\n"
        "        Принять(Запись.Разряд)\n"
        "    ;\n"
        ";\n"
    )
    assert [d.line for d in found] == [_line(module, "Принять(Запись")]
    assert "внешнего соединения" in found[0].message


def test_the_first_row_of_a_result_is_judged_after_the_assertion():
    module, found = _lint(
        "метод Собрать()\n"
        f"    знч Первая = {QUERY}.Выполнить().ПервыйИлиНеопределено()\n"
        "    если Первая != Неопределено\n"
        "        Принять(Первая!.Разряд)\n"
        "    ;\n"
        ";\n"
    )
    assert [d.line for d in found] == [_line(module, "Принять(Первая")]


@pytest.mark.parametrize("body", [
    # a computed column: the compiler narrows the guarded choice to a value without Null
    "метод Собрать()\n"
    "    для Запись из Запрос{ВЫБРАТЬ ВЫБОР КОГДА З.Исполнитель.Разряд ЕСТЬ NULL ТОГДА 0 "
    "ИНАЧЕ З.Исполнитель.Разряд КОНЕЦ КАК Разряд ИЗ Задачи КАК З}.Выполнить()\n"
    "        Принять(Запись.Разряд)\n"
    "    ;\n"
    ";\n",
    # a parameter of the root type takes Null
    "метод Собрать()\n"
    f"    для Запись из {QUERY}.Выполнить()\n"
    "        ПринятьЧтоУгодно(Запись.Разряд)\n"
    "    ;\n"
    ";\n",
    # a direct field of the main table is never Null
    "метод Собрать()\n"
    "    для Запись из Запрос{ВЫБРАТЬ И.Аватар КАК Аватар ИЗ Исполнители КАК И}.Выполнить()\n"
    "        знч К = новый Карточка(Аватар = Запись.Аватар)\n"
    "    ;\n"
    ";\n",
    # a local typed by its initializer: its type is inferred, not declared
    "метод Собрать()\n"
    "    пер Счет = 0\n"
    f"    для Запись из {QUERY}.Выполнить()\n"
    "        Счет = Запись.Разряд\n"
    "    ;\n"
    ";\n",
    # a union types a column by all its parts: its Null has no single origin
    "метод Собрать()\n"
    "    для Запись из Запрос{ВЫБРАТЬ З.Исполнитель.Разряд КАК Разряд ИЗ Задачи КАК З "
    "ОБЪЕДИНИТЬ ВСЕ ВЫБРАТЬ И.Разряд ИЗ Исполнители КАК И}.Выполнить()\n"
    "        Принять(Запись.Разряд)\n"
    "    ;\n"
    ";\n",
], ids=["guarded-choice", "root-type", "direct-field", "inferred-local", "union"])
def test_the_shapes_the_compiler_accepts_or_the_rule_cannot_read_are_silent(body):
    _module, found = _lint(body)
    assert found == [], [d.message for d in found]


def test_the_lambda_parameter_is_typed_only_where_the_scope_asks_for_it():
    """The rules of the casts and the guards judge their sites without the callback typing;
    only a scope built with `callbacks` gives an untyped lambda parameter a type."""
    from xbsl import parser as P

    text = ("метод Собрать(Список: Массив<Строка>)\n"
            "    знч Длины = Список.Преобразовать(Элемент -> Элемент.Длина())\n;\n")
    tree, errors = P.parse(engine.load_text("Сводки.xbsl", text))
    assert not errors
    method = tree.members[0]
    nodes = typeinfer.walk_nodes(method.body)
    plain = typeinfer._MethodScope(method, nodes)
    typed = typeinfer._MethodScope(method, nodes, callbacks=True)
    assert [entry.kind for entry in plain.entries["Элемент"]] == ["written"]
    assert [entry.kind for entry in typed.entries["Элемент"]] == ["callback"]


def test_a_callback_parameter_is_read_off_the_printed_signature():
    catalog = typeinfer.ProjectCatalog({}, {})
    string, number = typeinfer.TypeSet.of("Строка"), typeinfer.TypeSet.of("Число")
    assert catalog.callback_parameter("Массив<Строка>", "Преобразовать", 0, 1, 0) == string
    # the overload of two parameters hands the index first
    assert catalog.callback_parameter("Массив<Строка>", "Преобразовать", 0, 2, 0) == number
    assert catalog.callback_parameter("Массив<Строка>", "Фильтровать", 0, 2, 1) == string
    # a parameter the method binds itself (the accumulator of a fold) stays unknown
    assert catalog.callback_parameter("Массив<Строка>", "Свернуть", 1, 2, 0) is None
    # no function parameter of that arity, no such member
    assert catalog.callback_parameter("Массив<Строка>", "Преобразовать", 0, 3, 0) is None
    assert catalog.callback_parameter("Массив<Строка>", "НетТакогоМетода", 0, 1, 0) is None


def test_the_origin_of_null_is_recorded_for_plain_paths_only():
    catalog = typeinfer.ProjectCatalog({
        "Задачи": {"kind": "Справочник", "attributes": {"Исполнитель": "Исполнители.Ссылка?"}},
        "Исполнители": {"kind": "Справочник", "attributes": {"Разряд": "Число"}},
    }, {})
    scope = typeinfer.ModuleScope("Сводки", "", catalog)

    def origins(text: str) -> dict:
        found: dict = {}
        assert querytypes.row_columns(text, scope, None, found) is not None
        return found

    assert origins("Запрос{ВЫБРАТЬ З.Исполнитель.Разряд КАК Р ИЗ Задачи КАК З}") == {
        "Р": querytypes.NullOrigin("reference", "З.Исполнитель.Разряд")}
    assert origins("Запрос{ВЫБРАТЬ И.Разряд КАК Р ИЗ Задачи КАК З ЛЕВОЕ СОЕДИНЕНИЕ "
                   "Исполнители КАК И ПО И.Ссылка == З.Исполнитель}") == {
        "Р": querytypes.NullOrigin("outer", "И.Разряд")}
    assert origins("Запрос{ВЫБРАТЬ З.Исполнитель.Разряд.ЗаменитьNull(0) КАК Р ИЗ Задачи КАК З}") == {}
    assert origins("Запрос{ВЫБРАТЬ ВЫБОР КОГДА З.Исполнитель.Разряд ЕСТЬ NULL ТОГДА 0 "
                   "ИНАЧЕ З.Исполнитель.Разряд КОНЕЦ КАК Р ИЗ Задачи КАК З}") == {}
    assert origins("Запрос{ВЫБРАТЬ З.Исполнитель.Разряд КАК Р ИЗ Задачи КАК З "
                   "ОБЪЕДИНИТЬ ВЫБРАТЬ И.Разряд ИЗ Исполнители КАК И}") == {}
