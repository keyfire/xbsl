"""MCP `meta_fold_comments` with `compact`: the short report of a fold.

The whole report names every move, and over a tree that was never folded it ran to a quarter of
a megabyte - 333 files, 1184 blocks, nearly all of them moves the fold applies on its own. The
short one keeps counts, the files with the most moves and the moves worth a look, one line each
and up to the limit of the compact lint answer; the files the audit stopped come whole.

The report is assembled from the fold results, so its shape is checked on hand-built results
with no Element data; the folds themselves need the data (`needs_data`).
"""

from __future__ import annotations

import inspect

import pytest

from xbsl import commentfold
from xbsl.commentfold import FileFold, Move
from xbsl.report import COMPACT_FINDINGS_LIMIT


def _fold(rel: str, *moves: Move, audit: list[str] | None = None, text: str = "x") -> FileFold:
    return FileFold(rel, moves=list(moves), text=text, audit=list(audit or []))


def test_the_compact_switch_is_off_by_default(mcp_module):
    parameters = inspect.signature(mcp_module.meta_fold_comments).parameters
    assert parameters["compact"].default is False


def test_compact_report_counts_and_lists_what_a_reader_acts_on():
    folds = [
        _fold("Склады.yaml",
              Move(3, "property", "applied", target_line=1, subject="Видимость"),
              Move(9, "element-key", "proposed", target_line=1,
                   reason="fold.reason.first-block"),
              Move(12, "item", "applied", target_line=10, subject="Код",
                   notes=["строка 13: текст ссылается на место"])),
        _fold("Партии.yaml", Move(5, "end", "left", reason="fold.reason.end"), text=None),
    ]

    short = commentfold.compact_report(folds, 1)

    assert short["written"] == 1
    assert short["summary"] == commentfold.report(folds, 1)["summary"]
    assert short["counts"] == {
        "files": 2, "changed": 1, "applied": 2, "proposed": 1, "left": 1, "notes": 1}
    # the files with the most moves first, every action named - a zero is a zero
    assert list(short["by_file"]) == ["Склады.yaml", "Партии.yaml"]
    assert short["by_file"]["Партии.yaml"] == {"applied": 0, "proposed": 0, "left": 1}
    # the moves the fold does not apply on its own come first, then the applied ones with a note
    assert short["review"] == [
        "Склады.yaml:9 element-key proposed -> 1 – первый блок файла стоит над ключом, который "
        "не входит в шапку: это может быть и описание элемента, и заметка к ключу",
        "Партии.yaml:5 end left – после блока нет ни одного узла: у заметки нет хозяина, "
        "возможно, она устарела",
        "Склады.yaml:12 item applied `Код` -> 10 – строка 13: текст ссылается на место",
    ]
    assert sum(short["reasons"].values()) == 2
    assert short["audit"] == []
    assert "files" not in short and "by_file_hint" not in short and "review_hint" not in short


def test_compact_report_stops_the_lists_at_the_limit_and_counts_the_rest():
    many = COMPACT_FINDINGS_LIMIT + 3
    folds = [
        _fold(f"Объект{number:02}.yaml",
              *[Move(line, "property", "applied") for line in range(number % 4 + 1)],
              Move(40, "mapping", "proposed", reason="fold.reason.collection"))
        for number in range(many)
    ]

    short = commentfold.compact_report(folds, 0)

    assert len(short["by_file"]) == COMPACT_FINDINGS_LIMIT
    heaviest = max(len(fold.moves) for fold in folds)
    assert sum(short["by_file"][next(iter(short["by_file"]))].values()) == heaviest
    assert f"файлов с блоками: {many}" in short["by_file_hint"]
    assert len(short["review"]) == COMPACT_FINDINGS_LIMIT
    assert f"взглянуть: {many}" in short["review_hint"]
    # the count by reason is not held to the limit: it is what take_proposed decides over
    assert short["reasons"] == {
        "блок стоит над списком, а не над одним его элементом": many}


def test_a_file_the_audit_stopped_is_listed_whole_past_any_limit():
    folds = [_fold(f"Объект{number:02}.yaml", Move(1, "property", "applied"),
                   audit=["после свертки yaml разбирается в другие данные"])
             for number in range(COMPACT_FINDINGS_LIMIT + 2)]

    short = commentfold.compact_report(folds, 0)

    assert len(short["audit"]) == COMPACT_FINDINGS_LIMIT + 2
    assert short["audit"][0] == {
        "file": "Объект00.yaml", "audit": ["после свертки yaml разбирается в другие данные"]}
    assert short["counts"]["changed"] == 0


# --- through the tool ---------------------------------------------------------------------

_COMPONENT = """ВидЭлемента: КомпонентИнтерфейса
Ид: 44444444-4444-4444-4444-444444444444
Имя: КарточкаСклада
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Группа
    Содержимое:
        -
            Тип: Надпись
            Имя: Заголовок
            Значение: =Заголовок
    # Группа видна всегда.
    Видимость: Истина
# Свойства карточки.
Свойства:
    -
        Имя: Заголовок
        Тип: Строка
"""


@pytest.mark.needs_data
def test_the_tool_answers_the_short_report_and_writes_like_the_whole_one(mcp_module, tmp_path):
    folder = tmp_path / "Склады"
    folder.mkdir()
    path = folder / "КарточкаСклада.yaml"
    path.write_bytes(_COMPONENT.encode("utf-8"))

    short = mcp_module.meta_fold_comments(["Склады"], root=str(tmp_path), compact=True)

    assert short["dry-run"] is True and short["root"] == str(tmp_path)
    assert short["counts"] == {
        "files": 1, "changed": 1, "applied": 1, "proposed": 1, "left": 0, "notes": 0}
    assert short["by_file"] == {str(path): {"applied": 1, "proposed": 1, "left": 0}}
    [line] = short["review"]
    assert line.startswith(f"{path}:14 element-key proposed -> 1 – ")
    assert path.read_bytes().decode("utf-8") == _COMPONENT

    written = mcp_module.meta_fold_comments([str(path)], dry_run=False, compact=True)
    assert "dry-run" not in written and written["written"] == 1 and written["audit"] == []
    text = path.read_bytes().decode("utf-8")
    assert "    ## * `Видимость`:\n    ##   Группа видна всегда.\n" in text
    assert "# Свойства карточки.\nСвойства:" in text
