"""Apply the mechanical fixes a rule attached to its findings (--fix).

A fixable finding carries either a span edit (Diagnostic.fix, a TextEdit into the file's
decoded text) or, for whole-file rules like whitespace/mixed-newline, no span edit - the
fixer recognizes it by id and normalizes newlines. Only unambiguous, reversible mechanical
fixes are attached (whitespace, typography, redundant casts and other code edits); anything
that needs judgment is left to the author.

The edits of one file are applied together: overlapping spans are resolved deterministically
(earliest start wins, ties by longest span), the survivors applied last-to-first so offsets
stay valid, and the result re-encoded preserving the original BOM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from xbsl.diagnostics import Diagnostic
from xbsl.engine import SourceFile

# Rules fixed over the whole file rather than by a span edit.
_MIXED_NEWLINE = "whitespace/mixed-newline"
FULL_FILE_FIX_RULES = frozenset({_MIXED_NEWLINE})

_NEWLINE_RE = re.compile(r"\r\n|\r|\n")


@dataclass
class FixResult:
    text: str            # the fixed text
    applied: int         # number of findings actually fixed
    changed: bool        # text differs from the original


def is_fixable(diag: Diagnostic) -> bool:
    return diag.fix is not None or diag.rule_id in FULL_FILE_FIX_RULES


def _dominant_newline(text: str) -> str:
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    # Prefer CRLF, then LF, then CR on ties - a stable, platform-neutral order.
    return max((("\r\n", crlf), ("\n", lf), ("\r", cr)), key=lambda kv: kv[1])[0]


def _select_edits(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Non-overlapping span-fix diagnostics: earliest start wins, ties by longest span."""
    spans = sorted(
        (d for d in diags if d.fix is not None),
        key=lambda d: (d.fix.start, -(d.fix.end - d.fix.start)),
    )
    chosen: list[Diagnostic] = []
    last_end = -1
    for d in spans:
        if d.fix.start >= last_end:
            chosen.append(d)
            last_end = d.fix.end
    return chosen


def fix_source(source: SourceFile, diags: list[Diagnostic]) -> FixResult:
    """Compute the fixed text for one file from its diagnostics (does not write to disk)."""
    text = source.text
    edits = _select_edits(diags)
    for d in sorted(edits, key=lambda d: d.fix.start, reverse=True):
        text = text[: d.fix.start] + d.fix.new + text[d.fix.end :]
    applied = len(edits)

    if any(d.rule_id == _MIXED_NEWLINE for d in diags):
        # Newlines may be offset by the span edits above; recompute the dominant style on the
        # edited text (span edits never touch line breaks, so the dominant style is unchanged).
        nl = _dominant_newline(text)
        normalized = _NEWLINE_RE.sub(nl, text)
        if normalized != text:
            text = normalized
        applied += 1

    return FixResult(text=text, applied=applied, changed=text != source.text)


def encode(source: SourceFile, text: str) -> bytes:
    """Encode the fixed text back to bytes, preserving the original UTF-8 BOM."""
    return text.encode("utf-8-sig" if source.had_bom else "utf-8")


@dataclass
class _AcceptedOccurrence:
    original: Diagnostic
    anchor: int
    start: int
    end: int


