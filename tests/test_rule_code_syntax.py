"""Базовый синтаксис (xbsl/rules/code_syntax.py): параметры без типа и заголовок цикла.

Правила намеренно узкие: доказательство их безопасности – молчание на формах, которые
платформа допускает (параметр без типа, но со значением по умолчанию; оба вида цикла `для`).
"""

import pytest

from xbsl.engine import load_text, run_sources


def _diags(code: str, rule: str) -> list:
    src = load_text("Модуль.xbsl", code)
    return [d for d in run_sources([src], select={rule}, scopes=("file",))]


pytestmark = pytest.mark.needs_data


# --- параметр без типа --------------------------------------------------------------------


def test_param_without_type_and_default_is_error():
    diags = _diags("метод Тест(А, Б: Строка)\n    возврат\n;\n", "code/param-type-required")
    assert len(diags) == 1
    assert diags[0].severity.value == "error"
    assert "'А'" in diags[0].message


def test_param_without_type_but_with_default_is_allowed():
    # Тип выводится из значения по умолчанию – так пишет рабочий код.
    code = "метод Тест(Имя: Строка, ЭтоЛК = Истина, Флаг=Ложь)\n    возврат\n;\n"
    assert _diags(code, "code/param-type-required") == []


def test_typed_params_and_keyword_named_params_are_quiet():
    # Имя параметра может совпадать с ключевым словом: `Запрос`, `Метод`.
    code = (
        "метод Пинг(Запрос: HttpСервисЗапрос)\n    возврат\n;\n\n"
        "метод Вызов(Метод: Строка, Тело: Строка = \"\"): Строка\n    возврат Метод\n;\n"
    )
    assert _diags(code, "code/param-type-required") == []


def test_constructor_params_checked_too():
    diags = _diags("конструктор Тест(Значение)\n    возврат\n;\n", "code/param-type-required")
    assert len(diags) == 1


# --- заголовок цикла ----------------------------------------------------------------------


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
    # Внутри Запрос{...} слова языка запросов не разбираются как цикл.
    code = (
        "метод Тест()\n"
        "    знч Р = Запрос{ ВЫБРАТЬ Т.Ссылка ИЗ Товары КАК Т }\n"
        "    возврат Р\n"
        ";\n"
    )
    assert _diags(code, "code/loop-header") == []
