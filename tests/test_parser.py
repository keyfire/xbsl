"""Тесты парсера XBSL: AST по грамматике платформы + восстановление на ошибках.

Позитивные случаи – конструкции, на которых спотыкались токенные эвристики (и которые
встречаются в боевом корпусе); негативные – битый код обязан давать внятную ошибку в
правильном месте, не роняя разбор остатка файла.
"""

from __future__ import annotations

import pytest

from xbsl import parser as P


def ok(text: str) -> P.Module:
    module, errors = P.parse_text(text)
    assert errors == [], [e.message for e in errors]
    return module


def bad(text: str) -> list[P.ParseError]:
    _, errors = P.parse_text(text)
    assert errors, "ожидались синтаксические ошибки"
    return errors


# --- уровень модуля ----------------------------------------------------------------------


def test_module_members():
    m = ok(
        "импорт Основное\n"
        "импорт Внешние::Библиотека::Пакет\n"
        "конст Лимит = 10\n"
        "@Обработчик\n"
        "метод ПослеСоздания()\n"
        "    Х()\n"
        ";\n"
        "структура Точка\n"
        "    знч Х: Число = 0\n"
        "    обз пер У: Число\n"
        ";\n"
        "перечисление Цвет\n"
        "    Красный,\n"
        "    Зеленый умолчание\n"
        ";\n"
    )
    assert [i.name for i in m.imports] == ["Основное", "Внешние::Библиотека::Пакет"]
    kinds = [type(x).__name__ for x in m.members]
    assert kinds == ["ObjectField", "Method", "Structure", "Enum"]
    enum = m.members[3]
    assert [i.name for i in enum.items] == ["Красный", "Зеленый"]
    assert enum.items[1].is_default


def test_method_signature_and_body():
    m = ok(
        "метод Сумма(А: Число, Б: Число = 0): Число\n"
        "    возврат А + Б\n"
        ";\n"
        "статический метод Пусто()\n"
        ";\n"
        "абстрактный метод Контракт(Х: Строка): Булево\n"
    )
    m1, m2, m3 = m.members
    assert m1.name == "Сумма" and [p.name for p in m1.params] == ["А", "Б"]
    assert m1.params[1].default is not None
    assert m1.return_type.text == "Число"
    assert m2.is_static and m3.is_abstract


# --- операторы ---------------------------------------------------------------------------


def test_if_elsif_versus_nested_else():
    # `иначе если` на одной строке – ветка иначе-если; `если` на следующей строке –
    # вложенный если внутри иначе (грамматика: RULE_ELSE (RULE_NL)+ ...).
    m = ok(
        "метод А()\n"
        "    если Х\n"
        "        Ф()\n"
        "    иначе если У\n"
        "        Г()\n"
        "    иначе\n"
        "        Д()\n"
        "    ;\n"
        ";\n"
    )
    stmt = m.members[0].body[0]
    assert isinstance(stmt, P.If)
    assert len(stmt.branches) == 2 and stmt.else_body is not None

    m = ok(
        "метод А()\n"
        "    если Х\n"
        "        Ф()\n"
        "    иначе\n"
        "        если У\n"
        "            Г()\n"
        "        ;\n"
        "    ;\n"
        ";\n"
    )
    stmt = m.members[0].body[0]
    assert len(stmt.branches) == 1
    assert isinstance(stmt.else_body[0], P.If)


def test_case_for_try():
    m = ok(
        "метод А()\n"
        "    выбор Код\n"
        "    когда 1, 2\n"
        "        Ф()\n"
        "    когда > 10\n"
        "        Г()\n"
        "    когда это Строка\n"
        "        Д()\n"
        "    иначе\n"
        "        Е()\n"
        "    ;\n"
        "    для Инд = 0 по 10 шаг 2\n"
        "        Ф(Инд)\n"
        "    ;\n"
        "    для Эл из Список\n"
        "        Г(Эл)\n"
        "    ;\n"
        "    попытка\n"
        "        Р()\n"
        "    поймать Ош: ИсключениеВыполнения\n"
        "        Ж(Ош)\n"
        "    вконце\n"
        "        З()\n"
        "    ;\n"
        ";\n"
    )
    case, for_to, for_each, try_ = m.members[0].body
    assert len(case.whens) == 3 and case.else_body is not None
    assert isinstance(for_to, P.ForTo) and for_to.step is not None
    assert isinstance(for_each, P.ForEach) and for_each.var == "Эл"
    assert len(try_.catches) == 1 and try_.finally_body is not None


