"""translation/english-shape: traces of a mechanical replacement in the English dictionary values.

`xbsl translate --strict` judges the coverage of a dictionary, never its text, so a value with an
ending glued onto an adverb passes it. The rule reads the values of the dictionary files as yaml
and needs no Element data: its tests live in their own module and run in the public CI.
"""

import pytest

from xbsl import engine, i18n
from xbsl.cli import discover

RULE = "translation/english-shape"


def _dictionary(tmp_path, body: str, *, name: str = "010-entries.yaml"):
    """A dictionary file with `body` under its head; bytes as written, no newline translation."""
    folder = tmp_path / "xbsl-translation"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(("version: 1\nlanguage: en\n\n" + body).encode("utf-8"))
    return path


def _lint(tmp_path):
    return [d for d in engine.run(discover([str(tmp_path)]), select={RULE}) if d.rule_id == RULE]


def _words(diags):
    return sorted(d.message.split("'")[1] for d in diags)


def test_an_adverb_carrying_the_verb_ending_is_a_trace(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "лишний значок только загромождает строку.": "a second icon onlies clutter the row."\n'
        '    "иначе строка теряет отступ.": "the row otherwises lose its margin."\n'
    ))
    diags = _lint(tmp_path)

    assert _words(diags) == ["onlies", "otherwises"], [d.message for d in diags]
    assert all("приклеено окончание" in d.message for d in diags)


def test_participles_and_auxiliaries_with_an_ending_are_traces(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "Запись удалена.": "The record gones."\n'
        '    "Файл записан.": "The file writtens."\n'
        '    "Кэш уже есть.": "The cache hases a value."\n'
        '    "Строки загружены.": "The rows are loadeds."\n'
        "terms:\n"
        "    молча: silentlies\n"
    ))

    assert _words(_lint(tmp_path)) == ["gones", "hases", "loadeds", "silentlies", "writtens"]


def test_ordinary_english_endings_stay_silent(tmp_path):
    """Verbs and nouns in -lies/-eds/-s, compounds with a plural of their own, acronym plurals."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "первая": "The method applies the filter and replies with the list."\n'
        '    "вторая": "It needs the seeds of hundreds of rows, and the feed embeds them."\n'
        '    "третья": "The bounds come from the settings; it sets and reads them."\n'
        '    "четвёртая": "The has-beens and the also-rans stay; givens and knowns are listed."\n'
        '    "пятая": "The DIDs are counted, the family relies on them."\n'
    ))

    assert _lint(tmp_path) == []


def test_a_passive_followed_by_a_noun_phrase_is_a_trace(tmp_path):
    """A `which` behind a comma opens a different clause, and a finite verb of a relative clause
    after the phrase does not make the phrase a subject - neither excuses the passive."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "переменная перекрывает параметр.": "a variable is shadowed the parameter."\n'
        '    "верно, а поле перекрывает имя.": "which is fine, and a field is shadowed the name."\n'
        '    "имя перекрывает то, что передано.": "a name is shadowed the value that is passed."\n'
    ))
    diags = _lint(tmp_path)

    assert _words(diags) == ["is shadowed the"] * 3, [d.message for d in diags]
    assert all("страдательный залог" in d.message for d in diags)


def test_a_passive_that_keeps_its_object_or_opens_a_clause_stays_silent(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "первая": "the users who are assigned the editor role."\n'
        '    "вторая": "a user is assigned the editor role."\n'
        '    "третья": "the tile is built the same way as the badge."\n'
        '    "четвёртая": "until the counter is raised the call does not happen."\n'
        '    "пятая": "and so when the theme is switched the widget is rebuilt."\n'
        '    "шестая": "is shadowed the parameter by a local variable."\n'
        '    "седьмая": "the value is indeed the key, and the row is freed the moment it closes."\n'
    ))

    assert _lint(tmp_path) == []


def test_capitals_the_key_does_not_have_are_a_trace(tmp_path):
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "фильтр не сужает список": "the filter does NOT narrow the list"\n'
        '    "одним запросом вместо трёх": "in ONE query instead of three"\n'
    ))
    diags = _lint(tmp_path)

    assert _words(diags) == ["NOT", "ONE"], [d.message for d in diags]
    assert any("'not'" in d.message for d in diags)


