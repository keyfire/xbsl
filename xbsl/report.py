"""The machine-readable report shape, shared by the CLI (--format json), the MCP server and editors.

One contract for structured output - a list of diagnostics plus a summary - so that the CLI and the
MCP adapter cannot drift apart. Editors (the VS Code extension) consume the same JSON. The summary
carries the counts by rule, by file and by severity (breakdown()); rule_table() turns them into the
rows of the text `--summary` (rundiff.py). compact() omits the per-file map
and keeps the error-level findings whole; up to COMPACT_FINDINGS_LIMIT it also lists the findings
themselves, one line each, and past that limit only says how many there are - what a reader wants
when the list is too long to carry. fit() holds a compact answer to COMPACT_ANSWER_LIMIT
characters whatever the run found, and names what it cut. A run over several project roots adds
project_record() of each root to its summary, under `projects`.

CI integration lives here too: codeclimate() renders the diagnostics as a GitLab Code Quality
report (a subset of the Code Climate issue format), which GitLab shows as a widget on merge
requests (https://docs.gitlab.com/ee/ci/testing/code_quality.html).
"""

from __future__ import annotations

import hashlib
import json
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


def rule_table(diags: list[Diagnostic]) -> list[tuple[str, int, int]]:
    """The findings by rule as rows of (rule, files, findings) - the table of `--summary`.

    Built on breakdown(): the same count per rule and the same order, the most findings first,
    then by the rule id. It adds what by_rule does not say - how many files the rule reached,
    a file counted once however many findings of that rule it holds.
    """
    files: dict[str, set[str]] = {}
    for d in diags:
        files.setdefault(d.rule_id, set()).add(d.path)
    return [(rule, len(files[rule]), count) for rule, count in breakdown(diags)["by_rule"].items()]


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


def project_record(root: Path | None, diags: list[Diagnostic], n_files: int) -> dict:
    """One project root of a run over several, for `summary.projects`: its own counts.

    A run over several project roots checks each of them on its own; the summary of the run
    counts them all, and this record counts one of them - the files, the findings by rule and
    by severity. The per-file map stays in the summary of the run, whose paths already name
    the root they lie under. `project` is the root folder, None for the sources that lie in
    no project.
    """
    counts = summary(sorted(diags, key=lambda x: x.sort_key()), n_files)
    del counts["by_file"]
    return {"project": str(root) if root is not None else None, **counts}


#: compact() lists findings one line each up to this many; more, and only the count remains.
#: Ten is a screenful either way - fewer and a reader still has to ask again to see anything,
#: more and the "compact" answer is not compact any more. A named constant instead of a bare
#: number in the code below: the docstring here is the one place explaining the choice.
COMPACT_FINDINGS_LIMIT = 10


