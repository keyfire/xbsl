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


@pytest.mark.parametrize("tool", ["translate_status", "translate_gaps", "translate_entries"])
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
