from xbsl.translation.entries import Gap
from xbsl.translation.machine.literals import fill

TOKENS = {"Footer": "Подвал", "Reference": "Ссылка", "Code": "Код"}


def test_a_whole_literal_that_matches_a_token_is_filled():
    """Literal matching exactly a token key gets its value."""
    gap = Gap(key="Footer", kind="literal")
    assert fill([gap], TOKENS) == {"Footer": "Подвал"}


def test_a_partial_match_is_not_filled():
    """If only a segment of the literal matches a token, the literal is left alone.
    This prevents accidental substitution of unrelated entities."""
    gap = Gap(key="Language/Code.svg", kind="literal")
    assert fill([gap], TOKENS) == {}


def test_an_unknown_literal_is_left_alone():
    """Literal not in tokens yields no result."""
    assert fill([Gap(key="Unknown", kind="literal")], TOKENS) == {}


def test_tokens_and_phrases_are_not_touched():
    """Only literals are processed; tokens and phrases are ignored."""
    assert fill([Gap(key="Footer", kind="token")], TOKENS) == {}
    assert fill([Gap(key="Some phrase", kind="phrase")], TOKENS) == {}


def test_case_sensitive_matching():
    """Matching is exact: case differences disqualify."""
    gap = Gap(key="footer", kind="literal")
    assert fill([gap], TOKENS) == {}
