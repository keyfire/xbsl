"""A key one dictionary file declares twice: a place of its own, the way a second file is.

yaml keeps the last value of a repeated mapping key and says nothing about the first. A pair a
file declared twice with two translations therefore loaded as the second one, and neither the
load nor `--check-duplicates` saw it - only the line reader of the entries table showed both
lines. The sections of a file are read off the composed nodes now, every pair with the line its
key stands on. A repeat with two values joins the conflicts of the load's one refusal, a repeat
with one value joins the duplicates, and the check reports both with their lines. A place is
`file:line` in the text and `{file, line, value}` in the json, for a key two files declare too.

The reading of the files needs no Element data. The command and the MCP tool do, since the
command resolves the language data before anything else and the tool runs the translation pass.
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
    """A dictionary file written as bytes, so its lines end the same way on every platform."""
    folder.mkdir(parents=True, exist_ok=True)
    file = folder / name
    file.write_bytes((head + body).encode("utf-8"))
    return file


def _places(row: dict) -> list[tuple[str, int, str]]:
    return [(place["file"], place["line"], place["value"]) for place in row["places"]]


# --- the load -------------------------------------------------------------------------------


def test_a_key_one_file_translates_twice_differently_is_refused_with_both_lines(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    file = _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n"
                                    "    Задачи: Jobs\n")

    with pytest.raises(dictionary_module.DictionaryError) as refusal:
        dictionary_module.load(folder)

    lines = str(refusal.value).splitlines()
    assert lines[0].startswith("ключей, переведённых по-разному в нескольких местах: 1 ")
    assert lines[1:] == [f"  [tokens] Задачи: {file}:4 = 'Tasks'; {file}:6 = 'Jobs'"]


def test_a_key_one_file_translates_twice_the_same_way_loads_as_a_duplicate(tmp_path: Path):
    """The lookups do not care; the second line is listed for the person who takes it out."""
    folder = tmp_path / "xbsl-translation"
    file = _write(folder, "a.yaml", "phrases:\n    текст задачи: task text\n"
                                    "    другой текст: other text\n    текст задачи: task text\n")

    loaded = dictionary_module.load(folder)

    assert loaded.phrases == {"текст задачи": "task text", "другой текст": "other text"}
    assert loaded.duplicates == [{
        "section": "phrases", "key": "текст задачи",
        "places": [{"file": str(file), "line": 4, "value": "task text"},
                   {"file": str(file), "line": 6, "value": "task text"}],
    }]


def test_a_repeat_inside_a_file_and_a_conflict_between_files_share_one_refusal(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    a = _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n    Задачи: Jobs\n")
    b = _write(folder, "b.yaml", "tokens:\n    Склады: Warehouses\n", head="")
    c = _write(folder, "c.yaml", "tokens:\n    Склады: Depots\n", head="")

    with pytest.raises(dictionary_module.DictionaryError) as refusal:
        dictionary_module.load(folder)

    assert str(refusal.value).splitlines()[1:] == [
        f"  [tokens] Задачи: {a}:4 = 'Tasks'; {a}:5 = 'Jobs'",
        f"  [tokens] Склады: {b}:2 = 'Warehouses'; {c}:2 = 'Depots'",
    ]


def test_the_explicit_key_form_is_the_same_key_and_stands_on_its_question_mark_line(tmp_path: Path):
    """A dumper writes a long key as `? key` / `: value` on its own; it names the same key."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", 'tokens:\n    ? Задачи\n    : Tasks\n    Склады: Warehouses\n'
                             '    Задачи: Jobs\n    ? "Склады"\n    : Warehouses\n')

    conflicts, duplicates = dictionary_module.collisions(dictionary_module.read_sections(folder))

    assert [(row["key"], _places(row)) for row in conflicts] == [
        ("Задачи", [("a.yaml", 4, "Tasks"), ("a.yaml", 7, "Jobs")]),
    ]
    assert [(row["key"], _places(row)) for row in duplicates] == [
        ("Склады", [("a.yaml", 6, "Warehouses"), ("a.yaml", 8, "Warehouses")]),
    ]


