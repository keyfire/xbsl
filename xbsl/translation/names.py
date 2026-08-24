"""Names the PROJECT declares - the gate that keeps a rename consistent.

The platform dictionaries answer a lot of ordinary words, and some of those words are what a
project called its OWN things: an enumeration value, an attribute, a method. If a
declaration is left to the project dictionary while every use of the same word is answered by
the platform tables, the two drift apart - the yaml still declares the Russian value and the
module already calls the English one, and the compiler refuses the build. That happened on the
first full pass over a real project.

So the translator collects every name the project declares and treats those names as its own:
they are translated by the project dictionary alone, and an entry that is missing leaves the
name as written EVERYWHERE (a consistent no-op) and is reported. When a project names its own
thing after a platform word, the dictionary entry usually repeats the platform spelling - which
is exactly the answer that keeps the declaration and its uses together.

Two exceptions stay with the platform: the built-in items a collection dispatches by name (the standard code, name and owner
attributes and their kin - the platform declares them, the sources only mention them) and anything a project spells in Latin already.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from xbsl import metamodel
from xbsl.lexer import tokens
from xbsl.engine import SourceFile

#: `Имя:` / `Name:` of a yaml node, any nesting (a list item dash counts as indent).
_NAME_LINE_RE = re.compile(
    r"(?m)^[ \t]*(?:-[ \t]+)?(?:Имя|Name):[ \t]*(['\"]?)([^\r\n#]*?)\1[ \t]*(?:#.*)?\r?$"
)


@lru_cache(maxsize=1)
def _builtin_item_names() -> frozenset[str]:
    """Names of the built-in collection items the metamodel dispatches by (both spellings)."""
    out: set[str] = set()
    for cls in metamodel.class_names():
        presents = metamodel.dispatch_name(cls)
        if presents:
            out.add(presents)
    from xbsl import terms

    for name in list(out):
        english = terms.common_english(name)
        if english:
            out.add(english)
    return frozenset(out)


def declared_in_yaml(source: SourceFile) -> set[str]:
    """Names a yaml file declares: every name key, minus the built-in dispatched ones."""
    if source.kind != "yaml":
        return set()
    builtin = _builtin_item_names()
    return {
        value
        for value in (m.group(2).strip() for m in _NAME_LINE_RE.finditer(source.text))
        if value and not value.isascii() and value not in builtin
    }


#: A key of a dictionary section - one indent level under the section line.
_SECTION_LINE_RE = re.compile(r"(?m)^(Строки|Шаблоны|Strings|Templates):[ \t]*\r?$")
_KEY_LINE_RE = re.compile(r"^[ \t]+([^\s:#][^:]*?):")


def declared_keys(source: SourceFile) -> set[str]:
    """Keys of a localized-strings dictionary - names the project owns just like any other.

    A key is addressed as a member (`Dictionary.Key()` in code, `$Dictionary.Key` in yaml),
    so the platform dictionary would happily answer an ordinary word and
    rename the USES while the declaration waited for an entry. Worse, two different keys can
    collapse onto one platform spelling, and the platform refuses a dictionary with a
    repeated key at apply time - a whole project rolls back over it.
    """
    if source.kind != "yaml":
        return set()
    if not _SECTION_LINE_RE.search(source.text):
        return set()
    out: set[str] = set()
    inside = False
    for line in source.text.splitlines():
        if _SECTION_LINE_RE.match(line):
            inside = True
            continue
        if inside and line and not line[:1].isspace():
            inside = False
        if not inside:
            continue
        m = _KEY_LINE_RE.match(line)
        if m:
            key = m.group(1).strip().strip("\"'")
            if key and not key.isascii():
                out.add(key)
    return out


def declared_in_module(source: SourceFile) -> set[str]:
    """Names a module declares: methods, module structures and enumerations, and their fields.

    A field of a module structure has to be here: the DECLARATION reads as a type name and the
    USE after a dot reads as a member, and the two dictionaries answer one Russian word
    differently - a field declared `Strings` was then written `Rows` at every use, and the
    compiler refused the module.

    Locals and parameters are deliberately NOT collected: a variable may be named after a TYPE
    the platform owns, and gating that word off the platform tables would leave the type
    annotation of every declaration untranslated.
    """
    return _module_declarations(source)[0]


def structure_fields(source: SourceFile) -> set[str]:
    """Field names of the module's own STRUCTURES - the other half of a json key.

    A structure reads json by field name, so a key of the project's own resource file is the
    same name written twice: once as the field, once as the data. Told apart from the rest of
    the declarations because only a field binds data - a method or an enumeration value of the
    same word says nothing about a key.
    """
    return set(_module_declarations(source)[1])


def structure_field_owners(source: SourceFile) -> dict[str, set[str]]:
    """{field name: the structures of this module that declare it}.

    The OWNER is what lets a dictionary entry speak about one structure alone
    (`JsonRoot.Услуги: Offerings`): the fields of one structure share a namespace, so two
    Russian words translated into one English word make a structure the compiler refuses,
    and the only cure that does not touch the Russian source is a qualified entry.
    """
    return _module_declarations(source)[1]


def _module_declarations(source: SourceFile) -> tuple[set[str], dict[str, set[str]]]:
    """(every name the module declares, {structure field: the structures declaring it})."""
    if source.kind != "xbsl":
        return set(), {}
    out: set[str] = set()
    fields: dict[str, set[str]] = {}
    toks = tokens(source)
    inside_declaration = False
    inside_structure = False
    structure_name = ""
    for index, tok in enumerate(toks):
        if tok.kind == "KEYWORD" and tok.canonical in ("METHOD", "CONSTRUCTOR"):
            inside_declaration = False
            inside_structure = False
            structure_name = ""
            _add_next_name(toks, index, out)
        elif tok.kind == "KEYWORD" and tok.canonical in ("STRUCTURE", "ENUMERATION"):
            inside_declaration = True
            inside_structure = tok.canonical == "STRUCTURE"
            structure_name = _next_name(toks, index) if inside_structure else ""
            _add_next_name(toks, index, out)
        elif tok.kind == "OP" and tok.value == ";":
            inside_declaration = False
            inside_structure = False
            structure_name = ""
        elif inside_declaration and tok.kind == "KEYWORD" and tok.canonical in ("VAR", "VAL", "REQ"):
            # `req var Rows: ...` - the modifiers may stack, so the name is the next IDENT.
            _add_next_name(toks, index, out, skip_keywords=True)
            if inside_structure:
                name = _next_name(toks, index, skip_keywords=True)
                if name:
                    fields.setdefault(name, set()).add(structure_name)
        elif inside_declaration and tok.kind == "IDENT" and not tok.value.isascii():
            # A value of a module enumeration stands ALONE on its line, with no modifier and no
            # type after it. The line test is what keeps the TYPE of a field out: `var Rows:
            # Array<String>` puts Array and String on the same line as the field.
            nxt = toks[index + 1] if index + 1 < len(toks) else None
            prev = toks[index - 1] if index else None
            starts_line = prev is None or prev.line != tok.line
            ends_line = nxt is None or nxt.line != tok.line
            if starts_line and ends_line:
                out.add(tok.value)
    return out, fields


def _add_next_name(toks: list, index: int, out: set[str], skip_keywords: bool = False) -> None:
    """Add the identifier that follows the token at `index`, skipping stacked modifiers."""
    name = _next_name(toks, index, skip_keywords)
    if name:
        out.add(name)


def _next_name(toks: list, index: int, skip_keywords: bool = False) -> str:
    """The declared name after the token at `index` - "" when the next token is not one.

    Only a name with Cyrillic in it counts: an English one is already written the way the
    translated project spells it, and nothing here has anything to say about it.
    """
    position = index + 1
    while position < len(toks):
        tok = toks[position]
        if skip_keywords and tok.kind == "KEYWORD" and tok.canonical in ("VAR", "VAL", "REQ"):
            position += 1
            continue
        return tok.value if tok.kind == "IDENT" and not tok.value.isascii() else ""
    return ""


def declared(source: SourceFile) -> set[str]:
    """Names this source declares in the PROJECT-WIDE namespace (yaml names, module methods).

    Dictionary keys are deliberately left out: a key lives in its own namespace, and mixing it
    into the global set would let its translation reach a same-named standard attribute (a key
    "Наименование" is a caption, the attribute is the platform's `Name`). Keys are collected
    separately by `dictionary_scopes`.
    """
    return declared_in_yaml(source) | declared_in_module(source)


_LOCALIZED_KIND_RE = re.compile(
    r"(?m)^(?:ВидЭлемента|ElementKind):[ \t]*(ЛокализованныеСтроки|LocalizedStrings)[ \t]*\r?$"
)


_COMPONENT_KIND_RE = re.compile(
    r"(?m)^(?:ВидЭлемента|ElementKind):[ \t]*(КомпонентИнтерфейса|InterfaceComponent)[ \t]*\r?$"
)


def component_names(root: Path, loader) -> frozenset[str]:
    """Names of the NODES of the project's forms - what `Components.<Name>` addresses.

    Told apart from the rest on purpose: a node name is the project's word even when the ui
    vocabulary knows it (a node called "Возможности" is not the platform property of that
    name), while a built-in command of a component keeps the platform spelling even when the
    project declares a method of the same name somewhere else.
    """
    out: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            source = loader(path)
        except OSError:
            continue
        if not _COMPONENT_KIND_RE.search(source.text):
            continue
        out |= declared_in_yaml(source)
    return frozenset(out)


def dictionary_scopes(root: Path, loader) -> frozenset[str]:
    """Names of the localized-strings elements of a project - the namespaces of their keys.

    A name after a dot whose root is one of these is a dictionary KEY: it is the project's own
    word in that namespace alone, and the platform tables must not answer for it.
    """
    out: set[str] = set()
    for path in sorted(root.rglob("*.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            source = loader(path)
        except OSError:
            continue
        if not _LOCALIZED_KIND_RE.search(source.text):
            continue
        for name in declared_in_yaml(source):
            if name == path.stem:
                out.add(name)
                break
    return frozenset(out)


def collect_structure_fields(root: Path, loader) -> dict[str, str]:
    """{field name: its structure} for every structure the project declares.

    The owner is named only where it is UNAMBIGUOUS - one structure of the whole project
    declares a field spelled that way. Where several do, it is empty: a json key names a
    field by text alone, and picking one of two owners for it would be a guess.
    """
    owners: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.xbsl")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            found = structure_field_owners(loader(path))
        except OSError:
            continue
        for field, group in found.items():
            owners.setdefault(field, set()).update(group)
    return {
        field: next(iter(group)) if len(group) == 1 else ""
        for field, group in owners.items()
    }


def collect(root: Path, loader) -> frozenset[str]:
    """Every name declared under the project root, using the given file loader."""
    out: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".yaml", ".xbsl", ".xbql"):
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            out |= declared(loader(path))
        except OSError:
            continue
    return frozenset(out)
