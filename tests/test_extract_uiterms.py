"""Parsing units of xbsl/extract/uiterms.py (the English spellings of the ui vocabulary).

The inputs are synthetic, modeled on the real artifacts of the distribution - a component
description, a source of a predefined project, a class constant pool - so no distribution
and no generated data are needed. Vendors in the fixtures are acme/globex.
"""

import struct

import yaml

from xbsl.extract import uiterms as ut

_COMPONENT = yaml.safe_load("""
type: "ui"
stableId: "Std::Interface::AcmeCard"
namespace:
  en: "Std::Interface::CommonComponents"
  ru: "Стд::Интерфейс::ОбщиеКомпоненты"
term:
  en: "AcmeCard"
  ru: "КарточкаАкме"
properties:
- term:
    en: "SeoDescription"
    ru: "SeoОписание"
  type: "Std::String | Std::Auto"
- term:
  - value:
      en: "InvertPosition"
      ru: "ИнвертироватьРасположение"
    to: 9.0
  - value:
      en: "InvertLocation"
      ru: "ИнвертироватьРасположение"
    from: 9.0
  type: "Std::Boolean"
events:
- term:
    en: "OnRowSelection"
    ru: "ПриВыделенииСтроки"
  parameters:
  - term:
      en: "Source"
      ru: "Источник"
    type: "Std::Interface::Component"
""")

_PROJECT = yaml.safe_load("""
ElementKind: InterfaceComponent
Name:
    En: AcmeRegistration
    Ru: РегистрацияАкме
Inherits:
    Type: Group
Properties:
    -
        Name:
            En: AfterRegistrationUrl
            Ru: UrlПослеРегистрации
        Type: String?
""")


def _class_blob(strings: list[str]) -> bytes:
    """A minimal class file whose constant pool holds the given UTF8 entries."""
    out = bytearray(b"\xca\xfe\xba\xbe" + b"\x00" * 4)
    out += struct.pack(">H", len(strings) + 1)
    for text in strings:
        data = text.encode("utf-8")
        out += b"\x01" + struct.pack(">H", len(data)) + data
    return bytes(out)


def test_current_terms_drops_a_former_spelling():
    prop = _COMPONENT["properties"][1]
    assert ut._current_terms(prop) == [{"en": "InvertLocation", "ru": "ИнвертироватьРасположение"}]
    # a plain term is taken as it is
    assert ut._current_terms(_COMPONENT["properties"][0])[0]["en"] == "SeoDescription"


def test_walk_terms_separates_the_type_from_the_names_below_it():
    names: dict = {}
    types: dict = {}
    ut._walk_terms(_COMPONENT, names, types)
    assert ut._unambiguous(types) == {"AcmeCard": "КарточкаАкме"}
    assert ut._unambiguous(names) == {
        "InvertLocation": "ИнвертироватьРасположение",
        "OnRowSelection": "ПриВыделенииСтроки",
        "SeoDescription": "SeoОписание",
        "Source": "Источник",  # a parameter of an event is a name like any other
    }


def test_walk_project_names_reads_the_bilingual_name():
    names: dict = {}
    ut._walk_project_names(_PROJECT, names)
    assert ut._unambiguous(names) == {
        "AcmeRegistration": "РегистрацияАкме",
        "AfterRegistrationUrl": "UrlПослеРегистрации",
    }


def test_unambiguous_drops_an_english_name_with_two_russian_ones():
    votes: dict = {}
    ut._walk_project_names(
        {"Name": {"En": "Name", "Ru": "Имя"}, "x": {"Name": {"En": "Name", "Ru": "Наименование"}}},
        votes,
    )
    assert ut._unambiguous(votes) == {}


def test_enum_name_from_the_manifest():
    record = {"nameRu": "Стд::Интерфейс::ВажностьКоманды", "name": "CommandImportance"}
    assert ut._enum_name(record, None, "CommandImportance") == "ВажностьКоманды"


def test_enum_name_falls_back_to_the_type_class():
    # the manifest lists only part of the enumerations; the type class carries its own pair
    blob = _class_blob(["EventLogEventImportance", "ВажностьСобытияЖурналаСобытий"])
    name = ut._enum_name(None, blob, "EventLogEventImportance")
    assert name == "ВажностьСобытияЖурналаСобытий"


def test_enum_name_unknown_stays_none():
    assert ut._enum_name(None, None, "Whatever") is None
    assert ut._enum_name(None, _class_blob(["Other", "Другое"]), "Whatever") is None


def test_enum_pairs_reads_the_values_of_a_pool():
    blob = _class_blob([
        "java/lang/IllegalArgumentException",
        "Low", "Низкая", "677ba2cb-8dbc-4cd3-b0ca-cc58a3800b06",
        "Normal", "Обычная", "1dc2b423-5ded-4ae2-a19b-2e3f0ba883d3",
    ])
    assert ut.enum_pairs(blob) == {"Низкая": "Low", "Обычная": "Normal"}
