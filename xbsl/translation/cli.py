"""The `xbsl translate` command: translate a project, measure coverage, emit stubs.

Modes compose from flags around one pass over the project:

- no flags: the coverage summary alone - the cheap health check;
- `--coverage`: plus the per-object breakdown;
- `--missing FILE`: write the untranslated remainder as a dictionary stub to fill;
- `--out DIR`: write the translated tree;
- `--strict`: exit non-zero unless the coverage is complete, the platform data spells every
  name the sources use, and no problems were found - what a CI gate wants ("publish only a
  fully translated, lint-clean configuration").
"""

from __future__ import annotations

import argparse
import json
import os
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
    "translate.help.table": {
        "ru": "показать всё, что нужно панели, за один проход: записи, пропуски и сводку",
        "en": "everything the editor table shows in ONE pass: entries, gaps and the totals",
    },
    "translate.help.set": {
        "ru": "применить правки словаря из файла: либо yaml формата самого словаря (секции"
              " tokens/phrases/literals, пустое значение снимает запись), либо JSON"
              " [{{key, value, kind}}]; у литерала ключ и перевод – текст между кавычками"
              " ровно так, как он написан в исходнике (кавычка внутри – \\\", обратный"
              " слеш – \\\\)",
        "en": "apply dictionary edits from a file: either the dictionary's own yaml format"
              " (tokens/phrases/literals sections, an empty value removes the entry) or the"
              " JSON list [{{key, value, kind}}]; for a literal the key and the value are the"
              " text between the quotes exactly as the source writes it (an inner quote is"
              " \\\", a backslash is \\\\)",
    },
    "translate.help.target": {
        "ru": "файл словаря для НОВЫХ записей (по умолчанию 090-manual.yaml)",
        "en": "the dictionary file NEW entries go to (default 090-manual.yaml)",
    },
    "translate.help.comment": {
        "ru": "заголовок НОВОГО файла словаря: чему посвящена порция записей",
        "en": "the head line of a NEW dictionary file: what this batch of entries is about",
    },
    "translate.help.filter": {
        "ru": "отбор по подстроке ключа или перевода",
        "en": "filter by a substring of the key or the value",
    },
    "translate.help.kind": {
        "ru": "что показывать: имена, строки комментариев, строковые литералы или всё",
        "en": "what to list: names, comment lines, string literals or all of them",
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
    "translate.refused": {
        "ru": "не записано записей: {count} – значение не годится телом строкового литерала:",
        "en": "entries not written: {count} - the value is not a valid string-literal body:",
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
        "ru": "ненулевой выход, если покрытие неполное, есть проблемы или платформенные пропуски",
        "en": "non-zero exit when the coverage is incomplete, problems or platform gaps were found",
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
    "translate.summary-literals": {
        "ru": "различных строковых литералов: переведено {done}, осталось кириллических {missing}"
              " (вхождений переведено: {occurrences})",
        "en": "distinct string literals: {done} translated, {missing} left in Cyrillic"
              " ({occurrences} occurrences rewritten)",
    },
    "translate.summary-kept": {
        "ru": "оставлено как данные (тексты): {texts}; предупреждений: {warnings}",
        "en": "kept as data (texts): {texts}; warnings: {warnings}",
    },
    "translate.summary-data-keys": {
        "ru": "ключей json-ресурсов переименовано вслед за полями структур: {keys}",
        "en": "json resource keys renamed after their structure fields: {keys}",
    },
    "translate.warnings-header": {
        "ru": "предупреждения (string-equals-token: литерал равен переименованному имени;"
              " literal-data-value: литерал равен значению данных json-ресурса):",
        "en": "warnings (string-equals-token: a literal equals a renamed name;"
              " literal-data-value: a literal equals a json resource data value):",
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
        "ru": "заготовка словаря: {path} (токенов {tokens}, фраз {phrases}, литералов {literals})",
        "en": "dictionary stub: {path} ({tokens} tokens, {phrases} phrases, {literals} literals)",
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
    "translate.help.suggest": {
        "ru": "добить непереведённое внешним переводчиком: предложения, а не запись в словарь",
        "en": "fill the untranslated remainder with an external translator: suggestions, not writes",
    },
    "translate.help.suggest-out": {
        "ru": "записать предложения планом словаря рядом с остальными: каталог из пути отбрасывается,"
              " берётся только имя файла, и оно ложится внутрь каталога словаря (например 080-machine.yaml);"
              " если словарь – это один файл, отдельного плана нет и записи ложатся в него же",
        "en": "write the suggestions as a dictionary plan next to the others: the directory part of"
              " the path is dropped, only the file name is kept, and it lands inside the dictionary"
              " directory (say 080-machine.yaml); when the dictionary is a single file there is no"
              " separate plan and the records land in that file itself",
    },
    "translate.help.provider": {
        "ru": "сервис перевода: yandex или google (по умолчанию – единственный настроенный)",
        "en": "the translation service: yandex or google (default: the only configured one)",
    },
    "translate.help.plans": {
        "ru": "какие планы добивать через сервис, через запятую (по умолчанию tokens,phrases)",
        "en": "which plans to fill through the service, comma separated (default tokens,phrases)",
    },
    "translate.machine-refused": {
        "ru": "перевод недоступен: {error}",
        "en": "translation unavailable: {error}",
    },
    "translate.machine-report": {
        "ru": "сервис перевода: закэшировано {cached}, запрошено {requested}, отклонено {refused}",
        "en": "translation service: {cached} cached, {requested} requested, {refused} refused",
    },
    "translate.unknown-plans": {
        "ru": "неизвестный план в --plans: {names} (доступные: {valid})",
        "en": "unknown --plans value: {names} (available: {valid})",
    },
    "translate.suggest-unread-flags": {
        "ru": "режим предложений не читает эти флаги: {names}. Прогон идёт по всему проекту"
              " целиком; чтобы посмотреть срез, воспользуйтесь --gaps или --entries",
        "en": "the suggest mode does not read these flags: {names}. The run always covers the"
              " whole project; to look at a slice use --gaps or --entries",
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
    parser.add_argument("--table", action="store_true", help=i18n.t("translate.help.table"))
    parser.add_argument("--set", dest="set_file", help=i18n.t("translate.help.set"))
    parser.add_argument("--suggest", action="store_true", help=i18n.t("translate.help.suggest"))
    parser.add_argument("--suggest-out", dest="suggest_out",
                        help=i18n.t("translate.help.suggest-out"))
    parser.add_argument("--provider", choices=("yandex", "google"), default=None,
                        help=i18n.t("translate.help.provider"))
    parser.add_argument("--plans", default="tokens,phrases", help=i18n.t("translate.help.plans"))
    parser.add_argument("--target", default=None, help=i18n.t("translate.help.target"))
    parser.add_argument("--comment", default="", help=i18n.t("translate.help.comment"))
    parser.add_argument("--filter", default="", help=i18n.t("translate.help.filter"))
    parser.add_argument("--kind", choices=("token", "phrase", "literal", "any"), default="any",
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
    # `--table` is all three at once, and the reason it exists is that the editor panel needs
    # exactly those three: asked apart they cost two identical passes in two processes plus a
    # third that reads the same megabytes of dictionary a third time.
    if args.set_file:
        return _apply_edits(args, root, loaded)
    if args.table:
        return _list_table(args, root, loaded)
    if args.entries:
        return _list_entries(args, root, loaded)
    if args.gaps:
        return _list_gaps(args, root, loaded)
    if args.suggest:
        return _suggest(args, root, loaded)

    report = project_module.translate_project(
        root, loaded,
        Path(args.out) if args.out else None,
        swap_localization=not args.no_localization_swap,
    )

    missing_tokens = report.merged_missing_tokens()
    missing_phrases = report.merged_missing_phrases()
    missing_literals = report.merged_missing_literals()
    if args.missing:
        dictionary_module.write_stub(
            Path(args.missing), missing_tokens, missing_phrases, language=loaded.language,
            missing_literals=missing_literals,
        )

    if args.format == "json":
        print(json.dumps(_as_json(report, args), ensure_ascii=False, indent=1))
    else:
        _print_text(report, args, missing_tokens, missing_phrases, missing_literals)

    totals = report.totals()
    # A platform gap fails the gate as an untranslated name does, and for the same reason: the
    # name stays Cyrillic in the translated tree, so the build refuses it. It is named apart in
    # the report because the CURE is different - not a dictionary entry, which the compiler
    # would refuse, but the platform data.
    if args.strict and (totals["missing"] or totals["platform_gaps"] or report.problems):
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
        "missing_literals": report.merged_missing_literals(),
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


def _print_text(report, args, missing_tokens, missing_phrases, missing_literals) -> None:
    totals = report.totals()
    print(i18n.t("translate.summary", **{k: totals[k] for k in ("files", "surfaces", "translated", "coverage")}))
    print(i18n.t(
        "translate.summary-missing",
        tokens=totals["missing_tokens"], phrases=totals["missing_phrases"],
        platform=totals["platform_gaps"],
    ))
    print(i18n.t("translate.summary-kept", texts=totals["texts_kept"], warnings=totals["warnings"]))
    if totals["literals_translated"] or totals["missing_literals"]:
        print(i18n.t(
            "translate.summary-literals",
            done=totals["literals_translated"], missing=totals["missing_literals"],
            occurrences=totals["literal_occurrences"],
        ))
    if totals["data_keys"]:
        print(i18n.t("translate.summary-data-keys", keys=totals["data_keys"]))
    if totals["warnings"]:
        # The details, not only the count: a warning asks a person to look at ONE place, and
        # a bare number sends them hunting for it with the json mode.
        print(i18n.t("translate.warnings-header"))
        shown = 0
        for rel, file_report in sorted(report.files.items()):
            for kind, line, _col, what in file_report.warnings:
                print(f"  {rel}:{line}  [{kind}]  {what}")
                shown += 1
                if shown >= 20:
                    break
            if shown >= 20:
                break
        if totals["warnings"] > shown:
            print(f"  ... +{totals['warnings'] - shown}")
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
            literals=len(missing_literals),
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


def _entry_rows(args, path: Path) -> list:
    """The dictionary entries the query asks for - `--kind` and `--filter` applied."""
    from xbsl.translation import entries as entries_module

    needle = args.filter.casefold()
    return [
        entry for entry in entries_module.read_entries(path)
        if (args.kind in ("any", entry.kind))
        and (not needle or needle in entry.key.casefold() or needle in entry.value.casefold())
    ]


def _gap_rows(args, gaps: list) -> list:
    """The same query over the gaps - the filter matches a key, a gap has no value yet."""
    needle = args.filter.casefold()
    return [
        gap for gap in gaps
        if (args.kind in ("any", gap.kind)) and (not needle or needle in gap.key.casefold())
    ]


def _render_entries(page: list, total: int) -> None:
    print(i18n.t("translate.entries-header", shown=len(page), total=total))
    for entry in page:
        print(f"  {entry.kind:6} {entry.key}  ->  {entry.value}")


def _render_gaps(page: list, total: int) -> None:
    print(i18n.t("translate.gaps-header", shown=len(page), total=total))
    for gap in page:
        place = f"{gap.places[0][0]}:{gap.places[0][1]}" if gap.places else ""
        hint = f"  ~ {gap.suggestion}" if gap.suggestion else ""
        print(f"  {gap.count:5}x {gap.kind:6} {gap.key}{hint}   {place}")


def _list_entries(args, root: Path, loaded) -> int:
    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2
    rows = _entry_rows(args, path)
    total = len(rows)
    page = _page(rows, args)
    payload = {
        "dictionary": str(path), "total": total,
        "entries": [entry.as_dict() for entry in page],
    }
    return _emit(args, payload, page, lambda _rows: _render_entries(page, total))


def _list_gaps(args, root: Path, loaded) -> int:
    from xbsl.translation import entries as entries_module

    rows = _gap_rows(args, entries_module.gaps_of_project(root, loaded))
    total = len(rows)
    page = _page(rows, args)
    payload = {
        "dictionary": str(_dictionary_path(args, root) or ""), "total": total,
        "gaps": [gap.as_dict() for gap in page],
    }
    return _emit(args, payload, page, lambda _rows: _render_gaps(page, total))


def _list_table(args, root: Path, loaded) -> int:
    """Entries, gaps and the totals out of ONE pass over the project.

    The counts are named apart (`entries_total`, `gaps_total`) rather than shared: a reader
    that saw one `total` over two lists would have to guess which one it counted.
    """
    from xbsl.translation import entries as entries_module
    from xbsl.translation import project as project_module

    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2
    report = project_module.translate_project(
        root, loaded, None, swap_localization=not args.no_localization_swap,
    )
    entries = _entry_rows(args, path)
    gaps = _gap_rows(args, entries_module.gaps_of_report(report))
    entry_page, gap_page = _page(entries, args), _page(gaps, args)
    payload = {
        "dictionary": str(path),
        "entries_total": len(entries),
        "entries": [entry.as_dict() for entry in entry_page],
        "gaps_total": len(gaps),
        "gaps": [gap.as_dict() for gap in gap_page],
        "totals": report.totals(),
        "problems": report.problems,
    }

    def render(_rows):
        _render_entries(entry_page, len(entries))
        _render_gaps(gap_page, len(gaps))

    return _emit(args, payload, entry_page, render)


def _apply_edits(args, root: Path, loaded) -> int:
    from xbsl.translation import entries as entries_module

    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2
    try:
        edits = entries_module.read_edits_file(Path(args.set_file))
    except (OSError, ValueError) as exc:
        print(i18n.t("translate.set-unreadable", error=exc), file=sys.stderr)
        return 2
    result = entries_module.write_entries(
        path, edits, target=args.target or entries_module.DEFAULT_TARGET,
        comment=getattr(args, "comment", "") or "",
    )
    refused = result.get("refused") or []
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(i18n.t("translate.applied", **result))
        if refused:
            print(i18n.t("translate.refused", count=len(refused)), file=sys.stderr)
            for item in refused:
                print(f"  {item['key']}: {item['reason']}", file=sys.stderr)
    return 1 if refused else 0


#: Flags the table modes honor and the suggest mode does not: the flag, the parsed attribute
#: and the value that means "not given". The suggest run always covers the whole project.
SUGGEST_IGNORES = (
    ("--filter", "filter", ""),
    ("--kind", "kind", "any"),
    ("--limit", "limit", 0),
    ("--offset", "offset", 0),
)


def _suggest(args, root: Path, loaded) -> int:
    """Fill the untranslated remainder via an external service: suggestions, not writes.

    A flag this mode cannot honor is refused FIRST: it is a plain usage error, and answering it
    must not depend on whether a key happens to be exported. Then comes the provider, before the
    project is even walked - there is no point parsing the corpus when there is nothing to
    translate with, and the caller wants that refusal to name the environment variables, not get
    lost behind an unrelated complaint.
    """
    from xbsl.translation import entries as entries_module
    from xbsl.translation.machine.cache import Cache
    from xbsl.translation.machine.dispatch import suggest as run_machine
    from xbsl.translation.machine.literals import fill as fill_literals
    from xbsl.translation.machine.provider import MachineError, select

    # `--limit` is the dangerous one: it is what a person reaches for to cap a run that costs
    # money, and honored nowhere here it would hand back a full pass over the project instead.
    ignored = [flag for flag, attribute, absent in SUGGEST_IGNORES
               if getattr(args, attribute) != absent]
    if ignored:
        return _refused(args, i18n.t("translate.suggest-unread-flags", names=", ".join(ignored)))

    try:
        provider = select(args.provider, os.environ)
    except MachineError as exc:
        return _machine_refused(args, exc)

    # A --plans typo must not vanish into an empty, wordless run: caught here, before the
    # dictionary or the project is even touched, so the refusal is cheap and immediate.
    plan_names = {piece.strip() for piece in args.plans.split(",") if piece.strip()}
    unknown_plans = sorted(plan_names - set(entries_module.KIND_OF_SECTION))
    if unknown_plans:
        return _unknown_plans_refused(args, unknown_plans, sorted(entries_module.KIND_OF_SECTION))
    plan_kinds = {entries_module.KIND_OF_SECTION[name] for name in plan_names}

    path = _dictionary_path(args, root)
    if path is None:
        print(i18n.t("translate.entries.no-dictionary"), file=sys.stderr)
        return 2

    gaps = entries_module.gaps_of_project(root, loaded)
    # The accepted tokens serve two purposes below: exact substitution for literals, and the
    # identifiers already taken so a fresh suggestion never collides with one already in the
    # dictionary.
    accepted_tokens = {
        entry.key: entry.value for entry in entries_module.read_entries(path)
        if entry.kind == "token" and entry.value
    }
    literal_edits = fill_literals(gaps, accepted_tokens)
    service_gaps = [gap for gap in gaps if gap.kind in plan_kinds]

    dictionary_dir = path if path.is_dir() else path.parent
    cache = Cache(dictionary_dir / "machine-cache.json")
    # The dictionary's `terms` section ("Russian term" -> "English") gives both shapes the
    # service call needs: the pairs go to the provider as its glossary as they stand, and the
    # name builder gets a lowercase-lookup so the spelling holds even after the prose around a
    # term is inflected by the machine translation.
    glossary = list(loaded.terms.items())
    terms = {english.casefold(): english for english in loaded.terms.values()}
    result = run_machine(
        service_gaps, provider, cache,
        glossary=glossary, taken=set(accepted_tokens.values()), terms=terms,
    )
    cache.save()

    edits = [{"key": key, "value": value, "kind": "literal"} for key, value in literal_edits.items()]
    edits.extend(
        {"key": key, "value": value, "kind": kind}
        for (kind, key), value in result.values.items()
    )
    if args.suggest_out:
        entries_module.write_entries(path, edits, target=Path(args.suggest_out).name,
                                     comment=getattr(args, "comment", "") or "")

    # The count alone hides WHAT did not translate; a refusal is only actionable with its
    # reason next to it, the same way --set already reports a refused edit.
    refusals = [
        {"kind": kind, "key": key, "reason": reason}
        for (kind, key), reason in result.refused.items()
    ]
    machine_report = {
        "cached": result.cached, "requested": result.requested, "refused": len(result.refused),
    }
    if args.format == "json":
        payload = {
            "dictionary": str(path),
            "machine": {**machine_report, "refusals": refusals},
            "suggestions": edits,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        print(i18n.t("translate.machine-report", **machine_report))
        for item in refusals:
            print(f"  {item['kind']:7} {item['key']}: {item['reason']}")
        for edit in edits:
            print(f"  {edit['kind']:7} {edit['key']}  ->  {edit['value']}")
    return 0


def _machine_refused(args, exc) -> int:
    """No provider is configured (or the choice is ambiguous) - reported before any work."""
    if args.format == "json":
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
    else:
        print(i18n.t("translate.machine-refused", error=exc))
    return 2


def _unknown_plans_refused(args, unknown: list[str], valid: list[str]) -> int:
    """An unrecognized --plans name is refused by name, not silently dropped from the set."""
    return _refused(args, i18n.t(
        "translate.unknown-plans", names=", ".join(unknown), valid=", ".join(valid)))


def _refused(args, message: str) -> int:
    """One refusal of the suggest mode, in whichever format the caller asked for."""
    if args.format == "json":
        print(json.dumps({"error": message}, ensure_ascii=False))
    else:
        print(message)
    return 2


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
