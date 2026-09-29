"""yaml/union-needs-nullable: a union type without the empty value has no default.

The shapes are the ones live probes settled: the compiler rejected a union with no empty
member on an attribute of a catalog and of its tabular section, on a dimension and a resource
of an information register, on a field of a structure and of a storable structure, on a
constant, on a property of an interface component and on a property of an entity contract
("Default value initialization is not supported for types ..."), and applied the same union
with `|?`, with `DefaultValue` next to the type, on a required structure field, on a parameter
of a global client event and of a virtual table and on a property of a type contract. A write
or delete parameter, a report query parameter and an input field around a union fail with
messages of their own, and the rule quotes each; a write or delete parameter fails with a
single type too.

The rule needs no Element data, so the tests live outside test_rules and run in the public CI
(the English spelling of a description needs the platform dictionary and is marked).
"""

import pytest

from xbsl import engine

_RULE = "yaml/union-needs-nullable"
_HEAD = "ВидЭлемента: Справочник\nИд: 11111111-1111-1111-1111-111111111111\nИмя: Товары\n"


def _lint(text: str, name: str = "Товары.yaml"):
    return engine.run_sources([engine.load_text(name, text)], select={_RULE})


def _attribute(type_line: str, extra: str = "") -> str:
    return (_HEAD + "Реквизиты:\n    -\n        Ид: 22222222-2222-2222-2222-222222222222\n"
            f"        Имя: Значение\n        Тип: {type_line}\n" + extra)


def test_union_without_empty_member_is_flagged_with_a_fix():
    text = _attribute("Строка|Число")
    d = _lint(text)
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (8, 14)
    assert "'Строка|Число|?'" in d[0].message
    assert "ЗначениеПоУмолчанию" in d[0].message
    fix = d[0].fix
    assert fix is not None
    fixed = text[:fix.start] + fix.new + text[fix.end:]
    assert "Тип: Строка|Число|?\n" in fixed
    assert _lint(fixed) == []


def test_union_in_a_tabular_section_a_register_and_a_component():
    tabular = (_HEAD + "ТабличныеЧасти:\n    -\n        Ид: 33333333-3333-3333-3333-333333333333\n"
               "        Имя: Строки\n        Реквизиты:\n            -\n"
               "                Ид: 44444444-4444-4444-4444-444444444444\n"
               "                Имя: Отметка\n                Тип: Число|Булево\n")
    assert [(x.line, x.col) for x in _lint(tabular)] == [(12, 22)]
    register = ("ВидЭлемента: РегистрСведений\nИд: 11111111-1111-1111-1111-111111111111\n"
                "Имя: Курсы\nИзмерения:\n    -\n        Ид: 22222222-2222-2222-2222-222222222222\n"
                "        Имя: Ключ\n        Тип: Число|Булево\n")
    assert len(_lint(register, "Курсы.yaml")) == 1
    component = ("ВидЭлемента: КомпонентИнтерфейса\nИд: 11111111-1111-1111-1111-111111111111\n"
                 "Имя: Панель\nНаследует:\n    Тип: Группа\nСвойства:\n    -\n"
                 "        Имя: Значение\n        Тип: Строка|Число\n")
    assert len(_lint(component, "Панель.yaml")) == 1


def test_contract_property_is_advised_the_empty_member_only():
    # A property of an entity contract has no default-value key: the empty member is the
    # only way out, and the message does not send the author looking for another.
    text = ("ВидЭлемента: КонтрактСущности\nИд: 11111111-1111-1111-1111-111111111111\n"
            "Имя: КонтрактЦены\nСвойства:\n    -\n        Ид: 22222222-2222-2222-2222-222222222222\n"
            "        Имя: Значение\n        Тип: Строка|Булево\n")
    d = _lint(text, "КонтрактЦены.yaml")
    assert len(d) == 1
    assert "'Строка|Булево|?'" in d[0].message and "ЗначениеПоУмолчанию" not in d[0].message


