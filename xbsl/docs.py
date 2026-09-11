"""Runtime access to the Element documentation (docs.sqlite): search, page, tree, symbol.

The database is built by `tools/extract_docs.py` from the distribution and lives in the
data bundle at `<root>/<version>/docs.sqlite` next to `stdlib.json` (see dataset.py). The
documentation is optional: when the database is missing, `available()` returns False and
the other functions return an empty result, so the MCP server and the LSP keep working
without it.

A connection is opened per request and closed right away: requests are rare (driven by a
user action), while the database file is not kept open - it can be rebuilt while the
server is alive (on Windows an open connection blocks overwriting).

Built on top of this API: the MCP tools (Claude searches methods, their properties and
parameters), the LSP "docs for the symbol under the cursor" endpoint, and the extension
panel (tree + HTML view).
"""
from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from html import unescape
from pathlib import Path

from xbsl import dataset, i18n, terms

MESSAGES = {
    "docs.section-not-found": {
        "ru": "Раздела '{section}' на странице нет.",
        "en": "The page has no section '{section}'.",
    },
    "docs.member-of-many": {
        "ru": "'{member}' объявлен у нескольких типов ({count}); спросите"
              " '{owner}.{member}' или посмотрите type_members {owner}.",
        "en": "'{member}' is declared by several types ({count}); ask for"
              " '{owner}.{member}' or look at type_members {owner}.",
    },
}
i18n.register(MESSAGES)

_DB_NAME = "docs.sqlite"
# Plain-text extraction for a short page summary (the metadata-tree category tooltip).
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# A section boundary of a cleaned page: an h2 heading, or an h1 after the page's own (the
# index pages open a second h1 for their type list); h3/h4 stay inside their section.
_SECTION_RE = re.compile(r"<h([12])\b[^>]*>(.*?)</h\1>", re.S)
# The head of a page - what stands before the first section - answers to this name.
HEAD_TITLE = "Описание"
# The head of a reference page opens with the qualified name and the availability, both in code.
_CODE_PREAMBLE_RE = re.compile(r"^\s*<p>(?:\s*<code>[^<]*</code>\s*)+</p>")
# The same preamble as text, for a page cleaned without the code markup: an optional qualified
# name (one token) and the availability line, anchored to the start so that prose that happens
# to mention availability later is left alone.
_TEXT_PREAMBLE_RE = re.compile(r"^(?:\S+\s+)?Доступность:\s*\S+\s+")
# A paragraph that is nothing but a bold caption opens the blocks after the description
# (the comparison, the literals, the key and the hash) - facts, not prose.
_BOLD_CAPTION_RE = re.compile(r"<p>\s*<strong>[^<]*</strong>\s*</p>")
# A topic keeps its description under this heading rather than in the head.
_TOPIC_DESCRIPTION = "Общее описание"
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# English names of the standard sections of a reference page. The pages carry Russian headings
# only, so an English request is matched through this table - a translation of the fixed set
# of headings the reference uses, not a platform dictionary; the Russian spelling is compared
# case-insensitively as it is.
SECTION_ALIASES = {
    "description": HEAD_TITLE,
    "type hierarchy": "Иерархия типа",
    "hierarchy": "Иерархия типа",
    "inheritance hierarchy": "Иерархия наследования",
    "constructors": "Конструкторы",
    "properties": "Свойства",
    "methods": "Методы",
    "events": "События",
    "elements": "Элементы",
    "fields": "Поля",
    "literals": "Литералы",
    "parameters": "Параметры",
    "syntax": "Синтаксис",
    "examples": "Примеры",
    "example": "Пример",
    "see also": "См. также",
    "inherited methods": "Список унаследованных методов",
    "inherited properties": "Список унаследованных свойств",
    "inherited events": "Список унаследованных событий",
}
#: The sections whose h3 headings are the type's OWN members. The inherited lists are left
#: out on purpose - their h3 name the ANCESTOR, not a member, and a member is documented where
#: it is declared; so are the constructors, whose heading repeats the name of the type itself.
MEMBER_SECTIONS = frozenset({
    "Свойства", "Методы", "События", "Элементы", "Поля", "Динамические свойства",
})
# Any heading down to h3: the member index and the member block both walk the same boundaries
# (h1/h2 open a section, h3 opens a member), while h4 stays inside its member.
_HEADING_RE = re.compile(r"<h([123])\b[^>]*>(.*?)</h\1>", re.S)
# Query token: letters (incl. Cyrillic), digits, underscore - everything else is dropped for FTS5.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# Images live as files next to the database (`<version>/assets/...`), mime is derived from the extension.
_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
}


