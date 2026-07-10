#!/usr/bin/env python3
"""Извлечь каталог типов stdlib 1С:Элемент из документации дистрибутива.

Доки (Docusaurus HTML) лежат в дистрибутиве-.car под
`data/docs/help/ru/stdlib/element/xbsl/Std/**/index.html`. У каждого символа русское имя –
в <title> ("Имя | 1С:Предприятие.Элемент"), английское – в сегменте пути ("<Имя>_ru").
Типы двуязычны (как ключевые слова), поэтому в каталог кладём обе формы.

Рядом, под `.../xbsl/DeveloperName/ProjectName/SubsystemName/**`, лежат шаблонные страницы
типов, порождаемых объектами проекта: "{ИмяСправочника}.Ссылка",
"{ИмяРегистраСведений}.КлючЗаписи", "{ИмяДокумента}.АвтоматическаяФормаСписка..." Из них
собирается словарь object_members: вид объекта (по английскому имени шаблона в пути) ->
имена порождаемых членов (второй сегмент русского заголовка). Члены-плейсхолдеры
("{ИмяМетрики}", латинские шаблоны SOAP) пропускаются, виды вне известной карты – тоже.

Результат – xbsllint/data/element/<версия>/stdlib.json:
{ "names": [...], "object_members": {"Справочник": [...], ...} }.
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
TEMPLATE_BASE = "data/docs/help/ru/stdlib/element/xbsl/DeveloperName/ProjectName/SubsystemName/"
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_CYRILLIC_NAME_RE = re.compile(r"^[А-ЯЁ][А-Яа-яЁё0-9]*$")

# Английское имя шаблона в пути -> русское имя вида (значение ВидЭлемента в yaml).
_TEMPLATE_KINDS = {
    "CatalogName": "Справочник",
    "DocumentName": "Документ",
    "InformationRegisterName": "РегистрСведений",
    "AccumulationRegisterName": "РегистрНакопления",
    "ExchangePlanName": "ПланОбмена",
    "EnumerationName": "Перечисление",
    "AccessKeyName": "КлючДоступа",
    "ClientWorkParametersName": "ПараметрыРаботыКлиента",
    "ComponentName": "КомпонентИнтерфейса",
    "EntityContractName": "КонтрактСущности",
    "ReportName": "Отчет",
    "ReportPanelName": "ПанельОтчетов",
    "ProcessingName": "Обработка",
}


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


def extract(dist: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Имена символов stdlib (двуязычно) + порождаемые члены по видам объектов."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    members: dict[str, set[str]] = {}
    with zipfile.ZipFile(car) as z:
        entries = z.namelist()
        for n in (e for e in entries if e.startswith(STD_BASE) and e.endswith("/index.html")):
            raw = z.read(n).decode("utf-8", "replace")
            mt = _TITLE_RE.search(raw)
            if mt:
                title = mt.group(1).split("|")[0].strip()
                if title and not title.startswith("1С:"):
                    names.add(title)
            eng = _english_from_path(n)
            if eng:
                names.add(eng)
        for n in (e for e in entries if e.startswith(TEMPLATE_BASE) and e.endswith("/index.html")):
            dirname = n[len(TEMPLATE_BASE):].split("/")[0]
            kind = _TEMPLATE_KINDS.get(dirname.split(".")[0])
            if kind is None or "." not in dirname:
                continue  # вид вне карты или страница самого типа (без члена)
            raw = z.read(n).decode("utf-8", "replace")
            mt = _TITLE_RE.search(raw)
            if not mt:
                continue
            segs = mt.group(1).split("|")[0].strip().split(".")
            if len(segs) < 2 or not _CYRILLIC_NAME_RE.match(segs[1]):
                continue  # член-плейсхолдер или латинский шаблон
            members.setdefault(kind, set()).add(segs[1])
    return names, members


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
    names, members = extract(dist)
    data = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru/stdlib/element/xbsl",
            "count": len(names),
            "note": "двуязычные имена символов stdlib (русское из title + английское из пути)"
                    " + порождаемые члены по видам объектов (шаблонные страницы)",
        },
        "names": sorted(names),
        "object_members": {k: sorted(v) for k, v in sorted(members.items())},
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "stdlib.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  имён stdlib (двуязычно): {len(names)}")
    print(f"  видов с порождаемыми членами: {len(members)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
