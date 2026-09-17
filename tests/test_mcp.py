"""MCP adapter check via a stub FastMCP (does not require mcp to be installed)."""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from xbsl import cli


class _FakeMCP:
    def __init__(self, name):
        self.name = name
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco

    def run(self):  # pragma: no cover
        pass


def test_mcp_adapter_registers_tools_and_lints(monkeypatch):
    fast = types.ModuleType("mcp.server.fastmcp")
    fast.FastMCP = _FakeMCP
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fast)
    sys.modules.pop("xbsl.mcp_server", None)

    m = importlib.import_module("xbsl.mcp_server")
    assert {"lint_paths", "lint_source", "list_rules"}.issubset(m.mcp.tools)

    rules = m.list_rules()
    assert any(r["id"] == "code/blocks" for r in rules)

    res = m.lint_source("М.xbsl", "метод Ф()  \n;\n", select=["whitespace/trailing"])
    assert res["summary"]["diagnostics"] >= 1

    sys.modules.pop("xbsl.mcp_server", None)


def _with_stub(monkeypatch):
    """The server module imported against a stub FastMCP - its tools are plain functions."""
    fast = types.ModuleType("mcp.server.fastmcp")
    fast.FastMCP = _FakeMCP
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fast)
    sys.modules.pop("xbsl.mcp_server", None)
    return importlib.import_module("xbsl.mcp_server")


_TRAILING = "метод Ф(): Число\n    возврат 1  \n;\n"  # trailing whitespace on line 2
_NO_PAIR = ["structure/xbsl-pair"]  # a temporary .xbsl has no paired yaml


def test_lint_paths_applies_the_project_baseline(tmp_path, monkeypatch):
    """The MCP answer must match the CLI: a committed baseline suppresses its findings.

    Until it did, the agent read a project with frozen debt as dirty and had to run the CLI
    over the same folder to tell a real finding from a baselined one.
    """
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        f = project / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")
        cli.main(["--write-baseline", str(tmp_path / ".xbsllint-baseline"),
                  "--ignore", _NO_PAIR[0], str(f)])

        res = m.lint_paths([str(f)], ignore=_NO_PAIR)

        assert res["diagnostics"] == []
        assert res["summary"]["baselined"] == 1
        assert res["summary"]["baseline"].endswith(".xbsllint-baseline")
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_does_not_call_an_unchecked_entry_stale(tmp_path, monkeypatch):
    """A rule this server does not carry leaves its entries not checked, never stale.

    A server running an older plugin than CI answered `baseline_stale: 48` on a tree CI
    called clean - the entries belonged to rules that server never ran.
    """
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        f = project / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")
        bl = tmp_path / ".xbsllint-baseline"
        cli.main(["--write-baseline", str(bl), "--ignore", _NO_PAIR[0], str(f)])
        data = json.loads(bl.read_text(encoding="utf-8"))
        data["files"]["acme/Проба/Ч.xbsl"]["typography/em-dash"] = {
            "Длинное тире (em dash) - в этом проекте пишут среднее.": {"count": 2},
        }
        bl.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

        res = m.lint_paths([str(f)], ignore=[*_NO_PAIR, "typography/em-dash"])

        assert res["summary"]["baseline_stale"] == 0
        assert res["summary"]["baseline_unused"] == 0
        assert res["summary"]["baseline_not_checked"] == 1
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_answers_about_one_rule_with_its_parameters(monkeypatch):
    """Reading one threshold used to mean pulling all two hundred rules - and not finding it."""
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(select=["code/duplicate-method-body"])

        assert [r["id"] for r in listed] == ["code/duplicate-method-body"]
        param = listed[0]["params"][0]
        assert param["name"] == "min-lines"
        assert param["value"] == 5 and param["default"] == 5
        assert param["env"] == "XBSL_CODE_DUPLICATE_METHOD_BODY_MIN_LINES"
        assert param["doc"].strip()
        # a rule that judges by no number carries no empty list through the answer
        plain = next(r for r in m.list_rules() if r["id"] == "code/blocks")
        assert "params" not in plain
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