def available(version: str | None = None) -> bool:
    """Whether a documentation database exists for the data version."""
    return dataset.has_data_file(_DB_NAME, version)


def _open(version: str | None = None) -> sqlite3.Connection | None:
    """A fresh read-only connection (the caller must close it) or None if there is no database."""
    if not available(version):
        return None
    uri = Path(dataset.data_file(_DB_NAME, version)).as_uri() + "?mode=ro"  # file URI on any OS
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _fts_terms(query: str) -> list[str]:
    """Free text -> safe FTS5 terms: quoted words, the last one a prefix (convenient while typing)."""
    tokens = _TOKEN_RE.findall(query)
    if not tokens:
        return []
    return [f'"{t}"' for t in tokens[:-1]] + [f'"{tokens[-1]}"*']


def _fts_query(query: str) -> str:
    """The strict expression: every word must be on the page (FTS5 joins by AND implicitly)."""
    return " ".join(_fts_terms(query))


def _match(con: sqlite3.Connection, expr: str, limit: int) -> list[sqlite3.Row]:
    return con.execute(
        "SELECT p.id, p.title, p.qualified, p.kind, p.availability, p.url,"
        "       snippet(pages_fts, 3, '', '', ' ... ', 12) AS snippet "
        "FROM pages_fts f JOIN pages p ON p.id = f.id "
        "WHERE pages_fts MATCH ? ORDER BY bm25(pages_fts) LIMIT ?",
        (expr, limit),
    ).fetchall()


def _by_coverage(con: sqlite3.Connection, terms: list[str], limit: int) -> list[dict]:
    """An OR search ranked by how many of the query words a page carries, bm25 breaking ties.

    Plain bm25 over an OR expression answers with pages that repeat ONE of the words, and buries
    the page that carries several: measured on the shipped documentation, for "ПередЗакрытием
    закрытие формы вопрос" the page named after two of the words stood 17th, below pages matching
    "закрытие" alone. Coverage first is what a multi-word query means.

    Coverage is counted by an id-only lookup per word, so no page text is read for it.
    """
    candidates = _match(con, " OR ".join(terms), max(limit * 5, 50))
    if not candidates:
        return []
    coverage = dict.fromkeys((row["id"] for row in candidates), 0)
    for term in terms:
        for row in con.execute("SELECT id FROM pages_fts WHERE pages_fts MATCH ?", (term,)):
            if row["id"] in coverage:
                coverage[row["id"]] += 1
    # The candidate order is bm25 already, so an index tiebreaker keeps it inside a coverage group.
    ranked = sorted(enumerate(candidates), key=lambda pair: (-coverage[pair[1]["id"]], pair[0]))
    return [dict(row) for _, row in ranked[:limit]]


def search(query: str, limit: int = 10, version: str | None = None) -> list[dict]:
    """Full-text search over the documentation, bm25 ranking (best first).

    Words are required together first; when nothing carries them all, the search relaxes to
    "any of them" ranked by coverage instead of answering nothing (see `_by_coverage`).
    """
    terms = _fts_terms(query)
    if not terms:
        return []
    con = _open(version)
    if con is None:
        return []
    try:
        rows = _match(con, " ".join(terms), limit)
        if rows or len(terms) == 1:
            return [dict(r) for r in rows]
        return _by_coverage(con, terms, limit)
    finally:
        con.close()


