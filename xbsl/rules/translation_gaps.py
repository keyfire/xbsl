"""Tier D: conventions/missing-translation - the translation gaps, shown in the editor.

A project that translates its sources (see xbsl/translation/) keeps a dictionary of its own
names, comment lines and string literals. This rule shows what that dictionary does not cover
yet, right where the untranslated word stands: every project name, every Cyrillic comment line
and every Cyrillic string literal the translator would leave behind becomes one finding at its
first occurrence in the file.

Project-scoped on purpose. Whether a word is the PROJECT's own is a project-wide fact - the
declaration may sit in a yaml the module never mentions - and the translator gates such words
off the platform tables so that a declaration and its uses always move together. A per-file
check would call those words "already covered by the platform" and stay silent exactly where
the translated tree would fall apart.

The dictionary's own files are not judged. They are Russian by construction - the keys are
the words being translated, and the head comment says what a batch of entries is about - so
read as sources they gave 826 "gaps" on a project whose sources are covered to the last word.

Off by default and silent without a dictionary: the rule only means something for a project
that translates its sources, and an `xbsl-translation` directory (or file) next to or above
the project is what says so. It is also the most expensive rule of the set - every file goes
through the whole translation pass, which doubles the run on a live project - so it is asked
for rather than paid for on every save: `--enable conventions/missing-translation` in the CLI,
the `enable` parameter of the MCP lint tool, the Linter: Enable setting in the editor.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import i18n
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule

MESSAGES = {
    "conventions/missing-translation.title": {
        "ru": "Нет перевода в словаре проекта",
        "en": "Not in the project's translation dictionary",
    },
    "conventions/missing-translation.token": {
        "ru": "Имя '{name}' не переведено в словаре проекта ({count} вхождений в файле).",
        "en": "The name '{name}' has no project-dictionary translation ({count} occurrences in the file).",
    },
    "conventions/missing-translation.declared": {
        "ru": "Имя '{name}' объявлено проектом и не переведено в его словаре: платформенное "
              "написание к нему не применяется, иначе объявление и обращения разъедутся "
              "({count} вхождений в файле).",
        "en": "The name '{name}' is declared by the project and has no entry in its dictionary: "
              "the platform spelling is not applied to it, or the declaration and its uses "
              "would drift apart ({count} occurrences in the file).",
    },
    "conventions/missing-translation.phrase": {
        "ru": "Комментарий не переведён в словаре проекта: '{text}'.",
        "en": "The comment line has no project-dictionary translation: '{text}'.",
    },
    "conventions/missing-translation.literal": {
        "ru": "Строковый литерал не назван в плане literals словаря проекта: '{text}'. "
              "Он остаётся кириллицей: планом называют те литералы, которые на деле имена "
              "или сообщения.",
        "en": "The string literal is not named in the project dictionary's literals plane: "
              "'{text}'. It stays Cyrillic: the plane names the literals that are really "
              "names or messages.",
    },
    "conventions/missing-translation.broken": {
        "ru": "Словарь перевода не загрузился: {error}",
        "en": "The translation dictionary did not load: {error}",
    },
    "conventions/missing-translation.off": {
        "ru": "имеет смысл только для проекта, который переводит исходники (см. xbsl translate), "
              "и стоит дорого: на корпусе сайта прогон удваивается (10 с -> 20 с), потому что "
              "каждый файл проходит перевод целиком. Включайте флагом --enable (в MCP – параметр "
              "enable), когда словарь и нужен",
        "en": "only means something for a project that translates its sources (see xbsl translate), "
              "and it is expensive: on a live project the run doubles (10s -> 20s), since every "
              "file goes through the whole translation pass. Turn it on with --enable (the MCP "
              "tool takes an `enable` parameter) when the dictionary is what you are asking about",
    },
}
i18n.register(MESSAGES)


def platform_suggestion(name: str) -> str:
    """The platform spelling worth offering for a name, or an empty string."""
    from xbsl.translation import entries

    return entries._suggestion(name)  # noqa: SLF001 - one implementation, two surfaces


@lru_cache(maxsize=64)
def _dictionary_at(directory: str) -> Path | None:
    from xbsl.translation import dictionary

    return dictionary.discover(Path(directory))


def _entry_data(kind: str, key: str, suggestion: str) -> dict:
    """What a client needs to offer the repair: the exact key, its kind and a first guess.

    The message cannot carry this - it is bilingual and it elides a long comment line - and a
    span fix cannot either: the repair edits the DICTIONARY, another file entirely.
    """
    data = {"translation": {"kind": kind, "key": key}}
    if suggestion:
        data["translation"]["suggestion"] = suggestion
    return data


def _inside(path: Path, dictionary_path: Path) -> bool:
    """Is this file the dictionary itself (or one of its files)?

    The dictionary is written in Russian by construction - keys, and the comments that say
    what a batch of entries is about. Judged as sources, its own files gave 826 "gaps" on a
    project whose sources are covered to the last word.
    """
    if dictionary_path.is_file():
        return path == dictionary_path
    return dictionary_path in path.parents


def _gaps_mapper(source: SourceFile) -> dict | None:
    """Per-file facts: what this file DECLARES, what it leaves untranslated, what the platform answered."""
    resolved = source.path.resolve()
    found = _dictionary_at(str(resolved.parent))
    if found is None or _inside(resolved, found):
        return None
    # Deferred import: the translation package pulls the yaml walk and the platform maps,
    # none of which a run without this rule should pay for.
    from xbsl.translation import code, dictionary, names, reporting, yamlfile

    try:
        loaded = dictionary.load_cached(found)
    except dictionary.DictionaryError as exc:
        return {"error": str(exc)}
    report = reporting.FileReport(path=source.rel)
    resolver = code.Resolver(loaded)
    try:
        if source.kind == "xbsl":
            code.translate_code(source, resolver, report)
        else:
            yamlfile.translate_yaml(source, resolver, report)
    except Exception as exc:  # noqa: BLE001 - a gap report must never break the whole run
        return {"error": str(exc)}
    return {
        "declared": sorted(names.declared(source)),
        # A hint for every name the client may be asked to translate - the ones the dictionary
        # does not cover AND the ones the platform answered (those become gaps as soon as the
        # project turns out to declare the same word).
        "suggest": {
            name: platform_suggestion(name)
            for name in (*report.missing_tokens, *report.platform_tokens)
            if platform_suggestion(name)
        },
        "missing": {name: places[:1] + [len(places)] for name, places in report.missing_tokens.items()},
        "platform": {
            name: places[:1] + [len(places)]
            for name, places in report.platform_tokens.items()
            if not loaded.token(name)
        },
        "phrases": {text: places[:1] + [len(places)] for text, places in report.missing_phrases.items()},
        "literals": {text: places[:1] + [len(places)] for text, places in report.missing_literals.items()},
    }


@rule(
    "conventions/missing-translation", "conventions/missing-translation.title", "D",
    scope="project", severity=Severity.INFO, enabled_by_default=False,
    off_reason="conventions/missing-translation.off", mapper=_gaps_mapper,
)
def missing_translation(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    declared = {name for fact in facts.values() for name in (fact.get("declared") or ())}
    for rel, fact in sorted(facts.items()):
        error = fact.get("error")
        if error:
            yield Diagnostic(
                rel, 1, 1, "conventions/missing-translation", Severity.INFO,
                i18n.t("conventions/missing-translation.broken", error=error),
            )
            continue
        suggestions = fact.get("suggest") or {}
        for name, entry in sorted((fact.get("missing") or {}).items()):
            (line, col), count = entry[0], entry[1]
            key = "declared" if name in declared else "token"
            yield Diagnostic(
                rel, max(line, 1), max(col, 1), "conventions/missing-translation", Severity.INFO,
                i18n.t(f"conventions/missing-translation.{key}", name=name, count=count),
                data=_entry_data("token", name, suggestions.get(name, "")),
            )
        # A word the platform tables answer is a gap too when the PROJECT declares it: the
        # translator refuses the platform spelling there, so the file would keep the Russian.
        for name, entry in sorted((fact.get("platform") or {}).items()):
            if name not in declared:
                continue
            (line, col), count = entry[0], entry[1]
            yield Diagnostic(
                rel, max(line, 1), max(col, 1), "conventions/missing-translation", Severity.INFO,
                i18n.t("conventions/missing-translation.declared", name=name, count=count),
                data=_entry_data("token", name, suggestions.get(name, "")),
            )
        for text, entry in sorted((fact.get("phrases") or {}).items()):
            (line, col), count = entry[0], entry[1]
            del count
            preview = text if len(text) <= 60 else text[:57] + "..."
            yield Diagnostic(
                rel, max(line, 1), max(col, 1), "conventions/missing-translation", Severity.INFO,
                i18n.t("conventions/missing-translation.phrase", text=preview),
                data=_entry_data("phrase", text, ""),
            )
        # A literal carries no suggestion: the platform tables spell NAMES, and between the
        # quotes stands as often a sentence, where a table answer would be a guess.
        for text, entry in sorted((fact.get("literals") or {}).items()):
            (line, col), count = entry[0], entry[1]
            del count
            preview = text if len(text) <= 60 else text[:57] + "..."
            yield Diagnostic(
                rel, max(line, 1), max(col, 1), "conventions/missing-translation", Severity.INFO,
                i18n.t("conventions/missing-translation.literal", text=preview),
                data=_entry_data("literal", text, ""),
            )
