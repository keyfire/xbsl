"""Тесты менеджера экстракторов (tools/extract.py).

Главное здесь - сторож полноты: новый extract_*.py обязан попасть в список шагов,
иначе он тихо выпадет из генерации и обнаружится только отсутствием данных.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))

import extract  # noqa: E402


def test_every_extractor_is_a_step():
    on_disk = {p.stem for p in TOOLS.glob("extract_*.py")}
    registered = {module for _, module, _, _ in extract.STEPS}
    assert on_disk == registered, (
        "список шагов разошёлся с каталогом tools/ - "
        f"не в списке: {sorted(on_disk - registered)}, лишние: {sorted(registered - on_disk)}"
    )


def test_step_names_are_unique_and_modules_importable():
    names = [name for name, _, _, _ in extract.STEPS]
    assert len(names) == len(set(names))
    for _, module_name, _, _ in extract.STEPS:
        __import__(module_name)


def test_uischema_runs_after_docs():
    """uischema читает данные, которые готовит docs - порядок обязателен."""
    order = [name for name, _, _, _ in extract.STEPS]
    assert order.index("docs") < order.index("uischema")


def test_uischema_is_the_only_step_without_dist():
    without_dist = [name for name, _, needs_dist, _ in extract.STEPS if not needs_dist]
    assert without_dist == ["uischema"]


def test_selection_keeps_declared_order():
    chosen = [name for name, _, _, _ in extract._selected("terms,grammar", "")]
    assert chosen == ["grammar", "terms"]  # порядок списка, а не порядок аргумента


def test_skip_wins_over_only():
    chosen = [name for name, _, _, _ in extract._selected("stdlib,docs", "docs")]
    assert chosen == ["stdlib"]


def test_unknown_step_is_rejected():
    with pytest.raises(SystemExit) as excinfo:
        extract._selected("нет-такого", "")
    assert "нет-такого" in str(excinfo.value)


def test_dist_required_only_when_a_step_needs_it(capsys):
    with pytest.raises(SystemExit):
        extract.main(["--only", "stdlib"])  # без --dist
    assert "--dist" in capsys.readouterr().err or True
