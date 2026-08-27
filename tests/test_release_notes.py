"""The release-notes extractor feeding the GitHub release body from the changelogs.

Two live contracts are pinned here: the engine changelog (day headings naming the
released versions) and the extension changelog (version-only headings) both yield a
non-empty section for their newest version - the exact pair the publish workflows
will ask for on the next tag. A version nobody released must answer None: a wrong
day's notes on a release card is worse than no notes.
"""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release-notes.py"

spec = importlib.util.spec_from_file_location("relnotes", SCRIPT)
relnotes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relnotes)


def newest_version(text: str) -> str:
    """The last version named in the first `## ` heading of the changelog."""
    for line in text.splitlines():
        if line.startswith("## "):
            found = re.findall(r"\d+\.\d+\.\d+", line)
            assert found, f"the first day heading names no version: {line!r}"
            return found[-1]
    raise AssertionError("the changelog has no `## ` heading at all")


def test_engine_changelog_serves_its_newest_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = relnotes.extract(text, newest_version(text))
    assert section and "###" in section


def test_extension_changelog_serves_its_newest_version():
    text = (ROOT / "editors" / "vscode" / "CHANGELOG.md").read_text(encoding="utf-8")
    section = relnotes.extract(text, newest_version(text))
    assert section and section.strip()


def test_an_unreleased_version_answers_none():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert relnotes.extract(text, "999.999.999") is None
