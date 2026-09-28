"""A short comment line translated by a pair while the rest of its comment is new.

A phrase pair is keyed by one comment line. A line of one or two words ("нет.") means what
its comment makes of it: the pair may have been written for the tail of another sentence, and
a new comment that happens to end the same way takes that translation silently - "нет." got
"timer." from a sentence about a timer. The pass cannot tell a fitting pair from a stray one,
so it says where to look: the gaps of such a comment carry `neighbors`, the short lines their
comment already has translated, and the plain report warns `short-pair` at the short line.

A comment whose lines are all covered says nothing: the translator is not at work there, and
a line of three words and more carries its meaning on its own.

The report and the gaps table need no Element data; translating a module or a yaml file
tokenizes it and carries `needs_data`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import engine
from xbsl.translation import entries
from xbsl.translation.code import Resolver, short_phrase, translate_code
from xbsl.translation.dictionary import Dictionary
from xbsl.translation.project import ProjectReport
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml

_PAIRS = {"нет.": "timer.", "Остаток на складе.": "The stock at the store."}


def _module(text: str, phrases=None) -> FileReport:
    source = engine.load_text("Склады.xbsl", text)
    report = FileReport(path="Склады.xbsl")
    translate_code(source, Resolver(Dictionary(phrases=dict(phrases or _PAIRS))), report)
    return report


def _yaml(text: str, phrases=None) -> FileReport:
    source = engine.load_text("Склады.yaml", text)
    report = FileReport(path="Склады.yaml")
    translate_yaml(source, Resolver(Dictionary(phrases=dict(phrases or _PAIRS))), report)
    return report


# --- the file report without a pass ------------------------------------------------------

def test_a_line_of_two_words_is_short_and_one_of_three_is_not():
    assert short_phrase("нет.")
    assert short_phrase("не трогает.")
    assert not short_phrase("Остаток на складе.")


def _comment(report: FileReport, first_line: int, gap: str | None, short: str | None) -> None:
    """Two lines of one `//` comment: a gap and a short line a pair translated."""
    report.comment_line("//", first_line)
    if gap:
        report.note_phrase(gap, first_line, 1)
    report.comment_line("//", first_line + 1)
    if short:
        report.note_short_hit(first_line + 1, 1, short, "timer.")


def test_the_gaps_of_a_comment_get_its_short_lines():
    report = FileReport(path="Склады.xbsl")
    _comment(report, 3, "Остановить отсчет, когда времени", "нет.")
    report.close_comment()

    assert report.short_neighbors == {"Остановить отсчет, когда времени": [("нет.", "timer.")]}
    assert report.warnings == [("short-pair", 4, 1, "нет. -> timer.")]


def test_a_comment_without_gaps_says_nothing():
    report = FileReport(path="Склады.xbsl")
    _comment(report, 3, None, "нет.")
    report.close_comment()

    assert report.short_neighbors == {} and report.warnings == []


def test_a_comment_further_down_is_another_comment():
    report = FileReport(path="Склады.xbsl")
    report.comment_line("//", 1)
    report.note_phrase("Прежний комментарий без перевода", 1, 1)
    report.comment_line("//", 9)  # line 9 is not right under line 1
    report.note_short_hit(9, 1, "нет.", "timer.")
    report.close_comment()

    assert report.short_neighbors == {} and report.warnings == []


def test_another_marker_right_below_is_another_comment():
    report = FileReport(path="Склады.xbsl")
    report.comment_line("//", 1)
    report.note_phrase("Новая строка без перевода.", 1, 1)
    report.comment_line("///", 2)
    report.note_short_hit(2, 1, "нет.", "timer.")
    report.close_comment()

    assert report.short_neighbors == {} and report.warnings == []


def test_the_gaps_table_carries_the_neighbors_of_a_phrase(tmp_path: Path):
    first = FileReport(path="А.xbsl")
    _comment(first, 3, "Остановить отсчет, когда времени", "нет.")
    first.close_comment()
    second = FileReport(path="Б.xbsl")
    _comment(second, 7, "Остановить отсчет, когда времени", "нет.")
    second.close_comment()
    report = ProjectReport(root=tmp_path, files={"А.xbsl": first, "Б.xbsl": second})

    gaps = {gap.key: gap for gap in entries.gaps_of_report(report)}

    gap = gaps["Остановить отсчет, когда времени"]
    assert gap.neighbors == [("нет.", "timer.")]  # once, though two files say it
    assert gap.as_dict()["neighbors"] == [{"key": "нет.", "value": "timer."}]


def test_a_gap_without_neighbors_keeps_its_old_shape():
    assert "neighbors" not in entries.Gap(key="Слово", kind="phrase").as_dict()


# --- the pass over a module and a yaml file -------------------------------------------------

@pytest.mark.needs_data
def test_a_new_comment_ending_in_a_short_line_names_the_pair_it_took():
    report = _module("// Остановить отсчет, когда времени\n// нет.\nметод Ф()\n;\n")

    assert report.short_neighbors == {"Остановить отсчет, когда времени": [("нет.", "timer.")]}
    assert [(kind, line, what) for kind, line, _col, what in report.warnings] == [
        ("short-pair", 2, "нет. -> timer."),
    ]


@pytest.mark.needs_data
def test_a_comment_translated_whole_says_nothing():
    phrases = {**_PAIRS, "Остановить отсчет, когда таймера": "Stop counting when there is no"}
    report = _module("// Остановить отсчет, когда таймера\n// нет.\nметод Ф()\n;\n", phrases)

    assert report.short_neighbors == {} and report.warnings == []


@pytest.mark.needs_data
def test_a_long_line_a_pair_translated_is_no_neighbor():
    report = _module("// Остаток на складе.\n// Новая строка без перевода.\nметод Ф()\n;\n")

    assert report.short_neighbors == {} and report.warnings == []


@pytest.mark.needs_data
def test_two_comments_of_a_module_are_judged_apart():
    report = _module(
        "// Новая строка без перевода.\nметод Ф()\n;\n\n// нет.\nметод Г()\n;\n"
    )

    assert report.short_neighbors == {} and report.warnings == []


@pytest.mark.needs_data
def test_a_run_of_yaml_comment_lines_is_one_comment():
    report = _yaml("## Остановить отсчет, когда времени\n## нет.\nИмя: Склады\n")

    assert report.short_neighbors == {"Остановить отсчет, когда времени": [("нет.", "timer.")]}
    assert [kind for kind, *_rest in report.warnings] == ["short-pair"]


@pytest.mark.needs_data
def test_yaml_comments_apart_are_judged_apart():
    report = _yaml("## Новая строка без перевода.\nИмя: Склады\n## нет.\nВид: Справочник\n")

    assert report.short_neighbors == {} and report.warnings == []
