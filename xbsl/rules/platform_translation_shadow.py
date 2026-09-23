"""Warn when a project declaration suppresses a known platform translation.

The translator gathers Cyrillic names declared by YAML and XBSL into one project-wide set.
Without an explicit dictionary entry, that set prevents the platform map from translating the
same word at unrelated uses. The check only runs for projects with a translation dictionary;
an ordinary monolingual project has no missing translation to repair.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from xbsl import i18n, metamodel
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.translation import dictionary, names, platform_map
from xbsl.rules.yaml_schema import _composed, _mapping_nodes, _parsed, object_kind


RULE_ID = "conventions/platform-translation-shadow"

MESSAGES = {
    f"{RULE_ID}.title": {
        "ru": "Объявление перекрывает платформенный перевод",
        "en": "Declaration suppresses a platform translation",
    },
    f"{RULE_ID}.missing": {
        "ru": "Имя '{name}' объявлено проектом и может отключать платформенный перевод "
              "'{platform}' там, где имя разрешается без уточнения. Добавьте явную пару в "
              "словарь перевода проекта; при необходимости уточните ее владельцем.",
        "en": "Project declaration '{name}' can suppress the platform translation "
              "'{platform}' where the name is resolved without qualification. Add an explicit "
              "pair to the project translation dictionary; qualify it by owner if needed.",
    },
}
i18n.register(MESSAGES)


def _yaml_positions(source: SourceFile) -> list[tuple[str, int, int, str]]:
    """Position the exact Name scalars admitted by the translation collector."""
    data, error = _parsed(source)
    if error is not None or not isinstance(data, dict):
        return []
    kind = object_kind(data) or ("Проект" if source.path.stem in ("Проект", "Project") else None)
    owner = data.get("Имя", data.get("Name", "")) if kind and metamodel.class_for_kind(kind) else ""
    owner = owner if isinstance(owner, str) else ""
    declared = names.declared_in_yaml(source)
    if not declared:
        return []
    locations = linemap(source)
    written = {
        (line, name): col
        for match in names._NAME_LINE_RE.finditer(source.text)
        if (name := match.group(2).strip()) in declared
        for line, col in (locations.linecol(match.start(2)),)
    }
    root = _composed(source)
    if root is None:
        return []
    found = []
    for mapping in _mapping_nodes(root):
        for key, value in mapping.value:
            if getattr(key, "value", None) not in ("Имя", "Name"):
                continue
            name = getattr(value, "value", None)
            if not isinstance(name, str) or name not in declared:
                continue
            line = value.start_mark.line + 1
            col = written.get((line, name))
            if col is not None:
                found.append((name, line, col, owner))
    return found


def _module_positions(source: SourceFile) -> list[tuple[str, int, int, str]]:
    """Position methods, types, structure fields and enum values collected by the translator."""
    declared = names.declared_in_module(source)
    if not declared:
        return []
    found: list[tuple[str, int, int, str]] = []
    stream = tokens(source)
    inside = ""
    structure = ""

    def add(index: int, scope: str = "", skip_modifiers: bool = False) -> None:
        position = index + 1
        while (skip_modifiers and position < len(stream)
               and stream[position].kind == "KEYWORD"
               and stream[position].canonical in ("VAR", "VAL", "REQ")):
            position += 1
        if position >= len(stream):
            return
        name = stream[position]
        if name.kind == "IDENT" and name.value in declared:
            found.append((name.value, name.line, name.col, scope))

    for index, token in enumerate(stream):
        if token.kind == "KEYWORD" and token.canonical in ("METHOD", "CONSTRUCTOR"):
            inside = ""
            structure = ""
            add(index)
        elif token.kind == "KEYWORD" and token.canonical in ("STRUCTURE", "ENUMERATION"):
            inside = token.canonical
            structure = names._next_name(stream, index) if inside == "STRUCTURE" else ""
            add(index)
        elif token.kind == "OP" and token.value == ";":
            inside = ""
            structure = ""
        elif (inside and token.kind == "KEYWORD"
              and token.canonical in ("VAR", "VAL", "REQ")):
            add(index, structure if inside == "STRUCTURE" else "", skip_modifiers=True)
        elif inside == "ENUMERATION" and token.kind == "IDENT" and token.value in declared:
            previous = stream[index - 1] if index else None
            following = stream[index + 1] if index + 1 < len(stream) else None
            if (previous is None or previous.line != token.line) and (
                following is None or following.line != token.line
            ):
                found.append((token.value, token.line, token.col, ""))
    return list(dict.fromkeys(found))


def _shadow_mapper(source: SourceFile) -> dict | None:
    if source.kind == "yaml":
        found = _yaml_positions(source)
    elif source.kind == "xbsl" and source.path.suffix.lower() == ".xbsl":
        found = _module_positions(source)
    else:
        return None
    if not found:
        return None
    return {"path": str(source.path), "names": found}


@rule(
    RULE_ID, f"{RULE_ID}.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_shadow_mapper,
)
def platform_translation_shadow(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    if not facts:
        return
    by_dictionary: dict[Path, list[tuple[str, dict]]] = {}
    directories: dict[Path, Path | None] = {}
    for rel, fact in facts.items():
        directory = Path(fact["path"]).parent
        if directory not in directories:
            directories[directory] = dictionary.discover(directory)
        path = directories[directory]
        if path is not None:
            by_dictionary.setdefault(path, []).append((rel, fact))
    for path, group in by_dictionary.items():
        try:
            own = dictionary.load_for_pass(path)
        except dictionary.DictionaryError:
            continue  # The translation rule reports a broken dictionary separately.
        for rel, fact in group:
            for name, line, col, scope in fact["names"]:
                if own.token(name, scope) is not None:
                    continue
                candidates = {
                    value for value in (
                        platform_map.ident_english(name), platform_map.member_english(name),
                    ) if value
                }
                if not candidates:
                    continue
                yield Diagnostic(
                    rel, line, col, RULE_ID, Severity.WARNING,
                    i18n.t(
                        f"{RULE_ID}.missing", name=name,
                        platform=" / ".join(sorted(candidates)),
                    ),
                )
