#!/usr/bin/env python3
"""Extract the 1C:Element stdlib type catalog from the distribution documentation.

The docs (Docusaurus HTML) live in the distribution .car under
`data/docs/help/ru/stdlib/element/xbsl/Std/**/index.html`. Each symbol's Russian name is in
<title> ("Имя | 1С:Предприятие.Элемент"), the English one is in the path segment ("<Имя>_ru").
Types are bilingual (like keywords), so the catalog keeps both forms.

Nearby, under `.../xbsl/DeveloperName/ProjectName/SubsystemName/**`, sit the template pages of
types spawned by project objects: "{ИмяСправочника}.Ссылка",
"{ИмяРегистраСведений}.КлючЗаписи", "{ИмяДокумента}.АвтоматическаяФормаСписка..." From them
the object_members dictionary is built: object kind (by the English template name in the path) ->
names of the spawned members (the second segment of the Russian title). Placeholder members
("{ИмяМетрики}", Latin SOAP templates) are skipped, and so are kinds outside the known map.

From interface component pages (a type is a component when the "Иерархия типа" section lists
Стд::Интерфейс::Компонент among the bases; plus the page of Компонент itself) the
component_props dictionary is additionally built: Russian type name -> the full set of built-in
properties (own ones - the H3 headings of the "Свойства" section, inherited ones - the link
texts of the "Список унаследованных свойств" sections). Same-named types with differing sets
collapse into the intersection - a bare yaml name cannot tell them apart, so only the
indisputable part is kept.

From all Std pages type_members is built: type name -> its members for dot completion,
properties and methods SEPARATELY (different icons in the completion list, methods get parens).

The result is xbsl/data/element/<version>/stdlib.json:
{ "names": [...], "object_members": {"Справочник": [...], ...},
  "component_props": {"СтандартнаяКарточка": [...], ...},
  "type_members": {"Массив": {"methods": [...]}, "СтандартнаяКарточка": {"properties": [...]}} }.
The version is detected from the distribution automatically (or set with --element-version).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"
TEMPLATE_BASE = "data/docs/help/ru/stdlib/element/xbsl/DeveloperName/ProjectName/SubsystemName/"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_CYRILLIC_NAME_RE = re.compile(r"^[А-ЯЁ][А-Яа-яЁё0-9]*$")

# Parsing a component page: content is in <article>, sections are H2 headings, own properties
# are H3 headings, inherited ones are links to the base type's properties.
COMPONENT_BASE = "Стд::Интерфейс::Компонент"
COMPONENT_PAGE = STD_BASE + "Interface/Component_ru/index.html"
_ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.S)
_H2_OPEN_RE = re.compile(r"<h2[^>]*>")
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_LINK_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_JUNK_RE = re.compile(r"[\x00-\x1f​﻿]")  # control characters and Docusaurus anchors
# Underscores are part of member names: the constant-style properties (Символы.НОВАЯ_СТРОКА,
# ВОЗВРАТ_КАРЕТКИ, НЕРАЗРЫВНЫЙ_ПРОБЕЛ) are documented and must not be dropped.
_PROP_NAME_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_]*$")
# An entity type facet: "Пользователи.Объект", "ДвоичныйОбъект.Ссылка" - the record and
# reference members live on these pages, not on the type's own (manager) page.
_FACET_TITLE_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*\.[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*$")

# English template name in the path -> Russian kind name (the ВидЭлемента value in yaml).
_TEMPLATE_KINDS = {
    "CatalogName": "Справочник",
    "DocumentName": "Документ",
    "InformationRegisterName": "РегистрСведений",
    "AccumulationRegisterName": "РегистрНакопления",
    "ExchangePlanName": "ПланОбмена",
    "EnumerationName": "Перечисление",
    "AccessKeyName": "КлючДоступа",
    "ClientWorkParametersName": "ПараметрыРаботыКлиента",
    "ComponentName": "КомпонентИнтерфейса",
    "EntityContractName": "КонтрактСущности",
    "ReportName": "Отчет",
    "ReportPanelName": "ПанельОтчетов",
    "ProcessingName": "Обработка",
}


def _plain_text(html: str) -> str:
    """Text without tags, Docusaurus anchor characters and control characters.

    On some docs pages headings and member names arrive with control characters inside a
    word ("Св\x00ойства", "Список унаследованных \x00методов") - without cleaning, the section
    goes unrecognized, the member name fails validation, and such types' members are lost silently.
    """
    return _JUNK_RE.sub("", _TAG_RE.sub("", html)).strip()


def component_props(entry: str, raw: str) -> tuple[str, set[str]] | None:
    """(Russian component type name, its built-in properties), or None - not a component.

    A component is a type whose "Иерархия типа" section lists Стд::Интерфейс::Компонент
    among the bases, plus the page of Компонент itself (its only base is Объект). The
    property set is complete: own ones (H3s of the "Свойства" section) together with the
    inherited ones (link texts of the "Список унаследованных свойств" sections) - no need
    to resolve the inheritance chain.
    """
    mt = _TITLE_RE.search(raw)
    ma = _ARTICLE_RE.search(raw)
    if not mt or not ma:
        return None
    title = mt.group(1).split("|")[0].strip()
    if not title or not _PROP_NAME_RE.match(title):
        return None
    sections = _H2_OPEN_RE.split(ma.group(1))
    is_component = entry == COMPONENT_PAGE
    props: set[str] = set()
    for section in sections:
        head = _plain_text(section[:200])
        if head.startswith("Иерархия типа"):
            if COMPONENT_BASE in _plain_text(section):
                is_component = True
        elif head.startswith("Свойства"):
            for m in _H3_RE.finditer(section):
                name = _plain_text(m.group(1))
                if _PROP_NAME_RE.match(name):
                    props.add(name)
        elif head.startswith("Список унаследованных свойств"):
            for m in _LINK_RE.finditer(section):
                name = _plain_text(m.group(1))
                if _PROP_NAME_RE.match(name):
                    props.add(name)
    return (title, props) if is_component else None


def page_members(raw: str) -> tuple[set[str], set[str]]:
    """Type members for dot completion: (properties, methods).

    Own members are the H3 headings of the "Свойства" / "Методы" sections, inherited ones are
    the link texts of the "Список унаследованных свойств" / "Список унаследованных методов"
    sections (H3s there are base type names, not members). Constructors, literals and the
    hierarchy do not count.

    Most stdlib types have no properties at all (in Element even Длина() is a method); the
    "Свойства" section mostly belongs to interface components and record types.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return set(), set()
    props: set[str] = set()
    methods: set[str] = set()
    for section in _H2_OPEN_RE.split(ma.group(1)):
        head = _plain_text(section[:200])
        if head.startswith("Список унаследованных"):
            target = methods if head.startswith("Список унаследованных методов") else props
            found = (_plain_text(m.group(1)) for m in _LINK_RE.finditer(section))
        elif head.startswith(("Свойства", "Методы")):
            target = methods if head.startswith("Методы") else props
            found = (_plain_text(m.group(1)) for m in _H3_RE.finditer(section))
        else:
            continue
        target.update(name for name in found if _PROP_NAME_RE.match(name))
    return props, methods


