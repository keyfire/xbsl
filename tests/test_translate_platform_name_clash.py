"""A dictionary key spelled like a name the PLATFORM already carries.

A pair renames its key everywhere in the project, and the platform's own vocabulary is the one
place a rename must never reach. Two shapes, two cures:

* the key names a platform TYPE. A type expression takes the platform's word over any name of
  the project, so the pair is harmless - until the project declares a TYPE of that spelling.
  Then the gate steps aside for the project, the pair renames every use of the platform type
  too, and the English build fails in a file nobody touched: `Type "Swatch" is not defined`,
  where the word appears nowhere near. The cure is to rename the project's node, and nothing
  the dictionary can say replaces it.
* the key names a MEMBER of a platform type. There the pair has a right spelling: the one the
  platform itself gives the member, because a member reached through a receiver of no inferred
  type is spelled by the dictionary. The check names it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl.translation import dictionary as dict_module
from xbsl.translation import entries as entries_module
from xbsl.translation import platform_map
from xbsl.translation.project import translate_project


def _folder(tmp_path: Path, tokens: str = "") -> Path:
    folder = tmp_path / "xbsl-translation"
    folder.mkdir()
    (folder / "010.yaml").write_text(
        f"version: 1\nlanguage: en\n\ntokens:\n{tokens}", encoding="utf-8",
    )
    return folder


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dictionary(tokens: dict | None = None) -> dict_module.Dictionary:
    return dict_module.Dictionary(tokens=dict(tokens or {}), phrases={}, literals={})


# --- what the writer answers ------------------------------------------------------------------


@pytest.mark.needs_data
def test_a_key_spelled_like_a_platform_type_is_reported_with_the_platform_word(tmp_path: Path):
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "Образец", "value": "Swatch", "kind": "token"}],
    )

    assert written["platform_names"] == [
        {"key": "Образец", "value": "Swatch", "clash": "type", "spellings": ["Pattern"],
         "reason": written["platform_names"][0]["reason"]},
    ]
    assert "Pattern" in written["platform_names"][0]["reason"]
    # Written all the same: whether the pair is fatal depends on what the project declares, and
    # the writer does not have the project. The strict pass, which does, refuses the tree.
    assert written["added"] == 1


@pytest.mark.needs_data
def test_a_key_spelled_like_a_platform_type_passes_when_it_repeats_the_platform_word(
        tmp_path: Path):
    """`Образец: Pattern` renames nothing the platform did not already spell so."""
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "Образец", "value": "Pattern", "kind": "token"}],
    )
    assert written["platform_names"] == []


@pytest.mark.needs_data
def test_a_key_spelled_like_a_platform_member_is_told_the_spelling_to_use(tmp_path: Path):
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "ЦветСсылок", "value": "LinkColor", "kind": "token"}],
    )

    row = written["platform_names"][0]
    assert (row["key"], row["clash"], row["spellings"]) == ("ЦветСсылок", "member", ["LinksColor"])
    assert "LinksColor" in row["reason"]


@pytest.mark.needs_data
def test_a_member_key_spelled_as_the_platform_spells_it_is_not_reported(tmp_path: Path):
    """The cure of the member shape, and the proof that the check accepts it."""
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "ЦветСсылок", "value": "LinksColor", "kind": "token"}],
    )
    assert written["platform_names"] == []


@pytest.mark.needs_data
def test_an_ordinary_project_name_is_not_reported(tmp_path: Path):
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "Накладная", "value": "Waybill", "kind": "token"}],
    )
    assert written["platform_names"] == []


@pytest.mark.needs_data
def test_a_qualified_key_holds_inside_its_namespace_and_is_not_reported(tmp_path: Path):
    """A type expression asks the dictionary by the bare name, so a qualified key never answers
    one - which is the second way out of the type shape, next to renaming the node."""
    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "Палитра.Образец", "value": "Swatch", "kind": "token"}],
    )
    assert written["platform_names"] == []


@pytest.mark.needs_data
def test_removing_an_entry_is_never_reported(tmp_path: Path):
    """An emptied value takes the pair out - the cure itself must not be warned about."""
    folder = _folder(tmp_path, "    Образец: Swatch\n")
    written = entries_module.write_entries(
        folder, [{"key": "Образец", "value": "", "kind": "token"}],
    )
    assert (written["removed"], written["platform_names"]) == (1, [])


def test_without_platform_data_the_writer_reports_nothing_and_does_not_fail(
        tmp_path: Path, monkeypatch):
    """A run with no dataset answers "nothing known", never a guess: an invented clash would
    send the author renaming a node that collides with nothing."""
    monkeypatch.setattr(platform_map, "is_platform_type", lambda _name: False)
    monkeypatch.setattr(platform_map, "type_english", lambda _name: None)
    monkeypatch.setattr(platform_map, "is_member_name", lambda _name: False)
    monkeypatch.setattr(platform_map, "member_spellings", lambda _name: frozenset())

    folder = _folder(tmp_path)
    written = entries_module.write_entries(
        folder, [{"key": "Образец", "value": "Swatch", "kind": "token"}],
    )
    assert (written["added"], written["platform_names"]) == (1, [])


# --- the same answer on both surfaces ---------------------------------------------------------


@pytest.mark.needs_data
def test_the_mcp_tool_carries_the_same_rows(tmp_path: Path, mcp_module):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Project.yaml", "Vendor: Acme\nName: Demo\nVersion: 1.0.0\n")
    _folder(tmp_path)

    answer = mcp_module.translate_set(
        str(root), [{"key": "Образец", "value": "Swatch", "kind": "token"}],
    )
    assert [row["key"] for row in answer["platform_names"]] == ["Образец"]
    assert answer["platform_names"][0]["clash"] == "type"


@pytest.mark.needs_data
def test_the_cli_prints_the_rows_and_writes_the_entry(tmp_path: Path, capsys):
    from xbsl.translation import cli

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Project.yaml", "Vendor: Acme\nName: Demo\nVersion: 1.0.0\n")
    _folder(tmp_path)
    edits = tmp_path / "edits.yaml"
    edits.write_text("tokens:\n    Образец: Swatch\n", encoding="utf-8")

    code = cli.cli_main([str(root), "--set", str(edits), "--lang", "ru"])
    printed = capsys.readouterr()

    assert code == 0, "the pair is written; the note is a warning, not a refusal"
    # On stderr: what was written is the answer, and this is the caveat beside it.
    assert "Образец" in printed.err and "Pattern" in printed.err
    assert "Образец" not in printed.out


# --- the strict pass --------------------------------------------------------------------------


@pytest.mark.needs_data
def test_a_project_type_spelled_like_a_platform_type_fails_the_strict_pass(tmp_path: Path):
    """The shape the writer cannot see: here the entry really does rename the platform's type."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Палитра.xbsl", "структура Образец\n    пер Код: Строка\n;\n")
    _write(root / "Разбор.xbsl", (
        "метод Разобрать(Текст: Строка): Строка\n"
        "    возврат Текст.Заменить(новый Образец(\"<[^>]*>\"), \" \")\n"
        ";\n"
    ))
    out = tmp_path / "en"
    report = translate_project(root, _dictionary({
        "Образец": "Swatch", "Код": "Code", "Разобрать": "Parse", "Текст": "Text",
    }), out, swap_localization=False)

    # The proof: a file that knows nothing of the palette got the palette's word.
    assert "new Swatch(" in _read(out / "Разбор.xbsl")
    assert len(report.problems) == 1
    assert "Образец" in report.problems[0] and "Pattern" in report.problems[0]


