"""code/unused-local and code/unused-loop-var: the IDE's `Неиспользуемая переменная`.

The rules walk the parser's tree, and the parser sits on the lexer, which reads language.json -
so the module is data-dependent (tests/conftest.py). Every case also selects code/parse-error:
a silence that comes from a broken fixture would prove nothing, the rules stand down on a
method that does not parse.
"""

from pathlib import Path

from xbsl import engine, fixer, i18n

RULES = {"code/unused-local", "code/unused-loop-var", "code/parse-error"}


def _lint(content: str):
    return engine.run_sources([engine.load_text("Модуль.xbsl", content)], select=RULES)


def _found(diags):
    return [(d.rule_id, d.line, d.col) for d in diags]


def _fixed(content: str) -> str:
    source = engine.load_text("Модуль.xbsl", content)
    diags = engine.run_sources([source], select=RULES)
    return fixer.fix_source(source, diags).text


# --- `исп`: the case the IDE reports and the linter used to skip ----------------------------

_USE_UNUSED = (
    "метод ОбновитьКурсы()\n"
    "    исп Привилегии = КонтекстДоступа.Привилегированный()\n"
    "    Записать()\n"
    ";\n"
)


def test_unused_use_variable_is_reported_at_the_name():
    d = _lint(_USE_UNUSED)
    assert _found(d) == [("code/unused-local", 2, 9)], [x.message for x in d]
    assert "'Привилегии'" in d[0].message and "'исп'" in d[0].message


def test_unused_use_variable_fix_drops_the_name():
    fixed = _fixed(_USE_UNUSED)
    assert fixed.splitlines()[1] == "    исп КонтекстДоступа.Привилегированный()"
    # The unnamed form is a use statement, not a variable: nothing is left to report.
    assert _lint(fixed) == []


