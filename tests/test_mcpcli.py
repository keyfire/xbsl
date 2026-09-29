"""The refusal of a stale server names the CLI command of the same call (xbsl/mcpcli.py).

Caught live on 27.09.2026: the engine under a running session moved from 0.119.1 to 0.120.0,
the server refused every tool with "restart the xbsl MCP server", and an agent cannot restart
a server - the lint and the dictionary were finished through the CLI, the commands pieced
together by hand. The refusal now carries the command line of the same call. What is held
here: the line parses back into the arguments the call came with - the same paths, the same
rule set, the same page - through the CLI's own parsers; its words survive a POSIX shell
whatever a path spells; it runs this interpreter on the engine this process imported, whatever
folder the shell stands in; every argument of a mapped tool reaches it or is known to shape the
answer only; and a call the CLI cannot make the same way gets no command at all.

Every line is built twice: for this interpreter, and for a Python 3.10 (`sys.version_info`
swapped while the line is built). 3.10 has no `-P`, and its line stands each run in a subshell
that changes into the folder of the staged data first - the parser below reads both shapes and
holds that each run carries exactly one of the two guards.

Data-free but for the runs marked `needs_data`: the parsers, the rule registry and the
scaffolding need no Element data, a check of a text and the translation commands do.
"""

from __future__ import annotations

import collections
import inspect
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from xbsl import cli, engine, environment, freshness, i18n, mcpcli
from xbsl.translation import cli as translate_cli
from xbsl.translation import entries as entries_module

_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.S)
_OPERATOR = re.compile(r"&&|\|\||[();<>|&]")


def _tokens(line: str) -> list[str]:
    """The words and operators of a POSIX shell line. `shlex` hands a run of operators over as
    one token - `);` between two subshells - so such a run is split into its operators."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = []
    for token in lexer:
        if token and all(char in lexer.punctuation_chars for char in token):
            tokens += _OPERATOR.findall(token)
        else:
            tokens.append(token)
    return tokens


def _parsed(line: str) -> list[tuple[dict[str, str], list[str], str, str]]:
    """The line read the way a POSIX shell reads it: per command, the variable assignments in
    front of it, its words, the file its stdin is redirected from ("" for none) and the folder
    its subshell changes into first ("" for a command that runs where the shell stands)."""
    commands: list[list[str]] = [[]]
    for token in _tokens(line):
        if token == ";":
            commands.append([])
        else:
            commands[-1].append(token)
    read = []
    for words in commands:
        folder = ""
        if words[:1] == ["("]:
            assert words[1] == "cd" and words[3] == "&&" and words[-1] == ")", words
            folder, words = words[2], words[4:-1]
        assigned = {}
        while words and _ASSIGNMENT.fullmatch(words[0]):
            name, _, value = words.pop(0).partition("=")
            assigned[name] = value
        stdin = ""
        if "<" in words:
            at = words.index("<")
            stdin, words = words[at + 1], words[:at] + words[at + 2:]
        read.append((assigned, words, stdin, folder))
    return read


def _commands(line: str, *, guarded: bool = True) -> list[tuple[dict[str, str], list[str], str]]:
    """`_parsed` without the folder, once each run is seen to keep the shell's folder off the
    import path by exactly one guard: `-P`, or the subshell standing in the folder of the
    staged data. `guarded=False` reads a 3.10 line whose folder could not be made."""
    read = []
    for assigned, words, stdin, folder in _parsed(line):
        if guarded:
            safe_path = "-P" in words[1:words.index("-m")]
            assert safe_path != bool(folder), line
            assert not folder or folder == mcpcli._staged_in, (folder, mcpcli._staged_in)
        read.append((assigned, words, stdin))
    return read


def _one(answer: dict, *, guarded: bool = True) -> tuple[dict[str, str], list[str], str]:
    (command,) = _commands(answer["cli"], guarded=guarded)
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


_Version = collections.namedtuple("_Version", "major minor micro releaselevel serial")
#: An interpreter that knows no `-P` (it came with 3.11).
_PYTHON_3_10 = _Version(3, 10, 14, "final", 0)


@pytest.fixture(params=["this", "3.10"])
def python(request):
    """The interpreter a line is built for: this one (None), or a Python 3.10."""
    return None if request.param == "this" else _PYTHON_3_10


def _built_for(python, build):
    """What `build()` answers with `sys.version_info` swapped for `python`'s while it runs."""
    with pytest.MonkeyPatch.context() as patch:
        if python is not None:
            patch.setattr(sys, "version_info", python)
        return build()


