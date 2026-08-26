"""MCP adapter check via a stub FastMCP (does not require mcp to be installed)."""

import importlib
import json
import sys
import types

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


def test_lint_paths_can_add_a_rule_that_is_off_by_default(tmp_path, monkeypatch):
    """`select` answers with one rule alone; `enable` adds it on top of the defaults - the
    way a project asks for its translation gaps without losing everything else."""
    from xbsl.engine import SEVERITY_OVERRIDES

    off_by_default = "typography/yo-in-text"
    if off_by_default in SEVERITY_OVERRIDES:  # pragma: no cover - an installed plugin decides
        pytest.skip("правило включено установленным плагином – публичный дефолт не виден")
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
