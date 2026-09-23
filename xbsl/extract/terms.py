#!/usr/bin/env python3
"""Extract the Russian<->English term pairs of 1C:Element from the distribution.

The platform is bilingual: a type is `Запрос` and `Query`, a yaml key is `ОбластьВидимости`
and `VisibilityScope`, an enumeration value is `ВПроекте` and `InProject`. Sources are written
in either language, and so is documentation about them - but the pairing itself is nowhere in
one place, which is why the engine used to carry a few hand-written tuples (and one of them,
"VisibilityArea", matched nothing at all).

Every pair here comes from the distribution, never from a translation:

- types and facets - the documentation page carries the Russian name in <title> and the
  English one in its path segment (`.../Query_ru/index.html`), the same pairing extract_stdlib
  relies on;
- yaml properties - the EMF metamodel annotates them `@PropertyInfo(ru="Имя", en="Name")`;
- enumeration values - the metamodel declares them `InProject as "ВПроекте"`;
- members of every stdlib type - the distribution states them itself. The two
  documentation-and-xcore sources above are thin: a great many names carry no `en` in the
  metamodel at all (`@PropertyInfo(ru="Реквизиты")`), which used to read as "the platform has
  no English name for this" - and that was wrong. Reading what the distribution declares
  yields thousands of pairs the other sources never see (Реквизиты/Attributes,
  ТабличныеЧасти/TabularParts, СоздатьОбъект/CreateObject).

Keywords are NOT duplicated here: language.json already stores every form of each keyword.

The result is xbsl/data/element/<version>/terms.json:
    { "types": {ru: en}, "facets": {ru: en}, "properties": {ru: en}, "enums": {ru: en},
      "members": {en type: {ru: en}}, "common": {ru: en} }

`members` keeps the owner, because a word may be translated differently depending on where it
sits (`Ссылка` is `Reference` on a data-object facet and `Link` on a navigation property);
`common` holds only the names whose English spelling is unambiguous across the distribution.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import struct
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from xbsl.extract import _distro, classcode

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
# Nested jar plugins that carry the .xcore metamodel (same set as extract_metamodel).
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_PROP_RE = re.compile(r"@PropertyInfo\d?\(([^)]*)\)")
_RU_RE = re.compile(r"\bru\s*=\s*\"([^\"]+)\"")
_EN_RE = re.compile(r"\ben\s*=\s*\"([^\"]+)\"")
# `InProject as "ВПроекте"` - an enumeration literal with its Russian spelling.
_ENUM_RE = re.compile(r"(\w+)\s+as\s+\"([А-ЯЁ][А-Яа-яЁё0-9_]*)\"")
_NAME_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_]*$")


def _path_name(entry: str) -> str | None:
    """The English name from a `.../<Name>_ru/index.html` documentation path."""
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    return dirname[:-3] or None if dirname.endswith("_ru") else None


def _add(target: dict[str, str], ru: str, en: str, conflicts: set[str]) -> None:
    """Record a pair; a name that claims two different English spellings is dropped.

    A conflict means the word is used in more than one role (`Ссылка` is a property `Link`
    and a facet `Reference`), and a single mapping would be wrong in one of them.
    """
    if ru == en:
        return
    known = target.get(ru)
    if known is None:
        target[ru] = en
    elif known != en:
        conflicts.add(ru)


#: Classes that describe a type: the file name without this suffix is its English name.
_META_SUFFIX = re.compile(r"(CtMetaObject|MetaObject|BslImpl)$")
#: A class states its members only if it calls one of the builders that take the pair;
#: the test is a substring of the compiled reference, cheap enough to run on every class
#: and far cheaper than walking the bytecode of one that declares nothing.
_DECLARES_MEMBERS_RE = re.compile(rb"CtMeta(Method|Prop)Builder")
#: A class states TERMS - a type and its members as pairs stored into named static fields
#: (classcode.declared_terms) - only if it references one of the term factories.
_DECLARES_TERMS_RE = re.compile(rb"Term|QNames")
#: Jars of the platform itself - the only ones that can hold such classes.
_PLATFORM_JAR_RE = re.compile(r"g5rt|_1c")
_EN_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
#: The Russian side of a pair may be MIXED: the platform spells `HttpService`, `FtpSource`,
#: `SeoDescription` and `AppletTags` with the Latin prefix kept and only the tail in Russian,
#: so such a name STARTS with a Latin letter. What makes it the Russian side is a Cyrillic
#: letter somewhere in it (checked separately), not the first one; demanding a Cyrillic head
#: cost 354 member names their English spelling, every one of this shape. The kind table below
#: always read them this way - the member scan simply never followed.
_RU_NAME_RE = re.compile(r"^[A-Za-zА-ЯЁ][A-Za-zА-Яа-яЁё0-9_]*$")
#: How many times the leading spelling must beat the runner-up to be taken as unambiguous.
_DOMINANCE = 3
#: Names the JVM itself puts in every constant pool. They look exactly like an English name
#: and stand wherever the class file needs them, so a Cyrillic string that happens to follow
#: one used to be "translated" by it - that is how the html document type came out as
#: `BootstrapMethods` and one more name as `Deprecated`. The platform never names anything this
#: way, so the whole set is barred from the English side of a pair.
_CLASS_FILE_NAMES = frozenset({
    "AnnotationDefault", "BootstrapMethods", "Code", "ConstantValue", "Deprecated",
    "EnclosingMethod", "Exceptions", "InnerClasses", "LineNumberTable", "LocalVariableTable",
    "LocalVariableTypeTable", "MethodParameters", "Module", "ModuleMainClass",
    "ModulePackages", "NestHost", "NestMembers", "PermittedSubclasses", "Record",
    "RuntimeInvisibleAnnotations", "RuntimeInvisibleParameterAnnotations",
    "RuntimeInvisibleTypeAnnotations", "RuntimeVisibleAnnotations",
    "RuntimeVisibleParameterAnnotations", "RuntimeVisibleTypeAnnotations", "Signature",
    "SourceDebugExtension", "SourceFile", "StackMapTable", "Synthetic",
})


def _constant_pool(data: bytes) -> list[str]:
    """The UTF8 entries of a class constant pool, in index order.

    Only the strings are needed, so the other entry kinds are skipped by their fixed sizes
    (long and double take two pool slots - the quirk the `num += 1` accounts for).
    """
    count = struct.unpack_from(">H", data, 8)[0]
    out: dict[int, str] = {}
    i, num = 10, 1
    while num < count and i < len(data):
        tag = data[i]
        if tag == 1:
            length = struct.unpack_from(">H", data, i + 1)[0]
            out[num] = data[i + 3:i + 3 + length].decode("utf-8", "replace")
            i += 3 + length
        elif tag in (7, 8, 16, 19, 20):
            i += 3
        elif tag == 15:
            i += 4
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            i += 5
        elif tag in (5, 6):
            i += 9
            num += 1
        else:
            i += 1
        num += 1
    return [out[key] for key in sorted(out)]


#: A class that may state the pair of a TYPE - the same shapes extract_stdlib reads the
#: undocumented types from. Other classes store terms too, and a term is not a type because
#: a class happens to be named after it: `NameGenerator` stores the `Name` of a yaml key,
#: `CodeAttributeMetadata` the `Code` of an attribute, `ValueTerms` the query keyword `Value`.
_TYPE_CLASS_RE = re.compile(r"(Constants|G5Type|G5Enum|CtMetaObject)$")
#: The static field a type class stores its OWN term into. A Constants class also stores the
#: element KIND it serves (`PROJECT_ELEMENT_KIND_TERM` - `CommonModule`, `Structure`), and a
#: kind is not a type: only a field named for a type, or for the type itself (the English
#: name in upper snake case plus `_TERM`), states one.
_TYPE_FIELD_RE = re.compile(r"^(TYPE_NAME|TYPE_TERM|.*_TYPE_TERM)$")
_SNAKE_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _is_type_field(field: str, english: str) -> bool:
    return bool(_TYPE_FIELD_RE.match(field)) or field == _SNAKE_RE.sub("_", english).upper() + "_TERM"


def _is_term_pair(en: str, ru: str) -> bool:
    """Whether a stated term is a spelling pair: an English name against a Russian one."""
    return bool(_EN_NAME_RE.match(en) and _RU_NAME_RE.match(ru) and _CYRILLIC_RE.search(ru))


def _declared_type(
    simple: str, blob: bytes, found: list[tuple[str, str, str]] | None = None,
) -> tuple[str, str, dict[str, str]] | None:
    """(English type, Russian type, {Russian member: English}) a class states as TERMS, or None.

    A `<Type>Constants` class stores the type's own term and one term per member into named
    static fields; a `<Type>G5Type` class stores the type's term alone. The type is the term
    the class is NAMED AFTER - its English spelling is a prefix of the class name
    (`UserFavoritesItem` for `UserFavoritesItemConstants`), stored in a field that says it
    is the type's own (see _is_type_field); the longest such when several fit. A class of
    another shape, or one named after no type term it states, declares no type here. The
    members are the fields whose suffix says they are one (a property, a method, an event):
    a parameter term and the namespace term are neither.

    Filed under the class name, as every other class is, these pairs answered no receiver a
    program writes: no variable is of the type `UserFavoritesItemConstants`, and the link
    property of a favorites item stayed `Reference` where the platform says `Link`.
    """
    if not _TYPE_CLASS_RE.search(simple):
        return None
    if found is None:
        found = classcode.declared_terms(blob)
    if not found:
        return None
    named = [
        (en, ru) for field, en, ru in found
        if _is_term_pair(en, ru) and simple.startswith(en) and _is_type_field(field, en)
    ]
    if not named:
        return None
    english, russian = max(named, key=lambda pair: len(pair[0]))
    members = {
        ru: en for field, en, ru in found
        if field.endswith(classcode.MEMBER_TERM_SUFFIXES) and _is_term_pair(en, ru)
    }
    return english, russian, members


def _dominant(counter: Counter) -> str | None:
    """The spelling a counter settles on, or None when two of them are too close to call."""
    ranked = counter.most_common(2)
    best, best_n = ranked[0]
    if len(ranked) == 1 or best_n >= ranked[1][1] * _DOMINANCE:
        return best
    return None


@dataclass
class ManagerEvidence:
    """What the compiled classes say about the metaobjects built for elements of a project.

    `constructed` - the metaobject classes (`<Name>CtMetaObject`) a class of the compiler
    constructs from a project type, the type the compiler gives one element of a project;
    `stated` - {such a class: {Russian member: English}} of the terms its own code builds.
    Filled by _scan_meta_objects, judged by manager_owners.

    Both are keyed by the FULL internal name of the class, package and all. Kept by the simple
    name, two namesakes in different packages were one row: the first one met decided what the
    pair "states", and a class that states nothing could be joined to a kind on the terms of a
    namesake nothing constructs.
    """

    constructed: set[str] = field(default_factory=set)
    stated: dict[str, dict[str, str]] = field(default_factory=dict)


#: The suffix of a compile-time metaobject class and of the type of one element of a project.
_CT_META_SUFFIX = "CtMetaObject"
_PROJECT_TYPE_ARGUMENT_RE = re.compile(r"L[\w/$]+G5ProjectType;")


def _note_manager_evidence(managers: ManagerEvidence, class_name: str, data: bytes) -> None:
    """Record what the class `class_name` (full internal name) says about project metaobjects."""
    if b"G5ProjectType" in data and _CT_META_SUFFIX.encode() in data:
        for built, descriptor in classcode.constructions(data):
            parameters = descriptor.partition(")")[0]
            if built.endswith(_CT_META_SUFFIX) and _PROJECT_TYPE_ARGUMENT_RE.search(parameters):
                managers.constructed.add(built)
    if not class_name.endswith(_CT_META_SUFFIX) or class_name in managers.stated:
        return
    stated: dict[str, str] = {}
    for called, pushed in classcode.builder_calls(data):
        if len(pushed) < 2:
            continue
        if not any(called.endswith(factory) for factory in classcode.TERM_FACTORIES):
            continue
        english, russian = pushed[-2], pushed[-1]
        if _is_term_pair(english, russian):
            stated[russian] = english
    managers.stated[class_name] = stated


def _scan_meta_objects(
    car: zipfile.ZipFile, managers: ManagerEvidence | None = None,
) -> tuple[dict[str, dict[str, str]], dict[str, str], dict[str, str]]:
    """({owner type: {ru: en}}, {ru: en}, {ru type: en type}) from the compiled classes.

    The third table is the types the classes DECLARE as terms (see _declared_type) - the
    pairs of the types the reference pages never describe. The flat table is the
    neighbourhood's, and the terms the classes state answer where it settled nothing.
    `managers`, when given, collects on the same walk what manager_owners needs.

    A class without a single Cyrillic byte cannot hold a pair and is skipped before parsing -
    that check alone drops the overwhelming majority of the classes. The classes that construct
    the metaobjects hold no pair and are read before that check.
    """
    members: dict[str, dict[str, str]] = defaultdict(dict)
    variants: dict[str, Counter] = defaultdict(Counter)
    stated_variants: dict[str, Counter] = defaultdict(Counter)
    declared_types: dict[str, str] = {}
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            if not inner.endswith(".class"):
                continue
            try:
                data = jar.read(inner)
            except (zipfile.BadZipFile, KeyError):
                continue
            if managers is not None:
                _note_manager_evidence(managers, inner[:-len(".class")], data)
            if b"\xd0" not in data and b"\xd1" not in data:
                continue
            strings = _constant_pool(data)
            pairs = [
                (en, ru) for en, ru in zip(strings, strings[1:])
                if _EN_NAME_RE.match(en) and en not in _CLASS_FILE_NAMES
                and _RU_NAME_RE.match(ru) and _CYRILLIC_RE.search(ru)
            ]
            if inner == _QUERY_TERMS_CLASS:
                # In the query parser's own class a keyword the platform has NO English
                # spelling for is followed by a transliteration of itself, and adjacency reads
                # that as the next keyword's English. The function names of the same class are
                # paired correctly, so only the keywords named here are dropped.
                names = [
                    s for s in strings if _QUERY_EN_RE.match(s) or _QUERY_RU_RE.match(s)
                ]
                without = _query_untranslated(names)
                pairs = [(en, ru) for en, ru in pairs if ru not in without]
            simple = inner.rsplit("/", 1)[-1][:-len(".class")]
            found = classcode.declared_terms(data) if _DECLARES_TERMS_RE.search(data) else []
            stated = _declared_type(simple, data, found) if found else None
            if not pairs and not found:
                continue
            owner = _META_SUFFIX.sub("", simple)
            # A class STATES its members, and a statement beats the neighbourhood: adjacency
            # named 2 of 2015 members wrongly, both confidently - the `CharAt` of a `String`
            # came out `Symbol`, which is the fill PARAMETER of `PadFromBegin`. Read only
            # where such declarations are actually made.
            declared = classcode.declared_members(data) if _DECLARES_MEMBERS_RE.search(data) else {}
            resolved = {ru: en for en, ru in pairs}
            resolved.update(declared)
            for ru, en in resolved.items():
                members[owner][ru] = en
                variants[ru][en] += 1
            # A TERM a class states is a spelling the platform wrote down itself. It is counted
            # apart from the neighbourhood - once per class and pair - and answers only where
            # the neighbourhood settled nothing (see below): a class states its OWN vocabulary,
            # and mixed into the flat count the statements of a dozen classes broke the
            # dominance of fifteen settled words. The gap it exists for: the built-in code
            # attribute had no common spelling - a dozen classes state the term `Code`, and
            # adjacency reads none of them, because `Code` also names a class-file attribute
            # and is refused as an English candidate on that ground; the two declarations that
            # do name it are outweighed by one neighbour reading the class name instead.
            for en, ru in {(en, ru) for _field, en, ru in found if _is_term_pair(en, ru)}:
                if resolved.get(ru) != en:
                    stated_variants[ru][en] += 1
            if stated:
                # The members a class states as TERMS are the TYPE's, filed under the type
                # the class is named after - the row a receiver of that type is looked up by.
                # Only the stated pairs move there: the neighbourhood reading of the same class
                # stays under the class name, so no adjacency noise reaches a row that answers.
                # The pairs were counted above; a second count would tilt the common table.
                english, russian, term_members = stated
                declared_types.setdefault(russian, english)
                for ru, en in term_members.items():
                    members[english][ru] = en
    common: dict[str, str] = {}
    for ru, counter in variants.items():
        best = _dominant(counter)
        if best:
            common[ru] = best
    # The statements answer where the neighbourhood settled nothing: a word it never met, or
    # one it left between two spellings. A word it settled keeps its spelling.
    for ru, counter in stated_variants.items():
        if ru in common:
            continue
        best = _dominant(counter)
        if best:
            common[ru] = best
    return (
        {owner: dict(sorted(names.items())) for owner, names in sorted(members.items())},
        # Sorted like its neighbours above and below: `common` is filed in SCAN order (as a
        # class of the distribution happens to be read), and terms_full.json wrote it that way
        # verbatim - a re-extraction that changed no spelling still moved hundreds of unrelated
        # lines, because the scan order of the same distribution is not the alphabet.
        dict(sorted(common.items())),
        dict(sorted(declared_types.items())),
    )


def manager_owners(
    car: zipfile.ZipFile, members: dict[str, dict[str, str]], managers: ManagerEvidence,
) -> dict[str, str]:
    """{Russian element kind: the owner of `members` that spells the manager of that kind}.

    A project names an element and calls the methods of its manager on the name:
    `ПравоНаОтчеты.Проверить()`. The pair of such a method is in the members table, but
    under the class of the compiler that builds the manager (`PrivilegeOnActionManager`), and
    nothing else in the data joins that class to the kind. The kind's own name does not lead
    there: the manager of a catalog is not the only class named after a catalog, and the
    manager of a privilege on action is built by the environment of the access keys, which picks
    it by a flag of the project type - no rule of names reads that.

    So the join is stated only where three sources of the distribution say the same thing:
    - the compiler builds the metaobject class from the project type of an element (a class
      constructs it with such a type among the arguments of the constructor);
    - the class builds the terms of the manager's members itself;
    - the template of the kind documents exactly those members: the Russian names in the
      help page of the template (`<Kind>Name_ru`), the English ones in the language-server
      page of the same template, which the compiler generated from the template project.
    The members row of the owner must hold those pairs and nothing else - the runtime answers
    from the whole row. A kind two classes fit, or a class two kinds fit, is left out: the
    manager is then not proven, and the call stays the gap it was.
    """
    from xbsl.extract import stdlib  # the template pages and their kinds are read there

    kinds, _unmapped = stdlib._template_kinds(car)
    entries = set(car.namelist())
    markdown = _template_markdown_pages(car)
    owners_of_kind: dict[str, set[str]] = {}
    kinds_of_owner: dict[str, set[str]] = {}
    for template, kind in sorted(kinds.items()):
        page = f"{stdlib.TEMPLATE_BASE}{template}_ru/index.html"
        if page not in entries or template not in markdown:
            continue
        # The reader of the stdlib step: control characters out, the markup brought to form.
        props, methods, events = stdlib.page_members(stdlib._page(car, page), inherited=False)
        russian = props | methods | events
        english = _template_markdown_members(markdown[template], template)
        if not russian or not english:
            continue
        for class_name in sorted(managers.constructed):
            stated = managers.stated.get(class_name) or {}
            owner = _META_SUFFIX.sub("", class_name.rsplit("/", 1)[-1])
            if (stated and set(stated) == russian and set(stated.values()) == english
                    and members.get(owner) == stated):
                owners_of_kind.setdefault(kind, set()).add(owner)
                kinds_of_owner.setdefault(owner, set()).add(kind)
    out: dict[str, str] = {}
    for kind, found in sorted(owners_of_kind.items()):
        owner = next(iter(found))
        if len(found) == 1 and len(kinds_of_owner[owner]) == 1:
            out[kind] = owner
    return out


def _template_parts() -> list[str]:
    """`DeveloperName`, `ProjectName`, `SubsystemName` - where the templates of the kinds live."""
    from xbsl.extract import stdlib

    return stdlib.TEMPLATE_BASE.rstrip("/").split("/")[-3:]


def _template_markdown_pages(car: zipfile.ZipFile) -> dict[str, str]:
    """{template: the language-server page of its own type} (`PrivilegeOnActionName`)."""
    from xbsl.extract import stdlib

    prefix = stdlib.LSP_DOCS_BASE + "_".join(_template_parts()) + "_"
    pages: dict[str, str] = {}
    for entry in car.namelist():
        if not entry.endswith(".jar") or not stdlib.LSP_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            template = inner[len(prefix):-len(".md")] if inner.startswith(prefix) else ""
            if not inner.endswith(".md") or not template or "." in template:
                continue  # a facet of a template (`Name.Object`) is not the template's own type
            pages.setdefault(template, jar.read(inner).decode("utf-8", "replace"))
    return pages


_MD_HEADING_RE = re.compile(r"^# ([^#\n]+)#([^\n]+)$", re.M)
_MD_DEFINED_RE = re.compile(r"^\*\*Определен:\*\*\s*\*\*([^*\n]+)\*\*", re.M)


def _template_markdown_members(text: str, template: str) -> set[str]:
    """The English names of the members the template's own type declares on its page.

    Each member heading is followed by the type that defines it. The type's own name is the
    one most members name - an inherited member names its ancestor - and a constructor is
    named after the type itself, which is no member.
    """
    qualified = "::".join((*_template_parts(), template))
    found: list[tuple[str, str]] = []
    for match in _MD_HEADING_RE.finditer(text):
        if match.group(1).strip() != qualified:
            continue
        defined = _MD_DEFINED_RE.search(text, match.end())
        following = _MD_HEADING_RE.search(text, match.end())
        owner = defined.group(1) if defined and (
            following is None or defined.start() < following.start()) else ""
        found.append((match.group(2).strip(), owner))
    owners = [owner for _member, owner in found if owner]
    if not owners:
        return set()
    # A genuine tie (two owners naming the same number of methods) has to be broken the same
    # way every run: `set(owners)` iterates in a per-process hash order, so the same page used
    # to hand different runs of `xbsl extract` a different owner - and with it a different
    # member set - for no reason the distribution gives. Sorting the candidates first makes
    # `max` fall back to the alphabetically earliest one, deterministically.
    own = max(sorted(set(owners)), key=owners.count)
    return {
        member.split("(", 1)[0] for member, owner in found
        if owner == own and not member.startswith(qualified)
    }


#: The serializer's own element-kind enum: what an English project writes into ElementKind.
_KIND_ENUM_CLASS = "ProjectElementKindCmptEnum.class"
#: A kind name is Russian or MIXED (`HttpСервис`) - at least one Cyrillic letter tells it
#: from the English neighbour in the constant pool.
_KIND_RU_RE = re.compile(r"^[A-Za-zА-ЯЁ][0-9A-Za-zА-Яа-яЁё]*$")
_KIND_EN_RE = re.compile(r"^[A-Z][0-9A-Za-z]*$")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _kind_pairs(strings: list[str]) -> dict[str, str]:
    """{Russian element kind: English spelling} from adjacent constant-pool strings."""
    return {
        ru: en for en, ru in zip(strings, strings[1:])
        if _KIND_EN_RE.match(en) and _KIND_RU_RE.match(ru) and _CYRILLIC_RE.search(ru)
    }


def scan_kind_table(car: zipfile.ZipFile) -> dict[str, str]:
    """{Russian element kind: English spelling} from the serializer's kind enum, or empty.

    The type dictionary spells the STDLIB TYPE (`Перечисление` -> `Enum`), while the yaml
    of an English project carries the KIND enum's spelling (`ElementKind: Enumeration`) -
    mapping kinds through the dictionary lost such objects from every by-kind view. The
    enum class pairs the spellings the same way the type classes do: the English constant
    right before the Russian one.

    A distribution may carry several copies of the enum. The first one in archive order is
    often a rearranged constant pool whose pair walk yields only `HttpСервис` and
    `SoapСервис`; among the copies the fullest table is the one the rest of the extractor
    needs. The walk does not depend on the platform version: it was seen at least on
    9.2.9+12 and 9.3.1+4, and a later build is handled the same way.
    """
    best: dict[str, str] = {}
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            if not inner.endswith("/" + _KIND_ENUM_CLASS):
                continue
            table = _kind_pairs(_constant_pool(jar.read(inner)))
            if len(table) > len(best):
                best = table
    return best


#: The query language is a separate grammar (TreeSQL); its keyword pairs live in one class.
_QUERY_TERMS_CLASS = "com/e1c/g5/treesql/domain/QueryTerms.class"
_QUERY_JAR_RE = re.compile(r"treesql\.model")
_QUERY_EN_RE = re.compile(r"^[A-Z][A-Z0-9_ ]*$")
_QUERY_RU_RE = re.compile(r"^[А-ЯЁ][А-ЯЁ0-9_ ]*$")


def _scan_query_terms(car: zipfile.ZipFile) -> dict[str, str]:
    """{Russian keyword: English keyword} of the query language, empty when not found.

    The XBSL grammar does not describe queries at all - `Запрос{...}` is a nested language
    with its own parser (TreeSQL), and its vocabulary is nowhere in the documentation either.
    The one place that pairs the spellings is the QueryTerms class of the parser's model, and
    there the English name lies right before the Russian one, exactly as in the type classes.
    """
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _QUERY_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
            data = jar.read(_QUERY_TERMS_CLASS)
        except (zipfile.BadZipFile, KeyError):
            continue
        # Service entries of the pool (method descriptors, class names) sit between a pair
        # and would break the adjacency: `FROM`, the descriptor, then `ИЗ`.
        names = [
            s for s in _constant_pool(data)
            if _QUERY_EN_RE.match(s) or _QUERY_RU_RE.match(s)
        ]
        return _query_pairs(names)
    return {}


def _query_pairs(names: list[str]) -> dict[str, str]:
    """{Russian keyword: English keyword} out of the filtered constant pool.

    Read pair by pair rather than by every adjacency, because the pool holds three shapes and
    only the first is a translation:

    * an English keyword followed by its Russian spelling - a keyword that has both;
    * the same, followed by the ENUM CONSTANT of that pair (`CREATE INDEX` is followed by its
      Russian spelling and then by `CREATE_INDEX`, the English with underscores);
    * a Russian keyword followed by a TRANSLITERATION of itself - the platform has no English
      spelling for that word at all, and what stands next to it is its constant name.

    Taken by adjacency alone, the constant of one entry became the "English" of the next, and
    the dictionary claimed `ОТ` answers `OTLICHAYETSYA` and `ДЛЯ` answers `CREATE_INDEX` - both
    were skipped by hand on the translating side until this read them correctly.
    """
    return _query_scan(names)[0]


def _query_untranslated(names: list[str]) -> set[str]:
    """The query keywords the platform has NO English spelling for (see _query_pairs)."""
    return _query_scan(names)[1]


def _query_scan(names: list[str]) -> tuple[dict[str, str], set[str]]:
    """One pass over the filtered pool: the pairs it holds and the keywords without a pair."""
    pairs: dict[str, str] = {}
    without: set[str] = set()
    previous_english: str | None = None
    index = 0
    while index < len(names) - 1:
        current, following = names[index], names[index + 1]
        english, russian = _QUERY_EN_RE.match(current), _QUERY_RU_RE.match(current)
        if english and previous_english and current == previous_english.replace(" ", "_"):
            index += 1  # the enum constant of the pair just read
            continue
        if english and _QUERY_RU_RE.match(following):
            pairs[following] = current
            previous_english = current
            index += 2
            continue
        if russian and _QUERY_EN_RE.match(following):
            # No English spelling: the platform transliterated the keyword into a constant.
            without.add(current)
            previous_english = None
            index += 2
            continue
        index += 1
    return pairs, without


def extract(dist: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    from xbsl.extract import stdlib  # the page reader: stdlib imports this module in turn

    car = _distro.find_car(dist)
    types: dict[str, str] = {}
    facets: dict[str, str] = {}
    properties: dict[str, str] = {}
    enums: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {k: set() for k in ("types", "facets", "properties", "enums")}

    def scan_xcore(text: str) -> None:
        for match in _PROP_RE.finditer(text):
            body = match.group(1)
            ru, en = _RU_RE.search(body), _EN_RE.search(body)
            if ru and en and _NAME_RE.match(ru.group(1)) and _NAME_RE.match(en.group(1)):
                _add(properties, ru.group(1), en.group(1), conflicts["properties"])
        for match in _ENUM_RE.finditer(text):
            _add(enums, match.group(2), match.group(1), conflicts["enums"])

    with zipfile.ZipFile(car) as z:
        for entry in z.namelist():
            if entry.startswith(STD_BASE) and entry.endswith("/index.html"):
                english = _path_name(entry)
                if not english:
                    continue
                # Control characters inside a word are cut out, as the stdlib step does; the
                # markup is left as it is, the title pattern reads it that way.
                title_match = _TITLE_RE.search(
                    stdlib._RAW_JUNK_RE.sub("", z.read(entry).decode("utf-8", "replace")))
                if not title_match:
                    continue
                russian = title_match.group(1).split("|")[0].strip()
                if not russian or russian.startswith("1С:"):
                    continue
                if "." in english and english.count(".") == 1 and "." in russian:
                    _add(facets, russian, english, conflicts["facets"])
                elif "." not in english and _NAME_RE.match(russian):
                    _add(types, russian, english, conflicts["types"])
            elif entry.endswith(".xcore"):
                scan_xcore(z.read(entry).decode("utf-8", "replace"))
            elif entry.endswith(".jar") and _JAR_RE.search(entry):
                try:
                    with zipfile.ZipFile(io.BytesIO(z.read(entry))) as jar:
                        for inner in jar.namelist():
                            if inner.endswith(".xcore"):
                                scan_xcore(jar.read(inner).decode("utf-8", "replace"))
                except zipfile.BadZipFile:
                    continue

    with zipfile.ZipFile(car) as z:
        managers = ManagerEvidence()
        members, common, declared_types = _scan_meta_objects(z, managers)
        query = _scan_query_terms(z)
        kind_table = scan_kind_table(z)
        manager_table = manager_owners(z, members, managers)

    # A type the reference pages never describe is still paired by its own classes: the
    # favorites branch has no page and had no row here, so a receiver of that type found no
    # owner table. The pages stay the primary source - a class fills a gap, never overrides.
    class_types = {
        russian: english for russian, english in declared_types.items()
        if russian not in types and _NAME_RE.match(russian)
    }
    types.update(class_types)

    for section, names in conflicts.items():
        target = {"types": types, "facets": facets, "properties": properties, "enums": enums}[section]
        for name in names:
            target.pop(name, None)
    return {
        "types": types, "facets": facets, "properties": properties, "enums": enums,
        "members": members, "common": common, "query": query, "kinds": kind_table,
        "class_types": class_types, "manager_owners": manager_table,
    }, conflicts


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.terms"), description=__doc__.splitlines()[0]
    )
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия данных (по умолчанию определяется по дистрибутиву)")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    version = _distro.detect_version(dist, args.element_version)
    _distro.set_data_root(args.data_dir)
    sections, conflicts = extract(dist)

    meta = {
        "element_version": version,
        "source": "docs/help/ru (title + путь страницы), *.xcore (@PropertyInfo, значения "
                  "перечислений), метаобъекты компилятора в jar дистрибутива",
        "note": "пары русского и английского написания; имена с несколькими ролями "
                "(разное английское написание в разных местах) исключены",
    }
    # The compact file is read on every run and holds only what the rules use. The full
    # dictionary (thousands of members) sits beside it and loads on demand: 1 MB of json
    # in every parallel process would cost a quarter of the run time.
    small = {"meta": meta, **{name: dict(sorted(sections[name].items()))
                              for name in ("types", "facets", "properties", "enums", "query",
                                           "kinds")}}
    full = {"meta": meta, "members": sections["members"], "common": sections["common"],
            "manager_owners": sections["manager_owners"]}

    version_dir = _distro.version_dir(version)
    version_dir.mkdir(parents=True, exist_ok=True)
    out = version_dir / "terms.json"
    out.write_text(json.dumps(small, ensure_ascii=False, indent=1), encoding="utf-8",
                   newline="\n")
    out_full = version_dir / "terms_full.json"
    out_full.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8",
                        newline="\n")
    _distro.update_index(version)

    print(f"Записано: {out} (версия {version})")
    for name in ("types", "facets", "properties", "enums"):
        dropped = sorted(conflicts[name])
        extra = f", исключено по конфликту: {dropped}" if dropped else ""
        if name == "types":
            extra += f", из них объявлено классами: {len(sections['class_types'])}"
        print(f"  {name}: {len(sections[name])}{extra}")
    print(f"  query: {len(sections['query'])} ключевых слов языка запросов")
    print(f"  kinds: {len(sections['kinds'])} видов элементов (написания сериализатора)")
    print(f"Записано: {out_full}")
    print(f"  members: {len(sections['members'])} типов, common: {len(sections['common'])} имён")
    owners = sections["manager_owners"]
    listed = ", ".join(f"{kind} -> {owner}" for kind, owner in owners.items())
    print(f"  manager_owners: {len(owners)} видов элементов" + (f" ({listed})" if listed else ""))


if __name__ == "__main__":
    main()
