"""A phrases entry written the way a LITERAL is written: the quote escaped, the pair silent.

The literals plane spells its key and its value the way the source spells them, escaping and
all. A phrase is the opposite: it is keyed by the text of a comment line as it stands, because
that is what the pass compares against. The writer behind `translate --set` and `translate_set`
took the key as given, so a key spelled with a backslash before the quote matched no comment
anywhere. The pass reported the line as a gap, the entry sat in the dictionary looking like
coverage, and nothing in the answer said a word about it.

The same silence covered the other shapes a phrase cannot have: padding around the text, a
key on two lines, an entry with no key at all.

Only the pair that proves the fix over real sources needs Element data; the writer needs none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import cli, dictionary as dict_module, entries
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.reporting import FileReport

#: The key as a caller escapes it by mistake, and the text a comment actually carries.
_ESCAPED_KEY = 'Не заполнено поле \\"Наименование\\"'
_PLAIN_KEY = 'Не заполнено поле "Наименование"'
_ESCAPED_VALUE = 'The \\"Name\\" field is empty'
_PLAIN_VALUE = 'The "Name" field is empty'


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    """An empty dictionary directory: the entries of each test are the ones it writes."""
    path = tmp_path / "xbsl-translation"
    path.mkdir()
    (path / "010-base.yaml").write_text("version: 1\nlanguage: en\n", encoding="utf-8")
    return path


def _phrase(key: str, value: str) -> list[dict]:
    return [{"key": key, "value": value, "kind": "phrase"}]


# --- the escaped quote ------------------------------------------------------------------


def test_an_escaped_quote_in_a_phrase_key_is_written_the_way_a_comment_carries_it(folder: Path):
    result = entries.write_entries(folder, _phrase(_ESCAPED_KEY, _PLAIN_VALUE))

    assert result["added"] == 1 and result["refused"] == []
    assert dict_module.load(folder).phrases == {_PLAIN_KEY: _PLAIN_VALUE}


def test_the_correction_of_the_key_is_named_in_the_answer(folder: Path):
    result = entries.write_entries(folder, _phrase(_ESCAPED_KEY, _PLAIN_VALUE))

    rows = result["normalized"]
    assert [(row["kind"], row["was"], row["now"]) for row in rows] == [
        ("phrase", _ESCAPED_KEY, _PLAIN_KEY),
    ]
    assert rows[0]["key"] == _PLAIN_KEY and rows[0]["reason"]


def test_an_escaped_quote_in_the_translation_is_taken_off_as_well(folder: Path):
    """The value goes into the comment as it stands, so a backslash there reaches the source."""
    result = entries.write_entries(folder, _phrase(_PLAIN_KEY, _ESCAPED_VALUE))

    assert dict_module.load(folder).phrases == {_PLAIN_KEY: _PLAIN_VALUE}
    assert [(row["was"], row["now"]) for row in result["normalized"]] == [
        (_ESCAPED_VALUE, _PLAIN_VALUE),
    ]


@pytest.mark.needs_data
def test_the_corrected_pair_translates_the_comment_it_was_written_for(folder: Path):
    """The proof the answer is about: the pass now finds the pair over real sources."""
    entries.write_entries(folder, _phrase(_ESCAPED_KEY, _PLAIN_VALUE))
    loaded = dict_module.load(folder)

    source = engine.load_text("Модуль.xbsl", f"Метод Проверить()\n  // {_PLAIN_KEY}\nКонецМетода\n")
    report = FileReport(path="Модуль.xbsl")
    out = translate_code(source, Resolver(loaded), report)

    assert _PLAIN_VALUE in out
    assert report.phrases_done == 1 and report.missing_phrases == {}


# --- the quote a comment really carries -------------------------------------------------


def test_a_plain_quote_in_a_phrase_key_is_left_alone(folder: Path):
    """The control of the correction: a comment cites things, and its quotes are its own."""
    result = entries.write_entries(folder, _phrase(_PLAIN_KEY, _PLAIN_VALUE))

    assert result["normalized"] == [] and result["refused"] == []
    assert dict_module.load(folder).phrases == {_PLAIN_KEY: _PLAIN_VALUE}


def test_an_ordinary_phrase_is_written_the_way_it_always_was(folder: Path):
    """The negative control of the whole change: nothing about a plain pair moves."""
    result = entries.write_entries(
        folder, _phrase("Задача помечается выполненной.", "The task is marked done."))

    assert (result["added"], result["changed"], result["removed"]) == (1, 0, 0)
    assert result["normalized"] == [] and result["refused"] == []
    body = (folder / entries.DEFAULT_TARGET).read_text(encoding="utf-8")
    assert '    "Задача помечается выполненной.": "The task is marked done."\n' in body


# --- the padding a comment does not carry -----------------------------------------------


def test_padding_around_a_phrase_key_is_taken_off(folder: Path):
    """The pass reads a comment line without its marker and without the spaces after it."""
    result = entries.write_entries(folder, _phrase("  Задача готова.  ", "The task is done."))

    assert dict_module.load(folder).phrases == {"Задача готова.": "The task is done."}
    assert [(row["was"], row["now"]) for row in result["normalized"]] == [
        ("  Задача готова.  ", "Задача готова."),
    ]


# --- what cannot be repaired ------------------------------------------------------------


def test_a_phrase_key_on_two_lines_is_refused_with_the_reason(folder: Path):
    result = entries.write_entries(
        folder, _phrase("Первая строка\nвторая строка", "First line\nsecond line"))

    assert result["added"] == 0
    assert [(row["key"], row["kind"]) for row in result["refused"]] == [
        ("Первая строка\nвторая строка", "phrase"),
    ]
    assert result["refused"][0]["reason"]
    assert dict_module.load(folder).phrases == {}


def test_a_translation_on_two_lines_is_refused_too(folder: Path):
    """The value replaces the payload inside one comment line: a break there cuts the code."""
    result = entries.write_entries(folder, _phrase("Задача готова.", "The task\nis done."))

    assert result["added"] == 0 and len(result["refused"]) == 1
    assert dict_module.load(folder).phrases == {}


def test_an_entry_without_a_key_is_refused_rather_than_dropped(folder: Path):
    result = entries.write_entries(
        folder, [{"key": "", "value": "The task is done.", "kind": "phrase"}])

    assert result["added"] == 0
    assert [row["kind"] for row in result["refused"]] == ["phrase"]
    assert result["refused"][0]["reason"]


def test_a_key_of_spaces_alone_is_refused_for_any_kind(folder: Path):
    result = entries.write_entries(folder, [{"key": "   ", "value": "Tasks", "kind": "token"}])

    assert result["added"] == 0 and len(result["refused"]) == 1


# --- the entries already in the dictionary ----------------------------------------------


def test_an_entry_that_is_there_is_addressed_exactly_as_typed(folder: Path):
    """A dictionary written before the correction holds such a key - and it has to be removable."""
    (folder / "010-base.yaml").write_text(
        "version: 1\nlanguage: en\nphrases:\n"
        f"    {json.dumps(_ESCAPED_KEY, ensure_ascii=False)}: "
        f"{json.dumps(_PLAIN_VALUE, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    result = entries.write_entries(folder, _phrase(_ESCAPED_KEY, ""))

    assert result["removed"] == 1 and result["normalized"] == []
    assert dict_module.load(folder).phrases == {}


# --- both surfaces ----------------------------------------------------------------------


@pytest.mark.needs_data
def test_the_cli_prints_what_it_corrected(folder: Path, tmp_path: Path, capsys):
    batch = tmp_path / "edits.json"
    batch.write_text(json.dumps(_phrase(_ESCAPED_KEY, _PLAIN_VALUE), ensure_ascii=False),
                     encoding="utf-8")

    code = cli.cli_main([str(tmp_path), "--set", str(batch), "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert [(row["was"], row["now"]) for row in payload["normalized"]] == [
        (_ESCAPED_KEY, _PLAIN_KEY),
    ]


def test_the_mcp_tool_answers_the_same_way(mcp_module, folder: Path, tmp_path: Path):
    answer = mcp_module.translate_set(str(tmp_path), edits=_phrase(_ESCAPED_KEY, _PLAIN_VALUE))

    assert [(row["was"], row["now"]) for row in answer["normalized"]] == [
        (_ESCAPED_KEY, _PLAIN_KEY),
    ]
    assert dict_module.load(folder).phrases == {_PLAIN_KEY: _PLAIN_VALUE}
