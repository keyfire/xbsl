"""Localizable-typed yaml values and the data-value guard of the literals plane.

A presentation the metamodel types `Localizable` is read by a person on the page, so it goes
through the literals plane like a presentation template: named whole or reported as a gap.
The documentation properties (`Description`) stay data. And a code literal spelled exactly
like a VALUE of a json resource is usually compared against that data - moving it by a
dictionary entry draws a warning, because the data side never moves.

The deprecation mark at the head of a text is the engine's own to translate: an English
project marks a deprecated element with "(not used)" (naming/presentation), so the translated
tree carries that mark whether the entry of the text wrote it, left it out or is missing.
"""

import pytest

from xbsl import engine
from xbsl.translation import dictionary as dict_module
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml


def _dictionary(tokens=None, literals=None):
    return dict_module.Dictionary(
        tokens=dict(tokens or {}), phrases={}, literals=dict(literals or {}),
    )


def _yaml(text, name, tokens=None, literals=None):
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    return translate_yaml(source, Resolver(_dictionary(tokens, literals)), report), report


def _code(text, tokens=None, literals=None, data_values=frozenset()):
    source = engine.load_text("Модуль.xbsl", text)
    report = FileReport(path="Модуль.xbsl")
    resolver = Resolver(_dictionary(tokens, literals), data_values=frozenset(data_values))
    return translate_code(source, resolver, report), report


_PRIVILEGE = '''ВидЭлемента: ПравоНаДействие
Имя: ПравоНаНаполнение
Представление: Наполнение демо-данными
'''

_PRIVILEGE_TOKENS = {"ПравоНаНаполнение": "DemoFillingPrivilege"}


def test_a_localizable_presentation_takes_its_text_from_the_literals_plane():
    out, report = _yaml(
        _PRIVILEGE, "ПравоНаНаполнение.yaml", tokens=_PRIVILEGE_TOKENS,
        literals={"Наполнение демо-данными": "Demo data filling"},
    )
    assert "Demo data filling" in out
    assert report.missing_literals == {}
    assert report.texts_kept == []


def test_a_localizable_presentation_without_an_entry_is_a_gap():
    _out, report = _yaml(_PRIVILEGE, "ПравоНаНаполнение.yaml", tokens=_PRIVILEGE_TOKENS)
    assert "Наполнение демо-данными" in report.missing_literals
    assert report.texts_kept == []


def test_a_dollar_reference_presentation_stays_a_reference():
    # A presentation bound to a localized string is two NAMES, not prose: the reference
    # follows the renames and asks the literals plane for nothing.
    body = _PRIVILEGE.replace("Наполнение демо-данными", "$Локализация.Наполнение")
    _out, report = _yaml(
        body, "ПравоНаНаполнение.yaml",
        tokens={**_PRIVILEGE_TOKENS, "Локализация": "Localization", "Наполнение": "Filling"},
    )
    assert report.missing_literals == {}


_EVENT = '''ВидЭлемента: ВидСобытияЖурнала
Имя: ЗапускЗадачи
Описание: Событие регистрируется при каждом запуске задачи.
'''


def test_an_event_description_is_documentation_and_stays_data():
    _out, report = _yaml(_EVENT, "ЗапускЗадачи.yaml", tokens={"ЗапускЗадачи": "TaskStart"})
    assert report.missing_literals == {}
    assert any("Событие регистрируется" in text for text, _line, _col in report.texts_kept)


_DEPRECATED_REGISTER = '''ВидЭлемента: РегистрСведений
Имя: УстарелоКурсы
Интерфейс:
    Список:
        Представление: {caption}
'''

_DEPRECATED_TOKENS = {"УстарелоКурсы": "DeprecatedRates"}


def _deprecated_caption(caption: str, literals=None):
    """The translated list caption of a deprecated register, and the report."""
    out, report = _yaml(_DEPRECATED_REGISTER.format(caption=caption), "УстарелоКурсы.yaml",
                        tokens=_DEPRECATED_TOKENS, literals=literals)
    line = next(line for line in out.splitlines() if line.strip().startswith("Presentation:"))
    return line.split(":", 1)[1].strip(), report


