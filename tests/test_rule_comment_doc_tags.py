"""The tags of a documentation comment against what the environment will show (comment/doc-tag-*).

Five rules read the `///` block of a declaration through xbsl/doctags.py: a line the
environment does not take for a tag, the place of the tags inside the block, the parameter
tags against the signature, the result and exception tags against the declaration, and - over
the whole project - the names the tags point at.

The rules parse the module, so the whole module needs the data bundle (listed in
conftest._DATA_DEPENDENT).
"""

from xbsl import engine
from xbsl.cli import discover

UNKNOWN = "comment/doc-tag-unknown"
LAYOUT = "comment/doc-tag-layout"
PARAM = "comment/doc-tag-param"
RESULT = "comment/doc-tag-result"
TARGET = "comment/doc-tag-target"


def _lint(tmp_path, text: str, rule: str, name: str = "РасчетЦен.xbsl"):
    (tmp_path / name).write_bytes(text.encode("utf-8"))
    return [d for d in engine.run(discover([str(tmp_path)]), select={rule}) if d.rule_id == rule]


def _fixed(text: str, diags) -> str:
    for diag in sorted((d for d in diags if d.fix), key=lambda d: d.fix.start, reverse=True):
        text = text[: diag.fix.start] + diag.fix.new + text[diag.fix.end:]
    return text


_GOOD = """/// Цена товара со скидкой.
///
/// @параметр Цена - Цена без скидки.
/// @параметр Скидка - Скидка в процентах,
///   от нуля до ста.
///
/// @возвращает Цена со скидкой.
/// @выбрасывает ИсключениеНедопустимыйАргумент - Скидка больше ста.
/// @см ЦенаБезСкидки
@НаСервере
метод ЦенаСоСкидкой(Цена: Число, Скидка: Число): Число
    если Скидка > 100
        выбросить новый ИсключениеНедопустимыйАргумент("Скидка больше ста")
    ;
    возврат Цена * (100 - Скидка) / 100
;

/// Цена без скидки.
///
/// @параметр Цена - Цена товара.
///
/// @возвращает Та же цена.
метод ЦенаБезСкидки(Цена: Число): Число
    возврат Цена
;
"""


def test_a_well_formed_block_is_silent(tmp_path):
    for rule in (UNKNOWN, LAYOUT, PARAM, RESULT):
        assert _lint(tmp_path, _GOOD, rule) == [], rule


# --- comment/doc-tag-unknown -------------------------------------------------------------

def test_a_keyword_in_capitals_is_respelled(tmp_path):
    text = _GOOD.replace("/// @возвращает Цена со скидкой.", "/// @Возвращает Цена со скидкой.")
    diags = _lint(tmp_path, text, UNKNOWN)
    assert [(d.line, d.col) for d in diags] == [(7, 5)]
    assert "@возвращает" in diags[0].message
    assert _fixed(text, diags) == _GOOD


def test_a_foreign_short_form_is_respelled_in_the_language_of_the_module(tmp_path):
    text = _GOOD.replace("/// @параметр Цена - Цена без скидки.", "/// @param Цена - Цена без скидки.")
    diags = _lint(tmp_path, text, UNKNOWN)
    assert len(diags) == 1 and diags[0].fix.new == "параметр"
    english = (
        "/// The price.\n///\n/// @param Price - The price.\n"
        "method Price(Price: Number): Number\n    return Price\n;\n"
    )
    other = tmp_path / "en"
    other.mkdir()
    diags = _lint(other, english, UNKNOWN, name="Prices.xbsl")
    assert len(diags) == 1 and diags[0].fix.new == "parameter"


def test_an_unknown_word_after_at_is_reported_without_a_fix(tmp_path):
    text = _GOOD.replace("/// @см ЦенаБезСкидки", "/// @НаСервере вызывается из формы.")
    diags = _lint(tmp_path, text, UNKNOWN)
    assert len(diags) == 1 and diags[0].fix is None and "@НаСервере" in diags[0].message


def test_the_first_line_is_the_description_whatever_it_starts_with(tmp_path):
    text = "/// @НаСервере - только на сервере.\nметод Пересчитать()\n;\n"
    assert _lint(tmp_path, text, UNKNOWN) == []


# --- comment/doc-tag-layout --------------------------------------------------------------

def test_a_tag_on_the_first_line(tmp_path):
    text = "/// @параметр Цена - Цена.\nметод Округлить(Цена: Число): Число\n    возврат Цена\n;\n"
    diags = _lint(tmp_path, text, LAYOUT)
    assert len(diags) == 1 and (diags[0].line, diags[0].col) == (1, 5)
    assert "первую строку" in diags[0].message


def test_no_blank_line_before_the_tags_is_inserted(tmp_path):
    text = _GOOD.replace("/// Цена товара со скидкой.\n///\n", "/// Цена товара со скидкой.\n")
    diags = _lint(tmp_path, text, LAYOUT)
    assert len(diags) == 1 and diags[0].fix is not None
    assert _fixed(text, diags) == _GOOD
    indented = "структура Склад\n    /// Остаток.\n    /// @см Склады\n    пер Остаток: Число\n;\n"
    diags = _lint(tmp_path, indented, LAYOUT)
    assert _fixed(indented, diags) == indented.replace(
        "    /// @см Склады", "    ///\n    /// @см Склады")


