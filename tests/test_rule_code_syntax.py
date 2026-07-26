"""Basic syntax (xbsl/rules/code_syntax.py): untyped parameters and the loop header.

The rules are deliberately narrow: the proof of their safety is silence on the forms the
platform allows (a parameter without a type but with a default value; both kinds of the
`для` loop).
"""

import pytest

from xbsl.engine import load_text, run_sources


def _diags(code: str, rule: str) -> list:
    src = load_text("Модуль.xbsl", code)
    return [d for d in run_sources([src], select={rule}, scopes=("file",))]


pytestmark = pytest.mark.needs_data


# --- untyped parameter --------------------------------------------------------------------


def test_param_without_type_and_default_is_error():
    diags = _diags("метод Тест(А, Б: Строка)\n    возврат\n;\n", "code/param-type-required")
    assert len(diags) == 1
    assert diags[0].severity.value == "error"
    assert "'А'" in diags[0].message


def test_param_without_type_but_with_default_is_allowed():
    # The type is inferred from the default value - this is how real-world code is written.
    code = "метод Тест(Имя: Строка, ЭтоЛК = Истина, Флаг=Ложь)\n    возврат\n;\n"
    assert _diags(code, "code/param-type-required") == []


def test_typed_params_and_keyword_named_params_are_quiet():
    # A parameter name may coincide with a keyword: `Запрос`, `Метод`.
    code = (
        "метод Пинг(Запрос: HttpСервисЗапрос)\n    возврат\n;\n\n"
        "метод Вызов(Метод: Строка, Тело: Строка = \"\"): Строка\n    возврат Метод\n;\n"
    )
    assert _diags(code, "code/param-type-required") == []


def test_constructor_params_checked_too():
    diags = _diags("конструктор Тест(Значение)\n    возврат\n;\n", "code/param-type-required")
    assert len(diags) == 1


# --- string escapes -------------------------------------------------------------------------


def test_invalid_escape_is_reported():
    # the combat case: apostrophes escaped the CSS way (\') - the compiler rejects the literal
    code = "метод Т(): Строка\n    возврат \"стиль: \\'кавычки\\'\"\n;\n"
    diags = _diags(code, "code/invalid-string-escape")
    assert len(diags) == 2
    assert "\\'" in diags[0].message and diags[0].severity.value == "error"


def test_valid_escapes_are_quiet():
    code = (
        'метод Т(): Строка\n'
        '    пер А = "C:\\\\кат\\\\ф \\"имя\\" \\н\\в\\т \\% \\$ \\ю1080 \\n\\r\\t \\u1080"\n'
        "    возврат А\n;\n"
    )
    assert _diags(code, "code/invalid-string-escape") == []


def test_interpolation_span_is_skipped():
    # a pattern literal inside an interpolation carries regex escapes - not this rule's field
    code = "метод Т(С: Строка): Строка\n    возврат \"число: ${С.Совпадает('\\d+')}\"\n;\n"
    assert _diags(code, "code/invalid-string-escape") == []


def test_unicode_escape_requires_digits():
    diags = _diags('метод Т(): Строка\n    возврат "\\юня"\n;\n', "code/invalid-string-escape")
    assert len(diags) == 1


def test_pattern_literal_is_not_judged():
    code = "метод Т(С: Строка): Булево\n    возврат С.Совпадает('\\d+')\n;\n"
    assert _diags(code, "code/invalid-string-escape") == []


# --- loop header --------------------------------------------------------------------------


def test_for_in_and_for_counter_are_quiet():
    code = (
        "метод Тест(Данные: ЧитаемыйМассив<Строка>)\n"
        "    для Элемент из Данные\n"
        "        Сообщить(Элемент)\n"
        "    ;\n"
        "    для Индекс = 1 по 10\n"
        "        Сообщить(Индекс.ВСтроку())\n"
        "    ;\n"
        "    для Обратный = 10 вниз по 1 шаг 2\n"
        "        Сообщить(Обратный.ВСтроку())\n"
        "    ;\n"
        ";\n"
    )
    assert _diags(code, "code/loop-header") == []


def test_for_without_in_is_error():
    code = (
        "метод Тест(Данные: ЧитаемыйМассив<Строка>)\n"
        "    для Элемент Данные\n"
        "        Сообщить(Элемент)\n"
        "    ;\n"
        ";\n"
    )
    diags = _diags(code, "code/loop-header")
    assert len(diags) == 1
    assert diags[0].severity.value == "error"
    assert "Элемент" in diags[0].message and "из" in diags[0].message


def test_query_dsl_for_is_not_touched():
    # Inside Запрос{...} the query-language words are not parsed as a loop.
    code = (
        "метод Тест()\n"
        "    знч Р = Запрос{ ВЫБРАТЬ Т.Ссылка ИЗ Товары КАК Т }\n"
        "    возврат Р\n"
        ";\n"
    )
    assert _diags(code, "code/loop-header") == []
