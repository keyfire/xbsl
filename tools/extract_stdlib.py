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

Со страниц компонентов интерфейса (тип – компонент, если в секции "Иерархия типа" среди
базовых есть Стд::Интерфейс::Компонент; плюс страница самого Компонента) дополнительно
собирается словарь component_props: русское имя типа -> полный набор встроенных свойств
(свои – заголовки H3 секции "Свойства", унаследованные – тексты ссылок секций "Список
унаследованных свойств"). Одноимённые типы с разными наборами схлопываются в пересечение –
по голому имени в yaml их не различить, оставляем только бесспорное.

Со всех страниц Std собирается type_members: имя типа -> его члены для дополнения через точку,
свойства и методы РАЗДЕЛЬНО (разные значки в списке дополнения, у методов – скобки).

Результат – xbsllint/data/element/<версия>/stdlib.json:
{ "names": [...], "object_members": {"Справочник": [...], ...},
  "component_props": {"СтандартнаяКарточка": [...], ...},
  "type_members": {"Массив": {"methods": [...]}, "СтандартнаяКарточка": {"properties": [...]}} }.
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

# Разбор страницы компонента: контент в <article>, секции – заголовки H2, свои свойства –
# заголовки H3, унаследованные – ссылки на свойства базового типа.
COMPONENT_BASE = "Стд::Интерфейс::Компонент"
COMPONENT_PAGE = STD_BASE + "Interface/Component_ru/index.html"
_ARTICLE_RE = re.compile(r"<article[^>]*>(.*?)</article>", re.S)
_H2_OPEN_RE = re.compile(r"<h2[^>]*>")
_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
_LINK_RE = re.compile(r"<a[^>]*>(.*?)</a>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_JUNK_RE = re.compile(r"[\x00-\x1f​﻿]")  # управляющие символы и якоря Docusaurus
_PROP_NAME_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*$")

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


def _plain_text(html: str) -> str:
    """Текст без тегов, символов-якорей Docusaurus и управляющих символов.

    В части страниц доков заголовки и имена членов приходят с управляющими символами
    внутри слова ("Св\x00ойства", "Список унаследованных \x00методов") – без чистки секция
    не опознаётся, а имя члена не проходит проверку, и члены таких типов теряются молча.
    """
    return _JUNK_RE.sub("", _TAG_RE.sub("", html)).strip()


def component_props(entry: str, raw: str) -> tuple[str, set[str]] | None:
    """(русское имя типа компонента, его встроенные свойства) или None – не компонент.

    Компонент – тип, в секции "Иерархия типа" которого среди базовых есть
    Стд::Интерфейс::Компонент, плюс страница самого Компонента (у него в базовых
    только Объект). Набор свойств полный: свои (H3 секции "Свойства") вместе с
    унаследованными (тексты ссылок секций "Список унаследованных свойств") –
    цепочку наследования разрешать не нужно.
    """
    mt = _TITLE_RE.search(raw)
    ma = _ARTICLE_RE.search(raw)
    if not mt or not ma:
        return None
    title = mt.group(1).split("|")[0].strip()
    if not title or not _PROP_NAME_RE.match(title):
        return None
    sections = _H2_OPEN_RE.split(ma.group(1))
    is_component = entry == COMPONENT_PAGE
    props: set[str] = set()
    for section in sections:
        head = _plain_text(section[:200])
        if head.startswith("Иерархия типа"):
            if COMPONENT_BASE in _plain_text(section):
                is_component = True
        elif head.startswith("Свойства"):
            for m in _H3_RE.finditer(section):
                name = _plain_text(m.group(1))
                if _PROP_NAME_RE.match(name):
                    props.add(name)
        elif head.startswith("Список унаследованных свойств"):
            for m in _LINK_RE.finditer(section):
                name = _plain_text(m.group(1))
                if _PROP_NAME_RE.match(name):
                    props.add(name)
    return (title, props) if is_component else None


def page_members(raw: str) -> tuple[set[str], set[str]]:
    """Члены типа для дополнения через точку: (свойства, методы).

    Свои члены – заголовки H3 секций "Свойства" / "Методы", унаследованные – тексты ссылок
    секций "Список унаследованных свойств" / "Список унаследованных методов" (там H3 – имена
    базовых типов, а не члены). Конструкторы, литералы и иерархия не в счёт.

    Свойств у большинства типов stdlib нет вовсе (в Элементе даже Длина() – метод); секция
    "Свойства" – в основном у компонентов интерфейса и у типов-записей.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return set(), set()
    props: set[str] = set()
    methods: set[str] = set()
    for section in _H2_OPEN_RE.split(ma.group(1)):
        head = _plain_text(section[:200])
        if head.startswith("Список унаследованных"):
            target = methods if head.startswith("Список унаследованных методов") else props
            found = (_plain_text(m.group(1)) for m in _LINK_RE.finditer(section))
        elif head.startswith(("Свойства", "Методы")):
            target = methods if head.startswith("Методы") else props
            found = (_plain_text(m.group(1)) for m in _H3_RE.finditer(section))
        else:
            continue
        target.update(name for name in found if _PROP_NAME_RE.match(name))
    return props, methods


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


def extract(
    dist: Path,
) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, set[str]]]]:
    """Имена stdlib (двуязычно), порождаемые члены по видам, свойства компонентов, члены типов."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    members: dict[str, set[str]] = {}
    components: dict[str, set[str]] = {}
    types: dict[str, dict[str, set[str]]] = {}
    with zipfile.ZipFile(car) as z:
        entries = z.namelist()
        for n in (e for e in entries if e.startswith(STD_BASE) and e.endswith("/index.html")):
            raw = z.read(n).decode("utf-8", "replace")
            title = ""
            mt = _TITLE_RE.search(raw)
            if mt:
                title = mt.group(1).split("|")[0].strip()
                if title and not title.startswith("1С:"):
                    names.add(title)
            eng = _english_from_path(n)
            if eng:
                names.add(eng)
            # Члены типа (доступ через точку) под ОБЕИМИ формами имени – для дополнения глобалей и типов
            # (напр. КонтекстДоступа./AccessContext., Массив./Array.). Имена с "::" (namespaced) не берём.
            props, methods = page_members(raw)
            if props or methods:
                for key in (title if _PROP_NAME_RE.match(title) else "", eng or ""):
                    if not key:
                        continue
                    slot = types.setdefault(key, {"properties": set(), "methods": set()})
                    slot["properties"] |= props
                    slot["methods"] |= methods
            got = component_props(n, raw)
            if got is not None:
                comp, props = got
                if comp in components and components[comp] != props:
                    components[comp] &= props  # одноимённые типы: только бесспорное
                else:
                    components[comp] = props
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
    return names, members, components, types


def _members_json(members: dict[str, set[str]]) -> dict[str, list[str]]:
    """Члены типа в JSON: свойства и методы раздельно, пустой раздел опускаем."""
    return {kind: sorted(members[kind]) for kind in ("properties", "methods") if members.get(kind)}


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
    names, members, components, types = extract(dist)
    data = {
        "meta": {
            "element_version": version,
            "source": "docs/help/ru/stdlib/element/xbsl",
            "count": len(names),
            "note": "двуязычные имена символов stdlib (русское из title + английское из пути)"
                    " + порождаемые члены по видам объектов (шаблонные страницы)"
                    " + встроенные свойства компонентов интерфейса (страницы наследников"
                    " Стд::Интерфейс::Компонент)"
                    " + члены типов (свойства и методы страницы раздельно, под обеими формами имени)",
        },
        "names": sorted(names),
        "object_members": {k: sorted(v) for k, v in sorted(members.items())},
        "component_props": {k: sorted(v) for k, v in sorted(components.items())},
        "type_members": {k: _members_json(v) for k, v in sorted(types.items())},
    }

    out = Path(args.out) if args.out else _distro.version_dir(version) / "stdlib.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Записано: {out} (версия {version})")
    print(f"  имён stdlib (двуязычно): {len(names)}")
    print(f"  видов с порождаемыми членами: {len(members)}")
    print(f"  компонентов интерфейса со свойствами: {len(components)}")
    print(f"  типов с членами: {len(types)}"
          f" (со свойствами {sum(1 for v in types.values() if v['properties'])},"
          f" с методами {sum(1 for v in types.values() if v['methods'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