def test_positions_that_compile_are_silent():
    # The negative controls of the probe - every one of them applied cleanly.
    assert _lint(_attribute("Строка|Число|?")) == []
    assert _lint(_attribute("Строка?|Число")) == []
    assert _lint(_attribute("Строка|Неопределено")) == []
    assert _lint(_attribute("Строка|Число", "        ЗначениеПоУмолчанию: \"\"\n")) == []
    structure = ("ВидЭлемента: Структура\nИд: 11111111-1111-1111-1111-111111111111\n"
                 "Имя: Пакет\nПоля:\n    -\n        Имя: Значение\n        Тип: Строка|Число\n"
                 "        Обязательное: Истина\n")
    assert _lint(structure, "Пакет.yaml") == []
    event = ("ВидЭлемента: ГлобальноеКлиентскоеСобытие\nИд: 11111111-1111-1111-1111-111111111111\n"
             "Имя: Изменение\nПараметры:\n    -\n        Имя: Значение\n        Тип: Строка|Число\n")
    assert _lint(event, "Изменение.yaml") == []


def test_other_shapes_are_left_alone():
    # A single type is not a union; a reference member belongs to yaml/ref-needs-nullable;
    # a generic member and a typed literal are not judged.
    assert _lint(_attribute("Строка")) == []
    assert _lint(_attribute("Строка|Товары.Ссылка")) == []
    assert _lint(_attribute("Массив<Строка>|Число")) == []
    literal = (_HEAD + "Фильтр:\n    Значение:\n        Тип: Строка|Число\n        Значение: 1\n")
    assert _lint(literal) == []


def test_negative_control_the_same_union_without_the_guard_is_flagged():
    # The guard of the silent case above removed - the finding comes back.
    guarded = _attribute("Строка|Число", "        ЗначениеПоУмолчанию: \"\"\n")
    assert _lint(guarded) == []
    assert len(_lint(guarded.replace("        ЗначениеПоУмолчанию: \"\"\n", ""))) == 1


def test_quoted_union_is_flagged_without_a_fix():
    d = _lint(_attribute("\"Строка|Число\""))
    assert len(d) == 1 and d[0].fix is None
    assert (d[0].line, d[0].col) == (8, 15)


def test_storable_structure_field_and_constant_are_flagged():
    # Both failed in the probe with "Default value initialization is not supported ...".
    storable = ("ВидЭлемента: ХранимаяСтруктура\nИд: 11111111-1111-1111-1111-111111111111\n"
                "Имя: Адрес\nПоля:\n    -\n        Ид: 22222222-2222-2222-2222-222222222222\n"
                "        Имя: Значение\n        Тип: Строка|Число\n")
    assert len(_lint(storable, "Адрес.yaml")) == 1
    constants = ("ВидЭлемента: НаборКонстант\nИд: 11111111-1111-1111-1111-111111111111\n"
                 "Имя: Настройки\nКонстанты:\n    -\n"
                 "        Ид: 22222222-2222-2222-2222-222222222222\n"
                 "        Имя: Значение\n        Тип: Строка|Число\n")
    assert len(_lint(constants, "Настройки.yaml")) == 1


def test_a_type_contract_property_compiles_as_a_union():
    # The probe applied a type contract with a `String|Number` property - it only declares what
    # the implementing element stores - while an unknown type next to it was refused, so the
    # file was read. The entity contract above is the control: the same union fails there.
    text = ("ВидЭлемента: КонтрактТипа\nИд: 11111111-1111-1111-1111-111111111111\n"
            "Имя: Отмечаемое\nОкружение: Сервер\nСвойства:\n    -\n"
            "        Имя: Значение\n        Тип: Строка|Число\n")
    assert _lint(text, "Отмечаемое.yaml") == []
    entity = text.replace("КонтрактТипа", "КонтрактСущности").replace("Окружение: Сервер\n", "")
    assert len(_lint(entity, "Отмечаемое.yaml")) == 1


def test_a_virtual_table_parameter_compiles_as_a_union():
    # The value comes from whoever reads the table: the probe applied it without a default.
    text = ("ВидЭлемента: ВиртуальнаяТаблица\nИд: 11111111-1111-1111-1111-111111111111\n"
            "Имя: Остатки\nПараметры:\n    -\n        Имя: Отбор\n        Тип: Строка|Число\n")
    assert _lint(text, "Остатки.yaml") == []