def page(doc_id: str, version: str | None = None) -> dict | None:
    """Full page record (with cleaned HTML) by its id, or None."""
    con = _open(version)
    if con is None:
        return None
    try:
        row = con.execute(
            "SELECT id, kind, title, qualified, availability, url, html FROM pages WHERE id = ?",
            (doc_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        con.close()


def type_pages(version: str | None = None) -> list[dict]:
    """All reference pages of kind 'type' (id, title, qualified, html), ordered by id.

    A bulk read for offline consumers - tools/extract_uischema.py derives the interface
    component ui schema from these pages. Empty list when the documentation is absent.
    """
    con = _open(version)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, title, qualified, html FROM pages WHERE kind = 'type' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def guide_pages(version: str | None = None) -> list[dict]:
    """All pages that are NOT type reference articles (id, title, html), ordered by id.

    The guides carry what the reference does not: the yaml keys of a component instance are
    listed by the per-component guide topics, and some of them (the auto-interface flag, a
    property the reference page simply omits) appear nowhere else. A bulk read for offline
    consumers - xbsl/extract/uischema.py folds those names into the ui schema. Empty list
    when the documentation is absent.
    """
    con = _open(version)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT id, title, html FROM pages WHERE kind <> 'type' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def tree(version: str | None = None) -> list[dict]:
    """Flat list of curated table-of-contents nodes - the consumer builds the tree.

    Node: node (node id), parent (parent id, or None for a tab section), label (caption),
    page (page id to link to, otherwise None), anchor (section id on the page for a heading
    node), kind (section/category/link/heading).
    """
    con = _open(version)
    if con is None:
        return []
    try:
        rows = con.execute(
            "SELECT node, parent, ord, label, page, anchor, kind FROM tree "
            "ORDER BY parent IS NOT NULL, parent, ord"
        ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []  # old-schema database (no curated tree) - empty result rather than a failure
    finally:
        con.close()


def for_symbol(name: str, version: str | None = None) -> str | None:
    """Page id for a symbol/type name on a CONFIDENT match, otherwise None.

    A match is an exact title or the last qualifier segment (`Стд::...::Массив`); for a
    type we prefer the reference (stdlib) page over a guide topic with the same title.
    There is NO fuzzy (full-text) fallback here: a method section (e.g. `Настроить`) has
    no exact page, and a guide topic guessed by the word is confusing - candidates are
    picked by the caller via search().

    The qualifier match is REFERENCE pages only: a topic's `qualified` is whatever `Std::...`
    its text happened to mention first (the topic about breakpoints quotes `Std::Array::Add`),
    so matching topics that way documents a name with an unrelated article.

    The pages are Russian, the platform is bilingual: a name that finds nothing is tried once
    more under its Russian spelling, so `Array` answers with the page of the type it names
    instead of with nothing at all.
    """
    if not name:
        return None
    name = name.strip()
    con = _open(version)
    if con is None:
        return None
    try:
        found = _page_of(con, name)
        if found is not None:
            return found
        russian = terms.russian(name, "types") or terms.common_russian(name)
        return _page_of(con, russian) if russian and russian != name else None
    finally:
        con.close()


def _page_of(con: sqlite3.Connection, name: str) -> str | None:
    """The page id for one exact spelling: an exact title, then a reference qualifier."""
    exact = con.execute(
        "SELECT id FROM pages WHERE title = ? "
        "ORDER BY id LIKE 'stdlib/%' DESC, length(qualified) LIMIT 1",
        (name,),
    ).fetchone()
    if exact:
        return exact["id"]
    byq = con.execute(
        "SELECT id FROM pages WHERE qualified LIKE ? AND id LIKE 'stdlib/%' "
        "ORDER BY length(qualified) LIMIT 1",
        (f"%::{name}",),
    ).fetchone()
    return byq["id"] if byq else None


def member_places(name: str, version: str | None = None) -> tuple[str, list[tuple[str, str]]]:
    """(the spelling the PAGES use, [(type, page id)] of the types that DECLARE the member).

    A member has no page of its own - it is an h3 heading inside the type that declares it -
    so asking for one by name used to answer with nothing at all, and the semantics of an
    argument cost a deploy to find out. Only the OWN sections of a page count: the inherited
    lists repeat a member under every heir, and it is documented where it is declared.

    Both spellings are taken, and the first half of the answer is the one the pages are
    written in: an English name comes back as the Russian one the headings carry, and the
    block of the member is looked up under that. Empty for a name no type declares.
    """
    index = _member_index(version)
    for spelling in (name, terms.common_russian(name) if name else None):
        if spelling and spelling in index:
            return spelling, list(index[spelling])
    return name, []


def member_block(html: str, member: str) -> tuple[str, str] | None:
    """(the heading as the page writes it, the html of the member's block) - pure, no database.

    Every OVERLOAD of the member is joined: the page opens an h3 of its own for each, and one
    of them alone would document one signature out of three. The block runs to the next
    heading of any level down to h3, so the examples and the exceptions of a member (h4) stay
    with it. None when the page documents no such member of its own.
    """
    wanted = (member or "").strip().lower()
    if not wanted:
        return None
    headings = list(_HEADING_RE.finditer(html or ""))
    section: str | None = None
    title = ""
    blocks: list[str] = []
    for index, heading in enumerate(headings):
        text = _text(heading.group(2))
        if heading.group(1) != "3":
            section = text if text in MEMBER_SECTIONS else None
            continue
        if section is None or text.lower() != wanted:
            continue
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        title = title or text
        blocks.append(html[heading.start():end].strip())
    return (title, "\n".join(blocks)) if blocks else None


def _member_index(version: str | None = None) -> dict[str, tuple[tuple[str, str], ...]]:
    """The member index of the data version, built once per file and rebuilt when it changes."""
    if not available(version):
        return {}
    path = Path(dataset.data_file(_DB_NAME, version))
    try:
        stat = path.stat()
    except OSError:  # pragma: no cover - the file vanished between the check and the stat
        return {}
    return _member_index_cached(str(path), stat.st_mtime, stat.st_size)


@lru_cache(maxsize=4)
def _member_index_cached(path: str, mtime: float, size: int) -> dict[str, tuple[tuple[str, str], ...]]:
    """{member: ((type, page id), ...)} over every reference page of a type.

    Keyed by the file's own stamp the way the library archives are (libs.py): the database is
    regenerated in place by the extractor, and a long-lived server must not keep answering
    from an index built over the previous one. The walk reads 1151 pages in a tenth of a
    second, so it is done whole rather than guessed at with a full-text query, which would
    also match the pages that merely MENTION the word.
    """
    del mtime, size  # the stamp is the cache key, nothing else
    index: dict[str, list[tuple[str, str]]] = {}
    con = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT id, title, html FROM pages WHERE kind = 'type'").fetchall()
    finally:
        con.close()
    for row in rows:
        section: str | None = None
        for heading in _HEADING_RE.finditer(row["html"] or ""):
            text = _text(heading.group(2))
            if heading.group(1) != "3":
                section = text if text in MEMBER_SECTIONS else None
                continue
            if section is None:
                continue
            place = (row["title"], row["id"])
            places = index.setdefault(text, [])
            if place not in places:
                places.append(place)
    return {name: tuple(sorted(places)) for name, places in index.items()}


def plain_text(html: str) -> str:
    """Cleaned HTML as plain text: tags dropped, entities decoded, line breaks kept (pure).

    The line breaks matter: a constructor signature in a code block lists one parameter per
    line, and folded into one line it stops being readable. `_text` is the folded form for
    titles and summaries.
    """
    return unescape(_TAG_RE.sub(" ", html or "")).strip()


def _text(html: str) -> str:
    """Plain text with the whitespace folded - a title or a sentence of prose."""
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", html or ""))).strip()


def sections(html: str) -> list[tuple[str, str]]:
    """The page split by its section headings: [(title, html)], the head first (pure - no database).

    A reference page reads: the h1 title, the qualified name and the availability, the
    description, then h2 sections (the constructors, properties, methods, the inherited lists)
    with the members as h3 inside them. The head - what stands between the page's own h1 and the
    first section - comes first under HEAD_TITLE; every section's html starts at its heading.
    A page without section headings is its head alone. Titles are plain text.
    """
    html = html or ""
    headings = list(_SECTION_RE.finditer(html))
    start = 0
    if headings and headings[0].group(1) == "1" and not html[: headings[0].start()].strip():
        start = headings[0].end()  # the page's own title is not a section
        headings = headings[1:]
    first = headings[0].start() if headings else len(html)
    out = [(HEAD_TITLE, html[start:first].strip())]
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(html)
        out.append((_text(heading.group(2)), html[heading.start():end].strip()))
    return out


def find_section(html: str, name: str) -> tuple[str, str] | None:
    """The section `name` of the page - (title, html) - or None when there is no such section.

    The title is compared case-insensitively; an English name of a standard section
    (SECTION_ALIASES) is taken as well. HEAD_TITLE / "description" answers with the head.
    """
    wanted = (name or "").strip().lower()
    wanted = SECTION_ALIASES.get(wanted, wanted).lower()
    if not wanted:
        return None
    for title, body in sections(html):
        if title.lower() == wanted:
            return title, body
    return None


def description(html: str) -> str:
    """The description of a page as folded plain text, without the preamble (pure - no database).

    Read from the head: the qualified name and the availability that open a reference page
    are dropped, and so is everything from the first bold caption on (the comparison, the
    literals - facts that are not prose). A topic that keeps its description under a first
    general-description heading (_TOPIC_DESCRIPTION) is read from that section. Empty when
    the page has no text.
    """
    for title, body in sections(html):
        if title == HEAD_TITLE:
            body = _CODE_PREAMBLE_RE.sub("", body, count=1)
        elif title == _TOPIC_DESCRIPTION:
            body = _SECTION_RE.sub("", body, count=1)  # the heading itself
        else:
            break  # a section that is not the description - the head was empty
        text = _TEXT_PREAMBLE_RE.sub("", _text(_BOLD_CAPTION_RE.split(body, maxsplit=1)[0]))
        if text:
            return text
    return ""


def summarize(html: str, limit: int = 300) -> str:
    """The opening of the description: whole sentences within `limit` characters (pure).

    Sentences are taken from `description` while they fit; when not even the first one does,
    it is cut at a word boundary and marked with "...". A non-positive limit lifts the cut.
    Empty when the page has no description.
    """
    text = description(html)
    if not text or limit <= 0:
        return text
    taken = ""
    for sentence in _SENTENCE_RE.split(text):
        candidate = f"{taken} {sentence}" if taken else sentence
        if len(candidate) > limit:
            break
        taken = candidate
    if taken:
        return taken
    head = text[:limit]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return cut.rstrip(" ,;:") + "..."


def _summarize(html: str) -> str:
    """One-sentence description from a page's cleaned HTML (pure - no database) - the tooltip's line."""
    text = description(html)
    return _SENTENCE_RE.split(text, maxsplit=1)[0][:240] if text else ""


def summary(doc_id: str, version: str | None = None) -> str:
    """A one-sentence plain-text description of a page - the metadata-tree category tooltip."""
    rec = page(doc_id, version)
    return _summarize(rec.get("html") or "") if rec else ""


def asset(asset_id: str, version: str | None = None) -> dict | None:
    """Image bytes by its id (`assets/...`) with mime - a file next to the database, or None.

    Images are stored not in the database but as files in `<root>/<version>/assets/...`
    (git-lfs). The path is confined to the assets subdirectory - no escaping the bundle.
    """
    if not asset_id.startswith("assets/") or ".." in asset_id:
        return None
    try:
        ver = dataset.resolve_version(version)
    except dataset.DatasetError:
        return None
    path = dataset.data_root() / ver / asset_id
    if not path.is_file():
        return None
    return {
        "id": asset_id,
        "mime": _MIME.get(path.suffix.lower(), "application/octet-stream"),
        "bytes": path.read_bytes(),
    }
