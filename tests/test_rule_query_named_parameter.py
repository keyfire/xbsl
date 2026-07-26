"""Checks of the query/named-parameter rule (`&Имя` inside a query literal)."""

from xbsl import engine

_RULE = "query/named-parameter"


def _lint(code: str, name: str = "Модуль.xbsl"):
    return engine.run_sources([engine.load_text(name, code)], select={_RULE})


def test_named_parameter_is_reported():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ Т.Ссылка ИЗ Т КАК Т ГДЕ Т.Код = &Код}\n"
        ";\n"
    )
    assert len(d) == 1 and d[0].rule_id == _RULE and d[0].line == 2
    assert "%Код" in d[0].message


def test_interpolation_is_silent():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ Т.Ссылка ИЗ Т КАК Т ГДЕ Т.Код = %Код}\n"
        ";\n"
    )
    assert d == []


def test_ampersand_outside_a_query_literal_is_silent():
    # a literal containing an url with an ampersand is not a query parameter
    d = _lint(
        "метод М()\n"
        '    знч Адрес = "https://example.com/?a=1&b=2"\n'
        ";\n"
    )
    assert d == []


def test_ampersand_in_a_comment_inside_the_block_is_silent():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ Т.Ссылка ИЗ Т КАК Т\n"
        "        // раньше здесь стоял &Код\n"
        "        ГДЕ Т.Код = %Код}\n"
        ";\n"
    )
    assert d == []


def test_every_named_parameter_of_the_block_is_reported():
    d = _lint(
        "метод М()\n"
        "    знч З = Запрос{ВЫБРАТЬ Т.Ссылка ИЗ Т КАК Т\n"
        "        ГДЕ Т.Код = &Код И Т.Вид = &Вид}\n"
        ";\n"
    )
    assert [x.line for x in d] == [3, 3]
    assert "&Код" in d[0].message and "&Вид" in d[1].message
