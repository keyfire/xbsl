"""Command-line entry point: xbsl / python -m xbsl."""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

from xbsl import __version__, baseline, dataset, engine, i18n, plugins, report
from xbsl.templates import DEFAULT_FILE as DEFAULT_TEMPLATES_FILE


def discover(paths: list[str]) -> list[Path]:
    """Collect source files (.xbsl, .yaml and .xbql) under the given paths.

    The query file of a virtual table is collected too: it is the only place where the
    query language lives outside a `Запрос{ ... }` block, and until it was collected the
    query rules had nothing to look at there - an unknown table in such a file was found by
    nobody but the server compiler.
    """
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in (".xbsl", ".yaml") or engine.is_query_file(p):
                out.append(p)
        elif p.is_dir():
            out.extend(engine.find_sources(p, "*.xbsl"))
            out.extend(engine.find_sources(p, "*.yaml"))
            out.extend(engine.find_sources(p, f"*{engine.QUERY_SUFFIX}"))
    # Uniquify, preserving order
    seen: set[Path] = set()
    uniq: list[Path] = []
    for f in out:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


def _project_root(start: Path) -> Path | None:
    """The nearest directory - start itself, then upwards - holding a project descriptor.

    The platform accepts either spelling of the file name, so both are looked for.
    """
    for candidate in (start, *start.parents):
        if any((candidate / name).is_file() for name in ("Проект.yaml", "Project.yaml")):
            return candidate
    return None


def discover_with_context(paths: list[str]) -> tuple[list[Path], list[Path] | None]:
    """discover() plus the project context of the requested paths.

    A single file (or a subfolder) of a project does not carry the project-wide context: the
    other objects are unknown, and the project-scope rules would report false findings such as
    yaml/unknown-type on the project's own types. For every requested path that lives inside a
    project (an ancestor directory holds Проект.yaml) the whole project is loaded as well.

    Returns (files, requested): files is what to lint; requested is the explicitly asked-for
    subset the caller must narrow the diagnostics down to (_filter_requested), or None when no
    context was added and the diagnostics need no filtering."""
    files = discover(paths)
    seen = {f.resolve() for f in files}
    roots: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            root = _project_root(p.resolve().parent)
        elif p.is_dir():
            root = _project_root(p.resolve())
        else:
            continue
        if root is not None and root not in roots:
            roots.append(root)
    added: list[Path] = []
    for root in roots:
        for pattern in ("*.xbsl", "*.yaml"):
            for f in engine.find_sources(root, pattern):
                rp = f.resolve()
                if rp not in seen:
                    seen.add(rp)
                    added.append(f)
    if not added:
        return files, None
    return files + added, files


def _filter_requested(diagnostics, requested):
    """The diagnostics of the explicitly requested files: the project context loaded by
    discover_with_context is checked for the cross-file picture, not reported on."""
    if requested is None:
        return diagnostics
    wanted = {p.resolve() for p in requested}
    return [d for d in diagnostics if Path(d.path).resolve() in wanted]


def _commands_help() -> str:
    """The command list for the help epilog.

    The top-level commands are dispatched by hand in main(): the default mode accepts arbitrary
    paths, so argparse cannot tell "xbsl Форма.xbsl" from a command name and would not build this
    list itself. The names come from the same tuples as the dispatch, so they cannot drift apart.
    The help texts go through i18n.t: the language is chosen before build_parser is called.
    """
    entries = [(i18n.t("cli.help.commands.lint-name"), i18n.t("cli.help.commands.lint-desc"))]
    entries += [(name, i18n.t(f"cli.help.server.{name}")) for name in _SERVER_COMMANDS]
    entries += [
        ("templates", i18n.t("cli.help.commands.templates")),
        ("extract", i18n.t("cli.help.commands.extract")),
        ("data-diff", i18n.t("cli.help.commands.data-diff")),
        ("translate", i18n.t("cli.help.commands.translate")),
        ("self-update", i18n.t("cli.help.commands.self-update")),
    ]
    lines = [i18n.t("cli.help.commands.header")]
    lines += [f"  {name:<16}{description}" for name, description in entries]
    lines += ["", "  " + i18n.t("cli.help.commands.scaffold-header")]
    # break_on_hyphens=False: without it the wrapper splits names like add-subsystem in half.
    lines += textwrap.wrap(", ".join(_META_COMMANDS), width=74, break_on_hyphens=False,
                           initial_indent="    ", subsequent_indent="    ")
    lines += ["", i18n.t("cli.help.commands.footer")]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    rule_selector = i18n.t("cli.help.meta.rule-selector")  # shared metavar --select/--ignore/--enable
    baseline_file = i18n.t("cli.help.meta.file")  # shared metavar --baseline/--write-baseline
    parser = i18n.ArgumentParser(
        prog="xbsl",
        usage=i18n.t("cli.help.usage"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=i18n.t("cli.help.description"),
        epilog=_commands_help(),
    )
    parser.add_argument("paths", nargs="*", default=["."], help=i18n.t("cli.help.paths"))
    parser.add_argument(
        "--select",
        metavar=rule_selector,
        action="append",
        help=i18n.t("cli.help.select"),
    )
    parser.add_argument(
        "--ignore",
        metavar=rule_selector,
        action="append",
        help=i18n.t("cli.help.ignore"),
    )
    parser.add_argument(
        "--enable",
        metavar=rule_selector,
        action="append",
        help=i18n.t("cli.help.enable"),
    )
    parser.add_argument(
        "--baseline",
        metavar=baseline_file,
        help=i18n.t("cli.help.baseline"),
    )
    parser.add_argument(
        "--write-baseline",
        metavar=baseline_file,
        help=i18n.t("cli.help.write-baseline"),
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help=i18n.t("cli.help.no-baseline"),
    )
    parser.add_argument(
        "--stale-baseline",
        action="store_true",
        help=i18n.t("cli.help.stale-baseline"),
    )
    parser.add_argument(
        "--prune-baseline",
        action="store_true",
        help=i18n.t("cli.help.prune-baseline"),
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help=i18n.t("cli.help.fix"),
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help=i18n.t("cli.help.jobs"),
    )
    parser.add_argument(
        "--list-rules", action="store_true", help=i18n.t("cli.help.list-rules")
    )
    parser.add_argument(
        "--where",
        action="store_true",
        help=i18n.t("cli.help.where"),
    )
    parser.add_argument(
        "--element-version",
        metavar=i18n.t("cli.help.meta.version"),
        help=i18n.t("cli.help.element-version"),
    )
    parser.add_argument(
        "--data-dir",
        metavar=i18n.t("cli.help.meta.dir"),
        help=i18n.t("cli.help.data-dir"),
    )
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help=i18n.t("cli.help.lang"),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "codeclimate"),
        default="text",
        help=i18n.t("cli.help.format"),
    )
    parser.add_argument(
        "--out",
        metavar=i18n.t("cli.help.meta.file"),
        help=i18n.t("cli.help.out"),
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help=i18n.t("cli.help.stdin"),
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help=i18n.t("cli.help.index"),
    )
    parser.add_argument(
        "--filename",
        metavar=i18n.t("cli.help.meta.name"),
        help=i18n.t("cli.help.filename"),
    )
    data_note = ""
    try:
        data_note = (
            f" (данные Элемента: {dataset.default_version()}; "
            f"доступно: {', '.join(dataset.available_versions())})"
        )
    except dataset.DatasetError:
        pass
    # Надстройки называются с версиями: два окружения с разъехавшимися надстройками
    # отвечают на одном файле по-разному, и раньше на это ничто не указывало.
    plugin_note = ""
    listed = ", ".join(f"{p['name']} {p['version']}" for p in plugins.installed())
    if listed:
        plugin_note = "; " + i18n.t("cli.version.plugins", list=listed)
    parser.add_argument("--version", action="version", help=i18n.t("cli.help.version"),
                        version=f"xbsl {__version__}{data_note}{plugin_note}")
    return parser


