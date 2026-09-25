"""Phrases whose translation names a name otherwise than its pair (`translate --drift`).

A phrase entry translates a comment line whole, names included, and nothing ties those names
to the tokens section. A token renamed after the phrase was written - or a line translated
with its own idea of a name - leaves the English comment naming something the English tree
does not have; the only trace used to be a `comment/unknown-name` finding on the English
tree, pointing at the comment rather than at the entry. The check reads the dictionary alone:
a name of the key with a pair (the project token, or the platform's English spelling) whose
translation carries none of the pair's spellings and names something unknown instead.

The core runs on a dictionary object and needs no Element data (without the data the
platform half has nothing to offer, and the token half is the whole check); the platform
spelling, the CLI and the MCP tool carry `needs_data`.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli, i18n
from xbsl.translation import drift
from xbsl.translation.dictionary import Dictionary

KEY = "Пишет отметку (ОбщееСклада.Отметить) в журнал склада"


def _dictionary(value, tokens=None, key=KEY):
    return Dictionary(
        tokens=tokens if tokens is not None else {"ОбщееСклада": "StockCommon"},
        phrases={key: value},
    )


def test_a_renamed_token_left_behind_in_the_phrase_is_reported():
    rows = drift.phrase_drift(_dictionary("Writes a mark (WarehouseCommon.Mark) to the stock log"))
    assert [(r.name, r.expected, r.found) for r in rows] == [
        ("ОбщееСклада", ("StockCommon",), ("WarehouseCommon",)),
    ]
    assert rows[0].key == KEY and rows[0].as_dict()["found"] == ["WarehouseCommon"]


def test_the_spelling_of_the_pair_is_silent():
    assert drift.phrase_drift(_dictionary("Writes a mark (StockCommon.Mark) to the stock log")) == []


def test_a_name_rendered_in_plain_words_is_silent():
    """The English line names nothing, so there is nothing to rename."""
    assert drift.phrase_drift(_dictionary("Writes a mark to the log of the warehouse")) == []


def test_a_translation_naming_another_known_name_is_silent():
    tokens = {"ОбщееСклада": "StockCommon", "ЖурналСклада": "WarehouseCommon"}
    value = "Writes a mark (WarehouseCommon.Mark) to the stock log"
    assert drift.phrase_drift(_dictionary(value, tokens)) == []


def test_a_scoped_token_counts_as_a_spelling():
    tokens = {"ОбщееСклада": "StockCommon", "Сообщения.ОбщееСклада": "SharedStock"}
    value = "Writes a mark (SharedStock.Mark) to the stock log"
    assert drift.phrase_drift(_dictionary(value, tokens)) == []


def test_a_name_the_translation_keeps_in_russian_is_left_to_the_gaps():
    value = "Writes a mark (ОбщееСклада.Mark) to the WarehouseCommon log"
    assert drift.phrase_drift(_dictionary(value)) == []


def test_a_name_without_a_pair_is_not_judged():
    assert drift.phrase_drift(_dictionary("Writes a mark (WarehouseCommon.Mark)", tokens={})) == []


def test_every_name_of_a_line_is_judged_on_its_own():
    tokens = {"ОбщееСклада": "StockCommon", "ЖурналОстатков": "BalanceLog"}
    key = "ОбщееСклада пишет в ЖурналОстатков"
    rows = drift.phrase_drift(_dictionary("StockCommon writes to the RestLog", tokens, key))
    assert [(r.name, r.found) for r in rows] == [("ЖурналОстатков", ("RestLog",))]


@pytest.mark.needs_data
def test_a_platform_name_spelled_otherwise_is_reported():
    """No token: the pair is the platform's English name."""
    key = "стандартный Цвета.Стилевые.ФонПервичный, чтобы полотно совпало с формой"
    value = "the standard Colors.Style.PrimaryBackground so that the canvas matches the form"
    rows = drift.phrase_drift(_dictionary(value, tokens={}, key=key))
    assert [(r.name, r.found) for r in rows] == [("ФонПервичный", ("PrimaryBackground",))]
    assert "BackgroundPrimary" in rows[0].expected


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "Acme" / "Stock"
    root.mkdir(parents=True)
    (root / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nИмя: Склад\nПоставщик: Acme\n",
        encoding="utf-8",
    )
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010-tokens.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    ОбщееСклада: StockCommon\n", encoding="utf-8",
    )
    (folder / "030-phrases.yaml").write_text(
        "version: 1\nlanguage: en\nphrases:\n"
        f"    \"{KEY}\": \"Writes a mark (WarehouseCommon.Mark) to the stock log\"\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.needs_data
def test_cli_lists_the_drift_with_the_place_of_the_entry(tmp_path, capsys):
    root = _project(tmp_path)
    code = cli.main(["translate", str(root), "--drift", "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0 and payload["total"] == 1
    row = payload["drift"][0]
    assert (row["name"], row["expected"], row["found"]) == (
        "ОбщееСклада", ["StockCommon"], ["WarehouseCommon"])
    assert Path(row["file"]).name == "030-phrases.yaml" and row["line"] == 4
    assert "comment/unknown-name" in payload["note"]


@pytest.mark.needs_data
def test_cli_text_report_and_filter(tmp_path, capsys):
    root = _project(tmp_path)
    i18n.set_lang("ru")
    code = cli.main(["translate", str(root), "--drift", "--lang", "ru"])
    out = capsys.readouterr().out
    assert code == 0
    assert "ОбщееСклада -> StockCommon, а перевод называет WarehouseCommon" in out
    assert "030-phrases.yaml:4" in out
    cli.main(["translate", str(root), "--drift", "--filter", "нет-такого", "--lang", "ru"])
    assert "таких фраз нет" in capsys.readouterr().out


@pytest.mark.needs_data
def test_the_mcp_tool_answers_by_page(tmp_path, mcp_module):
    root = _project(tmp_path)
    answer = mcp_module.translate_drift(str(root), limit=1)
    assert answer["total"] == 1 and answer["drift"][0]["found"] == ["WarehouseCommon"]
    assert mcp_module.translate_drift(str(root), filter="нет-такого")["total"] == 0


def test_the_mcp_tool_refuses_a_root_without_a_dictionary(tmp_path, mcp_module):
    root = tmp_path / "Acme" / "Stock"
    root.mkdir(parents=True)
    (root / "Проект.yaml").write_text("Имя: Склад\n", encoding="utf-8")
    assert set(mcp_module.translate_drift(str(root))) == {"error"}
