"""MCP adapter check via a stub FastMCP (does not require mcp to be installed)."""

import importlib
import sys
import types

import pytest


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