@pytest.fixture()
def same(mcp_module, python):
    """`same(tool, **arguments)`: what mcpcli answers for a call of that tool, the arguments
    completed by the tool's own defaults - the way the server hands them over - and the line
    built for the interpreter of `python`."""

    def build(tool: str, **arguments):
        bound = inspect.signature(getattr(mcp_module, tool)).bind(**arguments)
        bound.apply_defaults()
        return _built_for(python, lambda: mcpcli.same_call(tool, dict(bound.arguments)))

    return build


# -- the line ----------------------------------------------------------------------------------


def test_the_command_starts_the_interpreter_of_the_server(same, python):
    ((assigned, words, stdin, folder),) = _parsed(same("list_rules")["cli"])
    safe_path = (python or sys.version_info) >= (3, 11)

    assert words[0] == sys.executable
    assert ("-P" in words[:words.index("-m")]) == safe_path
    assert folder == ("" if safe_path else mcpcli._staged_in)
    assert assigned[i18n.ENV_LANG] == i18n.current_lang() and stdin == ""


def test_every_run_of_a_3_10_line_stands_in_a_subshell_of_its_own(same, python, tmp_path):
    """A `cd` that fails stops its own run, and none starts from the shell's own folder; a line
    of an interpreter that takes `-P` has no subshell at all."""
    line = same("translate_status", root=str(tmp_path), against="origin/master")["cli"]
    subshell = f"(cd {shlex.quote(mcpcli._staged_in)} && "

    assert len(_commands(line)) == 2
    if (python or sys.version_info) >= (3, 11):
        assert "(cd " not in line
    else:
        assert line.startswith(subshell) and line.count(subshell) == 2
        assert line.endswith(")") and f"); {subshell}" in line


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


_DECOY = "the folder of the shell"


def _shell_folder(tmp_path: Path) -> Path:
    """A folder for the shell to stand in, holding a package named like the engine - a checkout
    of it, as far as `-m` can tell: `-m` puts the working folder first and imports from it."""
    decoy = tmp_path / "shell" / "xbsl"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("", encoding="utf-8")
    (decoy / "__main__.py").write_text(f"print({_DECOY!r})\n", encoding="utf-8")
    return decoy.parent


def _version_of(words: list[str], folder: Path | str,
                assigned: dict) -> subprocess.CompletedProcess:
    """The interpreter of the command, from `folder`, asked for the engine it runs."""
    return subprocess.run(
        [*words[:words.index("-m") + 2], "--version"],
        capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(folder),
        stdin=subprocess.DEVNULL, env={**os.environ, **assigned, "PYTHONIOENCODING": "utf-8"},
    )


def test_the_command_runs_the_engine_this_process_imported(same, tmp_path):
    """Run from a folder that holds a package named like the engine.

    The guard of the line keeps that folder off the import path: `-P` from Python 3.11, and on
    3.10 the subshell that changes into the folder of the staged data. The control: the same
    words without either guard, from the same folder, run the package the folder holds.
    """
    shell = _shell_folder(tmp_path)
    ((assigned, words, _stdin, folder),) = _parsed(same("list_rules")["cli"])

    done = _version_of(words, folder or shell, assigned)
    unguarded = _version_of([word for word in words if word != "-P"], shell, assigned)

    assert done.returncode == 0, done.stderr
    assert environment.location() in done.stdout and _DECOY not in done.stdout
    assert unguarded.stdout.strip() == _DECOY


