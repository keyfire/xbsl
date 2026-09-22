"""Baseline: freeze the existing findings so only new code is held to a rule.

The intended flow: enable a rule (or a whole group) over a codebase with legacy debt,
write the current findings once (`--write-baseline`), commit the file, and lint with
`--baseline` from then on - frozen findings are suppressed, anything new surfaces.

A finding's identity is line-independent on purpose: (file path, rule id, message text),
with an allowed COUNT per identity. Moving a line keeps its finding suppressed; a new
violation of the same rule with the same message in the same file exceeds the count and
the extra occurrences (in line order, the last ones) are reported. Paths are stored as
POSIX paths relative to the baseline file's directory, so the file can be committed and
the linter run from any working directory.

An entry's value is either a bare count or `{"count": N, "reason": "..."}` - the reason
records WHY the finding is excluded (a deliberate project decision, not just frozen debt).
Reasons are written by the editor tooling (the VS Code extension's "exclude the finding"
action) or by hand; `--write-baseline` keeps the reasons of the identities that survive
the rewrite.

The message text is part of the identity, so the baseline must be written and checked
under the same output language (--lang / XBSL_LANG); a language switch surfaces
every frozen finding and marks the whole file's entries as unused.

The text belongs to the rule, though, and a release may reword it. An entry frozen under
an earlier wording then held nothing: the finding came back as new with its reason unread,
and the entry was called stale. So an entry whose text fits no current wording of its rule
(`_reworded`) also holds a finding of that rule in that file which names the same values -
each in the quotes its template gives it, in the same order. The exact text is spent first;
a message without values is never matched this way, since nothing would tell two such
findings apart. The run names these entries (`reworded` of `apply`), and a rewrite carries
their reasons over to the new text.

Unused and stale are counted only over the entries whose RULE the run actually had: a rule
left out of the selection (or off by default, or unknown to the installed plugins) produces
no findings by construction, and calling its entries stale would say the debt is paid when
nobody looked. That is what made two environments disagree about one baseline - an MCP
server on an older plugin called 48 entries stale while CI, running the same tree with the
rules enabled, called none. Such entries are reported apart, as not checked, and `--prune-
baseline` never touches them.

The same standing goes to the entries of files the run did not reach. A run looks at what
it was asked for - the files named and everything under the directories named - and an
entry of any other file cannot be spent by it. Weighing the whole baseline against a
partial run is what made one server contradict itself within a minute: a request for two
files answered "0 suppressed, 76 stale", the project run "74 suppressed, 4 stale". The
reach is `roots_of` the requested paths; entries outside it are not checked, not stale.

A single decision is added without a rewrite: `xbsl baseline add <paths> --rule R
[--reason ...]` (`add_entries`) appends the findings of one rule the file does not cover
yet and moves nothing that is already there - a rewrite re-sorts the file and refreshes
every count, which is the wrong tool for one finding with a reason.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from string import Formatter

from xbsl import i18n
from xbsl.diagnostics import Diagnostic

_FORMAT = 1

_MESSAGES = {
    "baseline.missing": {
        "ru": "Файл списка принятых замечаний не найден: {path}. Создайте его: xbsl ... --write-baseline {path}",
        "en": "Baseline file not found: {path}. Create it: xbsl ... --write-baseline {path}",
    },
    "baseline.invalid": {
        "ru": "Файл списка принятых замечаний повреждён или неизвестного формата: {path}",
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


#: A file path INSIDE the text of a finding. The cross-file rules name the second file the way
#: the run received it - with the separators of the host, and absolute when the root given on
#: the command line was absolute - while the identity of an entry is its text. Without a common
#: form the same finding reads as two: a baseline frozen on Windows suppressed nothing in a
#: Linux CI and was announced stale on both sides (measured on a live project: "97 frozen, 2
#: stale" locally against "89 and 7" in CI on one revision).
_PATH_IN_MESSAGE = re.compile(r"[^\s\"'()<>]*[\\/][^\s\"'()<>]*\.(?:yaml|xbsl|xbql|json)")


# Only reviewed positional fields participate. Counts such as duplicate-bodies.lines,
# namespace names and every other semantic value remain part of the identity.
_POSITION_FIELDS = {
    "code/bound-property-assign.msg": "line",
    "yaml/computed-binding-assigned.msg": "line",
    "code/unclosed-resource.early-exit": "line",
    "code/query-in-loop.body": "line",
    "code/duplicate-import.repeated": "line",
    "yaml/duplicate-import.repeated": "line",
    "yaml/localization-key-unique.found": "line",
    "yaml/localization-key-unique.cross": "line",
    "code/param-redeclared.found": "line",
    "code/duplicate-declaration.type": "line",
    "code/duplicate-declaration.field": "line",
    "code/duplicate-declaration.item": "line",
    "code/duplicate-declaration.default": "line",
    "code/duplicate-declaration.method-case": "line",
    "code/duplicate-declaration.constant": "line",
    "code/duplicate-declaration.local": "line",
    "yaml/duplicate-key.repeat": "line",
    "yaml/missing-import.query": "query_line",
}
_POSITION_MESSAGES: dict[str, list[tuple[str, str]]] = {}
for _message_id, _field in _POSITION_FIELDS.items():
    _POSITION_MESSAGES.setdefault(_message_id.split(".", 1)[0], []).append((_message_id, _field))


@lru_cache(maxsize=128)
def _position_pattern(template: str, position: str) -> re.Pattern:
    """Match a complete translated template, capturing only its vetted position field.

    Other fields, including translated n[...] names, match their rendered values but stay
    byte-for-byte in the identity. Patterns follow the registered templates, not copies.
    """
    parts = []
    for literal, field, format_spec, conversion in Formatter().parse(template):
        parts.append(re.escape(literal))
        if field == position:
            parts.append(r"(?P<position>\d+)")
        elif field is not None:
            parts.append(".*?")
    return re.compile("".join(parts), re.DOTALL)


def _identity_message(message: str, base_dir: Path, rule_id: str | None = None) -> str:
    """Normalize paths and vetted display positions without changing diagnostic text."""
    message = _PATH_IN_MESSAGE.sub(lambda hit: _identity_path(hit.group(0), base_dir), message)
    candidates = _POSITION_MESSAGES.get(rule_id, [])
    if candidates:
        # Standalone baseline callers need the builtin message registry too.
        from xbsl import rules  # noqa: F401

        for message_id, position in candidates:
            for template in (i18n.translations(message_id) or {}).values():
                match = _position_pattern(template, position).fullmatch(message)
                if match is not None:
                    return (message[:match.start("position")] + "{" + position + "}"
                            + message[match.end("position"):])
    return message


# --- an entry the rule reworded ---------------------------------------------------------------

#: The quotes a template may put around a value, opening -> closing.
_QUOTES = {"'": "'", '"': '"', "`": "`"}


@lru_cache(maxsize=512)
def _wording(template: str, position: str | None) -> tuple[re.Pattern, tuple[tuple[str, str], ...]]:
    """A template as a pattern of its whole text, with the quotes around each value it captures.

    A value is what the finding names. A translated name (`n[...]`) belongs to the wording, and
    a display position (`position`, see _POSITION_FIELDS) is normalized in the identity, so both
    are matched without being captured.
    """
    pieces = list(Formatter().parse(template))
    parts: list[str] = []
    quotes: list[tuple[str, str]] = []
    for index, (literal, field, _spec, _conversion) in enumerate(pieces):
        parts.append(re.escape(literal))
        if field is None:
            continue
        if field.startswith("n[") or field == position:
            parts.append(".*?")
            continue
        parts.append("(.*?)")
        opening = literal[-1:]
        closing = pieces[index + 1][0][:1] if index + 1 < len(pieces) else ""
        quotes.append((opening, closing) if opening and _QUOTES.get(opening) == closing
                      else ("", ""))
    return re.compile("".join(parts), re.DOTALL), tuple(quotes)


def _wordings(rule_id: str, keys: list[str]) -> list[tuple[str, str | None]]:
    """Every current template of the rule in every language, with its position field."""
    prefix = rule_id + "."
    return [
        (template, _POSITION_FIELDS.get(key))
        for key in keys if key.startswith(prefix)
        for template in (i18n.translations(key) or {}).values()
    ]


def _values(message: str, wordings: list[tuple[str, str | None]]) -> list[str] | None:
    """The values a current wording fills into the message, each in its quotes, or None when
    no current wording fits the text."""
    for template, position in wordings:
        pattern, quotes = _wording(template, position)
        match = pattern.fullmatch(message)
        if match is not None:
            return [opening + value + closing
                    for value, (opening, closing) in zip(match.groups(), quotes)]
    return None


def _carries(text: str, values: list[str]) -> bool:
    """Whether the text names the values in this order."""
    at = 0
    for value in values:
        found = text.find(value, at)
        if found < 0:
            return False
        at = found + len(value)
    return True


class _Reworded:
    """The entries whose text fits no current wording of their rule, by file and rule.

    Built lazily: the registry of messages is read only when some entry is left unspent.
    """

    def __init__(self) -> None:
        # Standalone baseline callers need the builtin message registry too.
        from xbsl import rules  # noqa: F401

        self._keys = i18n.registered_keys()
        self._wordings: dict[str, list[tuple[str, str | None]]] = {}
        self.by_place: dict[tuple[str, str], list[tuple[str, str, str]]] = {}

    def wordings(self, rule_id: str) -> list[tuple[str, str | None]]:
        if rule_id not in self._wordings:
            self._wordings[rule_id] = _wordings(rule_id, self._keys)
        return self._wordings[rule_id]

    def add(self, key: tuple[str, str, str]) -> None:
        """Keep the entry of this identity when a release reworded it."""
        path, rule_id, message = key
        if _values(message, self.wordings(rule_id)) is None:
            self.by_place.setdefault((path, rule_id), []).append(key)

    def holder(self, path: str, rule_id: str, message: str,
               left: dict[tuple[str, str, str], int]) -> tuple[str, str, str] | None:
        """The reworded entry with budget `left` that holds this finding, if any."""
        candidates = self.by_place.get((path, rule_id))
        if not candidates:
            return None
        values = _values(message, self.wordings(rule_id))
        # A message without a named value gives nothing to tell two findings apart by.
        if not values or not any(ch.isalpha() for value in values for ch in value):
            return None
        for key in candidates:
            if left.get(key, 0) > 0 and _carries(key[2], values):
                return key
        return None


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


def reasons_of(data: dict, base_dir: Path) -> dict[tuple[str, str, str], str]:
    """(path, rule, message) -> reason for every entry of the payload that carries one.

    The message is taken in the common form, the same one `build` writes: a rewrite carries a
    reason over by identity, and an entry naming another file would otherwise lose it on the
    first machine whose separators differ from the ones it was frozen with.
    """
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
                    out[(path, rule_id, _identity_message(message, base_dir, rule_id))] = reason
    return out


def build(
    diags: list[Diagnostic], base_dir: Path,
    reasons: dict[tuple[str, str, str], str] | None = None,
) -> dict:
    """The baseline payload for the given findings: {files: {path: {rule: {message: count}}}}.

    An identity present in `reasons` is written as {"count": N, "reason": ...} instead of a
    bare count - this is how a rewrite keeps the reasons of the entries that survive it.
    """
    files: dict[str, dict[str, dict[str, object]]] = {}
    for d in sorted(diags, key=lambda x: x.sort_key()):
        path = _identity_path(d.path, base_dir)
        message = _identity_message(d.message, base_dir, d.rule_id)
        per_rule = files.setdefault(path, {})
        per_message = per_rule.setdefault(d.rule_id, {})
        per_message[message] = _entry_count(per_message.get(message, 0)) + 1
        reason = (reasons or {}).get((path, d.rule_id, message))
        if reason:
            per_message[message] = {"count": per_message[message], "reason": reason}
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
            reasons = reasons_of(load(path), path.parent)
        except BaselineError:
            pass
    if reasons:
        reasons.update(_reworded_reasons(reasons, diags, path.parent))
    data = build(diags, path.parent, reasons)
    save(path, data)
    return data


def _reworded_reasons(
    reasons: dict[tuple[str, str, str], str], diags: list[Diagnostic], base_dir: Path,
) -> dict[tuple[str, str, str], str]:
    """The reasons of reworded entries, keyed by the identity of the finding each one holds.

    Without them a rewrite after a reworded release wrote the finding under its new text and
    dropped the sentence explaining why it was excluded.
    """
    earlier: _Reworded | None = None
    every = dict.fromkeys(reasons, 1)
    out: dict[tuple[str, str, str], str] = {}
    for d in diags:
        key = (_identity_path(d.path, base_dir), d.rule_id,
               _identity_message(d.message, base_dir, d.rule_id))
        if key in reasons or key in out:
            continue
        if earlier is None:
            earlier = _Reworded()
            for entry in reasons:
                earlier.add(entry)
        holder = earlier.holder(key[0], key[1], key[2], every)
        if holder is not None:
            out[key] = reasons[holder]
    return out


def save(path: Path, data: dict) -> None:
    """Write a baseline payload in the file's canonical shape (one place, one format).

    The line endings and the BOM of an existing file are kept: a committed baseline is LF
    (git normalizes it so), and a rewrite in the platform's native style turned a one-entry
    addition on Windows into a diff of every line. A new file is written with LF - the form
    it is committed in.
    """
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    newline, bom = "\n", ""
    if path.is_file():
        raw = path.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            bom = "\ufeff"
        if b"\r\n" in raw:
            newline = "\r\n"
    path.write_text(bom + text, encoding="utf-8", newline=newline)


def load(path: Path, *, strict: bool = False) -> dict:
    if not path.is_file():
        raise BaselineError(i18n.t("baseline.missing", path=path))
    try:
        # utf-8-sig: a baseline rewritten by another editor or by PowerShell carries a
        # BOM - that is no reason to call the file unusable.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise BaselineError(i18n.t("baseline.invalid", path=path)) from exc
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        raise BaselineError(i18n.t("baseline.invalid", path=path))
    if strict:
        _validate_for_fix(data, path)
    return data


def _validate_for_fix(data: dict, path: Path) -> None:
    """Reject any malformed budget before an operation that writes source files.

    Legacy files may omit metadata and use bare integer counts. Current reasoned entries
    carry a count and an optional string reason; neither shape permits coercing a count.
    """
    def invalid() -> None:
        raise BaselineError(i18n.t("baseline.invalid", path=path))

    if "meta" in data:
        meta = data["meta"]
        if not isinstance(meta, dict):
            invalid()
        if "format" in meta and (type(meta["format"]) is not int or meta["format"] != _FORMAT):
            invalid()
        if any(key in meta and not isinstance(meta[key], str) for key in ("tool", "note")):
            invalid()
    for per_rule in data["files"].values():
        if not isinstance(per_rule, dict):
            invalid()
        for per_message in per_rule.values():
            if not isinstance(per_message, dict):
                invalid()
            for value in per_message.values():
                count = value.get("count") if isinstance(value, dict) else value
                if type(count) is not int or count < 0:
                    invalid()
                if isinstance(value, dict) and "reason" in value and not isinstance(value["reason"], str):
                    invalid()


def roots_of(paths: list[Path], base_dir: Path) -> list[str] | None:
    """The reach of a run inside the baseline: the requested paths in the baseline's own form.

    An entry can be spent only when the run looked at its file, and a run looks at what it
    was asked for: the files named on the command line and everything under the directories
    named there. Entries outside that reach are not stale, they are not checked - the same
    standing as the entries of a rule the run did not carry.

    None means the whole baseline is in reach: a requested path is the baseline's directory
    itself or one of its parents. A requested path outside the baseline's directory reaches
    no entry.
    """
    base = base_dir.resolve()
    roots: list[str] = []
    for p in paths:
        rp = Path(p).resolve()
        if rp == base or rp in base.parents:
            return None
        try:
            roots.append(rp.relative_to(base).as_posix())
        except ValueError:
            continue
    return roots


def _in_reach(path: str, roots: list[str] | None) -> bool:
    """Whether an entry's file lies within the requested paths of the run."""
    if roots is None:
        return True
    return any(path == root or path.startswith(root + "/") for root in roots)


