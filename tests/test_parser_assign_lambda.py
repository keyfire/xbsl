"""The body of a short lambda may be an assignment, and its parameter may be a keyword-name.

Two holes in the same construct, both met in vendor libraries that the IDE server accepts
without a single diagnostic:

- `Список.ДляКаждого(Элемент -> Элемент.Значение = 1)`: the body stopped at the expression,
  so the `=` broke the enclosing call - "expected ')' after the call arguments", then
  "expected an expression" and "cannot parse the statement";
- `Типы.Фильтровать(Тип -> Тип != Тип<Неопределено>)`: `Type`, `Query` and `Method` are legal
  names in either spelling, but the parser read them as the start of a type literal, a query
  or a full lambda, and the arrow broke the call the same way.

A module with either construct had parse errors, and every rule that skips such a module did
not see it at all. The named call argument `Имя = значение` is a different construct and must
stay one.
"""

from __future__ import annotations

import pytest

from xbsl import engine
from xbsl import parser as P
from xbsl.rules import undefined_names  # noqa: F401 - registers the rule

pytestmark = pytest.mark.needs_data  # the parser sits on the lexer, which reads the data


def _body(text: str) -> list[P.Stmt]:
    """Statements of the single method `А` wrapped around the given lines."""
    source = "метод А()\n" + "".join(f"    {line}\n" for line in text.splitlines()) + ";\n"
    module, errors = P.parse_text(source)
    assert errors == [], [e.message for e in errors]
    method = module.members[0]
    assert isinstance(method, P.Method)
    return method.body


def _only_arg(stmt: P.Stmt) -> P.CallArg:
    assert isinstance(stmt, P.ExprStmt)
    call = stmt.expr
    assert isinstance(call, P.Call)
    assert len(call.args) == 1, call.args
    return call.args[0]


def _lambda_assign(value: P.Expr | None) -> tuple[P.Lambda, P.Assign]:
    assert isinstance(value, P.Lambda)
    assert value.body_stmts is None
    assert isinstance(value.body_expr, P.Assign), value.body_expr
    return value, value.body_expr


# --- the assignment body ------------------------------------------------------------------


def test_single_parameter_lambda_assigns_a_member():
    arg = _only_arg(_body("Список.ДляКаждого(Элемент -> Элемент.Значение = 1)")[0])
    assert arg.name is None  # a lambda argument, not a named one
    lam, assign = _lambda_assign(arg.value)
    assert [p.name for p in lam.params] == ["Элемент"]
    assert isinstance(assign.target, P.Member) and assign.target.name == "Значение"
    assert assign.op == "="
    assert isinstance(assign.value, P.Literal) and assign.value.text == "1"
    # the lambda ends where the right-hand side ends, before the closing parenthesis
    assert lam.end == assign.end == assign.value.end


def test_parenthesized_parameters_lambda_assigns_a_member():
    arg = _only_arg(_body("Список.ДляКаждого((Элемент) -> Элемент.Значение = 1)")[0])
    lam, assign = _lambda_assign(arg.value)
    assert [p.name for p in lam.params] == ["Элемент"]
    assert isinstance(assign.target, P.Member)


def test_parameterless_lambda_assigns_a_name():
    arg = _only_arg(_body("ПриИзменении.ПодключитьОбработчик(() -> Изменено = Истина)")[0])
    lam, assign = _lambda_assign(arg.value)
    assert lam.params == []
    assert isinstance(assign.target, P.Name) and assign.target.name == "Изменено"
    assert isinstance(assign.value, P.Literal) and assign.value.kind == "TRUE"


@pytest.mark.parametrize("op", ["=", "+=", "-=", "*=", "/="])
def test_every_assignment_operator_is_accepted_in_the_body(op):
    arg = _only_arg(_body(f"Партии.ДляКаждого(Партия -> Партия.Остаток {op} 2)")[0])
    _lam, assign = _lambda_assign(arg.value)
    assert assign.op == op