def test_capitalized_control_word_is_a_name():
    # ruleident: капитализированные формы управляющих слов – законные имена.
    m = ok(
        "метод А()\n"
        "    знч Выбор = Ф()\n"
        "    если Выбор == Неопределено\n"
        "        возврат\n"
        "    ;\n"
        "    Выбор = Выбор + 1\n"
        "    Г(Выбор)\n"
        ";\n"
    )
    decl = m.members[0].body[0]
    assert isinstance(decl, P.VarDecl) and decl.name == "Выбор"


def test_bare_return_before_else():
    m = ok(
        "метод А()\n"
        "    если Х\n"
        "        возврат\n"
        "    иначе\n"
        "        Г()\n"
        "    ;\n"
        ";\n"
    )
    branch_body = m.members[0].body[0].branches[0][1]
    assert isinstance(branch_body[0], P.Return) and branch_body[0].value is None


def test_use_declaration_and_statement():
    # `исп Имя = ...` – объявление; `исп Выражение` – оператор БЕЗ тела, действующий
    # до конца охватывающего блока (так пишет боевой код: исп КонтекстДоступа...()).
    m = ok(
        "метод А()\n"
        "    исп Скоуп = Открыть()\n"
        "    исп КонтекстДоступа.Привилегированный()\n"
        "    Ф()\n"
        ";\n"
    )
    decl, use, call = m.members[0].body
    assert isinstance(decl, P.VarDecl) and decl.kind == "USE"
    assert isinstance(use, P.UseStmt)
    assert isinstance(call, P.ExprStmt)


# --- выражения ---------------------------------------------------------------------------


def test_ternary_and_coalesce():
    m = ok(
        "метод А()\n"
        "    знч Х = У == 0 ? \"ноль\" : \"нет\"\n"
        "    знч З = М ?? 42\n"
        "    знч В = Данные!\n"
        ";\n"
    )
    x, z, v = (s.init for s in m.members[0].body)
    assert isinstance(x, P.Ternary)
    assert isinstance(z, P.Coalesce)
    assert isinstance(v, P.NonNull)


def test_is_type_with_ternary_branch():
    # спец-ветка грамматики: `х это Тип ? а : б` – `?` здесь тернарный, не nullable
    m = ok(
        "метод А()\n"
        "    знч С = (Б это Число ? (Б как Число).ВСтроку() : \"\")\n"
        "    знч Д = Б это Строка?\n"
        ";\n"
    )
    s = m.members[0].body[0].init
    assert isinstance(s, P.Ternary)
    assert isinstance(s.cond, P.IsType) and not s.cond.type.nullable
    d = m.members[0].body[1].init
    assert isinstance(d, P.IsType) and d.type.nullable


def test_lambdas():
    m = ok(
        "метод А()\n"
        "    Список.Сортировать(х -> х.Имя)\n"
        "    Список.Обойти((а, б) -> а + б)\n"
        "    знч Ф = метод (х: Число) ->\n"
        "        возврат х * 2\n"
        "    ;\n"
        "    Отправить(Токен, Метод, Тело)\n"
        ";\n"
    )
    body = m.members[0].body
    assert isinstance(body[0].expr.args[0].value, P.Lambda)
    assert isinstance(body[1].expr.args[0].value, P.Lambda)
    assert isinstance(body[2].init, P.Lambda) and body[2].init.body_stmts is not None
    # `Метод` в позиции аргумента – имя, а не лямбда
    call = body[3].expr
    assert isinstance(call.args[1].value, P.Name) and call.args[1].value.name == "Метод"


