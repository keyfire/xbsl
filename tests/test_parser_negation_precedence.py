"""How `не` binds next to `это`, `как`, comparisons and `и`/`или`.

The grammar of the platform gives `не` the primary alone: `[не] logPrimary [это Тип | как Тип]`.
So `не Значение это Строка` is `(не Значение) это Строка` - the language server of the IDE refuses
it with a type error on the operand of `не` - while a comparison stays under the negation, since
the comparison is the primary itself: `не Количество > 0` is `не (Количество > 0)`. The parser used
to read the negation over the whole fact, `не (Значение это Строка)`, and every rule walking the tree
saw a check that the platform does not compile.

The parser sits on the lexer, which reads the operators and keywords from the Element data.
"""

import pytest

from xbsl import parser as P

pytestmark = pytest.mark.needs_data

_HEAD = "метод Проба(Флаг: Булево, Значение: Объект?, Количество: Число)\n    знч Итог = "


def _value(expression: str) -> P.Expr:
    module, errors = P.parse_text(f"{_HEAD}{expression}\n;\n")
    assert errors == [], errors
    return module.members[0].body[0].init


def _text(expression: str, node: P.Node) -> str:
    return f"{_HEAD}{expression}"[node.start:node.end]


def test_the_negation_is_the_operand_of_a_type_check():
    expression = "не Значение это Строка"
    node = _value(expression)

    assert isinstance(node, P.IsType) and not node.negated
    assert isinstance(node.operand, P.Unary) and node.operand.op == "не"
    assert isinstance(node.operand.operand, P.Name) and node.operand.operand.name == "Значение"
    assert _text(expression, node) == expression
    assert _text(expression, node.operand) == "не Значение"


def test_the_negation_is_the_operand_of_a_cast():
    node = _value("не Значение как Булево")

    assert isinstance(node, P.AsType)
    assert isinstance(node.operand, P.Unary) and isinstance(node.operand.operand, P.Name)


def test_a_negated_type_check_written_inside_keeps_its_shape():
    node = _value("Значение это не Строка")

    assert isinstance(node, P.IsType) and node.negated
    assert isinstance(node.operand, P.Name)


def test_a_group_puts_the_type_check_under_the_negation():
    node = _value("не (Значение это Строка)")

    assert isinstance(node, P.Unary) and isinstance(node.operand, P.IsType)


@pytest.mark.parametrize("expression", [
    "не Количество > 0",
    "не Количество + 1 > 0",
    "не Значение == Неопределено",
])
def test_a_comparison_stays_under_the_negation(expression):
    node = _value(expression)

    assert isinstance(node, P.Unary) and isinstance(node.operand, P.Compare)
    assert _text(expression, node) == expression


def test_the_negation_does_not_reach_over_and():
    node = _value("не Флаг и Флаг")

    assert isinstance(node, P.Binary) and node.op == "и"
    assert isinstance(node.left, P.Unary) and isinstance(node.right, P.Name)


def test_a_negation_on_the_right_of_and_negates_its_own_operand():
    node = _value("Флаг и не Значение это Строка")

    assert isinstance(node, P.Binary) and isinstance(node.right, P.IsType)
    assert isinstance(node.right.operand, P.Unary)


def test_the_ternary_after_a_type_check_takes_the_negated_operand():
    expression = "не Флаг это Булево ? 1 : 0"
    node = _value(expression)

    assert isinstance(node, P.Ternary)
    assert isinstance(node.cond, P.IsType) and isinstance(node.cond.operand, P.Unary)
    assert _text(expression, node) == expression


def test_a_double_negation_is_read_as_the_negation_of_a_negation():
    # the platform refuses a second `не` in a row; the parser stays permissive there
    node = _value("не не Флаг")

    assert isinstance(node, P.Unary) and isinstance(node.operand, P.Unary)
    assert isinstance(node.operand.operand, P.Name)


def test_the_english_keywords_bind_the_same_way():
    module, errors = P.parse_text("method Probe(Value: Object?)\n    val Result = not Value is String\n;\n")
    node = module.members[0].body[0].init

    assert errors == []
    assert isinstance(node, P.IsType) and isinstance(node.operand, P.Unary) and node.operand.op == "not"


# --- what the rules over the tree see ---------------------------------------------------------

def _lint(text: str, rule_id: str):
    from xbsl import engine

    return engine.run_sources([engine.load_text("Проба.xbsl", text)], select={rule_id})


def test_a_cast_of_a_negation_is_judged_as_a_cast_of_a_boolean():
    # the IDE warns that the cast is redundant: the value cast is `не Значение`, a boolean
    text = "метод Проба(Значение: Объект?): Булево\n    возврат не Значение как Булево\n;\n"
    found = _lint(text, "code/redundant-cast")

    assert [(d.line, d.col) for d in found] == [(2, 13)]


def test_a_type_check_of_a_negation_is_known_in_advance():
    text = "метод Проба(Флаг: Булево): Булево\n    возврат не Флаг это Булево\n;\n"
    found = _lint(text, "code/redundant-type-check")

    assert [(d.line, d.col) for d in found] == [(2, 13)]
