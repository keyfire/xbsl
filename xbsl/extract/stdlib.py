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
Two kinds of redundancy are removed at extraction and restored on load, so the file stays small
without the consumers changing:
- only a type's OWN members are stored (meta.members == "own"); the "Иерархия типа" section gives
  the whole ancestor chain in `bases`, and the loader rebuilds the full set by adding every
  ancestor's own - the object protocol is not repeated on all 2000 types;
- members, bases and facets are stored under ONE name form (meta.bilingual_keys == "expand"); the
  loader adds the English key of each from terms.json, so a type is not stored twice (Запрос/Query).
Both are done by dataset._add_english_keys + dataset._expand_inherited.

The result is xbsl/data/element/<version>/stdlib.json:
{ "names": [...], "object_members": {"Справочник": [...], ...},
  "component_props": {"СтандартнаяКарточка": [...], ...},
  "type_members": {"Массив": {"methods": [...]}, "СтандартнаяКарточка": {"properties": [...]}} }.
The version is detected from the distribution automatically (or set with --element-version).
"""

from __future__ import annotations

import argparse
import html
import json
import re
import zipfile
from pathlib import Path

from xbsl.dataset import MEMBER_KINDS
from xbsl.extract import _distro

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"
TEMPLATE_BASE = "data/docs/help/ru/stdlib/element/xbsl/DeveloperName/ProjectName/SubsystemName/"

# Platform surfaces the documentation describes only in guide topics, with no stdlib type
# page of their own - the page walk in extract() cannot see them, and yaml/unknown-type
# would flag legitimate code. Curated, not scraped: every entry cites its evidence, and
# both name forms are listed (the pair is the compiler's own, taken from its metaobject
# terms, never a translation guess).
#
# ФормаОбсужденийСистемыВзаимодействия - the Collaboration System conversations form:
# "специальный компонент" of the guide topic create-and-obtain-conversations (used both
# as a component Тип and as a navigation ТипФормы); the compiler carries the dedicated
# CollaborationSystemConversationsForm* packages in its metaobject terms.
TOPIC_ONLY_TYPES = frozenset({
    "ФормаОбсужденийСистемыВзаимодействия",
    "CollaborationSystemConversationsForm",
})
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_CYRILLIC_NAME_RE = re.compile(r"^[А-ЯЁ][А-Яа-яЁё0-9]*$")

# Parsing a component page: content is in <article>, sections are H2 headings, own properties
# are H3 headings, inherited ones are links to the base type's properties.
COMPONENT_BASE = "Стд::Интерфейс::Компонент"
COMPONENT_PAGE = STD_BASE + "Interface/Component_ru/index.html"
# Newer distributions list the base types as links with UNQUALIFIED texts ("Компонент"
# instead of "Стд::Интерфейс::Компонент") - the link target is the stable marker then.
COMPONENT_HREF = "/Std/Interface/Component_ru/"
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
    among the bases - as the qualified text or as a link to the Компонент page (newer
    distributions drop the qualification from the link text) - plus the page of Компонент
    itself (its only base is Объект). The property set is complete: own ones (H3s of the
    "Свойства" section) together with the inherited ones (link texts of the "Список
    унаследованных свойств" sections) - no need to resolve the inheritance chain.
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
            if COMPONENT_BASE in _plain_text(section) or COMPONENT_HREF in section:
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


def page_members(raw: str) -> tuple[set[str], set[str], set[str]]:
    """Type members for dot completion: (properties, methods, events).

    Own members are the H3 headings of the "Свойства" / "Методы" / "События" sections,
    inherited ones are the link texts of the matching "Список унаследованных ..." sections
    (H3s there are base type names, not members). Constructors, literals and the hierarchy do
    not count.

    Most stdlib types have no properties at all (in Element even Длина() is a method); the
    "Свойства" section mostly belongs to interface components and record types.

    EVENTS have a section of their own, and reading only the two others cost a false alarm:
    the diff of two data versions reported dozens of members as REMOVED (a Button without its
    OnClick, an HtmlContainer without its AfterContentLoad) because the newer documents moved
    the events out of the properties section - the API had not changed at all.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return set(), set(), set()
    props: set[str] = set()
    methods: set[str] = set()
    events: set[str] = set()
    # The longest heading first: the inherited-events heading starts with the same words as
    # the inherited-properties one, and the events heading must not be read as a property section.
    inherited = (("Список унаследованных методов", methods),
                 ("Список унаследованных событий", events),
                 ("Список унаследованных свойств", props))
    own = (("Методы", methods), ("События", events), ("Свойства", props))
    for section in _H2_OPEN_RE.split(ma.group(1)):
        head = _plain_text(section[:200])
        target = next((t for prefix, t in inherited if head.startswith(prefix)), None)
        if target is not None:
            found = (_plain_text(m.group(1)) for m in _LINK_RE.finditer(section))
        else:
            target = next((t for prefix, t in own if head.startswith(prefix)), None)
            if target is None:
                continue
            found = (_plain_text(m.group(1)) for m in _H3_RE.finditer(section))
        target.update(name for name in found if _PROP_NAME_RE.match(name))
    # A name the page ALSO lists as a property or a method is not an event, whatever the
    # heading it appeared under. Some pages state the inherited PROPERTIES under the
    # inherited-events heading (the links there point at the property anchors of the base) -
    # observed on the list and diagram components. Copying that verbatim would put a dozen
    # sizing properties among the events of every such type.
    return props, methods, events - props - methods


