"""The report says when the dictionary is behind the sources.

The count of project surfaces was the only sign that a local report had gone stale after an
edit, and noticing it took comparing that number by eye with a report from elsewhere. The mark
answers the question the number stood in for: has the code moved since the dictionary last did.
"""

import json
import os
from pathlib import Path

import pytest

from xbsl.translation import cli

pytestmark = pytest.mark.needs_data


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Задачи\nРеквизиты:\n    -\n        Имя: Шаг\n"
        "        Тип: Строка\n",
        encoding="utf-8",
    )
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(
        "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n    Шаг: Step\n",
        encoding="utf-8",
    )
    return root, dictionary


def _touch(path: Path, when: float) -> None:
    os.utime(path, (when, when))


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


def test_a_source_newer_than_the_dictionary_is_named(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path)
    _touch(dictionary, 1_700_000_000)
    _touch(root / "Задачи.yaml", 1_700_000_100)

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary)])

    assert code == 0, "the mark decides nothing - the gaps still own the verdict"
    behind = [line for line in lines if "словарь отстаёт" in line]
    assert behind, lines
    assert "Задачи.yaml" in behind[0]


def test_a_dictionary_newer_than_the_sources_says_nothing(tmp_path: Path, capsys):
    """The control: the dictionary was filled in, so there is no mark."""
    root, dictionary = _project(tmp_path)
    _touch(root / "Задачи.yaml", 1_700_000_000)
    _touch(dictionary, 1_700_000_100)

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary)])

    assert not [line for line in lines if "словарь отстаёт" in line], lines


def test_the_mark_is_a_field_of_the_json_report(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path)
    _touch(dictionary, 1_700_000_000)
    _touch(root / "Задачи.yaml", 1_700_000_100)

    _code, lines = _run(
        capsys, [str(root), "--dictionary", str(dictionary), "--format", "json"]
    )

    report = json.loads("\n".join(lines))
    assert report["dictionary_behind"]["files"] == 1
    assert report["dictionary_behind"]["newest"].endswith("Задачи.yaml")


def test_without_a_dictionary_there_is_nothing_to_lag_behind(tmp_path: Path, capsys):
    root, _dictionary = _project(tmp_path)

    _code, lines = _run(capsys, [str(root), "--format", "json"])

    report = json.loads("\n".join(lines))
    assert report["dictionary_behind"] is None
