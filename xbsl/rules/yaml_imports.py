"""Tier D: cross-subsystem references - six rules over one placement model.

The platform asks for three things before an element of subsystem Б may be used in subsystem А
(docs, "Модульная разработка"): the element is public, the consumer imports the namespace, and
the consumer's subsystem declares Б in its `Использование`. One rule per condition per side:
yaml/foreign-not-public and code/foreign-not-public for the first (the markup and the module
reach the element from two places), yaml/missing-import and code/missing-import for the
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

Every finding carries its namespaces in `Diagnostic.data` as well as in the message: the
import rules `{"namespaces": [...]}` (importing any one of them resolves the name), the
visibility rules `{"namespace": ..., "name": <the element>}`, code/unused-import
`{"namespace": ...}`, yaml/missing-subsystem-usage
`{"subsystem": ..., "uses": ...}`. A message is bilingual prose; the data is what a repair
reads. The scaffolding moves an object or renames a package by running these very rules over
the sources before and after the change (xbsl.scaffold.op_move_object), so the decision "this
reference loses its import" has one model, not a copy per surface.


The yaml/missing-import rule: a yaml element (a form, an object...) that references an
element of ANOTHER subsystem must list that subsystem in its own `Импорт:` section. A
reference is either a type position (the string values of `Тип` keys, generic arguments
included) or a navigation target (`ТипФормы`) - see _REFERENCE_KEYS. The namespace import in the paired `.xbsl` module does not cover the yaml – such
a project deploys, but the component initialization fails at runtime.

A third reference shape is a BINDING: a yaml string value opening with `=` holds an
expression, and the root of a dotted chain in it (`=ЧужойМодуль.Метод()`) reaches a
common module of another subsystem exactly the way a type position does - except the
refusal comes earlier, from the server compiler
(`Пространство имен ... не импортировано`), at the price of a full deploy cycle.

The binding shape is judged by both rules: this one wants the public foreign root imported,
yaml/foreign-not-public wants it public in the first place - a probe applied on a server
(02.09.2026) refused a binding to a non-public foreign module at the binding position with
the same `Тип "..." недоступен из-за модификатора видимости @ВПодсистеме` the type positions
get. The live case behind the extension: a form markup called a method of a foreign common
module from a property binding with no import line, the linter read only the type positions
and passed the whole project clean, and the refusal arrived from the server compiler at the
price of a full deploy cycle. Re-checked on a copy of that tree with the import line removed:
zero findings before this extension.

A qualified name (`Подсистема::Элемент`, in a type position, a binding or a call) needs no
import - it relies on the usage declaration - but the element it names must be public all
the same: the same probe refused a qualified binding and a qualified call from code with the
very same message. The two visibility rules judge the qualified form by the subsystem it
names; the import rules keep leaving it alone.

An element's place is read off the source layout by the placement model of `xbsl.layout`:
the project root is the folder holding `Проект.yaml`, a subsystem is a first-level folder
of it (its `Подсистема.yaml` is optional - the name is the descriptor's `Name` when there is
one, else the folder name), and the folders between the subsystem and the element are its
package (nested packages included; the resources and localization folders are not
packages). The placement KEY of an element is `Subsystem` at the subsystem root and
`Subsystem::Package` inside a package, and the key is what an import must name: within one
subsystem the root and the packages see each other without an import, but across a
subsystem boundary an element of a package comes only through `импорт Б::П` - the import
of the subsystem alone does not bring it (a server build refused exactly that, 13.09.2026,
with `Пространство имен "...::Б::П" не импортировано`). The full form
`Поставщик::Проект::Б::П` names the same package. Without a project descriptor in the run
the model falls back to the subsystem descriptors alone: the nearest `Подсистема.yaml` up
the path is the subsystem root, and the folders below it are its packages.

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
- a binding root declared in THIS yaml (any name-key value of the tree – an attribute,
  a component, a command, a property) or in the PAIRED module (a method, a field, a
  structure, an enumeration) resolves to the file's own scope and is skipped, as are
  the implicit names of the platform;
- a `$Словарь.Ключ` reference inside a binding belongs to
  yaml/localization-missing-import and does not match the chain pattern, and neither
  does a qualified `Подсистема::Элемент.Метод` chain (that form needs no import);
- a file outside any subsystem (directly in the project root, or with no descriptor up the
  path when the run holds no project descriptor) is skipped, as is the whole check when
  the run holds no descriptor at all.

One diagnostic is reported per missing subsystem per file (the fix is a single import
line), anchored at the first offending type value. When several foreign public
subsystems declare the same name and none of them is imported, the candidates are listed
together ('Б/В') – importing any of them resolves the name.

The rule is project-wide: it needs the layout of the whole project (like
yaml/unknown-type, it does not run in single-file mode).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from xbsl import dataset, i18n, parser as P, terms
from xbsl.dataset import DatasetError
from xbsl.diagnostics import Diagnostic, Severity
from xbsl.engine import SourceFile, rule
from xbsl.layout import (
    PROJECT_FILES,
    SUBSYSTEM_FILES,
    Layout,
    Place,
    first_text,
    name_keys,
    subsystem_of_key,
    vendor_keys,
)
from xbsl.lexer import Token, _skip_interpolation, linemap, tokens
from xbsl.parser import parse
from xbsl.rules import semantics
from xbsl.rules.enum_values import _binding_values, _name_values
from xbsl.rules.environment import _pair_stem
from xbsl.rules.undefined_names import _IMPLICIT
from xbsl.rules.yaml_schema import _HAVE_YAML, _parsed, object_kind, unreadable_object, value_of
from xbsl.rules.yaml_types import _parse_type_string, _type_values, _value_positions

MESSAGES = {
    "code/unused-import.title": {
        "ru": "Неиспользуемый импорт подсистемы",
        "en": "Unused subsystem import",
    },
    "code/unused-import.unused": {
        "ru": "Импорт пространства имён '{sub}' не используется: ни один его элемент в коде "
              "модуля не упомянут. Ссылки ПАРНОГО yaml импорт модуля не покрывает – у yaml "
              "своя секция Импорт. Строку можно снять.",
        "en": "The import of namespace '{sub}' is unused: no element of it is mentioned in "
              "the module code. References of the PAIRED yaml are not covered by a module "
              "import - the yaml has an {n[Импорт]} section of its own. The line can go.",
    },
    "code/unused-import.packages": {
        "ru": "Импорт подсистемы '{sub}' не используется: код модуля упоминает только "
              "элементы её пакетов ({packages}), а они через 'импорт {sub}' не приходят – "
              "у пакета своя строка импорта. Строку можно снять.",
        "en": "The import of subsystem '{sub}' is unused: the module code mentions only "
              "elements of its packages ({packages}), and those do not come through "
              "`{n[импорт]} {sub}` - a package has an import line of its own. The line can go.",
    },
    "code/missing-import.title": {
        "ru": "Нет импорта подсистемы в модуле",
        "en": "Missing subsystem import in a module",
    },
    "code/missing-import.missing": {
        "ru": "Тип '{name}' – из пространства имён '{sub}', а модуль его не импортирует: "
              "компиляция упадёт на этой строке. Нужна строка 'импорт {sub}' – импорт одной "
              "подсистемы элементы её пакетов не даёт, а секция Импорт парного yaml код не "
              "покрывает.",
        "en": "Type '{name}' comes from namespace '{sub}' which this module does not import: "
              "compilation fails at this line. The module needs the line `{n[импорт]} {sub}` - an "
              "import of the subsystem alone does not bring the elements of its packages, and "
              "the {n[Импорт]} section of the paired yaml does not cover the code.",
    },
    "code/missing-import.chain": {
        "ru": "Обращение '{name}' – к элементу пространства имён '{sub}', а модуль его не "
              "импортирует: компиляция упадёт на этой строке. Нужна строка 'импорт {sub}' – "
              "импорт одной подсистемы элементы её пакетов не даёт, а секция Импорт парного "
              "yaml код не покрывает.",
        "en": "'{name}' reaches an element of namespace '{sub}' which this module does not "
              "import: compilation fails at this line. The module needs the line "
              "`{n[импорт]} {sub}` - an import of the subsystem alone does not bring the elements "
              "of its packages, and the {n[Импорт]} section of the paired yaml does not cover "
              "the code.",
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
        "ru": "Тип '{name}' – из пространства имён '{sub}', а в секции Импорт его нет: "
              "инициализация компонента упадёт в рантайме. Нужна строка '- {sub}' в секции "
              "Импорт – импорт одной подсистемы элементы её пакетов не даёт, а импорт в "
              "парном .xbsl yaml не покрывает.",
        "en": "Type '{name}' comes from namespace '{sub}' which the {n[Импорт]} section does "
              "not list: the component initialization fails at runtime. The section needs "
              "the entry '- {sub}' - an import of the subsystem alone does not bring the "
              "elements of its packages, and an import in the paired .xbsl does not cover "
              "the yaml.",
    },
    "yaml/missing-import.chain": {
        "ru": "Обращение '{name}' – к элементу пространства имён '{sub}', а в секции Импорт "
              "его нет: деплой упадёт на серверной компиляции (\"Пространство имен ... не "
              "импортировано\"). Нужна строка '- {sub}' в секции Импорт – импорт одной "
              "подсистемы элементы её пакетов не даёт, а импорт в парном .xbsl биндинги "
              "разметки не покрывает.",
        "en": "'{name}' reaches an element of namespace '{sub}' which the {n[Импорт]} section "
              "does not list: the deploy fails at server compilation (\"the namespace is not "
              "imported\"). The section needs the entry '- {sub}' - an import of the subsystem "
              "alone does not bring the elements of its packages, and an import in the paired "
              ".xbsl does not cover the markup bindings.",
    },
}
i18n.register(MESSAGES)

#: Both spellings of the descriptors, as the placement model names them.
_SUBSYSTEM_FILES = SUBSYSTEM_FILES
_PROJECT_FILES = PROJECT_FILES
_DESCRIPTOR_FILES = (*_PROJECT_FILES, *_SUBSYSTEM_FILES)


@lru_cache(maxsize=1)
def _public_scopes() -> frozenset[str]:
    """Scopes that publish a subsystem member, both spellings."""
    return frozenset(terms.key_forms("ВПроекте", "Глобально"))


dataset.register_reset(_public_scopes.cache_clear)


def _layout_fact(source: SourceFile) -> dict | None:
    """The map phase of the placement model, shared by every rule of this module.

    A project descriptor contributes its folder and identity (vendor and name - the folder
    names when the file does not say), a subsystem descriptor its folder and the name it
    declares; any other source contributes nothing here.
    """
    if source.kind != "yaml" or source.path.name not in _DESCRIPTOR_FILES:
        return None
    data, err = _parsed(source)
    declared = data if err is None and isinstance(data, dict) else {}
    folder = source.path.parent
    if source.path.name in _PROJECT_FILES:
        return {
            "k": "proj",
            "dir": str(folder),
            "vendor": first_text(declared, vendor_keys()) or folder.parent.name,
            "name": first_text(declared, name_keys()) or folder.name,
        }
    return {
        "k": "sub",
        "dir": str(folder),
        "name": first_text(declared, name_keys()) or folder.name,
    }


def _layout_from(facts: Mapping[str, dict]) -> Layout:
    """The reduce side: the placement model out of the descriptor facts of the run."""
    return Layout(
        {Path(f["dir"]): (f["vendor"], f["name"]) for f in facts.values() if f["k"] == "proj"},
        {Path(f["dir"]): f["name"] for f in facts.values() if f["k"] == "sub"},
    )


def _module_imports(toks: Sequence[Token]) -> list[tuple[str, int, int]]:
    """The namespaces a module imports, each as written, with the position of the keyword.

    `импорт Б`, `импорт Б::П` and the full `импорт Поставщик::Проект::Б::П` are one shape -
    identifiers joined by `::`. The qualifiers are kept; the reduce takes the project's own
    prefix off, so the two spellings of a package meet the same placement key.
    """
    out: list[tuple[str, int, int]] = []
    for i, tok in enumerate(toks):
        if tok.kind != "KEYWORD" or tok.canonical != "IMPORT":
            continue
        parts: list[str] = []
        j = i + 1
        while j < len(toks) and toks[j].kind == "IDENT":
            parts.append(toks[j].value)
            if j + 2 < len(toks) and toks[j + 1].kind == "OP" and toks[j + 1].value == "::":
                j += 2
                continue
            break
        if parts:
            out.append(("::".join(parts), tok.line, tok.col))
    return out


def _foreign_candidates(
    root: str, my_place: Place, placement: dict[str, dict[str, object]],
) -> tuple[str, ...]:
    """The public placement keys a plain name resolves to outside the referrer's subsystem.

    Empty when the name is unknown, when the referrer's own subsystem owns a namesake (the
    root and the packages of one subsystem see each other, so the name resolves locally) or
    when no owner is public (the visibility rules' case). A key spells the namespace the
    import must name: `Б` for the subsystem root, `Б::П` for a package.
    """
    owners = placement.get(root)
    if not owners or any(subsystem_of_key(key) == my_place.subsystem for key in owners):
        return ()
    return tuple(sorted(key for key, vis in owners.items() if vis in _public_scopes()))

# Yaml keys that name another element. A navigation target is as much a reference as a type
# position, so both rules below read both keys: `ТипФормы: ЗадачиФормаСписка` reaches into
# another subsystem exactly the way `Тип: Задачи.Ссылка` does.
_REFERENCE_KEYS = ("Тип", "ТипФормы")

#: The root of a dotted chain inside a binding value (`=Модуль.Метод(...)`): an identifier
#: opening with a capital of either alphabet, a dot, a member (the same shape
#: code/unknown-enum-value reads out of bindings). The lookbehinds keep out what is not a
#: chain root: a member of a longer chain (after `.`), a `$Словарь.Ключ` localization
#: reference (yaml/localization-missing-import's case), and a qualified
#: `Подсистема::Элемент` name - that form relies on the usage declaration of the
#: subsystem and needs no import.
_BINDING_CHAIN = re.compile(
    r"(?<![\wА-Яа-яЁё.$])(?<!::)([А-ЯЁA-Z][\wА-Яа-яЁё]*)\.([А-Яа-яЁёA-Za-z_][\wА-Яа-яЁё]*)",
    re.UNICODE,
)


#: The opening of a full interpolation inside a string literal, `%{` or `${`.
_INTERPOLATION_OPEN = re.compile(r"[%$]\{")

#: A string nested inside an interpolation expression: its text is not names.
_NESTED_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')

#: Any identifier of an interpolation expression.
_INTERPOLATION_IDENT = re.compile(r"[^\W\d]\w*")

#: The root of a dotted chain inside an interpolation expression: the shape of
#: `_BINDING_CHAIN`, and neither a member of a longer chain nor the tail of a qualified name.
_INTERPOLATION_CHAIN = re.compile(
    r"(?<![\wА-Яа-яЁё.$%:])([А-ЯЁA-Z][\wА-Яа-яЁё]*)\.([А-Яа-яЁёA-Za-z_][\wА-Яа-яЁё]*)",
    re.UNICODE,
)


def _interpolation_bodies(raw: str, *, blank_strings: bool = True) -> list[tuple[int, str]]:
    """The full interpolations of a string literal: (offset of the expression, its text).

    `%{...}` and `${...}` hold code, and a name written there is a reference like any other:
    the compiler resolves it against the imports of the module and refuses a missing one at
    the line of the string. A server build over a project with packages showed both sides of
    it - an import serving nothing but such a name was reported unused, and the build without
    it failed. The balancing is the lexer's own, so a nested string or a collection literal
    does not cut the expression short, and a sign after an odd run of backslashes is an
    escaped character, as `code/undefined-name` reads it. With `blank_strings` the text of a
    nested string is replaced by spaces of the same length: the offsets stay true, and words
    in quotes are not taken for names.
    """
    if "%{" not in raw and "${" not in raw:
        return []
    out: list[tuple[int, str]] = []
    pos = 0
    while True:
        found = _INTERPOLATION_OPEN.search(raw, pos)
        if found is None:
            return out
        i = found.start()
        backslashes = i
        while backslashes > 0 and raw[backslashes - 1] == "\\":
            backslashes -= 1
        if (i - backslashes) % 2:  # an odd run of backslashes escapes the sign
            pos = i + 1
            continue
        end = _skip_interpolation(raw, i + 2)
        body = raw[i + 2:max(i + 2, end - 1)]
        if blank_strings:
            body = _NESTED_STRING.sub(lambda m: " " * len(m.group(0)), body)
        out.append((i + 2, body))
        pos = max(end, i + 2)


def _binding_chain_roots(
    source: SourceFile, data: dict, stdlib: frozenset[str],
) -> list[tuple[str, str, int, int]]:
    """Chain roots of the binding values of a parsed yaml, with positions.

    Everything THIS file explains is subtracted right here, where the answer lives: a root
    that any name-key value of the tree declares (an attribute, a component, a command, a
    property - the platform binds those names into the markup scope), a stdlib name (without
    an import it resolves to the standard namespace), an implicit platform name. What the
    PAIRED module declares is subtracted in the reduce - it lives in another file. The
    position is the first occurrence of the chain in the raw text, root first.
    """
    if "=" not in source.text:  # the cheap gate: no bindings, nothing to scan
        return []
    own_names = _name_values(data)
    pairs: dict[tuple[str, str], None] = {}
    for binding in _binding_values(data):
        for match in _BINDING_CHAIN.finditer(binding):
            root = match.group(1)
            if root in stdlib or root in own_names or root in _IMPLICIT:
                continue
            pairs.setdefault((root, match.group(2)))
    if not pairs:
        return []
    lm = linemap(source)
    roots: list[tuple[str, str, int, int]] = []
    for root, member in pairs:
        pat = re.compile(
            r"(?<![\wА-Яа-яЁё.$])(?<!::)" + re.escape(f"{root}.{member}") + r"(?![\wА-Яа-яЁё])"
        )
        found = pat.search(source.text)
        line, col = lm.linecol(found.start()) if found else (1, 1)
        roots.append((root, f"{root}.{member}", line, col))
    return roots


#: A qualified reference: one or more `Имя::` qualifiers and the element name. The
#: qualifiers are kept whole - `Б::Элемент` names a subsystem root, `Б::П::Элемент` a package,
#: `e1c::site::Б::Элемент` a subsystem with the project prefix on; what they name inside THIS
#: project is decided in the reduce, so a library (`Стд::...`) or a typo is left alone.
_QUALIFIED = re.compile(
    r"(?<![\wА-Яа-яЁё.$:])((?:[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*::)+)([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)"
)


def _qualified_roots(text: str) -> list[tuple[str, str]]:
    """`(qualifiers::element, the written form)` of every qualified name in a string.

    The root keeps the whole chain of qualifiers so the reduce resolves it by the placement
    key it names - the subsystem root, a package, or the same with the project prefix on. A
    qualified name never means "whichever public namesake". One entry per root, first
    written form kept.
    """
    out: dict[str, str] = {}
    for match in _QUALIFIED.finditer(text):
        out.setdefault(match.group(1) + match.group(2), match.group(0))
    return list(out.items())


def _qualified_positions(
    source: SourceFile, texts: Iterable[str],
) -> list[tuple[str, str, int, int]]:
    """Qualified roots of the given yaml values with the position of their first occurrence."""
    found: dict[str, tuple[str, int, int]] = {}
    lm = None
    for text in texts:
        if "::" not in text:
            continue
        for root, written in _qualified_roots(text):
            if root in found:
                continue
            lm = lm or linemap(source)
            hit = re.search(r"(?<![\wА-Яа-яЁё.$:])" + re.escape(written) + r"(?![\wА-Яа-яЁё:])", source.text)
            line, col = lm.linecol(hit.start()) if hit else (1, 1)
            found[root] = (written, line, col)
    return [(root, written, line, col) for root, (written, line, col) in found.items()]


def _foreign_owner(
    root: str, mine: str | None, project_dir: Path | None,
    placement: dict[str, dict[str, object]], layout: Layout,
) -> tuple[str, object] | None:
    """(owner key, its visibility) of the non-public foreign target `root` names, or None.

    A plain root resolves by name: the referrer's own subsystem wins (its root and its
    packages alike), and a public owner anywhere silences it (a missing import at most - the
    sibling rules' case). A qualified root names its place itself - the subsystem root, a
    package, the project prefix on or off: the element there is the target, and only its own
    visibility counts - a public namesake elsewhere does not reach a qualified reference.
    `mine` is None for a module outside every subsystem: nothing resolves locally for it.
    """
    if "::" in root:
        chain, _, name = root.rpartition("::")
        owners = placement.get(name)
        if not owners:
            return None
        key = layout.resolve(chain.split("::"), project_dir, owners)
        if key is None or subsystem_of_key(key) == mine or owners[key] in _public_scopes():
            return None
        return key, owners[key]
    owners = placement.get(root)
    if not owners or any(subsystem_of_key(key) == mine for key in owners):
        return None
    if any(vis in _public_scopes() for vis in owners.values()):
        return None
    owner = sorted(owners)[0]
    return owner, owners[owner]


def _yaml_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor contributes its place in the layout, an object yaml its
    placement slice (name, visibility, imports) with its candidate type roots and binding
    chain roots (stdlib settles here), a module its local types (the collision guard) and
    the names it declares - the paired yaml addresses those through the element name, so
    they explain a binding root the same way a local name does."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        try:
            local = semantics._file_local_types(source)
        except DatasetError:
            return None  # no language data – neither guard has anything to offer
        module, errors = parse(source)
        declared = set() if errors else {
            name for member in module.members
            if isinstance(member, (P.ObjectField, P.Structure, P.Enum, P.Method))
            and (name := getattr(member, "name", ""))
        }
        if not local and not declared:
            return None
        return {"k": "x", "stem": _pair_stem(source.rel),
                "local_types": sorted(local), "declared": sorted(declared)}
    if source.kind != "yaml":
        return None
    if (fact := _layout_fact(source)) is not None:
        return fact
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
        "stem": _pair_stem(source.rel),
        "name": nm if isinstance(nm, str) else None,
        "vis": value_of(data, "ОбластьВидимости", kind),
        "imports": imports,
        "cands": cands,
        "broots": _binding_chain_roots(source, data, stdlib),
    }


@rule(
    "yaml/missing-import", "yaml/missing-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_yaml_import_mapper,
)
def missing_yaml_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    layout = _layout_from(facts)
    if not layout.known:
        return
    local_types: set[str] = set()
    declared_by_stem: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            local_types.update(fact["local_types"])
            declared_by_stem.setdefault(fact["stem"], set()).update(fact["declared"])
    placement: dict[str, dict[str, object]] = {}
    elements: list[tuple[str, dict, Place]] = []
    for rel, fact in facts.items():
        if fact["k"] != "el":
            continue
        place = layout.place(Path(fact["path"]))
        if place is None:
            continue
        elements.append((rel, fact, place))
        if fact["name"]:
            placement.setdefault(fact["name"], {})[place.key] = fact["vis"]
    for rel, fact, my_place in elements:
        imports = {layout.local_name(name, my_place.project_dir) for name in fact["imports"]}
        # A binding root the PAIRED module declares (a method, a field, a structure) is
        # addressed through the element's own name - the file explains it, not an import.
        paired = declared_by_stem.get(fact["stem"], frozenset())
        candidates_here = [(*c, "missing") for c in fact["cands"]] + [
            (*c, "chain") for c in fact["broots"] if c[0] not in paired
        ]
        reported: set[tuple[str, ...]] = set()
        for root, chain_name, line, col, shape in candidates_here:
            if root in local_types:
                continue
            candidates = _foreign_candidates(root, my_place, placement)
            if not candidates or imports.intersection(candidates):
                continue
            if candidates in reported:
                continue
            reported.add(candidates)
            yield Diagnostic(
                rel, line, col, "yaml/missing-import", Severity.WARNING,
                i18n.t(f"yaml/missing-import.{shape}", name=chain_name,
                       sub="/".join(candidates)),
                data={"namespaces": list(candidates)},
            )


# --- The other half: the foreign element is not public at all ---------------------------

MESSAGES_VISIBILITY = {
    "yaml/foreign-not-public.title": {
        "ru": "Ссылка на непубличный элемент чужой подсистемы",
        "en": "Reference to a non-public element of another subsystem",
    },
    "yaml/foreign-not-public.found": {
        "ru": "Элемент '{name}' лежит в пространстве имён '{sub}' и не публичен "
              "(ОбластьВидимости: {vis}) – из другой подсистемы он недоступен. "
              "Задайте у него ОбластьВидимости: ВПроекте.",
        "en": "Element '{name}' lives in namespace '{sub}' and is not public "
              "({n[ОбластьВидимости]}: {vis}) - it is unreachable from another subsystem. "
              "Set {n[ОбластьВидимости]}: {n[ВПроекте]} on it.",
    },
}
i18n.register(MESSAGES_VISIBILITY)

_DEFAULT_SCOPE = "ВПодсистеме"  # the platform default when the property is absent


def _visibility_mapper(source: SourceFile) -> dict | None:
    """The map phase: the same placement slice as above, the candidates also coming from the
    navigation key `FormType` (a form opened from another subsystem must be public), from the
    roots of the binding chains and from the qualified names of both. A module contributes
    its local types and the names it declares - a binding root the paired module declares is
    addressed through the element's own name, not a reference."""
    if not _HAVE_YAML:
        return None
    if source.kind == "xbsl":
        try:
            local = semantics._file_local_types(source)
        except DatasetError:
            return None
        module, errors = parse(source)
        declared = set() if errors else {
            name for member in module.members
            if isinstance(member, (P.ObjectField, P.Structure, P.Enum, P.Method))
            and (name := getattr(member, "name", ""))
        }
        if not local and not declared:
            return None
        return {"k": "x", "stem": _pair_stem(source.rel),
                "local_types": sorted(local), "declared": sorted(declared)}
    if source.kind != "yaml":
        return None
    if (fact := _layout_fact(source)) is not None:
        return fact
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
    typed = [v for key in _REFERENCE_KEYS for v in dict.fromkeys(_type_values(data, key))]
    bound = list(_binding_values(data)) if "=" in source.text else []
    return {
        "k": "el",
        "path": str(source.path),
        "stem": _pair_stem(source.rel),
        "name": nm if isinstance(nm, str) else None,
        "vis": value_of(data, "ОбластьВидимости", kind),
        "cands": cands,
        "broots": _binding_chain_roots(source, data, stdlib),
        "qroots": _qualified_positions(source, typed + bound),
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
    false positives): names of the file's own subsystem resolve locally - its root and its
    packages alike, the default visibility spans them - stdlib names and module-declared
    local types are skipped, and a name no project element declares (a platform form like
    `ФормаЖурналаСобытий`) is unknown, not wrong. One diagnostic per target per file.

    Three shapes are read: the type positions and navigation targets, the roots of the
    binding chains (`=ЧужойМодуль.Метод()`, less what the paired module declares), and the
    qualified names `Подсистема[::Пакет]::Элемент` of both. The last two were proven the same
    way on a server build (02.09.2026): a binding to a non-public foreign module, a qualified
    binding and a qualified call from code all fail with the same message at the reference
    position - a qualified name needs no import, yet the element must be public. It resolves
    by the place it names alone: a public namesake elsewhere does not reach it.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return
    local_types: set[str] = set()
    declared_by_stem: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] == "x":
            local_types.update(fact["local_types"])
            declared_by_stem.setdefault(fact["stem"], set()).update(fact.get("declared", ()))
    placement: dict[str, dict[str, object]] = {}
    elements: list[tuple[str, dict, Place]] = []
    for rel, fact in facts.items():
        if fact["k"] != "el":
            continue
        place = layout.place(Path(fact["path"]))
        if place is None:
            continue
        elements.append((rel, fact, place))
        if fact["name"]:
            placement.setdefault(fact["name"], {})[place.key] = fact["vis"]
    for rel, fact, my_place in elements:
        # A binding root the PAIRED module declares is addressed through the element's own
        # name - the file explains it, not a foreign element.
        paired = declared_by_stem.get(fact.get("stem", ""), frozenset())
        candidates_here = list(fact["cands"]) + [
            c for c in fact.get("broots", ()) if c[0] not in paired
        ] + list(fact.get("qroots", ()))
        reported: set[str] = set()
        for root, chain_name, line, col in candidates_here:
            if root in local_types or root in reported:
                continue
            found = _foreign_owner(
                root, my_place.subsystem, my_place.project_dir, placement, layout,
            )
            if found is None:
                continue
            owner, vis = found
            vis = vis or _DEFAULT_SCOPE
            reported.add(root)
            yield Diagnostic(
                rel, line, col, "yaml/foreign-not-public", Severity.ERROR,
                i18n.t("yaml/foreign-not-public.found", name=chain_name, sub=owner, vis=vis),
                data={"namespace": owner, "name": root.rpartition("::")[2]},
            )