def page_bases(raw: str) -> list[str]:
    """Base types of a page, from its "Иерархия типа" section.

    The section lists the WHOLE ancestor chain (`Исключение, Объект` for an exception),
    so nothing has to be resolved afterwards. Names are taken unqualified: the page prints
    them as links, and a qualified `Стд::Интерфейс::Компонент` only shows up in the plain
    text of the section. "Дочерние типы" are a separate subsection and are not bases -
    the reason the search stops at the first heading after the bases list.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return []
    for section in _H2_OPEN_RE.split(ma.group(1)):
        if not _plain_text(section[:200]).startswith("Иерархия типа"):
            continue
        head, _, _rest = section.partition("Дочерние типы")
        bases: list[str] = []
        for m in _LINK_RE.finditer(head):
            name = _plain_text(m.group(1))
            if _PROP_NAME_RE.match(name) and name not in bases:
                bases.append(name)
        return bases
    return []


# The signature in the code block after a method's H3 heading: `Имя(Параметры): ТипВозврата`.
_SIG_CODE_RE = re.compile(r"<pre class=\"highlight\"><code>(.*?)</code></pre>", re.S)
# The return type root: the head before a generic bracket/alternative/nullable; allows
# a dotted facet name (Пользователи.Объект).
_RETURN_HEAD_RE = re.compile(r"^\s*([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)?)")
# The full spelling of a result type: the head plus a generic parameter (one or two nesting
# levels), the nullable marker AND the alternatives of a union - what the docs signature
# actually prints (`Авто|Булево`, `Булево|ОбъектJs|Число|Строка|?`). The union matters to the
# consumers: a value of type `Булево` and a value of type `Авто|Булево` are checked in code
# differently, and by the head alone they are indistinguishable. A lone `?` is a legal
# alternative (the docs write "or nothing"), so it is matched as one.
_ALTERNATIVE = (
    r"(?:[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)?"
    r"(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>)?\??|\?)"
)
_RETURN_FULL_RE = re.compile(r"^\s*(" + _ALTERNATIVE + r"(?:\s*\|\s*" + _ALTERNATIVE + r")*)")


#: How a type can be constructed, from the constructors section of its page (see
#: page_constructors).
CTOR_EMPTY = "empty"
CTOR_ARGS = "args"
CTOR_NONE = "none"
#: Two types from different packages may share a bare name (a `WebChat` value type and the
#: interface component of the same name, a `Geofence` of the geolocation package and the one
#: of the maps) - the catalog is keyed by that name and cannot tell them apart. The kinds
#: collapse to the most PERMISSIVE of the two, the one that makes the consumers keep quiet: a
#: type that can be constructed empty must never be reported as one that cannot.
CTOR_RANK = {CTOR_NONE: 0, CTOR_ARGS: 1, CTOR_EMPTY: 2}
# Parameters of a signature, split at the top level only: a generic argument carries commas
# of its own (`Map<String, Number>`) and must not break the parameter list apart.
_PARAM_SPLIT_RE = re.compile(r",(?![^<>]*>)")


def page_constructors(raw: str, title: str) -> str:
    """How the type is constructed: CTOR_EMPTY / CTOR_ARGS / CTOR_NONE.

    The constructors section holds one H3 per overload, and under it the signature in a code
    block - the same layout the methods use. A signature that can be called with NO arguments
    (empty parentheses, or every parameter with a default value) makes the type
    default-constructible: the argument-less `Array()` is why a field typed `Array<String>`
    needs no initializer. `ReadableArray` is the opposite case - a constructor exists, but it
    copies an `Iterable` and none can be called empty, so the compiler refuses to initialize
    a field or a variable of that type ("cannot be initialized with a default value").
    CTOR_NONE means the documentation lists no constructor at all - the type is only ever
    obtained from the platform (`HttpResponse`).

    Not the same as "has a default value": a primitive (`String`, `Boolean`, `Date`) has one
    although its only constructor takes arguments. The consumers narrow accordingly - the
    fact answers the constructor question alone.

    Only the FIRST code block under each H3 is the signature; the ones that follow belong to
    the examples subsection and would otherwise be read as overloads. Section and heading
    texts are matched in Russian because the documentation of the distribution is Russian-only.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return CTOR_NONE
    seen = False
    for section in _H2_OPEN_RE.split(ma.group(1)):
        if not _plain_text(section[:200]).startswith("Конструктор"):
            continue
        parts = _H3_RE.split(section)
        for k in range(1, len(parts) - 1, 2):
            if _plain_text(parts[k]) != title:
                continue  # an overload heading always repeats the type name
            m = _SIG_CODE_RE.search(parts[k + 1])
            if m is None:
                continue
            sig = html.unescape(_plain_text(m.group(1)))
            open_paren, close_paren = sig.find("("), sig.rfind(")")
            if open_paren < 0 or close_paren < open_paren:
                continue
            seen = True
            params = [p for p in _PARAM_SPLIT_RE.split(sig[open_paren + 1:close_paren]) if p.strip()]
            if not params or all("=" in p for p in params):
                return CTOR_EMPTY
    return CTOR_ARGS if seen else CTOR_NONE


