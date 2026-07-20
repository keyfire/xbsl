"""Extract 1C:Element documentation from the distribution into docs.sqlite (pages, index, tree).

Inside the server-with-IDE .car the documentation lives as a static site (Docusaurus) under
`data/docs/help/ru/`. Here it is assembled into a single SQLite database:

- `pages(id, kind, title, qualified, availability, url, html)` - a page per document;
  id is the URL path without the site prefix (`stdlib/element/xbsl/Std/Collections/Array_ru`,
  `topics/project-element-names-standard`);
- `pages_fts` - an FTS5 virtual table (title, qualified, text) for full-text search;
- `tree(node, parent, ord, label, page, kind)` - the curated "Содержание" tree, as on the site:
  several section tabs (guides and references), with categories and page links inside.
- `assets(id, mime, bytes)` - page images.

The tree structure is taken from the Docusaurus sidebar data (JSON in the site's JS bundle), not
from the paths - which is why it matches the site. The (uniform) page markup is cleaned with
string replaces: cut out the content block, flatten code, unwrap wrappers, rewrite internal links
into the `#<id>` scheme. HTML is stored cleaned - the panel renders it as is, MCP serves text.

The 1C help is copyrighted - the database goes into the private bundle (like stdlib.json) and
does not ship to PyPI.
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

# Root of the static help site in the archive and the prefix by which the site addresses its root.
SITE_ROOT = "data/docs/help/ru/"
SITE_PREFIX = "/docs/help/"
STD_BASE = SITE_ROOT + "stdlib/element/xbsl/Std/"  # the type reference: taken in full
# The template namespace "типы вашего проекта" (ИмяРазработчика::ИмяПроекта::...) is placeholders,
# not a real reference; it goes into neither the tree nor the database.
_TEMPLATE_NS = "stdlib/element/xbsl/DeveloperName"

# Site section tabs that go into the tree (sidebar key -> label). The server management REST API
# (console) is 534 endpoints with no bearing on writing code, so it is not included.
SIDEBARS = [
    ("developer", "Руководство разработчика"),
    ("administrator", "Руководство администратора"),
    ("xbslStdlib", "Типы языка 1С:Элемент"),
    ("xbqlStdlib", "Язык запросов"),
]

# The canonical docs site address comes from the sitemap; the fallback is the Element cloud.
_SITEMAP = SITE_ROOT + "sitemap.xml"
_DEFAULT_ORIGIN = "https://1cmycloud.com"
_LOC_RE = re.compile(r"<loc>\s*(https?://[^/\s<]+)")

_REGION_START = '<div class="theme-doc-markdown markdown">'
_REGION_END_RE = re.compile(r'<footer class="theme-doc-footer|<nav class="pagination-nav|</article>')

# Content tags that are kept (their attributes get stripped); links are handled separately.
_KEEP = "h1|h2|h3|h4|h5|p|ul|ol|li|strong|em|code|hr|br|blockquote|table|thead|tbody|tr|th|td"

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SVG_RE = re.compile(r"<svg\b.*?</svg>", re.S)
_PRE_RE = re.compile(r"<pre\b[^>]*>(.*?)</pre>", re.S)
_BR_RE = re.compile(r"<br\s*/?>")
_IMG_RE = re.compile(r'<img\b[^>]*?\bsrc="([^"]*)"[^>]*>')
_IMG_BARE_RE = re.compile(r'<img\b(?![^>]*\bsrc="assets/)[^>]*>')  # already rewritten stay put
_ASSET_REF_RE = re.compile(r'<img src="(assets/[^"]+)"')
_HASHLINK_RE = re.compile(r'<a\b[^>]*class="[^"]*hash-link[^"]*"[^>]*>.*?</a>', re.S)
_LINK_RE = re.compile(r'<a\b[^>]*?\bhref="([^"]*)"[^>]*>')
_BARE_A_RE = re.compile(r"<a\b(?![^>]*\bhref=)[^>]*>")  # links without href
_KEEP_RE = re.compile(rf"<(/?)(?:{_KEEP})\b[^>]*>")
_UNWRAP_RE = re.compile(r"</?(?:div|header|span|nav|button|time|meta|footer|figure|section)\b[^>]*>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CODE_SLOT_RE = re.compile(r"\x00(\d+)\x00")  # placeholder of a stashed code block
# Control characters, zero-widths and the soft hyphen - the markup has them inside words,
# silently corrupting both the text and the index (e.g. "Аннот\x00ации"); cut them out on input.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f​‌‍﻿­]")

_QUALIFIED_RE = re.compile(r"<code>(Стд(?:::[^<]+)*)</code>")
_AVAIL_RE = re.compile(r"Доступность:\s*([^<]+?)\s*</code>")
_H1_RE = re.compile(r"<h1>(.*?)</h1>", re.S)
# Section headings (with the id anchor kept) - for the page's outline in the tree.
_HEADING_RE = re.compile(r'<(h[23]) id="([^"]+)">(.*?)</\1>', re.S)


def _headings(html: str) -> list[tuple[int, str, str]]:
    """Page sections: (level 2/3, id anchor, text) in document order."""
    out: list[tuple[int, str, str]] = []
    for tag, anchor, inner in _HEADING_RE.findall(html):
        text = unescape(_TAG_RE.sub("", inner)).strip()
        if text:
            out.append((int(tag[1]), anchor, text))
    return out


def _rewrite_href(href: str) -> str:
    """Internal site link `/docs/help/<path>` -> `#<path>` (page id); the rest is left alone."""
    if not href.startswith(SITE_PREFIX):
        return href
    rest = href[len(SITE_PREFIX):]
    anchor = ""
    if "#" in rest:
        rest, anchor = rest.split("#", 1)
        anchor = "#" + anchor
    return "#" + rest.strip("/") + anchor


def _flatten_pre(m: re.Match) -> str:
    """A Prism/rouge code block -> `<pre><code>text</code></pre>` (spans dropped, <br> -> newline)."""
    inner = _BR_RE.sub("\n", m.group(1))
    code = unescape(_TAG_RE.sub("", inner)).strip("\n")  # a trailing <br> yields an extra newline
    return "<pre><code>" + escape(code) + "</code></pre>"


def _rewrite_img(m: re.Match) -> str:
    """<img src="/docs/help/assets/X.png"> -> <img src="assets/X.png">; no usable src -> dropped."""
    src = unescape(m.group(1))
    if src.startswith(SITE_PREFIX):
        return f'<img src="{escape(src[len(SITE_PREFIX):])}">'  # -> assets/...
    return ""


def _clean(raw: str) -> tuple[str, str]:
    """Cleaned content-block HTML and flat text for the index (both empty if there is no block)."""
    start = raw.find(_REGION_START)
    if start < 0:
        return "", ""
    me = _REGION_END_RE.search(raw, start)
    region = raw[start: me.start() if me else len(raw)]

    # Code blocks are stashed into placeholders before whitespace normalization - otherwise _WS_RE
    # eats the newlines and indentation inside examples (vital for YAML). Restored at the very end.
    codes: list[str] = []

    def _stash(m: re.Match) -> str:
        codes.append(_flatten_pre(m))
        return f"\x00{len(codes) - 1}\x00"

    region = _PRE_RE.sub(_stash, region)
    region = _COMMENT_RE.sub("", region)
    region = _SVG_RE.sub("", region)
    region = _IMG_RE.sub(_rewrite_img, region)      # keep the image (src -> asset id)
    region = _IMG_BARE_RE.sub("", region)           # drop an image without a usable src
    region = _HASHLINK_RE.sub("", region)
    region = _LINK_RE.sub(lambda m: f'<a href="{escape(_rewrite_href(unescape(m.group(1))))}">', region)
    region = _BARE_A_RE.sub("<a>", region)          # links without href
    region = _KEEP_RE.sub(_strip_attrs, region)     # strip attributes off the kept tags
    region = _UNWRAP_RE.sub("", region)             # unwrap the structural wrappers
    region = _WS_RE.sub(" ", region).strip()
    html = _CODE_SLOT_RE.sub(lambda m: codes[int(m.group(1))], region)  # put the code blocks back

    text = _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()
    return html, text


def _strip_attrs(m: re.Match) -> str:
    """<h2 class=... id=x> -> <h2 id=x>, the rest -> <tag> (headings keep their section id anchor)."""
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
    """A structured page record, or None if there is no content block."""
    raw = _CTRL_RE.sub("", raw)  # control characters corrupt the text, the index and titles
    html, text = _clean(raw)
    if not html:
        return None
    doc_id = entry[len(SITE_ROOT):].rsplit("/", 1)[0]  # the URL path without /index.html
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
    """Docs site scheme+host from the sitemap (for links to the source); the fallback is the cloud."""
    try:
        raw = z.read(_SITEMAP).decode("utf-8", "replace")
    except KeyError:
        return _DEFAULT_ORIGIN
    m = _LOC_RE.search(raw)
    return m.group(1) if m else _DEFAULT_ORIGIN


# --- curated tree from the Docusaurus sidebar -----------------------------------------

def _sidebar_js(z: zipfile.ZipFile) -> str | None:
    """Contents of the site's JS bundle with sidebar data (found by a recognizable key)."""
    for name in z.namelist():
        if name.startswith(SITE_ROOT + "assets/js/") and name.endswith(".js"):
            raw = z.read(name).decode("utf-8", "replace")
            if '"xbslStdlib":[{"type"' in raw or '"developer":[{"type"' in raw:
                return raw
    return None


