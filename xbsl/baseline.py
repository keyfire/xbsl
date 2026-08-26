"""Baseline: freeze the existing findings so only new code is held to a rule.

The intended flow: enable a rule (or a whole group) over a codebase with legacy debt,
write the current findings once (`--write-baseline`), commit the file, and lint with
`--baseline` from then on – frozen findings are suppressed, anything new surfaces.

A finding's identity is line-independent on purpose: (file path, rule id, message text),
with an allowed COUNT per identity. Moving a line keeps its finding suppressed; a new
violation of the same rule with the same message in the same file exceeds the count and
the extra occurrences (in line order, the last ones) are reported. Paths are stored as
POSIX paths relative to the baseline file's directory, so the file can be committed and
the linter run from any working directory.

An entry's value is either a bare count or `{"count": N, "reason": "..."}` – the reason
records WHY the finding is excluded (a deliberate project decision, not just frozen debt).
Reasons are written by the editor tooling (the VS Code extension's "exclude the finding"
action) or by hand; `--write-baseline` keeps the reasons of the identities that survive
the rewrite.

The message text is part of the identity, so the baseline must be written and checked
under the same output language (--lang / XBSL_LANG); a language switch surfaces
every frozen finding and marks the whole file's entries as unused.

Unused and stale are counted only over the entries whose RULE the run actually had: a rule
left out of the selection (or off by default, or unknown to the installed plugins) produces
no findings by construction, and calling its entries stale would say the debt is paid when
nobody looked. That is what made two environments disagree about one baseline - an MCP
server on an older plugin called 48 entries stale while CI, running the same tree with the
rules enabled, called none. Such entries are reported apart, as not checked, and `--prune-
baseline` never touches them.
"""

from __future__ import annotations

import json
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic

_FORMAT = 1

_MESSAGES = {
    "baseline.missing": {
        "ru": "Файл базлайна не найден: {path}. Создайте его: xbsl ... --write-baseline {path}",
        "en": "Baseline file not found: {path}. Create it: xbsl ... --write-baseline {path}",
    },
    "baseline.invalid": {
        "ru": "Файл базлайна повреждён или неизвестного формата: {path}",
        "en": "The baseline file is corrupt or of an unknown format: {path}",
    },
}
i18n.register(_MESSAGES)


class BaselineError(RuntimeError):
    pass


#: The baseline file a project keeps next to its sources - the same name the VS Code
#: extension writes exclusions into and CI passes explicitly.
DEFAULT_NAME = ".xbsllint-baseline"


def discover(files: list[Path]) -> Path | None:
    """The project's own baseline file, when it has one and the run did not name it.

    Without this the linter reported everything the committed baseline suppresses: CI passes
    `--baseline` explicitly, so the divergence showed up only in a local run and read as
    "the linter has lost its mind". The search goes upwards from the checked files - the
    baseline lives at the repository root, next to (or above) the project descriptor.

    Every surface that answers "is this project clean" discovers the same way (the CLI, the
    MCP server): an answer that depends on which surface asked is worse than no answer.
    """
    seen: set[Path] = set()
    for f in files[:1] or []:
        start = f.resolve().parent
        for candidate in (start, *start.parents):
            if candidate in seen:
                break
            seen.add(candidate)
            path = candidate / DEFAULT_NAME
            if path.is_file():
                return path
    return None


def _identity_path(diag_path: str, base_dir: Path) -> str:
    """The diagnostic path as stored in the baseline: POSIX, relative to the baseline dir."""
    p = Path(diag_path)
    try:
        return p.resolve().relative_to(base_dir.resolve()).as_posix()
    except (OSError, ValueError):
        return p.as_posix()


def _entry_count(value) -> int:
    """The allowed count of an entry: a bare int or the 'count' of a {count, reason} dict."""
    if isinstance(value, int):
        return value
    if isinstance(value, dict) and isinstance(value.get("count"), int):
        return value["count"]
    return 0