def page_member_types(raw: str) -> dict[str, str]:
    """Page member -> its result type (to infer the type of access chains).

    Signatures sit in code blocks after the H3 headings of the "Методы" (`Имя(...): Тип` -
    the return type) and "Свойства" (`Имя: Тип` - the property type) sections. The FULL
    docs spelling is stored (the generic parameter included - `ЧитаемоеМножество<Настройки>`
    keeps what `.Первый()` would answer); the consumers cut the nominal head at lookup
    (dataset.member_type_head). Overloads that agree on the head alone degrade to the head,
    overloads with differing heads drop the member (no common type can be inferred).
    Inherited members carry no signatures on the page and are not collected.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return {}
    out: dict[str, str] = {}
    heads: dict[str, str] = {}
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
                # The signature encodes the generic brackets as entities (&lt;/&gt;), with
                # every type name wrapped in a link the tag-stripping already removed -
                # unescape, or the full spelling silently degrades to the head.
                tail = html.unescape(tail)
                ret = _RETURN_HEAD_RE.match(tail)
                if not ret:
                    continue
                root = ret.group(1)
                mf = _RETURN_FULL_RE.match(tail)
                full = (mf.group(1) if mf else root).strip()
                if name in dropped:
                    continue
                if name in out:
                    if heads[name] != root:
                        del out[name]
                        del heads[name]
                        dropped.add(name)  # overloads with differing returns
                    elif out[name] != full:
                        out[name] = root  # the head is shared, the parameters differ
                else:
                    out[name] = full
                    heads[name] = root
    return out


#: A comma of a parameter list that the documentation prints without a space after it.
_TIGHT_COMMA_RE = re.compile(r",(?=\S)")


def page_member_signatures(raw: str) -> dict[str, list[str]]:
    """Method -> the signatures the page prints, one string per overload, in page order.

    The result type alone (`page_member_types`) answers the inference but not the question a
    reader has in front of a method - what do I pass? The parameters are printed in the very
    same code block, so they cost no extra page: a block counts as a signature when it opens
    with the member's own name and a parenthesis, which leaves the example blocks under the
    same heading out (those open with `знч` or a call of something else).

    Overloads are separate H3 headings of the same name (`КонтекстДоступа.Дополнить` has
    two), so the strings simply accumulate; identical ones collapse. The docs print the list
    without a space after the comma - that is a rendering artifact of the page, not the
    platform's spelling, and it is normalized here so the hover card reads like code.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return {}
    out: dict[str, list[str]] = {}
    for section in _H2_OPEN_RE.split(ma.group(1)):
        if not _plain_text(section[:200]).startswith("Методы"):
            continue
        parts = _H3_RE.split(section)
        for k in range(1, len(parts) - 1, 2):
            name = _plain_text(parts[k])
            if not _PROP_NAME_RE.match(name):
                continue
            for m in _SIG_CODE_RE.finditer(parts[k + 1]):
                text = _TIGHT_COMMA_RE.sub(", ", html.unescape(_plain_text(m.group(1))).strip())
                if not text.startswith(name + "("):
                    continue
                found = out.setdefault(name, [])
                if text not in found:
                    found.append(text)
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


