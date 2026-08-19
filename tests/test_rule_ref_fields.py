"""The code/ref-field-needs-req rule: a structure ref field without 'обз', '?' or an initializer.

Covered are both firing on the "bad" examples (a real pitfall: apply fails with
"cannot be initialized with a default value") and silence on all the correct forms and
deliberate narrowings (unions, generics, local method variables).

The rule is token-based, but the lexer needs the language data (language.json) - without
the generated data the module is skipped, like the other token-based tests (see conftest.py).
"""

import pytest

from xbsl import dataset, engine

pytestmark = pytest.mark.skipif(
    not dataset.available_versions(),
    reason="нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
)

RULE = "code/ref-field-needs-req"


def _lint(content, name="М.xbsl"):
    return engine.run_sources([engine.load_text(name, content)], select={RULE})


def _clean(content, name="М.xbsl"):
    return _lint(content, name) == []


# --- Findings --------------------------------------------------------------------------

def test_ref_field_without_req_flagged():
    d = _lint("структура Шапка\n    пер Ссылка: Товары.Ссылка\n;\n")
    assert len(d) == 1
    assert d[0].line == 2 and d[0].col == 9
    assert d[0].severity.value == "error"
    assert "обз пер Ссылка: Товары.Ссылка" in d[0].message


def test_val_ref_field_flagged():
    d = _lint("структура Шапка\n    знч Владелец: Склады.Ссылка\n;\n")
    assert len(d) == 1 and "обз знч Владелец: Склады.Ссылка" in d[0].message


def test_ns_qualified_ref_flagged():
    # a type with an NS prefix is also a direct ref field
    d = _lint("структура Шапка\n    пер Товар: Справочник.Товары.Ссылка\n;\n")
    assert len(d) == 1 and "Справочник.Товары.Ссылка" in d[0].message


def test_two_names_shared_type_flagged_each():
    d = _lint("структура Шапка\n    пер Первый, Второй: Товары.Ссылка\n;\n")
    assert [x.message.split("'")[1] for x in d] == ["Первый", "Второй"]


def test_second_structure_after_method_with_query_flagged():
    # a ';' inside Запрос{} does not break the block balance - the field after the method is found
    content = (
        "структура А\n"
        "    пер Имя: Строка\n"
        "\n"
        "    метод Ф(): Число\n"
        "        знч Р = Запрос{\n"
        "            ВЫБРАТЬ 1; ВЫБРАТЬ 2\n"
        "        }.Выполнить()\n"
        "        если Р.Пусто()\n"
        "            возврат 0\n"
        "        иначе если Истина\n"
        "            возврат 1\n"
        "        ;\n"
        "        возврат 2\n"
        "    ;\n"
        "\n"
        "    пер Ссылка: Товары.Ссылка\n"
        ";\n"
    )
    d = _lint(content)
    assert len(d) == 1 and d[0].line == 16


# --- Correct forms - silence -----------------------------------------------------------

def test_req_field_ok():
    assert _clean("структура Шапка\n    обз пер Ссылка: Товары.Ссылка\n;\n")


def test_req_val_field_ok():
    assert _clean("структура Шапка\n    обз знч Ссылка: Товары.Ссылка\n;\n")


def test_nullable_field_ok():
    assert _clean("структура Шапка\n    пер Ссылка: Товары.Ссылка? = Неопределено\n;\n")


def test_nullable_without_initializer_ok():
    assert _clean("структура Шапка\n    пер Ссылка: Товары.Ссылка?\n;\n")


def test_initializer_ok():
    assert _clean("структура Шапка\n    пер Ссылка: Товары.Ссылка = НайтиТовар()\n;\n")


def test_non_ref_fields_ok():
    assert _clean(
        "структура Шапка\n"
        "    пер Название: Строка\n"
        "    пер Объект: Программа.Объект\n"
        ";\n"
    )


# --- Narrowings and non-fields - silence -----------------------------------------------

def test_union_type_skipped():
    assert _clean("структура Шапка\n    пер Ссылка: Товары.Ссылка|Акция.Ссылка\n;\n")


def test_union_with_nullable_skipped():
    assert _clean("структура Шапка\n    пер Ссылка: Товары.Ссылка|?\n;\n")


def test_generic_skipped():
    assert _clean("структура Шапка\n    пер Ссылки: Массив<Товары.Ссылка>\n;\n")


def test_bare_link_name_skipped():
    # a single-segment 'Ссылка' is a local type name, not a project object reference
    assert _clean("структура Шапка\n    пер Ссылка: Ссылка\n;\n")


def test_local_variable_in_method_ok():
    # a method variable is not a structure field, even with the same type
    assert _clean(
        "метод Ф()\n"
        "    пер Ссылка: Товары.Ссылка = НайтиТовар()\n"
        "    пер Другая: Товары.Ссылка\n"
        ";\n"
    )


def test_field_in_structure_method_ok():
    # a variable inside a structure method is not a field either
    assert _clean(
        "структура Шапка\n"
        "    пер Имя: Строка\n"
        "    метод Ф()\n"
        "        пер Ссылка: Товары.Ссылка\n"
        "    ;\n"
        ";\n"
    )


def test_yaml_source_ok():
    assert engine.run_sources(
        [engine.load_text("Ф.yaml", "Имя: Ф\n")], select={RULE},
    ) == []
