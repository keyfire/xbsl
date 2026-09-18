"""The caches of the translating pass build their answer once, however the calls arrive.

Three caches answer the same question - "is what I kept still current?" - by reading the kept
entry, comparing it with the state of the files and, when they differ, building a fresh answer
and storing it: the project index (`ProjectIndex.build`), the project-wide passes
(`translation.names`) and the project dictionary (`dictionary.load_cached`). Read, compare,
build and store have to run as one step. Two callers racing over the same project otherwise
both find the entry stale, both build the whole answer, and the one that stores last wins:
the answer is right, the work is done twice, and on a real project that is seconds of parsing
thrown away.

The MCP server dispatches its tools one at a time today, so nothing exercises the race yet.
The lock is what keeps the guarantee true when a threaded dispatcher changes how the calls
arrive - and the same lock has to survive a build that reaches back into the cache: the build
reads the platform data, data that changed under it drops every derived cache, and the drop
asks for the lock on the thread that is already holding it.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from xbsl import engine, indexer
from xbsl.translation import dictionary, names
from xbsl.translation.code import ProjectIndex

pytestmark = pytest.mark.needs_data

#: Long enough that every thread is past the look at the cache before the first one stores.
_SLOW = 0.3
_THREADS = 4

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: Demo\nПоставщик: Acme\nЯзыкПоУмолчанию: Русский\n"
)
_CATALOG_YAML = (
    "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n"
)
_MODULE = "метод Первый()\n;\n"
_DICTIONARY = "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n"


@pytest.fixture(autouse=True)
def _empty_caches():
    """Every test starts with nothing kept: the caches are process-wide."""
    ProjectIndex.forget()
    names.forget()
    dictionary.forget_cached()
    yield
    ProjectIndex.forget()
    names.forget()
    dictionary.forget_cached()


def _project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    (folder / "Задачи.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (folder / "Задачи.xbsl").write_text(_MODULE, encoding="utf-8")
    return folder


def _together(work) -> None:
    """Run `work` on several threads at once and wait for all of them."""
    threads = [threading.Thread(target=work, daemon=True) for _ in range(_THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "a thread never finished"


def _alone(work) -> bool:
    """Whether `work` finishes on its own thread - False when it blocked on a lock it holds.

    A daemon on purpose. A thread that blocks forever is exactly what this asks about, and a
    thread of the ordinary kind would be waited for at the exit of the interpreter: the answer
    would arrive as a run that never ends instead of a test that fails.
    """
    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    thread.join(10)
    return not thread.is_alive()


# --- the work is done once ------------------------------------------------------------------


def test_the_index_of_one_project_is_built_once_by_many_callers(tmp_path: Path, monkeypatch):
    root = _project(tmp_path / "app")
    built: list[Path] = []
    original = indexer.build_index

    def slow(root: Path) -> dict:
        built.append(root)
        time.sleep(_SLOW)
        return original(root)

    monkeypatch.setattr(indexer, "build_index", slow)

    _together(lambda: ProjectIndex.build(root))

    assert len(built) == 1


def test_a_pass_over_one_project_is_walked_once_by_many_callers(tmp_path: Path):
    root = _project(tmp_path / "app")
    read: list[str] = []
    lock = threading.Lock()

    def slow(path: Path):
        with lock:
            read.append(Path(path).name)
        time.sleep(_SLOW / 3)
        return engine.load(path)

    _together(lambda: names.collect(root, slow))

    assert sorted(read) == ["Задачи.xbsl", "Задачи.yaml", "Проект.yaml"]


def test_a_dictionary_is_read_once_by_many_callers(tmp_path: Path, monkeypatch):
    folder = tmp_path / "dict"
    folder.mkdir()
    (folder / "main.yaml").write_text(_DICTIONARY, encoding="utf-8")
    loaded: list[Path] = []
    original = dictionary.load

    def slow(path: Path):
        loaded.append(path)
        time.sleep(_SLOW)
        return original(path)

    monkeypatch.setattr(dictionary, "load", slow)

    _together(lambda: dictionary.load_cached(folder))

    assert len(loaded) == 1


# --- a build that reaches back into the cache -----------------------------------------------


def test_an_index_build_that_drops_the_cache_does_not_deadlock(tmp_path: Path, monkeypatch):
    """The build reads the data, and data dropped under it calls `forget` on the same thread."""
    root = _project(tmp_path / "app")
    original = indexer.build_index

    def dropping(root: Path) -> dict:
        ProjectIndex.forget()
        names.forget()
        dictionary.forget_cached()
        return original(root)

    monkeypatch.setattr(indexer, "build_index", dropping)

    assert _alone(lambda: ProjectIndex.build(root)), "the build waited for a lock it holds"
    assert ProjectIndex.build(root) is not None


def test_a_pass_that_drops_the_cache_does_not_deadlock(tmp_path: Path):
    """The same re-entry through the loader: the walk reads data, the data drops the caches."""
    root = _project(tmp_path / "app")

    def dropping(path: Path):
        names.forget()
        return engine.load(path)

    assert _alone(lambda: names.collect(root, dropping)), "the walk waited for a lock it holds"
    assert "Первый" in names.collect(root, engine.load)


def test_a_dictionary_read_that_drops_the_cache_does_not_deadlock(tmp_path: Path, monkeypatch):
    folder = tmp_path / "dict"
    folder.mkdir()
    (folder / "main.yaml").write_text(_DICTIONARY, encoding="utf-8")
    original = dictionary.load

    def dropping(path: Path):
        dictionary.forget_cached()
        return original(path)

    monkeypatch.setattr(dictionary, "load", dropping)

    assert _alone(lambda: dictionary.load_cached(folder)), "the read waited for a lock it holds"
    assert dictionary.load_cached(folder).token("Задачи") == "Tasks"
