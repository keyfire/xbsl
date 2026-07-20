"""Tests of the code/catch-non-exception rule: the type in 'поймать' must be an exception.

The rule only proves the negative: a finding requires the type to be KNOWN as a
non-exception (a stdlib type without an exception signature, or a local 'структура').
"""

from __future__ import annotations

import pytest

from xbsl.diagnostics import Diagnostic
from xbsl.engine import load_text, run_sources


def _lint(code: str) -> list[Diagnostic]:
    src = load_text("Модуль.xbsl", code)
    return list(run_sources([src], select={"code/catch-non-exception"}, scopes=("file",)))


def _try(catch: str) -> str:
    return (
        "метод Тест()\n"
        "    попытка\n"
        "        Ф()\n"
        f"    поймать Ошибка: {catch}\n"
        "        Сообщить(Ошибка.Описание)\n"
        "    ;\n"
        ";\n"
    )


def test_stdlib_non_exception_is_flagged():
    diags = _lint(_try("Строка"))
    assert len(diags) == 1
    assert "Строка" in diags[0].message


def test_stdlib_exceptions_pass():
    assert _lint(_try("Исключение")) == []
    assert _lint(_try("ИсключениеHttp")) == []


def test_local_structure_is_flagged_and_local_exception_passes():
    base = (
        "структура Точка\n"
        "    знч Х: Число = 0\n"
        ";\n"
        "исключение ИсключениеСвоё\n"
        ";\n"
    )
    assert len(_lint(base + _try("Точка"))) == 1
    assert _lint(base + _try("ИсключениеСвоё")) == []


def test_unknown_project_type_is_silent():
    # a type from another module is invisible to the rule - do not raise false accusations
    assert _lint(_try("ЧужоеИсключениеПроекта")) == []


def test_catch_without_type_is_fine():
    diags = _lint(
        "метод Тест()\n"
        "    попытка\n"
        "        Ф()\n"
        "    поймать Ошибка\n"
        "        Сообщить(Ошибка.Описание)\n"
        "    ;\n"
        ";\n"
    )
    assert diags == []


def test_exception_set_comes_from_the_hierarchy():
    """Исключение опознаётся наследованием, а не набором свойств.

    Раньше признаком была сигнатура (Описание, Причина, ПоследовательностьВызовов) -
    она отбирает те же типы, но приняла бы и любой будущий тип, который просто похож
    на исключение. Каталог хранит цепочку предков, и ответ даёт платформа.
    """
    from xbsl.rules import catch_exceptions

    catch_exceptions._cache = None
    known, exceptions = catch_exceptions._stdlib_sets()
    if not known:
        pytest.skip("нет данных Элемента")
    assert "Исключение" in exceptions  # сам корень
    assert "ИсключениеНедопустимыйАргумент" in exceptions  # наследник
    assert "Строка" not in exceptions
    assert exceptions <= known


def test_signature_fallback_without_hierarchy(monkeypatch):
    """Данные старого экстрактора без bases: правило работает по прежнему признаку."""
    from xbsl.rules import catch_exceptions

    catalog = {
        "type_members": {
            "МоёИсключение": {"properties": ["Описание", "Причина", "ПоследовательностьВызовов"]},
            "Строка": {"methods": ["Длина"]},
        },
    }
    monkeypatch.setattr(catch_exceptions.dataset, "load_json", lambda name: catalog)
    catch_exceptions._cache = None
    known, exceptions = catch_exceptions._stdlib_sets()
    catch_exceptions._cache = None
    assert exceptions == {"МоёИсключение"}
    assert known == {"МоёИсключение", "Строка"}
