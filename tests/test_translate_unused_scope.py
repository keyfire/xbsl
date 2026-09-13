"""The orphan tools in the shape a cleaning pass asks its questions in.

One call with several names in place of one call per name; a compact answer where the
question is how a word is translated already; a walk over the sources that answers in part
rather than not at all; and the pairs a change wrote into the dictionary counted as that
change's own, so a line written and reworded inside one branch does not leave its first pair
behind for good.
"""

import asyncio
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from xbsl import i18n
from xbsl.translation import cli, dictionary as dictionary_module, entries

_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)
_BASE_DICTIONARY = "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n"


def _project(repo: Path, comment: str = "") -> Path:
    project = repo / "vendor" / "app"
    project.mkdir(parents=True, exist_ok=True)
    (project / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    _write_tasks(project, comment)
    return project


def _write_tasks(project: Path, comment: str) -> None:
    line = f"# {comment}\n" if comment else ""
    (project / "Задачи.yaml").write_text(
        "ВидЭлемента: Справочник\nИд: bbbbbbbb-1111-2222-3333-444444444444\n"
        f"Имя: Задачи\n{line}",
        encoding="utf-8",
    )


def _dictionary(next_to: Path, body: str) -> Path:
    """The dictionary catalog next to the vendor folder, where the discovery finds it."""
    folder = next_to / dictionary_module.DICTIONARY_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "010-objects.yaml").write_text(body, encoding="utf-8")
    return folder


def _git(repo: Path, *args: str) -> str:
    """One git call in the throwaway repository these tests build."""
    done = subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(repo), capture_output=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8", "replace")


# -- translate_entries: the compact answer -------------------------------------------


@pytest.mark.needs_data
def test_entries_answer_compactly_and_ten_rows_at_a_time(mcp_module, tmp_path):
    """The question is how a word is translated already. Ten rows settle it, and the file,
    the line and the scope of each row are the bulk of an answer that came to ten kilobytes
    for one common stem."""
    project = _project(tmp_path)
    rows = "".join(f"    Секция{n:02}: Section{n:02}\n" for n in range(12))
    _dictionary(tmp_path / "vendor", "version: 1\nlanguage: en\ntokens:\n" + rows)

    answer = mcp_module.translate_entries(str(project), filter="секция")

    assert answer["total"] == 12 and answer["shown"] == 10 and answer["truncated"]
    assert set(answer["entries"][0]) == {"key", "kind", "value", "file", "line", "scope"}

    compact = mcp_module.translate_entries(str(project), filter="секция", compact=True, limit=0)

    assert len(compact["entries"]) == 12 and not compact["truncated"]
    assert set(compact["entries"][0]) == {"key", "kind", "value"}
    assert compact["entries"][0]["value"] == "Section00"


# -- translate_unused: several filters, a budget ----------------------------------------


@pytest.mark.needs_data
def test_unused_takes_a_list_of_filters_and_names_the_ones_nothing_fell_under(
        mcp_module, tmp_path):
    """A sweep over the comments takes ten lines out, and whether the dictionary keeps any of
    them used to be ten calls. A list asks it once, and `unmatched` is the half of the
    answer the sweep reads: the lines the dictionary no longer holds."""
    project = _project(tmp_path)
    _dictionary(
        tmp_path / "vendor",
        _BASE_DICTIONARY + "    СнятоеИмя: RemovedName\n"
        "phrases:\n    Первая снятая строка.: The first removed line.\n"
        "    Вторая снятая строка.: The second removed line.\n",
    )

    answer = mcp_module.translate_unused(
        str(project), filter=["первая снятая", "RemovedName", "живая строка"])

    assert {row["key"] for row in answer["unused"]} == {"Первая снятая строка.", "СнятоеИмя"}
    assert answer["unmatched"] == ["живая строка"]
    assert "note" not in answer, "a filtered answer is not the whole-dictionary one"

    one = mcp_module.translate_unused(str(project), filter="вторая")

    assert [row["key"] for row in one["unused"]] == ["Вторая снятая строка."]
    assert one["unmatched"] == []
    assert "unmatched" not in mcp_module.translate_unused(str(project))


