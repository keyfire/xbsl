#!/usr/bin/env python3
"""Extract the metamodel of 1C:Element configuration element properties from the distribution.

The metamodel lives in the main .car (element-server-with-ide) as EMF `.xcore` files inside
nested jar plugins `*.designtime` / `*.model`. A class declares each property with the
`@PropertyInfo(ru="Имя", en="Name")` annotation (the ru name is the yaml key) followed by the
declaration itself, which carries the TYPE and the default:

    @PropertyInfo(ru="Иерархический")
    @PropertyViewItem(idePriority="9550")
    @PropertyAdded(from="8.0")
    unsettable boolean hierarchical = "false"

Classes inherit (`class X extends A, B`); a member annotated `@InlineProperty` with no
`@PropertyInfo` of its own splices the properties of ITS class into the owner (that is how a
string attribute gets МаксимальнаяДлина). Both are followed on load, not here.

The result is xbsl/data/element/<version>/metamodel.json:
    { "classes": { "<Class>": {"props": {"<ru name>": {kind, ...}}, "ext": [...], "inline": [...]} },
      "enums": { "<EnumClass>": ["<Russian value>", ...] },
      "enum_items": { "<EnumClass>": {"<Russian value>": {"en": "<English>",
                                                         "since": "<mode>", "until": "<mode>"}} },
      "languages": [ {"ru": "<name>", "en": "<name>", "code": "<ISO 639>", "since": "<mode>"} ],
      "vid2class": { "<ВидЭлемента>": "<root class>" },
      "vetted": [ kinds the unknown-property rule may judge ],
      "common": [universal keys of the project element envelope] }

`enum_items` - the platform calls the values of an enumeration its items - spells every value
the way ITS enumeration does (`en`), since the flat term table cannot hold a word two
enumerations spell apart, and dates the values the platform limits to some compatibility modes:
`since` is the mode a value appeared in, `until` the last mode that still has it. A value with
neither is in every mode.

Per property: `kind` (boolean | number | string | enum | type | block | list - what an editor
should offer), `type` (the declared type name), plus the optional `enum` (the enumeration class,
values are in the enums section), `item` (element type of a list), `default`, `since`, `required`,
`priority` (the IDE property-panel order), `types` (@PossibleTypes), `alias` (the alternate
spellings of @PropertyInfo2/3), `en` (the ENGLISH yaml key - the `en` argument of the annotation
or, where it declares none, the member's own name capitalized; the compiler accepts both spellings
in sources) and `deprecated`.

vid2class covers every kind whose root class is confirmed; `vetted` is the narrower list the
`yaml/unknown-property` rule judges - the properties panel uses the wider mapping, where an extra
property is a hint, not a diagnostic.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from xbsl.extract import _distro
from xbsl.extract.terms import (
    EnumerationValue, scan_enumeration_classes, scan_kind_table, scan_language_table,
)

# jar plugins that carry .xcore
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_HEADER_RE = re.compile(
    r"(?:abstract\s+)?(?:class|interface)\s+(\w+)\s*(?:<[^>]*>)?\s*(?:extends\s+([^{]+?))?\s*\{"
)
_ENUM_RE = re.compile(r"\benum\s+(\w+)\s*\{([^}]*)\}")
_ENUM_ITEM_RE = re.compile(r"(\w+)\s*(?:=\s*\d+\s*)?as\s+\"([^\"]+)\"")
#: A data type of the model over a Java class: `type Importance wraps ImportanceG5Enum`. The
#: class is named as the file imports it, fully qualified, or from the package of the file.
_WRAPS_RE = re.compile(r"\btype\s+(\w+)\s+wraps\s+([\w.$]+)")
_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)", re.M)
_IMPORT_RE = re.compile(r"^\s*import\s+([\w.$]+)\s*$", re.M)
_ANNOT_NAME_RE = re.compile(r"@(\w+)")
_MODIFIERS = ("unsettable", "contains", "refers", "unique", "transient", "derived", "readonly")
_DECL_RE = re.compile(
    r"^\s*(?P<mods>(?:\b(?:" + "|".join(_MODIFIERS) + r")\b\s+)*)"
    r"(?P<type>[\w.]+(?:<[^>]*>)?)\s*(?P<array>\[\])?\s+\^?(?P<name>\w+)"
    r"\s*(?:=\s*\"(?P<default>[^\"]*)\")?"
)
_RU_RE = re.compile(r"\bru\s*=\s*\"([^\"]+)\"")

# Declared types that are written as a scalar in yaml.
_BOOLEAN_TYPES = {"boolean", "Boolean"}
_NUMBER_TYPES = {"int", "Integer", "long", "Long", "short", "double", "float", "BigDecimal", "BigInteger"}
_STRING_TYPES = {
    "String", "UUID", "Duration", "LocalTime", "LocalDate", "LocalDateTime", "Instant",
    "PNamespace", "Namespace", "Term", "Date",
}
_TYPE_TYPES = {"Type", "TypeSet"}

# The root class of a kind follows from its English spelling plus a Descriptor suffix
# (Catalog -> CatalogNativeDescriptor), and the spellings come from the serializer's own kind
# enum - the same source the term dictionary reads, so the list of kinds is the platform's
# rather than ours. The kinds whose class the rule cannot name are spelled out here.
#
# The mapping used to be hand-written in full, and that is exactly how three kinds of a
# newer build went missing (DataJournal, ReportPanel, IntegrationProcess): their classes
# were extracted
# with all their properties, but nothing named them, so `metadata_schema` answered
# {"props": {}, "class": null} - indistinguishable from "the platform has no such kind".
_KIND_CLASS_EXCEPTIONS = {
    "ВиртуальнаяТаблица": "VirtualTableDescriptorBase",
    "КлючДоступа": "AccessKeysClassDescriptor",
    "КомпонентИнтерфейса": "ComponentModel",
    "ПравоНаДействие": "AccessPrivilegeClassDescriptor",
    "СобытиеЖурналаСобытий": "EventLogEvent",
}


def build_vid2class(classes: dict, kinds: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """({ElementKind: root class}, kinds left unresolved) for the kinds of the distribution.

    An unresolved kind is reported rather than dropped silently: it means the platform has
    added a kind whose class the suffix rule does not name, and the exceptions above need a
    new line. An empty kind table (a distribution without the serializer's enum) yields an
    empty mapping - the caller decides whether that is fatal.
    """
    out: dict[str, str] = {}
    unresolved: list[str] = []
    for russian, english in kinds.items():
        cls = _KIND_CLASS_EXCEPTIONS.get(russian)
        if cls is None:
            cls = next(
                (c for c in (english + "NativeDescriptor", english + "Descriptor") if c in classes),
                None,
            )
        if cls is None:
            unresolved.append(russian)
        else:
            out[russian] = cls
    return dict(sorted(out.items())), sorted(unresolved)
# The kinds `yaml/unknown-property` may judge: an incomplete class here turns into a false
# diagnostic on valid sources, so a kind joins the list only once its class is known to be
# complete (the generated stub of a kind proves the mapping, not the completeness of the
# class - a stub carries five keys). The rest keep the panel's wider
# vid2class, where an unlisted property is a missing hint rather than a diagnostic.
VETTED = [
    "HttpСервис",
    "ВиртуальнаяТаблица",
    "ГлобальноеКлиентскоеСобытие",
    "Документ",
    "КомпонентИнтерфейса",
    "КонтрактТипа",
    "ОбщийМодуль",
    "ПараметрыРаботыКлиента",
    "Перечисление",
    "РегистрСведений",
    "Справочник",
    "Структура",
    "ФрагментКомандногоИнтерфейса",
    # Joined 09.08.2026 on the same measure - live sources, not a generated stub. Across four
    # real projects these kinds are written with 6 to 11 top-level keys each, and every one of
    # those keys is declared by the class: nothing to report falsely. The kinds left out are
    # not in doubt - they are simply written with the four mandatory keys alone wherever they
    # occur, and four keys prove nothing about a class.
    "ЗапланированноеЗадание",     # 11 keys across 2 objects
    "СобытиеЖурналаСобытий",      # 10 keys across 4 objects
    "НаборКонстант",              # 8 keys
    "ЛокализованныеСтроки",       # 6 keys across 3 objects
    "Обработка",                  # 6 keys
]
# Universal keys of the project element envelope (shared by all kinds).
COMMON = ["ВидЭлемента", "Ид", "Имя", "ОбластьВидимости", "Импорт"]


def _strip_comments(text: str) -> str:
    """Drop /* */ and // comments, leaving string literals alone.

    A literal may hold the comment markers themselves - an url template defaults to `"/*"` - and a
    regex that does not know about quotes treats it as an opening comment and eats the rest of the
    file up to the next `*/`, silently losing the members that follow (that is how ЛюбойМетод,
    Методы and КонтрольДоступа of a url template went missing).
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            end = text.find("\n", i)
            end = n if end == -1 else end
            j = i + 1
            while j < end and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j < end:  # a closed literal - copy as is; a lone quote is an ordinary character
                out.append(text[i:j + 1])
                i = j + 1
                continue
            out.append(c)
            i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _balanced(text: str, start: int) -> int:
    """Index just past the (...) or {...} opening at `start`, quoted strings ignored.

    An annotation argument may contain the very brackets that delimit it - a handler signature
    reads `ru="Обработчик(Команда: ...)"` - so the scan has to know about string literals; a
    naive [^()]* stops inside the literal and loses the member that follows.
    """
    opening = text[start]
    closing = ")" if opening == "(" else "}"
    depth = 0
    i = start
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == opening:
            depth += 1
        elif c == closing:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _members(body: str):
    """Yield ({annotation: arguments}, declaration line) for every member of a class body."""
    annots: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c.isspace():
            i += 1
            continue
        if c == "@":
            m = _ANNOT_NAME_RE.match(body, i)
            if not m:
                i += 1
                continue
            name, i = m.group(1), m.end()
            args = ""
            if i < n and body[i] == "(":
                end = _balanced(body, i)
                args, i = body[i + 1:end - 1], end
            annots.setdefault(name, args)
            continue
        if c in "{}":
            # a method body (op ... { ... }) - not a property
            i = _balanced(body, i) if c == "{" else i + 1
            annots = {}
            continue
        end = body.find("\n", i)
        end = n if end == -1 else end
        brace = body.find("{", i)
        decl = body[i:end if brace == -1 or brace > end else brace].strip()
        if decl:
            yield annots, decl
            annots = {}
        i = end


def _arg(args: str, key: str) -> str | None:
    m = re.search(r"\b%s\s*=\s*\"([^\"]*)\"" % key, args)
    return m.group(1) if m else None


def _classify(type_name: str, array: bool, wrappers: set[str], enums: dict) -> dict:
    """The editor-facing kind of a declared type (see the module docstring)."""
    if array:
        return {"kind": "list", "item": type_name}
    if type_name in _BOOLEAN_TYPES:
        return {"kind": "boolean"}
    if type_name in _NUMBER_TYPES:
        return {"kind": "number"}
    if type_name in _STRING_TYPES:
        return {"kind": "string"}
    if type_name in _TYPE_TYPES:
        return {"kind": "type"}
    if type_name in enums:
        return {"kind": "enum", "enum": type_name}
    if type_name in wrappers:
        # A @TypedWrapper class holds a single scalar and is written as one in yaml.
        return {"kind": "string"}
    return {"kind": "block"}


def _member_property(annots: dict[str, str], decl: str, wrappers: set[str], enums: dict) -> tuple[str, dict] | None:
    """One property record out of a member, or None when the member is not a yaml property.

    The name comes from @PropertyInfo; @PropertyInfo2/3 are the alternate spellings the compiler
    also accepts, and a member that carries ONLY those (an old name kept alive with `to="4.0"`)
    is still a property - it is recorded as one, marked deprecated.
    """
    spellings = [
        (key, ru.group(1))
        for key in ("PropertyInfo", "PropertyInfo2", "PropertyInfo3")
        if (ru := _RU_RE.search(annots.get(key, "")))
    ]
    if not spellings:
        return None  # not a property, or an English-only info - no yaml key to offer
    m = _DECL_RE.match(decl)
    if not m:
        return None
    rec = _classify(m.group("type"), bool(m.group("array")), wrappers, enums)
    rec["type"] = m.group("type")
    default = m.group("default")
    if default is None:
        default = _arg(annots.get("PropertyDefVal", ""), "value")
    if default:
        rec["default"] = default
    since = _arg(annots.get("PropertyAdded", ""), "from")
    if since:
        rec["since"] = since
    if "Required" in annots:
        rec["required"] = True
    if "PropertyDeleted" in annots:
        rec["deprecated"] = True
    priority = _arg(annots.get("PropertyViewItem", ""), "idePriority")
    if priority and priority.isdigit():
        rec["priority"] = int(priority)
    possible = _arg(annots.get("PossibleTypes", ""), "value")
    if possible:
        rec["types"] = possible
    dispatched = annots.get("DescriptorDispatchedBy")
    if dispatched is not None:
        # A collection whose items are of different classes: the platform picks one by the value
        # of a key of the item itself (`Имя` for attributes, `Вид` for scheduled jobs), and falls
        # back to defaultImpl. The key is stored as `dispatch`, the fallback as `impl` - the name
        # of an implementation, resolved to a class through @DefaultImpl (see `implName`).
        by = _arg(dispatched, "ru")
        if by:
            rec["dispatch"] = by
        impl = _arg(dispatched, "defaultImpl")
        if impl:
            rec["impl"] = impl
    primary_key, primary = spellings[0]
    # The ENGLISH yaml key: the `en` argument when the annotation declares one, otherwise the
    # member's own name with a capital first letter. Proven against the compiler: a project
    # spelled `ElementKind` / `Name` / `Attributes` / `Length` applies, and only 405 of the 1120
    # @PropertyInfo annotations carry `en=` - `Реквизиты` (member `attributes`) is one of those
    # that do not, yet `Attributes:` compiles. Where both exist they agree except when `en`
    # deliberately shortens the member (`typeNames` -> `Type`), so `en` wins.
    english = _arg(annots.get(primary_key, ""), "en") or m.group("name")[:1].upper() + m.group("name")[1:]
    if english and english != primary:
        rec["en"] = english
    aliases = [name for _, name in spellings[1:]]
    if aliases:
        rec["alias"] = aliases
    if primary_key != "PropertyInfo":
        rec["deprecated"] = True  # only an old spelling is declared
    return primary, rec


def _leading_annotations(text: str, start: int) -> dict[str, str]:
    """Annotations written right before position `start` (a class header), name -> arguments.

    Walked BACKWARDS so the class regex stays as it is: an annotation block is a run of
    `@Name(args)` (or a bare `@Name`) separated by whitespace, and the first thing that is
    neither ends it.
    """
    out: dict[str, str] = {}
    i = start
    while i > 0:
        j = i
        while j > 0 and text[j - 1].isspace():
            j -= 1
        if j == 0:
            break
        if text[j - 1] == ")":
            depth = 0
            k = j - 1
            while k >= 0:
                if text[k] == ")":
                    depth += 1
                elif text[k] == "(":
                    depth -= 1
                    if depth == 0:
                        break
                k -= 1
            if k < 0:
                break
            args = text[k + 1:j - 1]
            n = k
            while n > 0 and (text[n - 1].isalnum() or text[n - 1] == "_"):
                n -= 1
            if n == k or n == 0 or text[n - 1] != "@":
                break
            out.setdefault(text[n:k], args)
            i = n - 1
            continue
        n = j
        while n > 0 and (text[n - 1].isalnum() or text[n - 1] == "_"):
            n -= 1
        if n < j and n > 0 and text[n - 1] == "@":
            out.setdefault(text[n:j], "")
            i = n - 1
            continue
        break
    return out


def _parse_xcore(text: str, classes: dict, enums: dict, wrappers: set[str],
                 wraps: dict[str, str] | None = None,
                 spellings: dict[str, dict[str, str]] | None = None) -> None:
    """Collect classes, enumerations and @TypedWrapper markers of one .xcore file.

    `wraps`, when given, collects the data types the file declares over a Java class: {the
    type's name in the model: the class file of the class (`pkg/Name.class`)}. `spellings`,
    when given, collects the English spelling of each value of each enumeration - {the
    enumeration: {Russian value: English}}: the literal of the model is the English spelling,
    and the Russian one follows it (`Normal as "Обычная"`).
    """
    text = _strip_comments(text)
    n = len(text)
    for name, body in _ENUM_RE.findall(text):
        literals = _ENUM_ITEM_RE.findall(body)
        if literals:
            enums.setdefault(name, [ru for _, ru in literals])
            if spellings is not None:
                spellings.setdefault(name, {ru: en for en, ru in literals})
    if wraps is not None:
        package = _PACKAGE_RE.search(text)
        imported = {path.rsplit(".", 1)[-1]: path for path in _IMPORT_RE.findall(text)}
        for name, wrapped in _WRAPS_RE.findall(text):
            if "." not in wrapped:
                wrapped = imported.get(wrapped) or (
                    f"{package.group(1)}.{wrapped}" if package else wrapped)
            wraps.setdefault(name, wrapped.replace(".", "/") + ".class")
    for m in re.finditer(r"@TypedWrapper\s*(?:\([^)]*\))?\s*(?:@\w+(?:\([^)]*\))?\s*)*"
                         r"(?:abstract\s+)?(?:class|interface)\s+(\w+)", text):
        wrappers.add(m.group(1))
    for m in _HEADER_RE.finditer(text):
        name = m.group(1)
        ext: list[str] = []
        if m.group(2):
            for part in m.group(2).split(","):
                base = re.sub(r"<[^>]*>", "", part).strip()
                if base:
                    ext.append(base)
        # the class body by curly-brace balance from '{'
        i = m.end() - 1
        j = _balanced(text, i) - 1
        node = classes.setdefault(name, {"props": {}, "ext": [], "inline": [], "_body": []})
        node["_body"].append(text[i + 1:j])
        for e in ext:
            if e not in node["ext"]:
                node["ext"].append(e)
        # Who this class is for, as the metamodel itself declares it: @DefaultImpl names the
        # implementation a collection falls back to, @DescriptorPresentation carries the value a
        # dispatched collection matches against (the name of a built-in attribute - Код,
        # Наименование, Владелец). Both let the item class be RESOLVED instead of guessed.
        leading = _leading_annotations(text, m.start())
        impl_name = _arg(leading.get("DefaultImpl", ""), "name")
        if impl_name:
            node["implName"] = impl_name
        presents = _arg(leading.get("DescriptorPresentation", ""), "ru")
        if presents:
            node["presents"] = presents
            # The annotation states BOTH spellings, and for a dispatch value nothing else in
            # the data does: a schedule kind (`Daily`) is not a type, not a property and not an
            # enumeration value, so the term dictionaries know no pair for it and the
            # translator honestly left it Russian.
            presents_en = _arg(leading.get("DescriptorPresentation", ""), "en")
            if presents_en and presents_en != presents:
                node["presentsEn"] = presents_en


def _fill_members(classes: dict, enums: dict, wrappers: set[str]) -> None:
    """Second pass over the collected bodies: now that wrappers and enums are known, type them."""
    for node in classes.values():
        for body in node.pop("_body"):
            for annots, decl in _members(body):
                prop = _member_property(annots, decl, wrappers, enums)
                if prop:
                    node["props"].setdefault(prop[0], prop[1])
                    continue
                if "InlineProperty" in annots and "PropertyInfo" not in annots:
                    # The inline member has no key of its own: its class's properties belong here.
                    d = _DECL_RE.match(decl)
                    if d and d.group("type") not in node["inline"]:
                        node["inline"].append(d.group("type"))


def _read_model(
    car: zipfile.ZipFile,
) -> tuple[dict, dict, set[str], dict[str, str], dict[str, dict[str, str]]]:
    """(classes, enumerations, @TypedWrapper classes, wrapped Java classes, the English spellings
    of the enumeration values) of every .xcore.

    The classes still carry their raw bodies (`_body`): the members are typed later, once
    every enumeration is known (see _fill_members).
    """
    classes: dict = {}
    enums: dict = {}
    wrappers: set[str] = set()
    wraps: dict[str, str] = {}
    spellings: dict[str, dict[str, str]] = {}
    for n in car.namelist():
        if not n.endswith(".jar") or not _JAR_RE.search(Path(n).name):
            continue
        try:
            jz = zipfile.ZipFile(io.BytesIO(car.read(n)))
        except zipfile.BadZipFile:
            continue
        for m in jz.namelist():
            if m.endswith(".xcore"):
                _parse_xcore(jz.read(m).decode("utf-8", "replace"), classes, enums, wrappers,
                             wraps, spellings)
    return classes, enums, wrappers, wraps, spellings


def _property_types(classes: dict) -> set[str]:
    """The declared types of every property of the raw class bodies - the item type of a list
    included, since a list is declared by the type of its items."""
    found: set[str] = set()
    for node in classes.values():
        for body in node["_body"]:
            for annots, decl in _members(body):
                if not any(key in annots for key in ("PropertyInfo", "PropertyInfo2", "PropertyInfo3")):
                    continue
                m = _DECL_RE.match(decl)
                if m:
                    found.add(m.group("type"))
    return found


def _compiled_enumerations(car: zipfile.ZipFile, classes: dict, enums: dict, wrappers: set[str],
                           wraps: dict[str, str]) -> dict[str, list[EnumerationValue]]:
    """{a data type a property is typed by: the values of the compiled enumeration it wraps}.

    The model types the importance of a command, the days of a weekly schedule, the periodicity
    of a set of constants and more by data types over Java enumerations; the values are in the
    compiled class alone (extract.terms.enumeration_values). A type that is an enumeration or a
    class of the model itself, or a wrapper written as a scalar, is not looked for; a wrapped
    class that is no enumeration of values gives nothing. A value comes in both spellings and
    with the modes the class limits it to.
    """
    used = _property_types(classes)
    wanted = {
        name: path for name, path in wraps.items()
        if name in used and name not in enums and name not in classes and name not in wrappers
    }
    values = scan_enumeration_classes(car, set(wanted.values()))
    return {name: values[path] for name, path in sorted(wanted.items()) if path in values}


def compiled_enumerations(car: zipfile.ZipFile) -> dict[str, list[EnumerationValue]]:
    """The compiled enumerations the properties of the model are typed by (see
    _compiled_enumerations) - for the terms step, which spells their values."""
    classes, enums, wrappers, wraps, _spellings = _read_model(car)
    return _compiled_enumerations(car, classes, enums, wrappers, wraps)


def _value_record(english: str, since: str | None = None, until: str | None = None) -> dict:
    """One value of an enumeration as metamodel.json keeps it: its English spelling, and the
    modes that limit it where the platform states them."""
    return {"en": english, **({"since": since} if since else {}),
            **({"until": until} if until else {})}


def extract(dist: Path) -> tuple[dict, dict, dict, list[dict[str, str]], list[str], dict]:
    """The classes, the enumerations, the kind table, the languages of the main .car, the
    compiled enumerations among the enumerations and the record of every enumeration value.

    The kind table (Russian kind -> its English spelling) is read from the serializer's own
    enum by the term extractor; it is taken here rather than from terms.json because this
    step runs BEFORE the terms one, and a mapping built from a stale dictionary would quietly
    lose the kinds a new build brings.

    The languages are the enumeration the project descriptor types its localization languages
    and its default language by. It is a compiled class, not an .xcore enumeration, so the
    walk above never met it: the default language came out a `block` and the list of
    languages a list of an unknown class. It joins the enumerations BEFORE the members are
    typed, and the default language becomes an enumeration like any other. So do the other
    compiled enumerations the model wraps for its properties (_compiled_enumerations): before
    them the importance of a command, the strategy of a scheduled job and a dozen more
    properties were typed `block`, with no list of the values they allow.

    The records ({enumeration: {Russian value: {"en", "since"?, "until"?}}}) spell each value
    the way ITS enumeration does. The flat table of the term pairs cannot: the same Russian
    word is `Normal` for the importance of a command and `Usual` for the importance of a
    favorite, and the table drops such a word altogether. Every source of the enumerations
    states the English spelling next to the Russian one: the literal of an .xcore, the term of
    a language, the pair a compiled value is built from. The modes come from the compiled
    classes alone - an .xcore dates no value - and from the language table.
    """
    car = _distro.find_car(dist)
    with zipfile.ZipFile(car) as z:
        classes, enums, wrappers, wraps, spellings = _read_model(z)
        kinds = scan_kind_table(z)
        languages = scan_language_table(z)
        records = {name: {russian: _value_record(english) for russian, english in pairs.items()}
                   for name, pairs in spellings.items()}
        rows: list[dict[str, str]] = []
        if languages is not None:
            language_class, rows = languages
            enums.setdefault(language_class, [row["ru"] for row in rows])
            records.setdefault(language_class, {
                row["ru"]: _value_record(row["en"], row.get("since")) for row in rows})
        compiled = _compiled_enumerations(z, classes, enums, wrappers, wraps)
    for name, values in compiled.items():
        enums.setdefault(name, [value.russian for value in values])
        records.setdefault(name, {
            value.russian: _value_record(value.english, value.since, value.until)
            for value in values})
    _fill_members(classes, enums, wrappers)
    # In the order of the values the enumeration lists, which is the order the platform
    # declares them in.
    values: dict[str, dict[str, dict]] = {}
    for name in sorted(enums):
        own = records.get(name) or {}
        listed = {russian: own[russian] for russian in enums[name] if russian in own}
        if listed:
            values[name] = listed
    return classes, enums, kinds, rows, sorted(compiled), values


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.metamodel"),
        description="Извлечь метамодель свойств элементов Элемента",
    )
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь metamodel.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    if not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")

    version = _distro.detect_version(dist, args.element_version)
    classes, enums, kinds, languages, compiled, enum_items = extract(dist)
    vid2class, unresolved = build_vid2class(classes, kinds)
    if not languages:
        print("ПРЕДУПРЕЖДЕНИЕ: в дистрибутиве не найдено перечисление языков локализации – "
              "раздел languages остался пустым", file=sys.stderr)
    if not kinds:
        print("ПРЕДУПРЕЖДЕНИЕ: в дистрибутиве не найдено перечисление видов элементов – "
              "vid2class остался пустым", file=sys.stderr)
    if unresolved:
        print(f"ПРЕДУПРЕЖДЕНИЕ: не найден корневой класс для видов: {unresolved} – "
              "допишите их в _KIND_CLASS_EXCEPTIONS", file=sys.stderr)

    data = {
        "meta": {
            "element_version": version,
            "source": "main .car / *.xcore (EMF-метамодель), @PropertyInfo + объявление члена",
            "classes": len(classes),
            "enums": len(enums),
            "props": "typed",
            "note": "свойства элементов конфигурации по видам: правило yaml/unknown-property и панель свойств",
        },
        "classes": {
            k: {
                "props": v["props"],
                "ext": v["ext"],
                **({"inline": v["inline"]} if v["inline"] else {}),
                # How a dispatched collection finds this class: by the implementation name it is
                # the default for, or by the value its items carry (Код, Наименование, Владелец).
                **({"implName": v["implName"]} if v.get("implName") else {}),
                **({"presents": v["presents"]} if v.get("presents") else {}),
                **({"presentsEn": v["presentsEn"]} if v.get("presentsEn") else {}),
            }
            for k, v in sorted(classes.items())
        },
        "enums": dict(sorted(enums.items())),
        # Every value of every enumeration with its English spelling, as that enumeration
        # spells it, and the compatibility modes the platform limits it to.
        "enum_items": enum_items,
        # The languages in the order the platform declares them, each with its code (the
        # folder of its translations is named by it) and the compatibility mode it needs.
        "languages": languages,
        "vid2class": vid2class,
        "vetted": sorted(VETTED),
        "common": COMMON,
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "metamodel.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  классов: {len(classes)}; перечислений: {len(enums)}; видов в vid2class: {len(vid2class)}")
    listed = ", ".join(f"{row['ru']} ({row['code']}, с {row['since']})" for row in languages)
    print(f"  языков локализации: {len(languages)}" + (f" – {listed}" if listed else ""))
    print(f"  скомпилированных перечислений у свойств: {len(compiled)}"
          + (f" – {', '.join(compiled)}" if compiled else ""))
    dated = []
    for name, records in enum_items.items():
        for russian, record in records.items():
            limits = [f"с {record['since']}"] if record.get("since") else []
            limits += [f"по {record['until']}"] if record.get("until") else []
            if limits:
                dated.append(f"{name}.{russian} ({', '.join(limits)})")
    print(f"  значений перечислений с английским написанием: "
          f"{sum(len(records) for records in enum_items.values())}; с режимами: {len(dated)}"
          + (f" – {', '.join(dated)}" if dated else ""))
    return 0


main = _distro.packed_step(main)


if __name__ == "__main__":
    raise SystemExit(main())
