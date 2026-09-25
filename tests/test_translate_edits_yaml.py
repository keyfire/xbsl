"""A batch of dictionary edits is read as yaml, not line by line.

`translate_set(edits_file=...)` and `xbsl translate --set` share `read_edits_file`. It read a
batch line by line and knew only bare section heads, so a batch a script wrote with
`yaml.safe_dump(data, default_style='"', allow_unicode=True)` - every key in quotes,
`version: !!int "1"` - was refused as "no entries found". The batch is now read by the
dictionary's own loader; the line reader stays for a file yaml cannot read, and a refusal names
the top-level keys the file does have.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from xbsl.translation import cli as translate_cli
from xbsl.translation import dictionary as dictionary_module
from xbsl.translation import entries

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


def _dumped(tmp_path: Path, data: dict, name: str = "правки.yaml") -> Path:
    """A batch written the way the script of the report wrote it."""
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, default_style='"', allow_unicode=True), encoding="utf-8")
    return path


def _written(tmp_path: Path, text: str, name: str = "правки.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _refusal(path: Path) -> str:
    with pytest.raises(ValueError) as caught:
        entries.read_edits_file(path)
    return str(caught.value)


def test_a_batch_dumped_with_every_scalar_quoted_is_read(tmp_path):
    path = _dumped(tmp_path, {
        "version": 1, "language": "en",
        "tokens": {"Склады": "Warehouses", "Партии": "Batches"},
        "phrases": {"Строка комментария": "A comment line"},
    })
    assert '"tokens":' in path.read_text(encoding="utf-8")
    assert '!!int "1"' in path.read_text(encoding="utf-8")

    edits = entries.read_edits_file(path)

    assert sorted((e["kind"], e["key"], e["value"]) for e in edits) == [
        ("phrase", "Строка комментария", "A comment line"),
        ("token", "Партии", "Batches"),
        ("token", "Склады", "Warehouses"),
    ]


def test_a_dumped_literal_keeps_the_escaping_of_the_source(tmp_path):
    """Both sides of a literal are the body as the source writes it: `\\"` stays two characters."""
    key, value = 'Текст \\"в кавычках\\"', 'Text \\"quoted\\"'
    path = _dumped(tmp_path, {"literals": {key: value}})

    assert entries.read_edits_file(path) == [{"key": key, "value": value, "kind": "literal"}]


def test_an_empty_or_null_value_is_a_removal(tmp_path):
    path = _written(tmp_path, 'tokens:\n    "Лишнее": ""\n    Старое: ~\n    Ненужное:\n')
    assert [(e["key"], e["value"]) for e in entries.read_edits_file(path)] == [
        ("Лишнее", ""), ("Старое", ""), ("Ненужное", "")]


def test_a_word_yaml_would_read_as_a_truth_value_stays_a_word(tmp_path):
    path = _written(tmp_path, "tokens:\n    Да: Yes\n    Один: 1\n    Нет: off\n")
    assert [(e["key"], e["value"]) for e in entries.read_edits_file(path)] == [
        ("Да", "Yes"), ("Один", "1"), ("Нет", "off")]


def test_a_comment_after_a_value_is_not_part_of_it(tmp_path):
    """The line reader took `Name  # the catalog` whole; yaml ends the value before the note."""
    path = _written(tmp_path, "tokens:\n    Имя: Name  # the catalog\n")
    assert entries.read_edits_file(path) == [{"key": "Имя", "value": "Name", "kind": "token"}]


def test_a_key_the_batch_names_twice_keeps_both_edits(tmp_path):
    """The writer takes the last edit of a key; the reader must not drop the first silently."""
    path = _written(tmp_path, "tokens:\n    Склады: Stores\n    Склады: Warehouses\n")
    assert [e["value"] for e in entries.read_edits_file(path)] == ["Stores", "Warehouses"]


def test_the_refusal_names_the_keys_the_file_has(tmp_path):
    message = _refusal(_dumped(tmp_path, {"version": 1, "Tokens": {"Склады": "Warehouses"}}))
    assert "не найдено ни одной записи" in message
    assert "Tokens" in message and "version" in message


def test_an_empty_section_is_named_as_empty(tmp_path):
    message = _refusal(_written(tmp_path, "version: 1\ntokens:\n"))
    assert "tokens (пустая)" in message and "version" in message


def test_a_file_without_keys_says_so(tmp_path):
    assert "ни одного" in _refusal(_written(tmp_path, "# nothing yet\n"))


def test_a_section_that_is_not_pairs_is_refused_by_name(tmp_path):
    message = _refusal(_written(tmp_path, "tokens:\n    - Склады\n    - Партии\n"))
    assert "tokens" in message and "ключ: значение" in message


def test_a_nested_value_is_refused_with_its_line(tmp_path):
    message = _refusal(_written(tmp_path, "tokens:\n    Склады:\n        en: Warehouses\n"))
    assert "секция tokens, строка 3" in message


def test_a_file_yaml_cannot_read_still_goes_through_the_line_reader(tmp_path):
    """A tab in the indentation is no yaml, and the line reader has always taken it."""
    path = _written(tmp_path, "tokens:\n\tСклады: Warehouses\n")
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(path.read_text(encoding="utf-8"))
    assert entries.read_edits_file(path) == [{"key": "Склады", "value": "Warehouses", "kind": "token"}]


def test_a_file_no_reader_understands_carries_the_yaml_error(tmp_path):
    message = _refusal(_written(tmp_path, "tokens: [unclosed\n"))
    assert "не разбирается как yaml" in message


def test_the_english_refusal_is_english(tmp_path):
    from xbsl import i18n

    path = _dumped(tmp_path, {"Tokens": {"Склады": "Warehouses"}})
    i18n.set_lang("en")
    try:
        message = _refusal(path)
        empty = _refusal(_written(tmp_path, "tokens:\n", name="empty.yaml"))
    finally:
        i18n.set_lang("ru")
    assert "The top-level keys of the file: Tokens" in message
    assert "tokens (empty)" in empty


def test_batch_pairs_reads_only_the_sections_asked_for():
    pairs, keys = dictionary_module.batch_pairs(
        '"terms":\n  "Склад": "warehouse"\n"tokens":\n  "Склады": "Warehouses"\n', ("tokens",))
    assert pairs == {"tokens": [("Склады", "Warehouses")]} and keys == ["terms", "tokens"]


# -- the CLI and the MCP tool answer alike -------------------------------------------------------


def _project(root: Path) -> tuple[Path, Path]:
    project = root / "vendor" / "app"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    dictionary = root / dictionary_module.DICTIONARY_DIR
    dictionary.mkdir()
    (dictionary / "010-base.yaml").write_text(
        "version: 1\nlanguage: en\n\ntokens:\n    Задачи: Tasks\n    Лишнее: Extra\n",
        encoding="utf-8")
    return project, dictionary


_BATCH = {"version": 1, "tokens": {"Склады": "Warehouses", "Задачи": "Jobs", "Лишнее": ""},
          "phrases": {"Строка комментария": "A comment line"}}


def test_the_mcp_tool_writes_a_dumped_batch(mcp_module, tmp_path):
    project, dictionary = _project(tmp_path / "mcp")

    answer = mcp_module.translate_set(str(project), edits_file=str(_dumped(tmp_path, _BATCH)))

    assert "error" not in answer, answer
    assert (answer["added"], answer["changed"], answer["removed"]) == (2, 1, 1)
    assert dictionary_module.load(dictionary).tokens == {"Задачи": "Jobs", "Склады": "Warehouses"}


def test_the_mcp_tool_refuses_naming_the_keys(mcp_module, tmp_path):
    project, _dictionary = _project(tmp_path / "mcp")
    batch = _dumped(tmp_path, {"version": 1, "Tokens": {"Склады": "Warehouses"}})

    answer = mcp_module.translate_set(str(project), edits_file=str(batch))

    assert set(answer) == {"error"} and "Tokens" in answer["error"]


@pytest.mark.needs_data
def test_the_cli_and_the_mcp_tool_write_the_same(mcp_module, tmp_path, capsys):
    batch = _dumped(tmp_path, _BATCH)
    by_cli, cli_dictionary = _project(tmp_path / "cli")
    by_mcp, mcp_dictionary = _project(tmp_path / "mcp")

    code = translate_cli.cli_main([str(by_cli), "--set", str(batch), "--format", "json",
                                   "--lang", "ru"])
    printed = json.loads(capsys.readouterr().out)
    answer = mcp_module.translate_set(str(by_mcp), edits_file=str(batch))

    assert code == 0
    strip = {"dictionary", "rewritten"}  # the paths differ by the root, nothing else
    assert {k: v for k, v in printed.items() if k not in strip} == \
        {k: v for k, v in answer.items() if k not in strip}
    assert [row["key"] for row in printed["rewritten"]] == [row["key"] for row in answer["rewritten"]]
    assert {p.name: p.read_bytes() for p in cli_dictionary.iterdir()} == \
        {p.name: p.read_bytes() for p in mcp_dictionary.iterdir()}


@pytest.mark.needs_data
def test_the_cli_refuses_like_the_mcp_tool(tmp_path, capsys):
    project, _dictionary = _project(tmp_path / "cli")
    batch = _dumped(tmp_path, {"version": 1, "Tokens": {"Склады": "Warehouses"}})

    code = translate_cli.cli_main([str(project), "--set", str(batch), "--lang", "ru"])

    assert code == 2 and "Tokens" in capsys.readouterr().err