def test_a_blank_line_before_the_tags_keeps_crlf(tmp_path):
    text = _GOOD.replace("/// Цена товара со скидкой.\n///\n", "/// Цена товара со скидкой.\n")
    crlf = text.replace("\n", "\r\n")
    (tmp_path / "РасчетЦен.xbsl").write_bytes(crlf.encode("utf-8"))
    diags = [d for d in engine.run(discover([str(tmp_path)]), select={LAYOUT})]
    assert _fixed(crlf, diags) == _GOOD.replace("\n", "\r\n")


def test_a_paragraph_after_the_tags(tmp_path):
    text = _GOOD.replace(
        "/// @см ЦенаБезСкидки\n", "/// @см ЦенаБезСкидки\n///\n/// Абзац после тегов.\n")
    diags = _lint(tmp_path, text, LAYOUT)
    assert [(d.line, d.col) for d in diags] == [(11, 5)]


def test_kinds_out_of_order(tmp_path):
    text = _GOOD.replace(
        "/// @возвращает Цена со скидкой.\n/// @выбрасывает ИсключениеНедопустимыйАргумент - "
        "Скидка больше ста.\n",
        "/// @выбрасывает ИсключениеНедопустимыйАргумент - Скидка больше ста.\n"
        "/// @возвращает Цена со скидкой.\n",
    )
    diags = _lint(tmp_path, text, LAYOUT)
    assert len(diags) == 1 and "@возвращает" in diags[0].message


def test_a_tag_without_its_text(tmp_path):
    text = _GOOD.replace("/// @см ЦенаБезСкидки", "/// @см")
    diags = _lint(tmp_path, text, LAYOUT)
    assert len(diags) == 1 and (diags[0].line, diags[0].col) == (9, 5)


def test_a_dash_other_than_a_hyphen_is_replaced(tmp_path):
    text = _GOOD.replace("/// @параметр Цена - Цена без скидки.", "/// @параметр Цена \u2013 Цена без скидки.")
    diags = _lint(tmp_path, text, LAYOUT)
    assert len(diags) == 1 and _fixed(text, diags) == _GOOD


# --- comment/doc-tag-param ---------------------------------------------------------------

def test_a_name_the_method_does_not_have(tmp_path):
    text = _GOOD.replace("/// @параметр Скидка - Скидка", "/// @параметр Скидкa - Скидка")
    diags = _lint(tmp_path, text, PARAM)
    messages = [d.message for d in diags]
    assert any("нет параметра \"Скидкa\"" in m and "Параметры метода: Скидка, Цена" in m
               for m in messages)
    assert any("нет описания у: Скидка" in m for m in messages)


def test_a_name_in_another_case_is_respelled(tmp_path):
    text = _GOOD.replace("/// @параметр Скидка - Скидка", "/// @параметр скидка - Скидка")
    diags = _lint(tmp_path, text, PARAM)
    assert len(diags) == 1 and _fixed(text, diags) == _GOOD


def test_a_name_twice_and_out_of_order(tmp_path):
    twice = _GOOD.replace(
        "/// @параметр Цена - Цена без скидки.\n",
        "/// @параметр Цена - Цена без скидки.\n/// @параметр Цена - Еще раз.\n")
    assert ["описан второй раз" in d.message for d in _lint(tmp_path, twice, PARAM)] == [True]
    swapped = _GOOD.replace(
        "/// @параметр Цена - Цена без скидки.\n/// @параметр Скидка - Скидка в процентах,\n"
        "///   от нуля до ста.\n",
        "/// @параметр Скидка - Скидка в процентах.\n/// @параметр Цена - Цена без скидки.\n")
    diags = _lint(tmp_path, swapped, PARAM)
    assert len(diags) == 1 and "в порядке сигнатуры" in diags[0].message


def test_parameters_described_in_part(tmp_path):
    text = _GOOD.replace("/// @параметр Скидка - Скидка в процентах,\n///   от нуля до ста.\n", "")
    diags = _lint(tmp_path, text, PARAM)
    assert len(diags) == 1 and "нет описания у: Скидка" in diags[0].message
    assert (diags[0].line, diags[0].col) == (3, 5)


def test_a_name_the_environment_cuts(tmp_path):
    text = (
        "/// Счетчик.\n///\n/// @параметр Счётчик - Текущее значение.\n"
        "метод Следующий(Счётчик: Число): Число\n    возврат Счётчик + 1\n;\n"
    )
    diags = _lint(tmp_path, text, PARAM)
    assert len(diags) == 1 and "\"Сч\"" in diags[0].message


def test_a_parameter_tag_above_a_field_and_no_name(tmp_path):
    field = "/// Лимит.\n///\n/// @параметр Лимит - Лимит.\nконст ЛИМИТ = 10\n"
    diags = _lint(tmp_path, field, PARAM)
    assert len(diags) == 1 and "не метод" in diags[0].message
    nameless = _GOOD.replace("/// @параметр Цена - Цена товара.", "/// @параметр")
    diags = _lint(tmp_path, nameless, PARAM)
    assert any("нет имени параметра" in d.message for d in diags)