def _balanced_array(raw: str, start: int) -> str:
    """String-aware bracket balancing from '[' to the matching ']'."""
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
    """The parsed sidebar items array by its key, or None.

    The bundle sometimes over-escapes quotes in a label (`\\"` instead of `\"`, e.g. in
    'Ключевое слово "ничто"') - valid JSON breaks on that, so on error a repair is attempted.
    """
    anchor = f'"{key}":['
    i = js.find(anchor)
    if i < 0:
        return None
    arr = _balanced_array(js, i + len(anchor) - 1)  # from the '[' position
    for candidate in (arr, arr.replace('\\\\"', '\\"')):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _href_to_page(href: str) -> str | None:
    """A sidebar link URL -> page id (as in pages), or None for an external link."""
    if not href or not href.startswith(SITE_PREFIX):
        return None
    return href[len(SITE_PREFIX):].strip("/") or None


def _collect_hrefs(items: list, out: set[str]) -> None:
    """Collect all page hrefs referenced by a sidebar subtree (except the template namespace)."""
    for it in items:
        page = _href_to_page(it.get("href", ""))
        if page and page.startswith(_TEMPLATE_NS):
            continue  # template placeholders are skipped along with their subtree
        if page:
            out.add(page)
        kids = it.get("items")
        if isinstance(kids, list):
            _collect_hrefs(kids, out)


