"""Tests of code/load-object-unwrap: a force-unwrapped `ЗагрузитьОбъект()` on a stored reference.

The rule flags `X.Поле!.ЗагрузитьОбъект()!` - the reference comes out of a FIELD of another
record or of a tabular-section row, so it may dangle after a physical deletion, and the `!`
on the load result then throws and fails the whole pass. A bare variable receiver and the
row's own reference member are deliberately silent.
"""

from __future__ import annotations

import pytest

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/load-object-unwrap"}, scopes=("file",)))


def _method(body: str) -> str:
    return f"метод Тест()\n    {body}\n;\n"


@pytest.mark.needs_data
def test_unwrap_of_field_reference_is_flagged():
    diags = _lint(_method("знч Код = СтрокаСервиса.Сервис!.ЗагрузитьОбъект()!.Код"))
    assert len(diags) == 1
    assert "Сервис" in diags[0].message
    assert "ЗагрузитьОбъект" in diags[0].message


@pytest.mark.needs_data
def test_field_without_receiver_unwrap_is_flagged_too():
    assert len(_lint(_method("знч Имя = Строчка.Программа.ЗагрузитьОбъект()!.Имя"))) == 1


@pytest.mark.needs_data
def test_call_receiver_chain_end_is_flagged():
    # The member access sits on a call result - the field is still stored data.
    assert len(_lint(_method("знч Код = ПолучитьСтроку().Поле!.ЗагрузитьОбъект()!.Код"))) == 1


@pytest.mark.needs_data
def test_lock_argument_does_not_hide_the_unwrap():
    assert len(_lint(_method("знч Объект = Строка.Поле!.ЗагрузитьОбъект(Истина)!"))) == 1


@pytest.mark.needs_data
def test_own_reference_field_is_silent():
    # The row's own reference of a query result is alive by construction.
    assert _lint(_method("знч Объект = Строка.Ссылка.ЗагрузитьОбъект()!")) == []


@pytest.mark.needs_data
def test_bare_variable_receiver_is_silent():
    assert _lint(_method("знч Объект = Ссылка.ЗагрузитьОбъект()!")) == []
    assert _lint(_method("знч Объект = СсылкаТовара.ЗагрузитьОбъект()!")) == []


@pytest.mark.needs_data
def test_no_unwrap_on_result_is_silent():
    assert _lint(_method("знч Объект = СтрокаСервиса.Сервис!.ЗагрузитьОбъект()")) == []


@pytest.mark.needs_data
def test_method_call_receiver_is_silent():
    # The reference is answered by a call, not read from a field - out of the narrow shape.
    assert _lint(_method("знч Объект = Строка.ПолучитьСервис()!.ЗагрузитьОбъект()!")) == []


@pytest.mark.needs_data
def test_inequality_after_call_is_not_an_unwrap():
    # `!=` is a single token: comparing the result IS the cure, not the defect.
    assert _lint(_method("знч Есть = Строка.Сервис!.ЗагрузитьОбъект() != Неопределено")) == []


@pytest.mark.needs_data
def test_comment_and_string_are_silent():
    code = (
        "метод Тест()\n"
        "    // Строка.Сервис!.ЗагрузитьОбъект()!\n"
        "    знч Текст = \"Строка.Сервис!.ЗагрузитьОбъект()!\"\n"
        ";\n"
    )
    assert _lint(code) == []


@pytest.mark.needs_data
def test_english_spellings_come_from_the_data():
    diags = _lint(_method("знч Code = Row.Service!.LoadObject()!.Code"))
    assert len(diags) == 1
    assert "Service" in diags[0].message


@pytest.mark.needs_data
def test_english_own_reference_is_silent():
    assert _lint(_method("знч Object = Row.Reference.LoadObject()!")) == []
