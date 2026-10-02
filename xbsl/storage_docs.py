"""Shared page contents with independent full-text indexes for each version."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import zlib
from functools import lru_cache
from pathlib import Path

from xbsl.storage_codec import identity


@lru_cache(maxsize=256)
def unpack_text(value):
    return zlib.decompress(value).decode("utf-8") if value is not None else None


def packed_text(value):
    return zlib.compress(value.encode("utf-8"), 9) if value is not None else None


class DocsBuilder:
    def __init__(self):
        self.contents = {}
        self.links = []
        self.nodes = {}
        self.tree_links = []
        self.versions = {}

    def add(self, version, connection):
        pages = connection.execute("SELECT rowid,id,kind,title,qualified,availability,url,html FROM pages ORDER BY rowid").fetchall()
        search = {row[1]: row for row in connection.execute("SELECT rowid,id,title,qualified,text FROM pages_fts ORDER BY rowid")}
        for row in pages:
            found = search.get(row[1])
            ft_title, ft_qualified, text = found[2:] if found else (None, None, None)
            record = (*row[1:], ft_title, ft_qualified, text)
            key = identity(record)
            self.contents[key] = record
            self.links.append((version, row[0], found[0] if found else None, row[1], key))
        for row in connection.execute("SELECT node,parent,ord,label,page,anchor,kind FROM tree ORDER BY node"):
            record = tuple(row)
            key = identity(record)
            self.nodes[key] = record
            self.tree_links.append((version, row[0], key))
        suffix = hashlib.sha256(version.encode("utf-8")).hexdigest()
        self.versions[version] = suffix
        return {"fts": "fts_" + suffix, "pages": len(pages)}

    def write(self, connection):
        connection.executescript("""
            CREATE TABLE docs_content (key TEXT PRIMARY KEY,id TEXT,kind TEXT,title TEXT,qualified TEXT,
                availability TEXT,url TEXT,html BLOB,ft_title TEXT,ft_qualified TEXT,text TEXT);
            CREATE TABLE docs_links (version TEXT,page_rowid INTEGER,fts_rowid INTEGER,id TEXT,content TEXT,
                PRIMARY KEY(version,id));
            CREATE TABLE tree_content (key TEXT PRIMARY KEY,node INTEGER,parent INTEGER,ord INTEGER,
                label BLOB,page TEXT,anchor TEXT,kind TEXT) WITHOUT ROWID;
            CREATE TABLE tree_links (version TEXT,node INTEGER,content TEXT,PRIMARY KEY(version,node)) WITHOUT ROWID;
        """)
        rows = []
        for key, record in sorted(self.contents.items()):
            page_id, kind, title, qualified, availability, url, html, ft_title, ft_qualified, text = record
            rows.append((key,page_id,kind,title,qualified,availability,url,packed_text(html),ft_title,ft_qualified,text))
        connection.executemany("INSERT INTO docs_content VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.executemany("INSERT INTO docs_links VALUES(?,?,?,?,?)", sorted(self.links))
        connection.executemany("INSERT INTO tree_content VALUES(?,?,?,?,?,?,?,?)", [(key,*row[:3],packed_text(row[3]),*row[4:]) for key,row in sorted(self.nodes.items())])
        connection.executemany("INSERT INTO tree_links VALUES(?,?,?)", sorted(self.tree_links))
        for version, suffix in sorted(self.versions.items()):
            quoted = "'" + version.replace("'", "''") + "'"
            view, fts = "content_" + suffix, "fts_" + suffix
            connection.execute(f"CREATE VIEW {view} AS SELECT l.fts_rowid AS rowid,c.id,c.ft_title AS title,c.ft_qualified AS qualified,c.text FROM docs_links l JOIN docs_content c ON c.key=l.content WHERE l.version={quoted} AND l.fts_rowid IS NOT NULL")
            connection.execute(f"CREATE VIRTUAL TABLE {fts} USING fts5(id UNINDEXED,title,qualified,text,content='{view}',content_rowid='rowid',tokenize='unicode61 remove_diacritics 0')")
            connection.execute(f"INSERT INTO {fts}(rowid,id,title,qualified,text) SELECT rowid,id,title,qualified,text FROM {view} ORDER BY rowid")
            connection.execute(f"INSERT INTO {fts}({fts}) VALUES('optimize')")
            connection.execute(f"INSERT INTO {fts}({fts},rank) VALUES('integrity-check',1)")


class ScopedConnection(sqlite3.Connection):
    fts_name = "pages_fts"

    def execute(self, sql, parameters=(), /):
        if self.fts_name != "pages_fts":
            sql = re.sub(r"\bpages_fts\b", self.fts_name, sql)
        return super().execute(sql, parameters)


def open_shared(path, version, description):
    fts = description["fts"]
    if not re.fullmatch(r"fts_[0-9a-f]{64}", fts):
        raise RuntimeError("Invalid full-text index identifier")
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, factory=ScopedConnection)
    connection.row_factory = sqlite3.Row
    connection.fts_name = fts
    connection.create_function("xbsl_unzip", 1, unpack_text, deterministic=True)
    quoted = "'" + version.replace("'", "''") + "'"
    try:
        connection.execute(f"CREATE TEMP VIEW pages AS SELECT l.page_rowid AS rowid,c.id,c.kind,c.title,c.qualified,c.availability,c.url,xbsl_unzip(c.html) AS html FROM docs_links l JOIN docs_content c ON c.key=l.content WHERE l.version={quoted} ORDER BY l.page_rowid")
        connection.execute(f"CREATE TEMP VIEW tree AS SELECT c.node,c.parent,c.ord,xbsl_unzip(c.label) AS label,c.page,c.anchor,c.kind FROM tree_links l JOIN tree_content c ON c.key=l.content WHERE l.version={quoted} ORDER BY c.node")
    except Exception:
        connection.close()
        raise
    return connection

def export_docs(source, path):
    """Rebuild the legacy schema with the original page and FTS row identifiers."""
    from xbsl.extract.docs import _SCHEMA
    path = Path(path)
    if path.exists():
        path.unlink()
    target = sqlite3.connect(path)
    try:
        target.executescript(_SCHEMA)
        rows = source.execute("SELECT rowid,id,kind,title,qualified,availability,url,html FROM pages ORDER BY rowid").fetchall()
        target.executemany("INSERT INTO pages(rowid,id,kind,title,qualified,availability,url,html) VALUES(?,?,?,?,?,?,?,?)", [tuple(r) for r in rows])
        rows = source.execute("SELECT rowid,id,title,qualified,text FROM pages_fts ORDER BY rowid").fetchall()
        target.executemany("INSERT INTO pages_fts(rowid,id,title,qualified,text) VALUES(?,?,?,?,?)", [tuple(r) for r in rows])
        rows = source.execute("SELECT node,parent,ord,label,page,anchor,kind FROM tree ORDER BY node").fetchall()
        target.executemany("INSERT INTO tree VALUES(?,?,?,?,?,?,?)", [tuple(r) for r in rows])
        target.execute("INSERT INTO pages_fts(pages_fts) VALUES('optimize')")
        target.commit()
    finally:
        target.close()