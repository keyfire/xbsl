"""The annotation half of the docs guard (`check_pitches` of `tools/docsguard.py`).

"What is in the box" on the front page is the full list of surfaces, but a search engine, PyPI
and an AI answer quote the one-liners around it instead: the site description, the README lede,
the PyPI summary. Those went stale without anyone noticing - `xbsl translate` shipped in August
2026, the block on the page named it the next day, and all six annotations kept describing the
toolkit as it had been before, so Yandex's assistant answered with the older set of surfaces.

Each test plants one of the three ways the block and the annotations can come apart, because a
guard that stays silent looks exactly like a repository with nothing wrong. The last two hold
the repository itself to the rule and check that the annotations are read as annotations - an
extractor that quietly returned a whole file would mute every word check above.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("docsguard", ROOT / "tools" / "docsguard.py")
docsguard = importlib.util.module_from_spec(_spec)
sys.modules["docsguard"] = docsguard
_spec.loader.exec_module(docsguard)


def _headlines() -> dict[str, list[str]]:
    return {
        "en": [item[0] for item in docsguard.PITCH_ITEMS],
        "ru": [item[1] for item in docsguard.PITCH_ITEMS],
    }


def _surfaces() -> dict[str, dict[str, str]]:
    """Annotations that mention every word the table asks for."""
    words = {
        "en": " ".join(item[2] for item in docsguard.PITCH_ITEMS if item[2]),
        "ru": " ".join(item[3] for item in docsguard.PITCH_ITEMS if item[3]),
    }
    return {
        "en": {"blume.config.ts": words["en"], "docs/index.md": words["en"],
               "README.md": words["en"]},
        "ru": {"docs/index.ru.md": words["ru"], "README.ru.md": words["ru"],
               "pyproject.toml": words["ru"]},
    }


def test_a_new_headline_without_a_row_is_reported():
    """A capability added to the page and to nothing else - the case this guard exists for."""
    headlines = _headlines()
    headlines["ru"].append("Отладчик платформы")
    problems = docsguard.pitch_problems(headlines, _surfaces())
    assert len(problems) == 1
    assert "Отладчик платформы" in problems[0]
    assert "docs/index.ru.md" in problems[0]


def test_a_row_the_page_no_longer_has_is_reported():
    headlines = _headlines()
    headlines["en"].remove("MCP server")
    problems = docsguard.pitch_problems(headlines, _surfaces())
    assert len(problems) == 1
    assert "MCP server" in problems[0]


def test_a_word_missing_from_one_annotation_is_reported():
    surfaces = _surfaces()
    surfaces["ru"]["pyproject.toml"] = surfaces["ru"]["pyproject.toml"].replace("перевод", "")
    problems = docsguard.pitch_problems(_headlines(), surfaces)
    assert len(problems) == 1
    assert "pyproject.toml" in problems[0]
    assert "Translation into English spellings" in problems[0]


def test_a_headline_kept_out_of_the_annotations_is_not_demanded():
    """A row with no words stands for a decision, not for an unnoticed gap."""
    kept_out = [item[0] for item in docsguard.PITCH_ITEMS if not item[2]]
    assert kept_out, "the row that records a deliberate omission is gone - is the rule still whole?"
    empty = {"en": dict.fromkeys(_surfaces()["en"], ""), "ru": dict.fromkeys(_surfaces()["ru"], "")}
    reported = " ".join(docsguard.pitch_problems(_headlines(), empty))
    for headline in kept_out:
        assert headline not in reported


def test_the_repository_passes_its_own_rule():
    problems: list[str] = []
    docsguard.check_pitches(problems)
    assert problems == []


def test_the_annotations_are_read_as_annotations():
    """Each surface is one short line - a whole file would silence every check above."""
    for locale, group in docsguard.pitch_surfaces().items():
        for where, text in group.items():
            assert 80 < len(text) < 600, f"{locale} {where}: {len(text)} characters"
            assert "\n#" not in text, f"{locale} {where}: a heading leaked into the annotation"