# --- code/unused-import -------------------------------------------------------------------


def _unused_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor contributes its place in the layout, an element yaml its
    name and path, a module its import lines (with positions) and the identifiers of its
    code."""
    if source.kind == "yaml":
        if not _HAVE_YAML:
            return None
        if (fact := _layout_fact(source)) is not None:
            return fact
        data, err = _parsed(source)
        if err is not None:
            # The file did not parse, but the element it declares still lives in this
            # subsystem: dropping it makes an import of the subsystem read as unused.
            unread = unreadable_object(source)
            return {"k": "el", "path": str(source.path), "name": unread} if unread else None
        if not isinstance(data, dict) or not object_kind(data):
            return None
        name = value_of(data, "Имя")
        return {"k": "el", "path": str(source.path),
                "name": name if isinstance(name, str) else source.path.stem}
    if source.kind != "xbsl":
        return None
    toks = tokens(source)
    imports = _module_imports(toks)
    if not imports:
        return None
    idents = {tok.value for tok in toks if tok.kind == "IDENT"}
    # A name inside `%{...}` of a string is a use as well. Every word of the expression counts,
    # nested strings included: here a word too many only keeps an import, never reports one.
    for tok in toks:
        if tok.kind == "STRING":
            for _offset, body in _interpolation_bodies(tok.value, blank_strings=False):
                idents.update(_INTERPOLATION_IDENT.findall(body))
    return {"k": "mod", "path": str(source.path), "imports": imports,
            "idents": sorted(idents)}


@rule(
    "code/unused-import", "code/unused-import.title", "D",
    scope="project", severity=Severity.WARNING, mapper=_unused_import_mapper,
)
def unused_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A module imports a namespace whose elements its code never mentions.

    The namespace is a placement key - a subsystem root (`импорт Б`) or a package
    (`импорт Б::П`) - and each is judged by the elements it owns itself: an import of the
    subsystem does not bring the elements of its packages, so a module that mentions only
    those has no use for `импорт Б` and is told which package imports carry the names
    instead. A namespace the project does not own (a library, another project, a typo) is
    not this rule's case.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
    owned: dict[str, set[str]] = {}  # placement key -> the names of its elements
    for fact in facts.values():
        if fact["k"] != "el":
            continue
        place = layout.place(Path(fact["path"]))
        if place is not None:
            owned.setdefault(place.key, set()).add(fact["name"])
    for rel, fact in facts.items():
        if fact["k"] != "mod":
            continue
        idents = set(fact["idents"])
        project_dir = layout.project_dir_of(Path(fact["path"]))
        for written, line, col in fact["imports"]:
            key = layout.local_name(written, project_dir)
            elements = owned.get(key)
            if elements is None:
                continue  # an unknown namespace (a library, a typo) - not this rule's case
            if elements & idents:
                continue
            packages = sorted(
                other for other, names in owned.items()
                if other.startswith(key + "::") and names & idents
            )
            if packages:
                message = i18n.t("code/unused-import.packages", sub=written,
                                 packages=", ".join(packages))
            else:
                message = i18n.t("code/unused-import.unused", sub=written)
            yield Diagnostic(rel, line, col, "code/unused-import", Severity.WARNING, message,
                             data={"namespace": key})


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
        if (fact := _layout_fact(source)) is not None:
            return fact
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
    imports = [name for name, _line, _col in _module_imports(toks)]
    cands: list[tuple[str, str, int, int]] = []
    for node in _nodes(module):
        if not isinstance(node, P.TypeRef):
            continue
        text = getattr(node, "text", "") or ""
        for chain in _parse_type_string(text) or ():
            if chain[0] in stdlib:
                continue
            line, col = lm.linecol(node.start)
            cands.append((chain[0], ".".join(chain), line, col))
        # A qualified type (`Б::Задачи.Ссылка`) does not parse as a plain chain; it is read
        # as what it is - a name with its subsystem - for the visibility rule to judge.
        if "::" in text:
            line, col = lm.linecol(node.start)
            for root, written in _qualified_roots(text):
                cands.append((root, written, line, col))
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
            if isinstance(node, P.Literal) and node.kind == "STRING":
                # The parser keeps an interpolation inside the literal, so its chains are read
                # from the text, with the same subtractions as the chains of the code.
                for offset, body in _interpolation_bodies(node.text):
                    for chain in _INTERPOLATION_CHAIN.finditer(body):
                        name = chain.group(1)
                        if (name in env or name in declared_here or name in stdlib
                                or name in _IMPLICIT):
                            continue
                        line, col = lm.linecol(node.start + offset + chain.start(1))
                        roots.append((name, f"{name}.{chain.group(2)}", line, col))
                continue
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
    """A module names a type of ANOTHER subsystem without importing its namespace - the
    compiler refuses.

    The mirror of code/unused-import, and the mirror is where the care goes: there a name that
    merely COINCIDES with an element of the imported namespace keeps the import and costs
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

    The namespace the import must name is the placement key of the element: `Б` for an element
    at the subsystem root, `Б::П` for one in a package - `импорт Б` alone does not bring the
    latter, and the message spells the line that does. An element of the module's own
    subsystem, root or package, needs no import at all.

    The narrowings of yaml/missing-import hold here too, for the same reasons: a stdlib name is
    skipped (without an import the foreign namespace is not in scope and the name resolves to
    the standard one), so is a type declared inside a module of the project, and so is a
    non-public foreign element - that one is a visibility error rather than a missing import.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
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
        place = layout.place(Path(fact["path"]))
        if place is not None:
            placement.setdefault(fact["name"], {})[place.key] = fact["vis"]
    for rel, fact in facts.items():
        if fact["k"] != "mod":
            continue
        own_keys = paired_keys.get(fact["stem"], frozenset())
        candidates_here = [(*c, "missing") for c in fact["cands"]] + [
            (*c, "chain") for c in fact.get("roots", ()) if c[0] not in own_keys
        ]
        if not candidates_here:
            continue
        my_place = layout.place(Path(fact["path"]))
        if my_place is None:
            continue  # a module outside any subsystem needs no import
        imports = {layout.local_name(name, my_place.project_dir) for name in fact["imports"]}
        reported: set[tuple[str, ...]] = set()
        for root, chain_name, line, col, shape in candidates_here:
            if root in local_types:
                continue
            candidates = _foreign_candidates(root, my_place, placement)
            if not candidates or imports.intersection(candidates):
                continue
            if candidates in reported:
                continue
            reported.add(candidates)
            yield Diagnostic(
                rel, line, col, "code/missing-import", Severity.WARNING,
                i18n.t(f"code/missing-import.{shape}", name=chain_name,
                       sub="/".join(candidates)),
                data={"namespaces": list(candidates)},
            )


