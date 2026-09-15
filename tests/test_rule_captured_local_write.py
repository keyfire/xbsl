"""Assignments after lambda capture respect bindings, lexical order and loop reuse."""

import pytest

from xbsl import engine

pytestmark = pytest.mark.needs_data
RULE = "code/captured-local-write"


def lint(text):
    diagnostics = engine.run_sources([engine.load_text("Sample.xbsl", text)],
                                     select={RULE, "code/parse-error"})
    assert not [d for d in diagnostics if d.rule_id == "code/parse-error"]
    return [d for d in diagnostics if d.rule_id == RULE]


def method(body):
    return "method Check(Flag: Boolean, Input: Number)\n" + body + ";\n"


@pytest.mark.parametrize("op", ["=", "+=", "-=", "*=", "/="])
def test_write_after_capture_is_an_error_at_the_target(op):
    diagnostics = lint(method("    var Counter = 1\n"
                              "    val Read = () -> Counter\n"
                              f"    Counter {op} 2\n"))
    assert [(d.line, d.col) for d in diagnostics] == [(4, 5)]
    assert diagnostics[0].severity.value == "error"
    assert "Counter" in diagnostics[0].message
    assert diagnostics[0].fix is None


def test_russian_spelling_and_parenthesized_target():
    diagnostics = lint("метод Проверить()\n"
                       "    пер Счетчик = 1\n"
                       "    знч Прочитать = () -> Счетчик\n"
                       "    (Счетчик) = 2\n;\n")
    assert [d.line for d in diagnostics] == [4]


@pytest.mark.parametrize("header", ["for Index = 1 to 3", "for Index in [1, 2]", "while Flag"])
def test_loop_reuses_the_outer_binding_even_when_write_precedes_capture(header):
    assert [d.line for d in lint(method("    var Counter = 1\n"
        f"    {header}\n        Counter += 1\n"
        "        val Read = () -> Counter\n    ;\n"))] == [4]


@pytest.mark.parametrize("branch", ["if Flag", "case Flag\n    when True"])
def test_later_sibling_branch_write_follows_the_compilers_lexical_capture_order(branch):
    assert len(lint(method("    var Counter = 1\n"
        f"    {branch}\n        val Read = () -> Counter\n"
        "    else\n        Counter = 2\n    ;\n"))) == 1


def test_method_parameter_is_captured_but_lambda_local_stays_mutable():
    assert [d.line for d in lint(method("    val Outer = method() ->\n"
        "        var Current = 1\n        val Read = () -> Current + Input\n"
        "        Current = 2\n    ;\n    Input = 3\n"))] == [7]


@pytest.mark.parametrize("read", [
    '() -> "%Counter"', '() -> "%{Counter + 1}"',
    'method() -> return Counter;', '() -> Query{SELECT %{Counter} AS Value}',
])
def test_reads_in_full_lambdas_and_interpolations_capture_the_local(read):
    assert len(lint(method(f"    var Counter = 1\n    val Read = {read}\n"
                           "    Counter = 2\n"))) == 1


def test_every_later_write_is_reported_once_despite_nested_loops():
    assert [d.line for d in lint(method("    var Counter = 1\n"
        "    while Flag\n        while Flag\n            Counter += 1\n"
        "            val Read = () -> Counter\n            Counter = 3\n"
        "        ;\n    ;\n    Counter = 4\n"))] == [5, 7, 10]


@pytest.mark.parametrize("body", [
    "    var Counter = 1\n    Counter = 2\n    val Read = () -> Counter\n",
    "    var Counter = 1\n    val Read = () -> Input\n    Counter = 2\n",
    '    var Counter = 1\n    val Read = () -> "Counter"\n    Counter = 2\n',
    "    var Counter = 1\n    val Read = () -> Other(Counter = 2)\n    Counter = 2\n",
    "    var Values = [1, 2]\n    val Read = () -> Values.Size()\n    Values[0] = 3\n",
    "    var Record = RecordType()\n    val Read = () -> Record.Value\n    Record.Value = 3\n",
    "    val Read = method() ->\n        var Current = 1\n        Current += 1\n        return Current\n    ;\n",
    "    var Counter = 1\n    val Write = () -> Counter = 2\n",
    "    val Read = () -> Missing\n    var Missing = 1\n    Missing = 2\n",
    "    val Counter = 1\n    val Read = () -> Counter\n    Counter = 2\n",
    "    for Index = 1 to 3\n        val Read = () -> Index\n        Index = 2\n    ;\n",
    "    for Index = 1 to 3\n        var Current = Index\n        Current += 1\n        val Read = () -> Current\n    ;\n",
    "    if Flag\n        var Current = 1\n        val Read = () -> Current\n    else\n        var Current = 2\n        Current += 1\n    ;\n",
])
def test_unrelated_bindings_earlier_writes_and_other_errors_are_not_reported(body):
    assert lint(method(body)) == []


def test_capture_of_a_block_local_does_not_escape_into_another_method():
    assert lint(method("    var Counter = 1\n    val Read = () -> Counter\n") +
                "method Next()\n    var Counter = 1\n    Counter = 2\n;\n") == []


def test_loop_local_written_after_capture_is_still_an_error():
    assert [d.line for d in lint(method("    for Index = 1 to 3\n"
        "        var Current = Index\n        val Read = () -> Current\n"
        "        Current += 1\n    ;\n"))] == [5]


def test_broken_method_is_skipped_but_other_methods_remain_checked():
    source = engine.load_text("Sample.xbsl", "method Broken()\n"
        "    var Counter = 1\n    val Read = () -> Counter\n    Counter = 2\n"
        "    var =\n;\n" + method("    var Current = 1\n"
        "    val Read = () -> Current\n    Current = 2\n"))
    diagnostics = engine.run_sources([source], select={RULE})
    assert [d.line for d in diagnostics] == [10]


@pytest.mark.parametrize("body", [
    "    val Outer = method(Current: Number) ->\n        val Read = () -> Current\n"
    "        Current = 2\n        return Read()\n    ;\n    Outer(1)\n",
    "    val Outer = method() ->\n        var Current = 1\n        val Read = () -> Current\n"
    "        Current += 2\n        return Read() + Current\n    ;\n    Outer()\n",
    "    val Outer = method() ->\n        var Current = 1\n        for Index = 1 to 3\n"
    "            Current += Index\n            val Read = () -> Current\n"
    "            Read()\n        ;\n        return Current\n    ;\n    Outer()\n",
])
def test_bindings_declared_by_a_lambda_are_not_frozen_by_nested_capture(body):
    assert lint(method(body)) == []


@pytest.mark.parametrize("exit_statement", ["break", "return"])
def test_loop_restriction_still_applies_with_an_unconditional_exit(exit_statement):
    assert [d.line for d in lint(method("    var Counter = 1\n"
        "    for Index = 1 to 3\n        Counter += Index\n"
        "        val Read = () -> Counter\n"
        f"        {exit_statement}\n    ;\n"))] == [4]


@pytest.mark.parametrize("branch", ["if Flag", "case Flag\n    when True"])
def test_earlier_sibling_write_is_allowed_when_a_later_branch_captures(branch):
    assert lint(method("    var Counter = 1\n"
        f"    {branch}\n        Counter = 2\n"
        "    else\n        val Read = () -> Counter\n    ;\n")) == []
