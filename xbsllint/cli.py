"""Command-line entry point: xbsllint / python -m xbsllint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xbsllint import __version__, dataset, i18n, report


def discover(paths: list[str]) -> list[Path]:
    """Collect source files (.xbsl and .yaml) under the given paths."""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in (".xbsl", ".yaml"):
                out.append(p)
        elif p.is_dir():
            out.extend(sorted(p.rglob("*.xbsl")))
            out.extend(sorted(p.rglob("*.yaml")))
    # Uniquify, preserving order
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
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help="язык вывода линтера (по умолчанию: env XBSLLINT_LANG / локаль системы / ru)",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "codeclimate"),
        default="text",
        help="формат вывода: text (по умолчанию), json (машиночитаемый: diagnostics + summary) "
             "или codeclimate (отчёт GitLab Code Quality – виджет в merge request)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="проверить один буфер из stdin (для интеграции с редактором); "
             "вид файла и путь в позициях задаёт --filename",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="вместо проверки вывести JSON-индекс проекта (объекты, методы, компоненты форм) "
             "для навигации в редакторе; путь – корень проекта",
    )
    parser.add_argument(
        "--filename",
        metavar="ИМЯ",
        help="имя проверяемого буфера при --stdin (напр. Форма.xbsl); расширение задаёт вид файла",
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
    # The linter output is always UTF-8, regardless of the console encoding (matters for
    # Cyrillic and for redirection to a file/editor).
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass

    parser = build_parser()
    args = parser.parse_args(argv)

    i18n.set_lang(args.lang)  # None keeps the env/locale lookup order
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    if args.element_version:
        dataset.set_version(args.element_version)
    try:
        dataset.resolve_version()  # check the selected data version is available
    except dataset.DatasetError as exc:
        print(i18n.t("cli.data-error", error=exc), file=sys.stderr)
        return 2

    if args.index:
        # Index mode: a JSON dump of the project for editor navigation, nothing on stderr.
        # The lexer (and the member families) needs the Element data, checked above.
        from xbsllint.indexer import build_index

        if len(args.paths) != 1:
            print(i18n.t("cli.index-single-path"), file=sys.stderr)
            return 2
        root = Path(args.paths[0])
        if not root.exists():
            print(i18n.t("cli.index-missing-path", path=args.paths[0]), file=sys.stderr)
            return 2
        print(json.dumps(build_index(root), ensure_ascii=False))
        return 0

    from xbsllint.engine import RULES, make_source, run, run_sources

    if args.list_rules:
        for r in sorted(RULES, key=lambda x: (x.tier, x.id)):
            mark = "   " if r.enabled_by_default else "off"
            print(f"{r.tier} {mark} {r.id:30} {r.severity.value:7} {r.title}")
        if not RULES:
            print(i18n.t("cli.no-rules"))
        return 0

    select = _parse_set(args.select)
    ignore = _parse_set(args.ignore)

    if args.stdin:
        # Editor mode: one buffer from stdin, checked with per-file rules only (cross-file rules
        # need the whole project). --filename sets the kind (.xbsl/.yaml) and the reported path.
        if not args.filename:
            print(i18n.t("cli.stdin-needs-filename"), file=sys.stderr)
            return 2
        src = make_source(Path(args.filename), sys.stdin.buffer.read())
        diagnostics = run_sources([src], select=select, ignore=ignore, scopes=("file",))
        files = [Path(args.filename)]
    else:
        files = discover(args.paths or ["."])
        diagnostics = run(files, select=select, ignore=ignore)

    if args.format == "json":
        # Machine-readable: the whole payload on stdout, nothing on stderr.
        print(json.dumps(report.report(diagnostics, len(files)), ensure_ascii=False))
    elif args.format == "codeclimate":
        # GitLab Code Quality report: the issue array on stdout, nothing on stderr.
        # Paths are made relative to the current directory — run from the repository root.
        print(json.dumps(report.codeclimate(diagnostics), ensure_ascii=False))
    else:
        for d in sorted(diagnostics, key=lambda x: x.sort_key()):
            print(d.format())
        n_xbsl = sum(1 for f in files if f.suffix == ".xbsl")
        n_yaml = sum(1 for f in files if f.suffix == ".yaml")
        n_err = sum(1 for d in diagnostics if d.severity.value == "error")
        print(
            i18n.t("cli.summary", files=len(files), xbsl=n_xbsl, yaml=n_yaml,
                   diags=len(diagnostics), errors=n_err),
            file=sys.stderr,
        )

    return 1 if any(d.severity.value == "error" for d in diagnostics) else 0


if __name__ == "__main__":
    raise SystemExit(main())
