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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def load(path: Path) -> dict:
    if not path.is_file():
        raise BaselineError(i18n.t("baseline.missing", path=path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BaselineError(i18n.t("baseline.invalid", path=path)) from exc
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise BaselineError(i18n.t("baseline.invalid", path=path))
    return data


def apply(
    diags: list[Diagnostic], data: dict, base_dir: Path,
) -> tuple[list[Diagnostic], int, int]:
    """Filter the findings through the baseline.

    Returns (kept findings, suppressed count, unused entry count). Per identity the first
    N occurrences in line order are suppressed; the extras are kept. Unused entries are
    frozen findings that no longer occur – a hint that the baseline is due a rewrite.
    """
    budgets: dict[tuple[str, str, str], int] = {}
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
    total_budget = sum(budgets.values())
    kept: list[Diagnostic] = []
    suppressed = 0
    for d in sorted(diags, key=lambda x: x.sort_key()):
        key = (_identity_path(d.path, base_dir), d.rule_id, d.message)
        left = budgets.get(key, 0)
        if left > 0:
            budgets[key] = left - 1
            suppressed += 1
        else:
            kept.append(d)
    return kept, suppressed, total_budget - suppressed
