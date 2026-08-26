"""Named groups of a pattern and the presentation template of an event kind.

Both sides of a group name - the declaration inside the pattern and the reading call - have to
move by one dictionary entry, and the prose of a presentation template has to come from the
literals plane instead of staying in the source language silently.
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


def _code(text, tokens=None, literals=None):
    source = engine.load_text("Модуль.xbsl", text)
    report = FileReport(path="Модуль.xbsl")
    return translate_code(source, Resolver(_dictionary(tokens, literals)), report), report


def _yaml(text, name, tokens=None, literals=None):
    source = engine.load_text(name, text)
    report = FileReport(path=name)
    return translate_yaml(source, Resolver(_dictionary(tokens, literals)), report), report


_PARSE = '''метод Разобрать(Текст: Строка): Строка
    знч Найденное = новый Образец("(?<Ключ>[a-z]+)").Найти(Текст)
    возврат Найденное.Группа("Ключ") ?? ""
;
'''

_TOKENS = {"Разобрать": "Parse", "Текст": "Text", "Найденное": "Found", "Ключ": "Key"}


def test_named_group_and_its_reader_move_together():
    out, _report = _code(_PARSE, tokens=_TOKENS)
    assert '(?<Key>[a-z]+)' in out
    assert '.Group("Key")' in out


def test_both_sides_of_a_group_name_answer_alike():
    # The literals plane answers first and answers BOTH sides: a project that already spelled a
    # pattern by hand named its group there. Which spelling wins matters less than that one wins
    # for both - part them, and the call asks for a group the pattern never declared.
    out, _report = _code(_PARSE, tokens=_TOKENS, literals={"Ключ": "Другое"})
    assert '(?<Другое>[a-z]+)' in out
    assert '.Group("Другое")' in out


def test_group_name_without_an_entry_is_reported():
    # The name has to be the project's own: a name the platform tables already know answers by
    # itself and leaves no gap for the project dictionary to fill.
    _out, report = _code(_PARSE.replace("Ключ", "Слаг"), tokens={"Разобрать": "Parse"})
    assert "Слаг" in report.missing_tokens


def test_ascii_group_name_is_left_alone():
    out, _report = _code('''метод Разобрать(Текст: Строка): Строка
    возврат новый Образец("(?<key>[a-z]+)").Найти(Текст).Группа("key") ?? ""
;
''', tokens={"Разобрать": "Parse", "Текст": "Text"})
    assert '(?<key>[a-z]+)' in out and '.Group("key")' in out


def test_a_pattern_literal_is_judged_too():
    # A single-quoted literal is a PATTERN token of its own, not a string - the branch that
    # translates group names has to cover it, or a project writing patterns that way keeps the
    # declaration in one language and the call in the other.
    out, _report = _code('''метод Разобрать(Текст: Строка): Строка
    возврат Текст.Найти('(?<Ключ>[a-z]+)').Группа("Ключ") ?? ""
;
''', tokens=_TOKENS)
    assert "(?<Key>[a-z]+)" in out and '.Group("Key")' in out


_EVENT = '''ВидЭлемента: ВидСобытияЖурнала
Имя: ЗапускЗадачи
ШаблонПредставления: "Запуск %{Логин}"
'''

_EVENT_TOKENS = {"ЗапускЗадачи": "TaskStart", "Логин": "Login"}


def test_presentation_template_takes_its_prose_from_the_literals_plane():
    out, report = _yaml(
        _EVENT, "ЗапускЗадачи.yaml", tokens=_EVENT_TOKENS,
        literals={"Запуск %{Логин}": "Start of %{Логин}"},
    )
    assert '"Start of %{Login}"' in out
    assert report.missing_literals == {}


def test_presentation_template_without_an_entry_is_reported_as_a_gap():
    out, report = _yaml(_EVENT, "ЗапускЗадачи.yaml", tokens=_EVENT_TOKENS)
    assert '"Запуск %{Login}"' in out, "выражение внутри шаблона переводится как прежде"
    assert "Запуск %{Логин}" in report.missing_literals


def test_a_template_of_expressions_alone_asks_for_nothing():
    # Cyrillic inside the expressions alone: the interpolation pass has already moved it, and
    # there is nothing left in it for a person to name.
    body = _EVENT.replace('"Запуск %{Логин}"', '"%{Логин}/%{Раздел}"')
    _out, report = _yaml(
        body, "ЗапускЗадачи.yaml",
        tokens={**_EVENT_TOKENS, "Раздел": "Section"},
    )
    assert report.missing_literals == {}
