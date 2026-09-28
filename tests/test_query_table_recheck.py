"""The readers of the platform data read it again once it is installed.

Three readers keep what they built over the `query` section of terms.json: the syntax helpers of
the rules (`xbsl/rules/_syntax.py`), the words of a cited query of comment/emphasis-caps and the
spellings of the translator (`xbsl/translation/platform_map.py`), which reads the grammar, the
type catalog and the interface terms as well. An editor or an MCP server started without the
data outlives its install, and what a reader concluded from data that was not there must not
answer after it arrived: the engine looks at the disk again before every pass
(`dataset.recheck_data`), and it does so only when a reader noted its miss. So each reader
reads the data as optional (`dataset.load_optional`), which notes the miss for it. Each test
pins an empty data root, reads, installs a tiny table into the same root and looks again - no
Element data is needed.
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


def _install_and_look_again(root, name: str = "terms.json", data: dict | None = None) -> None:
    # Nothing but the reader under test has looked for the data: the look at the disk before
    # the next pass happens only because that reader noted its own miss.
    (root / "1.0.0").mkdir()
    (root / "1.0.0" / name).write_text(
        json.dumps({"query": _TABLE} if data is None else data, ensure_ascii=False),
        encoding="utf-8")
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


@pytest.mark.parametrize("name, data, read, expected", [
    ("language.json", {"keywords": {"TRUE": {"forms": ["True", "Истина"]}}},
     lambda: platform_map.keyword_english().get("Истина"), "True"),
    ("stdlib.json", {"type_members": {"Склад": {"methods": ["Отгрузить"]}}},
     lambda: "Отгрузить" in platform_map._member_names(), True),
    ("uiterms.json", {"enum_values": {"Сторона": {"Лево": "Left"}}},
     lambda: platform_map._ui_enum_tables().get("Сторона"), {"Лево": "Left"}),
], ids=["grammar", "type-catalog", "interface-terms"])
def test_the_other_data_of_the_translator_is_read_once_it_is_installed(
        root, name, data, read, expected):
    assert read() != expected

    _install_and_look_again(root, name, data)

    assert read() == expected


def test_the_translator_spells_the_reserved_words_the_data_lists(root):
    """The reserved words of the query language come from the data (the documentation's table):
    a word the list adds is translated. The words kept by hand answer only where the data has
    no list - the control, and the public checkout."""
    _install_and_look_again(
        root, data={"query": _TABLE, "query_reserved": {"ИСТИНА": "TRUE", "ПУСТО": "EMPTY"}})

    assert platform_map.query_keyword_english("ПУСТО") == "EMPTY"
    assert platform_map.query_keyword_english("ИСТИНА") == "TRUE"
    assert platform_map.query_keyword_english("НЕОПРЕДЕЛЕНО") is None  # not in this list


def test_without_the_list_the_translator_keeps_the_reserved_words_it_knows(root):
    _install_and_look_again(root)

    assert platform_map.query_keyword_english("ПУСТО") is None
    assert platform_map.query_keyword_english("НЕОПРЕДЕЛЕНО") == "UNDEFINED"
