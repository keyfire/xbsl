"""code/module-var-not-const: only a constant may stand at module level.

The compiler answered "Выражения запрещено использовать вне тела метода" to a `знч` above
the methods, and the documentation states the other half - a constant is the module-level
declaration (topics/variable-declaration-statement).

The rule parses the module, so the tests need the Element data (see conftest).
"""

from xbsl import engine

RULE = "code/module-var-not-const"


def _lint(content: str):
    return engine.run_sources([engine.load_text("Модуль.xbsl", content)], select={RULE})


def test_value_above_the_methods_is_reported():
    d = _lint(
        "знч ИМЯ = \"значение\"\n"
        "\n"
        "метод Сделать()\n"
        ";\n"
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (1, 1)
    assert "знч ИМЯ" in d[0].message and "конст" in d[0].message


def test_a_constant_is_exactly_what_belongs_there():
    assert _lint("конст АРХИВ = \"Documents.zip\"\n\nметод Сделать()\n;\n") == []


def test_a_declaration_inside_a_method_is_not_module_level():
    d = _lint(
        "метод Сделать()\n"
        "    знч Локальная = 5\n"
        "    пер Счётчик: Число\n"
        "    Сообщить(Локальная.ВСтроку())\n"
        ";\n"
    )
    assert d == [], [x.message for x in d]


def test_every_modifier_that_needs_a_running_method_is_reported():
    d = _lint(
        "пер Состояние: Число = 0\n"
        "исп Поток = ВременныйФайл.ОткрытьПотокЗаписи()\n"
        "конст ПРЕДЕЛ = 10\n"
        "\n"
        "метод Сделать()\n"
        ";\n"
    )
    assert [x.line for x in d] == [1, 2]
    assert "пер Состояние" in d[0].message and "исп Поток" in d[1].message


def test_a_structure_field_is_not_a_module_declaration():
    # Inside a structure the same modifiers are the normal way to declare a field.
    d = _lint(
        "структура Точка\n"
        "    знч Х: Число\n"
        "    знч У: Число\n"
        ";\n"
    )
    assert d == [], [x.message for x in d]
