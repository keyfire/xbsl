"""The last line of the translate report is a verdict: READY, or NOT READY with the counts.

The report used to end the same way with zero gaps and with hundreds - the coverage, then the
list of incomplete objects - and the only differences were a line in the middle and the exit
code. A log read from its tail passed a tree with hundreds of Russian names as done. The exit
code is unchanged: `--strict` still decides it, the verdict only says out loud what it decides.
"""

import json
from pathlib import Path

import pytest

from xbsl.translation import cli

pytestmark = pytest.mark.needs_data


def _project(tmp_path: Path, tokens: str) -> tuple[Path, Path]:
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Задачи\nРеквизиты:\n    -\n        Имя: Шаг\n        Тип: Строка\n",
        encoding="utf-8",
    )
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(f"version: 1\nlanguage: en\ntokens:\n{tokens}", encoding="utf-8")
    return root, dictionary


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


def test_a_complete_translation_ends_with_ready(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Задачи: Tasks\n    Шаг: Step\n")
    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict"])
    assert code == 0
    assert lines[-1] == "ГОТОВО"


def test_gaps_end_with_not_ready_and_the_counts(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Задачи: Tasks\n")
    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary)])
    assert code == 0, "the verdict does not change the exit code without --strict"
    assert lines[-1] == "НЕ ГОТОВО: токенов 1, фраз 0"

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--strict"])
    assert code == 1
    assert lines[-1] == "НЕ ГОТОВО: токенов 1, фраз 0"


def test_the_verdict_stays_last_after_the_coverage_table(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Задачи: Tasks\n")
    out = tmp_path / "out"
    _code, lines = _run(capsys, [
        str(root), "--dictionary", str(dictionary), "--coverage", "--out", str(out),
    ])
    assert any(line.startswith("  Задачи: ") for line in lines), lines
    assert lines[-2].startswith("записано файлов: ")
    assert lines[-1] == "НЕ ГОТОВО: токенов 1, фраз 0"


def test_the_verdict_speaks_english_too(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Задачи: Tasks\n")
    code = cli.cli_main([str(root), "--dictionary", str(dictionary), "--lang", "en"])
    assert code == 0
    assert capsys.readouterr().out.rstrip("\n").splitlines()[-1] == "NOT READY: tokens 1, phrases 0"


def test_the_json_report_carries_the_same_verdict(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    Задачи: Tasks\n")
    cli.cli_main([str(root), "--dictionary", str(dictionary), "--format", "json", "--lang", "ru"])
    report = json.loads(capsys.readouterr().out)
    assert report["ready"] is False
    assert report["totals"]["missing_tokens"] == 1
