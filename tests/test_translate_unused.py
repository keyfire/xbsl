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
import shutil
import subprocess
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


# -- what a phrase is keyed by, and where a name may stand ----------------------


def _module(root: Path, name: str, body: str) -> None:
    (root / name).write_text(body, encoding="utf-8")


def test_a_doc_comment_is_keyed_the_way_the_translator_keys_it(tmp_path: Path):
    """`///` and `##` are markers, not text - and a private reading of them cost a live pair.

    The orphan pass used a regex of its own that took ONE space off the marker: a doc comment
    came back with a slash glued to the text, so the entry the translating pass had written
    matched nothing here and read as an orphan - the one mistake `--prune` acts on.
    """
    root, dictionary = _project(tmp_path)
    _module(root, "Модуль.xbsl", "/// Строка документирующего комментария.\nметод А()\n;\n")
    (root / "Прочее.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Прочее\n## Строка комментария в две решётки.\n",
        encoding="utf-8",
    )
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "    Строка документирующего комментария.: A line of a doc comment.\n"
        + "    Строка комментария в две решётки.: A line under a double hash.\n",
        encoding="utf-8",
    )

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Строка документирующего комментария." not in keys
    assert "Строка комментария в две решётки." not in keys


def test_a_block_comment_line_is_read_as_a_comment(tmp_path: Path):
    """A block comment translates like any other, so its lines are live pairs as well."""
    root, dictionary = _project(tmp_path)
    _module(root, "Модуль.xbsl", "/*\n * Строка блочного комментария.\n */\nметод А()\n;\n")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "    Строка блочного комментария.: A line of a block comment.\n",
        encoding="utf-8",
    )

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Строка блочного комментария." not in keys


def test_a_slash_star_inside_a_comment_does_not_swallow_the_file(tmp_path: Path):
    """`usr/idea/*` written inside a `//` line is a path, not the start of a block.

    A textual reading took it for one and read every line after it as a block line - which
    turned four hundred live comment pairs of a real project into orphans at once.
    """
    root, dictionary = _project(tmp_path)
    _module(
        root, "Модуль.xbsl",
        "// Работает на группе методов usr/idea/* сервиса.\n"
        "// Следующая строка комментария.\nметод А()\n;\n",
    )
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "    Следующая строка комментария.: The next comment line.\n",
        encoding="utf-8",
    )

    keys = {row.key for row in _unused(root, dictionary)}

    assert "Следующая строка комментария." not in keys


def test_a_name_that_only_stands_in_a_file_name_is_used(tmp_path: Path):
    """Folder and file names go through the same token plane, so a path is a place too."""
    root, dictionary = _project(tmp_path)
    (root / "Ресурсы").mkdir()
    (root / "Ресурсы" / "ЗначокЗадачи.svg").write_bytes(b"<svg/>")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8").replace(
            "    Реквизиты: Attributes\n",
            "    Реквизиты: Attributes\n    ЗначокЗадачи: TaskIcon\n    Ресурсы: Resources\n",
        ),
        encoding="utf-8",
    )

    keys = {row.key for row in _unused(root, dictionary)}

    assert "ЗначокЗадачи" not in keys and "Ресурсы" not in keys


# -- the orphans of ONE change -------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    """One git call in the throwaway repository these tests build."""
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


@pytest.fixture
def committed(tmp_path: Path):
    """A project under git with an orphan ALREADY in the dictionary, plus the base commit.

    The old orphan is the control of every test here: it is what the plain question answers
    with, and what the orphans of a change must leave alone.
    """
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    root, dictionary = _project(tmp_path, "    СнятоеИмя: RemovedName\n")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return root, dictionary, _git(tmp_path, "rev-parse", "HEAD").strip()


def _drop_a_name_and_a_comment(root: Path) -> None:
    """The change under test: a name renamed away, a comment line reworded."""
    (root / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\n"
        "Имя: Задачи\n"
        "# Шаги ведутся списком.\n"
        "Реквизиты:\n"
        "    -\n"
        "        Имя: ШагЗадачи\n"
        "        Тип: Строка\n",
        encoding="utf-8",
    )