def test_an_entry_that_left_the_deprecation_mark_out_gets_it_in_front():
    caption, report = _deprecated_caption(
        "(не используется) Курсы валют",
        literals={"(не используется) Курсы валют": "Exchange rates"},
    )
    assert caption == "(not used) Exchange rates"
    assert report.missing_literals == {}


@pytest.mark.parametrize("entry, expected", [
    ("(not used) Exchange rates", "(not used) Exchange rates"),
    # The Russian head copied into the entry gives way to the English one.
    ("(не используется) Exchange rates", "(not used) Exchange rates"),
    # A bracket of its own is the entry's rendering of the mark: written as the entry says,
    # and naming/presentation reports it on the translated tree.
    ("(deprecated) Exchange rates", "(deprecated) Exchange rates"),
])
def test_an_entry_that_heads_its_text_itself_keeps_it(entry, expected):
    caption, _report = _deprecated_caption(
        "(не используется) Курсы валют", literals={"(не используется) Курсы валют": entry},
    )
    assert caption == expected


def test_a_marked_text_without_an_entry_is_still_a_gap_under_the_english_mark():
    caption, report = _deprecated_caption("(не используется) Курсы валют")
    assert caption == "(not used) Курсы валют"
    # The gap is the whole text, as the dictionary keys it.
    assert list(report.missing_visible_literals) == ["(не используется) Курсы валют"]


def test_a_text_that_is_the_mark_alone_needs_no_entry():
    caption, report = _deprecated_caption("(не используется)")
    assert caption == "(not used)"
    assert report.missing_literals == {}


def test_a_mark_that_does_not_head_the_text_is_not_the_deprecation_mark():
    caption, _report = _deprecated_caption(
        "Курсы валют (не используется)",
        literals={"Курсы валют (не используется)": "Exchange rates"},
    )
    assert caption == "Exchange rates"


def test_the_mark_of_a_presentation_kept_as_data_is_translated_too():
    # The presentation of a report is typed a plain string, so it stays data - all but the
    # mark at its head, which naming/presentation reads there as well.
    text = "ВидЭлемента: Отчет\nИмя: УстарелоСверка\nПредставление: (не используется) Сверка\n"
    out, report = _yaml(text, "УстарелоСверка.yaml", tokens={"УстарелоСверка": "DeprecatedCheck"})
    assert "Presentation: (not used) Сверка" in out
    assert [kept for kept, _line, _col in report.texts_kept] == ["(не используется) Сверка"]


_PARSE = '''метод ИзСтроки(Код: Строка): Число
    выбор Код
    когда "Сбоку"
        возврат 1
    иначе
        возврат 0
    ;
;
'''

_PARSE_TOKENS = {"ИзСтроки": "FromString", "Код": "Code"}


def test_a_literal_that_doubles_a_json_value_draws_a_warning_when_moved():
    out, report = _code(
        _PARSE, tokens=_PARSE_TOKENS,
        literals={"Сбоку": "Side"}, data_values={"Сбоку"},
    )
    assert '"Side"' in out
    assert [w[0] for w in report.warnings] == ["literal-data-value"]
    assert report.warnings[0][3] == "Сбоку"


def test_an_entry_equal_to_its_key_marks_data_and_draws_no_warning():
    out, report = _code(
        _PARSE, tokens=_PARSE_TOKENS,
        literals={"Сбоку": "Сбоку"}, data_values={"Сбоку"},
    )
    assert '"Сбоку"' in out
    assert report.warnings == []
    assert report.missing_literals == {}


def test_a_moved_literal_that_matches_no_data_value_is_quiet():
    _out, report = _code(_PARSE, tokens=_PARSE_TOKENS, literals={"Сбоку": "Side"})
    assert report.warnings == []


def test_duration_suffixes_move_to_english():
    out, _report = _code('''метод Пауза(): Длительность
    знч Короткая = 300мс
    знч Сборная = 2д14ч30м5с6мс
    возврат Короткая + Сборная + 0с
;
''', tokens={"Пауза": "Pause", "Короткая": "Short", "Сборная": "Combined"})
    assert "300ms" in out and "2d14h30m5s6ms" in out and "0s" in out


def test_non_duration_number_letters_stay():
    # A number glued to letters outside the duration set is not the pass's to touch.
    out, _report = _code('''метод Предел(): Строка
    возврат "%{50мб}"
;
''', tokens={"Предел": "Limit"})
    assert "50мб" in out
