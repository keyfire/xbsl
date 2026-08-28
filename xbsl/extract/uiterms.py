#!/usr/bin/env python3
"""Extract the ENGLISH spellings of the ui vocabulary from the distribution.

The ui schema (`extract_uischema`) is derived from the documentation, and the documentation
ships in Russian only - so enumeration VALUES and package names come out Russian-only too.
The platform, however, reads a project written in English either way: a form with
`DisplayKind: Banner`, `WidthInColumns: Double`, `Kind: Main` compiles.
Without the pairs the linter reported such legal code as an unknown value, and the component
palette stayed Russian in an English editor.

Where the pairs live in the distribution:

- `types-manifest.yaml` of the `com.e1c.g5rt.appengine.*` jars - one record per platform type
  with `name` (the English short name), `nameEn` and `nameRu` (both fully qualified). The
  package pair is what stays after dropping the last segment of each.
- `<name>G5Enum.class` next to it - the values of that enumeration. In the constant pool the
  English spelling of a value sits right before the Russian one (`Icon`, `Иконка`, a UUID,
  `IconAndText`, `ИконкаИТекст`, ...), which is what this module reads. Pairs are collected
  PER ENUMERATION: globally the same Russian word answers to several English ones
  (`Обычная` is Common, Normal and Usual in different enumerations). The manifest names only
  part of the enumerations, so the name of the rest is taken from the neighbouring
  `<name>G5Type.class`, whose pool carries the type's own pair - without it the values of
  the event-log importance enumeration and of a hundred-odd others stayed unnamed.
- the component descriptions the runtime itself is built from -
  `com/e1c/g5rt/appengine/ui/stdcomponents/common/components/{ui,data}/<Type>.yaml`. Every
  type, property, event, method, method parameter and generic argument carries
  `term: {en, ru}` there, which is the authoritative bilingual vocabulary of the interface:
  the reference documentation is Russian-only, so for most names nothing else in the data
  states the pair - `SeoDescription`/`SeoОписание`, `XAxes`/`ОсиX`,
  `OnRowSelection`/`ПриВыделенииСтроки`. A `term` may be a LIST of versioned spellings
  (`{value: {...}, to: 9.0}` then `{value: {...}, from: 9.0}`) - a spelling with `to` is a
  former one and is not published.
- the predefined projects shipped as sources (`SelfRegistration_v8/...` and the like inside
  the designtime jars). Their elements are written bilingually - `Name: {En: ..., Ru: ...}` -
  and that is where the properties of the components composed as projects are named
  (`UrlПослеРегистрации` is `AfterRegistrationUrl`).

The result is uiterms.json in the same versioned data folder:

    { "meta": {...},
      "enum_values": {"ВидОтображенияСтандартнойКарточки": {"Карточка": "Card",
                                                            "Баннер": "Banner"}},
      "packages": {"Стд::Интерфейс::ОбщиеКомпоненты": "Std::Interface::CommonComponents"},
      "types": {"Checkbox": "Флажок"},
      "properties": {"PlaceholderText": "ЗамещающийТекст"} }

`types` and `properties` are keyed by the ENGLISH spelling: that is the direction the
consumers need (a source written in English is read against the Russian names of the schema),
and it is the direction that stays unambiguous. The other way round is not: `Видимость` is
`Visible` on the base component and `Visibility` on two others, `Удалить` is `Delete` on the
forms and `Remove` on a list - while `Visible`, `Visibility`, `Delete` and `Remove` all lead
back to one Russian name each. An English spelling that leads to two different Russian names
(`Name` is both `Имя` and `Наименование`) is dropped rather than guessed.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import struct
import zipfile
from collections import Counter
from pathlib import Path

import yaml

from xbsl.extract import _distro

#: A value spelling: a plain identifier, no dots or spaces (a UUID is filtered by the shape).
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.I)
#: Where the runtime keeps the description of a component (the path inside the jar).
_COMPONENT_DIR = "/stdcomponents/common/components/"
#: Sections of a component description whose items carry a `term` of their own.
_TERM_SECTIONS = ("properties", "events", "methods", "parameters", "generic")
#: The head of a source file of a predefined project, either spelling of the kind key.
_ELEMENT_KIND_KEYS = (b"ElementKind", "ВидЭлемента".encode())
#: How much of a yaml is read to tell a project source from anything else.
_HEAD_BYTES = 400


def utf8_constants(blob: bytes) -> list[str]:
    """Every UTF8 entry of a class constant pool, in pool order.

    A hand-rolled reader rather than a dependency: only the tag sizes matter, and the pool is
    the first structure of the file. A class that does not start with the magic - or one this
    reader cannot walk - yields nothing, so a future format change degrades to "no pairs"
    rather than to wrong ones.
    """
    if blob[:4] != b"\xca\xfe\xba\xbe":
        return []
    count = struct.unpack_from(">H", blob, 8)[0]
    out: list[str] = []
    i, n = 10, 1
    while n < count:
        tag = blob[i]
        i += 1
        if tag == 1:  # CONSTANT_Utf8
            length = struct.unpack_from(">H", blob, i)[0]
            out.append(blob[i + 2:i + 2 + length].decode("utf-8", "replace"))
            i += 2 + length
        elif tag in (7, 8, 16, 19, 20):
            i += 2
        elif tag == 15:
            i += 3
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            i += 4
        elif tag in (5, 6):
            i += 8
            n += 1  # long/double take two pool slots
        else:
            return out  # an unknown tag: keep what was read, guess nothing
        n += 1
    return out


def enum_pairs(blob: bytes) -> dict[str, str]:
    """{Russian value: its English spelling} of one enumeration class.

    Which side of the Russian value the English one sits on is not fixed: the values are
    constructor arguments, and the class declares them in the order of its own fields. The
    pool states that order in plain sight - the field NAMES stand in it, and whichever of
    `ruName` / `enName` comes first is the order the values follow. Read with the English
    always first, the enumerations declared the other way came out shifted by one value
    (a json node kind answered its boolean with `Null` and its string with `Boolean`), and the
    last value of such an enumeration lost its pair altogether.
    """
    strings = utf8_constants(blob)
    english_first = _english_first(strings)
    pairs: dict[str, str] = {}
    for idx, text in enumerate(strings):
        if not _CYRILLIC_RE.search(text) or "::" in text or " " in text or "/" in text:
            continue
        # the English twin is the nearest identifier-shaped string on the declared side
        steps = range(idx - 1, max(-1, idx - 3), -1) if english_first else range(idx + 1, min(len(strings), idx + 3))
        for step in steps:
            candidate = strings[step]
            if _NAME_RE.match(candidate) and not _UUID_RE.match(candidate):
                pairs.setdefault(text, candidate)
                break
    return pairs


def _english_first(strings: list[str]) -> bool:
    """Does the English spelling of a value precede the Russian one in this class?

    The two field names of the enumeration stand in the pool; the one that comes first is the
    first constructor argument. A class naming neither keeps the historical reading.
    """
    for text in strings:
        if text == "enName":
            return True
        if text == "ruName":
            return False
    return True


def _short(name: str) -> str:
    """The last segment of a qualified name (`Стд::Интерфейс::Кнопка` -> `Кнопка`)."""
    return name.rsplit("::", 1)[-1].strip().strip('"')


def _current_terms(node) -> list[dict]:
    """The CURRENT `term` pairs of a description node - a former spelling (`to`) is dropped.

    A node states either one pair or a list of versioned ones; the list form is how the
    platform records a rename (`InvertPosition` until 9.0, `InvertLocation` from 9.0).
    """
    if not isinstance(node, dict):
        return []
    term = node.get("term")
    if isinstance(term, dict):
        return [term]
    if not isinstance(term, list):
        return []
    out = []
    for item in term:
        if not isinstance(item, dict) or item.get("to") is not None:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            out.append(value)
    return out


def _walk_terms(node, names: dict[str, Counter], own: dict[str, Counter]) -> None:
    """Collect {English: Counter of Russian} from a component description, recursively.

    The node's own term goes to `own`, everything below it (properties, events, methods,
    their parameters, generic arguments) to `names`. At the top level the two differ - a type
    name is resolved elsewhere than a property name - and below it they are the same map: a
    parameter of a method is a name like any other.
    """
    if not isinstance(node, dict):
        return
    for pair in _current_terms(node):
        english, russian = pair.get("en"), pair.get("ru")
        if isinstance(english, str) and isinstance(russian, str):
            own.setdefault(english, Counter())[russian] += 1
    for section in _TERM_SECTIONS:
        for item in node.get(section) or ():
            _walk_terms(item, names, names)


def _walk_project_names(node, names: dict[str, Counter]) -> None:
    """Collect {English: Counter of Russian} from the bilingual `Name` of a project source."""
    if isinstance(node, dict):
        value = node.get("Name") or node.get("Имя")
        if isinstance(value, dict):
            english, russian = value.get("En"), value.get("Ru")
            if isinstance(english, str) and isinstance(russian, str):
                names.setdefault(english, Counter())[russian] += 1
        for item in node.values():
            _walk_project_names(item, names)
    elif isinstance(node, list):
        for item in node:
            _walk_project_names(item, names)


def _unambiguous(votes: dict[str, Counter]) -> dict[str, str]:
    """{English: Russian} for the spellings that lead to exactly one Russian name."""
    return {
        english: next(iter(counter))
        for english, counter in sorted(votes.items())
        if len(counter) == 1
    }


def _enum_name(record: dict | None, type_blob: bytes | None, name: str) -> str | None:
    """The Russian name of an enumeration: from the manifest, else from its `G5Type` class.

    The manifest lists well under half of the enumerations, and the rest would lose their
    values entirely. The type class carries the pair of the type itself in its pool, so the
    name is read from there rather than invented.
    """
    if record is not None:
        russian = record.get("nameRu")
        if isinstance(russian, str) and russian:
            return _short(russian)
    if type_blob is None:
        return None
    for russian, english in enum_pairs(type_blob).items():
        if english == name:
            return russian
    return None


def _member_names(meta_classes: dict[str, bytes]) -> dict[str, dict[str, str]]:
    """{type: {Russian member: English}} from the compile-time meta objects of the core library.

    The reference documentation is Russian-only, so the catalog stores a type's members under
    their Russian names alone - and a rule judging a member of an ENGLISH project had nothing
    to compare against. The pairs are stated in `<Type>CtMetaObject`: its constant pool holds
    the English name of every member immediately followed by the Russian one, the same layout
    the enumeration classes use, so the same reader serves.

    Kept PER TYPE rather than as one table, because the mapping is not a function: `Граница`
    is `Border` on one type and `Bound` on another, `Загрузить` is `Load` and `Upload`, and a
    flat table would have to drop such names - measured, that is a third of what the section
    is for. The key is the class stem, which is the English name of the type, the spelling
    the catalog stores next to the Russian one.

    Parameter names ride along with the member names here: telling them apart would need the
    signature, and the consumer of this section errs on the generous side anyway - a name too
    many costs a check not made, never a wrong finding.
    """
    out: dict[str, dict[str, str]] = {}
    for stem, blob in meta_classes.items():
        pairs = {ru: en for ru, en in enum_pairs(blob).items() if _NAME_RE.match(en)}
        if pairs:
            out[stem] = dict(sorted(pairs.items()))
    return dict(sorted(out.items()))


def _package(name: str) -> str:
    """Everything but the last segment of a qualified name."""
    return "::".join(part.strip().strip('"') for part in name.split("::")[:-1])


def _load_yaml(blob: bytes):
    """A parsed yaml member, or None when it does not parse (a template, a broken file)."""
    try:
        return yaml.safe_load(blob.decode("utf-8", "replace"))
    except yaml.YAMLError:
        return None


def collect(dist: Path) -> dict:
    """Walk the jars of the distribution and collect the maps (see the module docstring)."""
    car = _distro.find_car(dist)
    manifests: list[dict] = []
    classes: dict[str, bytes] = {}
    type_classes: dict[str, bytes] = {}
    meta_classes: dict[str, bytes] = {}
    # The same descriptions ship inside several jars - keyed by path so each is read once.
    components: dict[str, object] = {}
    projects: dict[str, object] = {}
    with zipfile.ZipFile(car) as z:
        for entry in z.namelist():
            if not entry.endswith(".jar"):
                continue
            try:
                jar = zipfile.ZipFile(io.BytesIO(z.read(entry)))
            except zipfile.BadZipFile:
                continue
            for member in jar.namelist():
                name = Path(member).name
                if member.endswith("types-manifest.yaml"):
                    data = _load_yaml(jar.read(member))
                    if isinstance(data, list):
                        manifests.extend(r for r in data if isinstance(r, dict))
                elif name.endswith("G5Enum.class") and "$" not in name:
                    classes.setdefault(name[: -len("G5Enum.class")], jar.read(member))
                elif name.endswith("G5Type.class") and "$" not in name:
                    type_classes.setdefault(name[: -len("G5Type.class")], jar.read(member))
                elif name.endswith("CtMetaObject.class") and "$" not in name:
                    meta_classes.setdefault(
                        name[: -len("CtMetaObject.class")], jar.read(member))
                elif member.endswith(".yaml") and _COMPONENT_DIR in member:
                    components.setdefault(member, _load_yaml(jar.read(member)))
                elif member.endswith(".yaml") and member not in projects:
                    blob = jar.read(member)
                    if any(key in blob[:_HEAD_BYTES] for key in _ELEMENT_KIND_KEYS):
                        projects[member] = _load_yaml(blob)

    packages: dict[str, Counter] = {}
    enum_records = {
        str(r.get("name") or ""): r for r in manifests if r.get("typeCategory") == "enum"
    }
    enum_values: dict[str, dict[str, str]] = {}
    for name, blob in sorted(classes.items()):
        pairs = enum_pairs(blob)
        if not pairs:
            continue
        russian = _enum_name(enum_records.get(name), type_classes.get(name), name)
        if russian:
            enum_values.setdefault(russian, pairs)
    for record in manifests:
        english, russian = record.get("nameEn"), record.get("nameRu")
        if not isinstance(english, str) or not isinstance(russian, str):
            continue
        if "::" in english and "::" in russian:
            packages.setdefault(_package(russian), Counter())[_package(english)] += 1

    type_votes: dict[str, Counter] = {}
    name_votes: dict[str, Counter] = {}
    for document in components.values():
        if isinstance(document, dict):
            _walk_terms(document, name_votes, type_votes)
    for document in projects.values():
        _walk_project_names(document, name_votes)

    # An ambiguous package is decided by the MAJORITY of the types that carry it: three packages
    # answer to two English names apiece, and in each case one name is worn by a single type
    # (`Стд::Интерфейс` is Std::Interface on dozens of types and Std::Interface::Charts on one).
    # A tie is dropped rather than guessed - a wrong package would mislabel a whole palette group.
    single: dict[str, str] = {}
    for russian, votes in packages.items():
        if not russian:
            continue
        ranked = votes.most_common(2)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            single[russian] = ranked[0][0]
    return {
        "packages": dict(sorted(single.items())),
        "enum_values": dict(sorted(enum_values.items())),
        "types": _unambiguous(type_votes),
        "properties": _unambiguous(name_votes),
        "member_names": _member_names(meta_classes),
    }


def build(dist: Path, version: str) -> dict:
    data = collect(dist)
    return {
        "meta": {
            "source": "distribution",
            "element_version": version,
            "tool": "extract_uiterms",
            "enums": len(data["enum_values"]),
            "packages": len(data["packages"]),
            "types": len(data["types"]),
            "properties": len(data["properties"]),
            "member_types": len(data["member_names"]),
        },
        **data,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog=_distro.prog_name("python -m xbsl.extract.uiterms"),
        description="Извлечь английские написания значений перечислений и пакетов интерфейса",
    )
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия (если не определяется из дистрибутива)")
    ap.add_argument("--out", help="переопределить путь uiterms.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    version = _distro.detect_version(dist, args.element_version)
    schema = build(dist, version)
    out = Path(args.out) if args.out else _distro.version_dir(version) / "uiterms.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Записано: {out} (версия {version})")
    print(f"  перечислений со значениями: {schema['meta']['enums']}")
    print(f"  пакетов: {schema['meta']['packages']}")
    print(f"  имён типов: {schema['meta']['types']}")
    print(f"  имён свойств, событий и методов: {schema['meta']['properties']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