# --- database -----------------------------------------------------------------------------

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
    assets_dir = out.parent / "assets"  # images sit next to the database as files; old ones purged
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    con = sqlite3.connect(out)
    _assert_fts5(con)
    con.executescript(_SCHEMA)
    with zipfile.ZipFile(car) as z:
        origin = _origin(z)
        names = set(z.namelist())

        # Parse the site sidebars: their structure is what becomes the "Содержание" tree.
        js = _sidebar_js(z)
        sidebars: list[tuple[str, list]] = []
        for key, label in SIDEBARS:
            items = _sidebar_items(js, key) if js else None
            if items:
                sidebars.append((label, items))

        # Pages to extract: everything the sidebars reference, plus the whole type reference
        # (the sidebar has categories and types only; member pages are needed for search and links).
        wanted: set[str] = set()
        for _label, items in sidebars:
            _collect_hrefs(items, wanted)
        for e in names:
            if e.startswith(STD_BASE) and e.endswith("/index.html"):
                wanted.add(e[len(SITE_ROOT):].rsplit("/", 1)[0])

        asset_ids: set[str] = set()
        page_headings: dict[str, list] = {}  # page id -> its sections (for the tree outline)
        pages = 0
        for doc_id in sorted(wanted):
            entry = SITE_ROOT + doc_id + "/index.html"
            if entry not in names:
                continue  # a link to a missing page (an external section) - skip
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
    """Lay sidebars out into the tree table: tab -> categories -> pages -> their sections (headings)."""
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
        """Page sections (h2/h3) under its link node; h3s nest under the preceding h2."""
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
                add(parent_node, h2_ord, text, page, anchor, "heading")  # an h3 with no h2 - top level
                h2_ord += 1

    def walk(items: list, parent: int) -> None:
        for i, it in enumerate(items):
            page = _href_to_page(it.get("href", ""))
            if page and page.startswith(_TEMPLATE_NS):
                continue  # the template namespace stays out of the tree
            label = (it.get("label") or "").strip()
            kids = it.get("items")
            kind = "category" if it.get("type") == "category" else "link"
            node = add(parent, i, label, page, None, kind)
            if isinstance(kids, list):
                walk(kids, node)
            elif page:
                add_headings(node, page)  # a leaf link gets its page sections expanded

    for i, (label, items) in enumerate(sidebars):
        root = add(None, i, label, None, None, "section")
        walk(items, root)
    return counter[0]


def _write_assets(z: zipfile.ZipFile, asset_ids: set[str], dest_dir: Path) -> None:
    """Write the page images as files next to the database (id = the `assets/...` path).

    Files rather than blobs in the database: the names are content-hashed, git-lfs deduplicates
    identical ones across versions, and docs.sqlite itself stays compact. An asset missing
    from the archive is skipped - its image simply will not show.
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Извлечь документацию Элемента из дистрибутива в docs.sqlite")
    ap.add_argument("--dist", required=True, help="каталог дистрибутива 1С:Элемент (с .car сервера-с-IDE)")
    ap.add_argument("--element-version", help="версия Элемента (если не из дистрибутива)")
    ap.add_argument("--no-default", action="store_true", help="не делать эту версию версией по умолчанию")
    ap.add_argument("--out", help="переопределить путь docs.sqlite")
    _distro.add_data_dir_arg(ap)
    args = ap.parse_args(argv)
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
