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


def test_enum_pairs_follows_the_declared_order_of_the_fields():
    """A class whose constructor takes the Russian name first is read the other way round.

    Read with the English always in front, such an enumeration came out shifted by one value
    - a json node kind answered its boolean with `Null` - and its last value lost the pair.
    """
    blob = _class_blob([
        "ruName", "enName",
        "НеЗаписывать", "NotWrite",
        "ЗаписыватьВсегда", "AlwaysWrite",
    ])

    assert ut.enum_pairs(blob) == {
        "НеЗаписывать": "NotWrite", "ЗаписыватьВсегда": "AlwaysWrite",
    }


def test_enum_pairs_keeps_the_english_first_reading_by_default():
    """Negative control: with `enName` in front (or neither name at all) nothing changes."""
    values = ["Low", "Низкая", "Normal", "Обычная"]
    assert ut.enum_pairs(_class_blob(["enName", "ruName", *values])) == {
        "Низкая": "Low", "Обычная": "Normal",
    }
    assert ut.enum_pairs(_class_blob(values)) == {"Низкая": "Low", "Обычная": "Normal"}


# --- the name a type class states for the enumeration it lists -------------------------------

#: How a type class builds its qualified name: the namespace, then the two spellings.
_QNAMES = "demo/utils/QNames.create"
_ENUM = "demo/acme/AcmePrivilegeG5Enum"


def _type_class(field: str = "TYPE_NAME", classes: tuple[str, ...] = (_ENUM,),
                spellings: tuple[str, str] = ("Acme.Privilege", "Акме.Право")) -> bytes:
    from test_extract_classcode import _class_of_terms

    return _class_of_terms([(field, _QNAMES, list(spellings))],
                           this="demo/acme/AcmePrivilegeG5Type", classes=classes)


def test_enum_name_reads_the_type_name_its_type_class_states():
    """A facet of the generic entity lists its values as an enumeration class, and the type
    class next to it states the public name as a qualified pair. Neither the manifest nor the
    adjacency reading names it: the English side is dotted, so no identifier matches."""
    assert ut._enum_name(None, _type_class(), "AcmePrivilege") == "Акме.Право"


def test_a_type_name_counts_only_for_the_exact_sibling_enumeration():
    """The type class has to refer to the enumeration of its own package and stem: a class of
    the same simple name elsewhere, another enumeration, or no reference at all is not proof
    that the stated name is the name of these values."""
    elsewhere = _type_class(classes=("demo/other/AcmePrivilegeG5Enum",))
    another = _type_class(classes=("demo/acme/AcmeRoleG5Enum",))
    none = _type_class(classes=())

    assert ut._enum_name(None, elsewhere, "AcmePrivilege") is None
    assert ut._enum_name(None, another, "AcmePrivilege") is None
    assert ut._enum_name(None, none, "AcmePrivilege") is None


def test_only_the_type_name_field_names_the_enumeration():
    blob = _type_class(field="PRIVILEGE_PROPERTY_TERM")

    assert ut._enum_name(None, blob, "AcmePrivilege") is None


def test_the_manifest_still_names_the_enumeration_first():
    record = {"nameRu": "Стд::Акме::ПравоАкме", "name": "AcmePrivilege"}

    assert ut._enum_name(record, _type_class(), "AcmePrivilege") == "ПравоАкме"


def test_collect_files_the_values_under_the_qualified_public_owner(tmp_path):
    """The whole walk: the values land under the qualified Russian name, the table the
    translator asks by the full owner of a chain (`Акме.Право.Чтение`)."""
    import io
    import zipfile

    values = _class_blob(["Read", "Чтение", "Create", "Создание"])
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr(_ENUM + ".class", values)
        z.writestr("demo/acme/AcmePrivilegeG5Type.class", _type_class())
    with zipfile.ZipFile(tmp_path / "acme-element-server-with-ide-1.0.0.car", "w") as car:
        car.writestr("data/lib/com.e1c.g5rt.demo-1.0.jar", jar.getvalue())

    found = ut.collect(tmp_path)["enum_values"]

    assert found["Акме.Право"] == {"Чтение": "Read", "Создание": "Create"}
    assert "Право" not in found


