"""A check run as counts, and the difference with the run saved before it.

`--summary` prints the counts by rule instead of the findings: the rule, the files it reached
and its findings, then one line of totals. `--compare FILE` keeps the run in FILE, and the next
run with the same file prints only what changed: the rules whose findings moved, with their
counts now and how many findings appeared and disappeared, then the changed findings themselves
while there are no more than COMPACT_FINDINGS_LIMIT of them. With nothing changed the answer
is one line.

Comparing the findings before and after a change on a set of projects is everyday work on the
rules. It used to go through `--format json` and a script of its own every time, and the text of
every finding came along - several hundred characters each, tens of thousands of lines over a
set of projects, to get a few numbers out of them.

A finding is keyed by the path given on the command line, the file under that path, the line,
the column, the rule and the text. The path is kept as it was typed rather than resolved:
`xbsl demo` run from two worktrees of the repository names the same findings, while the
absolute place of each checkout would make every one of them differ. The text is the message in
the language of the run, so a run saved in another language is refused instead of being
reported as a change of everything.

Two runs do not always check the same things, and a part only one of them checked is left out
of the comparison - its findings did not appear or disappear, one of the runs never looked:

  * a path given to one run and not to the other;
  * a rule only one run carried, when the two runs were given different rule selection flags.
    Under the same flags a different rule set comes from the engine itself - a rule added or
    removed, a default turned on - and that is exactly the change being measured, so it is
    compared. A rule one of the two engines does not know at all is compared under any flags.

Every part left out is named in a line of its own, with the count of its findings.

The saved file keeps the findings of the run one per line and, ahead of them, the changes
against the run before it. Past the listing limit the terminal gives the count and the file,
and the list is read there.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from xbsl import i18n, report
from xbsl.diagnostics import Diagnostic

#: The format of the saved file; a file of another format is not read.
FORMAT = 1
#: Tells a saved run from any other JSON the tool writes. A baseline is `{"meta": {"tool":
#: "xbsl", ...}}` as well, and a run written over it would destroy it.
KIND = "run"
#: How many names a line about a left-out part lists before it counts the rest.
NAMES_SHOWN = 5

#: (path given, file under it, line, column, rule, text)
Finding = tuple[str, str, int, int, str, str]

_NOTE = (
    "a check run saved by xbsl --compare: every finding is [path given, file under it, line, "
    "column, rule, text]; changes holds what appeared and disappeared against the run saved "
    "before it"
)

MESSAGES = {
    "rundiff.head-rule": {"ru": "правило", "en": "rule"},
    "rundiff.head-files": {"ru": "файлов", "en": "files"},
    "rundiff.head-findings": {"ru": "находок", "en": "findings"},
    "rundiff.head-appeared": {"ru": "появилось", "en": "appeared"},
    "rundiff.head-disappeared": {"ru": "исчезло", "en": "disappeared"},
    "rundiff.totals": {
        "ru": "Находок: {findings}; правил с находками: {rules}; "
              "файлов с находками: {files} из {checked}",
        "en": "Findings: {findings}; rules with findings: {rules}; "
              "files with findings: {files} of {checked}",
    },
    "rundiff.totals-baseline": {
        "ru": "Находок: {findings}; правил с находками: {rules}; "
              "файлов с находками: {files} из {checked}; погашено списком принятых: {suppressed}",
        "en": "Findings: {findings}; rules with findings: {rules}; "
              "files with findings: {files} of {checked}; suppressed by the baseline: {suppressed}",
    },
    "rundiff.first": {
        "ru": "Сравнивать пока не с чем: запуск сохранён в {path}",
        "en": "Nothing to compare with yet: the run is saved to {path}",
    },
    "rundiff.same": {
        "ru": "Без изменений по сравнению с {path}",
        "en": "No changes against {path}",
    },
    "rundiff.changed": {
        "ru": "По сравнению с {path}: появилось {appeared}, исчезло {disappeared}",
        "en": "Against {path}: {appeared} appeared, {disappeared} disappeared",
    },
    "rundiff.too-many": {
        "ru": "Изменений больше {limit}: весь список – в {path}, раздел changes",
        "en": "Over {limit} changes: the full list is in {path}, under changes",
    },
    "rundiff.skipped-paths-gone": {
        "ru": "Не сравнивались пути, которых нет в этом запуске: {names}; "
              "их находок в сохранённом: {count}",
        "en": "Not compared, the paths this run did not check: {names}; "
              "their findings in the saved run: {count}",
    },
    "rundiff.skipped-paths-new": {
        "ru": "Не сравнивались пути, которых нет в сохранённом запуске: {names}; "
              "их находок: {count}",
        "en": "Not compared, the paths the saved run did not check: {names}; "
              "their findings: {count}",
    },
    "rundiff.skipped-rules-gone": {
        "ru": "Не сравнивались правила, которых нет в наборе этого запуска: {names}; "
              "их находок в сохранённом: {count}",
        "en": "Not compared, the rules outside the set of this run: {names}; "
              "their findings in the saved run: {count}",
    },
    "rundiff.skipped-rules-new": {
        "ru": "Не сравнивались правила, которых не было в наборе сохранённого запуска: {names}; "
              "их находок: {count}",
        "en": "Not compared, the rules outside the set of the saved run: {names}; "
              "their findings: {count}",
    },
    "rundiff.more": {"ru": "и ещё {count}", "en": "and {count} more"},
    "rundiff.not-a-run": {
        "ru": "{path} не похож на запуск, сохранённый xbsl: сравнивать не с чем, а запись "
              "поверх уничтожит файл. Назовите другой файл",
        "en": "{path} does not look like a run saved by xbsl: there is nothing to compare "
              "with, and writing over it would destroy the file. Name another file",
    },
    "rundiff.other-language": {
        "ru": "Запуск в {path} сохранён на языке {saved}, а этот идёт на {lang}, и тексты "
              "находок не совпадут. Запустите с --lang {saved} или назовите другой файл",
        "en": "The run in {path} was saved in {saved} and this one runs in {lang}, so the "
              "texts of the findings would not match. Run with --lang {saved} or name "
              "another file",
    },
    "rundiff.save-failed": {
        "ru": "Запуск не сохранён в {path}: {error}",
        "en": "The run was not saved to {path}: {error}",
    },
}
i18n.register(MESSAGES)


class RunStateError(RuntimeError):
    """The saved file cannot be compared with; the text says why and what to do."""


@dataclass
class Run:
    """One check run as `--compare` keeps it."""

    #: The paths of the command line, as findings() keys them.
    corpora: list[str]
    #: The keyed findings, in the order of their keys.
    findings: list[Finding]
    #: The number of files checked.
    checked: int = 0
    lang: str = i18n.DEFAULT_LANG
    #: The rule selection flags as parsed: {"select": [...] or None, "ignore": ..., "enable": ...}.
    selection: dict = field(default_factory=dict)
    #: Every rule the engine knows, and whether this run carried it.
    rules: dict[str, bool] = field(default_factory=dict)
    #: The version of the engine, for the reader of the file.
    engine: str = ""


@dataclass
class Changes:
    """What moved between two runs, and what was left out as (message key, names, count)."""

    appeared: list[Finding]
    disappeared: list[Finding]
    skipped: list[tuple[str, list[str], int]]


def labels(paths: list[str]) -> list[str]:
    """The paths of the command line as they key the findings: as typed, forward slashes."""
    return list(dict.fromkeys(Path(p).as_posix() for p in paths))


def findings(diagnostics: list[Diagnostic], paths: list[str]) -> list[Finding]:
    """The findings keyed for a comparison, in the order of their keys.

    A file is placed under the first path of the command line that holds it; a file outside
    all of them keeps its own path and an empty path given.
    """
    roots: list[tuple[str, Path]] = []
    for label in labels(paths):
        try:
            roots.append((label, Path(label).resolve()))
        except OSError:
            continue
    placed: dict[str, tuple[str, str]] = {}
    keyed: list[Finding] = []
    for d in diagnostics:
        where = placed.get(d.path)
        if where is None:
            where = placed[d.path] = _place(d.path, roots)
        keyed.append((where[0], where[1], d.line, d.col, d.rule_id, d.message))
    return sorted(keyed)


def _place(path: str, roots: list[tuple[str, Path]]) -> tuple[str, str]:
    """(path given, file under it) of one file."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return "", Path(path).as_posix()
    for label, root in roots:
        try:
            inner = resolved.relative_to(root)
        except ValueError:
            continue
        return label, inner.as_posix() if inner.parts else ""
    return "", Path(path).as_posix()