def test_use_variable_with_a_type_gets_no_fix():
    # Dropping the name would drop the declared type as well - left to the author.
    d = _lint(
        "метод ЗаписатьЖурнал(Файл: Файл)\n"
        "    исп Поток: ПотокЗаписи = Файл.ОткрытьПотокЗаписи()\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 2, 9)]
    assert d[0].fix is None


def test_read_use_variable_and_unnamed_use_are_silent():
    assert _lint(
        "метод ЗаписатьЖурнал(Файл: Файл)\n"
        "    исп КонтекстДоступа.Привилегированный()\n"
        "    исп Поток = Файл.ОткрытьПотокЗаписи()\n"
        "    Поток.Записать(\"строка\")\n"
        ";\n"
    ) == []


def test_english_spelling_of_use():
    content = (
        "method Refresh()\n"
        "    use Privileges = AccessContext.Privileged()\n"
        "    val Draft = 1\n"
        ";\n"
    )
    assert _found(_lint(content)) == [("code/unused-local", 2, 9), ("code/unused-local", 3, 9)]
    assert _fixed(content).splitlines()[1] == "    use AccessContext.Privileged()"
    i18n.set_lang("en")
    message = _lint(content)[0].message
    assert "'Privileges'" in message and "'use'" in message


def test_fix_offsets_hold_on_a_file_with_bom_and_crlf(tmp_path: Path):
    path = tmp_path / "Модуль.xbsl"
    path.write_bytes(_USE_UNUSED.replace("\n", "\r\n").encode("utf-8-sig"))
    source = engine.load(path)
    diags = engine.run_sources([source], select=RULES)
    result = fixer.fix_source(source, diags)
    expected = _USE_UNUSED.replace("Привилегии = ", "").replace("\n", "\r\n")
    assert result.applied == 1 and result.text == expected
    assert fixer.encode(source, result.text).startswith(b"\xef\xbb\xbf")


# --- what counts as a read ------------------------------------------------------------------

def test_only_assigned_locals_get_their_own_message():
    d = _lint(
        "метод Пересчитать(): Число\n"
        "    пер Итог = 0\n"
        "    Итог = 5\n"
        "    пер Счетчик = 0\n"
        "    Счетчик += 1\n"
        "    пер Остаток = 10\n"
        "    Остаток = Остаток - 1\n"
        "    возврат Остаток\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 2, 9), ("code/unused-local", 4, 9)]
    assert all("только присваивается" in x.message for x in d)


def test_write_through_a_member_or_an_index_reads_the_variable():
    assert _lint(
        "метод Заполнить(): Число\n"
        "    знч Партия = новый Партии()\n"
        "    Партия.Количество = 2\n"
        "    знч Склады = [1, 2]\n"
        "    Склады[0] = 5\n"
        "    возврат 0\n"
        ";\n"
    ) == []


def test_sibling_blocks_declare_separate_variables():
    d = _lint(
        "метод Выбрать(Условие: Булево): Число\n"
        "    если Условие\n"
        "        знч Курс = 1\n"
        "    иначе\n"
        "        знч Курс = 2\n"
        "        возврат Курс\n"
        "    ;\n"
        "    возврат 0\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 3, 13)]


def test_block_variable_does_not_outlive_its_block():
    # After the block the name means the module constant again: its read is not a read of the
    # block's variable.
    d = _lint(
        "конст Порог = 5\n"
        "\n"
        "метод Выбрать(Условие: Булево): Число\n"
        "    если Условие\n"
        "        знч Порог = 2\n"
        "    ;\n"
        "    возврат Порог\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 5, 13)]


def test_named_argument_and_member_are_not_reads():
    d = _lint(
        "метод Создать(Склад: Склады): Партии\n"
        "    знч Количество = 1\n"
        "    знч Размер = 2\n"
        "    знч Итог = Склад.Размер()\n"
        "    возврат новый Партии(Количество = Итог)\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 2, 9), ("code/unused-local", 3, 9)]


def test_reads_in_strings_queries_and_closures():
    # The batch query carries a `;` of its own: the token walk used to end the method there,
    # and the read of the query result below the literal was lost.
    assert _lint(
        "метод Сводка(): Строка\n"
        "    знч Порог = 10\n"
        "    знч Код = \"А\"\n"
        "    знч Имя = \"Б\"\n"
        "    знч Номер = 3\n"
        "    знч Множитель = 2\n"
        "    знч Результат = Запрос{\n"
        "        ВЫБРАТЬ Партии.Ссылка ПОМЕСТИТЬ Отобранные ИЗ Партии ГДЕ Партии.Остаток > %Порог\n"
        "        ;\n"
        "        ВЫБРАТЬ Отобранные.Ссылка ИЗ Отобранные ГДЕ Отобранные.Код == %{Код}\n"
        "    }.Выполнить()\n"
        "    знч Умножить = (Значение: Число) -> Значение * Множитель\n"
        "    возврат \"%Имя ${Номер} %{Умножить(Номер)} %{Результат.Размер()}\"\n"
        ";\n"
    ) == []


def test_name_inside_plain_string_text_is_not_a_read():
    # No `%` in front of the name: the text is text, and the variable is only assigned.
    d = _lint(
        "метод Отметка(Отмечено: Булево): Строка\n"
        "    пер Строка: Строка\n"
        "    если Отмечено\n"
        "        Строка = \"да\"\n"
        "    ;\n"
        "    возврат \"Строка%{Символы.ПС}\"\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 2, 9)]


# --- which declarations are tracked ---------------------------------------------------------

def test_loop_variables():
    # `для Х из` is tracked, the counter of `для Х = А по Б` is not (neither is it in the IDE).
    d = _lint(
        "метод Обойти(Склады: Массив<Число>): Число\n"
        "    пер Сумма = 0\n"
        "    для Склад из Склады\n"
        "        Сумма = Сумма + 1\n"
        "    ;\n"
        "    для Номер = 1 по 3\n"
        "        Сумма = Сумма + 1\n"
        "    ;\n"
        "    для Склад из Склады\n"
        "        Сумма = Сумма + Склад\n"
        "    ;\n"
        "    возврат Сумма\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-loop-var", 3, 9)]


def test_catch_lambda_and_method_parameters_are_not_tracked():
    assert _lint(
        "метод Проверить(Склад: Склады): Булево\n"
        "    знч Фильтр = (Значение: Число) -> Истина\n"
        "    попытка\n"
        "        возврат Фильтр(1)\n"
        "    поймать Ошибка: Исключение\n"
        "        возврат Ложь\n"
        "    ;\n"
        ";\n"
    ) == []


def test_locals_of_a_lambda_body_and_of_a_structure_method():
    d = _lint(
        "структура Остатки\n"
        "    пер Количество: Число\n"
        "\n"
        "    метод Пересчитать(): Число\n"
        "        знч Черновик = 1\n"
        "        возврат Количество\n"
        "    ;\n"
        ";\n"
        "\n"
        "метод Посчитать(): Число\n"
        "    знч Расчет = метод(Значение: Число) ->\n"
        "        знч Промежуточный = Значение * 2\n"
        "        возврат Значение\n"
        "    ;\n"
        "    возврат Расчет(2)\n"
        ";\n"
    )
    assert _found(d) == [("code/unused-local", 5, 13), ("code/unused-local", 12, 13)]


def test_method_that_does_not_parse_is_skipped():
    d = _lint(
        "метод Сломанный()\n"
        "    знч Лишний = 1\n"
        "    Записать(\n"
        ";\n"
        "\n"
        "метод Целый()\n"
        "    знч Забытый = 2\n"
        ";\n"
    )
    rules = {x.rule_id for x in d}
    assert "code/parse-error" in rules
    assert [x.line for x in d if x.rule_id == "code/unused-local"] == [7]