# --- the pictures of the platform's library ---------------------------------------------------

_RU = "Icons/Стд/Ресурсы/"
_EN = "Icons/Std/Resources/"


def test_a_picture_pairs_with_its_twin_of_the_same_bytes():
    found = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg id='acme'/>"),
        (_EN + "Acme.svg", b"<svg id='acme'/>"),
        (_RU + "Глобекс.svg", b"<svg id='globex'/>"),
        (_EN + "Globex.svg", b"<svg id='globex'/>"),
    ])

    assert found["pairs"] == {_RU + "Акме.svg": _EN + "Acme.svg",
                              _RU + "Глобекс.svg": _EN + "Globex.svg"}
    assert found["conflicts"] == {} and found["ambiguous"] == [] and found["unmatched"] == []


def test_copies_of_one_picture_in_several_jars_collapse_into_one_pair():
    """The server, the designer and the language server each ship the library: the same path
    with the same bytes is one picture, not three."""
    copies = [(_RU + "Акме.svg", b"<svg/>"), (_EN + "Acme.svg", b"<svg/>")] * 3

    found = ut.pair_pictures(copies)

    assert found["pairs"] == {_RU + "Акме.svg": _EN + "Acme.svg"}
    assert found["instances"] == 6
    assert found["conflicts"] == {} and found["ambiguous"] == []


def test_one_content_under_several_names_pairs_none_of_them():
    """Two Russian names drawn the same, or two English ones: which name answers which is
    not written anywhere, so none is paired - neither by order nor by resemblance."""
    two_to_one = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg a/>"), (_RU + "АкмеКопия.svg", b"<svg a/>"),
        (_EN + "Acme.svg", b"<svg a/>"),
    ])
    one_to_two = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg b/>"),
        (_EN + "Acme.svg", b"<svg b/>"), (_EN + "AcmeCopy.svg", b"<svg b/>"),
    ])
    two_to_two = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg c/>"), (_RU + "Глобекс.svg", b"<svg c/>"),
        (_EN + "Acme.svg", b"<svg c/>"), (_EN + "Globex.svg", b"<svg c/>"),
    ])

    for found in (two_to_one, one_to_two, two_to_two):
        assert found["pairs"] == {}
        assert len(found["ambiguous"]) == 1 and found["unmatched"] == []
    assert two_to_one["ambiguous"][0]["ru"] == [_RU + "Акме.svg", _RU + "АкмеКопия.svg"]
    assert two_to_one["ambiguous"][0]["en"] == [_EN + "Acme.svg"]


def test_a_picture_without_a_twin_stays_unpaired():
    found = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg ru/>"),
        (_EN + "Globex.svg", b"<svg en/>"),
    ])

    assert found["pairs"] == {}
    assert sorted((group["ru"], group["en"]) for group in found["unmatched"]) == [
        ([], [_EN + "Globex.svg"]), ([_RU + "Акме.svg"], []),
    ]


def test_a_path_whose_copies_differ_is_left_out_whole():
    """One jar ships another drawing under the same name: no copy is preferred, the path is
    reported and its would-be twin stays without a pair."""
    found = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg old/>"),
        (_RU + "Акме.svg", b"<svg new/>"),
        (_EN + "Acme.svg", b"<svg new/>"),
    ])

    assert found["pairs"] == {}
    assert list(found["conflicts"]) == [_RU + "Акме.svg"]
    assert len(found["conflicts"][_RU + "Акме.svg"]) == 2
    assert found["unmatched"] == [
        {"sha256": found["unmatched"][0]["sha256"], "ru": [], "en": [_EN + "Acme.svg"]},
    ]


