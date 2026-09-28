"""The refusal of a stale server names the CLI command of the same call (xbsl/mcpcli.py).

Caught live on 27.09.2026: the engine under a running session moved from 0.119.1 to 0.120.0,
the server refused every tool with "restart the xbsl MCP server", and an agent cannot restart
a server - the lint and the dictionary were finished through the CLI, the commands pieced
together by hand. The refusal now carries the command line of the same call. What is held
here: the line parses back into the arguments the call came with - the same paths, the same
rule set, the same page - through the CLI's own parsers; its words survive a POSIX shell
whatever a path spells; it runs this interpreter on the engine this process imported; every
argument of a mapped tool reaches it or is known to shape the answer only; and a call the CLI
cannot make the same way gets no command at all.

Data-free but for the runs marked `needs_data`: the parsers and the rule registry need no
Element data, a check of a text and the translation commands do.
"""

from __future__ import annotations

import inspect
import io
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from xbsl import cli, engine, environment, freshness, i18n, mcpcli
from xbsl.translation import cli as translate_cli
from xbsl.translation import entries as entries_module

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)


def _commands(line: str) -> list[tuple[dict[str, str], list[str], str]]:
    """The line read the way a POSIX shell reads it: per command, the variable assignments in
    front of it, its words, and the file its stdin is redirected from ("" for none)."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    commands: list[list[str]] = [[]]
    for token in lexer:
        if token == ";":
            commands.append([])
        else:
            commands[-1].append(token)
    read = []
    for words in commands:
        assigned = {}
        while words and _ASSIGNMENT.fullmatch(words[0]):
            name, _, value = words.pop(0).partition("=")
            assigned[name] = value
        stdin = ""
        if "<" in words:
            at = words.index("<")
            stdin, words = words[at + 1], words[:at] + words[at + 2:]
        read.append((assigned, words, stdin))
    return read


def _one(answer: dict) -> tuple[dict[str, str], list[str], str]:
    (command,) = _commands(answer["cli"])
    return command


def _tail(words: list[str]) -> list[str]:
    """The arguments after `-m xbsl`: what the CLI's own parser reads."""
    at = words.index("-m")
    assert words[at + 1] == "xbsl"
    return words[at + 2:]


@pytest.fixture(autouse=True)
def _staged_in_the_tests_folder(monkeypatch, tmp_path):
    """The data of a call is saved in the test's own folder, not in the system's temporary one."""
    staged = tmp_path / "staged"
    staged.mkdir()
    monkeypatch.setattr(mcpcli, "_staged_in", str(staged))


@pytest.fixture()
def same(mcp_module):
    """`same(tool, **arguments)`: what mcpcli answers for a call of that tool, the arguments
    completed by the tool's own defaults - the way the server hands them over."""

    def build(tool: str, **arguments):
        bound = inspect.signature(getattr(mcp_module, tool)).bind(**arguments)
        bound.apply_defaults()
        return mcpcli.same_call(tool, dict(bound.arguments))

    return build


# -- the line ----------------------------------------------------------------------------------


def test_the_command_starts_the_interpreter_of_the_server(same):
    assigned, words, stdin = _one(same("list_rules"))

    assert words[0] == sys.executable
    assert ("-P" in words[:words.index("-m")]) == (sys.version_info >= (3, 11))
    assert assigned[i18n.ENV_LANG] == i18n.current_lang() and stdin == ""


def test_a_path_with_spaces_and_cyrillic_survives_the_shell(same, tmp_path):
    root = tmp_path / "корень с пробелом"
    absolute = tmp_path / "it's here" / "Ч.xbsl"

    _assigned, words, _stdin = _one(same(
        "lint_paths", paths=["acme/Мой Проект", str(absolute)], root=str(root)))

    assert _tail(words)[:2] == [str(root / "acme" / "Мой Проект"), str(absolute)]