# The signature in the code block after a method's H3 heading: `Имя(Параметры): ТипВозврата`.
_SIG_CODE_RE = re.compile(r"<pre class=\"highlight\"><code>(.*?)</code></pre>", re.S)
# The return type root: the head before a generic bracket/alternative/nullable; allows
# a dotted facet name (Пользователи.Объект).
_RETURN_HEAD_RE = re.compile(r"^\s*([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)?)")


def page_member_types(raw: str) -> dict[str, str]:
    """Page member -> the root of its result type (to infer the type of access chains).

    Signatures sit in code blocks after the H3 headings of the "Методы" (`Имя(...): Тип` -
    the return type) and "Свойства" (`Имя: Тип` - the property type) sections; a member
    whose overloads differ in return is dropped (no common type can be inferred). Inherited
    members carry no signatures on the page and are not collected.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return {}
    out: dict[str, str] = {}
    dropped: set[str] = set()
    for section in _H2_OPEN_RE.split(ma.group(1)):
        head = _plain_text(section[:200])
        is_method = head.startswith("Методы")
        if not is_method and not head.startswith("Свойства"):
            continue
        # Chunks between H3s: the first is the section heading, then one member per chunk.
        parts = _H3_RE.split(section)
        # _H3_RE captures the heading text: parts = [before, name1, body1, name2, body2...]
        for k in range(1, len(parts) - 1, 2):
            name = _plain_text(parts[k])
            if not _PROP_NAME_RE.match(name):
                continue
            body = parts[k + 1]
            for m in _SIG_CODE_RE.finditer(body):
                sig = _plain_text(m.group(1))
                if is_method:
                    paren = sig.rfind("):")
                    tail = sig[paren + 2:] if paren >= 0 else ""
                else:
                    colon = sig.find(":")
                    # a property signature is `Имя: Тип` with the member's own name
                    if colon < 0 or sig[:colon].strip() != name:
                        continue
                    tail = sig[colon + 1:]
                ret = _RETURN_HEAD_RE.match(tail)
                if not ret:
                    continue
                root = ret.group(1)
                if name in dropped:
                    continue
                if name in out and out[name] != root:
                    del out[name]
                    dropped.add(name)  # overloads with differing returns
                elif name not in dropped:
                    out[name] = root
    return out


_H1_OPEN_RE = re.compile(r"<h1[^>]*>")
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)


def package_members(raw: str) -> set[str]:
    """Members of a Стд PACKAGE page (the global context): properties and methods together.

    On package pages (Стд, Стд::Интерфейс...) the sections are H1 headings ("Свойства",
    "Методы") and the members themselves are H2/H3 headings; on type pages the sections are
    H2 (page_members handles those). The first H1 section is the page header and is skipped.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return set()
    out: set[str] = set()
    for section in _H1_OPEN_RE.split(ma.group(1))[1:]:
        head = _plain_text(section[:200])
        if not head.startswith(("Свойства", "Методы")):
            continue
        for m in list(_H2_RE.finditer(section)) + list(_H3_RE.finditer(section)):
            name = _plain_text(m.group(1))
            if _PROP_NAME_RE.match(name):
                out.add(name)
    return out