def test_the_bytes_are_compared_as_shipped():
    """No normalization: a drawing that differs by a line break is another drawing."""
    found = ut.pair_pictures([
        (_RU + "Акме.svg", b"<svg/>"),
        (_EN + "Acme.svg", b"<svg/>\n"),
    ])

    assert found["pairs"] == {}
    assert len(found["unmatched"]) == 2


def test_no_pictures_give_an_empty_table():
    found = ut.pair_pictures([])

    assert found == {"pairs": {}, "conflicts": {}, "ambiguous": [], "unmatched": [],
                     "instances": 0}


def _car_with_jars(root, *jars: dict[str, bytes]) -> None:
    import io
    import zipfile

    with zipfile.ZipFile(root / "acme-element-server-with-ide-1.0.0.car", "w") as car:
        for number, members in enumerate(jars):
            jar = io.BytesIO()
            with zipfile.ZipFile(jar, "w") as z:
                for member, blob in members.items():
                    z.writestr(member, blob)
            car.writestr(f"data/lib/com.e1c.g5rt.demo{number}-1.0.jar", jar.getvalue())


def test_collect_pairs_only_the_pictures_of_the_two_library_folders(tmp_path):
    """Only a picture below `Icons/Стд/Ресурсы` or `Icons/Std/Resources` is the library's: a
    drawing of the same bytes anywhere else is not its twin, and the descriptors of the folders
    are not pictures."""
    library = {
        _RU + "Акме.svg": b"<svg acme/>",
        _EN + "Acme.svg": b"<svg acme/>",
        _RU + "Ресурсы.yaml": "ОбластьВидимости: Глобально\n".encode(),
        _EN + "Resources.yaml": b"VisibilityScope: Global\n",
        _RU + "Глобекс.svg": b"<svg globex/>",
        "Icons/Прочее/Ресурсы/Globex.svg": b"<svg globex/>",
        "Other/Std/Resources/Globex.svg": b"<svg globex/>",
    }
    _car_with_jars(tmp_path, library, dict(library))

    diagnostics: dict = {}
    found = ut.collect(tmp_path, diagnostics)

    assert found["resource_paths"] == {_RU + "Акме.svg": _EN + "Acme.svg"}
    pictures = diagnostics["pictures"]
    assert pictures["instances"] == 6
    assert pictures["unmatched"][0]["ru"] == [_RU + "Глобекс.svg"]


def test_collect_leaves_out_a_picture_two_jars_ship_differently(tmp_path):
    _car_with_jars(
        tmp_path,
        {_RU + "Акме.svg": b"<svg one/>", _EN + "Acme.svg": b"<svg one/>"},
        {_RU + "Акме.svg": b"<svg two/>", _EN + "Acme.svg": b"<svg one/>"},
    )

    assert ut.collect(tmp_path)["resource_paths"] == {}


def test_the_table_is_counted_in_the_meta(tmp_path):
    _car_with_jars(tmp_path, {_RU + "Акме.svg": b"<svg/>", _EN + "Acme.svg": b"<svg/>"})

    built = ut.build(tmp_path, "1.0.0")

    assert built["meta"]["resource_paths"] == 1
    assert built["resource_paths"] == {_RU + "Акме.svg": _EN + "Acme.svg"}


def test_the_extractor_names_what_it_left_without_a_pair(tmp_path, capsys):
    _car_with_jars(tmp_path, {
        _RU + "Акме.svg": b"<svg/>", _EN + "Acme.svg": b"<svg/>",
        _RU + "Глобекс.svg": b"<svg ru/>",
    })
    out = tmp_path / "uiterms.json"

    assert ut.main(["--dist", str(tmp_path), "--element-version", "1.0.0",
                    "--out", str(out)]) == 0

    printed = capsys.readouterr().out
    assert "картинок библиотеки в паре: 1" in printed
    assert f"без пары: {_RU}Глобекс.svg" in printed
    assert '"resource_paths"' in out.read_text(encoding="utf-8")
