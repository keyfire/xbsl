"""Query keyword pairs out of the parser's constant pool (xbsl/extract/terms.py).

The windows below are real: they were read out of the QueryTerms class of a distribution,
and each one is a shape the pool actually holds. Taken by adjacency alone, the constant of
one entry became the "English" of the next, and the generated dictionary claimed that `ОТ`
answers `OTLICHAYETSYA` and `ДЛЯ` answers `CREATE_INDEX` - two words the translating side
then skipped by hand.

No Element data is needed here: the function is pure, the pool is the fixture.
"""

from xbsl.extract.terms import _query_pairs


def test_a_plain_pair_is_read():
    assert _query_pairs(["FROM", "ИЗ", "WHERE", "ГДЕ"]) == {"ИЗ": "FROM", "ГДЕ": "WHERE"}


def test_the_enum_constant_of_a_pair_is_not_the_next_english():
    """`CREATE INDEX`, `СОЗДАТЬ ИНДЕКС`, `CREATE_INDEX` - the third is the constant of the
    pair, and the word after it is a keyword of its own."""
    pairs = _query_pairs([
        "CREATE INDEX", "СОЗДАТЬ ИНДЕКС", "CREATE_INDEX", "ДЛЯ", "DLYA",
        "CREATE TEMPORARY TABLE", "СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ",
    ])

    assert pairs["СОЗДАТЬ ИНДЕКС"] == "CREATE INDEX"
    assert pairs["СОЗДАТЬ ВРЕМЕННУЮ ТАБЛИЦУ"] == "CREATE TEMPORARY TABLE"
    assert "ДЛЯ" not in pairs


def test_a_keyword_without_an_english_spelling_is_left_out():
    """What follows such a keyword is a transliteration - its constant name, not a translation."""
    pairs = _query_pairs([
        "GROUP", "ГРУППИРОВАТЬ", "HAVING", "ИМЕЮЩИЕ",
        "ОТЛИЧАЕТСЯ", "OTLICHAYETSYA", "ОТ", "OT",
        "INSERT", "ВСТАВИТЬ",
    ])

    assert pairs == {
        "ГРУППИРОВАТЬ": "GROUP", "ИМЕЮЩИЕ": "HAVING", "ВСТАВИТЬ": "INSERT",
    }


def test_an_empty_pool_answers_with_nothing():
    assert _query_pairs([]) == {}
    assert _query_pairs(["SELECT"]) == {}