def test_a_posix_shell_runs_the_line_from_where_it_stands(python, monkeypatch, tmp_path):
    """The whole line through `sh -c`, standing in the folder of the package named like the
    engine: the engine this process imported answers, and the shell stays in its folder after
    the line (a subshell, not a `cd` of the shell itself). The control: a 3.10 line built
    without its folder runs the package of the shell's folder."""
    posix = shutil.which("sh")
    if posix is None:
        pytest.skip("no POSIX shell (`sh`) on PATH")
    shell = _shell_folder(tmp_path)
    monkeypatch.setitem(mcpcli.BUILDERS, "probe",
                        lambda _arguments: ([mcpcli.Run(("--version",))], ""))

    def run(line: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [posix, "-c", f"{line}; test -d xbsl && echo still-in-the-folder"],
            capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=str(shell),
            stdin=subprocess.DEVNULL, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    done = run(_built_for(python, lambda: mcpcli.same_call("probe", {}))["cli"])
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(mcpcli, "_start_folder", lambda: "")
        unguarded = run(_built_for(_PYTHON_3_10, lambda: mcpcli.same_call("probe", {}))["cli"])

    assert done.returncode == 0, done.stderr
    assert environment.location() in done.stdout and _DECOY not in done.stdout
    assert done.stdout.rstrip().endswith("still-in-the-folder")
    assert unguarded.stdout.splitlines()[0] == _DECOY


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
    "meta_project_info": {"root": "project"},
    "meta_object_info": {"root": "project"},
    "meta_localization_info": {"yaml_path": "a.yaml"},
    "meta_component_tree": {"yaml_path": "a.yaml"},
    "meta_resource_references": {"root": "project", "resource_path": "Ресурсы/a.svg"},
    "meta_unused_resources": {"root": "project"},
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


def test_lint_source_reads_the_saved_text_on_stdin(same, monkeypatch, tmp_path):
    content = "метод Ф()\r\n    возврат  \r\n;\n"
    monkeypatch.chdir(tmp_path)

    answer = same("lint_source", filename="Задачи.xbsl", content=content, ignore=["code"])
    _assigned, words, stdin = _one(answer)
    args = cli.build_parser().parse_args(_tail(words))

    assert Path(stdin).read_bytes() == content.encode("utf-8")  # the line endings as they were
    assert stdin.endswith(".xbsl") and stdin in answer["cli_note"]
    # The name against the server's folder, where the tool reads it from (see below).
    assert args.stdin and args.filename == str(tmp_path / "Задачи.xbsl") and args.no_baseline
    assert args.ignore == ["code"] and args.format == "json"
    absolute = str(tmp_path / "Склад" / "Задачи.xbsl")
    _assigned, words, _stdin = _one(same("lint_source", filename=absolute, content=content))
    assert cli.build_parser().parse_args(_tail(words)).filename == absolute  # as it is


_LONE_MODULE = "метод Ф()\n;\n"


@pytest.mark.needs_data  # the CLI reads the Element data before a check of a text
def test_lint_source_looks_next_to_the_name_where_the_tool_looks(
        mcp_module, same, python, monkeypatch, tmp_path, capsys):
    """A relative name is read by the tool against the server's folder: the rules look there for
    the paired yaml. The command starts from another folder - on Python 3.10 always the folder
    of the staged data, on a newer one wherever the shell stands - and looks in the same place:
    both find the module under the name in the server's folder, and both miss its yaml."""
    server = tmp_path / "server"
    module = server / "Склад" / "Остатки.xbsl"
    module.parent.mkdir(parents=True)
    module.write_text(_LONE_MODULE, encoding="utf-8")
    shell = tmp_path / "shell"
    shell.mkdir()
    monkeypatch.chdir(server)
    call = {"filename": "Склад/Остатки.xbsl", "content": _LONE_MODULE,
            "select": ["structure/xbsl-pair"]}
    tool = mcp_module.lint_source(**call)
    ((_assigned, words, stdin, folder),) = _parsed(same("lint_source", **call)["cli"])

    monkeypatch.chdir(folder or shell)
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(Path(stdin).read_bytes())))
    capsys.readouterr()
    cli.main(_tail(words))
    printed = json.loads(capsys.readouterr().out)

    assert [finding["rule"] for finding in tool["diagnostics"]] == ["structure/xbsl-pair"]
    assert [(finding["rule"], finding["path"]) for finding in printed["diagnostics"]] == [
        ("structure/xbsl-pair", str(module))]


