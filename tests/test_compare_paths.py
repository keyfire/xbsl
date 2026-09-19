"""`--compare` pairs the paths of two runs by the folder they name, then by their spelling.

A finding is keyed by the path given on the command line and the file under it. Two runs of
one folder, one typed relative and the other absolute, used to be reported as two different
paths: the comparison left both runs out, a line apiece, and compared nothing. The spelling
still decides where the folders differ - `xbsl demo` run from two worktrees of a repository
compares the two checkouts. The unit tests build the diagnostics by hand and need no Element
data; the test that runs the linter itself is marked `needs_data`.
"""

from __future__ import annotations

import json
import sys

import pytest

from xbsl import cli, rundiff
from xbsl.diagnostics import Diagnostic, Severity


def _d(path, line, rule="style/x", message="m"):
    return Diagnostic(path=str(path), line=line, col=1, rule_id=rule, severity=Severity.WARNING,
                      message=message)


def _tree(root):
    """A folder `Задачи` holding one source under `root`: (the folder, the source)."""
    folder = root / "Задачи"
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "Шаги.xbsl"
    source.write_text("", encoding="utf-8")
    return folder, source


def _record(diagnostics, paths):
    return rundiff.record(
        diagnostics, paths, checked=1, lang="ru",
        selection={"select": None, "ignore": None, "enable": None}, rules={"style/x": True},
    )


def _key(label, line):
    return (label, "Шаги.xbsl", line, 1, "style/x", "m")


@pytest.mark.parametrize("before, after", [
    ("Задачи", "absolute"),
    ("absolute", "Задачи"),
    ("./Задачи/", "absolute"),
])
def test_a_folder_typed_relative_and_absolute_is_one_path(tmp_path, monkeypatch, before, after):
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    spell = {"absolute": str(folder)}
    saved = _record([_d(source, 1)], [spell.get(before, before)])
    now = _record([_d(source, 2)], [spell.get(after, after)])

    changes = rundiff.compare(saved, now)

    assert changes.skipped == []
    label = now.corpora[0]
    assert changes.disappeared == [_key(label, 1)]
    assert changes.appeared == [_key(label, 2)]


def test_the_changes_carry_the_paths_of_this_run(tmp_path, monkeypatch):
    """A finding that went is named the way this run names its folder: the reader looks for
    it from where the run was made, and the file saved next holds one spelling."""
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    saved = _record([_d(source, 1)], ["Задачи"])
    now = _record([], [str(folder)])
    assert rundiff.compare(saved, now).disappeared == [_key(folder.as_posix(), 1)]


def test_one_spelling_under_two_checkouts_still_compares(tmp_path, monkeypatch):
    """`xbsl demo` from two worktrees names two folders and one path: the comparison of the
    two checkouts, which the path as typed has always given."""
    runs = []
    for checkout, line in (("main", 1), ("branch", 2)):
        _folder, source = _tree(tmp_path / checkout)
        monkeypatch.chdir(tmp_path / checkout)
        runs.append(_record([_d(source, line)], ["Задачи"]))

    changes = rundiff.compare(*runs)

    assert changes.skipped == []
    assert changes.disappeared == [_key("Задачи", 1)]
    assert changes.appeared == [_key("Задачи", 2)]


def test_the_folder_decides_before_the_spelling(tmp_path, monkeypatch):
    """The saved `Задачи` is the folder this run names by its full path. This run's own
    `Задачи` lies in another checkout, so it is a path the saved run did not check."""
    main_folder, main_source = _tree(tmp_path / "main")
    _branch_folder, branch_source = _tree(tmp_path / "branch")
    monkeypatch.chdir(tmp_path / "main")
    saved = _record([_d(main_source, 1)], ["Задачи"])
    monkeypatch.chdir(tmp_path / "branch")
    now = _record([_d(branch_source, 5), _d(main_source, 1)], ["Задачи", str(main_folder)])

    changes = rundiff.compare(saved, now)

    assert (changes.appeared, changes.disappeared) == ([], [])
    assert changes.skipped == [("rundiff.skipped-paths-new", ["Задачи"], 1)]


