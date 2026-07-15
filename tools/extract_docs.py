"""Извлечение документации 1С:Элемент из дистрибутива в docs.sqlite (страницы, индекс, дерево).

Внутри .car сервера-с-IDE документация лежит статическим сайтом (Docusaurus) под
`data/docs/help/ru/`. Здесь из него собирается одна база SQLite:

- `pages(id, kind, title, qualified, availability, url, html)` – страница на каждый документ;
  id – это путь URL без префикса сайта (`stdlib/element/xbsl/Std/Collections/Array_ru`,
  `topics/project-element-names-standard`);
- `pages_fts` – виртуальная таблица FTS5 (title, qualified, text) для полнотекстового поиска;
- `tree(node, parent, ord, label, page, kind)` – курируемое дерево "Содержание", как на сайте:
  несколько разделов-вкладок (руководства и справочники), внутри – категории и ссылки на страницы.
- `assets(id, mime, bytes)` – картинки страниц.

Структуру дерева берём из данных сайдбара Docusaurus (JSON в JS-бандле сайта), а не из путей –
поэтому она совпадает с сайтом. Разметку страниц (единообразную) чистим строковыми заменами:
вырезаем контент-блок, сплющиваем код, разворачиваем обёртки, внутренние ссылки переписываем в
схему `#<id>`. HTML храним очищенным – панель рендерит его как есть, MCP отдаёт текст.

Справка 1С под копирайтом – база кладётся в приватный бандл (как stdlib.json), на PyPI не идёт.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
import zipfile
from html import escape, unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _distro  # noqa: E402

# Корень статического сайта помощи в архиве и префикс, которым сайт адресует свой корень.
SITE_ROOT = "data/docs/help/ru/"
SITE_PREFIX = "/docs/help/"
STD_BASE = SITE_ROOT + "stdlib/element/xbsl/Std/"  # справочник типов: берём его целиком
# Шаблонный неймспейс "типы вашего проекта" (ИмяРазработчика::ИмяПроекта::...) – это плейсхолдеры,
# а не реальный справочник; в дерево и базу его не берём.
_TEMPLATE_NS = "stdlib/element/xbsl/DeveloperName"

# Разделы-вкладки сайта, которые кладём в дерево (ключ сайдбара -> метка). REST-API управления
# сервером (console) – 534 эндпоинта, к написанию кода отношения не имеют, поэтому не включаем.
SIDEBARS = [
    ("developer", "Руководство разработчика"),
    ("administrator", "Руководство администратора"),
    ("xbslStdlib", "Типы языка 1С:Элемент"),
    ("xbqlStdlib", "Язык запросов"),
]

# Канонический адрес сайта документации берём из sitemap; запасной – облако Элемента.
_SITEMAP = SITE_ROOT + "sitemap.xml"
_DEFAULT_ORIGIN = "https://1cmycloud.com"
_LOC_RE = re.compile(r"<loc>\s*(https?://[^/\s<]+)")

_REGION_START = '<div class="theme-doc-markdown markdown">'
_REGION_END_RE = re.compile(r'<footer class="theme-doc-footer|<nav class="pagination-nav|</article>')

# Теги содержимого, которые сохраняем (у них срезаются атрибуты); ссылки обрабатываются отдельно.
_KEEP = "h1|h2|h3|h4|h5|p|ul|ol|li|strong|em|code|hr|br|blockquote|table|thead|tbody|tr|th|td"

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S)
_PRE_RE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.S)
_BR_RE = re.compile(r"<br\s*/?>")
_IMG_RE = re.compile(r'<img\b[^>]*?\bsrc="([^"]*)"[^>]*>')
_IMG_BARE_RE = re.compile(r'<img\b(?![^>]*\bsrc="assets/)[^>]*>')  # уже переписанные не трогаем
_ASSET_REF_RE = re.compile(r'<img src="(assets/[^"]+)"')
_HASHLINK_RE = re.compile(r'<a\b[^>]*class="[^"]*hash-link[^"]*"[^>]*>.*?</a>', re.S)
_LINK_RE = re.compile(r'<a\b[^>]*?\bhref="([^"]*)"[^>]*>')
_BARE_A_RE = re.compile(r"<a\b(?![^>]*\bhref=)[^>]*>")  # ссылки без href
_KEEP_RE = re.compile(rf"<(/?)(?:{_KEEP})\b[^>]*>")
_UNWRAP_RE = re.compile(r"</?(?:div|header|span|nav|button|time|meta|footer|figure|section)\b[^>]*>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Управляющие символы, нулевые ширины и мягкий перенос – в разметке попадаются внутри слов
# и молча портят и текст, и индекс (напр. "Аннот\x00ации"); вырезаем на входе.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f​‌‍﻿­]")

_QUALIFIED_RE = re.compile(r"<code>(Стд(?:::[^<]+)*)</code>")
_AVAIL_RE = re.compile(r"Доступность:\s*([^<]+?)\s*</code>")
_H1_RE = re.compile(r"<h1>(.*?)</h1>", re.S)
# Заголовки разделов (с сохранённым id-якорем) – для оглавления страницы в дереве.
_HEADING_RE = re.compile(r'<(h[23]) id="([^"]+)">(.*?)</\1>', re.S)


def _headings(html: str) -> list[tuple[int, str, str]]:
    """Разделы страницы: (уровень 2/3, id-якорь, текст) в порядке документа."""
    out: list[tuple[int, str, str]] = []
    for tag, anchor, inner in _HEADING_RE.findall(html):
        text = unescape(_TAG_RE.sub("", inner)).strip()
        if text:
            out.append((int(tag[1]), anchor, text))
    return out


def _rewrite_href(href: str) -> str:
    """Внутреннюю ссылку сайта `/docs/help/<путь>` -> `#<путь>` (id страницы); прочее не трогаем."""
    if not href.startswith(SITE_PREFIX):
        return href
    rest = href[len(SITE_PREFIX):]
    anchor = ""
    if "#" in rest:
        rest, anchor = rest.split("#", 1)
        anchor = "#" + anchor
    return "#" + rest.strip("/") + anchor


def _flatten_pre(m: re.Match) -> str:
    """Блок кода Prism/rouge -> `<pre><code>текст</code></pre>` (спаны выброшены, <br> -> перенос)."""
    inner = _BR_RE.sub("\n", m.group(1))
    code = unescape(_TAG_RE.sub("", inner)).strip("\n")  # хвостовой <br> даёт лишний перенос
    return "<pre><code>" + escape(code) + "</code></pre>"


def _rewrite_img(m: re.Match) -> str:
    """<img src="/docs/help/assets/X.png"> -> <img src="assets/X.png">; без пригодного src -> убираем."""
    src = unescape(m.group(1))
    if src.startswith(SITE_PREFIX):
        return f'<img src="{escape(src[len(SITE_PREFIX):])}">'  # -> assets/...
    return ""


def _clean(raw: str) -> tuple[str, str]:
    """Очищенный HTML контент-блока и плоский текст для индекса (пусто, если блока нет)."""
    start = raw.find(_REGION_START)
    if start < 0:
        return "", ""
    me = _REGION_END_RE.search(raw, start)
    region = raw[start: me.start() if me else len(raw)]

    region = _PRE_RE.sub(_flatten_pre, region)      # код сплющиваем до снятия тегов
    region = _COMMENT_RE.sub("", region)
    region = _SVG_RE.sub("", region)
    region = _IMG_RE.sub(_rewrite_img, region)      # картинку сохраняем (src -> id ассета)
    region = _IMG_BARE_RE.sub("", region)           # картинку без пригодного src убираем
    region = _HASHLINK_RE.sub("", region)
    region = _LINK_RE.sub(lambda m: f'<a href="{escape(_rewrite_href(unescape(m.group(1))))}">', region)
    region = _BARE_A_RE.sub("<a>", region)          # ссылки без href
    region = _KEEP_RE.sub(_strip_attrs, region)     # атрибуты сохраняемых тегов срезаем
    region = _UNWRAP_RE.sub("", region)             # структурные обёртки разворачиваем
    html = _WS_RE.sub(" ", region).strip()

    text = _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()
    return html, text


def _strip_attrs(m: re.Match) -> str:
    """<h2 class=... id=x> -> <h2 id=x>, прочее -> <тег> (у заголовков сохраняем id-якорь раздела)."""
    tag = m.group(0)
    slash = m.group(1)
    name = tag[1 + len(slash):].split()[0].rstrip(">/")
    if not slash and name in ("h2", "h3", "h4", "h5"):
        mid = re.search(r'\bid="([^"]+)"', tag)
        if mid:
            return f'<{name} id="{mid.group(1)}">'
    return f"<{slash}{name}>"


def _kind(text: str) -> str:
    if "Иерархия типа" in text or "Базовые типы" in text:
        return "type"
    if "Места применения" in text:
        return "annotation"
    if "Синтаксис" in text and "Параметры" in text:
        return "method"
    return "member"


def _record(entry: str, raw: str, origin: str) -> dict | None:
    """Структурированная запись страницы или None, если контент-блока нет."""
    raw = _CTRL_RE.sub("", raw)  # управляющие символы портят текст, индекс и заголовки
    html, text = _clean(raw)
    if not html:
        return None
    doc_id = entry[len(SITE_ROOT):].rsplit("/", 1)[0]  # URL-путь без /index.html
    mh = _H1_RE.search(html)
    title = unescape(_TAG_RE.sub("", mh.group(1)).strip()) if mh else doc_id.rsplit("/", 1)[-1]
    mq = _QUALIFIED_RE.search(raw)
    ma = _AVAIL_RE.search(raw)
    return {
        "id": doc_id,
        "kind": _kind(text),
        "title": title,
        "qualified": mq.group(1) if mq else "",
        "availability": ma.group(1).strip() if ma else "",
        "url": f"{origin}{SITE_PREFIX}{doc_id}/",
        "html": html,
        "text": text,
        "headings": _headings(html),
    }


def _origin(z: zipfile.ZipFile) -> str:
    """Схема+хост сайта документации из sitemap (для ссылок на первоисточник); запасной – облако."""
    try:
        raw = z.read(_SITEMAP).decode("utf-8", "replace")
    except KeyError:
        return _DEFAULT_ORIGIN
    m = _LOC_RE.search(raw)
    return m.group(1) if m else _DEFAULT_ORIGIN


# --- курируемое дерево из сайдбара Docusaurus -----------------------------------------

def _sidebar_js(z: zipfile.ZipFile) -> str | None:
    """Содержимое JS-бандла сайта с данными сайдбаров (ищем по узнаваемому ключу)."""
    for name in z.namelist():
        if name.startswith(SITE_ROOT + "assets/js/") and name.endswith(".js"):
            raw = z.read(name).decode("utf-8", "replace")
            if '"xbslStdlib":[{"type"' in raw or '"developer":[{"type"' in raw:
                return raw
    return None


def _balanced_array(raw: str, start: int) -> str:
    """Строку-осознающий баланс скобок от '[' до парного ']'."""
    depth = 0
    instr = esc = False
    for i in range(start, len(raw)):
        c = raw[i]
        if instr:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return raw[start:i + 1]
    return raw[start:]


def _sidebar_items(js: str, key: str) -> list | None:
    """Разобранный массив items сайдбара по его ключу, либо None.

    В бандле встречается лишнее экранирование кавычек в метке (`\\"` вместо `\"`, напр. в
    'Ключевое слово "ничто"') – валидный JSON это ломает, поэтому при ошибке пробуем починку.
    """
    anchor = f'"{key}":['
    i = js.find(anchor)
    if i < 0:
        return None
    arr = _balanced_array(js, i + len(anchor) - 1)  # с позиции '['
    for candidate in (arr, arr.replace('\\\\"', '\\"')):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _href_to_page(href: str) -> str | None:
    """URL ссылки сайдбара -> id страницы (как в pages), либо None для внешней ссылки."""
    if not href or not href.startswith(SITE_PREFIX):
        return None
    return href[len(SITE_PREFIX):].strip("/") or None


def _collect_hrefs(items: list, out: set[str]) -> None:
    """Собрать все href страниц, на которые ссылается поддерево сайдбара (кроме шаблонного неймспейса)."""
    for it in items:
        page = _href_to_page(it.get("href", ""))
        if page and page.startswith(_TEMPLATE_NS):
            continue  # шаблонные плейсхолдеры пропускаем вместе с их поддеревом
        if page:
            out.add(page)
        kids = it.get("items")
        if isinstance(kids, list):
            _collect_hrefs(kids, out)


# --- база -----------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE pages (
    id TEXT PRIMARY KEY, kind TEXT, title TEXT, qualified TEXT,
    availability TEXT, url TEXT, html TEXT
);
CREATE VIRTUAL TABLE pages_fts USING fts5(
    id UNINDEXED, title, qualified, text, tokenize='unicode61 remove_diacritics 0'
);
CREATE TABLE tree (node INTEGER PRIMARY KEY, parent INTEGER, ord INTEGER, label TEXT, page TEXT, anchor TEXT, kind TEXT);
CREATE INDEX tree_parent ON tree(parent);
"""


