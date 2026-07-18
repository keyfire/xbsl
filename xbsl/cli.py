"""Command-line entry point: xbsl / python -m xbsl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xbsl import __version__, baseline, dataset, engine, i18n, report
from xbsl.templates import DEFAULT_FILE as DEFAULT_TEMPLATES_FILE


def discover(paths: list[str]) -> list[Path]:
    """Collect source files (.xbsl and .yaml) under the given paths."""
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if p.suffix in (".xbsl", ".yaml"):
                out.append(p)
        elif p.is_dir():
            out.extend(engine.find_sources(p, "*.xbsl"))
            out.extend(engine.find_sources(p, "*.yaml"))
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
        prog="xbsl",
        description="Линтер исходников 1С:Элемент (пары .yaml/.xbsl).",
    )
    parser.add_argument("paths", nargs="*", default=["."], help="файлы или каталоги для проверки")
    parser.add_argument(
        "--select",
        metavar="ID/ГРУППА/ТИР",
        action="append",
        help="проверять только эти правила (через запятую или повтором флага: id, группа – "
             "часть id до '/' (напр. style) – или буква тира A/B/C/D)",
    )
    parser.add_argument(
        "--ignore",
        metavar="ID/ГРУППА/ТИР",
        action="append",
        help="исключить эти правила (через запятую или повтором флага: id, группа или буква тира)",
    )
    parser.add_argument(
        "--enable",
        metavar="ID/ГРУППА/ТИР",
        action="append",
        help="добавить выключенные по умолчанию правила ПОВЕРХ стандартного набора "
             "(--select набор заменяет); формы значений те же",
    )
    parser.add_argument(
        "--baseline",
        metavar="ФАЙЛ",
        help="гасить находки, замороженные в файле базлайна (создаётся --write-baseline); "
             "новые находки выводятся как обычно",
    )
    parser.add_argument(
        "--write-baseline",
        metavar="ФАЙЛ",
        help="вместо отчёта записать все текущие находки в файл базлайна "
             "(заморозить долг; пути в файле – относительно его каталога)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="исправить механические находки на месте (хвостовые пробелы, типографские "
             "символы, переводы строк) и вывести оставшиеся; правит только однозначно",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=0,
        metavar="N",
        help="процессов для файловых правил: 0 – авто (включается на больших прогонах), "
             "1 – последовательно, N – явное число воркеров",
    )
    parser.add_argument(
        "--list-rules", action="store_true", help="вывести список правил и выйти"
    )
    parser.add_argument(
        "--where",
        action="store_true",
        help="показать корень данных Элемента (путь, источник, версии) и выйти",
    )
    parser.add_argument(
        "--element-version",
        metavar="ВЕРСИЯ",
        help="версия данных Элемента (по умолчанию – последняя из бандла)",
    )
    parser.add_argument(
        "--data-dir",
        metavar="КАТАЛОГ",
        help="корень данных Элемента (каталог с index.json); также env XBSL_DATA_DIR",
    )
    parser.add_argument(
        "--lang",
        choices=i18n.LANGS,
        help="язык вывода линтера (по умолчанию: env XBSL_LANG / локаль системы / ru)",
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
    parser.add_argument("--version", action="version", version=f"xbsl {__version__}{data_note}")
    return parser


def _parse_set(values: list[str] | None) -> set[str] | None:
    # action="append" collects repeated flags; each value may itself be a comma-separated list.
    if not values:
        return None
    parts = {part.strip() for value in values for part in value.split(",") if part.strip()}
    return parts or None


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
        print(json.dumps(report.report(remaining, len(sources)), ensure_ascii=False))
    elif args.format == "codeclimate":
        print(json.dumps(report.codeclimate(remaining), ensure_ascii=False))
    else:
        for d in sorted(remaining, key=lambda x: x.sort_key()):
            print(d.format())
    print(
        i18n.t("cli.fix-summary", fixed=fixed, files=files_changed, left=len(remaining)),
        file=sys.stderr,
    )
    return 1 if any(d.severity.value == "error" for d in remaining) else 0


_META_COMMANDS = (
    "new-project", "new-object", "add-field", "add-route", "add-form",
    "add-subsystem", "add-dependency", "rename-object", "set-access",
    "object-info", "project-info", "form-tree", "form-edit", "form-handlers",
)
_SERVER_COMMANDS = ("lsp", "mcp", "web")

def _templates_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xbsl templates",
        description="шаблоны кода: встроенный набор и файл пользователя (формат выгрузки EDT)",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("list", help="перечислить шаблоны (встроенные и пользовательские)")
    p.add_argument("--format", choices=("text", "json"), default="text")

    p = sub.add_parser("export", help="выгрузить шаблоны в файл формата EDT")
    p.add_argument("--output", required=True, help="куда писать выгрузку")
    p.add_argument("--custom-only", action="store_true",
                   help="только шаблоны пользователя, без встроенных")

    p = sub.add_parser("import", help="влить выгрузку в файл шаблонов пользователя")
    p.add_argument("source", help="выгрузка (наша или из 1С:EDT)")

    sub.add_parser("save", help="заменить файл шаблонов пользователя (конверт JSON из stdin)")

    # Every subcommand takes --file: on the parent, argparse would demand it BEFORE the
    # subcommand ("templates --file X import Y") - that reads backwards and is easy to forget.
    for sp in sub.choices.values():
        sp.add_argument(
            "--file", default=DEFAULT_TEMPLATES_FILE,
            help=f"файл шаблонов пользователя (по умолчанию {DEFAULT_TEMPLATES_FILE}); "
                 "дополняет встроенный набор, одноимённые шаблоны замещает",
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
    parser = argparse.ArgumentParser(
        prog="xbsl", description="Скаффолдинг метаданных 1С:Элемент (вывод – JSON)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("new-project", help="создать проект: Проект.yaml + Проект.xbsl + подсистема")
    p.add_argument("root")
    p.add_argument("vendor")
    p.add_argument("name")
    p.add_argument("--representation")
    p.add_argument("--version", default="1.0.0")
    p.add_argument("--compatibility", default="9.0")
    p.add_argument("--subsystem", default="Основное")
    p.add_argument("--library", action="store_true")

    p = sub.add_parser("new-object", help="создать объект конфигурации (yaml + модуль по виду)")
    p.add_argument("directory")
    p.add_argument("kind")
    p.add_argument("name")
    p.add_argument("--scope")
    p.add_argument("--environment")
    p.add_argument("--access")
    p.add_argument("--routes", help='маршруты HttpСервис: "GET /, POST /, GET /{id}"')
    p.add_argument("--report", help="описание отчёта (JSON: source, rows, columns, measures)")

    p = sub.add_parser("add-field", help="добавить реквизит/измерение/ресурс/значение/ТЧ")
    p.add_argument("yaml_path")
    p.add_argument("field_kind", help=", ".join(("реквизит", "измерение", "ресурс", "значение",
                                                 "параметр", "поле", "табличная-часть")))
    p.add_argument("name")
    p.add_argument("--type", default="Строка")
    p.add_argument("--tabular", help="имя табличной части (реквизит добавляется в неё)")

    p = sub.add_parser("add-route", help="добавить маршруты в существующий HttpСервис")
    p.add_argument("yaml_path")
    p.add_argument("routes")

    p = sub.add_parser("add-form", help="создать формы объекта и зарегистрировать в Интерфейс")
    p.add_argument("root")
    p.add_argument("--name")
    p.add_argument("--path", help="yaml объекта (вместо --name)")
    p.add_argument("--forms", help="подмножество object,list,list-cards,report через запятую "
                                   "(list-cards – список карточками, вместо list)")
    p.add_argument("--card-min-width", type=int,
                   help="ширина колонки сетки карточек (по умолчанию 400, с фото – 250)")
    p.add_argument("--card-placeholder",
                   help='выражение картинки-заглушки, напр. "Ресурс{Аккаунт.svg}.Ссылка"')
    p.add_argument("--overwrite", action="store_true")

    p = sub.add_parser("add-subsystem", help="создать подсистему (папка + Подсистема.yaml)")
    p.add_argument("parent_dir")
    p.add_argument("name")
    p.add_argument("--representation")
    p.add_argument("--no-auto-interface", action="store_true")
    p.add_argument("--uses", help="имена подсистем через запятую")

    p = sub.add_parser(
        "add-dependency", help="подключить библиотеку к проекту (раздел Библиотеки Проект.yaml)"
    )
    p.add_argument("root")
    p.add_argument("vendor", help="поставщик библиотеки")
    p.add_argument("name", help="имя библиотеки")
    p.add_argument("version", help="версия релиза библиотеки, например 2.0")
    p.add_argument("--path", help="Проект.yaml (при нескольких проектах под корнем)")

    p = sub.add_parser(
        "rename-object",
        help="переименовать объект (файлы, формы) и обновить ссылки по всему проекту",
    )
    p.add_argument("root")
    p.add_argument("old_name")
    p.add_argument("new_name")
    p.add_argument("--new-presentation", help="новое Представление/Заголовок (по умолчанию – новое имя)")
    p.add_argument("--old-presentation", help="старое представление (для замены в Заголовок/Представление)")
    p.add_argument("--path", help="yaml объекта (при нескольких объектах с одним именем)")

    p = sub.add_parser("set-access", help="задать КонтрольДоступа.Разрешения объекта")
    p.add_argument("root")
    p.add_argument("--name")
    p.add_argument("--path", help="yaml объекта (вместо --name)")
    p.add_argument("--default", help="способ для права ПоУмолчанию")
    p.add_argument("--permission", action="append", metavar="ПРАВО=СПОСОБ",
                   help="способ отдельного права (повторяемый), напр. Чтение=РазрешеноВсем")
    p.add_argument("--calc-by", help="поля РасчетРазрешенийПо через запятую "
                                     "(обязательны для РазрешенияВычисляютсяДляКаждогоОбъекта)")

    p = sub.add_parser("object-info", help="сводка объекта: реквизиты, ТЧ, формы, namespace")
    p.add_argument("root")
    p.add_argument("--name")
    p.add_argument("--path")

    p = sub.add_parser("project-info", help="обзор исходников: проекты, подсистемы, объекты")
    p.add_argument("root")

    p = sub.add_parser(
        "form-tree", help="дерево компонента интерфейса (узлы, слоты, свойства со спанами)"
    )
    p.add_argument("yaml_path")
    p.add_argument("--at", type=int, metavar="СМЕЩЕНИЕ",
                   help="вместо дерева вернуть узел по смещению в файле (синхронизация курсора)")

    p = sub.add_parser(
        "form-edit",
        help="операция конструктора форм: точечная правка yaml компонента интерфейса",
    )
    p.add_argument("yaml_path")
    p.add_argument("op", choices=("insert", "insert-fragment", "move", "remove", "wrap",
                                  "unwrap", "duplicate", "rename",
                                  "set-property", "reset-property",
                                  "property-add", "property-retype", "property-remove",
                                  "property-rename"))
    p.add_argument("--parent", help="id узла-контейнера (insert/insert-fragment)")
    p.add_argument("--slot", help="слот детей: Содержимое, Страницы, Колонки, ... (insert/move)")
    p.add_argument("--type", help="Тип нового компонента (insert) или свойства (property-add)")
    p.add_argument("--name", help="Имя нового компонента (insert), обёртки (wrap) "
                                  "или свойства секции Свойства (property-*)")
    p.add_argument("--node", help="id узла операции (move/remove/wrap/unwrap/duplicate/"
                                  "rename/set-property/reset-property)")
    p.add_argument("--new-parent", help="id нового контейнера (move)")
    p.add_argument("--container", help="Тип контейнера-обёртки (wrap)")
    p.add_argument("--new-name", help="новое Имя узла (rename) или свойства (property-rename); "
                                      "для rename без флага Имя удаляется")
    p.add_argument("--before", help="id соседа: вставить/переместить ПЕРЕД ним")
    p.add_argument("--after", help="id соседа: вставить/переместить ПОСЛЕ него")
    p.add_argument("--key", help="имя свойства узла (set-property/reset-property)")
    p.add_argument("--value", help="скалярное значение или биндинг (set-property)")
    p.add_argument("--value-yaml", help="составное значение готовым yaml-фрагментом (set-property)")
    p.add_argument("--fragment", help="yaml-блок ОДНОГО компонента (insert-fragment)")
    p.add_argument("--fragment-file", metavar="ФАЙЛ",
                   help="файл с yaml-блоком компонента (insert-fragment, вместо --fragment)")
    p.add_argument("--new-type", help="новый Тип свойства (property-retype)")

    p = sub.add_parser(
        "form-handlers",
        help="обработчики парного модуля компонента: список методов или заготовка обработчика",
    )
    p.add_argument("yaml_path")
    p.add_argument("--node", help="id узла (создание обработчика; без --node/--key – "
                                  "список методов модуля)")
    p.add_argument("--key", help="ключ события узла: ПриНажатии, ПослеСоздания, ...")
    p.add_argument("--method", help="имя метода-обработчика (по умолчанию <Имя узла><Ключ>; "
                                    "существующий метод – только привязка в yaml)")
    p.add_argument("--signature", help='сигнатура события из ui-схемы, напр. '
                                       '"(Кнопка, СобытиеПриНажатии)->ничто" '
                                       '(без флага ищется в локальных данных)')

    for name, sp in sub.choices.items():
        if name.endswith("-info") or name == "form-tree":
            continue
        sp.add_argument("--dry-run", action="store_true",
                        help="показать изменения (с текстами файлов), ничего не записывая")
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
                routes=args.routes,
                report=json.loads(args.report) if args.report else None,
            )
        elif args.command == "add-field":
            result = scaffold.op_add_field(
                Path(args.yaml_path), args.field_kind, args.name,
                type_=args.type, tabular=args.tabular,
            )
        elif args.command == "add-route":
            result = scaffold.op_add_route(Path(args.yaml_path), args.routes)
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
                payload = {"root": formmodel.node_dict(form.root)}
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
                "name": args.name, "node": args.node, "new_parent": args.new_parent,
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

        sp = argparse.ArgumentParser(prog="xbsl self-update",
                                     description="обновить xbsl распаковкой колеса с PyPI")
        sp.add_argument("--version", help="целевая версия (по умолчанию – последняя с PyPI)")
        sp_args = sp.parse_args(argv[1:])
        try:
            old, new = selfupdate.self_update(version=sp_args.version,
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
    if argv and argv[0] in _META_COMMANDS:
        return _scaffold_main(argv)
    if argv[:1] == ["lint"]:
        argv = argv[1:]  # an explicit alias of the default mode

    parser = build_parser()
    args = parser.parse_args(argv)

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
        files = discover(args.paths or ["."])
        if args.fix:
            # --fix rewrites the buffers in place - it needs the sources in this process.
            sources = [load(p) for p in files]
            diagnostics = run_sources(sources, select=select, ignore=ignore, enable=enable)
            return _apply_fixes(sources, diagnostics, args)
        from xbsl.engine import run_parallel

        diagnostics = run_parallel(
            files, select=select, ignore=ignore, enable=enable,
            jobs=args.jobs, element_version=args.element_version or None,
        )

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
    if args.baseline:
        try:
            data = baseline.load(Path(args.baseline))
        except baseline.BaselineError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        diagnostics, suppressed, unused = baseline.apply(
            diagnostics, data, Path(args.baseline).parent,
        )

    if args.format == "json":
        # Machine-readable: the whole payload on stdout, nothing on stderr.
        payload = report.report(diagnostics, len(files))
        if suppressed is not None:
            payload["summary"]["baselined"] = suppressed
            payload["summary"]["baseline_unused"] = unused
        print(json.dumps(payload, ensure_ascii=False))
    elif args.format == "codeclimate":
        # GitLab Code Quality report: the issue array on stdout, nothing on stderr.
        # Paths are made relative to the current directory – run from the repository root.
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
        if suppressed is not None:
            print(
                i18n.t("cli.baseline-summary", suppressed=suppressed, unused=unused),
                file=sys.stderr,
            )

    return 1 if any(d.severity.value == "error" for d in diagnostics) else 0


if __name__ == "__main__":
    raise SystemExit(main())
