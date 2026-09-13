"""The keys more than one dictionary file translates: named all at once, and before the merge.

Two branches once closed the same gaps, each in a dictionary file of its own. Each pipeline
was green, and the target branch failed at the dictionary load after the merge - ten keys
translated twice, four of them differently - while git had shown no conflict, since the files
differed. The load then refused the FIRST colliding key and stopped, so the fix was a loop:
take one out, load again, meet the next. Two things changed. The load reads every file before
it refuses and names every conflict in one error. And `--check-duplicates` answers the question
before the merge: with `--against` naming the target branch, the dictionary files of that
branch are read out of git and laid over the working tree's, so a branch sees the collision it
would bring in while it is still a branch.

The reading of the files needs no Element data. The CLI and the MCP tool do, since the command
resolves the language data before anything else and the tool runs the translation pass.
"""

from __future__ import annotations

import codecs
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from xbsl.translation import cli, dictionary as dictionary_module, entries

_HEAD = "version: 1\nlanguage: en\n"


def _write(folder: Path, name: str, body: str, head: str = _HEAD) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / name
    file.write_text(head + body, encoding="utf-8")
    return file


# --- the load names every conflict at once --------------------------------------------------


def test_two_conflicts_in_two_pairs_of_files_are_refused_in_one_error(tmp_path: Path):
    """One key differs between a and b, another between b and c: one refusal, both named."""
    folder = tmp_path / "xbsl-translation"
    a = _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n")
    b = _write(folder, "b.yaml", "tokens:\n    Задачи: Jobs\n    Склады: Warehouses\n", head="")
    c = _write(folder, "c.yaml", "tokens:\n    Склады: Depots\n", head="")

    with pytest.raises(dictionary_module.DictionaryError) as refusal:
        dictionary_module.load(folder)

    text = str(refusal.value)
    assert ": 2" in text.splitlines()[0]
    assert f"[tokens] Задачи: {a}:4 = 'Tasks'; {b}:2 = 'Jobs'" in text
    assert f"[tokens] Склады: {b}:3 = 'Warehouses'; {c}:2 = 'Depots'" in text