@pytest.mark.needs_data
def test_unused_answers_in_part_when_the_budget_is_spent(mcp_module, tmp_path):
    """A call over a large project said nothing until the client gave up on it, half an hour
    later. With a budget it answers what it has read, says so, and prunes nothing on it: an
    entry used only in a file not read is on the list as well."""
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor", _BASE_DICTIONARY + "    СнятоеИмя: RemovedName\n")
    before = (folder / "010-objects.yaml").read_text(encoding="utf-8")

    answer = mcp_module.translate_unused(str(project), budget_seconds=0, prune=True)

    assert answer["partial"] is True
    assert answer["sources"] == {"read": 0, "total": 2}
    assert "budget_seconds" in answer["note"] and "0 файлов из 2" in answer["note"]
    assert isinstance(answer["unused"], list) and "counts" in answer
    assert {row["key"] for row in answer["unused"]} == {"Задачи", "СнятоеИмя"}
    assert "removed" not in answer
    assert (folder / "010-objects.yaml").read_text(encoding="utf-8") == before

    whole = mcp_module.translate_unused(str(project), budget_seconds=60)

    assert "partial" not in whole and whole["sources"] == {"read": 2, "total": 2}
    assert [row["key"] for row in whole["unused"]] == ["СнятоеИмя"]


@pytest.mark.needs_data
def test_the_command_reports_progress_on_stderr_and_keeps_the_json_whole(
        tmp_path, capsys, monkeypatch):
    """Progress goes to stderr, so `--format json` on stdout stays one document."""
    project = _project(tmp_path)
    _dictionary(tmp_path / "vendor", _BASE_DICTIONARY)
    monkeypatch.setattr(entries, "PROGRESS_STEP", 1)

    code = cli.cli_main([str(project), "--unused", "--format", "json", "--lang", "ru"])

    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out)["total"] == 0
    assert "прочитано файлов: 1 из 2" in captured.err
    assert "прочитано файлов: 2 из 2" in captured.err


# -- since: the pairs the change wrote ----------------------------------------------------


def _repo(tmp_path: Path) -> tuple[Path, Path, str]:
    """A project and its dictionary under git, at the base commit."""
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    project = _project(tmp_path)
    folder = _dictionary(tmp_path / "vendor", _BASE_DICTIONARY)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return project, folder / "010-objects.yaml", _git(tmp_path, "rev-parse", "HEAD").strip()


def _write_and_reword_inside_one_change(tmp_path: Path, project: Path, dictionary: Path
                                        ) -> None:
    """The change: a comment line with its pair, then the line reworded and translated anew.

    The first wording is committed and the second is left in the working tree, the way a
    task stands when it asks what it left behind.
    """
    _write_tasks(project, "Первая редакция строки.")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "phrases:\n    Первая редакция строки.: The first wording of the line.\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "the line and its pair")
    _write_tasks(project, "Вторая редакция строки.")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "    Вторая редакция строки.: The second wording of the line.\n",
        encoding="utf-8",
    )


@pytest.mark.needs_data
def test_a_pair_written_and_orphaned_inside_one_change_is_its_orphan(tmp_path):
    """The diff against the base shows neither wording of a line written and reworded in the
    branch, so the first pair stayed for good: 29 of them on one task, over 400 on another.
    The pairs the change wrote are its candidates, judged like the rest."""
    project, dictionary, base = _repo(tmp_path)
    _write_and_reword_inside_one_change(tmp_path, project, dictionary)
    loaded = dictionary_module.load(dictionary.parent)

    removed = entries.removed_surfaces(project, base, dictionary.parent)
    rows = entries.unused_entries(project, dictionary.parent, loaded, removed)

    assert removed.dictionary_files == 1 and removed.dictionary_added == 2
    assert removed.added_keys == {"Первая редакция строки.", "Вторая редакция строки."}
    assert [row.key for row in rows] == ["Первая редакция строки."]
    # The control: read from the sources alone, the change looks as if it left nothing.
    blind = entries.removed_surfaces(project, base)
    assert blind.dictionary_added == 0
    assert entries.unused_entries(project, dictionary.parent, loaded, blind) == []


@pytest.mark.needs_data
def test_an_explicit_key_on_an_added_line_is_read_as_a_candidate(tmp_path):
    """A long key is written `? key` / `: value` by a dumper; its added line reads too."""
    project, dictionary, base = _repo(tmp_path)
    _write_tasks(project, "Вторая редакция строки.")
    dictionary.write_text(
        dictionary.read_text(encoding="utf-8")
        + "phrases:\n    ? Первая редакция строки.\n    : The first wording of the line.\n"
        "    Вторая редакция строки.: The second wording of the line.\n",
        encoding="utf-8",
    )

    removed = entries.removed_surfaces(project, base, dictionary.parent)

    assert removed.added_keys == {"Первая редакция строки.", "Вторая редакция строки."}


