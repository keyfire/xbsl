"""The translation tools refuse a root without a dictionary instead of answering an empty one.

With the repository root passed instead of the project directory, `translate_status` used to
answer `dictionary: None`, coverage 0.0 and every name of the project as a gap - a report that
looked like work while the dictionary sat two levels down, out of the walk-up's sight. The
refusal names the root, the two spellings the discovery looks for and, when one sits below the
root, where it is. The CLI shares the mechanism.

The refusals need no Element data; the answers over a found dictionary translate the tree and do.
"""

import json
from pathlib import Path

import pytest

from xbsl import cli
from xbsl.translation import dictionary as dict_module

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)
_DICTIONARY = "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n"


def _project(repo: Path) -> Path:
    project = repo / "vendor" / "app"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    (project / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n",
        encoding="utf-8",
    )
    return project


def _dictionary(next_to: Path) -> Path:
    folder = next_to / dict_module.DICTIONARY_DIR
    folder.mkdir(parents=True)
    (folder / "010-objects.yaml").write_text(_DICTIONARY, encoding="utf-8")
    return folder


# --- the message ---------------------------------------------------------------------------


def test_missing_message_states_the_rules_of_the_discovery(tmp_path):
    project = _project(tmp_path)
    text = dict_module.missing_message(project)
    assert str(project) in text
    assert dict_module.DICTIONARY_DIR in text and dict_module.DICTIONARY_FILE in text


def test_missing_message_points_at_a_dictionary_below_a_root_passed_too_high(tmp_path):
    _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    text = dict_module.missing_message(tmp_path)
    assert str(folder) in text


def test_found_below_is_bounded_and_skips_hidden_directories(tmp_path):
    shallow = _dictionary(tmp_path / "a" / "b")
    _dictionary(tmp_path / "a" / "b" / "c" / "d")
    _dictionary(tmp_path / ".git")
    assert dict_module.found_below(tmp_path) == [shallow]


# --- the MCP tools -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool",
    ["translate_status", "translate_gaps", "translate_entries", "translate_unused"],
)
def test_translate_tools_refuse_a_root_without_a_dictionary(mcp_module, tmp_path, tool):
    project = _project(tmp_path)
    answer = getattr(mcp_module, tool)(str(project))
    assert set(answer) == {"error"}
    assert str(project) in answer["error"] and dict_module.DICTIONARY_DIR in answer["error"]


def test_translate_set_refuses_a_root_without_a_dictionary(mcp_module, tmp_path):
    project = _project(tmp_path)
    answer = mcp_module.translate_set(str(project), edits=[{"key": "Задачи", "value": "Tasks"}])
    assert set(answer) == {"error"}
    assert str(project) in answer["error"]


def test_translate_tools_name_the_dictionary_found_below_a_repository_root(mcp_module, tmp_path):
    _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    answer = mcp_module.translate_status(str(tmp_path))
    assert str(folder) in answer["error"]


@pytest.mark.needs_data
def test_translate_gaps_names_the_dictionary_it_answered_from(mcp_module, tmp_path):
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    gaps = mcp_module.translate_gaps(str(project))
    assert gaps["dictionary"] == str(folder)
    assert "error" not in gaps
    status = mcp_module.translate_status(str(project))
    assert status["dictionary"] == str(folder)


# --- the CLI -------------------------------------------------------------------------------


@pytest.mark.needs_data
def test_cli_table_modes_refuse_a_root_without_a_dictionary(tmp_path, capsys):
    project = _project(tmp_path)
    code = cli.main(["translate", str(project), "--gaps", "--format", "json"])
    err = capsys.readouterr().err
    assert code == 2
    assert str(project) in err and dict_module.DICTIONARY_DIR in err


