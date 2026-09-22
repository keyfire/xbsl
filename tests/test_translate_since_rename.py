"""A pure resource rename removes the old path even when Git emits no content hunk."""

import shutil
import subprocess

import pytest

from xbsl.translation import dictionary, entries


def _git(root, *args):
    result = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=root, capture_output=True, stdin=subprocess.DEVNULL, timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8", "replace").strip()


@pytest.mark.parametrize("committed", [False, True])
def test_pure_rename_finds_only_the_orphaned_old_filename(tmp_path, committed):
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    root = tmp_path / "project"
    resources = root / "Ресурсы"
    resources.mkdir(parents=True)
    old = resources / "СтарыйЗначок.svg"
    old.write_text("<svg/>\n", encoding="utf-8")
    (root / "Проект.yaml").write_text("ВидЭлемента: Проект\nИмя: app\n", encoding="utf-8")
    vocabulary = tmp_path / "dictionary.yaml"
    vocabulary.write_text("version: 1\nlanguage: en\ntokens:\n"
                          "  СтарыйЗначок: OldIcon\n  НовыйЗначок: NewIcon\n"
                          "  ПрежнийДолг: OldDebt\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "mv", str(old), str(resources / "НовыйЗначок.svg"))
    since = base
    if committed:
        _git(tmp_path, "commit", "-qm", "rename")
        since = base + "..HEAD"
    removed = entries.removed_surfaces(root, since)
    orphans = entries.unused_entries(root, vocabulary, dictionary.load(vocabulary), removed)
    assert removed.files == 1
    assert "СтарыйЗначок" in removed.names
    assert {entry.key for entry in orphans} == {"СтарыйЗначок"}


def test_quoted_old_rename_path_is_decoded(tmp_path):
    diff = ('diff --git "a/Old\\tIcon.svg" b/NewIcon.svg\n'
            'similarity index 100%\nrename from "Old\\tIcon.svg"\nrename to NewIcon.svg\n')
    removed = entries._removal_of_diff(tmp_path, "HEAD", diff)
    assert removed.files == 1
    assert {"Old", "Icon"} <= removed.names
    assert "tIcon" not in removed.names