@pytest.mark.needs_data
def test_a_dictionary_outside_the_repository_adds_no_candidates(tmp_path):
    """There is no diff to read for it: the mode answers with zeros rather than failing."""
    repo = tmp_path / "repo"
    project = _project(repo)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD").strip()
    elsewhere = tmp_path / "elsewhere" / "dictionary.yaml"
    elsewhere.parent.mkdir()
    elsewhere.write_text(_BASE_DICTIONARY, encoding="utf-8")

    removed = entries.removed_surfaces(project, base, elsewhere)

    assert removed.dictionary_files == 0 and removed.dictionary_added == 0
    assert removed.added_keys == set()


@pytest.mark.needs_data
def test_the_command_sizes_both_sides_of_the_change(tmp_path, capsys):
    """The `since` block says how much of each side was read, in JSON and in the header."""
    project, dictionary, base = _repo(tmp_path)
    _write_and_reword_inside_one_change(tmp_path, project, dictionary)

    code = cli.cli_main([str(project), "--unused", "--since", base,
                         "--format", "json", "--lang", "ru"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["since"] == {"base": base, "files": 1,
                                "dictionary_files": 1, "dictionary_added": 2}
    assert [row["key"] for row in payload["unused"]] == ["Первая редакция строки."]
    assert {"kind", "key", "value", "file", "line"} <= set(payload["unused"][0])

    cli.cli_main([str(project), "--unused", "--since", base, "--lang", "ru"])

    out = capsys.readouterr().out
    assert "файлов в правке: 1" in out and "добавленных правкой пар словаря: 2" in out


@pytest.mark.needs_data
def test_the_tool_counts_the_dictionary_side_of_the_change(mcp_module, tmp_path):
    project, dictionary, base = _repo(tmp_path)
    _write_and_reword_inside_one_change(tmp_path, project, dictionary)

    answer = mcp_module.translate_unused(str(project), since=base)

    assert answer["since"]["files"] == 1 and answer["since"]["dictionary_added"] == 2
    assert [row["key"] for row in answer["unused"]] == ["Первая редакция строки."]
    assert "note" not in answer


# -- the help, and the real server ----------------------------------------------------


def test_the_help_of_unused_points_at_the_json_fields():
    """The machine shape was there all along and the help did not say so - the text rows
    were being parsed with a regular expression over double spaces, which a key may hold."""
    for lang in ("ru", "en"):
        i18n.set_lang(lang)
        try:
            text = i18n.t("translate.help.unused")
        finally:
            i18n.set_lang("ru")
        assert "--format json" in text, lang
        assert all(name in text for name in ("kind", "key", "value", "file", "line")), lang


def _real_server():
    """The server module against the installed FastMCP, or a skip when the extra is absent."""
    pytest.importorskip("mcp.server.fastmcp")
    sys.modules.pop("xbsl.mcp_server", None)
    return importlib.import_module("xbsl.mcp_server")


def test_the_real_server_describes_a_filter_as_a_string_or_a_list():
    """The union has to reach the schema: a type FastMCP could not describe would drop the
    tool from the listing, and a caller would see no way to pass a list."""
    module = _real_server()
    try:
        tools = asyncio.run(module.mcp.list_tools())
    finally:
        sys.modules.pop("xbsl.mcp_server", None)

    schema = next(tool for tool in tools if tool.name == "translate_unused").inputSchema
    options = schema["properties"]["filter"]["anyOf"]
    assert {"type": "string"} in options
    assert {"type": "array", "items": {"type": "string"}} in options
    assert schema["properties"]["budget_seconds"]["default"] == 300
    entries_schema = next(tool for tool in tools if tool.name == "translate_entries").inputSchema
    assert entries_schema["properties"]["limit"]["default"] == 10
    assert entries_schema["properties"]["compact"]["default"] is False


@pytest.mark.needs_data
def test_the_real_server_takes_a_list_through_a_call(tmp_path):
    """The call path of the protocol, not the function: the list arrives through validation."""
    module = _real_server()
    project = _project(tmp_path)
    _dictionary(tmp_path / "vendor", _BASE_DICTIONARY + "    СнятоеИмя: RemovedName\n")
    try:
        result = asyncio.run(module.mcp.call_tool(
            "translate_unused",
            {"root": str(project), "filter": ["removedname", "нет-такого"], "compact": True},
        ))
    finally:
        sys.modules.pop("xbsl.mcp_server", None)

    content = result[0] if isinstance(result, tuple) else result
    answer = json.loads(content[0].text)
    assert [row["key"] for row in answer["unused"]] == ["СнятоеИмя"]
    assert answer["unmatched"] == ["нет-такого"]