def test_a_quoted_key_is_the_key_its_quotes_spell(tmp_path: Path):
    """Double quotes, single quotes and an escaped quote inside: the key yaml reads is compared."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", 'tokens:\n    "Задачи": Tasks\n    Задачи: Jobs\n'
                             'phrases:\n    "текст \\"в кавычках\\"": quoted text\n'
                             "    'текст \"в кавычках\"': quoted text\n")

    conflicts, duplicates = dictionary_module.collisions(dictionary_module.read_sections(folder))

    assert [(row["key"], _places(row)) for row in conflicts] == [
        ("Задачи", [("a.yaml", 4, "Tasks"), ("a.yaml", 5, "Jobs")]),
    ]
    assert [(row["key"], _places(row)) for row in duplicates] == [
        ('текст "в кавычках"', [("a.yaml", 7, "quoted text"), ("a.yaml", 8, "quoted text")]),
    ]


def test_the_same_key_in_two_sections_of_one_file_is_not_a_repeat(tmp_path: Path):
    """The planes answer different questions: a name and a comment line may read alike."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\nphrases:\n    Задачи: tasks\n"
                             "terms:\n    Задачи: task\n")

    loaded = dictionary_module.load(folder)

    assert (loaded.tokens, loaded.phrases, loaded.terms) == (
        {"Задачи": "Tasks"}, {"Задачи": "tasks"}, {"Задачи": "task"})
    assert loaded.duplicates == []


def test_a_stub_after_a_translation_of_the_same_key_leaves_the_translation(tmp_path: Path):
    """An empty value is a stub wherever it stands, never a second reading of the key."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", 'tokens:\n    Задачи: Tasks\n    Задачи: ""\n')

    loaded = dictionary_module.load(folder)

    assert loaded.tokens == {"Задачи": "Tasks"}
    assert loaded.duplicates == []


def test_a_section_head_written_twice_reads_as_one_section(tmp_path: Path):
    """yaml keeps the second block alone; the entries table reads both, and so does the load."""
    folder = tmp_path / "xbsl-translation"
    file = _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\nphrases:\n    текст: text\n"
                                    "tokens:\n    Склады: Warehouses\n")

    assert dictionary_module.load(folder).tokens == {"Задачи": "Tasks", "Склады": "Warehouses"}

    _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\nphrases:\n    текст: text\n"
                             "tokens:\n    Склады: Warehouses\n    Задачи: Jobs\n")
    with pytest.raises(dictionary_module.DictionaryError) as refusal:
        dictionary_module.load(folder)
    assert f"[tokens] Задачи: {file}:4 = 'Tasks'; {file}:9 = 'Jobs'" in str(refusal.value)


def test_the_lines_are_the_ones_an_editor_shows_in_a_file_with_a_mark_and_carriage_returns(
        tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "a.yaml").write_bytes(codecs.BOM_UTF8 + (
        "version: 1\r\nlanguage: en\r\ntokens:\r\n    Задачи: Tasks\r\n    Задачи: Jobs\r\n"
    ).encode("utf-8"))

    conflicts, _duplicates = dictionary_module.collisions(dictionary_module.read_sections(folder))

    assert _places(conflicts[0]) == [("a.yaml", 4, "Tasks"), ("a.yaml", 5, "Jobs")]


def test_the_check_and_the_entries_table_point_at_the_same_lines(tmp_path: Path):
    """Two readers of one file: the table jumps to a line, the check names one - the same line."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", 'tokens:\n    Задачи: Tasks\n    "Склады": Warehouses\n'
                             "    ? Партии\n    : Batches\n    Задачи: Jobs\n"
                             "phrases:\n    'текст партии': batch text\n    текст партии: batch text\n")

    by_check = sorted(
        (section, key, line)
        for _name, sections in dictionary_module.read_sections(folder)
        for section, pairs in sections.items()
        for key, _value, line in pairs
    )
    by_table = sorted(
        (entries.SECTION_OF_KIND[entry.kind], entry.key, entry.line)
        for entry in entries.read_entries(folder)
    )

    assert by_check == by_table
    assert len(by_check) == 6


def test_the_report_of_the_check_carries_the_repeat_without_loading(tmp_path: Path):
    """`collisions_report` answers where the load refuses: the same rows, the file named once."""
    folder = tmp_path / "xbsl-translation"
    _write(folder, "a.yaml", "tokens:\n    Задачи: Tasks\n    Задачи: Jobs\n")
    _write(folder, "b.yaml", "tokens:\n    Склады: Warehouses\n    Склады: Warehouses\n")

    report = cli.collisions_report(folder)

    assert report["against"] is None
    assert [(row["key"], _places(row)) for row in report["conflicts"]] == [
        ("Задачи", [("a.yaml", 4, "Tasks"), ("a.yaml", 5, "Jobs")]),
    ]
    assert [(row["key"], _places(row)) for row in report["duplicates"]] == [
        ("Склады", [("b.yaml", 4, "Warehouses"), ("b.yaml", 5, "Warehouses")]),
    ]


# --- a repeat in a file at a git ref ---------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    """One git call in the throwaway repository these tests build."""
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")


