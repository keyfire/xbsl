"""Shape of the machine-readable report (report.report) - no dependency on the Element data."""

import json

from xbsl import report
from xbsl.diagnostics import Diagnostic, Severity, TextEdit


def _d(line, col, rule, sev):
    return Diagnostic(path="X.xbsl", line=line, col=col, rule_id=rule, severity=sev, message="m")


def test_report_shape_counts_and_order():
    diags = [
        _d(3, 1, "code/brackets", Severity.ERROR),
        _d(1, 5, "typography/curly-quotes", Severity.WARNING),
        _d(1, 2, "whitespace/trailing", Severity.WARNING),
    ]
    payload = report.report(diags, 1)

    assert set(payload) == {"diagnostics", "summary"}
    assert payload["summary"] == {"files": 1, "diagnostics": 3, "errors": 1, "warnings": 2}

    # Sorted by (path, line, col, rule)
    positions = [(d["line"], d["col"]) for d in payload["diagnostics"]]
    assert positions == sorted(positions)

    # Fields of a single finding
    first = payload["diagnostics"][0]
    assert set(first) == {"path", "line", "col", "rule", "severity", "message"}
    assert first["severity"] in {"error", "warning", "info"}

    # Serializes to JSON without loss
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload


def test_report_empty():
    payload = report.report([], 0)
    assert payload == {
        "diagnostics": [],
        "summary": {"files": 0, "diagnostics": 0, "errors": 0, "warnings": 0},
    }


def test_fix_span_emitted_when_present():
    d = Diagnostic(
        path="X.xbsl", line=2, col=14, rule_id="whitespace/trailing",
        severity=Severity.WARNING, message="m", fix=TextEdit(20, 23, ""),
    )
    payload = report.report([d], 1)
    first = payload["diagnostics"][0]
    assert first["fix"] == {"start": 20, "end": 23, "newText": ""}
    # without a fix the key is absent
    plain = report.report([_d(1, 1, "code/unused-loop-var", Severity.WARNING)], 1)
    assert "fix" not in plain["diagnostics"][0]
