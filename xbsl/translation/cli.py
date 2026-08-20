"""The `xbsl translate` command: translate a project, measure coverage, emit stubs.

Modes compose from flags around one pass over the project:

- no flags: the coverage summary alone - the cheap health check;
- `--coverage`: plus the per-object breakdown;
- `--missing FILE`: write the untranslated remainder as a dictionary stub to fill;
- `--out DIR`: write the translated tree;
- `--strict`: exit non-zero unless the coverage is complete and no problems were found -
  what a CI gate wants ("publish only a fully translated, lint-clean configuration").
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from xbsl import dataset, i18n

MESSAGES = {
    "translate.help.description": {
        "ru": "Перевести исходники проекта на английские написания",
        "en": "Translate the project sources into English spellings",
    },
    "translate.help.root": {
        "ru": "каталог проекта (с Проект.yaml)",
        "en": "the project directory (with its project descriptor)",
    },
    "translate.help.out": {
        "ru": "куда записать переведённое дерево (без флага – только отчёт)",
        "en": "where to write the translated tree (without it - report only)",
    },
    "translate.help.dictionary": {
        "ru": "словарь проекта: файл или каталог (по умолчанию ищется xbsl-translation рядом и выше)",
        "en": "the project dictionary: a file or a directory (default: xbsl-translation next to or above the project)",
    },
    "translate.help.missing": {
        "ru": "записать непереведённый остаток заготовкой словаря в файл",
        "en": "write the untranslated remainder as a dictionary stub file",
    },
    "translate.help.gaps": {
        "ru": "показать непереведённое таблицей (с частотой, местами и предложением)",
        "en": "list the untranslated entries as a table (count, places, suggestion)",
    },
    "translate.help.entries": {
        "ru": "показать записи словаря таблицей (ключ, перевод, файл, строка)",
        "en": "list the dictionary entries as a table (key, value, file, line)",
    },
    "translate.help.set": {
        "ru": "применить правки словаря из файла JSON: [{{key, value, kind}}]",
        "en": "apply dictionary edits from a JSON file: [{{key, value, kind}}]",
    },
    "translate.help.target": {
        "ru": "файл словаря для НОВЫХ записей (по умолчанию 090-manual.yaml)",
        "en": "the dictionary file NEW entries go to (default 090-manual.yaml)",
    },
    "translate.help.filter": {
        "ru": "отбор по подстроке ключа или перевода",
        "en": "filter by a substring of the key or the value",
    },
    "translate.help.kind": {
        "ru": "что показывать: имена, строки комментариев или всё",
        "en": "what to list: names, comment lines or both",
    },
    "translate.help.limit": {
        "ru": "сколько строк отдать (0 – все)",
        "en": "how many rows to return (0 - all)",
    },
    "translate.help.offset": {
        "ru": "с какой строки начать",
        "en": "the row to start from",
    },
    "translate.applied": {
        "ru": "словарь обновлён: изменено {changed}, добавлено {added}, снято {removed}",
        "en": "dictionary updated: {changed} changed, {added} added, {removed} removed",
    },
    "translate.set-unreadable": {
        "ru": "правки не прочитаны: {error}",
        "en": "the edits did not parse: {error}",
    },
    "translate.help.coverage": {
        "ru": "показать покрытие по каждому объекту метаданных",
        "en": "print the coverage of every metadata object",
    },
    "translate.help.strict": {
        "ru": "ненулевой выход, если покрытие неполное или есть проблемы",
        "en": "non-zero exit when the coverage is incomplete or problems were found",
    },
    "translate.help.no-swap": {
        "ru": "не переворачивать словари локализации (база останется на исходном языке)",
        "en": "keep the localized-strings layout (the base stays in the source language)",
    },
    "translate.help.format": {
        "ru": "формат отчёта",
        "en": "the report format",
    },
    "translate.no-root": {
        "ru": "каталог проекта не найден: {path}",
        "en": "the project directory does not exist: {path}",
    },
    "translate.no-dictionary": {
        "ru": "словарь не найден – ни флага --dictionary, ни каталога xbsl-translation рядом с проектом; перевод считается пустым словарём",
        "en": "no dictionary found - neither --dictionary nor an xbsl-translation directory near the project; translating with an empty dictionary",
    },
    "translate.dictionary-error": {
        "ru": "словарь не загрузился: {error}",
        "en": "the dictionary did not load: {error}",
    },
    "translate.summary": {
        "ru": "файлов: {files}; поверхностей проекта: {surfaces}; переведено: {translated}; покрытие: {coverage:.1%}",
        "en": "files: {files}; project surfaces: {surfaces}; translated: {translated}; coverage: {coverage:.1%}",
    },
    "translate.summary-missing": {
        "ru": "не переведено: токенов {tokens}, фраз {phrases}; пробелов данных платформы: {platform}",
        "en": "untranslated: {tokens} tokens, {phrases} phrases; platform data gaps: {platform}",
    },
    "translate.summary-kept": {
        "ru": "оставлено как данные (тексты): {texts}; предупреждений: {warnings}",
        "en": "kept as data (texts): {texts}; warnings: {warnings}",
    },
    "translate.summary-data-keys": {
        "ru": "ключей json-ресурсов переименовано вслед за полями структур: {keys}",
        "en": "json resource keys renamed after their structure fields: {keys}",
    },
    "translate.problems": {
        "ru": "проблемы ({count}):",
        "en": "problems ({count}):",
    },
    "translate.written": {
        "ru": "записано файлов: {count} -> {out}",
        "en": "files written: {count} -> {out}",
    },
    "translate.stub-written": {
        "ru": "заготовка словаря: {path} (токенов {tokens}, фраз {phrases})",
        "en": "dictionary stub: {path} ({tokens} tokens, {phrases} phrases)",
    },
    "translate.coverage-header": {
        "ru": "покрытие по объектам (только неполные):",
        "en": "coverage by object (incomplete only):",
    },
    "translate.entries-header": {
        "ru": "записей словаря: {shown} из {total}",
        "en": "dictionary entries: {shown} of {total}",
    },
    "translate.gaps-header": {
        "ru": "непереведённых: {shown} из {total}",
        "en": "untranslated: {shown} of {total}",
    },
    "translate.platform-gaps-header": {
        "ru": "платформенные токены без английского написания в данных:",
        "en": "platform tokens with no English spelling in the data:",
    },
}
i18n.register(MESSAGES)


def _parser() -> argparse.ArgumentParser:
    parser = i18n.ArgumentParser(
        prog="xbsl translate",
        description=i18n.t("translate.help.description"),
    )
    parser.add_argument("root", help=i18n.t("translate.help.root"))
    parser.add_argument("--out", help=i18n.t("translate.help.out"))
    parser.add_argument("--dictionary", action="append", help=i18n.t("translate.help.dictionary"))
    parser.add_argument("--missing", help=i18n.t("translate.help.missing"))
    parser.add_argument("--coverage", action="store_true", help=i18n.t("translate.help.coverage"))
    parser.add_argument("--gaps", action="store_true", help=i18n.t("translate.help.gaps"))
    parser.add_argument("--entries", action="store_true", help=i18n.t("translate.help.entries"))
    parser.add_argument("--set", dest="set_file", help=i18n.t("translate.help.set"))
    parser.add_argument("--target", default=None, help=i18n.t("translate.help.target"))
    parser.add_argument("--filter", default="", help=i18n.t("translate.help.filter"))
    parser.add_argument("--kind", choices=("token", "phrase", "any"), default="any",
                        help=i18n.t("translate.help.kind"))
    parser.add_argument("--limit", type=int, default=0, help=i18n.t("translate.help.limit"))
    parser.add_argument("--offset", type=int, default=0, help=i18n.t("translate.help.offset"))
    parser.add_argument("--strict", action="store_true", help=i18n.t("translate.help.strict"))
    parser.add_argument("--no-localization-swap", action="store_true",
                        help=i18n.t("translate.help.no-swap"))
    parser.add_argument("--format", choices=("text", "json"), default="text",
                        help=i18n.t("translate.help.format"))
    parser.add_argument("--lang", choices=("ru", "en"), default=None, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--element-version", default=None, help=argparse.SUPPRESS)
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.set_lang(i18n.lang_from_argv(argv))
    args = _parser().parse_args(argv)
    i18n.set_lang(args.lang)
    if args.data_dir:
        dataset.set_data_root(args.data_dir)
    if args.element_version:
        dataset.set_version(args.element_version)
    try:
        dataset.resolve_version()
    except dataset.DatasetError as exc:
        print(i18n.t("cli.data-error", error=exc), file=sys.stderr)
        return 2

    from xbsl.translation import dictionary as dictionary_module
    from xbsl.translation import project as project_module

    root = Path(args.root)
    if not root.is_dir():
        print(i18n.t("translate.no-root", path=root), file=sys.stderr)
        return 2

    try:
        loaded = _load_dictionary(args.dictionary, root, dictionary_module)
    except dictionary_module.DictionaryError as exc:
        print(i18n.t("translate.dictionary-error", error=exc), file=sys.stderr)
        return 2

    # The table modes answer without translating the tree twice: `--entries` reads the
    # dictionary alone, `--set` writes it, and `--gaps` is the one that needs a pass.
    if args.set_file:
        return _apply_edits(args, root, loaded)
    if args.entries:
        return _list_entries(args, root, loaded)
    if args.gaps:
        return _list_gaps(args, root, loaded)

    report = project_module.translate_project(
        root, loaded,
        Path(args.out) if args.out else None,
        swap_localization=not args.no_localization_swap,
    )

    missing_tokens = report.merged_missing_tokens()
    missing_phrases = report.merged_missing_phrases()
    if args.missing:
        dictionary_module.write_stub(
            Path(args.missing), missing_tokens, missing_phrases, language=loaded.language,
        )

    if args.format == "json":
        print(json.dumps(_as_json(report, args), ensure_ascii=False, indent=1))
    else:
        _print_text(report, args, missing_tokens, missing_phrases)

    totals = report.totals()
    if args.strict and (totals["missing"] or report.problems):
        return 1
    return 0


def _load_dictionary(paths, root, dictionary_module):
    if paths:
        merged = None
        for raw in paths:
            one = dictionary_module.load(Path(raw))
            if merged is None:
                merged = one
            else:
                for key, value in one.tokens.items():
                    merged.tokens.setdefault(key, value)
                for key, value in one.phrases.items():
                    merged.phrases.setdefault(key, value)
        return merged
    found = dictionary_module.discover(root)
    if found is None:
        print(i18n.t("translate.no-dictionary"), file=sys.stderr)
        return dictionary_module.Dictionary()
    return dictionary_module.load(found)


def _as_json(report, args) -> dict:
    out = {
        "totals": report.totals(),
        "problems": report.problems,
        "missing_tokens": report.merged_missing_tokens(),
        "missing_phrases": report.merged_missing_phrases(),
        "platform_gaps": report.merged_platform_gaps(),
        "renames": report.renames,
        "warnings": {
            rel: [list(w) for w in fr.warnings]
            for rel, fr in report.files.items() if fr.warnings
        },
        "texts_kept": {
            rel: fr.texts_kept for rel, fr in report.files.items() if fr.texts_kept
        },
    }
    if args.coverage:
        out["coverage"] = [
            {"object": key, "translated": done, "total": total}
            for key, done, total in report.coverage_by_object()
        ]
    return out


def _print_text(report, args, missing_tokens, missing_phrases) -> None:
    totals = report.totals()
    print(i18n.t("translate.summary", **{k: totals[k] for k in ("files", "surfaces", "translated", "coverage")}))
    print(i18n.t(
        "translate.summary-missing",
        tokens=totals["missing_tokens"], phrases=totals["missing_phrases"],
        platform=totals["platform_gaps"],
    ))
    print(i18n.t("translate.summary-kept", texts=totals["texts_kept"], warnings=totals["warnings"]))
    if totals["data_keys"]:
        print(i18n.t("translate.summary-data-keys", keys=totals["data_keys"]))
    if report.problems:
        print(i18n.t("translate.problems", count=len(report.problems)))
        for problem in report.problems:
            print(f"  {problem}")
    gaps = report.merged_platform_gaps()
    if gaps:
        print(i18n.t("translate.platform-gaps-header"))
        for name, info in sorted(gaps.items(), key=lambda kv: -kv[1]["count"])[:20]:
            print(f"  {name}  ({info['count']}x, {info['sample']})")
    if args.coverage:
        print(i18n.t("translate.coverage-header"))
        for key, done, total in report.coverage_by_object():
            if done < total:
                print(f"  {key}: {done}/{total}")
    if args.missing:
        print(i18n.t(
            "translate.stub-written",
            path=args.missing, tokens=len(missing_tokens), phrases=len(missing_phrases),
        ))
    if args.out:
        print(i18n.t("translate.written", count=report.written, out=args.out))


# --- the table modes ---------------------------------------------------------------------


def _dictionary_path(args, root: Path) -> Path | None:
    """Where the dictionary lives: the flag, or the one discovered next to the project."""
    from xbsl.translation import entries as entries_module

    if args.dictionary:
        return Path(args.dictionary[0])
    return entries_module.discover(root)


def _emit(args, payload: dict, rows: list[dict], render) -> int:
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        render(rows)
    return 0


def _page(rows: list, args) -> list:
    """The requested slice of the rows: `--offset` then `--limit`."""
    start = max(args.offset, 0)
    end = start + args.limit if args.limit else None
    return rows[start:end]


def _list_entries(args, root: Path, loaded) -> int:
    from xbsl.translation import entries as entries_module

    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2
    needle = args.filter.casefold()
    rows = [
        entry for entry in entries_module.read_entries(path)
        if (args.kind in ("any", entry.kind))
        and (not needle or needle in entry.key.casefold() or needle in entry.value.casefold())
    ]
    total = len(rows)
    page = _page(rows, args)
    payload = {
        "dictionary": str(path), "total": total,
        "entries": [entry.as_dict() for entry in page],
    }

    def render(_rows):
        print(i18n.t("translate.entries-header", shown=len(page), total=total))
        for entry in page:
            print(f"  {entry.kind:6} {entry.key}  ->  {entry.value}")

    return _emit(args, payload, page, render)


def _list_gaps(args, root: Path, loaded) -> int:
    from xbsl.translation import entries as entries_module

    needle = args.filter.casefold()
    rows = [
        gap for gap in entries_module.gaps_of_project(root, loaded)
        if (args.kind in ("any", gap.kind)) and (not needle or needle in gap.key.casefold())
    ]
    total = len(rows)
    page = _page(rows, args)
    payload = {
        "dictionary": str(_dictionary_path(args, root) or ""), "total": total,
        "gaps": [gap.as_dict() for gap in page],
    }

    def render(_rows):
        print(i18n.t("translate.gaps-header", shown=len(page), total=total))
        for gap in page:
            place = f"{gap.places[0][0]}:{gap.places[0][1]}" if gap.places else ""
            hint = f"  ~ {gap.suggestion}" if gap.suggestion else ""
            print(f"  {gap.count:5}x {gap.kind:6} {gap.key}{hint}   {place}")

    return _emit(args, payload, page, render)


def _apply_edits(args, root: Path, loaded) -> int:
    from xbsl.translation import entries as entries_module

    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2
    try:
        raw = json.loads(Path(args.set_file).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(i18n.t("translate.set-unreadable", error=exc), file=sys.stderr)
        return 2
    edits = raw.get("edits") if isinstance(raw, dict) else raw
    if not isinstance(edits, list):
        print(i18n.t("translate.set-unreadable", error="expected a list of edits"), file=sys.stderr)
        return 2
    result = entries_module.write_entries(
        path, edits, target=args.target or entries_module.DEFAULT_TARGET,
    )
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(i18n.t("translate.applied", **result))
    return 0


# --- the shared entry point of the tool surfaces --------------------------------------------


def dictionary_path_for(root: Path) -> Path | None:
    """The dictionary that serves this project, or None."""
    from xbsl.translation import entries as entries_module

    return entries_module.discover(root)


def load_for_tools(root: str) -> tuple[Path, object, str]:
    """(project path, loaded dictionary, error) - what MCP and LSP need before answering.

    An empty error means the pair is usable; a project with no dictionary still answers, with
    an empty one, so a caller can ask "what is missing" before the first entry exists.
    """
    from xbsl.translation import dictionary as dictionary_module

    project = Path(root)
    if not project.is_dir():
        return project, None, i18n.t("translate.no-root", path=project)
    found = dictionary_path_for(project)
    if found is None:
        return project, dictionary_module.Dictionary(), ""
    try:
        return project, dictionary_module.load(found), ""
    except dictionary_module.DictionaryError as exc:
        return project, None, i18n.t("translate.dictionary-error", error=exc)