def test_collections_and_generics():
    m = ok(
        "метод А()\n"
        "    знч Массив = [1, 2, 3]\n"
        "    знч Пустой: Массив<Строка> = []\n"
        "    знч Карта = {\"а\": 1, \"б\": 2}\n"
        "    знч ПустаяКарта = {:}\n"
        "    знч Типизированная = <Строка, Число>{:}\n"
        "    знч Множество = {1, 2}\n"
        "    знч Рез = Обработать<Строка>(Данные)\n"
        ";\n"
    )
    b = m.members[0].body
    assert isinstance(b[0].init, P.ArrayLit) and len(b[0].init.items) == 3
    assert isinstance(b[2].init, P.MapLit) and b[2].init.kind == "map"
    assert isinstance(b[3].init, P.MapLit) and b[3].init.kind == "map"
    assert b[4].init.type_args
    assert isinstance(b[5].init, P.MapLit) and b[5].init.kind == "set"
    assert isinstance(b[6].init, P.Call) and b[6].init.type_args


def test_member_chains_and_safe_navigation():
    m = ok(
        "метод А()\n"
        "    знч Имя = Объект?.Владелец?.Наименование\n"
        "    знч Эл = Список[0].Поле\n"
        "    Значение = новый Справочник(Имя = \"Х\").Записать()\n"
        ";\n"
    )
    b = m.members[0].body
    assert isinstance(b[0].init, P.Member) and b[0].init.safe
    assert isinstance(b[1].init, P.Member)
    assert isinstance(b[2].value, P.Call)


def test_method_ref_stays_on_its_line():
    m = ok(
        "метод А()\n"
        "    Кнопка.ПриНажатии = &ТегПриНажатии\n"
        "    Кнопка.Вид = ВидКнопки.Дополнительная\n"
        "    знч Ссылка = &Справочники.Найти\n"
        ";\n"
    )
    b = m.members[0].body
    assert isinstance(b[0].value, P.MethodRef) and b[0].value.text == "ТегПриНажатии"
    assert isinstance(b[1].value, P.Member)


def test_string_interpolation_with_nested_string():
    # интерполяция со вложенной строкой – один STRING-токен, разбор не ломается
    m = ok(
        "метод А()\n"
        "    знч С = \"итог: %{\"★\".Повторить(Н)} из %{Всего.Представление(\"ЧЧ:мм\")}\"\n"
        "    знч Д = \"без интерполяции\"\n"
        ";\n"
    )
    assert isinstance(m.members[0].body[0].init, P.Literal)


def test_query_and_pattern_literals():
    m = ok(
        "метод А()\n"
        "    знч Рез = Запрос{\n"
        "        ВЫБРАТЬ Имя ИЗ Товары ГДЕ Цена > %{Порог}\n"
        "    }.Выполнить()\n"
        "    С = С.Заменить('[^a-z0-9]+', \"-\")\n"
        ";\n"
    )
    q = m.members[0].body[0].init
    assert isinstance(q, P.Call)  # .Выполнить() поверх литерала запроса


def test_expression_line_breaks():
    m = ok(
        "метод А()\n"
        "    знч Итог = Один\n"
        "        или Два\n"
        "        или (Три и Четыре)\n"
        "    знч Текст = \"а\" +\n"
        "        \"б\"\n"
        ";\n"
    )
    assert isinstance(m.members[0].body[0].init, P.Binary)


# --- ошибки ------------------------------------------------------------------------------


def test_error_unclosed_call():
    errors = bad("метод А()\n    Ф(1, 2\n;\n")
    assert any("')'" in e.message for e in errors)


def test_error_missing_method_semicolon():
    errors = bad("метод А()\n    Ф()\n")
    assert any("';'" in e.message for e in errors)


def test_error_missing_ternary_colon():
    errors = bad("метод А()\n    знч Х = А ? Б\n;\n")
    assert any("тернарном" in e.message for e in errors)


def test_error_recovers_to_next_statement():
    # ошибка в первом операторе не прячет разбор остального метода
    module, errors = P.parse_text(
        "метод А()\n"
        "    знч = 5\n"
        "    Годный()\n"
        ";\n"
        "метод Б()\n"
        ";\n"
    )
    assert errors
    assert [m.name for m in module.members] == ["А", "Б"]


