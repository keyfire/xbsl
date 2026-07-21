#!/usr/bin/env python3
"""Extract the Russian<->English term pairs of 1C:Element from the distribution.

The platform is bilingual: a type is `Запрос` and `Query`, a yaml key is `ОбластьВидимости`
and `VisibilityScope`, an enumeration value is `ВПроекте` and `InProject`. Sources are written
in either language, and so is documentation about them - but the pairing itself is nowhere in
one place, which is why the engine used to carry a few hand-written tuples (and one of them,
"VisibilityArea", matched nothing at all).

Every pair here comes from the distribution, never from a translation:

- types and facets - the documentation page carries the Russian name in <title> and the
  English one in its path segment (`.../Query_ru/index.html`), the same pairing extract_stdlib
  relies on;
- yaml properties - the EMF metamodel annotates them `@PropertyInfo(ru="Имя", en="Name")`;
- enumeration values - the metamodel declares them `InProject as "ВПроекте"`;
- members of every stdlib type - the compiler's meta objects. The two documentation-and-xcore
  sources above are thin: a great many names carry no `en` in the metamodel at all
  (`@PropertyInfo(ru="Реквизиты")`), which used to read as "the platform has no English name
  for this" - and that was wrong. The compiler builds each meta object with calls shaped like
  `builder.name("Get", "Получить")`, so the class constant pool holds the English name
  immediately before the Russian one, for every type and every member. Scanning those classes
  yields thousands of pairs the other sources never see (Реквизиты/Attributes,
  ТабличныеЧасти/TabularParts, СоздатьОбъект/CreateObject).

Keywords are NOT duplicated here: language.json already stores every form of each keyword.

The result is xbsl/data/element/<version>/terms.json:
    { "types": {ru: en}, "facets": {ru: en}, "properties": {ru: en}, "enums": {ru: en},
      "members": {en type: {ru: en}}, "common": {ru: en} }

`members` keeps the owner, because a word may be translated differently depending on where it
sits (`Ссылка` is `Reference` on a data-object facet and `Link` on a navigation property);
`common` holds only the names whose English spelling is unambiguous across the distribution.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import struct
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
# Nested jar plugins that carry the .xcore metamodel (same set as extract_metamodel).
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_PROP_RE = re.compile(r"@PropertyInfo\d?\(([^)]*)\)")
_RU_RE = re.compile(r"\bru\s*=\s*\"([^\"]+)\"")
_EN_RE = re.compile(r"\ben\s*=\s*\"([^\"]+)\"")
# `InProject as "ВПроекте"` - an enumeration literal with its Russian spelling.
_ENUM_RE = re.compile(r"(\w+)\s+as\s+\"([А-ЯЁ][А-Яа-яЁё0-9_]*)\"")
_NAME_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9_]*$")


def _path_name(entry: str) -> str | None:
    """The English name from a `.../<Name>_ru/index.html` documentation path."""
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    return dirname[:-3] or None if dirname.endswith("_ru") else None


def _add(target: dict[str, str], ru: str, en: str, conflicts: set[str]) -> None:
    """Record a pair; a name that claims two different English spellings is dropped.

    A conflict means the word is used in more than one role (`Ссылка` is a property `Link`
    and a facet `Reference`), and a single mapping would be wrong in one of them.
    """
    if ru == en:
        return
    known = target.get(ru)
    if known is None:
        target[ru] = en
    elif known != en:
        conflicts.add(ru)


#: Meta-object classes: the file name without this suffix is the English name of the type.
_META_SUFFIX = re.compile(r"(CtMetaObject|MetaObject|BslImpl)$")
#: Jars of the platform itself - the only ones that can hold meta objects.
_PLATFORM_JAR_RE = re.compile(r"g5rt|_1c")
_EN_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9_]*$")
_RU_NAME_RE = re.compile(r"^[А-ЯЁ][А-Яа-яЁё0-9_]*$")
#: How many times the leading spelling must beat the runner-up to be taken as unambiguous.
_DOMINANCE = 3


def _constant_pool(data: bytes) -> list[str]:
    """The UTF8 entries of a class constant pool, in index order.

    Only the strings are needed, so the other entry kinds are skipped by their fixed sizes
    (long and double take two pool slots - the quirk the `num += 1` accounts for).
    """
    count = struct.unpack_from(">H", data, 8)[0]
    out: dict[int, str] = {}
    i, num = 10, 1
    while num < count and i < len(data):
        tag = data[i]
        if tag == 1:
            length = struct.unpack_from(">H", data, i + 1)[0]
            out[num] = data[i + 3:i + 3 + length].decode("utf-8", "replace")
            i += 3 + length
        elif tag in (7, 8, 16, 19, 20):
            i += 3
        elif tag == 15:
            i += 4
        elif tag in (3, 4, 9, 10, 11, 12, 17, 18):
            i += 5
        elif tag in (5, 6):
            i += 9
            num += 1
        else:
            i += 1
        num += 1
    return [out[key] for key in sorted(out)]


def _scan_meta_objects(car: zipfile.ZipFile) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({owner type: {ru: en}}, {ru: en}) from the compiler meta objects of the distribution.

    A class without a single Cyrillic byte cannot hold a pair and is skipped before parsing -
    that check alone drops the overwhelming majority of the classes.
    """
    members: dict[str, dict[str, str]] = defaultdict(dict)
    variants: dict[str, Counter] = defaultdict(Counter)
    for entry in car.namelist():
        if not entry.endswith(".jar") or not _PLATFORM_JAR_RE.search(entry):
            continue
        try:
            jar = zipfile.ZipFile(io.BytesIO(car.read(entry)))
        except (zipfile.BadZipFile, KeyError):
            continue
        for inner in jar.namelist():
            if not inner.endswith(".class"):
                continue
            try:
                data = jar.read(inner)
            except (zipfile.BadZipFile, KeyError):
                continue
            if b"\xd0" not in data and b"\xd1" not in data:
                continue
            strings = _constant_pool(data)
            pairs = [
                (en, ru) for en, ru in zip(strings, strings[1:])
                if _EN_NAME_RE.match(en) and _RU_NAME_RE.match(ru)
            ]
            if not pairs:
                continue
            owner = _META_SUFFIX.sub("", inner.rsplit("/", 1)[-1][:-len(".class")])
            for en, ru in pairs:
                members[owner][ru] = en
                variants[ru][en] += 1
    common: dict[str, str] = {}
    for ru, counter in variants.items():
        ranked = counter.most_common(2)
        best, best_n = ranked[0]
        if len(ranked) == 1 or best_n >= ranked[1][1] * _DOMINANCE:
            common[ru] = best
    return {owner: dict(sorted(names.items())) for owner, names in sorted(members.items())}, common


