"""The name of a deprecated element keeps its prefix in the English tree.

The naming standard starts the name of a deprecated element with a fixed word, and
naming/presentation knows the element by that word in either spelling. A file of a translated
tree keeps nothing else of the Russian name - the dictionary lives next to the sources and never
travels with the tree - so the translator writes the English prefix itself
(Dictionary.written): an entry that starts with it is written as it is, any other one gets it in
front. The unit tests pin the pair of spellings the data gives the prefix, so they run without
the data; the translation of a whole project reads the term pairs and the metamodel, hence
`needs_data`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine, terms
from xbsl.translation import drift
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.project import translate_project

#: The two spellings of the prefix, the way the data pairs them.
_PAIR = ("Устарело", "Deprecated")


@pytest.fixture
def pair(monkeypatch):
    """The data's pair of spellings of the prefix, without the data."""
    monkeypatch.setattr(terms, "deprecation_prefixes", lambda: _PAIR)


@pytest.mark.parametrize("entry, written", [
    ("DeprecatedRates", "DeprecatedRates"),
    # An entry that leaves the prefix out, or renders it its own way, gets it in front.
    ("Rates", "DeprecatedRates"),
    ("ObsoleteRates", "DeprecatedObsoleteRates"),
    ("rates", "DeprecatedRates"),
    # The English word with no next word after it is no prefix either.
    ("Deprecated", "DeprecatedDeprecated"),
])
def test_a_deprecated_name_keeps_the_english_prefix(pair, entry, written):
    assert Dictionary(tokens={"УстарелоКурсы": entry}).token("УстарелоКурсы") == written


def test_a_scoped_entry_keeps_the_prefix_as_well(pair):
    dictionary = Dictionary(tokens={"Отчеты.УстарелоСверка": "Check",
                                    "УстарелоСверка": "Reconciliation"})
    assert dictionary.token("УстарелоСверка", "Отчеты") == "DeprecatedCheck"
    assert dictionary.scoped_token("УстарелоСверка", "Отчеты") == "DeprecatedCheck"
    assert dictionary.token("УстарелоСверка") == "DeprecatedReconciliation"


@pytest.mark.parametrize("name, entry", [
    # The head of a longer word is no prefix, and neither is the bare word.
    ("УстарелостьОборудования", "EquipmentObsolescence"),
    ("Устарело", "Outdated"),
    ("Курсы", "Rates"),
])
def test_a_name_without_the_prefix_is_written_as_the_entry_says(pair, name, entry):
    assert Dictionary(tokens={name: entry}).token(name) == entry


def test_a_name_without_an_entry_is_still_a_gap(pair):
    assert Dictionary().token("УстарелоКурсы") is None


def test_only_a_translation_into_english_is_prefixed(pair):
    dictionary = Dictionary(language="vi", tokens={"УстарелоКурсы": "Rates"})
    assert dictionary.token("УстарелоКурсы") == "Rates"


def test_without_an_english_spelling_of_the_prefix_the_entry_is_written_as_it_is(monkeypatch):
    monkeypatch.setattr(terms, "deprecation_prefixes", lambda: ("Устарело",))
    assert Dictionary(tokens={"УстарелоКурсы": "Rates"}).token("УстарелоКурсы") == "Rates"


def test_the_entry_itself_stays_as_the_file_writes_it(pair):
    """The prefix belongs to the spelling of the tree, not to the entry: a listing of the
    dictionary and a rewrite of its files see the value the author wrote."""
    dictionary = Dictionary(tokens={"УстарелоКурсы": "Rates"})
    assert dictionary.token("УстарелоКурсы") == "DeprecatedRates"
    assert dictionary.tokens == {"УстарелоКурсы": "Rates"}


_PHRASE = "Курсы валют хранит УстарелоКурсы."


@pytest.mark.parametrize("value, drifted", [
    ("Exchange rates are kept by ObsoleteRates.", True),
    ("Exchange rates are kept by DeprecatedObsoleteRates.", False),
])
def test_a_comment_naming_the_bare_entry_drifts_from_the_tree(pair, value, drifted):
    """The English tree spells the name with the prefix, so a comment that names it after the
    bare entry names something the tree does not have."""
    dictionary = Dictionary(tokens={"УстарелоКурсы": "ObsoleteRates"}, phrases={_PHRASE: value})
    rows = drift.phrase_drift(dictionary)
    if drifted:
        assert [(row.name, row.expected[0], row.found) for row in rows] == [
            ("УстарелоКурсы", "DeprecatedObsoleteRates", ("ObsoleteRates",)),
        ]
    else:
        assert rows == []


_BATCHES = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-0000000001a1
Имя: УстарелоПартии
ОбластьВидимости: ВПроекте
Интерфейс:
    Список:
        Представление: (не используется) Партии
    Объект:
        Представление: Партия
"""
_GOODS = """\
ВидЭлемента: Справочник
Ид: 1d1f5c60-0000-4000-8000-0000000001a2
Имя: Товары
ОбластьВидимости: ВПроекте
Реквизиты:
    -
        Ид: 1d1f5c60-0000-4000-8000-0000000001a3
        Имя: Партия
        Тип: УстарелоПартии.Ссылка
Интерфейс:
    Список:
        Представление: Товары
    Объект:
        Представление: Товар
"""
_ACCOUNTING = """\
ВидЭлемента: ОбщийМодуль
Ид: 1d1f5c60-0000-4000-8000-0000000001a4
Имя: Учет
ОбластьВидимости: ВПроекте
"""
_ACCOUNTING_CODE = """\
метод ПустаяПартия(): УстарелоПартии.Ссылка?
    возврат Неопределено
;
"""
_TOKENS = {"УстарелоПартии": "ObsoleteBatches", "Товары": "Goods", "Партия": "Batch",
           "Учет": "Accounting", "ПустаяПартия": "EmptyBatch"}


@pytest.mark.needs_data
def test_a_translated_project_spells_the_deprecated_name_the_same_everywhere(tmp_path):
    """The declaration, the name of its file, a type in another description and a type in a
    module all move together, and naming/presentation knows the element in the English tree."""
    root = tmp_path / "ru"
    root.mkdir()
    files = {"УстарелоПартии.yaml": _BATCHES, "Товары.yaml": _GOODS, "Учет.yaml": _ACCOUNTING,
             "Учет.xbsl": _ACCOUNTING_CODE}
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    out = tmp_path / "en"
    report = translate_project(root, Dictionary(tokens=_TOKENS), out=out)
    assert not report.problems
    assert not {name for file in report.files.values() for name in file.missing_tokens}

    written = {path.name: path.read_text(encoding="utf-8") for path in out.rglob("*.*")}
    assert "Name: DeprecatedObsoleteBatches\n" in written["DeprecatedObsoleteBatches.yaml"]
    assert "Type: DeprecatedObsoleteBatches.Reference\n" in written["Goods.yaml"]
    assert "DeprecatedObsoleteBatches.Reference?" in written["Accounting.xbsl"]
    assert not any("ObsoleteBatches" in text.replace("DeprecatedObsoleteBatches", "")
                   for text in written.values())

    found = engine.run(engine.find_sources(out, "*.yaml"), select={"naming/presentation"})
    assert [(Path(d.path).name, d.line) for d in found] == [("DeprecatedObsoleteBatches.yaml", 9)]
    assert "(not used)" in found[0].message