def build(dist: Path, out: Path) -> tuple[int, int]:
    car = _distro.find_car(dist)
    if out.exists():
        out.unlink()
    assets_dir = out.parent / "assets"  # картинки лежат рядом с базой файлами; старые чистим
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    con = sqlite3.connect(out)
    _assert_fts5(con)
    con.executescript(_SCHEMA)
    with zipfile.ZipFile(car) as z:
        origin = _origin(z)
        names = set(z.namelist())

        # Разбираем сайдбары сайта: их структура и станет деревом "Содержание".
        js = _sidebar_js(z)
        sidebars: list[tuple[str, list]] = []
        for key, label in SIDEBARS:
            items = _sidebar_items(js, key) if js else None
            if items:
                sidebars.append((label, items))

        # Страницы к извлечению: всё, на что ссылаются сайдбары, плюс справочник типов целиком
        # (в сайдбаре только категории и типы, а нужны и страницы членов – для поиска и ссылок).
        wanted: set[str] = set()
        for _label, items in sidebars:
            _collect_hrefs(items, wanted)
        for e in names:
            if e.startswith(STD_BASE) and e.endswith("/index.html"):
                wanted.add(e[len(SITE_ROOT):].rsplit("/", 1)[0])

        asset_ids: set[str] = set()
        page_headings: dict[str, list] = {}  # id страницы -> её разделы (для оглавления в дереве)
        pages = 0
        for doc_id in sorted(wanted):
            entry = SITE_ROOT + doc_id + "/index.html"
            if entry not in names:
                continue  # ссылка на отсутствующую страницу (внешний раздел) – пропускаем
            rec = _record(entry, z.read(entry).decode("utf-8", "replace"), origin)
            if rec is None:
                continue
            con.execute(
                "INSERT OR IGNORE INTO pages(id, kind, title, qualified, availability, url, html)"
                " VALUES(?,?,?,?,?,?,?)",
                (rec["id"], rec["kind"], rec["title"], rec["qualified"],
                 rec["availability"], rec["url"], rec["html"]),
            )
            con.execute(
                "INSERT INTO pages_fts(id, title, qualified, text) VALUES(?,?,?,?)",
                (rec["id"], rec["title"], rec["qualified"], rec["text"]),
            )
            asset_ids.update(_ASSET_REF_RE.findall(rec["html"]))
            if rec["headings"]:
                page_headings[rec["id"]] = rec["headings"]
            pages += 1

        _write_assets(z, asset_ids, out.parent)
        nodes = _build_tree(con, sidebars, page_headings)
    con.execute("INSERT INTO pages_fts(pages_fts) VALUES('optimize')")
    con.commit()
    con.close()
    return pages, nodes