def test_lambda_with_assignment_as_a_declaration_value_ends_on_its_line():
    body = _body(
        "знч Отметить = (Задача) -> Задача.Готово = Истина\n"
        "Итог = 2"
    )
    assert len(body) == 2
    decl, following = body
    assert isinstance(decl, P.VarDecl) and decl.name == "Отметить"
    _lambda_assign(decl.init)
    # the next line is a statement of its own, not a part of the lambda
    assert isinstance(following, P.Assign) and isinstance(following.target, P.Name)
    assert following.target.name == "Итог"


def test_statement_assigning_a_lambda_keeps_the_inner_assignment_in_the_lambda():
    stmt = _body("Обработчик = Задача -> Задача.Готово = Истина")[0]
    assert isinstance(stmt, P.Assign) and isinstance(stmt.target, P.Name)
    _lam, inner = _lambda_assign(stmt.value)
    assert isinstance(inner.target, P.Member) and inner.target.name == "Готово"


def test_assignment_targets_an_index_and_a_cast():
    body = _body(
        "Поля.ДляКаждого(Поле -> Итог[Поле.Имя] = Поле.Значение)\n"
        "Флажки.ДляКаждого((Компонент) -> (Компонент как Флажок).Значение = Ложь)"
    )
    _lam, by_index = _lambda_assign(_only_arg(body[0]).value)
    assert isinstance(by_index.target, P.Index)
    _lam, by_cast = _lambda_assign(_only_arg(body[1]).value)
    assert isinstance(by_cast.target, P.Member)
    assert isinstance(by_cast.target.obj, P.AsType)


def test_right_hand_side_keeps_its_own_operators_and_nested_lambdas():
    stmt = _body(
        "возврат Задачи.ДляКаждого(Задача -> Задача.Шаги = "
        "Кэш.Получить(Задача.Ссылка)?.Преобразовать(Строка -> Строка.Шаг) ?? [])"
    )[0]
    assert isinstance(stmt, P.Return)
    assert isinstance(stmt.value, P.Call)
    _lam, assign = _lambda_assign(stmt.value.args[0].value)
    assert isinstance(assign.value, P.Coalesce)
    assert isinstance(assign.value.right, P.ArrayLit)


def test_assignment_body_may_move_to_the_next_line():
    arg = _only_arg(_body(
        "Событие.ПодключитьОбработчик((Шаг) ->\n"
        "    этот.Шаг = Шаг\n"
        ")"
    )[0])
    _lam, assign = _lambda_assign(arg.value)
    assert isinstance(assign.target, P.Member) and isinstance(assign.target.obj, P.This)


def test_named_argument_stays_a_named_argument():
    stmt = _body(
        "Отправить(Получатель = Адрес, Обработчик = Ответ -> Ответ.Прочитано = Истина)"
    )[0]
    assert isinstance(stmt, P.ExprStmt) and isinstance(stmt.expr, P.Call)
    first, second = stmt.expr.args
    assert first.name == "Получатель" and isinstance(first.value, P.Name)
    assert second.name == "Обработчик"
    _lam, assign = _lambda_assign(second.value)
    assert isinstance(assign.target, P.Member) and assign.target.name == "Прочитано"


def test_lambda_body_without_assignment_is_still_an_expression():
    arg = _only_arg(_body("Список.Сортировать(Элемент -> Элемент.Имя == Образец)")[0])
    assert isinstance(arg.value, P.Lambda)
    assert isinstance(arg.value.body_expr, P.Compare)


def test_missing_right_hand_side_is_one_error_at_the_operator():
    text = "метод А()\n    Список.ДляКаждого(Элемент -> Элемент.Значение = )\n;\n"
    _module, errors = P.parse_text(text)
    assert [e.message for e in errors] == ["Ожидается выражение после присваивания"]
    assert text[errors[0].start:errors[0].end] == "="


