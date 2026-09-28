"""The readers of the keyword table of the query language read it again once it is installed.

Three readers keep what they built over the `query` section of terms.json: the syntax helpers of
the rules (`xbsl/rules/_syntax.py`), the words of a cited query of comment/emphasis-caps and the
spellings of the translator (`xbsl/translation/platform_map.py`). An editor or an MCP server
started without the data outlives its install, and what a reader concluded from data that was
not there must not answer after it arrived: the engine looks at the disk again before every pass
(`dataset.recheck_data`). Each test pins an empty data root, reads, installs a tiny table into
the same root and looks again - no Element data is needed.
"""

import json

import pytest

from xbsl import dataset
from xbsl.rules import _syntax, comment_prose
from xbsl.translation import platform_map

_TABLE = {"ГДЕ": "WHERE", "УПОРЯДОЧИТЬ ПО": "ORDER BY", "ССЫЛКА": "REFS"}


@pytest.fixture
def root(tmp_path):
    dataset.set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        dataset.set_data_root(None)


def _install_and_look_again(root) -> None:
    # A reader of the terms that found nothing noted the miss, as the term readers of every run
    # do (`dataset.load_optional`); the engine then looks at the disk before the next pass.
    dataset.load_optional("terms.json")
    (root / "1.0.0").mkdir()
    (root / "1.0.0" / "terms.json").write_text(
        json.dumps({"query": _TABLE}, ensure_ascii=False), encoding="utf-8")
    (root / "index.json").write_text(
        json.dumps({"available": ["1.0.0"], "default": "1.0.0"}), encoding="utf-8")
    dataset.recheck_data()


def test_the_syntax_helpers_read_the_table_once_it_is_installed(root):
    assert _syntax.query_words("REFS") == {"REFS"}
    assert "ССЫЛКА" not in _syntax._query_vocabulary()

    _install_and_look_again(root)

    assert _syntax.query_words("REFS") == {"REFS", "ССЫЛКА"}
    assert "ССЫЛКА" in _syntax._query_vocabulary()


def test_the_translator_reads_the_table_once_it_is_installed(root):
    assert platform_map.query_phrases() == {}
    assert platform_map.query_keyword_english("ССЫЛКА") is None

    _install_and_look_again(root)

    assert platform_map.query_phrases() == {("УПОРЯДОЧИТЬ", "ПО"): ("ORDER", "BY")}
    assert platform_map.query_keyword_english("ССЫЛКА") == "REFS"


def test_the_words_of_a_cited_query_follow_the_table_once_it_is_installed(root):
    assert "ССЫЛКА" not in comment_prose._query_words()

    _install_and_look_again(root)

    assert "ССЫЛКА" in comment_prose._query_words()
