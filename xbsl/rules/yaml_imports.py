"""Tier D: cross-subsystem references - five rules over one placement model.

The platform asks for three things before an element of subsystem Б may be used in subsystem А
(docs, "Модульная разработка"): the element is public, the consumer imports the namespace, and
the consumer's subsystem declares Б in its `Использование`. One rule per condition per side:
yaml/foreign-not-public for the first, yaml/missing-import and code/missing-import for the
second (the yaml and the code of one element import separately), yaml/missing-subsystem-usage
for the third. code/unused-import is the odd one out - it looks the other way, at an import
nothing needs.

code/unused-import is the mirror of code/missing-import: a module declares
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

import re
from collections.abc import Iterable
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, parser as P, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.lexer import linemap, tokens
from xbsl.parser import parse
from xbsl.rules import semantics
from xbsl.rules.environment import _pair_stem
from xbsl.rules.undefined_names import _IMPLICIT
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
    "code/missing-import.title": {
        "ru": "Нет импорта подсистемы в модуле",
        "en": "Missing subsystem import in a module",
    },
    "code/missing-import.missing": {
        "ru": "Тип '{name}' – из подсистемы '{sub}', а модуль её не импортирует: "
              "компиляция упадёт на этой строке. Нужна строка импорта этой подсистемы "
              "(секция Импорт парного yaml код не покрывает).",
        "en": "Type '{name}' comes from subsystem '{sub}' which this module does not import: "
              "compilation fails at this line. The module needs an import line of its own "
              "(the {n[Импорт]} section of the paired yaml does not cover the code).",
    },
    "code/missing-import.chain": {
        "ru": "Обращение '{name}' – к элементу подсистемы '{sub}', а модуль её не импортирует: "
              "компиляция упадёт на этой строке. Нужна строка импорта этой подсистемы "
              "(секция Импорт парного yaml код не покрывает).",
        "en": "'{name}' reaches an element of subsystem '{sub}' which this module does not "
              "import: compilation fails at this line. The module needs an import line of its "
              "own (the {n[Импорт]} section of the paired yaml does not cover the code).",
    },
    "yaml/missing-subsystem-usage.title": {
        "ru": "Подсистема импортируется, но не объявлена используемой",
        "en": "A subsystem is imported but not declared as used",
    },
    "yaml/missing-subsystem-usage.missing": {
        "ru": "Подсистему '{sub}' импортируют элементы и модули этой подсистемы "
              "(файлов: {count}), а в её описании нет блока Использование с этой подсистемой – "
              "применение проекта упадёт. Импорт даёт краткие имена, но саму подсистему "
              "разрешает именно Использование.",
        "en": "Subsystem '{sub}' is imported by elements and modules of this subsystem "
              "({count} file(s)) while its description has no {n[Использование]} entry for it - "
              "the project fails to apply. An import gives the short names, but it is "
              "{n[Использование]} that permits the subsystem itself.",
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
    kind = object_kind(data)
    if err is not None or not isinstance(data, dict) or not kind:
        return None
    stdlib = semantics._stdlib_names()
    raw = value_of(data, "Импорт", kind)
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
    nm = value_of(data, "Имя", kind)
    return {
        "k": "el",
        "path": str(source.path),
        "name": nm if isinstance(nm, str) else None,
        "vis": value_of(data, "ОбластьВидимости", kind),
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
    kind = object_kind(data)
    if err is not None or not isinstance(data, dict) or not kind:
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
    nm = value_of(data, "Имя", kind)
    return {
        "k": "el",
        "path": str(source.path),
        "name": nm if isinstance(nm, str) else None,
        "vis": value_of(data, "ОбластьВидимости", kind),
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


# --- code/missing-import ------------------------------------------------------------------


def _missing_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: the placement slice as above, and from a module its imports and the
    roots of the types it WRITES DOWN - a parameter, a variable, a return, `новый`, `как`,
    `это`, generic arguments included.

    Only written types are collected, and that narrowness is the rule (see the docstring of
    `missing_code_import`). A type position is a place where the name can be nothing but a
    type, which is what keeps the reading of a name free of guesswork.
    """
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
        kind = object_kind(data)
        if err is not None or not isinstance(data, dict) or not kind:
            return None
        nm = value_of(data, "Имя", kind)
        return {
            "k": "el",
            "path": str(source.path),
            "stem": _pair_stem(source.rel),
            "name": nm if isinstance(nm, str) else source.path.stem,
            "vis": value_of(data, "ОбластьВидимости", kind),
            # The sections of the element are what the platform hands to its module by name -
            # see the chain roots below.
            "keys": sorted(k for k in data if isinstance(k, str)),
        }
    if source.kind != "xbsl":
        return None
    try:
        local = sorted(semantics._file_local_types(source))
    except DatasetError:
        local = []  # no language data - the collision guard degrades to skipping nothing
    module, errors = parse(source)
    if errors:
        # A module that does not parse has no reliable type positions; the syntax rules
        # report it, and guessing over a broken tree would invent references.
        return {"k": "mod", "path": str(source.path), "stem": _pair_stem(source.rel),
                "imports": [], "cands": [], "local_types": local}
    stdlib = semantics._stdlib_names()
    lm = linemap(source)
    toks = tokens(source)
    imports = [
        toks[i + 1].value
        for i, tok in enumerate(toks)
        if tok.kind == "KEYWORD" and tok.canonical == "IMPORT" and i + 1 < len(toks)
        and toks[i + 1].kind == "IDENT"
    ]
    cands: list[tuple[str, str, int, int]] = []
    for node in _nodes(module):
        if not isinstance(node, P.TypeRef):
            continue
        for chain in _parse_type_string(getattr(node, "text", "") or "") or ():
            if chain[0] in stdlib:
                continue
            line, col = lm.linecol(node.start)
            cands.append((chain[0], ".".join(chain), line, col))
    # The other shape: the root of a chain, `Модуль.Метод()`. A bare name is many things, so
    # everything the module itself explains is taken off the table here, in the file that has
    # the answer: names declared in the method, names the module declares, and the implicit
    # names of the platform. The sections of the PAIRED yaml are subtracted in the reduce -
    # they live in another file.
    roots: list[tuple[str, str, int, int]] = []
    declared_here = {
        getattr(member, "name", "") for member in module.members
        if isinstance(member, (P.ObjectField, P.Structure, P.Enum, P.Method))
    }
    for method in module.members:
        if not isinstance(method, P.Method):
            continue
        env = _method_names(method)
        for node in _nodes(method.body):
            if not isinstance(node, P.Member) or not isinstance(node.obj, P.Name):
                continue
            name = node.obj.name
            if name in env or name in declared_here or name in stdlib or name in _IMPLICIT:
                continue
            line, col = lm.linecol(node.obj.start)
            roots.append((name, f"{name}.{node.name}", line, col))
    return {"k": "mod", "path": str(source.path), "stem": _pair_stem(source.rel),
            "imports": imports, "cands": cands, "roots": roots, "local_types": local}