def compact(payload: dict, *, as_ci_full: bool = False, list_info: bool = False) -> dict:
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

    The info-level findings are counted, not listed: `info_hint` gives their number and
    rules, and `list_info` lists them with the rest. A project keeps a few such findings on
    purpose, and a session of checks got the same lines with every answer - five of them
    cost about two and a half kilobytes a call - while the question was about the errors
    and warnings. They do not count towards the limit either.

    `as_ci`, under `summary` when the caller asked for it, narrows to one line - see
    compact_as_ci; `as_ci_full` keeps the whole record. Every other key of the payload (the
    environment, the baseline record) stays as it was.
    """
    out = dict(payload)
    out["summary"] = compact_summary(payload["summary"], as_ci_full=as_ci_full)
    findings = out.pop("diagnostics", [])
    out["errors"] = [d for d in findings if d["severity"] == "error"]
    info = [] if list_info else [d for d in findings if d["severity"] == "info"]
    if info:
        findings = [d for d in findings if d["severity"] != "info"]
        out["info_hint"] = i18n.t("report.info-hint", count=len(info), rules=_tally(info))
    if len(findings) <= COMPACT_FINDINGS_LIMIT:
        out["findings"] = [_compact_finding(d) for d in findings]
    else:
        out["findings_hint"] = i18n.t(
            "report.findings-hint", count=len(findings), limit=COMPACT_FINDINGS_LIMIT,
        )
    return out


def compact_summary(summary: dict, *, as_ci_full: bool = False) -> dict:
    """The summary of a compact answer: without the per-file map, `as_ci` as one line.

    compact() builds its summary here, and so does the comparison answer of `lint_paths`,
    which carries the changes in place of the findings. The record of each project root
    (`projects`, a run over several of them) keeps its CI job as one line too.
    """
    out = {key: value for key, value in summary.items() if key != "by_file"}
    as_ci = out.get("as_ci")
    if as_ci is not None and not as_ci_full:
        out["as_ci"] = compact_as_ci(as_ci)
    projects = out.get("projects")
    if projects and not as_ci_full:
        out["projects"] = [
            {**entry, "as_ci": compact_as_ci(entry["as_ci"])}
            if entry.get("as_ci") is not None else entry
            for entry in projects
        ]
    return out


#: The most characters a compact answer takes, counted as its JSON text. The lists of a
#: compact answer are held short by count (COMPACT_FINDINGS_LIMIT), but a few of them grow with
#: the run: the full records of the errors, the stale entries of a baseline, the records of the
#: project roots. Two worktrees of one project checked as one project once answered with 467
#: thousand characters under `compact` - hundreds of errors in full, when the question was
#: whether the trees were clean. Twelve thousand characters hold the counts of any run and a
#: screenful of records, and stay well inside what a client takes from one tool call.
COMPACT_ANSWER_LIMIT = 12_000


def _json_size(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _cut_places(answer: dict) -> list[tuple[str, dict, str]]:
    """The lists fit() may cut, in the order it cuts them: (name, container, key).

    What the reader can do without goes first: the stale and the reworded entries of a
    baseline (their counts stay), then the findings one line each, the error records, the
    counts by rule of each project root, the project roots themselves and the counts by rule
    of the run. The counts of the summary are never cut - they are what the answer is for.
    """
    summary = answer["summary"]
    projects = summary.get("projects") or []
    entries = ("baseline_stale_entries", "baseline_reworded_entries")
    places = [(f"summary.{key}", summary, key) for key in entries]
    places += [(f"summary.projects[{index}].{key}", entry, key)
               for index, entry in enumerate(projects) for key in entries]
    places += [("findings", answer, "findings"), ("errors", answer, "errors")]
    places += [(f"summary.projects[{index}].by_rule", entry, "by_rule")
               for index, entry in enumerate(projects)]
    places += [("summary.projects", summary, "projects"), ("summary.by_rule", summary, "by_rule")]
    return [(name, container, key) for name, container, key in places
            if isinstance(container.get(key), (list, dict)) and container[key]]


class _Cut:
    """One list of an answer being cut: keeps its first items and says how many."""

    def __init__(self, answer: dict, cuts: dict, limit: int, name: str, container: dict,
                 key: str) -> None:
        self.answer, self.cuts, self.limit = answer, cuts, limit
        self.name, self.container, self.key = name, container, key
        whole = container[key]
        self.as_dict = isinstance(whole, dict)
        self.items = list(whole.items()) if self.as_dict else list(whole)

    def keep(self, count: int) -> int:
        """Keep the first `count` items, name the cut, and measure the answer that makes."""
        kept = self.items[:count]
        self.container[self.key] = dict(kept) if self.as_dict else kept
        self.cuts[self.name] = {"shown": count, "total": len(self.items)}
        self.answer["truncated"] = dict(self.cuts)
        self.answer["truncated_hint"] = i18n.t("report.truncated", limit=self.limit)
        return _json_size(self.answer)


def fit(answer: dict, limit: int = COMPACT_ANSWER_LIMIT) -> dict:
    """A compact answer held to `limit` characters of JSON, every cut said out loud.

    An answer that fits comes back as it is. Otherwise the lists that grow with the run are
    cut from their end, one after another in the order of _cut_places, each to as many items
    as still fit, until the answer does: `truncated` names every list cut with {shown,
    total}, and `truncated_hint` says how to read the whole answer - a call without
    `compact`, narrower paths or rules, or the CLI writing the json report to a file. The
    parts that do not grow with the findings - the counts, the CI record, the hints - stay
    whole. The answer given is not changed: the containers on the way to a cut are copies.
    """
    if _json_size(answer) <= limit:
        return answer
    out = dict(answer)
    out["summary"] = dict(answer["summary"])
    if out["summary"].get("projects"):
        out["summary"]["projects"] = [dict(entry) for entry in out["summary"]["projects"]]
    cuts: dict[str, dict[str, int]] = {}
    for name, container, key in _cut_places(out):
        cut = _Cut(out, cuts, limit, name, container, key)
        if cut.keep(0) > limit:
            continue  # even without this list the answer is over: the next one goes too
        # With the whole list the answer is over the limit, so the count that fits is below
        # its length: the largest such count, by halving.
        low, high = 0, len(cut.items) - 1
        while low < high:
            middle = (low + high + 1) // 2
            if cut.keep(middle) <= limit:
                low = middle
            else:
                high = middle - 1
        cut.keep(low)
        break
    return out


def short(diagnostics: list[Diagnostic], files: int) -> dict:
    """The lint a writing tool answers with: counts, and the findings one line each.

    A metadata tool lints what it has just written and ships the result in its answer. The
    whole report there cost about twenty lines per call even with nothing found, and a run of
    small edits repeated them call after call. Clean files answer with two numbers; findings
    come one line each up to COMPACT_FINDINGS_LIMIT and as a count past it. The whole report
    of the same files is lint_paths on them.
    """
    payload = report(diagnostics, files)
    summary = payload["summary"]
    out = {"files": summary["files"], "diagnostics": summary["diagnostics"]}
    if not summary["diagnostics"]:
        return out
    out["errors"] = summary["errors"]
    out["warnings"] = summary["warnings"]
    findings = payload["diagnostics"]
    if len(findings) <= COMPACT_FINDINGS_LIMIT:
        out["findings"] = [_compact_finding(d) for d in findings]
    else:
        out["findings_hint"] = i18n.t(
            "report.written-hint", count=len(findings), limit=COMPACT_FINDINGS_LIMIT,
        )
    return out


#: _tally() names this many rules; the rest of them it counts.
_TALLY_RULES = 3


def _tally(findings: list[dict]) -> str:
    """The rules of the findings with their counts, the largest first: "rule ×5, rule ×1"."""
    counts = Counter(d["rule"] for d in findings).most_common()
    named = ", ".join(f"{rule} ×{count}" for rule, count in counts[:_TALLY_RULES])
    rest = len(counts) - _TALLY_RULES
    return named if rest <= 0 else named + ", " + i18n.t("report.more-rules", count=rest)


def _compact_finding(d: dict) -> str:
    """One line of a compact finding list: "path:line rule - message" (en dash - a message
    a reader sees, not a code comment)."""
    return f"{d['path']}:{d['line']} {d['rule']} – {d['message']}"


def compact_as_ci(job: dict) -> dict:
    """`as_ci` (cijob.CiLint.as_dict()) as one line: `{"adopted": True, "brief": ...}`.

    The same record comes with every call of a session, and the full `flags` sentence with an
    absolute path and every rule of a long `--enable` list cost about a thousand characters
    each time. The line keeps the file relative to the checkout, the job, the flags with a
    long list counted, the jobs left unchosen and the includes nobody read - the last two are
    the reader's blind spots, and an answer without them read as if the whole pipeline had
    been taken. The raw lists and the absolute paths stay in the full record.

    A refused adoption (`cijob.refused()`, `adopted: False`) has no line to build and is
    small already - it is returned unchanged.
    """
    if not job.get("adopted"):
        return job
    from xbsl import cijob

    return {"adopted": True, "brief": cijob.brief(job)}


# --- GitLab Code Quality (Code Climate issues) ----------------------------------------

# GitLab accepts info, minor, major, critical, blocker. Linter errors are broken conventions,
# not broken builds - major, not critical/blocker.
_CODECLIMATE_SEVERITY = {
    "error": "major",
    "warning": "minor",
    "info": "info",
}


def _relative_posix(path: str, root: Path) -> str:
    """The path relative to the run root, with forward slashes.

    GitLab matches location.path against the paths of the merge request diff, which are
    repository-relative POSIX paths without a './' prefix. A path outside the root cannot be
    expressed that way - it is kept whole (POSIX-normalized), which at worst loses the widget
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
    message - stable across runs; exact duplicates get an occurrence counter so every issue
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