def _parse_set(values: list[str] | None) -> set[str] | None:
    # action="append" collects repeated flags; each value may itself be a comma-separated list.
    if not values:
        return None
    parts = {part.strip() for value in values for part in value.split(",") if part.strip()}
    return parts or None


def _emit_report(text: str, out: str | None) -> None:
    """Print the check report to stdout, or write it to `out`.

    The file route exists because on Windows the shell redirection
    (`> file` in PowerShell) prefixes the output with a BOM, and a
    `json.load` of the result refuses it. The file is written as UTF-8
    without BOM with `\\n` newlines.
    """
    if not out:
        print(text)
        return
    Path(out).write_text(text + "\n", encoding="utf-8", newline="\n")


def _apply_fixes(sources, diagnostics, args) -> int:
    """--fix: rewrite files with the mechanical fixes, then report the remaining findings."""
    from xbsl import fixer

    by_path = {d.path: [] for d in diagnostics}
    for d in diagnostics:
        by_path[d.path].append(d)

    fixed = files_changed = 0
    for src in sources:
        result = fixer.fix_source(src, by_path.get(src.rel, []))
        if result.changed:
            src.path.write_bytes(fixer.encode(src, result.text))
            files_changed += 1
            fixed += result.applied

    remaining = [d for d in diagnostics if not fixer.is_fixable(d)]
    if args.format == "json":
        _emit_report(json.dumps(report.report(remaining, len(sources)), ensure_ascii=False),
                     args.out)
    elif args.format == "codeclimate":
        _emit_report(json.dumps(report.codeclimate(remaining), ensure_ascii=False), args.out)
    elif args.out:
        lines = [d.format() for d in sorted(remaining, key=lambda x: x.sort_key())]
        _emit_report("\n".join(lines), args.out)
    else:
        for d in sorted(remaining, key=lambda x: x.sort_key()):
            print(d.format())
    print(
        i18n.t("cli.fix-summary", fixed=fixed, files=files_changed, left=len(remaining)),
        file=sys.stderr,
    )
    return 1 if any(d.severity.value == "error" for d in remaining) else 0


_META_COMMANDS = (
    "new-project", "new-object", "add-field", "add-route", "add-method", "add-form",
    "add-subsystem", "add-dependency", "add-localization", "set-field-property",
    "rename-object", "delete-object", "set-access", "object-info", "project-info",
    "localization-info", "form-tree", "form-edit", "form-handlers",
)
_SERVER_COMMANDS = ("lsp", "mcp", "web")


def _selfupdate_parser() -> argparse.ArgumentParser:
    parser = i18n.ArgumentParser(prog="xbsl self-update",
                                 description=i18n.t("cli.help.commands.self-update"))
    parser.add_argument("--version", help=i18n.t("cli.help.selfupdate-version"))
    parser.add_argument("--stop-holders", action="store_true",
                        help=i18n.t("cli.help.selfupdate-stop"))
    return parser

