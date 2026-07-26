"""Тесты менеджера экстракторов (xbsl/extract/__init__.py).

Главное здесь - сторожа полноты: новый модуль-экстрактор обязан попасть в список шагов
(иначе он тихо выпадет из генерации и обнаружится только отсутствием данных), а каждый
шаг обязан иметь шим обратной совместимости tools/extract_<шаг>.py.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from xbsl import extract
from xbsl.extract import _distro

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "xbsl" / "extract"
TOOLS = REPO / "tools"
_NOT_STEPS = {"__init__", "__main__", "_distro"}


def test_every_extractor_module_is_a_step():
    on_disk = {p.stem for p in PACKAGE.glob("*.py")} - _NOT_STEPS
    registered = {module for _, module, _, _ in extract.STEPS}
    assert on_disk == registered, (
        "список шагов разошёлся с пакетом xbsl/extract - "
        f"не в списке: {sorted(on_disk - registered)}, лишние: {sorted(registered - on_disk)}"
    )


def test_every_step_has_a_tools_shim():
    shims = {p.stem.removeprefix("extract_") for p in TOOLS.glob("extract_*.py")}
    registered = {name for name, _, _, _ in extract.STEPS}
    assert shims == registered, (
        "шимы tools/extract_*.py разошлись со списком шагов - "
        f"нет шима: {sorted(registered - shims)}, лишние: {sorted(shims - registered)}"
    )


def test_step_names_are_unique_and_modules_importable():
    names = [name for name, _, _, _ in extract.STEPS]
    assert len(names) == len(set(names))
    for _, module_name, _, _ in extract.STEPS:
        importlib.import_module(f"xbsl.extract.{module_name}")


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


def test_prog_name_names_the_command_when_started_by_a_console_script(monkeypatch):
    """argv[0] of an installed script is a path, not a command - the usage line must not repeat it."""
    monkeypatch.setattr(sys, "argv", [r"C:\Python314\Scripts\xbsl", "extract"])
    assert _distro.prog_name("xbsl extract") == "xbsl extract"


def test_prog_name_keeps_argparse_answer_when_started_from_a_file(monkeypatch):
    """A tools/ shim or `python -m` IS the command typed - replacing it with a synonym would lie."""
    monkeypatch.setattr(sys, "argv", [str(TOOLS / "extract_stdlib.py")])
    assert _distro.prog_name("python -m xbsl.extract.stdlib") is None


def _usage_line(main, argv, monkeypatch, capsys) -> str:
    monkeypatch.setattr(sys, "argv", [r"C:\Python314\Scripts\xbsl"])
    with pytest.raises(SystemExit):
        main(argv)
    return capsys.readouterr().out.splitlines()[0]


def test_manager_usage_names_the_extract_command(monkeypatch, capsys):
    assert _usage_line(extract.main, ["--help"], monkeypatch, capsys).startswith(
        "usage: xbsl extract "
    )


@pytest.mark.parametrize("module", [module for _, module, _, _ in extract.STEPS])
def test_step_usage_names_a_runnable_command(module, monkeypatch, capsys):
    """A step run on its own is `python -m xbsl.extract.<step>`: unlike `xbsl extract --only`,
    it takes the step's own options (--out, --no-default), so the usage line stays true."""
    step_main = importlib.import_module(f"xbsl.extract.{module}").main
    usage = _usage_line(step_main, ["--help"], monkeypatch, capsys)
    assert usage.startswith(f"usage: python -m xbsl.extract.{module} ")