def record(
    diagnostics: list[Diagnostic], paths: list[str], *, checked: int, lang: str,
    selection: dict, rules: dict[str, bool], engine: str = "",
) -> Run:
    """The run as `--compare` saves it."""
    return Run(
        corpora=labels(paths), findings=findings(diagnostics, paths), checked=checked,
        lang=lang, selection=selection, rules=rules, engine=engine,
    )


def compare(saved: Run, run: Run) -> Changes:
    """What appeared and disappeared since the saved run, over what both runs checked.

    The findings are compared as multisets: two equal findings at one place are two, and
    losing one of them is a change.
    """
    # A finding outside every given path has the empty path given, and both runs share it.
    shared = (set(saved.corpora) & set(run.corpora)) | {""}
    gone_rules, new_rules = _rules_apart(saved, run)
    left_out = gone_rules | new_rules

    def compared(finding: Finding) -> bool:
        return finding[0] in shared and finding[4] not in left_out

    before = Counter(f for f in saved.findings if compared(f))
    after = Counter(f for f in run.findings if compared(f))
    skipped: list[tuple[str, list[str], int]] = []
    gone = [path for path in saved.corpora if path not in shared]
    if gone:
        skipped.append(("rundiff.skipped-paths-gone", gone,
                        sum(1 for f in saved.findings if f[0] in gone)))
    new = [path for path in run.corpora if path not in shared]
    if new:
        skipped.append(("rundiff.skipped-paths-new", new,
                        sum(1 for f in run.findings if f[0] in new)))
    for key, rules, side in (("rundiff.skipped-rules-gone", gone_rules, saved.findings),
                             ("rundiff.skipped-rules-new", new_rules, run.findings)):
        if rules:
            # The rules with findings first: a full run against a narrow one leaves out two
            # hundred rules, and the first five of the alphabet are rarely the ones that fired.
            counts = Counter(f[4] for f in side if f[0] in shared and f[4] in rules)
            names = sorted(rules, key=lambda rule: (-counts[rule], rule))
            skipped.append((key, names, sum(counts.values())))
    return Changes(
        appeared=sorted((after - before).elements()),
        disappeared=sorted((before - after).elements()),
        skipped=skipped,
    )


