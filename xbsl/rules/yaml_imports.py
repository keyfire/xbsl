"""Tier D: cross-subsystem references - three rules over one placement model.

The third one, code/unused-import, is the mirror of the first: a module declares
`импорт <Подсистема>` while nothing in its CODE resolves through it. The platform's own
editor reports such imports, the linter did not, and they accumulate - a subsystem is
imported "just in case", the code that needed it is rewritten, the line stays.

What counts as a use is deliberately narrow: a name of an element of that subsystem
appearing as an identifier anywhere in the module - a type position, a call, a namespace
qualifier. The rule errs towards silence by design, and both ways it can be wrong are
harmless: a local name that happens to match an element of the imported subsystem reads as
a use (the import is kept, no false report), and a qualified reference `Подсистема::Элемент`
mentions the element too, though such a reference needs no import at all.

The PAIRED yaml is NOT a use: its own `Импорт:` section covers its type positions, and the
module import does not extend to it - the live case that prompted the rule is exactly this
shape (a module importing a subsystem only its yaml refers to, with the yaml importing it
on its own).

yaml/missing-import wants a public foreign element to be imported; yaml/foreign-not-public
wants the foreign element to be public at all (see its own docstring). Together they cover
what the platform requires for a reference across a subsystem boundary; both are built on
the same placement model of the project, described below.


The yaml/missing-import rule: a yaml element (a form, an object...) that references an
element of ANOTHER subsystem must list that subsystem in its own `Импорт:` section. A
reference is either a type position (the string values of `Тип` keys, generic arguments
included) or a navigation target (`ТипФормы`) - see _REFERENCE_KEYS. The namespace import in the paired `.xbsl` module does not cover the yaml – such
a project deploys, but the component initialization fails at runtime.

An element's subsystem is determined by the source layout: a directory with a
`Подсистема.yaml` is a subsystem root (the subsystem name is the directory name, or the
file's `Имя` when present), and every element under it belongs to that subsystem
(packages included – within one subsystem all packages see each other, so only the
subsystem boundary matters).

Narrowings for zero false positives:

- only foreign objects with `ОбластьВидимости: ВПроекте`/`Глобально` are reported: a
  non-public foreign object is inaccessible regardless of imports – that is a visibility
  error, not a missing import, and the platform semantics of it are not this rule's;
- a name that also belongs to an element of the file's own subsystem resolves locally
  and is skipped;
- a name that is also a stdlib symbol is skipped: without an import the foreign project
  namespace is not in scope and the name resolves to the standard namespace (the guard
  is active when the type catalog is generated);
- a name that is also a module-declared local type (structure, enumeration, exception)
  anywhere in the project is skipped – the yaml may legitimately reference a type of a
  module of its own subsystem (without the language data this guard degrades to a skip
  of nothing);
- qualified names (`Подсистема::Тип`) rely on the subsystem's `Использование`, not on
  the element's import – they do not parse as short chains and are skipped;
- a file outside any subsystem (no `Подсистема.yaml` up the path) is skipped, as is the
  whole check when the project has no subsystem files at all.

One diagnostic is reported per missing subsystem per file (the fix is a single import
line), anchored at the first offending type value. When several foreign public
subsystems declare the same name and none of them is imported, the candidates are listed
together ('Б/В') – importing any of them resolves the name.

The rule is project-wide: it needs the layout of the whole project (like
yaml/unknown-type, it does not run in single-file mode).
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import tokens
from xbsl.rules import semantics
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, value_of
from xbsl.rules.yaml_types import _parse_type_string, _type_values, _value_positions

MESSAGES = {
    "code/unused-import.title": {
        "ru": "Неиспользуемый импорт подсистемы",
        "en": "Unused subsystem import",
    },
    "code/unused-import.unused": {
        "ru": "Импорт подсистемы '{sub}' не используется: ни один её элемент в коде модуля "
              "не упомянут. Ссылки ПАРНОГО yaml импорт модуля не покрывает – у yaml своя "
              "секция Импорт. Строку можно снять.",
        "en": "The import of subsystem '{sub}' is unused: no element of it is mentioned in "
              "the module code. References of the PAIRED yaml are not covered by a module "
              "import - the yaml has an {n[Импорт]} section of its own. The line can go.",
    },
    "yaml/missing-import.title": {
        "ru": "Нет импорта подсистемы в yaml",
        "en": "Missing subsystem import in yaml",
    },
    "yaml/missing-import.missing": {
        "ru": "Тип '{name}' – из подсистемы '{sub}', а в секции Импорт её нет: "
              "инициализация компонента упадёт в рантайме "
              "(импорт в парном .xbsl yaml не покрывает).",
        "en": "Type '{name}' comes from subsystem '{sub}' which the {n[Импорт]} section does "
              "not list: the component initialization fails at runtime "
              "(an import in the paired .xbsl does not cover the yaml).",
    },
}
i18n.register(MESSAGES)

#: Both spellings: the platform accepts the English service file names too.
_SUBSYSTEM_FILES = ("Подсистема.yaml", "Subsystem.yaml")
@lru_cache(maxsize=1)
def _public_scopes() -> frozenset[str]:
    """Scopes that publish a subsystem member, both spellings."""
    return frozenset(terms.key_forms("ВПроекте", "Глобально"))


dataset.register_reset(_public_scopes.cache_clear)

# Yaml keys that name another element. A navigation target is as much a reference as a type
# position, so both rules below read both keys: `ТипФормы: ЗадачиФормаСписка` reaches into
# another subsystem exactly the way `Тип: Задачи.Ссылка` does.
_REFERENCE_KEYS = ("Тип", "ТипФормы")


def _subsystem_roots(sources: list[SourceFile]) -> dict[Path, str]:
    """Directories that are subsystem roots, mapped to the subsystem name."""
    roots: dict[Path, str] = {}
    for s in sources:
        if s.kind != "yaml" or s.path.name not in _SUBSYSTEM_FILES:
            continue
        data, err = _parsed(s)
        name = value_of(data, "Имя") if err is None and isinstance(data, dict) else None
        roots[s.path.parent] = name if isinstance(name, str) else s.path.parent.name
    return roots


def _subsystem_of(path: Path, roots: dict[Path, str]) -> str | None:
    """The subsystem of a source path – the nearest ancestor subsystem root."""
    for parent in path.parents:
        if parent in roots:
            return roots[parent]
    return None


def _yaml_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a subsystem yaml contributes its root directory, an object yaml its
    placement slice (name, visibility, imports) and its candidate type roots (stdlib
    settles here), a module its local types (the collision guard)."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        try:
            local = semantics._file_local_types(source)
        except DatasetError:
            return None  # no language data – the collision guard has nothing to skip
        if not local:
            return None
        return {"k": "x", "local_types": sorted(local)}
    if source.kind != "yaml":
        return None
    if source.path.name in _SUBSYSTEM_FILES:
        data, err = _parsed(source)
        name = value_of(data, "Имя") if err is None and isinstance(data, dict) else None
        return {
            "k": "sub",
            "dir": str(source.path.parent),
            "name": name if isinstance(name, str) else source.path.parent.name,
        }
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict) or not object_kind(data):
        return None
    stdlib = semantics._stdlib_names()
    raw = data.get("Импорт")
    imports = [e for e in raw if isinstance(e, str)] if isinstance(raw, list) else []
    cands: list[tuple[str, str, int, int]] = []
    for key in _REFERENCE_KEYS:
        for value in dict.fromkeys(_type_values(data, key)):  # unique, in document order
            chains = _parse_type_string(value)
            if not chains:
                continue
            position: tuple[int, int] | None = None
            for chain in chains:
                root = chain[0]
                if root in stdlib:
                    continue
                if position is None:
                    position = (_value_positions(source, value, key) or [(1, 1)])[0]
                cands.append((root, ".".join(chain), position[0], position[1]))
    nm = value_of(data, "Имя")
    return {
        "k": "el",
        "path": str(source.path),
        "name": nm if isinstance(nm, str) else None,
        "vis": data.get("ОбластьВидимости"),
        "imports": imports,
        "cands": cands,
    }


@rule(
    "yaml/missing-import", "yaml/missing-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_yaml_import_mapper,
)
def missing_yaml_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    # Subsystem roots and the placement model from the facts.
    roots: dict[Path, str] = {}
    for fact in facts.values():
        if fact["k"] == "sub":
            roots[Path(fact["dir"])] = fact["name"]
    if not roots:
        return
    local_types: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "x":
            local_types.update(fact["local_types"])
    placement: dict[str, dict[str, object]] = {}
    elements: list[tuple[str, dict, str]] = []
    for rel, fact in facts.items():
        if fact["k"] != "el":
            continue
        sub = _subsystem_of(Path(fact["path"]), roots)
        if sub is None:
            continue
        elements.append((rel, fact, sub))
        if fact["name"]:
            placement.setdefault(fact["name"], {})[sub] = fact["vis"]
    for rel, fact, my_sub in elements:
        imports = set(fact["imports"])
        reported: set[tuple[str, ...]] = set()
        for root, chain_name, line, col in fact["cands"]:
            if root in local_types:
                continue
            subs = placement.get(root)
            if not subs or my_sub in subs:
                continue
            candidates = tuple(sorted(
                sub for sub, vis in subs.items() if vis in _public_scopes()
            ))
            if not candidates or imports.intersection(candidates):
                continue
            if candidates in reported:
                continue
            reported.add(candidates)
            yield Diagnostic(
                rel, line, col, "yaml/missing-import", Severity.WARNING,
                i18n.t("yaml/missing-import.missing", name=chain_name, sub="/".join(candidates)),
            )


# --- The other half: the foreign element is not public at all ---------------------------

MESSAGES_VISIBILITY = {
    "yaml/foreign-not-public.title": {
        "ru": "Ссылка на непубличный элемент чужой подсистемы",
        "en": "Reference to a non-public element of another subsystem",
    },
    "yaml/foreign-not-public.found": {
        "ru": "Элемент '{name}' лежит в подсистеме '{sub}' и не публичен "
              "(ОбластьВидимости: {vis}) – из другой подсистемы он недоступен. "
              "Задайте у него ОбластьВидимости: ВПроекте.",
        "en": "Element '{name}' lives in subsystem '{sub}' and is not public "
              "({n[ОбластьВидимости]}: {vis}) - it is unreachable from another subsystem. "
              "Set {n[ОбластьВидимости]}: {n[ВПроекте]} on it.",
    },
}
i18n.register(MESSAGES_VISIBILITY)

_DEFAULT_SCOPE = "ВПодсистеме"  # the platform default when the property is absent


def _visibility_mapper(source: SourceFile) -> dict | None:
    """The map phase: the same placement slice as above, but the candidates also come from
    the navigation key `ТипФормы` - a form opened from another subsystem must be public."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        try:
            local = semantics._file_local_types(source)
        except DatasetError:
            return None
        if not local:
            return None
        return {"k": "x", "local_types": sorted(local)}
    if source.kind != "yaml":
        return None
    if source.path.name in _SUBSYSTEM_FILES:
        data, err = _parsed(source)
        name = value_of(data, "Имя") if err is None and isinstance(data, dict) else None
        return {
            "k": "sub",
            "dir": str(source.path.parent),
            "name": name if isinstance(name, str) else source.path.parent.name,
        }
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict) or not object_kind(data):
        return None
    stdlib = semantics._stdlib_names()
    cands: list[tuple[str, str, int, int]] = []
    for key in _REFERENCE_KEYS:
        for value in dict.fromkeys(_type_values(data, key)):  # unique, in document order
            chains = _parse_type_string(value)
            if not chains:
                continue
            position: tuple[int, int] | None = None
            for chain in chains:
                root = chain[0]
                if root in stdlib:
                    continue
                if position is None:
                    position = (_value_positions(source, value, key) or [(1, 1)])[0]
                cands.append((root, ".".join(chain), position[0], position[1]))
    nm = value_of(data, "Имя")
    return {
        "k": "el",
        "path": str(source.path),
        "name": nm if isinstance(nm, str) else None,
        "vis": data.get("ОбластьВидимости"),
        "cands": cands,
    }


