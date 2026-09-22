"""A target is a dictionary filename; invalid paths fail before any edits are written."""

import json

import pytest

from xbsl.translation import cli, dictionary, entries


def _dictionary(tmp_path):
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    file = folder / "010-base.yaml"
    file.write_text("version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n", encoding="utf-8")
    return folder, file


@pytest.mark.parametrize("target", ["nested/new.yaml", r"nested\new.yaml", "../new.yaml",
                                    "/new.yaml", "C:new.yaml", "..", ".", ""])
def test_target_path_is_rejected_before_existing_entries_change(tmp_path, target):
    folder, file = _dictionary(tmp_path)
    before = file.read_bytes()
    with pytest.raises(ValueError, match="target"):
        entries.write_entries(folder, [{"key": "Задачи", "value": "Jobs"},
                                       {"key": "Склады", "value": "Warehouses"}], target=target)
    assert file.read_bytes() == before
    assert list(folder.iterdir()) == [file]


def test_plain_target_name_writes_next_to_existing_dictionary_files(tmp_path):
    folder, file = _dictionary(tmp_path)
    result = entries.write_entries(folder, [{"key": "Склады", "value": "Warehouses"}],
                                   target="020-new.yaml")
    assert result["added"] == 1
    assert dictionary.load(folder).tokens == {"Задачи": "Tasks", "Склады": "Warehouses"}
    assert (folder / "020-new.yaml").is_file()


@pytest.mark.needs_data
def test_cli_reports_invalid_target_without_traceback(tmp_path, capsys):
    folder, file = _dictionary(tmp_path)
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps([{"key": "Склады", "value": "Warehouses"}]), encoding="utf-8")
    result = cli.cli_main([str(tmp_path), "--dictionary", str(folder), "--set", str(edits),
                           "--target", "nested/new.yaml"])
    output = capsys.readouterr()
    assert result == 2
    assert "target" in output.err and "Traceback" not in output.err
    assert list(folder.iterdir()) == [file]


@pytest.mark.needs_data
def test_mcp_reports_invalid_target_without_writing(tmp_path, mcp_module):
    folder, file = _dictionary(tmp_path)
    project = tmp_path / "app"
    project.mkdir()
    (project / "Проект.yaml").write_text("ВидЭлемента: Проект\nИмя: app\n", encoding="utf-8")
    result = mcp_module.translate_set(str(project), [{"key": "Склады", "value": "Warehouses"}],
                                      target="nested/new.yaml")
    assert "target" in result["error"]
    assert list(folder.iterdir()) == [file]
