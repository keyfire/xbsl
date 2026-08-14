"""Checks of xbsl/typeinfer.py: the type of an expression, as far as the platform data allows.

The module answers None for everything it cannot name, so the tests state both halves: what it
does type, and what it deliberately leaves unknown.
"""

import pytest

from xbsl import dataset
from xbsl import parser as P
from xbsl import typeinfer as ti

if not dataset.available_versions():
    pytest.skip(
        "нет данных Элемента – сгенерируйте: python tools/extract.py --dist ...",
        allow_module_level=True,
    )


def _type_of(expression: str, env: ti.TypeEnv | None = None):
    module, errors = P.parse_text(f"метод Ф()\n    знч Х = {expression}\n;\n")
    assert not errors, [e.message for e in errors]
    return ti.expression_type(module.members[0].body[0].init, env or ti.TypeEnv({}))


def test_a_string_literal_types_itself():
    assert _type_of('"текст"') == ti.Inferred("Строка")


def test_a_number_and_a_boolean_literal():
    assert _type_of("42") == ti.Inferred("Число")
    assert _type_of("Истина") == ti.Inferred("Булево")


def test_the_empty_value_is_nullable():
    got = _type_of("Неопределено")
    assert got is not None and got.nullable


def test_a_variable_comes_from_the_environment():
    env = ti.TypeEnv({"Имя": ti.Inferred("Строка")})
    assert _type_of("Имя", env) == ti.Inferred("Строка")


def test_a_member_call_is_typed_by_the_catalog():
    env = ti.TypeEnv({"Имя": ti.Inferred("Строка")})
    assert _type_of("Имя.ВВерхнийРегистр()", env) == ti.Inferred("Строка")


def test_a_constructor_names_its_type():
    assert _type_of("новый Массив<Строка>()") == ti.Inferred("Массив")


def test_a_cast_names_its_type():
    env = ti.TypeEnv({"Значение": ti.Inferred("Объект")})
    assert _type_of("Значение как Число", env) == ti.Inferred("Число")


def test_the_non_null_operator_drops_the_empty_value():
    env = ti.TypeEnv({"Имя": ti.Inferred("Строка", nullable=True)})
    got = _type_of("Имя!", env)
    assert got == ti.Inferred("Строка") and not got.nullable


def test_the_coalescing_operator_answers_a_non_empty_type():
    env = ti.TypeEnv({"Имя": ti.Inferred("Строка", nullable=True)})
    got = _type_of('Имя ?? ""', env)
    assert got is not None and not got.nullable


def test_a_bare_type_name_is_read_as_the_type_only_when_allowed():
    assert _type_of("ДатаВремя") is None  # off by default: a form attribute may bear that name
    assert _type_of("ДатаВремя", ti.TypeEnv({}, type_names=True)) == ti.Inferred("ДатаВремя")


def test_a_shadowed_name_is_never_read_as_a_type():
    env = ti.TypeEnv({}, type_names=True, shadowed=frozenset({"ДатаВремя"}))
    assert _type_of("ДатаВремя", env) is None


def test_this_comes_from_the_environment():
    env = ti.TypeEnv({}, this_type=ti.Inferred("Форма"))
    assert _type_of("этот", env) == ti.Inferred("Форма")


def test_an_unknown_shape_stays_unknown():
    # arithmetic, a lambda and a call of another module are not typed - and must answer None
    # rather than a guess: a caller treats None as "do not judge".
    env = ti.TypeEnv({"А": ti.Inferred("Число")})
    assert _type_of("А + 1", env) is None
    assert _type_of("Модуль.Метод()", env) is None


def test_a_nominal_annotation_reads_the_nullable_marker():
    assert ti.nominal("Товары.Ссылка?") == ti.Inferred("Товары.Ссылка", True)
    assert ti.nominal("Массив<Строка>") == ti.Inferred("Массив")
    assert ti.nominal("Строка|Число") is None  # a union is not a nominal type


def test_an_inherited_member_resolves_through_the_base_chain():
    # a button inherits the presentation method from the object root - the catalog keeps it there
    assert ti.member_type("Кнопка", "Представление") == ti.Inferred("Строка")


# --- the two traps the corpora exposed ------------------------------------------------------


def _method(text: str):
    module, errors = P.parse_text(text)
    assert not errors, [e.message for e in errors]
    return module.members[0]


def test_a_declared_name_is_never_read_as_a_type():
    """`знч Список = ...` shadows the stdlib type of that name, even with no type of its own.

    A live module holds exactly this, and reading the name as the type answered "not nullable"
    for a value that plainly is - the shortcut has to lose to any declaration.
    """
    method = _method("метод Ф(Ключ: Строка)\n    пер Список = Соответствие.Получить(Ключ)\n"
                     "    возврат Список!\n;\n")
    env = ti.method_env(method, type_names=True)
    assert "Список" in env.shadowed and "Список" not in env.variables
    assert ti.expression_type(method.body[-1].value, env) is None


def test_a_parameter_of_a_loop_is_shadowed_too():
    method = _method("метод Ф(Данные: Массив<Строка>)\n    для Строка из Данные\n"
                     "        Сообщить(Строка)\n    ;\n;\n")
    env = ti.method_env(method, type_names=True)
    assert "Строка" in env.shadowed


def test_a_type_parameter_is_not_a_type():
    """The catalog states a generic member's result by the TYPE PARAMETER name.

    A data event answers with `DataType`, which is a variable, not a type - the answer
    depends on the argument the receiver was built with, so the module must say "unknown".
    """
    assert ti.member_type("СобытиеСДанными", "Данные") is None
    assert ti.member_type("Строка", "ВВерхнийРегистр") == ti.Inferred("Строка")
