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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from xbsl import libs, metamodel
from xbsl.lexer import tokens
from xbsl.engine import SourceFile
from xbsl.restext import RESOURCE_DIRS
from xbsl.rules.yaml_schema import _parsed, object_kind, value_of

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


def declared_types(source: SourceFile) -> set[str]:
    """Names this source declares as a TYPE: the element a yaml describes, the structures,
    exceptions and enumerations of a module.

    Told apart from the rest of the declarations because a type is the one thing a project
    can name after a platform type and mean by that name wherever a type stands. A field, an
    attribute, a method or a property spelled like a platform type is never what a type
    expression names: `Пользователи.Ссылка` is the platform's users catalog even in a project
    whose structure has a field spelled like the catalog.
    """
    if source.kind == "yaml":
        data, error = _parsed(source)
        kind = object_kind(data) if error is None else None
        if not kind:
            return set()
        name = value_of(data, "Имя", kind)
        return {name} if isinstance(name, str) and name and not name.isascii() else set()
    if source.kind != "xbsl":
        return set()
    out: set[str] = set()
    toks = tokens(source)
    for index, tok in enumerate(toks[:-1]):
        if tok.kind != "KEYWORD" or tok.canonical not in ("STRUCTURE", "ENUMERATION", "EXCEPTION"):
            continue
        prev = toks[index - 1] if index else None
        name = toks[index + 1]
        # A declaration opens its line and names the type on the same line; the keyword
        # elsewhere is a type word in an expression (`поймать Ошибка: Исключение`), and the
        # name on the next line has nothing to do with it.
        if prev is not None and prev.line == tok.line:
            continue
        if name.kind == "IDENT" and name.line == tok.line and not name.value.isascii():
            out.add(name.value)
    return out


def collect_types(root: Path, loader) -> frozenset[str]:
    """Every TYPE name declared under the project root (see declared_types)."""
    out: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in (".yaml", ".xbsl"):
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            out |= declared_types(loader(path))
        except OSError:
            continue
    return frozenset(out)


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