def _build_tree(
    con: sqlite3.Connection,
    sidebars: list[tuple[str, list]],
    page_headings: dict[str, list],
) -> int:
    """Разложить сайдбары в таблицу tree: вкладка -> категории -> страницы -> их разделы (заголовки)."""
    counter = [0]

    def add(parent: int | None, ordinal: int, label: str, page: str | None, anchor: str | None, kind: str) -> int:
        counter[0] += 1
        node = counter[0]
        con.execute(
            "INSERT INTO tree(node, parent, ord, label, page, anchor, kind) VALUES(?,?,?,?,?,?,?)",
            (node, parent, ordinal, label, page, anchor, kind),
        )
        return node

    def add_headings(parent_node: int, page: str) -> None:
        """Разделы страницы (h2/h3) под её узлом-ссылкой; h3 вкладываются в предшествующий h2."""
        h2_node: int | None = None
        h2_ord = h3_ord = 0
        for level, anchor, text in page_headings.get(page, []):
            if level == 2:
                h2_node = add(parent_node, h2_ord, text, page, anchor, "heading")
                h2_ord += 1
                h3_ord = 0
            elif h2_node is not None:
                add(h2_node, h3_ord, text, page, anchor, "heading")
                h3_ord += 1
            else:
                add(parent_node, h2_ord, text, page, anchor, "heading")  # h3 без h2 – на верхнем уровне
                h2_ord += 1

    def walk(items: list, parent: int) -> None:
        for i, it in enumerate(items):
            page = _href_to_page(it.get("href", ""))
            if page and page.startswith(_TEMPLATE_NS):
                continue  # шаблонный неймспейс в дерево не кладём
            label = (it.get("label") or "").strip()
            kids = it.get("items")
            kind = "category" if it.get("type") == "category" else "link"
            node = add(parent, i, label, page, None, kind)
            if isinstance(kids, list):
                walk(kids, node)
            elif page:
                add_headings(node, page)  # у листа-ссылки раскрываем разделы страницы

    for i, (label, items) in enumerate(sidebars):
        root = add(None, i, label, None, None, "section")
        walk(items, root)
    return counter[0]