# --- a keyword-name as the parameter ------------------------------------------------------


@pytest.mark.parametrize("name", ["Тип", "Запрос", "Метод"])
def test_keyword_name_can_be_the_single_parameter(name):
    arg = _only_arg(_body(f"Коллекция.Фильтровать({name} -> {name}.Имя != \"\")")[0])
    assert isinstance(arg.value, P.Lambda)
    assert [p.name for p in arg.value.params] == [name]
    assert isinstance(arg.value.body_expr, P.Compare)


def test_type_parameter_compared_with_a_type_literal():
    stmt = _body("знч Известные = Типы.Фильтровать(Тип -> Тип != Тип<Неопределено>)")[0]
    assert isinstance(stmt, P.VarDecl) and isinstance(stmt.init, P.Call)
    lam = stmt.init.args[0].value
    assert isinstance(lam, P.Lambda)
    compare = lam.body_expr
    assert isinstance(compare, P.Compare)
    assert isinstance(compare.first, P.Name) and compare.first.name == "Тип"
    assert isinstance(compare.rest[0][1], P.Literal) and compare.rest[0][1].kind == "TYPE"


def test_english_spelling_takes_both_constructs():
    module, errors = P.parse_text(
        "method Mark(Items: Array<String>)\n"
        "    Items.ForEach(Item -> Item.Done = True)\n"
        "    val Known = Types.Filter(Type -> Type != Type<Undefined>)\n"
        ";\n"
    )
    assert errors == [], [e.message for e in errors]
    method = module.members[0]
    assert isinstance(method, P.Method)
    first, second = method.body
    _lam, assign = _lambda_assign(_only_arg(first).value)
    assert isinstance(assign.target, P.Member) and assign.target.name == "Done"
    assert isinstance(second, P.VarDecl) and isinstance(second.init, P.Call)
    lam = second.init.args[0].value
    assert isinstance(lam, P.Lambda) and [p.name for p in lam.params] == ["Type"]


def test_keyword_names_without_an_arrow_keep_their_meaning():
    body = _body(
        "знч Т = Тип<Строка>\n"
        "знч Удвоить = метод (Х: Число) -> возврат Х * 2;\n"
        "Отправить(Метод, Тип, Запрос)"
    )
    assert isinstance(body[0].init, P.Literal) and body[0].init.kind == "TYPE"
    assert isinstance(body[1].init, P.Lambda) and body[1].init.body_stmts is not None
    call = body[2].expr
    assert [a.value.name for a in call.args] == ["Метод", "Тип", "Запрос"]


# --- rules see the construct ----------------------------------------------------------------


_TASKS = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-00000000f001
Имя: Шаги
ОбластьВидимости: ВПроекте
"""


def _undefined(module: str) -> list:
    sources = [engine.load_text("Шаги.yaml", _TASKS), engine.load_text("Шаги.xbsl", module)]
    return engine.run_sources(sources, select={"code/undefined-name"})


def test_undefined_name_reads_both_sides_of_a_lambda_assignment():
    module = (
        "метод Отметить(Задачи: Массив<Строка>, Итог: Соответствие<Строка, Булево>)\n"
        "    Задачи.ДляКаждого(Задача -> Итог[Задача] = Готово)\n"
        "    Задачи.ДляКаждого(Задача -> Сводка[Задача] = Истина)\n"
        ";\n"
    )
    found = sorted(_undefined(module), key=lambda d: d.line)
    assert [d.line for d in found] == [2, 3]
    assert "Готово" in found[0].message and "Сводка" in found[1].message


def test_undefined_name_is_silent_on_a_valid_lambda_assignment():
    module = (
        "метод Отметить(Задачи: Массив<Строка>, Итог: Соответствие<Строка, Булево>)\n"
        "    Задачи.ДляКаждого(Задача -> Итог[Задача] = Истина)\n"
        ";\n"
    )
    assert _undefined(module) == []