def test_lint_source_refused_twice_saves_one_file(same):
    first = _one(same("lint_source", filename="a.xbsl", content="x"))[2]
    second = _one(same("lint_source", filename="a.xbsl", content="x"))[2]

    assert first == second


def test_lint_source_without_a_file_to_save_to_says_how_to_feed_stdin(same, monkeypatch):
    """No temporary folder: no file to feed stdin from, and on 3.10 no folder to stand in -
    the line goes as it did before either existed."""
    def refuse(**_kwargs):
        raise OSError("no temporary folder")

    monkeypatch.setattr(mcpcli, "_staged_in", None)
    monkeypatch.setattr(mcpcli.tempfile, "mkdtemp", refuse)

    answer = same("lint_source", filename="a.xbsl", content="x")

    assert _one(answer, guarded=False)[2] == "" and " < " not in answer["cli"]
    assert "(cd " not in answer["cli"]
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


# -- the metadata readers ----------------------------------------------------------------------


def _scaffolding(answer: dict):
    """The parsed arguments of a meta_* reader's command: the scaffolding's own parser."""
    _assigned, words, _stdin = _one(answer)
    return cli._scaffold_parser().parse_args(_tail(words))


def test_the_project_map_parses_back_with_every_filter(same, monkeypatch, tmp_path):
    narrowed = _scaffolding(same("meta_project_info", root=str(tmp_path), kind="Справочник",
                                 subsystem="Склад", package="-Партии", brief=True))
    monkeypatch.chdir(tmp_path)
    everything = _scaffolding(same("meta_project_info", root="repo", reference=True))
    refused = _scaffolding(same("meta_project_info", root=str(tmp_path), project=""))

    assert narrowed.command == "project-info" and narrowed.root == str(tmp_path)
    assert (narrowed.kind, narrowed.subsystem, narrowed.package) == (
        "Справочник", "Склад", "-Партии")
    assert narrowed.brief and not narrowed.reference and narrowed.project is None
    assert everything.root == str(tmp_path / "repo") and everything.reference
    assert (everything.kind, everything.subsystem, everything.package) == (None, None, None)
    # An empty name is a name to the scaffolding: it matches no project, and the call is refused.
    assert refused.project == ""


def test_the_object_card_parses_back_by_name_or_by_path(same, tmp_path):
    by_name = _scaffolding(same("meta_object_info", root=str(tmp_path), name="Товары"))
    by_path = _scaffolding(same("meta_object_info", root=str(tmp_path),
                                yaml_path="Склад/Товары.yaml"))

    assert by_name.command == "object-info" and by_name.root == str(tmp_path)
    assert by_name.name == "Товары" and by_name.path is None
    assert by_path.path == str(tmp_path / "Склад" / "Товары.yaml") and by_path.name is None


def test_the_file_readers_parse_back_into_the_file_the_tool_reads(same, tmp_path):
    strings = _scaffolding(same("meta_localization_info", yaml_path="Склад/Тексты.yaml",
                                root=str(tmp_path)))
    tree = _scaffolding(same("meta_component_tree", yaml_path="Склад/Витрина.yaml",
                             root=str(tmp_path)))

    assert strings.command == "localization-info"
    assert strings.yaml_path == str(tmp_path / "Склад" / "Тексты.yaml")
    assert tree.command == "form-tree"
    assert tree.yaml_path == str(tmp_path / "Склад" / "Витрина.yaml")
    assert (tree.node, tree.name, tree.max_depth, tree.at) == (None, None, 0, None)
    assert not tree.no_properties and not tree.brief


def test_the_component_tree_parses_back_with_every_narrowing(same, tmp_path):
    by_id = _scaffolding(same("meta_component_tree", yaml_path=str(tmp_path / "Ф.yaml"),
                              node_id=_BUTTON, max_depth=2, properties=False, brief=True))
    by_name = _scaffolding(same("meta_component_tree", yaml_path=str(tmp_path / "Ф.yaml"),
                                name="КнопкаОбновить", max_depth=-1))

    assert by_id.node == _BUTTON and by_id.name is None and by_id.max_depth == 2
    assert by_id.no_properties and by_id.brief
    # Below one the depth has no limit, for the tool and for the CLI alike.
    assert by_name.name == "КнопкаОбновить" and by_name.node is None and by_name.max_depth == -1


