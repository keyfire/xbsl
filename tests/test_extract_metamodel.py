"""The kind -> root class mapping of the metamodel extractor (build_vid2class).

The mapping used to be hand-written, and a kind added by a new platform build joined it only
if somebody noticed: three kinds of one build did not, and their fully extracted classes stayed
unreachable. Now it follows from the serializer's own kind table, and these tests hold both
halves of that: the derivation rule itself and the promise that the shipped data covers every
kind the platform declares.
"""

import pytest

from xbsl import metamodel, terms
from xbsl.extract.metamodel import build_vid2class

_CLASSES = {
    "CatalogNativeDescriptor": {},
    "HttpServiceDescriptor": {},
    "ComponentModel": {},
    "DataJournalNativeDescriptor": {},
}


def test_native_descriptor_wins_over_plain():
    # both spellings may exist; the native one is the root class of a data kind
    classes = {**_CLASSES, "CatalogDescriptor": {}}
    mapping, unresolved = build_vid2class(classes, {"Справочник": "Catalog"})
    assert mapping == {"Справочник": "CatalogNativeDescriptor"} and not unresolved


def test_plain_descriptor_when_no_native():
    mapping, unresolved = build_vid2class(_CLASSES, {"HttpСервис": "HttpService"})
    assert mapping == {"HttpСервис": "HttpServiceDescriptor"} and not unresolved


def test_exception_overrides_the_rule():
    # the rule would look for InterfaceComponent*Descriptor, which does not exist
    mapping, unresolved = build_vid2class(_CLASSES, {"КомпонентИнтерфейса": "InterfaceComponent"})
    assert mapping == {"КомпонентИнтерфейса": "ComponentModel"} and not unresolved


def test_unresolved_kind_is_reported_not_dropped():
    mapping, unresolved = build_vid2class(_CLASSES, {"НовыйВид": "BrandNewKind"})
    assert mapping == {} and unresolved == ["НовыйВид"]


def test_kind_absent_from_the_table_is_not_invented():
    # a kind the distribution does not declare simply has no entry
    mapping, _ = build_vid2class(_CLASSES, {"ЖурналДанных": "DataJournal"})
    assert mapping == {"ЖурналДанных": "DataJournalNativeDescriptor"}
    assert "Справочник" not in mapping


def test_empty_kind_table_yields_empty_mapping():
    assert build_vid2class(_CLASSES, {}) == ({}, [])


@pytest.mark.needs_data
def test_shipped_data_covers_every_declared_kind():
    """Every kind of the serializer's table is named by the shipped metamodel.

    The guard that was missing: a new build adds a kind, the extractor picks up its class,
    and nothing tells that the kind itself never made it into the mapping - metadata_schema
    answers "no such kind" instead.
    """
    declared = set(terms.kinds_table())
    if not declared:
        pytest.skip("данные собраны экстрактором без таблицы видов")
    known = set(metamodel.kinds())
    assert not declared - known, f"виды без корневого класса: {sorted(declared - known)}"


@pytest.mark.needs_data
def test_kinds_added_by_the_serializer_table_have_properties():
    # the kinds the hand-written mapping had lost: their classes carry properties
    if not terms.kinds_table():
        pytest.skip("данные собраны экстрактором без таблицы видов")
    for kind in ("ЖурналДанных", "ПанельОтчетов", "ПроцессИнтеграции"):
        if kind not in set(metamodel.kinds()):
            continue  # the kind is newer than this data; an older set legitimately has none
        assert metamodel.properties(kind), f"вид {kind} без свойств"