def _entry_reason(value) -> str | None:
    if isinstance(value, dict):
        reason = value.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason
    return None


def reasons_of(data: dict) -> dict[tuple[str, str, str], str]:
    """(path, rule, message) -> reason for every entry of the payload that carries one."""
    out: dict[tuple[str, str, str], str] = {}
    for path, per_rule in data.get("files", {}).items():
        if not isinstance(per_rule, dict):
            continue
        for rule_id, per_message in per_rule.items():
            if not isinstance(per_message, dict):
                continue
            for message, value in per_message.items():
                reason = _entry_reason(value)
                if reason:
                    out[(path, rule_id, message)] = reason
    return out


def build(
    diags: list[Diagnostic], base_dir: Path,
    reasons: dict[tuple[str, str, str], str] | None = None,
) -> dict:
    """The baseline payload for the given findings: {files: {path: {rule: {message: count}}}}.

    An identity present in `reasons` is written as {"count": N, "reason": ...} instead of a
    bare count – this is how a rewrite keeps the reasons of the entries that survive it.
    """
    files: dict[str, dict[str, dict[str, object]]] = {}
    for d in sorted(diags, key=lambda x: x.sort_key()):
        path = _identity_path(d.path, base_dir)
        per_rule = files.setdefault(path, {})
        per_message = per_rule.setdefault(d.rule_id, {})
        per_message[d.message] = _entry_count(per_message.get(d.message, 0)) + 1
        reason = (reasons or {}).get((path, d.rule_id, d.message))
        if reason:
            per_message[d.message] = {"count": per_message[d.message], "reason": reason}
    return {
        "meta": {
            "tool": "xbsl",
            "format": _FORMAT,
            "note": "исключённые находки: путь -> правило -> сообщение -> количество или"
                    " {count, reason}; файл создаётся xbsl --write-baseline, исключение"
                    " с причиной добавляет расширение VS Code (или правка руками)",
        },
        "files": {p: files[p] for p in sorted(files)},
    }


def write(path: Path, diags: list[Diagnostic]) -> dict:
    """Write the baseline next to the code it freezes; returns the payload.

    The reasons of an existing file's surviving identities are carried over: a rewrite
    refreshes the counts, not the recorded decisions. A corrupt file is rewritten clean.
    """
    reasons: dict[tuple[str, str, str], str] = {}
    if path.is_file():
        try:
            reasons = reasons_of(load(path))
        except BaselineError:
            pass
    data = build(diags, path.parent, reasons)
    save(path, data)
    return data