def test_capitals_justified_by_the_key_or_by_the_word_itself_stay_silent(tmp_path):
    """A stressed Russian word, a glued prefix, a stressed one-letter word, the same Latin word,
    an abbreviation, a constant, and a word answering a capital that only opens a sentence."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    "фильтр НЕ сужает список": "the filter does NOT narrow the list"\n'
        '    "поля НЕизменяемые": "the fields are NON-editable"\n'
        '    "строка И столбец": "the row AND the column"\n'
        '    "поле status пустое": "the STATUS field is empty"\n'
        '    "размер до 5 мб": "a size up to 5 MB"\n'
        '    "ждать заданное время": "wait for CACHE_TTL_SECONDS"\n'
        '    "И строка тоже": "AND the row too"\n'
    ))

    assert _lint(tmp_path) == []


def test_an_identifier_or_a_latin_name_in_the_key_hides_no_other_capitals(tmp_path):
    """A one-letter word inside an identifier stresses nothing, `ExtAPI` justifies `API` alone,
    and a capital that opens the key's sentence says nothing about a word in the middle of the
    translation."""
    _dictionary(tmp_path, (
        "phrases:\n"
        '    ".ВСтроку() тут не подходит": ".ToString() does NOT fit here"\n'
        '    "Вид значением из ExtAPI": "The kind AS A value from the ExtAPI"\n'
        '    "В ряду заголовок не растянут": "In the row the title is NOT stretched"\n'
    ))

    assert _words(_lint(tmp_path)) == ["AS", "NOT", "NOT"]


def test_tokens_are_judged_by_their_camel_case_parts(tmp_path):
    _dictionary(tmp_path, (
        "tokens:\n"
        "    ПерТМ: TrMT\n"
        "    ТолькоЧтение: OnliesRead\n"
        "    ЗначениеКлюча: KeyVALUE\n"
        "    ЗаписьЗагружена: RecordIsLoadedTheFile\n"
    ))

    assert _words(_lint(tmp_path)) == ["Onlies", "VALUE"]


def test_the_position_points_at_each_occurrence_of_the_word(tmp_path):
    path = _dictionary(tmp_path, (
        "phrases:\n"
        "    'ни то, ни ''другое''': 'NOT this and NOT ''that'''\n"
        '    "первая": "the INSIDE part stays IN place"\n'
    ))
    text = path.read_bytes().decode("utf-8")
    lines = text.split("\n")
    first = next(i for i, line in enumerate(lines) if "NOT this" in line)
    second = next(i for i, line in enumerate(lines) if "INSIDE part" in line)
    expected = sorted([
        (first + 1, lines[first].index("NOT this") + 1),
        (first + 1, lines[first].index("NOT ''that") + 1),
        (second + 1, lines[second].index("INSIDE") + 1),
        (second + 1, lines[second].index("IN place") + 1),
    ])

    diags = _lint(tmp_path)

    found = sorted((d.line, d.col) for d in diags)
    assert found == expected, [(d.line, d.col, d.message) for d in diags]


def test_only_the_dictionary_files_are_judged(tmp_path):
    """The same yaml outside a dictionary says nothing; a single-file dictionary is judged."""
    body = 'phrases:\n    "только так": "onlies this way"\n'
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Модуль.yaml").write_bytes(body.encode("utf-8"))
    single = tmp_path / "single"
    single.mkdir()
    (single / "xbsl-translation.yaml").write_bytes(("version: 1\n" + body).encode("utf-8"))

    diags = _lint(tmp_path)

    paths = [d.path for d in diags]
    assert len(paths) == 1 and paths[0].endswith("xbsl-translation.yaml"), paths


def test_stubs_and_a_broken_dictionary_file_do_not_break_the_run(tmp_path):
    _dictionary(tmp_path, 'phrases:\n    "пустая": ""\n    "без значения":\n')
    _dictionary(tmp_path, "phrases:\n  - [unclosed\n", name="020-broken.yaml")

    assert _lint(tmp_path) == []


def test_the_english_message_names_the_word_and_its_base(tmp_path):
    _dictionary(tmp_path, 'phrases:\n    "только так": "onlies this way"\n')
    i18n.set_lang("en")

    diags = _lint(tmp_path)

    assert len(diags) == 1
    assert "The word 'onlies'" in diags[0].message and "'only'" in diags[0].message


def test_the_rule_is_an_enabled_file_warning_of_tier_b():
    """A file rule runs on every keystroke in the editor - a dictionary file is judged as typed."""
    info = next((r for r in engine.RULES if r.id == RULE), None)
    if info is None:  # pragma: no cover - the module is imported by xbsl.rules
        pytest.fail("the rule is not registered")

    assert (info.tier, info.scope, info.severity.value, info.enabled_by_default) == (
        "B", "file", "warning", True,
    )
