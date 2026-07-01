"""Проверка MCP-адаптера через подставной FastMCP (не требует установленного mcp)."""

import importlib
import sys
import types


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
    sys.modules.pop("xbsllint.mcp_server", None)

    m = importlib.import_module("xbsllint.mcp_server")
    assert {"lint_paths", "lint_source", "list_rules"}.issubset(m.mcp.tools)

    rules = m.list_rules()
    assert any(r["id"] == "code/blocks" for r in rules)

    res = m.lint_source("М.xbsl", "метод Ф()  \n;\n", select=["whitespace/trailing"])
    assert res["summary"]["diagnostics"] >= 1

    sys.modules.pop("xbsllint.mcp_server", None)
