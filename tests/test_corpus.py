"""Инвариант: корпус сайта проходит линтер без замечаний по умолчанию.

Тест пропускается, если репозиторий сайта недоступен (переносимость).
Путь можно переопределить переменной окружения XBSLLINT_CORPUS.
"""

import os
from pathlib import Path

import pytest

from xbsllint import engine
from xbsllint.cli import discover

_CORPUS = Path(os.environ.get("XBSLLINT_CORPUS", r"D:\Repos\site\e1c\site"))


@pytest.mark.skipif(not _CORPUS.exists(), reason="корпус сайта недоступен")
def test_corpus_no_errors_and_only_known_warnings():
    # Корпус – валидный задеплоенный код: ошибок линтера быть не должно. Допустимы только
    # известные находки code/unused-loop-var (их же выдаёт серверная компиляция); любое
    # другое срабатывание на корпусе – признак ложного и должно ловиться тестом.
    diags = engine.run(discover([str(_CORPUS)]))
    errors = [d for d in diags if d.severity.value == "error"]
    assert not errors, f"неожиданные ошибки: {[d.format() for d in errors[:5]]}"
    unexpected = [d for d in diags if d.rule_id != "code/unused-loop-var"]
    assert not unexpected, f"неожиданные замечания: {[d.format() for d in unexpected[:5]]}"
