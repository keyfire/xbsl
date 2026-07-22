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
      "vid2class": { "<ВидЭлемента>": "<root class>" },
      "vetted": [ kinds the unknown-property rule may judge ],
      "common": [universal keys of the project element envelope] }

Per property: `kind` (boolean | number | string | enum | type | block | list - what an editor
should offer), `type` (the declared type name), plus the optional `enum` (the enumeration class,
values are in the enums section), `item` (element type of a list), `default`, `since`, `required`,
`priority` (the IDE property-panel order), `types` (@PossibleTypes), `alias` (the alternate
spellings of @PropertyInfo2/3) and `deprecated`.

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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

# jar plugins that carry .xcore
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_HEADER_RE = re.compile(
    r"(?:abstract\s+)?(?:class|interface)\s+(\w+)\s*(?:<[^>]*>)?\s*(?:extends\s+([^{]+?))?\s*\{"
)
_ENUM_RE = re.compile(r"\benum\s+(\w+)\s*\{([^}]*)\}")
_ENUM_ITEM_RE = re.compile(r"(\w+)\s*(?:=\s*\d+\s*)?as\s+\"([^\"]+)\"")
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

# Mapping ВидЭлемента (yaml) -> the root class of the metamodel. Derived by rule - the English
# name of the kind (the term dictionary) plus a Descriptor suffix, e.g. Catalog ->
# CatalogNativeDescriptor - and confirmed against the corpora: every top-level key seen in real
# sources of a kind resolves through its class. The five kinds the rule misses (no English name
# or a differently named class) are spelled out.
VID2CLASS = {
    "HttpСервис": "HttpServiceDescriptor",
    "SoapСервис": "SoapServiceDescriptor",
    "ВиртуальнаяТаблица": "VirtualTableDescriptorBase",
    "ГлобальноеКлиентскоеСобытие": "GlobalClientEventDescriptor",
    "Документ": "DocumentNativeDescriptor",
    "ЗапланированноеЗадание": "ScheduledJobDescriptor",
    "КлючДоступа": "AccessKeysClassDescriptor",
    "КомандаСКомпонентом": "CommandWithComponentDescriptor",
    "КомпонентИнтерфейса": "ComponentModel",
    "КонтрактСервиса": "ServiceContractDescriptor",
    "КонтрактСущности": "EntityContractDescriptor",
    "КонтрактТипа": "TypeContractDescriptor",
    "ЛокализованныеСтроки": "LocalizedStringsDescriptor",
    "НаборКонстант": "ConstantsSetNativeDescriptor",
    "НавигационнаяКоманда": "NavigationCommandDescriptor",
    "Обработка": "ProcessingNativeDescriptor",
    "ОбщийМодуль": "CommonModuleDescriptor",
    "ОбычнаяКоманда": "UsualCommandDescriptor",
    "Отчет": "ReportNativeDescriptor",
    "ПараметрСамостоятельнойРегистрацииПользователя": "UserSelfRegistrationParameterDescriptor",
    "ПараметрыРаботыКлиента": "ClientWorkParametersDescriptor",
    "ПереключаемаяКоманда": "SwitchableCommandDescriptor",
    "Перечисление": "EnumerationDescriptor",
    "ПланОбмена": "ExchangePlanNativeDescriptor",
    "ПравоНаДействие": "AccessPrivilegeClassDescriptor",
    "ПравоНаЭлемент": "PrivilegeOnElementDescriptor",
    "РегистрНакопления": "AccumulationRegisterNativeDescriptor",
    "РегистрСведений": "InformationRegisterNativeDescriptor",
    "СобытиеЖурналаСобытий": "EventLogEvent",
    "Справочник": "CatalogNativeDescriptor",
    "Структура": "StructureDescriptor",
    "ФрагментКомандногоИнтерфейса": "CommandInterfaceFragmentDescriptor",
    "ХранилищеНастроек": "SettingsStorageNativeDescriptor",
    "ХранимаяСтруктура": "StorableStructureDescriptor",
    "ЦветоваяСхемаОтчета": "ReportColorSchemaNativeDescriptor",
}
# The kinds `yaml/unknown-property` may judge: an incomplete class here turns into a false
# diagnostic on valid sources, so a kind joins the list only once REAL sources of it have been
# checked against its class with zero findings (the generated stub of a kind proves the mapping,
# not the completeness of the class - a stub carries five keys). The rest keep the panel's wider
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


def _parse_xcore(text: str, classes: dict, enums: dict, wrappers: set[str]) -> None:
    """Collect classes, enumerations and @TypedWrapper markers of one .xcore file."""
    text = _strip_comments(text)
    n = len(text)
    for name, body in _ENUM_RE.findall(text):
        values = [ru for _, ru in _ENUM_ITEM_RE.findall(body)]
        if values:
            enums.setdefault(name, values)
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


def extract(dist: Path) -> tuple[dict, dict]:
    """Collect the classes and the enumerations from every .xcore of the main .car."""
    car = _distro.find_car(dist)
    classes: dict = {}
    enums: dict = {}
    wrappers: set[str] = set()
    with zipfile.ZipFile(car) as z:
        for n in z.namelist():
            if not n.endswith(".jar") or not _JAR_RE.search(Path(n).name):
                continue
            try:
                jz = zipfile.ZipFile(io.BytesIO(z.read(n)))
            except zipfile.BadZipFile:
                continue
            for m in jz.namelist():
                if m.endswith(".xcore"):
                    _parse_xcore(jz.read(m).decode("utf-8", "replace"), classes, enums, wrappers)
    _fill_members(classes, enums, wrappers)
    return classes, enums


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Извлечь метамодель свойств элементов Элемента")
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
    classes, enums = extract(dist)
    # sanity check: all vid2class root classes are present
    missing = sorted(c for c in VID2CLASS.values() if c not in classes)
    if missing:
        print(f"ПРЕДУПРЕЖДЕНИЕ: не найдены корневые классы: {missing}", file=sys.stderr)

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
            }
            for k, v in sorted(classes.items())
        },
        "enums": dict(sorted(enums.items())),
        "vid2class": dict(sorted(VID2CLASS.items())),
        "vetted": sorted(VETTED),
        "common": COMMON,
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "metamodel.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  классов: {len(classes)}; перечислений: {len(enums)}; видов в vid2class: {len(VID2CLASS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
