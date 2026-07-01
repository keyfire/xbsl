"""MCP-адаптер линтера (тонкая обёртка над xbsllint.engine).

Запуск: xbsllint-mcp  (или python -m xbsllint.mcp_server). Транспорт – stdio.
Зависимость `mcp` ставится через extra:  pip install "xbsllint[mcp]".

Регистрация в Claude Code:
    claude mcp add xbsllint -- xbsllint-mcp
"""

from __future__ import annotations

from pathlib import Path

from xbsllint.cli import discover
from xbsllint.diagnostics import Diagnostic
from xbsllint.engine import RULES, load_text, run, run_sources

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError as exc:  # pragma: no cover - подсказка при отсутствии зависимости
    raise SystemExit(
        "Не найден пакет 'mcp'. Установите MCP-зависимости: pip install \"xbsllint[mcp]\""
    ) from exc


mcp = FastMCP("xbsllint")


def _diag_dict(d: Diagnostic) -> dict:
    return {
        "path": d.path,
        "line": d.line,
        "col": d.col,
        "rule": d.rule_id,
        "severity": d.severity.value,
        "message": d.message,
    }


def _summary(diags: list[Diagnostic], n_files: int) -> dict:
    return {
        "files": n_files,
        "diagnostics": len(diags),
        "errors": sum(1 for d in diags if d.severity.value == "error"),
        "warnings": sum(1 for d in diags if d.severity.value == "warning"),
    }


def _as_set(value: list[str] | None) -> set[str] | None:
    return set(value) if value else None


@mcp.tool()
def list_rules() -> list[dict]:
    """Список доступных правил линтера (id, заголовок, тир, область, severity)."""
    return [r.as_dict() for r in sorted(RULES, key=lambda x: (x.tier, x.id))]


@mcp.tool()
def lint_paths(
    paths: list[str],
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> dict:
    """Проверить файлы/каталоги на диске.

    paths  – список путей (файлы .xbsl/.yaml или каталоги, обход рекурсивный);
    select – ограничить набор правил (id или буква тира A/B/C/D);
    ignore – исключить правила.
    Возвращает {diagnostics: [...], summary: {...}}.
    """
    files = discover(paths)
    diags = run(files, select=_as_set(select), ignore=_as_set(ignore))
    diags = sorted(diags, key=lambda x: x.sort_key())
    return {"diagnostics": [_diag_dict(d) for d in diags], "summary": _summary(diags, len(files))}


@mcp.tool()
def lint_source(
    filename: str,
    content: str,
    select: list[str] | None = None,
    ignore: list[str] | None = None,
) -> dict:
    """Проверить содержимое в памяти (напр. перед записью файла).

    filename – имя с расширением (.xbsl/.yaml), определяет тип и участвует в позициях;
    content  – текст исходника.
    Выполняются только пофайловые правила (кросс-файловым нужен весь проект).
    """
    src = load_text(filename, content)
    diags = run_sources(
        [src], select=_as_set(select), ignore=_as_set(ignore), scopes=("file",)
    )
    diags = sorted(diags, key=lambda x: x.sort_key())
    return {"diagnostics": [_diag_dict(d) for d in diags], "summary": _summary(diags, 1)}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