def test_three_conflicts_across_three_files_and_two_sections_are_all_named(tmp_path: Path):
    """The whole list at once, the tokens plane before the phrases plane."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\nphrases:\n    текст: text\n")
    _write(folder, "b.yaml", "tokens:\n    Задачи: Jobs\n    Партии: Batches\n", head="")
    _write(folder, "c.yaml", "tokens:\n    Партии: Lots\nphrases:\n    текст: prose\n", head="")

    with pytest.raises(dictionary_module.DictionaryError) as refusal:
        dictionary_module.load(folder)

    lines = str(refusal.value).splitlines()
    assert ": 3" in lines[0]
    keys = [line.split("] ", 1)[1].split(":", 1)[0] for line in lines[1:]]
    assert keys == ["Задачи", "Партии", "текст"]
    assert lines[3].startswith("  [phrases] текст: ")


def test_a_key_translated_the_same_way_twice_loads_and_is_kept_as_a_duplicate(tmp_path: Path):
    """The lookups do not care; the second copy is listed for the person who takes it out."""
    folder = tmp_path / "xbsl-translation"
    a = _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n")
    b = _write(folder, "b.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Depots\n", head="")

    loaded = dictionary_module.load(folder)

    assert loaded.tokens == {"Задачи": "Tasks", "Склады": "Depots"}
    assert loaded.duplicates == [{
        "section": "tokens", "key": "Задачи",
        "places": [{"file": str(a), "line": 4, "value": "Tasks"},
                   {"file": str(b), "line": 2, "value": "Tasks"}],
    }]


def test_a_third_reading_that_matches_one_of_two_is_still_a_conflict():
    """Two files agreeing does not outvote the third: three places, two values, a conflict."""
    conflicts, duplicates = dictionary_module.collisions([
        ("a.yaml", {"tokens": [("Задачи", "Tasks", 1)]}),
        ("b.yaml", {"tokens": [("Задачи", "Tasks", 1)]}),
        ("c.yaml", {"tokens": [("Задачи", "Jobs", 1)]}),
    ])

    assert duplicates == []
    assert [place["file"] for place in conflicts[0]["places"]] == ["a.yaml", "b.yaml", "c.yaml"]


def test_the_rows_come_in_section_order_then_by_key():
    conflicts, duplicates = dictionary_module.collisions([
        ("a.yaml", {"phrases": [("текст", "text", 5)],
                    "tokens": [("Склады", "Depots", 2), ("Задачи", "Tasks", 3)]}),
        ("b.yaml", {"phrases": [("текст", "text", 5)],
                    "tokens": [("Склады", "Stores", 2), ("Задачи", "Jobs", 3)]}),
    ])

    assert [(row["section"], row["key"]) for row in conflicts] == [
        ("tokens", "Задачи"), ("tokens", "Склады"),
    ]
    assert [(row["section"], row["key"]) for row in duplicates] == [("phrases", "текст")]


def test_the_report_lines_carry_the_section_the_key_and_every_place():
    conflict = {"section": "tokens", "key": "Задачи",
                "places": [{"file": "a.yaml", "line": 3, "value": "Tasks"},
                           {"file": "b.yaml", "line": 5, "value": "Jobs"}]}
    duplicate = {"section": "phrases", "key": "текст",
                 "places": [{"file": "a.yaml", "line": 7, "value": "text"},
                            {"file": "b.yaml", "line": 9, "value": "text"}]}

    assert dictionary_module.collision_line(conflict) == "[tokens] Задачи: a.yaml:3 = 'Tasks'; b.yaml:5 = 'Jobs'"
    assert dictionary_module.duplicate_line(duplicate) == "[phrases] текст = 'text': a.yaml:7, b.yaml:9"


# --- the same file at a ref is the same file -------------------------------------------------


def test_overlay_reads_the_same_file_at_the_ref_as_one_file():
    """A key the working tree spells differently is its own edit; the rest of the ref's copy
    comes in under the ref's name, and a file the working tree lacks comes in whole."""
    working = [("a.yaml", {"tokens": [("Задачи", "Jobs", 4)]})]
    at_ref = [
        ("a.yaml", {"tokens": [("Задачи", "Tasks", 4), ("Склады", "Depots", 5)]}),
        ("b.yaml", {"tokens": [("Партии", "Lots", 4)]}),
    ]

    merged = dictionary_module.overlay(working, at_ref, "main")

    assert merged == working + [
        ("main:a.yaml", {"tokens": [("Склады", "Depots", 5)]}),
        ("main:b.yaml", {"tokens": [("Партии", "Lots", 4)]}),
    ]
    assert dictionary_module.collisions(merged) == ([], [])


def test_read_sections_names_the_files_relative_to_the_dictionary(tmp_path: Path):
    """The names the ref's copies are matched by: POSIX, relative, a nested file included."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n")
    _write(folder / "more", "b.yaml", "phrases:\n    текст: text\n", head="")

    assert dictionary_module.read_sections(folder) == [
        ("a.yaml", {"tokens": [("Задачи", "Tasks", 4)]}),
        ("more/b.yaml", {"phrases": [("текст", "text", 2)]}),
    ]
    single = _write(tmp_path, "xbsl-translation.yaml", "tokens:\n    Задачи: Tasks\n")
    assert dictionary_module.read_sections(single) == [
        ("xbsl-translation.yaml", {"tokens": [("Задачи", "Tasks", 4)]}),
    ]


# --- the files at a ref, read out of git ------------------------------------------------------


_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


def _git(repo: Path, *args: str) -> str:
    """One git call in the throwaway repository these tests build."""
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


@pytest.fixture
def branches(tmp_path: Path) -> tuple[Path, Path]:
    """A repository on branch `feature`, whose target `main` moved on after the fork.

    The base commit holds `010-base.yaml`. The feature branch adds `020-feature.yaml`
    with two keys; `main` then adds `030-other.yaml` translating the same two - one of them
    differently (the conflict the merge would bring in) and one the same way (the redundant
    copy). The file on `main` carries a byte order mark, the way an editor on Windows writes
    one, so the read out of git is held to the same reading as the files on disk.

    Returns (the project directory, the dictionary directory).
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
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    _write(dictionary, "020-feature.yaml", "tokens:\n    Партии: Batches\n    Курсы: Rates\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the feature translates its gaps")
    _git(tmp_path, "checkout", "-q", "main")
    (dictionary / "030-other.yaml").write_bytes(
        codecs.BOM_UTF8 + (_HEAD + "tokens:\n    Партии: Lots\n    Курсы: Rates\n").encode("utf-8"))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "another branch translated the same gaps")
    _git(tmp_path, "checkout", "-q", "feature")
    return project, dictionary


