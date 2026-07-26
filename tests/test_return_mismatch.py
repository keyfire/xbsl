"""Tests of the code/return-mismatch rule: a return must agree with the method signature."""

from __future__ import annotations

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/return-mismatch"}, scopes=("file",)))


def test_value_in_void_method():
    diags = _lint(
        "метод Тест()\n"
        "    возврат 5\n"
        ";\n"
    )
    assert len(diags) == 1
    assert diags[0].severity.value == "error"


def test_empty_return_in_typed_method():
    diags = _lint(
        "метод Тест(): Число\n"
        "    возврат\n"
        ";\n"
    )
    assert len(diags) == 1
    assert "Число" in diags[0].message


def test_matching_returns_are_fine():
    diags = _lint(
        "метод Ничто(Х: Число)\n"
        "    если Х > 0\n"
        "        возврат\n"
        "    ;\n"
        ";\n"
        "метод Типизированный(): Число\n"
        "    возврат 5\n"
        ";\n"
    )
    assert diags == [], [d.message for d in diags]


def test_lambda_is_its_own_context():
    # returning a value inside a lambda body does not belong to the enclosing void method
    diags = _lint(
        "метод Тест()\n"
        "    знч Ф = метод () ->\n"
        "        возврат 5\n"
        "    ;\n"
        ";\n"
    )
    assert diags == []


def test_struct_methods_are_checked():
    diags = _lint(
        "структура Точка\n"
        "    знч Х: Число = 0\n"
        "    метод Имя(): Строка\n"
        "        возврат\n"
        "    ;\n"
        ";\n"
    )
    assert len(diags) == 1


def test_broken_file_is_left_to_parse_error():
    diags = _lint(
        "метод Тест(): Число\n"
        "    возврат (\n"
        ";\n"
    )
    assert diags == []
