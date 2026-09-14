"""A key the dictionary declares in several places: the writer corrects and removes it in all.

The load accepts a copy of a key while its value is the same - twice in one file or once more
in another - and `--check-duplicates` lists the copy for a person to take out. The writer behind
`--set`, the MCP `translate_set` and the prune lists (`plan_entries`) kept only the LAST place
of a key. A new value reached that one line, the copy kept the old value, and the next load
refused the dictionary with both lines - `--set` and `translate_set` included, since both load
the dictionary first. An emptied value left the copy translating the key. A key named twice in
one batch reached one line twice, and the second edit cut into the entry that had moved up in
its place; the prune lists name a key once per place, so a repeated key arrived exactly that way.

The writer needs no Element data. The command resolves the language data before anything else.
"""

from __future__ import annotations

import json
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


def _body(file: Path) -> list[str]:
    """The lines of a dictionary file below its head."""
    return file.read_bytes().decode("utf-8").splitlines()[2:]


# --- the writer ------------------------------------------------------------------------------


def test_a_new_value_reaches_every_line_of_a_key_one_file_repeats(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    file = _write(folder, "010-base.yaml",
                  "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n    Задачи: Tasks\n")

    result = entries.write_entries(folder, [{"key": "Задачи", "value": "Jobs", "kind": "token"}])

    assert _body(file) == ["tokens:", "    Задачи: Jobs", "    Склады: Warehouses",
                           "    Задачи: Jobs"]
    assert (result["changed"], result["removed"]) == (2, 0)
    assert [(row["line"], row["was"], row["now"]) for row in result["rewritten"]] == [
        (4, "Tasks", "Jobs"), (6, "Tasks", "Jobs"),
    ]
    loaded = dictionary_module.load(folder)
    assert loaded.tokens["Задачи"] == "Jobs"
    # The copy stays where it was, listed for the person who takes it out.
    assert [row["key"] for row in loaded.duplicates] == ["Задачи"]


def test_a_new_value_reaches_the_copy_of_a_key_in_another_file(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    base = _write(folder, "010-base.yaml", "tokens:\n    Склады: Warehouses\n    Задачи: Tasks\n")
    more = _write(folder, "020-more.yaml", "tokens:\n    Партии: Lots\n    Склады: Warehouses\n")

    result = entries.write_entries(folder, [{"key": "Склады", "value": "Depots", "kind": "token"}])

    assert _body(base) == ["tokens:", "    Склады: Depots", "    Задачи: Tasks"]
    assert _body(more) == ["tokens:", "    Партии: Lots", "    Склады: Depots"]
    assert [(Path(row["file"]).name, row["line"]) for row in result["rewritten"]] == [
        ("010-base.yaml", 4), ("020-more.yaml", 5),
    ]
    assert dictionary_module.load(folder).tokens["Склады"] == "Depots"


def test_an_emptied_value_removes_every_copy_of_a_key(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    base = _write(folder, "010-base.yaml",
                  "phrases:\n    текст задачи: task text\n    другой текст: other text\n"
                  "    текст задачи: task text\n")
    more = _write(folder, "020-more.yaml",
                  "phrases:\n    текст задачи: task text\n    третий текст: third text\n")

    result = entries.write_entries(
        folder, [{"key": "текст задачи", "value": "", "kind": "phrase"}],
    )

    assert result["removed"] == 3
    assert _body(base) == ["phrases:", "    другой текст: other text"]
    assert _body(more) == ["phrases:", "    третий текст: third text"]
    loaded = dictionary_module.load(folder)
    assert loaded.phrases == {"другой текст": "other text", "третий текст": "third text"}
    assert loaded.duplicates == []


@pytest.mark.parametrize("layout", ["one file", "two files"])
def test_a_key_the_prune_lists_name_once_per_place_takes_no_neighbour_along(
    tmp_path: Path, layout: str,
):
    folder = tmp_path / "xbsl-translation"
    if layout == "one file":
        _write(folder, "010-base.yaml", "tokens:\n    Задачи: Tasks\n    Задачи: Tasks\n"
                                        "    Склады: Warehouses\n    Партии: Lots\n")
    else:
        _write(folder, "010-base.yaml", "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n")
        _write(folder, "020-more.yaml", "tokens:\n    Задачи: Tasks\n    Партии: Lots\n")
    # What `--unused --prune`, `--redundant --prune` and their MCP twins hand over: an edit
    # for every row of the list, and the list reads the dictionary line by line.
    listed = [entry for entry in entries.read_entries(folder) if entry.key == "Задачи"]
    assert len(listed) == 2

    result = entries.write_entries(
        folder, [{"key": entry.key, "kind": entry.kind, "value": ""} for entry in listed],
    )

    assert result["removed"] == 2
    assert dictionary_module.load(folder).tokens == {"Склады": "Warehouses", "Партии": "Lots"}


def test_a_key_a_batch_names_twice_is_written_once_by_its_last_edit(tmp_path: Path):
    folder = tmp_path / "xbsl-translation"
    file = _write(folder, "010-base.yaml",
                  'phrases:\n    ? "текст: задачи"\n    : "text: tasks"\n'
                  "    другой текст: other text\n")

    result = entries.write_entries(folder, [
        {"key": "текст: задачи", "value": "first: text", "kind": "phrase"},
        {"key": "текст: задачи", "value": "second: text", "kind": "phrase"},
    ])

    assert _body(file) == ["phrases:", '    "текст: задачи": "second: text"',
                           "    другой текст: other text"]
    assert result["changed"] == 1


# --- the command and the tool ----------------------------------------------------------------


_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


def _catalog_project(tmp_path: Path) -> tuple[Path, Path]:
    """A project with one catalog, `Задачи`: (the project, where its dictionary goes)."""
    folder = tmp_path / "vendor" / "app"
    folder.mkdir(parents=True)
    (folder / "Проект.yaml").write_bytes(_PROJECT_YAML.encode("utf-8"))
    (folder / "Задачи.yaml").write_bytes(
        "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n"
        .encode("utf-8"))
    return folder, tmp_path / "xbsl-translation"


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    """The catalog project with a dictionary that declares the catalog's name in three places."""
    folder, dictionary = _catalog_project(tmp_path)
    _write(dictionary, "010-base.yaml",
           "tokens:\n    Задачи: Tasks\n    Склады: Warehouses\n    Задачи: Tasks\n")
    _write(dictionary, "020-more.yaml", "tokens:\n    Задачи: Tasks\n")
    return folder, dictionary


def _set(capsys, folder: Path, batch: Path, edits: list[dict]) -> tuple[int, dict]:
    batch.write_bytes(json.dumps(edits, ensure_ascii=False).encode("utf-8"))
    code = cli.cli_main([str(folder), "--set", str(batch), "--format", "json", "--lang", "ru"])
    out = capsys.readouterr().out
    return code, json.loads(out) if out.strip() else {}


@pytest.mark.needs_data
def test_set_writes_every_copy_and_runs_again_over_the_same_dictionary(
    project, tmp_path: Path, capsys,
):
    folder, dictionary = project
    batch = tmp_path / "batch.json"

    code, report = _set(capsys, folder, batch, [{"key": "Задачи", "value": "Jobs", "kind": "token"}])

    assert code == 0
    assert report["changed"] == 3
    assert [(Path(row["file"]).name, row["line"]) for row in report["rewritten"]] == [
        ("010-base.yaml", 4), ("010-base.yaml", 6), ("020-more.yaml", 4),
    ]
    assert dictionary_module.load(dictionary).tokens["Задачи"] == "Jobs"

    # The dictionary still loads, so the command reads it again - and a removal takes all three.
    code, report = _set(capsys, folder, batch, [{"key": "Задачи", "value": "", "kind": "token"}])

    assert code == 0
    assert report["removed"] == 3
    assert dictionary_module.load(dictionary).tokens == {"Склады": "Warehouses"}


def test_translate_set_writes_every_copy_and_answers_again(mcp_module, project):
    folder, dictionary = project

    answer = mcp_module.translate_set(str(folder), edits=[{"key": "Задачи", "value": "Jobs"}])

    assert "error" not in answer
    assert answer["changed"] == 3
    again = mcp_module.translate_set(str(folder), edits=[{"key": "Склады", "value": "Depots"}])
    assert "error" not in again
    assert again["changed"] == 1
    assert dictionary_module.load(dictionary).tokens == {"Задачи": "Jobs", "Склады": "Depots"}


def test_translate_unused_prunes_a_repeated_key_and_keeps_the_entry_below_it(
    mcp_module, tmp_path: Path,
):
    """The prune list names the orphan once per place; the entry below it is still in use."""
    folder, dictionary = _catalog_project(tmp_path)
    _write(dictionary, "010-base.yaml",
           "tokens:\n    Партии: Lots\n    Партии: Lots\n    Задачи: Tasks\n")

    answer = mcp_module.translate_unused(str(folder), filter="Партии", prune=True, compact=False)

    assert [(row["key"], row["line"]) for row in answer["unused"]] == [("Партии", 4), ("Партии", 5)]
    assert answer["removed"] == 2
    assert dictionary_module.load(dictionary).tokens == {"Задачи": "Tasks"}


@pytest.mark.needs_data
@pytest.mark.parametrize("lang", ["ru", "en"])
def test_set_text_names_every_rewritten_location(project, tmp_path, capsys, lang):
    folder, dictionary = project
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps([{"key": "Задачи", "value": "Jobs"}], ensure_ascii=False),
                     encoding="utf-8")
    assert cli.cli_main([str(folder), "--set", str(batch), "--lang", lang]) == 0
    lines = capsys.readouterr().out.splitlines()
    for file, line in [("010-base.yaml", 4), ("010-base.yaml", 6), ("020-more.yaml", 4)]:
        assert any(f"{dictionary / file}:{line}:" in text and "Jobs" in text for text in lines)


def test_prune_counts_repeated_occurrences_beyond_page(mcp_module, tmp_path):
    folder, dictionary = _catalog_project(tmp_path)
    file = _write(dictionary, "010-base.yaml",
                  "tokens:\n    Партии: Lots\n    Партии: Lots\n    Задачи: Tasks\n")
    answer = mcp_module.translate_unused(str(folder), filter="Партии", prune=True, limit=1)
    assert answer["removed"] == 2
    assert answer["pruned"] == {
        "by_kind": {"token": 2}, "by_file": {str(file): 2},
    }
    assert "unused" not in answer
    assert dictionary_module.load(dictionary).tokens == {"Задачи": "Tasks"}
