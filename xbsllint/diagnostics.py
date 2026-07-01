"""Модель диагностик линтера."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    """Одно замечание линтера, привязанное к позиции в файле.

    Строка и колонка – 1-индексированные (как в редакторах и в выводе компиляторов).
    """

    path: str
    line: int
    col: int
    rule_id: str
    severity: Severity
    message: str

    def format(self) -> str:
        # Формат, дружелюбный к переходу по клику: path:line:col
        return f"{self.path}:{self.line}:{self.col}: {self.severity.value}: [{self.rule_id}] {self.message}"

    # Сортировка замечаний по месту возникновения
    def sort_key(self) -> tuple:
        return (self.path, self.line, self.col, self.rule_id)