def test_the_files_at_a_ref_come_back_by_their_dictionary_names_without_the_mark(branches):
    _project, dictionary = branches

    copies = dict(entries.dictionary_at(dictionary, "main"))

    assert sorted(copies) == ["010-base.yaml", "030-other.yaml"]
    assert copies["030-other.yaml"].startswith("version: 1")
    assert dictionary_module.sections_of("main:030-other.yaml", copies["030-other.yaml"]) == {
        "tokens": [("Партии", "Lots", 4), ("Курсы", "Rates", 5)],
    }


def test_a_branch_sees_the_collision_with_its_target_before_the_merge(branches):
    """Alone the branch is clean; against `main` the conflict and the duplicate are named."""
    _project, dictionary = branches

    alone = cli.collisions_report(dictionary)
    against = cli.collisions_report(dictionary, "main")

    assert (alone["conflicts"], alone["duplicates"], alone["against"]) == ([], [], None)
    assert against["against"] == {"ref": "main", "files": 2, "added": 2}
    assert against["conflicts"] == [{
        "section": "tokens", "key": "Партии",
        "places": [{"file": "020-feature.yaml", "line": 4, "value": "Batches"},
                   {"file": "main:030-other.yaml", "line": 4, "value": "Lots"}],
    }]
    assert [(row["key"], [place["file"] for place in row["places"]])
            for row in against["duplicates"]] == [("Курсы", ["020-feature.yaml", "main:030-other.yaml"])]


def test_a_value_changed_in_the_same_file_is_not_a_collision(branches):
    """The working tree's copy of a file wins over the ref's: an edit, not a second reading."""
    _project, dictionary = branches
    _write(dictionary, "010-base.yaml", "tokens:\n    Задачи: Jobs\n    Склады: Warehouses\n")
    (dictionary / "020-feature.yaml").unlink()  # leaves only the edit to judge

    report = cli.collisions_report(dictionary, "main")

    assert report["conflicts"] == []
    assert report["against"]["added"] == 2  # the two keys of the file `main` added


def test_a_file_removed_in_the_working_tree_but_alive_at_the_ref_still_counts(branches):
    """The merge brings the file back, so its keys are judged as if it were still there."""
    _project, dictionary = branches
    (dictionary / "010-base.yaml").unlink()
    (dictionary / "020-feature.yaml").unlink()
    _write(dictionary, "040-moved.yaml", "tokens:\n    Задачи: Jobs\n")

    assert cli.collisions_report(dictionary)["conflicts"] == []
    conflicts = cli.collisions_report(dictionary, "main")["conflicts"]

    assert [(row["key"], [place["file"] for place in row["places"]]) for row in conflicts] == [
        ("Задачи", ["040-moved.yaml", "main:010-base.yaml"]),
    ]


def test_an_unknown_ref_and_a_dictionary_outside_git_are_refused_by_name(branches, tmp_path):
    _project, dictionary = branches

    with pytest.raises(ValueError) as unknown:
        entries.dictionary_at(dictionary, "нет-такой-ветки")
    assert "нет-такой-ветки" in str(unknown.value)

    outside = tmp_path.parent / f"{tmp_path.name}-outside" / "xbsl-translation"
    _write(outside, "a.yaml", "tokens:\n    Задачи: Tasks\n")
    with pytest.raises(ValueError) as refusal:
        entries.dictionary_at(outside, "main")
    assert str(outside) in str(refusal.value)
    assert "error" in cli.collisions_report(outside, "main")