def _write_assets(z: zipfile.ZipFile, asset_ids: set[str], dest_dir: Path) -> None:
    """Записать картинки страниц файлами рядом с базой (id = путь `assets/...`).

    Файлами, а не блобами в базе: имена контент-хешированы, git-lfs дедуплицирует одинаковые
    между версиями, а сама docs.sqlite остаётся компактной. Отсутствующий в архиве ассет
    пропускаем – картинка просто не покажется.
    """
    for aid in sorted(asset_ids):
        try:
            data = z.read(SITE_ROOT + aid)
        except KeyError:
            continue
        target = dest_dir / aid
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _assert_fts5(con: sqlite3.Connection) -> None:
    try:
        con.execute("CREATE VIRTUAL TABLE _t USING fts5(x)")
        con.execute("DROP TABLE _t")
    except sqlite3.OperationalError as e:
        raise SystemExit(f"В этой сборке SQLite нет FTS5: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Извлечь документацию Элемента из дистрибутива в docs.sqlite")
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент (с .car сервера-с-IDE)")
    ap.add_argument("--element-version", help="версия Элемента (если не из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь docs.sqlite")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args()
    _distro.set_data_root(args.data_dir)

    dist = Path(args.dist)
    if not dist.is_dir():
        raise SystemExit(f"Каталог дистрибутива не найден: {dist}")
    version = _distro.detect_version(dist, args.element_version)
    out = Path(args.out) if args.out else _distro.version_dir(version) / "docs.sqlite"
    pages, nodes = build(dist, out)
    if not args.out:
        _distro.update_index(version, make_default=not args.no_default)
    print(f"Документация {version}: {pages} страниц, {nodes} узлов дерева -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
