"""A misspelled `kind` is refused, and an overwritten entry is named.

Both used to be silent. `kind` is matched against the row's own kind, so the SECTION name
(`phrases`, plural) matched nothing and the answer came back empty - which reads exactly like
"the dictionary covers everything"; the gaps stayed unfilled and the strict pass found them
after the merge. And an edit that landed on an existing key reported only a count, leaving the
author to find WHICH entries changed by diffing the dictionary.
"""

from pathlib import Path

import pytest

from xbsl import i18n
from xbsl.translation import entries


@pytest.fixture(autouse=True)
def _ru_lang():
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


@pytest.fixture
def dictionary(tmp_path: Path) -> Path:
    path = tmp_path / "dict.yaml"
    path.write_text(
        "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n    Шаг: Step\n",
        encoding="utf-8",
    )
    return path


# -- the kind vocabulary -------------------------------------------------------


def test_a_known_kind_is_accepted():
    assert entries.kind_refusal("token") == ""
    assert entries.kind_refusal("phrase") == ""
    assert entries.kind_refusal("literal") == ""
    assert entries.kind_refusal("any") == ""


def test_a_section_name_is_not_a_kind():
    """The table speaks of kinds, the file of sections - the plural is the usual slip."""
    refusal = entries.kind_refusal("phrases")
    assert "phrases" in refusal
    assert "phrase" in refusal and "token" in refusal and "literal" in refusal


def test_any_is_refused_where_a_single_kind_is_required():
    """An edit writes ONE row: "any" names no section to write it into."""
    refusal = entries.kind_refusal("any", allow_any=False)
    assert refusal and "any" not in refusal.split(":")[-1]


def test_an_edit_of_an_unknown_kind_is_refused_and_writes_nothing(dictionary):
    plan = entries.plan_entries(dictionary, [{"key": "Товар", "value": "Item", "kind": "tokens"}])

    assert plan["added"] == 0 and plan["changed"] == 0
    assert plan["files"] == {}
    assert [row["key"] for row in plan["refused"]] == ["Товар"]
    assert "tokens" in plan["refused"][0]["reason"]


# -- what exactly was overwritten ----------------------------------------------


def test_an_overwritten_entry_is_named_with_both_values(dictionary):
    result = entries.write_entries(dictionary, [{"key": "Задачи", "value": "Jobs"}])

    assert result["changed"] == 1
    assert len(result["rewritten"]) == 1
    row = result["rewritten"][0]
    assert (row["key"], row["kind"], row["was"], row["now"]) == ("Задачи", "token", "Tasks", "Jobs")
    assert row["file"] == str(dictionary) and row["line"] > 0


def test_writing_the_same_value_is_not_an_overwrite(dictionary):
    """The control: the list names a DIFFERENCE, not every line the writer touched."""
    result = entries.write_entries(dictionary, [{"key": "Задачи", "value": "Tasks"}])

    assert result["rewritten"] == []


def test_a_new_entry_is_not_an_overwrite(dictionary):
    result = entries.write_entries(dictionary, [{"key": "Товар", "value": "Item"}])

    assert result["added"] == 1
    assert result["rewritten"] == []


def test_several_overwrites_come_back_in_file_order(dictionary):
    result = entries.write_entries(
        dictionary,
        [{"key": "Шаг", "value": "Stage"}, {"key": "Задачи", "value": "Jobs"}],
    )

    assert [row["key"] for row in result["rewritten"]] == ["Задачи", "Шаг"]
    assert [row["was"] for row in result["rewritten"]] == ["Tasks", "Step"]