# --- code/foreign-not-public --------------------------------------------------------------

MESSAGES_CODE_VISIBILITY = {
    "code/foreign-not-public.title": {
        "ru": "Обращение из кода к непубличному элементу чужой подсистемы",
        "en": "Code reference to a non-public element of another subsystem",
    },
    "code/foreign-not-public.found": {
        "ru": "Элемент '{name}' лежит в пространстве имён '{sub}' и не публичен "
              "(ОбластьВидимости: {vis}) – из модуля подсистемы '{mine}' он недоступен, "
              "компиляция упадёт на этой строке (\"Тип ... недоступен из-за модификатора "
              "видимости\"). Задайте у элемента ОбластьВидимости: ВПроекте; аннотация "
              "@ВПроекте на методе не помогает – видимость элемента старше.",
        "en": "Element '{name}' lives in namespace '{sub}' and is not public "
              "({n[ОбластьВидимости]}: {vis}) - it is unreachable from a module of subsystem "
              "'{mine}', and compilation fails at this line (\"Type ... is invisible due to "
              "visibility modifier\"). Set {n[ОбластьВидимости]}: {n[ВПроекте]} on the "
              "element; a @{n[ВПроекте]} annotation on the method does not help - the "
              "visibility of the element comes first.",
    },
    "code/foreign-not-public.root": {
        "ru": "Элемент '{name}' лежит в пространстве имён '{sub}' и не публичен "
              "(ОбластьВидимости: {vis}) – из модуля вне подсистем (модуль проекта) он "
              "недоступен, компиляция упадёт на этой строке (\"Тип ... недоступен из-за "
              "модификатора видимости\"). Задайте у элемента ОбластьВидимости: ВПроекте; "
              "аннотация @ВПроекте на методе не помогает – видимость элемента старше.",
        "en": "Element '{name}' lives in namespace '{sub}' and is not public "
              "({n[ОбластьВидимости]}: {vis}) - it is unreachable from a module outside any "
              "subsystem (the project module), and compilation fails at this line (\"Type ... "
              "is invisible due to visibility modifier\"). Set {n[ОбластьВидимости]}: "
              "{n[ВПроекте]} on the element; a @{n[ВПроекте]} annotation on the method does "
              "not help - the visibility of the element comes first.",
    },
}
i18n.register(MESSAGES_CODE_VISIBILITY)


