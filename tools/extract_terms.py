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
- enumeration values - the metamodel declares them `InProject as "ВПроекте"`.

Keywords are NOT duplicated here: language.json already stores every form of each keyword.

The result is xbsl/data/element/<version>/terms.json:
    { "types": {ru: en}, "facets": {ru: en}, "properties": {ru: en}, "enums": {ru: en} }
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

    for section, names in conflicts.items():
        target = {"types": types, "facets": facets, "properties": properties, "enums": enums}[section]
        for name in names:
            target.pop(name, None)
    return {"types": types, "facets": facets, "properties": properties, "enums": enums}, conflicts


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

    payload = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru (title + путь страницы), *.xcore (@PropertyInfo, значения перечислений)",
            "note": "пары русского и английского написания; имена с несколькими ролями "
                    "(разное английское написание в разных местах) исключены",
        },
        **{name: dict(sorted(values.items())) for name, values in sections.items()},
    }
    out = _distro.version_dir(version) / "terms.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    _distro.update_index(version)

    print(f"Записано: {out} (версия {version})")
    for name in ("types", "facets", "properties", "enums"):
        dropped = sorted(conflicts[name])
        extra = f", исключено по конфликту: {dropped}" if dropped else ""
        print(f"  {name}: {len(sections[name])}{extra}")


if __name__ == "__main__":
    main()
