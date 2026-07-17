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

Результат – xbsl/data/element/<версия>/stdlib.json:
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
# Фасет сущностного типа: "Пользователи.Объект", "ДвоичныйОбъект.Ссылка" – члены записи
# и ссылки живут на этих страницах, а не на странице самого типа (менеджерской).
_FACET_TITLE_RE = re.compile(r"^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*\.[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9]*$")

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


# Сигнатура в блоке кода после H3-заголовка метода: `Имя(Параметры): ТипВозврата`.
_SIG_CODE_RE = re.compile(r"<pre class=\"highlight\"><code>(.*?)</code></pre>", re.S)
# Корень типа возврата: голова до generic-скобки/альтернативы/nullable; допускает
# фасетное имя с точкой (Пользователи.Объект).
_RETURN_HEAD_RE = re.compile(r"^\s*([A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*(?:\.[A-Za-zА-Яа-яЁё_][\wА-Яа-яЁё]*)?)")


def page_method_returns(raw: str) -> dict[str, str]:
    """Метод страницы -> корень типа возврата (для вывода типа цепочек вызовов).

    Сигнатуры лежат в блоках кода после H3-заголовков секции "Методы"; у перегрузок с
    разными возвратами метод пропускается (вывести общий тип нельзя). Унаследованные
    методы сигнатур на странице не имеют и не собираются.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return {}
    out: dict[str, str] = {}
    dropped: set[str] = set()
    for section in _H2_OPEN_RE.split(ma.group(1)):
        head = _plain_text(section[:200])
        if not head.startswith("Методы"):
            continue
        # Куски между H3: первый – заголовок секции, дальше по методу на кусок.
        parts = _H3_RE.split(section)
        # _H3_RE captures the heading text: parts = [до, имя1, тело1, имя2, тело2...]
        for k in range(1, len(parts) - 1, 2):
            name = _plain_text(parts[k])
            if not _PROP_NAME_RE.match(name):
                continue
            body = parts[k + 1]
            for m in _SIG_CODE_RE.finditer(body):
                sig = _plain_text(m.group(1))
                paren = sig.rfind("):")
                if paren < 0:
                    continue
                ret = _RETURN_HEAD_RE.match(sig[paren + 2:])
                if not ret:
                    continue
                root = ret.group(1)
                if name in dropped:
                    continue
                if name in out and out[name] != root:
                    del out[name]
                    dropped.add(name)  # перегрузки с разными возвратами
                elif name not in dropped:
                    out[name] = root
    return out


_H1_OPEN_RE = re.compile(r"<h1[^>]*>")
_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.S)


def package_members(raw: str) -> set[str]:
    """Члены страницы ПАКЕТА Стд (глобальный контекст): свойства и методы вместе.

    У страниц пакетов (Стд, Стд::Интерфейс...) секции – заголовки H1 ("Свойства",
    "Методы"), а сами члены – заголовки H2/H3; у страниц типов секции – H2 (их разбирает
    page_members). Первая H1-секция – шапка страницы, она пропускается.
    """
    ma = _ARTICLE_RE.search(raw)
    if not ma:
        return set()
    out: set[str] = set()
    for section in _H1_OPEN_RE.split(ma.group(1))[1:]:
        head = _plain_text(section[:200])
        if not head.startswith(("Свойства", "Методы")):
            continue
        for m in list(_H2_RE.finditer(section)) + list(_H3_RE.finditer(section)):
            name = _plain_text(m.group(1))
            if _PROP_NAME_RE.match(name):
                out.add(name)
    return out


def _english_from_path(entry: str) -> str | None:
    """Английское имя типа из сегмента пути `.../<Имя>_ru/index.html` (без точек)."""
    name = _path_name(entry)
    return name if name and "." not in name else None


def _english_facet_from_path(entry: str) -> str | None:
    """Английское имя фасета из пути (`BinaryObject.Reference_ru` -> с точкой)."""
    name = _path_name(entry)
    return name if name and name.count(".") == 1 else None


def _path_name(entry: str) -> str | None:
    seg = entry[len(STD_BASE):].split("/")
    if len(seg) < 2:
        return None
    dirname = seg[-2]
    if not dirname.endswith("_ru"):
        return None
    return dirname[:-3] or None


def extract(
    dist: Path,
) -> tuple[
    set[str], dict[str, set[str]], dict[str, set[str]], dict[str, dict[str, set[str]]],
    set[str], dict[str, set[str]], dict[str, dict[str, set[str]]],
]:
    """Имена stdlib (двуязычно), порождаемые члены по видам, свойства компонентов, члены типов."""
    car = _distro.find_car(dist)
    names: set[str] = set()
    members: dict[str, set[str]] = {}
    components: dict[str, set[str]] = {}
    types: dict[str, dict[str, set[str]]] = {}
    globals_: set[str] = set()
    managers: dict[str, set[str]] = {}
    facets: dict[str, dict[str, set[str]]] = {}
    returns: dict[str, dict[str, str]] = {}
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
            # Глобальный контекст: свойства и методы страницы самого Стд и страниц его
            # ПАКЕТОВ (Стд::Интерфейс, Стд::Данные... – каталог верхнего уровня без
            # суффикса _ru) доступны в коде голым именем (ПерейтиПоСсылке, Сообщить,
            # ЗагрузкаФайлов) – пакеты авто-импортированы. У страниц пакетов своя
            # структура секций – их разбирает package_members.
            rest = n[len(STD_BASE):]
            top = rest.split("/", 1)[0]
            if rest == "index.html" or (rest.count("/") == 1 and not top.endswith("_ru")):
                globals_ |= package_members(raw)
            if props or methods:
                rets = page_method_returns(raw)
                for key in (title if _PROP_NAME_RE.match(title) else "", eng or ""):
                    if not key:
                        continue
                    slot = types.setdefault(key, {"properties": set(), "methods": set()})
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    if rets:
                        returns.setdefault(key, {}).update(rets)
                # Фасеты сущностных типов (Пользователи.Объект, ДвоичныйОбъект.Ссылка):
                # члены записи и ссылки – отдельным словарём, под обеими формами имени.
                eng_facet = _english_facet_from_path(n)
                for key in (title if _FACET_TITLE_RE.match(title) else "", eng_facet or ""):
                    if not key:
                        continue
                    slot = facets.setdefault(key, {"properties": set(), "methods": set()})
                    slot["properties"] |= props
                    slot["methods"] |= methods
                    if rets:
                        returns.setdefault(key, {}).update(rets)
            got = component_props(n, raw)
            if got is not None:
                comp, props = got
                if comp in components and components[comp] != props:
                    components[comp] &= props  # одноимённые типы: только бесспорное
                else:
                    components[comp] = props
        for n in (e for e in entries if e.startswith(TEMPLATE_BASE) and e.endswith("/index.html")):
            dirname = n[len(TEMPLATE_BASE):].split("/")[0]
            kind = _TEMPLATE_KINDS.get(dirname.split(".")[0].removesuffix("_ru"))
            if kind is None:
                continue  # вид вне карты
            if "." not in dirname:
                # Страница самого шаблона (<Kind>Name_ru) – это МЕНЕДЖЕР вида: его методы
                # (Записать, Заблокировать, НайтиПоКоду...) доступны голым именем в
                # менеджерном модуле объекта.
                raw = z.read(n).decode("utf-8", "replace")
                props, methods = page_members(raw)
                if props or methods:
                    managers.setdefault(kind, set()).update(props | methods)
                continue
            raw = z.read(n).decode("utf-8", "replace")
            mt = _TITLE_RE.search(raw)
            if not mt:
                continue
            segs = mt.group(1).split("|")[0].strip().split(".")
            if len(segs) < 2 or not _CYRILLIC_NAME_RE.match(segs[1]):
                continue  # член-плейсхолдер или латинский шаблон
            members.setdefault(kind, set()).add(segs[1])
    return names, members, components, types, globals_, managers, facets, returns


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
    names, members, components, types, globals_, managers, facets, returns = extract(dist)
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
        # Глобальный контекст: члены Стд и его пакетов первого уровня, доступные голым именем.
        "globals": sorted(globals_),
        # Методы менеджеров видов (страница шаблона <Kind>Name_ru): голые имена в модуле менеджера.
        "manager_members": {k: sorted(v) for k, v in sorted(managers.items())},
        # Фасеты сущностных типов (Пользователи.Объект, ДвоичныйОбъект.Ссылка): члены записи
        # и ссылки, не попадающие на страницу самого типа.
        "facet_members": {k: _members_json(v) for k, v in sorted(facets.items())},
        # Корни типов возвратов методов (сигнатуры со страниц): вывод типа цепочек вызовов.
        "method_returns": {k: dict(sorted(v.items())) for k, v in sorted(returns.items())},
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
    print(f"  глобальных имён контекста: {len(globals_)}")
    print(f"  видов с членами менеджера: {len(managers)}")
    print(f"  типов с членами: {len(types)}"
          f" (со свойствами {sum(1 for v in types.values() if v['properties'])},"
          f" с методами {sum(1 for v in types.values() if v['methods'])})")
    print(f"  фасетов сущностных типов: {len(facets)}")
    print(f"  типов с возвратами методов: {len(returns)}"
          f" (методов с возвратом: {sum(len(v) for v in returns.values())})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