def _entries(
    data: dict, rules: set[str] | None, wanted: bool, roots: list[str] | None = None,
) -> list[tuple[str, str, str, object]]:
    """Entries of the baseline, split by whether the run could have spent them.

    An entry is checked when the run carried its rule (`rules`, engine.active_rules; None
    means every rule) AND its file lies within the run's reach (`roots`, see roots_of; None
    means the whole baseline). `wanted` picks the checked or the unchecked side.
    """
    out: list[tuple[str, str, str, object]] = []
    for path, per_rule in sorted(data.get("files", {}).items()):
        if not isinstance(per_rule, dict):
            continue
        reached = _in_reach(path, roots)
        for rule_id, per_message in sorted(per_rule.items()):
            if not isinstance(per_message, dict):
                continue
            checked = reached and (rules is None or rule_id in rules)
            if checked is not wanted:
                continue
            for message, value in sorted(per_message.items()):
                out.append((path, rule_id, message, value))
    return out


def not_checked_entries(
    data: dict, rules: set[str] | None, roots: list[str] | None = None,
) -> list[dict]:
    """Entries the run could not judge - not stale, simply not looked at.

    `cause` names why: "path" when the file lies outside the run's reach, else "rule" when
    the run did not carry the rule. A file outside the reach is the stronger reason - its
    rules do not matter to a run that never opened it.
    """
    return [
        {"path": path, "rule": rule_id, "message": message,
         "count": _entry_count(value), "reason": _entry_reason(value),
         "cause": "rule" if _in_reach(path, roots) else "path"}
        for path, rule_id, message, value in _entries(data, rules, wanted=False, roots=roots)
        if _entry_count(value) > 0
    ]


