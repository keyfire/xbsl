"""The compact answer of `lint_paths`: a short list or counts, errors whole, `as_ci` as one line.

The full summary counts findings by rule, file and severity. Compact mode always omits the
per-file map and keeps complete error-level records; the finding list itself survives as
one line each ("path:line rule - message") up to COMPACT_FINDINGS_LIMIT, and only past it
falls back to counts plus a hint on how to read the rest. `as_ci`, when present, narrows to
its own `flags` sentence.
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
    assert set(compact) == {"summary", "errors", "findings"}
    assert compact["summary"] == {k: v for k, v in full["summary"].items() if k != "by_file"}
    assert compact["errors"] == [d for d in full["diagnostics"] if d["severity"] == "error"]
    assert compact["errors"][0]["message"] == "m"
    # report() sorts by (path, line, col, rule) - line 1 before line 3, same as "diagnostics".
    assert compact["findings"] == [
        "A.xbsl:1 whitespace/trailing – m", "A.xbsl:3 code/brackets – m",
    ]
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
    assert compact["summary"] == {k: v for k, v in full["summary"].items() if k != "by_file"}
    assert full["summary"]["errors"] >= 1 and full["summary"]["warnings"] >= 1
    errors = [d for d in full["diagnostics"] if d["severity"] == "error"]
    assert compact["errors"] == errors  # whole records: rule, position and message
    assert all({"rule", "line", "col", "message"} <= set(d) for d in compact["errors"])

    counts = compact["summary"]
    assert sum(counts["by_rule"].values()) == full["summary"]["diagnostics"]
    assert "by_file" not in counts
    assert set(full["summary"]["by_file"]) == {d["path"] for d in full["diagnostics"]}
    assert all(Path(p).is_absolute() for p in full["summary"]["by_file"])
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

    assert set(answer) == {"summary", "errors", "findings"}
    # One job in the file: the sentence already names it, so the key itself is left out.
    assert set(answer["summary"]["as_ci"]) == {"enabled", "adopted", "flags"}
    assert "xbsl-lint" in answer["summary"]["as_ci"]["flags"]
    assert answer["summary"]["diagnostics"] == sum(answer["summary"]["by_rule"].values())


@pytest.mark.needs_data
def test_compact_as_ci_names_the_job_when_the_file_runs_several(server, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "Первый.xbsl").write_text(_WARNING, encoding="utf-8")
    (tmp_path / ".gitlab-ci.yml").write_text(
        "lint-ru:\n  script:\n    - xbsl project --ignore structure/xbsl-pair\n"
        "lint-en:\n  script:\n    - xbsl project --ignore structure/xbsl-pair --lang en\n",
        encoding="utf-8",
    )

    full = server.lint_paths([str(project)], as_ci=True)
    compact = server.lint_paths([str(project)], as_ci=True, compact=True)

    # The full record keeps everything, compact only the sentence plus the job it names.
    assert set(full["summary"]["as_ci"]) >= {
        "file", "job", "select", "ignore", "enable", "baseline", "flags", "jobs", "hint",
    }
    assert full["summary"]["as_ci"]["jobs"] == ["lint-en"]
    assert set(compact["summary"]["as_ci"]) == {"enabled", "adopted", "flags", "job"}
    assert compact["summary"]["as_ci"]["job"] == "lint-ru"


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
    assert answer["summary"]["by_rule"] == {} and "by_file" not in answer["summary"]


def test_compact_omits_file_map_without_mutating_full_report():
    full = report.report([
        _diag(f"File{i}.xbsl", 1, "whitespace/trailing", Severity.WARNING)
        for i in range(50)
    ], 50)
    answer = report.compact(full)
    assert "by_file" not in answer["summary"]
    assert answer["summary"]["warnings"] == 50
    assert answer["summary"]["files"] == 50
    assert len(full["summary"]["by_file"]) == 50
    assert len(full["diagnostics"]) == 50


# --- findings: a short list up to the limit, only counts past it -----------------------


def _diags(n: int) -> list[Diagnostic]:
    return [_diag(f"F{i}.xbsl", i + 1, "whitespace/trailing", Severity.WARNING) for i in range(n)]


def test_compact_findings_is_empty_but_present_with_no_findings():
    answer = report.compact(report.report([], 0))
    assert answer["findings"] == []
    assert "findings_hint" not in answer


def test_compact_lists_one_finding_as_one_line():
    answer = report.compact(report.report(_diags(1), 1))
    assert answer["findings"] == ["F0.xbsl:1 whitespace/trailing – m"]
    assert "findings_hint" not in answer


def test_compact_lists_findings_at_the_limit_inclusive():
    """COMPACT_FINDINGS_LIMIT itself still lists - the count and the limit are equal."""
    answer = report.compact(report.report(_diags(report.COMPACT_FINDINGS_LIMIT), 10))
    assert len(answer["findings"]) == report.COMPACT_FINDINGS_LIMIT
    assert "findings_hint" not in answer


def test_compact_falls_back_to_counts_one_past_the_limit():
    answer = report.compact(report.report(_diags(report.COMPACT_FINDINGS_LIMIT + 1), 11))
    assert "findings" not in answer
    assert isinstance(answer["findings_hint"], str) and answer["findings_hint"]
    # The count is still readable from the summary, as before.
    assert answer["summary"]["diagnostics"] == report.COMPACT_FINDINGS_LIMIT + 1


def test_full_report_is_unaffected_by_the_compact_changes():
    """Regression: report()/summary()/breakdown() keep their shape - only compact() changed."""
    diags = _diags(15) + [_diag("E.xbsl", 1, "code/brackets", Severity.ERROR)]
    payload = report.report(diags, 16)
    assert set(payload) == {"diagnostics", "summary"}
    assert set(payload["summary"]) == {
        "files", "diagnostics", "errors", "warnings", "by_rule", "by_file", "by_severity",
    }
    assert len(payload["diagnostics"]) == 16
    assert "findings" not in payload and "findings_hint" not in payload