@pytest.mark.needs_data
def test_the_strict_run_of_the_command_answers_non_zero(tmp_path: Path, capsys):
    """The whole chain: the problem reaches the verdict and the exit code the pipeline reads."""
    from xbsl.translation import cli

    root = tmp_path / "Acme" / "Demo"
    _write(root / "Палитра.xbsl", "структура Образец\n    пер Код: Строка\n;\n")
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(
        "version: 1\nlanguage: en\ntokens:\n    Образец: Swatch\n    Код: Code\n",
        encoding="utf-8",
    )

    code = cli.cli_main([str(root), "--dictionary", str(dictionary), "--strict", "--lang", "ru"])
    assert code == 1
    assert "Образец" in capsys.readouterr().out


@pytest.mark.needs_data
def test_an_entry_that_repeats_the_platform_word_leaves_the_strict_pass_alone(tmp_path: Path):
    """`Образец: Pattern` moves no platform word anywhere: every type expression of that
    spelling comes out as the platform already spells it, the project's own included. Projects
    that name a component after a platform one and translate it the same way build."""
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Палитра.xbsl", "структура Образец\n    пер Код: Строка\n;\n")
    report = translate_project(root, _dictionary({"Образец": "Pattern", "Код": "Code"}), None)

    assert report.problems == []


@pytest.mark.needs_data
def test_a_project_type_the_platform_does_not_carry_leaves_the_strict_pass_alone(tmp_path: Path):
    root = tmp_path / "Acme" / "Demo"
    _write(root / "Склад.xbsl", "структура Накладная\n    пер Код: Строка\n;\n")
    report = translate_project(root, _dictionary({"Накладная": "Waybill", "Код": "Code"}), None)

    assert report.problems == []
