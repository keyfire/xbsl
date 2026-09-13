"""The compact answer of `lint_paths`: counts instead of the list of findings, errors whole.

The report's summary counts the findings by rule, by file and by severity in every mode; the
compact mode of the MCP tool drops the list itself and keeps the error-level records alone.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

from xbsl import report
from xbsl.diagnostics import Diagnostic, Severity


def _diag(path, line, rule, severity):
    return Diagnostic(path=path, line=line, col=1, rule_id=rule, severity=severity, message="m")


def test_breakdown_counts_by_rule_file_and_severity_largest_first():
    diags = [
        _diag("B.xbsl", 1, "whitespace/trailing", Severity.WARNING),
        _diag("A.xbsl", 2, "whitespace/trailing", Severity.WARNING),
        _diag("A.xbsl", 3, "code/brackets", Severity.ERROR),
        _diag("A.xbsl", 4, "typography/em-dash", Severity.INFO),
    ]
    counts = report.breakdown(diags)
    assert list(counts["by_rule"].items()) == [
        ("whitespace/trailing", 2), ("code/brackets", 1), ("typography/em-dash", 1),
    ]
    assert list(counts["by_file"].items()) == [("A.xbsl", 3), ("B.xbsl", 1)]
    assert counts["by_severity"] == {"error": 1, "warning": 2, "info": 1}


def test_breakdown_names_every_severity_even_at_zero():
    assert report.breakdown([])["by_severity"] == {"error": 0, "warning": 0, "info": 0}


def test_compact_drops_the_list_and_keeps_the_errors_whole():
    diags = [
        _diag("A.xbsl", 3, "code/brackets", Severity.ERROR),
        _diag("A.xbsl", 1, "whitespace/trailing", Severity.WARNING),
    ]
    full = report.report(diags, 1)
    full["summary"]["baselined"] = 4  # what a caller adds after report() has to survive
    compact = report.compact(full)
    assert set(compact) == {"summary", "errors"}
    assert compact["summary"] == full["summary"]
    assert compact["errors"] == [d for d in full["diagnostics"] if d["severity"] == "error"]
    assert compact["errors"][0]["message"] == "m"
    assert "diagnostics" in full  # the source payload is left as it was


# -- the MCP tool -----------------------------------------------------------------------


class _StubMCP:
    """The FastMCP stand-in of tests/test_mcp.py: tools register as plain functions."""

    def __init__(self, name, version=None):
        self.name = name
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


@pytest.fixture
def server(monkeypatch):
    fast = types.ModuleType("mcp.server.fastmcp")
    fast.FastMCP = _StubMCP
    monkeypatch.setitem(sys.modules, "mcp", types.ModuleType("mcp"))
    monkeypatch.setitem(sys.modules, "mcp.server", types.ModuleType("mcp.server"))
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fast)
    sys.modules.pop("xbsl.mcp_server", None)
    yield importlib.import_module("xbsl.mcp_server")
    sys.modules.pop("xbsl.mcp_server", None)


_NO_PAIR = ["structure/xbsl-pair"]  # a temporary .xbsl has no paired yaml
_WARNING = "метод Ф(): Число\n    возврат 1  \n;\n"  # trailing whitespace on line 2
_ERROR = "метод Г()\n    Ф((1)\n;\n"  # an unclosed bracket


@pytest.mark.needs_data
def test_compact_answer_carries_the_counts_and_the_errors_only(server, tmp_path):
    (tmp_path / "Первый.xbsl").write_text(_WARNING, encoding="utf-8")
    (tmp_path / "Второй.xbsl").write_text(_ERROR, encoding="utf-8")

    full = server.lint_paths([str(tmp_path)], ignore=_NO_PAIR)
    compact = server.lint_paths([str(tmp_path)], ignore=_NO_PAIR, compact=True)

    assert "diagnostics" not in compact
    assert compact["summary"] == full["summary"]
    assert full["summary"]["errors"] >= 1 and full["summary"]["warnings"] >= 1
    errors = [d for d in full["diagnostics"] if d["severity"] == "error"]
    assert compact["errors"] == errors  # whole records: rule, position and message
    assert all({"rule", "line", "col", "message"} <= set(d) for d in compact["errors"])

    counts = compact["summary"]
    assert sum(counts["by_rule"].values()) == full["summary"]["diagnostics"]
    assert set(counts["by_file"]) == {d["path"] for d in full["diagnostics"]}
    assert all(Path(p).is_absolute() for p in counts["by_file"])
    assert counts["by_severity"]["error"] == full["summary"]["errors"]
    assert counts["by_severity"]["warning"] == full["summary"]["warnings"]


@pytest.mark.needs_data
def test_compact_answer_keeps_the_record_of_the_ci_job(server, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "Первый.xbsl").write_text(_WARNING, encoding="utf-8")
    (tmp_path / ".gitlab-ci.yml").write_text(
        "xbsl-lint:\n  script:\n    - xbsl project --ignore structure/xbsl-pair\n",
        encoding="utf-8",
    )

    answer = server.lint_paths([str(project)], as_ci=True, compact=True)

    assert set(answer) == {"summary", "errors"}
    assert answer["summary"]["as_ci"]["job"] == "xbsl-lint"
    assert answer["summary"]["diagnostics"] == sum(answer["summary"]["by_rule"].values())


@pytest.mark.needs_data
def test_compact_answer_keeps_the_baseline_record(server, tmp_path):
    """The counts describe what is reported: a baselined finding is neither listed nor counted."""
    from xbsl import cli

    project = tmp_path / "acme" / "Проба"
    project.mkdir(parents=True)
    f = project / "Первый.xbsl"
    f.write_text(_WARNING, encoding="utf-8")
    cli.main(["--write-baseline", str(tmp_path / ".xbsllint-baseline"),
              "--ignore", _NO_PAIR[0], str(f)])

    answer = server.lint_paths([str(f)], ignore=_NO_PAIR, compact=True)

    assert answer["summary"]["baselined"] == 1
    assert answer["summary"]["baseline"].endswith(".xbsllint-baseline")
    assert answer["summary"]["diagnostics"] == 0 and answer["errors"] == []
    assert answer["summary"]["by_rule"] == {} and answer["summary"]["by_file"] == {}