# The availability line right under a member heading: `Доступность: Клиент`. The longest
# alternative goes first - `Клиент` is a prefix of `КлиентИСервер`.
_AVAILABILITY_RE = re.compile(r"Доступность:\s*(КлиентИСервер|Клиент|Сервер)")

# Both member heading levels of a package page, split with the heading text captured.
_H23_SPLIT_RE = re.compile(r"<h[23][^>]*>(.*?)</h[23]>", re.S)


def package_member_availability(raw: str) -> dict[str, str]:
    """Member of a package page -> its availability (Клиент / Сервер / КлиентИСервер).

    The docs print availability per member, right under its heading (`<h3>Сообщить</h3>
    <p><code>Доступность: Клиент</code></p>`) - the page-level column of docs.sqlite shows
    the first member's value, not the package's, so the per-member read is the only correct
    one. A member whose chunk names no availability is left out rather than guessed.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return {}
    out: dict[str, str] = {}
    for section in _H1_OPEN_RE.split(ma.group(1))[1:]:
        head = _plain_text(section[:200])
        if not head.startswith(("Свойства", "Методы")):
            continue
        parts = _H23_SPLIT_RE.split(section)
        # parts = [before, name1, body1, name2, body2, ...]
        for k in range(1, len(parts) - 1, 2):
            name = _plain_text(parts[k])
            if not _PROP_NAME_RE.match(name):
                continue
            m = _AVAILABILITY_RE.search(parts[k + 1])
            if m:
                out[name] = m.group(1)
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


def _merge_signatures(into: dict[str, list[str]], found: dict[str, list[str]]) -> None:
    """Add the signatures of one page to a type's set, keeping order and dropping repeats.

    A type is described by more than one page when its name is shared (a value type and an
    interface component of the same spelling), so the lists are merged rather than replaced.
    """
    for member, sigs in found.items():
        slot = into.setdefault(member, [])
        slot.extend(sig for sig in sigs if sig not in slot)


def extract(dist: Path) -> tuple:
    """Stdlib names (bilingual), spawned members by kind, component properties, type members,
    the global context with per-name availability, managers, facets, member types, bases and
    constructor kinds - the tuple main() unpacks."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    members: dict[str, set[str]] = {}
    components: dict[str, set[str]] = {}
    types: dict[str, dict[str, set[str]]] = {}
    globals_: set[str] = set()
    global_env: dict[str, str] = {}
    conflicted_env: set[str] = set()
    managers: dict[str, set[str]] = {}
    facets: dict[str, dict[str, set[str]]] = {}
    returns: dict[str, dict[str, str]] = {}
    signatures: dict[str, dict[str, list[str]]] = {}
    bases: dict[str, list[str]] = {}
    ctors: dict[str, str] = {}
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
            props, methods, events = page_members(raw)
            # One key per type - the Russian title (or the Latin one for a type that has no
            # Russian name). The English spelling is not stored: the loader adds it by terms.json,
            # which pairs the two forms. So members, bases and facets are kept once, not twice.
            key = (title if _PROP_NAME_RE.match(title) else "") or eng or ""
            # Иерархия: страница печатает ВСЮ цепочку предков, разворачивать нечего.
            page_base_list = page_bases(raw)
            if page_base_list and key:
                bases.setdefault(key, page_base_list)
            if key and title:
                kind = page_constructors(raw, title)
                if CTOR_RANK[kind] >= CTOR_RANK.get(ctors.get(key, CTOR_NONE), 0):
                    ctors[key] = kind
            # Global context: the properties and methods of the Стд page itself and of its
            # PACKAGE pages (Стд::Интерфейс, Стд::Данные... - a top-level directory without
            # the _ru suffix) are available in code by bare name (ПерейтиПоСсылке, Сообщить,
            # ЗагрузкаФайлов) - the packages are auto-imported. Package pages have a section
            # structure of their own - package_members parses them.
            rest = n[len(STD_BASE):]
            top = rest.split("/", 1)[0]
            if rest == "index.html" or (rest.count("/") == 1 and not top.endswith("_ru")):
                globals_ |= package_members(raw)
                for member, env in package_member_availability(raw).items():
                    # A name two packages give different environments is unjudgeable.
                    if global_env.setdefault(member, env) != env:
                        conflicted_env.add(member)
            if props or methods or events:
                rets = page_member_types(raw)
                sigs = page_member_signatures(raw)
                if key:
                    slot = types.setdefault(key, _empty_member_slot())
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    slot["events"] |= events
                    if rets:
                        returns.setdefault(key, {}).update(rets)
                    if sigs:
                        _merge_signatures(signatures.setdefault(key, {}), sigs)
                # Entity type facets (Пользователи.Объект, ДвоичныйОбъект.Ссылка): the record
                # and reference members go into a separate dictionary, under the Russian form.
                facet_key = (title if _FACET_TITLE_RE.match(title) else "") or _english_facet_from_path(n)
                if facet_key:
                    slot = facets.setdefault(facet_key, _empty_member_slot())
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    slot["events"] |= events
                    if rets:
                        returns.setdefault(facet_key, {}).update(rets)
                    if sigs:
                        _merge_signatures(signatures.setdefault(facet_key, {}), sigs)
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
                props, methods, events = page_members(raw)
                if props or methods:
                    # A manager has no events; nothing is dropped silently - the pages of the
                    # kinds carry none, and an event there would show up in the diff.
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
    names |= TOPIC_ONLY_TYPES
    for member in conflicted_env:
        global_env.pop(member, None)
    return (names, members, components, types, globals_, global_env, managers, facets,
            returns, signatures, bases, ctors)


