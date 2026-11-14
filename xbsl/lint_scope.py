"""Git-based selection of which findings are shown after a full lint run."""

from __future__ import annotations

from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic


def changed_paths(paths: list[str], revision: str) -> set[Path]:
    """Read the Git change in the repositories that contain the requested paths."""
    from xbsl.translation.entries import _git

    roots: set[Path] = set()
    changed: set[Path] = set()
    requested = {Path(name).resolve() for name in paths}
    directories = {path if path.is_dir() else path.parent for path in requested}
    for directory in sorted(directories):
        code, top, _ = _git(directory, "rev-parse", "--show-toplevel")
        if code:
            raise ValueError(i18n.t("translate.since.not-a-repo", path=directory))
        root = Path(top.strip()).resolve()
        if root in roots:
            continue
        roots.add(root)
        code, target, _ = _git(root, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}")
        if code:
            raise ValueError(i18n.t("translate.since.unknown-rev", rev=revision))
        code, base, error = _git(root, "merge-base", "HEAD", target.strip())
        if code:
            raise ValueError(i18n.t("translate.since.diff-failed", rev=revision, error=error.strip()))
        code, listing, error = _git(root, "diff", "--name-only", "-z", "--no-ext-diff",
                                    "--diff-filter=ACMRTUXB", base.strip(), "--")
        if code:
            raise ValueError(i18n.t("translate.since.diff-failed", rev=revision, error=error.strip()))
        code, untracked, error = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
        if code:
            raise ValueError(i18n.t("translate.since.diff-failed", rev=revision, error=error.strip()))
        changed.update((root / name).resolve() for name in (listing + untracked).split("\0") if name)
    return changed


def filter_diagnostics(diagnostics: list[Diagnostic], paths: set[Path]) -> list[Diagnostic]:
    """Select findings whose reported path belongs to the change."""
    return [d for d in diagnostics if Path(d.path).resolve() in paths]


def counts(revision: str, changed: set[Path], files: list[Path], total: int, shown: int) -> dict:
    return {
        "ref": revision,
        "changed_files": len(changed.intersection(path.resolve() for path in files)),
        "other_diagnostics": total - shown,
    }
