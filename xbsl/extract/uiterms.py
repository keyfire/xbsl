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
  (`Обычная` is Common, Normal and Usual in different enumerations).

The result is uiterms.json in the same versioned data folder:

    { "meta": {...},
      "enum_values": {"ВидОтображенияСтандартнойКарточки": {"Карточка": "Card",
                                                            "Баннер": "Banner"}},
      "packages": {"Стд::Интерфейс::ОбщиеКомпоненты": "Std::Interface::CommonComponents"} }
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
    """{Russian value: its English spelling} of one enumeration class."""
    strings = utf8_constants(blob)
    pairs: dict[str, str] = {}
    for idx, text in enumerate(strings):
        if not _CYRILLIC_RE.search(text) or "::" in text or " " in text or "/" in text:
            continue
        # the English twin is the nearest identifier-shaped string before it
        for back in range(idx - 1, max(-1, idx - 3), -1):
            candidate = strings[back]
            if _NAME_RE.match(candidate) and not _UUID_RE.match(candidate):
                pairs.setdefault(text, candidate)
                break
    return pairs


def _short(name: str) -> str:
    """The last segment of a qualified name (`Стд::Интерфейс::Кнопка` -> `Кнопка`)."""
    return name.rsplit("::", 1)[-1].strip().strip('"')


def _package(name: str) -> str:
    """Everything but the last segment of a qualified name."""
    return "::".join(part.strip().strip('"') for part in name.split("::")[:-1])


def collect(dist: Path) -> dict:
    """Walk the jars of the distribution and collect both maps."""
    car = _distro.find_car(dist)
    manifests: list[dict] = []
    classes: dict[str, bytes] = {}
    with zipfile.ZipFile(car) as z:
        for entry in z.namelist():
            if not entry.endswith(".jar"):
                continue
            try:
                jar = zipfile.ZipFile(io.BytesIO(z.read(entry)))
            except zipfile.BadZipFile:
                continue
            for member in jar.namelist():
                if member.endswith("types-manifest.yaml"):
                    data = yaml.safe_load(jar.read(member).decode("utf-8", "replace"))
                    if isinstance(data, list):
                        manifests.extend(r for r in data if isinstance(r, dict))
                elif member.endswith("G5Enum.class"):
                    classes.setdefault(Path(member).name[: -len("G5Enum.class")], jar.read(member))

    packages: dict[str, Counter] = {}
    enum_values: dict[str, dict[str, str]] = {}
    for record in manifests:
        english, russian = record.get("nameEn"), record.get("nameRu")
        if not isinstance(english, str) or not isinstance(russian, str):
            continue
        if "::" in english and "::" in russian:
            packages.setdefault(_package(russian), Counter())[_package(english)] += 1
        if record.get("typeCategory") != "enum":
            continue
        blob = classes.get(str(record.get("name") or ""))
        if blob is None:
            continue
        pairs = enum_pairs(blob)
        if pairs:
            enum_values[_short(russian)] = pairs

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
    return {"packages": dict(sorted(single.items())), "enum_values": dict(sorted(enum_values.items()))}


def build(dist: Path, version: str) -> dict:
    data = collect(dist)
    return {
        "meta": {
            "source": "distribution",
            "element_version": version,
            "tool": "extract_uiterms",
            "enums": len(data["enum_values"]),
            "packages": len(data["packages"]),
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
