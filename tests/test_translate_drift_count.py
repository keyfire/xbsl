"""The plain `translate` report counts the phrase drift that `--drift` lists.

`--drift` is a mode of its own and stays out of `--strict`: a phrase naming a name otherwise
than its pair breaks no build, the English comment only names something the English tree does
not have. So a drift was found only by whoever thought of running the mode. The plain report
now carries one line with the count and the flag that lists them, and only when there is
something to count; the json report and `translate_status` carry the same number. The exit code
does not change: `--strict` still answers whether the tree builds.

The count itself runs on a dictionary object and needs no Element data; the CLI and the MCP
tool carry `needs_data`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from xbsl import cli
from xbsl.translation import cli as translate_cli
from xbsl.translation.dictionary import Dictionary

KEY = "Пишет отметку (ОбщееСклада.Отметить) в журнал склада"
DRIFTED = "Writes a mark (WarehouseCommon.Mark) to the stock log"
FAITHFUL = "Writes a mark (StockCommon.Mark) to the stock log"
COUNTER = "фраз, где имя названо не по паре: 1 (список – --drift)"


def test_the_count_is_the_number_of_rows_the_mode_lists():
    tokens = {"ОбщееСклада": "StockCommon"}
    assert translate_cli.drift_count(Dictionary(tokens=tokens, phrases={KEY: DRIFTED})) == 1
    assert translate_cli.drift_count(Dictionary(tokens=tokens, phrases={KEY: FAITHFUL})) == 0
    assert translate_cli.drift_count(Dictionary()) == 0


def _project(tmp_path: Path, value: str) -> Path:
    root = tmp_path / "Acme" / "Stock"
    root.mkdir(parents=True)
    (root / "Проект.yaml").write_text(
        "Ид: ffeacdec-02d6-4f08-bcfa-be89e9a1861a\nИмя: Склад\nПоставщик: Acme\n",
        encoding="utf-8",
    )
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    # The name of the project has its pair as well: the tree is ready, so the exit code of
    # `--strict` below answers for the drift alone.
    (folder / "010-tokens.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    ОбщееСклада: StockCommon\n    Склад: Stock\n",
        encoding="utf-8",
    )
    (folder / "030-phrases.yaml").write_text(
        f"version: 1\nlanguage: en\nphrases:\n    \"{KEY}\": \"{value}\"\n", encoding="utf-8",
    )
    return root


@pytest.mark.needs_data
def test_the_plain_report_counts_the_drift_and_the_exit_code_stays(tmp_path, capsys):
    root = _project(tmp_path, DRIFTED)

    code = cli.main(["translate", str(root), "--strict", "--lang", "ru"])
    out = capsys.readouterr().out

    assert COUNTER in out.splitlines()
    # the drift breaks no build: the verdict and the exit code answer that question alone
    assert code == 0 and out.rstrip().splitlines()[-1].startswith("ГОТОВО")


@pytest.mark.needs_data
def test_a_faithful_dictionary_prints_no_counter(tmp_path, capsys):
    root = _project(tmp_path, FAITHFUL)

    assert cli.main(["translate", str(root), "--strict", "--lang", "ru"]) == 0
    assert "--drift" not in capsys.readouterr().out


@pytest.mark.needs_data
def test_the_json_report_carries_the_count(tmp_path, capsys):
    drifted = _project(tmp_path / "drifted", DRIFTED)
    faithful = _project(tmp_path / "faithful", FAITHFUL)

    cli.main(["translate", str(drifted), "--format", "json"])
    assert json.loads(capsys.readouterr().out)["dictionary_drift"] == 1
    cli.main(["translate", str(faithful), "--format", "json"])
    assert json.loads(capsys.readouterr().out)["dictionary_drift"] == 0


@pytest.mark.needs_data
def test_translate_status_counts_the_drift(tmp_path, mcp_module):
    root = _project(tmp_path, DRIFTED)

    status = mcp_module.translate_status(str(root))

    assert status["drift"] == 1 and status["duplicates"] == 0