def component_types(root: Path, loader) -> frozenset[str]:
    """Names and exact local qualifications of interface components the project declares.

    Unlike `component_names`, this set contains no node, property or method names from inside
    the component. A qualification is added only under this project's coordinates and the
    component's relative namespace. An external platform or library type with the same final
    segment therefore remains external.
    """
    out: set[str] = set()
    coordinates = _project_coordinates(root, loader)
    for path in sorted(root.rglob("*.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            source = loader(path)
        except OSError:
            continue
        data, error = _parsed(source)
        kind = object_kind(data) if error is None else None
        if kind != "КомпонентИнтерфейса":
            continue
        name = value_of(data, "Имя", kind)
        if isinstance(name, str) and name:
            out.add(name)
            namespace = path.parent.relative_to(root).parts
            if namespace:
                out.add("::".join((*namespace, name)))
            if coordinates:
                out.add("::".join((*coordinates, *namespace, name)))
    return frozenset(out)


def _project_coordinates(root: Path, loader) -> tuple[str, str] | None:
    """Coordinates that prefix a fully qualified local type.

    The descriptor is authoritative. A fragment translated without one still follows the
    repository layout accepted elsewhere: its project directory sits below the vendor.
    """
    for filename in ("Проект.yaml", "Project.yaml"):
        descriptor = root / filename
        if not descriptor.is_file():
            continue
        try:
            found = libs.project_coordinates(loader(descriptor).text)
        except OSError:
            continue
        if found is not None:
            return found
    if root.name and root.parent.name:
        return root.parent.name, root.name
    return None


def resource_keys(root: Path) -> frozenset[str]:
    """Every file below a folder of resources of the project as a reference addresses it - the
    path relative to that folder - and every folder on the way: `Значки`, `Значки/Флаг.svg`.

    A reference to a name outside this set is not a file of the project. The platform ships a
    library of pictures a project may name the same way (`Время.svg`), and those carry names
    of their own in each language; the project dictionary has nothing to say about them.
    """
    out: set[str] = set()
    for folder in (path for name in RESOURCE_DIRS for path in root.rglob(name)):
        hidden = any(part.startswith(".") for part in folder.relative_to(root).parts)
        if hidden or not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(folder).parts
            for end in range(1, len(parts) + 1):
                out.add("/".join(parts[:end]))
    return frozenset(out)


def component_methods(root: Path, loader) -> dict[str, frozenset[str]]:
    """{interface component of the project: the methods its module declares}.

    What a form calls on a node of such a component (`Компоненты.<Node>.<Method>()`) is then
    told apart from a built-in command of a platform component spelled the same way: a
    component of the project declared a method spelled like the refresh command, and the call
    took the platform's `Refresh` while the declaration waited for a dictionary entry.
    """
    out: dict[str, frozenset[str]] = {}
    for path in sorted(root.rglob("*.yaml")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        module = path.with_suffix(".xbsl")
        if not module.is_file():
            continue
        try:
            source = loader(path)
        except OSError:
            continue
        if not _COMPONENT_KIND_RE.search(source.text):
            continue
        data, error = _parsed(source)
        name = value_of(data, "Имя", object_kind(data)) if error is None else None
        if not isinstance(name, str) or not name:
            continue
        try:
            toks = tokens(loader(module))
        except OSError:
            continue
        out[name] = frozenset(
            toks[index + 1].value
            for index, tok in enumerate(toks[:-1])
            if tok.kind == "KEYWORD" and tok.canonical == "METHOD"
            and toks[index + 1].kind == "IDENT"
        )
    return out


def form_nodes(path: Path, loader) -> dict[str, str]:
    """{node name: the component its node is} of the component tree the module at `path` pairs with.

    The type is the one the node names - its head, without the namespace and the type
    arguments. A module that pairs with no interface component has no nodes.
    """
    if not path.name.endswith(".xbsl"):
        return {}
    pair = path.with_name(f"{path.name[: -len('.xbsl')]}.yaml")
    if not pair.is_file():
        return {}
    try:
        data, error = _parsed(loader(pair))
    except OSError:
        return {}
    if error is not None or object_kind(data) != _COMPONENT_KIND:
        return {}
    out: dict[str, str] = {}

    def walk(node: object) -> None:
        if isinstance(node, dict):
            name = node.get("Имя", node.get("Name"))
            kind = node.get("Тип", node.get("Type"))
            if isinstance(name, str) and isinstance(kind, str):
                out.setdefault(name, kind.split("<", 1)[0].rsplit("::", 1)[-1].strip())
            for key, value in node.items():
                # A declared property names a TYPE too, and it is not a node of the tree.
                if key not in ("Свойства", "Properties"):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return out


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


#: The element kinds whose OBJECT module works on the record: the attributes and the tabular
#: sections of the element are bare names in every method of that module.
_RECORD_KINDS = frozenset(("Справочник", "Документ", "Обработка"))
_RECORD_SECTIONS = ("Реквизиты", "ТабличныеЧасти")
_COMPONENT_KIND = "КомпонентИнтерфейса"
_STRUCTURE_KIND = "Структура"
#: The tail of an object module, in both spellings the platform accepts
#: (`Задачи.Объект.xbsl`, `Tasks.Object.xbsl`); either pairs with the yaml of the element.
_OBJECT_MODULE_TAILS = (".Объект", ".Object")


@dataclass(frozen=True)
class ModuleOwner:
    """The names the element of a module puts in scope of that module's methods.

    A method of an interface component works on the component, and its own properties are bare
    names there; so are the attributes and the tabular sections of the record in the object
    module of a catalog, a document or a processing, and the fields in the module of a
    structure element. Such a name may be spelled like a platform type, and then `Имя.Член`
    reads the property, not the type - the translator has to know that, or the uses of the
    property take the type's spelling while its declaration takes the dictionary's.

    Only the names the PROJECT declares are here: an inherited property is a platform word and
    reads the same either way. Two methods see less. A static method has no instance at all, and
    a method a component compiles on the server alone works on the CONTEXT of the component,
    which holds only the properties marked contextual - `contextual` lists those, and stays None
    for an owner that is not a component.
    """

    names: frozenset[str] = frozenset()
    contextual: frozenset[str] | None = None

    def visible(self, *, static: bool, server_only: bool) -> frozenset[str]:
        """The names a method of the module sees: none for a static one, fewer on the server."""
        if static:
            return frozenset()
        if server_only and self.contextual is not None:
            return self.contextual
        return self.names


def _item_names(data: dict, section: str, kind: str) -> list[tuple[str, dict]]:
    """(name, item) of every named item of a yaml list section."""
    items = value_of(data, section, kind)
    if not isinstance(items, list):
        return []
    out: list[tuple[str, dict]] = []
    for item in items:
        name = value_of(item, "Имя") if isinstance(item, dict) else None
        if isinstance(name, str) and name:
            out.append((name, item))
    return out


def _is_true(value: object) -> bool:
    """A yaml flag written either way: the Russian spelling of `True` loads as a string."""
    return value is True or value in ("Истина", "True", "true")


def module_owner(path: Path, loader) -> ModuleOwner:
    """The owner of the module at `path`, read off the yaml it pairs with; empty when none.

    `Имя.xbsl` pairs with `Имя.yaml` and speaks for an interface component or a structure
    element; `Имя.Объект.xbsl` pairs with the same yaml and speaks for the record of a catalog,
    a document or a processing. Any other module - a common module, the manager module of a
    catalog - has no instance to work on, and its owner is empty.
    """
    stem = path.name[: -len(".xbsl")] if path.name.endswith(".xbsl") else ""
    if not stem:
        return ModuleOwner()
    facet = next((tail for tail in _OBJECT_MODULE_TAILS if stem.endswith(tail)), "")
    pair = path.with_name(f"{stem[: len(stem) - len(facet)]}.yaml")
    if not pair.is_file():
        return ModuleOwner()
    try:
        data, error = _parsed(loader(pair))
    except OSError:
        return ModuleOwner()
    kind = object_kind(data) if error is None else None
    if not kind:
        return ModuleOwner()
    if facet:
        if kind not in _RECORD_KINDS:
            return ModuleOwner()
        return ModuleOwner(frozenset(
            name for section in _RECORD_SECTIONS for name, _item in _item_names(data, section, kind)
        ))
    if kind == _COMPONENT_KIND:
        properties = _item_names(data, "Свойства", kind)
        contextual = (name for name, item in properties if _is_true(value_of(item, "Контекстное")))
        return ModuleOwner(frozenset(name for name, _item in properties), frozenset(contextual))
    if kind == _STRUCTURE_KIND:
        return ModuleOwner(frozenset(name for name, _item in _item_names(data, "Поля", kind)))
    return ModuleOwner()


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
