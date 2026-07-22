"""The stdlib catalog is closed under its own references.

The gap this guards against: a type named by a method return or a property type must
exist in the catalog - otherwise a chain like
СпискиПользователей.ПолучитьСписокПоУмолчанию().НастройкиСервисовУчетныхЗаписей
breaks in completion and in the type rules, and no run ever shows the tear.
Judged over the data, never over CLI output.
"""

from __future__ import annotations

import re

import pytest

from xbsl import dataset

pytestmark = pytest.mark.needs_data

# Type-value heads of member_types that are DELIBERATELY absent from names: template-type
# parameters out of the documentation signatures (ТипЭлемента of ИзменяемыйМассив, ТипКлюча
# of КлючИЗначение) and service forms without pages of their own. A NEW name showing up here
# is a catalog gap, not a reason to quietly grow the list.
KNOWN_UNRESOLVED_HEADS = {
    "EsbForm",
    "InformationSystemsListForm",
    "ТипГраницы",
    "ТипДанных",
    "ТипДанныхИнтервала",
    "ТипДанныхСтроки",
    "ТипДанныхЭлемента",
    "ТипЗаписи",
    "ТипЗначения",
    "ТипИсточника",
    "ТипКлюча",
    "ТипКомпонента",
    "ТипОбъекта",
    "ТипПолейДанных",
    "ТипПоля",
    "ТипРезультата",
    "ТипСерии",
    "ТипЭлемента",
    "ТипЭлементаЛегенды",
    # extractor litter: a literal "неизвестно" instead of a type - a data-cleanup candidate
    "неизвестно",
}


def _head(type_name: str) -> str:
    return re.split(r"[<?]", type_name, maxsplit=1)[0].strip()


@pytest.fixture(scope="module")
def catalog() -> dict:
    return dataset.load_json("stdlib.json")


def test_member_type_heads_resolve(catalog):
    names = set(catalog.get("names") or [])
    unresolved = set()
    for members in (catalog.get("member_types") or {}).values():
        for type_name in members.values():
            head = _head(type_name)
            # a dotted head (ТипИсточника.IdType) is a derivative of a type parameter -
            # its base is judged via the parameter name itself
            if head and "." not in head and head not in names:
                unresolved.add(head)
    new = unresolved - KNOWN_UNRESOLVED_HEADS
    assert not new, f"new unresolved type heads: {sorted(new)}"
    stale = KNOWN_UNRESOLVED_HEADS - unresolved
    assert not stale, (
        f"stale exceptions (the names joined the catalog or left it): {sorted(stale)}"
    )


def test_bases_resolve(catalog):
    names = set(catalog.get("names") or [])
    broken = {
        _head(b)
        for chain in (catalog.get("bases") or {}).values()
        for b in chain
        if _head(b) and _head(b) not in names
    }
    assert not broken, f"base types outside the name catalog: {sorted(broken)}"


# Roots of the object-kind template pages (both language forms): Сущность.Объект is the
# member template for the entities of ANY project - "Сущность" itself is not a code type
# and is deliberately absent from the name catalog.
TEMPLATE_ROOTS = {
    "Сущность", "Entity",
    "ПравоНаДействие", "PrivilegeOnAction",
    "СправочникИнформационныхСистем", "InformationSystemsCatalog",
}


def test_member_owner_keys_resolve(catalog):
    names = set(catalog.get("names") or [])
    for section in ("type_members", "member_types", "facet_members"):
        owners = set(catalog.get(section) or {})
        # facet owners are dotted (Пользователи.Объект) - the root must resolve
        broken = {
            o for o in owners
            if o.split(".", 1)[0] not in names and o.split(".", 1)[0] not in TEMPLATE_ROOTS
        }
        assert not broken, f"{section}: owners outside the name catalog: {sorted(broken)}"


def test_owner_chain_is_alive(catalog):
    # the reported regression: the method return and the property type resolve, and the
    # property's type carries members
    returns = catalog["member_types"]
    got = returns["СпискиПользователей"]["ПолучитьСписокПоУмолчанию"]
    assert got == "СписокПользователей"
    prop = returns["СписокПользователей"]["НастройкиСервисовУчетныхЗаписей"]
    head = _head(prop)
    assert head in set(catalog["names"])
    assert catalog["type_members"][head]["methods"]