def not_checked_split(entries: list[dict]) -> dict[str, int]:
    """How many of the not-checked entries fall to each cause: {"rules": n, "paths": n}."""
    paths = sum(1 for e in entries if e.get("cause") == "path")
    return {"rules": len(entries) - paths, "paths": paths}


def stale_entries(
    data: dict, used: dict[tuple[str, str, str], int], rules: set[str] | None = None,
    base_dir: Path | None = None, roots: list[str] | None = None,
) -> list[dict]:
    """The baseline entries this run did not spend, as records ready to print.

    `used` counts how many occurrences of each identity the run actually suppressed. An
    entry nobody spent means the finding is gone (the code was fixed, the rule changed, the
    file moved) - the count is what the baseline still allows for it. Entries of rules the
    run did not carry, and of files outside its reach (`roots`), are not here: they belong
    to `not_checked_entries`.
    """
    out: list[dict] = []
    remaining_used = dict(used)
    for path, rule_id, message, value in _entries(data, rules, wanted=True, roots=roots):
        count = _entry_count(value)
        # Spent by identity, reported as WRITTEN: the caller drops the entry by its own key.
        spent = message if base_dir is None else _identity_message(message, base_dir, rule_id)
        key = (path, rule_id, spent)
        consumed = min(max(count, 0), remaining_used.get(key, 0))
        remaining_used[key] = remaining_used.get(key, 0) - consumed
        left = count - consumed
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

    An entry's `reason` goes with it - it is a sentence about THAT finding, and the finding
    is gone. Every surface therefore reads the reasons out before removing them (the CLI
    prints them under the entries, the MCP `baseline_prune` returns them), and after the
    commit the text lives on in the history of the file.
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
    roots: list[str] | None = None,
    accepted: list[tuple[Diagnostic, Diagnostic]] | None = None,
    reworded: list[dict] | None = None,
) -> tuple[list[Diagnostic], int, int, list[dict]]:
    """Filter the findings through the baseline.

    Returns (kept findings, suppressed count, unused entry count, stale entries). Per
    identity the first N occurrences in line order are suppressed; the extras are kept.
    Stale entries are frozen findings that no longer occur - they are both counted and
    listed, so a rewrite can name them instead of announcing a number.

    `rules` is the set of rule ids the run carried (engine.active_rules), `roots` the reach
    of the run (roots_of). Entries of the other rules and of files outside the reach still
    suppress - a finding cannot occur there anyway - but they are left out of the unused
    count and out of the stale list; `not_checked_entries` names them. Without the
    arguments the counts stay as they were: every entry judged.

    `reworded`, when given, receives the entries that held a finding under an earlier
    wording of their rule (see the module note): {path, rule, message, count, reason}, the
    message as the file writes it.
    """
    if accepted is not None:
        # A fix run pins occurrences once. Count their ORIGINAL identities for the budget,
        # while removing their current diagnostic objects: messages can contain line numbers.
        _, suppressed, unused, stale = apply(
            [original for current, original in accepted], data, base_dir, rules, roots,
            reworded=reworded,
        )
        frozen = {id(current) for current, original in accepted}
        return [d for d in diags if id(d) not in frozen], suppressed, unused, stale
    budgets: dict[tuple[str, str, str], int] = {}
    written: dict[tuple[str, str, str], tuple[str, str | None]] = {}
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
                    # Two entries of one identity meet when a file carries a message frozen
                    # on Windows and its twin frozen on Linux: their budgets add up rather
                    # than one replacing the other.
                    key = (path, rule_id, _identity_message(message, base_dir, rule_id))
                    budgets[key] = budgets.get(key, 0) + count
                    written.setdefault(key, (message, _entry_reason(value)))
                    if (rules is None or rule_id in rules) and _in_reach(path, roots):
                        total_budget += count
    kept: list[Diagnostic] = []
    used: dict[tuple[str, str, str], int] = {}
    suppressed = 0
    for d in sorted(diags, key=lambda x: x.sort_key()):
        key = (_identity_path(d.path, base_dir), d.rule_id,
               _identity_message(d.message, base_dir, d.rule_id))
        left = budgets.get(key, 0)
        if left > 0:
            budgets[key] = left - 1
            used[key] = used.get(key, 0) + 1
            suppressed += 1
        else:
            kept.append(d)
    if kept and any(left > 0 for left in budgets.values()):
        # The second pass: what the exact text left unspent may still hold a finding whose
        # rule reworded the message since the entry was frozen.
        earlier = _Reworded()
        for key, left in budgets.items():
            if left > 0:
                earlier.add(key)
        held: dict[tuple[str, str, str], int] = {}
        still: list[Diagnostic] = []
        for d in kept:
            path = _identity_path(d.path, base_dir)
            holder = earlier.holder(path, d.rule_id,
                                    _identity_message(d.message, base_dir, d.rule_id), budgets)
            if holder is None:
                still.append(d)
                continue
            budgets[holder] -= 1
            used[holder] = used.get(holder, 0) + 1
            held[holder] = held.get(holder, 0) + 1
            suppressed += 1
        kept = still
        if reworded is not None:
            for key in sorted(held):
                message, reason = written[key]
                reworded.append({"path": key[0], "rule": key[1], "message": message,
                                 "count": held[key], "reason": reason})
    return (kept, suppressed, total_budget - suppressed,
            stale_entries(data, used, rules, base_dir, roots))