def test_every_git_child_of_the_read_is_told_what_its_stdin_is(branches, monkeypatch):
    """The batch read feeds git the object names; the other calls get an empty stdin. A child
    left to inherit the stdin of an MCP or LSP server never reaches its own exit on Windows."""
    _project, dictionary = branches
    seen: list[dict] = []
    real = subprocess.run

    def spy(command, **options):
        seen.append(options)
        return real(command, **options)

    monkeypatch.setattr(subprocess, "run", spy)
    entries.dictionary_at(dictionary, "main")

    assert len(seen) == 4
    assert all("stdin" in options or "input" in options for options in seen)
    assert isinstance(seen[-1]["input"], bytes) and b"010-base.yaml" in seen[-1]["input"]


# --- the command and the tool -----------------------------------------------------------------


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


@pytest.mark.needs_data
def test_the_check_passes_the_branch_alone_and_fails_it_against_the_target(branches, capsys):
    project, _dictionary = branches

    code, lines = _run(capsys, [str(project), "--check-duplicates"])
    assert code == 0
    assert lines[-1] == "ключей, переведённых по-разному, нет"

    code, lines = _run(capsys, [str(project), "--check-duplicates", "--against", "main"])
    assert code == 1
    assert lines[0].startswith("сравнение с main: файлов словаря там 2")
    assert "  [tokens] Курсы = 'Rates': 020-feature.yaml:5, main:030-other.yaml:5" in lines
    assert lines[-1] == "  [tokens] Партии: 020-feature.yaml:4 = 'Batches'; main:030-other.yaml:4 = 'Lots'"

    code, out = _run(capsys, [str(project), "--check-duplicates", "--against", "main",
                              "--format", "json"])
    report = json.loads("\n".join(out))
    assert code == 1 and report["against"]["ref"] == "main"
    assert [row["key"] for row in report["conflicts"]] == ["Партии"]
    assert [row["key"] for row in report["duplicates"]] == ["Курсы"]


@pytest.mark.needs_data
def test_a_strict_run_over_a_conflicting_dictionary_names_every_conflict(branches, capsys):
    """What the merge used to meet one key at a time: both keys in the one refusal."""
    project, dictionary = branches
    _write(dictionary, "050-more.yaml", "tokens:\n    Задачи: Jobs\n    Склады: Depots\n")

    code = cli.cli_main([str(project), "--strict", "--lang", "ru"])

    err = capsys.readouterr().err
    assert code == 2
    assert "[tokens] Задачи:" in err and "[tokens] Склады:" in err


@pytest.mark.needs_data
def test_the_plain_report_counts_the_keys_translated_the_same_way_twice(branches, capsys):
    project, dictionary = branches
    _write(dictionary, "050-more.yaml", "tokens:\n    Задачи: Tasks\n")

    _code, lines = _run(capsys, [str(project)])
    assert "ключей, переведённых одинаково в нескольких местах: 1 (список – --check-duplicates)" in lines

    _code, out = _run(capsys, [str(project), "--format", "json"])
    assert [row["key"] for row in json.loads("\n".join(out))["dictionary_duplicates"]] == ["Задачи"]


@pytest.mark.needs_data
def test_the_flags_the_check_cannot_honor_are_refused_by_name(branches, capsys):
    project, _dictionary = branches

    code, lines = _run(capsys, [str(project), "--against", "main"])
    assert code == 2 and lines == ["--against читается только вместе с --check-duplicates"]

    code, lines = _run(capsys, [str(project), "--check-duplicates", "--limit", "5", "--prune"])
    assert code == 2 and lines[0].startswith("режим --check-duplicates не читает эти ключи: --limit, --prune")

    code, lines = _run(capsys, [str(project), "--check-duplicates", "--out", str(project / "x")])
    assert code == 2 and "--out" in lines[0]


@pytest.mark.needs_data
def test_translate_status_carries_the_collisions_against_a_ref(mcp_module, branches):
    project, dictionary = branches

    status = mcp_module.translate_status(str(project), against="main")

    assert status["duplicates"] == 0
    assert [row["key"] for row in status["collisions"]["conflicts"]] == ["Партии"]
    assert status["collisions"]["against"]["ref"] == "main"

    # a working tree that does not load: the error names every conflict, the report stands next to it
    _write(dictionary, "050-more.yaml", "tokens:\n    Задачи: Jobs\n")
    refused = mcp_module.translate_status(str(project), against="main")
    assert "[tokens] Задачи:" in refused["error"]
    assert [row["key"] for row in refused["collisions"]["conflicts"]] == ["Задачи", "Партии"]
