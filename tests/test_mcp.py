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