def test_the_resource_readers_parse_back(same, tmp_path):
    references = _scaffolding(same("meta_resource_references", root=str(tmp_path),
                                   resource_path="Склад/Ресурсы/logo.svg", limit=5))
    unused = _scaffolding(same("meta_unused_resources", root=str(tmp_path),
                               include_protected=True, limit=7))
    default = _scaffolding(same("meta_unused_resources", root=str(tmp_path)))

    assert references.command == "resource-references" and references.root == str(tmp_path)
    assert references.resource_path == str(tmp_path / "Склад" / "Ресурсы" / "logo.svg")
    assert references.limit == 5
    assert _scaffolding(same("meta_resource_references", root=str(tmp_path),
                             resource_path="logo.svg")).limit == 100
    assert unused.command == "unused-resources" and unused.include_protected and unused.limit == 7
    assert not default.include_protected and default.limit == 100


def test_a_reader_without_its_file_gets_no_command(same, tmp_path):
    """The tool has no file to read either: the CLI would read the folder `.` instead."""
    assert same("meta_localization_info", yaml_path="") is None
    assert same("meta_component_tree", yaml_path="", root=str(tmp_path)) is None
    assert same("meta_resource_references", root=str(tmp_path), resource_path="") is None


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
        mcp_module, same, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    tool = mcp_module.lint_source("Ч.xbsl", _TRAILING, select=["whitespace"])
    _assigned, words, stdin = _one(same("lint_source", filename="Ч.xbsl", content=_TRAILING,
                                        select=["whitespace"]))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(Path(stdin).read_bytes())))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 0
    printed = json.loads(capsys.readouterr().out)

    # The same findings, filed under the name made absolute against the server's folder.
    assert tool["diagnostics"] and printed["diagnostics"] == [
        {**finding, "path": str(tmp_path / finding["path"])} for finding in tool["diagnostics"]]


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


_FORM = """\
ВидЭлемента: КомпонентИнтерфейса
Ид: 6f0b6a44-0000-4000-8000-000000000511
Имя: Витрина
ОбластьВидимости: ВПодсистеме
Наследует:
    Тип: Форма
    Заголовок: Витрина
    Содержимое:
        Тип: ПроизвольныйШаблонФормы
        Содержимое:
            -
                Тип: Надпись
                Имя: Приветствие
                Значение: Добро пожаловать
            -
                Тип: Кнопка
                Имя: КнопкаОбновить
                Заголовок: Обновить
Свойства:
    -
        Имя: Титул
        Тип: Строка
"""
_TEMPLATE = "Наследует/Содержимое[0]"
_BUTTON = _TEMPLATE + "/Содержимое[1]"

#: One project of the `Демо` vendor: a subsystem with a package, a catalog in each, localized
#: strings with an English translation, a form with properties of its own, and resources - two
#: named by a module, one named nowhere.
_WAREHOUSE = {
    "Проект.yaml": (
        "Ид: 6f0b6a44-0000-4000-8000-000000000500\nВерсия: 1.0.0\nПоставщик: Демо\nИмя: Учет\n"
        "РежимСовместимости: 9.0\nЯзыкиЛокализации: [Русский, Английский]\n"
        "ЯзыкПоУмолчанию: Русский\nЯзыкРазработки: Русский\n"
    ),
    "Склад/Подсистема.yaml": "Интерфейс:\n    ВключатьВАвтоИнтерфейс: Ложь\n",
    "Склад/Товары.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000501\nИмя: Товары\n"
        "ОбластьВидимости: ВПодсистеме\nРеквизиты:\n    -\n"
        "        Ид: 6f0b6a44-0000-4000-8000-000000000502\n        Имя: Цвет\n        Тип: Строка\n"
    ),
    "Склад/Партии/Лоты.yaml": (
        "ВидЭлемента: Справочник\nИд: 6f0b6a44-0000-4000-8000-000000000503\nИмя: Лоты\n"
        "ОбластьВидимости: ВПодсистеме\n"
    ),
    "Склад/Тексты.yaml": (
        "ВидЭлемента: ЛокализованныеСтроки\nИд: 6f0b6a44-0000-4000-8000-000000000504\n"
        "Имя: Тексты\nОбластьВидимости: ВПодсистеме\nСтроки:\n    Первая: Первый текст\n"
    ),
    "Склад/Локализация/En/Тексты.yaml": "Строки:\n    Первая: First text\n",
    "Склад/Витрина.yaml": _FORM,
    "Склад/Остатки.yaml": (
        "ВидЭлемента: ОбщийМодуль\nИд: 6f0b6a44-0000-4000-8000-000000000505\nИмя: Остатки\n"
        "ОбластьВидимости: ВПроекте\n"
    ),
    "Склад/Остатки.xbsl": (
        "метод Разметка(): Строка\n"
        "    знч Ссылка = Ресурс{Стили/a.css}.Ссылка\n"
        "    знч Скрипт = ПакетРесурсов.Текущий().Получить(\"Стили/b.js\")\n"
        "    возврат Ссылка + Ресурс{Стили/a.css}.Ссылка\n"
        ";\n"
    ),
    "Склад/Ресурсы/Ресурсы.yaml": "ОбластьВидимости: ВПроекте\n",
    "Склад/Ресурсы/Стили/a.css": "body { margin: 0; }\n",
    "Склад/Ресурсы/Стили/b.js": "void 0;\n",
    "Склад/Ресурсы/logo.svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"/>\n",
}
_STOCK = "Демо/Учет/Склад"