def test_a_second_spelling_of_a_listed_folder_adds_no_path(tmp_path, monkeypatch):
    """A file goes under the first path that holds it, so a second spelling of the same folder
    would count no findings and read as a path the other run never checked."""
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    run = _record([_d(source, 1)], ["Задачи", str(folder)])
    assert run.corpora == ["Задачи"]
    assert run.findings == [_key("Задачи", 1)]


def test_the_saved_run_names_the_folder_of_each_path(tmp_path, monkeypatch):
    """The next run may start in another directory, so the folder is resolved when the run is
    made and kept in the file next to the path as typed."""
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "запуск.json"
    run = _record([_d(source, 1)], ["Задачи"])
    rundiff.save(target, run, None)

    data = json.loads(target.read_text(encoding="utf-8"))

    assert data["roots"] == {"Задачи": folder.resolve().as_posix()}
    assert rundiff.load(target, "ru") == run


def test_a_run_saved_without_the_folders_pairs_by_the_spelling(tmp_path, monkeypatch):
    """The format keeps its number: a file written before the folders were kept still loads,
    and its paths pair by the spelling alone."""
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "запуск.json"
    rundiff.save(target, _record([_d(source, 1)], ["Задачи"]), None)
    data = json.loads(target.read_text(encoding="utf-8"))
    del data["roots"]
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    saved = rundiff.load(target, "ru")
    same_spelling = rundiff.compare(saved, _record([_d(source, 2)], ["Задачи"]))
    other_spelling = rundiff.compare(saved, _record([_d(source, 2)], [str(folder)]))

    assert saved.roots == {}
    assert (same_spelling.skipped, len(same_spelling.appeared)) == ([], 1)
    assert [key for key, _names, _count in other_spelling.skipped] == [
        "rundiff.skipped-paths-gone", "rundiff.skipped-paths-new",
    ]


@pytest.mark.parametrize("roots", ['["Задачи"]', '{"Задачи": 1}'])
def test_folders_of_another_shape_are_refused(tmp_path, roots):
    target = tmp_path / "запуск.json"
    rundiff.save(target, _record([], ["Задачи"]), None)
    data = json.loads(target.read_text(encoding="utf-8"))
    data["roots"] = json.loads(roots)
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(rundiff.RunStateError, match="не похож на запуск"):
        rundiff.load(target, "ru")


@pytest.mark.skipif(sys.platform != "win32",
                    reason="the case of a letter names one folder on Windows only")
def test_the_case_of_a_letter_does_not_split_a_folder(tmp_path, monkeypatch):
    folder, source = _tree(tmp_path)
    monkeypatch.chdir(tmp_path)
    saved = _record([_d(source, 1)], [str(folder)])
    now = _record([_d(source, 1)], [str(folder).upper()])
    changes = rundiff.compare(saved, now)
    assert (changes.appeared, changes.disappeared, changes.skipped) == ([], [], [])


@pytest.mark.needs_data
def test_the_command_line_compares_one_folder_typed_two_ways(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "Задачи"
    folder.mkdir()
    (folder / "Шаги.xbsl").write_text("метод Ф(): Число\n    возврат 1  \n;\n", encoding="utf-8")
    state = tmp_path / "запуск.json"
    flags = ["--select", "whitespace/trailing", "--no-baseline", "--compare", str(state)]
    monkeypatch.chdir(tmp_path)

    cli.main(["Задачи", *flags])
    capsys.readouterr()
    cli.main([str(folder), *flags])

    assert capsys.readouterr().out.splitlines() == [
        f"Без изменений по сравнению с {state}. Находок: 1; правил с находками: 1; "
        "файлов с находками: 1 из 1"
    ]
