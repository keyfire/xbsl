"""code/this-in-static-method and code/instance-call-from-static: the object context a
static method does not have.

Both bans are quoted from the docs section "Статические методы элементов проекта":
"Статические методы не могут использовать контекст объекта и обращения к этот" and "Из
статического метода нельзя вызывать обычные методы в данном модуле".

The rules parse and tokenize the module, so the module is data-dependent (conftest).
"""

from xbsl import engine

_THIS = "code/this-in-static-method"
_CALL = "code/instance-call-from-static"


def _lint(content, rule_id):
    return engine.run_sources([engine.load_text("Проба.xbsl", content)], select={rule_id})


def test_this_in_static_method_is_reported():
    # The real shape it was written for: an enumeration module where a `выбор этот` method
    # is declared static by mistake.
    d = _lint(
        "статический метод КодСервиса(): Строка\n"
        "    выбор этот\n"
        "    когда Новое\n"
        "        возврат \"new\"\n"
        "    ;\n"
        "    возврат \"\"\n"
        ";\n",
        _THIS,
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (2, 11)
    assert "КодСервиса" in d[0].message


def test_this_in_an_instance_method_is_silent():
    d = _lint(
        "метод КодСервиса(): Строка\n"
        "    возврат СтатусПриложения.Переходные().Содержит(этот)\n"
        ";\n"
        "статический метод Переходные(): Массив<СтатусПриложения>\n"
        "    возврат []\n"
        ";\n",
        _THIS,
    )
    assert d == []


def test_this_in_a_lambda_of_a_static_method_is_reported():
    # The lambda body runs in the same static context - the ban holds inside it.
    d = _lint(
        "статический метод Отбор(Список: Массив<Строка>): Массив<Строка>\n"
        "    возврат Список.Отобрать(Элемент -> Элемент == этот.Код)\n"
        ";\n",
        _THIS,
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (2, 51)


def test_this_in_a_comment_is_silent():
    d = _lint(
        "статический метод Заголовок(): Строка\n"
        "    // этот метод общий для всего типа\n"
        "    возврат \"\"\n"
        ";\n",
        _THIS,
    )
    assert d == []


def test_static_method_of_a_structure_is_judged_too():
    d = _lint(
        "структура Точка\n"
        "    знч Х: Число\n"
        "    статический метод Ноль(): Точка\n"
        "        возврат этот\n"
        "    ;\n"
        ";\n",
        _THIS,
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (4, 17)


def test_instance_call_from_static_is_reported():
    d = _lint(
        "метод Представление(): Строка\n"
        "    возврат \"текст\"\n"
        ";\n"
        "статический метод Заголовок(): Строка\n"
        "    возврат Представление()\n"
        ";\n",
        _CALL,
    )
    assert len(d) == 1, [x.message for x in d]
    assert (d[0].line, d[0].col) == (5, 13)
    assert "Заголовок" in d[0].message and "Представление" in d[0].message


def test_member_call_of_the_same_name_is_silent():
    # `Значение.Представление()` is a call on a value, which is exactly the advised fix.
    d = _lint(
        "метод Представление(): Строка\n"
        "    возврат \"текст\"\n"
        ";\n"
        "статический метод Ссылка(Значение: Проба): Строка\n"
        "    возврат Значение.Представление()\n"
        ";\n",
        _CALL,
    )
    assert d == []


def test_call_of_another_static_method_is_silent():
    d = _lint(
        "статический метод Код(): Строка\n"
        "    возврат \"\"\n"
        ";\n"
        "статический метод Заголовок(): Строка\n"
        "    возврат Код()\n"
        ";\n",
        _CALL,
    )
    assert d == []


def test_name_declared_both_static_and_instance_is_skipped():
    # The docs allow the pair when the signatures do not overlap, and the bare call may
    # bind to the static one - the rule stays silent rather than guessing.
    d = _lint(
        "метод Значок(): Строка\n"
        "    возврат \"\"\n"
        ";\n"
        "статический метод Значок(Статус: Строка): Строка\n"
        "    возврат \"\"\n"
        ";\n"
        "статический метод Колонка(): Строка\n"
        "    возврат Значок(\"new\")\n"
        ";\n",
        _CALL,
    )
    assert d == []


def test_shadowed_name_is_skipped():
    d = _lint(
        "метод Представление(): Строка\n"
        "    возврат \"текст\"\n"
        ";\n"
        "статический метод Заголовок(): Строка\n"
        "    знч Представление = () -> \"иное\"\n"
        "    возврат Представление()\n"
        ";\n",
        _CALL,
    )
    assert d == []


def test_module_without_static_methods_is_not_parsed_twice():
    # The cheap exit: nothing static, nothing to judge.
    assert _lint("метод Имя(): Строка\n    возврат этот.Код\n;\n", _THIS) == []
    assert _lint("метод Имя(): Строка\n    возврат Имя()\n;\n", _CALL) == []


def test_broken_file_is_left_to_parse_error():
    assert _lint("статический метод (: Строка\n    возврат этот\n", _THIS) == []