def _operations(write: str, delete: str) -> str:
    return (_HEAD + "ПараметрыЗаписи:\n    -\n        Имя: Признак\n"
            f"        Тип: {write}\nПараметрыУдаления:\n    -\n        Имя: Режим\n"
            f"        Тип: {delete}\n")


def test_write_and_delete_parameters_quote_their_own_refusal():
    # The probe: "The type composition of parameter ... must contain "Undefined" type". There is
    # no default key for such a parameter, so the message does not advise one.
    d = _lint(_operations("Строка|Число", "Число|Булево"))
    assert [(x.line, x.col) for x in d] == [(7, 14), (11, 14)]
    for x in d:
        assert "must contain" in x.message and "ЗначениеПоУмолчанию" not in x.message
    fixed = _operations("Строка|Число|?", "Число|Булево|?")
    assert _lint(fixed) == []


def test_a_single_type_of_an_operation_parameter_is_flagged_with_a_fix():
    # The second probe: `Boolean` and `Number` alone got the same refusal - the composition of
    # such a parameter must hold the empty value even with one type in it.
    text = _operations("Булево", "Число")
    d = _lint(text)
    assert [(x.line, x.col) for x in d] == [(7, 14), (11, 14)]
    assert "must contain" in d[0].message and "'Булево?'" in d[0].message
    assert "'Число?'" in d[1].message
    for x in d:
        assert "ЗначениеПоУмолчанию" not in x.message
    fixed = text
    for x in sorted(d, key=lambda x: x.fix.start, reverse=True):
        fixed = fixed[:x.fix.start] + x.fix.new + fixed[x.fix.end:]
    assert "Тип: Булево?\n" in fixed and "Тип: Число?\n" in fixed
    assert _lint(fixed) == []


def test_a_single_type_outside_the_operation_sections_is_left_alone():
    # The negative control: the same `Boolean` as an attribute has a default value of its own,
    # and the finding appears only once the type moves into the operation section.
    assert _lint(_attribute("Булево")) == []
    assert len(_lint(_operations("Булево", "Число|?"))) == 1


def test_operation_parameters_that_compile_or_belong_to_the_siblings_are_left_alone():
    # The empty value in any spelling passes; a single reference is reported by
    # yaml/ref-needs-nullable, and a generic or a qualified name is not judged.
    for value in ("Булево?", "Неопределено", "Товары.Ссылка", "Массив<Строка>",
                  "Кладовая::Пополняемое"):
        assert _lint(_operations(value, "Число?")) == [], value


def test_a_quoted_single_type_of_an_operation_parameter_is_flagged_without_a_fix():
    d = _lint(_operations("\"Булево\"", "Число?"))
    assert len(d) == 1 and d[0].fix is None and (d[0].line, d[0].col) == (7, 15)


_ENUM = ("ВидЭлемента: Перечисление\nИд: 33333333-3333-3333-3333-333333333333\n"
         "Имя: ВидПометки\nЭлементы:\n    -\n        Имя: Важная\n    -\n        Имя: Обычная\n")


def _with_enum(text: str, rules: set[str]):
    sources = [engine.load_text("ВидПометки.yaml", _ENUM), engine.load_text("Товары.yaml", text)]
    return [(x.rule_id, x.line, x.col)
            for x in engine.run_sources(sources, select=rules)]


def test_an_enumeration_in_an_operation_parameter_is_reported_once():
    # yaml/enum-needs-nullable leaves the write and delete parameters to this rule, which quotes
    # the refusal of the section; the same enumeration as an attribute of the file stays its.
    text = _attribute("ВидПометки") + (
        "ПараметрыУдаления:\n    -\n        Имя: Режим\n        Тип: \"ВидПометки\"\n")
    both = {_RULE, "yaml/enum-needs-nullable"}
    assert _with_enum(text, both) == [(_RULE, 12, 15), ("yaml/enum-needs-nullable", 8, 14)]


def test_negative_control_the_same_item_outside_the_operation_section():
    # The section key alone makes the difference: under an ordinary list the enumeration rule
    # judges the item, and this rule leaves the single type alone.
    item = "    -\n        Имя: Режим\n        Тип: ВидПометки\n"
    both = {_RULE, "yaml/enum-needs-nullable"}
    assert _with_enum(_HEAD + "ПараметрыЗаписи:\n" + item, both) == [(_RULE, 7, 14)]
    listed = _with_enum(_HEAD + "Реквизиты:\n" + item, both)
    assert listed == [("yaml/enum-needs-nullable", 7, 14)]


