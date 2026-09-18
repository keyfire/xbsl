"""The project-wide passes of the translating pass run once per state of the sources.

`collect`, `collect_types`, `component_names`, `component_types`, `component_methods` and
`dictionary_scopes` each walk the whole project and read every file of it. The pass needs
each of them once, but the interactive tools run the pass again and again - `translate_status`,
`translate_gaps`, the dictionary echo of the MCP server - and every one of those calls used to
read the project through six times over, next to an index that was already kept.

They are now kept for the root they were read from and handed back while the sources stand
still, by the same digest of the bytes the index is kept by (see test_translate_index_cache):
a modification time would not do, because the filesystem stamps whole ticks and a rewrite of
the same length inside one of them reads as no change at all.

`resource_keys` is deliberately not among them. It reads the names of the FILES of the
resource folders - pictures, styles, scripts - and not one of those is a source. A picture
added under a resource folder changes its answer and changes no source digest, so the key the
index is kept by would hand back an answer that is already wrong; the test at the end of this
module holds that line.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from xbsl import dataset, engine
from xbsl.translation import names

pytestmark = pytest.mark.needs_data

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: Demo\nПоставщик: Acme\nЯзыкПоУмолчанию: Русский\n"
)
_CATALOG_YAML = (
    "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\nИмя: Задачи\n"
)
_CATALOG_MODULE = "метод Первый()\n;\n"
_COMPONENT_YAML = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Имя: Лента\n"
    "Свойства:\n"
    "    -\n"
    "        Имя: Заголовок\n"
    "        Тип: Строка\n"
    "Наследует:\n"
    "    Тип: ПроизвольныйКомпонент\n"
)
_COMPONENT_MODULE = "метод Обновить()\n;\n"
_STRINGS_YAML = "ВидЭлемента: ЛокализованныеСтроки\nИмя: Строки\nСтроки:\n    Привет: Привет\n"


class _Counting:
    """`engine.load` that remembers the files it was asked for - the passes read through it."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, path: Path):
        self.seen.append(Path(path).name)
        return engine.load(path)


def _project(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    (folder / "Задачи.yaml").write_text(_CATALOG_YAML, encoding="utf-8")
    (folder / "Задачи.xbsl").write_text(_CATALOG_MODULE, encoding="utf-8")
    (folder / "Лента.yaml").write_text(_COMPONENT_YAML, encoding="utf-8")
    (folder / "Лента.xbsl").write_text(_COMPONENT_MODULE, encoding="utf-8")
    (folder / "Строки.yaml").write_text(_STRINGS_YAML, encoding="utf-8")
    return folder


@dataclass(frozen=True)
class _Case:
    """One pass, with an edit of its sources that does not change their size."""

    run: Callable[[Path, Callable], object]
    #: What of the answer this case watches, so a failure names the word and not the whole set.
    probe: Callable[[object], object]
    file: str
    was: str
    now: str
    before: object
    after: object


def _watch(*words: str) -> Callable[[object], object]:
    def probe(answer: object) -> object:
        found = answer.keys() if isinstance(answer, dict) else answer
        return {word for word in words if word in found}

    return probe


_CASES = {
    # A method of a module: the name goes to the project plane, so a rename shows up here.
    "collect": _Case(
        run=names.collect, probe=_watch("Первый", "Второй"),
        file="Задачи.xbsl", was="метод Первый", now="метод Второй",
        before={"Первый"}, after={"Второй"},
    ),
    # The element a yaml describes is a TYPE of the project.
    "collect_types": _Case(
        run=names.collect_types, probe=_watch("Задачи", "Заявки"),
        file="Задачи.yaml", was="Имя: Задачи", now="Имя: Заявки",
        before={"Задачи"}, after={"Заявки"},
    ),
    # A node of a component form: the project's own word even where the ui vocabulary knows it.
    "component_names": _Case(
        run=names.component_names, probe=_watch("Заголовок", "Заголовки"),
        file="Лента.yaml", was="Имя: Заголовок", now="Имя: Заголовки",
        before={"Заголовок"}, after={"Заголовки"},
    ),
    # The component itself, without the names from inside it.
    "component_types": _Case(
        run=names.component_types, probe=_watch("Лента", "Полка"),
        file="Лента.yaml", was="Имя: Лента", now="Имя: Полка",
        before={"Лента"}, after={"Полка"},
    ),
    # The methods the module of a component declares, by the component that owns them.
    "component_methods": _Case(
        run=names.component_methods, probe=lambda answer: answer.get("Лента"),
        file="Лента.xbsl", was="метод Обновить", now="метод Обновись",
        before=frozenset({"Обновить"}), after=frozenset({"Обновись"}),
    ),
    # The namespace of the dictionary keys is the element named after its own file: renamed,
    # the element stops being one.
    "dictionary_scopes": _Case(
        run=names.dictionary_scopes, probe=_watch("Строки", "Стенки"),
        file="Строки.yaml", was="Имя: Строки", now="Имя: Стенки",
        before={"Строки"}, after=set(),
    ),
}


@pytest.mark.parametrize("case", list(_CASES), ids=list(_CASES))
def test_a_pass_reads_the_project_once(tmp_path: Path, case: str):
    """The second call over sources that did not move reads no file at all."""
    spec = _CASES[case]
    root = _project(tmp_path / "Acme" / "Demo")
    loader = _Counting()

    first = spec.run(root, loader)
    read_once = list(loader.seen)
    loader.seen.clear()
    again = spec.run(root, loader)

    assert read_once, "the first call has to read the project"
    assert spec.probe(again) == spec.probe(first)
    assert loader.seen == []


@pytest.mark.parametrize("case", list(_CASES), ids=list(_CASES))
def test_a_pass_sees_an_edit_of_the_same_size(tmp_path: Path, case: str):
    """The edit keeps the size of the file, so a modification time may not notice it."""
    spec = _CASES[case]
    root = _project(tmp_path / "Acme" / "Demo")
    loader = _Counting()
    source = root / spec.file
    text = source.read_text(encoding="utf-8")
    assert len(spec.was) == len(spec.now) and spec.was in text

    assert spec.probe(spec.run(root, loader)) == spec.before
    source.write_text(text.replace(spec.was, spec.now), encoding="utf-8")

    assert spec.probe(spec.run(root, loader)) == spec.after


def test_pinning_another_data_root_drops_the_passes(tmp_path: Path):
    """The passes read the metamodel with the sources, so they must not outlive the data."""
    root = _project(tmp_path / "Acme" / "Demo")
    loader = _Counting()
    names.collect(root, loader)
    loader.seen.clear()

    dataset.set_data_root(None)

    names.collect(root, loader)
    assert loader.seen != []


def test_the_resource_index_is_not_kept_by_the_sources(tmp_path: Path):
    """A file of a resource folder is no source: `resource_keys` must not follow their digest.

    The cache of the passes above is keyed on the sources, and this answer does not come from
    them. A picture dropped into a resource folder changes no source at all.
    """
    root = _project(tmp_path / "Acme" / "Demo")
    pictures = root / "Ресурсы" / "Значки"
    pictures.mkdir(parents=True)
    (pictures / "Флаг.svg").write_bytes(b"<svg/>")

    assert "Значки/Флаг.svg" in names.resource_keys(root)

    (pictures / "Метка.svg").write_bytes(b"<svg/>")

    assert "Значки/Метка.svg" in names.resource_keys(root)