def test_the_change_answers_with_its_own_orphans_only(committed):
    """The point of the mode: a live project answers the plain question with thousands of
    rows, and a task cleaning up after itself asks about the handful its change left."""
    root, dictionary, base = committed
    _drop_a_name_and_a_comment(root)
    loaded = dictionary_module.load(dictionary)

    removed = entries.removed_surfaces(root, base)
    rows = entries.unused_entries(root, dictionary, loaded, removed)

    assert {row.key for row in rows} == {"Шаг", "Шаги задачи ведутся списком."}
    # The control: what the plain question answers with - two of those four are older debt.
    plain = {row.key for row in entries.unused_entries(root, dictionary, loaded)}
    assert plain == {"Шаг", "Шаги задачи ведутся списком.", "СнятоеИмя",
                     "Прежняя строка, которой в коде уже нет."}


def test_a_live_entry_is_never_an_orphan_of_a_change(committed):
    """The narrowing is an intersection: a name the project still carries is listed by
    neither side, however generously the diff reads. The change rewrites the whole file, so
    every live name of it stands on a removed line as well."""
    root, dictionary, base = committed
    _drop_a_name_and_a_comment(root)

    keys = {row.key for row in entries.unused_entries(
        root, dictionary, dictionary_module.load(dictionary),
        entries.removed_surfaces(root, base))}

    assert "Задачи" not in keys and "Реквизиты" not in keys


def test_a_deleted_file_takes_the_names_of_its_path_with_it(committed):
    """A name that only ever stood in a file name is used - so its deletion is a removal."""
    root, dictionary, _base = committed
    (root / "Ресурсы").mkdir()
    (root / "Ресурсы" / "ЗначокЗадачи.svg").write_bytes(b"<svg/>")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8").replace(
            "    Реквизиты: Attributes\n",
            "    Реквизиты: Attributes\n    ЗначокЗадачи: TaskIcon\n"),
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "icon")
    base = _git(root, "rev-parse", "HEAD").strip()
    (root / "Ресурсы" / "ЗначокЗадачи.svg").unlink()

    keys = {row.key for row in entries.unused_entries(
        root, dictionary, dictionary_module.load(dictionary),
        entries.removed_surfaces(root, base))}

    assert "ЗначокЗадачи" in keys


def test_a_removed_line_of_dashes_is_source_and_not_a_diff_header(committed):
    """`-- text` arrives in the diff as `--- text`: reading that as a file header would
    attribute the rest of the hunk to a file with no suffix, and its names go missing."""
    root, dictionary, _base = committed
    (root / "Прочее.xbsl").write_text(
        "-- Разделитель оформления\nметод СнятыйМетод()\n;\n", encoding="utf-8")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8").replace(
            "    Реквизиты: Attributes\n",
            "    Реквизиты: Attributes\n    СнятыйМетод: RemovedMethod\n"),
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "module")
    base = _git(root, "rev-parse", "HEAD").strip()
    (root / "Прочее.xbsl").write_text("метод Живой()\n;\n", encoding="utf-8")

    keys = {row.key for row in entries.unused_entries(
        root, dictionary, dictionary_module.load(dictionary),
        entries.removed_surfaces(root, base))}

    assert "СнятыйМетод" in keys


