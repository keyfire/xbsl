"""The translator and the tags of a documentation comment.

A tag line (`@параметр Коды - ...`) with no pair of its own is translated by its parts: the tag
word is the English one, the name after it is translated like the name in the code, and only
the text after the name is a phrase. A pair written for the whole line still wins. The orphan
pass keeps a pair written for the text of a tag live, the re-wrap of a paragraph never glues a
tag to the line above, and `--drift` judges the name and the tag word of a whole-line pair.

Reading a tag line and judging the dictionary needs no Element data; the translation of a
module and the re-wrap tokenize it and carry `needs_data`.
"""

import pytest

from xbsl import engine
from xbsl.translation import code, drift, entries
from xbsl.translation.code import Resolver, translate_code
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.reporting import FileReport
from xbsl.translation.rewrap import rewrap_comments

_TOKENS = {"Остаток": "Remainder", "Код": "Code", "Склады": "Stores", "Резерв": "Reserve"}
_MODULE = """/// Остаток на складе.
///
/// @параметр Код - Код товара.
///
/// @возвращает Остаток товара.
/// @см Склады.Резерв
метод Остаток(Код: Строка): Число
    возврат 0
;
"""


def _code(text: str, tokens=None, phrases=None) -> tuple[str, FileReport]:
    source = engine.load_text("Склады.xbsl", text)
    report = FileReport(path="Склады.xbsl")
    dictionary = Dictionary(tokens=dict(tokens or {}), phrases=dict(phrases or {}))
    return translate_code(source, Resolver(dictionary), report), report


# --- reading a tag line ----------------------------------------------------------------------

@pytest.mark.parametrize(("payload", "phrase"), (
    ("@параметр Коды - Коды для проверки.", "Коды для проверки."),
    ("@выбрасывает Склады.Ошибка - при закрытом складе", "при закрытом складе"),
    ("@возвращает Число строк.", "Число строк."),
    ("@см ПересчетОстатков", "ПересчетОстатков"),
    ("@параметр Коды", None),
    ("@param Коды - Коды.", None),
    ("Описание метода.", None),
))
def test_the_phrase_of_a_tag_line_is_its_text(payload, phrase):
    assert code.tag_phrase(payload) == phrase


# --- the pass over a module ------------------------------------------------------------------

@pytest.mark.needs_data
def test_a_tag_line_without_a_pair_is_translated_by_its_parts():
    out, report = _code(_MODULE, _TOKENS, {
        "Остаток на складе.": "The stock at the warehouse.",
        "Код товара.": "The goods code.",
        "Остаток товара.": "The goods remainder.",
    })
    assert "/// @parameter Code - The goods code.\n" in out
    assert "/// @returns The goods remainder.\n" in out
    assert "/// @see Stores.Reserve\n" in out
    assert "method Remainder(Code: String): Number" in out
    assert report.missing_phrases == {}


@pytest.mark.needs_data
def test_the_text_of_a_tag_is_the_missing_phrase():
    out, report = _code(_MODULE, _TOKENS, {"Остаток на складе.": "The stock at the warehouse."})
    assert sorted(report.missing_phrases) == ["Код товара.", "Остаток товара."]
    # The tag word and the name are translated all the same: they need no pair.
    assert "/// @parameter Code - Код товара.\n" in out
    line, col = report.missing_phrases["Код товара."][0]
    assert (line, col) == (3, 1 + len("/// @параметр Код - "))


@pytest.mark.needs_data
def test_a_pair_for_the_whole_line_still_wins():
    out, _report = _code(_MODULE, _TOKENS, {
        "Остаток на складе.": "The stock at the warehouse.",
        "@параметр Код - Код товара.": "@parameter Code - The code of the goods.",
        "Остаток товара.": "The goods remainder.",
    })
    assert "/// @parameter Code - The code of the goods.\n" in out


@pytest.mark.needs_data
def test_a_name_without_a_pair_is_reported_and_kept():
    # A name neither the project nor the platform spells: the plain one has the platform's `Code`.
    text = _MODULE.replace("Код", "КодПартииСклада")
    out, report = _code(text, _TOKENS, {"КодПартииСклада товара.": "The goods code."})
    assert "/// @parameter КодПартииСклада - The goods code.\n" in out
    assert (3, 1 + len("/// @параметр ")) in report.missing_tokens["КодПартииСклада"]


@pytest.mark.needs_data
def test_a_reference_written_as_a_phrase_is_a_phrase():
    text = _MODULE.replace("/// @см Склады.Резерв", "/// @см Раздел о ценах")
    out, report = _code(text, _TOKENS, {"Раздел о ценах": "The section about prices"})
    assert "/// @see The section about prices\n" in out
    assert "Раздел о ценах" not in report.missing_phrases


# --- the orphan pass -------------------------------------------------------------------------

@pytest.mark.needs_data
def test_the_text_of_a_tag_is_a_live_key_of_the_dictionary():
    keys = entries._comment_bodies_of(".xbsl", _MODULE)
    assert "Код товара." in keys and "@параметр Код - Код товара." in keys
    assert "Остаток товара." in keys


# --- the re-wrap -----------------------------------------------------------------------------

@pytest.mark.needs_data
def test_the_rewrap_never_glues_a_tag_to_the_line_above():
    source = (
        "/// Описание метода.\n///\n/// @параметр Код - Код товара.\n/// @возвращает Остаток.\n"
        "метод Остаток(Код: Строка): Число\n;\n"
    )
    translated = (
        "/// Describes the method.\n///\n/// @parameter Code - The code of the goods, written "
        "with a lot of words to go past the limit of the line.\n/// @returns The remainder.\n"
        "method Remainder(Code: String): Number\n;\n"
    )
    out = rewrap_comments(translated, source, limit=80)
    lines = out.split("\n")
    assert "/// @returns The remainder." in lines
    assert lines[2].startswith("/// @parameter Code - ") and len(lines[2]) <= 80
    assert not lines[3].startswith("/// @")


# --- drift of a whole-line pair --------------------------------------------------------------

def test_a_tag_name_spelled_otherwise_than_its_token_is_drift():
    dictionary = Dictionary(
        tokens={"Коды": "Codes", "Склад": "Warehouse"},
        phrases={
            "@параметр Коды - Коды для проверки.": "@parameter CodeList - Codes to check.",
            "@параметр Склад - Склад отбора.": "@parameter Warehouse - The warehouse to pick.",
        },
    )
    rows = drift.phrase_drift(dictionary)
    assert [(r.name, r.expected, r.found) for r in rows] == [
        ("Коды", ("Codes",), ("CodeList",)),
    ]


def test_a_tag_word_of_another_system_is_drift():
    dictionary = Dictionary(phrases={"@возвращает Число строк.": "@return The number of rows."})
    rows = drift.phrase_drift(dictionary)
    assert [(r.name, r.expected, r.found) for r in rows] == [
        ("@возвращает", ("@returns",), ("@return",)),
    ]
