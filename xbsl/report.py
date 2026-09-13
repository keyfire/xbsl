"""The machine-readable report shape, shared by the CLI (--format json), the MCP server and editors.

One contract for structured output – a list of diagnostics plus a summary – so that the CLI and the
MCP adapter cannot drift apart. Editors (the VS Code extension) consume the same JSON. The summary
carries the counts by rule, by file and by severity (breakdown()), and compact() is the same
payload without the list of findings – what a reader wants when the list is too long to carry.

CI integration lives here too: codeclimate() renders the diagnostics as a GitLab Code Quality
report (a subset of the Code Climate issue format), which GitLab shows as a widget on merge
requests (https://docs.gitlab.com/ee/ci/testing/code_quality.html).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from xbsl.diagnostics import Diagnostic, Severity


def diag_dict(d: Diagnostic) -> dict:
    """One diagnostic as a plain dict. Position is 1-based (line, col), as in the model.

    A mechanically fixable finding also carries `fix`: {start, end, newText}, where start/end
    are 0-based character offsets into the file's decoded text (a UTF-8 buffer as sent to the
    linter). An editor turns it into a Quick Fix; the key is absent when the rule has no span
    fix (including whole-file fixes like whitespace/mixed-newline).
    """
    out = {
        "path": d.path,
        "line": d.line,
        "col": d.col,
        "rule": d.rule_id,
        "severity": d.severity.value,
        "message": d.message,
    }
    if d.fix is not None:
        out["fix"] = {"start": d.fix.start, "end": d.fix.end, "newText": d.fix.new}
    if d.data:
        out["data"] = d.data
    return out


def breakdown(diags: list[Diagnostic]) -> dict:
    """The findings as counts: by rule, by file and by severity.

    What a reader keeps from a run when the findings themselves are too many to carry: which
    rules fire, in which files, and whether an error is among them. Rules and files are ordered
    by their count, the largest first, then by name; the severities always list all three, so a
    zero is a zero and not a missing key. A file is named the way its diagnostics name it (the
    same relative or absolute path).
    """
    by_rule = Counter(d.rule_id for d in diags)
    by_file = Counter(d.path for d in diags)
    by_severity = {level.value: 0 for level in Severity}
    for d in diags:
        by_severity[d.severity.value] += 1
    return {
        "by_rule": dict(sorted(by_rule.items(), key=lambda item: (-item[1], item[0]))),
        "by_file": dict(sorted(by_file.items(), key=lambda item: (-item[1], item[0]))),
        "by_severity": by_severity,
    }


def summary(diags: list[Diagnostic], n_files: int) -> dict:
    """The counts of a run: files, findings, errors and warnings, plus the breakdown."""
    return {
        "files": n_files,
        "diagnostics": len(diags),
        "errors": sum(1 for d in diags if d.severity.value == "error"),
        "warnings": sum(1 for d in diags if d.severity.value == "warning"),
        **breakdown(diags),
    }


def report(diags: list[Diagnostic], n_files: int) -> dict:
    """The full payload: {diagnostics: [...sorted...], summary: {...}}."""
    ordered = sorted(diags, key=lambda x: x.sort_key())
    return {
        "diagnostics": [diag_dict(d) for d in ordered],
        "summary": summary(ordered, n_files),
    }


def compact(payload: dict) -> dict:
    """The payload of report() without its list of findings.

    The summary already counts the findings by rule, by file and by severity, so a reader
    asking "is the tree clean, and what fires where" has the answer without the text of every
    finding - which is what the list costs: several hundred characters each, tens of thousands
    over one project run. The errors alone keep their full records, under `errors`, because an
    error is what a build fails on and the reader has to see which one. Every other key of the
    payload (the environment, the baseline record, the CI job) stays as it was.
    """
    out = dict(payload)
    findings = out.pop("diagnostics", [])
    out["errors"] = [d for d in findings if d["severity"] == "error"]
    return out


# --- GitLab Code Quality (Code Climate issues) ----------------------------------------

# GitLab accepts info, minor, major, critical, blocker. Linter errors are broken conventions,
# not broken builds – major, not critical/blocker.
_CODECLIMATE_SEVERITY = {
    "error": "major",
    "warning": "minor",
    "info": "info",
}


def _relative_posix(path: str, root: Path) -> str:
    """The path relative to the run root, with forward slashes.

    GitLab matches location.path against the paths of the merge request diff, which are
    repository-relative POSIX paths without a './' prefix. A path outside the root cannot be
    expressed that way – it is kept whole (POSIX-normalized), which at worst loses the widget
    link but keeps the report valid.
    """
    p = Path(path)
    try:
        return p.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return p.as_posix()


def codeclimate(diags: list[Diagnostic], base: Path | None = None) -> list[dict]:
    """The diagnostics as a GitLab Code Quality report: a list of Code Climate issues.

    Only the fields GitLab requires: description, check_name, fingerprint, severity,
    location.path, location.lines.begin. The fingerprint is an md5 over path, rule, line and
    message – stable across runs; exact duplicates get an occurrence counter so every issue
    in the report stays unique. `base` is the run root the paths are made relative to
    (default: the current directory).
    """
    root = (base or Path.cwd()).resolve()
    issues: list[dict] = []
    seen: dict[str, int] = {}
    for d in sorted(diags, key=lambda x: x.sort_key()):
        path = _relative_posix(d.path, root)
        identity = f"{path}:{d.rule_id}:{d.line}:{d.message}"
        n = seen.get(identity, 0)
        seen[identity] = n + 1
        if n:
            identity += f":{n}"
        issues.append({
            "description": d.message,
            "check_name": d.rule_id,
            "fingerprint": hashlib.md5(identity.encode("utf-8")).hexdigest(),
            "severity": _CODECLIMATE_SEVERITY.get(d.severity.value, "info"),
            "location": {"path": path, "lines": {"begin": d.line}},
        })
    return issues
