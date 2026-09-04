"""Dictionary entries the project no longer has a place for.

Deleting code leaves its names and comment lines in the dictionary, and nothing said so: the
strict pass judges what is NOT covered, and the entries table shows where a pair is declared,
not whether anything uses it. One task left 43 of them behind, found only by a throwaway
script.

The reading is textual on purpose, and the direction of its error is the point: it may call an
orphan "used" (a name that also occurs in prose), which merely leaves an entry in place; it
must never call a LIVE entry an orphan, because that is the mistake `--prune` would act on.
"""

import json
from pathlib import Path

import pytest

from xbsl import i18n
from xbsl.translation import cli, dictionary as dictionary_module, entries

pytestmark = pytest.mark.needs_data


@pytest.fixture(autouse=True)
def _ru_lang():
    i18n.set_lang("ru")
    yield
    i18n.set_lang(None)


def _project(tmp_path: Path, extra_tokens: str = "") -> tuple[Path, Path]:
    """A tiny project plus a dictionary that covers it, with room for orphans."""
    root = tmp_path / "Acme" / "Demo"
    root.mkdir(parents=True)
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Имя: Задачи\n"
        "# Шаги задачи ведутся списком.\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: Шаг\n"
        "        Тип: Строка\n",
        encoding="utf-8",
    )
    dictionary = tmp_path / "dictionary.yaml"
    dictionary.write_text(
        "version: 1\nlanguage: en\n"
        "tokens:\n"
        "    Задачи: Tasks\n"
        "    Шаг: Step\n"
        "    Реквизиты: Attributes\n"
        f"{extra_tokens}"
        "phrases:\n"
        "    Шаги задачи ведутся списком.: The task steps are kept as a list.\n"
        "    Прежняя строка, которой в коде уже нет.: A former line the code no longer has.\n",
        encoding="utf-8",
    )
    return root, dictionary


def _unused(root: Path, dictionary: Path):
    loaded = dictionary_module.load(dictionary)
    return entries.unused_entries(root, dictionary, loaded)


def test_a_name_the_project_dropped_is_found(tmp_path: Path):
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")

    rows = _unused(root, dictionary)

    assert [(row.kind, row.key) for row in rows if row.kind == "token"] == [("token", "СнятоеИмя")]


def test_a_reworded_comment_leaves_its_former_line_behind(tmp_path: Path):
    root, dictionary = _project(tmp_path)

    rows = _unused(root, dictionary)

    phrases = [row.key for row in rows if row.kind == "phrase"]
    assert phrases == ["Прежняя строка, которой в коде уже нет."]


def test_a_live_entry_is_never_called_an_orphan(tmp_path: Path):
    """The control, and the one that matters: --prune acts on this answer."""
    root, dictionary = _project(tmp_path)

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Задачи" not in keys and "Шаг" not in keys and "Реквизиты" not in keys
    assert "Шаги задачи ведутся списком." not in keys


def test_a_renamed_name_does_not_hide_behind_its_longer_successor(tmp_path: Path):
    """A name renamed into a LONGER one leaves an orphan a substring search would miss."""
    root, dictionary = _project(tmp_path)
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Задачи\nРеквизиты:\n    -\n"
        "        Имя: ШагЗадачи\n        Тип: Строка\n",
        encoding="utf-8",
    )

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Шаг" in keys


def test_a_qualified_key_is_judged_by_both_halves(tmp_path: Path):
    """A qualified key spells the owner and the name apart - the dotted text is not a name.

    Judging it whole called EVERY qualified entry an orphan, and there are hundreds of them.
    """
    root, dictionary = _project(
        tmp_path, "    Задачи.Шаг: TaskStep\n    Небыло.Шаг: NeverWasStep\n")

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Задачи.Шаг" not in keys, "both halves of the key are in the project"
    assert "Небыло.Шаг" in keys, "the owner is gone - there is nothing left to qualify"


# -- the command ---------------------------------------------------------------


def _run(capsys, args: list[str]) -> tuple[int, list[str]]:
    code = cli.cli_main(args + ["--lang", "ru"])
    return code, capsys.readouterr().out.rstrip("\n").splitlines()


def test_the_command_lists_them_and_writes_nothing(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")
    before = dictionary.read_text(encoding="utf-8")

    code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--unused"])

    assert code == 0
    assert any("СнятоеИмя" in line for line in lines)
    assert dictionary.read_text(encoding="utf-8") == before


def test_prune_removes_exactly_what_it_listed(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--prune"])

    assert any("снято пар: 2" in line for line in lines), lines
    left = dictionary.read_text(encoding="utf-8")
    assert "СнятоеИмя" not in left and "Прежняя строка" not in left
    # The live half stays: exactly what was listed is what goes.
    assert "Задачи: Tasks" in left and "Шаги задачи ведутся списком." in left


def test_prune_of_a_page_says_it_is_a_page(tmp_path: Path, capsys):
    """`--limit` cuts what is removed too, and silence about that would be a trap."""
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")

    _code, lines = _run(
        capsys, [str(root), "--dictionary", str(dictionary), "--prune", "--limit", "1"])

    assert any("только показанная страница" in line for line in lines), lines
    assert any("снято пар: 1" in line for line in lines), lines


def test_json_mode_answers_with_the_rows(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")

    _code, lines = _run(
        capsys,
        [str(root), "--dictionary", str(dictionary), "--unused", "--format", "json"],
    )

    payload = json.loads("\n".join(lines))
    assert payload["total"] == 2
    assert {row["key"] for row in payload["unused"]} == {
        "СнятоеИмя", "Прежняя строка, которой в коде уже нет."}


def test_a_clean_dictionary_says_so(tmp_path: Path, capsys):
    root, dictionary = _project(tmp_path)
    dictionary.write_text(
        "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n    Шаг: Step\n"
        "    Реквизиты: Attributes\n",
        encoding="utf-8",
    )

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--unused"])

    assert any("пар без места в проекте нет" in line for line in lines), lines
