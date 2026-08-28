"""Translate a whole project tree: files, names of files, localization, coverage.

`translate_project` walks the project, translates every `.yaml`/`.xbsl`/`.xbql`, copies the
resources, renames every path component through the same token map the contents use (a
reference and the file it points to cannot drift apart when both go through one map), and
turns the localized-strings layout around: the project's dictionaries already carry the
target language, so the translated project gets those values as its BASE (with the keys
translated), the original base values move into `Localization/<Code>/`, and the project
descriptor's default and development languages follow. The identifiers (`Id`) never change:
the translated tree stays the same project.

Without an output directory nothing is written - the walk still produces the full report
(coverage by metadata object, the untranslated remainder, the data gaps), which is what the
`--coverage`/`--missing` modes and the CI gate read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from xbsl import engine, scaffold, terms
from xbsl.rules.yaml_schema import _parsed, object_kind
from xbsl.translation import names as project_names_module
from xbsl.translation.code import Resolver, has_cyrillic, translate_code
from xbsl.translation.dictionary import (
    DICTIONARY_DIR, DICTIONARY_FILE, Dictionary,
)
from xbsl.translation.jsonfile import translate_json
from xbsl.translation.reporting import FileReport
from xbsl.translation.yamlfile import translate_yaml

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

#: The directory a localized-strings element keeps its per-language sections in.
_LOCALIZATION_DIR_RU = "Локализация"
_LOCALIZATION_DIR_EN = "Localization"

#: Path components with a fixed spelling of their own.
_FIXED_COMPONENTS = {
    scaffold.PROJECT_FILE: scaffold.PROJECT_FILE_EN,
    "Проект.xbsl": "Project.xbsl",
    scaffold.SUBSYSTEM_FILE: scaffold.SUBSYSTEM_FILE_EN,
    _LOCALIZATION_DIR_RU: _LOCALIZATION_DIR_EN,
}

#: The language names of the project descriptor, as the dictionary language codes them.
_LANGUAGE_NAMES = {"en": "Английский", "ru": "Русский"}


@dataclass
class ProjectReport:
    """Everything one translation pass learned about the project."""

    root: Path
    files: dict[str, FileReport] = field(default_factory=dict)
    renames: dict[str, str] = field(default_factory=dict)
    #: Fatal-for-the-tree problems: a path collision, a swap without the target language.
    problems: list[str] = field(default_factory=list)
    written: int = 0

    def merged_missing_tokens(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for rel, report in sorted(self.files.items()):
            for name, places in report.missing_tokens.items():
                entry = out.setdefault(name, {"count": 0, "sample": ""})
                entry["count"] += len(places)
                if not entry["sample"] and places:
                    entry["sample"] = f"{rel}:{places[0][0]}"
                if name in report.resource_tokens:
                    entry["resource"] = True
        return out

    def merged_missing_phrases(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for rel, report in sorted(self.files.items()):
            for text, places in report.missing_phrases.items():
                entry = out.setdefault(text, {"count": 0, "sample": ""})
                entry["count"] += len(places)
                if not entry["sample"] and places:
                    entry["sample"] = f"{rel}:{places[0][0]}"
        return out

    def merged_named_literals(self) -> dict[str, int]:
        """{literal text: occurrences} the literals plane named across the project.

        Counted by TEXT so that the summary compares like with like: what the plane covers and
        what it does not are both entries of one dictionary, not appearances in one tree.
        """
        out: dict[str, int] = {}
        for report in self.files.values():
            for text, count in report.named_literals.items():
                out[text] = out.get(text, 0) + count
        return out

    def merged_missing_literals(self) -> dict[str, dict]:
        """Cyrillic string literals the literals plane does not name yet, with their places."""
        out: dict[str, dict] = {}
        for rel, report in sorted(self.files.items()):
            for text, places in report.missing_literals.items():
                entry = out.setdefault(text, {"count": 0, "sample": ""})
                entry["count"] += len(places)
                if not entry["sample"] and places:
                    entry["sample"] = f"{rel}:{places[0][0]}"
        return out

    def merged_platform_gaps(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for rel, report in sorted(self.files.items()):
            for name, places in report.missing_platform.items():
                entry = out.setdefault(name, {"count": 0, "sample": ""})
                entry["count"] += len(places)
                if not entry["sample"] and places:
                    entry["sample"] = f"{rel}:{places[0][0]}"
        return out

    def coverage_by_object(self) -> list[tuple[str, int, int]]:
        """[(metadata object, its own surfaces translated, total)] - the coverage report.

        An object is the yaml/xbsl file family sharing one stem (`Задачи.yaml`,
        `Задачи.xbsl`, `Задачи.Объект.xbsl` count as one).
        """
        grouped: dict[str, tuple[int, int]] = {}
        for rel, report in self.files.items():
            path = PurePosixPath(rel.replace("\\", "/"))
            stem = path.name.split(".", 1)[0]
            key = str(path.parent / stem)
            done = report.user_done + report.phrases_done
            total = done + report.user_missing + report.phrases_missing
            known = grouped.get(key, (0, 0))
            grouped[key] = (known[0] + done, known[1] + total)
        return sorted((key, done, total) for key, (done, total) in grouped.items())

    def totals(self) -> dict:
        done = sum(r.user_done + r.phrases_done for r in self.files.values())
        missing = sum(r.user_missing + r.phrases_missing for r in self.files.values())
        return {
            "files": len(self.files),
            "surfaces": done + missing,
            "translated": done,
            "missing": missing,
            "coverage": (done / (done + missing)) if (done + missing) else 1.0,
            "missing_tokens": len(self.merged_missing_tokens()),
            "missing_phrases": len(self.merged_missing_phrases()),
            "platform_gaps": len(self.merged_platform_gaps()),
            # Literals are counted APART from the coverage: naming a literal is a decision
            # about data, and a project that leaves a message in the source language is not a
            # project with an unfinished dictionary. Both halves count distinct TEXTS - the
            # unit of the tokens and the phrases above - so that the two numbers of one
            # sentence can be added, compared and turned into a percentage.
            "literals_translated": len(self.merged_named_literals()),
            "missing_literals": len(self.merged_missing_literals()),
            #: How many literal SPANS the pass rewrote - the size of the change, not of the
            #: dictionary; kept apart so no summary line mixes it with the counts above.
            "literal_occurrences": sum(r.literals_done for r in self.files.values()),
            "texts_kept": sum(len(r.texts_kept) for r in self.files.values()),
            "warnings": sum(len(r.warnings) for r in self.files.values()),
            "collisions": sum(len(r.collided()) for r in self.files.values()),
            "data_keys": sum(r.data_keys for r in self.files.values()),
            "data_keys_missing": sum(r.data_keys_missing for r in self.files.values()),
        }

    def collect_collisions(self) -> None:
        """Lift every name collision into `problems` - a translated tree with one would not apply."""
        for rel, report in sorted(self.files.items()):
            for namespace, translated, sources in report.collided():
                self.problems.append(
                    f"{rel}: {namespace} - '{translated}' <- {', '.join(sources)}"
                )


def _iter_files(root: Path, dictionary: Dictionary | None = None) -> list[Path]:
    """The files of the project under `root` - the dictionary that translates it excluded.

    A run rooted ABOVE the project (the repository root, say) finds the dictionary catalog
    next to the sources, and its files are yaml of the same shape. Counted as sources, their
    own comments came back as untranslated prose: on the site project such a run reported 871
    phrase gaps and 99.2% coverage while the project itself is at 100%. The figure looks
    trustworthy, which is what makes it expensive.
    """
    known = {path.resolve() for path in (dictionary.sources if dictionary else ())}
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if DICTIONARY_DIR in rel.parts or path.name == DICTIONARY_FILE:
            continue
        if path.resolve() in known:  # a dictionary named by the caller, wherever it lies
            continue
        out.append(path)
    return out


def _language_dir(language: str) -> str:
    return language[:1].upper() + language[1:].lower()


def _translate_component(part: str, resolver: Resolver, report: FileReport) -> str:
    fixed = _FIXED_COMPONENTS.get(part)
    if fixed:
        return fixed
    if not has_cyrillic(part):
        return part
    stem, dot, suffixes = part.partition(".")
    pieces: list[str] = []
    for piece in ([stem] + suffixes.split(".") if dot else [stem]):
        if not has_cyrillic(piece):
            pieces.append(piece)
            continue
        replacement, plane = resolver.identifier(piece, after_dot=bool(pieces))
        if plane == "user":
            report.user_done += 1
        if replacement is None:
            report.note_missing(piece, 0, 0, plane)
            pieces.append(piece)
        else:
            pieces.append(replacement)
    return ".".join(pieces)


def translate_project(
    root: Path,
    dictionary: Dictionary,
    out: Path | None = None,
    *,
    swap_localization: bool = True,
) -> ProjectReport:
    """Translate the tree under `root`; write it under `out` when one is given."""
    files = _iter_files(root, dictionary)
    resolver = Resolver(
        dictionary,
        project_names_module.collect(root, engine.load),
        project_names_module.dictionary_scopes(root, engine.load),
        project_names_module.component_names(root, engine.load),
        _collect_data_values(files),
    )
    fields = project_names_module.collect_structure_fields(root, engine.load)
    report = ProjectReport(root=root)
    swaps = _localization_map(root, files) if swap_localization else {}
    outputs: dict[Path, tuple[str, bytes | str, engine.SourceFile | None]] = {}
    targets: dict[str, str] = {}

    for path in files:
        rel = path.relative_to(root)
        rel_str = str(rel)
        file_report = FileReport(path=rel_str)
        translated: str | bytes
        source: engine.SourceFile | None = None
        if path.suffix in (".yaml", ".xbsl", ".xbql"):
            source = engine.load(path)
            if path.suffix == ".yaml":
                translated = translate_yaml(source, resolver, file_report)
            else:
                translated = translate_code(source, resolver, file_report)
        elif path.suffix == ".json":
            translated = _translate_json_bytes(path.read_bytes(), dictionary, fields, file_report)
        else:
            translated = path.read_bytes()
        new_rel_parts = [_translate_component(part, resolver, file_report) for part in rel.parts]
        report.files[rel_str] = file_report
        new_rel = Path(*new_rel_parts)
        if str(new_rel) != rel_str:
            report.renames[rel_str] = str(new_rel)
        known = targets.get(str(new_rel))
        if known is not None:
            report.problems.append(f"{rel_str} -> {new_rel} <- {known}")
            continue
        targets[str(new_rel)] = rel_str
        outputs[new_rel] = (rel_str, translated, source)

    _apply_language_flip(root, outputs, swaps, dictionary, report)
    report.collect_collisions()

    if out is not None:
        _write_tree(out, outputs, report)
    return report


# --- localized strings: the base and the translation swap places ---------------------------


@dataclass
class _Swap:
    role: str  # 'base' | 'section'
    partner: Path | None  # the other file of the pair, when it exists


def _collect_data_values(files: list[Path]) -> frozenset[str]:
    """Cyrillic string VALUES of the project's json resources.

    The key side of a json resource follows the structure fields (`translate_json`); the
    values are data and stay as written. A code literal spelled exactly like one of these
    values is where the two meet - `_literal_edit` warns when a dictionary entry moves it.
    """
    values: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, str):
            if has_cyrillic(node):
                values.add(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for item in node.values():
                walk(item)

    for path in files:
        if path.suffix != ".json":
            continue
        try:
            walk(json.loads(path.read_text(encoding="utf-8-sig")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return frozenset(values)


def _translate_json_bytes(
    raw: bytes, dictionary: Dictionary, fields: frozenset[str], report: FileReport
) -> bytes:
    """Translate the keys of a json resource, keeping its encoding and byte order mark."""
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        text = raw.decode("utf-8-sig" if bom else "utf-8")
    except UnicodeDecodeError:
        # Not a text resource this pass understands - copied as it is, like any binary.
        return raw
    translated = translate_json(text, dictionary, fields, report)
    if translated == text:
        return raw
    return (b"\xef\xbb\xbf" if bom else b"") + translated.encode("utf-8")


def _localization_map(root: Path, files: list[Path]) -> dict[Path, _Swap]:
    """{file: its role in the localization swap} for every localized-strings element."""
    out: dict[Path, _Swap] = {}
    for path in files:
        if path.suffix != ".yaml":
            continue
        if _LOCALIZATION_DIR_RU in path.parts or _LOCALIZATION_DIR_EN in path.parts:
            continue
        try:
            source = engine.load(path)
        except OSError:
            continue
        data, err = _parsed(source)
        if err is not None or object_kind(data) != "ЛокализованныеСтроки":
            continue
        partner = None
        for dir_name in (_LOCALIZATION_DIR_RU, _LOCALIZATION_DIR_EN):
            for code in ("En", "en"):
                candidate = path.parent / dir_name / code / path.name
                if candidate.is_file():
                    partner = candidate
                    break
            if partner:
                break
        out[path] = _Swap("base", partner)
        if partner:
            out[partner] = _Swap("section", path)
    return out


def _apply_language_flip(root, outputs, swaps, dictionary, report) -> None:
    """Finish the swap: headers, the displaced base, the project languages."""
    if not swaps:
        return
    # 1. Rebuild the swapped pairs: the base file's SECTIONS move under Localization/Ru,
    #    the base file keeps its header and receives the target-language sections.
    by_base: dict[str, dict] = {}
    for new_rel, (rel_str, translated, source) in list(outputs.items()):
        if source is None or source.path not in swaps:
            continue
        swap = swaps[source.path]
        entry = by_base.setdefault(str(swap.partner if swap.role == "section" else source.path), {})
        entry[swap.role] = (new_rel, rel_str, translated, source)
    for pair in by_base.values():
        base = pair.get("base")
        section = pair.get("section")
        if base is None:
            continue
        base_rel, base_rel_str, base_text, base_source = base
        header, base_body = _split_localization(base_text)
        if section is None:
            report.problems.append(f"{base_rel_str}: no {dictionary.language} section to swap in")
            continue
        section_rel, section_rel_str, section_text, section_source = section
        del section_rel_str, section_source
        section_body = section_text.lstrip("﻿")
        merged, missing = _merge_localization_bodies(section_body, base_body)
        names = _source_key_names(base_source, base_body)
        for section_name, key in missing:
            source_name = names.get((section_name, key), "")
            shown = f"'{source_name}' ({key})" if source_name and source_name != key else f"'{key}'"
            report.problems.append(
                f"{base_rel_str}: {shown} has no {dictionary.language} value; kept as is")
        outputs[base_rel] = (base_rel_str, header + merged, base_source)
        displaced = Path(*base_rel.parts[:-1], _LOCALIZATION_DIR_EN, _language_dir("ru"), base_rel.name)
        outputs[displaced] = (base_rel_str, base_body, base_source)
        report.renames[base_rel_str + " (sections)"] = str(displaced)
        del outputs[section_rel]
    # 2. The project descriptor: the default and development languages follow the swap.
    for new_rel, (rel_str, translated, source) in list(outputs.items()):
        if new_rel.name != scaffold.PROJECT_FILE_EN or not isinstance(translated, str):
            continue
        target_name = _LANGUAGE_NAMES.get(dictionary.language, "Английский")
        target = terms.english(target_name, "enums") or target_name
        for key in ("DefaultLanguage", "ЯзыкПоУмолчанию", "DevelopmentLanguage", "ЯзыкРазработки"):
            translated = re.sub(
                rf"(?m)^({re.escape(key)}:)[ \t]*[^\r\n#]+",
                rf"\g<1> {target}",
                translated,
            )
        outputs[new_rel] = (rel_str, translated, source)


_SECTION_LINE_RE = re.compile(r"(?m)^(Строки|Шаблоны|Strings|Templates):")


def _split_localization(text: str) -> tuple[str, str]:
    """(the header of a localized-strings element, its sections) - split at the first section."""
    m = _SECTION_LINE_RE.search(text)
    if not m:
        return text, ""
    return text[:m.start()], text[m.start():]


def _localization_sections(body: str) -> dict[str, dict]:
    """The sections of a localized-strings body - both spellings of a section name
    collapse to the canonical English one."""
    if yaml is None:  # pragma: no cover - pyyaml is an install-time dependency
        return {}
    try:
        data = yaml.safe_load(body) or {}
    except Exception:  # noqa: BLE001 - an unparsable body contributes nothing
        return {}
    out: dict[str, dict] = {}
    for name, keys in (data.items() if isinstance(data, dict) else ()):
        if isinstance(keys, dict):
            out[_canonical_section(str(name))] = keys
    return out


def _source_key_names(base_source, translated_body: str) -> dict[tuple[str, str], str]:
    """(canonical section, translated key) -> the key as the SOURCE file spells it.

    A problem must point at a line its reader can find, and after the pass the keys are
    already translated - looking one up in the source takes the reverse dictionary. The
    two bodies are the same file before and after one deterministic pass, so pairing the
    keys of a section by position is exact; a section whose counts diverge contributes
    nothing rather than a guess.
    """
    if base_source is None:
        return {}
    _header, original_body = _split_localization(base_source.text.lstrip("﻿"))
    original = _localization_sections(original_body)
    translated = _localization_sections(translated_body)
    out: dict[tuple[str, str], str] = {}
    for section, translated_keys in translated.items():
        original_keys = original.get(section)
        if not original_keys or len(original_keys) != len(translated_keys):
            continue
        for source_key, key in zip(original_keys, translated_keys):
            out[(section, str(key))] = str(source_key)
    return out


def _merge_localization_bodies(
    target_body: str, fallback_body: str,
) -> tuple[str, list[tuple[str, str]]]:
    """The target-language sections, completed with keys only the fallback carries.

    A key that never got a target value cannot simply disappear - the references to it
    would stop compiling - so its fallback (original-language) line joins the matching
    section, and the caller reports it as a (canonical section, key) pair.
    """
    if yaml is None:  # pragma: no cover - pyyaml is an install-time dependency
        return target_body, []

    target = _localization_sections(target_body)
    fallback = _localization_sections(fallback_body)
    missing: list[tuple[str, str]] = []
    additions: dict[str, list[str]] = {}
    for section, fallback_keys in fallback.items():
        target_keys = target.get(section) or {}
        for key, value in fallback_keys.items():
            if key in target_keys:
                continue
            missing.append((section, str(key)))
            additions.setdefault(section, []).append(
                f"    {key}: {json.dumps(value, ensure_ascii=False)}")
    if not additions:
        return target_body, missing
    lines = target_body.splitlines(keepends=True)
    out: list[str] = []
    current: str | None = None
    newline = "\r\n" if "\r\n" in target_body else "\n"

    def flush(section: str | None) -> None:
        if section:
            for addition in additions.pop(section, ()):
                out.append(addition + newline)

    for line in lines:
        m = _SECTION_LINE_RE.match(line)
        if m:
            flush(current)
            current = _canonical_section(m.group(1))
        out.append(line)
    flush(current)
    for section, rest in additions.items():
        out.append(f"{section}:{newline}")
        out.extend(addition + newline for addition in rest)
    return "".join(out), missing


def _canonical_section(name: str) -> str:
    return {"Строки": "Strings", "Шаблоны": "Templates"}.get(name, name)


# --- writing ----------------------------------------------------------------------------------


def _write_tree(out: Path, outputs, report: ProjectReport) -> None:
    if out.exists() and any(out.iterdir()):
        marker = any((out / name).exists() for name in (scaffold.PROJECT_FILE_EN, scaffold.PROJECT_FILE))
        if not marker:
            report.problems.append(f"{out}: not empty and not a translated project; nothing written")
            return
    for new_rel, (rel_str, translated, source) in sorted(outputs.items(), key=lambda kv: str(kv[0])):
        del rel_str
        target = out / new_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(translated, bytes):
            target.write_bytes(translated)
        else:
            bom = bool(source and source.had_bom)
            target.write_bytes(translated.encode("utf-8-sig" if bom else "utf-8"))
        report.written += 1
