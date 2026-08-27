"""Localizable-typed yaml values and the data-value guard of the literals plane.

A presentation the metamodel types `Localizable` is read by a person on the page, so it goes
through the literals plane like a presentation template: named whole or reported as a gap.
The documentation properties (`Description`) stay data. And a code literal spelled exactly
like a VALUE of a json resource is usually compared against that data - moving it by a
dictionary entry draws a warning, because the data side never moves.
"""

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