def _warehouse(repo: Path) -> Path:
    project = repo / "Демо" / "Учет"
    for rel, text in _WAREHOUSE.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return repo


#: What the tool of a reader adds around the data it read: the paths it repeats, and the hint
#: of meta_component_tree about its own parameters. The command names the paths itself; the
#: `root` of a component tree is the tree, not a path.
_ECHOED = {
    "meta_project_info": ("root",),
    "meta_object_info": ("root",),
    "meta_localization_info": ("root", "file"),
    "meta_component_tree": ("file", "hint"),
    "meta_resource_references": ("root",),
    "meta_unused_resources": (),
}


def _reader_calls(repo: Path) -> dict[str, tuple[str, dict]]:
    """The calls of the readers against the project, by what each one asks."""
    stock, root = f"{_STOCK}/", str(repo)
    form = {"yaml_path": stock + "Витрина.yaml", "root": root}
    return {
        "map": ("meta_project_info", {"root": root}),
        "catalogs": ("meta_project_info", {"root": root, "kind": "Справочник",
                                           "reference": True}),
        "package": ("meta_project_info", {"root": root, "package": "Партии",
                                          "project": "Демо::Учет"}),
        "counts": ("meta_project_info", {"root": root, "brief": True}),
        "card": ("meta_object_info", {"root": root, "name": "Товары"}),
        "card by path": ("meta_object_info", {"root": root,
                                              "yaml_path": stock + "Партии/Лоты.yaml"}),
        "strings": ("meta_localization_info", {"yaml_path": stock + "Тексты.yaml",
                                               "root": root}),
        "form": ("meta_component_tree", form),
        "button": ("meta_component_tree", {**form, "name": "КнопкаОбновить",
                                           "properties": False}),
        "template": ("meta_component_tree", {**form, "node_id": _TEMPLATE, "max_depth": 1}),
        "skeleton": ("meta_component_tree", {**form, "brief": True}),
        "styles": ("meta_resource_references", {"root": root,
                                                "resource_path": stock + "Ресурсы/Стили"}),
    }


def _answered_alike(mcp_module, same, capsys, label: str, tool: str, call: dict) -> dict:
    """The command of the call run through the CLI, held against the tool's answer: the same
    data, and the paths the tool repeats being the paths the command names. The printed
    answer comes back."""
    answer = getattr(mcp_module, tool)(**call)
    _assigned, words, _stdin = _one(same(tool, **call))
    args = cli._scaffold_parser().parse_args(_tail(words))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 0, label
    printed = json.loads(capsys.readouterr().out)

    assert "error" not in answer, (label, answer)
    echoed = _ECHOED[tool]
    assert printed == {key: value for key, value in answer.items() if key not in echoed}, label
    if "root" in echoed and "root" in vars(args):  # localization-info names the file alone
        assert answer["root"] == args.root, label
    if "file" in echoed:
        assert answer["file"] == args.yaml_path, label
    return printed


