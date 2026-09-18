"""The project dictionary is kept for the bytes of its files, not for their modification time.

`dictionary.load_cached` answers the rule `code/translation-gaps`, which loads the dictionary on
every file it checks, so the directory has to answer from memory between them. What "unchanged"
meant was the modification time of each file - and that is not an answer the filesystem can give:
it stamps whole ticks, so two writes in a row share one. Measured on Windows, out of two hundred
pairs of consecutive writes into one file 151 came out with the same `st_mtime_ns`. In a
long-lived MCP server an edit through `translate_set` and the lint that follows it therefore saw
the dictionary from before the edit.

The stamp is now a digest of the bytes, the one the project index is kept by, and the cache is
dropped with the data it was read under - the load checks a token value against the English
keywords, and those come from the platform data.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from xbsl import dataset
from xbsl.translation import dictionary

pytestmark = pytest.mark.needs_data

#: Two dictionaries of the same LENGTH: an edit between two reads changes the translation and
#: nothing else, so the file keeps its size and, written at once, its timestamp as well.
_BEFORE = "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n"
_AFTER = "version: 1\nlanguage: en\ntokens:\n    Задачи: Cases\n"


@pytest.fixture(autouse=True)
def _empty_cache():
    """Every test starts with nothing kept: the cache is process-wide."""
    dictionary.forget_cached()
    yield
    dictionary.forget_cached()


@pytest.fixture
def reads(monkeypatch) -> list[Path]:
    """The paths `load` was actually run over, in order."""
    seen: list[Path] = []
    original = dictionary.load

    def counted(path: Path):
        seen.append(path)
        return original(path)

    monkeypatch.setattr(dictionary, "load", counted)
    return seen


def _folder(tmp_path: Path, text: str = _BEFORE) -> Path:
    folder = tmp_path / "xbsl-translation"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.yaml").write_text(text, encoding="utf-8")
    return folder


def test_an_unchanged_dictionary_is_read_once(tmp_path: Path, reads: list[Path]):
    folder = _folder(tmp_path)

    assert dictionary.load_cached(folder).token("Задачи") == "Tasks"
    assert dictionary.load_cached(folder).token("Задачи") == "Tasks"

    assert len(reads) == 1


def test_an_edited_dictionary_is_read_again_at_the_same_tick(tmp_path: Path, reads: list[Path]):
    """The hard case: the rewrite keeps the size of the file and lands in the same tick."""
    folder = _folder(tmp_path)
    file = folder / "main.yaml"
    assert dictionary.load_cached(folder).token("Задачи") == "Tasks"
    stamped = file.stat()

    file.write_text(_AFTER, encoding="utf-8")
    # What the filesystem does on its own often enough to matter - here on purpose, so the
    # test asks the question every time instead of once in four runs.
    os.utime(file, ns=(stamped.st_atime_ns, stamped.st_mtime_ns))
    assert file.stat().st_mtime_ns == stamped.st_mtime_ns

    assert dictionary.load_cached(folder).token("Задачи") == "Cases"
    assert len(reads) == 2


def test_a_dictionary_file_added_next_to_it_is_read(tmp_path: Path, reads: list[Path]):
    folder = _folder(tmp_path)
    dictionary.load_cached(folder)

    (folder / "more.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Заявки: Requests\n", encoding="utf-8")

    assert dictionary.load_cached(folder).token("Заявки") == "Requests"
    assert len(reads) == 2


def test_a_dictionary_read_without_an_edit_is_not_read_again(tmp_path: Path, reads: list[Path]):
    """The control of the checks above: reading a file changes no digest of it."""
    folder = _folder(tmp_path)
    dictionary.load_cached(folder)
    (folder / "main.yaml").read_text(encoding="utf-8")

    dictionary.load_cached(folder)

    assert len(reads) == 1


def test_pinning_another_data_root_drops_the_dictionary(tmp_path: Path, reads: list[Path]):
    """The load checks values against the language keywords, so it must not outlive the data."""
    folder = _folder(tmp_path)
    dictionary.load_cached(folder)

    dataset.set_data_root(None)

    dictionary.load_cached(folder)
    assert len(reads) == 2
