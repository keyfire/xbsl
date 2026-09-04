"""code/member-kind-mismatch: a stdlib method read as a property, and the other way round.

The member EXISTS - that is the neighbouring check's job - and what is wrong is the form. A
probe on a throwaway application answered `Unknown constant "ЧасовойПояс.Текущий"` for a
method read without parentheses and `Unknown method "ЧасовойПояс.Имя"` for a property called;
the control, the method called and the property read, compiled.

The catalog says which is which: of 5057 members only nine carry both kinds on one type, all
of them form commands, and those are left alone.
"""

import pytest

from xbsl import engine
from xbsl.cli import discover

RULE = "code/member-kind-mismatch"

pytestmark = pytest.mark.needs_data


def _lint(tmp_path, module: str):
    (tmp_path / "Модуль.yaml").write_text(
        "ВидЭлемента: ОбщийМодуль\nИмя: Модуль\nОкружение: Сервер\n", encoding="utf-8")
    (tmp_path / "Модуль.xbsl").write_text(module, encoding="utf-8")
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE})]


def test_a_method_read_as_a_property_is_found(tmp_path):
    d = _lint(tmp_path, "@НаСервере\nметод Ф()\n    знч Пояс = ЧасовойПояс.Текущий\n;\n")

    assert len(d) == 1
    assert "МЕТОД" in d[0].message and "Текущий" in d[0].message


def test_a_property_called_as_a_method_is_found(tmp_path):
    module = ("@НаСервере\nметод Ф(): Строка\n"
              "    знч Пояс = ЧасовойПояс.Текущий()\n    возврат Пояс.Имя()\n;\n")

    d = _lint(tmp_path, module)

    assert len(d) == 1
    assert "СВОЙСТВО" in d[0].message and "Имя" in d[0].message


def test_the_right_forms_are_silent(tmp_path):
    """The control: the method called and the property read - this compiles."""
    module = ("@НаСервере\nметод Ф(): Строка\n"
              "    знч Пояс = ЧасовойПояс.Текущий()\n    возврат Пояс.Имя\n;\n")

    assert _lint(tmp_path, module) == []


def test_a_member_the_type_does_not_have_is_left_to_its_own_check(tmp_path):
    """A missing member belongs to code/unknown-static-member, not here."""
    d = _lint(tmp_path, "@НаСервере\nметод Ф()\n    знч Х = ЧасовойПояс.НетТакого\n;\n")

    assert d == []


def test_a_name_the_project_shadows_is_not_read_as_a_type(tmp_path):
    """An object named like a platform type owns the name - the same rule as next door."""
    (tmp_path / "ЧасовойПояс.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: ЧасовойПояс\nПредставление: Наименование\n",
        encoding="utf-8")

    d = _lint(tmp_path, "@НаСервере\nметод Ф()\n    знч Х = ЧасовойПояс.Текущий\n;\n")

    assert d == []


def test_the_name_shadow_survives_windows_line_endings(tmp_path):
    """A CRLF checkout used to lose the shadow set whole - and an empty shadow is a finding.

    In multiline mode the end anchor matches before the line feed, and the carriage return
    stood exactly where the pattern expected the end of the line. The rule that reads those
    names is an ERROR one, so the loss showed up as a false refusal of ordinary code.
    """
    (tmp_path / "ЧасовойПояс.yaml").write_bytes(
        "ВидЭлемента: Справочник\r\nИмя: ЧасовойПояс\r\n".encode("utf-8"))

    d = _lint(tmp_path, "@НаСервере\nметод Ф()\n    знч Х = ЧасовойПояс.Текущий\n;\n")

    assert d == []