def test_the_reader_commands_answer_what_the_tools_answer(mcp_module, same, tmp_path, capsys):
    """Every meta_* reader but meta_unused_resources (below, it needs the data) against one
    project: the command prints the tool's own data."""
    repo = _warehouse(tmp_path / "repo")
    printed = {label: _answered_alike(mcp_module, same, capsys, label, tool, call)
               for label, (tool, call) in _reader_calls(repo).items()}

    # The answers hold what the calls asked about - two empty answers would match whatever
    # the command did - and a filter of the call reaches the answer of the command.
    assert {entry["name"] for entry in printed["map"]["objects"]} >= {
        "Товары", "Лоты", "Витрина"}
    assert printed["map"]["packages"] and printed["map"]["projects"]
    assert {entry["name"] for entry in printed["package"]["objects"]} == {"Лоты"}
    assert printed["catalogs"]["objects"] != printed["map"]["objects"]
    assert [record["name"] for record in printed["form"]["componentProperties"]] == ["Титул"]
    assert [node["id"] for node in printed["button"]["roots"]] == [_BUTTON]
    assert printed["strings"]["existing"] == ["En"]
    assert printed["styles"]["total"] >= 3


@pytest.mark.needs_data
def test_the_unused_resources_command_answers_what_the_tool_answers(
        mcp_module, same, tmp_path, capsys):
    repo = _warehouse(tmp_path / "repo")
    call = {"root": str(repo), "include_protected": True}

    printed = _answered_alike(mcp_module, same, capsys, "unused", "meta_unused_resources", call)

    unused = json.dumps(printed["unused"], ensure_ascii=False)
    assert "logo.svg" in unused and "a.css" not in unused  # a module names the styles


def test_the_references_command_cuts_the_list_as_the_tool_does(
        mcp_module, same, tmp_path, capsys):
    """`limit` reaches the CLI as `--limit`: the same first places, and `total` counts all."""
    repo = _warehouse(tmp_path / "repo")
    call = {"root": str(repo), "resource_path": f"{_STOCK}/Ресурсы/Стили", "limit": 1}

    printed = _answered_alike(mcp_module, same, capsys, "limit", "meta_resource_references", call)

    assert printed["total"] > len(printed["references"]) == 1
    assert cli.main(["resource-references", str(repo), f"{repo}/{_STOCK}/Ресурсы/Стили",
                     "--limit", "-1"]) == 0
    assert json.loads(capsys.readouterr().out)["references"] == []  # none below zero, as there


def test_a_tree_the_tool_cannot_find_is_refused_by_the_command_too(
        mcp_module, same, tmp_path, capsys):
    """A refusal is an answer as well: the command refuses the same call with the same words."""
    repo = _warehouse(tmp_path / "repo")
    call = {"yaml_path": f"{_STOCK}/Витрина.yaml", "root": str(repo), "name": "Нетакого"}
    answer = mcp_module.meta_component_tree(**call)
    _assigned, words, _stdin = _one(same("meta_component_tree", **call))
    capsys.readouterr()

    assert cli.main(_tail(words)) == 2
    assert json.loads(capsys.readouterr().out)["error"] == answer["error"]


def test_old_staged_folders_are_swept_and_the_rest_kept(tmp_path):
    """A server leaves its folder for a command run after the restart; the next one sweeps."""
    day = 24 * 3600
    now = time.time()
    old = tmp_path / "xbsl-mcp-old"
    old.mkdir()
    (old / "call.xbsl").write_text("x", encoding="utf-8")
    young = tmp_path / "xbsl-mcp-young"
    young.mkdir()
    stranger = tmp_path / "another-tool-old"
    stranger.mkdir()
    lone_file = tmp_path / "xbsl-mcp-file"
    lone_file.write_text("x", encoding="utf-8")
    for aged in (old, stranger, lone_file):
        os.utime(aged, (now - 2 * day, now - 2 * day))

    assert mcpcli.sweep_old_folders(str(tmp_path), now) == 1
    assert not old.exists()
    assert young.exists() and stranger.exists() and lone_file.exists()
