"""Checks of the generated language data (language.json)."""

from xbsl.lexer import _keyword_forms, _language, _operators


def test_language_has_bilingual_keywords():
    lang = _language()
    assert lang["keywords"]["METHOD"]["forms"], "у METHOD должны быть формы"
    kf = _keyword_forms()
    assert kf.get("метод") == "METHOD"
    assert kf.get("method") == "METHOD"
    assert kf.get("возврат") == "RETURN"


def test_operators_have_multichar_and_sorted_longest_first():
    ops = _operators()
    for op in ("??", "?.", "::", "->", "==", "!="):
        assert op in ops, f"оператор {op} отсутствует"
    # in decreasing length order (for the longest-match bite in the lexer)
    assert len(ops[0]) >= len(ops[-1])