def _templates_parser() -> argparse.ArgumentParser:
    parser = i18n.ArgumentParser(
        prog="xbsl templates",
        description=i18n.t("cli.help.tpl.description"),
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("list", help=i18n.t("cli.help.tpl.list"))
    p.add_argument("--format", choices=("text", "json"), default="text",
                   help=i18n.t("cli.help.tpl.list-format"))

    p = sub.add_parser("export", help=i18n.t("cli.help.tpl.export"))
    p.add_argument("--output", required=True, help=i18n.t("cli.help.tpl.export-output"))
    p.add_argument("--custom-only", action="store_true",
                   help=i18n.t("cli.help.tpl.export-custom-only"))

    p = sub.add_parser("import", help=i18n.t("cli.help.tpl.import"))
    p.add_argument("source", help=i18n.t("cli.help.tpl.import-source"))

    sub.add_parser("save", help=i18n.t("cli.help.tpl.save"))

    # Every subcommand takes --file: on the parent, argparse would demand it BEFORE the
    # subcommand ("templates --file X import Y") - that reads backwards and is easy to forget.
    for sp in sub.choices.values():
        sp.add_argument(
            "--file", default=DEFAULT_TEMPLATES_FILE,
            help=i18n.t("cli.help.tpl.file", path=DEFAULT_TEMPLATES_FILE),
        )
    return parser


def _template_row(t, builtin_names: set[str]) -> dict:
    from xbsl import templates as tpl

    return {
        "name": t.name,
        "trigger": t.trigger,
        "prefix": t.prefix,
        "title": t.title,
        "description": t.description,
        "category": t.category,
        "contexts": list(t.contexts),
        "environments": list(t.environments),
        "pattern": t.pattern,
        "preview": tpl.preview(t.pattern),
        "isAutoinsertable": t.autoinsertable,
        "builtin": t.name in builtin_names,
    }


def _templates_main(argv: list[str]) -> int:
    from xbsl import templates as tpl

    args = _templates_parser().parse_args(argv)
    path = Path(args.file)
    try:
        builtin = tpl.load_builtin()
        custom = tpl.load_file(path) if path.exists() else []
        merged = tpl.merge(builtin, custom)
        builtin_names = {t.name for t in builtin} - {t.name for t in custom}

        if args.action == "list":
            rows = [_template_row(t, builtin_names) for t in merged]
            if args.format == "json":
                print(json.dumps({"templates": rows, "file": str(path)}, ensure_ascii=False))
                return 0
            for row in rows:
                mark = " " if row["builtin"] else "*"
                print(f"{mark} {row['trigger']:<20} {row['title']:<40} {row['category']}")
            print(f"\nВсего: {len(rows)} (пользовательских: "
                  f"{sum(0 if r['builtin'] else 1 for r in rows)}); файл: {path}")
            return 0

        if args.action == "export":
            chosen = custom if args.custom_only else merged
            Path(args.output).write_text(tpl.dumps(chosen), encoding="utf-8")
            print(json.dumps({"exported": len(chosen), "output": args.output}, ensure_ascii=False))
            return 0

        if args.action == "import":
            incoming = tpl.load_file(Path(args.source))
            # Only what differs from the builtin set is stored: an import of our own export
            # must not freeze a copy of every builtin template into the user's file, or the
            # next release would not reach them.
            builtin_by_name = {t.name: t for t in builtin}
            fresh = [t for t in incoming if builtin_by_name.get(t.name) != t]
            saved = tpl.merge(custom, fresh)
            path.write_text(tpl.dumps(saved), encoding="utf-8")
            print(json.dumps(
                {"imported": len(fresh), "skipped": len(incoming) - len(fresh),
                 "total": len(saved), "file": str(path)},
                ensure_ascii=False,
            ))
            return 0

        # save - the panel sends the whole set it edited; we validate before writing.
        incoming = tpl.loads(sys.stdin.read(), path="<stdin>")
        builtin_by_name = {t.name: t for t in builtin}
        fresh = [t for t in incoming if builtin_by_name.get(t.name) != t]
        if fresh:
            path.write_text(tpl.dumps(fresh), encoding="utf-8")
        elif path.exists():
            path.unlink()  # nothing but the builtin set left - the file has no reason to exist
        print(json.dumps({"saved": len(fresh), "file": str(path)}, ensure_ascii=False))
        return 0
    except (tpl.TemplateError, OSError, UnicodeError) as exc:
        # UnicodeError: a non-UTF-8 stdio pipe (Windows ANSI) - report, not a traceback.
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2


def _scaffold_parser() -> argparse.ArgumentParser:
    parser = i18n.ArgumentParser(
        prog="xbsl", description=i18n.t("cli.help.scaf.description")
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new-project", help=i18n.t("cli.help.scaf.new-project"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.np-root"))
    p.add_argument("vendor", help=i18n.t("cli.help.scaf.np-vendor"))
    p.add_argument("name", help=i18n.t("cli.help.scaf.np-name"))
    p.add_argument("--representation", help=i18n.t("cli.help.scaf.np-representation"))
    p.add_argument("--version", default="1.0.0", help=i18n.t("cli.help.scaf.np-version"))
    p.add_argument("--compatibility", default="9.0", help=i18n.t("cli.help.scaf.np-compatibility"))
    p.add_argument("--subsystem", default="Основное", help=i18n.t("cli.help.scaf.np-subsystem"))
    p.add_argument("--library", action="store_true", help=i18n.t("cli.help.scaf.np-library"))

    p = sub.add_parser("new-object", help=i18n.t("cli.help.scaf.new-object"))
    p.add_argument("directory", help=i18n.t("cli.help.scaf.no-directory"))
    p.add_argument("kind", help=i18n.t("cli.help.scaf.no-kind"))
    p.add_argument("name", help=i18n.t("cli.help.scaf.no-name"))
    p.add_argument("--scope", help=i18n.t("cli.help.scaf.no-scope"))
    p.add_argument("--environment", help=i18n.t("cli.help.scaf.no-environment"))
    p.add_argument("--access", help=i18n.t("cli.help.scaf.no-access"))
    p.add_argument("--routes", help=i18n.t("cli.help.scaf.new-object-routes"))
    p.add_argument("--report", help=i18n.t("cli.help.scaf.new-object-report"))
    p.add_argument("--presentation", help=i18n.t("cli.help.scaf.no-presentation"))

    p = sub.add_parser("add-field", help=i18n.t("cli.help.scaf.add-field"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.af-yaml"))
    # field_kind help lists the literal accepted kind names - Russian XBSL values, not prose.
    p.add_argument("field_kind", help=", ".join(("реквизит", "измерение", "ресурс", "значение",
                                                 "параметр", "поле", "табличная-часть")))
    p.add_argument("name", help=i18n.t("cli.help.scaf.af-name"))
    p.add_argument("--type", default="Строка", help=i18n.t("cli.help.scaf.af-type"))
    p.add_argument("--tabular", help=i18n.t("cli.help.scaf.add-field-tabular"))
    p.add_argument("--prop", action="append", metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                   help=i18n.t("cli.help.scaf.field-prop"))

    p = sub.add_parser("set-field-property", help=i18n.t("cli.help.scaf.set-field-property"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.af-yaml"))
    p.add_argument("field_kind", help=", ".join(("реквизит", "измерение", "ресурс", "значение",
                                                 "параметр", "поле", "константа")))
    p.add_argument("name", help=i18n.t("cli.help.scaf.sfp-name"))
    p.add_argument("--prop", action="append", required=True, metavar="КЛЮЧ=ЗНАЧЕНИЕ",
                   help=i18n.t("cli.help.scaf.field-prop"))
    p.add_argument("--tabular", help=i18n.t("cli.help.scaf.add-field-tabular"))

    p = sub.add_parser("add-route", help=i18n.t("cli.help.scaf.add-route"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.ar-yaml"))
    p.add_argument("routes", help=i18n.t("cli.help.scaf.ar-routes"))

    p = sub.add_parser("add-localization", help=i18n.t("cli.help.scaf.add-localization"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.al-yaml"))
    p.add_argument("language", help=i18n.t("cli.help.scaf.al-language"))

    p = sub.add_parser("localization-info", help=i18n.t("cli.help.scaf.localization-info"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.al-yaml"))

    p = sub.add_parser("add-method", help=i18n.t("cli.help.scaf.add-method"))
    p.add_argument("module_path", help=i18n.t("cli.help.scaf.am-module"))
    p.add_argument("name", help=i18n.t("cli.help.scaf.am-name"))
    p.add_argument("--params", default="", help=i18n.t("cli.help.scaf.add-method-params"))
    p.add_argument("--returns", help=i18n.t("cli.help.scaf.add-method-returns"))
    p.add_argument("--annotations", help=i18n.t("cli.help.scaf.add-method-annotations"))
    p.add_argument("--after", help=i18n.t("cli.help.scaf.add-method-after"))
    p.add_argument("--before", help=i18n.t("cli.help.scaf.add-method-before"))
    p.add_argument("--body", help=i18n.t("cli.help.scaf.add-method-body"))

    p = sub.add_parser("add-form", help=i18n.t("cli.help.scaf.add-form"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("--name", help=i18n.t("cli.help.scaf.af2-name"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.yaml-vs-name"))
    p.add_argument("--forms", help=i18n.t("cli.help.scaf.add-form-forms"))
    p.add_argument("--card-min-width", type=int, help=i18n.t("cli.help.scaf.add-form-card-min-width"))
    p.add_argument("--card-placeholder", help=i18n.t("cli.help.scaf.add-form-card-placeholder"))
    p.add_argument("--overwrite", action="store_true", help=i18n.t("cli.help.scaf.af2-overwrite"))

    p = sub.add_parser("add-subsystem", help=i18n.t("cli.help.scaf.add-subsystem"))
    p.add_argument("parent_dir", help=i18n.t("cli.help.scaf.as-parent"))
    p.add_argument("name", help=i18n.t("cli.help.scaf.as-name"))
    p.add_argument("--representation", help=i18n.t("cli.help.scaf.as-representation"))
    p.add_argument("--no-auto-interface", action="store_true", help=i18n.t("cli.help.scaf.as-no-auto-interface"))
    p.add_argument("--uses", help=i18n.t("cli.help.scaf.add-subsystem-uses"))

    p = sub.add_parser("add-dependency", help=i18n.t("cli.help.scaf.add-dependency"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("vendor", help=i18n.t("cli.help.scaf.add-dependency-vendor"))
    p.add_argument("name", help=i18n.t("cli.help.scaf.add-dependency-name"))
    p.add_argument("version", help=i18n.t("cli.help.scaf.add-dependency-version"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.add-dependency-path"))

    p = sub.add_parser("rename-object", help=i18n.t("cli.help.scaf.rename-object"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("old_name", help=i18n.t("cli.help.scaf.ro-old"))
    p.add_argument("new_name", help=i18n.t("cli.help.scaf.ro-new"))
    p.add_argument("--new-presentation", help=i18n.t("cli.help.scaf.rename-new-presentation"))
    p.add_argument("--old-presentation", help=i18n.t("cli.help.scaf.rename-old-presentation"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.rename-path"))

    p = sub.add_parser("delete-object", help=i18n.t("cli.help.scaf.delete-object"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("--name", help=i18n.t("cli.help.scaf.arg.object-name"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.yaml-vs-name"))
    p.add_argument("--apply", action="store_true", help=i18n.t("cli.help.scaf.delete-apply"))

    p = sub.add_parser("set-access", help=i18n.t("cli.help.scaf.set-access"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("--name", help=i18n.t("cli.help.scaf.arg.object-name"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.yaml-vs-name"))
    p.add_argument("--default", help=i18n.t("cli.help.scaf.set-access-default"))
    p.add_argument("--permission", action="append", metavar=i18n.t("cli.help.scaf.meta.right-method"),
                   help=i18n.t("cli.help.scaf.set-access-permission"))
    p.add_argument("--calc-by", help=i18n.t("cli.help.scaf.set-access-calc-by"))

    p = sub.add_parser("object-info", help=i18n.t("cli.help.scaf.object-info"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))
    p.add_argument("--name", help=i18n.t("cli.help.scaf.arg.object-name"))
    p.add_argument("--path", help=i18n.t("cli.help.scaf.yaml-vs-name"))

    p = sub.add_parser("project-info", help=i18n.t("cli.help.scaf.project-info"))
    p.add_argument("root", help=i18n.t("cli.help.scaf.arg.project-root"))

    p = sub.add_parser("form-tree", help=i18n.t("cli.help.scaf.form-tree"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.arg.form-yaml"))
    p.add_argument("--at", type=int, metavar=i18n.t("cli.help.scaf.meta.offset"),
                   help=i18n.t("cli.help.scaf.form-tree-at"))
    p.add_argument("--node", metavar=i18n.t("cli.help.scaf.meta.node-id"),
                   help=i18n.t("cli.help.scaf.form-tree-node"))
    p.add_argument("--name", metavar=i18n.t("cli.help.scaf.meta.name"),
                   help=i18n.t("cli.help.scaf.form-tree-name"))
    p.add_argument("--max-depth", type=int, default=0,
                   metavar=i18n.t("cli.help.scaf.meta.levels"),
                   help=i18n.t("cli.help.scaf.form-tree-max-depth"))
    p.add_argument("--no-properties", action="store_true",
                   help=i18n.t("cli.help.scaf.form-tree-no-properties"))

    p = sub.add_parser("form-edit", help=i18n.t("cli.help.scaf.form-edit"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.arg.form-yaml"))
    # A metavar instead of the choice list: sixteen values drown the usage line, so the
    # list goes into the description - the same shape as field_kind above.
    form_ops = ("insert", "insert-fragment", "move", "move-nodes",
                "remove", "remove-nodes", "wrap",
                "unwrap", "duplicate", "rename",
                "set-property", "reset-property",
                "property-add", "property-retype", "property-remove",
                "property-rename")
    p.add_argument("op", choices=form_ops, metavar=i18n.t("cli.help.scaf.meta.form-op"),
                   help=", ".join(form_ops))
    p.add_argument("--parent", help=i18n.t("cli.help.scaf.fe-parent"))
    p.add_argument("--slot", help=i18n.t("cli.help.scaf.fe-slot"))
    p.add_argument("--type", help=i18n.t("cli.help.scaf.fe-type"))
    p.add_argument("--name", help=i18n.t("cli.help.scaf.fe-name"))
    p.add_argument("--node", help=i18n.t("cli.help.scaf.fe-node"))
    p.add_argument("--nodes", action="append", metavar="ID[,ID...]",
                   help=i18n.t("cli.help.scaf.fe-nodes"))
    p.add_argument("--new-parent", help=i18n.t("cli.help.scaf.fe-new-parent"))
    p.add_argument("--container", help=i18n.t("cli.help.scaf.fe-container"))
    p.add_argument("--new-name", help=i18n.t("cli.help.scaf.fe-new-name"))
    p.add_argument("--before", help=i18n.t("cli.help.scaf.fe-before"))
    p.add_argument("--after", help=i18n.t("cli.help.scaf.fe-after"))
    p.add_argument("--key", help=i18n.t("cli.help.scaf.fe-key"))
    p.add_argument("--value", help=i18n.t("cli.help.scaf.fe-value"))
    p.add_argument("--value-yaml", help=i18n.t("cli.help.scaf.fe-value-yaml"))
    p.add_argument("--fragment", help=i18n.t("cli.help.scaf.fe-fragment"))
    p.add_argument("--fragment-file", metavar=i18n.t("cli.help.meta.file"),
                   help=i18n.t("cli.help.scaf.fe-fragment-file"))
    p.add_argument("--new-type", help=i18n.t("cli.help.scaf.fe-new-type"))

    p = sub.add_parser("form-handlers", help=i18n.t("cli.help.scaf.form-handlers"))
    p.add_argument("yaml_path", help=i18n.t("cli.help.scaf.arg.form-yaml"))
    p.add_argument("--node", help=i18n.t("cli.help.scaf.fh-node"))
    p.add_argument("--key", help=i18n.t("cli.help.scaf.fh-key"))
    p.add_argument("--method", help=i18n.t("cli.help.scaf.fh-method"))
    p.add_argument("--signature", help=i18n.t("cli.help.scaf.fh-signature"))

    for name, sp in sub.choices.items():
        if name.endswith("-info") or name == "form-tree":
            continue
        sp.add_argument("--dry-run", action="store_true", help=i18n.t("cli.help.scaf.dry-run"))
    return parser


def _scaffold_lint(paths: list[str]) -> dict | None:
    """File-scope lint of the written files; without the Element data - None, not a failed operation."""
    from xbsl import dataset as _dataset
    from xbsl.engine import load, run_sources

    try:
        sources = [load(Path(p)) for p in paths]
        diags = run_sources(sources, scopes=("file",))
        return report.report(diags, len(sources))
    except _dataset.DatasetError:
        return None


def _props(pairs: list[str] | None) -> dict[str, str] | None:
    """--prop КЛЮЧ=ЗНАЧЕНИЕ ... as a dict; the value may contain "=" (only the first splits)."""
    if not pairs:
        return None
    props: dict[str, str] = {}
    for item in pairs:
        key, sep, value = item.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"Ожидается КЛЮЧ=ЗНАЧЕНИЕ, получено: '{item}'")
        props[key.strip()] = value
    return props


def _scaffold_main(argv: list[str]) -> int:
    from xbsl import scaffold

    args = _scaffold_parser().parse_args(argv)
    try:
        if args.command == "new-project":
            result = scaffold.op_new_project(
                Path(args.root), args.vendor, args.name,
                representation=args.representation, version=args.version,
                compatibility=args.compatibility, subsystem=args.subsystem,
                library=args.library,
            )
        elif args.command == "new-object":
            result = scaffold.op_new_object(
                Path(args.directory), args.kind, args.name,
                scope=args.scope, environment=args.environment, access=args.access,
                routes=args.routes, presentation=args.presentation,
                report=json.loads(args.report) if args.report else None,
            )
        elif args.command == "add-field":
            result = scaffold.op_add_field(
                Path(args.yaml_path), args.field_kind, args.name,
                type_=args.type, tabular=args.tabular, props=_props(args.prop),
            )
        elif args.command == "set-field-property":
            result = scaffold.op_set_field_property(
                Path(args.yaml_path), args.field_kind, args.name, _props(args.prop),
                tabular=args.tabular,
            )
        elif args.command == "add-route":
            result = scaffold.op_add_route(Path(args.yaml_path), args.routes)
        elif args.command == "add-localization":
            result = scaffold.op_add_localization(Path(args.yaml_path), args.language)
        elif args.command == "localization-info":
            print(json.dumps(
                scaffold.localization_info(Path(args.yaml_path)), ensure_ascii=False,
            ))
            return 0
        elif args.command == "add-method":
            result = scaffold.op_add_method(
                Path(args.module_path), args.name,
                params=args.params, returns=args.returns,
                annotations=args.annotations, after=args.after, before=args.before,
                body=args.body,
            )
        elif args.command == "add-form":
            result = scaffold.op_add_form(
                Path(args.root), name=args.name,
                yaml_path=Path(args.path) if args.path else None,
                forms=args.forms.split(",") if args.forms else None,
                overwrite=args.overwrite,
                card_min_width=args.card_min_width,
                card_placeholder=args.card_placeholder,
            )
        elif args.command == "add-subsystem":
            result = scaffold.op_add_subsystem(
                Path(args.parent_dir), args.name,
                representation=args.representation,
                auto_interface=not args.no_auto_interface,
                uses=args.uses.split(",") if args.uses else None,
            )
        elif args.command == "add-dependency":
            result = scaffold.op_add_dependency(
                Path(args.root), args.vendor, args.name, args.version,
                project_yaml=Path(args.path) if args.path else None,
            )
        elif args.command == "set-access":
            perms = {}
            for item in args.permission or []:
                right, sep, method = item.partition("=")
                if not sep:
                    raise ValueError(f"Ожидается ПРАВО=СПОСОБ, получено: '{item}'")
                perms[right.strip()] = method.strip()
            result = scaffold.op_set_access(
                Path(args.root), name=args.name,
                yaml_path=Path(args.path) if args.path else None,
                default=args.default, permissions=perms or None,
                calc_by=[f.strip() for f in args.calc_by.split(",")] if args.calc_by else None,
            )
        elif args.command == "rename-object":
            result = scaffold.op_rename_object(
                Path(args.root), args.old_name, args.new_name,
                new_presentation=args.new_presentation,
                old_presentation=args.old_presentation,
                yaml_path=Path(args.path) if args.path else None,
            )
        elif args.command == "delete-object":
            result = scaffold.op_delete_object(
                Path(args.root), args.name,
                yaml_path=Path(args.path) if args.path else None,
            )
            # Deletion is irreversible: the PLAN is the default answer, --apply performs it.
            if not args.apply or args.dry_run:
                payload = result.as_dict(content=False)
                payload["dry-run"] = True
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            scaffold.apply_result(result)
            print(json.dumps(result.as_dict(content=False), ensure_ascii=False))
            return 0
        elif args.command == "form-tree":
            from xbsl import formedits, formmodel

            form = formedits.load_form(Path(args.yaml_path))
            if args.at is not None:
                node = formmodel.node_at(form, args.at)
                payload = {"node": formmodel.node_dict(node, deep=False) if node else None}
                if node is not None:
                    # Parity with LSP xbsl/formNodeAt: the nearest parent COMPONENT
                    # (slots skipped) without children, null for the root.
                    parent = formmodel.parent_component(form, node)
                    payload["parent"] = (
                        formmodel.node_dict(parent, deep=False) if parent else None
                    )
            else:
                if args.node and args.name:
                    raise ValueError("Укажите только один из флагов --node и --name")
                depth = args.max_depth if args.max_depth and args.max_depth > 0 else None
                shape = {"max_depth": depth, "properties": not args.no_properties}
                if args.name:
                    found = formmodel.find_by_name(form.root, args.name)
                    if not found:
                        raise ValueError(
                            f"Компонент с именем \"{args.name}\" в форме не найден"
                        )
                    payload = {"roots": [formmodel.node_dict(n, **shape) for n in found]}
                elif args.node:
                    node = formmodel.get_node(form, args.node)
                    payload = {"root": formmodel.node_dict(node, **shape)}
                else:
                    payload = {"root": formmodel.node_dict(form.root, **shape)}
            print(json.dumps(payload, ensure_ascii=False))
            return 0
        elif args.command == "form-edit":
            from xbsl import formedits

            fragment = args.fragment
            if args.fragment_file:
                if fragment is not None:
                    raise ValueError("Укажите только один из флагов --fragment и --fragment-file")
                fragment = Path(args.fragment_file).read_text(encoding="utf-8-sig")
            outcome = formedits.op_component_edit(Path(args.yaml_path), args.op, {
                "parent": args.parent, "slot": args.slot, "type": args.type,
                "name": args.name, "node": args.node, "nodes": args.nodes,
                "new_parent": args.new_parent,
                "container": args.container, "new_name": args.new_name,
                "before": args.before, "after": args.after,
                "key": args.key, "value": args.value, "value_yaml": args.value_yaml,
                "fragment": fragment, "new_type": args.new_type,
            })
            if args.dry_run:
                payload = outcome.result.as_dict()
                payload["edits"] = [
                    {"start": e.start, "end": e.end, "newText": e.new_text}
                    for e in outcome.edits
                ]
                payload["node"] = outcome.node
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            written = scaffold.apply_result(outcome.result)
            out = {
                "files": [
                    {"path": str(c.path), "created": c.created}
                    for c in outcome.result.changes
                ],
                "notes": outcome.result.notes,
                "node": outcome.node,
                "lint": _scaffold_lint(written),
            }
            print(json.dumps(out, ensure_ascii=False))
            return 0
        elif args.command == "form-handlers":
            from xbsl import formhandlers

            if not args.node and not args.key:
                # The list mode: the methods of the paired module (the same shape as
                # the LSP xbsl/moduleHandlers, with a path instead of a uri).
                module_path = formhandlers.module_path_for(Path(args.yaml_path))
                if module_path.is_file():
                    from xbsl.engine import load

                    methods, errors = formhandlers.module_methods(load(module_path).text)
                    payload = {"available": True, "module": str(module_path),
                               "methods": methods, "parseErrors": errors}
                else:
                    payload = {"available": False, "module": None, "methods": []}
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            if not (args.node and args.key):
                raise ValueError("Для создания обработчика нужны оба флага --node и --key")
            outcome = formhandlers.op_add_handler(
                Path(args.yaml_path), args.node, args.key,
                method=args.method, signature=args.signature,
            )
            extras = {
                "method": outcome.plan.method,
                "created": outcome.plan.created,
                "methodAdded": outcome.plan.method_added,
            }
            if args.dry_run:
                payload = outcome.result.as_dict()
                payload.update(extras)
                print(json.dumps(payload, ensure_ascii=False))
                return 0
            written = scaffold.apply_result(outcome.result)
            out = {
                "files": [
                    {"path": str(c.path), "created": c.created}
                    for c in outcome.result.changes
                ],
                "notes": outcome.result.notes,
                **extras,
                "lint": _scaffold_lint(written),
            }
            print(json.dumps(out, ensure_ascii=False))
            return 0
        elif args.command == "object-info":
            print(json.dumps(
                scaffold.object_info(
                    Path(args.root), name=args.name,
                    yaml_path=Path(args.path) if args.path else None,
                ),
                ensure_ascii=False,
            ))
            return 0
        else:  # project-info
            print(json.dumps(scaffold.project_info(Path(args.root)), ensure_ascii=False))
            return 0
    except (scaffold.ScaffoldError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

    if args.dry_run:
        print(json.dumps(result.as_dict(), ensure_ascii=False))
        return 0
    written = scaffold.apply_result(result)
    out = {
        "renames": [
            {"from": str(r.old_path), "to": str(r.new_path)} for r in result.renames
        ],
        "files": [{"path": str(c.path), "created": c.created} for c in result.changes],
        "notes": result.notes,
        "lint": _scaffold_lint(written),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


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

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["self-update"]:
        # Updating by unpacking the wheel - safe while the exe files are held by LSP/MCP processes.
        from xbsl import selfupdate

        sp_args = _selfupdate_parser().parse_args(argv[1:])
        try:
            old, new = selfupdate.self_update(version=sp_args.version,
                                              stop_busy=sp_args.stop_holders,
                                              log=lambda msg: print(msg, file=sys.stderr))
        except selfupdate.SelfUpdateError as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 2
        print(json.dumps({"updated": old != new, "from": old, "to": new}, ensure_ascii=False))
        return 0
    if argv and argv[0] in _SERVER_COMMANDS:
        # xbsl lsp|mcp|web - a dispatcher to the entry points of the same names.
        command, rest = argv[0], argv[1:]
        sys.argv = [f"xbsl-{command}", *rest]
        if command == "lsp":
            from xbsl.lsp import main as server_main
        elif command == "mcp":
            from xbsl.mcp_server import main as server_main
        else:
            from xbsl.web import main as server_main
        server_main()
        return 0
    if argv[:1] == ["templates"]:
        return _templates_main(argv[1:])
    if argv[:1] == ["extract"]:
        # The dataset generator (xbsl.extract) - the same code as tools/extract.py in a clone.
        from xbsl import extract as extract_package

        return extract_package.main(argv[1:])
    if argv[:1] == ["data-diff"]:
        from xbsl import datadiff

        return datadiff.cli_main(argv[1:])
    if argv[:1] == ["translate"]:
        from xbsl.translation import cli as translate_cli

        return translate_cli.cli_main(argv[1:])
    if argv and argv[0] in _META_COMMANDS:
        return _scaffold_main(argv)
    if argv[:1] == ["lint"]:
        argv = argv[1:]  # an explicit alias of the default mode

    # The language must be known BEFORE build_parser: the check-mode help (help=) is assembled in
    # the chosen language. Prescan argv for --lang; env and locale are read by t() via current_lang().
    i18n.set_lang(i18n.lang_from_argv(argv))
    parser = build_parser()
    args = parser.parse_args(argv)

    # Re-pin from the parsed value: argparse also accepts an abbreviation (--lan en) that the
    # prescan does not catch; for the runtime this is the authoritative source.
    i18n.set_lang(args.lang)  # None keeps the env/locale lookup order
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    if args.element_version:
        dataset.set_version(args.element_version)

    if args.where:
        print(f"корень данных: {dataset.data_root()}")
        print(f"источник: {dataset.data_root_source()}")
        try:
            print(f"версия по умолчанию: {dataset.default_version()}")
            avail = dataset.available_versions()
            print(f"доступные версии: {', '.join(avail) if avail else '–'}")
        except dataset.DatasetError as exc:
            print(f"индекс версий: {exc}")
        return 0

    try:
        dataset.resolve_version()  # check the selected data version is available
    except dataset.DatasetError as exc:
        print(i18n.t("cli.data-error", error=exc), file=sys.stderr)
        return 2

    if args.index:
        # Index mode: a JSON dump of the project for editor navigation, nothing on stderr.
        # The lexer (and the member families) needs the Element data, checked above.
        from xbsl.indexer import build_index

        if len(args.paths) != 1:
            print(i18n.t("cli.index-single-path"), file=sys.stderr)
            return 2
        root = Path(args.paths[0])
        if not root.exists():
            print(i18n.t("cli.index-missing-path", path=args.paths[0]), file=sys.stderr)
            return 2
        print(json.dumps(build_index(root), ensure_ascii=False))
        return 0

    from xbsl.engine import RULES, load, make_source, run_sources

    if args.list_rules:
        for r in sorted(RULES, key=lambda x: (x.tier, x.id)):
            mark = "   " if r.enabled_by_default else "off"
            print(f"{r.tier} {mark} {r.id:30} {r.severity.value:7} {r.title}")
            # A bare "off" leaves the reader guessing whether the rule is broken, noisy or
            # simply not for them - so a disabled rule states its reason right here.
            if r.off_reason_text:
                print(f"       {i18n.t('cli.rule-off')}: {r.off_reason_text}")
        if not RULES:
            print(i18n.t("cli.no-rules"))
        return 0

    select = _parse_set(args.select)
    ignore = _parse_set(args.ignore)
    enable = _parse_set(args.enable)

    if args.fix and args.stdin:
        print(i18n.t("cli.fix-needs-files"), file=sys.stderr)
        return 2
    if args.fix and (args.baseline or args.write_baseline):
        print(i18n.t("cli.fix-conflicts-baseline"), file=sys.stderr)
        return 2

    if args.stdin:
        # Editor mode: one buffer from stdin, checked with per-file rules only (cross-file rules
        # need the whole project). --filename sets the kind (.xbsl/.yaml) and the reported path.
        if not args.filename:
            print(i18n.t("cli.stdin-needs-filename"), file=sys.stderr)
            return 2
        src = make_source(Path(args.filename), sys.stdin.buffer.read())
        diagnostics = run_sources(
            [src], select=select, ignore=ignore, enable=enable, scopes=("file",),
        )
        files = [Path(args.filename)]
    else:
        # A path that does not exist is a mistake, not an empty check: `xbsl e1c/sit` used to
        # answer "0 files checked, 0 findings" with the exit code of a clean run, so a typo in
        # a CI step passed for a green check of the whole project. The same shape covers a
        # mistyped subcommand - an unknown name is parsed as a path (`list-rules` against
        # `--list-rules`).
        missing = [p for p in (args.paths or []) if not Path(p).exists()]
        if missing:
            print(i18n.t("cli.missing-paths", paths=", ".join(f"'{p}'" for p in missing)),
                  file=sys.stderr)
            return 2
        files, requested = discover_with_context(args.paths or ["."])
        if not files:
            # The paths exist but hold no sources at all: not an error (an empty directory is
            # a legitimate state of a fresh project), yet worth saying out loud - silence here
            # reads as "everything is clean".
            asked = args.paths or ["."]
            print(i18n.t("cli.nothing-collected", paths=", ".join(f"'{p}'" for p in asked)),
                  file=sys.stderr)
        if args.fix:
            # --fix rewrites the buffers in place - it needs the sources in this process.
            sources = [load(p) for p in files]
            diagnostics = _filter_requested(
                run_sources(sources, select=select, ignore=ignore, enable=enable), requested,
            )
            return _apply_fixes(sources, diagnostics, args)
        from xbsl.engine import run_parallel

        diagnostics = _filter_requested(
            run_parallel(
                files, select=select, ignore=ignore, enable=enable,
                jobs=args.jobs, element_version=args.element_version or None,
            ),
            requested,
        )
        if requested is not None:
            files = requested  # the counters below speak of what was asked for

    if args.write_baseline:
        # Freeze mode: the findings become the baseline instead of a report. Deliberate debt –
        # the run itself succeeds regardless of severities.
        target = Path(args.write_baseline)
        data = baseline.write(target, diagnostics)
        print(
            i18n.t("cli.baseline-written", path=target,
                   diags=len(diagnostics), files=len(data["files"])),
            file=sys.stderr,
        )
        return 0

    suppressed = unused = None
    stale: list[dict] = []
    if not args.baseline and not args.no_baseline:
        found = baseline.discover(files)
        if found is not None:
            args.baseline = str(found)
            if args.format == "text":
                print(i18n.t("cli.baseline-found", path=found), file=sys.stderr)
    if args.baseline:
        try:
            data = baseline.load(Path(args.baseline))
        except baseline.BaselineError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        diagnostics, suppressed, unused, stale = baseline.apply(
            diagnostics, data, Path(args.baseline).parent,
        )
        # The stale entries are named, not just counted: without the list the only way to
        # find them was to rewrite the whole baseline and diff it.
        if (args.stale_baseline or args.prune_baseline) and args.format == "text":
            for entry in stale:
                print(i18n.t(
                    "cli.baseline-stale-entry", path=entry["path"], rule=entry["rule"],
                    count=entry["count"], message=entry["message"],
                ), file=sys.stderr)
        if args.prune_baseline:
            target = Path(args.baseline)
            if stale:
                baseline.save(target, baseline.without_entries(data, stale))
            print(i18n.t("cli.baseline-pruned", path=target, removed=len(stale)),
                  file=sys.stderr)

    if args.format == "json":
        # Machine-readable: the whole payload on stdout (or in --out), nothing on stderr.
        payload = report.report(diagnostics, len(files))
        if suppressed is not None:
            payload["summary"]["baselined"] = suppressed
            # Two different units, both useful: `unused` counts the suppressions nobody
            # spent, `stale` the entries they belong to (one entry may allow several).
            payload["summary"]["baseline_unused"] = unused
            payload["summary"]["baseline_stale"] = len(stale)
            payload["summary"]["baseline_stale_entries"] = stale
        _emit_report(json.dumps(payload, ensure_ascii=False), args.out)
    elif args.format == "codeclimate":
        # GitLab Code Quality report: the issue array on stdout, nothing on stderr.
        # Paths are made relative to the current directory – run from the repository root.
        _emit_report(json.dumps(report.codeclimate(diagnostics), ensure_ascii=False), args.out)
    else:
        if args.out:
            lines = [d.format() for d in sorted(diagnostics, key=lambda x: x.sort_key())]
            _emit_report("\n".join(lines), args.out)
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
        if suppressed is not None:
            # The count names ENTRIES, as the text promises; `unused` counts the individual
            # suppressions behind them and lives in the json payload.
            print(
                i18n.t("cli.baseline-summary", suppressed=suppressed, unused=len(stale)),
                file=sys.stderr,
            )

    return 1 if any(d.severity.value == "error" for d in diagnostics) else 0


if __name__ == "__main__":
    raise SystemExit(main())