def test_a_value_that_starts_with_a_dash_is_not_taken_for_a_flag(same, tmp_path):
    _assigned, words, _stdin = _one(same(
        "translate_entries", root=str(tmp_path), filter="-dash", compact=True))

    args = translate_cli._parser().parse_args(_tail(words)[1:])

    assert args.filter == "-dash" and args.entries


def test_a_tool_without_a_counterpart_gets_no_command(same):
    assert same("docs_search", query="Массив") is None
    assert same("meta_add_field", yaml_path="Задачи.yaml", field_kind="реквизит",
                name="Срок") is None


# -- the environment ---------------------------------------------------------------------------


def test_the_settings_of_the_server_travel_and_its_secrets_do_not(same, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("XBSL_DATA_DIR", "data")
    monkeypatch.setenv("XBSL_NO_PLUGINS", "1")
    monkeypatch.setenv("XBSL_TRANSLATE_YANDEX_KEY", "secret-key")
    param = engine.PARAMS[0]
    monkeypatch.setenv(param.env, "7")

    assigned, _words, _stdin = _one(same("list_rules"))
    line = same("list_rules")["cli"]

    assert assigned["XBSL_DATA_DIR"] == str(tmp_path / "data")
    assert assigned["XBSL_NO_PLUGINS"] == "1" and assigned[param.env] == "7"
    assert "secret-key" not in line and "XBSL_TRANSLATE" not in line


def test_a_source_checkout_goes_on_the_path_and_an_installation_does_not(
        same, monkeypatch, tmp_path):
    import sysconfig

    installed = Path(sysconfig.get_paths()["purelib"]) / "xbsl"
    monkeypatch.setattr(freshness, "PACKAGE", installed)
    assert "PYTHONPATH" not in _one(same("list_rules"))[0]

    monkeypatch.setattr(freshness, "PACKAGE", tmp_path / "checkout" / "xbsl")
    assert _one(same("list_rules"))[0]["PYTHONPATH"] == str(tmp_path / "checkout")


def test_the_command_runs_the_engine_this_process_imported(same, tmp_path):
    """Run as a shell would run it, from a folder that is not the repository's.

    From Python 3.11 a package named like the engine stands there too - a checkout of it, as
    far as `-m` can tell: `-m` alone puts that folder first and imports it, and the command
    would answer with whatever the folder holds.
    """
    assigned, words, _stdin = _one(same("list_rules"))
    if sys.version_info >= (3, 11):
        decoy = tmp_path / "xbsl"
        decoy.mkdir()
        (decoy / "__init__.py").write_text("", encoding="utf-8")
        (decoy / "__main__.py").write_text("print('the folder of the shell')\n", encoding="utf-8")

    done = subprocess.run(
        [*words[:words.index("-m") + 2], "--version"],
        capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(tmp_path),
        stdin=subprocess.DEVNULL, env={**os.environ, **assigned, "PYTHONIOENCODING": "utf-8"},
    )

    assert done.returncode == 0, done.stderr
    assert environment.location() in done.stdout


def test_the_resolution_of_paths_is_the_servers_own(mcp_module, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for root in (None, str(tmp_path / "root"), "relative"):
        base = mcpcli._base(root)
        assert base == str(mcp_module._base(root))
        for path in ("a/b.xbsl", "../c", str(tmp_path / "abs"), "."):
            assert mcpcli._under(base, path) == str(mcp_module._under(Path(base), path))


# -- every argument ----------------------------------------------------------------------------

#: The smallest call of each tool the CLI can make: its required arguments.
_BASE_CALLS = {
    "list_rules": {},
    "lint_paths": {"paths": ["a.xbsl"]},
    "lint_source": {"filename": "a.xbsl", "content": "x"},
    "baseline_prune": {"paths": ["a.xbsl"]},
    "meta_fold_comments": {"paths": ["a.yaml"]},
    "translate_status": {"root": "project"},
    "translate_gaps": {"root": "project"},
    "translate_entries": {"root": "project"},
    "translate_unused": {"root": "project"},
    "translate_redundant": {"root": "project"},
    "translate_drift": {"root": "project"},
    "translate_set": {"root": "project", "edits_file": "batch.yaml"},
}

#: The arguments that shape only the ANSWER of a tool, which the CLI prints its own way.
_SHAPE_ONLY = {
    ("lint_paths", "as_ci_full"),            # the whole CI-job record instead of its one line
    ("lint_paths", "list_info"),             # the info findings listed, not counted
    ("translate_status", "full"),            # every duplicate the ref has, instead of a count
    ("translate_unused", "budget_seconds"),  # the CLI walks every file, with no clock
}


def _changed(name: str, value, annotation) -> object:
    """Another value of an argument, of the kind the tool takes."""
    if name == "edits":
        return [{"key": "Проба", "value": "Probe"}]
    if isinstance(value, bool) or "bool" in str(annotation):
        return not value
    if isinstance(value, (int, float)):
        return value + 7
    if isinstance(value, list) or "list" in str(annotation):
        return [*(value or []), "code/blocks"]
    return f"{value or ''}-other"


def test_every_argument_of_a_mapped_tool_reaches_the_command(mcp_module, same):
    """A new argument of a tool the CLI runs must be carried or said to shape the answer only.

    Otherwise the command silently makes a different call than the one refused - the very
    thing the field exists to prevent.
    """
    assert set(mcpcli.BUILDERS) == set(_BASE_CALLS)
    for tool, base in _BASE_CALLS.items():
        assert tool in mcp_module.mcp.tools
        plain = same(tool, **base)
        assert plain is not None, tool
        for name, parameter in inspect.signature(getattr(mcp_module, tool)).parameters.items():
            value = base.get(name, parameter.default)
            answer = same(tool, **{**base, name: _changed(name, value, parameter.annotation)})
            if (tool, name) in _SHAPE_ONLY:
                assert answer == plain, (tool, name)
            else:
                assert answer != plain, (tool, name)


_DOCS = Path(__file__).resolve().parents[1] / "docs"


def _named(text: str, marker: str, tools) -> set[str]:
    """The tools a sentence names: the one holding `marker`, `translate_*` standing for the
    family."""
    flat = " ".join(text.split())
    (sentence,) = [part for part in re.split(r"(?<=[.:])\s", flat) if marker in part]
    names = set(re.findall(r"[a-z]+_[a-z_]*\*?", sentence))
    family = {name for name in names if name.endswith("*")}
    return (names - family) | {tool for tool in tools for prefix in family
                               if tool.startswith(prefix[:-1])}


def test_the_texts_name_the_tools_that_have_a_command(mcp_module):
    """The description of version_info and the servers page list the tools by hand, and a hand
    list drifts the moment a builder is added."""
    tools, mapped = set(mcp_module.mcp.tools), set(mcpcli.BUILDERS)

    assert _named(mcp_module.version_info.__doc__, "the CLI can run", tools) == mapped
    for page, marker in (("servers.md", "have such a command"),
                         ("servers.ru.md", "Такая команда есть")):
        assert _named((_DOCS / page).read_text(encoding="utf-8"), marker, tools) == mapped, page


# -- the linter --------------------------------------------------------------------------------


def test_lint_paths_parses_back_into_the_same_paths_and_rules(same, tmp_path):
    select, ignore, enable = ["code", "style"], ["code/blocks"], ["typography/em-dash"]
    _assigned, words, _stdin = _one(same(
        "lint_paths", paths=["acme/Проба"], root=str(tmp_path), select=select, ignore=ignore,
        enable=enable, baseline="base/.xbsllint-baseline", as_ci_job="english", fix=True))

    args = cli.build_parser().parse_args(_tail(words))
    parsed = (cli._parse_set(args.select), cli._parse_set(args.ignore), cli._parse_set(args.enable))

    assert args.paths == [str(tmp_path / "acme" / "Проба")]
    chosen = (set(select), set(ignore), set(enable))
    assert parsed == chosen and engine.active_rules(*parsed) == engine.active_rules(*chosen)
    assert args.baseline == str(tmp_path / "base" / ".xbsllint-baseline")
    assert args.as_ci_job == "english" and args.fix and args.format == "json"


def test_lint_paths_with_compact_or_compare_asks_for_the_text_report(same, tmp_path):
    _assigned, words, _stdin = _one(same("lint_paths", paths=["a"], root=str(tmp_path),
                                         compact=True, as_ci=True))
    compact = cli.build_parser().parse_args(_tail(words))
    _assigned, words, _stdin = _one(same("lint_paths", paths=["a"], root=str(tmp_path),
                                         compare="run.json"))
    compared = cli.build_parser().parse_args(_tail(words))

    assert compact.format == "text" and compact.as_ci == ""
    assert compact.paths == [str(tmp_path / "a")]
    assert compared.format == "text" and compared.compare == str(tmp_path / "run.json")


def test_a_call_without_paths_gets_no_command(same):
    """The CLI would check the working folder instead, and the tool checks nothing."""
    assert same("lint_paths", paths=[]) is None
    assert same("baseline_prune", paths=[""]) is None


def test_baseline_prune_names_the_entries_and_counts_the_findings(same, tmp_path):
    _assigned, words, _stdin = _one(same("baseline_prune", paths=["a"], root=str(tmp_path),
                                         select=["code"]))
    pruning = cli.build_parser().parse_args(_tail(words))
    _assigned, words, _stdin = _one(same("baseline_prune", paths=["a"], root=str(tmp_path),
                                         dry_run=True))
    looking = cli.build_parser().parse_args(_tail(words))

    assert pruning.prune_baseline and not pruning.stale_baseline and pruning.summary
    assert pruning.select == ["code"] and pruning.paths == [str(tmp_path / "a")]
    assert looking.stale_baseline and not looking.prune_baseline and looking.summary


def test_lint_source_reads_the_saved_text_on_stdin(same):
    content = "метод Ф()\r\n    возврат  \r\n;\n"

    answer = same("lint_source", filename="Задачи.xbsl", content=content, ignore=["code"])
    _assigned, words, stdin = _one(answer)
    args = cli.build_parser().parse_args(_tail(words))

    assert Path(stdin).read_bytes() == content.encode("utf-8")  # the line endings as they were
    assert stdin.endswith(".xbsl") and stdin in answer["cli_note"]
    assert args.stdin and args.filename == "Задачи.xbsl" and args.no_baseline
    assert args.ignore == ["code"] and args.format == "json"


def test_lint_source_refused_twice_saves_one_file(same):
    first = _one(same("lint_source", filename="a.xbsl", content="x"))[2]
    second = _one(same("lint_source", filename="a.xbsl", content="x"))[2]

    assert first == second


def test_lint_source_without_a_file_to_save_to_says_how_to_feed_stdin(same, monkeypatch):
    def refuse(**_kwargs):
        raise OSError("no temporary folder")

    monkeypatch.setattr(mcpcli, "_staged_in", None)
    monkeypatch.setattr(mcpcli.tempfile, "mkdtemp", refuse)

    answer = same("lint_source", filename="a.xbsl", content="x")

    assert _one(answer)[2] == "" and " < " not in answer["cli"]
    assert answer["cli_note"] == i18n.t("mcpcli.stdin-unstaged")


def test_list_rules_parses_back(same):
    _assigned, words, _stdin = _one(same("list_rules", select=["code/blocks"], ignore=["B"],
                                         filter="trailing"))

    args = cli.build_parser().parse_args(_tail(words))

    assert args.list_rules and args.format == "json" and args.rules_filter == "trailing"
    assert args.select == ["code/blocks"] and args.ignore == ["B"]


def test_fold_comments_writes_only_when_the_call_writes(same, tmp_path):
    _assigned, words, _stdin = _one(same("meta_fold_comments", paths=["a"], root=str(tmp_path)))
    planned = cli._fold_parser().parse_args(_tail(words)[1:])
    _assigned, words, _stdin = _one(same("meta_fold_comments", paths=["a"], root=str(tmp_path),
                                         dry_run=False, take_proposed=True, compact=True))
    written = cli._fold_parser().parse_args(_tail(words)[1:])

    assert planned.paths == [str(tmp_path / "a")] and not planned.write
    assert written.write and written.take_proposed and written.compact
    assert written.format == "json"


# -- the translation dictionary ----------------------------------------------------------------


def _translate(answer: dict) -> list:
    """The parsed arguments of every run of a translate command line."""
    parsed = []
    for _assigned, words, _stdin in _commands(answer["cli"]):
        tail = _tail(words)
        assert tail[0] == "translate"
        parsed.append(translate_cli._parser().parse_args(tail[1:]))
    return parsed


def test_the_listing_tools_parse_back_with_the_same_page(same, tmp_path):
    root = str(tmp_path / "проект")
    (gaps,) = _translate(same("translate_gaps", root=root, kind="token", filter="Сайт"))
    (entries,) = _translate(same("translate_entries", root=root, offset=20, compact=True))
    (drift,) = _translate(same("translate_drift", root=root, limit=0))
    (redundant,) = _translate(same("translate_redundant", root=root, filter="x", offset=5))

    assert gaps.root == root and gaps.gaps and gaps.kind == "token" and gaps.filter == "Сайт"
    assert (gaps.limit, gaps.offset, gaps.format) == (50, 0, "json")
    assert entries.entries and (entries.limit, entries.offset, entries.format) == (10, 20, "text")
    assert drift.drift and (drift.limit, drift.format) == (0, "json")
    assert redundant.redundant and (redundant.limit, redundant.offset) == (50, 5)


def test_a_relative_root_is_read_against_the_servers_folder(same, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    (status,) = _translate(same("translate_status", root="vendor/app"))

    assert status.root == str(tmp_path / "vendor" / "app") and status.format == "text"


def test_a_pruning_run_takes_the_whole_filtered_set(same, tmp_path):
    """The tool removes every row the filter selects, the CLI the page it lists."""
    (unused,) = _translate(same("translate_unused", root=str(tmp_path), filter=["Карточка"],
                                since="origin/master", prune=True, limit=5, offset=10))
    (redundant,) = _translate(same("translate_redundant", root=str(tmp_path), prune=True, limit=5))

    assert unused.unused and unused.prune and unused.filter == "Карточка"
    assert unused.since == "origin/master" and (unused.limit, unused.offset) == (0, 0)
    assert redundant.redundant and redundant.prune and redundant.limit == 0


def test_several_filters_of_translate_unused_get_no_command(same, tmp_path):
    assert same("translate_unused", root=str(tmp_path), filter=["a", "b"]) is None


def test_translate_status_with_a_ref_runs_the_collision_check_too(same, tmp_path):
    report, check = _translate(same("translate_status", root=str(tmp_path),
                                    against="origin/master"))

    assert not report.check_duplicates and report.root == str(tmp_path)
    assert check.check_duplicates and check.against == "origin/master"


def test_translate_set_hands_the_inline_edits_over_in_a_file(same, monkeypatch, tmp_path):
    edits = [{"key": "Проба", "value": "Probe"}, {"key": "Строка \\\"с кавычкой\\\"",
                                                   "value": "String", "kind": "literal"}]

    answer = same("translate_set", root=str(tmp_path), edits=edits, target="050-probe.yaml",
                  comment="Имена проб")
    (args,) = _translate(answer)

    assert entries_module.read_edits_file(Path(args.set_file)) == edits
    assert args.set_file in answer["cli_note"]
    assert (args.target, args.comment, args.format) == ("050-probe.yaml", "Имена проб", "json")

    monkeypatch.chdir(tmp_path)
    (from_file,) = _translate(same("translate_set", root=str(tmp_path), edits_file="batch.yaml"))
    assert from_file.set_file == str(tmp_path / "batch.yaml")
    assert same("translate_set", root=str(tmp_path), edits=edits, edits_file="batch.yaml") is None
    assert same("translate_set", root=str(tmp_path)) is None


# -- the same answer ---------------------------------------------------------------------------

_TRAILING = "метод Ф(): Число\r\n    возврат 1  \r\n;\r\n"  # trailing whitespace on line 2
_NO_PAIR = ["structure/xbsl-pair"]  # a temporary .xbsl has no paired yaml


@pytest.mark.needs_data
def test_the_lint_source_command_answers_what_the_tool_answers(
        mcp_module, same, monkeypatch, capsys):
    tool = mcp_module.lint_source("Ч.xbsl", _TRAILING, select=["whitespace"])
    _assigned, words, stdin = _one(same("lint_source", filename="Ч.xbsl", content=_TRAILING,
                                        select=["whitespace"]))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(Path(stdin).read_bytes())))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 0
    printed = json.loads(capsys.readouterr().out)

    assert tool["diagnostics"] and printed["diagnostics"] == tool["diagnostics"]


@pytest.mark.needs_data
def test_the_lint_paths_command_answers_what_the_tool_answers(mcp_module, same, tmp_path, capsys):
    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    (project / "Ч.xbsl").write_text(_TRAILING, encoding="utf-8", newline="")
    call = {"paths": ["acme/Проба/Ч.xbsl"], "ignore": _NO_PAIR, "root": str(tmp_path)}
    tool = mcp_module.lint_paths(**call)
    _assigned, words, _stdin = _one(same("lint_paths", **call))
    capsys.readouterr()

    cli.main(_tail(words))
    printed = json.loads(capsys.readouterr().out)

    assert tool["diagnostics"] and printed["diagnostics"] == tool["diagnostics"]


@pytest.mark.needs_data
def test_the_list_rules_command_answers_what_the_tool_answers(mcp_module, same, capsys):
    tool = mcp_module.list_rules(select=["whitespace"], filter="trailing")
    _assigned, words, _stdin = _one(same("list_rules", select=["whitespace"], filter="trailing"))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 0

    assert tool and json.loads(capsys.readouterr().out) == tool


_PROJECT_YAML = (
    "ВидЭлемента: Проект\nИд: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: app\nПоставщик: vendor\nЯзыкПоУмолчанию: Русский\n"
)


def _translated_project(repo: Path) -> Path:
    """A project with a dictionary next to it, as the translation tools find one."""
    project = repo / "vendor" / "app"
    project.mkdir(parents=True)
    (project / "Проект.yaml").write_text(_PROJECT_YAML, encoding="utf-8")
    folder = repo / "vendor" / "xbsl-translation"
    folder.mkdir()
    (folder / "010-objects.yaml").write_text(
        "version: 1\nlanguage: en\ntokens:\n    Задачи: Tasks\n    Задача: Task\n",
        encoding="utf-8")
    return project


@pytest.mark.needs_data
def test_the_translate_set_command_writes_what_the_tool_writes(mcp_module, same, tmp_path):
    by_tool, by_command = _translated_project(tmp_path / "a"), _translated_project(tmp_path / "b")
    edits = [{"key": "Проба", "value": "Probe"}, {"key": "Задача", "value": ""}]

    written = mcp_module.translate_set(root=str(by_tool), edits=edits, comment="Пробы")
    _assigned, words, _stdin = _one(same("translate_set", root=str(by_command), edits=edits,
                                         comment="Пробы"))
    assert cli.main(_tail(words)) == 0

    folders = [project.parent / "xbsl-translation" for project in (by_tool, by_command)]
    files = [{path.name: path.read_bytes() for path in folder.iterdir()} for folder in folders]
    assert "error" not in written and files[0] == files[1]


@pytest.mark.needs_data
def test_the_translate_entries_command_lists_what_the_tool_lists(
        mcp_module, same, tmp_path, capsys):
    project = _translated_project(tmp_path)
    tool = mcp_module.translate_entries(root=str(project), filter="Задач")
    _assigned, words, _stdin = _one(same("translate_entries", root=str(project), filter="Задач"))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 0

    assert len(tool["entries"]) == 2
    assert json.loads(capsys.readouterr().out)["entries"] == tool["entries"]