def test_a_method_without_parameters(tmp_path):
    text = "/// Сброс.\n///\n/// @параметр Режим - Режим.\nметод Сбросить()\n;\n"
    diags = _lint(tmp_path, text, PARAM)
    assert len(diags) == 1 and "нет параметров" in diags[0].message


def test_a_structure_and_its_constructor_are_not_judged(tmp_path):
    text = (
        "/// Точка.\n///\n/// @параметр X - Абсцисса.\n/// @возвращает Точку.\n"
        "структура Точка\n    пер X: Число\n    /// Создает точку.\n    ///\n"
        "    /// @параметр X - Абсцисса.\n    конструктор\n;\n"
    )
    assert _lint(tmp_path, text, PARAM) == []
    assert _lint(tmp_path, text, RESULT) == []


# --- comment/doc-tag-result --------------------------------------------------------------

def test_a_result_tag_above_a_method_without_a_result(tmp_path):
    for head in ("метод Сбросить(Режим: Число)", "метод Сбросить(Режим: Число): ничто"):
        text = f"/// Сброс.\n///\n/// @параметр Режим - Режим.\n/// @возвращает Ничего.\n{head}\n;\n"
        diags = _lint(tmp_path, text, RESULT)
        assert len(diags) == 1 and "не возвращает значения" in diags[0].message, head


def test_two_result_tags(tmp_path):
    text = _GOOD.replace("/// @возвращает Та же цена.\n", "/// @возвращает Та же цена.\n/// @возвращает Еще.\n")
    diags = _lint(tmp_path, text, RESULT)
    assert len(diags) == 1 and diags[0].line == 23


def test_an_exception_type_the_environment_cuts(tmp_path):
    text = _GOOD.replace("@выбрасывает ИсключениеНедопустимыйАргумент", "@выбрасывает Цены.ОшибкаСкидки")
    diags = _lint(tmp_path, text, RESULT)
    assert len(diags) == 1 and "\"Цены\"" in diags[0].message
    assert (diags[0].line, diags[0].col) == (8, 18)


def test_result_tags_above_a_field(tmp_path):
    text = "/// Лимит.\n///\n/// @возвращает Число.\nконст ЛИМИТ = 10\n"
    diags = _lint(tmp_path, text, RESULT)
    assert len(diags) == 1 and "не метод" in diags[0].message


# --- comment/doc-tag-target --------------------------------------------------------------

_ELEMENT = "ВидЭлемента: ОбщийМодуль\nИд: 00000000-0000-0000-0000-000000000001\nИмя: Склады\n"
_STOCK = """/// Остаток на складе.
///
/// @параметр Код - Код товара.
///
/// @возвращает Остаток.
/// @выбрасывает ИсключениеСклада - Склад закрыт.
/// @см {see}
метод Остаток(Код: Строка): Число
    если Код == ""
        выбросить новый ИсключениеСклада("Склад закрыт")
    ;
    возврат 0
;

/// Склад закрыт.
исключение ИсключениеСклада
;

/// Резерв товара.
метод Резерв(): Число
    возврат 0
;
"""


def _project(tmp_path, see: str, throws: str = "ИсключениеСклада"):
    (tmp_path / "Склады.yaml").write_bytes(_ELEMENT.encode("utf-8"))
    text = _STOCK.format(see=see).replace(
        "/// @выбрасывает ИсключениеСклада", f"/// @выбрасывает {throws}")
    (tmp_path / "Склады.xbsl").write_bytes(text.encode("utf-8"))
    return [d for d in engine.run(discover([str(tmp_path)]), select={TARGET})]


def test_references_that_resolve_are_silent(tmp_path):
    for see in ("Резерв", "Склады", "Склады.Резерв", "Строка", "Раздел о ценах", "документацию",
                "OpenAPI"):
        assert _project(tmp_path, see) == [], see
    assert _project(tmp_path, "Резерв", throws="ИсключениеВыполнения") == []


def test_a_reference_to_a_name_nobody_has(tmp_path):
    diags = _project(tmp_path, "РезервСтарый")
    assert len(diags) == 1 and "\"РезервСтарый\"" in diags[0].message
    assert (diags[0].line, diags[0].col) == (7, 9)


def test_a_reference_to_a_member_the_owner_lacks(tmp_path):
    diags = _project(tmp_path, "Склады.РезервСтарый")
    assert len(diags) == 1 and "у \"Склады\" нет \"РезервСтарый\"" in diags[0].message


def test_an_exception_type_nobody_declares_lists_what_the_body_throws(tmp_path):
    diags = _project(tmp_path, "Резерв", throws="ИсключениеСкладаСтарое")
    assert len(diags) == 1
    assert "ИсключениеСкладаСтарое" in diags[0].message
    assert "Тело метода выбрасывает: ИсключениеСклада." in diags[0].message