def _empty_member_slot() -> dict[str, set[str]]:
    return {kind: set() for kind in MEMBER_KINDS}


def _members_json(members: dict[str, set[str]]) -> dict[str, list[str]]:
    """Type members as JSON: by kind, an empty section is omitted."""
    return {kind: sorted(members[kind]) for kind in MEMBER_KINDS if members.get(kind)}


def _own_members(
    types: dict[str, dict[str, set[str]]],
    returns: dict[str, dict[str, str]],
    signatures: dict[str, dict[str, list[str]]],
    bases: dict[str, list[str]],
) -> tuple[dict[str, dict[str, set[str]]], dict[str, dict[str, str]], dict[str, dict[str, list[str]]]]:
    """Strip inherited members, leaving only each type's own - the loader re-expands them.

    `bases` is the transitively closed ancestor list, so subtracting every ancestor's FULL
    set leaves exactly the members a type does not inherit. A member a type overrides with a
    different result type stays (its type differs from the ancestor's) - that is why
    member_types is compared by value, not just by name.
    """
    own_types: dict[str, dict[str, set[str]]] = {}
    for name, sets in types.items():
        inherited = {kind: set() for kind in MEMBER_KINDS}
        for base in bases.get(name, ()):
            for kind in MEMBER_KINDS:
                inherited[kind] |= types.get(base, {}).get(kind, set())
        own_types[name] = {
            kind: sets.get(kind, set()) - inherited[kind] for kind in MEMBER_KINDS
        }
    own_returns: dict[str, dict[str, str]] = {}
    for name, member_types in returns.items():
        inherited = {}
        for base in bases.get(name, ()):
            inherited.update(returns.get(base, {}))
        own_returns[name] = {
            member: rtype for member, rtype in member_types.items()
            if inherited.get(member) != rtype
        }
    own_signatures: dict[str, dict[str, list[str]]] = {}
    for name, member_sigs in signatures.items():
        inherited_sigs: dict[str, list[str]] = {}
        for base in bases.get(name, ()):
            inherited_sigs.update(signatures.get(base, {}))
        own_signatures[name] = {
            member: sigs for member, sigs in member_sigs.items()
            if inherited_sigs.get(member) != sigs
        }
    return own_types, own_returns, own_signatures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.stdlib"),
        description="Извлечь каталог типов stdlib Элемента из доков",
    )
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
    (names, members, components, types, globals_, global_env, managers, facets, returns,
     signatures, bases, ctors) = extract(dist)
    # Store only OWN members, not the full set: an inherited member (the object protocol on
    # every type, an exception's fields on every exception) would otherwise be repeated once
    # per heir. The loader re-expands them by `bases` - a member set is completed by adding
    # every ancestor's own set. This also fills the pages the docs left incomplete (a heir
    # that fails to list a member its base owns still gets it back on expansion).
    own_types, own_returns, own_signatures = _own_members(types, returns, signatures, bases)
    data = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru/stdlib/element/xbsl",
            "count": len(names),
            # The loader expands type_members/member_types only when this marker is present -
            # older full datasets (without it) are read as is.
            "members": "own",
            # Members/bases/facets are stored under one name form; the loader adds the English
            # keys from terms.json. Older datasets without this marker carry both forms already.
            "bilingual_keys": "expand",
            "note": "двуязычные имена символов stdlib (русское из title + английское из пути)"
                    " + порождаемые члены по видам объектов (шаблонные страницы)"
                    " + встроенные свойства компонентов интерфейса (страницы наследников"
                    " Стд::Интерфейс::Компонент)"
                    " + СОБСТВЕННЫЕ члены типов (унаследованные разворачиваются по bases"
                    " при загрузке), под обеими формами имени"
                    " + типы, описанные только в topics-страницах (TOPIC_ONLY_TYPES)",
        },
        "names": sorted(names),
        "object_members": {k: sorted(v) for k, v in sorted(members.items())},
        "component_props": {k: sorted(v) for k, v in sorted(components.items())},
        "type_members": {k: _members_json(v) for k, v in sorted(own_types.items())},
        # Global context: members of Стд and its first-level packages, available by bare name.
        "globals": sorted(globals_),
        # The environment a global name exists in (the member's own "Доступность" line of
        # its package page): Клиент / Сервер / КлиентИСервер. A name whose availability the
        # docs do not print, or print differently in two packages, is absent here.
        "global_availability": dict(sorted(global_env.items())),
        # Kind manager methods (the <Kind>Name_ru template page): bare names in the manager module.
        "manager_members": {k: sorted(v) for k, v in sorted(managers.items())},
        # Entity type facets (Пользователи.Объект, ДвоичныйОбъект.Ссылка): the record and
        # reference members that do not land on the type's own page.
        "facet_members": {k: _members_json(v) for k, v in sorted(facets.items())},
        # Result type roots of members (page signatures: method returns and property types).
        "member_types": {k: dict(sorted(v.items())) for k, v in sorted(own_returns.items())},
        # Method signatures as the page prints them, one string per overload: what the result
        # type alone cannot answer - which parameters to pass. Only methods have them.
        "member_signatures": {
            k: dict(sorted(v.items())) for k, v in sorted(own_signatures.items()) if v
        },
        # Type hierarchy: the WHOLE ancestor chain a page prints under "Иерархия типа", so a
        # check needs no resolution of its own - `"Исключение" in bases[type]` decides.
        "bases": {k: v for k, v in sorted(bases.items())},
        # How the type is constructed (page_constructors): "empty" - a constructor callable
        # with no arguments, "args" - constructors that all demand arguments, "none" - the
        # documentation lists none at all. A field or a variable of a type that is not
        # "empty" cannot be left uninitialized unless the type has a default value of its
        # own (a primitive does, a collection does not).
        "type_ctors": {k: v for k, v in sorted(ctors.items())},
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
    print(f"  глобальных имён контекста: {len(globals_)}"
          f" (с доступностью: {len(global_env)})")
    print(f"  видов с членами менеджера: {len(managers)}")
    print(f"  типов с членами: {len(types)}"
          f" (со свойствами {sum(1 for v in types.values() if v['properties'])},"
          f" с методами {sum(1 for v in types.values() if v['methods'])})")
    print(f"  фасетов сущностных типов: {len(facets)}")
    print(f"  типов с типами членов: {len(returns)}"
          f" (членов с типом: {sum(len(v) for v in returns.values())})")
    print(f"  типов с сигнатурами методов: {len(signatures)}"
          f" (методов: {sum(len(v) for v in signatures.values())},"
          f" перегрузок: {sum(len(s) for v in signatures.values() for s in v.values())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
