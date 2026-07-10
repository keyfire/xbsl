"""Точка входа командной строки: xbsllint / python -m xbsllint."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from xbsllint import __version__, dataset


def discover(paths: list[str]) -> list[Path]:
    """Собрать файлы исходников (.xbsl и .yaml) по указанным путям."""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in (".xbsl", ".yaml"):
                out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.xbsl")))
            out.extend(sorted(p.rglob("*.yaml")))
    # Уникализируем, сохраняя порядок
    seen: set[Path] = set()
    uniq: list[Path] = []
    for f in out:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xbsllint",
        description="Линтер исходников 1С:Элемент (пары .yaml/.xbsl).",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="файлы или каталоги для проверки")
    parser.add_argument(
        "--select",
        metavar="ID/ГРУППА/ТИР",
        help="проверять только эти правила (через запятую: id, группа – часть id до '/' "
             "(напр. style) – или буква тира A/B/C/D)",
    )
    parser.add_argument(
        "--ignore",
        metavar="ID/ГРУППА/ТИР",
        help="исключить эти правила (через запятую: id, группа или буква тира)",
    )
    parser.add_argument(
        "--list-rules", action="store_true", help="вывести список правил и выйти"
    )
    parser.add_argument(
        "--element-version",
        metavar="ВЕРСИЯ",
        help="версия данных Элемента (по умолчанию – последняя из бандла)",
    )
    parser.add_argument(
        "--data-dir",
        metavar="КАТАЛОГ",
        help="корень данных Элемента (каталог с index.json); также env XBSLLINT_DATA_DIR",
    )
    data_note = ""
    try:
        data_note = (
            f" (данные Элемента: {dataset.default_version()}; "
            f"доступно: {', '.join(dataset.available_versions())})"
        )
    except dataset.DatasetError:
        pass
    parser.add_argument("--version", action="version", version=f"xbsllint {__version__}{data_note}")
    return parser


def _parse_set(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def main(argv: list[str] | None = None) -> int:
    # Вывод линтера всегда в UTF-8, независимо от кодировки консоли (важно для кириллицы
    # и для перенаправления в файл/редактор).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    if args.element_version:
        dataset.set_version(args.element_version)
    try:
        dataset.resolve_version()  # проверить доступность выбранной версии данных
    except dataset.DatasetError as exc:
        print(f"Ошибка данных Элемента: {exc}", file=sys.stderr)
        return 2

    from xbsllint.engine import RULES, run

    if args.list_rules:
        for r in sorted(RULES, key=lambda x: (x.tier, x.id)):
            mark = "   " if r.enabled_by_default else "off"
            print(f"{r.tier} {mark} {r.id:30} {r.severity.value:7} {r.title}")
        if not RULES:
            print("(правила ещё не зарегистрированы)")
        return 0

    files = discover(args.paths or ["."])
    diagnostics = run(files, select=_parse_set(args.select), ignore=_parse_set(args.ignore))
    for d in sorted(diagnostics, key=lambda x: x.sort_key()):
        print(d.format())

    n_xbsl = sum(1 for f in files if f.suffix == ".xbsl")
    n_yaml = sum(1 for f in files if f.suffix == ".yaml")
    n_err = sum(1 for d in diagnostics if d.severity.value == "error")
    print(
        f"\nПроверено файлов: {len(files)} ({n_xbsl} .xbsl, {n_yaml} .yaml); "
        f"замечаний: {len(diagnostics)} (ошибок: {n_err})",
        file=sys.stderr,
    )
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