def _method_names(method: P.Method) -> set[str]:
    """Names a method introduces itself: parameters, variables, loop and lambda names."""
    names = {getattr(p, "name", "") for p in (getattr(method, "params", ()) or ())}
    for node in _nodes(getattr(method, "body", None)):
        if isinstance(node, P.VarDecl):
            names.add(node.name)
        elif isinstance(node, (P.ForEach, P.ForTo)):
            names.add(getattr(node, "var", ""))
        elif isinstance(node, P.Lambda):
            names.update(getattr(p, "name", "") for p in (getattr(node, "params", ()) or ()))
    return names


def _nodes(node: object) -> Iterable[P.Node]:
    """Every node of a tree, list fields included."""
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _nodes(item)
        return
    if not isinstance(node, P.Node):
        return
    yield node
    for f in fields(node):
        yield from _nodes(getattr(node, f.name, None))


@rule(
    "code/missing-import", "code/missing-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_missing_import_mapper,
)
def missing_code_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A module names a type of ANOTHER subsystem without importing it - the compiler refuses.

    The mirror of code/unused-import, and the mirror is where the care goes: there a name that
    merely COINCIDES with an element of the imported subsystem keeps the import and costs
    nothing, here the same coincidence would be a false report. So the two rules do not read
    the module the same way. That one takes every identifier; this one takes only the roots of
    types WRITTEN DOWN in a type position, where a name can be nothing else.

    The root of a chain (`Модуль.Метод()`) is judged too, and everything that can explain such
    a bare name is subtracted first: the names the method introduces (parameters, variables,
    loop and lambda names), the names the module declares, the implicit names of the platform,
    and the SECTIONS OF THE PAIRED YAML - a scheduled job reads its own parameters as
    `Parameters`, and a project that happens to hold an element of that name elsewhere must not
    turn that into a report. Each of those is a fact of the file at hand rather than an entry
    in a list, which is what makes the subtraction safe to trust.

    The narrowings of yaml/missing-import hold here too, for the same reasons: a stdlib name is
    skipped (without an import the foreign namespace is not in scope and the name resolves to
    the standard one), so is a type declared inside a module of the project, and so is a
    non-public foreign element - that one is a visibility error rather than a missing import.
    """
    roots = {Path(f["dir"]): f["name"] for f in facts.values() if f["k"] == "sub"}
    if not roots:
        return  # no subsystem files - the project layout is unknown, nothing to judge
    local_types: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "mod":
            local_types.update(fact["local_types"])
    placement: dict[str, dict[str, object]] = {}
    paired_keys: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] != "el":
            continue
        paired_keys[fact["stem"]] = set(fact["keys"])
        sub = _subsystem_of(Path(fact["path"]), roots)
        if sub:
            placement.setdefault(fact["name"], {})[sub] = fact["vis"]
    for rel, fact in facts.items():
        if fact["k"] != "mod":
            continue
        own_keys = paired_keys.get(fact["stem"], frozenset())
        candidates_here = [(*c, "missing") for c in fact["cands"]] + [
            (*c, "chain") for c in fact.get("roots", ()) if c[0] not in own_keys
        ]
        if not candidates_here:
            continue
        my_sub = _subsystem_of(Path(fact["path"]), roots)
        if my_sub is None:
            continue  # a module outside any subsystem needs no import
        imports = set(fact["imports"])
        reported: set[tuple[str, ...]] = set()
        for root, chain_name, line, col, shape in candidates_here:
            if root in local_types:
                continue
            owners = placement.get(root)
            if not owners or my_sub in owners:
                continue
            candidates = tuple(sorted(
                sub for sub, vis in owners.items() if vis in _public_scopes()
            ))
            if not candidates or imports.intersection(candidates):
                continue
            if candidates in reported:
                continue
            reported.add(candidates)
            yield Diagnostic(
                rel, line, col, "code/missing-import", Severity.WARNING,
                i18n.t(f"code/missing-import.{shape}", name=chain_name,
                       sub="/".join(candidates)),
            )


# --- yaml/missing-subsystem-usage -----------------------------------------------------------

#: The key of the subsystem descriptor that permits another subsystem, both spellings.
_USAGE_KEYS = ("Использование", "Usage")
_USAGE_LINE_RE = re.compile(r"(?m)^[ \t]*(?:Использование|Usage):")


def _usage_mapper(source: SourceFile) -> dict | None:
    """The map phase: a subsystem descriptor contributes what it declares as used, an element
    or a module - the subsystems it imports."""
    if source.kind == "xbsl":
        toks = tokens(source)
        imports = [
            toks[i + 1].value
            for i, tok in enumerate(toks)
            if tok.kind == "KEYWORD" and tok.canonical == "IMPORT" and i + 1 < len(toks)
            and toks[i + 1].kind == "IDENT"
        ]
        if not imports:
            return None
        return {"k": "imp", "path": str(source.path), "imports": imports}
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    if source.path.name in _SUBSYSTEM_FILES:
        name = value_of(data, "Имя")
        used: list[str] = []
        for key in _USAGE_KEYS:
            raw = data.get(key)
            if isinstance(raw, list):
                used.extend(e for e in raw if isinstance(e, str))
        match = _USAGE_LINE_RE.search(source.text)
        line = linemap(source).linecol(match.start())[0] if match else 1
        return {
            "k": "sub",
            "dir": str(source.path.parent),
            "name": name if isinstance(name, str) else source.path.parent.name,
            "used": used,
            "line": line,
        }
    kind = object_kind(data)
    if not kind:
        return None
    raw = value_of(data, "Импорт", kind)
    imports = [e for e in raw if isinstance(e, str)] if isinstance(raw, list) else []
    if not imports:
        return None
    return {"k": "imp", "path": str(source.path), "imports": imports}


@rule(
    "yaml/missing-subsystem-usage", "yaml/missing-subsystem-usage.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_usage_mapper,
)
def missing_subsystem_usage(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """The third condition of a reference across a subsystem boundary, and the last one the
    linter did not check.

    The platform asks for three things (docs, "Модульная разработка"): the supplier publishes
    the element, the consumer imports the namespace - and the consumer's SUBSYSTEM declares the
    supplier in its `Использование`. The documentation puts the import second and in brackets
    ("или дополнительно импортируйте"): the usage is what permits the subsystem, the import
    only adds the short names. Miss it and the project fails to apply, with the compiler naming
    the description of the subsystem - a message that arrives at deploy time, which is exactly
    where a linter is supposed to save the trip.

    The evidence is the import itself, not a resolved reference: a file that writes
    `импорт Б` states its intent outright, so the check is a cross-read of two declarations
    rather than a guess about names. An import of something that is not a subsystem of this
    project - a library, another project (`e1c::...`), a typo - is not this rule's case, the
    same way code/unused-import leaves it alone.

    One diagnostic per missing subsystem, on the DESCRIPTOR: that is the single line to add,
    and reporting it once there beats repeating it at every importing file.
    """
    roots: dict[Path, str] = {}
    used: dict[str, set[str]] = {}
    where: dict[str, tuple[str, int]] = {}
    for rel, fact in facts.items():
        if fact["k"] != "sub":
            continue
        roots[Path(fact["dir"])] = fact["name"]
        used[fact["name"]] = set(fact["used"])
        where[fact["name"]] = (rel, fact["line"])
    if not roots:
        return  # no subsystem files - the project layout is unknown, nothing to judge
    known = set(roots.values())
    counts: dict[tuple[str, str], int] = {}
    for fact in facts.values():
        if fact["k"] != "imp":
            continue
        my_sub = _subsystem_of(Path(fact["path"]), roots)
        if my_sub is None:
            continue  # a file outside any subsystem imports on its own behalf
        for name in fact["imports"]:
            if name not in known or name == my_sub or name in used.get(my_sub, ()):
                continue
            counts[(my_sub, name)] = counts.get((my_sub, name), 0) + 1
    for (my_sub, name), count in sorted(counts.items()):
        rel, line = where[my_sub]
        yield Diagnostic(
            rel, line, 1, "yaml/missing-subsystem-usage", Severity.WARNING,
            i18n.t("yaml/missing-subsystem-usage.missing", sub=name, count=count),
        )
