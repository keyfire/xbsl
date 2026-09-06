"""code/param-redeclared: a local `знч` / `пер` with the name of the method's own parameter.

The compiler answers "Переменная с именем ... уже определена" only at the server apply, and
the stand rolls back to the previous build; the linter reports the clash at the declaration.
The rule needs no Element data, so the tests live outside test_rules (that module is skipped
whole in a data-less checkout) and run in the public CI.

Every "silent" case also selects code/parse-error: a silence that comes from a broken fixture
would prove nothing, the rule stands down on a file that does not parse.
"""

from xbsl import engine

RULE = "code/param-redeclared"


def _lint(content: str, *, with_parse: bool = False):
    select = {RULE, "code/parse-error"} if with_parse else {RULE}
    return engine.run_sources([engine.load_text("Module.xbsl", content)], select=select)


def _positions(diags):
    return [(d.line, d.col) for d in diags]


def test_param_redeclared_in_loop():
    # The case behind the rule: a parameter added to a method whose loop already declared
    # a `знч` of that name - the linter was silent, the apply rolled back.
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    пер Копилка = 0\n"
        "    для Долька из Дольки\n"
        "        знч ШагСетки = Долька * 2\n"
        "        Копилка += ШагСетки\n"
        "    ;\n"
        "    возврат Копилка\n"
        ";\n"
    )
    assert _positions(d) == [(4, 13)], [x.message for x in d]
    message = d[0].message
    assert "'знч ШагСетки'" in message and "'СложитьДольки'" in message
    assert "(строка 1)" in message or "(line 1)" in message
    assert d[0].rule_id == RULE and d[0].severity.value == "error"


def test_param_redeclared_in_condition():
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    если ШагСетки > 1\n"
        "        пер Дольки = []\n"
        "    иначе\n"
        "        знч Кратность: Число = ШагСетки\n"
        "    ;\n"
        "    возврат Дольки.Размер()\n"
        ";\n"
    )
    assert _positions(d) == [(3, 13)], [x.message for x in d]
    assert "'пер Дольки'" in d[0].message


def test_param_redeclared_in_try():
    # Both the guarded body and the catch body are blocks nested in the method's scope.
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    попытка\n"
        "        знч ШагСетки = 1\n"
        "    поймать Осечка: Исключение\n"
        "        пер Дольки: Массив<Число> = []\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _positions(d) == [(3, 13), (5, 13)], [x.message for x in d]


def test_param_redeclared_in_nested_scope_and_use():
    # `область` nests like any block, and `исп` declares a variable like `знч` does.
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    область\n"
        "        пока Истина\n"
        "            исп ШагСетки = ОткрытьЛенту()\n"
        "        ;\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _positions(d) == [(4, 17)], [x.message for x in d]
    assert "'исп ШагСетки'" in d[0].message


def test_param_redeclared_english_spelling():
    # The keywords come from the bilingual lexer: `method` / `val` clash the same way.
    d = _lint(
        "method SumSlices(GridStep: Number, Slices: Array<Number>): Number\n"
        "    for Slice in Slices\n"
        "        val GridStep = Slice\n"
        "    ;\n"
        "    return GridStep\n"
        ";\n"
    )
    assert _positions(d) == [(3, 13)], [x.message for x in d]
    assert "'val GridStep'" in d[0].message and "'SumSlices'" in d[0].message


def test_param_redeclared_silent_on_other_names():
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    пер Копилка = 0\n"
        "    для Долька из Дольки\n"
        "        знч Слагаемое = Долька * ШагСетки\n"
        "        Копилка += Слагаемое\n"
        "    ;\n"
        "    возврат Копилка\n"
        ";\n",
        with_parse=True,
    )
    assert d == [], [x.message for x in d]


def test_param_redeclared_silent_across_methods():
    # A name is scoped to its method: another method may declare a local of that name.
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число): Число\n"
        "    возврат ШагСетки * 2\n"
        ";\n"
        "\n"
        "метод ВычислитьКратность(): Число\n"
        "    знч ШагСетки = 3\n"
        "    возврат ШагСетки\n"
        ";\n",
        with_parse=True,
    )
    assert d == [], [x.message for x in d]


def test_param_redeclared_leaves_loops_catches_and_lambdas_alone():
    # Deliberately outside the rule (see the module docstring): a loop variable, a catch
    # variable, a lambda parameter and a declaration inside a full-form lambda body.
    d = _lint(
        "метод СложитьДольки(ШагСетки: Число, Дольки: Массив<Число>): Число\n"
        "    для ШагСетки из Дольки\n"
        "    ;\n"
        "    попытка\n"
        "    поймать ШагСетки: Исключение\n"
        "    ;\n"
        "    знч Удвоить = (ШагСетки) -> ШагСетки * 2\n"
        "    знч Сложить = метод(Долька) ->\n"
        "        знч Дольки = Долька\n"
        "        возврат Дольки\n"
        "    ;\n"
        "    возврат Удвоить(1) + Сложить(2)\n"
        ";\n",
        with_parse=True,
    )
    assert d == [], [x.message for x in d]
