"""The project index of the translating pass is built once per state of the sources.

`ProjectIndex.build` went through `indexer.build_index` on every call - a full parse of every
module of the project, seconds on a real one. The pass needs it once, but the interactive tools
call the pass again and again: `translate_status`, `translate_gaps` and the dictionary echo of
the MCP server each pay for the same parse of the same unchanged files.

The index is now kept for the root it was built from and reused while the sources stand still.
"Stand still" is judged by the file list and a digest of each file's bytes. A modification time
would not do: the filesystem stamps whole ticks, and a rewrite of the same length inside one of
them reads as no change at all - which is exactly the case
`test_an_edited_module_is_read_again_even_at_the_same_size` writes.

The index needs the lexer and the parser, so the module needs Element data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from xbsl import dataset, indexer
from xbsl.translation.code import ProjectIndex

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)
_CATALOG_YAML = (
    "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n"
)
#: Two modules of the same LENGTH: the edit between two passes changes the name of the method
#: and nothing else, so the file keeps its size and, written at once, its timestamp as well.
_MODULE_ONE = "метод Первый()\n;\n"
_MODULE_TWO = "метод Второй()\n;\n"


@pytest.fixture(autouse=True)
def _empty_cache():
    """Every test starts with nothing kept: the cache is process-wide."""
    ProjectIndex.forget()
    yield
    ProjectIndex.forget()


@pytest.fixture
def builds(monkeypatch) -> list[Path]:
    """The roots `build_index` was actually run over, in order."""
    seen: list[Path] = []
    original = indexer.build_index

    def counted(root: Path) -> dict:
        seen.append(root)
        return original(root)

    monkeypatch.setattr(indexer, "build_index", counted)
    return seen


def _project(folder: Path, module: str = _MODULE_ONE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    (folder / "Задачи.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (folder / "Задачи.xbsl").write_text(module, encoding="utf-8")
    return folder


def _methods(index: ProjectIndex) -> set[str]:
    return {str(m["name"]) for m in index.lookup.index["methods"]}


pytestmark = pytest.mark.needs_data


# --- the index is reused ------------------------------------------------------------------


def test_the_same_project_is_indexed_once(tmp_path: Path, builds: list[Path]):
    root = _project(tmp_path / "app")

    first = ProjectIndex.build(root)
    again = ProjectIndex.build(root)

    assert first is again
    assert len(builds) == 1


def test_the_reused_index_answers_what_the_project_declares(tmp_path: Path):
    root = _project(tmp_path / "app")

    assert _methods(ProjectIndex.build(root)) == {"Первый"}
    assert _methods(ProjectIndex.build(root)) == {"Первый"}


# --- and dropped as soon as the sources move ----------------------------------------------


def test_an_edited_module_is_read_again_even_at_the_same_size(tmp_path: Path, builds: list[Path]):
    """The hard case: the rewrite lands in the same millisecond and keeps the file's size."""
    root = _project(tmp_path / "app")
    assert _methods(ProjectIndex.build(root)) == {"Первый"}

    (root / "Задачи.xbsl").write_text(_MODULE_TWO, encoding="utf-8")

    assert _methods(ProjectIndex.build(root)) == {"Второй"}
    assert len(builds) == 2


def test_a_new_module_is_read_again(tmp_path: Path, builds: list[Path]):
    root = _project(tmp_path / "app")
    ProjectIndex.build(root)

    (root / "Склады.xbsl").write_text("метод Третий()\n;\n", encoding="utf-8")

    assert _methods(ProjectIndex.build(root)) == {"Первый", "Третий"}
    assert len(builds) == 2


def test_a_deleted_module_is_read_again(tmp_path: Path, builds: list[Path]):
    root = _project(tmp_path / "app")
    ProjectIndex.build(root)

    (root / "Задачи.xbsl").unlink()

    assert _methods(ProjectIndex.build(root)) == set()
    assert len(builds) == 2


def test_an_untouched_project_is_not_indexed_again_after_a_read(tmp_path: Path,
                                                                builds: list[Path]):
    """The control of the checks above: reading a file changes no stamp of it."""
    root = _project(tmp_path / "app")
    ProjectIndex.build(root)
    (root / "Задачи.xbsl").read_text(encoding="utf-8")

    ProjectIndex.build(root)

    assert len(builds) == 1


# --- the pass that reads it ---------------------------------------------------------------


def test_two_passes_over_one_project_answer_the_same(tmp_path: Path, builds: list[Path]):
    """An index shared by two passes must come out of the first one as it went in."""
    from xbsl.translation import dictionary as dict_module
    from xbsl.translation.project import translate_project

    root = _project(tmp_path / "app")
    empty = dict_module.Dictionary()

    first = translate_project(root, empty, None)
    second = translate_project(root, empty, None)

    assert first.totals() == second.totals()
    assert first.renames == second.renames
    assert len(builds) == 1


# --- one project at a time ----------------------------------------------------------------


def test_another_root_answers_with_its_own_index(tmp_path: Path, builds: list[Path]):
    one = _project(tmp_path / "one")
    two = _project(tmp_path / "two", "метод Второй()\n;\n")

    assert _methods(ProjectIndex.build(one)) == {"Первый"}
    assert _methods(ProjectIndex.build(two)) == {"Второй"}
    assert _methods(ProjectIndex.build(one)) == {"Первый"}
    # One root at a time: the parse of a project is megabytes, and a second one would double it.
    assert len(builds) == 3


# --- the data the index is parsed with ----------------------------------------------------


def test_pinning_another_data_root_drops_the_index(tmp_path: Path, builds: list[Path]):
    """The parse follows the language data, so the index must not outlive the pinned root."""
    root = _project(tmp_path / "app")
    ProjectIndex.build(root)

    dataset.set_data_root(None)

    ProjectIndex.build(root)
    assert len(builds) == 2