def test_a_base_that_has_moved_on_is_read_from_the_fork_point(committed):
    """A ref is diffed from where it PARTED with HEAD: what the base branch did afterwards
    is not something this change removed."""
    root, dictionary, base = committed
    _drop_a_name_and_a_comment(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    _git(root, "branch", "-q", "work")
    _git(root, "checkout", "-q", base)
    (root / "Прочее.yaml").write_text(
        "ВидЭлемента: Справочник\nИмя: Прочее\nПоле: Реквизиты\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "the base branch moves on")
    moved = _git(root, "rev-parse", "HEAD").strip()
    _git(root, "checkout", "-q", "work")

    removed = entries.removed_surfaces(root, moved)

    assert removed.base == base, "the fork point, not the tip of the base branch"
    keys = {row.key for row in entries.unused_entries(
        root, dictionary, dictionary_module.load(dictionary), removed)}
    assert keys == {"Шаг", "Шаги задачи ведутся списком."}


def test_a_range_is_handed_to_git_as_written(committed):
    """`A..B` is how a change already merged is examined, whatever the sources on disk say."""
    root, _dictionary, base = committed
    _drop_a_name_and_a_comment(root)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")
    tip = _git(root, "rev-parse", "HEAD").strip()

    removed = entries.removed_surfaces(root, f"{base}..{tip}")

    assert removed.base == f"{base}..{tip}" and removed.files == 1
    assert "Шаг" in removed.names and "Шаги задачи ведутся списком." in removed.lines


def test_an_unknown_revision_is_refused_by_name(committed):
    root, _dictionary, _base = committed

    with pytest.raises(ValueError) as refusal:
        entries.removed_surfaces(root, "нет-такой-ветки")

    assert "нет-такой-ветки" in str(refusal.value)


def test_the_child_git_never_gets_the_stdin_of_this_process(committed, monkeypatch):
    """The whole mode ran inside a server and answered nothing for as long as it was let to.

    An MCP or LSP server speaks over stdin, and a child that says nothing about stdin gets
    that handle. On Windows git then never reaches its own exit - the work took four
    milliseconds and the read waited out the timeout - so `--since` looked like a mode that
    hangs while the same question with `--filter` answered at once.
    """
    root, _dictionary, base = committed
    seen = {}
    real = subprocess.run

    def spy(command, **options):
        seen.update(options)
        return real(command, **options)

    monkeypatch.setattr(subprocess, "run", spy)
    entries.removed_surfaces(root, base)

    assert seen.get("stdin") == subprocess.DEVNULL


def test_a_git_call_that_stops_answering_is_refused_with_a_way_round(committed, monkeypatch):
    """A bound on the silence: what cannot be read is said, and there is another way to ask."""
    root, _dictionary, base = committed

    def stalls(command, **options):
        raise subprocess.TimeoutExpired(command, options.get("timeout") or 0)

    monkeypatch.setattr(subprocess, "run", stalls)
    with pytest.raises(ValueError) as refusal:
        entries.removed_surfaces(root, base)

    assert str(entries.GIT_TIMEOUT) in str(refusal.value)
    assert "--filter" in str(refusal.value)


def test_the_command_narrows_and_prunes_exactly_the_change(committed, capsys):
    """`--prune --since` is the pass a task makes at its end: its own leavings, nothing else."""
    root, dictionary, base = committed
    _drop_a_name_and_a_comment(root)

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary),
                                 "--prune", "--since", base])

    assert any("снято пар: 2" in line for line in lines), lines
    left = dictionary.read_text(encoding="utf-8")
    assert "Шаг: Step" not in left and "Шаги задачи ведутся списком." not in left
    # What the change did not touch stays, orphan or not.
    assert "СнятоеИмя" in left and "Прежняя строка" in left


def test_the_command_says_the_reading_is_textual_when_nothing_narrows_it(committed, capsys):
    """Without a filter the answer describes the whole accumulated dictionary, and a run that
    took it for a worklist would prune the project's history."""
    root, dictionary, _base = committed

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary), "--unused"])

    assert any("чтение сирот текстовое" in line for line in lines), lines
    assert any("--since" in line for line in lines), lines


def test_the_note_goes_once_the_question_is_narrowed(committed, capsys):
    root, dictionary, base = committed
    _drop_a_name_and_a_comment(root)

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary),
                                 "--unused", "--since", base, "--format", "json"])
    payload = json.loads("\n".join(lines))
    assert "note" not in payload and payload["since"]["files"] == 1

    _code, lines = _run(capsys, [str(root), "--dictionary", str(dictionary),
                                 "--unused", "--filter", "Шаг", "--format", "json"])
    assert "note" not in json.loads("\n".join(lines))


def test_the_command_refuses_an_unknown_revision(committed, capsys):
    root, dictionary, _base = committed

    code = cli.cli_main([str(root), "--dictionary", str(dictionary),
                         "--unused", "--since", "нет-такой-ветки", "--lang", "ru"])

    assert code == 2
    assert "нет-такой-ветки" in capsys.readouterr().err
