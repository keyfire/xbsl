"""The linter's diagnostic model."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class TextEdit:
    """A replacement of source.text[start:end] with `new`, in character offsets.

    Offsets index the decoded text of the SAME file the diagnostic belongs to (newlines
    kept as-is). A rule attaches one to a diagnostic when the fix is mechanical and
    unambiguous; --fix applies non-overlapping edits and rewrites the file.
    """

    start: int
    end: int
    new: str


@dataclass(frozen=True)
class Diagnostic:
    """A single linter diagnostic, anchored to a position in a file.

    Line and column are 1-based (as in editors and compiler output). `fix` is present only
    for rules that can repair the finding automatically (see TextEdit).
    """

    path: str
    line: int
    col: int
    rule_id: str
    severity: Severity
    message: str
    fix: TextEdit | None = None

    def format(self) -> str:
        # A click-to-jump friendly format: path:line:col
        return f"{self.path}:{self.line}:{self.col}: {self.severity.value}: [{self.rule_id}] {self.message}"

    # Sort diagnostics by where they occur
    def sort_key(self) -> tuple:
        return (self.path, self.line, self.col, self.rule_id)