# --- list_rules: filter by id, group, title or description ------------------------------


def test_list_rules_filter_by_id_substring(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="duplicate-method-body")
        assert [r["id"] for r in listed] == ["code/duplicate-method-body"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_by_group_includes_the_whole_group(monkeypatch):
    """A group name reaches every rule of that group, not a lucky few of them."""
    from xbsl import engine

    m = _with_stub(monkeypatch)
    try:
        listed = {r["id"] for r in m.list_rules(filter="style")}
        style_rules = {r.id for r in engine.RULES if r.id.startswith("style/")}
        assert len(style_rules) > 1
        assert style_rules <= listed
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_matching_rules_group_check_is_exact_not_a_substring():
    """The group half of the filter is an EQUALITY check against the id's own group - not a
    text search that would also catch "code" inside a hypothetical "yaml/error-code".

    Built from two bare RuleInfo records rather than the real registry: real rule text is
    prose, and prose about one group legitimately mentions another group's name in passing
    (whitespace/mixed-newline's message says "bring them to a single style") - a fact about
    the description search, not about whether group matching itself stays an equality check.
    """
    from xbsl.diagnostics import Severity
    from xbsl.engine import RuleInfo, matching_rules

    def _dummy():
        """Used only to give RuleInfo a callable; never invoked here."""

    in_group = RuleInfo("style/abbreviation-case", "style/abbreviation-case.title", "C",
                        "file", Severity.WARNING, _dummy)
    outside_group = RuleInfo("yaml/error-code", "yaml/error-code.title", "A",
                             "file", Severity.WARNING, _dummy)

    matched = matching_rules([in_group, outside_group], "style")

    assert [r.id for r in matched] == ["style/abbreviation-case"]


def test_list_rules_filter_by_a_title_word_in_either_language(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        en = m.list_rules(filter="abbreviation")
        ru = m.list_rules(filter="аббревиатур")
        ids = {"naming/abbreviation", "style/abbreviation-case"}
        assert {r["id"] for r in en} == ids
        assert {r["id"] for r in ru} == ids
        assert m.list_rules(filter="ABBREVIATION") == en  # case-insensitive
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_by_a_word_of_the_description(monkeypatch):
    """"description" reaches past the short title into the rule's own explanation.

    code/self-assignment's title is "Assignment to itself" / "Присваивание самому себе" -
    neither spelling carries "compiler"; its docstring and its diagnostic messages do.
    """
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="compiler")
        assert any(r["id"] == "code/self-assignment" for r in listed)
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_by_a_russian_word_only_in_a_message_template(monkeypatch):
    """The description half of the filter is bilingual too - not just the English docstring.

    The Russian word this test filters by names the compiler ("the compiler rejects...") and
    sits only in the RU text of code/self-assignment's diagnostic messages
    (code/self-assignment.plain/.compound); neither its RU title nor its (English) docstring
    carries it.
    """
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="компилятор")
        assert any(r["id"] == "code/self-assignment" for r in listed)
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_by_an_english_word_only_in_the_docstring(monkeypatch):
    """The docstring stays part of the search even once message templates are too.

    "assigned" sits in code/self-assignment's docstring ("A value assigned back to the
    place...") but in none of its registered i18n text: the title says "Assignment", the
    messages say "assignment" - neither is the word "assigned" itself.
    """
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="assigned")
        assert any(r["id"] == "code/self-assignment" for r in listed)
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


# --- a title_key SHARED by two rules, without either rule's id in it --------------------
#
# code/ambiguous-type and yaml/ambiguous-type both pass title_key="ambiguous-type.title" -
# a key registered without EITHER rule's id as a prefix, alongside a sibling
# "ambiguous-type.found" that carries the finding's own message. Neither key satisfies the
# "<rule id> + '.'" sweep, so both rules used to be reachable only through the single
# language `info.title` happened to answer with, and never through "ambiguous-type.found"
# at all - the one pair in the registry the id-prefix sweep alone cannot see.


