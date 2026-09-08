"""The `Type` of a new item comes from a CLIENT, so it is read before it is written.

The component base was fixed first (markup escapes, the spelling of another language); a field
type arrives the same way and used to be written verbatim - a file that looks finished and that
the compiler only rejects at deploy time.
"""

import pytest
import yaml

import xbsl.engine  # noqa: F401 - breaks the scaffold <-> rules import cycle
from xbsl import scaffold

# The shape the platform itself writes: a bare dash, four spaces of indent.
_CATALOG = (
    "ВидЭлемента: Справочник\n"
    "Ид: 20d26596-68fd-42d6-aef9-1eab5d73c844\n"
    "Имя: Товар\n"
    "Реквизиты:\n"
    "    -\n"
    "        Ид: 11111111-1111-1111-1111-111111111111\n"
    "        Имя: Заметка\n"
    "        Тип: Строка\n"
)


def _added(tmp_path, name, type_):
    path = tmp_path / "Товар.yaml"
    path.write_text(_CATALOG, encoding="utf-8")
    result = scaffold.op_add_field(path, "реквизит", name, type_=type_)
    data = yaml.safe_load(result.changes[0].content)
    return {item["Имя"]: item.get("Тип") for item in data["Реквизиты"]}


def test_an_escaped_type_is_read_as_the_brackets_it_stands_for(tmp_path):
    assert _added(tmp_path, "Цены", "Массив&lt;Число&gt;")["Цены"] == "Массив<Число>"


def test_a_composite_type_keeps_its_alternatives(tmp_path):
    assert _added(tmp_path, "Значение", "Строка|Число|?")["Значение"] == "Строка|Число|?"


def test_a_type_given_in_english_is_written_in_the_project_language(tmp_path):
    assert _added(tmp_path, "Вес", "Number")["Вес"] == "Число"


def test_an_author_name_is_left_alone(tmp_path):
    assert _added(tmp_path, "Владелец", "Товар.Ссылка")["Владелец"] == "Товар.Ссылка"


def test_a_type_that_is_not_a_type_expression_is_refused(tmp_path):
    with pytest.raises(scaffold.ScaffoldError):
        _added(tmp_path, "Битый", 'Массив&amp;lt;Строка"')


def test_the_value_of_a_localized_string_is_not_read_as_a_type(tmp_path):
    """The mapping branch takes TEXT, where the ampersand and the semicolon are legal."""
    path = tmp_path / "ОбщиеСтроки.yaml"
    path.write_text(
        "ВидЭлемента: ЛокализованныеСтроки\n"
        "Ид: 30d26596-68fd-42d6-aef9-1eab5d73c855\n"
        "Имя: ОбщиеСтроки\n"
        "Строки:\n"
        "    Привет: Привет\n",
        encoding="utf-8",
    )
    value = "Условия и сроки; читайте внимательно"
    result = scaffold.op_add_field(path, "строка", "Условия", type_=value)
    assert yaml.safe_load(result.changes[0].content)["Строки"]["Условия"] == value
