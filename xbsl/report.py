"""The machine-readable report shape, shared by the CLI (--format json), the MCP server and editors.

One contract for structured output – a list of diagnostics plus a summary – so that the CLI and the
MCP adapter cannot drift apart. Editors (the VS Code extension) consume the same JSON. The summary
carries the counts by rule, by file and by severity (breakdown()). compact() omits the per-file map
and keeps the error-level findings whole; up to COMPACT_FINDINGS_LIMIT it also lists the findings
themselves, one line each, and past that limit only says how many there are – what a reader wants
when the list is too long to carry.

CI integration lives here too: codeclimate() renders the diagnostics as a GitLab Code Quality
report (a subset of the Code Climate issue format), which GitLab shows as a widget on merge
requests (https://docs.gitlab.com/ee/ci/testing/code_quality.html).
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

from xbsl import i18n
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


#: compact() lists findings one line each up to this many; more, and only the count remains.
#: Ten is a screenful either way - fewer and a reader still has to ask again to see anything,
#: more and the "compact" answer is not compact any more. A named constant instead of a bare
#: number in the code below: the docstring here is the one place explaining the choice.
COMPACT_FINDINGS_LIMIT = 10


def compact(payload: dict) -> dict:
    """The payload of report() without its per-file map, and its findings held short.

    The summary keeps counts by rule and severity; the unbounded per-file map is available
    in the full report. Up to COMPACT_FINDINGS_LIMIT findings, `findings` lists them one line
    each ("path:line rule - message") - a handful of findings is exactly what "is the tree
    clean" wants to see, and a second call for the plain list buys nothing when the count is
    this low. Past the limit `findings` is left out and `findings_hint` says how many there
    are and how to read them (call again without `compact`, or narrow `paths`/`select`) - the
    text of every finding is what the list costs: several hundred characters each, tens of
    thousands over one project run. The errors alone always keep their full records, under
    `errors`, because an error is what a build fails on and the reader has to see which one.

    `as_ci`, under `summary` when the caller asked for it, narrows the same way: the `flags`
    sentence alone (it already names the file, the job and the adopted rules) plus the job
    name when the file runs the linter more than once - see _compact_as_ci. Every other key
    of the payload (the environment, the baseline record) stays as it was.
    """
    out = dict(payload)
    out["summary"] = {key: value for key, value in payload["summary"].items()
                      if key != "by_file"}
    findings = out.pop("diagnostics", [])
    out["errors"] = [d for d in findings if d["severity"] == "error"]
    if len(findings) <= COMPACT_FINDINGS_LIMIT:
        out["findings"] = [_compact_finding(d) for d in findings]
    else:
        out["findings_hint"] = i18n.t(
            "report.findings-hint", count=len(findings), limit=COMPACT_FINDINGS_LIMIT,
        )
    as_ci = out["summary"].get("as_ci")
    if as_ci is not None:
        out["summary"]["as_ci"] = _compact_as_ci(as_ci)
    return out


def _compact_finding(d: dict) -> str:
    """One line of a compact finding list: "path:line rule - message" (en dash - a message
    a reader sees, not a code comment)."""
    return f"{d['path']}:{d['line']} {d['rule']} – {d['message']}"


def _compact_as_ci(job: dict) -> dict:
    """`as_ci` (cijob.CiLint.as_dict()) narrowed to what `flags` does not already say.

    `flags` is the full sentence ("Rule set as in CI: <file>, job <job> - <select/ignore/
    enable/baseline>"), so the raw lists, the baseline path and the include chain add
    nothing a reader could not already read there. `job` alone survives, and only when the
    file runs the linter in more than one job (`jobs` non-empty) - with a single job the
    sentence is unambiguous about which one it describes.

    What `flags` cannot say survives: the includes nobody fetched (`unread_includes` and
    the `note` line built from them) and the `hint` naming the jobs left unchosen. Those
    are the reader's blind spots, not a longer spelling of the sentence, and an answer that
    dropped them read as if the whole pipeline had been taken - the very thing `cijob.note()`
    exists to prevent. Each is carried only when it says something: a pipeline with one job
    and no unread include keeps the short record it had.

    A refused adoption (`cijob.refused()`, `adopted: False`) has no `flags` to fall back on
    and is small already - it is returned unchanged.
    """
    if not job.get("adopted"):
        return job
    out = {"enabled": job.get("enabled", True), "adopted": True, "flags": job["flags"]}
    if job.get("jobs"):
        out["job"] = job.get("job")
    for key in ("hint", "note", "unread_includes"):
        if job.get(key):
            out[key] = job[key]
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
