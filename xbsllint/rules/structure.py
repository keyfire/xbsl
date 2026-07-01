"""Тир A: структурные проверки файлов (без разбора кода)."""

from __future__ import annotations

from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule


@rule("structure/xbsl-pair", "Модуль .xbsl без парного .yaml", "A", severity=Severity.WARNING)
def xbsl_pair(source: SourceFile) -> Iterable[Diagnostic]:
    # Модуль (.xbsl) – это код элемента, описанного парным .yaml. Одиночный .xbsl осиротел.
    # Проверка о файлах на диске: для контента в памяти (lint_source) парность не проверяем.
    if source.kind != "xbsl" or not source.path.exists():
        return
    yaml_path = source.path.with_suffix(".yaml")
    if not yaml_path.exists():
        yield Diagnostic(
            source.rel, 1, 1, "structure/xbsl-pair", Severity.WARNING,
            f"Нет парного описания {yaml_path.name} для модуля.",
        )