def save(path: Path, data: dict) -> None:
    """Write a baseline payload in the file's canonical shape (one place, one format)."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load(path: Path) -> dict:
    if not path.is_file():
        raise BaselineError(i18n.t("baseline.missing", path=path))
    try:
        # utf-8-sig: базлайн, переписанный чужим редактором или PowerShell, несёт BOM -
        # это не повод объявлять файл негодным.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise BaselineError(i18n.t("baseline.invalid", path=path)) from exc
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise BaselineError(i18n.t("baseline.invalid", path=path))
    return data


def _entries(data: dict, rules: set[str] | None, wanted: bool) -> list[tuple[str, str, str, object]]:
    """Entries of the baseline, split by whether the run had their rule.

    `rules` is the set of rule ids the run actually carried (engine.active_rules); without
    it every entry counts, which is what a caller that does not know its selection gets.
    """
    out: list[tuple[str, str, str, object]] = []
    for path, per_rule in sorted(data.get("files", {}).items()):
        if not isinstance(per_rule, dict):
            continue
        for rule_id, per_message in sorted(per_rule.items()):
            if not isinstance(per_message, dict):
                continue
            if rules is not None and (rule_id in rules) is not wanted:
                continue
            for message, value in sorted(per_message.items()):
                out.append((path, rule_id, message, value))
    return out


def not_checked_entries(data: dict, rules: set[str] | None) -> list[dict]:
    """Entries whose rule the run did not carry - not stale, simply not looked at."""
    return [
        {"path": path, "rule": rule_id, "message": message,
         "count": _entry_count(value), "reason": _entry_reason(value)}
        for path, rule_id, message, value in _entries(data, rules, wanted=False)
        if _entry_count(value) > 0
    ]


def stale_entries(
    data: dict, used: dict[tuple[str, str, str], int], rules: set[str] | None = None,
) -> list[dict]:
    """The baseline entries this run did not spend, as records ready to print.

    `used` counts how many occurrences of each identity the run actually suppressed. An
    entry nobody spent means the finding is gone (the code was fixed, the rule changed, the
    file moved) - the count is what the baseline still allows for it. Entries of rules the
    run did not carry are not here: they belong to `not_checked_entries`.
    """
    out: list[dict] = []
    for path, rule_id, message, value in _entries(data, rules, wanted=True):
        count = _entry_count(value)
        left = count - used.get((path, rule_id, message), 0)
        if count > 0 and left > 0:
            out.append({
                "path": path, "rule": rule_id, "message": message,
                "count": left, "reason": _entry_reason(value),
            })
    return out


def without_entries(data: dict, entries: list[dict]) -> dict:
    """A copy of the baseline without the given identities (and without the emptied nests).

    Only whole identities are removed, never a part of a count: an entry is either spent by
    the run or gone. Emptied rule and file nests go with them, so a pruned baseline of a
    clean project is an empty `files` rather than a tree of husks.
    """
    drop = {(e["path"], e["rule"], e["message"]) for e in entries}
    files: dict = {}
    for path, per_rule in data.get("files", {}).items():
        if not isinstance(per_rule, dict):
            continue
        kept_rules: dict = {}
        for rule_id, per_message in per_rule.items():
            if not isinstance(per_message, dict):
                continue
            kept = {
                message: value for message, value in per_message.items()
                if (path, rule_id, message) not in drop
            }
            if kept:
                kept_rules[rule_id] = kept
        if kept_rules:
            files[path] = kept_rules
    return {**data, "files": files}


def apply(
    diags: list[Diagnostic], data: dict, base_dir: Path, rules: set[str] | None = None,
) -> tuple[list[Diagnostic], int, int, list[dict]]:
    """Filter the findings through the baseline.

    Returns (kept findings, suppressed count, unused entry count, stale entries). Per
    identity the first N occurrences in line order are suppressed; the extras are kept.
    Stale entries are frozen findings that no longer occur - they are both counted and
    listed, so a rewrite can name them instead of announcing a number.

    `rules` is the set of rule ids the run carried (engine.active_rules). Entries of the
    other rules still suppress - a finding cannot occur without its rule anyway - but they
    are left out of the unused count and out of the stale list; `not_checked_entries` names
    them. Without the argument the counts stay as they were: every entry judged.
    """
    budgets: dict[tuple[str, str, str], int] = {}
    total_budget = 0
    for path, per_rule in data.get("files", {}).items():
        if not isinstance(per_rule, dict):
            continue
        for rule_id, per_message in per_rule.items():
            if not isinstance(per_message, dict):
                continue
            for message, value in per_message.items():
                count = _entry_count(value)
                if count > 0:
                    budgets[(path, rule_id, message)] = count
                    if rules is None or rule_id in rules:
                        total_budget += count
    kept: list[Diagnostic] = []
    used: dict[tuple[str, str, str], int] = {}
    suppressed = 0
    for d in sorted(diags, key=lambda x: x.sort_key()):
        key = (_identity_path(d.path, base_dir), d.rule_id, d.message)
        left = budgets.get(key, 0)
        if left > 0:
            budgets[key] = left - 1
            used[key] = used.get(key, 0) + 1
            suppressed += 1
        else:
            kept.append(d)
    return kept, suppressed, total_budget - suppressed, stale_entries(data, used, rules)