def _english_from_path(entry: str) -> str | None:
    """The English type name from the `.../<Имя>_ru/index.html` path segment (no dots)."""
    name = _path_name(entry)
    return name if name and "." not in name else None


def _english_facet_from_path(entry: str) -> str | None:
    """The English facet name from the path (`BinaryObject.Reference_ru` -> with a dot)."""
    name = _path_name(entry)
    return name if name and name.count(".") == 1 else None


def _path_name(entry: str) -> str | None:
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    if not dirname.endswith("_ru"):
        return None
    return dirname[:-3] or None


def extract(
    dist: Path,
) -> tuple[
    set[str], dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, set[str]]],
    set[str], dict[str, set[str]], dict[str, dict[str, set[str]]],
]:
    """Stdlib names (bilingual), spawned members by kind, component properties, type members."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    members: dict[str, set[str]] = {}
    components: dict[str, set[str]] = {}
    types: dict[str, dict[str, set[str]]] = {}
    globals_: set[str] = set()
    managers: dict[str, set[str]] = {}
    facets: dict[str, dict[str, set[str]]] = {}
    returns: dict[str, dict[str, str]] = {}
    with zipfile.ZipFile(car) as z:
        entries = z.namelist()
        for n in (e for e in entries if e.startswith(STD_BASE) and e.endswith("/index.html")):
            raw = z.read(n).decode("utf-8", "replace")
            title = ""
            mt = _TITLE_RE.search(raw)
            if mt:
                title = mt.group(1).split("|")[0].strip()
                if title and not title.startswith("1С:"):
                    names.add(title)
            eng = _english_from_path(n)
            if eng:
                names.add(eng)
            # Type members (dot access) under BOTH name forms - to complete globals and types
            # (e.g. КонтекстДоступа./AccessContext., Массив./Array.). "::" (namespaced) names are skipped.
            props, methods = page_members(raw)
            # Global context: the properties and methods of the Стд page itself and of its
            # PACKAGE pages (Стд::Интерфейс, Стд::Данные... - a top-level directory without
            # the _ru suffix) are available in code by bare name (ПерейтиПоСсылке, Сообщить,
            # ЗагрузкаФайлов) - the packages are auto-imported. Package pages have a section
            # structure of their own - package_members parses them.
            rest = n[len(STD_BASE):]
            top = rest.split("/", 1)[0]
            if rest == "index.html" or (rest.count("/") == 1 and not top.endswith("_ru")):
                globals_ |= package_members(raw)
            if props or methods:
                rets = page_member_types(raw)
                for key in (title if _PROP_NAME_RE.match(title) else "", eng or ""):
                    if not key:
                        continue
                    slot = types.setdefault(key, {"properties": set(), "methods": set()})
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    if rets:
                        returns.setdefault(key, {}).update(rets)
                # Entity type facets (Пользователи.Объект, ДвоичныйОбъект.Ссылка): the record
                # and reference members go into a separate dictionary, under both name forms.
                eng_facet = _english_facet_from_path(n)
                for key in (title if _FACET_TITLE_RE.match(title) else "", eng_facet or ""):
                    if not key:
                        continue
                    slot = facets.setdefault(key, {"properties": set(), "methods": set()})
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    if rets:
                        returns.setdefault(key, {}).update(rets)
            got = component_props(n, raw)
            if got is not None:
                comp, props = got
                if comp in components and components[comp] != props:
                    components[comp] &= props  # same-named types: only the indisputable
                else:
                    components[comp] = props
        for n in (e for e in entries if e.startswith(TEMPLATE_BASE) and e.endswith("/index.html")):
            dirname = n[len(TEMPLATE_BASE):].split("/")[0]
            kind = _TEMPLATE_KINDS.get(dirname.split(".")[0].removesuffix("_ru"))
            if kind is None:
                continue  # a kind outside the map
            if "." not in dirname:
                # The template's own page (<Kind>Name_ru) is the kind's MANAGER: its methods
                # (Записать, Заблокировать, НайтиПоКоду...) are available by bare name in
                # the object's manager module.
                raw = z.read(n).decode("utf-8", "replace")
                props, methods = page_members(raw)
                if props or methods:
                    managers.setdefault(kind, set()).update(props | methods)
                continue
            raw = z.read(n).decode("utf-8", "replace")
            mt = _TITLE_RE.search(raw)
            if not mt:
                continue
            segs = mt.group(1).split("|")[0].strip().split(".")
            if len(segs) < 2 or not _CYRILLIC_NAME_RE.match(segs[1]):
                continue  # a placeholder member or a Latin template
            members.setdefault(kind, set()).add(segs[1])
    return names, members, components, types, globals_, managers, facets, returns


def _members_json(members: dict[str, set[str]]) -> dict[str, list[str]]:
    """Type members as JSON: properties and methods separately, an empty section is omitted."""
    return {kind: sorted(members[kind]) for kind in ("properties", "methods") if members.get(kind)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Извлечь каталог типов stdlib Элемента из доков")
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия Элемента (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь stdlib.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    if not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")

    version = _distro.detect_version(dist, args.element_version)
    names, members, components, types, globals_, managers, facets, returns = extract(dist)
    data = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru/stdlib/element/xbsl",
            "count": len(names),
            "note": "двуязычные имена символов stdlib (русское из title + английское из пути)"
                    " + порождаемые члены по видам объектов (шаблонные страницы)"
                    " + встроенные свойства компонентов интерфейса (страницы наследников"
                    " Стд::Интерфейс::Компонент)"
                    " + члены типов (свойства и методы страницы раздельно, под обеими формами имени)",
        },
        "names": sorted(names),
        "object_members": {k: sorted(v) for k, v in sorted(members.items())},
        "component_props": {k: sorted(v) for k, v in sorted(components.items())},
        "type_members": {k: _members_json(v) for k, v in sorted(types.items())},
        # Global context: members of Стд and its first-level packages, available by bare name.
        "globals": sorted(globals_),
        # Kind manager methods (the <Kind>Name_ru template page): bare names in the manager module.
        "manager_members": {k: sorted(v) for k, v in sorted(managers.items())},
        # Entity type facets (Пользователи.Объект, ДвоичныйОбъект.Ссылка): the record and
        # reference members that do not land on the type's own page.
        "facet_members": {k: _members_json(v) for k, v in sorted(facets.items())},
        # Result type roots of members (page signatures: method returns and property types).
        "member_types": {k: dict(sorted(v.items())) for k, v in sorted(returns.items())},
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "stdlib.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  имён stdlib (двуязычно): {len(names)}")
    print(f"  видов с порождаемыми членами: {len(members)}")
    print(f"  компонентов интерфейса со свойствами: {len(components)}")
    print(f"  глобальных имён контекста: {len(globals_)}")
    print(f"  видов с членами менеджера: {len(managers)}")
    print(f"  типов с членами: {len(types)}"
          f" (со свойствами {sum(1 for v in types.values() if v['properties'])},"
          f" с методами {sum(1 for v in types.values() if v['methods'])})")
    print(f"  фасетов сущностных типов: {len(facets)}")
    print(f"  типов с типами членов: {len(returns)}"
          f" (членов с типом: {sum(len(v) for v in returns.values())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
