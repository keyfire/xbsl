"""Тир B: проектные конвенции.

Запрет номеров задач в исходном коде и комментариях: номер задачи несёт ветка,
в коде идентификаторов вида SITE-482 / MC-17950 быть не должно (CLAUDE.md, память владельца).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from xbsllint.diagnostics import Diagnostic, Severity
from xbsllint.engine import SourceFile, rule
from xbsllint.lexer import linemap, tokens

# Известные префиксы трекера задач проекта. Узкий шаблон, чтобы не ловить UTF-8, RFC-822 и т.п.
_TASK_RE = re.compile(r"\b(?:SITE|MC)-\d+\b")


@rule("conventions/task-number", "Номер задачи в коде/комментарии", "B", severity=Severity.WARNING)
def task_number(source: SourceFile) -> Iterable[Diagnostic]:
    if source.kind != "xbsl":
        return
    lm = linemap(source)
    for tok in tokens(source):
        if tok.kind not in ("COMMENT", "STRING"):
            continue
        for m in _TASK_RE.finditer(tok.value):
            line, col = lm.linecol(tok.start + m.start())
            yield Diagnostic(
                source.rel, line, col, "conventions/task-number", Severity.WARNING,
                f"Номер задачи {m.group(0)} в исходнике – номер несёт ветка, в коде его быть не должно.",
            )