def fix_paths(
    files: list[Path], *, select=None, ignore=None, enable=None,
    requested: list[Path] | None = None, baseline_path: Path | None = None,
) -> tuple[list[Diagnostic], dict[str, int], list[tuple[Diagnostic, Diagnostic]]]:
    """Apply fixes in bounded passes and return final diagnostics, counts and frozen matches.

    Baseline occurrences are pinned before writing. Their anchors and protected spans move
    with edits; later findings cannot spend their budgets, and messages with changing line
    numbers remain accepted. The third return value pairs current and original diagnostics
    for baseline.apply, so adapters retain the same decisions in their final reports.
    """
    from xbsl import baseline, engine

    data = baseline.load(baseline_path, strict=True) if baseline_path is not None else None
    wanted = {p.resolve() for p in requested} if requested is not None else None
    # The context of a list run feeds the project rules only (engine.run_sources).
    context = (frozenset(p for p in files if p.resolve() not in wanted)
               if wanted is not None else None)
    fixed = 0
    changed: set[Path] = set()
    frozen: list[_AcceptedOccurrence] = []
    for iteration in range(11):
        sources = [engine.load(path) for path in files]
        starts = {source.rel: [0] + [m.end() for m in _NEWLINE_RE.finditer(source.text)]
                  for source in sources}

        def offset(diagnostic: Diagnostic) -> int:
            lines = starts[diagnostic.path]
            return lines[min(diagnostic.line - 1, len(lines) - 1)] + diagnostic.col - 1

        diagnostics = engine.run_sources(
            sources, select=select, ignore=ignore, enable=enable, context=context,
        )
        if wanted is not None:
            diagnostics = [d for d in diagnostics if Path(d.path).resolve() in wanted]
        if iteration == 0 and data is not None:
            eligible = {id(d) for d in baseline.apply(diagnostics, data, baseline_path.parent)[0]}
            for diagnostic in diagnostics:
                if id(diagnostic) not in eligible:
                    anchor = offset(diagnostic)
                    edit = diagnostic.fix
                    frozen.append(_AcceptedOccurrence(
                        diagnostic, anchor, edit.start if edit else anchor,
                        edit.end if edit else anchor + 1,
                    ))
        available = {}
        for occurrence in frozen:
            key = (occurrence.original.path, occurrence.original.rule_id, occurrence.anchor)
            available.setdefault(key, []).append(occurrence)
        accepted = []
        for diagnostic in diagnostics:
            matches = available.get((diagnostic.path, diagnostic.rule_id, offset(diagnostic)), [])
            if matches:
                accepted.append((diagnostic, matches.pop(0).original))
        if iteration == 10:
            break
        accepted_ids = {id(current) for current, original in accepted}
        by_path: dict[str, list[Diagnostic]] = {}
        for diagnostic in diagnostics:
            if id(diagnostic) not in accepted_ids:
                by_path.setdefault(diagnostic.path, []).append(diagnostic)
        progress = False
        for source in sources:
            own = by_path.get(source.rel, [])
            protected = [f for f in frozen if f.original.path == source.rel]
            if protected:
                spans = [(f.start, max(f.end, f.start + 1)) for f in protected]
                spans.extend((f.anchor, f.anchor + 1) for f in protected)
                if any(f.original.rule_id in FULL_FILE_FIX_RULES for f in protected):
                    spans = [(0, len(source.text))]
                own = [d for d in own if d.fix is not None and not any(
                    (d.fix.start < end and d.fix.end > start)
                    or (d.fix.start == d.fix.end and start <= d.fix.start < end)
                    for start, end in spans
                )]
            result = fix_source(source, own)
            if result.changed:
                edits = [d.fix for d in _select_edits(own)]

                def moved(position: int) -> int:
                    return position + sum(len(edit.new) - (edit.end - edit.start)
                                          for edit in edits if edit.end <= position)

                source.path.write_bytes(encode(source, result.text))
                for occurrence in protected:
                    occurrence.anchor = moved(occurrence.anchor)
                    occurrence.start = moved(occurrence.start)
                    occurrence.end = moved(occurrence.end)
                changed.add(source.path)
                fixed += result.applied
                progress = True
        if not progress:
            break
    if requested is not None:
        # The run went over resolved paths (cli.discover_with_context); the report names the
        # files as they were asked for. The findings are already narrowed to those files, so
        # the two lists align one to one, and the pinned pairs follow their current finding.
        narrowed = engine.narrow_to_requested(diagnostics, requested)
        renamed = {id(old): new for old, new in zip(diagnostics, narrowed)}
        accepted = [(renamed.get(id(current), current), original)
                    for current, original in accepted]
        diagnostics = narrowed
    return diagnostics, {"fixed": fixed, "files_changed": len(changed)}, accepted
