#!/usr/bin/env python3
"""Извлечь каталог типов stdlib 1С:Элемент из документации дистрибутива.

Доки (Docusaurus HTML) лежат в дистрибутиве-.car под
`data/docs/help/ru/stdlib/element/xbsl/Std/**/index.html`. У каждого символа русское имя –
в <title> ("Имя | 1С:Предприятие.Элемент"), английское – в сегменте пути ("<Имя>_ru").
Типы двуязычны (как ключевые слова), поэтому в каталог кладём обе формы.

Результат – xbsllint/data/element/<версия>/stdlib.json: { "names": [...] }.
Версия определяется из дистрибутива автоматически (или задаётся --element-version).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

STD_BASE = "data/docs/help/ru/stdlib/element/xbsl/Std/"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)


def _english_from_path(entry: str) -> str | None:
    """Английское имя типа из сегмента пути `.../<Имя>_ru/index.html` (без точек)."""
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    if not dirname.endswith("_ru"):
        return None
    name = dirname[:-3]
    return name if name and "." not in name else None


def extract(dist: Path) -> set[str]:
    """Двуязычный набор имён символов stdlib: русское из <title> + английское из пути."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    with zipfile.ZipFile(car) as z:
        docs = [n for n in z.namelist() if n.startswith(STD_BASE) and n.endswith("/index.html")]
        for n in docs:
            raw = z.read(n).decode("utf-8", "replace")
            mt = _TITLE_RE.search(raw)
            if mt:
                title = mt.group(1).split("|")[0].strip()
                if title and not title.startswith("1С:"):
                    names.add(title)
            eng = _english_from_path(n)
            if eng:
                names.add(eng)
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description="Извлечь каталог типов stdlib Элемента из доков")
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент")
    ap.add_argument("--element-version", help="версия Элемента (если не определяется из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь stdlib.json")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args()
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    if not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")

    version = _distro.detect_version(dist, args.element_version)
    names = extract(dist)
    data = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru/stdlib/element/xbsl/Std",
            "count": len(names),
            "note": "двуязычные имена символов stdlib (русское из title + английское из пути)",
        },
        "names": sorted(names),
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "stdlib.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  имён stdlib (двуязычно): {len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