def _with_file(files: dict, path: str, per_rule: dict) -> dict:
    """`files` plus a new file key at the place `build` would sort it; nothing else moves."""
    out: dict = {}
    placed = False
    for existing, value in files.items():
        if not placed and existing > path:
            out[path] = per_rule
            placed = True
        out[existing] = value
    if not placed:
        out[path] = per_rule
    return out


def add_entries(
    data: dict, diags: list[Diagnostic], base_dir: Path, reason: str | None = None,
) -> list[dict]:
    """Extend the payload with the findings it does not cover yet; returns what was added.

    The counterpart of `write` for ONE decision. A rewrite refreshes every count and re-sorts
    the file, and merging a snapshot by hand once re-sorted a project's baseline for two
    findings (a diff of 28/16 lines instead of +12). Here nothing that exists moves: a new
    file goes to its sorted place among the files (the order `build` writes), a new rule or
    message to the end of its nest, and an existing entry only grows its count. `reason` is
    written on new entries and on those that had none; a recorded reason is never replaced.
    Findings the payload already covers add nothing, so a repeated call changes nothing.

    Each record of the result is {path, rule, message, count, reason}: `count` is the number
    of occurrences added, `reason` the one the entry carries afterwards, `message` the key
    as written in the file.
    """
    kept, _suppressed, _unused, _stale = apply(diags, data, base_dir)
    added: dict[tuple[str, str, str], int] = {}
    for d in sorted(kept, key=lambda x: x.sort_key()):
        key = (_identity_path(d.path, base_dir), d.rule_id,
               _identity_message(d.message, base_dir, d.rule_id))
        added[key] = added.get(key, 0) + 1
    files = data.get("files")
    if not isinstance(files, dict):
        files = data["files"] = {}
    records: list[dict] = []
    for (path, rule_id, message), count in added.items():
        per_rule = files.get(path)
        if not isinstance(per_rule, dict):
            per_rule = {}
            if path in files:
                files[path] = per_rule
            else:
                files = data["files"] = _with_file(files, path, per_rule)
        per_message = per_rule.get(rule_id)
        if not isinstance(per_message, dict):
            per_message = per_rule[rule_id] = {}
        # The entry is matched by identity but kept under the key as WRITTEN: a message
        # naming a file may carry the separators of another host.
        written = next(
            (k for k in per_message if _identity_message(k, base_dir, rule_id) == message), None,
        )
        if written is None:
            per_message[message] = {"count": count, "reason": reason} if reason else count
            records.append({"path": path, "rule": rule_id, "message": message,
                            "count": count, "reason": reason})
            continue
        value = per_message[written]
        total = _entry_count(value) + count
        kept_reason = _entry_reason(value) or reason
        per_message[written] = {"count": total, "reason": kept_reason} if kept_reason else total
        records.append({"path": path, "rule": rule_id, "message": written,
                        "count": count, "reason": kept_reason})
    return records