@pytest.mark.needs_data
def test_cli_report_without_a_dictionary_warns_with_the_rules_and_marks_the_json(tmp_path, capsys):
    project = _project(tmp_path)
    code = cli.main(["translate", str(project), "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0
    assert str(project) in captured.err and dict_module.DICTIONARY_DIR in captured.err
    assert json.loads(captured.out)["dictionary"] is None


@pytest.mark.needs_data
def test_cli_report_names_the_dictionary_it_used(tmp_path, capsys):
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    code = cli.main(["translate", str(project), "--format", "json"])
    captured = capsys.readouterr()
    assert code == 0 and captured.err == ""
    assert json.loads(captured.out)["dictionary"] == str(folder)


# --- the page says what it left out --------------------------------------------------------


def _many_gaps(project: Path, count: int) -> None:
    """A project with more untranslated names than one page carries."""
    for number in range(count):
        (project / f"Объект{number}.yaml").write_text(
            "ВидЭлемента: Справочник\n"
            f"Ид: cccccccc-1111-2222-3333-{number:012d}\nИмя: Объект{number}\n",
            encoding="utf-8",
        )


@pytest.mark.needs_data
def test_translate_gaps_says_the_page_is_not_the_whole_list(mcp_module, tmp_path):
    """`total: 72` beside fifty rows and nothing else reads as a complete answer.

    A dictionary built from such a page was short by twenty-two entries, and the strict pass
    found them after the merge - so the cut is stated: `truncated`, how many rows are left,
    and a hint naming the ways to the rest.
    """
    project = _project(tmp_path)
    _dictionary(tmp_path / "vendor")
    _many_gaps(project, 12)

    page = mcp_module.translate_gaps(str(project), limit=5)

    assert page["truncated"] is True
    assert page["shown"] == 5 and page["total"] > 5
    assert page["remaining"] == page["total"] - 5
    assert "offset=5" in page["hint"] and "--missing" in page["hint"]


@pytest.mark.needs_data
def test_a_page_that_holds_everything_says_so(mcp_module, tmp_path):
    """The negative control: no cut, no warning, and no `remaining` to act on."""
    project = _project(tmp_path)
    _dictionary(tmp_path / "vendor")

    page = mcp_module.translate_gaps(str(project), limit=0)

    assert page["truncated"] is False
    assert page["shown"] == page["total"]
    assert "hint" not in page and "remaining" not in page


@pytest.mark.needs_data
def test_the_entries_page_is_marked_too(mcp_module, tmp_path):
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    (folder / "020-more.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Шаг: Step\n    Этап: Stage\n",
        encoding="utf-8",
    )

    page = mcp_module.translate_entries(str(project), limit=1)

    assert page["truncated"] is True and page["remaining"] == 2
    assert "offset=1" in page["hint"]


# --- the orphan tool -----------------------------------------------------------------------


@pytest.mark.needs_data
def test_translate_unused_names_the_pairs_the_project_dropped(mcp_module, tmp_path):
    """The MCP side of `--unused`: what the dictionary still says and the project has not."""
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    (folder / "020-more.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    СнятоеИмя: RemovedName\n",
        encoding="utf-8",
    )

    answer = mcp_module.translate_unused(str(project))

    assert {row["key"] for row in answer["unused"]} == {"СнятоеИмя"}
    assert answer["dictionary"] == str(folder)


@pytest.mark.needs_data
def test_translate_unused_writes_nothing_unless_prune_is_asked_for(mcp_module, tmp_path):
    """Listing is the default: this is the one direction where a misreading destroys a word."""
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    extra = folder / "020-more.yaml"
    extra.write_text(
        "version: 1\nlanguage: en\ntokens:\n    СнятоеИмя: RemovedName\n", encoding="utf-8")
    before = extra.read_text(encoding="utf-8")

    listed = mcp_module.translate_unused(str(project))
    assert "removed" not in listed
    assert extra.read_text(encoding="utf-8") == before

    pruned = mcp_module.translate_unused(str(project), prune=True)
    assert pruned["removed"] == 1
    assert "СнятоеИмя" not in extra.read_text(encoding="utf-8")


@pytest.mark.needs_data
def test_translate_unused_filters_by_the_name_of_what_was_deleted(mcp_module, tmp_path):
    """The question a deletion asks is about ITS names, not about the whole history."""
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    (folder / "020-more.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n"
        "    СнятыйКомпонент: RemovedComponent\n    ДругоеСнятое: OtherRemoved\n",
        encoding="utf-8",
    )

    answer = mcp_module.translate_unused(str(project), filter="СнятыйКомпонент")

    assert {row["key"] for row in answer["unused"]} == {"СнятыйКомпонент"}


@pytest.mark.needs_data
def test_translate_unused_compact_rows_and_counts_by_kind(mcp_module, tmp_path):
    """A cleaning pass needs the keys and their places, not the translations: `compact`
    drops the values, and `counts` sizes the work over the whole set before a page is read."""
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor")
    (folder / "020-more.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    СнятоеИмя: RemovedName\n"
        "phrases:\n    Снятая строка комментария.: \"A removed comment line.\"\n",
        encoding="utf-8",
    )

    answer = mcp_module.translate_unused(str(project), compact=True, limit=1)

    assert answer["counts"] == {"token": 1, "phrase": 1}
    assert len(answer["unused"]) == 1
    assert set(answer["unused"][0]) == {"key", "kind", "file", "line"}
    full = mcp_module.translate_unused(str(project))
    assert full["counts"] == {"token": 1, "phrase": 1}
    assert "value" in full["unused"][0]