def test_error_position_is_local():
    text = "метод А()\n    Ф(\n;\n"
    errors = bad(text)
    line = text.count("\n", 0, errors[0].start) + 1
    assert line <= 3


# --- правило code/parse-error --------------------------------------------------------------


def _rule_diags(code: str) -> list:
    from xbsl.engine import load_text, run_sources

    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/parse-error"}, scopes=("file",)))


def test_rule_reports_parse_errors():
    assert _rule_diags("метод А()\n    Ф()\n;\n") == []
    found = _rule_diags("метод А()\n    Ф(1, 2\n;\n")
    assert found and all(d.severity.value == "error" for d in found)
    assert all(d.rule_id == "code/parse-error" for d in found)


def test_rule_caps_error_cascade():
    # изуродованный файл: много ошибок, но диагностик не больше лимита + итоговая строка
    lines = "".join(f"    Ф{i}(незакрыто\n" for i in range(30))
    found = _rule_diags(f"метод А()\n{lines};\n")
    assert 0 < len(found) <= 11


# --- правило code/undefined-name -----------------------------------------------------------


def _undef(code: str, extra_yaml: str | None = None) -> list:
    from xbsl.engine import load_text, run_sources

    sources = [load_text("Модуль.xbsl", code)]
    if extra_yaml is not None:
        sources.append(load_text("Модуль.yaml", extra_yaml))
    return list(run_sources(sources, select={"code/undefined-name"}))


def test_undefined_name_catches_the_screenshot_typo():
    # параметр Адреса, в цикле Адресар - компилятор откажет, теперь видит и линтер
    diags = _undef(
        "метод ТелоПравки(Адреса: Массив<Строка>): Строка\n"
        "    пер Строки = \"\"\n"
        "    для Адрес из Адресар\n"
        "        Строки = Строки + Адрес\n"
        "    ;\n"
        "    возврат Строки\n"
        ";\n"
    )
    assert len(diags) == 1
    assert "Адресар" in diags[0].message and "Адреса" in diags[0].message  # подсказка


def test_undefined_name_knows_scopes():
    diags = _undef(
        "конст ЛИМИТ = 10\n"
        "метод А(Парам: Число)\n"
        "    знч Локал = Парам + ЛИМИТ\n"
        "    для Инд = 0 по Локал\n"
        "        Б(Инд)\n"
        "    ;\n"
        "    попытка\n"
        "        Б(0)\n"
        "    поймать Ош: ИсключениеВыполнения\n"
        "        Б(Ош.Код)\n"
        "    ;\n"
        "    Список.Обойти(х -> Б(х))\n"
        ";\n"
        "метод Б(Ч: Число)\n"
        ";\n",
        extra_yaml="ВидЭлемента: Справочник\nИмя: Список\n",
    )
    assert diags == [], [d.message for d in diags]


def test_undefined_name_reads_component_yaml():
    # свойство из парного yaml и член унаследованного типа доступны голым именем
    diags = _undef(
        "метод ПриНажатии()\n"
        "    Титул = \"х\"\n"
        "    Закрыть()\n"
        ";\n",
        extra_yaml=(
            "ВидЭлемента: КомпонентИнтерфейса\nИмя: Модуль\n"
            "Наследует:\n    Тип: Форма\n"
            "Свойства:\n    -\n        Имя: Титул\n        Тип: Строка\n"
        ),
    )
    assert diags == [], [d.message for d in diags]


def test_parser_catalog_ru_texts_are_texts():
    # Грабля локализации: глобальная замена литералов однажды подменила ru-тексты каталога
    # вызовами i18n.t, и простые сообщения выводились сырыми ключами (en-тексты целы,
    # поэтому смоук и тесты этого не увидели).
    from xbsl import i18n

    for key in i18n.registered_keys():
        if key.startswith("parser."):
            ru = i18n.translations(key)["ru"]
            assert ru and not ru.startswith("parser."), key
