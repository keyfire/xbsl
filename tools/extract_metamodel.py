#!/usr/bin/env python3
"""Extract the metamodel of 1C:Element configuration element properties from the distribution.

The metamodel lives in the main .car (element-server-with-ide) as EMF `.xcore` files inside
nested jar plugins `*.designtime` / `*.model`. Each class declares its properties with the
`@PropertyInfo(ru="Имя", en="Name")` annotation - the ru name matches the yaml key. Classes
inherit (`class X extends A, B`); properties are collected along the whole chain.

The result is xbsl/data/element/<version>/metamodel.json:
    { "classes": { "<Class>": {"props": [ru names], "ext": [base classes]} },
      "vid2class": { "<ВидЭлемента>": "<root class>" },
      "common": [universal keys of the project element envelope] }

vid2class lists ONLY the verified kinds (for the rest the rule performs no check - that
rules out false positives on unverified kinds). common holds the keys shared by all kinds
(the project element envelope) that some kinds do not express in their class.
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

# jar plugins that carry .xcore
_JAR_RE = re.compile(r"designtime|\.model|mdd|dmf|metamodel", re.I)
_HEADER_RE = re.compile(
    r"(?:abstract\s+)?(?:class|interface)\s+(\w+)\s*(?:<[^>]*>)?\s*(?:extends\s+([^{]+?))?\s*\{"
)
_PROP_RE = re.compile(r"@PropertyInfo\d?\(([^)]*)\)")
_RU_RE = re.compile(r"\bru\s*=\s*\"([^\"]+)\"")

# Mapping ВидЭлемента (yaml) -> metamodel root class. Verified kinds only: the rule works
# just for those listed and stays silent for the rest (0 false positives on the unverified).
VID2CLASS = {
    "Справочник": "CatalogNativeDescriptor",
    "Документ": "DocumentNativeDescriptor",
    "РегистрСведений": "InformationRegisterNativeDescriptor",
    "Перечисление": "EnumerationDescriptor",
    "ОбщийМодуль": "CommonModuleDescriptor",
    "КомпонентИнтерфейса": "ComponentModel",
}
# Universal keys of the project element envelope (shared by all kinds).
COMMON = ["ВидЭлемента", "Ид", "Имя", "ОбластьВидимости", "Импорт"]


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _parse_xcore(text: str, classes: dict) -> None:
    text = _strip_comments(text)
    n = len(text)
    for m in _HEADER_RE.finditer(text):
        name = m.group(1)
        ext: list[str] = []
        if m.group(2):
            for part in m.group(2).split(","):
                base = re.sub(r"<[^>]*>", "", part).strip()
                if base:
                    ext.append(base)
        # the class body by curly-brace balance from '{'
        i = m.end() - 1
        depth = 0
        j = i
        while j < n:
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        props: set[str] = set()
        for pm in _PROP_RE.finditer(text[i:j]):
            rm = _RU_RE.search(pm.group(1))
            if rm:
                props.add(rm.group(1))
        node = classes.setdefault(name, {"props": set(), "ext": []})
        node["props"] |= props
        for e in ext:
            if e not in node["ext"]:
                node["ext"].append(e)


def extract(dist: Path) -> dict:
    """Collect { class -> {props, ext} } from every .xcore of the main .car."""
    car = _distro.find_car(dist)
    classes: dict = {}
    with zipfile.ZipFile(car) as z:
        for n in z.namelist():
            if not n.endswith(".jar") or not _JAR_RE.search(Path(n).name):
                continue
            try:
                jz = zipfile.ZipFile(io.BytesIO(z.read(n)))
            except zipfile.BadZipFile:
                continue
            for m in jz.namelist():
                if m.endswith(".xcore"):
                    _parse_xcore(jz.read(m).decode("utf-8", "replace"), classes)
    return classes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Извлечь метамодель свойств элементов Элемента")
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь metamodel.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    if not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")

    version = _distro.detect_version(dist, args.element_version)
    classes = extract(dist)
    # sanity check: all vid2class root classes are present
    missing = sorted(c for c in VID2CLASS.values() if c not in classes)
    if missing:
        print(f"ПРЕДУПРЕЖДЕНИЕ: не найдены корневые классы: {missing}", file=sys.stderr)

    data = {
        "meta": {
            "element_version": version,
            "source": "main .car / *.xcore (EMF-метамодель), @PropertyInfo(ru)",
            "classes": len(classes),
            "note": "свойства элементов конфигурации по видам (для yaml/unknown-property)",
        },
        "classes": {k: {"props": sorted(v["props"]), "ext": v["ext"]} for k, v in sorted(classes.items())},
        "vid2class": VID2CLASS,
        "common": COMMON,
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "metamodel.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  классов: {len(classes)}; видов в vid2class: {len(VID2CLASS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
