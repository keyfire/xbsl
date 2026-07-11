"""Инвариант: реальный корпус проходит линтер без замечаний по умолчанию.

Тест пропускается, если корпус недоступен (переносимость).
Путь задаётся переменной окружения XBSLLINT_CORPUS.
"""

import os
from pathlib import Path

import pytest

from xbsllint import engine
from xbsllint.cli import discover

_CORPUS = os.environ.get("XBSLLINT_CORPUS")


# Правила, чьи находки на корпусе допустимы: это НАСТОЯЩИЕ находки, а не ложные.
# code/unused-loop-var – их же выдаёт серверная компиляция; code/unused-method – корпус
# сейчас несёт мёртвый обработчик, ожидающий чистки на стороне проекта. Любое срабатывание
# ДРУГОГО правила на корпусе – признак ложного и должно ловиться этим тестом.
_KNOWN_FINDING_RULES = {"code/unused-loop-var", "code/unused-method"}


@pytest.mark.skipif(not (_CORPUS and Path(_CORPUS).exists()), reason="корпус недоступен (задайте XBSLLINT_CORPUS)")
def test_corpus_no_errors_and_only_known_warnings():
    # Корпус – валидный задеплоенный код: ошибок линтера быть не должно.
    diags = engine.run(discover([str(_CORPUS)]))
    errors = [d for d in diags if d.severity.value == "error"]
    assert not errors, f"неожиданные ошибки: {[d.format() for d in errors[:5]]}"
    unexpected = [d for d in diags if d.rule_id not in _KNOWN_FINDING_RULES]
    assert not unexpected, f"неожиданные замечания: {[d.format() for d in unexpected[:5]]}"