def extract(dist: Path) -> tuple[dict[str, dict[str, str]], dict[str, set[str]]]:
    car = _distro.find_car(dist)
    types: dict[str, str] = {}
    facets: dict[str, str] = {}
    properties: dict[str, str] = {}
    enums: dict[str, str] = {}
    conflicts: dict[str, set[str]] = {k: set() for k in ("types", "facets", "properties", "enums")}

    def scan_xcore(text: str) -> None:
        for match in _PROP_RE.finditer(text):
            body = match.group(1)
            ru, en = _RU_RE.search(body), _EN_RE.search(body)
            if ru and en and _NAME_RE.match(ru.group(1)) and _NAME_RE.match(en.group(1)):
                _add(properties, ru.group(1), en.group(1), conflicts["properties"])
        for match in _ENUM_RE.finditer(text):
            _add(enums, match.group(2), match.group(1), conflicts["enums"])

    with zipfile.ZipFile(car) as z:
        for entry in z.namelist():
            if entry.startswith(STD_BASE) and entry.endswith("/index.html"):
                english = _path_name(entry)
                if not english:
                    continue
                title_match = _TITLE_RE.search(z.read(entry).decode("utf-8", "replace"))
                if not title_match:
                    continue
                russian = title_match.group(1).split("|")[0].strip()
                if not russian or russian.startswith("1С:"):
                    continue
                if "." in english and english.count(".") == 1 and "." in russian:
                    _add(facets, russian, english, conflicts["facets"])
                elif "." not in english and _NAME_RE.match(russian):
                    _add(types, russian, english, conflicts["types"])
            elif entry.endswith(".xcore"):
                scan_xcore(z.read(entry).decode("utf-8", "replace"))
            elif entry.endswith(".jar") and _JAR_RE.search(entry):
                try:
                    with zipfile.ZipFile(io.BytesIO(z.read(entry))) as jar:
                        for inner in jar.namelist():
                            if inner.endswith(".xcore"):
                                scan_xcore(jar.read(inner).decode("utf-8", "replace"))
                except zipfile.BadZipFile:
                    continue

    with zipfile.ZipFile(car) as z:
        members, common = _scan_meta_objects(z)

    for section, names in conflicts.items():
        target = {"types": types, "facets": facets, "properties": properties, "enums": enums}[section]
        for name in names:
            target.pop(name, None)
    return {
        "types": types, "facets": facets, "properties": properties, "enums": enums,
        "members": members, "common": common,
    }, conflicts


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия данных (по умолчанию определяется по дистрибутиву)")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)

    dist = Path(args.dist)
    version = _distro.detect_version(dist, args.element_version)
    _distro.set_data_root(args.data_dir)
    sections, conflicts = extract(dist)

    meta = {
        "element_version": version,
        "source": "docs/help/ru (title + путь страницы), *.xcore (@PropertyInfo, значения "
                  "перечислений), метаобъекты компилятора в jar дистрибутива",
        "note": "пары русского и английского написания; имена с несколькими ролями "
                "(разное английское написание в разных местах) исключены",
    }
    # Компактный файл читает рантайм на каждом прогоне - в нём только то, чем пользуются
    # правила. Полный словарь (тысячи членов) лежит рядом и грузится по требованию:
    # 1 МБ json в каждом параллельном воркере стоил бы четверти времени прогона.
    small = {"meta": meta, **{name: dict(sorted(sections[name].items()))
                              for name in ("types", "facets", "properties", "enums")}}
    full = {"meta": meta, "members": sections["members"], "common": sections["common"]}

    version_dir = _distro.version_dir(version)
    version_dir.mkdir(parents=True, exist_ok=True)
    out = version_dir / "terms.json"
    out.write_text(json.dumps(small, ensure_ascii=False, indent=1), encoding="utf-8")
    out_full = version_dir / "terms_full.json"
    out_full.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
    _distro.update_index(version)

    print(f"Записано: {out} (версия {version})")
    for name in ("types", "facets", "properties", "enums"):
        dropped = sorted(conflicts[name])
        extra = f", исключено по конфликту: {dropped}" if dropped else ""
        print(f"  {name}: {len(sections[name])}{extra}")
    print(f"Записано: {out_full}")
    print(f"  members: {len(sections['members'])} типов, common: {len(sections['common'])} имён")


if __name__ == "__main__":
    main()