@rule(
    "code/foreign-not-public", "code/foreign-not-public.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_missing_import_mapper,
)
def code_foreign_not_public(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """A module reaches an element of a subsystem it is not in, and the element is not public.

    The code side of yaml/foreign-not-public, split the way yaml/missing-import is split from
    code/missing-import: the markup and the module reach the element from two places, so
    they are two rules. The compiler refuses the reference at the position of the name
    (`Тип "..." недоступен из-за модификатора видимости @ВПодсистеме`); the live case was the
    project module calling a common module of a subsystem left at the default visibility, and
    the refusal arrived from the server compilation at the price of a deploy. The annotation
    on the called method does not enter into it: a method marked `@ВПроекте` inside a module
    whose element is `InSubsystem` stays unreachable, because the type of the module is what
    the compiler judges first.

    The facts are those of code/missing-import - the written type positions and the roots of
    `Модуль.Метод()` chains, with everything the module itself explains subtracted in the
    mapper - and the reduce mirrors foreign_not_public: a name the module's own subsystem
    owns (at its root or in any of its packages) resolves locally, a target that is public
    anywhere is at most a missing import (the sibling's case), a module-declared local type
    and a section of the paired yaml are not references. What this rule adds is the place
    OUTSIDE any subsystem: the project module (`Проект.xbsl`) belongs to none, so every
    non-public element is foreign to it - the live case exactly, and the place where
    code/missing-import stands down because such a module needs no import. A module outside
    the subsystems is not judged against a name that an unplaced element carries as well (a
    namesake next to it resolves nearer). A qualified `Подсистема[::Пакет]::Элемент` root - a
    type position or the root of a call - is judged by the place it names: the form needs no
    import, yet the element must be public (proven on a server build 02.09.2026, the same
    refusal at the position of the name). One diagnostic per target per module.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
    local_types: set[str] = set()
    for fact in facts.values():
        if fact["k"] == "mod":
            local_types.update(fact["local_types"])
    placement: dict[str, dict[str, object]] = {}
    unplaced: set[str] = set()  # elements that sit outside every subsystem
    paired_keys: dict[str, set[str]] = {}
    for fact in facts.values():
        if fact["k"] != "el":
            continue
        paired_keys[fact["stem"]] = set(fact["keys"])
        place = layout.place(Path(fact["path"]))
        if place is not None:
            placement.setdefault(fact["name"], {})[place.key] = fact["vis"]
        else:
            unplaced.add(fact["name"])
    for rel, fact in facts.items():
        if fact["k"] != "mod":
            continue
        own_keys = paired_keys.get(fact["stem"], frozenset())
        candidates_here = list(fact["cands"]) + [
            c for c in fact.get("roots", ()) if c[0] not in own_keys
        ]
        if not candidates_here:
            continue
        path = Path(fact["path"])
        my_place = layout.place(path)
        mine = my_place.subsystem if my_place is not None else None
        project_dir = layout.project_dir_of(path)
        reported: set[str] = set()
        for root, chain_name, line, col in candidates_here:
            if root in reported or root in local_types:
                continue
            if my_place is None and root in unplaced:
                continue
            found = _foreign_owner(root, mine, project_dir, placement, layout)
            if found is None:
                continue
            owner, vis = found
            reported.add(root)
            yield Diagnostic(
                rel, line, col, "code/foreign-not-public", Severity.ERROR,
                i18n.t(
                    "code/foreign-not-public.found" if mine else "code/foreign-not-public.root",
                    name=chain_name, sub=owner, mine=mine or "",
                    vis=vis or i18n.name(_DEFAULT_SCOPE),
                ),
                data={"namespace": owner, "name": root.rpartition("::")[2]},
            )


# --- yaml/missing-subsystem-usage -----------------------------------------------------------

#: The key of the subsystem descriptor that permits another subsystem, in the RUSSIAN spelling.
#: The English one is not guessed: the metamodel of the distribution pairs this key with `Using`
#: (class SubsystemDescriptor, annotation en=Using - the serializer's own word, the same in every
#: shipped dataset), and `Using` is the only standalone spelling the data holds at all.
_USAGE_KEY = "Использование"
#: Spellings added to whatever the data pairs, the way the library manifest adds `Vendor`
#: (libs._VENDOR_KEYS) - `extra` is what stands WITHOUT the distribution: key_forms degrades to
#: the Russian key alone on a clean public clone, and an English project would then have its
#: permission unread and every import through it reported.
#:
#: Only what the PLATFORM reads. `Usage` was named by this linter and its documentation up to
#: 0.70, but no serializer writes it and the platform does not know it: a descriptor spelled that
#: way permits nothing, so reporting it is the service - accepting it would hide a section that
#: does not work.
_USAGE_KEYS_EXTRA = ("Using",)


@lru_cache(maxsize=1)
def _usage_keys() -> tuple[str, ...]:
    """Every spelling of the permission section of a subsystem descriptor, Russian first."""
    return terms.key_forms(_USAGE_KEY, extra=_USAGE_KEYS_EXTRA)


@lru_cache(maxsize=1)
def _usage_line_re() -> re.Pattern[str]:
    """The line the diagnostic points at - the section itself, in whichever spelling."""
    return re.compile(r"(?m)^[ \t]*(?:" + "|".join(re.escape(k) for k in _usage_keys()) + r"):")


dataset.register_reset(_usage_keys.cache_clear)
dataset.register_reset(_usage_line_re.cache_clear)


def _usage_mapper(source: SourceFile) -> dict | None:
    """The map phase: a subsystem descriptor contributes what it declares as used, a project
    descriptor its place in the layout, an element or a module - the namespaces it imports."""
    if source.kind == "xbsl":
        imports = [name for name, _line, _col in _module_imports(tokens(source))]
        if not imports:
            return None
        return {"k": "imp", "path": str(source.path), "imports": imports}
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if source.path.name in _PROJECT_FILES:
        return _layout_fact(source)
    data, err = _parsed(source)
    if err is not None or not isinstance(data, dict):
        return None
    if source.path.name in _SUBSYSTEM_FILES:
        used: list[str] = []
        for key in _usage_keys():
            raw = data.get(key)
            if isinstance(raw, list):
                used.extend(e for e in raw if isinstance(e, str))
        match = _usage_line_re().search(source.text)
        line = linemap(source).linecol(match.start())[0] if match else 1
        return {
            "k": "sub",
            "dir": str(source.path.parent),
            "name": first_text(data, name_keys()) or source.path.parent.name,
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
    rather than a guess about names. An import of a package (`импорт Б::П`) is an import of
    subsystem Б for this purpose - the package lies inside it. An import of something that is
    not a subsystem of this project - a library, another project, a typo - is not this rule's
    case, the same way code/unused-import leaves it alone.

    One diagnostic per missing subsystem, on the DESCRIPTOR: that is the single line to add,
    and reporting it once there beats repeating it at every importing file. A subsystem with
    no descriptor has nowhere to declare its usage and nowhere to be reported - it is left
    alone.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
    used: dict[str, set[str]] = {}
    where: dict[str, tuple[str, int]] = {}
    for rel, fact in facts.items():
        if fact["k"] != "sub":
            continue
        used[fact["name"]] = set(fact["used"])
        where[fact["name"]] = (rel, fact["line"])
    known = set(layout.subsystem_names.values())
    counts: dict[tuple[str, str], int] = {}
    for fact in facts.values():
        if fact["k"] != "imp":
            continue
        place = layout.place(Path(fact["path"]))
        if place is None or place.subsystem not in where:
            continue  # outside any subsystem, or in one with no descriptor to declare usage
        for written in fact["imports"]:
            target = subsystem_of_key(layout.local_name(written, place.project_dir))
            if (target not in known or target == place.subsystem
                    or target in used.get(place.subsystem, ())):
                continue
            counts[(place.subsystem, target)] = counts.get((place.subsystem, target), 0) + 1
    for (my_sub, name), count in sorted(counts.items()):
        rel, line = where[my_sub]
        yield Diagnostic(
            rel, line, 1, "yaml/missing-subsystem-usage", Severity.WARNING,
            i18n.t("yaml/missing-subsystem-usage.missing", sub=name, count=count),
            data={"subsystem": my_sub, "uses": name},
        )


# --- yaml/localization-missing-import -------------------------------------------------------

MESSAGES_LOCALIZATION = {
    "yaml/localization-missing-import.title": {
        "ru": "Нет импорта подсистемы локализации в yaml",
        "en": "Missing import of a localization subsystem in yaml",
    },
    "yaml/localization-missing-import.missing": {
        "ru": "Ссылка '${ref}' берёт строку словаря подсистемы '{sub}', а секции {n[Импорт]} "
              "с этой подсистемой в ЭТОМ yaml нет – применение сборки отвергнет узел "
              "(\"Пространство имен ... с локализованными строками ... не импортировано\"); "
              "импорт в парном .xbsl разметку не покрывает. Добавьте подсистему в {n[Импорт]} "
              "либо назовите её прямо в ссылке: '${sub}::{ref}' (эта форма работает без "
              "импорта).",
        "en": "The reference '${ref}' takes a string of a dictionary of subsystem '{sub}', "
              "which the {n[Импорт]} section of THIS yaml does not list – the apply rejects "
              "the node (\"the namespace with the localized strings is not imported\"); an "
              "import in the paired .xbsl does not cover the markup. Add the subsystem to "
              "{n[Импорт]}, or name it right in the reference: '${sub}::{ref}' (that form "
              "needs no import).",
    },
}
i18n.register(MESSAGES_LOCALIZATION)

#: A dictionary reference of a yaml value: `$Словарь.Ключ`. The qualified form
#: (`$Подсистема::Словарь.Ключ`) does not match on purpose - it needs no import.
_LOCALIZATION_REF = re.compile(r"\$([^\W\d]\w*)\.([^\W\d]\w*)", re.UNICODE)
_LOCALIZATION_KIND = "ЛокализованныеСтроки"


@lru_cache(maxsize=1)
def _localization_kind_names() -> frozenset[str]:
    """Every spelling of the localized-strings kind: the serializer's vocabulary plus the
    type dictionary - with no data only the Russian spelling matches, as everywhere."""
    return frozenset({
        _LOCALIZATION_KIND,
        terms.kinds_table().get(_LOCALIZATION_KIND),
        terms.english(_LOCALIZATION_KIND, "types"),
    } - {None})


dataset.register_reset(_localization_kind_names.cache_clear)


def _localization_import_mapper(source: SourceFile) -> dict | None:
    """The map phase: a descriptor contributes its place in the layout, a localized-strings
    element its name and place, any other yaml element - its imports and the `$Словарь.Ключ`
    references it makes, with positions."""
    if source.kind != "yaml" or not _HAVE_YAML:
        return None
    if (fact := _layout_fact(source)) is not None:
        return fact
    data, err = _parsed(source)
    kind = object_kind(data)
    if err is not None or not isinstance(data, dict) or not kind:
        return None  # a translation file carries no kind - its texts are data
    if kind in _localization_kind_names():
        name = value_of(data, "Имя", kind)
        if not isinstance(name, str) or not name:
            return None
        return {
            "k": "dict",
            "path": str(source.path),
            "name": name,
            "vis": value_of(data, "ОбластьВидимости", kind),
        }
    if "$" not in source.text:
        return None
    lm = linemap(source)
    refs = [
        [m.group(1), m.group(2), *lm.linecol(m.start())]
        for m in _LOCALIZATION_REF.finditer(source.text)
    ]
    if not refs:
        return None
    raw = value_of(data, "Импорт", kind)
    imports = [e for e in raw if isinstance(e, str)] if isinstance(raw, list) else []
    return {"k": "el", "path": str(source.path), "imports": imports, "refs": refs}


@rule(
    "yaml/localization-missing-import", "yaml/localization-missing-import.title", "D",
    scope="project", severity=Severity.ERROR, mapper=_localization_import_mapper,
)
def localization_missing_import(facts: dict[str, dict]) -> Iterable[Diagnostic]:
    """An unqualified `$Словарь.Ключ` whose dictionary lives in a subsystem this yaml does
    not import - the apply refuses the node.

    The documentation ("Локализация", the collision rules) states the resolution outright:
    an unqualified reference reaches the local subsystem's dictionaries and the IMPORTED
    ones, collisions resolve in favour of the local, and a subsystem that is used but not
    imported must be named in the reference itself. An import in the paired module does not
    cover the markup - the live case that prompted the rule was exactly that shape, and the
    apply refused it with the namespace-not-imported message, so the defect costs a deploy
    cycle and a rollback.

    The narrowings mirror the sibling rules, for the same reasons: a name of the file's own
    subsystem resolves locally and is skipped, only PUBLIC foreign dictionaries are counted
    as candidates (a non-public one is a visibility problem, not an import one), a name no
    project dictionary declares is unknown rather than wrong, and the qualified reference
    form does not match the pattern at all. One diagnostic per missing subsystem per file,
    anchored at the first offending reference.
    """
    layout = _layout_from(facts)
    if not layout.known:
        return  # no descriptor at all - the project layout is unknown, nothing to judge
    owners: dict[str, dict[str, object]] = {}
    for fact in facts.values():
        if fact["k"] != "dict":
            continue
        place = layout.place(Path(fact["path"]))
        if place is not None:
            owners.setdefault(fact["name"], {})[place.key] = fact["vis"]
    if not owners:
        return
    for rel, fact in facts.items():
        if fact["k"] != "el":
            continue
        my_place = layout.place(Path(fact["path"]))
        if my_place is None:
            continue
        imports = {layout.local_name(name, my_place.project_dir) for name in fact["imports"]}
        reported: set[tuple[str, ...]] = set()
        for name, key, line, col in fact["refs"]:
            candidates = _foreign_candidates(name, my_place, owners)
            if not candidates or imports.intersection(candidates):
                continue
            if candidates in reported:
                continue
            reported.add(candidates)
            yield Diagnostic(
                rel, line, col, "yaml/localization-missing-import", Severity.ERROR,
                i18n.t("yaml/localization-missing-import.missing",
                       ref=f"{name}.{key}", sub="/".join(candidates)),
                data={"namespaces": list(candidates)},
            )