@rule(
    "yaml/foreign-not-public", "yaml/foreign-not-public.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_visibility_mapper,
)
def foreign_not_public(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A yaml reference to an element of ANOTHER subsystem that is not public.

    The documentation is explicit ("Модульная разработка"): an element is visible only
    inside its own subsystem (ВПодсистеме, the default) and unreachable from the others
    unless its ОбластьВидимости is ВПроекте or Глобально. No import can help - which is
    exactly the case yaml/missing-import leaves alone, so the two rules never overlap:
    that one fires when a public foreign element is not imported, this one when the
    foreign element is not public in the first place.

    The severity is `error` because the compiler rejects such a project outright - checked
    on a two-subsystem probe built and applied on a server: with the navigation target left
    at ВПодсистеме the build fails with `Тип "ЦелеваяФорма" не виден из-за модификатора
    видимости @ВПодсистеме` at the exact position this rule reports, and the same probe with
    ВПроекте compiles that reference clean.

    The narrowings of the sibling rule apply here too (they are what keeps this at zero
    false positives): names of the file's own subsystem resolve locally, stdlib names and
    module-declared local types are skipped, qualified `Подсистема::Тип` names rely on the
    subsystem's `Использование`, and a name no project element declares (a platform form
    like ФормаЖурналаСобытий) is unknown, not wrong. One diagnostic per target per file.
    """
    roots: dict[Path, str] = {}
    for fact in facts.values():
        if fact["k"] == "sub":
            roots[Path(fact["dir"])] = fact["name"]
    if not roots:
        return
    local_types: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "x":
            local_types.update(fact["local_types"])
    placement: dict[str, dict[str, object]] = {}
    elements: list[tuple[str, dict, str]] = []
    for rel, fact in facts.items():
        if fact["k"] != "el":
            continue
        sub = _subsystem_of(Path(fact["path"]), roots)
        if sub is None:
            continue
        elements.append((rel, fact, sub))
        if fact["name"]:
            placement.setdefault(fact["name"], {})[sub] = fact["vis"]
    for rel, fact, my_sub in elements:
        reported: set[str] = set()
        for root, chain_name, line, col in fact["cands"]:
            if root in local_types or root in reported:
                continue
            subs = placement.get(root)
            if not subs or my_sub in subs:
                continue
            if any(vis in _public_scopes() for vis in subs.values()):
                continue  # a public one exists - missing import at most, the sibling's case
            owner = sorted(subs)[0]
            vis = subs[owner] or _DEFAULT_SCOPE
            reported.add(root)
            yield Diagnostic(
                rel, line, col, "yaml/foreign-not-public", Severity.ERROR,
                i18n.t("yaml/foreign-not-public.found", name=chain_name, sub=owner, vis=vis),
            )


# --- code/unused-import -------------------------------------------------------------------


def _unused_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a subsystem yaml contributes its root, an element yaml its name and
    place, a module its import lines (with positions) and the identifiers of its code."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        if source.path.name in _SUBSYSTEM_FILES:
            data, err = _parsed(source)
            name = value_of(data, "Имя") if err is None and isinstance(data, dict) else None
            return {
                "k": "sub",
                "dir": str(source.path.parent),
                "name": name if isinstance(name, str) else source.path.parent.name,
            }
        data, err = _parsed(source)
        if err is not None or not isinstance(data, dict) or not object_kind(data):
            return None
        name = value_of(data, "Имя")
        return {"k": "el", "path": str(source.path),
                "name": name if isinstance(name, str) else source.path.stem}
    if source.kind != "xbsl":
        return None
    toks = tokens(source)
    imports: list[tuple[str, int, int]] = []
    idents: set[str] = set()
    for i, tok in enumerate(toks):
        if tok.kind == "IDENT":
            idents.add(tok.value)
        if tok.kind == "KEYWORD" and tok.canonical == "IMPORT" and i + 1 < len(toks):
            following = toks[i + 1]
            if following.kind == "IDENT":
                imports.append((following.value, tok.line, tok.col))
    if not imports:
        return None
    return {"k": "mod", "path": str(source.path), "imports": imports, "idents": sorted(idents)}


@rule(
    "code/unused-import", "code/unused-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_unused_import_mapper,
)
def unused_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A module imports a subsystem whose elements its code never mentions."""
    roots = {
        Path(f["dir"]): f["name"] for f in facts.values() if f["k"] == "sub"
    }
    if not roots:
        return  # no subsystem files - the project layout is unknown, nothing to judge
    # subsystem -> the names of its elements
    owned: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] != "el":
            continue
        sub = _subsystem_of(Path(fact["path"]), roots)
        if sub:
            owned.setdefault(sub, set()).add(fact["name"])
    for rel, fact in facts.items():
        if fact["k"] != "mod":
            continue
        idents = set(fact["idents"])
        for sub, line, col in fact["imports"]:
            elements = owned.get(sub)
            if elements is None:
                continue  # an unknown subsystem (a library, a typo) - not this rule's case
            if elements & idents:
                continue
            yield Diagnostic(
                rel, line, col, "code/unused-import", Severity.WARNING,
                i18n.t("code/unused-import.unused", sub=sub),
            )
