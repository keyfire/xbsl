"""MCP `meta_fold_comments`: the fold of `xbsl fold-comments` for an agent.

The command existed in the CLI alone, so an agent editing an element description through the
`meta_*` tools had to leave them for a shell to fold the comments. The tool answers with the
report of `xbsl fold-comments --format json` and writes nothing unless `dry_run=false`.

Which node has room for a description comes from the metamodel and the ui schema, so the folds
themselves need the Element data (`needs_data`); the refusals and the surface do not.
"""

from __future__ import annotations

import inspect
import json

import pytest

from xbsl import cli

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
Свойства:
    -
        Имя: Заголовок
        Тип: Строка
"""

#: A block the fold only proposes: above a key outside the head, it may describe the element
#: or only that key.
_PROPOSED = _COMPONENT.replace("Свойства:\n", "# Свойства карточки.\nСвойства:\n")


def _element(folder, text: str = _COMPONENT, name: str = "КарточкаСклада.yaml"):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_the_tool_is_a_dry_run_unless_told_otherwise(mcp_module):
    parameters = inspect.signature(mcp_module.meta_fold_comments).parameters
    assert parameters["dry_run"].default is True
    assert parameters["take_proposed"].default is False
    assert "root" in parameters


def test_a_path_that_does_not_exist_is_refused_by_name(mcp_module, tmp_path):
    answer = mcp_module.meta_fold_comments(["Нет/Такого.yaml"], root=str(tmp_path))

    assert set(answer) == {"error", "root"}
    assert str(tmp_path / "Нет" / "Такого.yaml") in answer["error"]
    assert answer["root"] == str(tmp_path)


@pytest.mark.needs_data
def test_a_dry_run_answers_the_plan_and_writes_nothing(mcp_module, tmp_path):
    path = _element(tmp_path / "Склады")

    answer = mcp_module.meta_fold_comments(["Склады"], root=str(tmp_path))

    assert answer["dry-run"] is True and answer["written"] == 0
    assert answer["root"] == str(tmp_path)
    [record] = answer["files"]
    assert record["file"] == str(path) and record["changed"] is True and record["audit"] == []
    assert [(move["subject"], move["action"]) for move in record["moves"]] == [
        ("Видимость", "applied")]
    assert answer["summary"] == {"property/applied": 1}
    assert path.read_bytes().decode("utf-8") == _COMPONENT


@pytest.mark.needs_data
def test_dry_run_false_writes_the_fold(mcp_module, tmp_path):
    path = _element(tmp_path / "Склады")

    answer = mcp_module.meta_fold_comments([str(path)], dry_run=False)

    assert "dry-run" not in answer and answer["written"] == 1
    text = path.read_bytes().decode("utf-8")
    assert "    ## * `Видимость`:\n    ##   Группа видна всегда.\n    Тип: Группа\n" in text
    assert "# Группа видна всегда.\n    Видимость" not in text


@pytest.mark.needs_data
def test_the_report_is_the_one_the_cli_prints(mcp_module, tmp_path, capsys):
    folder = tmp_path / "Склады"
    _element(folder, _PROPOSED)

    assert cli.main(["fold-comments", str(folder), "--format", "json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    answer = mcp_module.meta_fold_comments([str(folder)])

    assert {key: value for key, value in answer.items() if key not in ("root", "dry-run")} == printed


@pytest.mark.needs_data
def test_proposed_moves_wait_for_take_proposed(mcp_module, tmp_path):
    path = _element(tmp_path / "Склады", _PROPOSED)

    listed = mcp_module.meta_fold_comments([str(path)], dry_run=False)
    proposed = [move for move in listed["files"][0]["moves"] if move["action"] == "proposed"]
    assert len(proposed) == 1 and proposed[0]["reason"]
    assert "# Свойства карточки." in path.read_bytes().decode("utf-8")

    taken = mcp_module.meta_fold_comments([str(path)], dry_run=False, take_proposed=True)
    assert taken["written"] == 1
    text = path.read_bytes().decode("utf-8")
    assert "\n# Свойства карточки.\nСвойства:" not in text
    assert text.startswith("## Свойства карточки.\nВидЭлемента:")
