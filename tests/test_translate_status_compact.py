"""`translate_status` with `against`: the duplicates the target branch already has are counted.

A duplicate - a key translated the same way in two places - is harmless to the load and stays
until a person takes the copy out, so the collisions report brought the same rows back on every
call of a branch: six of them, some three thousand characters a call, five calls a session. The
tool now lists only the duplicates the ref does not have - the ones the branch brings - and
counts the rest; `full=true` gives the whole list. The conflicts are listed whole either way.
The CLI `--check-duplicates` report is not touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xbsl.translation import cli as translate_cli

_HEAD = "version: 1\nlanguage: en\n\n"
_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


def _write(folder: Path, name: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(_HEAD + body, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


@pytest.fixture
def branches(tmp_path: Path) -> tuple[Path, Path]:
    """Branch `feature` against `main`: one duplicate from the base, one the branch brings.

    The base translates `Склады` in two files - both branches carry that copy. The feature
    translates `Партии` and `Курсы`; `main` then translates them too, `Партии` differently (a
    conflict) and `Курсы` the same way (a duplicate only the merge makes).
    """
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    project = tmp_path / "vendor" / "app"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    (project / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n",
        encoding="utf-8",
    )
    dictionary = tmp_path / "xbsl-translation"
    _write(dictionary, "010-base.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n")
    _write(dictionary, "015-copy.yaml", "tokens:\n    Склады: Warehouses\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    _write(dictionary, "020-feature.yaml", "tokens:\n    Партии: Batches\n    Курсы: Rates\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the feature translates its gaps")
    _git(tmp_path, "checkout", "-q", "main")
    _write(dictionary, "030-other.yaml", "tokens:\n    Партии: Lots\n    Курсы: Rates\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the target translated the same gaps")
    _git(tmp_path, "checkout", "-q", "feature")
    return project, dictionary


def test_the_compact_report_lists_only_what_the_branch_brings(branches):
    _project, dictionary = branches

    report = translate_cli.collisions_report(dictionary, "main", compact=True)

    assert [row["key"] for row in report["duplicates"]] == ["Курсы"]
    assert (report["duplicates_total"], report["duplicates_at_ref"]) == (2, 1)
    assert "main" in report["duplicates_hint"] and "full=true" in report["duplicates_hint"]
    assert [row["key"] for row in report["conflicts"]] == ["Партии"]
    assert report["against"]["ref"] == "main"


def test_the_full_report_is_the_one_the_cli_prints(branches):
    _project, dictionary = branches

    report = translate_cli.collisions_report(dictionary, "main")

    assert [row["key"] for row in report["duplicates"]] == ["Курсы", "Склады"]
    assert set(report) == {"dictionary", "against", "conflicts", "duplicates"}


def test_nothing_at_the_ref_means_nothing_omitted(branches):
    """The negative control: without the base copy every duplicate is the branch's own."""
    _project, dictionary = branches
    (dictionary / "015-copy.yaml").unlink()
    _git(dictionary.parent, "add", "-A")
    _git(dictionary.parent, "commit", "-q", "-m", "the copy is taken out on the branch")

    report = translate_cli.collisions_report(dictionary, "main", compact=True)

    # The copy is gone from the branch, but main still carries it: the three-way view keeps it
    # out, since the removal is the branch's edit of a file both sides have.
    assert [row["key"] for row in report["duplicates"]] == ["Курсы"]
    assert (report["duplicates_total"], report["duplicates_at_ref"]) == (1, 0)
    assert "duplicates_hint" not in report


def test_without_a_ref_compact_changes_nothing(branches):
    _project, dictionary = branches

    assert translate_cli.collisions_report(dictionary, compact=True) == \
        translate_cli.collisions_report(dictionary)


@pytest.mark.needs_data
def test_the_cli_check_prints_the_whole_list_as_before(branches, capsys):
    project, _dictionary = branches

    code = translate_cli.cli_main([str(project), "--check-duplicates", "--against", "main",
                                   "--format", "json", "--lang", "ru"])
    report = json.loads(capsys.readouterr().out)

    assert code == 1
    assert [row["key"] for row in report["duplicates"]] == ["Курсы", "Склады"]
    assert "duplicates_total" not in report


@pytest.mark.needs_data
def test_translate_status_is_compact_unless_full_is_asked(mcp_module, branches):
    project, _dictionary = branches

    short = mcp_module.translate_status(str(project), against="main")
    whole = mcp_module.translate_status(str(project), against="main", full=True)

    assert [row["key"] for row in short["collisions"]["duplicates"]] == ["Курсы"]
    assert short["collisions"]["duplicates_at_ref"] == 1
    assert [row["key"] for row in whole["collisions"]["duplicates"]] == ["Курсы", "Склады"]
    assert "duplicates_at_ref" not in whole["collisions"]
    assert short["duplicates"] == whole["duplicates"] == 1  # the working tree's own count
    assert len(json.dumps(short, ensure_ascii=False)) < len(json.dumps(whole, ensure_ascii=False))
