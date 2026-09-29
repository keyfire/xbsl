"""xbsl/querytypes.py: the type of a literal of the query language comes from the data.

The literals are the words of the table of reserved words on the help page on the syntax of
query text that link the page of a type (`query_reserved_types` of terms.json, the English
spelling from `query_reserved`). The list the module kept by hand stays for a checkout without
that data. `NULL` is no row of the table - it links the IS NULL expression - and stays the
Null of a query.

Every test builds its own tiny data root, so the module is checked in a public checkout too.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from xbsl import dataset, querytypes
from xbsl.typeinfer import TypeSet


def _word(text: str) -> SimpleNamespace:
    return SimpleNamespace(kind="IDENT", value=text)


def _root(tmp_path, terms: dict | None):
    version = tmp_path / "9.9.9"
    version.mkdir()
    (tmp_path / "index.json").write_text(
        json.dumps({"available": ["9.9.9"], "default": "9.9.9"}), encoding="utf-8")
    if terms is not None:
        (version / "terms.json").write_text(json.dumps(terms, ensure_ascii=False),
                                            encoding="utf-8")
    return tmp_path


@pytest.fixture
def data_root():
    def pin(path):
        dataset.set_data_root(path)
    try:
        yield pin
    finally:
        dataset.set_data_root(None)


def test_the_literals_are_read_from_the_data(tmp_path, data_root):
    # A made-up literal proves where the answer comes from: the hand-kept list does not know
    # it, and a literal the data leaves out is no literal any more.
    data_root(_root(tmp_path, {
        "query_reserved": {"ИСТИНА": "TRUE", "ПУСТО": "EMPTY", "ИЗ": "FROM"},
        "query_reserved_types": {"ИСТИНА": "Булево", "ПУСТО": "Неопределено"},
    }))

    assert querytypes._literal(_word("истина")) == TypeSet.of("Булево")
    assert querytypes._literal(_word("TRUE")) == TypeSet.of("Булево")
    assert querytypes._literal(_word("Пусто")) == TypeSet(undefined=True)
    assert querytypes._literal(_word("EMPTY")) == TypeSet(undefined=True)
    assert querytypes._literal(_word("ЛОЖЬ")) is None
    assert querytypes._literal(_word("FROM")) is None  # a reserved word, not a literal


@pytest.mark.parametrize("terms", [None, {"query_reserved": {"ИСТИНА": "TRUE"}}],
                         ids=["no-terms", "no-types"])
def test_without_the_list_the_literals_are_the_ones_kept_by_hand(tmp_path, data_root, terms):
    data_root(_root(tmp_path, terms))

    for word in ("ИСТИНА", "ЛОЖЬ", "true", "False"):
        assert querytypes._literal(_word(word)) == TypeSet.of("Булево"), word
    for word in ("НЕОПРЕДЕЛЕНО", "Undefined"):
        assert querytypes._literal(_word(word)) == TypeSet(undefined=True), word
    assert querytypes._literal(_word("ПУСТО")) is None


def test_null_is_the_null_of_a_query_with_or_without_the_data(tmp_path, data_root):
    data_root(_root(tmp_path, {"query_reserved_types": {"ИСТИНА": "Булево"}}))

    assert querytypes._literal(_word("NULL")) == TypeSet(null=True)
    assert querytypes._literal(SimpleNamespace(kind="NUMBER", value="1")) == TypeSet.of("Число")
    assert querytypes._literal(SimpleNamespace(kind="STRING", value="1")) == TypeSet.of("Строка")


@pytest.mark.needs_data  # the platform data of the checkout, whichever version it is
def test_the_literals_of_the_platform_data_keep_their_types():
    for word in ("ИСТИНА", "FALSE"):
        assert querytypes._literal(_word(word)) == TypeSet.of("Булево"), word
    assert querytypes._literal(_word("UNDEFINED")) == TypeSet(undefined=True)
