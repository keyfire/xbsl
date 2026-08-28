"""read_edits_file: a dictionary batch authored as a FILE, not as inline JSON.

A real task's batch runs to hundreds of entries, so `--set` (CLI) and `edits_file` (MCP)
take a file in the dictionary's own yaml format - the same sections, the same quoting, an
empty value removes the entry - with the JSON list kept for scripts. The reader is shared
with the dictionary itself (read_entries), which is what keeps the literal escaping honest.

Needs no Element data - runs in the public CI.
"""

import pytest

from xbsl.translation import entries


def test_yaml_format_batch_is_read_and_applied(tmp_path):
    batch = tmp_path / "правки.yaml"
    batch.write_text(
        "# Batch of the task.\n"
        "tokens:\n"
        "    ИмяА: NameA\n"
        "    Лишнее:\n"           # an empty value - a removal
        "phrases:\n"
        "    \"строка комментария\": \"a comment line\"\n"
        "literals:\n"
        "    \"Заявка не найдена\": \"The request was not found\"\n",
        encoding="utf-8",
    )
    edits = entries.read_edits_file(batch)
    assert {e["kind"] for e in edits} == {"token", "phrase", "literal"}
    assert {"key": "Лишнее", "value": "", "kind": "token"} in edits

    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010.yaml").write_text(
        "version: 1\nlanguage: en\n\ntokens:\n    Лишнее: Stub\n", encoding="utf-8")
    # The literal plane checks its bodies with the lexer, which needs the language data -
    # the data-free half of the batch is applied here, the literal one in its own test.
    result = entries.write_entries(folder, [e for e in edits if e["kind"] != "literal"])
    assert (result["added"], result["removed"]) == (2, 1)
    rows = {(e.kind, e.key): e.value for e in entries.read_entries(folder)}
    assert rows[("token", "ИмяА")] == "NameA"
    assert rows[("phrase", "строка комментария")] == "a comment line"
    assert ("token", "Лишнее") not in rows


@pytest.mark.needs_data
def test_yaml_format_literal_batch_is_applied(tmp_path):
    batch = tmp_path / "правки.yaml"
    batch.write_text(
        "literals:\n    \"Заявка не найдена\": \"The request was not found\"\n",
        encoding="utf-8",
    )
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    result = entries.write_entries(folder, entries.read_edits_file(batch))
    assert (result["added"], result["refused"]) == (1, [])
    rows = {(e.kind, e.key): e.value for e in entries.read_entries(folder)}
    assert rows[("literal", "Заявка не найдена")] == "The request was not found"


def test_yaml_format_keeps_literal_escaping(tmp_path):
    # Both sides of a literal are the text between the quotes AS THE SOURCE WRITES IT
    # (an inner quote is the two characters \") - the batch file uses the dictionary's own
    # quoting, so a line built the way the writer builds one round-trips exactly.
    key, value = 'Текст \\"в кавычках\\"', 'Text \\"quoted\\"'
    batch = tmp_path / "правки.yaml"
    batch.write_text(
        f"literals:\n    {entries.scalar(key)}: {entries.scalar(value)}\n",
        encoding="utf-8",
    )
    edits = entries.read_edits_file(batch)
    assert edits == [{"key": key, "value": value, "kind": "literal"}]


def test_json_shapes_stay_accepted(tmp_path):
    plain = tmp_path / "список.json"
    plain.write_text('[{"key": "А", "value": "A", "kind": "token"}]', encoding="utf-8")
    assert entries.read_edits_file(plain) == [{"key": "А", "value": "A", "kind": "token"}]

    wrapped = tmp_path / "объект.json"
    wrapped.write_text('{"edits": [{"key": "Б", "value": "B"}]}', encoding="utf-8")
    assert entries.read_edits_file(wrapped) == [{"key": "Б", "value": "B"}]


def test_json_without_a_list_is_refused(tmp_path):
    bad = tmp_path / "объект.json"
    bad.write_text('{"tokens": {"А": "A"}}', encoding="utf-8")
    with pytest.raises(ValueError):
        entries.read_edits_file(bad)


def test_file_without_entries_is_refused(tmp_path):
    # A misspelled section must not read as "nothing to change".
    prose = tmp_path / "заметка.yaml"
    prose.write_text("токены:\n    ИмяА: NameA\n", encoding="utf-8")
    with pytest.raises(ValueError):
        entries.read_edits_file(prose)


def test_a_bare_key_may_hold_a_double_colon(tmp_path):
    """A key ends at a colon followed by a SPACE, the way yaml ends it - not at any colon.

    The regression: a platform form is cited in comments by its `Std::Jobs::JobsForm` path,
    and reading the key as "everything up to the first colon" tore the entry in two - the key
    stopped mid-word and the rest of it was stored as part of the translation. Both halves
    are valid strings, so nothing complained; the phrase simply vanished from the coverage,
    and the dictionary carried a broken entry until someone counted the gaps.
    """
    batch = tmp_path / "batch.yaml"
    batch.write_text(
        "phrases:\n"
        "    Регламентные задания - форма (Стд::Задания::ФормаЗаданий),: "
        "Scheduled jobs - the form (Std::Jobs::JobsForm),\n"
        "tokens:\n"
        "    Стд::Задания::ФормаЗаданий: Std::Jobs::JobsForm\n",
        encoding="utf-8",
    )
    edits = entries.read_edits_file(batch)
    by_key = {e["key"]: e["value"] for e in edits}
    assert "Регламентные задания - форма (Стд::Задания::ФормаЗаданий)," in by_key
    assert by_key["Регламентные задания - форма (Стд::Задания::ФормаЗаданий),"] == (
        "Scheduled jobs - the form (Std::Jobs::JobsForm),")
    assert by_key["Стд::Задания::ФормаЗаданий"] == "Std::Jobs::JobsForm"


def test_a_key_with_a_colon_and_a_space_still_needs_quoting(tmp_path):
    """The negative control: `: ` inside a BARE key still ends it, as yaml says.

    Widening the key must not swallow the separator - otherwise the reader would part ways
    with the loader, and an entry would be written under a key no yaml parser agrees with.
    """
    batch = tmp_path / "batch.yaml"
    batch.write_text("tokens:\n    Ключ: значение: хвост\n", encoding="utf-8")
    edits = entries.read_edits_file(batch)
    assert edits == [{"key": "Ключ", "value": "значение: хвост", "kind": "token"}]