def _ambiguous_type_ids(listed) -> set[str]:
    return {r["id"] for r in listed} & {"code/ambiguous-type", "yaml/ambiguous-type"}


def test_list_rules_filter_finds_a_shared_title_key_pair_by_an_english_title_word(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="short")  # "Ambiguous short type name"
        assert _ambiguous_type_ids(listed) == {"code/ambiguous-type", "yaml/ambiguous-type"}
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_finds_a_shared_title_key_pair_by_a_russian_title_word(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="короткое")  # "Неоднозначное короткое имя типа"
        assert _ambiguous_type_ids(listed) == {"code/ambiguous-type", "yaml/ambiguous-type"}
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_finds_a_shared_title_key_pair_by_an_english_message_word(monkeypatch):
    """"namespaces" sits only in ambiguous-type.found, a sibling key of the shared title_key -
    not in the title of either rule, so only the stem sweep (not the title alone) reaches it.
    """
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="namespaces")
        assert _ambiguous_type_ids(listed) == {"code/ambiguous-type", "yaml/ambiguous-type"}
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_finds_a_shared_title_key_pair_by_a_russian_message_word(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(filter="пространств")
        assert _ambiguous_type_ids(listed) == {"code/ambiguous-type", "yaml/ambiguous-type"}
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_combines_with_select(monkeypatch):
    """select/ignore work as before, and the filter narrows further inside what they leave."""
    m = _with_stub(monkeypatch)
    try:
        listed = m.list_rules(select=["style"], filter="abbreviation")
        assert [r["id"] for r in listed] == ["style/abbreviation-case"]

        empty = m.list_rules(select=["code"], filter="abbreviation")
        assert "error" in empty and "near_groups" in empty
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_empty_filter_lists_everything(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        assert m.list_rules(filter="") == m.list_rules()
        assert m.list_rules(filter="   ") == m.list_rules()
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_matching_nothing_explains_and_suggests_groups(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        answer = m.list_rules(filter="zzzznotarule")
        assert isinstance(answer, dict) and "error" in answer
        assert "zzzznotarule" in answer["error"]
        assert "near_groups" in answer
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_list_rules_filter_suggests_a_near_group_for_a_typo(monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        answer = m.list_rules(filter="stlye")  # a typo of "style"
        assert "style" in answer["near_groups"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def _project_with_stale_entry(tmp_path, reason="так и задумано, правило здесь не применяем"):
    """A project whose baseline holds one live entry and one stale entry with a reason."""
    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    f = project / "Ч.xbsl"
    f.write_text(_TRAILING, encoding="utf-8")
    bl = tmp_path / ".xbsllint-baseline"
    cli.main(["--write-baseline", str(bl), "--ignore", _NO_PAIR[0], str(f)])
    data = json.loads(bl.read_text(encoding="utf-8"))
    data["files"]["acme/Проба/Ушедший.xbsl"] = {
        "whitespace/trailing": {"Хвостовые пробелы.": {"count": 2, "reason": reason}},
    }
    bl.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return project, bl


def test_lint_paths_names_the_stale_entries(tmp_path, monkeypatch):
    """The summary said `baseline_stale: 9` and stopped there.

    Which nine it was could only be found by taking the file apart with a script of one's
    own, sorting the entries by the prose of their `reason`. The entries travel with the
    count now, the same way the CLI json carries them.
    """
    m = _with_stub(monkeypatch)
    try:
        project, _bl = _project_with_stale_entry(tmp_path)

        res = m.lint_paths([str(project)], ignore=_NO_PAIR)

        summary = res["summary"]
        assert summary["baseline_stale"] == 1
        entry = summary["baseline_stale_entries"][0]
        assert entry["path"] == "acme/Проба/Ушедший.xbsl"
        assert entry["rule"] == "whitespace/trailing" and entry["count"] == 2
        assert entry["reason"] == "так и задумано, правило здесь не применяем"
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_baseline_prune_removes_the_stale_entries_and_reports_their_reasons(
    tmp_path, monkeypatch,
):
    """Removing is a tool of its own: a check never touches the file by itself."""
    m = _with_stub(monkeypatch)
    try:
        project, bl = _project_with_stale_entry(tmp_path)
        before = bl.read_text(encoding="utf-8")

        res = m.baseline_prune([str(project)], ignore=_NO_PAIR)

        assert res["stale"] == 1 and res["written"] is True
        assert res["removed"][0]["reason"] == "так и задумано, правило здесь не применяем"
        data = json.loads(bl.read_text(encoding="utf-8"))
        assert "acme/Проба/Ушедший.xbsl" not in data["files"]
        # the live entry keeps its place, its count and the shape of the file
        assert data["files"]["acme/Проба/Ч.xbsl"]["whitespace/trailing"]
        assert before.count("\r\n") == bl.read_text(encoding="utf-8").count("\r\n")
        assert m.lint_paths([str(project)], ignore=_NO_PAIR)["summary"]["baseline_stale"] == 0
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_baseline_prune_dry_run_leaves_the_file_alone(tmp_path, monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        project, bl = _project_with_stale_entry(tmp_path)
        before = bl.read_text(encoding="utf-8")

        res = m.baseline_prune([str(project)], ignore=_NO_PAIR, dry_run=True)

        assert res["stale"] == 1 and res["written"] is False
        assert bl.read_text(encoding="utf-8") == before
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_baseline_prune_leaves_the_entries_it_could_not_check(tmp_path, monkeypatch):
    """A rule outside this run's set is debt nobody looked at - pruning must not drop it."""
    m = _with_stub(monkeypatch)
    try:
        project, bl = _project_with_stale_entry(tmp_path)

        res = m.baseline_prune(
            [str(project)], ignore=[*_NO_PAIR, "whitespace/trailing"],
        )

        assert res["stale"] == 0 and res["not_checked"] == 2 and res["written"] is False
        data = json.loads(bl.read_text(encoding="utf-8"))
        assert "acme/Проба/Ушедший.xbsl" in data["files"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_baseline_prune_says_when_there_is_no_baseline(tmp_path, monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        f = tmp_path / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")

        res = m.baseline_prune([str(f)], ignore=_NO_PAIR)

        assert "error" in res and "--write-baseline" in res["error"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_can_be_asked_for_the_frozen_findings(tmp_path, monkeypatch):
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        f = project / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")
        cli.main(["--write-baseline", str(tmp_path / ".xbsllint-baseline"),
                  "--ignore", _NO_PAIR[0], str(f)])

        res = m.lint_paths([str(f)], ignore=_NO_PAIR, no_baseline=True)

        assert any(d["rule"] == "whitespace/trailing" for d in res["diagnostics"])
        assert "baselined" not in res["summary"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_takes_a_named_baseline(tmp_path, monkeypatch):
    """An explicit path wins over discovery - the same order the CLI keeps."""
    m = _with_stub(monkeypatch)
    try:
        f = tmp_path / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")
        named = tmp_path / "своё.json"
        cli.main(["--write-baseline", str(named), "--ignore", _NO_PAIR[0], str(f)])

        res = m.lint_paths([str(f)], ignore=_NO_PAIR, baseline=str(named))

        assert res["diagnostics"] == []
        assert res["summary"]["baseline"] == str(named)
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_unknown_argument_is_rejected_not_ignored():
    """A guessed parameter name must fail loudly (the real FastMCP models, if installed)."""
    pytest.importorskip("mcp.server.fastmcp")
    ValidationError = pytest.importorskip("pydantic").ValidationError
    sys.modules.pop("xbsl.mcp_server", None)
    m = importlib.import_module("xbsl.mcp_server")
    tools = {t.name: t for t in m.mcp._tool_manager.list_tools()}
    model = tools["lint_paths"].fn_metadata.arg_model
    assert model.model_validate({"paths": [], "select": ["code/blocks"]})
    with pytest.raises(ValidationError) as exc:
        model.model_validate({"paths": [], "rules": ["code/blocks"]})
    assert "rules" in str(exc.value)
    sys.modules.pop("xbsl.mcp_server", None)


# -- compatibility with both mcp majors ----------------------------------------


class _FakeMcpServer(_FakeMCP):
    """A stand-in of the mcp 2.x shape: the class takes a version, 1.x had no such parameter."""

    def __init__(self, name, version=None):
        super().__init__(name)
        self.version = version


def _load_copy(monkeypatch, *, mcpserver, fastmcp):
    """A private copy of xbsl.mcp_server loaded with the homes of the class substituted.

    The two majors cannot be installed side by side, so the branch that is not the installed
    one is proven by substitution: the modules the compatibility import reaches for are put
    into sys.modules and the file is executed again. None as the value is how a module is made
    unimportable - that is what proves a missing home.
    """
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.mcpserver", mcpserver)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fastmcp)
    sys.modules.pop("xbsl.mcp_server", None)
    module = importlib.import_module("xbsl.mcp_server")
    sys.modules.pop("xbsl.mcp_server", None)
    return module


def _home(name, klass):
    home = types.ModuleType(name)
    setattr(home, name.rsplit(".", 1)[-1] == "mcpserver" and "MCPServer" or "FastMCP", klass)
    return home


def test_the_new_home_of_the_server_class_wins(monkeypatch):
    """mcp 2.x renamed FastMCP to MCPServer and moved it; that one is preferred."""
    module = _load_copy(
        monkeypatch,
        mcpserver=_home("mcp.server.mcpserver", _FakeMcpServer),
        fastmcp=_home("mcp.server.fastmcp", _FakeMCP),
    )
    assert module.McpServer is _FakeMcpServer


def test_the_old_home_is_the_fallback(monkeypatch):
    """No mcp.server.mcpserver means mcp 1.x, and the class lives in fastmcp."""
    module = _load_copy(
        monkeypatch, mcpserver=None, fastmcp=_home("mcp.server.fastmcp", _FakeMCP)
    )
    assert module.McpServer is _FakeMCP


def test_the_version_goes_only_to_a_class_that_takes_one(monkeypatch):
    """The version parameter is 2.x only: without it serverInfo comes out empty there, and a
    1.x class cannot be given one - it does not accept it."""
    from xbsl import __version__

    new = _load_copy(
        monkeypatch,
        mcpserver=_home("mcp.server.mcpserver", _FakeMcpServer),
        fastmcp=_home("mcp.server.fastmcp", _FakeMCP),
    )
    assert new.mcp.version == __version__
    old = _load_copy(
        monkeypatch, mcpserver=None, fastmcp=_home("mcp.server.fastmcp", _FakeMCP)
    )
    assert not hasattr(old.mcp, "version")


def test_without_either_home_the_message_names_the_extra(monkeypatch):
    """Neither of the two - the extra is not installed, and the message says exactly that."""
    with pytest.raises(SystemExit, match=r"xbsl\[mcp\]"):
        _load_copy(monkeypatch, mcpserver=None, fastmcp=None)


def test_lint_paths_resolves_relative_paths_against_the_callers_root(tmp_path, monkeypatch):
    """A session in a git worktree names files relative to ITS checkout, while the server's
    working directory is wherever the client started it: without `root` the relative path
    named nothing (or the other checkout) and the answer looked clean. With `root` the paths
    resolve against the caller's tree, the findings carry absolute paths and the summary
    names the root they were counted from - as the meta_* tools do.
    """
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        (project / "Ч.xbsl").write_text(_TRAILING, encoding="utf-8")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        blind = m.lint_paths(["acme/Проба/Ч.xbsl"], ignore=_NO_PAIR)
        res = m.lint_paths(["acme/Проба/Ч.xbsl"], ignore=_NO_PAIR, root=str(tmp_path))

        assert blind["diagnostics"] == []
        assert len(res["diagnostics"]) == 1
        assert Path(res["diagnostics"][0]["path"]) == project / "Ч.xbsl"
        assert res["summary"]["root"] == str(tmp_path)
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_resolves_a_relative_baseline_against_the_root(tmp_path, monkeypatch):
    """The named baseline is a path of the caller's tree as well."""
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        f = project / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")
        cli.main(["--write-baseline", str(tmp_path / "frozen.baseline"),
                  "--ignore", _NO_PAIR[0], str(f)])
        monkeypatch.chdir(tmp_path / "acme")

        res = m.lint_paths(["acme/Проба/Ч.xbsl"], ignore=_NO_PAIR,
                           baseline="frozen.baseline", root=str(tmp_path))

        assert res["diagnostics"] == []
        assert res["summary"]["baselined"] == 1
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


_YO_FORM = (
    "ВидЭлемента: КомпонентИнтерфейса\n"
    "Ид: aaaaaaaa-1111-2222-3333-444444444444\n"
    "Имя: Форма\nТип: Форма\nЗаголовок: Показать удалённые\n"
)


def test_lint_paths_checks_with_the_rule_set_of_the_ci_job(tmp_path, monkeypatch):
    """A preflight has to judge what the job judges - that is what `as_ci` reads it for.

    The project turns a rule on in its pipeline; an agent that lints without it reports
    clean, and the merge request fails on the same tree an hour later.
    """
    from xbsl.engine import SEVERITY_OVERRIDES

    off_by_default = "typography/yo-in-text"
    if off_by_default in SEVERITY_OVERRIDES:  # pragma: no cover - an installed plugin decides
        pytest.skip("правило включено установленным плагином – не видно, что по умолчанию оно выключено")
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "project"
        project.mkdir()
        (project / "Форма.yaml").write_text(_YO_FORM, encoding="utf-8")
        (tmp_path / ".gitlab-ci.yml").write_text(
            f"xbsl-lint:\n  script:\n    - xbsl project --enable {off_by_default}\n",
            encoding="utf-8",
        )

        plain = m.lint_paths([str(project)])
        as_ci = m.lint_paths([str(project)], as_ci=True)

        assert not any(d["rule"] == off_by_default for d in plain["diagnostics"])
        assert any(d["rule"] == off_by_default for d in as_ci["diagnostics"])
        assert as_ci["summary"]["as_ci"]["job"] == "xbsl-lint"
        assert as_ci["summary"]["as_ci"]["file"] == str(tmp_path / ".gitlab-ci.yml")
        assert "as_ci" not in plain["summary"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_can_be_told_which_ci_job_to_judge_by(tmp_path, monkeypatch):
    """A pipeline that checks a second tree runs the linter twice, by two different sets."""
    from xbsl.engine import SEVERITY_OVERRIDES

    off_by_default = "typography/yo-in-text"
    if off_by_default in SEVERITY_OVERRIDES:  # pragma: no cover - an installed plugin decides
        pytest.skip("правило включено установленным плагином – не видно, что по умолчанию оно выключено")
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "project"
        project.mkdir()
        (project / "Форма.yaml").write_text(_YO_FORM, encoding="utf-8")
        (tmp_path / ".gitlab-ci.yml").write_text(
            "xbsl-lint:\n  script:\n    - xbsl project\n"
            f"English to S3:\n  script:\n    - xbsl project --enable {off_by_default}\n",
            encoding="utf-8",
        )

        first = m.lint_paths([str(project)], as_ci=True)
        named = m.lint_paths([str(project)], as_ci_job="english")

        assert not any(d["rule"] == off_by_default for d in first["diagnostics"])
        assert first["summary"]["as_ci"]["jobs"] == ["English to S3"]
        assert any(d["rule"] == off_by_default for d in named["diagnostics"])
        assert named["summary"]["as_ci"]["job"] == "English to S3"
        assert named["summary"]["as_ci"]["jobs"] == ["xbsl-lint"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_says_why_it_cannot_check_as_the_ci_job_does(tmp_path, monkeypatch):
    """No pipeline file - an explicit error, never a quieter verdict from a narrower set."""
    m = _with_stub(monkeypatch)
    try:
        answer = m.lint_paths([str(tmp_path)], as_ci=True)
        assert ".gitlab-ci.yml" in answer["error"]
        assert "diagnostics" not in answer
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_can_add_a_rule_that_is_off_by_default(tmp_path, monkeypatch):
    """`select` answers with one rule alone; `enable` adds it on top of the defaults - the
    way a project asks for its translation gaps without losing everything else."""
    from xbsl.engine import SEVERITY_OVERRIDES

    off_by_default = "typography/yo-in-text"
    if off_by_default in SEVERITY_OVERRIDES:  # pragma: no cover - an installed plugin decides
        pytest.skip("правило включено установленным плагином – не видно, что по умолчанию оно выключено")
    m = _with_stub(monkeypatch)
    try:
        f = tmp_path / "Форма.yaml"
        f.write_text(
            "ВидЭлемента: КомпонентИнтерфейса\n"
            "Ид: aaaaaaaa-1111-2222-3333-444444444444\n"
            "Имя: Форма\nТип: Форма\nЗаголовок: Показать удалённые\n",
            encoding="utf-8",
        )

        default = m.lint_paths([str(f)])
        added = m.lint_paths([str(f)], enable=[off_by_default])

        assert not any(d["rule"] == off_by_default for d in default["diagnostics"])
        assert any(d["rule"] == off_by_default for d in added["diagnostics"])
        assert len(added["diagnostics"]) > len(default["diagnostics"])
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_over_a_few_files_judges_their_entries_alone(tmp_path, monkeypatch):
    """The entries of files the request did not name are not stale - nobody looked at them.

    One server, one baseline, one minute apart: a request for two files answered
    `baselined: 0, baseline_stale: 76`, a request for the project `baselined: 74,
    baseline_stale: 4`. The whole baseline was being weighed against a partial run.
    """
    m = _with_stub(monkeypatch)
    try:
        project = tmp_path / "acme" / "Проба"
        project.mkdir(parents=True)
        first = project / "А.xbsl"
        second = project / "Б.xbsl"
        first.write_text(_TRAILING, encoding="utf-8")
        second.write_text(_TRAILING, encoding="utf-8")
        cli.main(["--write-baseline", str(tmp_path / ".xbsllint-baseline"),
                  "--ignore", _NO_PAIR[0], str(first), str(second)])

        part = m.lint_paths([str(first)], ignore=_NO_PAIR)["summary"]
        whole = m.lint_paths([str(project)], ignore=_NO_PAIR)["summary"]

        assert part["baselined"] == 1
        assert part["baseline_stale"] == 0 and part["baseline_unused"] == 0
        assert part["baseline_not_checked"] == 1 and part["baseline_not_checked_paths"] == 1
        assert whole["baselined"] == 2 and whole["baseline_stale"] == 0
        assert "baseline_not_checked" not in whole
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


def test_lint_paths_names_the_engine_and_the_rule_set_it_judged_by(tmp_path, monkeypatch):
    """Two environments answering differently about one tree must SAY what they ran with."""
    from xbsl import __version__

    m = _with_stub(monkeypatch)
    try:
        f = tmp_path / "Ч.xbsl"
        f.write_text(_TRAILING, encoding="utf-8")

        summary = m.lint_paths([str(f)], ignore=_NO_PAIR)["summary"]

        assert summary["engine"] == __version__
        assert isinstance(summary["plugins"], list)
        rules = summary["rules"]
        assert set(rules) == {"active", "total", "plugin"}
        assert 0 < rules["active"] < rules["total"]  # one rule ignored, some off by default
        assert 0 <= rules["plugin"] <= rules["active"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


@pytest.mark.parametrize("no_baseline", [False, True])
def test_lint_paths_fix_uses_ci_baseline_and_defaults_to_read_only(tmp_path, monkeypatch, no_baseline):
    from xbsl import baseline, engine

    m = _with_stub(monkeypatch)
    source = tmp_path / "Sample.xbsl"
    original = "метод Ф()  \n    знч А = 1  \n;\n"
    source.write_text(original, encoding="utf-8", newline="")
    rule = "whitespace/trailing"
    frozen = tmp_path / "accepted.json"
    baseline.write(frozen, engine.run([source], select={rule})[:1])
    before = frozen.read_bytes()
    (tmp_path / ".gitlab-ci.yml").write_text(
        "lint:\n  script:\n    - xbsl . --select whitespace/trailing --baseline accepted.json\n",
        encoding="utf-8",
    )
    try:
        readonly = m.lint_paths([str(source)], as_ci=True)
        assert len(readonly["diagnostics"]) == 1
        assert source.read_text(encoding="utf-8") == original
        result = m.lint_paths([str(source)], as_ci=True, fix=True, no_baseline=no_baseline)
        assert result["diagnostics"] == []
        expected = "метод Ф()\n    знч А = 1\n;\n" if no_baseline else "метод Ф()  \n    знч А = 1\n;\n"
        assert source.read_text(encoding="utf-8") == expected
        assert frozen.read_bytes() == before
        assert result["summary"].get("baselined", 0) == (0 if no_baseline else 1)
        assert result["summary"]["fixed"] == (2 if no_baseline else 1)
        assert result["summary"]["files_changed"] == 1
        assert "as_ci" in result["summary"]
    finally:
        sys.modules.pop("xbsl.mcp_server", None)


@pytest.mark.parametrize("original, expected, rules, accepted_line", [
    ("// first \u2014\n// frozen \u2013\n", "// first -\n// frozen \u2013\n",
     ["typography/em-dash", "typography/en-dash-comment"], 2),
    ("import Alpha\nimport Alpha\nimport Beta\nimport Beta\n",
     "import Alpha\nimport Beta\nimport Beta\n", ["code/duplicate-import"], 4),
    ("Import:\n  - Alpha\n  - Alpha\n  - Beta\n  - Beta\n",
     "Import:\n  - Alpha\n  - Beta\n  - Beta\n", ["yaml/duplicate-import"], 5),
])
def test_mcp_fix_reports_the_original_accepted_occurrences(tmp_path, monkeypatch, original, expected, rules, accepted_line):
    from xbsl import baseline, engine

    m = _with_stub(monkeypatch)
    source = tmp_path / ("Sample.yaml" if rules[0].startswith("yaml/") else "Sample.xbsl")
    source.write_text(original, encoding="utf-8", newline="")
    frozen = tmp_path / "accepted.json"
    findings = engine.run([source], select=set(rules))
    accepted = next(d for d in findings if d.line == accepted_line)
    baseline.save(frozen, {"files": {source.name: {accepted.rule_id: {accepted.message: 1}}}})
    before = frozen.read_bytes()
    try:
        result = m.lint_paths([str(source)], select=rules, baseline=str(frozen), fix=True)
        assert source.read_text(encoding="utf-8") == expected
        assert frozen.read_bytes() == before
        assert result["diagnostics"] == []
        assert result["summary"]["baselined"] == 1
        assert result["summary"]["baseline_stale"] == 0
        later = m.lint_paths([str(source)], select=rules, baseline=str(frozen))
        assert later["diagnostics"] == []
        assert later["summary"]["baselined"] == 1
        assert later["summary"]["baseline_stale"] == 0
        assert frozen.read_bytes() == before
    finally:
        sys.modules.pop("xbsl.mcp_server", None)