@pytest.mark.needs_data
def test_an_english_write_parameter_is_advised_in_its_own_spelling():
    # An English description is read as an element only with the platform dictionary.
    text = ("ElementKind: Catalog\nId: 11111111-1111-1111-1111-111111111111\nName: Goods\n"
            "WriteParameters:\n    -\n        Name: Mark\n        Type: Boolean\n")
    d = _lint(text, "Goods.yaml")
    assert len(d) == 1 and "'Boolean?'" in d[0].message and (d[0].line, d[0].col) == (7, 15)
    fixed = text[:d[0].fix.start] + d[0].fix.new + text[d[0].fix.end:]
    assert "Type: Boolean?\n" in fixed and _lint(fixed, "Goods.yaml") == []


def _report(param: str) -> str:
    return ("ВидЭлемента: Отчет\nИд: 11111111-1111-1111-1111-111111111111\nИмя: Остатки\n"
            "ВидИсточникаДанных: Запрос\nПараметрыЗапроса:\n    -\n        Имя: Отбор\n"
            + "".join(f"        {line}\n" for line in param.split("\n")))


def test_a_report_query_parameter_quotes_its_own_refusal():
    # The probe: "Не указано значение по умолчанию для параметра". The default key is there for
    # a report parameter, and with it the same union compiled.
    d = _lint(_report("Тип: Строка|Число"), "Остатки.yaml")
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 14)
    assert "Не указано значение по умолчанию" in d[0].message
    assert "ЗначениеПоУмолчанию" in d[0].message
    assert _lint(_report("Тип: Строка|Число\nЗначениеПоУмолчанию: \"а\""), "Остатки.yaml") == []
    assert _lint(_report("Тип: Строка|Число|?"), "Остатки.yaml") == []


def _field(type_line: str, extra: str = "") -> str:
    return ("ВидЭлемента: КомпонентИнтерфейса\nИд: 11111111-1111-1111-1111-111111111111\n"
            "Имя: Панель\nНаследует:\n    Тип: Группа\n    Содержимое:\n        -\n"
            f"            Тип: {type_line}\n            Имя: Поле\n" + extra)


def test_an_input_field_around_a_union_is_flagged_with_a_fix():
    # The probe: "Parameter ... of type ... must have a default value" - and the same with a
    # value bound to the field.
    text = _field("ПолеВвода<Строка|Число>")
    d = _lint(text, "Панель.yaml")
    assert len(d) == 1 and (d[0].line, d[0].col) == (8, 28)
    assert "'ПолеВвода<Строка|Число|?>'" in d[0].message
    fixed = text[:d[0].fix.start] + d[0].fix.new + text[d[0].fix.end:]
    assert "Тип: ПолеВвода<Строка|Число|?>\n" in fixed and _lint(fixed, "Панель.yaml") == []
    bound = _field("ПолеВвода<Строка|Число>", "            Значение: 5\n")
    assert len(_lint(bound, "Панель.yaml")) == 1


def test_input_fields_that_compile_or_belong_to_the_sibling_are_left_alone():
    assert _lint(_field("ПолеВвода<Строка|Число|?>"), "Панель.yaml") == []
    assert _lint(_field("ПолеВвода<Строка>"), "Панель.yaml") == []
    assert _lint(_field("ПолеВвода<Товары.Ссылка|Строка>"), "Панель.yaml") == []


@pytest.mark.needs_data
def test_an_english_input_field_keeps_its_spelling():
    # An English description is read as an element only with the platform dictionary.
    text = ("ElementKind: UiComponent\nId: 11111111-1111-1111-1111-111111111111\nName: Panel\n"
            "Inherits:\n    Type: Group\n    Content:\n        -\n"
            "            Type: Edit<String|Number>\n            Name: Field\n")
    d = _lint(text, "Panel.yaml")
    assert len(d) == 1 and "'Edit<String|Number|?>'" in d[0].message