def _rules_apart(saved: Run, run: Run) -> tuple[set[str], set[str]]:
    """The rules only one of the runs carried by its own flags: (the saved run's, this run's).

    Empty when the selection flags of both runs are the same: then every difference in the
    rule set is the engine's own. A rule one of the engines does not know is never among them.
    """
    if saved.selection == run.selection:
        return set(), set()
    known = saved.rules.keys() & run.rules.keys()
    carried_then = {rule for rule, on in saved.rules.items() if on}
    carried_now = {rule for rule, on in run.rules.items() if on}
    return (carried_then - carried_now) & known, (carried_now - carried_then) & known


# --- the text ------------------------------------------------------------------------------


def summary_lines(
    diagnostics: list[Diagnostic], *, checked: int, suppressed: int | None = None,
) -> list[str]:
    """The text of `--summary`: a row per rule, then the totals of the run."""
    rows = report.rule_table(diagnostics)
    lines = _table(_headers("rule", "files", "findings"), rows) if rows else []
    lines.append(_totals(diagnostics, len(rows), checked, suppressed))
    return lines


def changes_lines(
    changes: Changes, diagnostics: list[Diagnostic], *, path: str, checked: int,
    suppressed: int | None = None,
) -> list[str]:
    """The text of `--compare` against a saved run: only what changed, then the totals.

    A changed rule gets a row with its files and findings in this run and the counts of what
    appeared and disappeared. The changed findings follow one per line, a minus for the one
    that went and a plus for the one that came, while there are no more of them than
    COMPACT_FINDINGS_LIMIT; past it a line points at the saved file. With nothing changed and
    nothing left out, the answer is the last line alone.
    """
    rows = report.rule_table(diagnostics)
    now = {rule: (files, count) for rule, files, count in rows}
    appeared = Counter(f[4] for f in changes.appeared)
    disappeared = Counter(f[4] for f in changes.disappeared)
    changed = sorted(appeared.keys() | disappeared.keys(),
                     key=lambda rule: (-(appeared[rule] + disappeared[rule]), rule))
    lines: list[str] = []
    if changed:
        lines += _table(
            _headers("rule", "files", "findings", "appeared", "disappeared"),
            [(rule, *now.get(rule, (0, 0)), appeared[rule], disappeared[rule])
             for rule in changed],
        )
        limit = report.COMPACT_FINDINGS_LIMIT
        if len(changes.appeared) + len(changes.disappeared) <= limit:
            lines += _listing(changes, changed)
        else:
            lines.append(i18n.t("rundiff.too-many", limit=limit, path=path))
    lines += [_left_out(key, names, count) for key, names, count in changes.skipped]
    if changed:
        head = i18n.t("rundiff.changed", path=path, appeared=len(changes.appeared),
                      disappeared=len(changes.disappeared))
    else:
        head = i18n.t("rundiff.same", path=path)
    lines.append(f"{head}. {_totals(diagnostics, len(rows), checked, suppressed)}")
    return lines


def _headers(*names: str) -> tuple[str, ...]:
    return tuple(i18n.t(f"rundiff.head-{name}") for name in names)


def _table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    """Rows under a header: the first column to the left, the numbers to the right."""
    cells = [header, *(tuple(str(cell) for cell in row) for row in rows)]
    widths = [max(len(row[n]) for row in cells) for n in range(len(header))]
    return [
        "  ".join([row[0].ljust(widths[0]),
                   *(cell.rjust(width) for cell, width in zip(row[1:], widths[1:]))])
        for row in cells
    ]


