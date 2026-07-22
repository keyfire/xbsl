"""The linter core: source loading, the rule registry and the run.

Rules register themselves with the @rule(...) decorator (id, tier, severity, scope). Scope:
- 'file'    – per-file rule: (SourceFile) -> Iterable[Diagnostic];
- 'project' – cross-file rule (e.g. Ид uniqueness): (list[SourceFile]) -> Iterable[Diagnostic].

Tiers: 'A' structure/YAML, 'B' text/conventions, 'C' parser/code structure, 'D' semantics.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity

UTF8_BOM = b"\xef\xbb\xbf"


@dataclass
class SourceFile:
    path: Path
    kind: str  # 'xbsl' | 'yaml'
    data: bytes
    text: str
    had_bom: bool
    newline: str  # '\n', '\r\n', '\r', 'mixed', or '' when there are no line breaks
    decode_error: str | None = None
    # Cache of the expensive representations (tokens, AST, YAML) – filled on demand
    cache: dict = field(default_factory=dict)

    @property
    def rel(self) -> str:
        return str(self.path)


def _detect_newline(data: bytes) -> str:
    crlf = data.count(b"\r\n")
    cr = data.count(b"\r") - crlf
    lf = data.count(b"\n") - crlf
    kinds = [k for k, n in (("\r\n", crlf), ("\r", cr), ("\n", lf)) if n]
    if not kinds:
        return ""
    if len(kinds) > 1:
        return "mixed"
    return kinds[0]


def make_source(path: Path, data: bytes) -> SourceFile:
    """Build a SourceFile from a path and bytes (shared by the disk and memory paths)."""
    kind = "xbsl" if path.suffix == ".xbsl" else "yaml"
    had_bom = data.startswith(UTF8_BOM)
    decode_error: str | None = None
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        decode_error = str(exc)
        text = data.decode("utf-8", errors="replace")
    return SourceFile(
        path=path,
        kind=kind,
        data=data,
        text=text,
        had_bom=had_bom,
        newline=_detect_newline(data),
        decode_error=decode_error,
    )


def load(path: Path) -> SourceFile:
    return make_source(path, path.read_bytes())


def load_text(name: str, content: str) -> SourceFile:
    """Build a SourceFile from in-memory content (for the MCP lint_source tool)."""
    return make_source(Path(name), content.encode("utf-8"))


def find_sources(root: Path, pattern: str) -> list[Path]:
    """Files matching the pattern under the root, skipping hidden directories and files.

    Dot-directories hold service copies of the sources (git worktrees under `.claude/`,
    `.git` itself, caches) that poison project-scope rules with false cross-file findings
    such as duplicated `Ид`. Components are checked relative to the root, so a root that
    itself lives inside a hidden directory (an opened worktree) is scanned normally.
    """
    result: list[Path] = []
    for f in root.rglob(pattern):
        rel = f.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        result.append(f)
    return sorted(result)


# --- Rule registry -------------------------------------------------------------------

FileRuleFn = Callable[[SourceFile], Iterable[Diagnostic]]
ProjectRuleFn = Callable[[list[SourceFile]], Iterable[Diagnostic]]


@dataclass(frozen=True)
class RuleInfo:
    id: str
    title_key: str
    tier: str  # 'A' | 'B' | 'C' | 'D'
    scope: str  # 'file' | 'project'
    severity: Severity
    func: Callable
    enabled_by_default: bool = True
    # Map-reduce for a project rule: mapper(source) -> a small picklable per-file fact
    # (None = the file contributes nothing). The rule func then takes {rel: fact} instead
    # of the source list. In a parallel run the mapper executes inside the FILE workers
    # (where the AST is already cached), the reduce runs in the parent - such a rule
    # never joins a project group and stops paying the whole-project preparation.
    mapper: Callable | None = None

    @property
    def title(self) -> str:
        """Translated at read time: the output language may be set after registration."""
        return i18n.t(self.title_key)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tier": self.tier,
            "scope": self.scope,
            "severity": self.severity.value,
            "enabled_by_default": self.enabled_by_default,
        }


RULES: list[RuleInfo] = []


def rule(
    rule_id: str,
    title: str,
    tier: str,
    *,
    scope: str = "file",
    severity: Severity = Severity.WARNING,
    enabled_by_default: bool = True,
    mapper: Callable | None = None,
) -> Callable[[Callable], Callable]:
    """Register a rule with its metadata.

    `title` is a catalog key (`<rule id>.title`); a literal string still works and is used
    verbatim, which keeps plugins written against 0.3 running. A project rule may pass
    `mapper` to run map-reduce style (see RuleInfo.mapper); its func then receives
    `{rel: fact}` instead of the source list.
    """

    def deco(fn: Callable) -> Callable:
        RULES.append(RuleInfo(
            rule_id, title, tier, scope, severity, fn, enabled_by_default, mapper,
        ))
        return fn

    return deco


# Rule id -> effective severity from plugin overrides ("off" entries end up as
# enabled_by_default=False in RULES and are not listed here). Diagnostics carry the
# severity their rule baked in at yield time, so run_sources() recolors them by this map.
SEVERITY_OVERRIDES: dict[str, Severity] = {}

_LEVEL_OFF = "off"


#: Whether plugin overrides have been applied to a COMPLETE registry (see _ensure_overrides).
_overrides_applied = False


def _ensure_overrides() -> None:
    """Apply the overrides if the import-time attempt happened on a partial registry.

    Importing a single rule module (`from xbsl.rules.<name> import ...`) starts the rules
    package, whose first module imports the engine - so the engine's own import-time call
    sees only the rules registered so far and cannot tell a typo from a not-yet-imported
    rule. In that case the call is deferred to here, where the registry is complete.
    """
    if not _overrides_applied:
        apply_severity_overrides()


def apply_severity_overrides() -> None:
    """Apply plugin severity overrides to the registry (idempotent, called on import).

    An unknown rule id or level raises PluginError: a silently ignored override is a typo
    nobody notices, and the linter must not pretend the project's levels are in force.
    """
    global _overrides_applied
    overrides = _plugins.severity_overrides()
    _overrides_applied = True
    if not overrides:
        return
    by_id = {info.id: i for i, info in enumerate(RULES)}
    for rule_id, level in overrides.items():
        if rule_id not in by_id:
            raise _plugins.PluginError(
                f"Переопределение уровня для неизвестного правила '{rule_id}' "
                f"(группа {_plugins.SEVERITY_GROUP})"
            )
        idx = by_id[rule_id]
        if level == _LEVEL_OFF:
            RULES[idx] = replace(RULES[idx], enabled_by_default=False)
            SEVERITY_OVERRIDES.pop(rule_id, None)
            continue
        try:
            severity = Severity(level)
        except ValueError:
            raise _plugins.PluginError(
                f"Неизвестный уровень '{level}' для правила '{rule_id}' "
                f"(группа {_plugins.SEVERITY_GROUP}): допустимы "
                f"error/warning/info/off"
            ) from None
        RULES[idx] = replace(RULES[idx], severity=severity, enabled_by_default=True)
        SEVERITY_OVERRIDES[rule_id] = severity


def _is_selected(
    info: RuleInfo,
    select: set[str] | None,
    ignore: set[str] | None,
    enable: set[str] | None = None,
) -> bool:
    # select/ignore/enable match a rule id, a rule group (the part of the id before '/')
    # or a tier letter ('A'..'D')
    group = info.id.split("/", 1)[0]

    def matches(keys: set[str]) -> bool:
        return info.id in keys or group in keys or info.tier in keys

    if ignore and matches(ignore):
        return False
    if select:
        # An explicit selection enables a rule even when it is off by default
        return matches(select)
    if enable and matches(enable):
        # enable adds off-by-default rules ON TOP of the default set (select replaces it)
        return True
    return info.enabled_by_default


def active_rules(
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    enable: set[str] | None = None,
) -> list[RuleInfo]:
    _ensure_overrides()
    return [r for r in RULES if _is_selected(r, select, ignore, enable)]


def run_sources(
    sources: list[SourceFile],
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    enable: set[str] | None = None,
    scopes: tuple[str, ...] = ("file", "project"),
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    active = active_rules(select, ignore, enable)
    if "file" in scopes:
        file_rules = [r for r in active if r.scope == "file"]
        for src in sources:
            for r in file_rules:
                diags.extend(r.func(src))
    if "project" in scopes:
        for r in (r for r in active if r.scope == "project"):
            if r.mapper is not None:
                facts = {}
                for src in sources:
                    fact = r.mapper(src)
                    if fact is not None:
                        facts[src.rel] = fact
                diags.extend(r.func(facts))
            else:
                diags.extend(r.func(sources))
    if SEVERITY_OVERRIDES:
        diags = [
            replace(d, severity=SEVERITY_OVERRIDES[d.rule_id])
            if d.rule_id in SEVERITY_OVERRIDES and d.severity != SEVERITY_OVERRIDES[d.rule_id]
            else d
            for d in diags
        ]
    return diags


def run(
    paths: list[Path],
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    enable: set[str] | None = None,
) -> list[Diagnostic]:
    sources = [load(p) for p in paths]
    return run_sources(sources, select=select, ignore=ignore, enable=enable)


# --- parallel run ------------------------------------------------------------------------
#
# The file-scope rules are independent per file, so they shard across processes; the
# project-scope rules need every source at once and stay in the parent. Worth it only on
# big projects: on Windows every worker pays a spawn (a fresh interpreter + imports), so
# small runs are faster sequentially - the auto mode picks based on the file count.

_PARALLEL_MIN_FILES = 120


def _worker_lint(payload: tuple) -> tuple[list[Diagnostic], dict[str, dict[str, object]]]:
    """A worker task: the file rules on a shard of files OR a group of project rules
    over the whole project (kind == "project"; the rule ids arrive as a ready select).

    A file worker additionally runs the mappers of the map-reduce project rules
    (mapped_ids) over its shard - the AST/yaml caches are already warm there - and
    returns the facts as {rule_id: {rel: fact}}; the reduce runs in the parent."""
    kind, paths, select, ignore, enable, lang, element_version, mapped_ids = payload
    from xbsl import dataset, i18n

    i18n.set_lang(lang)
    if element_version:
        dataset.set_version(element_version)
    sources = [load(Path(p)) for p in paths]
    scopes = ("project",) if kind == "project" else ("file",)
    diags = run_sources(sources, select=select, ignore=ignore, enable=enable, scopes=scopes)
    facts: dict[str, dict[str, object]] = {}
    if kind == "file" and mapped_ids:
        by_id = {r.id: r for r in RULES if r.mapper is not None}
        for rule_id in mapped_ids:
            info = by_id.get(rule_id)
            if info is None:
                continue
            per_file: dict[str, object] = {}
            for src in sources:
                fact = info.mapper(src)
                if fact is not None:
                    per_file[src.rel] = fact
            facts[rule_id] = per_file
    return diags, facts


def resolve_jobs(jobs: int, file_count: int) -> int:
    """The worker count: 0 - auto (by run size and cores), 1 - sequential."""
    import math
    import os

    cpus = os.cpu_count() or 1
    if jobs == 0:
        if file_count < _PARALLEL_MIN_FILES or cpus < 4:
            return 1
        # Every worker pays a fixed cost F (the spawn, the imports, its own dataset
        # parse) against its share of the work W: the wall clock F*w + W/w bottoms
        # out near w = sqrt(W/F), and W grows with the file count - so cpus-1 workers
        # overshoot badly on mid-size runs. Measured on a 20-core machine: 253 files
        # ran best at ~4 workers (cpus-1 was 2x slower than sequential), ~1000 files
        # flat across 4..8, ~4000 files flat across 13..19; sqrt(files/25) tracks
        # those optima and is capped by the cores.
        return max(2, min(cpus - 1, round(math.sqrt(file_count / 25))))
    return max(1, min(jobs, cpus))


def run_parallel(
    paths: list[Path],
    *,
    select: set[str] | None = None,
    ignore: set[str] | None = None,
    enable: set[str] | None = None,
    jobs: int = 0,
    lang: str | None = None,
    element_version: str | None = None,
) -> list[Diagnostic]:
    """run() with the file rules sharded across processes.

    Diagnostics are sorted by (file, line, column) - the parallel and the sequential
    runs produce the same report.
    """
    workers = resolve_jobs(jobs, len(paths))
    if workers <= 1:
        diags = run(paths, select=select, ignore=ignore, enable=enable)
        return sorted(diags, key=lambda d: (d.path, d.line, d.col, d.rule_id))

    from concurrent.futures import ProcessPoolExecutor

    from xbsl import i18n

    lang = lang or i18n.current_lang()
    all_paths = [str(p) for p in paths]

    # Map-reduce project rules ride inside the FILE workers (mappers collect per-file
    # facts where the caches are already warm; the reduce runs here in the parent).
    # The rest of the project rules shard in groups: every group-worker loads the whole
    # project by itself (duplicated preparation, but the heaviest rules stop being the
    # sequential ceiling). Few groups: the preparation in each one is not free.
    active = active_rules(select, ignore, enable)
    mapped_rules = [r for r in active if r.scope == "project" and r.mapper is not None]
    mapped_ids = [r.id for r in mapped_rules]
    project_ids = [r.id for r in active if r.scope == "project" and r.mapper is None]
    # Few groups: every group pays the whole-project preparation (reading + parsing),
    # and that cost dominates - measured on the x10 corpus, 8 groups run twice as SLOW
    # as 4 (the preparations compete for the disk and the cores). The way to shrink the
    # ceiling further is migrating rules to mappers, not adding groups.
    group_count = min(4, workers, len(project_ids)) if project_ids else 0
    project_groups = [set(project_ids[i::group_count]) for i in range(group_count)]

    file_workers = max(1, workers - group_count)
    chunks = [[str(p) for p in paths[i::file_workers]] for i in range(file_workers)]
    payloads: list[tuple] = [
        ("file", chunk, select, ignore, enable, lang, element_version, mapped_ids)
        for chunk in chunks if chunk
    ]
    payloads += [
        ("project", all_paths, group, None, None, lang, element_version, ())
        for group in project_groups
    ]
    diags: list[Diagnostic] = []
    merged: dict[str, dict[str, object]] = {r.id: {} for r in mapped_rules}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part, facts in pool.map(_worker_lint, payloads):
            diags.extend(part)
            for rule_id, per_file in facts.items():
                merged[rule_id].update(per_file)
    for r in mapped_rules:
        diags.extend(r.func(merged[r.id]))
    if SEVERITY_OVERRIDES:
        diags = [
            replace(d, severity=SEVERITY_OVERRIDES[d.rule_id])
            if d.rule_id in SEVERITY_OVERRIDES and d.severity != SEVERITY_OVERRIDES[d.rule_id]
            else d
            for d in diags
        ]
    return sorted(diags, key=lambda d: (d.path, d.line, d.col, d.rule_id))


# Importing the rules package registers them (the decorators run on module import).
from xbsl import rules as _rules  # noqa: E402,F401
from xbsl import plugins as _plugins  # noqa: E402

# Rules of external packages come after the built-in ones, to keep the registry order stable.
_plugins.load_rules()
# Severity overrides come last: they may target both built-in and plugin rules. When the rules
# package is still being imported (someone imported a single rule module, so this module got a
# partially initialized package above), the registry is incomplete and an override could not be
# told from a typo - then it is applied later, on the first active_rules().
try:
    apply_severity_overrides()
except _plugins.PluginError:
    _overrides_applied = False