def test_a_repeat_in_a_file_at_the_ref_is_judged_against_it(tmp_path: Path):
    """The branch `feature` is clean; the target `main` repeated keys after the fork.

    A file only the ref has comes in whole, its repeat included. In the file both sides have,
    a key the working tree's copy does not carry comes in with both of its places, while a key
    that copy carries stays out however often the ref repeats it - the rule of the overlay.
    """
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    dictionary = tmp_path / "xbsl-translation"
    _write(dictionary, "010-base.yaml", "tokens:\n    Задачи: Tasks\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    _git(tmp_path, "checkout", "-q", "main")
    _write(dictionary, "010-base.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n"
                                        "    Склады: Depots\n    Задачи: Jobs\n")
    _write(dictionary, "030-other.yaml", "tokens:\n    Партии: Lots\n    Партии: Batches\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the target repeats keys in its files")
    _git(tmp_path, "checkout", "-q", "feature")

    assert cli.collisions_report(dictionary)["conflicts"] == []
    report = cli.collisions_report(dictionary, "main")

    assert report["against"] == {"ref": "main", "files": 2, "added": 4}
    assert [(row["key"], _places(row)) for row in report["conflicts"]] == [
        ("Партии", [("main:030-other.yaml", 4, "Lots"), ("main:030-other.yaml", 5, "Batches")]),
        ("Склады", [("main:010-base.yaml", 5, "Warehouses"), ("main:010-base.yaml", 6, "Depots")]),
    ]
    assert report["duplicates"] == []


# --- the command and the tool -----------------------------------------------------------------


_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    """A project with one catalog and a dictionary next to it: (the project, the dictionary)."""
    folder = tmp_path / "vendor" / "app"
    folder.mkdir(parents=True)
    (folder / "Проект.yaml").write_bytes(_PROJECT_YAML.encode("utf-8"))
    (folder / "Задачи.yaml").write_bytes(
        "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n"
        .encode("utf-8"))
    dictionary = tmp_path / "xbsl-translation"
    _write(dictionary, "010-base.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n")
    return folder, dictionary


def _run(capsys, args: list[str]) -> tuple[int, list[str], str]:
    code = cli.cli_main(args + ["--lang", "ru"])
    captured = capsys.readouterr()
    return code, captured.out.rstrip("\n").splitlines(), captured.err


@pytest.mark.needs_data
def test_the_check_lists_a_repeat_inside_a_file_with_both_lines(project, capsys):
    folder, dictionary = project
    _write(dictionary, "020-more.yaml", "tokens:\n    Партии: Lots\n    Курсы: Rates\n"
                                        "    Партии: Batches\n    Курсы: Rates\n")

    code, lines, _err = _run(capsys, [str(folder), "--check-duplicates"])
    assert code == 1
    assert lines == [
        "ключей, переведённых одинаково в нескольких местах: 1 – лишние копии снимают",
        "  [tokens] Курсы = 'Rates': 020-more.yaml:5, 020-more.yaml:7",
        "ключей, переведённых по-разному в нескольких местах: 1 – оставьте одно значение",
        "  [tokens] Партии: 020-more.yaml:4 = 'Lots'; 020-more.yaml:6 = 'Batches'",
    ]

    code, out, _err = _run(capsys, [str(folder), "--check-duplicates", "--format", "json"])
    report = json.loads("\n".join(out))
    assert code == 1
    assert report["conflicts"] == [{
        "section": "tokens", "key": "Партии",
        "places": [{"file": "020-more.yaml", "line": 4, "value": "Lots"},
                   {"file": "020-more.yaml", "line": 6, "value": "Batches"}],
    }]
    assert [place["line"] for place in report["duplicates"][0]["places"]] == [5, 7]


@pytest.mark.needs_data
def test_a_strict_run_over_a_file_with_a_repeat_names_both_lines(project, capsys):
    folder, dictionary = project
    more = _write(dictionary, "020-more.yaml", "tokens:\n    Партии: Lots\n    Партии: Batches\n")

    code, _lines, err = _run(capsys, [str(folder), "--strict"])

    assert code == 2
    assert f"[tokens] Партии: {more}:4 = 'Lots'; {more}:5 = 'Batches'" in err


@pytest.mark.needs_data
def test_translate_status_counts_a_repeat_and_refuses_a_conflicting_one(mcp_module, project):
    folder, dictionary = project
    _write(dictionary, "020-more.yaml", "tokens:\n    Партии: Lots\n    Партии: Lots\n")

    assert mcp_module.translate_status(str(folder))["duplicates"] == 1

    _write(dictionary, "020-more.yaml", "tokens:\n    Партии: Lots\n    Партии: Batches\n")
    refused = mcp_module.translate_status(str(folder))
    assert "020-more.yaml:4 = 'Lots'" in refused["error"]
    assert "020-more.yaml:5 = 'Batches'" in refused["error"]