def _totals(
    diagnostics: list[Diagnostic], rules: int, checked: int, suppressed: int | None,
) -> str:
    fields = {"findings": len(diagnostics), "rules": rules,
              "files": len({d.path for d in diagnostics}), "checked": checked}
    if suppressed is None:
        return i18n.t("rundiff.totals", **fields)
    return i18n.t("rundiff.totals-baseline", suppressed=suppressed, **fields)


def _listing(changes: Changes, order: list[str]) -> list[str]:
    """The changed findings, rule by rule in the order of the table, then by place.

    At one place the finding that went comes before the one that came, so a finding whose
    text changed reads as a pair.
    """
    rank = {rule: n for n, rule in enumerate(order)}
    marked = [("-", f) for f in changes.disappeared] + [("+", f) for f in changes.appeared]
    marked.sort(key=lambda item: (rank[item[1][4]], item[1][:4], item[0] == "+", item[1][5]))
    return [
        f"{sign} {PurePosixPath(f[0], f[1]).as_posix()}:{f[2]}:{f[3]}: [{f[4]}] {f[5]}"
        for sign, f in marked
    ]


def _left_out(key: str, names: list[str], count: int) -> str:
    shown = ", ".join(names[:NAMES_SHOWN])
    if len(names) > NAMES_SHOWN:
        shown += " " + i18n.t("rundiff.more", count=len(names) - NAMES_SHOWN)
    return i18n.t(key, names=shown, count=count)


# --- the saved file ------------------------------------------------------------------------


def save(path: Path, run: Run, changes: Changes | None) -> None:
    """Write the run: its header, the changes against the run before it, then the findings.

    One finding per line, the changes first: past the listing limit this file is where the
    reader goes for the list, and its first screen is what changed.
    """
    head = {
        "meta": {"tool": "xbsl", "kind": KIND, "format": FORMAT, "note": _NOTE},
        "engine": run.engine, "lang": run.lang, "corpora": run.corpora,
        "checked": run.checked, "selection": run.selection,
    }
    parts = [f" {_json(key)}: {_json(value)}" for key, value in head.items()]
    if changes is None:
        parts.append(' "changes": null')
    else:
        parts.append(' "changes": {\n'
                     f'  "appeared": {_rows(changes.appeared, 3)},\n'
                     f'  "disappeared": {_rows(changes.disappeared, 3)}\n'
                     ' }')
    parts.append(f' "rules": {_json(run.rules)}')
    parts.append(f' "findings": {_rows(run.findings, 2)}')
    path.write_text("{\n" + ",\n".join(parts) + "\n}\n", encoding="utf-8", newline="\n")


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _rows(rows: list[Finding], indent: int) -> str:
    if not rows:
        return "[]"
    return ("[\n" + ",\n".join(" " * indent + _json(list(row)) for row in rows)
            + "\n" + " " * (indent - 1) + "]")


def load(path: Path, lang: str) -> Run | None:
    """The run saved in `path`, or None when there is none yet: no file, or an empty one.

    RunStateError when the file cannot be compared with: it is not a run saved by this tool,
    and writing over it would destroy it, or it was saved in another language.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise RunStateError(i18n.t("rundiff.not-a-run", path=path)) from exc
    if not text.strip():
        return None
    try:
        run = _parse(json.loads(text))
    except ValueError as exc:
        raise RunStateError(i18n.t("rundiff.not-a-run", path=path)) from exc
    if run.lang != lang:
        raise RunStateError(
            i18n.t("rundiff.other-language", path=path, saved=run.lang, lang=lang)
        )
    return run


def _parse(data) -> Run:
    """The Run of a loaded file; ValueError when the file does not hold one."""
    def expect(ok: bool) -> None:
        if not ok:
            raise ValueError("not a saved run")

    expect(isinstance(data, dict) and isinstance(data.get("meta"), dict))
    meta = data["meta"]
    expect((meta.get("tool"), meta.get("kind"), meta.get("format")) == ("xbsl", KIND, FORMAT))
    corpora, rows, rules = data.get("corpora"), data.get("findings"), data.get("rules")
    expect(isinstance(corpora, list) and all(isinstance(c, str) for c in corpora))
    expect(isinstance(rows, list) and all(_is_finding(row) for row in rows))
    expect(isinstance(rules, dict) and all(isinstance(on, bool) for on in rules.values()))
    expect(isinstance(data.get("selection"), dict) and isinstance(data.get("lang"), str)
           and isinstance(data.get("checked"), int))
    return Run(
        corpora=corpora, findings=[tuple(row) for row in rows], checked=data["checked"],
        lang=data["lang"], selection=data["selection"], rules=rules,
        engine=str(data.get("engine", "")),
    )


def _is_finding(row) -> bool:
    return (isinstance(row, list) and len(row) == 6
            and all(isinstance(row[n], str) for n in (0, 1, 4, 5))
            and all(isinstance(row[n], int) for n in (2, 3)))
